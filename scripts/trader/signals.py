"""信号评分（B3 抽取第一块）。

从 `scripts/ai_factor_trader.py`（原 3565 行）搬出的 `evaluate_asset_signal`
与它专用的 `clamp`。

## 为什么是这块

研究文档 B3 要求"只搬纯函数、门面保留被钉字符串、绝不碰 execute_portfolio"。
逐项核对后本块满足全部条件：

- `evaluate_asset_signal` / `clamp` **不在任何测试的源码锚点或结构 split 断言里**
  （已把 8 个测试文件的锚点与 `ENFORCERS` 指纹表逐条比对过）；
- 门面里此函数的 3 处调用点（L2197 / L3169 / L3512）都走**全局名**查找，
  因此原位置留同名薄壳即可，**调用点一行都不用改**；
- 紧邻的 `def single_trader_cycle` 未被 split 钉住，
  且 `execute_portfolio`（含 `# 1a. 跨所封顶`、`# 汇入多所…` 两个被 split 的注释块）不碰。

## 为什么依赖是"注入"而不是 import

`ASSET_CLASS_PROFILES` / `is_in_stop_cooldown` / `load_adaptive_config` 留在门面，
由门面**每次调用时**传入：

1. `is_in_stop_cooldown` 读 `STOP_COOLDOWN_FILE`，而测试会 patch
   `ai_factor_trader.STOP_COOLDOWN_FILE` —— 若本模块在 import 期绑死，patch 会失效；
2. 更隐蔽的一条：`tests/risk_test_env.py::pin_baseline_risk_env()` 只对
   `risk_constants` / `ai_factor_trader` / `ai_brain_trader` 做**原地 reload**。
   本模块不在重载名单里，所以**任何在 import 期烘焙的风控值都不会被刷新** ——
   基线风控测试会随机翻红。注入式调用从结构上消除了这个陷阱。
"""
from astra_backend.math_utils import clamp as _clamp


def clamp(value, lower, upper, default):
    """把 value 夹到 [lower, upper]；不可比较时返回 default。

    结构优化阶段 4·B3 第五十一刀：本函数与 ``scripts/self_improvement_engine.py`` 的同名函数原为逐字重复，
    已收敛到 `astra_backend.math_utils.clamp`。

    ⚠️ 名字保留在本模块：调用点按全局名查找，且 `patch.object(模块, "clamp")`
    是既有接缝（别名赋值会让它失效）。
    """
    return _clamp(value, lower, upper, default)


