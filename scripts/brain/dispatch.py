"""主脑批次的 LLM 派发与决策落盘（B3 抽取，`ai_brain_trader.py` 尾块）。

从 `scripts/ai_brain_trader.py::execute_batch_ai_brain_cycle`（305 行）中
**纯搬家**末尾 173 行 `try` 块：LLM 请求 → 决策解析/校验 → 决策缓存、历史、
持仓指令三份落盘 → 周期健康记录。

## 安全属性（与 trader 域同一套纪律）

- 段体 **AST 逐字**（对拍门 `tests/extraction/test_brain_dispatch_extraction.py`）；
- 全部自由名（`37` 个）**同名 kw-only 入参** ⇒ 门面调用期解析，
  `patch.object(ai_brain_trader, "assemble_decision_cache", ...)` 这类测试缝照常生效；
- 段内两处 `return` 即函数终返 ⇒ 调用点 `return helper(...)` 直接透传（无哨兵）。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def dispatch_llm_and_persist_decisions(*,
        AI_DECISION_CACHE_FILE,
        AI_DECISION_HISTORY_FILE,
        AI_POSITION_MANAGEMENT_FILE,
        Any,
        Dict,
        _build_effective_prompt_text,
        _build_history_record,
        _normalize_position_management,
        _record_cycle_health,
        active_inst_ids,
        active_position_sides,
        api_format,
        api_key,
        assemble_decision_cache,
        atomic_write_json,
        base_url,
        effective_system_prompt,
        effort,
        execute_brain_pending_cancels,
        execute_llm_request,
        json,
        model_name,
        os,
        packages,
        policy_hash,
        policy_snapshot,
        policy_summary,
        policy_version,
        prompt,
        runtime_context,
        safe_float,
        telemetry,
        thinking_timeout,
        time,
        time_str,
        urllib):
    """主脑批次：LLM 请求派发 → 决策解析归一 → 缓存/历史/持仓指令落盘 → 健康记录。

    原为 `ai_brain_trader.execute_batch_ai_brain_cycle` 末尾的 173 行 `try` 块
    （**纯搬家**，段体 AST 逐字）。

    ## 为什么调用点是 `return helper(...)`

    该块是函数体**最后一段**，其内部两处 `return`（成功返回 `standard_cache`、
    异常返回 `None`）就是函数的终返值；连同"正常执行完自然返回 None"的路径，
    一起透传即可 —— 无需哨兵、无需回传列表。
    """
    try:
        t0 = time.time()
        raw_res = None
        brain_output = None

        # Transparent check: is Multi-Agent Council enabled?
        council_enabled = False
        try:
            from astra_backend.council_manager import load_council_config, execute_council_debate
            c_cfg = load_council_config()
            council_enabled = bool(c_cfg.get("enabled"))
        except Exception:
            council_enabled = False

        # 委员会运行状态对前台透明（2026-09-10）：此前静默降级——50 周期 0 成功也
        # 无处诊断。ran=False 必带降级原因，进 per-symbol 缓存与历史审计。
        council_status: Dict[str, Any] = {"ran": False, "reason": "未启用（后台投委会开关关闭）"}
        if council_enabled:
            council_status = {"ran": False, "reason": "辩论未返回"}
            print("[AI Brain Council] 🏛️ 多模型委员会已开启，正在启动各专家参谋现场辩论与首席仲裁...")
            try:
                # 审计 P1-4d：席位提示词里的 {{account_balance}}/{{market_matrix}}/{{trading_memory}}
                # 等占位符此前从不渲染（render_variables 在委员会全文 0 次）→ 模型只看得到花括号。
                # 这里把本轮真实运行上下文交给委员会，让席位提示词与交易提示词同源渲染。
                brain_output, council_transcript = execute_council_debate(
                    market_prompt=prompt,
                    original_system_prompt=effective_system_prompt,
                    timeout=float(c_cfg.get("timeout_seconds", 240.0)),
                    runtime_context=runtime_context,
                )
                council_status = {
                    "ran": True,
                    "duration_ms": int(council_transcript.get("total_duration_ms") or 0),
                    "consensus_mode": council_transcript.get("consensus_mode"),
                    "advisors_ok": sum(
                        1 for v in (council_transcript.get("advisors") or {}).values()
                        if isinstance(v, dict) and v.get("status") != "error"
                    ),
                    "advisors_total": len(council_transcript.get("advisors") or {}),
                }
                print(f"[AI Brain Council] ✅ 委员会辩论与终审完成，耗时: {council_status['duration_ms']}ms"
                      f"（参谋 {council_status['advisors_ok']}/{council_status['advisors_total']} 提案有效）")
            except Exception as e:
                council_status = {"ran": False, "reason": f"{type(e).__name__}: {str(e)[:300]}"}
                print(f"[AI Brain Council] ⚠️ 委员会决策超时或异常: {e}，自动降级为单模型极速决策！")
                brain_output = None

        if brain_output is None:
            print(f"[AI Brain Batch] 🚀 正在发起单次全市场大模型宏观决策推演 ({model_name} / {api_format} / 思考上限 {thinking_timeout:.0f}s)...")
            if execute_llm_request:
                content, _, usage_dict, _ = execute_llm_request(
                    messages=[
                        {"role": "system", "content": effective_system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    model=model_name,
                    base_url=base_url,
                    api_key=api_key,
                    api_format=api_format,
                    reasoning_effort=effort,
                    temperature=0.2,
                    response_format={"type": "json_object"},
                    timeout=thinking_timeout,
                )
                raw_res = {"usage": usage_dict} if isinstance(usage_dict, dict) else {}
            else:
                payload = {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": effective_system_prompt},
                        {"role": "user", "content": prompt}
                    ],
                    "temperature": 0.2,
                    "response_format": {"type": "json_object"}
                }
                if effort not in ("none", "auto"):
                    payload["reasoning_effort"] = effort
                req = urllib.request.Request(
                    f"{base_url}/chat/completions",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
                )
                with urllib.request.urlopen(req, timeout=thinking_timeout) as resp:
                    res = json.loads(resp.read().decode("utf-8"))
                    content = res["choices"][0]["message"]["content"].strip()
                    raw_res = res

            if content.startswith("```json"): content = content[7:]
            if content.startswith("```"): content = content[3:]
            if content.endswith("```"): content = content[:-3]

            brain_output = json.loads(content.strip())
            if not isinstance(brain_output, dict):
                raise ValueError("LLM response root must be an object")
        decisions_dict = brain_output.get("decisions", {})
        pos_mgmt_list = brain_output.get("position_management", [])
        macro_summary = str(brain_output.get("macro_assessment", "宏观中性震荡"))[:120]
        if not isinstance(decisions_dict, dict):
            decisions_dict = {}
        if not isinstance(pos_mgmt_list, list):
            pos_mgmt_list = []

        # 白名单归一 + 遗漏持仓安全兜底，见 scripts/brain/cycle_parts.py
        pos_mgmt_list = _normalize_position_management(
            pos_mgmt_list, active_inst_ids, safe_float=safe_float)

        # Execute Pending Orders Cancellation if AI Brain decides CANCEL
        pending_mgmt_list = brain_output.get("pending_orders_management", [])
        if isinstance(pending_mgmt_list, list):
            execute_brain_pending_cancels(pending_mgmt_list)

        standard_cache = assemble_decision_cache(
            packages=packages,
            decisions_dict=decisions_dict,
            active_inst_ids=active_inst_ids,
            active_position_sides=active_position_sides,
            time_str=time_str,
            macro_summary=macro_summary,
            policy_snapshot=policy_snapshot,
            council_status=council_status,
        )

        # 审计③(2026-09-13)：整档覆盖与 trader 的 venue-decision 读-改-写互斥
        # （astra_backend.file_locks，同锁文件路径即同临界区），防互相回退。
        from astra_backend.file_locks import file_lock
        with file_lock(AI_DECISION_CACHE_FILE):
            atomic_write_json(AI_DECISION_CACHE_FILE, standard_cache)
        atomic_write_json(AI_POSITION_MANAGEMENT_FILE, {
            "timestamp": int(time.time()),
            "time_str": time_str,
            "policy_version": policy_version,
            "policy_hash": policy_hash,
            "instructions": pos_mgmt_list
        })

        # Record durable history for Web Audit
        full_prompt_text = _build_effective_prompt_text(
            effective_system_prompt=effective_system_prompt, policy_version=policy_version,
            time_str=time_str, prompt=prompt)
        history_record = _build_history_record(
            time_str=time_str, policy_version=policy_version, policy_hash=policy_hash,
            policy_snapshot=policy_snapshot, policy_summary=policy_summary,
            macro_summary=macro_summary, council_status=council_status,
            ai_last_prompt=full_prompt_text, pos_mgmt_list=pos_mgmt_list,
            council_transcript=(brain_output.get("council_transcript")
                                if isinstance(brain_output, dict) else None),
            packages=packages, standard_cache=standard_cache,
        )

        history_list = []
        if os.path.exists(AI_DECISION_HISTORY_FILE):
            try:
                with open(AI_DECISION_HISTORY_FILE, "r", encoding="utf-8") as f:
                    history_list = json.load(f)
            except Exception:
                pass

        history_list.insert(0, history_record)
        history_list = history_list[:50] # Keep recent 50 rounds
        # 轻量化优化：首条(当前最新轮次)完整保留全景提示词用于排错审计；
        # 历史较旧轮次(idx >= 1)剔除重复庞大的 40KB prompt，缩减至前缀，大幅削减 90% 存储与反序列化开销
        for idx, item in enumerate(history_list):
            if idx > 0 and isinstance(item, dict) and "ai_last_prompt" in item:
                p_text = str(item["ai_last_prompt"])
                if len(p_text) > 500:
                    item["ai_last_prompt"] = p_text[:200] + "...(历史轮次已精简收敛)"

        atomic_write_json(AI_DECISION_HISTORY_FILE, history_list)

        latency = round(time.time() - t0, 2)
        telemetry.finish("success", raw_res, output_chars=len(content))
        print(f"[AI Brain Batch] ✅ 全标的池({len(packages)} 币种)全景决策完成 (耗时 {latency}s, 宏观基调: {macro_summary})")
        _record_cycle_health("ok")
        return standard_cache

    except Exception as e:
        telemetry.finish("failed", error=e)
        print(f"[AI Brain Batch] Error in batch inference: {e}")
        _record_cycle_health("failed", str(e))
        return None

