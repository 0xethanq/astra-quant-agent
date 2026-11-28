"""Agent 变更提案的审批确认、前置策略快照与原子落地引擎。"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import time
from typing import Any, Dict, List, Optional

from astra_backend.agent.store import AgentStore
from astra_backend.agent.tools_read import build_state_summary
from astra_backend.audit import record as audit_record

BJ_TZ = timezone(timedelta(hours=8))


def _capture_extra_pre_state() -> Dict[str, Any]:
    """捕获整包政策快照之外的附加策略面状态（标的池/时段/LLM设置/自进化配置）。"""
    out: Dict[str, Any] = {}
    try:
        from scripts.instrument_pool import load_instruments
        out["instruments"] = [i.get("instId") for i in load_instruments() if isinstance(i, dict)]
    except Exception:
        out["instruments"] = []
    try:
        from astra_backend.trading_session_store import load_trading_session
        out["trading_session"] = load_trading_session()
    except Exception:
        out["trading_session"] = {}
    try:
        from astra_backend.llm_manager import load_llm_config
        cfg = load_llm_config(mask_keys=True)
        out["llm_settings"] = {
            "active_model_id": cfg.get("active_model_id"),
            "active_reasoning_effort": cfg.get("active_reasoning_effort"),
            "thinking_timeout": cfg.get("thinking_timeout"),
            "request_attempts": cfg.get("request_attempts"),
            "fallback_model_ids": cfg.get("fallback_model_ids") or [],
        }
    except Exception:
        out["llm_settings"] = {}
    try:
        from astra_backend.evolution_config import load_evolution_config
        out["evolution_config"] = load_evolution_config()
    except Exception:
        out["evolution_config"] = {}
    try:
        from astra_backend.config import settings
        out["order_mode"] = (os.getenv("ASTRA_ORDER_MODE") or getattr(settings, "order_mode", "limit") or "limit").strip().lower()
    except Exception:
        out["order_mode"] = "limit"
    return out


def _apply_single_item(item: Dict[str, Any], actor: str) -> Dict[str, Any]:
    domain = str(item.get("domain") or "")
    action = str(item.get("action") or "")
    payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}

    if domain == "risk":
        from astra_backend import risk_config
        from astra_backend.config import refresh_settings
        from astra_backend.settings_store import remove_env, update_env

        if action == "reset":
            remove_env(set(risk_config.reset_keys()))
            refresh_settings()
            risk_config.reload_risk_constants()
            try:
                from scripts.instrument_pool import sync_pool_leverage_caps
                cur_v = risk_config.current_values()
                sync_pool_leverage_caps(
                    min_leverage=float(cur_v.get("ASTRA_MIN_LEVERAGE", 2.0)),
                    max_leverage=float(cur_v.get("ASTRA_MAX_LEVERAGE", 5.0)),
                )
            except Exception:
                pass
            audit_record("risk.config.reset", "success", {"actor": actor, "via": "agent"})
            return {"ok": True, "detail": "已重置全部风控参数为出厂基线"}

        merged: Dict[str, Any] = {}
        if payload.get("suite_id"):
            merged.update(risk_config.suite_values(str(payload["suite_id"])))
        if isinstance(payload.get("values"), dict):
            merged.update(payload["values"])
        env_updates = risk_config.normalize(merged)
        update_env(env_updates)
        refresh_settings()
        risk_config.reload_risk_constants()
        try:
            from scripts.instrument_pool import sync_pool_leverage_caps
            cur_v = risk_config.current_values()
            sync_pool_leverage_caps(
                min_leverage=float(env_updates.get("ASTRA_MIN_LEVERAGE", cur_v.get("ASTRA_MIN_LEVERAGE", 2.0))),
                max_leverage=float(env_updates.get("ASTRA_MAX_LEVERAGE", cur_v.get("ASTRA_MAX_LEVERAGE", 5.0))),
            )
        except Exception:
            pass
        audit_record("risk.config.update", "success", {"actor": actor, "via": "agent", "updated": sorted(env_updates.keys())})
        return {"ok": True, "detail": f"已更新 {len(env_updates)} 项风控参数（下一交易周期自动生效）"}

    if domain == "prompt":
        from scripts.prompt_library import activate_profile, create_profile, rollback_profile, update_profile

        if action == "clone_profile":
            created = create_profile(
                str(payload["name"]),
                str(payload.get("description") or ""),
                str(payload.get("source_id") or "allpattern_swing"),
                note=f"Agent 克隆 ({actor})",
            )
            if payload.get("activate"):
                activate_profile(created["id"])
            audit_record("prompt.profile.create", "success", {"actor": actor, "via": "agent", "profile_id": created["id"]})
            return {"ok": True, "detail": f"已创建方案 {created['id']}"}

        if action == "activate_profile":
            pid = str(payload["profile_id"])
            activate_profile(pid)
            audit_record("prompt.profile.activate", "success", {"actor": actor, "via": "agent", "profile_id": pid})
            return {"ok": True, "detail": f"已激活方案 {pid}"}

        if action == "rollback_profile":
            pid = str(payload["profile_id"])
            rev_id = str(payload["revision_id"])
            rollback_profile(pid, rev_id)
            audit_record("prompt.profile.rollback", "success", {"actor": actor, "via": "agent", "profile_id": pid, "revision_id": rev_id})
            return {"ok": True, "detail": f"已回滚方案 {pid} 至 {rev_id}"}

        pid = str(payload["profile_id"])
        pipelines = payload.get("pipelines") or {}
        note = str(payload.get("note") or f"Agent 更新 ({actor})")
        update_profile(pid, {"pipelines": pipelines}, note)
        audit_record("prompt.profile.update", "success", {"actor": actor, "via": "agent", "profile_id": pid})
        return {"ok": True, "detail": f"已保存提示词方案 {pid}"}

    if domain == "council":
        from astra_backend.council_manager import save_council_config

        saved = save_council_config({
            "enabled": payload.get("enabled"),
            "consensus_mode": payload.get("consensus_mode"),
            "timeout_seconds": payload.get("timeout_seconds"),
            "roles": payload.get("roles"),
        })
        audit_record("council.config.update", "success", {"actor": actor, "via": "agent", "enabled": saved.get("enabled")})
        return {"ok": True, "detail": "已更新投委会配置"}

    if domain == "instrument":
        from astra_backend import dependencies as deps
        from astra_backend.routers.risk import _holdings_report
        from scripts.instrument_pool import load_instruments, mutate_instruments

        inst_id = str(payload["inst_id"]).upper()
        if action == "add":
            new_item = dict(payload["item"])

            def _append_pool(pool: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
                if any(r.get("instId") == inst_id for r in pool):
                    raise ValueError(f"{inst_id} 已在交易池中")
                if len(pool) >= deps.MAX_POOL_SIZE:
                    raise ValueError(f"交易池已达上限 {deps.MAX_POOL_SIZE}")
                return [*pool, new_item]

            mutate_instruments(_append_pool)
            audit_record("instrument.add", "success", {"actor": actor, "via": "agent", "instId": inst_id})
            return {"ok": True, "detail": f"已新增交易标的 {inst_id}"}

        if action == "remove":
            if inst_id == "BTC-USDT-SWAP":
                raise ValueError("BTC-USDT-SWAP 不可删除")
            current = load_instruments()
            if len(current) <= deps.MIN_POOL_SIZE:
                raise ValueError(f"交易池至少保留 {deps.MIN_POOL_SIZE} 个币种")
            trackers = deps.read_json("position_trackers.json", {})
            report = _holdings_report(inst_id, trackers if isinstance(trackers, dict) else {})
            if report["tracker_keys"] or report["held_live"] or report["holdings_unknown"]:
                raise ValueError(f"无法移除 {inst_id}：存在持仓或实时持仓未知")
            mutate_instruments(lambda pool: [r for r in pool if r.get("instId") != inst_id])
            audit_record("instrument.remove", "success", {"actor": actor, "via": "agent", "instId": inst_id})
            return {"ok": True, "detail": f"已移除交易标的 {inst_id}"}

    if domain == "trading_session":
        from astra_backend.trading_session_store import save_trading_session
        from scripts.trader.session import normalize_session

        norm_sess, errs = normalize_session(payload)
        if errs:
            raise ValueError("；".join(errs))
        save_trading_session(norm_sess)
        audit_record("gateway.trading_session.update", "success", {"actor": actor, "via": "agent", "enabled": norm_sess["enabled"]})
        return {"ok": True, "detail": "已更新交易时段闸门"}

    if domain == "llm":
        from astra_backend.llm_manager import update_llm_settings

        res = update_llm_settings(
            active_model_id=payload.get("active_model_id"),
            reasoning_effort=payload.get("reasoning_effort"),
            thinking_timeout=payload.get("thinking_timeout"),
            request_attempts=payload.get("request_attempts"),
            fallback_model_ids=payload.get("fallback_model_ids"),
        )
        audit_record("llm.settings.update", "success", {"actor": actor, "via": "agent", "active_model_id": res.get("active_model_id")})
        return {"ok": True, "detail": f"已更新 LLM 全局设置（主脑：{res.get('active_model_id')}）"}

    if domain == "evolution":
        from astra_backend.evolution_config import save_evolution_config

        save_evolution_config(payload)
        audit_record("evolution.config.update", "success", {"actor": actor, "via": "agent"})
        return {"ok": True, "detail": "已更新自进化配置"}

    if domain == "memory":
        from scripts import evolution_shield

        view = evolution_shield.admin_memory_view()
        ver = view.get("version")
        if action == "add":
            evolution_shield.admin_mutate("add", texts=[str(payload["text"])], expected_version=ver)
            audit_record("memory.item.add", "success", {"actor": actor, "via": "agent"})
            return {"ok": True, "detail": "已新增自进化心法条目"}
        if action == "toggle":
            target = evolution_shield.toggle_lesson(str(payload["lesson_id"]), expected_version=ver)
            if not target:
                raise ValueError("未找到指定心法条目")
            audit_record("memory.lesson.toggle", "success", {"actor": actor, "via": "agent", "id": payload["lesson_id"]})
            return {"ok": True, "detail": f"已切换心法启停：{payload['lesson_id']}"}
        if action == "delete":
            evolution_shield.admin_mutate("delete", index=0, lesson_id=str(payload["lesson_id"]), expected_version=ver)
            audit_record("memory.item.delete", "success", {"actor": actor, "via": "agent", "id": payload["lesson_id"]})
            return {"ok": True, "detail": f"已删除心法条目：{payload['lesson_id']}"}
        if action == "reset":
            evolution_shield.reset_all_lessons(expected_version=ver)
            audit_record("memory.reset_all", "success", {"actor": actor, "via": "agent"})
            return {"ok": True, "detail": "已清空心法库"}

    if domain == "policy_restore":
        from astra_backend.policy_snapshot import restore_archived_policy

        p_hash = str(payload["policy_hash"])
        restore_archived_policy(policy_hash=p_hash)
        audit_record("policy.restore", "success", {"actor": actor, "via": "agent", "policy_hash": p_hash})
        return {"ok": True, "detail": f"已回滚策略至快照 {p_hash}"}

    if domain == "order_mode":
        from astra_backend.config import refresh_settings
        from astra_backend.settings_store import update_env

        mode = str(payload.get("order_mode") or "").strip().lower()
        if mode not in {"limit", "market", "smart"}:
            raise ValueError(f"不支持的委托订单模式：{mode}")
        update_env({"ASTRA_ORDER_MODE": mode})
        refresh_settings()
        audit_record("system.order_mode.update", "success", {"actor": actor, "via": "agent", "order_mode": mode})
        return {"ok": True, "detail": f"已切换委托订单模式为 {mode}（下一决策周期立即生效）"}

    if domain == "ops_action":
        act = str(payload.get("action") or action or "").strip().lower()
        if act == "run_dry_run":
            from astra_backend.agent.tools_verify import execute_verify_tool

            res = execute_verify_tool("dry_run_decision_preview", {"mode": "single"})
            audit_record("agent.ops.dry_run", "success" if res.get("ok") else "failed", {"actor": actor, "via": "agent"})
            if not res.get("ok"):
                raise ValueError(str(res.get("error") or "预演失败"))
            return {"ok": True, "detail": "已完成实景快照只读预演"}

        if act == "trigger_evolution_review":
            from astra_backend import dependencies as deps
            from astra_backend.spawn import run_script

            script_path = deps.ROOT / "scripts" / "self_improvement_engine.py"
            if not script_path.is_file():
                raise ValueError("未找到 self_improvement_engine.py")
            cp = run_script(script_path, timeout=90, label="agent-evolution", env=dict(os.environ))
            audit_record("agent.ops.evolution", "success" if cp.returncode == 0 else "failed", {"actor": actor, "via": "agent", "rc": cp.returncode})
            if cp.returncode != 0:
                raise ValueError(f"自进化复盘退出码 {cp.returncode}")
            return {"ok": True, "detail": "已完成一轮自进化认知复盘"}

        if act == "cancel_stale_limit_orders":
            from astra_backend import dependencies as deps
            from astra_backend.file_locks import file_lock
            from scripts.risk_constants import LIMIT_ORDER_TTL_MINUTES

            override_dir = os.environ.get("ASTRA_DATA_DIR", "").strip()
            base_dir = Path(override_dir) if (override_dir and deps.DATA_DIR == deps.ROOT / "data") else deps.DATA_DIR
            intents_file = base_dir / "open_order_intents.json"
            removed = 0
            kept = 0
            if intents_file.is_file():
                with file_lock(intents_file):
                    try:
                        raw = json.loads(intents_file.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        raw = []
                    if isinstance(raw, list):
                        cutoff_ms = int(time.time() * 1000) - int(float(LIMIT_ORDER_TTL_MINUTES or 90) * 60_000)
                        fresh: List[Dict[str, Any]] = []
                        for entry in raw:
                            ts_val = int(entry.get("ts") or 0) if isinstance(entry, dict) else 0
                            if ts_val and ts_val < cutoff_ms:
                                removed += 1
                            else:
                                fresh.append(entry)
                        kept = len(fresh)
                        intents_file.write_text(json.dumps(fresh, ensure_ascii=False, indent=2), encoding="utf-8")
            audit_record("agent.ops.cancel_stale", "success", {"actor": actor, "via": "agent", "removed": removed, "kept": kept})
            return {"ok": True, "detail": f"已清理 {removed} 条超期挂单意图（保留 {kept} 条在途）"}

    raise ValueError(f"不支持的变更域或动作：{domain}/{action}")


def apply_proposal(
    store: AgentStore,
    proposal_id: str,
    actor: str,
    selected_item_ids: Optional[List[str]] = None,
    confirmations: Optional[Dict[str, str]] = None,
) -> Dict[str, Any]:
    """审批通过提案：校验二次确认短语、前置自动拍策略快照、逐项原子落地并记录审计。"""
    proposal = store.get_proposal(proposal_id)
    if not proposal:
        raise KeyError(f"未找到变更提案：{proposal_id}")
    if proposal["status"] != "pending":
        raise ValueError(f"提案当前状态为 {proposal['status']}，不可重复应用")

    all_items = proposal.get("items") or []
    if selected_item_ids is not None:
        selected_set = set(selected_item_ids)
        chosen = [it for it in all_items if it.get("id") in selected_set]
    else:
        chosen = list(all_items)

    if not chosen:
        raise ValueError("请至少勾选一项要应用的变更")

    raw_confs = confirmations or {}
    conf_by_id = {str(k): str(v or "").strip().upper() for k, v in raw_confs.items()}
    conf_by_phrase = {str(k).strip().upper(): str(v or "").strip().upper() for k, v in raw_confs.items()}
    missing_phrases: List[str] = []
    for it in chosen:
        req_phrase = str(it.get("required_phrase") or "").strip().upper()
        if not req_phrase:
            continue
        item_id = str(it.get("id") or "")
        provided = conf_by_id.get(item_id) or conf_by_phrase.get(req_phrase) or conf_by_id.get("_global") or ""
        if provided != req_phrase:
            missing_phrases.append(req_phrase)
    if missing_phrases:
        raise ValueError(f"高危变更缺少精确确认短语：{', '.join(dict.fromkeys(missing_phrases))}")

    # 应用前自动拍一次整包策略快照作为兜底
    snapshot_hash = ""
    try:
        from astra_backend.policy_snapshot import archive_current_policy
        ts_label = datetime.now(BJ_TZ).strftime("%m%d-%H%M%S")
        arch_entry = archive_current_policy(
            name=f"Agent变更前-{ts_label}",
            description=str(proposal.get("title") or proposal_id)[:180],
            author=f"{actor}(agent)",
        )
        snapshot_hash = str(arch_entry.get("package_hash") or arch_entry.get("policy_hash") or "")
    except Exception:
        snapshot_hash = ""

    pre_state = _capture_extra_pre_state()
    results: List[Dict[str, Any]] = []
    applied_count = 0
    failed_count = 0

    for it in chosen:
        item_id = str(it.get("id") or "")
        try:
            res = _apply_single_item(it, actor)
            applied_count += 1
            results.append({"item_id": item_id, "title": it.get("title"), "ok": True, "detail": res.get("detail", "")})
        except Exception as exc:
            failed_count += 1
            results.append({"item_id": item_id, "title": it.get("title"), "ok": False, "error": str(exc)})

    if applied_count > 0 and failed_count == 0:
        final_status = "applied"
    elif applied_count > 0 and failed_count > 0:
        final_status = "partially_applied"
    else:
        final_status = "failed"

    audit_record(
        "agent.proposal.apply",
        "success" if failed_count == 0 else ("partial" if applied_count > 0 else "failed"),
        {
            "actor": actor,
            "via": "agent",
            "session_id": proposal["session_id"],
            "proposal_id": proposal_id,
            "snapshot_hash": snapshot_hash,
            "results": results,
        },
    )

    updated = store.update_proposal(
        proposal_id,
        final_status,
        snapshot_hash=snapshot_hash,
        pre_state=pre_state,
        applied_result={"results": results, "applied_count": applied_count, "failed_count": failed_count},
        actor=actor,
    )
    return {
        "ok": failed_count == 0,
        "status": final_status,
        "proposal": updated,
        "snapshot_hash": snapshot_hash,
        "results": results,
        "state_summary": build_state_summary(),
    }


def reject_proposal(store: AgentStore, proposal_id: str, actor: str, reason: str = "") -> Dict[str, Any]:
    proposal = store.get_proposal(proposal_id)
    if not proposal:
        raise KeyError(f"未找到变更提案：{proposal_id}")
    if proposal["status"] != "pending":
        raise ValueError(f"提案当前状态为 {proposal['status']}，不可再拒绝")
    updated = store.update_proposal(
        proposal_id,
        "rejected",
        applied_result={"rejected_reason": reason.strip()[:200]},
        actor=actor,
    )
    audit_record(
        "agent.proposal.reject",
        "success",
        {"actor": actor, "via": "agent", "session_id": proposal["session_id"], "proposal_id": proposal_id},
    )
    return {"ok": True, "proposal": updated}


def rollback_proposal(store: AgentStore, proposal_id: str, actor: str) -> Dict[str, Any]:
    """一键回滚已应用的 Agent 提案，尽量恢复到变更前自动捕获的策略快照与运行状态。"""
    proposal = store.get_proposal(proposal_id)
    if not proposal:
        raise KeyError(f"未找到变更提案：{proposal_id}")
    if proposal["status"] not in ("applied", "partially_applied"):
        raise ValueError(f"提案当前状态为 {proposal['status']}，仅支持回滚已应用提案")
    if proposal.get("rolled_back"):
        raise ValueError("该提案已完成回滚，不可重复回滚")

    details: List[str] = []
    snap_hash = str(proposal.get("snapshot_hash") or "").strip()
    if snap_hash:
        try:
            from astra_backend.policy_snapshot import restore_archived_policy

            restore_archived_policy(policy_hash=snap_hash)
            details.append(f"已恢复前置策略快照 {snap_hash}")
        except Exception as exc:
            details.append(f"前置策略快照恢复警告：{exc}")

    pre = proposal.get("pre_state") if isinstance(proposal.get("pre_state"), dict) else {}
    prev_order_mode = str(pre.get("order_mode") or "").strip().lower()
    if prev_order_mode in {"limit", "market", "smart"}:
        from astra_backend.config import refresh_settings
        from astra_backend.settings_store import update_env

        update_env({"ASTRA_ORDER_MODE": prev_order_mode})
        refresh_settings()
        details.append(f"已恢复委托订单模式为 {prev_order_mode}")

    if isinstance(pre.get("trading_session"), dict) and pre["trading_session"]:
        try:
            from astra_backend.trading_session_store import save_trading_session
            from scripts.trader.session import normalize_session

            norm_sess, errs = normalize_session(pre["trading_session"])
            if not errs:
                save_trading_session(norm_sess)
                details.append("已恢复交易时段配置")
        except Exception:
            pass

    if isinstance(pre.get("llm_settings"), dict) and pre["llm_settings"].get("active_model_id"):
        try:
            from astra_backend.llm_manager import update_llm_settings

            ls = pre["llm_settings"]
            update_llm_settings(
                active_model_id=ls.get("active_model_id"),
                reasoning_effort=ls.get("active_reasoning_effort"),
                thinking_timeout=ls.get("thinking_timeout"),
                request_attempts=ls.get("request_attempts"),
                fallback_model_ids=ls.get("fallback_model_ids"),
            )
            details.append("已恢复 LLM 全局设置")
        except Exception:
            pass

    if isinstance(pre.get("evolution_config"), dict) and pre["evolution_config"]:
        try:
            from astra_backend.evolution_config import save_evolution_config

            save_evolution_config(pre["evolution_config"])
            details.append("已恢复自进化引擎配置")
        except Exception:
            pass

    old_res = dict(proposal.get("applied_result") or {})
    old_res.update({
        "rolled_back": True,
        "rolled_back_at": datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "rolled_back_by": actor,
        "rollback_details": details,
    })
    updated = store.update_proposal(
        proposal_id,
        proposal["status"],
        applied_result=old_res,
        actor=actor,
    )
    audit_record(
        "agent.proposal.rollback",
        "success",
        {
            "actor": actor,
            "via": "agent",
            "session_id": proposal["session_id"],
            "proposal_id": proposal_id,
            "snapshot_hash": snap_hash,
            "details": details,
        },
    )
    return {
        "ok": True,
        "proposal": updated,
        "details": details,
        "state_summary": build_state_summary(),
    }
