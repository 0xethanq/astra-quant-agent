"""Binance/Gate 后台一次性平仓意图（三所平权；OKX 意图走 okx_trade_service 自有存储）。

与 OKX 平仓契约同构：服务端随机令牌登记 · 90 秒时效 · 环境绑定 · 口令短语全等 ·
消费前仓位数量二次校验 · 平仓后回读归零核验。ASTRA-BUGFIX 2026-09-13：修复合并快照
伪造 `token-venue-...` 假令牌导致非 OKX 仓位平仓必然「令牌无效或已使用」的回归。
"""
from __future__ import annotations
import secrets
import threading
import time
from typing import Any

_INTENTS: dict[str, dict[str, Any]] = {}
_LOCK = threading.Lock()
INTENT_TTL_SECONDS = 90


# 三所档位轴：OKX env.mode(demo/live) 为全站唯一档位；gate demo→sandbox，binance 同名。
# 唯一定义点（审计 C3：ai_factor_trader/ exchanges 等所有非 OKX 适配器路径都应引用本表）。
ADAPTER_ENV = {"binance": {"demo": "demo", "live": "live"}, "gate": {"demo": "sandbox", "live": "live"}}
_ADAPTER_ENV = ADAPTER_ENV


def adapter_environment(venue: str, mode: str) -> str:
    """OKX 档位轴 → 该所适配器档位（未知轴值原样透传给适配器自校验）。"""
    return ADAPTER_ENV.get(str(venue or "").lower(), {}).get(str(mode or "").lower(), str(mode or ""))


def _current_credential_fp(venue: str, adapter_env: str) -> str:
    from astra_backend.exchanges import venue_credentials
    from astra_backend.exchanges.identity import credential_fingerprint
    try:
        api_key, _ = venue_credentials(venue, adapter_env)
    except Exception:
        api_key = ""
    return credential_fingerprint(api_key)


def create(*, venue: str, environment: str, display_inst: str, symbol: str,
           pos_side: str, expected_size: float, credential_fingerprint: str = "") -> tuple[str, str]:
    """登记一次平仓意图，返回 (token, confirmation)。confirmation 由前端逐字回显。"""
    token = secrets.token_urlsafe(32)
    confirmation = f"CLOSE {venue.upper()} {environment.upper()} {display_inst} {pos_side.upper()} {float(expected_size):g}"
    record: dict[str, Any] = {
        "venue": venue, "environment": environment, "display_inst": display_inst,
        "symbol": symbol, "pos_side": pos_side, "expected_size": float(expected_size),
        "confirmation": confirmation, "expires_at": time.time() + INTENT_TTL_SECONDS,
        "credential_fingerprint": str(credential_fingerprint or ""),
    }
    with _LOCK:
        now = time.time()
        for stale in [key for key, value in _INTENTS.items() if value["expires_at"] < now]:
            _INTENTS.pop(stale, None)
        _INTENTS[token] = record
    return token, confirmation


def peek(token: str) -> dict[str, Any] | None:
    """只读窥视（不消费）：用于口令/环境预检，避免输错口令烧掉一次性令牌。"""
    with _LOCK:
        intent = _INTENTS.get(str(token))
        return dict(intent) if intent else None


def consume(token: str) -> dict[str, Any]:
    """一次性消费；缺失/过期抛 ValueError（文案与 OKX 通道同构，fail-closed）。"""
    with _LOCK:
        intent = _INTENTS.pop(str(token), None)
    if not intent:
        raise ValueError("平仓令牌无效或已使用，请刷新当前持仓")
    if intent["expires_at"] < time.time():
        raise ValueError("平仓令牌已过期，请刷新当前持仓")
    return intent


# （_ADAPTER_ENV 已上移至文件头唯一定义——审计 C3 单一事实源）


def _pos_side(size_signed: float) -> str:
    return "long" if size_signed > 0 else "short"


def venue_fast_close(venue: str, environment: str, token: str, confirmation: str) -> dict[str, Any]:
    """Binance/Gate 市价全平：口令预检→一次性消费→数量回验→平仓→归零核验。

    返回与 OKX ``fast_close_confirmed`` 同构，供审计与前端复用；任一核验失败均
    fail-closed 抛异常（ValueError→409，其余→502），绝不静默半平。
    """
    if venue not in _ADAPTER_ENV:
        raise ValueError(f"不支持的平仓场所：{venue}")
    pending = peek(token)
    if not pending:
        # 令牌缺失：交由上层转 409；此处不消费任何状态
        raise ValueError("平仓令牌无效或已使用，请刷新当前持仓")
    if str(pending["environment"]) != str(environment):
        raise ValueError(f"{venue.upper()} 环境已切换为 {environment}，请刷新当前持仓")
    if str(confirmation or "").strip().upper() != str(pending["confirmation"]):
        raise ValueError(f"确认短语必须精确为：{pending['confirmation']}")
    adapter_env = adapter_environment(venue, environment)
    # 审计 B3（对齐 OKX env.identity 强度）：快照签发与此刻之间若发生过凭证轮换，
    # 旧令牌会打到新账户——按 api_key 指纹钉死，指纹漂移即拒绝并令刷新。
    pinned_fp = str(pending.get("credential_fingerprint") or "")
    live_fp = _current_credential_fp(venue, adapter_env)
    if pinned_fp and pinned_fp != live_fp:
        raise ValueError(f"{venue.upper()} API Key 已轮换（指纹 {pinned_fp}→{live_fp}），请刷新当前持仓后重新签发")
    intent = consume(token)
    from astra_backend.exchanges import get_adapter
    ad = get_adapter(venue, environment=adapter_env)
    sym = str(intent["symbol"])
    expected = float(intent["expected_size"])
    want_side = str(intent["pos_side"])

    def _live_size() -> float:
        for row in (ad.positions() or []):
            base = str(row.get("base") or (str(row.get("symbol") or "").split("-")[0]))
            if base != sym:
                continue
            amt = float(row.get("size_signed", 0) or 0)
            if abs(amt) < 1e-12 or _pos_side(amt) != want_side:
                continue
            return abs(amt)
        return 0.0

    current = _live_size()
    if current <= 1e-12:
        raise ValueError("目标仓位已不存在，请刷新")
    tolerance = max(1e-12, current * 1e-6)
    if abs(current - expected) > tolerance:
        raise ValueError(f"仓位数量已从 {expected:g} 变化为 {current:g}，请刷新")
    import inspect
    kwargs: dict[str, Any] = {}
    try:
        if "pos_side" in inspect.signature(ad.fast_close_position).parameters:
            kwargs["pos_side"] = want_side
    except (TypeError, ValueError):
        pass
    raw = ad.fast_close_position(sym, **kwargs)
    if isinstance(raw, dict) and raw.get("closed") is False:
        raise RuntimeError(f"平仓未受理：{raw.get('reason') or raw}")
    remaining = current
    for _ in range(6):
        time.sleep(0.6)
        remaining = _live_size()
        if remaining <= tolerance:
            break
    if remaining > tolerance:
        raise RuntimeError(f"平仓请求已受理但仓位未确认归零，剩余 {remaining:g}；请刷新，禁止重复点击")
    return {"status": "confirmed_closed", "environment": str(environment), "venue": venue,
            "instId": str(intent["display_inst"]), "posSide": want_side, "closed_size": current,
            "close_result": raw}

