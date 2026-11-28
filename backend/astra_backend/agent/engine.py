"""Agent 对话编排主循环：SSE 流式推演、多轮工具调用与变更提案收集落库。"""
from __future__ import annotations

import asyncio
import json
from typing import Any, AsyncIterator, Dict, List, Optional

from astra_backend.agent.config import load_agent_config, resolve_agent_llm_runtime
from astra_backend.agent.llm_stream import stream_llm_turn
from astra_backend.agent.store import AgentStore
from astra_backend.agent.tools_read import READ_TOOL_SCHEMAS, build_state_summary, execute_read_tool
from astra_backend.agent.tools_verify import VERIFY_TOOL_SCHEMAS, execute_verify_tool
from astra_backend.agent.tools_write import WRITE_TOOL_SCHEMAS, build_proposal_item, is_write_proposal_tool

MAX_HISTORY_MESSAGES = 24


def _build_system_prompt(is_superadmin: bool) -> str:
    perm_note = (
        "当前操作者为超级管理员 (superadmin)：你可以生成变更提案卡片供其审批确认。"
        if is_superadmin
        else "当前操作者为普通只读管理员 (admin)：严禁生成或承诺写操作落地，仅提供只读诊断、复盘归因与预演建议。"
    )
    return (
        "你是 AstraQuant 量化交易系统的「策略运维 Copilot Agent」，负责协助操盘手完成诊断复盘、参数调优与提示词工程。\n\n"
        "【核心铁律（必须严格遵守）】\n"
        "1. **只读优先、数据诚实**：任何分析、归因、修改建议之前，必须先调用只读工具核实真实运行状态（持仓、台账、因子、日志、风控、提示词正文、投委会、快照）；缺失字段必须直说缺失，绝不编造数字。\n"
        "2. **禁止直接改盘（Proposal-Only）**：你没有任何直接写入配置的权限。所有配置改动（调风控、改提示词、调投委会、增删标的、改交易时段、切模型/思考强度、管心法、策略回滚）都必须调用 `propose_*` 工具生成结构化 Diff 提案卡片，等待用户点击确认后才生效。\n"
        "3. **提示词编辑准则**：默认通过 `get_prompt_library(include_content=true)` 查看当前激活方案的模块清单与原文，再用 `propose_prompt_edit` 精准修改目标模块。系统只读 JSON 输出契约模块（`READONLY_OUTPUT_SCHEMA`）禁止修改或停用；仅当用户明确要求时才克隆/新建/切换方案。\n"
        "4. **合理打包提案**：若需要同时联动调整（例如“调严风控 + 微调交易提示词”），在同一轮中依次调用对应的 `propose_*` 工具，系统会自动合并为一张多项目提案卡片。\n"
        "5. **善用演练与回测**：用户在纠结改动效果或要求验证时，主动调用 `dry_run_decision_preview`（实景快照预演）或 `backtest_risk_comparison`（历史 K 线回测对比）给出量化依据。\n"
        "6. **安全红线**：绝不尝试读取、输出或修改 OKX/LLM/通知渠道的 API 密钥/Webhook、绝不切换 DEMO/LIVE 环境、绝不手动触发交易或平仓、绝不管理管理员账号密码或全量灾备恢复。\n"
        f"7. **权限状态**：{perm_note}\n"
        "请用简洁、专业、结构化的中文回答，引用参数或指标时给出准确数值。"
    )


def _summarize_tool_result(tool_name: str, result: Dict[str, Any]) -> str:
    if isinstance(result, dict) and result.get("error"):
        return f"失败：{str(result['error'])[:80]}"
    if is_write_proposal_tool(tool_name):
        return f"已生成提案：{result.get('title', tool_name)}"
    if tool_name == "get_trade_performance_and_ledger":
        return f"已读取 {result.get('total_closed_trades', 0)} 笔平仓统计"
    if tool_name == "get_risk_config":
        return f"已读取 {len(result.get('current_values') or {})} 项风控参数"
    if tool_name == "get_prompt_library":
        return f"已读取方案 {result.get('inspected_profile_id', '')}"
    if tool_name == "backtest_risk_comparison":
        return "已完成历史 K 线回测对比" if result.get("ok") else str(result.get("error") or "回测不可用")
    if tool_name == "dry_run_decision_preview":
        return "已完成实景快照预演" if result.get("ok") else str(result.get("error") or "预演失败")
    return "已完成"


