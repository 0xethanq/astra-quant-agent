"""**心法经验健康度**：让 `health_score` 从装饰品变成承重件（方向 4，2026-10）。

## 改造前的实况

`health_score` 只在两处被写：基准心法的常量（92/95/98/99）与
`_new_lesson()` 里写死的 `90.0`。它**从未被重算、也从未被读取**：

- 注入排序是 `(is_baseline, created_at)` ⇒ **"新的赢"**，与实战表现无关；
- 一条心法无论落地后是赚是亏，`health_score` 永远停在 90.0。

于是"心法库"实际是个只增不减的日志：学到的战术层心法会按 TTL 过期，
但**在有效期内不管对不对都一直占着注入配额**（上限 8 条）。

## 本模块给什么

用**平仓证据**给每条心法算一个可辩护的健康分：

1. **析出心法的适用人群（cohort）**：它点名的标的 / 方向 / 离场机制。
   一条只说"顺势追多"的心法，就用**多头样本**评价它；点名 BTC 的就用 BTC 样本。
2. **用该人群的实盘结果打分**：胜率与期望值（每笔平均净利 ÷ 每笔平均绝对净利），
   并**按样本量向 50 分回归** —— 样本刚好达标时不敢给极端分。
3. **证据不足就不打分**（返回 `None`）：绝不"因为算不出来就默认 90 分健康"，
   也绝不用它去改变心法的启用状态。

## 三条不可越的边界（Code is Law）

- **不删任何心法**：`archived` 只是 `enabled=False` ＋ 留痕，面板可见可人工恢复；
- **样本不足恒不改分**：`< MIN_HEALTH_SAMPLE` 一律返回 `None` ⇒ 保留原分；
- **证据不足恒不改状态**：没分就不归档（"算不出来"不是"不健康"）。

2026-10：原「绝不动基准心法」一条随基准机制**整体拆除** —— 用户要求系统不再预设
任何心法，故不再有宪法级豁免，所有心法一律同标准评分与归档。
"""

from __future__ import annotations

import copy
import datetime
from typing import Any, Dict, List, Optional, Tuple

#: 给心法打分所需的最低样本量。低于此值**不打分**（保留原分），
#: 与 `self_improvement_engine.DETERMINISTIC_MIN_SAMPLE` 同一量级。
MIN_HEALTH_SAMPLE = 10

#: 归档阈值：健康分低于此值**且**样本达标**且**非基准 ⇒ 归档（停用留痕）。
ARCHIVE_HEALTH_THRESHOLD = 70.0

#: 归档判定所需的更高样本门槛（比"能打分"更严：改状态比只改数字后果重）。
ARCHIVE_MIN_SAMPLE = 10

#: 方向词 → long / short（心法正文是中文散文，故按词表析出）。
_LONG_WORDS = ("做多", "多头", "追多", "低吸", "回踩买", "买入", "看涨")
_SHORT_WORDS = ("做空", "空头", "高空", "抛压", "反弹空", "卖出", "看跌")

#: 离场机制词 → 机制标签（与 `close_evidence._EXIT_CAUSE_LABELS` 同口径）。
_EXIT_WORDS = {
    "硬止损": "hard_stop", "保护失效": "protection_fail", "时间止损": "time_stop",
    "阶梯锁利": "ratchet_lock", "移动止盈": "momentum_tp", "分批止盈": "scale_out",
    "保本": "breakeven", "主动退出": "ai_close",
}

_SIDE_ALIASES = {"多": "long", "空": "short", "long": "long", "short": "short"}


def _num(value) -> Optional[float]:
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


def extract_cohort(rule_text, *, available_insts) -> Dict[str, Any]:
    """从心法正文析出它**适用的人群**（标的 / 方向 / 离场机制）。

    只析出**正文里真的点名**的维度：没点名的维度不加过滤（"所有人"）。
    这样"点名 BTC 的心法用 BTC 样本评价"、"只说顺势追多的心法用多头样本评价"，
    而一条泛泛的心法就用全样本 —— 不硬套一个不存在的 cohort。

    返回 `{"insts": [...], "side": "long|short|", "exit_causes": [...]}`。
    """
    text = str(rule_text or "")
    cohort: Dict[str, Any] = {"insts": [], "side": "", "exit_causes": []}

    insts = []
    for inst in sorted({str(i) for i in (available_insts or []) if i}):
        # 用词边界匹配，避免 `ETH` 命中 `ETHFI` 之类的子串假名
        if _contains_symbol(text, inst):
            insts.append(inst)
    cohort["insts"] = insts

    long_hit = any(w in text for w in _LONG_WORDS)
    short_hit = any(w in text for w in _SHORT_WORDS)
    # 多空都提到 ⇒ 这条心法本身是双向的，不加方向过滤（否则会把它按错的一半评价）
    if long_hit != short_hit:
        cohort["side"] = "long" if long_hit else "short"

    cohort["exit_causes"] = sorted({label for word, label in _EXIT_WORDS.items()
                                    if word in text})
    return cohort


