"""写操作提案构造工具：所有变更必须先经服务端校验并生成结构化 Diff 提案，绝不绕过确认直接落盘。"""
from __future__ import annotations

import copy
import difflib
import re
import uuid
from typing import Any, Dict, List

from astra_backend import dependencies as deps


def _item_id() -> str:
    return f"item_{uuid.uuid4().hex[:10]}"


def _propose_risk_update(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend import risk_config

    suite_id = str(args.get("suite_id") or "").strip()
    values = args.get("values") if isinstance(args.get("values"), dict) else {}
    reason = str(args.get("reason") or "").strip()

    merged: Dict[str, Any] = {}
    if suite_id:
        merged.update(risk_config.suite_values(suite_id))
    merged.update(values)
    if not merged:
        raise ValueError("未提供任何需要修改的风控参数或预设套件")

    normalized_str = risk_config.normalize(merged)
    before = risk_config.current_values()
    schema_by_key = {p["key"]: p for p in risk_config.schema().get("params") or []}

    diffs: List[Dict[str, Any]] = []
    parsed_updates: Dict[str, float | int] = {}
    for key, raw_str in normalized_str.items():
        p_meta = schema_by_key.get(key, {})
        val: float | int = int(float(raw_str)) if p_meta.get("type") == "int" else float(raw_str)
        parsed_updates[key] = val
        prev = before.get(key)
        if prev is None or abs(float(prev) - float(val)) > 1e-9:
            scale = float(p_meta.get("display_scale") or 1)
            unit = str(p_meta.get("unit") or "")
            diffs.append({
                "field": key,
                "label": str(p_meta.get("label") or key),
                "before": f"{round(float(prev) * scale, 4):g}{unit}" if prev is not None else "—",
                "after": f"{round(float(val) * scale, 4):g}{unit}",
            })

    if not diffs:
        raise ValueError("目标风控参数与当前生效值完全一致，无需产生变更")

    high_risk = risk_config.high_risk_changes(parsed_updates)
    phrase = ""
    phrase_reason = ""
    warnings: List[str] = []
    if high_risk:
        phrase = risk_config.HIGH_RISK_PHRASE
        phrase_reason = "；".join(
            f"{i['label']} = {i['value'] * 100 if 'RATIO' in i['key'] else i['value']:g}"
            f"（极端阈值 {i['threshold'] * 100 if 'RATIO' in i['key'] else i['threshold']:g}）"
            for i in high_risk
        )
        warnings.append(f"命中极端风控区间，应用时需逐字确认：{phrase}")

    title = f"应用风控套件「{suite_id}」" if suite_id and not values else f"调整 {len(diffs)} 项风控参数"
    return {
        "id": _item_id(),
        "domain": "risk",
        "action": "update",
        "title": title,
        "reason": reason,
        "payload": {"suite_id": suite_id or None, "values": parsed_updates},
        "diff_type": "kv",
        "diff": diffs,
        "warnings": warnings,
        "high_risk": bool(high_risk),
        "required_phrase": phrase,
        "required_phrase_reason": phrase_reason,
    }


def _propose_risk_reset(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend import risk_config
    from scripts.risk_constants import DEFAULTS

    reason = str(args.get("reason") or "").strip()
    before = risk_config.current_values()
    schema_by_key = {p["key"]: p for p in risk_config.schema().get("params") or []}
    diffs = []
    for k, default_v in DEFAULTS.items():
        if abs(float(before.get(k, default_v)) - float(default_v)) > 1e-9:
            p_meta = schema_by_key.get(k, {})
            scale = float(p_meta.get("display_scale") or 1)
            unit = str(p_meta.get("unit") or "")
            diffs.append({
                "field": k,
                "label": str(p_meta.get("label") or k),
                "before": f"{round(float(before[k]) * scale, 4):g}{unit}",
                "after": f"{round(float(default_v) * scale, 4):g}{unit}",
            })
    if not diffs:
        raise ValueError("当前所有风控参数已是出厂基线默认值，无需重置")
    return {
        "id": _item_id(),
        "domain": "risk",
        "action": "reset",
        "title": f"重置 {len(diffs)} 项自定义风控为出厂基线",
        "reason": reason,
        "payload": {},
        "diff_type": "kv",
        "diff": diffs,
        "warnings": ["该操作将清除所有自定义风控覆盖值并回退代码基线"],
        "high_risk": True,
        "required_phrase": "RESET RISK",
        "required_phrase_reason": "清除全部自定义风控参数覆盖值",
    }


def _propose_prompt_edit(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend.prompt_views import EVOLUTION_USER_TEMPLATE, TRADING_USER_TEMPLATE
    from scripts.ai_brain_trader import SYSTEM_PROMPT
    from scripts.prompt_library import (
        TEMPLATE_KEYS,
        _clean_profile,
        demote_edited_base_modules,
        get_profile,
        load_library,
        pipeline_view,
        profile_history,
        validate_profile,
    )
    from scripts.self_improvement_engine import EVOLUTION_SYSTEM_PROMPT

    base_map = {
        "trading_system": SYSTEM_PROMPT,
        "trading_user": TRADING_USER_TEMPLATE,
        "evolution_system": EVOLUTION_SYSTEM_PROMPT,
        "evolution_user": EVOLUTION_USER_TEMPLATE,
    }
    action = str(args.get("action") or "edit_module").strip()
    reason = str(args.get("reason") or args.get("note") or "").strip()
    lib = load_library()
    profile_id = str(args.get("profile_id") or "").strip() or str(lib.get("active_profile_id") or "allpattern_swing")

    if action == "clone_profile":
        source_id = profile_id
        get_profile(source_id)  # 验证存在
        new_name = str(args.get("new_name") or "").strip()
        if not 1 <= len(new_name) <= 60:
            raise ValueError("克隆新方案的名称长度必须为 1~60 字符")
        desc = str(args.get("description") or "").strip()[:240]
        return {
            "id": _item_id(),
            "domain": "prompt",
            "action": "clone_profile",
            "title": f"克隆提示词方案「{new_name}」",
            "reason": reason,
            "payload": {"source_id": source_id, "name": new_name, "description": desc, "activate": bool(args.get("activate", False))},
            "diff_type": "kv",
            "diff": [
                {"field": "source_id", "label": "复制源方案", "before": source_id, "after": new_name},
                {"field": "activate", "label": "创建后激活", "before": "否", "after": "是" if args.get("activate") else "否"},
            ],
            "warnings": [],
            "high_risk": False,
            "required_phrase": "",
            "required_phrase_reason": "",
        }

    if action == "activate_profile":
        prof = get_profile(profile_id)
        if not prof.get("enabled", True):
            raise ValueError("目标提示词方案已停用，无法直接激活")
        cur_active = str(lib.get("active_profile_id") or "")
        if cur_active == profile_id:
            raise ValueError(f"方案 {profile_id} 已是当前激活方案")
        return {
            "id": _item_id(),
            "domain": "prompt",
            "action": "activate_profile",
            "title": f"切换激活提示词方案为「{prof.get('name', profile_id)}」",
            "reason": reason,
            "payload": {"profile_id": profile_id},
            "diff_type": "kv",
            "diff": [{"field": "active_profile_id", "label": "激活提示词方案", "before": cur_active, "after": profile_id}],
            "warnings": [],
            "high_risk": False,
            "required_phrase": "",
            "required_phrase_reason": "",
        }

    if action == "rollback_profile":
        rev_id = str(args.get("revision_id") or "").strip()
        hist = profile_history(profile_id)
        rev = next((h for h in hist if h.get("id") == rev_id), None)
        if not rev:
            raise ValueError(f"方案 {profile_id} 中未找到历史修订 {rev_id}")
        return {
            "id": _item_id(),
            "domain": "prompt",
            "action": "rollback_profile",
            "title": f"回滚提示词方案 {profile_id} 至修订 {rev_id}",
            "reason": reason,
            "payload": {"profile_id": profile_id, "revision_id": rev_id},
            "diff_type": "kv",
            "diff": [{"field": "revision_id", "label": "回滚目标修订", "before": "当前版本", "after": f"{rev_id} ({rev.get('created_at', '')})"}],
            "warnings": [],
            "high_risk": False,
            "required_phrase": "",
            "required_phrase_reason": "",
        }

    pipeline = str(args.get("pipeline") or "trading_system").strip()
    if pipeline not in TEMPLATE_KEYS:
        raise ValueError(f"无效管线名：{pipeline}")
    prof = get_profile(profile_id)
    modules = copy.deepcopy(pipeline_view(base_map[pipeline], prof, pipeline))
    mod_id = str(args.get("module_id") or "").strip()
    mod_title = str(args.get("module_title") or "").strip()

    if action == "add_module":
        title = mod_title or "自定义规则模块"
        content = str(args.get("content") or "").strip()
        if not content:
            raise ValueError("新增提示词模块内容不能为空")
        new_mod = {
            "id": f"module-{uuid.uuid4().hex[:10]}",
            "title": title[:100],
            "content": content,
            "enabled": True if args.get("enabled") is None else bool(args.get("enabled")),
            "locked": False,
            "source": "custom",
        }
        modules.append(new_mod)
        old_text = ""
        new_text = content
        target_label = f"{pipeline}/{title}"
    elif action in {"edit_module", "toggle_module"}:
        idx = next(
            (i for i, m in enumerate(modules) if (mod_id and m.get("id") == mod_id) or (mod_title and m.get("title") == mod_title)),
            None,
        )
        if idx is None:
            raise ValueError(f"在方案 {profile_id} 的 {pipeline} 管线中未找到指定模块（module_id={mod_id!r}, module_title={mod_title!r}）")
        target_mod = modules[idx]
        target_label = f"{pipeline}/{target_mod.get('title') or mod_id}"
        old_text = str(target_mod.get("content") or "")
        new_text = str(args["content"]).strip() if ("content" in args and args.get("content") is not None) else old_text
        if action == "toggle_module":
            new_enabled = bool(args["enabled"]) if args.get("enabled") is not None else not bool(target_mod.get("enabled", True))
            target_mod["enabled"] = new_enabled
            if not new_text:
                new_text = old_text
        else:
            if not new_text:
                raise ValueError("edit_module 必须提供非空 content")
            target_mod["content"] = new_text
            if args.get("enabled") is not None:
                target_mod["enabled"] = bool(args.get("enabled"))
    else:
        raise ValueError(f"不支持的提示词操作：{action}")

    # 用服务端同一条规范化 + 校验闸预先检查（如篡改只读 JSON Schema / 未知变量直接拒绝）
    pipelines_next = copy.deepcopy(prof.get("pipelines") or {})
    pipelines_next[pipeline] = demote_edited_base_modules(modules, base_map[pipeline], pipeline)
    cand = _clean_profile({**prof, "pipelines": pipelines_next}, profile_id)
    check = validate_profile(cand)
    if not check["valid"]:
        raise ValueError("；".join(check["errors"]))

    if action == "toggle_module" and old_text == new_text:
        diff_type = "kv"
        diff_data: Any = [{"field": target_label, "label": target_label, "before": "启用" if not modules[idx]["enabled"] else "停用", "after": "启用" if modules[idx]["enabled"] else "停用"}]
    else:
        diff_type = "text"
        diff_lines = list(difflib.unified_diff(
            old_text.splitlines(),
            new_text.splitlines(),
            fromfile=f"修改前 ({target_label})",
            tofile=f"修改后 ({target_label})",
            lineterm="",
            n=3,
        ))
        diff_data = "\n".join(diff_lines) if diff_lines else f"(仅变更模块启停状态: {target_label})"

    return {
        "id": _item_id(),
        "domain": "prompt",
        "action": action,
        "title": f"修改提示词：{target_label}（方案 {prof.get('name', profile_id)}）",
        "reason": reason,
        "payload": {
            "profile_id": profile_id,
            "pipeline": pipeline,
            "pipelines": {pipeline: pipelines_next[pipeline]},
            "note": reason or f"Agent 修改 {target_label}",
        },
        "diff_type": diff_type,
        "diff": diff_data,
        "warnings": list(check.get("warnings") or []),
        "high_risk": False,
        "required_phrase": "",
        "required_phrase_reason": "",
    }


def _propose_council_update(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend.council.policy import VALID_CONSENSUS_MODES
    from astra_backend.council.roster import clamp_council_timeout, validate_council_roles, validate_seat_model_bindings
    from astra_backend.council_manager import load_council_config

    cur = load_council_config()
    nxt = copy.deepcopy(cur)
    diffs: List[Dict[str, Any]] = []
    reason = str(args.get("reason") or "").strip()

    if args.get("enabled") is not None:
        val = bool(args["enabled"])
        if val != bool(cur.get("enabled", False)):
            diffs.append({"field": "enabled", "label": "投委会总开关", "before": str(bool(cur.get("enabled"))), "after": str(val)})
        nxt["enabled"] = val

    if args.get("consensus_mode"):
        mode = str(args["consensus_mode"]).strip().lower()
        if mode not in VALID_CONSENSUS_MODES:
            raise ValueError(f"无效仲裁模式：{mode}（可选：{', '.join(sorted(VALID_CONSENSUS_MODES))}）")
        if mode != cur.get("consensus_mode"):
            diffs.append({"field": "consensus_mode", "label": "仲裁模式", "before": str(cur.get("consensus_mode")), "after": mode})
        nxt["consensus_mode"] = mode

    if args.get("timeout_seconds") is not None:
        t_val = clamp_council_timeout(args["timeout_seconds"])
        if abs(float(cur.get("timeout_seconds", 240.0)) - t_val) > 1e-6:
            diffs.append({"field": "timeout_seconds", "label": "超时预算(秒)", "before": str(cur.get("timeout_seconds")), "after": str(t_val)})
        nxt["timeout_seconds"] = t_val

    role_updates = args.get("role_updates")
    if isinstance(role_updates, dict):
        roles = nxt.setdefault("roles", {})
        for rid, patch_data in role_updates.items():
            if not isinstance(patch_data, dict):
                continue
            if rid not in roles or not isinstance(roles[rid], dict):
                raise ValueError(f"投委会不存在席位：{rid}")
            for field_name in ("enabled", "weight", "model_id", "reasoning_effort", "temperature", "prompt", "name"):
                if field_name not in patch_data or patch_data[field_name] is None:
                    continue
                old_v = roles[rid].get(field_name)
                new_v = patch_data[field_name]
                if field_name == "weight":
                    new_v = min(1.0, max(0.05, float(new_v)))
                elif field_name == "temperature":
                    new_v = min(1.0, max(0.0, float(new_v)))
                if old_v != new_v:
                    before_disp = f"{str(old_v)[:80]}..." if field_name == "prompt" and len(str(old_v)) > 80 else str(old_v)
                    after_disp = f"{str(new_v)[:80]}..." if field_name == "prompt" and len(str(new_v)) > 80 else str(new_v)
                    diffs.append({"field": f"roles.{rid}.{field_name}", "label": f"席位 {rid} · {field_name}", "before": before_disp, "after": after_disp})
                roles[rid][field_name] = new_v

    if not diffs:
        raise ValueError("投委会配置与当前完全一致，无变更")

    prob = validate_council_roles(nxt.get("roles"))
    if prob:
        raise ValueError(f"投委会配置校验失败：{prob}")
    model_probs = validate_seat_model_bindings(nxt.get("roles"), cur.get("roles"))
    if model_probs:
        raise ValueError("；".join(model_probs))

    return {
        "id": _item_id(),
        "domain": "council",
        "action": "update",
        "title": f"更新投委会配置（{len(diffs)} 项）",
        "reason": reason,
        "payload": {
            "enabled": bool(nxt.get("enabled", False)),
            "consensus_mode": nxt.get("consensus_mode"),
            "timeout_seconds": nxt.get("timeout_seconds"),
            "roles": nxt.get("roles"),
        },
        "diff_type": "kv",
        "diff": diffs,
        "warnings": [],
        "high_risk": False,
        "required_phrase": "",
        "required_phrase_reason": "",
    }


def _propose_instrument_change(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend.routers.risk import _holdings_report
    from scripts.instrument_pool import from_okx_instrument, load_instruments

    action = str(args.get("action") or "").strip().lower()
    inst_id = str(args.get("inst_id") or "").strip().upper()
    reason = str(args.get("reason") or "").strip()
    if not re.fullmatch(r"[A-Z0-9]{2,15}-USDT-SWAP", inst_id):
        raise ValueError("仅支持标准 USDT 永续合约标识（如 SOL-USDT-SWAP）")

    pool = load_instruments()
    if action == "add":
        if any(row.get("instId") == inst_id for row in pool):
            raise ValueError(f"{inst_id} 已在交易标的池中")
        if len(pool) >= deps.MAX_POOL_SIZE:
            raise ValueError(f"交易池已达上限 {deps.MAX_POOL_SIZE} 个币种")
        try:
            matches = deps.okx.instruments("SWAP", inst_id)
        except Exception as exc:
            raise ValueError(f"OKX 合约校验失败：{exc}") from exc
        raw = matches[0] if matches else {}
        if raw.get("instId") != inst_id or raw.get("settleCcy") != "USDT" or raw.get("state") != "live":
            raise ValueError(f"{inst_id} 不是 OKX 在线可交易的 USDT 永续合约")
        item = from_okx_instrument(raw)
        return {
            "id": _item_id(),
            "domain": "instrument",
            "action": "add",
            "title": f"新增交易标的：{inst_id}",
            "reason": reason,
            "payload": {"inst_id": inst_id, "item": item},
            "diff_type": "kv",
            "diff": [
                {"field": "instId", "label": "新增标的", "before": "未收录", "after": f"{inst_id} ({item.get('tier')}, max {item.get('max_leverage')}x)"},
            ],
            "warnings": [],
            "high_risk": False,
            "required_phrase": "",
            "required_phrase_reason": "",
        }

    if action == "remove":
        if inst_id == "BTC-USDT-SWAP":
            raise ValueError("BTC-USDT-SWAP 是全局黑天鹅基准，禁止删除")
        if len(pool) <= deps.MIN_POOL_SIZE:
            raise ValueError(f"交易池至少保留 {deps.MIN_POOL_SIZE} 个币种")
        if not any(row.get("instId") == inst_id for row in pool):
            raise ValueError(f"{inst_id} 不在当前交易池中")
        trackers = deps.read_json("position_trackers.json", {})
        if not isinstance(trackers, dict):
            trackers = {}
        report = _holdings_report(inst_id, trackers)
        if report["tracker_keys"] or report["held_live"] or report["holdings_unknown"]:
            raise ValueError(
                f"Fail-Closed 拒绝移除 {inst_id}："
                f"{report['holdings_unknown'] or '存在持仓或追踪记录，删除后将失去风控接管'}"
            )
        return {
            "id": _item_id(),
            "domain": "instrument",
            "action": "remove",
            "title": f"从交易池移除：{inst_id}",
            "reason": reason,
            "payload": {"inst_id": inst_id},
            "diff_type": "kv",
            "diff": [{"field": "instId", "label": "移除标的", "before": f"{inst_id}（池内）", "after": "移出交易池"}],
            "warnings": ["移除后交易引擎将停止扫描与开仓该标的"],
            "high_risk": True,
            "required_phrase": f"REMOVE {inst_id}",
            "required_phrase_reason": f"确认从交易池移除 {inst_id}",
        }

    raise ValueError(f"不支持的标的池操作：{action}（仅支持 add / remove）")


def _propose_trading_session_update(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend.trading_session_store import load_trading_session
    from scripts.trader.session import normalize_session

    cur, _ = normalize_session(load_trading_session())
    raw_next = {
        "enabled": bool(args.get("enabled")) if args.get("enabled") is not None else cur.get("enabled", False),
        "mode_outside": args.get("mode_outside") or cur.get("mode_outside", "manage_only"),
        "timezone": cur.get("timezone", "Asia/Shanghai"),
        "windows": args.get("windows") if args.get("windows") is not None else cur.get("windows", []),
    }
    nxt, errors = normalize_session(raw_next)
    if errors:
        raise ValueError("；".join(errors))
    if nxt == cur:
        raise ValueError("交易时段配置与当前一致，无变更")
    return {
        "id": _item_id(),
        "domain": "trading_session",
        "action": "update",
        "title": "调整允许开仓的交易时段窗口",
        "reason": str(args.get("reason") or "").strip(),
        "payload": nxt,
        "diff_type": "kv",
        "diff": [
            {"field": "enabled", "label": "时段闸门开关", "before": str(cur["enabled"]), "after": str(nxt["enabled"])},
            {"field": "mode_outside", "label": "窗口外模式", "before": str(cur["mode_outside"]), "after": str(nxt["mode_outside"])},
            {"field": "windows", "label": "允许时段列表", "before": str(cur["windows"]), "after": str(nxt["windows"])},
        ],
        "warnings": [],
        "high_risk": False,
        "required_phrase": "",
        "required_phrase_reason": "",
    }


def _propose_llm_settings_update(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend.llm.policy import MAX_FALLBACK_MODELS, MAX_REQUEST_ATTEMPTS, MIN_REQUEST_ATTEMPTS, STANDARD_REASONING_EFFORTS
    from astra_backend.llm_manager import load_llm_config

    cfg = load_llm_config(mask_keys=True)
    known = {str(m.get("id")) for m in (cfg.get("models") or []) if isinstance(m, dict) and m.get("id")}
    diffs: List[Dict[str, Any]] = []
    payload: Dict[str, Any] = {}

    if args.get("active_model_id"):
        mid = str(args["active_model_id"]).strip()
        if known and mid not in known:
            raise ValueError(f"模型 {mid} 未在「模型连接」中登记")
        if mid != cfg.get("active_model_id"):
            diffs.append({"field": "active_model_id", "label": "交易主脑模型", "before": str(cfg.get("active_model_id")), "after": mid})
            payload["active_model_id"] = mid

    if args.get("reasoning_effort"):
        eff = str(args["reasoning_effort"]).strip().lower()
        if eff not in STANDARD_REASONING_EFFORTS:
            raise ValueError(f"不支持的思考强度：{eff}")
        if eff != cfg.get("active_reasoning_effort"):
            diffs.append({"field": "reasoning_effort", "label": "思考强度", "before": str(cfg.get("active_reasoning_effort")), "after": eff})
            payload["reasoning_effort"] = eff

    if args.get("thinking_timeout") is not None:
        t_val = max(5.0, min(float(args["thinking_timeout"]), 1800.0))
        if abs(float(cfg.get("thinking_timeout", 120.0)) - t_val) > 1e-6:
            diffs.append({"field": "thinking_timeout", "label": "推理超时(秒)", "before": str(cfg.get("thinking_timeout")), "after": str(t_val)})
            payload["thinking_timeout"] = t_val

    if args.get("request_attempts") is not None:
        att = int(args["request_attempts"])
        if not (MIN_REQUEST_ATTEMPTS <= att <= MAX_REQUEST_ATTEMPTS):
            raise ValueError(f"请求次数需在 {MIN_REQUEST_ATTEMPTS}~{MAX_REQUEST_ATTEMPTS} 之间")
        if att != cfg.get("request_attempts"):
            diffs.append({"field": "request_attempts", "label": "单模型重试次数", "before": str(cfg.get("request_attempts")), "after": str(att)})
            payload["request_attempts"] = att

    if args.get("fallback_model_ids") is not None:
        fb = [str(x).strip() for x in args["fallback_model_ids"] if str(x).strip()]
        target_active = payload.get("active_model_id") or cfg.get("active_model_id")
        fb = [x for x in fb if x != target_active]
        for x in fb:
            if known and x not in known:
                raise ValueError(f"回退模型 {x} 未在模型库登记")
        if len(fb) > MAX_FALLBACK_MODELS:
            raise ValueError(f"回退模型最多 {MAX_FALLBACK_MODELS} 个")
        if fb != (cfg.get("fallback_model_ids") or []):
            diffs.append({"field": "fallback_model_ids", "label": "容灾回退链", "before": str(cfg.get("fallback_model_ids") or []), "after": str(fb)})
            payload["fallback_model_ids"] = fb

    if not diffs:
        raise ValueError("LLM 全局设置与当前完全一致，无变更")

    return {
        "id": _item_id(),
        "domain": "llm",
        "action": "update",
        "title": f"调整交易 LLM 全局设置（{len(diffs)} 项）",
        "reason": str(args.get("reason") or "").strip(),
        "payload": payload,
        "diff_type": "kv",
        "diff": diffs,
        "warnings": [],
        "high_risk": False,
        "required_phrase": "",
        "required_phrase_reason": "",
    }


def _propose_evolution_config_update(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend.evolution_config import MAX_TIMEOUT, MIN_TIMEOUT, VALID_EFFORTS, load_evolution_config
    from astra_backend.llm_manager import load_llm_config

    cur = load_evolution_config()
    diffs: List[Dict[str, Any]] = []
    payload: Dict[str, Any] = {}

    if args.get("model_id"):
        mid = str(args["model_id"]).strip()
        if mid != "auto":
            known = {str(m.get("id")) for m in (load_llm_config(mask_keys=True).get("models") or []) if isinstance(m, dict)}
            if known and mid not in known:
                raise ValueError(f"自进化模型 {mid} 未在模型库登记")
        if mid != cur.get("model_id"):
            diffs.append({"field": "model_id", "label": "自进化专属模型", "before": str(cur.get("model_id")), "after": mid})
            payload["model_id"] = mid

    if args.get("reasoning_effort"):
        eff = str(args["reasoning_effort"]).strip().lower()
        if eff not in VALID_EFFORTS:
            raise ValueError(f"自进化思考强度无效：{eff}（可选：{', '.join(sorted(VALID_EFFORTS))}）")
        if eff != cur.get("reasoning_effort"):
            diffs.append({"field": "reasoning_effort", "label": "自进化思考强度", "before": str(cur.get("reasoning_effort")), "after": eff})
            payload["reasoning_effort"] = eff

    if args.get("thinking_timeout") is not None:
        t_val = max(MIN_TIMEOUT, min(MAX_TIMEOUT, float(args["thinking_timeout"])))
        if abs(float(cur.get("thinking_timeout", 300.0)) - t_val) > 1e-6:
            diffs.append({"field": "thinking_timeout", "label": "自进化思考超时(秒)", "before": str(cur.get("thinking_timeout")), "after": str(t_val)})
            payload["thinking_timeout"] = t_val

    if args.get("analysis_depth"):
        depth = str(args["analysis_depth"]).strip().lower()
        if depth not in {"standard", "deep"}:
            raise ValueError("analysis_depth 仅支持 standard 或 deep")
        if depth != cur.get("analysis_depth"):
            diffs.append({"field": "analysis_depth", "label": "自进化复盘深度", "before": str(cur.get("analysis_depth")), "after": depth})
            payload["analysis_depth"] = depth

    if args.get("start_time"):
        st = str(args["start_time"]).strip()
        if st != cur.get("start_time"):
            diffs.append({"field": "start_time", "label": "复盘起算时间", "before": str(cur.get("start_time")), "after": st})
            payload["start_time"] = st

    if not diffs:
        raise ValueError("自进化配置与当前完全一致，无变更")

    return {
        "id": _item_id(),
        "domain": "evolution",
        "action": "update",
        "title": f"更新自进化配置（{len(diffs)} 项）",
        "reason": str(args.get("reason") or "").strip(),
        "payload": payload,
        "diff_type": "kv",
        "diff": diffs,
        "warnings": [],
        "high_risk": False,
        "required_phrase": "",
        "required_phrase_reason": "",
    }


def _propose_memory_mutation(args: Dict[str, Any]) -> Dict[str, Any]:
    from scripts import evolution_shield

    action = str(args.get("action") or "").strip().lower()
    reason = str(args.get("reason") or "").strip()
    view = evolution_shield.admin_memory_view()
    lessons = view.get("structured_lessons") or []

    if action == "add":
        text = str(args.get("text") or "").strip()
        if not text or len(text) > 1000:
            raise ValueError("心法内容长度须在 1~1000 字符之间")
        passed, shield_reason = evolution_shield.audit_proposed_lesson(text, sample_size=3)
        if not passed:
            raise ValueError(f"心法未通过宪法门禁校验：{shield_reason}")
        return {
            "id": _item_id(),
            "domain": "memory",
            "action": "add",
            "title": "新增自进化实战心法",
            "reason": reason,
            "payload": {"text": text},
            "diff_type": "kv",
            "diff": [{"field": "lesson", "label": "新增心法条目", "before": "—", "after": text}],
            "warnings": [],
            "high_risk": False,
            "required_phrase": "",
            "required_phrase_reason": "",
        }

    if action in {"toggle", "delete"}:
        lesson_id = str(args.get("lesson_id") or "").strip()
        target = next((item for item in lessons if isinstance(item, dict) and item.get("id") == lesson_id), None)
        if not target:
            raise ValueError(f"未找到心法条目：{lesson_id}")
        if action == "toggle":
            nxt_enabled = not bool(target.get("enabled", True))
            return {
                "id": _item_id(),
                "domain": "memory",
                "action": "toggle",
                "title": f"{'启用' if nxt_enabled else '停用'}心法：{str(target.get('rule_text') or '')[:32]}",
                "reason": reason,
                "payload": {"lesson_id": lesson_id},
                "diff_type": "kv",
                "diff": [{
                    "field": lesson_id,
                    "label": str(target.get("rule_text") or "")[:80],
                    "before": "启用" if target.get("enabled", True) else "停用",
                    "after": "启用" if nxt_enabled else "停用",
                }],
                "warnings": [],
                "high_risk": False,
                "required_phrase": "",
                "required_phrase_reason": "",
            }
        return {
            "id": _item_id(),
            "domain": "memory",
            "action": "delete",
            "title": f"删除心法：{str(target.get('rule_text') or '')[:32]}",
            "reason": reason,
            "payload": {"lesson_id": lesson_id},
            "diff_type": "kv",
            "diff": [{
                "field": lesson_id,
                "label": "删除条目",
                "before": str(target.get("rule_text") or ""),
                "after": "（已删除）",
            }],
            "warnings": [],
            "high_risk": False,
            "required_phrase": "",
            "required_phrase_reason": "",
        }

    if action == "reset":
        return {
            "id": _item_id(),
            "domain": "memory",
            "action": "reset",
            "title": f"清空全部 {len(lessons)} 条实战心法",
            "reason": reason,
            "payload": {},
            "diff_type": "kv",
            "diff": [{"field": "lessons", "label": "心法库条数", "before": str(len(lessons)), "after": "0"}],
            "warnings": ["该操作将清空所有已积累的心法（应用前会自动拍策略快照以便恢复）"],
            "high_risk": True,
            "required_phrase": "RESET MEMORY",
            "required_phrase_reason": "清空全部自进化实战心法",
        }

    raise ValueError(f"不支持的心法操作：{action}")


def _propose_policy_restore(args: Dict[str, Any]) -> Dict[str, Any]:
    from astra_backend.policy_snapshot import ARCHIVE_DIR, _resolve_archive_file, load_archive_index

    policy_hash = str(args.get("policy_hash") or "").strip()
    if not policy_hash or not re.fullmatch(r"[a-zA-Z0-9_-]+", policy_hash):
        raise ValueError(f"无效的策略快照标识：{policy_hash}")
    arch_file = _resolve_archive_file(ARCHIVE_DIR, policy_hash)
    if not arch_file.is_file():
        raise ValueError(f"未找到归档策略快照：{policy_hash}")
    entry = next(
        (i for i in load_archive_index() if i.get("policy_hash") == policy_hash or i.get("package_hash") == policy_hash),
        {"policy_hash": policy_hash, "name": policy_hash},
    )
    return {
        "id": _item_id(),
        "domain": "policy_restore",
        "action": "restore",
        "title": f"回滚整套策略至快照「{entry.get('name', policy_hash)}」",
        "reason": str(args.get("reason") or "").strip(),
        "payload": {"policy_hash": policy_hash},
        "diff_type": "kv",
        "diff": [
            {"field": "target_snapshot", "label": "目标策略快照", "before": "当前运行策略", "after": f"{entry.get('name', policy_hash)} ({policy_hash})"},
            {"field": "archived_at", "label": "快照归档时间", "before": "—", "after": str(entry.get("archived_at") or "—")},
        ],
        "warnings": ["将同时恢复该快照对应的提示词方案、心法库、投委会与风控参数（恢复前会自动拍当前快照兜底）"],
        "high_risk": False,
        "required_phrase": "",
        "required_phrase_reason": "",
    }


def _propose_order_mode_update(args: Dict[str, Any]) -> Dict[str, Any]:
    import os
    from astra_backend.config import settings

    target = str(args.get("order_mode") or "").strip().lower()
    if target not in {"limit", "market", "smart"}:
        raise ValueError(f"不支持的委托订单模式：{target}（允许 limit / market / smart）")
    current = (os.getenv("ASTRA_ORDER_MODE") or getattr(settings, "order_mode", "limit") or "limit").strip().lower()
    if current == target:
        raise ValueError(f"当前委托订单模式已为 {current}，无需重复修改")
    labels = {
        "limit": "限价单 (limit)",
        "market": "市价单 (market)",
        "smart": "智能自适应 (smart)",
    }
    return {
        "id": _item_id(),
        "domain": "order_mode",
        "action": "update",
        "title": f"切换委托订单模式为 {labels[target]}",
        "reason": str(args.get("reason") or "").strip(),
        "payload": {"order_mode": target},
        "diff_type": "kv",
        "diff": [
            {"field": "ASTRA_ORDER_MODE", "label": "委托订单模式", "before": labels.get(current, current), "after": labels[target]},
        ],
        "warnings": ["smart 模式在近盘/高置信度机会下自动采用市价极速吃单并重锚保护腿，深回踩位仍挂限价单"] if target == "smart" else [],
        "high_risk": False,
        "required_phrase": "",
        "required_phrase_reason": "",
    }


def _propose_ops_action(args: Dict[str, Any]) -> Dict[str, Any]:
    action = str(args.get("action") or "").strip().lower()
    reason = str(args.get("reason") or "").strip()
    meta = {
        "run_dry_run": {
            "title": "执行一轮实时决策快照预演 (Dry-Run)",
            "after": "立即基于最新行情与策略触发只读预演",
            "warnings": ["仅执行推演诊断，不产生实际委托单"],
            "high_risk": False,
            "phrase": "",
            "phrase_reason": "",
        },
        "trigger_evolution_review": {
            "title": "触发一次自进化认知复盘 (Evolution Review)",
            "after": "拉起 self_improvement_engine 执行一次只读账本复盘",
            "warnings": ["仅触发复盘分析与记忆评估，不改变实盘头寸"],
            "high_risk": False,
            "phrase": "",
            "phrase_reason": "",
        },
        "cancel_stale_limit_orders": {
            "title": "清理超期或失效限价挂单意图",
            "after": "清理超过 TTL 的过期挂单意图记录（不强制平已有持仓）",
            "warnings": ["请核对在途挂单情况；执行后将清除过期挂单意图等待下一轮重评估"],
            "high_risk": True,
            "phrase": "CANCEL STALE ORDERS",
            "phrase_reason": "清理过期或失效的限价挂单意图",
        },
    }
    if action not in meta:
        raise ValueError(f"不支持的运维动作：{action}")
    spec = meta[action]
    return {
        "id": _item_id(),
        "domain": "ops_action",
        "action": action,
        "title": spec["title"],
        "reason": reason,
        "payload": {"action": action},
        "diff_type": "kv",
        "diff": [
            {"field": "ops_action", "label": "运维执行动作", "before": "待审批触发", "after": spec["after"]},
        ],
        "warnings": list(spec["warnings"]),
        "high_risk": bool(spec["high_risk"]),
        "required_phrase": spec["phrase"],
        "required_phrase_reason": spec["phrase_reason"],
    }


WRITE_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "propose_risk_update",
        "description": "生成「风控参数/预设套件」变更提案卡片（不直接写盘，须用户点击确认后生效）。",
        "parameters": {
            "type": "object",
            "properties": {
                "suite_id": {"type": "string", "enum": ["conservative", "balanced", "aggressive"], "description": "可选：应用整套风控预设"},
                "values": {"type": "object", "description": "需要调整的 ASTRA_* 风控键与原生值（比例用小数如 0.25 表示 25%）"},
                "reason": {"type": "string", "description": "给用户看的修改原因说明"},
            },
        },
    },
    {
        "name": "propose_risk_reset",
        "description": "生成「重置风控为出厂基线」提案卡片（需二次确认 RESET RISK）。",
        "parameters": {
            "type": "object",
            "properties": {"reason": {"type": "string"}},
        },
    },
    {
        "name": "propose_prompt_edit",
        "description": "生成「提示词方案编辑/新增/启停/克隆/切换/回滚」提案卡片（默认精准编辑当前激活方案模块，只读 JSON 输出契约不可篡改）。",
        "parameters": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {"type": "string", "enum": ["edit_module", "add_module", "toggle_module", "clone_profile", "activate_profile", "rollback_profile"]},
                "profile_id": {"type": "string", "description": "目标方案 ID，留空默认当前激活方案"},
                "pipeline": {"type": "string", "enum": ["trading_system", "trading_user", "evolution_system", "evolution_user"]},
                "module_id": {"type": "string", "description": "要编辑/启停的模块 ID（先用 get_prompt_library 查看）"},
                "module_title": {"type": "string", "description": "模块标题（匹配或新增模块名）"},
                "content": {"type": "string", "description": "修改后或新增模块的完整正文"},
                "enabled": {"type": "boolean", "description": "模块启停状态"},
                "new_name": {"type": "string", "description": "clone_profile 时的新方案名称"},
                "description": {"type": "string", "description": "clone_profile 时的方案说明"},
                "activate": {"type": "boolean", "description": "clone_profile 后是否立即激活"},
                "revision_id": {"type": "string", "description": "rollback_profile 时的修订 ID"},
                "reason": {"type": "string"},
            },
        },
    },
    {
        "name": "propose_council_update",
        "description": "生成「多模型投委会」变更提案卡片（总开关、仲裁模式、超时、各席位权重/模型/提示词）。",
        "parameters": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "consensus_mode": {"type": "string", "enum": ["standard", "cross_examination", "debate"]},
                "timeout_seconds": {"type": "number"},
                "role_updates": {"type": "object", "description": "按 role_id 映射要修改的席位字段"},
                "reason": {"type": "string"},
            },
        },
    },
    {
        "name": "propose_instrument_change",
        "description": "生成「交易标的池新增/移除」提案卡片（移除遵循持仓 Fail-Closed 与 BTC 保底红线）。",
        "parameters": {
            "type": "object",
            "required": ["action", "inst_id"],
            "properties": {
                "action": {"type": "string", "enum": ["add", "remove"]},
                "inst_id": {"type": "string", "description": "永续合约标识，如 AVAX-USDT-SWAP"},
                "reason": {"type": "string"},
            },
        },
    },
    {
        "name": "propose_trading_session_update",
        "description": "生成「交易时段闸门」变更提案卡片（控制允许 AI 决策开仓的北京时间窗口）。",
        "parameters": {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "mode_outside": {"type": "string", "enum": ["manage_only", "off"]},
                "windows": {"type": "array", "items": {"type": "object"}, "description": "[{days:[0..6], start:'HH:MM', end:'HH:MM'}]"},
                "reason": {"type": "string"},
            },
        },
    },
    {
        "name": "propose_llm_settings_update",
        "description": "生成「交易 LLM 全局设置」变更提案卡片（切换已登记主脑模型、思考强度、超时、重试次数与回退链；绝不触碰密钥）。",
        "parameters": {
            "type": "object",
            "properties": {
                "active_model_id": {"type": "string"},
                "reasoning_effort": {"type": "string", "enum": ["none", "minimal", "low", "medium", "high", "auto"]},
                "thinking_timeout": {"type": "number"},
                "request_attempts": {"type": "integer"},
                "fallback_model_ids": {"type": "array", "items": {"type": "string"}},
                "reason": {"type": "string"},
            },
        },
    },
    {
        "name": "propose_evolution_config_update",
        "description": "生成「自进化引擎专属配置」变更提案卡片（模型、思考强度、超时、复盘深度与起算时间）。",
        "parameters": {
            "type": "object",
            "properties": {
                "model_id": {"type": "string"},
                "reasoning_effort": {"type": "string", "enum": ["low", "medium", "high", "max"]},
                "thinking_timeout": {"type": "number"},
                "analysis_depth": {"type": "string", "enum": ["standard", "deep"]},
                "start_time": {"type": "string"},
                "reason": {"type": "string"},
            },
        },
    },
    {
        "name": "propose_memory_mutation",
        "description": "生成「自进化心法库增删改开关」提案卡片（新增条目须通过宪法红线校验）。",
        "parameters": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {"type": "string", "enum": ["add", "toggle", "delete", "reset"]},
                "text": {"type": "string", "description": "action=add 时的心法文本"},
                "lesson_id": {"type": "string", "description": "action=toggle/delete 时的心法 ID"},
                "reason": {"type": "string"},
            },
        },
    },
    {
        "name": "propose_policy_restore",
        "description": "生成「回滚整套策略快照」提案卡片（应用前同样会先拍当前快照保护）。",
        "parameters": {
            "type": "object",
            "required": ["policy_hash"],
            "properties": {
                "policy_hash": {"type": "string", "description": "目标快照的 policy_hash 或 package_hash"},
                "reason": {"type": "string"},
            },
        },
    },
    {
        "name": "propose_order_mode_update",
        "description": "生成「切换委托订单执行模式 (limit / market / smart)」提案卡片，不直接落盘。",
        "parameters": {
            "type": "object",
            "required": ["order_mode"],
            "properties": {
                "order_mode": {"type": "string", "enum": ["limit", "market", "smart"], "description": "目标委托执行模式"},
                "reason": {"type": "string", "description": "变更原因"},
            },
        },
    },
    {
        "name": "propose_ops_action",
        "description": "生成可控运维触发提案卡片（执行实景预演 run_dry_run、触发自进化复盘 trigger_evolution_review、或清理过期挂单 cancel_stale_limit_orders）。",
        "parameters": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {"type": "string", "enum": ["run_dry_run", "trigger_evolution_review", "cancel_stale_limit_orders"]},
                "reason": {"type": "string", "description": "触发原因"},
            },
        },
    },
]

_WRITE_BUILDERS = {
    "propose_risk_update": _propose_risk_update,
    "propose_risk_reset": _propose_risk_reset,
    "propose_prompt_edit": _propose_prompt_edit,
    "propose_council_update": _propose_council_update,
    "propose_instrument_change": _propose_instrument_change,
    "propose_trading_session_update": _propose_trading_session_update,
    "propose_llm_settings_update": _propose_llm_settings_update,
    "propose_evolution_config_update": _propose_evolution_config_update,
    "propose_memory_mutation": _propose_memory_mutation,
    "propose_policy_restore": _propose_policy_restore,
    "propose_order_mode_update": _propose_order_mode_update,
    "propose_ops_action": _propose_ops_action,
}


def is_write_proposal_tool(name: str) -> bool:
    return name in _WRITE_BUILDERS


def build_proposal_item(name: str, args: Dict[str, Any]) -> Dict[str, Any]:
    builder = _WRITE_BUILDERS.get(name)
    if not builder:
        raise ValueError(f"未知提案构造工具：{name}")
    return builder(args or {})
