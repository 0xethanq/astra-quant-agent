"""台账同步后的新平仓通知（从 sync_full_ledger.build_lifecycle_ledger 搬出）。

判定"新平仓"= id 不在本轮既有已平集合里、且 status == "closed"；本轮
OKX 生命周期来源逐条通知。

qq_notifier 用**惰性导入**（函数内），保持原语义以免拖慢/拖挂在未配置通知的环境；
通知失败只打印告警，绝不影响台账落盘（整段在 try 内）。

## ⚠️ 为什么还需要一份**持久化**去重集（2026-09-30）

`existing_closed_ids` 只是**本进程这一轮**读到的"上一版台账里已平的 id"。而
`sync_full_ledger.py` 有**四个调用点**（trader 周期、后端台账视图、熔断自愈、
日报备份），彼此是**不同进程**、各自读一遍旧台账 ⇒ 两个进程几乎同时跑时，
**两边都判定"这是新平仓"**，于是同一笔发两张卡片。真机实测：2026-09-29
20:34:41 与 20:34:43 两条同 payload、不同 event_id 的 XRP 卡片（相差 2 秒）。

`existing_closed_ids` 另有一个固有弱点：台账行会随行情推进被**重建**（分批腿成交
先落一条部分平仓行，余仓也平掉后又被**改写**成整笔），于是"同一个 id 的旧值"未必
能覆盖 —— 实测 2026-09-29 20:38 XRP 真正结清那一行（+39.06U）因为 id 已进"已平
集合"而**一条通知都没发**。故这里再加两条：

1. `data/close_notify_state.json` —— 持久化记下**已经通知过的台账行 id**，
   跨进程、跨重启生效（进程内的 `existing_closed_ids` 挡不住并发）；
2. **余仓还在跑的"部分平仓行"先不发**（见 `_still_open`）：等整笔生命周期走完，
   用整笔的数字发**一条**。避免"半仓金额 + 整笔金额"两张卡片互相打架。

### 读失败的方向：**宁可重复一次，不可静默漏发**

去重集损坏/不可读 ⇒ 报警并**按空集处理**（照常通知）。理由：把"读不到"当成
"全都通知过了"会让通知器**永久静音**，用户再也收不到任何平仓卡片 ——
那是比"多发一条"严重得多的静默失败（本仓红线：读不到 ≠ 没有）。

返回值为空：副作用是外部通知，与本模块纯判定部分不同，故单列一个文件。
"""
from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterable, Iterator, List, Set

# ⚠️ 双模导入：本模块既可能以裸名导入（`scripts/` 在 sys.path，交易进程里就是这种），
# 也可能以 `scripts.ledger.notify` 导入（repo 根在 sys.path，测试与后端里是这种）。
# 2026-09-30 实测教训：只写裸名导入时，测试路径下 `No module named 'local_lock'`
# 被最外层 `except` 吞掉 ⇒ **一条通知都发不出去**（静默漏发，最严重的失败方向）。
try:  # repo 根在 sys.path
    from scripts.local_lock import local_file_lock  # noqa: E402
except ImportError:  # scripts/ 在 sys.path
    try:
        from local_lock import local_file_lock  # noqa: E402
    except ImportError:  # 锁不可用 ⇒ 退化到"不锁但照常通知"，绝不静默
        local_file_lock = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[2]
#: 已通知过的台账行 id（跨进程/跨重启去重）。落 `data/` 下（`data/*.json` 已忽略）。
CLOSE_NOTIFY_STATE_FILE = ROOT / "data" / "close_notify_state.json"
#: 生产落点快照（**不随 patch 变化**）：用例拿它比对"生产文件是否被动过"。
#: ⚠️ 真实事故（2026-09-30 本轮）：本模块刚落地时，两条既有用例没重定向落点，
#: 一次 `pytest` 就把夹具 id（`new-2`/`g1`）写进了**生产**去重集 —— 与 2026-09-29
#: 事件流水被灌夹具行是同一类事故。故落点做成模块常量（用例可 patch），
#: 并把该文件登记进 `tests/__init__.py` 的写保护名单（忘 patch 也拦得住）。
_PRODUCTION_STATE_FILE = CLOSE_NOTIFY_STATE_FILE
#: 只保留最近 N 条 —— 文件不能无限长；台账本身也只有几百行。
MAX_REMEMBERED = 500


