"""改名迁移工具的门禁（2026-09-27 `r20` → `astra` 全量改名的收尾件）。

## 为什么这个工具值得单独一道门

`scripts/migrate_r20_to_astra.py` 是**升级路径上的承重件**：它错了，用户的台账、
凭证库、锁与心跳就搬不过去，而症状是"启动后一切正常、只是台账空的" ——
最难排查的一类事故。本门把它当生产代码对待。

## 本门钉住的四件事（都对着真实踩过的坑）

1. **必须是 dry-run 默认**：不加 `--apply` 时**一个文件都不许动**。
   会搬数据的工具默认就该是只读的。
2. **两代同名文件并存时拒绝自动接管**：本机实测就是这么个局面 ——
   新名那三个库是跑测试在真实 `data/` 里建出来的空库（0/125/10 行），
   真数据在旧名里（7/235/16403 行）。静默覆盖 = 直接毁掉真数据。
3. **sidecar（`-wal`/`-shm`）必须跟着主库走，且必须在完整性探针之后扫**：
   探针只读打开 WAL 库就会**新建** `-shm`，第一版按"计划算好的清单"搬 sidecar，
   于是探针新造出来的那几个被留在原地变成孤儿（启动前检查抓出来的）。
4. **`data/*.json` 配置文件里的旧名记号也要改写**：
   `data/backup_methods.json` 的 `scope` 写着已不存在的 `r20_backend`/`r20_gateway`
   ⇒ 每晚备份**静默漏掉整个后端**。这类"改名改不到的配置"不会报错，只会悄悄少做事。
"""
from __future__ import annotations

import importlib.util
import json
import sqlite3
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

spec = importlib.util.spec_from_file_location(
    "migrate_r20_to_astra", ROOT / "scripts" / "migrate_r20_to_astra.py")
mig = importlib.util.module_from_spec(spec)
sys.modules["migrate_r20_to_astra"] = mig
spec.loader.exec_module(mig)


class _Sandbox:
    """把工具的 DATA / LOGS / ROOT 指向临时目录，避免碰真实运行态。"""

    def __init__(self, tmp: Path):
        self.tmp = tmp
        self.saved = {}

    def __enter__(self):
        for name in ("ROOT", "DATA", "LOGS", "SUPERSEDED_DIR", "RENAME_PAIRS"):
            self.saved[name] = getattr(mig, name)
        mig.ROOT = self.tmp
        mig.DATA = self.tmp / "data"
        mig.LOGS = self.tmp / "logs"
        mig.SUPERSEDED_DIR = self.tmp / ".archive" / "astra-migration-superseded"
        # ⚠️ 必须连 `RENAME_PAIRS` 一起重定位：它在模块导入时由 `_pairs(ROOT)` 派生，
        #    只改 `DATA`/`LOGS` 而不管它，工具会继续盯着**真实**运行态 ——
        #    门禁不仅测不到东西，还可能真去动生产文件。
        mig.RENAME_PAIRS = mig._pairs(self.tmp)
        mig.DATA.mkdir(parents=True, exist_ok=True)
        mig.LOGS.mkdir(parents=True, exist_ok=True)
        return self

    def __exit__(self, *exc):
        for name, value in self.saved.items():
            setattr(mig, name, value)
        return False


def _make_db(path: Path, rows: int) -> None:
    con = sqlite3.connect(path)
    con.execute("create table t (id integer primary key, v text)")
    con.executemany("insert into t (v) values (?)", [(f"r{i}",) for i in range(rows)])
    con.commit()
    con.close()


