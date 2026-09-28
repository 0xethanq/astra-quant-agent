"""Exchange credentials, venue status, and account snapshot routes (OKX-only)."""
from __future__ import annotations
import json
import time
from typing import Any
from fastapi import APIRouter, Header, HTTPException, Query

from astra_backend.config import settings, refresh_settings
from astra_backend.settings_store import update_env
from astra_backend.audit import record as audit_record
from astra_backend.dependencies import (
    DATA_DIR, app_attr, require_admin_header, require_superadmin,
)
from astra_backend.schemas import (
    MultiExchangeUpdate,
    VenueTestConnectionRequest,
)
from astra_backend.okx_trade_service import account_snapshot as okx_account_snapshot
from scripts.okx_rest import OKXNotConfigured
from astra_gateway.secrets import save_secrets

router = APIRouter(tags=["exchanges"])


@router.get("/api/v1/account/positions")
def positions(x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token)
    from scripts.okx_runtime import current_environment
    from astra_backend.dependencies import okx
    env = current_environment()
    if not env.configured:
        raise HTTPException(status_code=503, detail=f"OKX {env.mode.upper()} NOT READY：请在后台配置完整 API Key 三件套")
    try:
        return {"positions": okx.positions(env=env), "source": "OKX REST"}
    except OKXNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"OKX account request failed: {exc}") from exc


_VENUE_ACCOUNT_FIELDS = ("equity", "available", "positions_count", "open_orders_count")

_LISTING_ENV_MAP: dict[str, dict[str, str]] = {
    "okx": {"demo": "demo", "live": "live"},
}


def _venue_account_unknown(status: str, reason: str) -> dict[str, Any]:
    out: dict[str, Any] = {"status": status, "reason": reason}
    for f in _VENUE_ACCOUNT_FIELDS:
        out[f] = None
    # 第一百六十九刀：`last_sync_ts` → **`last_sync_ms`**（值一直是毫秒，名字在说谎）。
    # 本字段只出现在本接口的响应里（不落盘），仓库内无旧名读者；前端 store 已同步改名。
    out["last_sync_ms"] = None
    return out


def _venue_accounts_okx(environment: str) -> dict[str, Any]:
    from scripts.okx_runtime import current_environment
    try:
        env = current_environment()
    except Exception as exc:
        return _venue_account_unknown("unavailable", f"OKX 环境解析失败: {type(exc).__name__}: {exc}")
    if env.mode != environment:
        # 「档位不符」四个字是 `test_venue_accounts_endpoint.py` 钉住的判定词，
        # 也是前端 `VenueAccountCard.statusMeta` 归到「环境不符」态的判据之一
        # （另一个是「跨档」）—— 改写文案时不要把它顺手删掉。
        return _venue_account_unknown(
            "unavailable",
            f"当前请求为 {environment.upper()} 环境，OKX 后台配置为 {env.mode.upper()} —— 档位不符，"
            "已拦截跨档读取；请在后台「账户与标的」切换档位")
    if not env.configured:
        return _venue_account_unknown(
            "unavailable",
            f"OKX {env.mode.upper()} 静态 API Key 三件套未配置，未发起任何请求；"
            "请在后台「账户接入」录入后自动出现")
    try:
        from scripts import okx_rest
        bal = okx_rest.request("GET", "/api/v5/account/balance", {"ccy": "USDT"}, env=env)
        pos = okx_rest.request("GET", "/api/v5/account/positions", {"instType": "SWAP"}, env=env)
        pend = okx_rest.request("GET", "/api/v5/trade/orders-pending", {"instType": "SWAP"}, env=env)
    except OKXNotConfigured as exc:
        return _venue_account_unknown("unavailable", f"OKX 凭证失效：{exc}")
    except Exception as exc:
        return _venue_account_unknown("degraded", f"OKX 账户读取失败: {type(exc).__name__}: {exc}")
    out = {"status": "ready", "reason": f"OKX {env.mode.upper()} 直签只读"}
    try:
        row = (bal or [{}])[0]
        usdt_detail = None
        for d in (row.get("details") or []):
            if str(d.get("ccy", "")).upper() == "USDT":
                usdt_detail = d
                break

        if usdt_detail and (usdt_detail.get("eq") not in (None, "") or usdt_detail.get("cashBal") not in (None, "")):
            eq_val = float(usdt_detail.get("eq") or usdt_detail.get("cashBal") or 0.0)
            avail_val = float(usdt_detail.get("availEq") or usdt_detail.get("availBal") or eq_val)
        else:
            eq_val = float(row.get("totalEq") or row.get("eq") or 0.0)
            avail_val = float(usdt_detail.get("availEq") or usdt_detail.get("availBal") or eq_val) if usdt_detail else eq_val

        out["equity"] = eq_val if eq_val > 0 else None
        out["available"] = avail_val
        out["positions_count"] = sum(1 for p in (pos or []) if abs(float(p.get("pos") or 0)) > 1e-12)
        out["open_orders_count"] = len(pend or [])
        out["last_sync_ms"] = int(time.time() * 1000)
    except Exception as exc:
        return _venue_account_unknown("degraded", f"OKX 返回解析失败: {type(exc).__name__}: {exc}")
    return out


