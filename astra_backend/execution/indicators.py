"""Pure mathematical technical indicators engine for quantitative feature extraction."""
from __future__ import annotations
from typing import List, Tuple, Any


def calc_ema(prices: List[float], period: int) -> float:
    if not prices or len(prices) < period:
        return prices[-1] if prices else 0.0
    k = 2.0 / (period + 1)
    ema = prices[0]
    for p in prices[1:]:
        ema = p * k + ema * (1 - k)
    return ema


def calc_rsi(prices: List[float], period: int = 14) -> float:
    if not prices or len(prices) <= period:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(prices)):
        chg = prices[i] - prices[i - 1]
        if chg >= 0:
            gains.append(chg)
            losses.append(0.0)
        else:
            gains.append(0.0)
            losses.append(abs(chg))

    if len(gains) < period:
        return 50.0
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    for i in range(period, len(gains)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def calc_atr(candles: List[List[Any]], period: int = 14) -> float:
    if not candles or len(candles) < 2:
        return 0.0
    trs = []
    for i in range(1, len(candles)):
        h = float(candles[i][2])
        l = float(candles[i][3])
        prev_c = float(candles[i - 1][4])
        tr = max(h - l, abs(h - prev_c), abs(l - prev_c))
        trs.append(tr)
    if not trs:
        return 0.0
    if len(trs) < period:
        return sum(trs) / len(trs)
    atr = sum(trs[:period]) / period
    for tr in trs[period:]:
        atr = (atr * (period - 1) + tr) / period
    return atr


def calc_macd_histogram_acceleration(prices: List[float], fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[float, float, float, float]:
    """Calculates MACD Line, Signal Line, Histogram, and Histogram Delta (Acceleration)."""
    if len(prices) < slow + signal:
        return 0.0, 0.0, 0.0, 0.0

    k_fast = 2.0 / (fast + 1)
    k_slow = 2.0 / (slow + 1)
    k_sig = 2.0 / (signal + 1)

    fast_ema = prices[0]
    slow_ema = prices[0]
    macd_series = []

    for p in prices:
        fast_ema = p * k_fast + fast_ema * (1 - k_fast)
        slow_ema = p * k_slow + slow_ema * (1 - k_slow)
        macd_series.append(fast_ema - slow_ema)

    sig_ema = macd_series[0]
    hist_series = []
    for m in macd_series:
        sig_ema = m * k_sig + sig_ema * (1 - k_sig)
        hist_series.append(m - sig_ema)

    latest_macd = macd_series[-1]
    latest_sig = sig_ema
    latest_hist = hist_series[-1]
    hist_accel = hist_series[-1] - hist_series[-2] if len(hist_series) >= 2 else 0.0

    return latest_macd, latest_sig, latest_hist, hist_accel


def calc_obv_trend(closes: List[float], vols: List[float], period: int = 14) -> Tuple[float, str]:
    """On-Balance Volume (OBV) and OBV Divergence Slope."""
    if len(closes) < period or len(vols) < period:
        return 0.0, "NEUTRAL"

    obv_val = 0.0
    obv_series = [0.0]
    for i in range(1, len(closes)):
        if closes[i] > closes[i - 1]:
            obv_val += vols[i]
        elif closes[i] < closes[i - 1]:
            obv_val -= vols[i]
        obv_series.append(obv_val)

    recent_obv = obv_series[-5:]
    recent_px = closes[-5:]
    obv_up = recent_obv[-1] > recent_obv[0]
    px_up = recent_px[-1] > recent_px[0]

    if obv_up and not px_up:
        div_state = "BULL_ACCUMULATION"
    elif not obv_up and px_up:
        div_state = "BEAR_DISTRIBUTION"
    elif obv_up and px_up:
        div_state = "BULL_FLOW"
    else:
        div_state = "BEAR_FLOW"

    return obv_val, div_state


def calc_bollinger_squeeze(closes: List[float], period: int = 20, mult: float = 2.0) -> Tuple[float, float, bool]:
    """Bollinger Bandwidth & Squeeze Ratio."""
    if len(closes) < period:
        return 0.0, 0.0, False

    sub = closes[-period:]
    sma = sum(sub) / period
    variance = sum((x - sma) ** 2 for x in sub) / period
    std_dev = variance ** 0.5
    upper = sma + mult * std_dev
    lower = sma - mult * std_dev
    bandwidth = ((upper - lower) / sma) * 100.0 if sma > 0 else 0.0

    is_squeeze = bandwidth < 1.80
    return bandwidth, std_dev, is_squeeze
