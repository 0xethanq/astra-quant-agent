"""平仓时刻**证据归档**（自进化复盘的开仓/离场证据真源，2026-10）。

## 这个模块为什么存在

自进化复盘要回答的问题只有两类：

1. **开仓那一刻现场是什么样**（哪些梯队因子在什么状态）—— 由开仓快照承载；
2. **这笔单最后是怎么离场的、曾经有多少浮盈被give back** —— 由本模块承载。

而这两样证据在生产里**都在平仓瞬间消失**：

| 证据 | 平仓前在哪 | 平仓后 |
|---|---|---|
| 开仓快照（梯队因子） | `position_trackers.json` 的 `signal_snapshot` | 追踪器被 `trackers.pop()` ⇒ **没了** |
| 最大浮盈/浮亏（MFE/MAE） | 追踪器的 `highWaterMark` / `lowWaterMark` | 同上 ⇒ **没了** |
| 政策版本溯源 | 追踪器的 `policy_version` / `policy_hash` | 同上 ⇒ **没了** |
| **真实离场原因** | `manage_position_tp_and_trailing` 的**返回值第二项** | 调用方**丢弃返回值** ⇒ 只剩交易所侧按金额猜 |

后果（实测）：台账 82 笔平仓里 **34 笔（41%）** 出场原因是
`🎯 止盈推定（未匹配平仓单）`——那是**猜**出来的；而 `阶梯锁利` / `移动止盈` /
`时间止损` 三个**机制真实发生过**（日志可见）却从未在台账留下痕迹。
`policy_version` 溯源率 **0/84**。

## 设计

平仓那一刻把追踪器（值快照）＋机制级离场原因＋决策来源写成一条**旁车**记录，
落 `data/closed_trade_evidence.json`，由 `sync_full_ledger` 在**合并后富化**时
按 `(标的, 方向, 开仓时刻)` 容差 join 进平仓行。台账历史行**不回填、不重写**
（读取时派生），删掉本文件即完全回滚。

## 边界（Code is Law）

- **零交易动作**：本模块只组装字典与写盘，不读行情、不下单、不改仓位。
- **绝不伪造**：R 分母（初始止损距离）取不到就给 `null`，**不用**任何默认值
  硬凑一个 R —— 一个编造的 1R 会污染整个回吐分析。
- **fail-soft**：写盘失败只打印，绝不打断交易周期（与 `record_signal_snapshot` 同纪律）。
- **归因标签只认机制**：`exit_cause` 由**代码返回值**推导，绝不由盈亏金额猜。
"""

from __future__ import annotations

import json
import os
import tempfile

#: 归档保留上限（与 `signal_journal.json` 的 500 条同族的成熟做法）。
#: 取 2000：一次自进化复盘只需近期样本，而"按 key 去重、后者覆盖"保证同一笔
#: 不会因重复归档而重复计数。
CLOSE_EVIDENCE_LIMIT = 2000

#: 机制级离场原因映射：`manage_position_tp_and_trailing` 的返回语 → 稳定机器标签。
#:
#: ⚠️ 顺序敏感（长的/更具体的在前）。这些词元来自**代码返回值**，
#: 不是从台账的 `exit_reason` 散文里猜的 —— 这正是本模块存在的意义。
_EXIT_CAUSE_LABELS = (
    ("保护失效", "protection_fail"),
    ("硬止损", "hard_stop"),
    ("时间止损", "time_stop"),
    ("阶梯锁利", "ratchet_lock"),
    ("移动止盈", "momentum_tp"),
    ("平仓失败", "close_failed"),
    ("AI高置信度整仓退出", "ai_close"),
    ("AI平仓", "ai_close"),
    ("分批止盈", "scale_out"),
    ("保本", "breakeven"),
)

#: 本模块的归档 schema 版本（未来改形状时用于读取侧分流）。
EVIDENCE_SCHEMA_VERSION = 1


def exit_cause_label(cause) -> str:
    """把中文离场语归一成稳定机器标签；认不出就返回 `"unknown"`。

    `"unknown"` 是**诚实的**结果，不是失败：台账侧会据此把该行的
    `exit_reason_source` 标成"推断"，而不是伪装成机制确认。
    """
    text = str(cause or "")
    for token, label in _EXIT_CAUSE_LABELS:
        if token in text:
            return label
    return "unknown"


def _base_inst(inst_id, name) -> str:
    """标的基名（台账 `inst` 用的就是基名，如 `BTC`）。"""
    base = str(name or "").strip()
    if base:
        return base
    return str(inst_id or "").replace("-USDT-SWAP", "").strip()


def _norm_side(side) -> str:
    """方向归一为 `long` / `short`（台账侧是 `多`/`空`，join 时同样归一）。"""
    text = str(side or "").strip().lower()
    if text in ("short", "空", "sell"):
        return "short"
    if text in ("long", "多", "buy"):
        return "long"
    return "unknown"


