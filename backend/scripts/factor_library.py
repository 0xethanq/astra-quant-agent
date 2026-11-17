#!/usr/bin/env python3
"""
ASTRA High-Alpha Quantitative Factor Library Engine (factor_library.py)
Calculates and normalizes 5 core factor pillars for crypto perpetuals:
1. Momentum & Trend (ADX, RSI, EMA slope, KDJ)
2. Volatility & Channel (ATR%, Bollinger Bandwidth)
3. Volume & Money Flow (15M Volume Ratio, OBV, CMF Chaikin Flow, 5M Taker Net Flow)
4. Orderbook & Microstructure (Bid/Ask Imbalance Ratio, BBO Spread)
5. Smart Money & Derivatives (Top100 Weighted Long Ratio, 24H Net Flow, Funding Rate, OI)
"""

import os
import sys
from pathlib import Path

_THIS_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
if str(_THIS_DIR) not in sys.path:
    sys.path.insert(0, str(_THIS_DIR))

from astra_backend.math_utils import safe_float as _shared_safe_float

import json
import time
from datetime import datetime, timedelta, timezone
import subprocess
import urllib.request
from typing import Dict, Any, List, Optional

from scripts.factors.defaults import build_default_factors
from scripts.factors.scoring import score_composite_alpha
from scripts.factors.candles_15m import compute_15m_indicators, mark_15m_missing
from scripts.factors import okx_quant_factors as qf
from concurrent.futures import ThreadPoolExecutor

_BJ = timezone(timedelta(hours=8))

WORKSPACE_DIR = str(_PROJECT_ROOT)
#: ⚠️ `ASTRA_DATA_DIR` 是**测试沙箱专用环境变量**（由 tests/config_sandbox.isolate_config
#: 设置、由 `run_script` 拉起的子进程继承）：跑测试时把 data/ 写入重定向到沙箱，
#: **生产从不设置该变量 → 取值与原先逐位相同**。修复"测试经子进程写生产文件"
#: 的泄漏（§88/§91.6），不改任何业务行为。
DATA_DIR = os.environ.get("ASTRA_DATA_DIR") or os.path.join(WORKSPACE_DIR, "data")
FACTOR_LIB_CACHE_FILE = os.path.join(DATA_DIR, "factor_library_snapshot.json")

from instrument_pool import load_instruments
from market_data_service import fetch_orderbook_depth, fetch_indicators_batch, fetch_ticker, fetch_funding_rate, fetch_candles

TARGET_INSTRUMENTS = load_instruments()

def safe_float(val: Any, default: float = 0.0) -> float:
    """薄壳：转调单一事实源（`astra_backend.math_utils.safe_float`，第一百五十刀）。

    本函数与 `scripts/ai_brain_trader.safe_float`、`scripts/calculus/regime._safe_float`
    原为**三份**逐条等价的实现（按 14 组输入行为对拍一致），现收敛到一处：
    `nan`/`±inf`/不可转 ⇒ `default`；`bool` 按 `float()` 语义（`True→1.0`）。
    """
    return _shared_safe_float(val, default)


