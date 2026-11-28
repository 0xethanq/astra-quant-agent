"""后台「风控管理页」的参数 schema、校验与读写辅助。

单一事实源在 scripts/risk_constants.py（执行层 import 时读取 .env 生效）；
本模块只负责：给前端渲染用的元数据、写入前的服务端校验、以及当前生效值读取。
"""
from __future__ import annotations

import os
import time
from typing import Any, Mapping

from scripts.risk_constants import (
    DEFAULTS,
    RISK_ENV_KEYS,
    MAX_RISK_REWARD_RATIO,
    MAX_TAKE_PROFIT_ATR,
    STOP_LOSS_ATR_MULT,
    MIN_ENTRY_CONFIDENCE,
    MIN_RISK_REWARD_RATIO,
    SCALE_OUT_ENABLED,
    SCALE_OUT_RATIO,
    SCALE_OUT_TRIGGER_ATR,
    effective_daily_loss_limit,
    effective_max_positions,
    effective_single_asset_margin,
    effective_risk_per_trade,
)

# 本进程读取单一事实源（= 读一次 .env）的时刻。后台/worker 是长驻进程：改完 .env 后
# 这里的常量不会自己变，必须重启才同步——把它显式暴露出来，"改了没生效"才看得见。
_LOADED_AT = time.time()

# 分组元数据（前端按此顺序渲染卡片）
GROUPS = [
    {"id": "exposure", "label": "仓位与敞口", "label_en": "Position & Exposure",
     "desc": "控制同时持有多少仓、单边敞口多大、单个标的能吃掉多少保证金。"},
    {"id": "exit_strategy", "label": "出场与分批止盈", "label_en": "Exit & Scale-Out",
     "desc": "核心出场锁利机制：分批止盈开关、首批平仓比例、触发门槛（首屏核心风控）。"},
    {"id": "per_trade", "label": "单笔风险门禁", "label_en": "Per-Trade Risk Gates",
     "desc": "每一笔开仓在下单前必须通过的最低质量门槛。"},
    {"id": "stop_loss", "label": "止损与熔断", "label_en": "Stops & Circuit Breaker",
     "desc": "亏损兜底与时间兜底：日亏熔断、最长持仓时间、止损后冷静期。"},
    {"id": "pyramiding", "label": "顺势金字塔加仓", "label_en": "Pyramiding Scale-In",
     "desc": "浮盈加仓的三重门禁：次数、底仓浮盈、AI 置信度。设为 0 次即彻底禁止加仓。"},
]

