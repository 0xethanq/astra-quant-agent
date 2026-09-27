"""B3（主脑侧第四块）`scripts/brain/cycle_parts.py` 的抽取回归。

## 这个测试在守什么

`execute_batch_ai_brain_cycle`（350 行）是主脑最后的巨型函数，整体是 I/O 编排、
不适合搬迁；但内部有三段**纯组装**被提出来：

| 函数 | 原门面位置 |
|---|---|
| `normalize_position_management` | 33 行内联循环（AI 持仓指令白名单归一） |
| `build_effective_prompt_text` | 2 处内联 f-string（提示词全文） |
| `build_history_record` | 28 行内联字典（Web 审计历史） |

其中两条最容易出错、也最难靠"全量绿"发现的地方，本文件专门钉住：

1. **`normalize_position_management` 的安全语义**：模型漏答的在途持仓必须被补成
   安全 `HOLD`（漏一条 = 该仓位无人看管）；`suggested_sl_price` **只在
   `UPDATE_SL` 时保留**（否则模型能在 HOLD 上夹带止损价）。
2. **`build_effective_prompt_text` 的字节形状**：两处调用点的格式**原本就不完全一样**
   —— 历史记录那处标签带 `(policy_version)`，提示词快照那处无版本标签。
   把它俩统一成一个函数时极易顺手改掉其中一处的格式，而这两段文本会进
   「最近提示词」快照与决策历史，属于线上可查证据。
   本测试用**搬走前 f-string 的逐字副本**做逐字节对拍。
"""
from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

import scripts.ai_brain_trader as abt
from scripts.brain import cycle_parts

ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "scripts" / "ai_brain_trader.py"


def _safe_float(v, d=0.0):
    try:
        return float(v or d)
    except (TypeError, ValueError):
        return d


class NormalizePositionManagementTest(unittest.TestCase):
    def _norm(self, items, active):
        return cycle_parts.normalize_position_management(
            items, active, safe_float=_safe_float)

    def test_missing_positions_are_filled_with_safe_hold(self):
        """模型漏答的在途持仓必须补 HOLD —— 漏一条就是该仓位无人看管。"""
        got = self._norm([], {"BTC-USDT-SWAP", "ETH-USDT-SWAP"})
        self.assertEqual([g["instId"] for g in got], ["BTC-USDT-SWAP", "ETH-USDT-SWAP"])
        for g in got:
            self.assertEqual(g["action"], "HOLD")
            self.assertEqual(g["suggested_sl_price"], 0.0)
            self.assertEqual(g["confidence"], 0.0)

    def test_unknown_inst_ids_are_dropped(self):
        got = self._norm([{"instId": "DOGE-USDT-SWAP", "action": "CLOSE_MARKET"}],
                         {"BTC-USDT-SWAP"})
        self.assertEqual([g["instId"] for g in got], ["BTC-USDT-SWAP"])  # 只补 HOLD

    def test_action_whitelist_degrades_to_hold(self):
        got = self._norm([{"instId": "B", "action": "SELL_SHORT"}], {"B"})
        self.assertEqual(got[0]["action"], "HOLD")

    def test_suggested_sl_only_kept_for_update_sl(self):
        """`suggested_sl_price` 只在 UPDATE_SL 时保留 —— 否则模型能在 HOLD 上夹带止损价。"""
        got = self._norm([
            {"instId": "B", "action": "HOLD", "suggested_sl_price": 123.0},
            {"instId": "E", "action": "CLOSE_MARKET", "suggested_sl_price": 9.0},
        ], {"B", "E"})
        by_id = {g["instId"]: g for g in got}
        self.assertEqual(by_id["B"]["suggested_sl_price"], 0.0)
        self.assertEqual(by_id["E"]["suggested_sl_price"], 0.0)

        kept = self._norm([{"instId": "B", "action": "UPDATE_SL", "suggested_sl_price": 123.0}],
                          {"B"})
        self.assertEqual(kept[0]["suggested_sl_price"], 123.0)

    def test_duplicate_first_wins(self):
        got = self._norm([
            {"instId": "B", "action": "CLOSE_MARKET", "confidence": 90},
            {"instId": "B", "action": "HOLD", "confidence": 10},
        ], {"B"})
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["action"], "CLOSE_MARKET")

    def test_confidence_is_clamped(self):
        got = self._norm([{"instId": "B", "action": "HOLD", "confidence": 999}], {"B"})
        self.assertEqual(got[0]["confidence"], 100.0)
        got = self._norm([{"instId": "B", "action": "HOLD", "confidence": -5}], {"B"})
        self.assertEqual(got[0]["confidence"], 0.0)

    def test_reason_truncated_and_defaulted(self):
        got = self._norm([{"instId": "B", "action": "HOLD", "reason": "x" * 500}], {"B"})
        self.assertEqual(len(got[0]["reason"]), 120)
        got = self._norm([{"instId": "B", "action": "HOLD"}], {"B"})
        self.assertEqual(got[0]["reason"], "模型未提供持仓理由")

    def test_non_dict_and_non_list_inputs_are_tolerated(self):
        self.assertEqual([g["instId"] for g in self._norm("nope", {"B"})], ["B"])
        got = self._norm([None, 1, "x", {"instId": "B", "action": "HOLD"}], {"B"})
        self.assertEqual(len(got), 1)


