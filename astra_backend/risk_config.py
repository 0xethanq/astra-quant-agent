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
    {"key": "ASTRA_PORTFOLIO_RISK_BUDGET_USDT", "group": "exposure",
     "label": "组合风险总预算（全所资金池）", "label_en": "Portfolio Risk Budget",
     "desc": "全系统三所合计可支配的风险预算总上限（USDT）。0 = 自动按持仓上限×单标的保证金绝对封顶派生。",
     "type": "float", "min": 0.0, "max": 1000000.0, "step": 100.0, "unit": "USDT", "display_scale": 1},
    {"key": "ASTRA_MAX_CONCURRENT_POSITIONS", "group": "exposure",
     "label": "最高持仓数（总仓位上限）", "label_en": "Max Concurrent Positions",
     "desc": "全系统同时持有的仓位总数上限。0 = 自动跟随标的池容量；超过池容量的配置会被钳制到池容量。",
     "type": "int", "min": 0, "max": 50, "step": 1, "unit": "仓", "display_scale": 1},
    {"key": "ASTRA_MAX_SAME_DIRECTION_POSITIONS", "group": "exposure",
     "label": "同向持仓上限（单边敞口）", "label_en": "Max Same-Direction Positions",
     "desc": "纯多单或纯空单各自的笔数上限，防高相关标的同向堆叠踩踏。不会超过总仓位上限。",
     "type": "int", "min": 1, "max": 50, "step": 1, "unit": "仓", "display_scale": 1},
    {"key": "ASTRA_MAX_MARGIN_EQUITY_RATIO", "group": "exposure",
     "label": "单笔保证金占比（硬顶）", "label_en": "Max Margin per Order (% of equity)",
     "desc": "单笔下单占用保证金不得超过可用余额的这个比例，超出部分执行层直接砍掉。也是提示词中「强信号单笔保证金上限」的同口径值。",
     "type": "float", "min": 0.01, "max": 1.0, "step": 0.01, "unit": "%", "display_scale": 100},
    {"key": "ASTRA_SINGLE_ASSET_EQUITY_RATIO", "group": "exposure",
     "label": "单标的累计保证金占比", "label_en": "Single-Asset Margin Cap (% of equity)",
     "desc": "同一标的（含金字塔加仓后）累计占用保证金占可用余额的上限。",
     "type": "float", "min": 0.01, "max": 1.0, "step": 0.01, "unit": "%", "display_scale": 100},
    {"key": "ASTRA_MAX_SINGLE_ASSET_MARGIN_USDT", "group": "exposure",
     "label": "单标的保证金绝对封顶", "label_en": "Single-Asset Margin Hard Cap",
     "desc": "单标的累计保证金的绝对金额封顶（USDT）。实际生效取 min(本值, 余额×占比上限)，小资金账户自动收紧。",
     "type": "float", "min": 1.0, "max": 100000.0, "step": 10.0, "unit": "USDT", "display_scale": 1},
    {"key": "ASTRA_MAX_TOTAL_EXPOSURE_USDT", "group": "exposure",
     "label": "跨所同向敞口上限", "label_en": "Cross-Venue Same-Side Exposure Cap",
     "desc": "同一标同方向的跨所合计名义敞口上限（USDT，0 = 不限制）。发送前核算：已开同向名义额 + 本单名义额超过即拒开（不夹取）。",
     "type": "float", "min": 0.0, "max": 1000000.0, "step": 50.0, "unit": "USDT", "display_scale": 1},
    {"key": "ASTRA_MIN_LEVERAGE", "group": "exposure",
     "label": "单笔杠杆下限", "label_en": "Min Leverage",
     "desc": "AI 自主裁决杠杆的区间下限：模型须在 [下限, 上限] 内按信号强度取值，低于下限会被执行层抬升钳制。调高下限 = 强制放大名义敞口，请配合日亏熔断使用。",
     "type": "float", "min": 1.0, "max": 20.0, "step": 1.0, "unit": "x", "display_scale": 1},
    {"key": "ASTRA_MAX_LEVERAGE", "group": "exposure",
     "label": "单笔杠杆上限", "label_en": "Max Leverage",
     "desc": "AI 自主裁决杠杆的区间上限：执行层强制钳制不超过此倍数。与「单笔杠杆下限」共同构成模型的自主取值区间。",
     "type": "float", "min": 1.0, "max": 20.0, "step": 1.0, "unit": "x", "display_scale": 1},
    # ── 组2 单笔风险门禁 ──
    {"key": "ASTRA_RISK_PER_TRADE_RATIO", "group": "per_trade",
     "label": "单笔风险额占比（1R）", "label_en": "Risk per Trade (% of equity)",
     "desc": "单笔最大可承受亏损（1R）占可用余额的比例，与标的池内绝对风险额取小。",
     "type": "float", "min": 0.001, "max": 0.2, "step": 0.001, "unit": "%", "display_scale": 100},
    {"key": "ASTRA_MIN_RISK_REWARD", "group": "per_trade",
     "label": "最小盈亏比 R:R 硬底线", "label_en": "Minimum R:R Ratio",
     "desc": "盈亏比低于该值的开仓报价会被核心风控物理拦截（Fail-Closed），无论来自 AI 还是人工。",
     "type": "float", "min": 1.0, "max": 10.0, "step": 0.1, "unit": ": 1", "display_scale": 1},
    {"key": "ASTRA_MAX_RISK_REWARD", "group": "per_trade",
     "label": "最大盈亏比 R:R 上限", "label_en": "Max Risk-Reward Ratio Cap",
     "desc": "单笔开仓允许的最大盈亏比上限。超出此上限的止盈报价会被执行层平滑收窄钳制，防止规划无法触及的虚高止盈。须 ≥ 最小盈亏比底线。",
     "type": "float", "min": 2.0, "max": 10.0, "step": 0.1, "unit": ": 1", "display_scale": 1},
    {"key": "ASTRA_MIN_ENTRY_CONFIDENCE", "group": "per_trade",
     "label": "新开仓最低 AI 置信度", "label_en": "Min Entry Confidence",
     "desc": "AI 裁决置信度低于该百分比时禁止新开仓（金字塔加仓另有独立门禁）。",
     "type": "float", "min": 0.0, "max": 100.0, "step": 1.0, "unit": "%", "display_scale": 1},
    # ── 组3 止损与熔断 ──
    {"key": "ASTRA_DAILY_LOSS_EQUITY_RATIO", "group": "stop_loss",
     "label": "日亏熔断比例（按余额）", "label_en": "Daily Loss Circuit Breaker (% of equity)",
     "desc": "当日累计已实现亏损达到可用余额的这个比例时，本周期停止新开仓。",
     "type": "float", "min": 0.005, "max": 0.5, "step": 0.005, "unit": "%", "display_scale": 100},
    {"key": "ASTRA_MAX_DAILY_LOSS_USDT", "group": "stop_loss",
     "label": "日亏熔断绝对封顶", "label_en": "Daily Loss Hard Cap",
     "desc": "熔断线的绝对金额封顶（USDT）。实际生效取 min(本值, 余额×比例)，小资金账户自动收紧。",
     "type": "float", "min": 1.0, "max": 1000000.0, "step": 10.0, "unit": "USDT", "display_scale": 1},
    {"key": "ASTRA_TIME_STOP_HOURS", "group": "stop_loss",
     "label": "最长持仓时间（时间止损）", "label_en": "Max Hold Time (Time Stop)",
     "desc": "持仓超过该时长且波幅仍不足横盘带宽时，主动平仓释放保证金与仓位配比。",
     "type": "float", "min": 0.5, "max": 168.0, "step": 0.5, "unit": "小时", "display_scale": 1},
    {"key": "ASTRA_TIME_STOP_ATR_BAND", "group": "stop_loss",
     "label": "时间止损横盘带宽", "label_en": "Time-Stop ATR Band",
     "desc": "浮盈绝对值小于「该系数 × 1H ATR」才判定为无突破横盘；调大更易触发时间止损。",
     "type": "float", "min": 0.0, "max": 2.0, "step": 0.05, "unit": "× ATR", "display_scale": 1},
    {"key": "ASTRA_STOP_COOLDOWN_MINUTES", "group": "stop_loss",
     "label": "止损后冷静期", "label_en": "Post-Stop Cooldown",
     "desc": "某标的止损出局后，同标的同方向在该分钟内禁止再次开仓，防情绪化反手与连续磨损。",
     "type": "int", "min": 0, "max": 1440, "step": 5, "unit": "分钟", "display_scale": 1},
    {"key": "ASTRA_STOP_LOSS_ATR_MULT", "group": "stop_loss",
     "label": "单笔基准止损宽度 (×ATR)", "label_en": "Base Stop-Loss ATR Band",
     "desc": "单笔止损距离入场价的基准 ATR 倍数（通常为 1.8~2.2x ATR），与标的池档位结合确定防插针安全呼吸空间。",
     "type": "float", "min": 1.0, "max": 4.0, "step": 0.1, "unit": "× ATR", "display_scale": 1},
    # ── 组4 顺势金字塔加仓 ──
    {"key": "ASTRA_MAX_SCALE_IN_COUNT", "group": "pyramiding",
     "label": "单标的最大加仓次数", "label_en": "Max Scale-In Count",
     "desc": "每个标的允许的顺势浮盈加仓次数；0 = 彻底禁止加仓（只允许底仓）。",
     "type": "int", "min": 0, "max": 10, "step": 1, "unit": "次", "display_scale": 1},
    {"key": "ASTRA_MIN_SCALE_IN_PROFIT_RATIO", "group": "pyramiding",
     "label": "加仓最小底仓浮盈率", "label_en": "Min Base-Position Unrealized ROI",
     "desc": "底仓浮盈达到该比例（保本之上）才允许顺势追加，绝不浮盈外加仓。",
     "type": "float", "min": 0.0, "max": 0.2, "step": 0.001, "unit": "%", "display_scale": 100},
    {"key": "ASTRA_MIN_SCALE_IN_CONFIDENCE", "group": "pyramiding",
     "label": "加仓最低 AI 置信度", "label_en": "Min Scale-In Confidence",
     "desc": "金字塔加仓需要达到的 AI 置信度门槛，通常应高于新开仓门禁。",
     "type": "float", "min": 0.0, "max": 100.0, "step": 1.0, "unit": "%", "display_scale": 1},
    # ── 组5 出场与分批止盈 ──
    {"key": "ASTRA_SCALE_OUT_ENABLED", "group": "exit_strategy",
     "label": "启用分批止盈 (Scale-Out)", "label_en": "Enable Scale-Out",
     "desc": "开启后，当浮盈达到触发门槛时，执行层自动市价平仓指定比例锁定现金利润，并同步将剩余仓位推进至成本保本位（1=开启，0=关闭）。",
     "type": "int", "min": 0, "max": 1, "step": 1, "unit": "", "display_scale": 1},
    {"key": "ASTRA_SCALE_OUT_RATIO", "group": "exit_strategy",
     "label": "首批平仓止盈比例", "label_en": "Scale-Out Close Ratio",
     "desc": "第一目标达成时市价落袋的仓位百分比，默认 50%（平一半、留一半博大单边）。",
     "type": "float", "min": 0.1, "max": 0.9, "step": 0.05, "unit": "%", "display_scale": 100},
    {"key": "ASTRA_SCALE_OUT_TRIGGER_ATR", "group": "exit_strategy",
     "label": "分批止盈触发门槛", "label_en": "Scale-Out Trigger Threshold",
     "desc": "持仓浮盈达到该倍数 × 1H ATR 时启动分批平仓（通常为 1.0~1.5x ATR）。",
     "type": "float", "min": 0.5, "max": 5.0, "step": 0.1, "unit": "× ATR", "display_scale": 1},
    {"key": "ASTRA_MAX_TAKE_PROFIT_ATR", "group": "exit_strategy",
     "label": "单笔最大止盈宽度 (×ATR)", "label_en": "Max Take-Profit ATR Band",
     "desc": "单笔止盈单距离入场价的最大 ATR 跨度。超出此倍数的止盈单会被执行层平滑收窄钳制，防止止盈目标过远导致行情反转无法落袋。",
     "type": "float", "min": 1.5, "max": 8.0, "step": 0.1, "unit": "× ATR", "display_scale": 1},
]