# 参数 schema：key = .env 键（与执行层一致）；value 为渲染与校验元数据。
# 所有 min/max/default 均为「原生值」（比例类为小数），前端按 display_scale 换算显示。
_PARAMS: list[dict[str, Any]] = [
    # ── 组1 仓位与敞口 ──
    {"key": "ASTRA_PORTFOLIO_RISK_BUDGET_USDT", "group": "exposure", "tier": "internal",
     "label": "组合风险总预算（账户资金池）", "label_en": "Portfolio Risk Budget",
     "desc": "全系统可支配的组合风险预算总上限（USDT）。0 = 自动按持仓上限×单标的保证金绝对封顶派生。",
     "type": "float", "min": 0.0, "max": 1000000.0, "step": 100.0, "unit": "USDT", "display_scale": 1},
    {"key": "ASTRA_MAX_CONCURRENT_POSITIONS", "group": "exposure", "tier": "core",
     "label": "最高持仓数（总仓位上限）", "label_en": "Max Concurrent Positions",
     "desc": "全系统同时持有的仓位总数上限。0 = 自动跟随标的池容量；超过池容量的配置会被钳制到池容量。",
     "type": "int", "min": 0, "max": 50, "step": 1, "unit": "仓", "display_scale": 1},
    {"key": "ASTRA_MAX_SAME_DIRECTION_POSITIONS", "group": "exposure", "tier": "core",
     "label": "同向持仓上限（单边敞口）", "label_en": "Max Same-Direction Positions",
     "desc": "纯多单或纯空单各自的笔数上限，防高相关标的同向堆叠踩踏。不会超过总仓位上限。",
     "type": "int", "min": 1, "max": 50, "step": 1, "unit": "仓", "display_scale": 1},
    {"key": "ASTRA_MAX_MARGIN_EQUITY_RATIO", "group": "exposure", "tier": "core",
     "label": "单笔保证金占比（硬顶）", "label_en": "Max Margin per Order (% of equity)",
     "desc": "单笔下单占用保证金不得超过可用余额的这个比例，超出部分执行层直接砍掉。也是提示词中「强信号单笔保证金上限」的同口径值。",
     "type": "float", "min": 0.01, "max": 1.0, "step": 0.01, "unit": "%", "display_scale": 100},
    {"key": "ASTRA_SINGLE_ASSET_EQUITY_RATIO", "group": "exposure", "tier": "advanced",
     "label": "单标的累计保证金占比", "label_en": "Single-Asset Margin Cap (% of equity)",
     "desc": "同一标的（含金字塔加仓后）累计占用保证金占可用余额的上限。",
     "type": "float", "min": 0.01, "max": 1.0, "step": 0.01, "unit": "%", "display_scale": 100},
    {"key": "ASTRA_MAX_SINGLE_ASSET_MARGIN_USDT", "group": "exposure", "tier": "internal",
     "label": "单标的保证金绝对封顶", "label_en": "Single-Asset Margin Hard Cap",
     "desc": "单标的累计保证金的绝对金额封顶（USDT；0 = 不设绝对硬顶，纯按比例）。实际生效取 min(本值, 余额×占比上限)，小资金账户自动收紧。",
     "type": "float", "min": 0.0, "max": 100000.0, "step": 10.0, "unit": "USDT", "display_scale": 1},
    {"key": "ASTRA_MAX_TOTAL_EXPOSURE_USDT", "group": "exposure", "tier": "internal",
     "label": "单标同向总敞口上限", "label_en": "Consolidated Same-Side Exposure Cap",
     "desc": "同一标的同方向的合并名义敞口上限（USDT，0 = 不限制）。发送前核算：已开同向名义额 + 本单名义额超过即拒开（不夹取）。",
     "type": "float", "min": 0.0, "max": 1000000.0, "step": 50.0, "unit": "USDT", "display_scale": 1},
    {"key": "ASTRA_MIN_LEVERAGE", "group": "exposure", "tier": "core",
     "label": "单笔杠杆下限", "label_en": "Min Leverage",
     "desc": "AI 自主裁决杠杆的区间下限：模型须在 [下限, 上限] 内按信号强度取值，低于下限会被执行层抬升钳制。调高下限 = 强制放大名义敞口，请配合日亏熔断使用。",
     "type": "float", "min": 1.0, "max": 20.0, "step": 1.0, "unit": "x", "display_scale": 1},
    {"key": "ASTRA_MAX_LEVERAGE", "group": "exposure", "tier": "core",
     "label": "单笔杠杆上限", "label_en": "Max Leverage",
     "desc": "AI 自主裁决杠杆的区间上限：执行层强制钳制不超过此倍数。与「单笔杠杆下限」共同构成模型的自主取值区间。",
     "type": "float", "min": 1.0, "max": 20.0, "step": 1.0, "unit": "x", "display_scale": 1},
    # ── 组2 单笔风险门禁 ──
    {"key": "ASTRA_RISK_PER_TRADE_RATIO", "group": "per_trade", "tier": "advanced",
     "label": "单笔风险额占比（1R）", "label_en": "Risk per Trade (% of equity)",
     "desc": "单笔最大可承受亏损（1R）占可用余额的比例，0.03 = 3% 动态风险。",
     "type": "float", "min": 0.001, "max": 0.2, "step": 0.001, "unit": "%", "display_scale": 100},
    {"key": "ASTRA_MAX_RISK_PER_TRADE_USDT", "group": "per_trade", "tier": "internal",
     "label": "单笔风险额绝对封顶（1R）", "label_en": "Max Risk per Trade Hard Cap",
     "desc": "单笔 1R 最大可承受亏损绝对上限（USDT；0 = 不设绝对硬顶，纯按可用余额×单笔风险额占比动态推导）。实际生效取 min(本值, 余额×占比)，设 0 为纯动态比例。",
     "type": "float", "min": 0.0, "max": 50000.0, "step": 10.0, "unit": "USDT", "display_scale": 1},
    {"key": "ASTRA_MIN_RISK_REWARD", "group": "per_trade", "tier": "advanced",
     "label": "最小盈亏比 R:R 基准底线", "label_en": "Base Minimum R:R Ratio",
     "desc": "单笔交易的基础盈亏比底线。若报价低于此基准但 ≥ 1.2 且 AI 置信度满足高正期望（E ≥ +0.30R），执行层将弹性放行；低于 1.2 物理绝对拦截。",
     "type": "float", "min": 1.0, "max": 10.0, "step": 0.1, "unit": ": 1", "display_scale": 1},
    {"key": "ASTRA_MAX_RISK_REWARD", "group": "per_trade", "tier": "advanced",
     "label": "最大盈亏比 R:R 上限", "label_en": "Max Risk-Reward Ratio Cap",
     "desc": "单笔开仓允许的最大盈亏比上限。超出此上限的止盈报价会被执行层平滑收窄钳制，防止规划无法触及的虚高止盈。须 ≥ 最小盈亏比底线。",
     "type": "float", "min": 2.0, "max": 10.0, "step": 0.1, "unit": ": 1", "display_scale": 1},
    {"key": "ASTRA_MIN_ENTRY_CONFIDENCE", "group": "per_trade", "tier": "core",
     "label": "新开仓最低 AI 置信度", "label_en": "Min Entry Confidence",
     "desc": "AI 裁决置信度低于该百分比时禁止新开仓（金字塔加仓另有独立门禁）。",
     "type": "float", "min": 0.0, "max": 100.0, "step": 1.0, "unit": "%", "display_scale": 1},
    # ── 组3 止损与熔断 ──
    {"key": "ASTRA_DAILY_LOSS_EQUITY_RATIO", "group": "stop_loss", "tier": "core",
     "label": "日亏熔断比例（按余额）", "label_en": "Daily Loss Circuit Breaker (% of equity)",
     "desc": "当日累计已实现亏损达到可用余额的这个比例时，本周期停止新开仓。",
     "type": "float", "min": 0.005, "max": 0.5, "step": 0.005, "unit": "%", "display_scale": 100},
    {"key": "ASTRA_MAX_DAILY_LOSS_USDT", "group": "stop_loss", "tier": "internal",
     "label": "日亏熔断绝对封顶", "label_en": "Daily Loss Hard Cap",
     "desc": "熔断线的绝对金额封顶（USDT）。实际生效取 min(本值, 余额×比例)，小资金账户自动收紧。",
     "type": "float", "min": 1.0, "max": 1000000.0, "step": 10.0, "unit": "USDT", "display_scale": 1},
    {"key": "ASTRA_TIME_STOP_HOURS", "group": "stop_loss", "tier": "core",
     "label": "最长持仓时间（时间止损）", "label_en": "Max Hold Time (Time Stop)",
     "desc": "持仓超过该时长且波幅仍不足横盘带宽时，主动平仓释放保证金与仓位配比。",
     "type": "float", "min": 0.5, "max": 168.0, "step": 0.5, "unit": "小时", "display_scale": 1},
    {"key": "ASTRA_TIME_STOP_ATR_BAND", "group": "stop_loss", "tier": "internal",
     "label": "时间止损横盘带宽", "label_en": "Time-Stop ATR Band",
     "desc": "浮盈绝对值小于「该系数 × 1H ATR」才判定为无突破横盘；调大更易触发时间止损。",
     "type": "float", "min": 0.0, "max": 2.0, "step": 0.05, "unit": "× ATR", "display_scale": 1},
    {"key": "ASTRA_STOP_COOLDOWN_MINUTES", "group": "stop_loss", "tier": "advanced",
     "label": "止损后冷静期", "label_en": "Post-Stop Cooldown",
     "desc": "某标的止损出局后，同标的同方向在该分钟内禁止再次开仓，防情绪化反手与连续磨损。",
     "type": "int", "min": 0, "max": 1440, "step": 5, "unit": "分钟", "display_scale": 1},
    {"key": "ASTRA_STOP_LOSS_ATR_MULT", "group": "stop_loss", "tier": "internal",
     "label": "单笔基准止损宽度 (×ATR)", "label_en": "Base Stop-Loss ATR Band",
     "desc": "单笔止损距离入场价的基准 ATR 倍数（通常为 1.8~2.2x ATR），与标的池档位结合确定防插针安全呼吸空间。",
     "type": "float", "min": 1.0, "max": 4.0, "step": 0.1, "unit": "× ATR", "display_scale": 1},
    # ── 组4 顺势金字塔加仓 ──
    {"key": "ASTRA_MAX_SCALE_IN_COUNT", "group": "pyramiding", "tier": "core",
     "label": "单标的最大加仓次数", "label_en": "Max Scale-In Count",
     "desc": "每个标的允许的顺势浮盈加仓次数；0 = 彻底禁止加仓（只允许底仓）。",
     "type": "int", "min": 0, "max": 10, "step": 1, "unit": "次", "display_scale": 1},
    {"key": "ASTRA_MIN_SCALE_IN_PROFIT_RATIO", "group": "pyramiding", "tier": "internal",
     "label": "加仓最小底仓浮盈率", "label_en": "Min Base-Position Unrealized ROI",
     "desc": "底仓浮盈达到该比例（保本之上）才允许顺势追加，绝不浮盈外加仓。",
     "type": "float", "min": 0.0, "max": 0.2, "step": 0.001, "unit": "%", "display_scale": 100},
    {"key": "ASTRA_MIN_SCALE_IN_CONFIDENCE", "group": "pyramiding", "tier": "internal",
     "label": "加仓最低 AI 置信度", "label_en": "Min Scale-In Confidence",
     "desc": "金字塔加仓需要达到的 AI 置信度门槛，通常应高于新开仓门禁。",
     "type": "float", "min": 0.0, "max": 100.0, "step": 1.0, "unit": "%", "display_scale": 1},
    # ── 组5 出场与分批止盈 ──
    {"key": "ASTRA_SCALE_OUT_ENABLED", "group": "exit_strategy", "tier": "core",
     "label": "启用分批止盈 (Scale-Out)", "label_en": "Enable Scale-Out",
     "desc": "开启后，当浮盈达到触发门槛时，执行层自动市价平仓指定比例锁定现金利润，并同步将剩余仓位推进至成本保本位（1=开启，0=关闭）。",
     "type": "int", "min": 0, "max": 1, "step": 1, "unit": "", "display_scale": 1},
    {"key": "ASTRA_SCALE_OUT_RATIO", "group": "exit_strategy", "tier": "internal",
     "label": "首批平仓止盈比例", "label_en": "Scale-Out Close Ratio",
     "desc": "第一目标达成时市价落袋的仓位百分比，默认 35%（先落袋三分之一强，剩余仓位博大单边）。",
     "type": "float", "min": 0.1, "max": 0.9, "step": 0.05, "unit": "%", "display_scale": 100},
    {"key": "ASTRA_SCALE_OUT_TRIGGER_ATR", "group": "exit_strategy", "tier": "internal",
     "label": "分批止盈触发门槛", "label_en": "Scale-Out Trigger Threshold",
     "desc": "持仓浮盈达到该倍数 × 1H ATR 时启动分批平仓（通常 1.8~2.5x ATR）。"
             "⚠️ 必须不低于止损的 ATR 倍数（池内主流币 1.8、其余 2.2），否则首批止盈会在止损之前落袋，"
             "锁定的 R 小于 1 ⇒ 结构上赢小输大（2026-09-30 实测矫正：旧默认 1.20x 只锁 0.6R）。",
     "type": "float", "min": 1.8, "max": 5.0, "step": 0.1, "unit": "× ATR", "display_scale": 1},
    {"key": "ASTRA_MAX_TAKE_PROFIT_ATR", "group": "exit_strategy", "tier": "internal",
     "label": "单笔最大止盈宽度 (×ATR)", "label_en": "Max Take-Profit ATR Band",
     "desc": "单笔止盈单距离入场价的最大 ATR 跨度。超出此倍数的止盈单会被执行层平滑收窄钳制，防止止盈目标过远导致行情反转无法落袋。",
     "type": "float", "min": 1.5, "max": 8.0, "step": 0.1, "unit": "× ATR", "display_scale": 1},
    {"key": "ASTRA_MAX_PORTFOLIO_OPEN_RISK_R", "group": "exposure", "tier": "core",
     "label": "组合在途净风险上限 (R)", "label_en": "Max Portfolio Open Risk (R)",
     "desc": "所有未保本在途持仓的合计初始下行风险上限（以 1R 为单位）。已提损保本或锁利的仓位记为 0R，超出该上限时抑制新开仓。",
     "type": "float", "min": 0.5, "max": 10.0, "step": 0.5, "unit": "R", "display_scale": 1},
    {"key": "ASTRA_COUNTER_4H_RISK_SCALE", "group": "per_trade", "tier": "internal",
     "label": "逆 4H 大势风险缩放系数", "label_en": "Counter-4H Risk Scale",
     "desc": "开仓方向与 4H 宏观趋势相反时，对单笔 1R 风险预算的缩减倍率（例如 0.5 表示逆势半仓试探）。",
     "type": "float", "min": 0.1, "max": 1.0, "step": 0.1, "unit": "×", "display_scale": 1},
    {"key": "ASTRA_COUNTER_4H_MIN_CONFIDENCE", "group": "per_trade", "tier": "internal",
     "label": "逆 4H 大势最低置信度", "label_en": "Counter-4H Min Confidence",
     "desc": "开仓方向逆 4H 宏观大势时要求达到的最低 AI 置信度，低于该门槛直接拦截。",
     "type": "float", "min": 60.0, "max": 95.0, "step": 1.0, "unit": "%", "display_scale": 1},
    {"key": "ASTRA_LIMIT_ORDER_TTL_MINUTES", "group": "exit_strategy", "tier": "internal",
     "label": "限价挂单有效期 (分钟)", "label_en": "Limit Order TTL (min)",
     "desc": "未成交非减仓限价入场单超过该分钟数后自动撤单，释放账户保证金与并发槽位。",
     "type": "int", "min": 5, "max": 360, "step": 5, "unit": "分钟", "display_scale": 1},
    {"key": "ASTRA_LIMIT_ORDER_DRIFT_ATR", "group": "exit_strategy", "tier": "internal",
     "label": "限价单偏离撤单阈值 (×ATR)", "label_en": "Limit Order Drift (×ATR)",
     "desc": "现价偏离未成交限价入场单价格超过该倍数的 1H ATR 时，自动撤单避免滞后成交。",
     "type": "float", "min": 0.2, "max": 3.0, "step": 0.1, "unit": "× ATR", "display_scale": 1},
]