def compute_instrument_factors(item: Dict[str, Any], smart_money_pool: Dict[str, Any]) -> Dict[str, Any]:
    inst_id = item["instId"]
    name = item["name"]
    ccy = item.get("ccy", "")
    headers = {"User-Agent": "Mozilla/5.0"}
    
    factors = build_default_factors(inst_id, name)

    # 1. Ticker & Depth (Orderbook)
    try:
        req = urllib.request.Request(f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}", headers=headers)
        with urllib.request.urlopen(req, timeout=3) as resp:
            d = json.loads(resp.read().decode("utf-8"))
            if d.get("code") == "0" and d.get("data"):
                t = d["data"][0]
                factors["price"] = safe_float(t.get("last"))
                factors["microstructure"]["bid_px"] = safe_float(t.get("bidPx", factors["price"]))
                factors["microstructure"]["ask_px"] = safe_float(t.get("askPx", factors["price"]))
                op = safe_float(t.get("open24h", 0))
                factors["chg24h"] = round(((factors["price"] - op) / op * 100) if op > 0 else 0.0, 2)
                
                # Spread
                if factors["microstructure"]["ask_px"] > 0 and factors["price"] > 0:
                    spread = factors["microstructure"]["ask_px"] - factors["microstructure"]["bid_px"]
                    factors["microstructure"]["spread_pct"] = round(spread / factors["price"] * 100, 4)
    except Exception:
        pass

    # 2. Orderbook Depth（T1：Top20 一次取回，同时导出 Top5/Top20 深度比与 OBI）
    depth_data = None
    try:
        depth_data = fetch_orderbook_depth(inst_id, sz=20)
    except Exception:
        depth_data = None

    # 3. 15M Candles -> ATR, RSI, VWAP Bias, Vol Ratio, OBV（+ T3 筹码分布）
    closes_15m: List[float] = []
    try:
        d = {"data": fetch_candles(inst_id, bar="15m", limit=24)}
        if d["data"] and len(d["data"]) >= 15:
            raw_candles = d["data"]
            # 15M 派生序列 + 指标（阶段 4·B3 第三十二刀：
            # 迁至 scripts/factors/candles_15m.py）。取数仍在本门面内，
            # 故对 fetch_candles 的 patch.object 缝不受影响。
            closes_15m, _h15, _l15, _v15 = compute_15m_indicators(
                raw_candles, factors, safe_float=safe_float)
        else:
            print(f"[Factor] ⚠️ {inst_id} 15m K线获取不足15根（www/aws/CLI 三级容灾均未取回），15M 因子降级缺省")
            # ★「不许假数据」：降级缺省 ≠ 留着默认值（rsi_14=50.0 会被打分读成中性偏多加 15 分）
            mark_15m_missing(factors)
    except Exception as exc:
        print(f"[Factor] ⚠️ {inst_id} 15m K线处理异常: {exc}")
        mark_15m_missing(factors)

    # 4. 1H Candles -> 1H ATR（+ T4 动量源序列）
    #    ⚠️ `limit=100` 而不是 24：MACD(12,26,9) 需要 **35 根**收盘价，
    #    只取 24 根会让 MACD 块静默退化成 0/中性（实盘已观测到）。
    closes_1h: List[float] = []
    try:
        d = {"data": fetch_candles(inst_id, bar="1H", limit=100)}
        if d["data"] and len(d["data"]) >= 15:
            raw_1h = d["data"]
            closes_1h = [safe_float(c[4]) for c in reversed(raw_1h)]
            highs_1h = [safe_float(c[2]) for c in reversed(raw_1h)]
            lows_1h = [safe_float(c[3]) for c in reversed(raw_1h)]

            tr_list_1h = []
            for i in range(1, len(closes_1h)):
                tr = max(highs_1h[i] - lows_1h[i], abs(highs_1h[i] - closes_1h[i-1]), abs(lows_1h[i] - closes_1h[i-1]))
                tr_list_1h.append(tr)
            if len(tr_list_1h) >= 14:
                atr_1h = sum(tr_list_1h[-14:]) / 14
                factors["volatility_channel"]["atr_1h"] = round(atr_1h, 4)
                if factors["price"] > 0:
                    factors["volatility_channel"]["atr_1h_pct"] = round(atr_1h / factors["price"] * 100, 2)
        else:
            print(f"[Factor] ⚠️ {inst_id} 1H K线获取不足15根（www/aws/CLI 三级容灾均未取回），1H ATR 字段降级缺省")
    except Exception as exc:
        print(f"[Factor] ⚠️ {inst_id} 1H K线处理异常: {exc}")

    # 5. OKX Official Indicators (ADX, KDJ, BBWidth, CMF) via 1 single batch REST call (zero Node CLI fork)
    # ★ 2026-10「不许假数据」：先把这批键置为缺失，取到才写真值。
    #   原实现只在 `if "ADX" in inds:` 里写 ⇒ 指标批失败时默认值（0.0）留在原地，
    #   提示词会显示"ADX=0.0 / CMF=0.0"这类**假读数**（ADX=0 是个结论：无趋势）。
    factors["trend_momentum"]["adx_1h"] = None
    factors["trend_momentum"]["kdj_j"] = None
    factors["volatility_channel"]["bb_width_1h"] = None
    factors["volume_money_flow"]["cmf_1h"] = None
    try:
        inds = fetch_indicators_batch(inst_id, ["adx", "kdj", "bbwidth", "cmf"], bar="1H")
        if "ADX" in inds:
            factors["trend_momentum"]["adx_1h"] = safe_float(inds["ADX"].get("adx"))
        if "KDJ" in inds:
            factors["trend_momentum"]["kdj_j"] = safe_float(inds["KDJ"].get("j"))
        if "BBWIDTH" in inds:
            factors["volatility_channel"]["bb_width_1h"] = safe_float(inds["BBWIDTH"].get("bbWidth"))
        if "CMF" in inds:
            factors["volume_money_flow"]["cmf_1h"] = safe_float(inds["CMF"].get("cmf"))
    except Exception:
        pass

    # =========================================================================
    # 6. OKX 7 梯队量化因子（2026-10 重构：替代原 Pillar 6 的微积分/定积分/概率）
    #    取数全部走公开 REST（T3/T4 纯本地计算），失败即显式降级。
    # =========================================================================
    trend_hint = "BULL" if factors["chg24h"] > 0 else ("BEAR" if factors["chg24h"] < 0 else "CHOP")

    # --- T4 动量确认（1H MACD(12,26,9) + 1H/15M RSI(14) 情境区间 + 顶底背离）---
    if closes_1h:
        qf.apply_momentum_tier(factors, closes_1h=closes_1h,
                               closes_15m=closes_15m, trend=trend_hint,
                              price=safe_float(factors.get('price')))
    else:
        # 没有 K 线 ⇒ 显式标缺失（默认值 0.0/RSI 50 会被读成"真实的中性动量"）
        qf.mark_momentum_missing(factors)

    # --- T3 筹码分布（24H 滚动 VWAP ± σ 带 + VPVR POC）---
    try:
        raw_vp = fetch_candles(inst_id, bar="15m", limit=qf.VWAP_WINDOW_15M)
        if raw_vp:
            qf.apply_volume_profile_tier(factors, raw_candles_15m=raw_vp,
                                         price=factors["price"])
        else:
            qf.mark_volume_profile_missing(factors)
    except Exception:
        pass

    # --- T1 盘口微观结构（OBI / Top5/Top20 深度比 / 有效点差 bps）---
    qf.apply_microstructure_tier(factors, depth=depth_data, price=factors["price"])
    # ★ `spread_bps` 现在缺失即 `None`（不许 0.0 冒充"零点差"），比较前必须先取值
    if depth_data and safe_float(factors["microstructure"].get("spread_bps")) > 0:
        factors["microstructure"]["spread_pct"] = round(
            factors["microstructure"]["spread_bps"] / 100.0, 4)

    # --- T0.5 订单流（5M/1H CVD、Taker 买卖比、量价背离）---
    if ccy:
        taker_5m = qf.fetch_taker_volume(ccy, "5m")
        taker_1h = qf.fetch_taker_volume(ccy, "1H")
        qf.apply_orderflow_tier(factors, taker_5m=taker_5m, taker_1h=taker_1h,
                                closes_1h=closes_1h)
        # 兼容既有消费端（前端/提示词旧的 taker_net_usd 字符串）
        # ★ 先置缺失：`taker_5m` 取不到时原实现留着默认 "0 U"，
        #   提示词会显示"5M主动吃单净差=0 U"——那是"零净流"这个**结论**。
        factors["volume_money_flow"]["taker_net_usd"] = "--"
        if taker_5m:
            buy = safe_float(taker_5m[0][2]) if len(taker_5m[0]) > 2 else 0.0
            sell = safe_float(taker_5m[0][1]) if len(taker_5m[0]) > 1 else 0.0
            net_diff = buy - sell
            factors["volume_money_flow"]["taker_net_usd"] = (
                f"{round(net_diff / 1e4, 1)}万 U" if abs(net_diff) >= 1e4
                else f"{net_diff:.0f} U")

    # --- T0 衍生品（费率/预测费率/ΔOI/账户多空比/清算脉冲）+ T1.5/T2（BTC/ETH 限定）---
    if ccy:
        ul_y = "-".join(inst_id.split("-")[:2]) if "-" in inst_id else inst_id
        snapshot = qf.fetch_derivatives_snapshot(ccy, inst_id, ul_y)
        options_block = basis_block = loan_block = None
        if ccy in ("BTC", "ETH"):
            options_block = qf.fetch_option_snapshot(f"{ccy}-USD", ccy) or None
            basis_block = qf.fetch_quarterly_basis_inputs(ccy) or None
            loan_block = qf.fetch_loan_rate_snapshot() or None
        price_chg_1h_pct = 0.0
        if len(closes_1h) >= 2 and closes_1h[-2] > 0:
            price_chg_1h_pct = (closes_1h[-1] - closes_1h[-2]) / closes_1h[-2] * 100.0
        qf.apply_derivatives_tier(
            factors, snapshot=snapshot, ct_val=item.get("ctVal", 1.0),
            price_chg_1h_pct=price_chg_1h_pct, price=safe_float(factors.get("price")),
            options_block=options_block,
            basis_block=basis_block, loan_block=loan_block)

    # SmartMoney Overlay（仅当真有数据源时覆盖缺失占位；无源时保留 available=False）
    if ccy in smart_money_pool:
        factors["smart_money_derivatives"]["available"] = True
        factors["smart_money_derivatives"]["reason"] = ""
        sm = smart_money_pool[ccy]
        ls = sm.get("longShortRatio", {})
        notional = sm.get("notional", {})
        win = sm.get("winRate", {})
        w_long = round(safe_float(ls.get("weightedLongRatio", 0.5)) * 100, 1)
        net_usdt = safe_float(notional.get("netNotionalUsdt", 0))
        net_str = f"{round(net_usdt / 1e4, 1)}万 U" if abs(net_usdt) >= 1e4 else f"{round(net_usdt, 0)} U"
        
        factors["smart_money_derivatives"]["weighted_long_pct"] = w_long
        factors["smart_money_derivatives"]["smart_money_flow_usd"] = net_str
        if ls.get("longShortRatio") is not None:
            factors["smart_money_derivatives"]["long_short_ratio"] = str(round(safe_float(ls.get("longShortRatio")), 2))
        long_avg = safe_float(notional.get("smartMoneyLongAvgEntry", 0))
        short_avg = safe_float(notional.get("smartMoneyShortAvgEntry", 0))
        if long_avg > 0:
            factors["smart_money_derivatives"]["avg_long_entry"] = f"{long_avg:.6g}"
        if short_avg > 0:
            factors["smart_money_derivatives"]["avg_short_entry"] = f"{short_avg:.6g}"
        long_win = safe_float(win.get("avgLongWinRate", 0))
        short_win = safe_float(win.get("avgShortWinRate", 0))
        if long_win > 0 or short_win > 0:
            parts = []
            if long_win > 0:
                parts.append(f"多胜率{round(long_win * 100, 1)}%")
            if short_win > 0:
                parts.append(f"空胜率{round(short_win * 100, 1)}%")
            factors["smart_money_derivatives"]["top_win_rate"] = " / ".join(parts)
        if w_long >= 65.0 and net_usdt > 0:
            factors["smart_money_derivatives"]["signal"] = "BULL_ACCUMULATION"
        elif w_long <= 35.0 and net_usdt < 0:
            factors["smart_money_derivatives"]["signal"] = "BEAR_DISTRIBUTION"

    # ★ 2026-10 用户拍板：预估型强平热力图**已整块移除**（构建/透传/渲染/看板卡片）。
    # 复合 alpha 打分与信号建议（-100~+100）
    # 阶段 4·B3 第二十九刀：整段迁至 scripts/factors/scoring.py::score_composite_alpha，
    # 本处只保留调用。八项门槛/加减分与两处阻尼的说明见该模块文档串。
    score_composite_alpha(factors)


    return factors