def _build_conversation_messages(history: List[Dict[str, Any]], is_superadmin: bool) -> List[Dict[str, Any]]:
    msgs: List[Dict[str, Any]] = [{"role": "system", "content": _build_system_prompt(is_superadmin)}]
    for row in history[-MAX_HISTORY_MESSAGES:]:
        role = str(row.get("role") or "user")
        if role not in ("user", "assistant"):
            continue
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        msgs.append({"role": role, "content": content})
    return msgs


async def run_agent_chat(
    store: AgentStore,
    session_id: str,
    user_message: str,
    actor: str,
    is_superadmin: bool,
    model_override: Optional[str] = None,
) -> AsyncIterator[Dict[str, Any]]:
    """执行一次 Agent 对话流：持续 yield SSE 事件直到 done 或 error。"""
    session = store.get_session(session_id)
    if not session:
        yield {"type": "error", "error": "会话不存在或已被删除"}
        return

    clean_msg = (user_message or "").strip()
    if not clean_msg:
        yield {"type": "error", "error": "输入消息不能为空"}
        return

    existing_history = store.list_messages(session_id, limit=200)
    if not existing_history and session.get("title") in ("新会话", "New Session", ""):
        auto_title = clean_msg.replace("\n", " ")[:28] + ("..." if len(clean_msg) > 28 else "")
        store.rename_session(session_id, title=auto_title)
        yield {"type": "session_updated", "session": store.get_session(session_id)}

    store.append_message(session_id, role="user", content=clean_msg)
    full_history = store.list_messages(session_id, limit=200)
    messages = _build_conversation_messages(full_history, is_superadmin)

    agent_cfg = load_agent_config()
    eff_override = (model_override or "").strip() or (
        session.get("model_id") if session.get("model_id") and session.get("model_id") != "auto" else None
    )
    try:
        runtime = resolve_agent_llm_runtime(agent_cfg, model_override=eff_override)
    except Exception as exc:
        err_msg = str(exc)
        store.append_message(session_id, role="assistant", content=f"⚠️ 模型未就绪：{err_msg}")
        yield {"type": "error", "error": err_msg}
        return

    tools = [*READ_TOOL_SCHEMAS, *VERIFY_TOOL_SCHEMAS]
    if is_superadmin:
        tools.extend(WRITE_TOOL_SCHEMAS)

    max_rounds = int(agent_cfg.get("max_tool_rounds") or 8)
    collected_text: List[str] = []
    collected_reasoning: List[str] = []
    tool_trace: List[Dict[str, Any]] = []
    pending_items: List[Dict[str, Any]] = []
    last_usage: Dict[str, Any] = {}

    for _round_idx in range(max_rounds):
        round_text: List[str] = []
        round_calls: List[Dict[str, Any]] = []
        round_error: Optional[str] = None

        async for ev in stream_llm_turn(runtime, messages, tools, temperature=0.2):
            etype = ev.get("type")
            if etype == "reasoning_delta":
                txt = str(ev.get("text") or "")
                collected_reasoning.append(txt)
                yield {"type": "reasoning_delta", "text": txt}
            elif etype == "text_delta":
                txt = str(ev.get("text") or "")
                round_text.append(txt)
                collected_text.append(txt)
                yield {"type": "text_delta", "text": txt}
            elif etype == "tool_calls":
                round_calls = list(ev.get("calls") or [])
            elif etype == "usage":
                if isinstance(ev.get("usage"), dict):
                    last_usage = dict(ev["usage"])
            elif etype == "error":
                round_error = str(ev.get("error") or "未知推演错误")

        if round_error:
            if not collected_text:
                collected_text.append(f"⚠️ 推演中断：{round_error}")
            store.append_message(
                session_id,
                role="assistant",
                content="".join(collected_text),
                reasoning="".join(collected_reasoning),
                tool_calls=tool_trace,
                usage=last_usage,
            )
            yield {"type": "error", "error": round_error}
            return

        if not round_calls:
            break

        messages.append({
            "role": "assistant",
            "content": "".join(round_text),
            "tool_calls": round_calls,
        })

        for call in round_calls:
            cid = str(call.get("id") or "")
            cname = str(call.get("name") or "")
            cargs = call.get("arguments") if isinstance(call.get("arguments"), dict) else {}

            yield {"type": "tool_start", "id": cid, "name": cname, "arguments": cargs}
            status = "ok"
            try:
                if is_write_proposal_tool(cname):
                    if not is_superadmin:
                        raise PermissionError("仅超级管理员 (superadmin) 允许发起策略变更提案")
                    item = await asyncio.to_thread(build_proposal_item, cname, cargs)
                    pending_items.append(item)
                    result_obj: Dict[str, Any] = {
                        "ok": True,
                        "proposal_item_created": item["id"],
                        "title": item["title"],
                        "high_risk": item["high_risk"],
                        "required_phrase": item["required_phrase"],
                        "diff": item["diff"],
                    }
                elif cname in {"dry_run_decision_preview", "backtest_risk_comparison"}:
                    result_obj = await asyncio.to_thread(execute_verify_tool, cname, cargs)
                else:
                    result_obj = await asyncio.to_thread(execute_read_tool, cname, cargs)
            except Exception as exc:
                status = "error"
                result_obj = {"ok": False, "error": str(exc)}

            summary = _summarize_tool_result(cname, result_obj)
            tool_trace.append({
                "id": cid,
                "name": cname,
                "arguments": cargs,
                "status": status,
                "summary": summary,
            })
            yield {"type": "tool_result", "id": cid, "name": cname, "status": status, "summary": summary}

            serialized = json.dumps(result_obj, ensure_ascii=False, default=str)
            if len(serialized) > 24000:
                serialized = serialized[:24000] + "...(truncated)"
            messages.append({
                "role": "tool",
                "tool_call_id": cid,
                "tool_name": cname,
                "content": serialized,
            })

    proposal_ids: List[str] = []
    created_proposal: Optional[Dict[str, Any]] = None
    if pending_items:
        if len(pending_items) == 1:
            prop_title = str(pending_items[0].get("title") or "策略变更提案")
        else:
            prop_title = f"联动变更提案（共 {len(pending_items)} 项）"
        prop_summary = "；".join(str(i.get("title") or "") for i in pending_items)[:240]
        created_proposal = store.create_proposal(
            session_id=session_id,
            title=prop_title,
            items=pending_items,
            summary=prop_summary,
            actor=actor,
        )
        proposal_ids.append(created_proposal["id"])
        yield {"type": "proposal", "proposal": created_proposal}

    final_content = "".join(collected_text).strip()
    if not final_content and created_proposal is not None:
        final_content = f"已为你生成变更提案「{created_proposal['title']}」，请核对下方 Diff 详情后勾选确认应用。"
        yield {"type": "text_delta", "text": final_content}

    saved_msg = store.append_message(
        session_id,
        role="assistant",
        content=final_content,
        reasoning="".join(collected_reasoning),
        tool_calls=tool_trace,
        proposal_ids=proposal_ids,
        usage=last_usage,
    )

    try:
        state_summary = await asyncio.to_thread(build_state_summary)
    except Exception:
        state_summary = None

    yield {
        "type": "done",
        "message": saved_msg,
        "proposal": created_proposal,
        "state_summary": state_summary,
    }