_INDEX = {p["key"]: p for p in _PARAMS}

# ── 优质预设套件（一键应用；values 为原生单位，必须通过本 schema 校验） ──
SUITES: list[dict[str, Any]] = [
    {"id": "conservative", "name": "保守", "tagline": "本金安全优先 · 严格控制回撤",
     "desc": "适合新手起步、小资金账户或高波动震荡行情。严格将杠杆限制在 2x~3x，单笔仓位最多占用 10% 保证金，"
             "只参与 AI 置信度 ≥85% 的高确定性机会。单笔 1R 风险压降至 1%，单币累计集中度上限 20%，"
             "最小盈亏比门槛提升至 2.2:1，止损冷静期延长至 60 分钟防反复磨损，禁止加仓，"
             "单日亏损达到 3% 即刻熔断停机，全力保护本金防线。",
     "values": {
         "ASTRA_PORTFOLIO_RISK_BUDGET_USDT": 0.0,
         "ASTRA_MAX_CONCURRENT_POSITIONS": 3, "ASTRA_MAX_SAME_DIRECTION_POSITIONS": 2,
         "ASTRA_MAX_MARGIN_EQUITY_RATIO": 0.10, "ASTRA_SINGLE_ASSET_EQUITY_RATIO": 0.20,
         "ASTRA_MAX_SINGLE_ASSET_MARGIN_USDT": 300.0, "ASTRA_MIN_LEVERAGE": 2.0, "ASTRA_MAX_LEVERAGE": 3.0,
         "ASTRA_RISK_PER_TRADE_RATIO": 0.01, "ASTRA_MAX_RISK_PER_TRADE_USDT": 100.0, "ASTRA_MIN_RISK_REWARD": 2.2, "ASTRA_MAX_RISK_REWARD": 3.0,
         "ASTRA_MIN_ENTRY_CONFIDENCE": 85.0,
         "ASTRA_STOP_LOSS_ATR_MULT": 1.8,
         "ASTRA_DAILY_LOSS_EQUITY_RATIO": 0.03, "ASTRA_MAX_DAILY_LOSS_USDT": 100.0,
         "ASTRA_TIME_STOP_HOURS": 12.0, "ASTRA_TIME_STOP_ATR_BAND": 0.10, "ASTRA_STOP_COOLDOWN_MINUTES": 60,
         "ASTRA_MAX_SCALE_IN_COUNT": 0, "ASTRA_MIN_SCALE_IN_PROFIT_RATIO": 0.012, "ASTRA_MIN_SCALE_IN_CONFIDENCE": 85.0,
         "ASTRA_MAX_TOTAL_EXPOSURE_USDT": 600.0,
         "ASTRA_SCALE_OUT_ENABLED": 1, "ASTRA_SCALE_OUT_RATIO": 0.30, "ASTRA_SCALE_OUT_TRIGGER_ATR": 2.20,
         "ASTRA_MAX_TAKE_PROFIT_ATR": 4.20,
         "ASTRA_MAX_PORTFOLIO_OPEN_RISK_R": 2.0, "ASTRA_COUNTER_4H_RISK_SCALE": 0.3,
         "ASTRA_COUNTER_4H_MIN_CONFIDENCE": 85.0, "ASTRA_LIMIT_ORDER_TTL_MINUTES": 60,
         "ASTRA_LIMIT_ORDER_DRIFT_ATR": 1.0,
     }},
    {"id": "balanced", "name": "平衡", "tagline": "出厂默认推荐 · 攻守兼备",
     "desc": "系统出厂推荐基准，适合绝大多数常规趋势行情。杠杆自适应在 2x~5x 之间，单笔仓位上限 20%，"
             "单笔 1R 风险 2%，单币累计集中度上限 30%，盈亏比区间 2.0~3.5，止损冷静期 30 分钟。"
             "当底仓建立可观浮盈后允许顺势追加 1 次，浮盈达 2.0x ATR 时自动平仓 35% 锁定利润并将止损推至成本保本，"
             "日亏 5% 熔断。兼顾收益爆发力与防守底线。",
     "values": {key: DEFAULTS[key] for key in DEFAULTS}},
    {"id": "aggressive", "name": "激进", "tagline": "高频活跃大单边 · 经验交易者专用",
     "desc": "专为追求高周转率与大单边行情的资深交易者打造。杠杆区间放宽至 6x~9.9x，单笔仓位上限提升至 40%，"
             "单笔 1R 风险放大至 4.5%，单币集中度放宽至 48%，盈亏比下限放宽至 1.4:1、上限拉伸至 5.0:1，"
             "止损冷静期缩短至 15 分钟快速再上车。AI 准入门禁 65%，允许顺势金字塔加仓 2 次放大单边赢利，日亏熔断线设为 10%。"
             "在承受合理回撤的前提下最大化波段收益弹性。",
     "values": {
         "ASTRA_PORTFOLIO_RISK_BUDGET_USDT": 0.0,
         "ASTRA_MAX_CONCURRENT_POSITIONS": 0, "ASTRA_MAX_SAME_DIRECTION_POSITIONS": 5,
         "ASTRA_MAX_MARGIN_EQUITY_RATIO": 0.40, "ASTRA_SINGLE_ASSET_EQUITY_RATIO": 0.48,
         "ASTRA_MAX_SINGLE_ASSET_MARGIN_USDT": 0.0, "ASTRA_MIN_LEVERAGE": 6.0, "ASTRA_MAX_LEVERAGE": 9.9,
         "ASTRA_RISK_PER_TRADE_RATIO": 0.045, "ASTRA_MAX_RISK_PER_TRADE_USDT": 0.0, "ASTRA_MIN_RISK_REWARD": 1.4, "ASTRA_MAX_RISK_REWARD": 5.0,
         "ASTRA_MIN_ENTRY_CONFIDENCE": 65.0,
         "ASTRA_STOP_LOSS_ATR_MULT": 1.8,
         "ASTRA_DAILY_LOSS_EQUITY_RATIO": 0.10, "ASTRA_MAX_DAILY_LOSS_USDT": 500.0,
         "ASTRA_TIME_STOP_HOURS": 8.0, "ASTRA_TIME_STOP_ATR_BAND": 0.15, "ASTRA_STOP_COOLDOWN_MINUTES": 15,
         "ASTRA_MAX_SCALE_IN_COUNT": 2, "ASTRA_MIN_SCALE_IN_PROFIT_RATIO": 0.006, "ASTRA_MIN_SCALE_IN_CONFIDENCE": 65.0,
         "ASTRA_MAX_TOTAL_EXPOSURE_USDT": 50000.0,
         "ASTRA_SCALE_OUT_ENABLED": 1, "ASTRA_SCALE_OUT_RATIO": 0.35, "ASTRA_SCALE_OUT_TRIGGER_ATR": 2.00,
         "ASTRA_MAX_TAKE_PROFIT_ATR": 4.20,
         "ASTRA_MAX_PORTFOLIO_OPEN_RISK_R": 4.5, "ASTRA_COUNTER_4H_RISK_SCALE": 0.7,
         "ASTRA_COUNTER_4H_MIN_CONFIDENCE": 75.0, "ASTRA_LIMIT_ORDER_TTL_MINUTES": 90,
         "ASTRA_LIMIT_ORDER_DRIFT_ATR": 1.2,
     }},
]

