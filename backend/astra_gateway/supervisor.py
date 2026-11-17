"""Single-owner process supervisor for the ASTRA Gateway worker."""
from __future__ import annotations
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
from astra_gateway.pidfile import PID_FILE  # noqa: E402  (唯一定义处：pidfile.py)
LOCK_FILE = ROOT / "data" / ".astra_gateway.lock"
LOG_FILE = ROOT / "logs" / "astra_gateway_supervisor.log"
_stop = threading.Event()
_thread: threading.Thread | None = None
_owned_pid = 0


def _alive(pid: int) -> bool:
    if pid <= 0: return False
    try: os.kill(pid, 0); return True
    except OSError: return False


def _is_gateway_worker(pid: int) -> bool:
    if not _alive(pid): return False
    try:
        cmdline=(Path("/proc")/str(pid)/"cmdline").read_bytes().replace(b"\0",b" ").decode(errors="replace")
    except OSError: return False
    if "astra_gateway.worker" not in cmdline: return False
    try:
        return (Path("/proc")/str(pid)/"cwd").resolve() == ROOT.resolve()
    except OSError:
        # 跨进程 readlink /proc/pid/cwd 在非 ptrace 权限下 EACCES（沙箱继承/
        # 跨用户）——降级 cmdline-only 判定：flock 单持有者保证收养/探活语义
        # 安全（本主机单 checkout，不存在同名他仓 worker 歧义）。
        return True


def current_pid() -> int:
    try: pid=int(PID_FILE.read_text(encoding="utf-8").strip())
    except (OSError,ValueError): return 0
    if _is_gateway_worker(pid): return pid
    try: PID_FILE.unlink(missing_ok=True)
    except OSError: pass
    return 0


def _lock_held() -> bool:
    """flock 探针：锁与持锁进程同生共死，是唯一的「有没有活体 worker」真相
    （PID 文件只是缓存提示，可能漂移）。能拿到 NB 锁 = 无活体持有者。"""
    import fcntl
    if not LOCK_FILE.exists():
        return False
    try:
        probe = LOCK_FILE.open("a", encoding="utf-8")
    except OSError:
        return False
    try:
        try:
            fcntl.flock(probe, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return False
        except BlockingIOError:
            return True
    finally:
        try:
            fcntl.flock(probe, fcntl.LOCK_UN)
        except OSError:
            pass
        probe.close()


def _find_live_worker_pid() -> int:
    """扫 /proc 收养活体 worker 真身（取启动最早者，排除刚 spawn 的将死子进程）。"""
    best_pid, best_start = 0, None
    try:
        entries = os.listdir("/proc")
    except OSError:
        return 0
    for entry in entries:
        if not entry.isdigit():
            continue
        pid = int(entry)
        if pid == os.getpid() or not _is_gateway_worker(pid):
            continue
        try:
            stat_raw = (Path("/proc")/entry/"stat").read_text()
            fields = stat_raw.rsplit(")", 1)[-1].split()
            start = int(fields[19])  # starttime（jiffies）：越小越老=真身
        except (OSError, IndexError, ValueError):
            continue
        if best_start is None or start < best_start:
            best_pid, best_start = pid, start
    return best_pid


def ensure_worker() -> int:
    global _owned_pid
    pid = current_pid()
    if pid: return pid
    if _owned_pid and _is_gateway_worker(_owned_pid):
        return _owned_pid  # 亲生子已活但尚未写完自注册：不重复 spawn
    # 审计风暴修复：旧实现在 Popen 后盲写 PID 文件——注定因抢锁失败的秒退子
    # 进程把死 pid 盖进文件，活体持锁者（孤儿/前代）永远不可见 → 每 10s 重生
    # 风暴。改以 flock 为真相：锁被持有 → 收养 /proc 真身，绝不 spawn；
    # 锁空闲 → spawn，PID 文件由持锁子进程自我登记（worker.run 权威写入）。
    if _lock_held():
        live = _find_live_worker_pid()
        if live:
            try:
                PID_FILE.write_text(str(live), encoding="utf-8")
                os.chmod(PID_FILE, 0o600)
            except OSError:
                pass
            _owned_pid = 0  # 非本 supervisor 亲生子：不接管、不杀掉
            return live
        return 0  # 锁被占但真身不可辨（临界窗口）：本轮不动，下 tick 再探
    LOG_FILE.parent.mkdir(parents=True,exist_ok=True)
    with LOG_FILE.open("a",encoding="utf-8") as log:
        process=subprocess.Popen([sys.executable,"-m","astra_gateway.worker"],cwd=ROOT,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
    _owned_pid=process.pid
    return process.pid


def _run() -> None:
    while not _stop.is_set(): ensure_worker(); _stop.wait(10)


def start_supervisor() -> None:
    global _thread
    if _thread and _thread.is_alive(): return
    _stop.clear(); ensure_worker(); _thread=threading.Thread(target=_run,name="astra-gateway-supervisor",daemon=True); _thread.start()


def stop_supervisor() -> None:
    global _owned_pid
    _stop.set()
    pid=_owned_pid
    if pid and _is_gateway_worker(pid):
        try: os.kill(pid,signal.SIGTERM)
        except OSError: pass
        deadline=time.time()+8
        while _alive(pid) and time.time()<deadline: time.sleep(.1)
    if pid and not _alive(pid):
        try: PID_FILE.unlink(missing_ok=True)
        except OSError: pass
    _owned_pid=0