def evaluate_asset_signal(f, *, asset_class_profiles, is_in_stop_cooldown, load_adaptive_config):
    """连续多因子量化评分（-5.0 ~ +5.0），返回 (score, action, reasons, tag, desc)。

    三个依赖由门面注入，理由见模块 docstring。
"""
    """
    Continuous Multi-Factor Quantitative Scoring Engine (-5.0 ~ +5.0).
    Uses trend, volume, mean-reversion and sentiment sub-scores.
    """
    if not f.get("market_data_valid"):
        return 0.0, "HOLD", ["关键行情数据缺失"], "⚪ 观望", "行情数据不完整，禁止生成交易信号"
    inst_id = f["instId"]
    inst_name = f["name"]
    asset_type = f.get("type", "crypto")
    profile = asset_class_profiles.get(asset_type, asset_class_profiles["crypto"])
    
    # 1. Hot-reload AI Evolution Config
    adaptive_cfg = load_adaptive_config()
    cooldown_assets = adaptive_cfg.get("cooldown_assets", [])
    strat_weights = adaptive_cfg.get("strategy_weights", {})
    strat_enabled = adaptive_cfg.get("strategy_enabled", {})
    entry_threshold = float(adaptive_cfg.get("entry_threshold", profile.get("entry_threshold", 2.2)))

    # Intervene 1: Cooldown Blacklist
    if inst_name in cooldown_assets or inst_id in cooldown_assets:
        return 0.0, "HOLD", ["⛔ 标的处于AI避险冷却池中，自进化系统禁止开仓"], "⚪ 避险冷却", f"【自进化干预】{inst_name} 胜率不足或连续止损，已被自动关入冷却池避险"

    px = f["price"]
    # ★ 2026-10「不许假数据」：核心指标缺失 ⇒ **fail-closed**，不再拿"现价当 EMA"、
    #   "50.0 当 RSI"顶替。旧写法 `f.get("ema9", px)` 会让缺失的 EMA 等于现价，
    #   于是 `ema9 > ema21 > ema55` 退化成 `px > px > px`；`f.get("rsi", 50.0)` 则让
    #   "没有 RSI"直接命中做多形态的 38~56 带。缺失必须显式，不得满足任何入场条件。
    _missing_core = [k for k in ("rsi", "ema9", "ema21", "ema55") if f.get(k) is None]
    if _missing_core:
        return (0.0, "HOLD", [f"关键指标缺失: {','.join(_missing_core)}"], "⚪ 观望",
                f"指标数据不完整（{'、'.join(_missing_core)}），禁止生成交易信号")
    ema9 = f["ema9"]
    ema21 = f["ema21"]
    ema55 = f["ema55"]
    rsi = f["rsi"]
    # 其余证据：缺失一律保持 `None`（比较处显式判空 ⇒ 该条证据不成立），
    # 不再给 "0.0 / 1.0 / NEUTRAL / CHOP" 这类会被读成结论的兜底值。
    e21_slope = f.get("ema21_slope_pct")
    vwap_bias = f.get("vwap_bias")
    macd_hist = f.get("macd_hist")
    macd_accel = f.get("macd_accel")
    obv_flow = f.get("obv_flow")
    vol_ratio = f.get("vol_ratio")
    regime = f.get("market_regime")
    struct_1h = f.get("structure_1h")

    is_bull_c = f.get("is_bull_candle_15m")
    is_bear_c = f.get("is_bear_candle_15m")
    lower_wick = f.get("lower_wick_ratio")
    upper_wick = f.get("upper_wick_ratio")

    cooldown_long = is_in_stop_cooldown(inst_id, "long")
    cooldown_short = is_in_stop_cooldown(inst_id, "short")

    # -------------------------------------------------------------------------
    # 📊 Sub-Factor 1: Trend & Slope Momentum (-1.5 ~ +1.5)
    # -------------------------------------------------------------------------
    score_trend = 0.0
    if regime == "BULL_TREND" and e21_slope is not None and e21_slope > 0.02:
        score_trend = 1.2 + (0.3 if struct_1h == "HH_HL" else 0.0)
    elif regime == "BEAR_TREND" and e21_slope is not None and e21_slope < -0.02:
        score_trend = -1.2 - (0.3 if struct_1h == "LH_LL" else 0.0)
    elif ema9 > ema21 > ema55:
        score_trend = 0.6
    elif ema9 < ema21 < ema55:
        score_trend = -0.6

    # -------------------------------------------------------------------------
    # 📊 Sub-Factor 2: Volume & MACD Acceleration (-1.5 ~ +1.5)
    # -------------------------------------------------------------------------
    score_vol = 0.0
    if macd_accel is not None and macd_hist is not None and macd_accel > 0 and macd_hist > 0:
        score_vol += 0.6
    elif macd_accel is not None and macd_hist is not None and macd_accel < 0 and macd_hist < 0:
        score_vol -= 0.6

    if obv_flow in ["BULL_FLOW", "BULL_ACCUMULATION"]:
        score_vol += 0.5
    elif obv_flow in ["BEAR_FLOW", "BEAR_DISTRIBUTION"]:
        score_vol -= 0.5

    if vol_ratio is not None and vol_ratio >= 1.25 and is_bull_c:
        score_vol += 0.4
    elif vol_ratio is not None and vol_ratio >= 1.25 and is_bear_c:
        score_vol -= 0.4

    # -------------------------------------------------------------------------
    # 📊 Sub-Factor 3: Mean Reversion & RSI Extremes (-1.2 ~ +1.2)
    # -------------------------------------------------------------------------
    score_mr = 0.0
    if vwap_bias is not None and vwap_bias <= -0.75 and rsi <= 35.0:
        score_mr = 1.2 # 超跌反弹多
    elif vwap_bias is not None and vwap_bias >= 0.75 and rsi >= 65.0:
        score_mr = -1.2 # 超买冲高空
    elif 40.0 <= rsi <= 55.0 and regime == "BULL_TREND":
        score_mr = 0.5 # 顺势健康区间
    elif 45.0 <= rsi <= 60.0 and regime == "BEAR_TREND":
        score_mr = -0.5 # 顺势空头区间

    # -------------------------------------------------------------------------
    # 📊 Sub-Factor 4: News & Sentiment (-0.8 ~ +0.8)
    # -------------------------------------------------------------------------
    sent_score = f.get("sentiment_score", 0.0)
    score_sent = max(-0.8, min(0.8, sent_score * 1.5))

    # -------------------------------------------------------------------------
    # 📊 Sub-Factor 5: 7 梯队因子共振（MACD 动量 + 订单流 + 盘口 + 筹码）(-1.5 ~ +1.5)
    #
    # 2026-10 重构：原「因果微积分动力学 + 定积分能量学 + 概率论统计风险」
    # 三块整体退场（用户决策：噱头、无增量信息）。同一"方向证据"意图现由
    # **可观测、可复核**的 7 梯队因子承载：
    #   ① T4 动量：MACD 柱与加速度同向 ⇒ 趋势在延续；背离 ⇒ 反转预警（反向扣分）
    #   ② T0.5 订单流：CVD 与 Taker 买卖比（主动买 − 主动卖）验证"真金白银"方向
    #   ③ T1 盘口：OBI 失衡度（谁在挂单接货）
    #   ④ T3 筹码：VWAP 乖离与价值区位置（价格相对成本中枢的偏离）
    # -------------------------------------------------------------------------
    t4 = f.get("trend_momentum", {}) or {}
    t05 = f.get("volume_money_flow", {}) or {}
    t1 = f.get("microstructure", {}) or {}
    t3 = f.get("volume_profile", {}) or {}
    t0 = f.get("smart_money_derivatives", {}) or {}
    score_calc = 0.0

    def _num(block, key, default=0.0):
        try:
            return float(block.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    c_hist = _num(t4, "macd_hist")
    c_a = _num(t4, "macd_accel")
    c_state = str(t4.get("macd_momentum_state", "") or "")
    c_div = str(t4.get("macd_divergence", "") or "")
    c_rsi_div = str(t4.get("rsi_divergence", "") or "")
    c_cvd5 = _num(t05, "cvd_5m_usd")
    c_taker = _num(t05, "taker_buy_sell_ratio", 1.0)
    c_obi = _num(t1, "obi_pct")
    c_vwap = _num(t3, "vwap_bias_pct")
    c_quadrant = str(t0.get("oi_price_quadrant", "") or "")

    # ① T4 动量：柱体方向与加速度方向
    if c_hist > 0 and c_a > 0:
        score_calc += 0.6
    elif c_hist < 0 and c_a < 0:
        score_calc -= 0.6
    elif c_hist > 0 and c_a < 0:
        score_calc -= 0.3   # 柱体仍正但已在收缩：动能衰减（反 FOMO）
    elif c_hist < 0 and c_a > 0:
        score_calc += 0.3   # 空头动能衰减（反抄底 FOMO）
    if c_state == "EXHAUSTED" or "EXHAUST" in c_state:
        score_calc = score_calc * 0.5

    # ② 顶/底背离：一票反向（最强反转信号）
    # 兼容 okx_quant_factors.py 标准枚举（BEARISH/BULLISH）与旧别名
    if c_div in ("BEARISH", "BEARISH_DIVERGENCE") or c_rsi_div in ("BEARISH", "BEARISH_DIVERGENCE"):
        score_calc -= 0.5
    elif c_div in ("BULLISH", "BULLISH_DIVERGENCE") or c_rsi_div in ("BULLISH", "BULLISH_DIVERGENCE"):
        score_calc += 0.5

    # ③ T0.5 订单流：CVD 与 Taker 比必须**同向**才算数（单看一个容易被单笔大单骗）
    if c_cvd5 > 0 and c_taker >= 1.05:
        score_calc += 0.4
    elif c_cvd5 < 0 and c_taker <= 0.95:
        score_calc -= 0.4

    # ④ T1 盘口：OBI 失衡（±20% 为强失衡）
    #    ⚠️ 仅在 `depth_reliable` 为真时采信，且优先用多笔档口径：OKX 永续的
    #    触价档会被单笔可撤挂单支配（买一实测在 3~574 张间跳变），而极端失衡
    #    本身可能为真（实测全簿买 17.7 vs 卖 1786 张）⇒ 不可信时整项略过。
    depth_reliable = t1.get("depth_reliable") is True
    if depth_reliable:
        c_obi_robust = _num(t1, "obi_robust_pct", c_obi)
        if c_obi_robust >= 20.0:
            score_calc += 0.3
        elif c_obi_robust <= -20.0:
            score_calc -= 0.3

    # ⑤ T3 筹码：价格相对 24H VWAP 的偏离方向（追高/杀低的反向抑制）
    if c_vwap <= -0.85:
        score_calc += 0.2    # 深度负乖离：均值回归多头倾向
    elif c_vwap >= 0.85:
        score_calc -= 0.2    # 深度正乖离：追高风险
    # ⚠️ 象限名必须与 `classify_derivatives_quadrant()` 的**词表**逐字一致
    #    （涨+OI减=空头爆仓回补 `SHORT_COVERING`；跌+OI减=多头踩踏 `LONG_LIQUIDATION`）。
    #    写成不存在的名字不会报错，只会让这条门**永远不触发** —— 本文件曾因此
    #    静默失效，现由 `tests/trading/test_okx_quant_factors.py::QuadrantVocabularyTest` 钉住。
    if c_quadrant == "SHORT_COVERING":
        score_calc += 0.3
    elif c_quadrant == "LONG_LIQUIDATION":
        score_calc -= 0.3

    score_calc = max(-1.5, min(1.5, score_calc))

    # -------------------------------------------------------------------------
    # 🎯 Continuous Synthesis Multi-Factor Alpha Score
    # -------------------------------------------------------------------------
    raw_alpha_score = round(score_trend + score_vol + score_mr + score_sent + score_calc, 2)
    
    # -------------------------------------------------------------------------
    # 🏆 6 Institutional Quant Setups Recognition
    # -------------------------------------------------------------------------
    strategy_tag = "⚪ 观望"
    strategy_desc = "因子分布中性，无高置信度共振信号"
    reasons = []

    # 波动冲击过滤器（2026-10 由「高 jerk 冲击」改钉 **ATR 冲击 + 点差走阔**）：
    # 极端波动或流动性抽离时，突破类形态的假信号率显著上升。
    atr_pct_now = float(f.get("volatility_channel", {}).get("atr_pct", 0.0) or 0.0)
    spread_now = _num(t1, "spread_bps")
    is_high_jerk_shock = (atr_pct_now >= 4.0 or spread_now >= 15.0)

    # Setup 1: 🌊 顺势机构回踩 (Institutional Pullback)
    if regime == "BULL_TREND" and (px <= ema21 * 1.008 and px >= ema55 * 0.994) and (38.0 <= rsi <= 56.0) and (is_bull_c or (lower_wick is not None and lower_wick >= 0.20)) and not cooldown_long and not is_high_jerk_shock:
        strategy_tag = "🌊 顺势回踩"
        raw_alpha_score = max(raw_alpha_score, 2.4)
        strategy_desc = f"【1H机构顺势】回踩EMA21/55价值中枢止跌收阳(RSI={rsi:.1f}, MACD柱={c_hist:+.2f})，顺势低吸做多"
        reasons = ["1H单边主升结构", "EMA价值区放量承接", "MACD 动能企稳"]

    # Setup 2: ⚡ 阻力抛压做空 (Resistance Exhaustion)
    elif regime == "BEAR_TREND" and (px >= ema21 * 0.992 and px <= ema55 * 1.006) and (44.0 <= rsi <= 62.0) and (is_bear_c or (upper_wick is not None and upper_wick >= 0.20)) and not cooldown_short and not is_high_jerk_shock:
        strategy_tag = "⚡ 阻力抛压"
        raw_alpha_score = min(raw_alpha_score, -2.4)
        strategy_desc = f"【1H机构顺势】反弹测试EMA21/55阻力带右侧收阴遇阻(RSI={rsi:.1f}, MACD柱={c_hist:+.2f})，顺势做空"
        reasons = ["1H单边主跌结构", "EMA阻力带量能衰竭遇阻", "MACD 动能向下发散"]

    # Setup 3: 🚀 动量挤压突破 (Momentum Squeeze Breakout)
    elif (px > ema9) and (55.0 <= rsi <= 74.0) and vol_ratio is not None and vol_ratio >= 1.3 and macd_accel is not None and macd_accel > 0 and is_bull_c and not cooldown_long and (c_a >= -0.2) and not is_high_jerk_shock:
        strategy_tag = "🚀 动量突破"
        raw_alpha_score = max(raw_alpha_score, 2.5)
        strategy_desc = f"【动量爆发】放量突破前高动能发散(量能={vol_ratio}x, MACD加速度={c_a:+.2f})，顺势追涨"
        reasons = ["动量主升放量突破", f"成交量放大 {vol_ratio} 倍", "MACD 正加速度扩张"]

    # Setup 4: 🌪️ 破位放量追空 (Breakdown Acceleration)
    elif (px < ema9) and (26.0 <= rsi <= 45.0) and vol_ratio is not None and vol_ratio >= 1.3 and macd_accel is not None and macd_accel < 0 and is_bear_c and not cooldown_short and (c_a <= 0.2) and not is_high_jerk_shock:
        strategy_tag = "🌪️ 破位追空"
        raw_alpha_score = min(raw_alpha_score, -2.5)
        strategy_desc = f"【空头加速】击穿前低关键支撑放量下泄(量能={vol_ratio}x, MACD加速度={c_a:+.2f})，顺势破位做空"
        reasons = ["空头破位下泄加速", f"放量破位 (量能 {vol_ratio}x)", "MACD 负加速度下泄"]

    # Setup 5: 💎 极值均值回归 (Extreme Mean Reversion)
    elif vwap_bias is not None and vwap_bias <= -0.85 and rsi <= 30.0 and (is_bull_c or (lower_wick is not None and lower_wick >= 0.28)) and not cooldown_long:
        strategy_tag = "💎 极值回归"
        raw_alpha_score = max(raw_alpha_score, 2.3)
        strategy_desc = f"【VWAP极值偏离】量价严重负乖离({vwap_bias:+.2f}%)且RSI超卖({rsi:.1f})，MACD 柱收缩企稳收阳"
        reasons = [f"VWAP严重负偏离 ({vwap_bias:+.2f}%)", "RSI极值超卖区间", "下引线止跌确认"]

    # Setup 6: 🛡️ 流动性猎杀反转 (Liquidity Sweep Reversal)
    elif vwap_bias is not None and vwap_bias >= 0.85 and rsi >= 70.0 and (is_bear_c or (upper_wick is not None and upper_wick >= 0.28)) and not cooldown_short:
        strategy_tag = "🛡️ 冲高反转"
        raw_alpha_score = min(raw_alpha_score, -2.3)
        strategy_desc = f"【冲高衰竭】刺破正乖离极值区({vwap_bias:+.2f}%)受阻长上影线回落(RSI={rsi:.1f})，MACD 柱缩短钝化反转"
        reasons = [f"VWAP严重正偏离 ({vwap_bias:+.2f}%)", "RSI严重超买动能钝化", "上引线受阻承压"]

    # Adaptive strategy enablement and bounded weighting are applied after classification.
    if strategy_tag != "⚪ 观望":
        if strat_enabled.get(strategy_tag, True) is False:
            return 0.0, "HOLD", ["自进化配置已停用该策略"], "⚪ 观望", f"【自进化干预】{strategy_tag} 当前已停用"
        strategy_weight = clamp(strat_weights.get(strategy_tag, 1.0), 0.7, 1.3, 1.0)
        raw_alpha_score *= strategy_weight

    final_score = round(raw_alpha_score, 1)

    # Action Decision based on Adaptive Entry Threshold
    action = "HOLD"
    if final_score >= entry_threshold and not cooldown_long:
        action = "BUY_LONG"
    elif final_score <= -entry_threshold and not cooldown_short:
        action = "SELL_SHORT"

    return final_score, action, reasons, strategy_tag, strategy_desc