# 套件自检：键必须全在 schema 内、值必须越界为零、同向≤总仓（显式配置时）
for _s in SUITES:
    for _k, _v in _s["values"].items():
        _p = _INDEX[_k]
        assert _p["min"] <= _v <= _p["max"], f"suite {_s['id']} 越界: {_k}={_v}"
    _total, _same = _s["values"].get("ASTRA_MAX_CONCURRENT_POSITIONS", 0), _s["values"].get("ASTRA_MAX_SAME_DIRECTION_POSITIONS", 3)
    assert _total <= 0 or _same <= _total, f"suite {_s['id']} 同向>总仓"
assert {s["id"] for s in SUITES} == {"conservative", "balanced", "aggressive"}


def suite_values(suite_id: str) -> dict[str, float | int]:
    for s in SUITES:
        if s["id"] == suite_id:
            return dict(s["values"])
    raise ValueError(f"未知风控预设套件: {suite_id}")

# 一致性自检：schema 必须与执行层 DEFAULTS 一一对应，防止悄悄漂移
assert set(_INDEX) == set(DEFAULTS), (
    f"risk schema drift: schema={sorted(set(_INDEX) - set(DEFAULTS))} defaults={sorted(set(DEFAULTS) - set(_INDEX))}")
for _p in _PARAMS:
    _p["default"] = DEFAULTS[_p["key"]]


