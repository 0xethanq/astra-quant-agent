"""交易时段配置的持久化（`data/trading_session.json`）—— 后台写、交易引擎读。

## 为什么单独一个 store，而不是塞进 `schedule_store`

`schedule_store` 管的是"**通知与维护作业**什么时候跑"（每日简报/自进化/备份），
这份配置管的是"**实盘交易引擎允不允许跑**"。两者虽然都是"时间"，但后果不同：
前者漏跑少一条简报，后者漏判会让持仓该管没人管、或多烧 4M token。
分开落盘也让"时段闸门读的是哪份文件"在排障时一眼可见，不必先分辨
`notification_schedule.json` 里哪个键属于交易。

## 与 `schedule_store` 一致的两条既有语义（照抄，不重新发明）

1. **缺文件给默认、坏文件也给默认**：`load_*` 永不抛。默认是
   `scripts/trader/session.py::DEFAULT_SESSION`（`enabled=False`）⇒ 部署后行为逐位不变；
2. **写入必须原子**：`mkstemp` + `fsync` + `os.replace`（与 `save_schedule` 同路数）。
   半截 JSON 会让下一轮周期读到"配置损坏" ⇒ 按全天候运行 —— 方向安全，但不该发生。

## 归一化在哪

本模块**只负责读写**，不解释语义：归一化（HH:MM 规范化、星期掩码、模式回落）与判定
全部在 `scripts/trader/session.py`（纯函数）。这样"后台校验口径"与"运行时判定口径"
共用同一份实现，不会出现"页面说存进去了、引擎却按另一套理解跑"的分叉。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRADING_SESSION_FILE = ROOT / "data" / "trading_session.json"

#: 出厂默认（未启用 ⇒ 全天候运行）。与 `scripts/trader/session.py::DEFAULT_SESSION` 同源。
try:
    from scripts.trader.session import DEFAULT_SESSION
except Exception:                                    # pragma: no cover - 兜底：独立运行/极早期 import
    DEFAULT_SESSION = {
        "enabled": False,
        "mode_outside": "manage_only",
        "timezone": "Asia/Shanghai",
        "windows": [],
    }


def default_session() -> dict[str, Any]:
    """默认配置的**副本**（绝不返回内部字典本体，防调用方就地改写污染全局）。"""
    base = dict(DEFAULT_SESSION)
    base["windows"] = [dict(w) for w in DEFAULT_SESSION.get("windows") or []]
    return base


def load_trading_session() -> dict[str, Any]:
    """读配置。缺文件/坏 JSON/形状不对 ⇒ 默认（未启用）。**绝不抛异常**。

    与 `schedule_store.load_schedule` 同款浅合并：未知键保留，便于前后端版本错开时
    不丢字段（真正写回时由 `save_trading_session` 决定写什么）。
    """
    if not TRADING_SESSION_FILE.exists():
        return default_session()
    try:
        payload = json.loads(TRADING_SESSION_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_session()
    if not isinstance(payload, dict):
        return default_session()
    return {**default_session(), **payload}


def save_trading_session(session: dict[str, Any]) -> None:
    """原子写配置（`mkstemp` + `fsync` + `os.replace`）。

    ⚠️ 本函数**不做归一化也不补默认值** —— 传什么写什么（归一化由调用方用
    `session.py` 完成），这样"路由校验口径"与"运行时判定口径"共用同一份实现。
    """
    TRADING_SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".trading-session-", suffix=".tmp",
                                     dir=str(TRADING_SESSION_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(session, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, TRADING_SESSION_FILE)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
