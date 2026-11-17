"""自进化**报告载荷**的形状（从 `self_improvement_engine.run_self_evolution` 搬出）。

这段 20 行的字典字面量是**与前端/看板之间的契约**：键名即前端读取的字段。
原先埋在 154 行编排函数的中后段（前后是落盘与通知），改动它没有任何提示；
独立成函数后，门可以把**键集精确钉住**，新人删/改字段时会立刻被拦下。

几处**不是"看起来那样"的字段**（原样保留，勿"优化"）：

- `insights` 与 `diagnosis_insights` **是同一个列表**（历史字段名并存，前端两者都在读）；
- `retired_count` = `len(retired_lessons)` —— 是**计数快照**，不是明细；
- `memory_preserved` 直接取 `preserve_existing_memory`（不是"是否保留"的再判断）；
- `llm_error` 把 `__llm_error__` 转成字符串，缺省 `""`（前端据此显示上游失败，而非静默 NO_CHANGE）；
- `mode` 是固定文案（启发式长期记忆模式）。

2026-10：`baseline_memory_protected` 键与 `constitution_readded` 入参**随基准机制整体拆除**
（用户要求系统不再预设任何心法 ⇒ 没有"宪法级补回"这回事可言），故本函数
13 入参 / 20 键。

零副作用、零模块全局读取：全部依赖由调用方注入。
"""


def _pct(numerator, denominator) -> float:
    """百分比（分母 0 ⇒ 0.0；分子大于分母时**封顶 100**）。

    封顶不是多余的：`snapshot_audit` 来自旁车/历史载荷，一旦计数自相矛盾
    （分子 > 分母），前端会显示"覆盖率 250%"这种自毁可信度的数字。
    宁可封顶到一个诚实的 100%，也不让页面出现不可能的读数。
    """
    try:
        denominator = int(denominator or 0)
        if denominator <= 0:
            return 0.0
        ratio = int(numerator or 0) / denominator * 100.0
        return round(min(ratio, 100.0), 1)
    except (TypeError, ValueError):
        return 0.0


def derive_evidence_coverage(snapshot_audit) -> tuple:
    """从 `snapshot_audit` 派生**证据链健康度**（纯函数，零入参变更）。

    返回 `(entry_coverage_pct, exit_coverage_pct, gap_reasons)`。

    为什么"派生"而不是新增入参：`build_evolution_report` 的 **14 个 kw-only 入参**
    被 `tests/extraction/test_evolution_report_extraction.py` 逐项钉住（调用点必须
    同名传参），加参数等于把那一刀的重构门一起改掉。而 `snapshot_audit` 本来就在
    入参里、本来就携带这些计数 —— 故在函数内派生，门禁与契约两全。

    两把尺子：

    - **开仓侧**：平仓行里**真正可观测**（含 7 梯队因子，即 `DYNAMICS_OBSERVED` /
      `PARTIAL`）的比例 —— 复盘能否回答"当时现场如何"；
    - **离场侧**：离场原因来自**机制确认**的比例 —— 复盘能否回答"为什么离场"。

    ## ⚠️ 为什么开仓侧不数"有快照的行数"

    实测：`entry_snapshot_present` 已经是 **39/39（100%）**，可同一批行的
    `DYNAMICS_OBSERVED` 仍是 **0/39** —— 因为那些快照是**旧格式**（只有价格类观测，
    18 个梯队因子一个都没有）。若拿"快照非空"当覆盖率，报告头一行就会写
    "开仓现场覆盖 100%"，而复盘实际**一个梯队因子都读不到** —— 这个指标恰好会
    掩盖它本该暴露的缺口（用户的原话就是"很多数据没在台账里面"）。

    故开仓侧一律以**梯队因子可观测率**为准，并把"有快照但无因子"单独说成一条缺口。

    2026-10 改造前的实测值：两者都是 **0%** —— 82 笔平仓行既无梯队因子，
    出场原因又有 41% 是"止盈推定"猜出来的。
    """
    audit = snapshot_audit if isinstance(snapshot_audit, dict) else {}
    total = int(audit.get("total") or 0)
    present = int(audit.get("entry_snapshot_present") or 0)
    observable = int(audit.get("math_observable") or 0)
    exit_mechanism = int(audit.get("exit_mechanism") or 0)
    exit_inferred = int(audit.get("exit_inferred") or 0)
    exit_unlabeled = int(audit.get("exit_unlabeled") or 0)

    gaps = []
    if total <= 0:
        gaps.append("暂无平仓样本：证据链健康度不可评估")
    else:
        if observable == 0:
            if present:
                gaps.append(f"梯队因子可观测 0/{total}：快照虽非空但只有价格类观测，"
                            "18 个梯队因子一个都读不到（旧格式快照）")
            else:
                gaps.append(f"梯队因子可观测 0/{total}：平仓行完全没有开仓现场快照，"
                            "逐标的/逐因子归因只能靠价格")
        elif observable < total:
            gaps.append(f"梯队因子可观测 {observable}/{total}：仍有行缺现场，追赶期数据不齐")
        if exit_unlabeled:
            gaps.append(f"离场原因未标记 {exit_unlabeled}/{total}：属证据链改造前的历史行，"
                        "只能读 `exit_reason` 散文")
        if exit_inferred:
            gaps.append(f"离场原因属**推断** {exit_inferred}/{total}"
                        "（交易所侧 clOrdId/金额启发式）：不可当作机制事实引用")
        if exit_mechanism == 0 and (exit_inferred or exit_unlabeled):
            gaps.append("尚无一行离场原因来自**机制确认**：离场质量分析（回吐/效率）暂不可信")

    return _pct(observable, total), _pct(exit_mechanism, total), gaps


def build_evolution_report(*,
        actions_taken,
        change_status,
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
        "llm_error": str(llm_review.get("__llm_error__") or ""),
    }
    # ── 证据链健康度（2026-10，方向 1）─────────────────────────────────────
    # 由 `snapshot_audit` 内部派生 ⇒ **不改 14 入参契约**（见 `derive_evidence_coverage`）。
    # 三个键让"台账缺什么"在前端与报告里直接可读：开仓侧覆盖率、离场侧机制确认率、
    # 以及人类可读的缺口清单。改造前两者均为 0%。
    _entry_cov, _exit_cov, _gaps = derive_evidence_coverage(snapshot_audit)
    report_payload["evidence_coverage_pct"] = _entry_cov
    report_payload["exit_cause_coverage_pct"] = _exit_cov
    report_payload["evidence_gap_reasons"] = _gaps
    return report_payload
