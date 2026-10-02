"""多因子提取（B3 抽取第二块）。

从 `scripts/ai_factor_trader.py` 搬出的 `fetch_single_instrument_data`（258 行）——
每个标的每周期跑一次的因子装配。

## 注入的 4 个依赖及其理由

| 依赖 | 为什么注入而不是 import |
|---|---|
| `fetch_candles_direct` | 测试 patch 了 `ai_factor_trader.fetch_candles_direct` |
| `news_sentiment_file` | 测试 patch 了 `ai_factor_trader.NEWS_SENTIMENT_FILE`（本模块参数去掉 `_FILE` 后缀，语义是"路径值"） |
| `instrument_profile` | 留在门面（它自身还读 `ASSET_CLASS_PROFILES`，且被测试按门面属性调用） |
| `load_adaptive_config` | 同上，属于门面里可被替换的配置读取面 |

**通例**：`tests/risk_test_env.py::pin_baseline_risk_env()` 的原地重载名单只有
`risk_constants` / `ai_factor_trader` / `ai_brain_trader`，**不含任何子模块** ——
子模块 import 期绑定的任何风控/配置值都不会被刷新，会让基线风控用例随机翻红。
凡读配置、或读被 patch 路径的东西，一律走调用期注入。

## 可以直接导入的

`calc_*`（6 个）与 `effective_risk_per_trade` / `quantize_size` 都来自
`astra_backend.execution` —— 与门面**同一个对象**，因此
`test_audit_config_p1_alignment` 的 `assertIs(getattr(trader, name), getattr(sizing, name))`
照旧成立。`calculate_multi_timeframe` 与其所属的 `calculus_engine` 已整体删除
（2026-10：数理链退场，不再有任何调用方）。
"""
import json
import os
import urllib
import warnings

from astra_backend.execution import (
    calc_atr,
    calc_bollinger_squeeze,
    calc_ema,
    calc_macd_histogram_acceleration,
    calc_obv_trend,
    calc_rsi,
    effective_risk_per_trade,
    quantize_size,
)


