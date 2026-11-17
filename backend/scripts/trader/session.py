"""交易时段闸门 —— 用户自定义「系统允许运行」的时间窗口（2026-09-30）。

## 为什么需要它

实测（`data/astra_gateway.db::model_calls`，最近三天）：交易主脑每 15 分钟一次大模型调用，
均值 31,033 输入 + 12,761 输出 = 43,793 token/次 ⇒ **≈4.2M token/天，占全系统模型消耗的 94%**
（`self_improvement` 仅 0.25M/天）。而行情有相当一部分时段并不值得做决策 ——
用户要的是「只在自定义的时段里跑」。

## 三种模式

| 模式 | 含义 |
|---|---|
| `full` | 窗口内 / 未启用 / 强制运行：一切照旧 |
| `manage_only` | 窗口外（默认）：**跳过 AI 大模型决策与新开仓**，机械风控照常（追踪止损、分批止盈、交易所保护腿） |
| `off` | 窗口外（可选）：相位 0/0a 的挂单核验/回收之后即退出，不做持仓管理 |

`manage_only` 之所以是默认：它砍掉的正是唯一的 token 大头（相位 4 的批量主脑调用，
`scripts/trader/cycle_stages.py::scan_risk_gates_and_ai_brain`），
而机械退出链路（相位 2–3）**本来就不花 token**，没有理由一起停。

## 失败方向（写死在这里，不要"顺手改成默认安全值"）

| 情形 | 行为 |
|---|---|
| 配置文件缺失 / 损坏 / 非 dict | **按 `full` 运行** + 告警 |
| 已启用但没有任何有效时段 | **按 `full` 运行** + 告警 |
| 某段 HH:MM 非法 / 起止相同 | 跳过该段 + 告警 |
| `mode_outside` 未知取值 | 回落 `manage_only`（收不到明确指令时选保留机械风控的那侧） |

前三条与 `scripts/ai_factor_trader.py::_slot_guard_should_skip` 的既有先例同向：
**读不到/配不全 ≠ 停掉实盘**（"不因一个状态文件把实盘交易停掉"），但必须**吼出来**。
代价对比很清楚：多花 token 远轻于"该管的仓没人管"。
唯一例外是 `mode_outside` 取值本身 —— 那是**明确指令**，只是拼错了，故回落到更安全的一侧。

## 纯函数纪律

本模块**零 IO、零模块状态、零 import 期绑定**（与 `tp1.py` / `data_shape.py` 同族）：
配置对象由调用方在调用期传入，这样门面侧的 `patch.object` 测试缝与 `risk_constants`
的 .env 重载语义都不受影响（见 `scripts/trader/__init__.py` 的两条铁律）。
**绝不抛异常**：闸门本身不得成为新的单点故障（对齐 `cycle_disclosure_payload` 的"绝不抛"）。
"""
from __future__ import annotations

import datetime
from typing import Any

#: 唯一支持的时区（与 `astra_backend/schedule_store.py` 的 `timezone`、提示词时间戳同源）。
BJ_TZ = datetime.timezone(datetime.timedelta(hours=8))

MODE_FULL = "full"
MODE_MANAGE_ONLY = "manage_only"
MODE_OFF = "off"

#: 窗口外允许的模式（未知取值一律回落 MODE_MANAGE_ONLY）。
VALID_MODES_OUTSIDE = (MODE_MANAGE_ONLY, MODE_OFF)

#: 星期标签（0=周一 … 6=周日，与 `datetime.weekday()` 同序）。
WEEKDAY_LABELS = ("周一", "周二", "周三", "周四", "周五", "周六", "周日")

#: trader 周期槽位数（每 15 分钟一槽，与 `astra_gateway/scheduler.py::JOBS` 同源）。
SLOTS_PER_DAY = 96

#: 出厂默认：**未启用** ⇒ 全天候运行 ⇒ 部署后行为逐位不变。
DEFAULT_SESSION: dict[str, Any] = {
    "enabled": False,
    "mode_outside": MODE_MANAGE_ONLY,
    "timezone": "Asia/Shanghai",
    "windows": [],
}