def _contains_symbol(text, inst) -> bool:
    """标的必须是**独立词**出现（`ETH` 不该命中 `ETHFI`）。"""
    import re
    return bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(inst)}(?![A-Za-z0-9])", text))


def _side_of(row) -> str:
    return _SIDE_ALIASES.get(str(row.get("side") or "").strip().lower(), "")


def select_cohort(closed_trades, cohort) -> List[Dict[str, Any]]:
    """按 cohort 过滤平仓样本（各维度 AND）。"""
    insts = {str(i) for i in (cohort.get("insts") or [])}
    side = str(cohort.get("side") or "")
    causes = {str(c) for c in (cohort.get("exit_causes") or [])}
    out = []
    for row in closed_trades or []:
        if not isinstance(row, dict):
            continue
        if insts and str(row.get("inst") or "") not in insts:
            continue
        if side and _side_of(row) != side:
            continue
        if causes and str(row.get("exit_cause") or "") not in causes:
            continue
        if _num(row.get("net_pnl")) is None:
            continue
        out.append(row)
    return out


def score_cohort(rows) -> Optional[Dict[str, Any]]:
    """用一组平仓样本打分（胜率 ＋ 期望值，按样本量向 50 分回归）。

    期望值口径：`每笔平均净利 ÷ 每笔平均绝对净利` ∈ [-1, 1] ——
    与金额绝对规模无关，故不同标的/不同保证金的心法可横向比较。
    """
    nets = [_num(r.get("net_pnl")) for r in rows]
    nets = [n for n in nets if n is not None]
    n = len(nets)
    if n <= 0:
        return None
    wins = sum(1 for x in nets if x > 0)
    win_rate = wins / n * 100.0
    total = sum(nets)
    avg_abs = sum(abs(x) for x in nets) / n
    expectancy_norm = (total / n / avg_abs) if avg_abs > 0 else 0.0

    raw = 50.0 + (win_rate - 50.0) * 0.5 + expectancy_norm * 30.0
    raw = max(0.0, min(100.0, raw))
    # 样本越少越不敢给极端分：恰好达标时只信一半偏离
    confidence = min(1.0, n / (2.0 * MIN_HEALTH_SAMPLE))
    health = 50.0 + (raw - 50.0) * confidence

    # 证据可观测性折价：人群样本大多是"仅价格"(PRICE_ONLY/NONE) 时，
    # 这条心法赖以成立的因子根本不可观测 ⇒ 得分偏离减半（低置信）。
    observable = sum(1 for r in rows
                     if str(r.get("snapshot_observability") or "") in ("DYNAMICS_OBSERVED", "PARTIAL"))
    low_confidence = bool(rows) and (observable / len(rows)) < 0.5
    if low_confidence:
        health = 50.0 + (health - 50.0) * 0.5

    return {
        "health_score": round(max(0.0, min(100.0, health)), 1),
        "sample_size": n,
        "win_rate_pct": round(win_rate, 1),
        "net_pnl": round(total, 2),
        "expectancy_norm": round(expectancy_norm, 4),
        "low_confidence": low_confidence,
    }


def score_lesson_against_trades(rule_text, *, closed_trades, min_sample: int = MIN_HEALTH_SAMPLE
                                ) -> Optional[Dict[str, Any]]:
    """给一条心法算健康分；**证据不足返回 `None`**（调用方必须保留原分）。

    `None` 的三种情况：没有平仓样本、析不出任何 cohort、cohort 样本 < `min_sample`。
    这三种都**不是**"健康"或"不健康"，而是**未知** —— 因此绝不改分、更不归档。
    """
    rows = [r for r in closed_trades or [] if isinstance(r, dict)] if isinstance(
        closed_trades, (list, tuple)) else []
    if not rows:
        return None
    insts = {str(r.get("inst") or "") for r in rows if r.get("inst")}
    cohort = extract_cohort(rule_text, available_insts=insts)
    subset = select_cohort(rows, cohort)
    if len(subset) < max(1, int(min_sample or 1)):
        return None
    scored = score_cohort(subset)
    if not scored:
        return None
    scored["cohort"] = cohort
    scored["basis"] = _describe_basis(cohort)
    return scored


