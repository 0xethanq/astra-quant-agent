"""全市场提示词装配（B3 抽取第五块）。

从 `scripts/ai_brain_trader.py` 原 L%d-L%d（%d 行）搬出：把本轮所有标的的行情、
数理基石、账户上下文与策略快照渲染成**发给模型的用户提示词**。

## 注入面（15 项，全部是门面名）

这块的注入面是本阶段最宽的一处 —— 因为它是"装配中心"，本来就要读全局配置。
逐项列明，**每项都有不得不注入的理由**：

### 被测试缝钉住的（不注入就会静默失效）

| 依赖 | 缝在哪 |
|---|---|
| `safe_float` | 门面私有函数；门面会被 `pin_baseline_risk_env()` 原地重载 |
| `ai_memory_md_file` / `ai_memory_file` | `tests/self_evolution_safety` 按门面名注入 |
| `news_sentiment_file` | 测试按门面 `NEWS_SENTIMENT_FILE` 注入（本模块参数名去掉 `_FILE`） |

### 必须与执行层同源的风控常量

| 依赖 | 说明 |
|---|---|
| `max_leverage` / `min_leverage` | 与交易侧同一 `risk_constants` 事实源 |
| `max_scale_in_count` / `min_scale_in_confidence` | 金字塔加仓门禁 |
| `max_margin_equity_ratio` | 权益占比硬顶 |

`risk_constants` 的值在 `.env` 改参后由**门面重载**刷新；子模块 import 期绑定
就会变成过期快照 —— 这正是 `astra_backend/README.md` §5 的铁律。
**不是风格问题：提示词里的风控口径与执行层不一致，会让模型按不存在的空间规划。**

### 门面内部函数（保持单一实现）

`sl_atr_mult_for` / `xvenue_prompt_line` / `build_risk_budget_text` /
`active_profile` / `apply_module_layout` / `system_version`。

> `build_risk_budget_text` **留在门面不搬**：它读 22 个 `risk_constants` 常量，
> 搬出去要么注入 22 个参数、要么破坏重载语义。以 `build_risk_budget_text`
> 作为**函数**注入，既保住它的重载语义，又让本模块保持"只依赖入参"。
"""
import datetime
import json
import os
from typing import Any, Dict, List