# ── 审计 P2-9：极端值必须二次确认（逐字短语） ─────────────────────
# 风控页此前允许把单标的占比拉到 100%、日亏熔断拉到 50% 权益，一次点击即落盘——
# 移动端误触就能把硬风控放松到接近失效。超过下表阈值时后端要求 confirmation 逐字
# 匹配 HIGH RISK，前端弹逐字确认框；阈值本身不是硬上限（管理员仍可显式确认后越过），
# 但"悄悄放松风控"不再可能。
HIGH_RISK_PHRASE = "HIGH RISK"
HIGH_RISK_LIMITS: dict[str, float] = {
    "ASTRA_SINGLE_ASSET_EQUITY_RATIO": 0.50,   # 单标的累计保证金占权益 ≥50%
    "ASTRA_DAILY_LOSS_EQUITY_RATIO": 0.25,     # 日亏熔断 ≥25% 权益
    "ASTRA_MAX_MARGIN_EQUITY_RATIO": 0.50,     # 单笔保证金 ≥50% 权益
    "ASTRA_MAX_SINGLE_ASSET_MARGIN_USDT": 5000.0,
    "ASTRA_MAX_LEVERAGE": 10.0,
    "ASTRA_MIN_LEVERAGE": 10.0,
}


def high_risk_changes(values: dict[str, Any]) -> list[dict[str, Any]]:
    """返回本次保存中越过"极端值"线的参数（含阈值与请求值），供路由要求二次确认。"""
    out: list[dict[str, Any]] = []
    for key, threshold in HIGH_RISK_LIMITS.items():
        if key not in values:
            continue
        try:
            value = float(values[key])
        except (TypeError, ValueError):
            continue
        if value < threshold:
            continue
        label = next((p.get("label", key) for p in _PARAMS if p.get("key") == key), key)
        out.append({"key": key, "label": label, "value": value, "threshold": threshold})
    return out


def schema() -> dict[str, Any]:
    # 审计 P2-9：把"极端值线"随 schema 一起给前端，避免前端再抄一份阈值（漂移源）
    params = [
        {**p, "high_risk_at": HIGH_RISK_LIMITS.get(str(p.get("key")))} for p in _PARAMS
    ]
    return {"groups": GROUPS, "params": params, "high_risk_phrase": HIGH_RISK_PHRASE}


def current_values() -> dict[str, float | int]:
    """当前生效值（原生单位）：读进程环境变量（update_env 会同步刷新），缺省回退默认值。"""
    out: dict[str, float | int] = {}
    for p in _PARAMS:
        raw = os.environ.get(p["key"], "")
        try:
            out[p["key"]] = int(float(raw)) if p["type"] == "int" else float(raw)
        except (TypeError, ValueError):
            out[p["key"]] = DEFAULTS[p["key"]]
    return out


def reload_risk_constants() -> None:
    """热重载 scripts.risk_constants 并刷新快照时间戳。

    后台长驻进程在管理员保存修改后即可原地同步新值，无需手动重启后台。
    """
    import importlib
    import scripts.risk_constants as rc

    importlib.reload(rc)
    global _LOADED_AT
    _LOADED_AT = time.time()


