"""`/api/all` 载荷瘦身的契约测试（审计「未完成清单」#1）。

背景：一次 `/api/all` 实测 30 万字符量级——`ai_brain_history` 25 条里每条都带
`top_opportunities`/`position_management`/`policy_snapshot`（约 5.6KB/条），
`review.ai_last_prompt` 与顶层 `ai_last_prompt` 是同一段 3.6 万字符提示词的拷贝，
`trades`/`logs` 又是明细页专用端点的重复。移动端与弱网下首屏因此明显卡顿。

瘦身的三条硬约束（本文件钉住）：
1. **形状稳定**：顶层键只增不减（新增 `_meta`），前端不会因子段消失而崩；
2. **省略留痕**：每一处省略都必须出现在 `_meta.omitted` 或该条的 `_trimmed` 里，
   缺失不得被渲染成 0/空（"缺失≠0"红线）；
3. **可回退**：`?full=1` 必须与瘦身前逐字节一致，缓存本身不得被就地修改。
"""
from __future__ import annotations

import copy
import json
import unittest

from astra_backend.dashboard_cache import (
    SLIM_HISTORY_DROP_KEYS,
    SLIM_HISTORY_FULL_ENTRIES,
    SLIM_LOGS,
    SLIM_TRADES,
    slim_payload,
)
from astra_backend.dashboard_payload.ledger_view import LEDGER_TRADES_MAX

#: 台账夹具必须**多于**瘦身上限，否则「截断并留痕」这条契约根本不会触发。
_TRADES_TOTAL = SLIM_TRADES + 11


def _entry(index: int, prompt: str = "") -> dict:
    row = {
        "time": f"2026-09-14 0{index % 10}:00:00",
        "macro_assessment": f"宏观 {index}",
        "policy_version": "v7.9.1",
        "policy_hash": f"hash{index}",
        "council_status": {"ran": True},
        "policy_snapshot_summary": f"摘要 {index}",
        "policy_snapshot": {"prompt_sections": "x" * 1400},
        "top_opportunities": [{"instId": "BTC-USDT-SWAP", "why": "y" * 80} for _ in range(6)],
        "position_management": [{"instId": "ETH-USDT-SWAP", "action": "HOLD"}] * 5,
    }
    if prompt:
        row["ai_last_prompt"] = prompt
    return row


def _payload() -> dict:
    prompt = "系" * 5000
    return {
        "timestamp": "2026-09-14 03:30:00",
        "ai_last_prompt": prompt,
        "review": {"timestamp": "2026-09-14 03:00:00", "ai_last_prompt": prompt, "insights": ["a"]},
        "ai_brain_history": [_entry(0, prompt)] + [_entry(i, "短" * 210) for i in range(1, 25)],
        "trades": [{"id": i} for i in range(_TRADES_TOTAL)],
        "logs": [f"line {i}" for i in range(60)],
        "factors": [{"name": "f"}],
        "account": {"avail_eq": 1.0},
    }


class SlimShapeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.full = _payload()
        self.slim = slim_payload(self.full)

    def test_top_level_keys_only_grow(self):
        extra = set(self.slim) - set(self.full)
        self.assertEqual(extra, {"_meta"}, "瘦身只允许新增 _meta，不得增删业务键")
        self.assertEqual(set(self.full) - set(self.slim), set(), "瘦身不得删掉任何顶层键")

    def test_full_payload_is_untouched(self):
        """瘦身必须是纯函数：缓存对象本身保持完整（否则 ?full=1 也拿不到全量）。"""
        self.assertEqual(len(self.full["ai_brain_history"]), 25)
        self.assertIn("ai_last_prompt", self.full["review"])
        self.assertEqual(len(self.full["trades"]), _TRADES_TOTAL)

    def test_meta_documents_every_omission(self):
        omitted = self.slim["_meta"]["omitted"]
        self.assertTrue(self.slim["_meta"]["slim"])
        self.assertEqual(self.slim["_meta"]["full_payload"], "/api/all?full=1")
        for key in ("ai_brain_history", "review.ai_last_prompt", "trades", "logs"):
            self.assertIn(key, omitted, f"{key} 被省略却没有留痕")

    def test_history_trimming_is_marked_per_entry(self):
        history = self.slim["ai_brain_history"]
        self.assertEqual(len(history), 25, "时间线行数必须保持（否则前端时间线会缺行）")
        for index, row in enumerate(history):
            if index < SLIM_HISTORY_FULL_ENTRIES:
                self.assertNotIn("_trimmed", row, "近期条目必须完整")
                for key in SLIM_HISTORY_DROP_KEYS:
                    self.assertIn(key, row)
            else:
                self.assertEqual(row.get("_trimmed"), list(SLIM_HISTORY_DROP_KEYS),
                                 "被裁条目必须逐项声明裁掉了什么")
                for key in SLIM_HISTORY_DROP_KEYS:
                    self.assertNotIn(key, row)
                self.assertIn("macro_assessment", row, "摘要仍需保留行内可读的上下文")

    def test_review_prompt_is_referenced_not_silently_dropped(self):
        review = self.slim["review"]
        self.assertNotIn("ai_last_prompt", review)
        self.assertEqual(review["ai_last_prompt_chars"], len(self.full["review"]["ai_last_prompt"]))
        self.assertEqual(review["ai_last_prompt_ref"], "top_level")
        self.assertTrue(self.slim["ai_last_prompt"], "顶层完整提示词必须保留（白盒承诺）")

    def test_review_prompt_kept_when_texts_differ(self):
        payload = _payload()
        payload["review"]["ai_last_prompt"] = "另一段完全不同的提示词" * 100
        slim = slim_payload(payload)
        self.assertIn("ai_last_prompt", slim["review"], "不同文的提示词不得当成重复省略")

    def test_lists_are_capped_and_marked(self):
        self.assertEqual(len(self.slim["trades"]), SLIM_TRADES)
        self.assertEqual(len(self.slim["logs"]), SLIM_LOGS)
        self.assertEqual(self.slim["_meta"]["omitted"]["trades"]["total"], _TRADES_TOTAL)
        self.assertEqual(self.slim["_meta"]["omitted"]["logs"]["total"], 60)
        # 保留的是**最新**的尾巴，不是最早的
        self.assertEqual(self.slim["trades"][-1], {"id": _TRADES_TOTAL - 1})
        self.assertEqual(self.slim["logs"][-1], "line 59")

    def test_slim_cap_never_undercuts_the_ledger_view_cap(self):
        """2026-09-16 台账少行事故的不变量：瘦身不得比台账视图本身更紧。

        `SLIM_TRADES` 曾写死 20，而台账视图上限是 60 ⇒ `/api/all` 默认把 34 笔
        已平仓台账砍到最近 20 笔，台账页少 14 行、且「累计平仓/胜率/净盈亏」
        全在被砍切片上聚合。两处上限必须同源。
        """
        self.assertGreaterEqual(
            SLIM_TRADES, LEDGER_TRADES_MAX,
            "瘦身上限比台账视图上限更紧：台账页必然少行（UI 说谎）")

    def test_unrelated_sections_untouched(self):
        for key in ("factors", "account", "timestamp"):
            self.assertEqual(self.slim[key], self.full[key])

    def test_payload_shrinks_materially_and_stays_json(self):
        before = len(json.dumps(self.full, ensure_ascii=False))
        after = len(json.dumps(self.slim, ensure_ascii=False))
        self.assertLess(after, before * 0.75, f"瘦身效果不足: {before} → {after}")
        json.loads(json.dumps(self.slim, ensure_ascii=False))  # 必须可序列化

    def test_short_lists_are_left_alone(self):
        payload = _payload()
        payload["trades"] = payload["trades"][:3]
        payload["logs"] = payload["logs"][:2]
        payload["ai_brain_history"] = payload["ai_brain_history"][:2]
        slim = slim_payload(payload)
        self.assertEqual(slim["trades"], payload["trades"])
        self.assertEqual(slim["logs"], payload["logs"])
        self.assertNotIn("ai_brain_history", slim["_meta"]["omitted"])
        self.assertNotIn("trades", slim["_meta"]["omitted"])

    def test_missing_sections_do_not_crash(self):
        for payload in ({}, {"ai_brain_history": None}, {"review": []}, {"trades": "x"}):
            slim_payload(payload)  # 不抛异常即可

    def test_idempotent(self):
        once = slim_payload(copy.deepcopy(self.full))
        twice = slim_payload(slim_payload(copy.deepcopy(self.full)))
        self.assertEqual(json.dumps(once, ensure_ascii=False), json.dumps(twice, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
