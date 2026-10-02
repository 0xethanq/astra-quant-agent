"""平仓行 ← 平仓证据 的 join（`scripts/ledger/` 部件，2026-10）。

## 这个模块解决什么

台账的**权威来源**是交易所平仓历史（`scripts/ledger/okx_history.py`），它只能拿到
交易所知道的字段：开平价、张数、手续费、盈亏。而复盘要的两类证据交易所**根本不知道**：

- **开仓那一刻的现场**（7 梯队因子快照）；
- **这笔单真实是怎么离场的、曾经浮盈到过多少**（MFE/MAE ＋ 机制级离场原因）。

这些只存在于交易进程内存里的追踪器（`position_trackers.json`），并在平仓瞬间被
`trackers.pop()` 抹掉。`scripts/trader/close_evidence.py` 在 pop 之前把它们钉成旁车
记录，本模块负责把旁车**按标的＋方向＋开仓时刻**容差 join 回平仓行。

## 设计取舍

- **纯计算、零 I/O**：读盘与写盘留在 `sync_full_ledger`（调用方），本模块只吃列表出列表，
  于是可以完全离线单测。
- **只在 `build_lifecycle_ledger` 的"合并后、写盘前"调用**，**绝不碰
  `build_okx_trade`** —— 那个函数被 `tests/extraction/test_ledger_okx_history_extraction.py`
  以 AST ＋逐行双重钉死，改它等于把六个历史判定一起置于风险中。
- **事实与猜测显式分离**：匹配上且离场原因是机制标签 ⇒ `exit_reason_source="mechanism"`；
  否则 `"inferred"`（沿用交易所侧 clOrdId 匹配/金额启发式）。旧实现把两者混成一句话，
  于是 41% 的"止盈推定"看起来和"首批分批止盈"一样可信。
- **绝不覆盖交易所既有字段**：只写台账从来不产出的键（见 `EVIDENCE_FIELDS`）。
- **一条证据只用一次**：两个平仓行不会共享同一条证据（否则回吐统计会重复计数）。
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional, Tuple

#: 证据的 `entryTime`（追踪器建档时刻）可能比交易所开仓时刻（`cTime`）晚最多一个
#: 巡检周期（15min，留 20min 余量）；反向允许 6h —— 与
#: `scripts/evolution/observability` 同族的因果窗口口径一致（禁止用未来/过期证据）。
EVIDENCE_MAX_LATE_SECONDS = 1200
EVIDENCE_MAX_EARLY_SECONDS = 6 * 3600

#: 需要从证据搬进平仓行的键。**全部是台账交易所路径从不产出的键**，
#: 故写入不会覆盖任何既有事实字段。
EVIDENCE_FIELDS = (
    "entry_snapshot",
    "mfe_pct", "mae_pct", "mfe_r", "mae_r", "r_denominator",
    "entry_px", "initial_stop_px", "high_water_mark", "low_water_mark",
    "policy_version", "policy_hash", "strategy_tag", "scale_out_phase",
    "decision_source", "adopted_role",
    "evidence_closed_at",
)

#: 方向别名（台账侧是 `多`/`空`，证据侧是 `long`/`short`）。
_SIDE_ALIASES = {"多": "long", "空": "short", "long": "long", "short": "short",
                 "buy": "long", "sell": "short"}

#: 离场原因的"事实 vs 猜测"标记。
SOURCE_MECHANISM = "mechanism"
SOURCE_INFERRED = "inferred"


def normalize_inst(value) -> str:
    """标的基名（去掉 `-USDT-SWAP` 后缀），两侧 join 用它对齐。"""
    return str(value or "").strip().replace("-USDT-SWAP", "")


def normalize_side(value) -> str:
    """方向归一为 `long` / `short`；认不出返回空串。"""
    return _SIDE_ALIASES.get(str(value or "").strip().lower(), "")


def _parse_bj(text) -> Optional[datetime.datetime]:
    """解析北京时间的 `YYYY-MM-DD HH:MM:SS`（台账与追踪器同格式）。"""
    raw = str(text or "").strip()
    if not raw or raw.startswith("--"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _match_evidence(row: Dict[str, Any], pool: List[Dict[str, Any]],
                    used: set) -> Optional[Dict[str, Any]]:
    """在同一标的＋同一方向的候选里，取开仓时刻**最近**且落在窗口内的一条。"""
    row_inst = normalize_inst(row.get("inst"))
    row_side = normalize_side(row.get("side"))
    row_dt = _parse_bj(row.get("open_time"))
    if not row_inst or not row_dt:
        return None
    best_delta, best_item = None, None
    for idx, item in enumerate(pool):
        if idx in used:
            continue
        if normalize_inst(item.get("inst") or item.get("inst_id")) != row_inst:
            continue
        item_side = normalize_side(item.get("side"))
        # 方向必须可比；证据侧认不出方向时不强行匹配（宁可留"推断"）
        if not row_side or not item_side or item_side != row_side:
            continue
        item_dt = _parse_bj(item.get("open_time")) or _parse_bj(item.get("closed_at"))
        if item_dt is None:
            continue
        delta = (item_dt - row_dt).total_seconds()
        # 追踪器建档在成交之后 ⇒ 正向偏差是常态；反向偏差留 6h 容差（与快照 join 同口径）
        if delta < -EVIDENCE_MAX_EARLY_SECONDS or delta > EVIDENCE_MAX_LATE_SECONDS:
            continue
        if best_delta is None or abs(delta) < abs(best_delta):
            best_delta, best_item = delta, idx
    if best_item is None:
        return None
    used.add(best_item)
    return pool[best_item]


def _apply_evidence(row: Dict[str, Any], evidence: Dict[str, Any]) -> Dict[str, Any]:
    """把证据字段写进平仓行，并给出**事实/猜测**标记。就地修改并返回该行。"""
    for key in EVIDENCE_FIELDS:
        if key == "evidence_closed_at":
            continue
        value = evidence.get(key)
        # 只写台账交易所路径从不产出的键；空值不写（避免用 None 覆盖可能存在的历史值）
        if value is not None:
            row[key] = value
    if evidence.get("closed_at"):
        row["evidence_closed_at"] = evidence["closed_at"]
    exit_cause = str(evidence.get("exit_cause") or "").strip()
    if exit_cause and exit_cause != "unknown":
        row["exit_cause"] = exit_cause
        row["exit_cause_raw"] = str(evidence.get("exit_cause_raw") or "")
        row["exit_reason_source"] = SOURCE_MECHANISM
    else:
        row["exit_reason_source"] = SOURCE_INFERRED
    return row


def enrich_closed_rows_with_evidence(*, trades, evidence) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """把平仓证据 join 进平仓行（纯函数，无 I/O）。

    返回 `(行列表, 统计)`；统计用于同步日志与自进化报告的可观测性披露。

    语义要点：
    - 只处理 `status == "closed"` 且场所为 OKX 的行（外所行已随场所下线只读容错）；
    - **没有匹配到证据的平仓行也会被打上 `exit_reason_source="inferred"`** ——
      这正是本次改造的目的：让"猜的"在数据里就看得出来，而不是与"确认的"长得一样；
    - 台账既有字段一律不动（证据只写新增键）。
    """
    rows = [t for t in (trades or []) if isinstance(t, dict)]
    pool = [e for e in (evidence or []) if isinstance(e, dict)]
    used: set = set()
    stats = {"closed_rows": 0, "matched": 0, "mechanism": 0, "inferred": 0}

    for row in rows:
        if str(row.get("status") or "").strip().lower() != "closed":
            continue
        venue = str(row.get("venue") or "okx").strip().lower()
        if venue and venue != "okx":
            continue
        stats["closed_rows"] += 1
        matched = _match_evidence(row, pool, used)
        if matched is None:
            row["exit_reason_source"] = SOURCE_INFERRED
            stats["inferred"] += 1
            continue
        _apply_evidence(row, matched)
        stats["matched"] += 1
        if row.get("exit_reason_source") == SOURCE_MECHANISM:
            stats["mechanism"] += 1
        else:
            stats["inferred"] += 1

    return rows, stats
