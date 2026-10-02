"""进化复盘的心法合并与发布（`scripts/evolution/` 部件，从门面搬出）。

承载**宪法级保护**（基准心法不得被进化输出物理删除）与"发布失败即保留既有权威"逻辑 ——
见函数 docstring。
"""

from __future__ import annotations

from typing import Any, Dict, List


def apply_memory_review(*,
        change_status,
        log_msg,
        long_term_memory,
        memory_service,
        memory_snapshot,
        merge_lesson_texts,
        preserve_existing_memory,
        retired_lessons,
        total_trades):
    """合并复盘心法 → 记录停用存档 → 发布到记忆服务。

    ## 两处 in-out（都是**调用方预先初始化**的跨分支状态）

    `retired_lessons`（门面 `= []`）与 `preserve_existing_memory`（上一句
    `resolve_memory_update` 的产物）—— 它们只在 `if not preserve_existing_memory:`
    分支里被赋值，分支跳过时保持原值，块后又会被报告消费。
    **只按"段内是否赋值"判必然绑定会误判**，故一律 in-out。

    ⚠️ 2026-10：原「宪法级保护（基准心法不可被进化输出删除，遗漏即补回）」已随
    基准机制**整体拆除** —— 用户要求系统不再预设任何心法，故没有"宪法级记忆"
    这回事可言。现在只保留**停用存档**语义：模型漏述的启用条目落成
    `enabled=False` 存档（不注入、不蒸发、面板可复核恢复）。

    段体 **AST 逐字**（对拍门 `tests/extraction/test_evolution_memory_review_extraction.py`）。
    """
    if not preserve_existing_memory:
        # Safe extraction: convert potential dicts {"rule_text": "..."} to string safely
        safe_long_term = []
        for item in long_term_memory:
            if isinstance(item, dict):
                val = str(item.get("rule_text") or item.get("text") or item.get("lesson") or "").strip()
            else:
                val = str(item or "").strip()
            if val:
                safe_long_term.append(val)
        # 2026-10：只做追加与去重（原「宿主按宪法补回基准心法」已随基准机制拆除）
        safe_long_term = merge_lesson_texts(
            change_status, safe_long_term, memory_snapshot.get("lessons") or [])
        # 审计 P1-8c：被模型省略的**已学**心法不再是"静默消失"，而是停用存档；
        # 这里把条数写进日志，报告口径不再只统计基准补回。
        _already = {t.strip() for t in safe_long_term}
        _dropped = [str(l.get("rule_text") or "").strip() for l in (memory_snapshot.get("lessons") or [])
                    if l.get("enabled")
                    and str(l.get("rule_text") or "").strip() and str(l.get("rule_text") or "").strip() not in _already]
        if _dropped:
            retired_lessons = _dropped
            log_msg(f"📦 {len(_dropped)} 条既学心法本轮未被复述：已按停用存档保留（不注入提示词，可在面板复核恢复）")

        try:
            published = memory_service.publish_review(
                safe_long_term, expected_version=memory_snapshot["version"],
                sample_size=total_trades, change_status=change_status)
            preserve_existing_memory = not published
        except Exception as exc:
            preserve_existing_memory = True
            log_msg(f"Memory publication rejected; retaining authority: {exc}")
    return (preserve_existing_memory, retired_lessons)