class BuildEffectivePromptTextTest(unittest.TestCase):
    """与搬走前门面 f-string 的逐字副本做**逐字节**对拍。"""

    ESP, PROMPT, TIME = "  SYS  \n", "  用户正文 \n", "2026-09-14 10:00:00"

    def test_snapshot_variant_has_no_version_label(self):
        """提示词快照那处**历史上就没有**版本标签，且分隔线前少一个空格。

        这条专门防止"为统一而顺手改格式"：两处文本都会进线上可查证据
        （最近提示词快照 / 决策历史），格式变化必须是有意的。
        """
        legacy = (f"【SYSTEM PROMPT】：\n{self.ESP.strip()}"
                  f"\n\n{'='*70}\n【USER PROMPT ({self.TIME})】：\n{self.PROMPT.strip()}")
        got = cycle_parts.build_effective_prompt_text(
            effective_system_prompt=self.ESP, policy_version="",
            time_str=self.TIME, prompt=self.PROMPT)
        self.assertEqual(got, legacy)
        self.assertNotIn("SYSTEM PROMPT ()", got)


class BuildHistoryRecordTest(unittest.TestCase):
    PKG = [{"instId": "B", "name": "BTC"}]
    CACHE = {"B": {"decision": {"action": "BUY_LONG", "confidence": 88.0, "leverage": 5,
                                "margin_usdt": 42.0, "risk_reward_ratio": 2.5,
                                "summary_reason": "因为"}, "data_quality": "valid",
                   "council": {"adopted_role": "trader_momentum"}}}

    def _build(self, **over):
        kw = dict(time_str="T", policy_version="v1", policy_hash="h", policy_snapshot={"a": 1},
                  policy_summary="s", macro_summary="m", council_status={"ran": True},
                  ai_last_prompt="P", pos_mgmt_list=[{"instId": "B"}],
                  council_transcript=None, packages=self.PKG, standard_cache=self.CACHE)
        kw.update(over)
        return cycle_parts.build_history_record(**kw)

    def test_contract_fields_and_opportunity_projection(self):
        rec = self._build()
        for k in ("time", "policy_version", "policy_hash", "policy_snapshot",
                  "policy_snapshot_summary", "macro_assessment", "council_status",
                  "ai_last_prompt", "position_management", "council_transcript",
                  "top_opportunities"):
            self.assertIn(k, rec)
        self.assertEqual(len(rec["top_opportunities"]), 1)
        top = rec["top_opportunities"][0]
        self.assertEqual(top["inst"], "BTC")
        self.assertEqual(top["action"], "BUY_LONG")
        self.assertEqual(top["leverage"], 5)
        self.assertEqual(top["council_adopted"], "trader_momentum")
        self.assertEqual(top["policy_version"], "v1")
        self.assertEqual(top["risk_reward_ratio"], 2.5)

    def test_leverage_and_margin_defaults_preserved(self):
        cache = {"B": {"decision": {"action": "WAIT", "confidence": 10.0,
                                    "risk_reward_ratio": 0.0, "summary_reason": "r"},
                       "data_quality": "invalid"}}
        top = self._build(standard_cache=cache)["top_opportunities"][0]
        self.assertEqual(top["leverage"], 3)
        self.assertEqual(top["margin_usdt"], 0.0)
        self.assertIsNone(top["council_adopted"])

    def test_missing_required_cache_key_raises(self):
        """`action`/`risk_reward_ratio` 缺键必须抛 —— 静默填默认值会让审计失真。"""
        bad = {"B": {"decision": {"confidence": 1.0}, "data_quality": "x"}}
        with self.assertRaises(KeyError):
            self._build(standard_cache=bad)


