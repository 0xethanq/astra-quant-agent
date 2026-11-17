"""主脑周期内的纯组装助手（B3 抽取第四块）。

从 `scripts/ai_brain_trader.py::execute_batch_ai_brain_cycle`（原 350 行）里
把**两段纯组装**提出来 —— 这个大函数剩下的部分本质是 I/O 编排，不适合整体搬迁，
但内部这两段是"给输入就出确定结果"的，值得独立并可单测：

| 函数 | 作用 |
|---|---|
| `normalize_position_management` | AI 持仓指令的**白名单归一**（原门面 33 行内联） |
| `build_history_record` | Web 审计历史记录的载荷装配（原门面 28 行内联字典） |
| `build_effective_prompt_text` | "SYSTEM + 分隔线 + USER" 全文（原门面 2 处内联 f-string） |

## 为什么这三块安全

- **纯函数**：入参全是普通数据，出参是 list / dict / str，不读模块状态、不做 I/O；
- **只有一个注入依赖** `safe_float`（定义在门面自身，且门面会被
  `pin_baseline_risk_env()` 原地重载，故必须调用期注入）；
- 三者都不在任何测试的源码锚点、`split("def ")` 结构断言、`ast.parse(单文件)`
  节点抽取或 `inspect.getsource` 目标里（已逐条 grep 核对）。

## `normalize_position_management` 的语义（照搬，不得放宽）

1. 非 dict 项直接丢弃；
2. `instId` 必须**在白名单 `active_inst_ids` 里**，且**同标的只取第一条**；
3. `action` 只允许 `HOLD` / `CLOSE_MARKET` / `UPDATE_SL` / `UPDATE_TP`，其余一律降级 `HOLD`；
4. `confidence` 夹到 `[0, 100]`；
5. `suggested_sl_price` **仅在 `UPDATE_SL` 时才保留**，其余强制 `0.0`；
   `suggested_tp1_price` / `suggested_tp2_price` **仅在 `UPDATE_TP` 时才保留**，
   其余强制 `0.0`（防止模型在 HOLD/CLOSE 上夹带价位）；
   两者**互斥**：各自动作不匹配就清零 —— "既改止损又改止盈"要模型分两条指令表达，
   执行层才能对每一处变更分别做几何校验与留痕；
6. `reason` 截断到 120 字符；
7. **模型遗漏的持仓**按 `sorted()` 补一条安全 `HOLD`（顺序确定，便于审计对拍）。

第 7 条是关键的安全兜底：模型漏答某个在途持仓时，绝不能让它"无人看管"。
"""


def normalize_position_management(pos_mgmt_list, active_inst_ids, *, safe_float):
    """把 AI 的 `position_management` 归一并补齐遗漏持仓，返回新的列表。

    语义见模块 docstring（7 条，逐条照搬自原门面内联实现）。
    """
    if not isinstance(pos_mgmt_list, list):
        pos_mgmt_list = []

    validated = []
    seen_positions = set()
    for item in pos_mgmt_list:
        if not isinstance(item, dict):
            continue
        inst_id = str(item.get("instId", ""))
        if inst_id not in active_inst_ids or inst_id in seen_positions:
            continue
        seen_positions.add(inst_id)
        action = str(item.get("action", "HOLD")).upper()
        if action not in {"HOLD", "CLOSE_MARKET", "UPDATE_SL", "UPDATE_TP"}:
            action = "HOLD"
        confidence = max(0.0, min(100.0, safe_float(item.get("confidence"))))
        suggested_sl = safe_float(item.get("suggested_sl_price"))
        if action != "UPDATE_SL":
            suggested_sl = 0.0
        suggested_tp1 = safe_float(item.get("suggested_tp1_price"))
        suggested_tp2 = safe_float(item.get("suggested_tp2_price"))
        if action != "UPDATE_TP":
            suggested_tp1 = 0.0
            suggested_tp2 = 0.0
        validated.append({
            "instId": inst_id,
            "action": action,
            "suggested_sl_price": suggested_sl,
            "suggested_tp1_price": suggested_tp1,
            "suggested_tp2_price": suggested_tp2,
            "confidence": confidence,
            "reason": str(item.get("reason", "模型未提供持仓理由"))[:120]
        })

    for inst_id in sorted(active_inst_ids - seen_positions):
        validated.append({
            "instId": inst_id,
            "action": "HOLD",
            "suggested_sl_price": 0.0,
            "suggested_tp1_price": 0.0,
            "suggested_tp2_price": 0.0,
            "confidence": 0.0,
            "reason": "模型遗漏该持仓，安全降级为 HOLD"
        })
    return validated