def fetch_single_instrument_data(item, all_positions, usdt_available, *,
                                 news_sentiment_file,
                                 fetch_candles_direct,
                                 instrument_profile,
                                 load_adaptive_config):
    """装配单个标的的多因子特征字典。依赖由门面注入，理由见模块 docstring。"""
    inst_id = item["instId"]
    name = item["name"]
    asset_type = item["type"]
    base_sz = item["base_sz"]
    # 交易所最小下单量与步长（OKX 多数永续为 0.01 张），此前被代码的 int()+max(1,..) 完全忽略
    min_sz = float(item.get("minSz", 1) or 1)

    f = {
        "instId": inst_id,
        "name": name,
        "type": asset_type,
        "base_sz": base_sz,
        "sz": base_sz,
        "precision": item["precision"],
        "ctVal": item["ctVal"],
        "risk_per_trade_usd": effective_risk_per_trade(item.get("risk_per_trade_usd", 0.0), usdt_available),
        "minSz": min_sz,
        # 标的分级信息随因子包下发，供拦截插件与提示词按「层级」而非写死币种名做通用判断
        "tier": item.get("tier", "tier_2_momentum"),
        "max_leverage": item.get("max_leverage", 3),
        "sl_atr_mult": item.get("sl_atr_mult", 2.2),
        "price": 0.0,
        "change24h": 0.0,
        "vol24h": 0.0,
        # ★ 2026-10「不许假数据」：以下全部由"看起来合理的值"改为**显式缺失**。
        #   旧初值把未取到数据的标的说成"RSI 中性 50 / 量能正常 1.0x / 区间震荡 CHOP /
        #   1H·4H 趋势看多 True"—— 其中 `trend_*_bullish=True` 是**方向性**假值
        #   （默认偏多），`rsi=50.0` 还恰好落在做多形态的命中带里。
        #   这些字段现在只有真算出来才有值；没算出来就是 None，由 `market_data_valid`
        #   闸（本函数结尾）与 `signals.py` 的显式缺失检查 fail-closed。
        "rsi": None,
        "rsi_7": None,
        "ema9": None,
        "ema21": None,
        "ema55": None,
        "ema21_slope_pct": None,
        "vwap": None,
        "vwap_bias": None,
        "macd_hist": None,
        "macd_accel": None,
        "obv_flow": None,
        "bb_bandwidth": None,
        "bb_squeeze": None,
        # `atr`/`price` 保留 0.0 **哨兵**：结尾 `market_data_valid` 硬闸 `price > 0 and atr > 0`，
        # 三条下游（signals/position_exit/scale_out）都先查该闸 ⇒ fail-closed，不会当成"零波动"。
        "atr": 0.0,
        "atr_pct": None,
        "vol_15m": None,
        "vol_ma20": None,
        "vol_ratio": None,
        "is_bull_candle_15m": None,
        "is_bear_candle_15m": None,
        "lower_wick_ratio": None,
        "upper_wick_ratio": None,
        "market_regime": None,
        "structure_1h": None,
        "trend_1h_bullish": None,
        "trend_4h_bullish": None,
        "trend_1h_bearish": None,
        "trend_4h_bearish": None,
        "sentiment_score": 0.0,
        "position": None,
        "market_data_valid": False,
        "usdtAvailable": usdt_available
    }

    # Match existing position
    for p in all_positions:
        if p.get("instId") == inst_id:
            pos_val = float(p.get("pos", 0))
            if pos_val != 0:
                f["position"] = {
                    "instId": inst_id,
                    "name": name,
                    "side": p.get("posSide", p.get("side", "")),
                    "pos": pos_val,
                    "avgPx": float(p.get("avgPx", 0)),
                    "markPx": float(p.get("markPx", p.get("last", 0)) or 0),
                    "upl": float(p.get("upl", 0)),
                    "uplRatio": float(p.get("uplRatio", 0) or 0),
                    "lever": p.get("lever", "3"),
                    "venue": str(p.get("venue") or p.get("exchange") or "okx").lower(),
                    "exchange": str(p.get("venue") or p.get("exchange") or "okx").lower(),
                    # ⚠️ 单位覆盖（历史外所行容错）：若持仓记录自带该场所的原生单位
                    # （旧多所接管的遗留字段），`pos × ctVal × price` 必须用它自己的
                    # `ctVal`/`minSz`/`precision` —— 沿用 OKX 合约池的面值会把名义额
                    # 与手续费算错几个数量级。
                    # OKX 持仓记录不带这些键 ⇒ 值为 `None` ⇒ 下游回落到 `f[...]`，
                    # OKX 路径逐位不变。
                    "ctVal": (float(p["ctVal"]) if p.get("ctVal") else None),
                    "minSz": (float(p["minSz"]) if p.get("minSz") else None),
                    "precision": p.get("precision"),
                    "raw": p.get("raw", {}),
                }
                break

    # 1. Fetch 15M Candles
    # ★ 2026-10：45 → 60。`ema55` 需要 ≥55 根，取 45 根时它**退化等于现价**
    #   （见 `calc_ema` 的缺失语义），而 `signals.py` 用 `px >= ema55*0.994`
    #   判定"顺势回踩"的入场位置 ⇒ 那个条件会恒真。取 60 根后 EMA55 是真指标。
    raw_15m = fetch_candles_direct(inst_id, "15m", 60)
    if raw_15m:
        candles_15m = list(reversed(raw_15m))
        closes = [float(c[4]) for c in candles_15m]
        vols = [float(c[5]) if len(c) > 5 else 1.0 for c in candles_15m]
        
        f["price"] = closes[-1]
        f["rsi"] = calc_rsi(closes, 14)
        f["rsi_7"] = calc_rsi(closes, 7)
        f["ema9"] = calc_ema(closes, 9)
        f["ema21"] = calc_ema(closes, 21)
        f["ema55"] = calc_ema(closes, 55)
        
        # Calculate EMA21 Slope over last 3 bars
        if len(closes) >= 5 and f["ema21"] is not None:
            prev_e21 = calc_ema(closes[:-3], 21)
            if prev_e21:            # None/0 ⇒ 保持缺失，不写 0.0（那是"斜率走平"这个结论）
                f["ema21_slope_pct"] = (f["ema21"] - prev_e21) / prev_e21 * 100.0

        f["atr"] = calc_atr(candles_15m, 14)
        if f["price"] > 0:
            f["atr_pct"] = (f["atr"] / f["price"]) * 100.0

        # MACD Acceleration
        m_line, m_sig, m_hist, m_accel = calc_macd_histogram_acceleration(closes)
        f["macd_hist"] = round(m_hist, 4)
        f["macd_accel"] = round(m_accel, 4)

        # OBV Flow
        _, obv_flow = calc_obv_trend(closes, vols)
        f["obv_flow"] = obv_flow

        # Bollinger Bands & Squeeze
        bw, std_d, is_sq = calc_bollinger_squeeze(closes)
        f["bb_bandwidth"] = round(bw, 2)
        f["bb_squeeze"] = is_sq

        # Multi-scale VWAP & Bias
        cum_pv = sum([closes[i] * vols[i] for i in range(-15, 0)])
        cum_v = sum(vols[-15:])
        f["vwap"] = (cum_pv / cum_v) if cum_v > 0 else None
        if f["vwap"] is not None and f["vwap"] > 0:
            f["vwap_bias"] = ((f["price"] - f["vwap"]) / f["vwap"]) * 100.0
        
        # Latest **已闭合** 15M Candle Geometry
        #
        # ★ 2026-10 实盘修复：原取 `candles_15m[-1]` —— 那是 OKX 正在形成的**当前根**。
        #   交易周期固定在 :00/:15/:30/:45 触发，此刻该根刚开盘：开≈收、上下影≈0
        #   ⇒ `is_bull_candle_15m`/`is_bear_candle_15m` 双双为 False、影线比≈0，
        #   而 `signals.py` 的形态闸正是"收阳/收阴**或**长影线"（`>= 0.20`/`>= 0.28`）
        #   ⇒ 三个形态的确认条件在实盘几乎永远不成立。
        #   条文（【因子证据与决策优先级】）本就要求"必须有**已闭合** K 线给出的确认信号"，
        #   故改用最近一根**已收盘**的 15M（`[-2]`）；`price` 仍取当前价（那是真实最新价）。
        last_c = candles_15m[-2] if len(candles_15m) >= 2 else candles_15m[-1]
        c_open, c_high, c_low, c_close = float(last_c[1]), float(last_c[2]), float(last_c[3]), float(last_c[4])
        f["bidPx"] = f["price"]
        f["askPx"] = f["price"]
        # Fetch Real-time Orderbook Ticker BBO (Best Bid & Ask) for Precision Limit Placement
        try:
            req_t = urllib.request.Request(f"https://www.okx.com/api/v5/market/ticker?instId={inst_id}", headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req_t, timeout=3) as response_t:
                d_t = json.loads(response_t.read().decode("utf-8"))
                if d_t.get("code") == "0" and "data" in d_t and len(d_t["data"]) > 0:
                    t_item = d_t["data"][0]
                    f["bidPx"] = float(t_item.get("bidPx", f["price"]) or f["price"])
                    f["askPx"] = float(t_item.get("askPx", f["price"]) or f["price"])
        except Exception as _bbo_err:
            # 2026-09-16：原先静默 pass —— BBO 取不到时 bid/ask 会悄悄退回最新价，
            # 限价精度随之降级而无人知道。保留降级（不阻断取数），但必须留痕。
            warnings.warn(
                f"[factors] {inst_id} BBO 盘口取价失败，bid/ask 退回最新价（限价精度降级）: {_bbo_err!r}",
                RuntimeWarning)

        f["is_bull_candle_15m"] = (c_close > c_open)
        f["is_bear_candle_15m"] = (c_close < c_open)
        
        total_len = max(c_high - c_low, f["price"] * 0.0001)
        lower_wick = min(c_open, c_close) - c_low
        upper_wick = c_high - max(c_open, c_close)
        # ⚠️ 2026-09-30 与下面 1H 分支同一族（同一份坏数据触发）：`price` 为 0 且
        # 高低价齐平时 `total_len` 也是 0 ⇒ 除零崩掉整周期。正常行情下 `total_len`
        # 必然 > 0（价格 > 0 有 0.0001 倍兜底），故这里只挡退化情形、不改任何正常取值。
        if total_len > 0:
            f["lower_wick_ratio"] = lower_wick / total_len
            f["upper_wick_ratio"] = upper_wick / total_len
        
        # ★ 2026-10 实盘修复（与 `scripts/brain/packages.py` 同一族）：量比必须用
        #   **已收盘**的那根 15M。交易周期固定在 :00/:15/:30/:45 触发，此刻 OKX 返回的
        #   `vols[-1]` 是**刚开盘**的当前根（累积量 ≈ 整根的 1%）⇒ 实盘 `vol_ratio`
        #   长期是 0.01~0.06x，于是 `vol_ratio >= 1.25`（量能子分）与 `>= 1.3`
        #   （「动量爆发」「空头加速」两个形态）**永远无法命中** —— 等于把量能证据静默关掉。
        #   现在：最近一根已收盘的量 ÷ 它之前 20 根已收盘均量（排除正在形成的当前根）。
        _closed_vols = vols[:-1]                  # ① 排除正在形成的当前根
        f["vol_15m"] = _closed_vols[-1] if _closed_vols else None
        _baseline = _closed_vols[:-1]             # ② 基线再排除"被比较的那根"本身
        if _baseline:
            _tail = _baseline[-20:]
            f["vol_ma20"] = sum(_tail) / len(_tail)
        if f["vol_ma20"] is not None and f["vol_ma20"] > 0 and f["vol_15m"] is not None:
            f["vol_ratio"] = round(f["vol_15m"] / f["vol_ma20"], 2)

    # 2. Fetch 1H & 4H Trend Confluence
    raw_1h = fetch_candles_direct(inst_id, "1H", 35)
    if raw_1h:
        c_1h = list(reversed(raw_1h))
        closes_1h = [float(c[4]) for c in c_1h]
        highs_1h = [float(c[2]) for c in c_1h]
        lows_1h = [float(c[3]) for c in c_1h]
        
        # 1H ATR 14 for Macro Swing Protection
        f["atr_1h"] = calc_atr(c_1h, 14)
        f["atr_15m"] = f["atr"]
        # ⚠️ 2026-10 审计记录（**未改行为**）：这条 `max(..., price * 0.012)` 是"ATR 下限"，
        #   平静行情里它会**主导** —— 实测 6/6 标的（BTC 83k / ETH 2.6k / SOL 118 …）
        #   下限均大于 1H ATR 与 1.5×15M ATR。后果：仓位标定（`raw_dyn_sz` 用 `atr_val`）
        #   与止损宽度实际上按 **价格的固定 1.2%** 而非市场真实波动走。
        #   这是**风险参数**不是假数据（它明示是下限），但对"按波动自适应"的预期有偏差；
        #   高波动时段（真实 ATR > 1.2% 价）才会回到按波动标定。
        f["atr"] = max(f["atr_1h"], f["atr_15m"] * 1.5, f["price"] * 0.012)
        # ⚠️ 2026-09-30 真机事故：15M 取数被 OKX **429 限流**时 `f["price"]` 保持默认 0
        # （15M 分支整段跳过），而 1H 取数成功 ⇒ 走到这里直接 ZeroDivisionError，
        # **整个交易周期崩掉**（连持仓的追踪止损都不再执行 —— 最危险的失败形态）。
        # 与上面 15M 分支同一口径：价格不可用时不臆造百分比，交给结尾的
        # `market_data_valid` 闸（它会 `sz=0` 并让下游跳过该标的）。
        if f["price"] > 0:
            f["atr_pct"] = (f["atr"] / f["price"]) * 100.0
        
        e9_1h = calc_ema(closes_1h, 9)
        e21_1h = calc_ema(closes_1h, 21)
        # 审计D(2026-09-13)：e55_1h 死算清除（趋势判定只用 e9/e21；ema55 基线另在 f["ema55"] 生产）
        
        if e9_1h is not None and e21_1h is not None:
            f["trend_1h_bullish"] = (e9_1h >= e21_1h and closes_1h[-1] >= e21_1h * 0.996)
            f["trend_1h_bearish"] = (e9_1h <= e21_1h and closes_1h[-1] <= e21_1h * 1.004)

        recent_low = min(lows_1h[-5:])
        prev_low = min(lows_1h[-15:-5])
        recent_high = max(highs_1h[-5:])
        prev_high = max(highs_1h[-15:-5])

        # 结构判定需要 15 根（[-15:-5] 与 [-5:]）⇒ 不够就保持缺失
        if len(lows_1h) >= 15 and len(highs_1h) >= 15:
            if recent_low < prev_low and recent_high < prev_high:
                f["structure_1h"] = "LH_LL"
            elif recent_high > prev_high and recent_low > prev_low:
                f["structure_1h"] = "HH_HL"
            else:
                f["structure_1h"] = "CHOP"
    
    raw_4h = fetch_candles_direct(inst_id, "4H", 25)
    if raw_4h:
        c_4h = list(reversed(raw_4h))
        closes_4h = [float(c[4]) for c in c_4h]
        e9_4h = calc_ema(closes_4h, 9)
        e21_4h = calc_ema(closes_4h, 21)
        if e9_4h is not None and e21_4h is not None:
            f["trend_4h_bullish"] = (e9_4h >= e21_4h)
            f["trend_4h_bearish"] = (e9_4h <= e21_4h)

    # 3. Dynamic Multi-Wave Regime Classification (Strict 15M + 1H + 4H Real-Time Alignment)
    # Anti-Inertia Fix: Never classify as BEAR_TREND if short-term 15M is actively reversing upwards (EMA9 > EMA21) or price > 15M EMA21/55
    # ★ 2026-10：任一输入缺失 ⇒ `market_regime` 保持 **None（未知）**，
    #   不再"一律 CHOP" —— CHOP 是"已判定为区间震荡"这个**结论**，不能用来兜缺失。
    _ema_ready = (f["ema9"] is not None and f["ema21"] is not None and f["price"] > 0)
    _trend_ready = (f["trend_1h_bullish"] is not None or f["trend_1h_bearish"] is not None)
    if _ema_ready and _trend_ready:
        is_15m_bullish = (f["ema9"] >= f["ema21"] and f["price"] >= f["ema21"] * 0.998)
        is_15m_bearish = (f["ema9"] <= f["ema21"] and f["price"] <= f["ema21"] * 1.002)
        if f["trend_1h_bullish"] and is_15m_bullish and (f["structure_1h"] == "HH_HL" or f["price"] >= f["ema21"]):
            f["market_regime"] = "BULL_TREND"
        elif f["trend_1h_bearish"] and is_15m_bearish and (f["structure_1h"] == "LH_LL" or f["price"] <= f["ema21"]):
            f["market_regime"] = "BEAR_TREND"
        else:
            # If 1H says bearish but 15M is rebounding upwards (e.g. V-reversal), strictly lock into CHOP / TRANSITION
            f["market_regime"] = "CHOP"

    # 4. Load Real-time News Sentiment
    if os.path.exists(news_sentiment_file):
        try:
            with open(news_sentiment_file, "r", encoding="utf-8") as f_news:
                n_data = json.load(f_news)
                coins_s = n_data.get("coins_sentiment", {})
                if name in coins_s:
                    f["sentiment_score"] = float(coins_s[name].get("sentiment_factor_score", 0.0) or 0.0)
                # 2026-09-16：区分「情绪=0（真中性）」与「情绪面没读到」。
                # 原先读失败静默 pass，`sentiment_score` 停在默认 0.0 —— 正是
                # 本仓红线「缺失≠0」的反例：主脑会把"没数据"当"中性"。
                f["sentiment_available"] = bool(name in coins_s)
        except Exception as _sent_err:
            f["sentiment_available"] = False
            warnings.warn(
                f"[factors] {name} 舆情文件读取失败，sentiment_score 保持默认"
                f"（标记 sentiment_available=False，不得当成中性）: {_sent_err!r}",
                RuntimeWarning)

    # 5. 已退役：多周期微积分动力学（2026-10 数理链整体退场）
    #
    # 2026-10 第二轮：`f["calculus"]` 的**零动力学占位也已删除** —— 用户要求
    # "系统里不存在的因子一个都不留"。占位键只会让下游误判"只是这次没取到"。
    # 同一「开仓时刻可观测证据」意图现由 7 梯队因子承载
    # （见 `scripts/factors/okx_quant_factors.py` 与 `pkg["quant_factors"]`）。

    # 6. Dynamic Equal-Risk Position Sizing with AI Self-Evolution Kelly Multipliers
    adaptive_cfg = load_adaptive_config()
    pos_multipliers = adaptive_cfg.get("position_size_multipliers", {})
    pos_mult = float(pos_multipliers.get(f["name"], 1.0))

    sl_mult = float(instrument_profile(f, asset_type).get("sl_atr_mult", 1.3))
    atr_val = max(f["atr"], f["price"] * 0.005)
    if f["ctVal"] > 0 and atr_val > 0:
        raw_dyn_sz = (f["risk_per_trade_usd"] * pos_mult) / (f["ctVal"] * atr_val * sl_mult)
        f["sz"] = quantize_size(raw_dyn_sz, min_sz) if pos_mult > 0 else 0.0
    else:
        f["sz"] = quantize_size(base_sz * pos_mult, min_sz) if pos_mult > 0 else 0.0
    # 基准风险额推导出的数量不足交易所最小下单步长 -> 标记为资金规模不匹配，由上层跳过而非放大成 1 张
    f["size_below_exchange_min"] = bool(f["sz"] <= 0 and pos_mult > 0)

    market_data_valid = (
        len(raw_15m) >= 30
        and len(raw_1h) >= 20
        and len(raw_4h) >= 20
        and f["price"] > 0
        and f["atr"] > 0
        and f.get("bidPx", 0) > 0
        and f.get("askPx", 0) >= f.get("bidPx", 0)
        # ★ 2026-10：指标必须**真的算出来**才算有效 —— `calc_ema/calc_rsi` 现在
        #   不足周期返回 None，若闸不查它们，None 会流进 signals/离场链路。
        #   15M 取 60 根 ⇒ EMA55（需 55）满足；1H 取 35（需 21）、4H 取 25（需 21）满足。
        and f["rsi"] is not None
        and f["ema9"] is not None
        and f["ema21"] is not None
        and f["ema55"] is not None
    )
    f["market_data_valid"] = market_data_valid
    if not market_data_valid:
        f["sz"] = 0

    return f