def _fmt_hhmm(minutes: int) -> str:
    minutes = int(minutes) % (24 * 60)
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _parse_hhmm(value: Any) -> int | None:
    """`"9:5"` / `"09:05"` / `9*60+5` 一律解析成当日分钟数；不可解析返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        total = int(value)
        return total if 0 <= total < 24 * 60 else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if ":" not in text:
        return None
    head, _, tail = text.partition(":")
    try:
        hour = int(head.strip() or -1)
        minute = int(tail.strip() or -1)
    except (TypeError, ValueError):
        return None
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour * 60 + minute


def _normalize_days(raw: Any) -> tuple[list[int], list[str]]:
    errors: list[str] = []
    if raw is None or raw == "":
        return [], errors
    if not isinstance(raw, (list, tuple)):
        return [], [f"星期掩码形状非法（{type(raw).__name__}），按「每天」处理"]
    picked: set[int] = set()
    for value in raw:
        try:
            day = int(value)
        except (TypeError, ValueError):
            errors.append(f"星期取值非法（{value!r}），已忽略")
            continue
        if not 0 <= day <= 6:
            errors.append(f"星期取值越界（{value!r}，应为 0=周一…6=周日），已忽略")
            continue
        picked.add(day)
    return sorted(picked), errors


def normalize_windows(raw: Any) -> tuple[list[dict], list[str]]:
    """归一化时段列表：返回 (规范时段, 中文错误列表)。非法段**跳过**而不是整体拒绝。

    规范化内容：HH:MM 补零、`days` 去重升序（空 = 每天）、去重、按开始时间排序。
    """
    windows: list[dict] = []
    errors: list[str] = []
    if raw is None or raw == "":
        return windows, errors
    if not isinstance(raw, (list, tuple)):
        return windows, [f"时段列表形状非法（{type(raw).__name__}），已忽略"]
    seen: set[tuple] = set()
    for index, item in enumerate(raw):
        label = f"第{index + 1}段"
        if not isinstance(item, dict):
            errors.append(f"{label}不是对象（{type(item).__name__}），已忽略")
            continue
        start = _parse_hhmm(item.get("start"))
        end = _parse_hhmm(item.get("end"))
        if start is None:
            errors.append(f"{label}开始时间非法（{item.get('start')!r}），已忽略")
            continue
        if end is None:
            errors.append(f"{label}结束时间非法（{item.get('end')!r}），已忽略")
            continue
        if start == end:
            errors.append(f"{label}起止时间相同（{_fmt_hhmm(start)}），无法判定运行区间，已忽略")
            continue
        days, day_errors = _normalize_days(item.get("days"))
        errors.extend(f"{label}{msg}" for msg in day_errors)
        key = (tuple(days), start, end)
        if key in seen:
            continue
        seen.add(key)
        windows.append({"days": days, "start": _fmt_hhmm(start), "end": _fmt_hhmm(end)})
    windows.sort(key=lambda w: (w["start"], w["end"], w["days"]))
    return windows, errors


def normalize_session(raw: Any) -> tuple[dict, list[str]]:
    """归一化整份配置：返回 (规范配置, 中文错误列表)。形状非法一律按默认处理。"""
    errors: list[str] = []
    if raw is None or raw == "":
        raw = {}
    if not isinstance(raw, dict):
        errors.append(f"配置形状非法（{type(raw).__name__}），按默认（全天候运行）处理")
        raw = {}
    mode = str(raw.get("mode_outside") or "").strip().lower()
    if mode not in VALID_MODES_OUTSIDE:
        if mode:
            errors.append(f"窗口外模式未知（{mode!r}），已回落为 {MODE_MANAGE_ONLY}")
        mode = MODE_MANAGE_ONLY
    windows, window_errors = normalize_windows(raw.get("windows"))
    errors.extend(window_errors)
    return {
        "enabled": bool(raw.get("enabled")),
        "mode_outside": mode,
        "timezone": str(raw.get("timezone") or DEFAULT_SESSION["timezone"]),
        "windows": windows,
    }, errors


def matched_window_index(windows: list[dict], now: datetime.datetime) -> int | None:
    """当前时刻命中的时段下标（含跨午夜与星期掩码语义）；无命中返回 None。

    - `[start, end)`：左含右不含，避免相邻时段在边界重复命中；
    - `end <= start` = 跨午夜；此时 `days` 指的是**窗口开始那天**：
      `days=[0]` + `21:30–04:00` ⇒ 周一 21:30 ~ 周二 04:00（周二 03:00 **在内**）。
    """
    minutes = now.hour * 60 + now.minute
    weekday = now.weekday()
    for index, window in enumerate(windows):
        start = _parse_hhmm(window.get("start"))
        end = _parse_hhmm(window.get("end"))
        if start is None or end is None:
            continue
        days = list(window.get("days") or [])
        if start < end:
            if (not days or weekday in days) and start <= minutes < end:
                return index
            continue
        if start <= minutes and (not days or weekday in days):
            return index
        if minutes < end and (not days or (weekday - 1) % 7 in days):
            return index
    return None


def next_change_bj(windows: list[dict], now: datetime.datetime, lookahead_days: int = 8) -> str:
    """下一次时段边界（开始或结束）的北京时间 `YYYY-mm-dd HH:MM`；算不出返回空串。

    候选点 = 未来 `lookahead_days` 天 × 每段两端。`offset` 从 -1 起：
    跨午夜时"今天凌晨的结束点"属于昨天的时段，算进去才不会把当天的边界漏掉。
    """
    candidates: list[datetime.datetime] = []
    for window in windows:
        start = _parse_hhmm(window.get("start"))
        end = _parse_hhmm(window.get("end"))
        if start is None or end is None:
            continue
        days = list(window.get("days") or [0, 1, 2, 3, 4, 5, 6])
        for offset in range(-1, lookahead_days):
            day = (now + datetime.timedelta(days=offset)).date()
            if day.weekday() not in days:
                continue
            midnight = datetime.datetime.combine(day, datetime.time(0, 0), tzinfo=BJ_TZ)
            moments = [midnight + datetime.timedelta(minutes=start)]
            # ⚠️ 跨午夜时结束点落在**次日**（`days` 指的是开始那天）——
            # 若也按当天的星期过滤，`days=[0]` 的段会漏掉"周二 04:00 结束"这个边界。
            moments.append(midnight + (datetime.timedelta(minutes=end) if start < end
                                       else datetime.timedelta(days=1, minutes=end)))
            for moment in moments:
                if moment > now:
                    candidates.append(moment)
    return min(candidates).strftime("%Y-%m-%d %H:%M") if candidates else ""


def resolve_session(config: Any, now_bj: datetime.datetime | None = None,
                    force: bool = False) -> dict[str, Any]:
    """时段闸门判定（**绝不抛异常**）。返回可直接渲染进日志/披露/接口的状态字典。

    键：`enabled` / `restricted` / `mode` / `in_window` / `matched_index` / `reason` /
    `next_change_bj` / `window_count` / `errors`。
    """
    normalized, errors = normalize_session(config)
    now = now_bj or datetime.datetime.now(BJ_TZ)
    if now.tzinfo is None:
        now = now.replace(tzinfo=BJ_TZ)
    else:
        now = now.astimezone(BJ_TZ)

    enabled = bool(normalized["enabled"])
    mode_outside = str(normalized["mode_outside"])
    windows = list(normalized["windows"])
    matched = matched_window_index(windows, now) if windows else None
    in_window = matched is not None

    if force:
        mode, reason = MODE_FULL, "强制运行（ASTRA_SESSION_FORCE=1）"
    elif not enabled:
        mode, reason = MODE_FULL, "未启用交易时段（全天候运行）"
    elif not windows:
        mode = MODE_FULL
        reason = "已启用交易时段但没有任何有效时段（按全天候运行）"
        errors = [*errors, "没有任何有效时段 ⇒ 本轮按全天候运行，请检查时段配置"]
    elif in_window:
        mode, reason = MODE_FULL, f"运行中（命中时段 #{int(matched) + 1}）"
    elif mode_outside == MODE_OFF:
        mode, reason = MODE_OFF, "休市中（窗口外）：完全停跑巡检"
    else:
        mode, reason = MODE_MANAGE_ONLY, "休市中（窗口外）：只做机械风控"

    return {
        "enabled": enabled,
        "restricted": mode != MODE_FULL,
        "mode": mode,
        "in_window": in_window,
        "matched_index": matched,
        "reason": reason,
        "next_change_bj": next_change_bj(windows, now) if windows else "",
        "window_count": len(windows),
        "errors": errors,
    }


def session_state_summary(state: Any) -> str:
    """把状态渲染成**一条可检索**的日志行（渲染器；判定见 `resolve_session`）。"""
    state = state if isinstance(state, dict) else {}
    mode = str(state.get("mode") or MODE_FULL)
    reason = str(state.get("reason") or mode)
    line = f"[交易时段] {reason}"
    nxt = str(state.get("next_change_bj") or "")
    if nxt:
        line += f"（下次切换 {nxt}）"
    if mode == MODE_MANAGE_ONLY:
        line += "｜本周期跳过 AI 大模型决策与新开仓，机械风控照常"
    elif mode == MODE_OFF:
        line += "｜本周期仅做挂单核验/回收，随后退出"
    errors = [str(e) for e in (state.get("errors") or [])]
    if errors:
        line += f"｜配置告警 {len(errors)} 条: " + "; ".join(errors[:2])
    return line


def coverage_estimate(config: Any) -> dict[str, Any]:
    """时段覆盖的**估算**（供后台展示取舍参考，不是承诺值）。

    ⚠️ 重叠时段会被重复计入 —— 这是估算而非精确并集，接口字段名与 UI 文案都写明"估算"。
    未启用时段时按全天候计（覆盖 100%、节省 0）。
    """
    normalized, _ = normalize_session(config)
    windows = list(normalized["windows"])
    weekly_minutes = 0
    for window in windows:
        start = _parse_hhmm(window.get("start"))
        end = _parse_hhmm(window.get("end"))
        if start is None or end is None:
            continue
        duration = (end - start) % (24 * 60)
        days = list(window.get("days") or [0, 1, 2, 3, 4, 5, 6])
        weekly_minutes += duration * len(days)
    fraction = 1.0
    if normalized["enabled"] and windows:
        fraction = min(1.0, weekly_minutes / float(7 * 24 * 60))
    in_window_slots = int(round(SLOTS_PER_DAY * fraction))
    return {
        "hours_per_week": round(weekly_minutes / 60.0, 1),
        "estimated_brain_calls_per_day": in_window_slots,
        "saved_brain_calls_per_day": max(0, SLOTS_PER_DAY - in_window_slots),
    }
