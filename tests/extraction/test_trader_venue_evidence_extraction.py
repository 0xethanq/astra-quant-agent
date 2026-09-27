r"""venue_evidence 抽取对拍门（结构优化阶段 4·B3 第八十二刀）。

`build_venue_candidates` / `persist_venue_decision` 从
`scripts/ai_factor_trader.py` **纯搬家**到 `scripts/trader/venue_evidence.py`。
注入 kw 与门面全局**同名** ⇒ 函数体应逐字相同，唯一机械差异：
基线内部直调门面私有 `_venue_health_stamp()` → 子包调注入名
`venue_health_stamp()`（归一为同一假名后对拍）。

壳形状/调用期注入/判据自检与前两刀门同构。
"""
from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "1541c13"
FNS = ("build_venue_candidates", "persist_venue_decision")


def _old_tree() -> ast.Module:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:scripts/ai_factor_trader.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    return ast.parse(normalize(r.stdout))


def _get_func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name} 不在顶层")


def _normalize(node: ast.AST) -> str:
    for sub in ast.walk(node):
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name)
                and sub.func.id in ("_venue_health_stamp", "venue_health_stamp")):
            sub.func.id = "__stamp__"
    return ast.dump(node, include_attributes=False)


class VenueEvidenceVerbatimTest(unittest.TestCase):
    def test_shells_are_def_with_lazy_injection(self):
        tree = ast.parse((ROOT / "scripts/ai_factor_trader.py").read_text(encoding="utf-8"))
        for fn, want in (("build_venue_candidates",
                          ("_venue_health_stamp", "venue_registry", "MAKER_FEE_RATE",
                           "VENUE_HEALTH_MAX_AGE_S", "load_preferred_venue",
                           "venue_execution_ready")),
                         ("persist_venue_decision", ("AI_DECISION_CACHE_FILE",))):
            with self.subTest(fn=fn):
                dumped = ast.unparse(_get_func(tree, fn))
                self.assertIn("_venue_evidence_", dumped, "壳没有转调子包")
                for g in want:
                    self.assertIn(g, dumped, f"壳未调用期注入 {g}")

    def test_persist_shell_reads_patched_constant(self):
        """行为：patch 门面 AI_DECISION_CACHE_FILE，经壳 persist 必须写到
        patch 后的文件（import 期快照=红）。缓存无该标的 → False + 不伪造。"""
        import json
        import tempfile
        from pathlib import Path as P
        from unittest.mock import patch
        import scripts.ai_factor_trader as aft
        with tempfile.TemporaryDirectory() as td:
            cache = P(td) / "ai_brain_decisions.json"
            cache.write_text(json.dumps({"BTC-USDT-SWAP": {"side": "buy"}}), encoding="utf-8")
            with patch.object(aft, "AI_DECISION_CACHE_FILE", str(cache)):
                ok = aft.persist_venue_decision("BTC-USDT-SWAP", {"venue": "okx"})
            data = json.loads(cache.read_text(encoding="utf-8"))
        self.assertTrue(ok)
        self.assertEqual(data["BTC-USDT-SWAP"]["venue_decision"], {"venue": "okx"})
        self.assertEqual(data["BTC-USDT-SWAP"]["side"], "buy", "既有字段必须逐键保留")

if __name__ == "__main__":
    unittest.main()