def _load_notified(path: Path | None = None) -> Set[str]:
    """读已通知集合。**缺失**⇒空集（全新环境）；**损坏/不可读**⇒报警 + 空集。

    为什么损坏也返回空集：见模块 docstring —— 静音比重复严重。
    """
    target = Path(path) if path is not None else CLOSE_NOTIFY_STATE_FILE
    try:
        raw = json.loads(target.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return set()
    except Exception as exc:
        print(f"[Ledger Sync Notify Warning] 去重集读不到（{type(exc).__name__}: {exc}）"
              f" ⇒ 本轮按『没有记录』处理：可能重复发一条，但绝不静默漏发平仓")
        return set()
    ids = raw.get("notified") if isinstance(raw, dict) else raw
    if not isinstance(ids, list):
        print("[Ledger Sync Notify Warning] 去重集结构认不出 ⇒ 按空集处理（同上）")
        return set()
    return {str(x) for x in ids if x}


def _save_notified(ids: Iterable[str], path: Path | None = None) -> None:
    """原子写回（mkstemp + fsync + os.replace）；失败只告警，绝不影响通知主流程。"""
    target = Path(path) if path is not None else CLOSE_NOTIFY_STATE_FILE
    kept: List[str] = list(dict.fromkeys(str(x) for x in ids if x))[-MAX_REMEMBERED:]
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".close-notify-", suffix=".tmp", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"notified": kept}, handle, ensure_ascii=False)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, target)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
    except Exception as exc:
        print(f"[Ledger Sync Notify Warning] 去重集写回失败（{type(exc).__name__}: {exc}）"
              f" ⇒ 下一轮可能重发同一条通知（不影响台账）")


def _notify_lock():
    """通知步骤的跨进程互斥（优先后端可重入锁，退化到本地 flock）。

    锁落在 `data/.close_notify_state.json.lock`（与既有 `.prompt_library.json.lock`
    同款命名，已被 `.gitignore` 的 `data/*.lock` 覆盖）。

    ⚠️ **锁不可用时退化到"不锁、照常通知"，绝不静默**：漏发一笔平仓是比多发一条
    严重得多的失败（本仓红线）。
    """
    if local_file_lock is None:
        return _no_lock()
    try:
        from astra_backend.file_locks import file_lock
        return file_lock(str(CLOSE_NOTIFY_STATE_FILE))
    except Exception:
        try:
            return local_file_lock(str(CLOSE_NOTIFY_STATE_FILE))
        except Exception as exc:                       # 锁文件都建不起来 ⇒ 不锁
            print(f"[Ledger Sync Notify Warning] 取不到通知互斥锁（{exc}）"
                  f" ⇒ 本轮不锁照常通知（宁可重发一条，不可漏发）")
            return _no_lock()


@contextmanager
def _no_lock() -> Iterator[None]:
    yield