class DryRunIsTheDefaultTest(unittest.TestCase):
    def test_plain_run_touches_nothing(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, _Sandbox(Path(d)):
            old = mig.DATA / "r20_quant.db"
            _make_db(old, 5)
            before = {p.name: p.stat().st_mtime_ns for p in mig.DATA.iterdir()}
            self.assertEqual(mig.main([]), 0)
            after = {p.name: p.stat().st_mtime_ns for p in mig.DATA.iterdir()}
            self.assertEqual(before, after, "默认 dry-run 不许改动任何文件")
            self.assertTrue(old.exists(), "dry-run 后旧文件必须还在")
            self.assertFalse((mig.DATA / "astra_quant.db").exists())

    def test_check_reports_legacy_state_with_exit_code_3(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, _Sandbox(Path(d)):
            _make_db(mig.DATA / "r20_quant.db", 3)
            self.assertEqual(mig.main(["--check"]), 3,
                             "--check 检测到遗留必须用退出码 3（启动脚本据此 fail-closed）")

    def test_check_passes_on_a_migrated_tree(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, _Sandbox(Path(d)):
            _make_db(mig.DATA / "astra_quant.db", 3)
            self.assertEqual(mig.main(["--check"]), 0, "已迁移的树必须放行")


class SidecarSweepTest(unittest.TestCase):
    def test_sidecars_created_by_the_probe_are_moved_too(self):
        """★ 对着真实缺陷：探针自己造出来的 `-shm` 必须跟着走。

        时序是关键 —— SQLite 只读打开 WAL 库就会创建 `-shm`，所以"先算计划、
        再跑探针、按计划搬"必然漏掉探针新造的那几个。
        """
        import tempfile
        with tempfile.TemporaryDirectory() as d, _Sandbox(Path(d)):
            old = mig.DATA / "r20_quant.db"
            _make_db(old, 4)
            # 模拟探针行为：打开一次，让 SQLite 自己长出 sidecar
            con = sqlite3.connect(f"file:{old}?mode=ro", uri=True)
            con.execute("select count(*) from t").fetchone()
            con.close()
            self.assertEqual(mig.main(["--apply"]), 0)
            self.assertTrue((mig.DATA / "astra_quant.db").exists())
            left = sorted(p.name for p in mig.DATA.glob("r20_quant.db*"))
            self.assertEqual(left, [], f"主库搬走后不许留下旧名孤儿：{left}")


class ConflictIsRefusedTest(unittest.TestCase):
    def test_refuses_when_both_generations_exist(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, _Sandbox(Path(d)):
            _make_db(mig.DATA / "r20_quant.db", 200)      # 真数据
            _make_db(mig.DATA / "astra_quant.db", 1)      # 测试产物
            self.assertEqual(mig.main(["--apply"]), 4, "两代并存时必须拒绝并要求显式接管")
            self.assertEqual(mig._row_count(mig.DATA / "astra_quant.db"), 1,
                             "拒绝时不许动任何一侧")

    def test_supersede_moves_the_weaker_side_aside_without_deleting(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, _Sandbox(Path(d)):
            _make_db(mig.DATA / "r20_quant.db", 200)
            _make_db(mig.DATA / "astra_quant.db", 1)
            self.assertEqual(mig.main(["--apply", "--supersede-existing"]), 0)
            archived = mig.SUPERSEDED_DIR / "astra_quant.db"
            self.assertTrue(archived.exists(), "被接管的一份必须**移走留档**，不能删除")
            self.assertEqual(mig._row_count(archived), 1, "留档的应是被接管的那一份")
            self.assertEqual(mig._row_count(mig.DATA / "astra_quant.db"), 200,
                             "接管后新名文件必须是行数更多的那一份（真数据）")

    def test_refuses_to_supersede_when_the_old_side_is_smaller(self):
        """反向保护：不许用"较小的一份"去接管"较大的一份"。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d, _Sandbox(Path(d)):
            _make_db(mig.DATA / "r20_quant.db", 2)
            _make_db(mig.DATA / "astra_quant.db", 500)
            self.assertEqual(mig.main(["--apply", "--supersede-existing"]), 4)
            self.assertEqual(mig._row_count(mig.DATA / "astra_quant.db"), 500,
                             "拒绝后不许动较大的一份")


class ConfigTextMigrationTest(unittest.TestCase):
    def test_old_names_inside_data_json_are_rewritten(self):
        """★ `data/backup_methods.json` 实测：scope 指着已不存在的目录。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d, _Sandbox(Path(d)):
            cfg = mig.DATA / "backup_methods.json"
            cfg.write_text(json.dumps({
                "jobs": [{"scope": ["data", "r20_backend", "r20_gateway"],
                          "exclude": ["data/r20_admin.db*"]}],
            }, ensure_ascii=False), encoding="utf-8")
            self.assertEqual(mig._migrate_config_texts(apply=True), 1)
            out = cfg.read_text(encoding="utf-8")
            self.assertIn("astra_backend", out)
            self.assertIn("astra_gateway", out)
            self.assertIn("data/astra_admin.db*", out)
            self.assertNotIn("r20_backend", out)
            backup = mig.ROOT / ".archive" / "astra-migration-config-backup" / cfg.name
            self.assertTrue(backup.exists(), "改写必须留档原文件")
            self.assertIn("r20_backend", backup.read_text(encoding="utf-8"),
                          "留档必须是**改写前**的内容")
            # ⚠️ 留档**不能**留在 data/ 旁边：`data/<名>.pre-astra` 匹配不上
            #    `.gitignore` 的 `data/*.json`，实测被 `git add -A` 收进过仓库。
            stray = list(mig.DATA.glob("*.pre-astra"))
            self.assertEqual(stray, [], f"data/ 下不许留 *.pre-astra：{stray}")

    def test_lowercase_matchers_do_not_touch_unrelated_text(self):
        """不做模糊匹配：用户自己的池配置里写着别的 `r20` 字样时不许被动。"""
        import tempfile
        with tempfile.TemporaryDirectory() as d, _Sandbox(Path(d)):
            cfg = mig.DATA / "venue_routing.json"
            cfg.write_text('{"note": "我的备注含 r20 字样", "gate": {"dry_run": false}}',
                           encoding="utf-8")
            self.assertEqual(mig._migrate_config_texts(apply=True), 0)
            self.assertIn("我的备注含 r20 字样", cfg.read_text(encoding="utf-8"))


class KindnessToOperatorsTest(unittest.TestCase):
    def test_the_three_known_early_returns_all_run_the_finisher(self):
        """★ 对着真实缺陷：第 3 步曾挂在某个分支上，导致"打印了却没写下去"。

        凡是"必须发生"的步骤都不能挂在某个提前返回上 —— 用源码级断言钉住
        `apply()` 的每条返回路径都走 `_finish()`。
        """
        src = (ROOT / "scripts" / "migrate_r20_to_astra.py").read_text(encoding="utf-8")
        body = src.split("def apply(", 1)[1].split("\ndef ", 1)[0]
        bare_zeros = [ln for ln in body.splitlines() if ln.strip() == "return 0"]
        self.assertEqual(bare_zeros, [],
                         "apply() 里不许有裸 `return 0` —— 必须走 _finish()（第 3 步在里面）")
        self.assertGreaterEqual(body.count("_finish()"), 4,
                                "apply() 的每条收尾路径都必须调用 _finish()")

    def test_exit_codes_are_documented_and_stable(self):
        """退出码是启动脚本的契约：0 放行 / 3 有遗留 / 4 失败。"""
        src = (ROOT / "scripts" / "migrate_r20_to_astra.py").read_text(encoding="utf-8")
        for frag in ("退出码：`0`", "`3` 检测到遗留", "`4` 迁移失败"):
            self.assertIn(frag, src, f"模块 docstring 缺少退出码契约：{frag}")


class EntrypointsAreFailClosedTest(unittest.TestCase):
    """启动路径必须真的接上 `--check`，否则工具写得再好也没人跑它。"""

    ENTRYPOINTS = ("deploy/docker-entrypoint.sh", "start.sh")

    def test_every_entrypoint_runs_the_preflight(self):
        for rel in self.ENTRYPOINTS:
            with self.subTest(f=rel):
                src = (ROOT / rel).read_text(encoding="utf-8")
                self.assertIn("migrate_r20_to_astra.py", src,
                              f"{rel} 没接改名前置检查 ⇒ 未迁移的实例会拿空台账启动")
                self.assertIn("--check", src)
                self.assertIn("exit 1", src, "检测到未迁移必须 fail-closed 停下")


if __name__ == "__main__":
    unittest.main()
