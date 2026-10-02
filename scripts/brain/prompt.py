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

`sl_atr_mult_for` / `build_risk_budget_text` /
`active_profile` / `apply_module_layout` / `system_version`。

> `build_risk_budget_text` **留在门面不搬**：它读 22 个 `risk_constants` 常量，
> 搬出去要么注入 22 个参数、要么破坏重载语义。以 `build_risk_budget_text`
> 作为**函数**注入，既保住它的重载语义，又让本模块保持"只依赖入参"。
"""
import datetime
import json
import os
from typing import Any, Dict, List

# ★ 2026-10 用户拍板：预估型强平热力图**整块移除**（不再生产、不再透传、不再渲染）。
#   原因：R2 是 OI 重建估算，实测毛/净差 26~356×，绝对金额不可信；它既不在 P0–P3
#   证据分级里，又缺少可验证的校准样本。移除后提示词的 T0 行仍保留
#   `smart_money_derivatives` 的**真实**清算脉冲（OKX 口径）。



def construct_full_market_prompt(packages: List[Dict[str, Any]], pos_summary: str = "[MISSING_CONTEXT:account_positions]", active_positions_detail: List[Dict[str, Any]] = None, pending_orders_detail: List[Dict[str, Any]] = None, current_time_str: str = "", usdt_available: float = None, runtime_context_out: Dict[str, Any] = None, policy_snapshot: Dict[str, Any] = None, *,
                             safe_float=None, sl_atr_mult_for=None,
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
        quality = p.get("data_quality", "invalid")

        sm = p.get("smart_money", {})
        # ★ 交易侧包里的 `adx_1h`/`atr`/`vol_ratio` 初值是 0.0/0.0/1.0（取数失败时不写）
        #   ⇒ 直接显示会把"没取到"渲染成"ADX=0.0（无趋势）""ATR=0.0""量比=1.0x（正常量）"。
        #   这里用真值判定：0/None/空一律显示 `--`（真 ADX 与 ATR 不可能为 0）。
        adx_val = p.get("adx_1h") or "--"
        # 审计 P2-5：止损基准不再硬编码「1.5~2.0x」——它必须等于真正下单用的那一套
        # （池条目 per-instrument sl_atr_mult 优先，资产类别档兜底），否则提示词与执行面
        # 又是两份口径（模型以为 1.5~2.0x，实际按 1.4x 下单）。
        sl_atr_desc = f"{sl_atr_mult_for(p):g}x 1H ATR（与执行层同源）"

        # ------------------------------------------------------------------
        # 2026-10 重构：**彻底移除**原始 K 线与数理噱头，改为 7 梯队量化因子。
        #
        # 删掉的是：
        #   - 15M/1H/4H 倒序原始 K 线浮点数组（每标的 ~32 根 [O,H,L,C,V]）；
        #   - 「1H三大数理基石硬证据」/「多周期微积分动力学摘要」/「定积分能量学」
        #     /「概率论与统计风险」/「分周期速度/加速度/冲量」五行。
        # 换上的 7 梯队因子来自 `pkg["quant_factors"]`（= 因子引擎快照的透传，
        # 见 `scripts/brain/packages.py::load_quant_factor_tiers`）：
        # T0 衍生品 / T0.5 订单流 / T1 盘口 / T1.5 期权 / T2 期限 / T3 筹码 / T4 动量。
        #
        # ⚠️ 本函数体会被 `tests/llm/test_prompt_rendering_isolated.py` 按 AST
        #    抽取后隔离 exec —— 故**不得**新增模块级 helper，取值一律内联。
        # ------------------------------------------------------------------
        qf_tiers = p.get("quant_factors") if isinstance(p.get("quant_factors"), dict) else {}
        tm = qf_tiers.get("trend_momentum") if isinstance(qf_tiers.get("trend_momentum"), dict) else {}
        mf = qf_tiers.get("volume_money_flow") if isinstance(qf_tiers.get("volume_money_flow"), dict) else {}
        ms = qf_tiers.get("microstructure") if isinstance(qf_tiers.get("microstructure"), dict) else {}
        smd = qf_tiers.get("smart_money_derivatives") if isinstance(qf_tiers.get("smart_money_derivatives"), dict) else {}
        vp = qf_tiers.get("volume_profile") if isinstance(qf_tiers.get("volume_profile"), dict) else {}
        op = qf_tiers.get("options_structure") if isinstance(qf_tiers.get("options_structure"), dict) else {}

        def _t(block, key, default="--"):
            """梯队取值：缺失/占位一律显式显示 `--`（绝不编造中性值）。"""
            v = block.get(key, default) if isinstance(block, dict) else default
            return default if v is None or v == "" else v

        # 费率与 OI 的"老字段"（`p['fundingRate']` 等）来自主脑自己那一次取数，
        # 梯队快照缺失时它们仍在 —— 两处同源时优先显示梯队值，避免一格两值。
        funding_show = _t(smd, "funding_rate_pct", p.get("fundingRate", "--"))
        oi_show = _t(smd, "oi_usd", p.get("oiUsd", "--"))
        ls_show = _t(smd, "long_short_ratio", p.get("lsRatio", "--"))
        taker_show = _t(mf, "taker_net_usd", p.get("takerNetUsd", "--"))
        spread_show = _t(ms, "spread_bps", p.get("spread_bps", "--"))

        tier_line_t0 = (
            f"- ⚡ T0 衍生品博弈: 当期费率={funding_show}% | 预测费率={_t(smd, 'next_funding_rate_pct')}% "
            f"| 费率拥挤度={_t(smd, 'funding_crowding')} | OI={oi_show} | 1H ΔOI={_t(smd, 'oi_chg_1h_pct')}% "
            f"| OI四象限={_t(smd, 'oi_price_quadrant')} | 散户账户多空比={ls_show} "
            f"| 精英账户比={_t(smd, 'elite_account_ratio')} | 精英持仓比={_t(smd, 'elite_position_ratio')} "
            f"| 精英背离={_t(smd, 'elite_divergence')} | 多头清算={_t(smd, 'liquidation_long_usd')}U "
            f"| 空头清算={_t(smd, 'liquidation_short_usd')}U ({_t(smd, 'liquidation_bias')}) "
            f"| 强平价位堆积={_t(smd, 'liquidation_cluster_top')}"
        )
        tier_line_t05 = (
            f"- 🌊 T0.5 资金与订单流: 5M主动吃单净差={taker_show} | 5M CVD={_t(mf, 'cvd_5m_usd')}U "
            f"| 1H CVD={_t(mf, 'cvd_1h_usd')}U | Taker买卖比={_t(mf, 'taker_buy_sell_ratio')} "
            f"| CVD量价背离={_t(mf, 'cvd_divergence')}"
        )
        tier_line_t1 = (
            f"- 🛡️ T1 盘口与微观深度: 订单簿失衡度(OBI)={_t(ms, 'obi_pct')}%/{_t(ms, 'obi_robust_pct')}%(稳健) ({_t(ms, 'depth_bias')}, 可信={_t(ms, 'depth_reliable')}) "
            f"| Top5买卖深度比={_t(ms, 'bid_ask_depth_ratio')} | Top20深度比={_t(ms, 'depth_ratio_20')} "
            f"| 有效点差={spread_show}bps | 15M量比={p.get('vol_ratio') or '--'}x "
            f"| OBV资金流={p.get('obv_flow', '--')} | CMF={_t(mf, 'cmf_1h')}"
            f"{'' if str(_t(ms, 'depth_reliable')) == 'True' else ' ⚠️盘口厚度被单笔可撤挂单支配 ⇒ OBI 不可作方向证据'}"
        )
        tier_line_t3 = (
            f"- 📊 T3 筹码中枢与分布: 24H VWAP={_t(vp, 'vwap_24h')} (乖离 {_t(tm, 'vwap_bias_pct')}%) "
            f"| σ带宽={_t(vp, 'vwap_sigma_pct')}% | 价值区[VAL={_t(vp, 'val')}, VAH={_t(vp, 'vah')}] "
            f"| VPVR筹码密集峰(POC)={_t(vp, 'vpvr_poc')} | 位置={_t(vp, 'value_area_position')}/{_t(vp, 'vwap_extreme_band')}"
        )
        tier_line_t4 = (
            f"- 📐 T4 动量与形态过滤: 1H RSI(14)={_t(tm, 'rsi_1h', p.get('rsi_1h', '--'))} ({_t(tm, 'rsi_zone')}) "
            f"| 15M RSI(14)={_t(tm, 'rsi_15m', p.get('rsi_15m', '--'))} "
            # ★ 2026-10：绝对 MACD 是**价格单位**的量（BTC 柱 27.88 vs ARB 柱 −1.8e−05），
            # 跨标的不可比；方括号里补归一化口径（占现价 %）供模型横向比较。
            f"| 1H MACD(12,26,9) 柱={_t(tm, 'macd_hist')}[{_t(tm, 'macd_hist_pct')}%价] "
            f"(加速度={_t(tm, 'macd_accel')}[{_t(tm, 'macd_accel_pct')}%价], "
            f"态={_t(tm, 'macd_momentum_state')}, 背离={_t(tm, 'macd_divergence')}) "
            f"| RSI背离={_t(tm, 'rsi_divergence')} | 1H ADX={adx_val} | 1H ATR(14)={(p.get('atr_1h') or p.get('atr') or '--')} "
            f"(止损基准: {sl_atr_desc}) | 布林带宽={_t(qf_tiers.get('volatility_channel') or {}, 'bb_width_1h', '--')}%"
        )
        tier_line_t15 = (
            f"- 🎯 T1.5 期权结构: 可用={_t(op, 'available', False)} | 平值IV={_t(op, 'atm_iv_pct')}% "
            f"| 25d风险反转偏度={_t(op, 'risk_reversal_25d_pct')} | Put/Call OI比={_t(op, 'put_call_oi_ratio')} "
            f"| 最近到期={_t(op, 'expiry')}"
            # Max Pain 只在期权链可用时才有意义：山寨没有期权市场，硬写"持仓量未取回"
            # 会把"标的不存在该市场"说成"取数失败"（两种缺失的处置完全不同）。
            + (f" | 最大痛点(MaxPain)={_t(op, 'max_pain_price')}"
               + ("" if not op.get("max_pain_reason") else f"（{op.get('max_pain_reason')}）")
               if str(_t(op, 'available', False)) in ("True", "true") else " | 最大痛点(MaxPain)=--（该标的无期权市场）")
        )
        if qf_tiers:
            _tier_lines = [tier_line_t0, tier_line_t05, tier_line_t1,
                           tier_line_t3, tier_line_t4, tier_line_t15]
            tier_block = "\n".join(_tier_lines)
        else:
            # 快照缺失时**只出一行**明确说明 —— 把同一句警告重复 6 遍既浪费 token
            # 又让人误以为有 6 条独立证据缺失（实测渲染出来就是那样）。
            tier_block = ("- ⚠️ 7 梯队因子快照缺失（因子引擎尚未产出或该标的缺席）："
                          "本标的**不得**据此臆测资金博弈与筹码位置，"
                          "只能按 4H/1H 结构与本周期风控预算行事")

        info = f"""---------------------------------------------------------
