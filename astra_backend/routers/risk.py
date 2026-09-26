"""Risk constants, instrument pool, baseline capital, and position close routes."""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Body, Header, HTTPException, Query

from astra_backend.config import settings, refresh_settings
from astra_backend.settings_store import update_env, remove_env
from astra_backend.account_baseline import update_initial_capital
from astra_backend.audit import record as audit_record
from astra_backend import risk_config
from astra_backend.dependencies import (
    DATA_DIR, MAX_POOL_SIZE, MIN_POOL_SIZE, REQUEST_SESSION,
    app_attr, admin_auth, okx, read_json, require_admin_header, require_superadmin,
)
from astra_backend.schemas import (
    RiskConfigUpdate,
    RiskResetRequest,
    InitialCapitalUpdate,
    InstrumentAddRequest,
    InstrumentDeleteRequest,
    ManualCloseRequest,
)
from astra_backend.okx_trade_service import fast_close_confirmed
from scripts.okx_rest import OKXNotConfigured
from scripts.instrument_pool import from_okx_instrument, load_instruments, mutate_instruments, save_instruments

router = APIRouter(tags=["risk"])

# 审计 P1-5(2026-09-13)：持仓快照由 dashboard 后台线程每 2s 刷新；超过此年龄视为"未知"，
# 未知 ≠ 无持仓（缺失≠0 红线）→ 删除标的这种破坏性操作在未知态必须 fail-closed。
HELD_SNAPSHOT_MAX_AGE_S = 90.0


def _tracker_keys_for(inst_id: str, trackers: dict[str, Any]) -> list[str]:
    """真实 tracker key 形如 `BTC-USDT-SWAP_long`（ai_factor_trader 写入）——精确等值永远命中不了。"""
    coin = inst_id.split("-", 1)[0].upper()
    hits = []
    for key in trackers or {}:
        k = str(key).strip().upper()
        if k == inst_id or k.startswith(f"{inst_id}_") or k == coin or k.startswith(f"{coin}_"):
            hits.append(str(key))
    return sorted(hits)


def _live_holdings(inst_id: str) -> tuple[bool, list[str], str]:
    """多所合一实时持仓判定（只读 dashboard 缓存，零网络）。

    返回 (是否持仓, 持仓场所列表, 未知原因)。未知原因非空 = 无法确认持仓，调用方须 fail-closed。
    """
    coin = inst_id.split("-", 1)[0].upper()
    try:
        import astra_backend.dashboard_cache as dashboard_app
        cache = getattr(dashboard_app, "CACHE_DATA", None)
    except Exception as exc:  # 模块不可用/导入失败
        return False, [], f"持仓快照模块不可用：{exc}"
    if not isinstance(cache, dict):
        return False, [], "持仓快照不可用"
    positions = cache.get("positions")
    if not isinstance(positions, list):
        return False, [], "持仓快照缺失"
    health = cache.get("data_health") if isinstance(cache.get("data_health"), dict) else {}
    age = health.get("cache_age_seconds")
    if isinstance(age, (int, float)) and float(age) > HELD_SNAPSHOT_MAX_AGE_S:
        return False, [], f"持仓快照已过期 {float(age):.0f}s"
    venues = set()
    for item in positions:
        if not isinstance(item, dict):
            continue
        held = str(item.get("instId") or "").strip().upper()
        if not held:
            continue
        if held == inst_id or held.startswith(f"{coin}-") or held == coin:
            venues.add(str(item.get("venue") or "okx").strip().lower())
    return bool(venues), sorted(venues), ""


def _holdings_report(inst_id: str, trackers: dict[str, Any]) -> dict[str, Any]:
    keys = _tracker_keys_for(inst_id, trackers)
    held_live, venues, unknown = _live_holdings(inst_id)
    return {
        "tracker_keys": keys,
        "has_tracker": bool(keys),
        "held_live": held_live,
        "held_venues": venues,
        "holdings_unknown": unknown or None,
        "held": held_live or bool(keys),
    }


@router.get("/api/v1/admin/risk")
def admin_risk_get(equity: float | None = Query(default=None, description="可用权益（USDT），用于派生引擎当前口径"),
                   x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_session=x_astra_session)
    return {
        "schema": risk_config.schema(),
        "suites": risk_config.SUITES,
        "values": risk_config.current_values(),
        # 审计未完成清单#3：把"引擎此刻真正在用什么"和"下一周期会用什么"并排给出——
        # P0-2/P1-1 能长期隐身，正是因为页面上只有前者（文件值）没有后者（进程快照）。
        "process_values": risk_config.process_values(),
        "process_freshness": risk_config.process_freshness(),
        "file_vs_process": risk_config.file_vs_process_diff(),
        "engine_values": risk_config.effective_engine_values(equity),
        "effect": "交易引擎每 15 分钟一个巡检周期；子进程启动时重新读取 .env，保存后下一周期自动生效，无需重启后台。",
    }


