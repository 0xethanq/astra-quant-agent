"""聪明钱与大户多空明细数据采集模块（Pillar 5）。

为解决 OKX 内部 CLI 移除后聪明钱数据缺失（US-014 遗留）的问题，本模块提供单源采集：
1. 数据源：OKX Rubik 官方公开统计端点（合约多空账户数/持仓比 + 深度成交量）；
2. 容灾：数据源不可用时优雅返回 None，保留显式缺失语义，绝不伪造虚假中性信号。
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def _shared_cache_module():
    """在跨进程磁盘缓存激活时复用 okx_quant_factors 缓存，消除同周期重复 Rubik 请求。"""
    for mod_name in ("scripts.factors.okx_quant_factors", "factors.okx_quant_factors"):
        mod = sys.modules.get(mod_name)
        if mod is not None and callable(getattr(mod, "_disk_cache_enabled", None)):
            return mod if mod._disk_cache_enabled() else None
    try:
        from scripts.factors import okx_quant_factors as _qf
    except ImportError:
        try:
            from factors import okx_quant_factors as _qf
        except Exception:
            return None
    return _qf if getattr(_qf, "_disk_cache_enabled", lambda: False)() else None


def _rubik_hooks() -> Tuple[Callable[[str], None], Callable[[str], None]]:
    """Reuse the process-wide OKX Rubik rate-limiter (5 req / 2s per IP)."""
    try:
        from scripts.factors import okx_quant_factors as _qf
        return _qf._throttle_rubik, _qf._mark_rubik_called
    except ImportError:
        try:
            from factors import okx_quant_factors as _qf
            return _qf._throttle_rubik, _qf._mark_rubik_called
        except Exception:
            return (lambda _url: None), (lambda _url: None)


def _okx_rubik_get(
    url: str,
    timeout: float = 3.5,
    *,
    out_status: Optional[List[int]] = None,
) -> Optional[Dict[str, Any]]:
    """Fetch an OKX Rubik endpoint with shared throttling and 429 exponential backoff."""
    throttle_rubik, mark_rubik_called = _rubik_hooks()
    for attempt, backoff in enumerate((0.0, 0.5, 1.5)):
        if backoff:
            time.sleep(backoff)
        throttle_rubik(url)
        try:
            req = urllib.request.Request(url, headers=_HEADERS)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            mark_rubik_called(url)
            return payload if isinstance(payload, dict) else None
        except urllib.error.HTTPError as exc:
            mark_rubik_called(url)
            if out_status is not None:
                out_status.append(int(exc.code))
            if exc.code == 429 and attempt < 2:
                continue
            return None
        except Exception:
            return None
    return None


def fetch_smart_money_for_symbol(
    ccy: str,
    price: float = 0.0,
    *,
    timeout: float = 3.5,
) -> Optional[Dict[str, Any]]:
    """采集单标的顶级大户持仓多空比与主动资金流（OKX Rubik 公开统计端点）。"""
    base_ccy = str(ccy or "").upper().strip()
    if not base_ccy:
        return None

    res_okx = _fetch_from_okx_rubik(base_ccy, price=price, timeout=timeout)
    if res_okx and res_okx.get("longShortRatio"):
        return res_okx

    return None


def _fetch_from_okx_rubik(ccy: str, price: float = 0.0, timeout: float = 3.5) -> Optional[Dict[str, Any]]:
    w_long: Optional[float] = None
    ls_ratio: Optional[float] = None
    net_notional_usd = 0.0
    taker_str = "--"
    cache_mod = _shared_cache_module()

    try:
        pos_rows: Optional[List[Any]] = None
        skip_pos_fetch = False
        if cache_mod is not None:
            pos_cached = cache_mod._cache_get(f"sm-pos-ratio:{ccy}", 3600.0)
            if pos_cached == "__404__":
                skip_pos_fetch = True
            elif isinstance(pos_cached, list) and pos_cached:
                pos_rows = pos_cached
        if pos_rows is None and not skip_pos_fetch:
            url = f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-pos-ratio?ccy={ccy}&period=5m"
            st_codes: List[int] = []
            d = _okx_rubik_get(url, timeout=timeout, out_status=st_codes)
            if st_codes and 404 in st_codes and cache_mod is not None:
                cache_mod._cache_put(f"sm-pos-ratio:{ccy}", "__404__")
            elif d and d.get("code") == "0" and d.get("data") and len(d["data"]) > 0:
                pos_rows = d["data"]
                if cache_mod is not None:
                    cache_mod._cache_put(f"sm-pos-ratio:{ccy}", pos_rows)
        if pos_rows and len(pos_rows) > 0:
            raw_ratio = float(pos_rows[0][1])
            ls_ratio = raw_ratio
            w_long = round(raw_ratio / (1.0 + raw_ratio), 4)
    except Exception:
        pass

    if w_long is None:
        try:
            ls_rows: Optional[List[Any]] = None
            if cache_mod is not None:
                ls_cached = cache_mod._cache_get(f"lsratio:{ccy}", 300.0)
                if isinstance(ls_cached, list) and ls_cached:
                    ls_rows = ls_cached
            if ls_rows is None:
                url2 = f"https://www.okx.com/api/v5/rubik/stat/contracts/long-short-account-ratio?ccy={ccy}&period=5m"
                d2 = _okx_rubik_get(url2, timeout=timeout)
                if d2 and d2.get("code") == "0" and d2.get("data") and len(d2["data"]) > 0:
                    ls_rows = d2["data"]
                    if cache_mod is not None:
                        cache_mod._cache_put(f"lsratio:{ccy}", ls_rows)
            if ls_rows and len(ls_rows) > 0:
                raw_ratio2 = float(ls_rows[0][1])
                ls_ratio = raw_ratio2
                w_long = round(raw_ratio2 / (1.0 + raw_ratio2), 4)
        except Exception:
            pass

    if w_long is None:
        return None

    try:
        tv_rows: Optional[List[Any]] = None
        if cache_mod is not None:
            tv_cached = cache_mod._cache_get(f"taker:{ccy}:5m", 45.0)
            if isinstance(tv_cached, list) and tv_cached:
                tv_rows = tv_cached
        if tv_rows is None:
            url_t = f"https://www.okx.com/api/v5/rubik/stat/taker-volume?ccy={ccy}&instType=CONTRACTS&period=5m"
            d_t = _okx_rubik_get(url_t, timeout=timeout)
            if d_t and d_t.get("code") == "0" and d_t.get("data") and len(d_t["data"]) > 0:
                tv_rows = d_t["data"]
                if cache_mod is not None:
                    cache_mod._cache_put(f"taker:{ccy}:5m", tv_rows)
        if tv_rows and len(tv_rows) > 0:
            # OKX rubik/stat/taker-volume 返回列序: [ts, sellVol, buyVol]
            s_vol = float(tv_rows[0][1])
            b_vol = float(tv_rows[0][2])
            net_notional_usd = b_vol - s_vol
            taker_str = (
                f"{round(net_notional_usd / 1e4, 1)}万 U"
                if abs(net_notional_usd) >= 1e4
                else f"{round(net_notional_usd, 0)} U"
            )
    except Exception:
        pass

    return {
        "longShortRatio": {
            "weightedLongRatio": w_long,
            "longShortRatio": ls_ratio,
        },
        "notional": {
            "netNotionalUsdt": net_notional_usd,
        },
        "winRate": {},
        "takerNetUsd": taker_str,
        "lsRatio": ls_ratio,
        "weighted_long_pct": round(w_long * 100, 1),
    }


def fetch_smart_money_pool(
    instruments: List[Dict[str, Any]],
    *,
    max_workers: int = 6,
    timeout: float = 3.5,
) -> Dict[str, Any]:
    """并发采集标的池内全部币种的聪明钱与大户数据，返回标准 pool 字典。"""
    pool: Dict[str, Any] = {}
    if not instruments:
        return pool

    def _fetch_one(item: Dict[str, Any]) -> tuple[str, Optional[Dict[str, Any]]]:
        ccy = item.get("ccy") or item.get("name") or (item.get("instId", "").split("-")[0] if "-" in item.get("instId", "") else "")
        price = float(item.get("price") or 0.0)
        res = fetch_smart_money_for_symbol(ccy, price=price, timeout=timeout)
        return ccy, res

    with ThreadPoolExecutor(max_workers=min(max_workers, len(instruments))) as executor:
        for ccy, sm in executor.map(_fetch_one, instruments):
            if ccy and sm:
                pool[ccy] = sm

    return pool