【{p['name']} ({p['instId']})】| 数据质量: {quality} | 现价: {p['price']} | 24H涨跌: {p['chg24h']}% | 盘口买/卖: {p['bidPx']}/{p['askPx']}
- 🏛️ 三重滤网宏观结构: 4H宏观大势={(p.get('macro_4h') or '--')} | 1H波段结构={(p.get('structure_1h') or '--')}
{tier_block}
- 💰 T2 期限与资金成本: 季度基差年化={_t(smd, 'basis_annualized_pct')}% | 杠杆借贷利率={_t(smd, 'loan_rate_usdt')}%
- 👑 顶级聪明钱 (SmartMoney Top100 加权流): {("加权做多占比=" + str(sm.get('weighted_long_pct')) + "% | 24H净流入=" + str(sm.get('net_flow_usdt', '--')) + " | 多头均价=" + str(sm.get('avg_long_entry', '--')) + " | 空头均价=" + str(sm.get('avg_short_entry', '--')) + " | " + str(sm.get('top_win_rate', ''))) if sm.get('available') else "该项（Top100 加权多空比/净流）无公开 V5 等价接口 ⇒ 本行不构成证据；**持仓方向的替代证据见 T0 的「精英账户比 / 精英持仓比 / 精英背离」**（OKX 官方 top-trader 端点，真实可得）。禁止臆测填充"}"""
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

    # ── 提示词正文已全部迁出代码（2026-09-30 重构，用户批准）──────────────────
    # 本函数**只负责装配实时数据**；系统/用户提示词的正文（角色、军规、快节奏
    # 兑现纪律、形态、任务清单、JSON 输出骨架）一律存在 `data/prompt_library.json`
    # 的 `trading_user` 模块里，由其中的 `{{slot}}` 引用下面这份 `runtime_vars`。
    #
    # 因此 `base_text` 传**空串**：`apply_module_layout` 会直接按方案里的模块编排，
    # 并用 `context=runtime_vars` 渲染插槽。这里不再拼任何提示词文本。
    #
    # ⚠️ 历史教训（别退回去）：旧实现把任务清单与**第二份 JSON Schema** 写在这个
    # f-string 里，与 `SYSTEM_PROMPT` 的契约各存一份 ⇒ 两处漂移，表现就是
    # "在工坊里改了、实发却没变"。现在 Schema 只有一份（代码所有、工坊只读）。
    prompt = ""

    # ★ 2026-10 用户拍板：**移除**提示词里的【全市场宏观体制】块。
    #
    # 它是**已退役数理系统**的输出（`scripts/calculus_engine.py` →
    # `scripts/calculus/regime.py`），且缺数据时**凭空编结论**：函数内写死
    # `atr_pct=1.5` / `adx=20.0` 兜底，而实盘 `calculus` 块已完全不存在
    # （因子快照里 6 个标的都没有该块）⇒ 其"震荡指数/冲击风险"是用**假零**算出来的，
    # 却以"当前全市场宏观体制为【X】｜主导方向=Y"的**结论句**进入提示词，且不在
    # P0–P3 证据分级里。实测：给它一份什么都没有的数据包，它会输出
    # 「趋势强度=48.1／波动=29.1／震荡=39.7／方向=BULL」。
    #
    # 移除后提示词仍保留每个标的的**真实** 4H 宏观结构、ADX、ATR 与 T4 动量，
    # 方向证据不缺；而"全市场体制"这种跨标的总括，模型可以自己按真实 4H 结构汇总。
    regime_text = ""
    regime_data = None

    # 分节标题现在由 `data/prompt_library.json` 的模块自己承载；而
    # `render_trading_memory()` 会**前置**同一个标题（那是给 Markdown 镜像用的）。
    # 不剥掉就会在实发提示词里出现**两遍**同名小节（2026-09-30 在
    # data/ai_brain_last_prompt.txt 里实测确认过这个重复）。
    # ⚠️ 刻意写成**行内**逻辑而不是模块级 helper：本函数体会被
    #    tests/llm/test_prompt_rendering_isolated.py 按 AST 抽取后隔离 exec，
    #    那个命名空间只注入它已知的名字，模块级 helper 在那里是 NameError。
    memory_body = memory_lessons.strip()
    if memory_body.startswith("=") and "\n" in memory_body:
        _first, _rest = memory_body.split("\n", 1)
        if "【" in _first:
            memory_body = _rest.strip()

    runtime_vars = {
        "decision_timestamp": f"【推演基准时间】: {now_bj_str}",
        "account_balance": f"【当前账户可用资金】: {avail_balance_str}",
        "risk_budget": risk_budget_text,
        "account_positions": f"【账户持仓概况】: {pos_summary}\n【当前活动在途持仓明细】:\n{active_pos_text}",
        "pending_orders": f"【当前在途挂单列表】:\n{pending_orders_text}",
        "news_intelligence": f"【宏观环境基调】: {macro_env}\n【最新核心资讯要闻】:\n{news_text}",
        "trading_memory": memory_body,
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
        if policy_snapshot:
            runtime_context_out["policy_snapshot"] = policy_snapshot
    return apply_module_layout(prompt, profile, "trading_user", f"{profile.get('name', '稳健')}交易用户提示词模板", context=runtime_vars)