def process_values() -> dict[str, float | int]:
    """**本进程内**实际生效的值（= 本进程当前加载的风控常量真实值）。"""
    import scripts.risk_constants as rc

    mapping: dict[str, float | int] = {
        "ASTRA_PORTFOLIO_RISK_BUDGET_USDT": rc.PORTFOLIO_RISK_BUDGET_USDT,
        "ASTRA_MAX_TOTAL_EXPOSURE_USDT": rc.MAX_TOTAL_EXPOSURE_USDT,
        "ASTRA_MAX_CONCURRENT_POSITIONS": rc.MAX_CONCURRENT_POSITIONS_CAP,
        "ASTRA_MAX_SAME_DIRECTION_POSITIONS": rc.MAX_SAME_DIRECTION_POSITIONS,
        "ASTRA_MAX_MARGIN_EQUITY_RATIO": rc.MAX_MARGIN_EQUITY_RATIO,
        "ASTRA_SINGLE_ASSET_EQUITY_RATIO": rc.SINGLE_ASSET_EQUITY_RATIO,
        "ASTRA_MAX_SINGLE_ASSET_MARGIN_USDT": rc.MAX_SINGLE_ASSET_MARGIN,
        "ASTRA_MIN_LEVERAGE": rc.MIN_LEVERAGE,
        "ASTRA_MAX_LEVERAGE": rc.MAX_LEVERAGE,
        "ASTRA_RISK_PER_TRADE_RATIO": rc.RISK_PER_TRADE_EQUITY_RATIO,
        "ASTRA_MIN_RISK_REWARD": rc.MIN_RISK_REWARD_RATIO,
        "ASTRA_MAX_RISK_REWARD": rc.MAX_RISK_REWARD_RATIO,
        "ASTRA_MIN_ENTRY_CONFIDENCE": rc.MIN_ENTRY_CONFIDENCE,
        "ASTRA_STOP_LOSS_ATR_MULT": rc.STOP_LOSS_ATR_MULT,
        "ASTRA_MAX_DAILY_LOSS_USDT": rc.MAX_DAILY_LOSS_USDT,
        "ASTRA_DAILY_LOSS_EQUITY_RATIO": rc.DAILY_LOSS_EQUITY_RATIO,
        "ASTRA_TIME_STOP_HOURS": rc.TIME_STOP_HOURS,
        "ASTRA_TIME_STOP_ATR_BAND": rc.TIME_STOP_ATR_BAND,
        "ASTRA_STOP_COOLDOWN_MINUTES": rc.STOP_COOLDOWN_MINUTES,
        "ASTRA_MAX_SCALE_IN_COUNT": rc.MAX_SCALE_IN_COUNT,
        "ASTRA_MIN_SCALE_IN_PROFIT_RATIO": rc.MIN_SCALE_IN_PROFIT_RATIO,
        "ASTRA_MIN_SCALE_IN_CONFIDENCE": rc.MIN_SCALE_IN_CONFIDENCE,
        "ASTRA_SCALE_OUT_ENABLED": 1 if rc.SCALE_OUT_ENABLED else 0,
        "ASTRA_SCALE_OUT_RATIO": rc.SCALE_OUT_RATIO,
        "ASTRA_SCALE_OUT_TRIGGER_ATR": rc.SCALE_OUT_TRIGGER_ATR,
        "ASTRA_MAX_TAKE_PROFIT_ATR": rc.MAX_TAKE_PROFIT_ATR,
        "ASTRA_MAX_PORTFOLIO_OPEN_RISK_R": rc.MAX_PORTFOLIO_OPEN_RISK_R,
        "ASTRA_COUNTER_4H_RISK_SCALE": rc.COUNTER_4H_RISK_SCALE,
        "ASTRA_COUNTER_4H_MIN_CONFIDENCE": rc.COUNTER_4H_MIN_CONFIDENCE,
        "ASTRA_LIMIT_ORDER_TTL_MINUTES": rc.LIMIT_ORDER_TTL_MINUTES,
        "ASTRA_LIMIT_ORDER_DRIFT_ATR": rc.LIMIT_ORDER_DRIFT_ATR,
    }
    return {key: mapping.get(key, DEFAULTS.get(key, 0)) for key in RISK_ENV_KEYS}


def process_freshness() -> dict[str, Any]:
    """本进程的单一事实源快照 vs `.env` 文件的新鲜度（用于"需重启才生效"提示）。"""
    loaded_at = _LOADED_AT
    env_mtime: float | None = None
    try:
        from astra_backend.settings_store import ENV_FILE  # 惰性导入：避免与设置存储互相牵制

        if os.path.exists(ENV_FILE):
            env_mtime = os.path.getmtime(ENV_FILE)
    except Exception:
        env_mtime = None
    stale = bool(env_mtime is not None and env_mtime > loaded_at + 1.0)
    return {
        "loaded_at": loaded_at,
        "env_file_mtime": env_mtime,
        "stale": stale,
        # 陈旧的判定与解释都给出，前端不自行编造文案
        "note": ("本进程内的风控常量快照早于 .env 的最近一次修改——长驻进程（后台/worker）"
                 "需重启才同步；交易子进程每周期重启，下一周期即用新值。"
                 if stale else "本进程快照不早于 .env 最近修改。"),
    }


def file_vs_process_diff() -> dict[str, Any]:
    """`current_values()`（文件/环境） vs `process_values()`（进程内快照）的差异。"""
    file_values = current_values()
    proc_values = process_values()
    differing: dict[str, dict[str, float | int]] = {}
    for key in RISK_ENV_KEYS:
        want, have = file_values.get(key), proc_values.get(key)
        if isinstance(want, (int, float)) and isinstance(have, (int, float)) and float(want) != float(have):
            differing[key] = {"file": want, "process": have}
    return {"differing": differing, "count": len(differing)}


def effective_engine_values(usdt_available: float | None = None,
                            pool_size: int | None = None) -> dict[str, Any]:
    """引擎此刻「真正会用」的派生口径（与提示词同源的 min()/目标值）。

    权益缺失（None）时只给绝对封顶与不依赖权益的量，并把 `usdt_available_used` 显式标为
    None——绝不用 0 代填（缺失≠0）。池容量缺失时同样如实标注，不臆造持仓上限。
    """
    if pool_size is None:
        try:
            from scripts.instrument_pool import load_instruments

            pool_size = len(load_instruments())
        except Exception:
            pool_size = None
    total: int | None = None
    same: int | None = None
    if isinstance(pool_size, int) and pool_size > 0:
        total, same = effective_max_positions(pool_size)
    return {
        "daily_loss_limit_usdt": effective_daily_loss_limit(usdt_available),
        "single_asset_margin_usdt": effective_single_asset_margin(usdt_available),
        "risk_per_trade_usdt": effective_risk_per_trade(0.0, usdt_available),
        "max_positions": total,
        "max_same_direction": same,
        "pool_size_used": pool_size,
        # 2026-10：目标 R:R 的下限由硬编码 2.2 改为跟随可配的硬底线 ——
        # 与下方「目标盈亏比 R:R」文案同源，避免"页面显示 1.6、提示词仍说 ≥2.2"。
        "target_rr": round(max(1.4, float(MIN_RISK_REWARD_RATIO or 0.0)), 2),
        "max_risk_reward": float(MAX_RISK_REWARD_RATIO),
        "max_take_profit_atr": float(MAX_TAKE_PROFIT_ATR),
        "stop_loss_atr_mult": float(STOP_LOSS_ATR_MULT),
        # 2026-10：标定带下沿 = **实际新开仓门禁**本身。原实现留了 78 硬地板，
        # 于是门禁配 68 时预算文本出现自相矛盾的「标定带 78%~86%（下沿=门禁 68%）」——
        # 模型会以为 68~77 的信号"必被物理拦截"而主动放弃（实测模型置信度带 75~82）。
        "confidence_band": [float(MIN_ENTRY_CONFIDENCE or 0.0),
                            float(MIN_ENTRY_CONFIDENCE or 0.0) + 8.0],
        "scale_out_enabled": bool(SCALE_OUT_ENABLED),
        "scale_out_ratio": float(SCALE_OUT_RATIO),
        "scale_out_trigger_atr": float(SCALE_OUT_TRIGGER_ATR),
        "usdt_available_used": usdt_available,
    }