@router.get("/api/v1/admin/multi-exchange")
def admin_multi_exchange_status(x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token)
    from astra_backend.exchanges import venue_credentials, venue_passphrase
    # 外所凭证卡已随外所下架移除：`venues` 保留空字典只为维持响应形状
    # （前端据 `venues` 是否存在渲染"多交易所"区块；本仓收口后恒为空）。
    venues: dict[str, Any] = {}
    def _read_creds(v: str, env: str | None = None) -> tuple[str, str]:
        try:
            return venue_credentials(v, env)
        except TypeError:
            return venue_credentials(v)

    from scripts.okx_runtime import current_environment
    okx_env = current_environment()
    okx_live_ak, okx_live_sk = _read_creds("okx", "live")
    okx_demo_ak, okx_demo_sk = _read_creds("okx", "demo")
    try:
        okx_live_pp = venue_passphrase("okx", "live")
        okx_demo_pp = venue_passphrase("okx", "demo")
    except Exception:
        okx_live_pp, okx_demo_pp = "", ""
    accounts_status = {
        "okx": {
            "live": {"has_api_key": bool(okx_live_ak), "has_secret": bool(okx_live_sk), "has_passphrase": bool(okx_live_pp)},
            "demo": {"has_api_key": bool(okx_demo_ak), "has_secret": bool(okx_demo_sk), "has_passphrase": bool(okx_demo_pp)},
        },
    }

    health: dict[str, Any] = {}
    try:
        health_path = DATA_DIR / "venue_health.json"
        if health_path.exists():
            health = json.loads(health_path.read_text(encoding="utf-8"))
    except Exception:
        health = {}

    # 保证 OKX 健康度与延迟展示
    if "venues" in health and "okx" in health["venues"]:
        okx_h = health["venues"]["okx"]
        okx_h["testnet"] = bool(okx_env.simulated)
        if not okx_h.get("avg_ms"):
            try:
                from astra_backend.exchanges.diagnostics import diagnose_venue_connection
                diag = diagnose_venue_connection("okx", "demo" if okx_env.simulated else "live", timeout=2.5)
                if diag.get("latency_ms"):
                    okx_h["avg_ms"] = diag["latency_ms"]
            except Exception:
                pass

    from astra_backend.exchanges import routing_policy
    pref = routing_policy.load_preferred_venue()
    return {"venues": venues, "health": health, "preferred_venue": pref,
            "routing_mode": routing_policy.load_routing_mode(),
            "accounts_status": accounts_status}


