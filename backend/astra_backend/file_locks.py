"""跨进程文件锁（审计③ 2026-09-13）。

多进程 RMW（读-改-写）同一个小 JSON 时，即使每次写都原子（mkstemp+replace），
「读最新→改→写最新」仍会互相覆盖丢更新（经典 lost update）。本模块提供与
scripts/evolution_shield._memory_lock、gateway worker 同路数的 flock 互斥，
锁文件与被保护文件同目录（.名字.lock），锁随内核自动释放，进程崩溃不留死锁。

用法（写者必须包整个 RMW，不能只包写那一半）：
    from astra_backend.file_locks import file_lock
    with file_lock(TARGET_JSON_PATH):
        data = load(...)
        ...merge...
        atomic_save(...)

可重入（审计 P2-6，2026-09-13）：同一线程重复进入同一目标文件**不会**死锁
（`flock` 对同一进程的不同 fd 也会互斥，嵌套调用会自锁）。层数计数归零才真正解锁，
因此「外层包装整个 RMW、内层 save 再包一次」是安全的。
"""
from __future__ import annotations

import fcntl
import os
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Dict, Iterator, Tuple

_STATE = threading.local()


def _held() -> Dict[str, int]:
    held = getattr(_STATE, "held", None)
    if held is None:
        held = {}
        _STATE.held = held
    return held


def _lock_path(target_file: str | os.PathLike[str]) -> Tuple[Path, str]:
    p = Path(str(target_file))
    lock_path = p.with_name("." + p.name + ".lock")
    return lock_path, str(lock_path)


@contextmanager
def file_lock(target_file: str | os.PathLike[str]) -> Iterator[None]:
    """对 target_file 的 RMW 取进程间互斥锁（阻塞式、同线程可重入）。"""
    lock_path, key = _lock_path(target_file)
    held = _held()
    if held.get(key):
        # 已持有：只加层数，不再 flock（否则同一进程二次 flock 会阻塞自己）
        held[key] += 1
        try:
            yield
        finally:
            held[key] -= 1
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
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


def lock_is_held(target_file: str | os.PathLike[str]) -> bool:
    """当前线程是否已持有该目标文件的锁（测试与断言用）。"""
    _, key = _lock_path(target_file)
    return bool(_held().get(key))