def _coerce(param: dict[str, Any], value: Any) -> float | int:
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{param['label']}: 必须是数字，收到 {value!r}")
    if param["type"] == "int":
        num = int(round(num))
    else:
        num = round(num, 6)
    if num < param["min"] or num > param["max"]:
        disp_min, disp_max = param["min"] * param["display_scale"], param["max"] * param["display_scale"]
        raise ValueError(f"{param['label']}: 须在 {disp_min:g}~{disp_max:g} {param['unit']} 之间（收到 {num * param['display_scale']:g}）")
    return num


def normalize(values: Mapping[str, Any]) -> dict[str, str]:
    """校验前端提交的 {env_key: native_value}，返回可直接 update_env 的字符串映射。"""
    unknown = [k for k in values if k not in _INDEX]
    if unknown:
        raise ValueError(f"未知风控参数: {', '.join(sorted(unknown))}")
    parsed: dict[str, float | int] = {}
    errors: list[str] = []
    for key, value in values.items():
        param = _INDEX[key]
        try:
            parsed[key] = _coerce(param, value)
        except ValueError as exc:
            errors.append(str(exc))
    # 跨字段一致性：同向上限不应超过显式配置的总仓上限（0=自动 时由执行层按池容量钳制）
    total = parsed.get("ASTRA_MAX_CONCURRENT_POSITIONS", current_values().get("ASTRA_MAX_CONCURRENT_POSITIONS", 0))
    same = parsed.get("ASTRA_MAX_SAME_DIRECTION_POSITIONS", current_values().get("ASTRA_MAX_SAME_DIRECTION_POSITIONS", 3))
    if isinstance(total, (int, float)) and total > 0 and isinstance(same, (int, float)) and same > total:
        errors.append(f"同向持仓上限 ({same:g}) 不能高于最高持仓数 ({total:g})")
    # 杠杆区间一致性：下限不得越过上限（执行层虽有读时兜底钳制，配置面必须显式拒绝）
    lev_min = parsed.get("ASTRA_MIN_LEVERAGE", current_values().get("ASTRA_MIN_LEVERAGE", DEFAULTS["ASTRA_MIN_LEVERAGE"]))
    lev_max = parsed.get("ASTRA_MAX_LEVERAGE", current_values().get("ASTRA_MAX_LEVERAGE", DEFAULTS["ASTRA_MAX_LEVERAGE"]))
    if isinstance(lev_min, (int, float)) and isinstance(lev_max, (int, float)) and lev_min > lev_max:
        errors.append(f"杠杆下限 ({lev_min:g}x) 不能高于杠杆上限 ({lev_max:g}x)")
    # 盈亏比区间一致性：底线不得高于上限
    rr_min = parsed.get("ASTRA_MIN_RISK_REWARD", current_values().get("ASTRA_MIN_RISK_REWARD", DEFAULTS["ASTRA_MIN_RISK_REWARD"]))
    rr_max = parsed.get("ASTRA_MAX_RISK_REWARD", current_values().get("ASTRA_MAX_RISK_REWARD", DEFAULTS["ASTRA_MAX_RISK_REWARD"]))
    if isinstance(rr_min, (int, float)) and isinstance(rr_max, (int, float)) and rr_min > rr_max:
        errors.append(f"最小盈亏比底线 ({rr_min:g}) 不能高于最大盈亏比上限 ({rr_max:g})")
    # 分批止盈触发门槛护栏：不得低于 1.8x ATR，防止首批止盈先于止损被击穿（倒置为赢小输大结构）
    scale_out_atr = parsed.get("ASTRA_SCALE_OUT_TRIGGER_ATR", current_values().get("ASTRA_SCALE_OUT_TRIGGER_ATR", DEFAULTS["ASTRA_SCALE_OUT_TRIGGER_ATR"]))
    if isinstance(scale_out_atr, (int, float)) and scale_out_atr < 1.8:
        errors.append(f"分批止盈触发门槛 ({scale_out_atr:g}x ATR) 不得低于 1.8x ATR，否则首批止盈在止损之前被击穿，导致盈亏比倒置（赢小输大）")
    if errors:
        raise ValueError("；".join(errors))
    return {k: str(v) for k, v in parsed.items()}


def reset_keys() -> list[str]:
    return list(RISK_ENV_KEYS)