@router.post("/api/v1/admin/risk")
def admin_risk_update(payload: RiskConfigUpdate, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    merged: dict[str, Any] = {}
    if payload.suite_id:
        try:
            merged.update(risk_config.suite_values(payload.suite_id))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    merged.update(payload.values)
    if not merged:
        raise HTTPException(status_code=400, detail="没有需要保存的修改")
    # 审计 P2-9：极端值（单标的占比≥50% / 日亏≥25% 权益 / 杠杆≥10x 等）必须逐字确认，
    # 否则一次误触即把硬风控放松到接近失效。阈值不是硬上限——显式确认后仍可越过。
    high_risk = risk_config.high_risk_changes(merged)
    if high_risk:
        if str(payload.confirmation or "").strip().upper() != risk_config.HIGH_RISK_PHRASE:
            audit_record("risk.config.update", "rejected_high_risk", {
                "actor": actor["username"], "items": high_risk,
            })
            detail = "；".join(f"{i['label']} = {i['value'] * 100 if 'RATIO' in i['key'] else i['value']:g}"
                              f"（阈值 {i['threshold'] * 100 if 'RATIO' in i['key'] else i['threshold']:g}）" for i in high_risk)
            raise HTTPException(
                status_code=400,
                detail=f"以下参数已进入极端区间，必须逐字确认 {risk_config.HIGH_RISK_PHRASE}：{detail}")
    before = risk_config.current_values()
    try:
        env_updates = risk_config.normalize(merged)
    except ValueError as exc:
        audit_record("risk.config.update", "failed", {"actor": actor["username"], "suite": payload.suite_id, "reason": str(exc)})
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    update_env(env_updates)
    refresh_settings()
    risk_config.reload_risk_constants()
    try:
        from scripts.instrument_pool import sync_pool_leverage_caps
        cur_v = risk_config.current_values()
        _sync_min = float(env_updates.get("ASTRA_MIN_LEVERAGE", cur_v.get("ASTRA_MIN_LEVERAGE", 2.0)))
        _sync_max = float(env_updates.get("ASTRA_MAX_LEVERAGE", cur_v.get("ASTRA_MAX_LEVERAGE", 5.0)))
        sync_pool_leverage_caps(min_leverage=_sync_min, max_leverage=_sync_max)
    except Exception:
        pass
    audit_record("risk.config.update", "success", {
        "actor": actor["username"],
        "suite": payload.suite_id or None,
        "changed": {k: {"before": before.get(k), "after": float(v)} for k, v in env_updates.items()},
        "high_risk_confirmed": [i["key"] for i in high_risk],
    })
    return {
        "updated": sorted(env_updates.keys()),
        "applied_suite": payload.suite_id or None,
        "values": risk_config.current_values(),
        "effect": "已写入 .env；下一交易巡检周期（≤15 分钟）起对新开仓/加仓/时间止损全面生效，AI 主脑提示词中的风控口径同步对齐。",
    }


@router.post("/api/v1/admin/risk/reset")
def admin_risk_reset(payload: RiskResetRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    refresh_settings()
    actor = require_superadmin(x_astra_session)
    if payload.confirmation.strip().upper() != "RESET RISK":
        raise HTTPException(status_code=400, detail="确认短语必须精确为：RESET RISK")
    remove_env(set(risk_config.reset_keys()))
    refresh_settings()
    risk_config.reload_risk_constants()
    try:
        from scripts.instrument_pool import sync_pool_leverage_caps
        cur_v = risk_config.current_values()
        sync_pool_leverage_caps(min_leverage=float(cur_v.get("ASTRA_MIN_LEVERAGE", 2.0)),
                                max_leverage=float(cur_v.get("ASTRA_MAX_LEVERAGE", 5.0)))
    except Exception:
        pass
    audit_record("risk.config.reset", "success", {"actor": actor["username"]})
    return {
        "reset": True,
        "values": risk_config.current_values(),
        "effect": "全部自定义风控覆盖值已清除，执行层回退到代码默认基线。",
    }


@router.put("/api/v1/admin/account-baseline")
def admin_update_account_baseline(payload: InitialCapitalUpdate, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    if payload.confirmation.strip().upper() != "UPDATE CAPITAL":
        raise HTTPException(status_code=400, detail="确认短语必须精确为：UPDATE CAPITAL")
    try:
        fn_update = app_attr("update_initial_capital", update_initial_capital)
        result = fn_update(payload.initial_capital)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    rec_audit = app_attr("audit_record", audit_record)
    rec_audit("account.baseline.update", "success", {
        "actor": actor["username"],
        "previous_initial_capital": result["previous_initial_capital"],
        "initial_capital": result["initial_capital"],
        "reset_time_preserved": result["reset_time"],
    })
    return {
        "updated": True,
        **result,
        "effect": "主页累计盈亏、累计 ROI 与权益基准线将按新本金重算；历史起算时间保持不变。",
    }


@router.get("/api/v1/admin/instruments")
def admin_instruments(x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token)
    trackers = read_json("position_trackers.json", {})
    if not isinstance(trackers, dict):
        trackers = {}
    rows = []
    for item in load_instruments():
        report = _holdings_report(item["instId"], trackers)
        rows.append({
            **item,
            "protected": item["instId"] == "BTC-USDT-SWAP",
            # 审计 P1-5：旧实现在这里拿 inst_id 直接 in trackers（真实键带 _long/_short 后缀）
            # → 恒 False，UI「存在持仓追踪记录，禁止删除」徽标与禁用态永不出现。
            "has_tracker": report["has_tracker"],
            "tracker_keys": report["tracker_keys"],
            "held_live": report["held_live"],
            "held_venues": report["held_venues"],
            "holdings_unknown": report["holdings_unknown"],
            "removable": item["instId"] != "BTC-USDT-SWAP" and not report["held"] and not report["holdings_unknown"],
        })
    stale = [row for row in rows if row["holdings_unknown"] and not row["protected"]]
    return {
        "instruments": rows,
        "limits": {"minimum": MIN_POOL_SIZE, "maximum": MAX_POOL_SIZE, "btc_required": True},
        "holdings_snapshot": {
            "source": "dashboard 多所合一持仓快照（2s 刷新）",
            "max_age_seconds": HELD_SNAPSHOT_MAX_AGE_S,
            # 只统计"本可删除但因持仓未知而暂停"的标的（BTC 属保底标的，恒不可删，不计入）
            "unknown_count": len(stale),
        },
    }


@router.post("/api/v1/admin/instruments")
def add_admin_instrument(payload: InstrumentAddRequest, x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token)
    inst_id = payload.inst_id.upper()
    try:
        matches = okx.instruments("SWAP", inst_id)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OKX 合约校验失败：{exc}") from exc
    raw = matches[0] if matches else {}
    if raw.get("instId") != inst_id or raw.get("settleCcy") != "USDT" or raw.get("state") != "live":
        raise HTTPException(status_code=400, detail="仅允许添加 OKX 在线可交易的 USDT 永续合约")
    item = from_okx_instrument(raw)

    # 审计 P2-6：load→校验→改→save 整段持锁（旧实现无锁 → 两个并发保存丢标的）；
    # 去重与容量不变量放进锁内，避免"检查通过后另一个请求插进来"。
    def _append(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if any(row["instId"] == inst_id for row in pool):
            raise HTTPException(status_code=409, detail="该币种已在交易池中")
        if len(pool) >= MAX_POOL_SIZE:
            raise HTTPException(status_code=409, detail=f"交易池最多允许 {MAX_POOL_SIZE} 个币种；请先删除一个无持仓币种，或调整环境变量 ASTRA_MAX_POOL_SIZE")
        return [*pool, item]

    updated = mutate_instruments(_append)
    audit_record("instrument.add", "success", {"instId": inst_id})
    return {"added": item, "count": len(updated), "effective": "immediate", "message": f"{item['name']} 已成功加入交易池并实时同步全网大屏与因果雷达"}


@router.delete("/api/v1/admin/instruments/{inst_id}")
def delete_admin_instrument(
    inst_id: str,
    payload: InstrumentDeleteRequest | None = Body(default=None),
    confirmation: str | None = None,
    x_astra_admin_token: str | None = Header(default=None),
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")
) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token, x_astra_session)
    inst_id = inst_id.upper()
    conf = ((payload.confirmation if payload else None) or confirmation or "").strip().upper()
    # 审计 P1-5：旧实现 `if conf and conf != ...` → 不传短语就免检，确认形同虚设。
    if conf != f"REMOVE {inst_id}":
        audit_record("instrument.remove", "rejected_phrase", {"instId": inst_id, "provided": bool(conf)})
        raise HTTPException(status_code=400, detail=f"必须提供确认短语（精确为：REMOVE {inst_id}）")
    if inst_id == "BTC-USDT-SWAP":
        raise HTTPException(status_code=403, detail="BTC 是全局黑天鹅哨兵基准，不允许从交易池删除")
    current = load_instruments()
    if len(current) <= MIN_POOL_SIZE:
        raise HTTPException(status_code=409, detail=f"交易池至少保留 {MIN_POOL_SIZE} 个币种")
    if not any(item["instId"] == inst_id for item in current):
        raise HTTPException(status_code=404, detail="该币种不在交易池中")
    trackers = read_json("position_trackers.json", {})
    if not isinstance(trackers, dict):
        trackers = {}
    report = _holdings_report(inst_id, trackers)
    if report["tracker_keys"]:
        audit_record("instrument.remove", "rejected_tracker", {"instId": inst_id, "tracker_keys": report["tracker_keys"]})
        raise HTTPException(status_code=409, detail=f"该币种存在持仓追踪记录（{', '.join(report['tracker_keys'])}），为防止失去风控接管，禁止删除")
    if report["held_live"]:
        audit_record("instrument.remove", "rejected_live_holdings", {"instId": inst_id, "venues": report["held_venues"]})
        raise HTTPException(status_code=409, detail=f"该币种在 {', '.join(report['held_venues'])} 仍有实时持仓，删除后将失去移动止损/时间止损/AI 平仓接管，禁止删除")
    if report["holdings_unknown"]:
        # 未知 ≠ 无持仓：拒绝而不是放行（破坏性操作 fail-closed）
        audit_record("instrument.remove", "rejected_unknown_holdings", {"instId": inst_id, "reason": report["holdings_unknown"]})
        raise HTTPException(status_code=503, detail=f"无法确认实时持仓（{report['holdings_unknown']}），为防止删掉有持仓的标的而失去风控接管，已拒绝删除；请稍后重试")
    # 审计 P2-6：删除也在锁内重读整池后再落盘——否则并发保存（例如另一页在改
    # 另一标的的参数）会被这份旧快照整份覆盖。
    updated = mutate_instruments(lambda pool: [item for item in pool if item["instId"] != inst_id])
    audit_record("instrument.remove", "success", {"instId": inst_id, "holdings_cleared": {"tracker_keys": [], "held_live": False}})
    return {"removed": inst_id, "count": len(updated), "effective": "immediate", "message": f"{inst_id} 已从交易池移除并实时同步全网大屏与因果雷达"}


@router.post("/api/v1/admin/positions/close")
def manual_close_position(payload: ManualCloseRequest) -> dict[str, Any]:
    actor = require_superadmin(REQUEST_SESSION.get())
    refresh_settings()
    from scripts.okx_runtime import current_environment
    _close_env = current_environment()
    _close_venue = str(getattr(payload, "venue", "") or "okx").strip().lower()
    if _close_venue not in ("okx", "binance", "gate"):
        raise HTTPException(status_code=400, detail=f"不支持的平仓场所：{_close_venue}")
    if _close_venue == "okx" and not _close_env.configured:
        raise HTTPException(status_code=503, detail=f"OKX {_close_env.mode.upper()} 静态 API Key 未配置（系统 NOT READY）：V5 直签是唯一私有通道，禁止后台手动平仓；请先在「账户接入」补齐完整三件套")
    if not settings.manual_close_enabled:
        raise HTTPException(status_code=403, detail="后台手动平仓功能未启用")
    import fcntl
    lock_path = DATA_DIR / ".ai_factor_trader.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    from astra_backend.dependencies import get_auth_store
    auth_store = get_auth_store()
    if actor.get("role") == "legacy" or not auth_store.verify_password(int(actor["id"]), payload.admin_password):
        raise HTTPException(status_code=403, detail="管理员密码验证失败")
    with lock_path.open("a+", encoding="utf-8") as lock_handle:
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise HTTPException(status_code=409, detail="交易主循环正在执行，暂不允许后台快速平仓；请等待本周期结束")
        try:
            if _close_venue == "okx":
                result = fast_close_confirmed(payload.close_token, payload.confirmation)
            else:
                from astra_backend.close_intent import venue_fast_close
                result = venue_fast_close(_close_venue, _close_env.mode, payload.close_token, payload.confirmation)
            audit_record("position.close", "confirmed_closed", {"instId": result.get("instId"), "side": result.get("posSide"), "venue": _close_venue, "environment": result.get("environment"), "size": result.get("closed_size"), "actor": actor.get("username", "admin")})
            return result
        except OKXNotConfigured as exc:
            audit_record("position.close", "rejected_not_ready", {"venue": _close_venue, "error": str(exc)[:300], "actor": actor.get("username", "admin")})
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            audit_record("position.close", "rejected", {"venue": _close_venue, "error": str(exc)[:300], "actor": actor.get("username", "admin")})
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            audit_record("position.close", "verification_failed", {"venue": _close_venue, "error": str(exc)[:300], "actor": actor.get("username", "admin")})
            raise HTTPException(status_code=502, detail=f"{_close_venue.upper()} 快速平仓未完成确认：{exc}") from exc
        finally:
            try:
                fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
