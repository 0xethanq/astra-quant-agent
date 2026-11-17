"""仪表盘载荷瘦身（只读、幂等）。

从 astra_backend/dashboard_cache.py 原样迁出（结构优化阶段 2 / B2 第一刀）。本函数是**纯函数**：
入参 dict 与 4 个模块级阈值常量，返回新的顶层字典，不读任何文件、不碰任何全局可变
状态，因此无需薄壳注入，门面直接重导出即可。

核心语义（搬迁时逐字保留）：省略必须**显式留痕**（`_meta.omitted`），
缺失一律不用 0 或空值代填 —— 这正是前端「UI 不说谎」的依据。
"""
from __future__ import annotations

from typing import Any

from .ledger_view import LEDGER_TRADES_MAX

__all__ = ["slim_payload", "SLIM_HISTORY_FULL_ENTRIES", "SLIM_HISTORY_DROP_KEYS",
           "SLIM_TRADES", "SLIM_LOGS"]


SLIM_HISTORY_FULL_ENTRIES = 5      # 保留最近 N 条的完整明细
SLIM_HISTORY_DROP_KEYS = ("top_opportunities", "position_management", "policy_snapshot")
#: 台账行上限 —— **与台账视图同一事实源**（`ledger_view.LEDGER_TRADES_MAX`）。
#:
#: ⚠️ 2026-09-16 修：此处原为 20，而台账视图本身的上限是 60 —— 默认瘦身把
#: 34 笔已平仓台账砍到最近 20 笔（`_meta.omitted.trades` 有留痕，但前端从不读），
#: 台账页于是少 14 行，且「累计平仓/胜率/净盈亏/手续费」全在被砍的切片上聚合。
#: 瘦身**不得比视图本身更紧**，否则台账页必然少数据；实测代价：34 行 16.4KB vs
#: 20 行 9.6KB（+6.8KB / 瘦身载荷 233.8KB 的 +2.9%），换来台账页零截断。
#: 若台账真超过本上限（>60 笔），`_meta.omitted.trades` 仍会留痕，前端据此显式提示。
SLIM_TRADES = LEDGER_TRADES_MAX
SLIM_LOGS = 20


def slim_payload(data: dict[str, Any]) -> dict[str, Any]:
    """对缓存快照做只读瘦身：不改动 CACHE_DATA 本身，返回新的顶层字典。"""
    out = dict(data)
    # 幂等：若传入的已是瘦身载荷（例如被二次缓存），必须**保留**上一轮的省略记录——
    # 否则省略留痕会消失，前端会把被裁过的数据当完整数据渲染（正是本项要防的"UI 说谎"）。
    prior_meta = out.get("_meta") if isinstance(out.get("_meta"), dict) else {}
    omitted: dict[str, Any] = dict(prior_meta.get("omitted") or {})

    history = out.get("ai_brain_history")
    if isinstance(history, list) and len(history) > SLIM_HISTORY_FULL_ENTRIES:
        trimmed_rows = 0
        slimmed: list[Any] = []
        for index, entry in enumerate(history):
            if index < SLIM_HISTORY_FULL_ENTRIES or not isinstance(entry, dict):
                slimmed.append(entry)
                continue
            row = dict(entry)
            dropped = [key for key in SLIM_HISTORY_DROP_KEYS if key in row]
            for key in dropped:
                row.pop(key, None)
            if dropped:
                # 显式标记"本条被裁成摘要"，前端据此渲染提示，绝不假装明细为空
                row["_trimmed"] = dropped
                trimmed_rows += 1
            slimmed.append(row)
        # 行内整段提示词与顶层 ai_last_prompt 同文时只保留"字数 + 省略标记"：
        # 顶层那份仍完整（白盒承诺），此处避免同段 3.6 万字符文本再发一遍。
        top_prompt = str(out.get("ai_last_prompt") or "")
        elided_prompts = 0
        if top_prompt:
            for row in slimmed:
                if not isinstance(row, dict):
                    continue
                text = str(row.get("ai_last_prompt") or "")
                if len(text) < 2000 or text[:200] != top_prompt[:200]:
                    continue   # 短存根（210 字）与不同文的历史提示词原样保留
                row.pop("ai_last_prompt", None)
                row["ai_last_prompt_chars"] = len(text)
                row["ai_last_prompt_elided"] = True
                row["ai_last_prompt_ref"] = "top_level"
                elided_prompts += 1
        out["ai_brain_history"] = slimmed
        if elided_prompts:
            omitted["ai_brain_history.prompt_text"] = {
                "entries": elided_prompts,
                "reason": "与顶层 ai_last_prompt 同文，避免重复下发整段提示词",
                "ref": "ai_last_prompt",
            }
        if trimmed_rows:
            omitted["ai_brain_history"] = {
                "kept_full": SLIM_HISTORY_FULL_ENTRIES,
                "total": len(history),
                "trimmed_entries": trimmed_rows,
                "dropped_fields": list(SLIM_HISTORY_DROP_KEYS),
                "full": "/api/v1/cache/brain-history",
            }

    review = out.get("review")
    if isinstance(review, dict) and review.get("ai_last_prompt"):
        top_prompt = str(out.get("ai_last_prompt") or "")
        review_prompt = str(review.get("ai_last_prompt") or "")
        if top_prompt and review_prompt[:200] == top_prompt[:200]:
            review = dict(review)
            review.pop("ai_last_prompt", None)
            review["ai_last_prompt_chars"] = len(review_prompt)
            review["ai_last_prompt_ref"] = "top_level"
            out["review"] = review
            omitted["review.ai_last_prompt"] = {
                "chars": len(review_prompt),
                "reason": "与顶层 ai_last_prompt 同文，避免同段提示词重复下发",
                "ref": "ai_last_prompt",
            }

    trades = out.get("trades")
    if isinstance(trades, list) and len(trades) > SLIM_TRADES:
        out["trades"] = trades[-SLIM_TRADES:]
        omitted["trades"] = {"kept": SLIM_TRADES, "total": len(trades), "full": "/api/v1/cache/ledger"}

    logs = out.get("logs")
    if isinstance(logs, list) and len(logs) > SLIM_LOGS:
        out["logs"] = logs[-SLIM_LOGS:]
        omitted["logs"] = {"kept": SLIM_LOGS, "total": len(logs)}

    meta = dict(out.get("_meta") or {})
    meta.update({
        "slim": True,
        "full_payload": "/api/all?full=1",
        "omitted": omitted,
        "note": "省略项均已显式留痕；缺失一律不用 0 或空值代填",
    })
    out["_meta"] = meta
    return out