def _num(value):
    """取数值；bool / 非数值 / 非有限值一律 None（绝不让 `True` 混进价格）。"""
    if isinstance(value, bool):
        return None          # 刻意先拦 bool：`float(True) == 1.0` 会伪装成合法价格
    if not isinstance(value, (int, float)):
        try:
            value = float(value)  # 字符串数字（JSON 里偶见）允许
        except (TypeError, ValueError):
            return None
    value = float(value)
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def evidence_key(*, inst, side, open_time) -> str:
    """归档键（已归一）：`<基名>|<long|short>|<开仓时刻>`。

    join 侧按**容差**匹配（追踪器的 `entryTs` 是建仓后首次巡检时刻，可能比交易所
    `cTime` 晚最多一个巡检周期），故键只用于**去重**，不用于精确 join。
    """
    return f"{_base_inst(inst, None)}|{_norm_side(side)}|{str(open_time or '').strip()}"


def _resolve_side(tracker) -> str:
    """定方向：先认追踪器 `side`，认不出再从冻结的止损相对位置推导。

    ⚠️ 为什么需要兜底：净持仓账户的 `posSide` 是 `net`，而 `position_exit.py`
    用 `"long" in side.lower()` 判方向 —— 于是追踪器里可能出现 `side="net"`，
    而真实方向只能从价位关系看出来。用**自己冻结的两个价格**推导不是编造：
    止损在开仓价**下方** ⇒ 多头（做空不会把止损放在下方）。
    """
    side = _norm_side(tracker.get("side"))
    if side != "unknown":
        return side
    entry_px = _num(tracker.get("entryPx"))
    stop_px = _num(tracker.get("initialStopPx"))
    if entry_px is not None and stop_px is not None and entry_px != stop_px:
        return "long" if stop_px < entry_px else "short"
    return "unknown"


def build_close_evidence(*, tracker, position_key, exit_cause, closed_at,
                         decision_source=None, adopted_role=None) -> dict:
    """组装一条平仓证据记录（纯函数，零 I/O）。

    `tracker` 必须是**平仓前**的追踪器值快照（调用方负责在 `trackers.pop` 之前取）。

    ## 决策来源为什么从追踪器读

    `decision_source` / `adopted_role` 描述的是**建仓那一刻**是谁做的决定
    （单模型直连 / 投委会 + 采纳席位）。追踪器在**建仓后首次巡检**建立，
    那一刻 per-symbol 决策缓存里还留着建仓周期的决定，故在**建仓时**钉进追踪器
    最准确；到平仓时缓存早被后续周期覆盖，再读就是错的。因此这两个字段由
    `position_exit.py` 在建档时写入，本函数**优先**读追踪器，入参只作兜底。

    ## 浮动盈亏口径（MFE / MAE）——**方向感知**

    追踪器的两个水位是**原始价格**，含义随方向翻转
    （`position_exit.py`：多头 `highWaterMark` 是浮盈极值、空头 `lowWaterMark` 才是）。
    若不分方向地取 `highWaterMark` 当浮盈极值，**空头会被整笔读反**
    （把最痛的那一瞬记成最大浮盈）。

    故本函数统一输出**盈亏口径**（不是价格口径）：

    | 字段 | 含义 | 多头来源 | 空头来源 |
    |---|---|---|---|
    | `mfe_pct` / `mfe_r` | 最有利时浮盈（≥0 才好） | `highWaterMark` | `lowWaterMark` |
    | `mae_pct` / `mae_r` | 最不利时浮亏（≤0 才好） | `lowWaterMark` | `highWaterMark` |

    R 口径：`r_denominator = |entry_px − initial_stop_px|`，即"1R = 初始止损距离"。
    两个价格任一取不到、或距离 ≤ 0 ⇒ `mfe_r` / `mae_r` 为 `null`（**不硬凑**），
    但百分比口径 `mfe_pct` / `mae_pct` 仍然给出（它们不依赖止损）。
    """
    tracker = tracker if isinstance(tracker, dict) else {}
    inst_id = tracker.get("instId") or ""
    inst = _base_inst(inst_id, tracker.get("name"))
    side = _resolve_side(tracker)
    open_time = str(tracker.get("entryTime") or "").strip()

    entry_px = _num(tracker.get("entryPx"))
    initial_stop = _num(tracker.get("initialStopPx"))
    hwm = _num(tracker.get("highWaterMark"))
    lwm = _num(tracker.get("lowWaterMark"))

    # 方向感知：先把"最有利 / 最不利"水位挑出来（认不出方向就都不算）
    favorable_px = adverse_px = None
    if side == "long":
        favorable_px, adverse_px = hwm, lwm
    elif side == "short":
        favorable_px, adverse_px = lwm, hwm

    mfe_pct = mae_pct = None
    if entry_px and entry_px > 0:
        if favorable_px is not None:
            mfe_pct = round((favorable_px - entry_px) / entry_px * 100.0, 4)
        if adverse_px is not None:
            mae_pct = round((adverse_px - entry_px) / entry_px * 100.0, 4)
        if side == "short":
            # 空头的浮盈是"价格跌"，故盈亏口径要取反号
            if mfe_pct is not None:
                mfe_pct = -mfe_pct
            if mae_pct is not None:
                mae_pct = -mae_pct

    r_denom = None
    if entry_px is not None and initial_stop is not None:
        distance = abs(entry_px - initial_stop)
        if distance > 0:
            r_denom = distance
    mfe_r = mae_r = None
    if r_denom:
        if favorable_px is not None:
            delta = (favorable_px - entry_px) if side == "long" else (entry_px - favorable_px)
            mfe_r = round(delta / r_denom, 4)
        if adverse_px is not None:
            delta = (adverse_px - entry_px) if side == "long" else (entry_px - adverse_px)
            mae_r = round(delta / r_denom, 4)

    return {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "key": evidence_key(inst=inst, side=side, open_time=open_time),
        "position_key": str(position_key or ""),
        "inst": inst,
        "inst_id": str(inst_id),
        "side": side,
        "open_time": open_time,
        "entry_ts": _num(tracker.get("entryTs")),
        "closed_at": str(closed_at or ""),
        "exit_cause": exit_cause_label(exit_cause),
        "exit_cause_raw": str(exit_cause or ""),
        "entry_px": entry_px,
        "initial_stop_px": initial_stop,
        "high_water_mark": hwm,
        "low_water_mark": lwm,
        "r_denominator": r_denom,
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "take_profit_px": _num(tracker.get("takeProfitPx")),
        "scale_out_tp": _num(tracker.get("scale_out_tp")),
        "scale_out_phase": _num(tracker.get("scale_out_phase")),
        "strategy_tag": str(tracker.get("strategy_tag") or ""),
        "policy_version": str(tracker.get("policy_version") or ""),
        "policy_hash": str(tracker.get("policy_hash") or ""),
        "decision_source": str(tracker.get("decision_source") or decision_source or "unknown"),
        "adopted_role": (tracker.get("adopted_role") or adopted_role) or None,
        "entry_snapshot": tracker.get("signal_snapshot") if isinstance(
            tracker.get("signal_snapshot"), dict) else None,
    }