def build_effective_prompt_text(*, effective_system_prompt, policy_version, time_str, prompt):
    """SYSTEM + 分隔线 + USER 的全文（原门面 2 处逐字相同的 f-string）。

    两处用途不同（一处存「最近提示词」快照、一处进历史记录），格式也必须一致，
    故收成一个函数 —— 否则以后改格式要改两遍，容易只改一处。

    **`policy_version` 为空串时标签不带括号**（`【SYSTEM PROMPT】：`），这是
    原快照那处的历史格式（它当时写的是无版本标签）。调用方直接传 `""` 即可，
    不需要在外面做字符串替换 —— 那样做等于把格式知识散回调用点。
    """
    label = f"【SYSTEM PROMPT ({policy_version})】：" if policy_version else "【SYSTEM PROMPT】："
    return (
        f"{label}\n{effective_system_prompt.strip()}"
        f"\n\n{'=' * 70}\n【USER PROMPT ({time_str})】：\n{prompt.strip()}"
    )


def _calculate_scale_out_tp(entry_price, action, atr, precision=2):
    try:
        from scripts.risk_constants import SCALE_OUT_ENABLED, SCALE_OUT_TRIGGER_ATR
        if not SCALE_OUT_ENABLED:
            return None
        ep = float(entry_price or 0.0)
        atr_val = float(atr or 0.0)
        act = str(action or "").upper()
        if ep <= 0 or atr_val <= 0:
            return None
        trigger_threshold = float(SCALE_OUT_TRIGGER_ATR or 1.20) * atr_val
        if "BUY" in act or "LONG" in act:
            return round(ep + trigger_threshold, int(precision or 2))
        elif "SELL" in act or "SHORT" in act:
            return round(ep - trigger_threshold, int(precision or 2))
    except Exception:
        pass
    return None


def build_history_record(*, time_str, policy_version, policy_hash, policy_snapshot,
                         policy_summary, macro_summary, council_status, ai_last_prompt,
                         pos_mgmt_list, council_transcript, packages, standard_cache):
    """装配「Web 审计历史」记录（原门面内联 28 行字典）。

    `top_opportunities` 逐标的从 `standard_cache` 取字段；`leverage` 缺省 3、
    `margin_usdt` 缺省 0.0 —— 与原实现一致（原样保留 `.get(..., default)`
    与直接下标访问的区别：`action` / `confidence` / `risk_reward_ratio` /
    `summary_reason` 缺键应抛错，而不是静默填默认值，否则审计会失真）。
    """
    return {
        "time": time_str,
        "policy_version": policy_version,
        "policy_hash": policy_hash,
        "policy_snapshot": policy_snapshot,
        "policy_snapshot_summary": policy_summary,
        "macro_assessment": macro_summary,
        # 投委会周期级状态（ran/降级原因/参谋有效率）；逐单采纳席位在各缓存条目 "council" 内
        "council_status": council_status,
        "ai_last_prompt": ai_last_prompt,
        "position_management": pos_mgmt_list,
        "council_transcript": council_transcript,
        "top_opportunities": [
            {
                "inst": p["name"],
                "action": standard_cache[p["instId"]]["decision"]["action"],
                "confidence": standard_cache[p["instId"]]["decision"]["confidence"],
                "leverage": standard_cache[p["instId"]]["decision"].get("leverage", 3),
                "council_adopted": (standard_cache[p["instId"]].get("council") or {}).get("adopted_role"),
                "margin_usdt": standard_cache[p["instId"]]["decision"].get("margin_usdt", 0.0),
                "risk_reward_ratio": standard_cache[p["instId"]]["decision"]["risk_reward_ratio"],
                "data_quality": standard_cache[p["instId"]]["data_quality"],
                "policy_version": policy_version,
                "reason": standard_cache[p["instId"]]["decision"]["summary_reason"],
                "entry_price": standard_cache[p["instId"]]["decision"].get("entry_price"),
                "target_entry_price": standard_cache[p["instId"]]["decision"].get("entry_price"),
                "stop_loss_price": standard_cache[p["instId"]]["decision"].get("stop_loss_price"),
                "take_profit_price": standard_cache[p["instId"]]["decision"].get("take_profit_price"),
                "scale_out_tp": _calculate_scale_out_tp(
                    standard_cache[p["instId"]]["decision"].get("entry_price"),
                    standard_cache[p["instId"]]["decision"].get("action"),
                    p.get("atr") or p.get("atr_1h") or p.get("atr_15m"),
                    p.get("precision", 2),
                ),
            }
            for p in packages
        ]
    }
