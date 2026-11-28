"""两段式零前视回测与分层盲测 LLM Replay 验证引擎（Layer 1 Walk-Forward + Layer 2 LLM A/B）。"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import math
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from astra_backend.sandbox.data_warehouse import DEFAULT_DB_PATH, MarketReplayWarehouse
from astra_backend.sandbox.replay import PointInTimeReplayEngine
from scripts.factors.defaults import build_default_factors
from scripts.factors.okx_quant_factors import (
    apply_momentum_tier,
    compute_btc_beta_and_residual,
    compute_rv_compression,
    compute_structural_anchors,
)
from scripts.factors.scoring import score_composite_alpha

_BJ_TZ = datetime.timezone(datetime.timedelta(hours=8))


def _spearman_rank_ic(xs: Sequence[float], ys: Sequence[float]) -> float:
    """计算两组样本的 Spearman 秩相关系数（无第三方依赖）。"""
    n = min(len(xs), len(ys))
    if n < 3:
        return 0.0

    def _ranks(vals: Sequence[float]) -> List[float]:
        indexed = sorted(enumerate(vals), key=lambda kv: kv[1])
        ranks = [0.0] * len(vals)
        i = 0
        while i < len(indexed):
            j = i
            while j + 1 < len(indexed) and indexed[j + 1][1] == indexed[i][1]:
                j += 1
            avg_rank = (i + j) / 2.0 + 1.0
            for k in range(i, j + 1):
                ranks[indexed[k][0]] = avg_rank
            i = j + 1
        return ranks

    rx = _ranks(xs[:n])
    ry = _ranks(ys[:n])
    mx = sum(rx) / n
    my = sum(ry) / n
    num = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    deny = math.sqrt(sum((b - my) ** 2 for b in ry))
    if denx <= 1e-12 or deny <= 1e-12:
        return 0.0
    return round(num / (denx * deny), 4)


def _compute_point_in_time_features(
    symbol: str,
    candles_1h_slice: Sequence[Sequence[Any]],
    *,
    btc_closes_slice: Optional[Sequence[float]] = None,
) -> Dict[str, Any]:
    """基于 `ts <= t` 的历史 1H K 线严格零前视计算因子、体制、结构锚定与 Alpha 分。"""
    closes = [float(c[4]) for c in candles_1h_slice]
    highs = [float(c[2]) for c in candles_1h_slice]
    lows = [float(c[3]) for c in candles_1h_slice]
    vols = [float(c[5]) if len(c) > 5 else 0.0 for c in candles_1h_slice]
    px = closes[-1]

    base = symbol.split("-")[0]
    factors = build_default_factors(symbol, base)
    factors["price"] = px
    if len(closes) >= 25 and closes[-25] > 0:
        factors["chg24h"] = round((px - closes[-25]) / closes[-25] * 100.0, 2)

    # 1H ATR (Wilder / 14-bar TR)
    atr_1h = px * 0.015
    if len(closes) >= 15:
        trs = [
            max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))
            for i in range(1, len(closes))
        ]
        atr_1h = sum(trs[-14:]) / 14.0
    factors["volatility_channel"]["atr_1h"] = round(atr_1h, 6)
    factors["volatility_channel"]["atr_1h_pct"] = round((atr_1h / px * 100.0) if px > 0 else 0.0, 3)

    # ADX 代理指标：直接由 1H TR/DM 估算（无真实交易所接口，标注合理区间，避免伪 0）
    if len(closes) >= 28:
        plus_dm, minus_dm, tr_vals = [], [], []
        for i in range(1, len(closes)):
            up_move = highs[i] - highs[i - 1]
            dn_move = lows[i - 1] - lows[i]
            plus_dm.append(up_move if (up_move > dn_move and up_move > 0) else 0.0)
            minus_dm.append(dn_move if (dn_move > up_move and dn_move > 0) else 0.0)
            tr_vals.append(max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1])))
        tr14 = sum(tr_vals[-14:])
        if tr14 > 1e-12:
            pdi = 100.0 * sum(plus_dm[-14:]) / tr14
            mdi = 100.0 * sum(minus_dm[-14:]) / tr14
            dx = abs(pdi - mdi) / max(1e-9, pdi + mdi) * 100.0
            factors["trend_momentum"]["adx_1h"] = round(dx, 2)
        else:
            factors["trend_momentum"]["adx_1h"] = None
    else:
        factors["trend_momentum"]["adx_1h"] = None

    # Volume Ratio & OBV
    if len(vols) >= 6:
        avg_v5 = sum(vols[-6:-1]) / 5.0
        factors["volume_money_flow"]["vol_ratio_15m"] = round(vols[-1] / avg_v5, 2) if avg_v5 > 0 else None
    else:
        factors["volume_money_flow"]["vol_ratio_15m"] = None

    obv = 0.0
    for i in range(max(1, len(closes) - 24), len(closes)):
        if closes[i] > closes[i - 1]:
            obv += vols[i]
        elif closes[i] < closes[i - 1]:
            obv -= vols[i]
    factors["volume_money_flow"]["obv_flow"] = "BULL_FLOW" if obv > 0 else ("BEAR_FLOW" if obv < 0 else "NEUTRAL")
    # 无历史 L2 盘口/taker 时诚实置缺失，不编造假数值
    factors["microstructure"]["spread_bps"] = None
    factors["microstructure"]["obi_pct"] = None
    factors["microstructure"]["bid_ask_depth_ratio"] = None
    factors["volume_money_flow"]["taker_buy_sell_ratio"] = None
    factors["volume_money_flow"]["cvd_5m_usd"] = None
    factors["volume_money_flow"]["cvd_1h_usd"] = None

    ma7 = sum(closes[-7:]) / min(len(closes), 7)
    ma20 = sum(closes[-20:]) / min(len(closes), 20)
    trend_hint = "BULL" if (px > ma7 > ma20) else ("BEAR" if (px < ma7 < ma20) else "CHOP")
    apply_momentum_tier(factors, closes_1h=closes, closes_15m=[], trend=trend_hint, price=px)

    rv_ratio = compute_rv_compression(closes)
    rs_blk: Dict[str, Any] = {}
    if rv_ratio is not None:
        rs_blk["rv_ratio_6h_72h"] = rv_ratio
    if btc_closes_slice:
        beta_res = compute_btc_beta_and_residual(closes, btc_closes_slice)
        rs_blk.update({k: v for k, v in beta_res.items() if v is not None})
    if rs_blk:
        factors["relative_strength"] = rs_blk

    score_composite_alpha(factors)
    anchors = compute_structural_anchors(
        closes_1h=closes,
        highs_1h=highs,
        lows_1h=lows,
        raw_1h=list(reversed(candles_1h_slice[-15:])),
        price=px,
        atr_1h=atr_1h,
        sl_atr_mult=2.0,
    )
    factors["structural_anchors"] = anchors
    adx_v = float(factors["trend_momentum"].get("adx_1h") or 0.0)
    regime = "TREND" if (trend_hint in ("BULL", "BEAR") and adx_v >= 22.0) else "CHOP"
    factors["regime_tag"] = regime
    return factors


def run_deterministic_walk_forward(
    symbols_candles_1h: Dict[str, List[List[Any]]],
    *,
    funding_by_symbol: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    initial_balance: float = 10000.0,
    risk_per_trade_pct: float = 0.02,
    alpha_entry_threshold: float = 28.0,
    sl_atr_mult: float = 2.0,
    tp_rr: float = 2.4,
    be_offset_pct: float = 0.0030,
    time_stop_hours: float = 4.0,
    n_folds: int = 3,
    train_ratio: float = 0.6,
    forward_horizon_bars: int = 4,
) -> Dict[str, Any]:
    """Layer 1：零 Token 确定性因子与出场状态机 Walk-Forward 验证。"""
    if not symbols_candles_1h:
        return {"folds": [], "oos_summary": {"total_trades": 0, "rank_ic": 0.0, "expectancy_r": 0.0}}

    btc_key = next((k for k in symbols_candles_1h if k.upper().startswith("BTC")), None)
    btc_by_ts: Dict[int, float] = {
        int(c[0]): float(c[4]) for c in (symbols_candles_1h.get(btc_key, []) if btc_key else [])
    }

    # Pre-index sorted candles and timestamps
    norm_candles = {
        sym: sorted(rows, key=lambda c: int(c[0]))
        for sym, rows in symbols_candles_1h.items()
        if len(rows) >= 60
    }
    if not norm_candles:
        return {"folds": [], "oos_summary": {"total_trades": 0, "rank_ic": 0.0, "expectancy_r": 0.0}}

    all_ts = sorted({int(c[0]) for rows in norm_candles.values() for c in rows})
    warmup = 48
    if len(all_ts) <= warmup + 10:
        return {"folds": [], "oos_summary": {"total_trades": 0, "rank_ic": 0.0, "expectancy_r": 0.0}}

    eval_ts = all_ts[warmup:]
    fold_len = max(12, len(eval_ts) // max(1, int(n_folds)))

    folds_out: List[Dict[str, Any]] = []
    all_oos_scores: List[float] = []
    all_oos_fwd: List[float] = []
    all_oos_trades: List[Dict[str, Any]] = []

    for fold_idx in range(n_folds):
        f_start = fold_idx * fold_len
        if f_start >= len(eval_ts):
            break
        f_end = len(eval_ts) if fold_idx == n_folds - 1 else min(len(eval_ts), (fold_idx + 1) * fold_len)
        split_idx = f_start + int((f_end - f_start) * train_ratio)
        if split_idx >= f_end - 2:
            continue

        oos_start_ts = eval_ts[split_idx]
        oos_end_ts = eval_ts[f_end - 1]

        fold_candles = {
            sym: [c for c in rows if int(c[0]) <= oos_end_ts]
            for sym, rows in norm_candles.items()
        }

        ic_scores: List[float] = []
        ic_fwds: List[float] = []
        close_maps = {sym: {int(c[0]): c for c in rows} for sym, rows in fold_candles.items()}
        ts_idx_maps = {sym: {int(c[0]): idx for idx, c in enumerate(rows)} for sym, rows in fold_candles.items()}
        regime_at_entry: Dict[int, str] = {}

        engine = PointInTimeReplayEngine(initial_balance=initial_balance, maker_fee=0.0002, taker_fee=0.0005, slippage=0.0002)

        def _strategy(adapter, ts_ms: int):
            if ts_ms < oos_start_ts:
                return None

            # Update funding rate if available
            if funding_by_symbol:
                for sym, flist in funding_by_symbol.items():
                    eligible = [f for f in flist if int(f["ts_ms"]) <= ts_ms]
                    if eligible:
                        adapter.set_funding_rate(sym, float(eligible[-1]["funding_rate"]))

            orders: List[Dict[str, Any]] = []
            open_bases = {p["base"] for p in adapter.positions()}

            for sym, rows in fold_candles.items():
                idx = ts_idx_maps[sym].get(ts_ms)
                if idx is None or idx < warmup:
                    continue
                hist = rows[: idx + 1]
                btc_hist = [btc_by_ts[int(r[0])] for r in hist if int(r[0]) in btc_by_ts] if btc_by_ts else None
                f = _compute_point_in_time_features(sym, hist, btc_closes_slice=btc_hist)
                score = float(f.get("composite_alpha_score") or 0.0)

                # Forward 4H return for Rank-IC evaluation
                if idx + forward_horizon_bars < len(rows):
                    cur_c = float(rows[idx][4])
                    fwd_c = float(rows[idx + forward_horizon_bars][4])
                    if cur_c > 0:
                        ic_scores.append(score)
                        ic_fwds.append((fwd_c - cur_c) / cur_c)

                base = sym.split("-")[0]
                if base in open_bases or adapter.open_orders(sym):
                    continue

                atr = float(f["volatility_channel"].get("atr_1h") or 0.0)
                px = float(f["price"] or 0.0)
                if px <= 0 or atr <= 0:
                    continue

                action = None
                if score >= alpha_entry_threshold:
                    action = "BUY"
                elif score <= -alpha_entry_threshold:
                    action = "SELL"
                if action is None:
                    continue

                sl_dist = atr * sl_atr_mult
                tp2_dist = sl_dist * tp_rr
                if action == "BUY":
                    sl_px = px - sl_dist
                    tp2_px = px + tp2_dist
                    tp1_px = px + max(sl_dist, 1.0 * atr)
                else:
                    sl_px = px + sl_dist
                    tp2_px = px - tp2_dist
                    tp1_px = px - max(sl_dist, 1.0 * atr)
                if tp2_px <= 0 or sl_px <= 0:
                    continue

                risk_usd = adapter.equity * risk_per_trade_pct
                contracts = round(max(0.01, risk_usd / max(1e-9, sl_dist)), 4)
                regime_at_entry[ts_ms] = str(f.get("regime_tag") or "CHOP")
                orders.append({
                    "symbol": sym,
                    "side": "buy" if action == "BUY" else "sell",
                    "action": action,
                    "contracts": contracts,
                    "order_type": "market",
                    "price": px,
                    "take_profit_price": tp2_px,
                    "stop_loss_price": sl_px,
                    "atr": atr,
                    "initial_sl_px": sl_px,
                    "tp1_px": tp1_px,
                    "scale_out_ratio": 0.35,
                    "be_offset_pct": be_offset_pct,
                    "time_stop_hours": time_stop_hours,
                })
            return orders

        metrics = engine.run_replay(fold_candles, _strategy, bar="1H")
        rank_ic = _spearman_rank_ic(ic_scores, ic_fwds)
        all_oos_scores.extend(ic_scores)
        all_oos_fwd.extend(ic_fwds)

        total_fees = sum(float(t.get("fee") or 0.0) for t in engine.adapter._trades)
        gross_wins = sum(float(t.get("gross_pnl") or 0.0) for t in metrics.trades if float(t.get("gross_pnl") or 0.0) > 0)
        fee_ratio_pct = round(total_fees / gross_wins * 100.0, 2) if gross_wins > 0 else 0.0

        folds_out.append({
            "fold": fold_idx + 1,
            "oos_start_ms": oos_start_ts,
            "oos_end_ms": oos_end_ts,
            "rank_ic": rank_ic,
            "total_trades": metrics.total_trades,
            "win_rate_pct": metrics.win_rate_pct,
            "profit_factor": metrics.profit_factor,
            "total_return_pct": metrics.total_return_pct,
            "max_drawdown_pct": metrics.max_drawdown_pct,
            "sharpe_ratio": metrics.sharpe_ratio,
            "sortino_ratio": metrics.sortino_ratio,
            "avg_r_multiple": metrics.avg_r_multiple,
            "fee_ratio_pct": fee_ratio_pct,
        })
        all_oos_trades.extend(metrics.trades)

    n_tr = len(all_oos_trades)
    r_vals = [float(t.get("r_multiple") or 0.0) for t in all_oos_trades if float(t.get("initial_risk_usd") or 0.0) > 0]
    wins = [t for t in all_oos_trades if float(t.get("net_pnl") or 0.0) > 0]
    losses = [t for t in all_oos_trades if float(t.get("net_pnl") or 0.0) <= 0]
    gw = sum(float(t["net_pnl"]) for t in wins)
    gl = abs(sum(float(t["net_pnl"]) for t in losses))
    pf = round(gw / gl, 2) if gl > 0 else (99.0 if gw > 0 else 0.0)
    total_fees = sum(float(t.get("fee") or 0.0) for t in all_oos_trades)
    gross_abs = sum(abs(float(t.get("gross_pnl") or 0.0)) for t in all_oos_trades)

    return {
        "folds": folds_out,
        "oos_summary": {
            "n_folds": len(folds_out),
            "total_trades": n_tr,
            "win_rate_pct": round(len(wins) / n_tr * 100.0, 2) if n_tr else 0.0,
            "profit_factor": pf,
            "expectancy_r": round(sum(r_vals) / len(r_vals), 3) if r_vals else 0.0,
            "rank_ic": _spearman_rank_ic(all_oos_scores, all_oos_fwd),
            "fee_ratio_pct": round(total_fees / gross_abs * 100.0, 2) if gross_abs > 0 else 0.0,
            "net_pnl_usd": round(sum(float(t.get("net_pnl") or 0.0) for t in all_oos_trades), 2),
        },
    }


def select_stratified_replay_points(
    symbols_candles_1h: Dict[str, List[List[Any]]],
    *,
    n_points: int = 120,
    warmup: int = 48,
) -> List[int]:
    """抽取分层关键回放时间戳（覆盖强上涨、强下跌、高波脉冲与盘整阶段）。"""
    btc_key = next((k for k in symbols_candles_1h if k.upper().startswith("BTC")), next(iter(symbols_candles_1h), None))
    if not btc_key:
        return []
    rows = sorted(symbols_candles_1h[btc_key], key=lambda c: int(c[0]))
    if len(rows) <= warmup + 8:
        return []

    buckets: Dict[str, List[int]] = {"BULL": [], "BEAR": [], "SPIKE": [], "CHOP": []}
    for i in range(warmup, len(rows) - 6):
        c_now = float(rows[i][4])
        c_prev = float(rows[i - 4][4])
        ret4 = (c_now - c_prev) / c_prev if c_prev > 0 else 0.0
        rng = (float(rows[i][2]) - float(rows[i][3])) / c_now if c_now > 0 else 0.0
        ts = int(rows[i][0])
        if rng >= 0.025:
            buckets["SPIKE"].append(ts)
        elif ret4 >= 0.012:
            buckets["BULL"].append(ts)
        elif ret4 <= -0.012:
            buckets["BEAR"].append(ts)
        else:
            buckets["CHOP"].append(ts)

    per_bucket = max(1, int(n_points) // 4)
    selected: List[int] = []
    for name in ("BULL", "BEAR", "SPIKE", "CHOP"):
        pts = buckets[name]
        if not pts:
            continue
        step = max(1, len(pts) // per_bucket)
        selected.extend(pts[::step][:per_bucket])
    return sorted(set(selected))[:n_points]


def build_point_in_time_packages(
    symbols_candles_1h: Dict[str, List[List[Any]]],
    ts_ms: int,
    *,
    warehouse: Optional[MarketReplayWarehouse] = None,
) -> List[Dict[str, Any]]:
    """构造严格零前视偏差 (`ts <= ts_ms`) 的主脑数据包列表（缺失字段诚实标 `--`）。"""
    btc_key = next((k for k in symbols_candles_1h if k.upper().startswith("BTC")), None)
    btc_slice = (
        [float(c[4]) for c in sorted(symbols_candles_1h[btc_key], key=lambda x: int(x[0])) if int(c[0]) <= ts_ms]
        if btc_key else []
    )

    pkgs: List[Dict[str, Any]] = []
    for sym, raw_rows in symbols_candles_1h.items():
        hist = [c for c in sorted(raw_rows, key=lambda x: int(x[0])) if int(c[0]) <= ts_ms]
        if len(hist) < 40:
            continue
        snap_payload = None
        if warehouse is not None:
            rec = warehouse.get_latest_market_snapshot_before(sym, ts_ms)
            if rec and (ts_ms - int(rec["ts_ms"])) <= 1800 * 1000:
                snap_payload = rec["payload"]

        if isinstance(snap_payload, dict) and snap_payload.get("price"):
            pkgs.append(snap_payload)
            continue

        f = _compute_point_in_time_features(sym, hist[-100:], btc_closes_slice=btc_slice[-100:] if btc_slice else None)
        px = float(f["price"])
        base = sym.split("-")[0]
        pkgs.append({
            "instId": sym,
            "name": base,
            "ccy": base,
            "type": "crypto",
            "precision": 4 if px < 100 else 2,
            "price": px,
            "chg24h": f.get("chg24h", 0.0),
            "bidPx": px,
            "askPx": px,
            "fundingRate": "--",
            "oiUsd": "--",
            "vol24h": round(sum(float(c[5]) for c in hist[-24:] if len(c) > 5), 2),
            "lsRatio": "--",
            "takerNetUsd": "--",
            "spread_bps": "--",
            "atr": f["volatility_channel"].get("atr_1h", 0.0),
            "atr_1h": f["volatility_channel"].get("atr_1h", 0.0),
            "rsi_1h": f["trend_momentum"].get("rsi_1h"),
            "vol_ratio": f["volume_money_flow"].get("vol_ratio_15m"),
            "obv_flow": f["volume_money_flow"].get("obv_flow", "NEUTRAL"),
            "adx_1h": f["trend_momentum"].get("adx_1h"),
            "macro_4h": "4H_MACRO_BULL (大级别多头通道)" if f.get("chg24h", 0.0) > 1.0 else ("4H_MACRO_BEAR (大级别空头承压)" if f.get("chg24h", 0.0) < -1.0 else "4H_MACRO_RANGE (大级别区间震荡)"),
            "structure_1h": "1H_SWING_BULL" if f["trend_momentum"].get("macd_hist", 0.0) and f["trend_momentum"]["macd_hist"] > 0 else "1H_SWING_BEAR",
            "smart_money": {"available": False},
            "quant_factors": {
                k: f[k] for k in (
                    "trend_momentum", "volatility_channel", "volume_money_flow",
                    "microstructure", "smart_money_derivatives", "volume_profile", "options_structure",
                ) if isinstance(f.get(k), dict)
            },
            "structural_anchors": f.get("structural_anchors", {}),
            "relative_strength": f.get("relative_strength", {}),
            "composite_alpha_score": f.get("composite_alpha_score"),
            "signal_recommendation": f.get("signal_recommendation"),
            "data_quality": "valid",
        })
    return pkgs


def run_llm_replay_ab(
    symbols_candles_1h: Dict[str, List[List[Any]]],
    *,
    llm_call_fn: Callable[[str, str, str], Tuple[Dict[str, Any], int]],
    system_prompt_a: str,
    system_prompt_b: str,
    model_name: str = "replay-model",
    prompt_builder_fn: Optional[Callable[[List[Dict[str, Any]], str], str]] = None,
    warehouse: Optional[MarketReplayWarehouse] = None,
    replay_timestamps: Optional[Sequence[int]] = None,
    n_points: int = 100,
    horizon_bars: int = 8,
    risk_usd: float = 100.0,
) -> Dict[str, Any]:
    """Layer 2：同批分层样本盲测 A/B 对比（`temperature=0` 口径 + SQLite 响应缓存去重）。"""
    wh = warehouse or MarketReplayWarehouse(DEFAULT_DB_PATH)
    timestamps = list(replay_timestamps or select_stratified_replay_points(symbols_candles_1h, n_points=n_points))
    if prompt_builder_fn is None:
        from scripts.ai_brain_trader import construct_full_market_prompt
        prompt_builder_fn = lambda pkgs, tstr: construct_full_market_prompt(pkgs, current_time_str=tstr, usdt_available=5000.0)

    from scripts.order_risk import validate_quote_geometry_and_rr

    norm_candles = {
        sym: sorted(rows, key=lambda c: int(c[0]))
        for sym, rows in symbols_candles_1h.items()
    }
    ts_idx_maps = {sym: {int(c[0]): idx for idx, c in enumerate(rows)} for sym, rows in norm_candles.items()}

    def _eval_arm(label: str, sys_prompt: str) -> Dict[str, Any]:
        cache_hits = 0
        llm_calls = 0
        total_slots = 0
        omitted_slots = 0
        geom_rejected = 0
        longs = 0
        shorts = 0
        waits = 0
        trade_rs: List[float] = []
        eq = 10000.0
        peak = eq
        max_dd = 0.0

        for ts_ms in timestamps:
            pkgs = build_point_in_time_packages(norm_candles, ts_ms, warehouse=wh)
            if not pkgs:
                continue
            tstr = datetime.datetime.fromtimestamp(ts_ms / 1000.0, tz=_BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")
            user_prompt = prompt_builder_fn(pkgs, tstr)
            phash = hashlib.sha256(f"{sys_prompt}\n---\n{user_prompt}".encode("utf-8")).hexdigest()

            cached = wh.get_cached_llm_response(phash, model_name)
            if cached:
                resp = cached["response"]
                cache_hits += 1
            else:
                resp, lat_ms = llm_call_fn(sys_prompt, user_prompt, model_name)
                llm_calls += 1
                wh.put_cached_llm_response(phash, model_name, resp, created_ts_ms=ts_ms, latency_ms=lat_ms)

            decisions = resp.get("decisions") if isinstance(resp, dict) else {}
            if not isinstance(decisions, dict):
                decisions = {}

            for pkg in pkgs:
                sym = pkg["instId"]
                total_slots += 1
                d = decisions.get(sym)
                if not isinstance(d, dict):
                    omitted_slots += 1
                    waits += 1
                    continue
                act = str(d.get("action") or "WAIT").upper()
                if act == "WAIT":
                    waits += 1
                    continue

                entry = float(d.get("entry_price") or pkg["price"] or 0.0)
                tp = float(d.get("take_profit_price") or 0.0)
                sl = float(d.get("stop_loss_price") or 0.0)
                conf = float(d.get("confidence") or 0.0)
                ok, _, _ = validate_quote_geometry_and_rr(act, entry, tp, sl, confidence=conf)
                if not ok:
                    geom_rejected += 1
                    continue

                if act == "BUY_LONG":
                    longs += 1
                else:
                    shorts += 1

                # Simulate forward window conservatively (SL before TP on future bars!)
                idx = ts_idx_maps[sym].get(ts_ms)
                if idx is None:
                    continue
                rows = norm_candles[sym]
                fut = rows[idx + 1 : idx + 1 + horizon_bars]
                if not fut:
                    continue
                r_dist = abs(entry - sl)
                if r_dist <= 0:
                    continue
                qty = risk_usd / r_dist
                outcome_pnl = None
                for bar_row in fut:
                    hi, lo = float(bar_row[2]), float(bar_row[3])
                    if act == "BUY_LONG":
                        if lo <= sl:
                            outcome_pnl = (sl * (1 - 0.0002) - entry) * qty - (entry + sl) * qty * 0.0005
                            break
                        if hi >= tp:
                            outcome_pnl = (tp * (1 - 0.0002) - entry) * qty - (entry + tp) * qty * 0.0005
                            break
                    else:
                        if hi >= sl:
                            outcome_pnl = (entry - sl * (1 + 0.0002)) * qty - (entry + sl) * qty * 0.0005
                            break
                        if lo <= tp:
                            outcome_pnl = (entry - tp * (1 + 0.0002)) * qty - (entry + tp) * qty * 0.0005
                            break
                if outcome_pnl is None:
                    close_px = float(fut[-1][4])
                    outcome_pnl = ((close_px - entry) if act == "BUY_LONG" else (entry - close_px)) * qty - (entry + close_px) * qty * 0.0005

                trade_rs.append(outcome_pnl / risk_usd)
                eq += outcome_pnl
                peak = max(peak, eq)
                if peak > 0:
                    max_dd = max(max_dd, (peak - eq) / peak * 100.0)

        wins = [r for r in trade_rs if r > 0]
        losses = [r for r in trade_rs if r <= 0]
        gw = sum(wins)
        gl = abs(sum(losses))
        return {
            "label": label,
            "total_slots": total_slots,
            "omission_rate_pct": round(omitted_slots / total_slots * 100.0, 2) if total_slots else 0.0,
            "geometry_reject_rate_pct": round(geom_rejected / total_slots * 100.0, 2) if total_slots else 0.0,
            "long_count": longs,
            "short_count": shorts,
            "wait_count": waits,
            "executed_trades": len(trade_rs),
            "win_rate_pct": round(len(wins) / len(trade_rs) * 100.0, 2) if trade_rs else 0.0,
            "profit_factor": round(gw / gl, 2) if gl > 0 else (99.0 if gw > 0 else 0.0),
            "expectancy_r": round(sum(trade_rs) / len(trade_rs), 3) if trade_rs else 0.0,
            "total_return_pct": round((eq - 10000.0) / 100.0, 2),
            "max_drawdown_pct": round(max_dd, 2),
            "cache_hits": cache_hits,
            "llm_calls": llm_calls,
        }

    return {
        "timestamps_evaluated": len(timestamps),
        "baseline": _eval_arm("baseline", system_prompt_a),
        "upgraded": _eval_arm("upgraded", system_prompt_b),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Layer 1 Walk-Forward from MarketReplayWarehouse")
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="Warehouse SQLite path")
    parser.add_argument("--folds", type=int, default=3, help="Number of walk-forward folds")
    args = parser.parse_args()

    wh = MarketReplayWarehouse(Path(args.db))
    from instrument_pool import load_instruments
    syms = [item["instId"] for item in load_instruments() if item.get("instId")]
    candles_1h = {s: wh.query_candles("okx", s, "1H", limit=5000) for s in syms}
    candles_1h = {k: v for k, v in candles_1h.items() if len(v) >= 60}
    funding = {s: wh.query_funding_history("okx", s, limit=2000) for s in candles_1h}
    res = run_deterministic_walk_forward(candles_1h, funding_by_symbol=funding, n_folds=args.folds)
    print(json.dumps(res, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