def update_factor_library() -> Dict[str, Any]:
    """Fetch and calculate multi-pillar factor library snapshot for 6 instruments."""
    # 1. Smart Money Pool：通过 OKX Rubik 官方公开统计端点采集
    #    取数不可用时保持空池 → 优雅缺失化 available=False
    try:
        try:
            from scripts.factors.smart_money import fetch_smart_money_pool
        except ImportError:
            from factors.smart_money import fetch_smart_money_pool
        smart_money_pool = fetch_smart_money_pool(TARGET_INSTRUMENTS)
    except Exception as e:
        print(f"[Factor Library] SmartMoney pool fetch fallback: {e}")
        smart_money_pool = {}

    # 2. Parallel Factor Computations
    with ThreadPoolExecutor(max_workers=6) as executor:
        results = list(executor.map(lambda item: compute_instrument_factors(item, smart_money_pool), TARGET_INSTRUMENTS))

    snapshot = {
        "timestamp": int(time.time()),
        "time_str": datetime.now(_BJ).isoformat(sep=" ", timespec="seconds"),
        "instruments": results
    }

    # Atomic Write
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp_file = FACTOR_LIB_CACHE_FILE + ".tmp"
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(snapshot, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, FACTOR_LIB_CACHE_FILE)
    except Exception as e:
        print(f"[Factor Library] Cache write error: {e}")

    return snapshot

if __name__ == "__main__":
    snap = update_factor_library()
    print(f"✅ Factor Library Engine Snapshot Complete at {snap['time_str']}:")
    for inst in snap["instruments"]:
        print(f"[{inst['name']}] Alpha Score: {inst['composite_alpha_score']:+5.1f} | Signal: {inst['signal_recommendation']:10} | ADX: {inst['trend_momentum']['adx_1h']} | SM Long: {inst['smart_money_derivatives']['weighted_long_pct']}% | CMF: {inst['volume_money_flow']['cmf_1h']} | Depth: {inst['microstructure']['bid_ask_depth_ratio']}")
