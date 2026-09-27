r"""自进化报告载荷抽取对拍门（第一百一十七刀）。

`scripts/self_improvement_engine.py::run_self_evolution`（154 行）里 20 行的报告字典 →
`scripts/evolution/report.py::build_evolution_report`（14 入参 / 1 输出）。

## 本门最重要的判据：**键集精确不变**

这段字典是**与前端/看板之间的契约** —— 键名就是前端读的字段。原先埋在 154 行编排函数
的中后段（前后是落盘与通知），删一个字段没有任何提示。门把 18 个键**逐个**钉住，
并按字段分组断言几条**不是"看起来那样"**的语义：

- `insights` 与 `diagnosis_insights` **是同一个列表**（历史字段名并存，前端两者都读）；
- `retired_count` / `baseline_memory_protected` 是**计数快照**，不是明细；
- `memory_preserved` 直接透传 `preserve_existing_memory`（不做二次判断）；
- `llm_error` 由 `__llm_error__` 转字符串、缺省 `""`（前端据此显示上游失败）；
- `mode` 是固定文案。

基线：`ec650b0`（本刀动工前最后提交）。
"""
from __future__ import annotations

import ast
import builtins
import subprocess
import sys
import unittest
from pathlib import Path
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "ec650b0"
FACADE = ROOT / "scripts" / "self_improvement_engine.py"
MOD = ROOT / "scripts" / "evolution" / "report.py"
OWNER = "run_self_evolution"

EXPECTED_KEYS = {
    "timestamp", "ledger_revision", "total_trades", "win_rate", "profit_factor", "mode",
    "change_status", "retired_lessons", "retired_count", "memory_preserved", "insights",
    "diagnosis_insights", "memory_overwrites_reason", "actions_taken", "core_lessons",
    "snapshot_audit", "baseline_memory_protected", "llm_error",
}


def _baseline_stmt() -> ast.Assign:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:scripts/self_improvement_engine.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    fn = next(n for n in ast.parse(normalize(r.stdout)).body
              if isinstance(n, ast.FunctionDef) and n.name == OWNER)
    return fn.body[40]


def _impl() -> ast.FunctionDef:
    t = ast.parse(MOD.read_text(encoding="utf-8"))
    return next(n for n in t.body
                if isinstance(n, ast.FunctionDef) and n.name == "build_evolution_report")


class EvolutionReportExtractionTest(unittest.TestCase):
    def test_call_site_passes_every_parameter_once_same_name(self):
        params = [a.arg for a in _impl().args.kwonlyargs]
        self.assertEqual(len(params), 14)
        tree = ast.parse(FACADE.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == OWNER)
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "build_evolution_report"]
        self.assertEqual(len(calls), 1)
        self.assertEqual([k.arg for k in calls[0].keywords], params)
        for k in calls[0].keywords:
            self.assertEqual(ast.unparse(k.value), k.arg)

    def test_no_undeclared_free_names(self):
        mod = ast.parse(MOD.read_text(encoding="utf-8"))
        mod_names = set()
        for n in mod.body:
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                mod_names.add(n.name)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                mod_names |= {a.asname or a.name.split(".")[0] for a in n.names}
        fn = _impl()
        local = {a.arg for a in fn.args.kwonlyargs}
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                local.add(n.id)
        reads = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        self.assertEqual(sorted(reads - local - set(dir(builtins)) - mod_names), [])

    # ---------- 行为例 ----------

    def _build(self, **over):
        from scripts.evolution.report import build_evolution_report
        kw = dict(actions_taken=[], change_status="NO_CHANGE", constitution_readded=[],
                  insights=[], ledger_revision="rev-1", llm_review={},
                  long_term_memory=["L1"], preserve_existing_memory=True,
                  profit_factor=1.5, retired_lessons=[], snapshot_audit={"n": 1},
                  timestamp_str="2026-09-15 13:00:00", total_trades=10, win_rate=60.0)
        kw.update(over)
        return build_evolution_report(**kw)

    def test_key_set_is_exactly_the_frontend_contract(self):
        self.assertEqual(set(self._build()), EXPECTED_KEYS,
                         "报告键集变了 —— 前端/看板按这些键读数据，改动必须同步前端与文档")

    def test_passthrough_fields(self):
        p = self._build(total_trades=7, win_rate=42.5, profit_factor=2.25,
                        ledger_revision="abc", timestamp_str="T",
                        snapshot_audit={"x": 1}, long_term_memory=["a", "b"],
                        actions_taken=["A"], insights=["I"], change_status="UPDATED")
        self.assertEqual((p["total_trades"], p["win_rate"], p["profit_factor"]), (7, 42.5, 2.25))
        self.assertEqual((p["ledger_revision"], p["timestamp"]), ("abc", "T"))
        self.assertEqual(p["snapshot_audit"], {"x": 1})
        self.assertEqual(p["core_lessons"], ["a", "b"])
        self.assertEqual(p["actions_taken"], ["A"])
        self.assertEqual(p["change_status"], "UPDATED")
        self.assertEqual(p["mode"], "ASTRA Native Heuristic Memory (启发式长期记忆)")

    def test_insights_and_diagnosis_insights_are_the_same_object(self):
        p = self._build(insights=["one"])
        self.assertEqual(p["insights"], ["one"])
        self.assertEqual(p["diagnosis_insights"], ["one"])
        self.assertIs(p["insights"], p["diagnosis_insights"],
                      "两个键共享同一个列表对象（历史字段名并存，勿改成两份拷贝）")

    def test_count_fields_are_snapshots(self):
        p = self._build(retired_lessons=["r1", "r2"], constitution_readded=["c1"])
        self.assertEqual(p["retired_count"], 2)
        self.assertEqual(p["baseline_memory_protected"], 1)
        self.assertEqual(p["retired_lessons"], ["r1", "r2"], "明细与计数都要有")

    def test_memory_preserved_passes_through(self):
        self.assertTrue(self._build(preserve_existing_memory=True)["memory_preserved"])
        self.assertFalse(self._build(preserve_existing_memory=False)["memory_preserved"])

    def test_llm_error_and_overwrite_reason_defaults(self):
        self.assertEqual(self._build()["llm_error"], "")
        self.assertEqual(self._build()["memory_overwrites_reason"], "")
        self.assertEqual(self._build(llm_review={"__llm_error__": "Timeout: 504"})["llm_error"],
                         "Timeout: 504", "上游失败必须可见（前端据此区别于静默 NO_CHANGE）")
        self.assertEqual(self._build(llm_review={"__llm_error__": {"code": 500}})["llm_error"],
                         "{'code': 500}", "非字符串也要 str 化，不得抛错")
        self.assertEqual(self._build(llm_review={"memory_overwrites_reason": "覆盖理由"})["memory_overwrites_reason"],
                         "覆盖理由")

if __name__ == "__main__":
    unittest.main()
