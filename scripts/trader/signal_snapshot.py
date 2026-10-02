"""开仓时刻信号快照组装（B3 抽取·trader 瘦身第二刀，第八十二刀）。

从 `scripts/ai_factor_trader.py` **纯搬家** `build_signal_snapshot`（85 行，
零交易动作：只组装 dict 并读一次因子库快照文件）。

## 域归属

这是**自进化复盘**的观测面：开仓瞬间把因果动力学/数理/微观/舆情字段
钉进 journal，供 `self_improvement_engine` 做真实因果归因（2026-09-09
的 schema 错配事故让 22/24 字段恒 None —— 修复的兼容逻辑在函数体内，
本次搬家一字未动，专测 `tests/trading/test_signal_snapshot_schema.py`）。

## 注入形状

唯一外部依赖 `DATA_DIR`（因子库快照文件路径的根）由门面壳**调用期**
注入 —— 专测的 `patch.object(aft, "DATA_DIR", tmp)` patch 面照常生效。
对拍门：`tests/extraction/test_trader_signal_snapshot_extraction.py`。
"""
from __future__ import annotations

import json
import os

#: 快照键 ← 因子库快照 `factor_library_snapshot.json` 的取数表（2026-10 修复）。
#:
#: 每项是 `(快照键, ((组名, 组内键), ...))`，组按优先级从前到后；`组名 is None`
#: 表示取该标的条目的**顶层键**。带 `or` 语义的旧链（如 `trend.get("rsi") or
#: f.get("rsi")`）留在上方 `snap` 构造里，本表只负责"缺了就补"。
#:
#: **为什么必须有这张表**：真实调用方 `fetch_single_instrument_data` 产出的是
#: **扁平 f**（只有 `f["macd_hist"]` / `f["rsi"]` / `f["calculus"]`，**不含**
#: `trend_momentum` / `microstructure` / `volume_money_flow` / `volume_profile` /
#: `smart_money_derivatives` 等嵌套组）—— 那套嵌套结构属于**因子库**（`scripts/factors/`）。
#: 于是上方按嵌套组取的 18 项 7 梯队因子在**生产里恒为 None**：宿主可观测性审计
#: 恒判 `PRICE_ONLY`，自进化复盘的因子归因长期失效（实测 37/37 笔全不可观测）。
#: 旧版本这里只补 `adx` / `funding_rate` / `composite_alpha_score` / `smart_money_net`
#: 四个旧字段，梯队字段一项都没补；本表把补齐面扩到**全部**梯队字段。
#:
#: ⚠️ **为什么不用扁平 f 兜底梯队字段**：时间框架不同，会伪造证据。
#: `f["macd_hist"]` 由 **15M** `closes` 算出（`factors.py`），而因子库的 `macd_hist`
#: 由 **1H** `closes_1h` 算出（`okx_quant_factors.apply_momentum_tier`）；`f["rsi"]`
#: 同样是 15M RSI，**不是** `rsi_1h`。把 15M 值填进 1H 槽位 = 把"看起来可观测"的错
#: 数据喂给复盘，正是宿主宪章禁止的倒推伪造。故梯队字段**只认因子库真源**，
#: 取不到就保持 None（诚实地不可观测）。
_TIER_LIBRARY_SOURCES = (
    # ---- T4 趋势动量（1H MACD/RSI）----
    ("macd_hist", (("trend_momentum", "macd_hist"),)),
    ("macd_accel", (("trend_momentum", "macd_accel"),)),
    ("macd_hist_pct", (("trend_momentum", "macd_hist_pct"),)),
    ("macd_accel_pct", (("trend_momentum", "macd_accel_pct"),)),
    ("macd_momentum_state", (("trend_momentum", "macd_momentum_state"),)),
    ("macd_divergence", (("trend_momentum", "macd_divergence"),)),
    ("rsi_1h", (("trend_momentum", "rsi_1h"),)),
    ("rsi_zone", (("trend_momentum", "rsi_zone"),)),
    ("rsi_divergence", (("trend_momentum", "rsi_divergence"),)),
    # ---- T0.5 订单流 ----
    ("cvd_5m_usd", (("volume_money_flow", "cvd_5m_usd"),)),
    ("cvd_1h_usd", (("volume_money_flow", "cvd_1h_usd"),)),
    ("cvd_divergence", (("volume_money_flow", "cvd_divergence"),)),
    ("taker_buy_sell_ratio", (("volume_money_flow", "taker_buy_sell_ratio"),)),
    # ---- T1 微观结构 ----
    ("obi_pct", (("microstructure", "obi_pct"),)),
    ("bid_ask_depth_ratio", (("microstructure", "bid_ask_depth_ratio"),)),
    ("spread_bps", (("microstructure", "spread_bps"),)),
    # ---- T3 价值区 / 筹码（`vwap_bias_pct` 两处都可能承载）----
    ("vwap_bias_pct", (("volume_profile", "vwap_bias_pct"),
                       ("trend_momentum", "vwap_bias_pct"))),
    ("value_area_position", (("volume_profile", "value_area_position"),)),
    ("vpvr_poc", (("volume_profile", "vpvr_poc"),)),
    # ---- T0 衍生品资金 / 持仓量 ----
    ("funding_rate_pct", (("smart_money_derivatives", "funding_rate_pct"),)),
    ("funding_crowding", (("smart_money_derivatives", "funding_crowding"),)),
    ("oi_chg_1h_pct", (("smart_money_derivatives", "oi_chg_1h_pct"),)),
    ("oi_price_quadrant", (("smart_money_derivatives", "oi_price_quadrant"),)),
    ("elite_divergence", (("smart_money_derivatives", "elite_divergence"),)),
    ("basis_annualized_pct", (("smart_money_derivatives", "basis_annualized_pct"),)),
    # ---- 旧口径四字段（原有补齐面，语义逐字保留）----
    ("adx", (("trend_momentum", "adx_1h"),)),
    ("funding_rate", (("smart_money_derivatives", "funding_rate_pct"),
                      ("trend_momentum", "funding_rate"))),
    ("smart_money_net", (("smart_money_derivatives", "smart_money_flow_usd"),)),
    ("composite_alpha_score", ((None, "composite_alpha_score"),)),
)


