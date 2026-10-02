"""**离场质量**分析（自进化方向 3，2026-10）。

## 为什么需要这个模块

台账能算出"这笔赚/亏多少"，但算不出**这笔本来能赚多少**。于是复盘永远只能得到
"止损太频繁"这类无法行动的结论 —— 真正的问题是"**让浮盈跑掉了多少**"。

本模块用平仓证据里的 **MFE / MAE**（最大有利/不利偏移）回答：

| 指标 | 问的问题 | 直接驱动的动作 |
|---|---|---|
| `give_back_r` | 到过 +2R，最后只拿到 +0.3R —— 吐回去多少？ | 棘轮档位/移动止盈回撤缓冲是不是太宽 |
| `exit_efficiency_pct` | 兑现比例（实收 ÷ 最好时浮盈） | 离场时机 vs 入场质量哪个才是瓶颈 |
| 机制化出场表 | 哪种**机制**（阶梯锁利/移动止盈/时间止损/硬止损）真实效果最好 | 三档棘轮阈值、时间止损小时数 |
| 时间止损有效性 | 时间止损的单子，继续持有是否本来会赢？ | `TIME_STOP_HOURS` 该不该调 |
| 逐标的离场矩阵 | 哪些标的"进场对、出场烂" | 自适应权重该按**归因**而不是总盈亏调 |

## 三个诚实纪律

1. **R 口径只用真证据**：`give_back_r` 需要 `mfe_r` 与 1R 距离；任缺其一 ⇒ `None`，
   **绝不**用"默认 1% 止损"之类凑一个 R（一个编造的 R 会污染整张表）。
   同步给出**百分比口径**（`give_back_pct` / `exit_efficiency_pct`），它不依赖止损。
2. **样本不足就说不足**：每张表都带 `sample`，低于 `MIN_SAMPLE` 的结论进
   `insufficient`，让模型知道"这条别当真"。
3. **不把推断当事实**：`exit_reason_source == "inferred"` 的行只进总表，
   机制化出场表**只统计机制确认的行**。
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional

#: 单条结论的最低样本量（低于此值只进 `insufficient`，不给结构性判断）。
MIN_SAMPLE = 8

#: 机制标签 → 中文名（报告与提示词都读这一份，避免两处措辞漂移）。
CAUSE_LABELS = {
    "hard_stop": "硬止损",
    "protection_fail": "保护失效退出",
    "time_stop": "时间止损",
    "ratchet_lock": "阶梯锁利",
    "momentum_tp": "移动止盈",
    "scale_out": "分批止盈",
    "breakeven": "保本平仓",
    "ai_close": "AI 主动退出",
    "close_failed": "平仓失败",
    "unknown": "未识别",
}

_SIDE_ALIASES = {"多": "long", "空": "short", "long": "long", "short": "short",
                 "buy": "long", "sell": "short"}


def _num(value) -> Optional[float]:
    """数值化；bool/非数值/非有限一律 None（`float(True)==1.0` 会伪装成价格）。"""
    if isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _side(value) -> str:
    return _SIDE_ALIASES.get(str(value or "").strip().lower(), "")


def _pct(values) -> Optional[float]:
    clean = [v for v in values if v is not None]
    if not clean:
        return None
    return round(sum(clean) / len(clean), 4)


def _median(values) -> Optional[float]:
    clean = sorted(v for v in values if v is not None)
    if not clean:
        return None
    mid = len(clean) // 2
    if len(clean) % 2:
        return round(clean[mid], 4)
    return round((clean[mid - 1] + clean[mid]) / 2.0, 4)


def _one_r_pct(row) -> Optional[float]:
    """1R 折算成**价格百分比**（`|开仓−初始止损| / 开仓`）。

    只有 `entry_px` 与 `initial_stop_px` **都来自同一份证据快照**才算 —— 混用台账
    `open_px` 与证据止损会引入两次记录的时点差，得不偿失。
    """
    entry = _num(row.get("entry_px"))
    stop = _num(row.get("initial_stop_px"))
    if not entry or entry <= 0 or stop is None:
        return None
    distance = abs(entry - stop)
    if distance <= 0:
        return None
    return distance / entry * 100.0


def _realized_pct(row) -> Optional[float]:
    """实收价格变动百分比（交易所口径：`open_px` → `close_px`，按方向取号）。"""
    open_px = _num(row.get("open_px"))
    close_px = _num(row.get("close_px"))
    side = _side(row.get("side"))
    if not open_px or open_px <= 0 or close_px is None or not side:
        return None
    move = (close_px - open_px) if side == "long" else (open_px - close_px)
    return move / open_px * 100.0


def classify_row(row) -> Dict[str, Any]:
    """把一行平仓交易折成**离场质量样本**（纯计算）。

    **入样门槛：必须带浮动偏移证据（`mfe_pct` 或 `mae_pct`）。**
    只有开平价/平仓价的行**不入样** —— 那只能算实收，回答不了"本来能赚多少、
    吐回去多少"，正是本模块要回答的问题。若把它算进 `evidence_rows`，
    "证据覆盖率"就会被虚报成 100%（历史 82 笔全都有开平价），
    于是"缺证据"这件事反而看不见了。

    返回 `None` 表示这行没有离场证据可用。
    """
    if not isinstance(row, dict):
        return None
    mfe_pct = _num(row.get("mfe_pct"))
    mae_pct = _num(row.get("mae_pct"))
    if mfe_pct is None and mae_pct is None:
        return None
    mfe_r = _num(row.get("mfe_r"))
    mae_r = _num(row.get("mae_r"))
    realized_pct = _realized_pct(row)

    one_r = _one_r_pct(row)
    realized_r = None
    if realized_pct is not None and one_r:
        realized_r = realized_pct / one_r

    give_back_pct = None
    if mfe_pct is not None and realized_pct is not None:
        give_back_pct = mfe_pct - realized_pct
    give_back_r = None
    if mfe_r is not None and realized_r is not None:
        give_back_r = mfe_r - realized_r

    # 兑现比例：只在"曾经浮盈"时有意义（MFE ≤ 0 时谈兑现率是伪命题）
    efficiency = None
    if mfe_pct is not None and mfe_pct > 0 and realized_pct is not None:
        efficiency = realized_pct / mfe_pct * 100.0

    return {
        "inst": str(row.get("inst") or ""),
        "side": _side(row.get("side")),
        "exit_cause": str(row.get("exit_cause") or ""),
        "exit_reason_source": str(row.get("exit_reason_source") or ""),
        "net_pnl": _num(row.get("net_pnl")),
        "mfe_pct": mfe_pct, "mae_pct": mae_pct,
        "mfe_r": mfe_r, "mae_r": mae_r,
        "realized_pct": None if realized_pct is None else round(realized_pct, 4),
        "realized_r": None if realized_r is None else round(realized_r, 4),
        "one_r_pct": None if one_r is None else round(one_r, 4),
        "give_back_pct": None if give_back_pct is None else round(give_back_pct, 4),
        "give_back_r": None if give_back_r is None else round(give_back_r, 4),
        "exit_efficiency_pct": None if efficiency is None else round(efficiency, 2),
    }


def _group_stats(samples: List[Dict[str, Any]]) -> Dict[str, Any]:
    """一组样本的汇总（胜率/净利/MFE/MAE/回吐/兑现率）。"""
    pnls = [s["net_pnl"] for s in samples if s["net_pnl"] is not None]
    wins = sum(1 for p in pnls if p > 0)
    return {
        "n": len(samples),
        "wins": wins,
        "win_rate_pct": round(wins / len(pnls) * 100.0, 1) if pnls else None,
        "net_pnl": round(sum(pnls), 2) if pnls else None,
        "avg_mfe_r": _pct([s["mfe_r"] for s in samples]),
        "avg_mae_r": _pct([s["mae_r"] for s in samples]),
        "avg_give_back_r": _pct([s["give_back_r"] for s in samples]),
        "median_give_back_r": _median([s["give_back_r"] for s in samples]),
        "avg_efficiency_pct": _pct([s["exit_efficiency_pct"] for s in samples]),
        "r_sample": sum(1 for s in samples if s["mfe_r"] is not None),
    }


def analyze_exit_quality(*, closed_trades, min_sample: int = MIN_SAMPLE) -> Dict[str, Any]:
    """离场质量总分析（纯函数，零 I/O）。

    结构：

    - `overall`：全样本汇总（含 `r_sample`，即真有多少行带 R 证据）；
    - `by_mechanism`：**只统计机制确认**的出场原因分布与效果；
    - `per_symbol`：逐标的离场矩阵（找出"进场对、出场烂"的标的）；
    - `time_stop`：时间止损有效性（被时间止损的单子，离场前浮盈/浮亏如何）；
    - `insufficient`：样本不足、不可据以断言的结论清单（**诚实披露**）。
    """
    rows = [t for t in closed_trades or [] if isinstance(t, dict)] if isinstance(
        closed_trades, (list, tuple)) else []
    samples = [s for s in (classify_row(r) for r in rows) if s]
    # 只用于机制表的样本：离场原因必须是**机制确认**的
    mechanism = [s for s in samples if s["exit_reason_source"] == "mechanism" and s["exit_cause"]]

    insufficient = []
    result: Dict[str, Any] = {
        "total_rows": len(rows),
        "evidence_rows": len(samples),
        "r_rows": sum(1 for s in samples if s["mfe_r"] is not None),
        "min_sample": min_sample,
        "overall": _group_stats(samples) if samples else None,
        "by_mechanism": [],
        "per_symbol": [],
        "time_stop": None,
        "insufficient": insufficient,
    }
    if not samples:
        insufficient.append("无任何行带离场证据（MFE/MAE）：离场质量不可评估")
        return result
    if result["overall"]["r_sample"] < min_sample:
        insufficient.append(
            f"仅 {result['overall']['r_sample']} 行有 R 口径证据（< {min_sample}）："
            "回吐/兑现的 R 值不可据以断言，请只看百分比口径")

    # ── 机制化出场表（只认机制确认）──────────────────────────────────────
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for s in mechanism:
        buckets.setdefault(s["exit_cause"], []).append(s)
    by_mechanism = []
    for cause, group in buckets.items():
        stats = _group_stats(group)
        stats["exit_cause"] = cause
        stats["label"] = CAUSE_LABELS.get(cause, cause)
        by_mechanism.append(stats)
    by_mechanism.sort(key=lambda x: (x["net_pnl"] if x["net_pnl"] is not None else 0.0))
    result["by_mechanism"] = by_mechanism
    if mechanism and len(mechanism) < min_sample:
        insufficient.append(f"机制确认的样本仅 {len(mechanism)} 笔（< {min_sample}）："
                            "出场机制优劣暂不可断言")
    if samples and not mechanism:
        insufficient.append("尚无机制确认的离场原因：出场机制效果表为空（不是'效果好'）")

    # ── 逐标的离场矩阵 ──────────────────────────────────────────────────
    per_inst: Dict[str, List[Dict[str, Any]]] = {}
    for s in samples:
        if s["inst"]:
            per_inst.setdefault(s["inst"], []).append(s)
    matrix = []
    for inst, group in per_inst.items():
        stats = _group_stats(group)
        stats["inst"] = inst
        matrix.append(stats)
    matrix.sort(key=lambda x: (x["net_pnl"] if x["net_pnl"] is not None else 0.0))
    result["per_symbol"] = matrix
    thin = [m["inst"] for m in matrix if m["n"] < min_sample]
    if thin:
        insufficient.append(f"以下标的样本 < {min_sample}，其离场矩阵仅供参考："
                            f"{', '.join(thin[:8])}")

    # ── 时间止损有效性 ─────────────────────────────────────────────────
    time_stop_rows = [s for s in mechanism if s["exit_cause"] == "time_stop"]
    if time_stop_rows:
        stats = _group_stats(time_stop_rows)
        stats["avg_mfe_pct"] = _pct([s["mfe_pct"] for s in time_stop_rows])
        stats["avg_mae_pct"] = _pct([s["mae_pct"] for s in time_stop_rows])
        stats["avg_realized_pct"] = _pct([s["realized_pct"] for s in time_stop_rows])
        # "时间止损是否砍在了半路上"：MFE 明显为正却在亏损离场 ⇒ 给过机会又收走
        stats["cut_while_positive"] = sum(
            1 for s in time_stop_rows
            if (s["mfe_pct"] or 0) > 0 and (s["net_pnl"] or 0) < 0)
        result["time_stop"] = stats
        if stats["n"] < min_sample:
            insufficient.append(f"时间止损样本仅 {stats['n']} 笔（< {min_sample}）："
                                "`TIME_STOP_HOURS` 是否该调不可据以断言")
    else:
        insufficient.append("样本期内未发生时间止损：无法评估时间止损参数")

    return result


def _fmt_pct(value, unit="%", sign=False) -> str:
    """把可空数值渲染成 `--` 或带符号文本（无值就明说无值，不写 0）。"""
    if value is None:
        return "--"
    return f"{value:+.2f}{unit}" if sign else f"{value:.1f}{unit}"


def render_exit_quality_brief(analysis) -> str:
    """把分析折成**给模型看的短文本**（无证据时明说不可评估，不编造）。"""
    data = analysis if isinstance(analysis, dict) else {}
    if not data.get("evidence_rows"):
        return ("【离场质量】暂不可评估：本批平仓行没有任何 MFE/MAE 证据"
                "（平仓证据归档从 2026-10 起才开始累积，历史行无此项）。")

    lines = [f"【离场质量】样本 {data['evidence_rows']} 行"
             f"（其中 R 口径 {data.get('r_rows', 0)} 行）"]
    overall = data.get("overall") or {}
    pieces = []
    if overall.get("avg_mfe_r") is not None:
        pieces.append(f"平均最大浮盈 {overall['avg_mfe_r']:+.2f}R")
    if overall.get("avg_mae_r") is not None:
        pieces.append(f"平均最大浮亏 {overall['avg_mae_r']:+.2f}R")
    if overall.get("avg_give_back_r") is not None:
        pieces.append(f"平均回吐 {overall['avg_give_back_r']:+.2f}R")
    if overall.get("avg_efficiency_pct") is not None:
        pieces.append(f"平均兑现率 {overall['avg_efficiency_pct']:.1f}%")
    if pieces:
        lines.append("- 全样本：" + "，".join(pieces))

    if data.get("by_mechanism"):
        lines.append("- 机制化出场（仅机制确认样本）：")
        for item in data["by_mechanism"]:
            win_rate = _fmt_pct(item.get("win_rate_pct"))
            net = _fmt_pct(item.get("net_pnl"), " USDT", sign=True)
            lines.append(f"  • {item.get('label')}: {item['n']}笔 | 胜率 {win_rate} | 净利 {net}")

    ts = data.get("time_stop")
    if ts:
        lines.append(f"- 时间止损：{ts['n']} 笔，其中 {ts.get('cut_while_positive', 0)} 笔"
                     f"「曾有浮盈却亏损离场」（平均最大浮盈 "
                     f"{_fmt_pct(ts.get('avg_mfe_pct'), '')}%）")

    worst = (data.get("per_symbol") or [])[:3]
    if worst:
        rendered = []
        for m in worst:
            net = _fmt_pct(m.get("net_pnl"), " USDT", sign=True)
            give_back = _fmt_pct(m.get("avg_give_back_r"), "R", sign=True)
            rendered.append(f"{m['inst']}（{m['n']}笔/净利 {net}/平均回吐 {give_back}）")
        lines.append("- 离场最差的标的：" + "，".join(rendered))

    if data.get("insufficient"):
        lines.append("- ⚠️ 不可据以断言：" + "；".join(data["insufficient"]))
    return "\n".join(lines)