def resolve_decision_attribution(inst_id, *, cache_path) -> tuple:
    """从 per-symbol 决策缓存解析 `(decision_source, adopted_role)`。

    | 缓存实况 | 返回 | 理由 |
    |---|---|---|
    | `council.ran is True` | `("council", adopted_role)` | 投委会真的跑了，采纳席位可归因 |
    | `council.ran is False` | `("single_model", None)` | 单模型直连，**显式**记录"没有席位" |
    | 读不到 / 无该标的 / 无 `council` 字段 | `("unknown", None)` | **诚实标未知** |

    ⚠️ 最后一行刻意**不**默认成 `single_model`：那会在委员会模式下对"没读到"的
    持仓撒谎，把委员会的单子记成单模型的，复盘分段就全错了。

    本函数只读一次 JSON，不做任何写入；`cache_path` 由门面按 `DATA_DIR` 调用期解析。
    """
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            cache = json.load(handle)
    except (OSError, ValueError, TypeError):
        return "unknown", None
    if not isinstance(cache, dict):
        return "unknown", None
    entry = cache.get(inst_id)
    if not isinstance(entry, dict):
        return "unknown", None
    council = entry.get("council")
    if not isinstance(council, dict):
        return "unknown", None
    adopted = council.get("adopted_role")
    if council.get("ran"):
        return "council", (str(adopted) if adopted else None)
    return "single_model", None


def load_close_evidence(path) -> list:
    """读取归档（列表）。文件不存在/损坏 ⇒ 空列表（**绝不**因旁车损坏影响交易）。"""
    if not path:
        return []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return []
    if not isinstance(raw, list):
        return []
    return [item for item in raw if isinstance(item, dict)]


def append_close_evidence(path, record) -> bool:
    """把一条证据**原子**写入归档；按 `key` 去重（后者覆盖），保留最近 N 条。

    返回是否写成功。**任何失败都只返回 False**（调用方只需按 fail-soft 处理）：
    旁车写不进去绝不该打断交易周期。
    """
    if not path or not isinstance(record, dict):
        return False
    key = str(record.get("key") or "").strip()
    try:
        records = [r for r in load_close_evidence(path) if str(r.get("key") or "").strip() != key]
        records.append(record)
        records = records[-CLOSE_EVIDENCE_LIMIT:]
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(prefix=".close-evidence-", suffix=".tmp", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(records, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, path)
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
        return True
    except Exception as exc:  # noqa: BLE001 - 旁车写盘绝不打断主流程
        print(f"[平仓证据] 归档失败（不影响交易）: {exc}")
        return False
