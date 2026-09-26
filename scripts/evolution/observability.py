"""数理快照**可观测性**审计（结构优化阶段 4·B3 第四十二刀）。

原样搬自 `scripts/self_improvement_engine.py` 的 L128–196 聚簇（约 69 行）：

| 成员 | 作用 |
|---|---|
| `DYNAMICS_FIELDS` | **17** 个动力学链字段名 |
| `DYNAMICS_OBSERVED_MIN` | 视为"可观测"的最低非空字段数（88% 容差）= **15** |
| `_parse_bj` | 北京时间解析（去掉 tzinfo 后再 join） |
| `classify_snapshot_observability` | 逐单打标签 |
| `prune_snapshot` | 剔除 null 字段 |
| `audit_snapshot_observability` | 汇总统计 |
| `render_observability_brief` | 渲染成一行人类可读摘要 |

## 为什么值得单独成模块

这一簇是**宿主侧的确定性审计**，与自进化引擎的编排、LLM 调用、记忆合并
没有任何关系。抽出来后，"可观测性怎么判定"这件事才有一个唯一的落点。

## 背景（原注释保留）

事故链：`build_signal_snapshot` 旧版 schema 错配（09-09 已修复写入侧）导致历史
journal 全部为「对象存在但 22/17 动力学字段 null」的空壳；宿主把空壳原样喂给
模型，模型只能自数 null，既易漂移，也给「倒推伪造」留了口子。从此由宿主逐单
判定可观测性并把统计结论前置注入 Prompt；join 侧同时禁止用未来或过期快照
回填因果证据。

## ⚠️ `15` 这个数不是手写的，且原注释里的「22/17」是错的

`DYNAMICS_OBSERVED_MIN = max(1, int(len(DYNAMICS_FIELDS) * 0.85) + 1)`
—— 字段表实际 **17** 项：17 × 0.85 = 14.45 → `int` 截断为 14 → +1 = **15**。
它是**从字段表算出来的**，不是常数。改字段表会同步改门槛，
**勿**"顺手"换成字面量。

> 原文件里那段事故说明写的是「22/17 动力学字段 null」，把 22 写成了字段数。
> 实测字段表是 **17** 项（`DYNAMICS_OBSERVED_MIN` 因此是 15 而非 19）。
> 这是个**注释与代码不符**的小瑕疵，本刀**只修正注释、不动代码** ——
> 因为 22 从未参与任何计算。
"""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional

from astra_backend.time_utils import parse_beijing

__all__ = [
    "DYNAMICS_FIELDS",
    "DYNAMICS_OBSERVED_MIN",
    "classify_snapshot_observability",
    "prune_snapshot",
    "audit_snapshot_observability",
    "render_observability_brief",
]

DYNAMICS_FIELDS = (
    "velocity", "acceleration", "jerk", "impulse", "curvature", "power",
    "power_regime", "regime", "dynamics_quality",
    "continuation_prob_pct", "breakdown_prob_pct", "var_95_pct", "cvar_95_pct",
    "prob_regime", "is_fat_tail", "energy_integral", "deviation_area_integral",
)
# 动力学链视为「可观测」的最低非空字段数（88% 容差：允许个别外部观测缺失）
DYNAMICS_OBSERVED_MIN = max(1, int(len(DYNAMICS_FIELDS) * 0.85) + 1)


def _parse_bj(ts) -> Optional[datetime.datetime]:
    dt = parse_beijing(ts)
    # Existing join callers use naive Beijing values; normalize BEFORE removing tz.
    return dt.replace(tzinfo=None) if dt else None


def classify_snapshot_observability(snap) -> str:
    """逐单分类：DYNAMICS_OBSERVED / PARTIAL / PRICE_ONLY / NONE。

    只按 DYNAMICS_FIELDS 的真实非空计数；price/atr/adx/funding 等属于普通观测，
    不算动力学链。全 null 空壳不再是「有快照」，杜绝表面可观测、实际不可归因。
    """
    if not isinstance(snap, dict) or not snap:
        return "NONE"
    n = sum(1 for k in DYNAMICS_FIELDS if snap.get(k) is not None)
    if n == 0:
        return "PRICE_ONLY"
    if n >= DYNAMICS_OBSERVED_MIN:
        return "DYNAMICS_OBSERVED"
    return "PARTIAL"


def prune_snapshot(snap):
    """剔除值为 null 的字段；可观测性判定由 snapshot_observability 标签承载，
    不再让模型在 22 个 null 里自行数证据。"""
    if not isinstance(snap, dict):
        return None
    pruned = {k: v for k, v in snap.items() if v is not None}
    return pruned or None


def audit_snapshot_observability(closed_trades) -> Dict[str, int]:
    total = len(closed_trades)
    counts = {"DYNAMICS_OBSERVED": 0, "PARTIAL": 0, "PRICE_ONLY": 0, "NONE": 0}
    for t in closed_trades:
        tag = str(t.get("snapshot_observability") or "NONE")
        counts[tag] = counts.get(tag, 0) + 1
    counts["total"] = total
    counts["math_observable"] = counts["DYNAMICS_OBSERVED"] + counts["PARTIAL"]
    return counts


def render_observability_brief(audit) -> str:
    return (
        f"已平仓 {audit['total']} 笔 | 开仓时刻数理快照：完全可观测 {audit['DYNAMICS_OBSERVED']} / "
        f"部分可观测 {audit['PARTIAL']} / 仅价格与普通观测 {audit['PRICE_ONLY']} / 无快照 {audit['NONE']}"
    )