class NormalizePositionManagementParityTest(unittest.TestCase):
    """与搬走前的门面内联实现做**随机差分**（不只是逐条边界）。"""

    @staticmethod
    def _legacy(pos_mgmt_list, active_inst_ids, safe_float):
        """搬走前门面里的内联循环（逐字原样）。"""
        validated_pos_mgmt = []
        seen_positions = set()
        for item in pos_mgmt_list:
            if not isinstance(item, dict):
                continue
            inst_id = str(item.get("instId", ""))
            if inst_id not in active_inst_ids or inst_id in seen_positions:
                continue
            seen_positions.add(inst_id)
            action = str(item.get("action", "HOLD")).upper()
            if action not in {"HOLD", "CLOSE_MARKET", "UPDATE_SL"}:
                action = "HOLD"
            confidence = max(0.0, min(100.0, safe_float(item.get("confidence"))))
            suggested_sl = safe_float(item.get("suggested_sl_price"))
            if action != "UPDATE_SL":
                suggested_sl = 0.0
            validated_pos_mgmt.append({
                "instId": inst_id,
                "action": action,
                "suggested_sl_price": suggested_sl,
                "confidence": confidence,
                "reason": str(item.get("reason", "模型未提供持仓理由"))[:120]
            })

        for inst_id in sorted(active_inst_ids - seen_positions):
            validated_pos_mgmt.append({
                "instId": inst_id,
                "action": "HOLD",
                "suggested_sl_price": 0.0,
                "confidence": 0.0,
                "reason": "模型遗漏该持仓，安全降级为 HOLD"
            })
        return validated_pos_mgmt

    def test_random_parity(self):
        import random
        rng = random.Random(20260919)
        universe = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "SOL-USDT-SWAP", "DOGE-USDT-SWAP", ""]
        actions = ["HOLD", "CLOSE_MARKET", "UPDATE_SL", "BUY_LONG", "hold", "junk", ""]
        for _ in range(5000):
            active = set(rng.sample(universe, rng.randint(0, 3)))
            items = []
            for _ in range(rng.randint(0, 5)):
                if rng.random() < 0.15:
                    items.append(rng.choice([None, 1, "x", [1]]))
                    continue
                items.append({
                    "instId": rng.choice(universe),
                    "action": rng.choice(actions),
                    "confidence": rng.choice([None, 0, 50, 99.5, 100, 150, -3, "abc", "77"]),
                    "suggested_sl_price": rng.choice([None, 0, 12.5, -1, "9"]),
                    "reason": rng.choice([None, "", "r" * 200, "正常理由", 123]),
                })
            got = cycle_parts.normalize_position_management(items, active, safe_float=_safe_float)
            expected = self._legacy(items, active, _safe_float)
            self.assertEqual(got, expected, f"分叉:\nitems={items}\nactive={active}")

    def test_non_list_parity(self):
        for bad in (None, "x", 3, {"a": 1}, (1, 2)):
            got = cycle_parts.normalize_position_management(bad, {"B"}, safe_float=_safe_float)
            expected = self._legacy(bad if isinstance(bad, list) else [], {"B"}, _safe_float)
            self.assertEqual(got, expected)


class FacadeWiringTest(unittest.TestCase):
    def test_facade_delegates_and_has_no_inline_copies(self):
        # 第九十八刀：三个 helper 的**调用点**随"派发+落盘"尾块迁入
        # `scripts/brain/dispatch.py`（原意不变：必须仍被调用，内联实现不得复活）
        disp = (ROOT / "scripts" / "brain" / "dispatch.py").read_text(encoding="utf-8")
        for call in ("_normalize_position_management(", "_build_effective_prompt_text(",
                     "_build_history_record("):
            self.assertIn(call, disp, f"派发模块未调用 {call}")
        src = FACADE.read_text(encoding="utf-8")
        # 反向哨：内联实现不得复活（门面与派发模块都查）
        for text in (src, disp):
            self.assertNotIn("validated_pos_mgmt = []", text)
            self.assertNotIn('"top_opportunities": [', text)
            self.assertNotIn("模型遗漏该持仓，安全降级为 HOLD", text)

    def test_safe_float_is_injected_at_call_time(self):
        """`safe_float` 是门面私有函数，必须调用期注入（否则门面重载后会失配）。"""
        src = FACADE.read_text(encoding="utf-8")
        self.assertIn("safe_float=safe_float)", src)

    def test_snapshot_call_site_uses_empty_policy_version(self):
        """两处调用点的**标签差异**必须留在调用点，且快照那处传 `policy_version=""`。

        这是本块唯一无法靠"helper 对拍"守住的点：helper 与调用点的分工是
        「helper 管排版、调用点管是否带版本标签」。若有人把快照那处改成传真实
        版本号（或反过来给历史记录传空串），helper 级测试照样全绿，
        但线上「最近提示词快照」的格式就变了。下钉这两条。

        另钉反向哨：不得用 `.replace(...)` 在外面补格式 —— 那会把格式知识
        散回调用点（本块第一版就是这么写的，属于自己踩过的坑）。
        """
        # 第九十九刀：快照调用点随"本地快照落盘"块迁入 brain/snapshots.py；
        # 历史记录调用点随派发尾块迁入 brain/dispatch.py（判定对象随实现迁移）
        snap = (ROOT / "scripts" / "brain" / "snapshots.py").read_text(encoding="utf-8")
        self.assertIn('effective_system_prompt=effective_system_prompt, policy_version="",', snap,
                      "快照写入必须传 policy_version 空串")
        disp = (ROOT / "scripts" / "brain" / "dispatch.py").read_text(encoding="utf-8")
        self.assertIn("policy_version=policy_version,", disp,
                      "历史记录必须传真实 policy_version")
        src = FACADE.read_text(encoding="utf-8")
        self.assertNotIn('effective_system_prompt=effective_system_prompt, policy_version="",',
                         src, "门面不得残留该调用点（残留=孪生）")
        self.assertNotIn('replace("【SYSTEM PROMPT ()】："', src)


if __name__ == "__main__":
    unittest.main()