_INDEX = {p["key"]: p for p in _PARAMS}

# ── 优质预设套件（一键应用；values 为原生单位，必须通过本 schema 校验） ──
SUITES: list[dict[str, Any]] = [
    {"id": "conservative", "name": "🛡️ 稳健防守", "tagline": "本金安全绝对优先",
     "desc": "适合新账户、小资金或高波动恶劣行情：仓位少而精、置信度与盈亏比门槛拉高(2.5:1)、杠杆压至 3x、"
             "90分钟止损冷静期彻底隔绝震荡反复磨损、彻底禁止金字塔加仓、日亏 3% 即熔断。牺牲部分机会换极低回撤。",
     "values": {
         "ASTRA_PORTFOLIO_RISK_BUDGET_USDT": 0.0,
         "ASTRA_MAX_CONCURRENT_POSITIONS": 4, "ASTRA_MAX_SAME_DIRECTION_POSITIONS": 2,
         "ASTRA_MAX_MARGIN_EQUITY_RATIO": 0.10, "ASTRA_SINGLE_ASSET_EQUITY_RATIO": 0.20,
         "ASTRA_MAX_SINGLE_ASSET_MARGIN_USDT": 300.0, "ASTRA_MIN_LEVERAGE": 2.0, "ASTRA_MAX_LEVERAGE": 3.0,
         "ASTRA_RISK_PER_TRADE_RATIO": 0.01, "ASTRA_MIN_RISK_REWARD": 2.5, "ASTRA_MAX_RISK_REWARD": 3.0,
         "ASTRA_MIN_ENTRY_CONFIDENCE": 85.0,
         "ASTRA_STOP_LOSS_ATR_MULT": 1.8,
         "ASTRA_DAILY_LOSS_EQUITY_RATIO": 0.03, "ASTRA_MAX_DAILY_LOSS_USDT": 100.0,
         "ASTRA_TIME_STOP_HOURS": 12.0, "ASTRA_TIME_STOP_ATR_BAND": 0.10, "ASTRA_STOP_COOLDOWN_MINUTES": 90,
         "ASTRA_MAX_SCALE_IN_COUNT": 0, "ASTRA_MIN_SCALE_IN_PROFIT_RATIO": 0.012, "ASTRA_MIN_SCALE_IN_CONFIDENCE": 85.0,
         "ASTRA_MAX_TOTAL_EXPOSURE_USDT": 600.0,
         "ASTRA_SCALE_OUT_ENABLED": 1, "ASTRA_SCALE_OUT_RATIO": 0.50, "ASTRA_SCALE_OUT_TRIGGER_ATR": 1.00,
         "ASTRA_MAX_TAKE_PROFIT_ATR": 2.80,
     }},
    {"id": "balanced", "name": "⚖️ 均衡波段", "tagline": "推荐默认 · 攻守兼备",
     "desc": "系统出厂基线：同向 3 仓防共振踩踏、单笔保证金 20% 硬顶、2% 单笔风险、R:R 底线 2.0、"
             "60分钟止损冷静期防连续磨损、8 小时时间止损释放配比、允许 1 次严格浮盈加仓。兼顾让利润奔跑与风险下限。",
     "values": {key: DEFAULTS[key] for key in DEFAULTS}},
    {"id": "aggressive", "name": "🚀 进取猎手", "tagline": "单边趋势市 · 经验账户专用",
     "desc": "适合明确单边主升/主跌浪与老手账户：同向放宽至 4 仓吃足趋势、置信度门禁降至 72% 抢先上车、"
             "允许 2 次金字塔加仓放大盈利单、30分钟止损冷静期防极速反噬、持仓时间放宽至 16 小时。回撤与熔断线同步放大，风险自负。",
     "values": {
         "ASTRA_PORTFOLIO_RISK_BUDGET_USDT": 0.0,
         "ASTRA_MAX_CONCURRENT_POSITIONS": 0, "ASTRA_MAX_SAME_DIRECTION_POSITIONS": 4,
         "ASTRA_MAX_MARGIN_EQUITY_RATIO": 0.25, "ASTRA_SINGLE_ASSET_EQUITY_RATIO": 0.40,
         "ASTRA_MAX_SINGLE_ASSET_MARGIN_USDT": 800.0, "ASTRA_MIN_LEVERAGE": 5.0, "ASTRA_MAX_LEVERAGE": 7.0,
         "ASTRA_RISK_PER_TRADE_RATIO": 0.03, "ASTRA_MIN_RISK_REWARD": 2.0, "ASTRA_MAX_RISK_REWARD": 5.0,
         "ASTRA_MIN_ENTRY_CONFIDENCE": 72.0,
         "ASTRA_STOP_LOSS_ATR_MULT": 2.2,
         "ASTRA_DAILY_LOSS_EQUITY_RATIO": 0.08, "ASTRA_MAX_DAILY_LOSS_USDT": 300.0,
         "ASTRA_TIME_STOP_HOURS": 16.0, "ASTRA_TIME_STOP_ATR_BAND": 0.20, "ASTRA_STOP_COOLDOWN_MINUTES": 30,
         "ASTRA_MAX_SCALE_IN_COUNT": 2, "ASTRA_MIN_SCALE_IN_PROFIT_RATIO": 0.006, "ASTRA_MIN_SCALE_IN_CONFIDENCE": 70.0,
         "ASTRA_MAX_TOTAL_EXPOSURE_USDT": 3000.0,
         "ASTRA_SCALE_OUT_ENABLED": 1, "ASTRA_SCALE_OUT_RATIO": 0.40, "ASTRA_SCALE_OUT_TRIGGER_ATR": 1.50,
         "ASTRA_MAX_TAKE_PROFIT_ATR": 5.00,
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
        "max_positions": total,
        "max_same_direction": same,
        "pool_size_used": pool_size,
        "target_rr": round(max(2.2, float(MIN_RISK_REWARD_RATIO or 0.0)), 2),
        "max_risk_reward": float(MAX_RISK_REWARD_RATIO),
        "max_take_profit_atr": float(MAX_TAKE_PROFIT_ATR),
        "stop_loss_atr_mult": float(STOP_LOSS_ATR_MULT),
        "confidence_band": [max(float(MIN_ENTRY_CONFIDENCE or 0.0), 78.0),
                            max(float(MIN_ENTRY_CONFIDENCE or 0.0), 78.0) + 8.0],
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
    if errors:
        raise ValueError("；".join(errors))
    return {k: str(v) for k, v in parsed.items()}


def reset_keys() -> list[str]:
    return list(RISK_ENV_KEYS)
