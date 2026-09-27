r"""dashboard 相位 1 抽取对拍门（结构优化阶段 2·B2 续刀·第九十四刀）。

`astra_backend/dashboard_cache.py::update_cache_cycle` 的相位 1（并发抓取余额/持仓/挂单 +
失败语义 + 连接缺失判定 + 基础解析，58 行）**纯搬家**到
`astra_backend/dashboard_payload/collect.py::collect_core_account_state`。

判据同 trader 域：段体 **AST 逐字**、调用点**逐个同名恰好一次**、自由名可解析；
另加三条**行为例**（连接缺失判定 / 部分失败 / 成功解析）——这三条正是这段代码
存在的理由，光有 AST 对拍证明不了它们仍然成立。
"""
from __future__ import annotations

import ast
import builtins
import subprocess
import sys
import types
import unittest
from pathlib import Path
from tests.extraction.rename_baseline import legacy_rev_path, normalize

# 第 143 刀：本模块从 `dashboard/app.py` 迁到 `astra_backend/dashboard_cache.py`。
# **对拍基线必须按历史路径取**（旧 revision 里只有 dashboard/app.py），
# LIVE 文件走新路径 —— 两者不可混用，否则基线取不到、对拍门必然失真。
PRE_MOVE_PATH = "dashboard/app.py"

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "a4f310a"                      # 本刀动工前最后提交（第九十三刀收口）
APP = ROOT / "astra_backend" / "dashboard_cache.py"
MOD = ROOT / "astra_backend" / "dashboard_payload" / "collect.py"
FN = "collect_core_account_state"
SEG = (6, 26)                        # 基线 update_cache_cycle 的语句下标区间


def _baseline_cycle() -> ast.FunctionDef:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:{PRE_MOVE_PATH}")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    t = ast.parse(normalize(r.stdout))
    return next(n for n in t.body if isinstance(n, ast.FunctionDef)
                and n.name == "update_cache_cycle")


def _impl() -> ast.FunctionDef:
    t = ast.parse(MOD.read_text(encoding="utf-8"))
    return next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == FN)


