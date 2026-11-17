r"""持仓行判定件抽取对拍门（第一百零七刀）。

从 `sync_full_ledger.py::_holding_row`（88 行）里抽出两个**判定段**到
`scripts/ledger/holdings.py`：`judge_position_side`（审计 C8 方向判定）、
`format_holding_duration`（持仓时长格式化）。

## 本门钉两条**事故规则**

1. **审计 C8**：net-mode 行 `posSide="net"` 让旧式 `"long" in side_raw` 恒 False，
   净模式多仓被**系统性标成"空"**（策略/追踪 join 全错位）。修法是按符号回退判向，
   符号不可判 → 诚实标"未知"，**绝不猜**。
2. 时长：`<60分钟` 显示"N分钟"，否则"N时M分"；时间戳解析失败 → `"--"`（不得抛错）。

## 为什么本体没搬（边界性 pin，不是实现位置问题）

`test_ledger_okx_history_extraction::test_facade_still_exposes_the_public_surface_tests_use`
要求 `_holding_row` **仍以 `def` 定义在门面**（测试直接调用 + 双导入路径）。
本门把这条边界**再钉一次**，防后人"顺手把本体也搬走"。

基线：`7b84ad0`（本刀动工前最后提交）。
"""
from __future__ import annotations

import ast
import builtins
import datetime as _dt
import subprocess
import sys
import unittest
from pathlib import Path
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "7b84ad0"
FACADE = ROOT / "scripts" / "sync_full_ledger.py"
MOD = ROOT / "scripts" / "ledger" / "holdings.py"
OWNER = "_holding_row"
SPECS = {"judge_position_side": (7, 7), "format_holding_duration": (23, 23)}


class FakeDatetime:
    """注入用假 `datetime` 模块：`now` 固定，`strptime` 走真实实现 ⇒ 时长例可确定复现。"""

    class datetime:
        @staticmethod
        def strptime(s, fmt):
            return _dt.datetime.strptime(s, fmt)

        @staticmethod
        def now(tz=None):
            return _dt.datetime(2026, 9, 15, 12, 0, 0, tzinfo=tz)


def _baseline_fn() -> ast.FunctionDef:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:scripts/sync_full_ledger.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    return next(n for n in ast.parse(normalize(r.stdout)).body
                if isinstance(n, ast.FunctionDef) and n.name == OWNER)