def _describe_basis(cohort) -> str:
    """把 cohort 说成人话，供面板与报告展示（"依据什么样本打的这个分"）。"""
    parts = []
    if cohort.get("insts"):
        parts.append("/".join(cohort["insts"]))
    if cohort.get("side"):
        parts.append("多头" if cohort["side"] == "long" else "空头")
    if cohort.get("exit_causes"):
        parts.append("＋".join(cohort["exit_causes"]))
    return "·".join(parts) if parts else "全样本"


def rank_key(item) -> tuple:
    """注入/展示排序键：**健康分降序，分数相同才比新旧**。

    ⚠️ 这是本次改造的关键：旧键 `(is_baseline, created_at)` 是**"新的赢"** ——
    一条落地后一直亏钱的战术心法，只要够新就挤掉更有效的旧心法（配额只有 8 条）。
    `health_score` 缺失时按 0 处理，于是"没打过分的"排在有分的之后（不冒充健康）。

    2026-10：`is_baseline` 那一档随基准机制整体拆除（系统不再预设任何心法）。
    """
    item = item if isinstance(item, dict) else {}
    health = _num(item.get("health_score"))
    return (
        health if health is not None else 0.0,
        str(item.get("created_at") or ""),
    )


def rank_lessons(lessons) -> List[Dict[str, Any]]:
    """按 `rank_key` 降序排好（`render_lessons` 与 `injection_report` 共用一份，
    避免两处排序逻辑漂移 —— 面板说注入了 A，提示词里却是 B）。"""
    return sorted([i for i in (lessons or []) if isinstance(i, dict)],
                  key=rank_key, reverse=True)


def decide_archive(item, scored) -> Tuple[bool, str]:
    """决定是否归档（停用留痕）。证据不足永不归档。

    2026-10：基准豁免随基准机制整体拆除 —— 系统已不再预设任何心法，
    故所有心法一律同标准（低分 ＋ 样本达标 ⇒ 归档）。
    """
    item = item if isinstance(item, dict) else {}
    if not scored:
        return False, "证据不足，不改变状态"
    if int(scored.get("sample_size") or 0) < ARCHIVE_MIN_SAMPLE:
        return False, f"样本 {scored.get('sample_size')} < {ARCHIVE_MIN_SAMPLE}，不改变状态"
    health = _num(scored.get("health_score"))
    if health is None:
        return False, "无健康分，不改变状态"
    if health >= ARCHIVE_HEALTH_THRESHOLD:
        return False, f"健康分 {health} ≥ {ARCHIVE_HEALTH_THRESHOLD}，保持启用"
    return True, (f"健康分 {health} < {ARCHIVE_HEALTH_THRESHOLD}（样本 "
                  f"{scored.get('sample_size')} 笔，依据 {scored.get('basis')}）："
                  "归档为停用存档，可人工复核恢复")


def refresh_lesson_health(lessons, *, closed_trades,
                          min_sample: int = MIN_HEALTH_SAMPLE) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """重算全部心法健康度并给出归档决定（**纯函数**，不写盘）。

    返回 `(新列表, 变更明细)`。变更明细每条含
    `{id, action, old_health, new_health, sample_size, basis, reason}`，
    供审计日志与面板如实披露"谁的分变了、为什么、依据多少样本"。

    **绝不删除条目**：归档 = `enabled=False` ＋ `shield_status="archived"` ＋ 留痕字段。
    """
    updated: List[Dict[str, Any]] = []
    changes: List[Dict[str, Any]] = []
    now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

    for item in lessons or []:
        if not isinstance(item, dict):
            continue
        fresh = copy.deepcopy(item)
        scored = score_lesson_against_trades(
            fresh.get("rule_text"), closed_trades=closed_trades, min_sample=min_sample)
        if scored:
            old_health = _num(fresh.get("health_score"))
            fresh["health_score"] = scored["health_score"]
            fresh["sample_size"] = scored["sample_size"]
            fresh["health_basis"] = scored["basis"]
            fresh["health_scored_at"] = now_str
            if old_health is None or abs(old_health - scored["health_score"]) >= 0.05:
                changes.append({
                    "id": fresh.get("id"), "action": "rescore",
                    "old_health": old_health, "new_health": scored["health_score"],
                    "sample_size": scored["sample_size"], "basis": scored["basis"],
                    "reason": "按平仓证据重算",
                })
            should_archive, reason = decide_archive(fresh, scored)
            if should_archive and fresh.get("enabled", True):
                fresh["enabled"] = False
                fresh["shield_status"] = "archived"
                fresh["archived_at"] = now_str
                fresh["archived_reason"] = reason
                changes.append({
                    "id": fresh.get("id"), "action": "archive",
                    "old_health": old_health, "new_health": scored["health_score"],
                    "sample_size": scored["sample_size"], "basis": scored["basis"],
                    "reason": reason,
                })
        updated.append(fresh)

    return updated, changes