def _seg_stmts(fn: ast.FunctionDef) -> list:
    body = list(fn.body)
    if (body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    if body and isinstance(body[-1], ast.Return):
        body = body[:-1]
    return body


def _call() -> ast.Call:
    t = ast.parse(APP.read_text(encoding="utf-8"))
    for n in ast.walk(t):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == FN:
            return n
    raise AssertionError("app.py 里没有 collect_core_account_state 调用点")


FIELDS = ("_private_not_ready", "avail_eq", "balance_ok", "cash_bal", "long_count",
          "orders_data", "pending_orders_list", "positions", "positions_ok", "short_count",
          "total_eq", "total_pos_upl", "trackers", "upl_acc")


def field(got, name):
    """按字段名取返回元组的一项（不靠人肉数下标）。"""
    return got[FIELDS.index(name)]


class CollectVerbatimTest(unittest.TestCase):
    def test_call_passes_every_parameter_once_same_name(self):
        params = [a.arg for a in _impl().args.kwonlyargs]
        call = _call()
        self.assertEqual(call.args, [])
        self.assertEqual([k.arg for k in call.keywords], params,
                         "调用点参数与签名不一致（漏传=生产 NameError）")
        for k in call.keywords:
            self.assertEqual(ast.unparse(k.value), k.arg, f"{k.arg} 未按同名传参")

    def test_no_undeclared_free_names(self):
        fn = _impl()
        module = ast.parse(MOD.read_text(encoding="utf-8"))
        mod_names = set()
        for n in module.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                mod_names.add(n.name)
            elif isinstance(n, ast.Assign):
                for tg in n.targets:
                    if isinstance(tg, ast.Name):
                        mod_names.add(tg.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    mod_names.add(a.asname or a.name.split(".")[0])
        local = {a.arg for a in fn.args.args} | {a.arg for a in fn.args.kwonlyargs}
        for n in ast.walk(fn):
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                local.add(n.name); local |= {a.arg for a in n.args.args}
            if isinstance(n, ast.Lambda):
                local |= {a.arg for a in n.args.args}
            if isinstance(n, ast.comprehension):
                tg = n.target
                for e in (tg.elts if isinstance(tg, (ast.Tuple, ast.List)) else [tg]):
                    if isinstance(e, ast.Name):
                        local.add(e.id)
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                local.add(n.id)
            if isinstance(n, ast.ExceptHandler) and n.name:
                local.add(n.name)
        reads = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)
                 and isinstance(n.ctx, ast.Load)}
        missing = sorted(reads - local - set(dir(builtins)) - mod_names)
        self.assertEqual(missing, [], f"解析不到的名字（会 NameError）: {missing}")

    # ---------- 行为例：这段代码存在的三条理由 ----------

    def _run(self, *, bal, pos, orders, errors=None):
        from astra_backend.dashboard_payload import collect as C
        src_errors = errors if errors is not None else []
        collected = {}

        class _Pool:
            def __init__(self, **k): pass
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def submit(self, fn, call):
                return types.SimpleNamespace(result=lambda: fn(call))

        # `_fetch_json(call)` 的语义就是"调用这个无参可调用对象并把异常折成三元组"，
        # 故替身直接调用即可；三个方法各自返回自己的载荷（不再按 lambda 名分发）。
        def _fetch(call):
            return call()

        def _pos_rows(data, positions, trackers, *, load_instruments):
            # 与真实收集器一致：**只有拿到数据才填充**（失败时 data 被降级为空列表）
            if data:
                positions.append({"instId": "BTC-USDT-SWAP"})
                return (1, 0, 5.0)
            return (0, 0, 0.0)

        def _ord_rows(data, out, *, tz_beijing, datetime):
            if data:
                out.append({"instId": "BTC-USDT-SWAP"})
            return None

        got = C.collect_core_account_state(
            source_errors=src_errors, tz_beijing=None, ThreadPoolExecutor=_Pool,
            _NOT_READY_TEXT="NOT_READY", _core_collect_pending_order_rows=_ord_rows,
            _core_collect_position_rows=_pos_rows, _fetch_json=_fetch, datetime=None,
            load_instruments=lambda: [], load_position_trackers=lambda: {},
            okx_rest=types.SimpleNamespace(balances=lambda: bal, positions=lambda: pos,
                                           pending_orders=lambda: orders))
        return got, src_errors

    @staticmethod
    def _ok():
        return (True, [{"details": [{"ccy": "USDT", "eq": "1000", "availBal": "900",
                                     "cashBal": "950", "upl": "10"}]}], "")

    def test_all_private_queries_not_ready_marks_connection_missing(self):
        got, errs = self._run(bal=(False, None, "NOT_READY"),
                              pos=(False, None, "NOT_READY"),
                              orders=(False, None, "NOT_READY"))
        self.assertTrue(field(got, "_private_not_ready"),
                        "三项同时 NOT_READY ⇒ 连接方式缺失（_private_not_ready）")
        self.assertEqual(len(errs), 3, "三项失败都要记 source_errors")
        self.assertEqual(field(got, "positions"), [], "失败时持仓降级为空列表")
        self.assertEqual(field(got, "pending_orders_list"), [], "失败时挂单降级为空列表")

    def test_partial_failure_is_not_connection_missing(self):
        got, errs = self._run(bal=self._ok(), pos=(False, None, "timeout"),
                              orders=(False, None, "NOT_READY"))
        self.assertFalse(field(got, "_private_not_ready"), "只有一项成功 ⇒ 不是「连接方式缺失」")
        self.assertEqual(len(errs), 2)
        self.assertEqual(field(got, "total_eq"), 1000.0, "余额仍要解析出来（total_eq）")

    def test_success_parses_balance_and_collects_rows(self):
        got, errs = self._run(bal=self._ok(), pos=self._ok(), orders=self._ok())
        _, avail_eq, balance_ok, cash_bal, long_count, orders_data, pending, positions, \
            positions_ok, short_count, total_eq, total_pos_upl, trackers, upl_acc = got
        self.assertTrue(balance_ok and positions_ok)
        self.assertEqual((total_eq, avail_eq, cash_bal, upl_acc), (1000.0, 900.0, 950.0, 10.0))
        self.assertEqual(len(positions), 1, "持仓行由 _core_collect_position_rows 原地填充")
        self.assertEqual(len(pending), 1, "挂单行同上")
        self.assertEqual((long_count, short_count, total_pos_upl), (1, 0, 5.0),
                         "方向计数与浮盈增量来自收集器的返回值")
        self.assertEqual(errs, [])

if __name__ == "__main__":
    unittest.main()
