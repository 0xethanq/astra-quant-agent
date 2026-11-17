r"""signal_snapshot 抽取对拍门（结构优化阶段 4·B3 第八十二刀）。

`build_signal_snapshot` 从 `scripts/ai_factor_trader.py` **纯搬家**到
`scripts/trader/signal_snapshot.py`。判据与 circuit_guard 门同构：

1. **逐字相同**：基线函数体 vs 子包实现，只允许登记过的机械差异
   （`DATA_DIR → data_dir` 注入改名）；
2. 门面壳 `def` 形状 + 调用期解析 `DATA_DIR`（import 期快照即红）；
3. 行为接线：patch 门面 `DATA_DIR` 必须改变经壳调用的读文件行为
   （既有专测同款 patch 面的最小复证）；
4. 判据自检（± 双向）。
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

PRE = "1541c13"  # 本刀动工前的最后提交（第七十九～八十一刀收口）
RENAMES = {"DATA_DIR": "data_dir"}
FN = "build_signal_snapshot"


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
        if isinstance(sub, ast.Name) and sub.id in RENAMES:
            sub.id = RENAMES[sub.id]
    return ast.dump(node, include_attributes=False)


class SignalSnapshotVerbatimTest(unittest.TestCase):
    def test_facade_shell_is_def_with_lazy_injection(self):
        tree = ast.parse((ROOT / "scripts/ai_factor_trader.py").read_text(encoding="utf-8"))
        shell = _get_func(tree, FN)
        dumped = ast.unparse(shell)
        self.assertIn("_signal_snapshot_build", dumped, "壳没有转调子包实现")
        self.assertIn("DATA_DIR", dumped, "壳未在调用期解析门面全局 DATA_DIR")

    def test_shell_wiring_reacts_to_facade_patch(self):
        """patch 门面 DATA_DIR 必须改变经壳行为：指向"损坏 JSON"的目录时
        二次补齐必须静默跳过（fail-soft），指向正常沙箱时必须补齐。"""
        import json
        import tempfile
        from unittest.mock import patch
        import scripts.ai_factor_trader as aft

        f_in = {"instId": "BTC-USDT-SWAP", "calculus": {},
                "price": 1.0}  # adx 等四字段缺 → 触发二次补齐分支
        with tempfile.TemporaryDirectory() as td:
            snap_dir = Path(td) / "data"
            snap_dir.mkdir()
            (snap_dir / "factor_library_snapshot.json").write_text(
                json.dumps({"instruments": [{"instId": "BTC-USDT-SWAP",
                                             "composite_alpha_score": 77.7}]}),
                encoding="utf-8")
            with patch.object(aft, "DATA_DIR", str(snap_dir)):
                good = aft.build_signal_snapshot(dict(f_in))
            with patch.object(aft, "DATA_DIR", str(Path(td) / "missing")):
                miss = aft.build_signal_snapshot(dict(f_in))
        self.assertEqual(good.get("composite_alpha_score"), 77.7,
                         "沙箱 DATA_DIR 没传到子包 ⇒ 壳在 import 期快照了值")
        self.assertIsNone(miss.get("composite_alpha_score"),
                          "文件缺失路径不得伪造数据（fail-soft 语义）")

if __name__ == "__main__":
    unittest.main()
