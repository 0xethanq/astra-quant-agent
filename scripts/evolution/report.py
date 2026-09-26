"""自进化**报告载荷**的形状（从 `self_improvement_engine.run_self_evolution` 搬出）。

这段 20 行的字典字面量是**与前端/看板之间的契约**：键名即前端读取的字段。
原先埋在 154 行编排函数的中后段（前后是落盘与通知），改动它没有任何提示；
独立成函数后，门可以把**键集精确钉住**，新人删/改字段时会立刻被拦下。

几处**不是"看起来那样"的字段**（原样保留，勿"优化"）：

- `insights` 与 `diagnosis_insights` **是同一个列表**（历史字段名并存，前端两者都在读）；
- `retired_count` = `len(retired_lessons)`、`baseline_memory_protected` = `len(constitution_readded)`
  —— 是**计数快照**，不是明细；
- `memory_preserved` 直接取 `preserve_existing_memory`（不是"是否保留"的再判断）；
- `llm_error` 把 `__llm_error__` 转成字符串，缺省 `""`（前端据此显示上游失败，而非静默 NO_CHANGE）；
- `mode` 是固定文案（启发式长期记忆模式）。

零副作用、零模块全局读取：全部依赖由调用方注入。
"""
def build_evolution_report(*,
        actions_taken,
        change_status,
        constitution_readded,
        insights,
        ledger_revision,
        llm_review,
        long_term_memory,
        preserve_existing_memory,
        profit_factor,
        retired_lessons,
        snapshot_audit,
        timestamp_str,
        total_trades,
        win_rate):
    report_payload = {
        "timestamp": timestamp_str,
        "ledger_revision": ledger_revision,
        "total_trades": total_trades,
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "mode": "ASTRA Native Heuristic Memory (启发式长期记忆)",
        "change_status": change_status,
        "retired_lessons": retired_lessons,
        "retired_count": len(retired_lessons),
        "memory_preserved": preserve_existing_memory,
        "insights": insights,
        "diagnosis_insights": insights,
        "memory_overwrites_reason": llm_review.get("memory_overwrites_reason", ""),
        "actions_taken": actions_taken,
        "core_lessons": long_term_memory,
        "snapshot_audit": snapshot_audit,
        "baseline_memory_protected": len(constitution_readded),
        "llm_error": str(llm_review.get("__llm_error__") or ""),
    }
    return report_payload
