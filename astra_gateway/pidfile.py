"""网关进程 pid 文件的**唯一定义处**与读取助手。

## 为什么要有这个模块

`data/astra_gateway.pid` 原先在 4 处各自拼路径（本包 `supervisor.py`、`worker.py`，
以及 `astra_backend/routers/gateway/gateway_ops.py`、`astra_backend/routers/system.py`），
其中两个 router 还写成

    pid = int(f.read_text().strip()) if f.exists() and f.read_text().strip().isdigit() else 0

—— **同一个文件读两次**：两次读之间文件被改写（或第二次读失败）会抛 `ValueError`/`OSError`
变成 500；`exists()` → `read_text()` 之间也是 TOCTOU 窗口。本包 `supervisor.current_pid()`
早就是正确写法（单次读 + 捕获 `(OSError, ValueError)`），router 那两处属于复制粘贴退化。

**第一百一十八刀**：把路径常量收敛到这里，并提供 `read_pid()` / `process_running()`，
让四个调用点用同一套语义。

## 语义（与原实现逐条等价，除了原先会崩的那几种情况）

`read_pid()`：

- 文件不存在 / 不可读 / 内容不是纯数字（去空白后）⇒ `0`；
- 正常情况与原 `int(text)` 结果一致；
- 差异只在于**原实现会抛错**的情形（读失败、两次读不一致、非 UTF-8 字节）现在返回 `0`
  —— 即把 500 变成"未运行"，这是修复而非行为变更。

`process_running()`：`pid` 为 0 ⇒ `False`；`os.kill(pid, 0)` 成功 ⇒ `True`；
抛 `OSError`（含无权限 `PermissionError`）⇒ `False`。**无权限也判为未运行**，
与原实现逐字一致 —— 不要"顺手改成"视为存活。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Union

ROOT = Path(__file__).resolve().parents[1]
PID_FILE = ROOT / "data" / "astra_gateway.pid"

__all__ = ["PID_FILE", "read_pid", "process_running"]


def read_pid(path: Union[str, Path, None] = None) -> int:
    """读取 pid；任何失败都返回 0（只读一次，无 TOCTOU 窗口）。"""
    target = PID_FILE if path is None else path
    try:
        text = Path(target).read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError, ValueError):
        return 0
    return int(text) if text.isdigit() else 0


def process_running(pid: int) -> bool:
    """`os.kill(pid, 0)` 探活；pid 为 0 或信号失败（含无权限）一律 False。"""
    if not pid:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False