def audit_risk_consistency(values: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Check mathematical consistency and execution viability across risk parameters."""
    vals = dict(values) if values is not None else current_values()

    def _f(key: str, default: float) -> float:
        try:
            return float(vals.get(key, default))
        except (TypeError, ValueError):
            return float(default)

    def _i(key: str, default: int) -> int:
        try:
            return int(round(float(vals.get(key, default))))
        except (TypeError, ValueError):
            return int(default)

    sl_atr = _f("ASTRA_STOP_LOSS_ATR_MULT", DEFAULTS["ASTRA_STOP_LOSS_ATR_MULT"])
    tp_cap_atr = _f("ASTRA_MAX_TAKE_PROFIT_ATR", DEFAULTS["ASTRA_MAX_TAKE_PROFIT_ATR"])
    min_rr = _f("ASTRA_MIN_RISK_REWARD", DEFAULTS["ASTRA_MIN_RISK_REWARD"])
    max_rr = _f("ASTRA_MAX_RISK_REWARD", DEFAULTS["ASTRA_MAX_RISK_REWARD"])
    min_conf = _f("ASTRA_MIN_ENTRY_CONFIDENCE", DEFAULTS["ASTRA_MIN_ENTRY_CONFIDENCE"])
    counter_conf = _f("ASTRA_COUNTER_4H_MIN_CONFIDENCE", DEFAULTS["ASTRA_COUNTER_4H_MIN_CONFIDENCE"])
    scale_out_enabled = _i("ASTRA_SCALE_OUT_ENABLED", int(DEFAULTS["ASTRA_SCALE_OUT_ENABLED"]))
    scale_out_trig = _f("ASTRA_SCALE_OUT_TRIGGER_ATR", DEFAULTS["ASTRA_SCALE_OUT_TRIGGER_ATR"])
    ttl_minutes = _i("ASTRA_LIMIT_ORDER_TTL_MINUTES", int(DEFAULTS["ASTRA_LIMIT_ORDER_TTL_MINUTES"]))
    drift_atr = _f("ASTRA_LIMIT_ORDER_DRIFT_ATR", DEFAULTS["ASTRA_LIMIT_ORDER_DRIFT_ATR"])

    theoretical_max_rr = round(tp_cap_atr / sl_atr, 4) if sl_atr > 0 else 0.0
    issues: list[dict[str, Any]] = []

    if sl_atr > 0 and theoretical_max_rr + 1e-4 < min_rr:
        issues.append({
            "code": "SL_TP_RR_DEADLOCK",
            "severity": "critical",
            "title": "止盈 ATR 上限与最低盈亏比构成数学死锁",
            "detail": (
                f"当前止盈宽度上限 ({tp_cap_atr:g}x ATR) ÷ 止损距离 ({sl_atr:g}x ATR) = "
                f"理论最大盈亏比 {theoretical_max_rr:.2f}:1，低于最低盈亏比底线 {min_rr:g}:1，导致所有新单在风控门禁被物理拦截。"
            ),
            "recommendation": f"将 ASTRA_MAX_TAKE_PROFIT_ATR 提高至 ≥ {round(sl_atr * max(min_rr + 0.3, min_rr), 2):g} 或下调 ASTRA_MIN_RISK_REWARD / ASTRA_STOP_LOSS_ATR_MULT。",
        })
    elif sl_atr > 0 and theoretical_max_rr < min_rr + 0.15:
        issues.append({
            "code": "SL_TP_RR_TIGHT_MARGIN",
            "severity": "warning",
            "title": "理论最大盈亏比余量偏窄",
            "detail": (
                f"理论最大盈亏比 {theoretical_max_rr:.2f}:1 仅比最低底线 {min_rr:g}:1 高 "
                f"{round(theoretical_max_rr - min_rr, 2):.2f}，宽止损结构单极易触顶裁减后被拒绝。"
            ),
            "recommendation": "建议适度放宽 ASTRA_MAX_TAKE_PROFIT_ATR 至 ≥ 4.2x ATR。",
        })

    if min_rr > max_rr:
        issues.append({
            "code": "RR_RANGE_INVERTED",
            "severity": "critical",
            "title": "盈亏比上下限倒置",
            "detail": f"最小盈亏比 {min_rr:g} 高于最大盈亏比 {max_rr:g}。",
            "recommendation": "保持 ASTRA_MIN_RISK_REWARD ≤ ASTRA_MAX_RISK_REWARD。",
        })

    if scale_out_enabled:
        if scale_out_trig < sl_atr:
            issues.append({
                "code": "SCALE_OUT_BEFORE_SL",
                "severity": "warning",
                "title": "分批止盈触发门槛低于止损宽度",
                "detail": f"分批止盈触发 {scale_out_trig:g}x ATR 小于止损 {sl_atr:g}x ATR，可能形成赢小输大结构。",
                "recommendation": f"保持 ASTRA_SCALE_OUT_TRIGGER_ATR ≥ {max(1.8, sl_atr):g}。",
            })
        if scale_out_trig > tp_cap_atr:
            issues.append({
                "code": "SCALE_OUT_ABOVE_TP_CAP",
                "severity": "warning",
                "title": "分批止盈门槛高于总止盈宽度上限",
                "detail": f"分批门槛 {scale_out_trig:g}x ATR 超过最大止盈 {tp_cap_atr:g}x ATR，可能导致分批止盈无法提前触发。",
                "recommendation": "提高 ASTRA_MAX_TAKE_PROFIT_ATR 或下调分批门槛。",
            })

    if ttl_minutes < 60 or drift_atr < 0.8:
        issues.append({
            "code": "LIMIT_ORDER_STRICT_EXPIRY",
            "severity": "warning",
            "title": "限价单过期/漂移撤单偏紧",
            "detail": f"当前挂单 TTL={ttl_minutes}m、漂移撤单阈值={drift_atr:g}x ATR，趋势微幅拉扯易反复撤单空转。",
            "recommendation": "建议搭配智能订单模式 (smart)，并将 TTL ≥ 60~90m、漂移阈值 ≥ 1.0~1.2x ATR。",
        })

    if counter_conf < min_conf:
        issues.append({
            "code": "COUNTER_CONF_LOWER_THAN_ENTRY",
            "severity": "warning",
            "title": "逆 4H 置信度门槛低于顺势开仓门槛",
            "detail": f"逆势门槛 {counter_conf:g}% < 常规开仓门槛 {min_conf:g}%。",
            "recommendation": "确保 ASTRA_COUNTER_4H_MIN_CONFIDENCE ≥ ASTRA_MIN_ENTRY_CONFIDENCE。",
        })

    critical_count = sum(1 for item in issues if item["severity"] == "critical")
    warning_count = sum(1 for item in issues if item["severity"] == "warning")
    status = "critical" if critical_count else ("warning" if warning_count else "healthy")
    return {
        "ok": critical_count == 0,
        "status": status,
        "critical_count": critical_count,
        "warning_count": warning_count,
        "theoretical_max_rr": theoretical_max_rr,
        "sl_atr_mult": sl_atr,
        "max_take_profit_atr": tp_cap_atr,
        "min_risk_reward": min_rr,
        "issues": issues,
    }
