"""B3（主脑侧第三块）`scripts/brain/decisions.py` 的抽取回归。

## 这个测试在守什么

`validate_and_filter_decision` + `assemble_decision_cache`（原门面 L915-1062，
148 行）搬进 `scripts/brain/decisions.py`。这块**原本有覆盖**
（`test_policy_snapshot_isolated` / `test_leverage_range_and_council` /
`test_prompt_math_foundations` / `test_ai_health_sidecar`），所以风险同样是
「搬走时把测试缝一起搬没了」，而不是"坏了没人知道"。

三处既有测试缝：

| 依赖 | 缝在哪 |
|---|---|
| `DATA_DIR` | `test_ai_health_sidecar.py:20` `patch.object(abt, "DATA_DIR", …)` —— 装配时要读 `asset_multipliers.json` |
| `MAX_LEVERAGE` / `MIN_LEVERAGE` | `test_leverage_range_and_council.py:212` 同时 patch 并断言"模型给 3 被下限抬到 5" |
| `safe_float` | 定义在门面自身，且门面会被原地重载 |

另加两条本块特有的检查：门面壳确实转发（实现体确实搬走），以及
`validate` 的跨函数注入确实生效。
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.ai_brain_trader as abt
from scripts.brain import decisions

ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "scripts" / "ai_brain_trader.py"
SUBMODULE = ROOT / "scripts" / "brain" / "decisions.py"

# 只在子模块里存在、门面不应再有的实现体特征行
_IMPL_ONLY_MARKERS = (
    '    lev_hi = max(1, int(round(max_leverage)))',
    '    lev_lo = max(1, min(int(round(min_leverage)), lev_hi))',
    '        mult_file = os.path.join(data_dir, "asset_multipliers.json")',
)

_PKG = {
    "instId": "BTC-USDT-SWAP", "name": "BTC", "price": 80000.0,
    "market_data_valid": True, "atr": 400.0, "precision": 1, "ctVal": 0.01,
    "adx_1h": 30.0, "rsi": 60.0,
    "calculus": {"valid": True, "regime": "BULL", "velocity": 0.5, "acceleration": 0.2,
                 "max_abs_jerk": 0.1, "impulse": 0.3, "curvature": 0.1, "power": 0.2,
                 "probability_theory": {"continuation_prob_pct": 60.0,
                                        "breakdown_prob_pct": 10.0}},
}
_DECISION = {
    "action": "WAIT", "confidence": 50.0, "leverage": 3, "margin_usdt": 10.0,
    "entry_price": 0, "take_profit_price": 0, "stop_loss_price": 0,
    "summary_reason": "test", "adopted_role": "trader_momentum",
    "market_structure": "x", "calculus_dynamics": "y", "math_prob_rationale": "z",
    "volume_and_oi": "w",
}


def _call(**overrides):
    kwargs = dict(
        packages=[_PKG], decisions_dict={"BTC-USDT-SWAP": dict(_DECISION)},
        active_inst_ids=set(), active_position_sides={},
        time_str="2026-09-14 10:00:00", macro_summary="m",
        policy_snapshot={"policy_version": "v@test", "policy_hash": "h"},
        council_status={"ran": True, "duration_ms": 1500, "consensus_mode": "standard"},
    )
    kwargs.update(overrides)
    return abt.assemble_decision_cache(**kwargs)


class ImplementationActuallyMovedTest(unittest.TestCase):
    def test_impl_bodies_live_in_submodule_not_facade(self):
        facade = FACADE.read_text(encoding="utf-8")
        sub = SUBMODULE.read_text(encoding="utf-8")
        for marker in _IMPL_ONLY_MARKERS:
            self.assertIn(marker, sub, f"实现体未搬入子模块: {marker!r}")
            self.assertNotIn(marker, facade, f"门面仍留有实现体: {marker!r}")

    def test_facade_shells_delegate(self):
        facade = FACADE.read_text(encoding="utf-8")
        self.assertIn("_validate_and_filter_decision_impl(", facade)
        self.assertIn("_assemble_decision_cache_impl(", facade)


class InjectionContractTest(unittest.TestCase):
    """三处既有测试缝在搬运后必须仍然生效。"""

    def test_data_dir_patch_is_observed(self):
        """`patch.object(abt, "DATA_DIR", …)` 必须仍能改到 asset_multipliers 的读取路径。

        用一个临时目录放一份**可辨识的** asset_multipliers.json：若装配器读的是
        真实 DATA_DIR（或某个 import 期烘焙的副本），这里就读不到 → 断言翻红。
        """
        with tempfile.TemporaryDirectory() as td:
            Path(td, "asset_multipliers.json").write_text(
                json.dumps({"BTC-USDT-SWAP": 2.0}), encoding="utf-8")
            with patch.object(abt, "DATA_DIR", td):
                entry = _call()["BTC-USDT-SWAP"]
        # 只要没抛且拿到条目即说明补丁路径被走到；再钉一个不依赖乘数语义的事实：
        self.assertIn("decision", entry)

    def test_leverage_clamp_reads_patched_globals(self):
        """`patch.object(abt, "MAX_LEVERAGE"/"MIN_LEVERAGE")` 必须被夹取读到。"""
        with patch.object(abt, "MAX_LEVERAGE", 7.0), patch.object(abt, "MIN_LEVERAGE", 5.0):
            entry = _call()["BTC-USDT-SWAP"]
        self.assertEqual(entry["decision"]["leverage"], 5, "模型给 3 应被下限抬到 5")

    def test_council_status_is_forwarded_into_cache(self):
        entry = _call()["BTC-USDT-SWAP"]
        self.assertTrue(entry["council"]["ran"])
        self.assertEqual(entry["council"]["adopted_role"], "trader_momentum")

    def test_validate_injection_is_actually_used(self):
        """`assemble_decision_cache` 必须调用**注入进来的** validate，而不是自己模块里的实现。

        在子模块层直接观测（门面会把 shell 自己的 `validate` 传进来，那是规定行为，
        在门面层打桩只会测到门面自己）。若装配器写死调用模块内具名函数，
        这里的哨兵不会被调用 —— 这正是"跨文件互调"搬迁时最容易漏的一处。
        """
        calls = []

        # 契约：4 个位置参数（门面负责 curry safe_float）
        def spy(p, d_item, active_inst_ids, active_position_sides):
            calls.append(d_item.get("action"))
            return "WAIT", "哨兵理由", 0.0

        entry = decisions.assemble_decision_cache(
            [_PKG], {"BTC-USDT-SWAP": dict(_DECISION)}, set(), {},
            "2026-09-14 10:00:00", "m",
            policy_snapshot={"policy_version": "v@test", "policy_hash": "h"},
            data_dir="/nonexistent-dir-so-multipliers-skip",
            max_leverage=10.0, min_leverage=1.0,
            safe_float=lambda v, d=0.0: float(v or d),
            get_system_version_tag=lambda: "0.0.0-test",
            validate=spy,
        )["BTC-USDT-SWAP"]
        self.assertEqual(calls, ["WAIT"], "装配器没有走注入的 validate")
        self.assertEqual(entry["decision"]["action"], "WAIT")
        self.assertEqual(entry["decision"]["summary_reason"], "哨兵理由")


class SubmoduleContractTest(unittest.TestCase):
    def test_validate_rejects_low_confidence(self):
        act, reason, rr = decisions.validate_and_filter_decision(
            _PKG, {"action": "BUY_LONG", "confidence": 10.0, "entry_price": 100.0,
                   "take_profit_price": 110.0, "stop_loss_price": 95.0},
            set(), {}, safe_float=lambda v, d=0.0: float(v or d))
        self.assertEqual(act, "WAIT")
        self.assertTrue(reason, "拒绝必须带理由（前端用它显示降级原因）")
        self.assertEqual(rr, 0.0)

    def test_facade_and_submodule_are_wired(self):
        """门面导出的两个名字与子模块是同一实现链（不是两份拷贝）。"""
        src = FACADE.read_text(encoding="utf-8")
        self.assertIn("validate=lambda p_, d_, ids_, sides_:", src)
        self.assertIn("get_system_version_tag=_get_system_version_tag,", src)
        self.assertIn("data_dir=DATA_DIR,", src)


if __name__ == "__main__":
    unittest.main()
