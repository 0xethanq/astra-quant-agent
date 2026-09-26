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
    ema9 = f.get("ema9", px)
    ema21 = f.get("ema21", px)
    ema55 = f.get("ema55", px)
    e21_slope = f.get("ema21_slope_pct", 0.0)
    rsi = f.get("rsi", 50.0)
    vwap_bias = f.get("vwap_bias", 0.0)
    macd_hist = f.get("macd_hist", 0.0)
    macd_accel = f.get("macd_accel", 0.0)
    obv_flow = f.get("obv_flow", "NEUTRAL")
    vol_ratio = f.get("vol_ratio", 1.0)
    regime = f.get("market_regime", "CHOP")
    struct_1h = f.get("structure_1h", "CHOP")

    is_bull_c = f.get("is_bull_candle_15m", False)
    is_bear_c = f.get("is_bear_candle_15m", False)
    lower_wick = f.get("lower_wick_ratio", 0.0)
    upper_wick = f.get("upper_wick_ratio", 0.0)

    cooldown_long = is_in_stop_cooldown(inst_id, "long")
    cooldown_short = is_in_stop_cooldown(inst_id, "short")

    # -------------------------------------------------------------------------
    # 📊 Sub-Factor 1: Trend & Slope Momentum (-1.5 ~ +1.5)
    # -------------------------------------------------------------------------
    score_trend = 0.0
    if regime == "BULL_TREND" and e21_slope > 0.02:
        score_trend = 1.2 + (0.3 if struct_1h == "HH_HL" else 0.0)
    elif regime == "BEAR_TREND" and e21_slope < -0.02:
        score_trend = -1.2 - (0.3 if struct_1h == "LH_LL" else 0.0)
    elif ema9 > ema21 > ema55:
        score_trend = 0.6
    elif ema9 < ema21 < ema55:
        score_trend = -0.6

    # -------------------------------------------------------------------------
    # 📊 Sub-Factor 2: Volume & MACD Acceleration (-1.5 ~ +1.5)
    # -------------------------------------------------------------------------
    score_vol = 0.0
    if macd_accel > 0 and macd_hist > 0:
        score_vol += 0.6
    elif macd_accel < 0 and macd_hist < 0:
        score_vol -= 0.6

    if obv_flow in ["BULL_FLOW", "BULL_ACCUMULATION"]:
        score_vol += 0.5
    elif obv_flow in ["BEAR_FLOW", "BEAR_DISTRIBUTION"]:
        score_vol -= 0.5

    if vol_ratio >= 1.25 and is_bull_c:
        score_vol += 0.4
    elif vol_ratio >= 1.25 and is_bear_c:
        score_vol -= 0.4

    # -------------------------------------------------------------------------
    # 📊 Sub-Factor 3: Mean Reversion & RSI Extremes (-1.2 ~ +1.2)
    # -------------------------------------------------------------------------
    score_mr = 0.0
    if vwap_bias <= -0.75 and rsi <= 35.0:
        score_mr = 1.2 # 超跌反弹多
    elif vwap_bias >= 0.75 and rsi >= 65.0:
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
    # 📊 Sub-Factor 5: Causal Calculus, Definite Integrals & Probability (-1.5 ~ +1.5)
    # -------------------------------------------------------------------------
    score_calc = 0.0
    c_dyn = f.get("calculus", {})
    c_v = float(c_dyn.get("velocity", 0.0) or 0.0)
    c_a = float(c_dyn.get("acceleration", 0.0) or 0.0)
    c_i = float(c_dyn.get("impulse", 0.0) or 0.0)
    c_j = abs(float(c_dyn.get("max_abs_jerk", 0.0) or 0.0))
    c_regime = c_dyn.get("regime", "")

    # 1. Calculus Dynamics
    if c_regime == "BULL_ACCELERATING" or (c_v > 0.2 and c_a > 0.1 and c_i > 0):
        score_calc += 0.6
    elif c_regime == "BULL_DECELERATING" or (c_v > 0.2 and c_a < -0.3):
        score_calc -= 0.5 # Anti-FOMO deceleration penalty
    elif c_regime == "BEAR_ACCELERATING" or (c_v < -0.2 and c_a < -0.1 and c_i < 0):
        score_calc -= 0.6
    elif c_regime == "BEAR_DECELERATING" or (c_v < -0.2 and c_a > 0.3):
        score_calc += 0.5 # Anti-bottom chasing penalty

    # 2. Definite Integrals (Energy & Area Accumulation)
    d_int = c_dyn.get("definite_integrals", {})
    e_int = float(d_int.get("energy_integral", 0.0) or 0.0)
    dev_area = float(d_int.get("deviation_area_integral", 0.0) or 0.0)
    if e_int > 1.0 and dev_area > 0.6:
        score_calc += 0.4 # Net positive kinetic work done
    elif e_int < -1.0 and dev_area < -0.6:
        score_calc -= 0.4 # Net negative depletion

    # 3. Probability Theory & Stochastic Risk
    p_th = c_dyn.get("probability_theory", {})
    p_cont = float(p_th.get("continuation_prob_pct", 50.0) or 50.0)
    p_break = float(p_th.get("breakdown_prob_pct", 50.0) or 50.0)
    if p_cont >= 70.0:
        score_calc += 0.4
    elif p_break >= 70.0:
        score_calc -= 0.4

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

    # High Jerk Shock Filter: Shock market dampens high-risk breakout setups
    is_high_jerk_shock = (c_j >= 1.8 or c_regime == "SHOCK_HIGH_JERK")

    # Setup 1: 🌊 顺势机构回踩 (Institutional Pullback)
    if regime == "BULL_TREND" and (px <= ema21 * 1.008 and px >= ema55 * 0.994) and (38.0 <= rsi <= 56.0) and (is_bull_c or lower_wick >= 0.20) and not cooldown_long and not is_high_jerk_shock:
        strategy_tag = "🌊 顺势回踩"
        raw_alpha_score = max(raw_alpha_score, 2.4)
        strategy_desc = f"【1H机构顺势】回踩EMA21/55价值中枢止跌收阳(RSI={rsi:.1f}, 微积分速度={c_v:+.2f})，顺势低吸做多"
        reasons = ["1H单边主升结构", "EMA价值区放量承接", "微积分动能企稳"]

    # Setup 2: ⚡ 阻力抛压做空 (Resistance Exhaustion)
    elif regime == "BEAR_TREND" and (px >= ema21 * 0.992 and px <= ema55 * 1.006) and (44.0 <= rsi <= 62.0) and (is_bear_c or upper_wick >= 0.20) and not cooldown_short and not is_high_jerk_shock:
        strategy_tag = "⚡ 阻力抛压"
        raw_alpha_score = min(raw_alpha_score, -2.4)
        strategy_desc = f"【1H机构顺势】反弹测试EMA21/55阻力带右侧收阴遇阻(RSI={rsi:.1f}, 微积分速度={c_v:+.2f})，顺势做空"
        reasons = ["1H单边主跌结构", "EMA阻力带量能衰竭遇阻", "微积分动能向下发散"]

    # Setup 3: 🚀 动量挤压突破 (Momentum Squeeze Breakout)
    elif (px > ema9) and (55.0 <= rsi <= 74.0) and vol_ratio >= 1.3 and macd_accel > 0 and is_bull_c and not cooldown_long and (c_a >= -0.2) and not is_high_jerk_shock:
        strategy_tag = "🚀 动量突破"
        raw_alpha_score = max(raw_alpha_score, 2.5)
        strategy_desc = f"【动量爆发】放量突破前高动能发散(量能={vol_ratio}x, 微积分加速度={c_a:+.2f})，顺势追涨"
        reasons = ["动量主升放量突破", f"成交量放大 {vol_ratio} 倍", "微积分正加速度扩张"]

    # Setup 4: 🌪️ 破位放量追空 (Breakdown Acceleration)
    elif (px < ema9) and (26.0 <= rsi <= 45.0) and vol_ratio >= 1.3 and macd_accel < 0 and is_bear_c and not cooldown_short and (c_a <= 0.2) and not is_high_jerk_shock:
        strategy_tag = "🌪️ 破位追空"
        raw_alpha_score = min(raw_alpha_score, -2.5)
        strategy_desc = f"【空头加速】击穿前低关键支撑放量下泄(量能={vol_ratio}x, 微积分加速度={c_a:+.2f})，顺势破位做空"
        reasons = ["空头破位下泄加速", f"放量破位 (量能 {vol_ratio}x)", "微积分负加速度下泄"]

    # Setup 5: 💎 极值均值回归 (Extreme Mean Reversion)
    elif vwap_bias <= -0.85 and rsi <= 30.0 and (is_bull_c or lower_wick >= 0.28) and not cooldown_long:
        strategy_tag = "💎 极值回归"
        raw_alpha_score = max(raw_alpha_score, 2.3)
        strategy_desc = f"【VWAP极值偏离】量价严重负乖离({vwap_bias:+.2f}%)且RSI超卖({rsi:.1f})，微积分减速企稳收阳"
        reasons = [f"VWAP严重负偏离 ({vwap_bias:+.2f}%)", "RSI极值超卖区间", "下引线止跌确认"]

    # Setup 6: 🛡️ 流动性猎杀反转 (Liquidity Sweep Reversal)
    elif vwap_bias >= 0.85 and rsi >= 70.0 and (is_bear_c or upper_wick >= 0.28) and not cooldown_short:
        strategy_tag = "🛡️ 冲高反转"
        raw_alpha_score = min(raw_alpha_score, -2.3)
        strategy_desc = f"【冲高衰竭】刺破正乖离极值区({vwap_bias:+.2f}%)受阻长上影线回落(RSI={rsi:.1f})，微积分动能钝化反转"
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
