"""`file_lock` 的**本地兜底**实现（结构优化阶段 4·B3 第四十八刀）。

## 为什么需要它

`scripts/prompt_library.py` 的 `_library_lock()` 与
`scripts/instrument_pool.py` 的 `_pool_lock()` 都写成同一个形状：

```python
try:
    from astra_backend.file_locks import file_lock
    return file_lock(TARGET_FILE)
except Exception:
    # …… 手写一个 contextmanager 做本地 flock ……
```

两处手写的那段**逐字相同**（只有目标文件名不同），且**各自都不具备可重入性**
（见下）。本模块把它收成一份，两个调用方共用。

## ⚠️ 它修掉的是一个**潜伏死锁**

后端 `astra_backend/file_locks.py::file_lock` 是**可重入**的（审计 P2-6：
「同一线程重复进入同一目标文件不会死锁」）。而两处手写兜底都是**裸 flock**、
**不可重入**。

调用方**确实存在嵌套**：

```python
# scripts/instrument_pool.py
def mutate_instruments(mutator):
    with _pool_lock():          # ← 外层
        ...
        save_instruments(...)   # ← 内部又 with _pool_lock()
```

正常路径下 `file_lock` 用层数计数兜住，嵌套**不会**自锁；
但一旦走到兜底分支，**同线程二次 `flock` 会阻塞自己** —— 该脚本会**永久挂死**。

**如实记录：该兜底分支在本仓当前是"不可达"的**（`astra_backend.file_locks`
只依赖标准库，且两个脚本在本仓都由 `astra_backend` 侧导入）。
所以这是一个**潜伏**缺陷，不是正在发生的线上故障。
但把兜底改成可重入是**纯行为收窄**：只在"本来会挂死"的路径上改为"正常返回"，
正常路径一行不变。故按「发现 bug 直接修」处理。

## 实现与后端同路数

层数计数放在 `threading.local()` 上，归零才真正 `flock`/解锁 ——
与 `astra_backend/file_locks.py` 的 `_STATE` 机制**逐条对应**。
本模块**只依赖标准库**，故可被"脱离 `astra_backend`"的脚本安全导入。
"""

from __future__ import annotations

import fcntl
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator

__all__ = ["local_file_lock", "lock_is_held"]

_STATE = threading.local()


def _held() -> Dict[str, int]:
    held = getattr(_STATE, "held", None)
    if held is None:
        held = {}
        _STATE.held = held
    return held


def _lock_path(target_file) -> str:
    p = Path(str(target_file))
    return str(p.with_name("." + p.name + ".lock"))


@contextmanager
def local_file_lock(target_file) -> Iterator[None]:
    """对 `target_file` 的 RMW 取**进程内 + 跨进程**互斥（阻塞式、同线程可重入）。

    ⚠️ 语义必须与 `astra_backend.file_locks.file_lock` 保持一致 ——
    调用方在两者之间无条件切换（后者 import 失败就退到本函数），
    任何语义差异都会让"退化路径"变成另一种行为。
    """
    key = _lock_path(target_file)
    held = _held()
    if held.get(key):
        # 已持有：只加层数，不再 flock（否则同一进程二次 flock 会阻塞自己）
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    lock_dir = os.path.dirname(key)
    if lock_dir:
        os.makedirs(lock_dir, exist_ok=True)
    fd = os.open(key, os.O_RDWR | os.O_CREAT, 0o600)
    held[key] = 1
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        held.pop(key, None)
        os.close(fd)


def lock_is_held(target_file) -> bool:
    """当前线程是否已持有该目标文件的锁（测试与断言用）。"""
    return bool(_held().get(_lock_path(target_file)))