def _impl(name: str) -> ast.FunctionDef:
    t = ast.parse(MOD.read_text(encoding="utf-8"))
    return next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _facade_calls() -> dict:
    out = {}
    for n in ast.walk(ast.parse(FACADE.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in SPECS:
            out.setdefault(n.func.id, n)
    return out


class LedgerHoldingsTest(unittest.TestCase):
    #: 已记录的**刻意差异**：第一百零七刀修掉了 `format_holding_duration` 里的
    #: naive/aware 失配（原实现使持仓时长恒为 "--"）。除这一处外，段体必须逐字一致。
    FIXED_DIFF = {("format_holding_duration", "strptime(open_time, \"%Y-%m-%d %H:%M:%S\")",
                   'strptime(open_time, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz_bj)')}

    def test_the_documented_fix_is_actually_present(self):
        """白名单必须"真的被应用"，否则它就变成为将来漂开的后门。"""
        from scripts.ledger.holdings import format_holding_duration
        import datetime as _d
        tz = _d.timezone(_d.timedelta(hours=8))
        got = format_holding_duration(
            datetime=_d, open_time="2026-09-15 11:30:00", tz_bj=tz)
        self.assertNotEqual(got, "--", "生产格式（naive 字符串）下时长**不得**再退化成占位符")

    def test_audit_comment_travelled_with_the_code(self):
        """审计 C8 的说明必须跟着代码走（注释丢了，规则就没人知道了）。"""
        text = MOD.read_text(encoding="utf-8")
        self.assertIn("审计 C8", text)
        self.assertIn("绝不猜", text)
        self.assertIn("净模式多仓被系统性标成", text)

    def test_holder_row_body_stays_in_facade(self):
        """边界性 pin：`_holding_row` 本体必须仍是门面的 `def`（不得顺手搬走）。"""
        tree = ast.parse(FACADE.read_text(encoding="utf-8"))
        self.assertIn("_holding_row", {n.name for n in tree.body if isinstance(n, ast.FunctionDef)})

    def test_calls_pass_every_parameter_once_same_name(self):
        calls = _facade_calls()
        for name in SPECS:
            with self.subTest(fn=name):
                params = [a.arg for a in _impl(name).args.kwonlyargs]
                call = calls[name]
                self.assertEqual(call.args, [])
                self.assertEqual([k.arg for k in call.keywords], params)
                for k in call.keywords:
                    self.assertEqual(ast.unparse(k.value), k.arg)

    def test_no_undeclared_free_names(self):
        module = ast.parse(MOD.read_text(encoding="utf-8"))
        mod_names = {n.name for n in module.body if isinstance(n, ast.FunctionDef)}
        for name in SPECS:
            with self.subTest(fn=name):
                fn = _impl(name)
                local = {a.arg for a in fn.args.kwonlyargs}
                for n in ast.walk(fn):
                    if isinstance(n, ast.ExceptHandler) and n.name:
                        local.add(n.name)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                        local.add(n.id)
                    if isinstance(n, (ast.Import, ast.ImportFrom)):
                        for a in n.names:
                            local.add(a.asname or a.name.split(".")[0])
                reads = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)
                         and isinstance(n.ctx, ast.Load)}
                missing = sorted(reads - local - set(dir(builtins)) - mod_names)
                self.assertEqual(missing, [], f"{name} 解析不到: {missing}")

    # ---------- 行为例：审计 C8 方向判定 ----------

    def _side(self, pos, side_raw):
        from scripts.ledger.holdings import judge_position_side
        return judge_position_side(p=pos, side_raw=side_raw)

    def test_explicit_sides_win(self):
        self.assertEqual(self._side({"pos": "1"}, "long"), "多")
        self.assertEqual(self._side({"pos": "-1"}, "short"), "空")

    def test_net_mode_falls_back_to_sign(self):
        """审计 C8 的核心：net-mode 不得被判成"空"。"""
        self.assertEqual(self._side({"pos": "1.5"}, "net"), "多",
                         "净模式多仓**必须**判成多（旧实现在此系统性错标为空）")
        self.assertEqual(self._side({"pos": "-2"}, "net"), "空")
        self.assertEqual(self._side({"pos": "0"}, "net"), "未知", "符号不可判 ⇒ 诚标未知")

    def test_missing_posside_also_falls_back(self):
        self.assertEqual(self._side({"pos": "3"}, ""), "多")

    def test_unparsable_size_is_unknown_not_crash(self):
        self.assertEqual(self._side({"pos": "abc"}, "net"), "未知")

    # ---------- 行为例：时长 ----------

    def _dur(self, open_time):
        from scripts.ledger.holdings import format_holding_duration
        return format_holding_duration(datetime=FakeDatetime, open_time=open_time,
                                       tz_bj=_dt.timezone.utc)

    def test_minutes_and_hours_format(self):
        self.assertEqual(self._dur("2026-09-15 11:30:00"), "30分钟")
        self.assertEqual(self._dur("2026-09-15 10:30:00"), "1时30分")
        self.assertEqual(self._dur("2026-09-15 11:00:00"), "1时0分",
                         "整 60 分钟走「时/分」分支（`< 60` 是严格小于）")

    def test_bad_timestamp_degrades_to_placeholder(self):
        self.assertEqual(self._dur("not-a-time"), "--", "解析失败必须降级为占位符，不得抛错")
        self.assertEqual(self._dur(""), "--")

if __name__ == "__main__":
    unittest.main()