@router.put("/api/v1/admin/multi-exchange")
def admin_multi_exchange_update(payload: MultiExchangeUpdate,
                                x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    secret_map = {
        "OKX_LIVE_API_KEY": payload.okx_live_api_key,
        "OKX_LIVE_SECRET_KEY": payload.okx_live_secret_key,
        "OKX_LIVE_PASSPHRASE": payload.okx_live_passphrase,
        "OKX_DEMO_API_KEY": payload.okx_demo_api_key,
        "OKX_DEMO_SECRET_KEY": payload.okx_demo_secret_key,
        "OKX_DEMO_PASSPHRASE": payload.okx_demo_passphrase,
    }
    secret_values = {k: str(v).strip() for k, v in secret_map.items() if v and str(v).strip()}
    fn_save_secrets = app_attr("save_secrets", save_secrets)
    fn_update_env = app_attr("update_env", update_env)
    fn_refresh_settings = app_attr("refresh_settings", refresh_settings)
    rec_audit = app_attr("audit_record", audit_record)
    if secret_values:
        fn_save_secrets(secret_values)
    env_values: dict[str, Any] = {}
    if payload.okx_execution is not None:
        if payload.confirmation.strip().upper() != "OPEN OKX EXECUTION":
            raise HTTPException(status_code=400,
                                detail="变更执行开关确认短语必须精确为：OPEN OKX EXECUTION")
        env_values["ASTRA_OKX_EXECUTION"] = "1" if payload.okx_execution else "0"
    if payload.okx_environment is not None:
        env_values["ASTRA_OKX_ENV"] = "demo" if payload.okx_environment.lower() == "demo" else "live"
    if env_values:
        fn_update_env(env_values)
    fn_refresh_settings()
    if payload.preferred_venue is not None:
        from astra_backend.exchanges import routing_policy
        routing_policy.save_preferred_venue(payload.preferred_venue)
    if payload.routing_mode is not None:
        from astra_backend.exchanges import routing_policy
        if not routing_policy.save_routing_mode(payload.routing_mode):
            raise HTTPException(
                status_code=400,
                detail=f"非法 routing_mode，允许 {list(routing_policy.VALID_ROUTING_MODES)}")
    try:
        from astra_backend.exchanges import clear_instances
        clear_instances()
    except Exception:
        pass
    rec_audit("multi_exchange.update", "success", {
        "actor": actor["username"],
        "secret_keys_saved": sorted(secret_values.keys()),
        "env_updated": sorted(env_values.keys()),
        "preferred_venue": payload.preferred_venue,
        "routing_mode": payload.routing_mode,
    })
    refresh_settings()
    return {"ok": True, "saved_secret_keys": sorted(secret_values.keys())}


@router.post("/api/v1/admin/multi-exchange/test-connection")
def admin_multi_exchange_test_connection(
    payload: VenueTestConnectionRequest,
    x_astra_admin_token: str | None = Header(default=None),
) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token)
    from astra_backend.exchanges.diagnostics import diagnose_venue_connection

    result = diagnose_venue_connection(
        venue=payload.venue,
        environment=payload.environment,
        api_key=payload.api_key,
        secret_key=payload.secret_key,
        passphrase=payload.passphrase,
        timeout=payload.timeout,
    )
    audit_record("multi_exchange.test_connection", "success" if result.get("ok") else "failed", {
        "venue": payload.venue,
        "environment": payload.environment,
        "authenticated": result.get("authenticated"),
        "mode": result.get("mode"),
        "ok": result.get("ok"),
    })
    return result


