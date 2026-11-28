"""Asynchronous background job runner for control-plane maintenance & trading jobs."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from astra_backend.audit import record as audit_record
from astra_backend.dependencies import ROOT, SCRIPTS_DIR

_BJ = timezone(timedelta(hours=8))
_MAX_RUN_HISTORY = 30
_LOCK = threading.Lock()
_RUNS: list[dict[str, Any]] = []

ALLOWED_JOBS: dict[str, dict[str, Any]] = {
    "trader": {
        "script": "ai_factor_trader.py",
        "args": [],
        "timeout": 240,
        "label": "AI 量化主脑决策",
        "env": {"ASTRA_SESSION_FORCE": "1"},
    },
    "factor_library": {
        "script": "factor_library.py",
        "args": [],
        "timeout": 120,
        "label": "多因子矩阵计算",
    },
    "news": {
        "script": "news_sentiment_harvester.py",
        "args": [],
        "timeout": 120,
        "label": "全网情绪抓取",
    },
    "self_improvement": {
        "script": "self_improvement_engine.py",
        "args": ["--force"],
        "timeout": 240,
        "label": "自进化深度复盘",
    },
    "daily_briefing": {
        "script": "daily_summary_and_backup.py",
        "args": [],
        "timeout": 180,
        "label": "每日战报生成",
    },
}


class UnknownJobError(KeyError):
    """Requested job id does not exist."""


class JobAlreadyRunningError(RuntimeError):
    """Same job id is already executing."""


def _now_bj() -> str:
    return datetime.now(_BJ).strftime("%Y-%m-%d %H:%M:%S")


def _default_subprocess_runner(
    cmd: list[str],
    *,
    timeout: int,
    env: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=timeout,
        env=env,
    )


def _find_running(job_id: str) -> dict[str, Any] | None:
    for item in _RUNS:
        if item["job_id"] == job_id and item["status"] == "running":
            return dict(item)
    return None


def list_job_runs(limit: int = 20) -> list[dict[str, Any]]:
    capped = max(1, min(int(limit or 20), _MAX_RUN_HISTORY))
    with _LOCK:
        return [dict(item) for item in _RUNS[:capped]]


def get_job_run(run_id: str) -> dict[str, Any] | None:
    with _LOCK:
        for item in _RUNS:
            if item["run_id"] == run_id:
                return dict(item)
    return None


def job_catalog() -> list[dict[str, Any]]:
    with _LOCK:
        catalog: list[dict[str, Any]] = []
        for job_id, cfg in ALLOWED_JOBS.items():
            latest = next((dict(r) for r in _RUNS if r["job_id"] == job_id), None)
            catalog.append({
                "id": job_id,
                "label": cfg["label"],
                "script": cfg["script"],
                "timeout": cfg["timeout"],
                "running": bool(latest and latest["status"] == "running"),
                "latest_run": latest,
            })
        return catalog


def trigger_job_async(
    job_id: str,
    *,
    actor: str = "admin",
    runner: Callable[..., subprocess.CompletedProcess[str]] | None = None,
) -> dict[str, Any]:
    cfg = ALLOWED_JOBS.get(job_id)
    if not cfg:
        raise UnknownJobError(f"未找到网关任务：{job_id}")

    script_path = SCRIPTS_DIR / cfg["script"]
    if not script_path.is_file():
        raise FileNotFoundError(f"任务脚本不存在：{script_path}")

    # Snapshot environment before spawning thread so isolated test env overrides stay deterministic.
    spawn_env = {**os.environ, **(cfg.get("env") or {})}
    cmd = [sys.executable, str(script_path), *(cfg.get("args") or [])]
    exec_fn = runner or _default_subprocess_runner

    with _LOCK:
        active = _find_running(job_id)
        if active:
            raise JobAlreadyRunningError(f"任务「{cfg['label']}」正在运行中（run_id={active['run_id']}）")

        run_id = f"run_{uuid.uuid4().hex[:10]}"
        record: dict[str, Any] = {
            "run_id": run_id,
            "job_id": job_id,
            "label": cfg["label"],
            "actor": actor,
            "status": "running",
            "started_at": _now_bj(),
            "finished_at": None,
            "duration_ms": None,
            "returncode": None,
            "output_tail": "",
            "error": "",
        }
        _RUNS.insert(0, record)
        del _RUNS[_MAX_RUN_HISTORY:]

    def _worker() -> None:
        t0 = time.monotonic()
        status = "failed"
        rc: int | None = None
        output_tail = ""
        error_msg = ""
        try:
            cp = exec_fn(cmd, timeout=int(cfg["timeout"]), env=spawn_env)
            rc = int(cp.returncode)
            combined = "\n".join(part for part in ((cp.stdout or "").strip(), (cp.stderr or "").strip()) if part)
            output_tail = combined[-2500:]
            if rc == 0:
                status = "success"
            else:
                status = "failed"
                error_msg = f"退出码 {rc}"
        except subprocess.TimeoutExpired:
            status = "timeout"
            error_msg = f"执行超时（限时 {cfg['timeout']} 秒）"
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            error_msg = str(exc)[:300]

        elapsed_ms = max(0, int((time.monotonic() - t0) * 1000))
        with _LOCK:
            for entry in _RUNS:
                if entry["run_id"] == run_id:
                    entry["status"] = status
                    entry["finished_at"] = _now_bj()
                    entry["duration_ms"] = max(0, int((time.monotonic() - t0) * 1000))
                    elapsed_ms = entry["duration_ms"]
                    entry["returncode"] = rc
                    entry["output_tail"] = output_tail
                    entry["error"] = error_msg
                    break

        try:
            audit_record(
                f"control_plane.job.{job_id}",
                status,
                {"actor": actor, "run_id": run_id, "duration_ms": elapsed_ms, "returncode": rc},
            )
        except Exception:
            pass

    thread = threading.Thread(target=_worker, name=f"astra-job-{job_id}", daemon=True)
    thread.start()
    return dict(record)