def _still_open(row: dict[str, Any], open_rows: List[dict[str, Any]]) -> bool:
    """这一行是不是"**同一笔持仓还没走完**"的一部分？

    为什么需要它（2026-09-30）：OKX 的持仓历史是**按 posId 记录、随行情被改写**的 ——
    分批止盈的首批腿一成交，就会出现一条 `status: closed`、只含那一半的行；余仓
    随后被单独列为一条 `holding_*` 行。于是同一笔持仓会"先后出现两条 closed 语义"：
    · 2026-09-29 20:34 XRP：部分行（sz 5.97 / +9.32U）先出现并被通知**两次**；
    · 20:38 余仓也平掉后，行被**改写**为整笔（sz 11.95 / +39.06U），
      而它的 id 早已进了"已通知"集合 ⇒ **真正的结清一条都没发**。

    新口径：**同一笔持仓还在跑（存在同 `inst`+`side`+开仓时刻的 holding 行）时，
    先不发** —— 等它真正走完，用整笔生命周期的数字发一条。这样：
    ① 不会出现"半仓金额"与"整笔金额"两张互相打架的卡片；
    ② 余仓结清那一次一定发得出去（id 去重不会把它吃掉，因为它是**唯一**被发的那条）。
    """
    inst = row.get("inst")
    side = row.get("side")
    open_time = str(row.get("open_time") or "")
    open_px = float(row.get("open_px") or 0.0)
    for other in open_rows:
        if other.get("inst") != inst or other.get("side") != side:
            continue
        if open_time and str(other.get("open_time") or "") == open_time:
            return True
        # 退回按开仓均价判定（时刻字符串若被 OKX 改写/时区漂移仍能配上）
        try:
            other_px = float(other.get("open_px") or 0.0)
        except (TypeError, ValueError):
            continue
        if open_px > 0 and other_px > 0 and abs(other_px - open_px) <= max(1e-9, open_px * 1e-4):
            return True
    return False


def pending_notifications(*, existing_closed_ids, trades_lifecycle,
                          state_file: Path | None = None) -> List[dict[str, Any]]:
    """挑出**确实该发**的平仓行（纯判定，不发通知）—— 便于单测与自检。"""
    notified = _load_notified(state_file)
    rows = list(trades_lifecycle or [])
    open_rows = [t for t in rows if t.get("status") == "holding"]
    out: List[dict[str, Any]] = []
    seen: Set[str] = set()
    for t in rows:
        tid = str(t.get("id") or "")
        if not tid or tid in seen:
            continue
        if tid in existing_closed_ids or tid in notified:
            continue
        if t.get("status") != "closed":
            continue
        if _still_open(t, open_rows):
            continue
        seen.add(tid)
        out.append(t)
    return out


def notify_newly_closed_trades(*,
        existing_closed_ids,
        trades_lifecycle):
    """按"台账行 id 未通知过"逐条发通知，并把本轮发过的 id 持久化记下。"""
    try:
        with _notify_lock():
            fresh = pending_notifications(existing_closed_ids=existing_closed_ids,
                                          trades_lifecycle=trades_lifecycle)
            if not fresh:
                return
            from qq_notifier import notify_trade_close
            sent = []
            for t in fresh:
                _kw = dict(
                    inst=t.get("inst", "CRYPTO"),
                    pnl=float(t.get("pnl", 0.0) or 0.0),
                    stage=t.get("exit_reason", "平仓结清"),
                    exit_px=float(t.get("close_px", 0.0) or 0.0),
                    roi_pct=float(t.get("roi_pct", 0.0) or 0.0),
                    duration_str=str(t.get("duration", "")),
                )
                if t.get("venue"):
                    _kw["venue"] = str(t["venue"]).lower()
                if t.get("side") or t.get("action"):
                    _kw["side"] = str(t.get("side") or t.get("action"))
                if t.get("open_px"):
                    _kw["entry_px"] = float(t["open_px"])
                if t.get("fee") is not None:
                    _kw["fee"] = float(t["fee"])
                if t.get("net_pnl") is not None:
                    _kw["net_pnl"] = float(t["net_pnl"])
                if t.get("is_partial") is not None:
                    _kw["is_partial"] = bool(t["is_partial"])
                notify_trade_close(**_kw)
                sent.append(str(t["id"]))
            # 只有**真的发出去**的才记下（发布抛错 ⇒ 不记 ⇒ 下一轮重试，
            # 不能让一次通道故障把这一笔永久吃掉）。
            _save_notified(_load_notified() | set(sent))
    except Exception as e:
        print(f"[Ledger Sync Notify Warning] {e}")
