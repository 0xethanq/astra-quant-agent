"""`sync_web_data.generate_trading_data` 的重复读修复（结构优化阶段 4·B3 第六十二刀）。

## 修了什么

用户目标里明确列了"**清理无效循环重复计算**"。用 AST 扫全仓
"同函数内同一纯表达式出现 >=3 次" 得到 194 个候选 —— 但逐个看下来**几乎全是误报**
（`if/elif` 分支里的同名调用每轮只走一条、`time.time()` 本就该每次取新值等）。
**这个结论本身值得记下来：静态重复计数不能直接当成浪费。**

真正的浪费只有一处，且是 I/O 级的：

`generate_trading_data()` 里 `snapshots.json` 与 `trading_ledger.json`
**各被 open + json.load 两次**：

| 位置 | 用途 | 条件 |
|---|---|---|
| 权益为 0 时的快照兜底 | 取最后一个有效快照 | `total_eq == 0 and exists` |
| 当日胜负统计（JSON 兜底分支） | 遍历全部台账行 | `ledger 不存在（无 SQLite）` |
| 第 4 步 `snapshots`（尾部 40 条） | 喂前端曲线 | `exists` |
| 第 4 步 `trades`（倒序 60 条） | 喂前端列表 | `exists` |

台账可到数千行，**第二次解析完全浪费**。

## ⚠️ 语义必须逐条对齐（修这种"顺手优化"最容易改坏的地方）

1. **四处各自的 `try/except` 一个都不能合并** —— 原代码是两个独立 try，
   合并会改变异常传播路径；
2. **取值必须惰性** —— 原代码只在各自 `os.path.exists(...)` 成立时才读；
   若函数一进来就预读，`disk_usage` 的失败顺序会变；
3. **缓存必须逐调用清空** —— 调用方 `scripts/daemon_web_sync.py`
   是 `while True: generate_trading_data()` **循环**调用的，
   缓存跨调用存活就会读到上一轮的文件内容（陈旧数据）。
   这一点我是**读调用点才发现**的，不是想当然；
4. **用哨兵而不是 `None` 表示"未缓存"** —— 否则文件内容恰为 `null`
   （合法 JSON）时每次都判为未缓存，退化成"每调用一次读一次"；
5. 返回值**不拷贝** —— 已逐处确认调用点无 `del` / `append` / `[i]=` 等原地修改。
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULE = ROOT / "scripts" / "sync_web_data.py"

import scripts.sync_web_data as sync_web_data  # noqa: E402


def _code(p: Path) -> str:
    """剥注释与文档串（逐字符扫描，不用正则 —— 第五十六刀的教训）。"""
    text = p.read_text(encoding="utf-8")
    res: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "#":
            j = text.find("\n", i)
            if j == -1:
                break
            res.append(" " * (j - i))
            i = j
            continue
        if c in "\"'":
            quote = c * 3 if text[i:i + 3] == c * 3 else c
            j = i + len(quote)
            while j < n:
                if text[j] == "\\":
                    j += 2
                    continue
                if text[j:j + len(quote)] == quote:
                    break
                j += 1
            seg = text[i:j + len(quote)]
            res.append("\n" * seg.count("\n") + " " * (len(seg) - seg.count("\n")))
            i = j + len(quote)
            continue
        res.append(c)
        i += 1
    return "".join(res)


class SingleReadPerCallTest(unittest.TestCase):
    """⚠️ 核心：同一文件在一次调用里只应被读一次。"""

    def setUp(self):
        sync_web_data._JSON_CACHE.clear()
        self.addCleanup(sync_web_data._JSON_CACHE.clear)
        self.tmp = tempfile.mkdtemp(prefix="r62-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)

    def _path(self, name, payload):
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            f.write(payload)
        return p

    def test_repeated_calls_read_the_file_once(self):
        p = self._path("a.json", "[1, 2, 3]")
        real_open = open
        calls = {"n": 0}

        def counting_open(*a, **k):
            if a and str(a[0]) == p:
                calls["n"] += 1
            return real_open(*a, **k)

        sync_web_data._JSON_CACHE.clear()
        with patch.object(sync_web_data, "open", counting_open, create=True):
            first = sync_web_data._load_json_list(p, default=[])
            second = sync_web_data._load_json_list(p, default=[])
        self.assertEqual(first, [1, 2, 3])
        self.assertEqual(second, [1, 2, 3])
        self.assertEqual(calls["n"], 1, f"同一路径被读了 {calls['n']} 次，应为 1")

    def test_null_payload_is_cached_not_reread(self):
        """⚠️ 文件内容恰为 `null` 时不得退化成"每次重读"。"""
        p = self._path("n.json", "null")
        real_open = open
        calls = {"n": 0}

        def counting_open(*a, **k):
            if a and str(a[0]) == p:
                calls["n"] += 1
            return real_open(*a, **k)

        sync_web_data._JSON_CACHE.clear()
        with patch.object(sync_web_data, "open", counting_open, create=True):
            self.assertIsNone(sync_web_data._load_json_list(p))
            self.assertIsNone(sync_web_data._load_json_list(p))
        self.assertEqual(calls["n"], 1, "null 内容被重复读取 —— 哨兵失效")

    def test_missing_file_returns_default_and_does_not_raise(self):
        # ⚠️ 两个断言必须用**不同路径**（或先清缓存）：同一路径第二次会命中缓存，
        #    拿到的仍是第一次的 default —— 我第一版就是栽在这里（误报成"代码 bug"）。
        self.assertEqual(
            sync_web_data._load_json_list(os.path.join(self.tmp, "no1.json"), default=[]), [])
        sync_web_data._JSON_CACHE.clear()
        self.assertIsNone(
            sync_web_data._load_json_list(os.path.join(self.tmp, "no1.json")))

    def test_corrupt_file_returns_default(self):
        p = self._path("bad.json", "{not json")
        self.assertEqual(sync_web_data._load_json_list(p, default=[]), [])

    def test_clear_resets_the_cache(self):
        """逐调用清空是必需的 —— 调用方 daemon 在 while 循环里调它。"""
        p = self._path("c.json", "[1]")
        sync_web_data._JSON_CACHE.clear()
        self.assertEqual(sync_web_data._load_json_list(p, default=[]), [1])
        self._path("c.json", "[2]")
        self.assertEqual(sync_web_data._load_json_list(p, default=[]), [1],
                         "未清空时应命中缓存（证明缓存真的在生效）")
        sync_web_data._JSON_CACHE.clear()
        self.assertEqual(sync_web_data._load_json_list(p, default=[]), [2],
                         "清空后应重读新内容")

    def test_generate_trading_data_clears_the_cache_each_call(self):
        """⚠️ 端到端钉住「逐调用清空」这条不变量。"""
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "generate_trading_data")
        head = ast.unparse(ast.Module(body=fn.body[:3], type_ignores=[]))
        self.assertIn("_JSON_CACHE.clear()", head,
                      "generate_trading_data 开头必须清空缓存（否则循环调用读到陈旧数据）")


class EndToEndSingleReadTest(unittest.TestCase):
    """⚠️ 端到端证明：一次 `generate_trading_data()` 调用里，
    两个数据文件各只被读 **一次**。

    ⚠️ 安全设计：**放行读、硬拦写**。

    本环境里 `tests/config_sandbox.isolate_config()` **不覆盖**
    `scripts/sync_web_data`（它只重定向白名单模块的大写路径常量），
    所以直接调用会写**生产** `data/trading_data.json`。
    故本用例不用隔离目录，而是把 `open` 换成"读放行、写一律抛
    `PermissionError`"的守卫 —— 既拿到结论，又保证绝不触碰生产数据。

    探针实测（2026-09-15）：`snapshots.json` 1 次、`trading_ledger.json` 1 次，
    被拦下的写入只有 `trading_data.json.tmp`（即函数跑到了最后一步才被拦）。
    """

    def test_generate_reads_each_data_file_exactly_once(self):
        # ⚠️ 第七十九刀：本用例原先**隐式依赖真实凭证** —— 非离线时
        # `env.configured=True` ⇒ generate **拿 .env 真 key 打 www.okx.com
        # ×4/次**（探针实测），真实失败才 fail-soft 走到文件读取；
        # 离线时 NotConfigured 提前 raise ⇒ 读 0（上轮的 skip 是权宜）。
        # 现在把 fetch 层显式压成 None：fail-soft 语义下流程**确定地**
        # 抵达 L215/L221 的读取点 ⇒ 非离线零外呼、离线也从 skip 变真测。
        prod = pathlib.Path(sync_web_data.DATA_DIR).resolve()
        snaps = str(pathlib.Path(sync_web_data.SNAPSHOTS_JSON_FILE))
        led = str(pathlib.Path(sync_web_data.LEDGER_JSON_FILE))
        # 先确认"我们面对的是生产目录"—— 若哪天它变成临时目录，本用例的安全
        # 假设就不再成立，应当显式知道（而不是静默地继续）。
        # ⚠️ 原来这里钉的是**检出目录的字面名字**（`/data/dsh/home/<检出目录>/data`）。
        #    2026-09-27「r20 → astra 全量改名」把它一起改掉了，于是它开始断言一个
        #    不存在的路径 —— 同一类问题在本轮共出现三处。改判真正要钉的性质：
        #    DATA_DIR 就是**本模块所在仓库根**下的 data/，且不在临时目录里。
        repo_root = pathlib.Path(sync_web_data.__file__).resolve().parents[1]
        self.assertEqual(prod, (repo_root / "data").resolve(),
                         f"DATA_DIR 不是仓库根的 data/：{prod}")
        self.assertFalse(str(prod).startswith(("/tmp", "/var/folders")),
                         f"DATA_DIR 落在临时目录里，本用例的安全假设不再成立：{prod}")

        real_open, seen, blocked = open, {}, []

        def guard_open(f, mode="r", *a, **k):
            fs = str(f)
            if fs in (snaps, led):
                seen[fs] = seen.get(fs, 0) + 1
            if any(c in str(mode) for c in ("w", "a", "x", "+")):
                blocked.append(fs)
                raise PermissionError("单读测试拦截写入: " + fs)
            return real_open(f, mode, *a, **k)

        sync_web_data._JSON_CACHE.clear()
        self.addCleanup(sync_web_data._JSON_CACHE.clear)
        # fetch 层压成 None（fail-soft 语义下继续走到文件读取），
        # 环境标成 configured（不走 NotConfigured 提前 raise）——零外呼。
        import types
        _env = types.SimpleNamespace(configured=True)
        with patch.object(sync_web_data, "open", guard_open, create=True), \
             patch.object(sync_web_data.okx_runtime, "current_environment", lambda: _env), \
             patch.object(sync_web_data.okx_rest, "balances", lambda *a, **k: None), \
             patch.object(sync_web_data.okx_rest, "positions", lambda *a, **k: None), \
             patch.object(sync_web_data.okx_rest, "pending_orders", lambda *a, **k: None), \
             patch.object(sync_web_data.okx_rest, "bills", lambda *a, **k: None), \
             patch.object(sync_web_data, "fetch_tickers_bulk", lambda *a, **k: []):
            try:
                sync_web_data.generate_trading_data()
            except PermissionError:
                pass      # 走到写盘那一步被我们拦下，属预期
            except Exception:
                pass      # 凭证未配置等 fail-closed，同样不影响读取次数结论

        self.assertNotIn(str(prod / "trading_data.json"), blocked,
                         "本用例绝不允许写生产 trading_data.json")
        for path in (snaps, led):
            if os.path.exists(path):
                with self.subTest(f=os.path.basename(path)):
                    self.assertEqual(seen.get(path, 0), 1,
                                     f"{os.path.basename(path)} 被读了 "
                                     f"{seen.get(path, 0)} 次，应为 1")


class NoRawDualReadTest(unittest.TestCase):
    """⚠️ 那两处"同一文件读两次"不得长回来。"""

    def test_no_duplicate_open_of_the_same_path(self):
        """⚠️ 断言必须覆盖 `open()` 的**所有**写法，不能只匹配某一种。

        负向验证当场抓到我第一版的漏洞：断言写的是 `open(X, "r"`，
        于是 `open(SNAPSHOTS_JSON_FILE)`（**不带 mode**）这种注入
        完全绕过了它 —— 4 条注入全部 `OK`（未被抓住）。
        改为按 AST 找 `open(<常量>)` 调用，与写法无关。
        """
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        consts = {"SNAPSHOTS_JSON_FILE", "LEDGER_JSON_FILE"}
        direct = []
        for n in ast.walk(tree):
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "open" and n.args
                    and isinstance(n.args[0], ast.Name) and n.args[0].id in consts):
                direct.append(f"L{n.lineno}: open({n.args[0].id})")
        # 唯一的直接 open 允许出现在 `_load_json_list` 自己的实现里
        helper = next(n for n in tree.body
                      if isinstance(n, ast.FunctionDef) and n.name == "_load_json_list")
        inside = {n.lineno for n in ast.walk(helper) if isinstance(n, ast.Call)}
        outside = [d for d in direct if int(d.split(":")[0][1:]) not in inside]
        self.assertEqual(outside, [],
                         f"这些位置绕过了 _load_json_list()，会重复读盘: {outside}")
        src = _code(MODULE)
        for const in sorted(consts):
            self.assertIn(f"_load_json_list({const}", src, f"{const} 未走缓存载入器")

    def test_generate_trading_data_still_exists_and_is_the_entry(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        names = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertIn("generate_trading_data", names)
        self.assertIn("_load_json_list", names)

    PRE = "9caee5d"   # 第六十一刀提交 —— 本刀之前

    def test_no_new_dependencies(self):
        """⚠️ 用**与改动前的对比**，而不是手抄一份"允许名单"。

        我第一版手抄了一份名单，结果漏了 `instrument_pool` /
        `market_data_service`（第 33-34 行**既有的**本地导入）→ 误报。
        手抄名单必然漏 —— 改成直接和 `git show <改动前>` 对比依赖集合，
        只有**新增**才算违规。
        """
        import subprocess
        old = subprocess.run(["git", "show", f"{self.PRE}:scripts/sync_web_data.py"],
                             capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(old.returncode, 0, old.stderr)

        def mods_of(text: str) -> set:
            out = set()
            for n in ast.walk(ast.parse(text)):
                if isinstance(n, ast.Import):
                    out |= {a.name.split(".")[0] for a in n.names}
                elif isinstance(n, ast.ImportFrom) and n.module:
                    out.add(n.module.split(".")[0])
            return out

        # ⚠️ 基线取自**改名前**的提交（`r20_backend.*`），直接比会把命名空间迁移
        #    误判成"新增第三方依赖 `astra_backend`"。用本仓已有的基线归一助手，
        #    把两侧放到同一命名空间下再比（这是"声明一次"而非临时放行）。
        from tests.extraction.rename_baseline import normalize
        added = mods_of(MODULE.read_text(encoding="utf-8")) - mods_of(normalize(old.stdout))
        # ⚠️ 用户约束是"禁止增减**依赖**"，指的是第三方包；标准库不是依赖。
        #    本刀只新增了 `typing`（stdlib），故按 stdlib 白名单放行，
        #    第三方新增仍然会被抓住。
        stdlib = set(sys.stdlib_module_names)
        third_party_added = {m for m in added if m not in stdlib}
        self.assertEqual(third_party_added, set(),
                         f"新增了第三方依赖（禁止增减依赖）: {sorted(third_party_added)}")
        self.assertTrue(added <= stdlib,
                        f"新增的模块应为标准库: {sorted(added - stdlib)}")


class BehaveUnchangedTest(unittest.TestCase):
    def test_helper_does_not_copy_the_payload(self):
        """原实现把 `json.load` 的结果直接交给调用点；缓存也不得拷贝
        （逐处确认过调用点只读）。"""
        p = os.path.join(tempfile.mkdtemp(prefix="r62b-"), "d.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump([{"a": 1}], f)
        sync_web_data._JSON_CACHE.clear()
        first = sync_web_data._load_json_list(p, default=[])
        second = sync_web_data._load_json_list(p, default=[])
        self.assertIs(first, second, "两次调用应返回同一对象（未拷贝）")


if __name__ == "__main__":
    unittest.main()
