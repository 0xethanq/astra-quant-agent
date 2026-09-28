"""OKX 账户凭证连接诊断引擎（US-003）。

支持 OKX 的 LIVE / DEMO（模拟盘）资金环境与凭证验证：
1. 既有凭证检测（从密钥库读取已加密凭证）
2. 预保存检测（用户录入 Key/Secret 但尚未提交保存，先做预检验证）
3. 零凭证回退（只读公共网络与行情端点连通性测试）

封闭三律遵守：
- 支持依赖注入测试（http_client / urlopen 可 mock）
- 错误信息全结构化返回，永不抛出 500
- 严格遵循 OKX V5 鉴权规范
- 永不在诊断响应中泄露 API Secret 或 Passphrase 明文
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from .identity import is_sandbox_environment
from .registry import venue_credentials, venue_passphrase

OKX_BASE_URL = "https://www.okx.com"


def _default_http_call(url: str, method: str = "GET", headers: Optional[Dict[str, str]] = None,
                       body: Optional[bytes] = None, timeout: float = 8.0) -> Tuple[int, Dict[str, Any], Dict[str, str]]:
    """标准 HTTP 请求封装；返回 (status_code, json_or_raw_dict, response_headers)。"""
    req = Request(url, data=body, headers=headers or {}, method=method.upper())
    try:
        with urlopen(req, timeout=timeout) as resp:
            status = getattr(resp, "status", 200)
            raw = resp.read().decode("utf-8", errors="replace")
            try:
                data = json.loads(raw) if raw else {}
            except Exception:
                data = {"raw_text": raw[:500]}
            resp_headers = dict(resp.headers.items()) if hasattr(resp, "headers") else {}
            return status, data if isinstance(data, dict) else {"data": data}, resp_headers
    except HTTPError as exc:
        status = exc.code
        raw = ""
        try:
            raw = exc.read().decode("utf-8", errors="replace")
            data = json.loads(raw) if raw else {}
        except Exception:
            data = {"raw_text": raw[:500]}
        resp_headers = dict(exc.headers.items()) if hasattr(exc, "headers") else {}
        return status, data if isinstance(data, dict) else {"data": data}, resp_headers


def diagnose_venue_connection(
    venue: str,
    environment: str = "live",
    api_key: Optional[str] = None,
    secret_key: Optional[str] = None,
    passphrase: Optional[str] = None,
    timeout: float = 8.0,
    http_client: Optional[Callable[..., Tuple[int, Dict[str, Any], Dict[str, str]]]] = None,
) -> Dict[str, Any]:
    """诊断指定交易所及环境的连接与凭证有效性。

    入参：
    - venue: "okx"（唯一受支持场所；其他场所显式拒答）
    - environment: "live" | "demo" | "testnet" | "sandbox"
    - api_key/secret_key/passphrase: 显式指定则优先使用（预保存预检）；否则从加密库加载
    - timeout: 超时秒数
    - http_client: 可选注入，用于单元测试封闭性
    """
    v = str(venue or "").strip().lower()
    if v != "okx":
        return {
            "ok": False,
            "venue": v,
            "environment": environment,
            "authenticated": False,
            "mode": "invalid_venue",
            "message": f"不支持的交易所：{venue!r}，可用: ['okx']",
            "latency_ms": None,
            "details": {},
        }

    env = str(environment or "live").strip().lower()
    is_sandbox = is_sandbox_environment(env)
    caller = http_client or _default_http_call

    # 凭证归一化：仅当完全未提供凭证参数时（api_key is None and secret_key is None），才从密钥库加载已存凭证
    if api_key is None and secret_key is None:
        ak, sk = venue_credentials(v, env)
        if passphrase is None:
            pp = venue_passphrase(v, env)
        else:
            pp = str(passphrase or "").strip()
    else:
        ak = str(api_key or "").strip()
        sk = str(secret_key or "").strip()
        pp = str(passphrase or "").strip()

    has_credentials = bool(ak and sk)

    # 1. 零凭证情况：回退为公共端点网络连通性测试
    if not has_credentials:
        return _diagnose_public_ping(v, env, caller, timeout)

    # 2. 已认证私有端点探测
    t0 = time.monotonic()
    try:
        return _diagnose_okx(env, is_sandbox, ak, sk, pp, caller, timeout, t0)
    except Exception as exc:
        latency = max(1, round((time.monotonic() - t0) * 1000))
        return {
            "ok": False,
            "venue": v,
            "environment": env,
            "authenticated": False,
            "mode": "network_error",
            "latency_ms": latency,
            "message": f"连接异常: {type(exc).__name__} - {str(exc)[:180]}",
            "details": {"error_type": type(exc).__name__},
        }


def _diagnose_public_ping(venue: str, env: str, caller: Callable, timeout: float) -> Dict[str, Any]:
    t0 = time.monotonic()
    try:
        base_url = OKX_BASE_URL
        path = "/api/v5/public/time"

        status, data, _ = caller(f"{base_url}{path}", method="GET", timeout=timeout)
        latency = max(1, round((time.monotonic() - t0) * 1000))
        ok = (status == 200)
        return {
            "ok": ok,
            "venue": venue,
            "environment": env,
            "authenticated": False,
            "mode": "public_fallback",
            "latency_ms": latency,
            "message": f"{venue.upper()} 公共网络连通{'正常' if ok else '失败（HTTP ' + str(status) + '）'}（延迟 {latency}ms），未配置私有凭证",
            "details": {"status_code": status, "base_url": base_url, "endpoint": path},
        }
    except Exception as exc:
        latency = max(1, round((time.monotonic() - t0) * 1000))
        return {
            "ok": False,
            "venue": venue,
            "environment": env,
            "authenticated": False,
            "mode": "network_error",
            "latency_ms": latency,
            "message": f"{venue.upper()} 公共网络连通失败: {type(exc).__name__} - {str(exc)[:180]}",
            "details": {"error_type": type(exc).__name__},
        }


def _diagnose_okx(env: str, is_sandbox: bool, ak: str, sk: str, pp: str,
                   caller: Callable, timeout: float, t0: float) -> Dict[str, Any]:
    base_url = OKX_BASE_URL
    path = "/api/v5/account/balance?ccy=USDT"
    ts = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    prehash = f"{ts}GET{path}"
    sign = base64.b64encode(hmac.new(sk.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()).decode("utf-8")

    headers = {
        "OK-ACCESS-KEY": ak,
        "OK-ACCESS-SIGN": sign,
        "OK-ACCESS-TIMESTAMP": ts,
        "OK-ACCESS-PASSPHRASE": pp,
        "Accept": "application/json",
        "User-Agent": "ASTRA-Diag/1.0",
    }
    if is_sandbox:
        headers["x-simulated-trading"] = "1"

    status, data, _ = caller(f"{base_url}{path}", method="GET", headers=headers, timeout=timeout)
    latency = max(1, round((time.monotonic() - t0) * 1000))

    code = str(data.get("code") or "")
    msg = str(data.get("msg") or "")
    if status == 200 and code == "0":
        return {
            "ok": True,
            "venue": "okx",
            "environment": env,
            "authenticated": True,
            "mode": "authenticated",
            "latency_ms": latency,
            "message": f"OKX {env.upper()} 凭证鉴权成功，连接正常（延迟 {latency}ms）",
            "details": {"code": "0", "has_balance_data": bool(data.get("data"))},
        }
    else:
        err_msg = msg or f"HTTP {status}"
        return {
            "ok": False,
            "venue": "okx",
            "environment": env,
            "authenticated": False,
            "mode": "auth_failed",
            "latency_ms": latency,
            "message": f"OKX 鉴权失败: [{code or status}] {err_msg}",
            "details": {"status_code": status, "code": code, "msg": msg},
        }