@router.get("/api/v1/admin/okx/runtime")
def admin_okx_runtime(x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"), refresh: int = 0) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_session=x_astra_session)
    from scripts.okx_runtime import current_environment
    env = current_environment()
    mode_configured = env.configured
    payload: dict[str, Any] = {
        "environment": env.mode,
        "mode_configured": bool(mode_configured),
        "live_configured": bool(settings.okx_live_configured),
        "demo_configured": bool(settings.okx_demo_configured),
        "fingerprint": env.fingerprint,
        "base_url": env.base_url,
        "connection": "static-v5-key",
        "status": "READY" if mode_configured else "NOT_READY",
    }
    if not mode_configured:
        payload["not_ready_reason"] = "未配置 OKX API Key：请在后台「账户接入」填入当前档位（DEMO/LIVE）的 API Key / Secret Key / Passphrase 三件套；未配置时系统禁止一切交易。"
    return payload


@router.get("/api/v1/admin/okx/account-snapshot")
def admin_okx_account_snapshot(
    x_astra_admin_token: str | None = Header(default=None),
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")
) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token, x_astra_session)
    from scripts.okx_runtime import current_environment
    env = current_environment()

    combined_positions: list[dict[str, Any]] = []
    combined_orders: list[dict[str, Any]] = []
    venue_errors: dict[str, str] = {}

    try:
        fn_snap = app_attr("okx_account_snapshot", okx_account_snapshot)
        okx_snap = fn_snap()
        for p in (okx_snap.get("positions") or []):
            p_copy = dict(p)
            p_copy.setdefault("venue", "okx")
            imr = float(p.get("imr", 0) or p.get("margin", 0) or 0)
            if imr <= 0 and float(p.get("notionalUsd", 0) or 0) > 0 and float(p.get("lever", 0) or 0) > 0:
                imr = round(float(p.get("notionalUsd")) / float(p.get("lever")), 2)
            p_copy["margin"] = imr
            combined_positions.append(p_copy)
        for o in (okx_snap.get("orders") or []):
            o_copy = dict(o)
            o_copy.setdefault("venue", "okx")
            combined_orders.append(o_copy)
    except OKXNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # 审计 C6：所失败显式化，不再抹平为"完整"
        venue_errors["okx"] = f"{type(exc).__name__}: {str(exc)[:180]}"

    if not env.configured and not combined_positions and not combined_orders:
        raise HTTPException(status_code=503, detail=f"OKX {str(env.mode).upper()} API Key 未配置：V5 直签是唯一私有通道（fail-closed，无 CLI 回退）")

    return {
        "environment": env.mode,
        "environment_id": f"okx:{env.mode}:{env.fingerprint}",
        "credential_source": "multi-venue-aggregator",
        "positions": combined_positions,
        "orders": combined_orders,
        "venue_errors": venue_errors,
        "captured_at_ms": int(time.time() * 1000),
    }


@router.get("/api/v1/venue_accounts")
def venue_accounts(environment: str = Query(default="demo"),
                   x_astra_admin_token: str | None = Header(default=None),
                   x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    env_key = str(environment or "").strip().lower()
    if env_key not in ("demo", "live"):
        raise HTTPException(status_code=400, detail="environment 只允许 demo 或 live")
    require_admin_header(x_astra_admin_token, x_astra_session)
    venues_map = {
        "okx": _venue_accounts_okx(env_key),
    }
    from astra_backend.portfolio_aggregator import aggregate_venue_accounts
    summary = aggregate_venue_accounts(venues_map, env_key)
    return {
        "environment": env_key,
        "venues": venues_map,
        "portfolio_summary": summary,
        "captured_at_ms": int(time.time() * 1000),
    }


@router.get("/api/v1/listing_status")
def listing_status(environment: str = Query(default="demo"),
                   x_astra_admin_token: str | None = Header(default=None),
                   x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token, x_astra_session)
    env_key = str(environment or "").strip().lower()
    if env_key not in ("demo", "live"):
        raise HTTPException(status_code=400, detail="environment 只允许 demo 或 live")
    from astra_backend.exchanges.listing import listing_snapshot
    venues: dict[str, dict[str, Any]] = {}
    for venue in ("okx",):
        snap = listing_snapshot(venue, _LISTING_ENV_MAP[venue][env_key])
        venues[venue] = {
            "ok": snap.ok,
            "reason": snap.reason,
            "listed_count": snap.listed_count,
            "sample_symbols": getattr(snap, "sample_symbols", []),
            "source": snap.source,
            "checked_at": snap.checked_at,
        }
    return {
        "environment": env_key,
        "venues": venues,
        "captured_at_ms": int(time.time() * 1000),
    }