def _lib_pick(libf: dict, sources) -> object:
    """按优先级从因子库条目取第一个非 None 值（保留 0 / False / "" 这类合法假值）。"""
    for group, key in sources:
        container = libf if group is None else (libf.get(group) or {})
        if not isinstance(container, dict):
            continue
        value = container.get(key)
        if value is not None:
            return value
    return None


def build_signal_snapshot(f: dict, *, data_dir: str) -> dict:
    """抽取开仓时刻的因果动力学与数理快照，供自进化复盘做真实因果归因（而非事后倒推）。

    兼容两套数据源 schema（2026-09-09 修复）：
    1. factor_library 快照块结构（calculus_dynamics / probability_theory / definite_integrals）
    2. 执行层 f["calculus"] = calculate_multi_timeframe 聚合结构
       （velocity / max_abs_jerk / 嵌套 probability_theory / definite_integrals）
    旧版只认结构 1，而开仓路径传入的是结构 2，导致 journal 里 22/24 字段恒为
    None → 复盘全量「数理快照不可观测」、逐单归因失效。

    ## 2026-10：归因证据换成 **7 梯队因子**（数理链已退场）

    微积分/定积分/概率论整条链路退场后，上面那套动力学字段永远是 None，
    逐单归因会退化成"什么都不可观测"。同一意图（**开仓时刻的因果证据**）
    现由本函数新增的 `factor_tiers` 扁平键承载：MACD 柱/加速度、RSI 区间、
    CVD、Taker 买卖比、OBI、VWAP 乖离、POC、资金费率、ΔOI 四象限、精英背离。

    旧键（17 个动力学/概率/积分字段）**已从新快照中整体剥离**（2026-10）：
    系统里不存在的因子不该继续以"恒 None 键位"的形式留在证据里 —— 那会让人误以为
    "只是这次没取到"，而不是"这条链路已经不存在了"。历史 journal 里的旧键仍可读，
    由 `observability.RETIRED_DYNAMICS_FIELDS` 作为**容忍名单**处理。

    ## ⚠️ 2026-10 修复：梯队因子的真源是**因子库**，不是执行层 f

    上面的"新键"最初按 `f["trend_momentum"]` / `f["microstructure"]` 等**嵌套组**取值，
    但真实调用方 `fetch_single_instrument_data` 产出的是**扁平 f**（只有
    `f["macd_hist"]` / `f["rsi"]` / `f["calculus"]`），嵌套结构属于**因子库**
    （`scripts/factors/`）。于是 18 项梯队因子在生产里**恒为 None**：
    实测台账/journal 里 37/37 笔全判 `PRICE_ONLY`、自进化复盘长期无因子可归因。

    现行口径（见 `_TIER_LIBRARY_SOURCES`）：嵌套组优先（兼容因子库形态的调用方），
    缺了就按表从 `factor_library_snapshot.json` **补齐全部梯队字段**。
    刻意**不**用扁平 f 兜底梯队字段 —— `f["macd_hist"]` 是 **15M** 口径、因子库的
    `macd_hist` 是 **1H** 口径，`f["rsi"]` 同样是 15M RSI 而非 `rsi_1h`；
    跨时间框架回填等于伪造证据（宿主宪章明令禁止），取不到宁可保持 None。
    """
    micro = f.get("microstructure") or {}
    money = f.get("smart_money_derivatives") or {}
    trend = f.get("trend_momentum") or {}
    flow = f.get("volume_money_flow") or {}
    value = f.get("volume_profile") or {}
    snap = {
        "price": f.get("price"),
        "atr": f.get("atr"),
        # ---- 2026-10 新证据链：7 梯队因子（复盘归因的真实可观测字段）----
        "macd_hist": trend.get("macd_hist"),
        "macd_accel": trend.get("macd_accel"),
        # 归一化（占现价 %）：跨标的复盘可比（低价币绝对值小到看不见）
        "macd_hist_pct": trend.get("macd_hist_pct"),
        "macd_accel_pct": trend.get("macd_accel_pct"),
        "macd_momentum_state": trend.get("macd_momentum_state"),
        "macd_divergence": trend.get("macd_divergence"),
        "rsi_1h": trend.get("rsi_1h") or f.get("rsi_1h"),
        "rsi_zone": trend.get("rsi_zone"),
        "rsi_divergence": trend.get("rsi_divergence"),
        "cvd_5m_usd": flow.get("cvd_5m_usd"),
        "cvd_1h_usd": flow.get("cvd_1h_usd"),
        "cvd_divergence": flow.get("cvd_divergence"),
        "taker_buy_sell_ratio": flow.get("taker_buy_sell_ratio"),
        "obi_pct": micro.get("obi_pct"),
        "bid_ask_depth_ratio": micro.get("bid_ask_depth_ratio"),
        "spread_bps": micro.get("spread_bps"),
        "vwap_bias_pct": value.get("vwap_bias_pct") or trend.get("vwap_bias_pct"),
        "value_area_position": value.get("value_area_position"),
        "vpvr_poc": value.get("vpvr_poc"),
        "funding_rate_pct": money.get("funding_rate_pct"),
        "funding_crowding": money.get("funding_crowding"),
        "oi_chg_1h_pct": money.get("oi_chg_1h_pct"),
        "oi_price_quadrant": money.get("oi_price_quadrant"),
        "elite_divergence": money.get("elite_divergence"),
        "basis_annualized_pct": money.get("basis_annualized_pct"),
        # 2026-10：原「已退役动力学字段保留键位」的 17 个恒 None 僵尸键**已整体剥离**
        # （用户要求：系统里不存在的因子一个都不留）。历史 journal 里的旧键照旧可读
        # —— `scripts/evolution/observability.RETIRED_DYNAMICS_FIELDS` 仍把它们当
        # **容忍名单**处理，只是新快照不再产出。
        "adx": trend.get("adx") or f.get("adx") or f.get("adx_1h"),
        "rsi": trend.get("rsi") or f.get("rsi") or f.get("rsi_14"),
        "funding_rate": micro.get("funding_rate") or f.get("funding_rate"),
        "composite_alpha_score": f.get("composite_alpha_score") or f.get("alpha_score"),
        "smart_money_net": money.get("net_flow") or money.get("taker_net") or money.get("smart_money_flow_usd"),
    }

    # 因子库快照（60s 频，开仓时刻即最新）二次补齐。
    #
    # 2026-10：补齐面由"四个旧字段"扩到**全部梯队字段**（见 `_TIER_LIBRARY_SOURCES`
    # 的模块级说明）。执行层扁平 `f` 里没有梯队因子，因子库才是它们的真源；
    # 不补 = 快照里 18 项全 None = 复盘不可归因。
    # fail-soft 语义逐字保留：文件缺失 / 损坏 / 未命中该标的 / 字段为 None 一律静默
    # 跳过，**绝不伪造**（取不到就保持 None，由宿主审计如实标"不可观测"）。
    if any(snap.get(key) is None for key, _srcs in _TIER_LIBRARY_SOURCES):
        try:
            lib_file = os.path.join(data_dir, "factor_library_snapshot.json")
            if os.path.exists(lib_file):
                with open(lib_file, "r", encoding="utf-8") as handle:
                    lib = json.load(handle)
                entries = lib.get("instruments") or []
                if isinstance(entries, dict):
                    entries = list(entries.values())
                libf = next(
                    (x for x in entries if isinstance(x, dict) and x.get("instId") == f.get("instId")),
                    None,
                )
                if libf:
                    for _key, _sources in _TIER_LIBRARY_SOURCES:
                        if snap.get(_key) is None:
                            snap[_key] = _lib_pick(libf, _sources)
        except Exception:
            pass
    return snap