def construct_full_market_prompt(packages: List[Dict[str, Any]], pos_summary: str = "[MISSING_CONTEXT:account_positions]", active_positions_detail: List[Dict[str, Any]] = None, pending_orders_detail: List[Dict[str, Any]] = None, current_time_str: str = "", usdt_available: float = None, runtime_context_out: Dict[str, Any] = None, policy_snapshot: Dict[str, Any] = None, *,
                             safe_float=None, sl_atr_mult_for=None, xvenue_prompt_line=None,
                             build_risk_budget_text=None, active_profile=None,
                             apply_module_layout=None, system_version=None,
                             ai_memory_md_file=None, ai_memory_file=None,
                             news_sentiment_file=None, max_leverage=None, min_leverage=None,
                             max_scale_in_count=None, min_scale_in_confidence=None,
                             max_margin_equity_ratio=None,
                             _build_position_lines=None, _build_pending_order_lines=None) -> str:
    # --- 注入项解析 ---------------------------------------------------------
    # 两种调用方式必须都成立：
    #   a) 门面薄壳：显式传全部 15 项（生产路径）；
    #   b) 测试按 AST 抽取本函数体后 exec，只传用户参数 —— 此时从被 exec 的
    #      globals 里对应名字取值（`tests/llm/test_prompt_rendering_isolated.py` 就是这么做的，
    #      它的 ns 里注入了 safe_float / 风控常量 / 文件路径 / 门面函数等）。
    # 因此这里用"同名回退"而不是设默认值：默认值会把解析结果固化成 import 期快照。
    _g = globals()

    def _resolve(_name, _fallback=None):
        """按名解析注入项：`_g` 里没有时用 `_fallback`。

        ⚠️ 为什么不是 `_g["NAME"]`：本函数体会被 `tests/llm/test_prompt_rendering_isolated.py`
        **按 AST 抽取后隔离 exec**，那个命名空间只注入它**已知**的名字。用裸下标
        会让"新增一个注入项"直接 KeyError 打挂隔离测试 —— 而隔离测试本来就
        **不该**知道实现细节（它测的是渲染，不是依赖清单）。
        故：显式参数 → `_g` → 回退（懒 import 或 `_g` 取）。
        """
        if _name in _g:
            return _g[_name]
        if _fallback is not None:
            return _fallback()
        raise KeyError(_name)

    if safe_float is None:
        safe_float = _resolve("safe_float", lambda: safe_float)
    if sl_atr_mult_for is None:
        sl_atr_mult_for = _resolve("_sl_atr_mult_for", lambda: _sl_atr_mult_for)
    if xvenue_prompt_line is None:
        xvenue_prompt_line = _resolve("_xvenue_prompt_line", lambda: _xvenue_prompt_line)
    if build_risk_budget_text is None:
        build_risk_budget_text = _resolve("build_risk_budget_text", lambda: build_risk_budget_text)
    if active_profile is None:
        active_profile = _resolve("active_profile", lambda: active_profile)
    if apply_module_layout is None:
        apply_module_layout = _resolve("apply_module_layout", lambda: apply_module_layout)
    if system_version is None:
        system_version = _resolve("__version__", lambda: __version__)
    if ai_memory_md_file is None:
        ai_memory_md_file = _resolve("AI_MEMORY_MD_FILE", lambda: AI_MEMORY_MD_FILE)
    if ai_memory_file is None:
        ai_memory_file = _resolve("AI_MEMORY_FILE", lambda: AI_MEMORY_FILE)
    if news_sentiment_file is None:
        news_sentiment_file = _resolve("NEWS_SENTIMENT_FILE", lambda: NEWS_SENTIMENT_FILE)
    if max_leverage is None:
        max_leverage = _resolve("MAX_LEVERAGE", lambda: MAX_LEVERAGE)
    if min_leverage is None:
        min_leverage = _resolve("MIN_LEVERAGE", lambda: MIN_LEVERAGE)
    if max_scale_in_count is None:
        max_scale_in_count = _resolve("MAX_SCALE_IN_COUNT", lambda: MAX_SCALE_IN_COUNT)
    if min_scale_in_confidence is None:
        min_scale_in_confidence = _resolve("MIN_SCALE_IN_CONFIDENCE", lambda: MIN_SCALE_IN_CONFIDENCE)
    if max_margin_equity_ratio is None:
        max_margin_equity_ratio = _resolve("MAX_MARGIN_EQUITY_RATIO", lambda: MAX_MARGIN_EQUITY_RATIO)
    if _build_position_lines is None:
        _build_position_lines = _resolve(
            "_build_position_lines",
            lambda: __import__("scripts.brain.account_text", fromlist=["x"]).build_position_lines)
    if _build_pending_order_lines is None:
        _build_pending_order_lines = _resolve(
            "_build_pending_order_lines",
            lambda: __import__("scripts.brain.account_text", fromlist=["x"]).build_pending_order_lines)

    tz_bj = datetime.timezone(datetime.timedelta(hours=8))
    now_bj_str = current_time_str or datetime.datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M:%S (北京时间)")
    market_lines = []
    for p in packages:
        k15 = p.get("recent_15m", [])
        k1h = p.get("recent_1h", [])
        k4h = p.get("recent_4h", [])
        quality = p.get("data_quality", "invalid")

        sm = p.get("smart_money", {})
        adx_val = p.get("adx_1h", "--")
        # 审计 P2-5：止损基准不再硬编码「1.5~2.0x」——它必须等于真正下单用的那一套
        # （池条目 per-instrument sl_atr_mult 优先，资产类别档兜底），否则提示词与执行面
        # 又是两份口径（模型以为 1.5~2.0x，实际按 1.4x 下单）。
        sl_atr_desc = f"{sl_atr_mult_for(p):g}x 1H ATR（与执行层同源）"
        calc = p.get("calculus", {})
        calc_tfs = calc.get("timeframes", {}) if isinstance(calc, dict) else {}
        d_int = calc.get("definite_integrals", {}) if isinstance(calc, dict) else {}
        p_th = calc.get("probability_theory", {}) if isinstance(calc, dict) else {}
        calc_1h = calc_tfs.get("1H", {}) if isinstance(calc_tfs.get("1H", {}), dict) else {}
        int_1h = calc_1h.get("definite_integrals", {}) if isinstance(calc_1h, dict) else {}
        prob_1h = calc_1h.get("probability_theory", {}) if isinstance(calc_1h, dict) else {}

        calc_line = (
            f"动力学态={calc.get('regime', 'DATA_UNRELIABLE')} | 速度={calc.get('velocity', '--')} "
            f"| 加速度={calc.get('acceleration', '--')} | 累计冲量={calc.get('impulse', '--')} "
            f"| 冲击变化={calc.get('max_abs_jerk', '--')} | 质量={calc.get('quality', 0)}"
        )
        integral_line = (
            f"多周期净做功积分={d_int.get('energy_integral', 'UNKNOWN')} | 路径偏离面积积分={d_int.get('deviation_area_integral', 'UNKNOWN')} "
            f"| 量价作用积分={d_int.get('volume_action_integral', 'UNKNOWN')} | 能量态={d_int.get('regime', 'UNKNOWN')}"
        )
        prob_line = (
            f"多头延续估计概率={p_th.get('continuation_prob_pct', 'UNKNOWN')}% | 空头击穿估计概率={p_th.get('breakdown_prob_pct', 'UNKNOWN')}% "
            f"| 偏度S={p_th.get('skewness', 'UNKNOWN')} | 超额峰度K={p_th.get('kurtosis', 'UNKNOWN')} "
            f"| 95%VaR={p_th.get('var_95_pct', 'UNKNOWN')}% | 95%CVaR={p_th.get('cvar_95_pct', 'UNKNOWN')}% "
            f"| 尾部风险态={p_th.get('regime', 'UNKNOWN')}"
        )
        core_math_line = (
            f"1H:v={calc_1h.get('velocity', 'UNKNOWN')},a={calc_1h.get('acceleration', 'UNKNOWN')},"
            f"j={calc_1h.get('jerk', 'UNKNOWN')},I={calc_1h.get('impulse', 'UNKNOWN')},态={calc_1h.get('regime', 'UNKNOWN')} "
            f"| E={int_1h.get('energy_integral', 'UNKNOWN')},A={int_1h.get('deviation_area_integral', 'UNKNOWN')} "
            f"| P续={prob_1h.get('continuation_prob_pct', 'UNKNOWN')}%,P破={prob_1h.get('breakdown_prob_pct', 'UNKNOWN')}%,"
            f"VaR={prob_1h.get('var_95_pct', 'UNKNOWN')}%,CVaR={prob_1h.get('cvar_95_pct', 'UNKNOWN')}%"
        )
        calc_tf_line = "；".join(
            f"{tf}:v={v.get('velocity', '--')},a={v.get('acceleration', '--')},I={v.get('impulse', '--')},态={v.get('regime', '--')}"
            for tf, v in calc_tfs.items() if isinstance(v, dict)
        )
        _xv_line = xvenue_prompt_line(p)
        xv_suffix = ("\n" + _xv_line) if _xv_line else ""
        info = f"""---------------------------------------------------------
【{p['name']} ({p['instId']})】| 数据质量: {quality} | 现价: {p['price']} | 24H涨跌: {p['chg24h']}% | 盘口买/卖: {p['bidPx']}/{p['askPx']}
- 🏛️ 三重滤网宏观结构: 4H宏观大势={p.get('macro_4h', '4H_MACRO_RANGE')} | 1H波段结构={p.get('structure_1h', '1H_SWING_CHOP')}
- 👑 顶级聪明钱 (SmartMoney Top100): {("加权做多占比=" + str(sm.get('weighted_long_pct')) + "% | 24H净流入=" + str(sm.get('net_flow_usdt', '--')) + " | 多头均价=" + str(sm.get('avg_long_entry', '--')) + " | 空头均价=" + str(sm.get('avg_short_entry', '--')) + " | " + str(sm.get('top_win_rate', ''))) if sm.get('available') else "数据源缺失（OKX CLI 已移除，暂无公开 V5 等价接口；本项不构成任何方向的证据，禁止臆测填充）"}
- 📐 1H核心波段指标: 1H ATR(14)={p.get('atr_1h', p.get('atr', '--'))} (止损基准: {sl_atr_desc}) | 1H RSI(14)={p.get('rsi_1h', '--')} | 1H ADX趋势强度={adx_val} (注:<20无趋势垃圾市, ≥22强单边)
- ⚡ 15M微观执行参考: 15M ATR={p.get('atr_15m', '--')} | 15M RSI={p.get('rsi_15m', '--')} | VWAP乖离={p.get('vwap_bias', '--')}% | 15M量比={p.get('vol_ratio', '--')}x | OBV资金流={p.get('obv_flow', '--')}
- 📐 1H三大数理基石硬证据: {core_math_line}
- ∂ 多周期微积分动力学摘要: {calc_line}
- ∫ 定积分能量学: {integral_line}
- ⚅ 概率论与统计风险: {prob_line}
- ∂ 分周期速度/加速度/冲量: {calc_tf_line or 'UNKNOWN'}
- 衍生品博弈: 资金费率: {p['fundingRate']}% | OI未平仓: {p['oiUsd']} | 多空比: {p['lsRatio']} | 5M主动吃单净差: {p['takerNetUsd']}{xv_suffix}
- 15M K线(倒序12根 [O,H,L,C,V]): {k15}
- 1H K线(倒序12根 [O,H,L,C,V]): {k1h}
- 4H K线(倒序8根 [O,H,L,C,V]): {k4h}"""
        market_lines.append(info)

    all_market_str = "\n".join(market_lines)

    # Format Active Positions / Pending Limit Orders
    # （阶段 4·B3 第三十刀：两段文本装配迁至 scripts/brain/account_text.py。
    #   经同名回退解析 —— 见本函数开头的注入项解析约定：本函数体会被测试按
    #   AST 抽取后 exec，故子模块函数也必须**按名解析**而不是直接引用。）
    active_pos_text = _build_position_lines(
        active_positions_detail, safe_float=safe_float)
    pending_orders_text = _build_pending_order_lines(
        pending_orders_detail, tz_bj=tz_bj, datetime=datetime)


    from scripts.evolution_shield import render_trading_memory
    # Damaged authority raises; empty authority never falls back to legacy text.
    memory_lessons = render_trading_memory(ai_memory_md_file, ai_memory_file)

    # Harvest Latest Live News & Multi-Coin Sentiment
    news_briefs = []
    macro_env = "中性平衡"
    if os.path.exists(news_sentiment_file):
        try:
            with open(news_sentiment_file, "r", encoding="utf-8") as f:
                ns_data = json.load(f)
                macro_env = ns_data.get("macro_sentiment", "中性平衡")
                raw_latest = ns_data.get("latest_news", [])
                if raw_latest:
                    try:
                        from scripts.news.selection import select_weighted_news, format_news_for_prompt
                        # 标的池关注币种提取（优先保障当前持仓与标的池专属资讯）
                        target_coins = {
                            str(pkg.get("name") or "").upper()
                            for pkg in (packages or [])
                            if pkg.get("name")
                        }
                        if not target_coins and active_positions_detail:
                            for p in active_positions_detail:
                                inst = str(p.get("instId") or p.get("symbol") or "")
                                if inst:
                                    target_coins.add(inst.split("-")[0].upper())
                        selected = select_weighted_news(
                            raw_latest,
                            target_coins=target_coins,
                            total_limit=6,
                            crypto_quota=4,
                            macro_quota=2,
                        )
                        news_briefs = format_news_for_prompt(selected, target_coins=target_coins)
                    except Exception:
                        for n in raw_latest[:6]:
                            news_briefs.append(f"- [{n.get('time', '')}] {n.get('title', '')} ({n.get('summary', '')[:80]}...)")
        except Exception:
            pass

    news_text = "\n".join(news_briefs) if news_briefs else "无可验证新闻输入；不得据此推断市场平稳或不存在事件风险"

    avail_balance_str = f"{usdt_available:.2f} USDT" if usdt_available is not None and usdt_available >= 0 else "[MISSING_CONTEXT:account_balance]"

    risk_budget_text = build_risk_budget_text(usdt_available)

    prompt = f"""======================= 【当前决策时间戳与市场时效】 =======================
【推演基准时间】: {now_bj_str}
【当前账户可用资金】: {avail_balance_str}
{risk_budget_text}

======================= 【全网实时重大快讯与宏观情报】 =======================
【宏观环境基调】: {macro_env}
【最新核心资讯要闻】:
{news_text}

======================= 【账户当前持仓与风险敞口全景】 =======================
【账户持仓概况】: {pos_summary}
【当前活动在途持仓明细】:
{active_pos_text}

======================= 【在途未成交限价挂单 (Pending Maker Orders)】 =======================
【当前在途挂单列表】:
{pending_orders_text}

{memory_lessons}

======================= 【全标的池原生行情、技术指标与筹码矩阵】 =======================
{all_market_str}

================================================================================
【推演与决策任务】:
你只能在 System Prompt 的 P0 硬约束内进行综合裁决。按“数据有效性 → 4H方向 → 1H三大数理基石 → 量能/OI/聪明钱 → 15M执行位置”的顺序逐项检查；任一硬条件失败或证据无法闭环时，开仓输出 WAIT：
1. 【在途持仓管理 (科学持仓与动态风控)】：
   - 逐一分析当前在途持仓：
     • 若 1H 波段趋势完好且微积分动能平稳，坚决坚定持有 (HOLD)，给大波段充分呼吸空间；
     • 若出现【1H 结构破位 / 动能加速度严重逆转 / 聪明钱反向出逃】等真实趋势逆转信号且置信度 ≥ 85%，果断输出 CLOSE_MARKET 提前斩仓止损，杜绝死等硬止损；
     • 若底仓浮盈已超过 1.2x 1H ATR 且需锁定利润，输出 UPDATE_SL 并确保新止损与现价保留 0.7x 1H ATR 安全缓冲，严禁贴脸移动止损。
2. 【在途限价挂单生命周期审查与裁决 (Pending Orders Management)】：
   - 仔细审查上述在途未成交挂单：若挂单价格已大幅偏离最新盘口、或者行情动能/突发要闻已转变导致原挂单计划失效，必须在 pending_orders_management 中为该挂单输出 CANCEL 立即撤单指令，防止挂单成交在不利价格；若原计划仍然有效且价格合适，输出 KEEP 维持挂单。
3. 【多空开仓与顺势浮盈加仓全权裁决 (Opening & Pyramiding)】：
   - 【首发开仓】：自主判断未持仓品种是否具备确定性爆发机会，结合最新资讯、多周期形态与筹码，决定多空方向 (action: BUY_LONG / SELL_SHORT / WAIT)；
   - 【顺势浮盈金字塔加仓申请】：已有多仓仅可输出同向 BUY_LONG，已有空仓仅可输出同向 SELL_SHORT；这只是加仓申请，执行层仍将复核底仓 ROI/保本、最多{max_scale_in_count}次、累计保证金≤【本周期风险预算】单标的上限、置信度≥{min_scale_in_confidence:g}%、加速度与延续/击穿概率门禁。任何不确定均输出 WAIT；
   - 自主规划拟开仓/加仓保证金 (margin_usdt: 可用余额的 5%~{max_margin_equity_ratio:.0%}，且不得超过系统上限) 与杠杆 ({min_leverage:g}~{max_leverage:g}x 内按信心强弱自主裁决)；
   - 自主规划 entry_price、take_profit_price 与 stop_loss_price；目标盈亏比与止盈宽度见【本周期风险预算】，且任何低于其硬底线的报价会被执行层拒绝，超出上限的超远止盈将被执行层自动平滑收窄。
4. 必须输出严格 JSON，格式如下：
{{
  "macro_assessment": "30字内全市场宏观流动性与情绪总结",
  "position_management": [
    {{
      "instId": "LINK-USDT-SWAP",
      "action": "HOLD" | "CLOSE_MARKET" | "UPDATE_SL",
      "suggested_sl_price": float (若调整止损填具体价格，否则0),
      "confidence": 0~100,
      "reason": "30字内持仓调整原因与当前动能分析"
    }}
  ],
  "pending_orders_management": [
    {{
      "ordId": "3879092142614409217",
      "instId": "LINK-USDT-SWAP",
      "action": "KEEP" | "CANCEL",
      "reason": "30字内撤单或维持挂单原因"
    }}
  ],
  "decisions": {{
    "BTC-USDT-SWAP": {{
      "action": "BUY_LONG" | "SELL_SHORT" | "WAIT",
      "confidence": 0~100,
      "leverage": {int(max(min_leverage, min(max_leverage, (min_leverage + max_leverage) / 2)))} (杠杆必须落在 {min_leverage:g}~{max_leverage:g} 区间内按信心强弱自主取值：一般信号取下限侧、P0 全通过且概率优势显著才取上限侧；本模板数字仅为占位，严禁无差别照抄),
      "margin_usdt": float (根据信号强度自主取值：常规机会取上方【本周期风险预算】常规单笔区间，强信号可上浮至强信号单笔上限；严禁套用任何固定绝对金额),
      "entry_price": float,
      "take_profit_price": float,
      "stop_loss_price": float,
      "summary_reason": "30字内核心逻辑",
      "market_structure": "4H/1H趋势与15M短线形态",
      "calculus_dynamics": "必须引用1H具体 v/a/j/I、状态及方向解释；WAIT也需说明冲突或缺失",
      "math_prob_rationale": "必须引用具体 E/A、延续或击穿估计概率、VaR/CVaR与肥尾风险",
      "volume_and_oi": "量能/筹码流向简述"
    }},
    ... (依次包含全部标的)
  }}
}}
"""
    regime_text = ""
    regime_data = None
    try:
        from scripts.calculus_engine import detect_macro_market_regime
        regime_data = detect_macro_market_regime(packages)
        regime_text = regime_data.get("summary_text", "")
    except Exception:
        try:
            from calculus_engine import detect_macro_market_regime
            regime_data = detect_macro_market_regime(packages)
            regime_text = regime_data.get("summary_text", "")
        except Exception:
            pass

    runtime_vars = {
        "decision_timestamp": f"【推演基准时间】: {now_bj_str}",
        "account_balance": f"【当前账户可用资金】: {avail_balance_str}",
        "risk_budget": risk_budget_text,
        "account_positions": f"【账户持仓概况】: {pos_summary}\n【当前活动在途持仓明细】:\n{active_pos_text}",
        "pending_orders": f"【当前在途挂单列表】:\n{pending_orders_text}",
        "news_intelligence": f"【宏观环境基调】: {macro_env}\n【最新核心资讯要闻】:\n{news_text}",
        "trading_memory": memory_lessons.strip(),
        "market_regime": regime_text,
        "market_matrix": f"{regime_text}\n\n{all_market_str}" if regime_text else all_market_str,
    }
    _sys_ver = system_version
    profile = active_profile()
    policy_ver = (policy_snapshot or {}).get("policy_version") or os.getenv("ASTRA_VERSION", f"v{_sys_ver}")
    policy_hash = (policy_snapshot or {}).get("policy_hash") or ""
    runtime_vars.update({
        "timestamp": now_bj_str, "timezone": "Asia/Shanghai",
        "active_instruments": ",".join(str(p.get("name") or p.get("instId") or "") for p in packages),
        "strategy_version": policy_ver,
        "policy_version": policy_ver,
        "policy_hash": policy_hash,
        "profile_name": profile.get("name", ""),
    })
    if runtime_context_out is not None:
        runtime_context_out.update(runtime_vars)
        if regime_data:
            runtime_context_out["market_regime"] = regime_data
        if policy_snapshot:
            runtime_context_out["policy_snapshot"] = policy_snapshot
    return apply_module_layout(prompt, profile, "trading_user", f"{profile.get('name', '稳健')}交易用户提示词模板", context=runtime_vars)
