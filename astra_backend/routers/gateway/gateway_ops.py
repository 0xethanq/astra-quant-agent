"""网关（gateway）状态 / 投递重放 / 作业执行端点。

从 `routers/gateway.py` 按域拆出；URL/方法/处理器名/tags 一字未改。
"""
from __future__ import annotations

import subprocess
import sys
from typing import Any
from fastapi import Body, Header, HTTPException
from astra_backend.config import refresh_settings
from astra_backend.audit import record as audit_record
from astra_backend.dependencies import ROOT, SCRIPTS_DIR, require_admin_header
from astra_backend.schemas import GatewayReplayRequest
from astra_gateway import __version__ as GATEWAY_VERSION
from astra_gateway.publisher import DB_PATH as GATEWAY_DB_PATH
from astra_gateway.scheduler import scheduler_snapshot
from astra_gateway.pidfile import process_running, read_pid
from astra_gateway.store import GatewayStore

from fastapi import APIRouter

router = APIRouter(tags=["gateway"])


@router.get("/api/v1/admin/gateway")
def gateway_status(x_astra_admin_token: str | None = Header(default=None), limit: int = 50) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token)
    store = GatewayStore(GATEWAY_DB_PATH)
    pid = read_pid()
    running = process_running(pid)
    return {"version": GATEWAY_VERSION, "running": running, "pid": pid or None, "stats": store.stats(), "event_health": store.event_health(), "deliveries": store.recent(limit), "scheduler": scheduler_snapshot(store)}


@router.post("/api/v1/admin/gateway/deliveries/{delivery_id}/replay")
def replay_gateway_delivery(delivery_id: int, payload: GatewayReplayRequest, x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token)
    if payload.confirmation.strip().upper() != f"REPLAY {delivery_id}":
        raise HTTPException(status_code=400, detail=f"确认短语必须精确为：REPLAY {delivery_id}")
    store = GatewayStore(GATEWAY_DB_PATH)
    if not store.replay_dead(delivery_id):
        raise HTTPException(status_code=409, detail="仅允许重放当前处于 dead 状态的投递")
    audit_record("gateway.delivery.replay", "accepted", {"delivery_id": delivery_id})
    return {"accepted": True, "delivery_id": delivery_id, "status": "pending"}


@router.post("/api/v1/admin/gateway/jobs/{job_id}/run")
def run_gateway_job(
    job_id: str,
    payload: dict[str, Any] = Body(default={}),
    x_astra_admin_token: str | None = Header(default=None),
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> dict[str, Any]:
    refresh_settings()
    actor = require_admin_header(x_astra_admin_token, x_astra_session)
    allowed_jobs = {
        "self_improvement": {
            "script": "self_improvement_engine.py",
            "args": ["--force"],
            "timeout": 180,
            "label": "自进化复盘",
        },
        "trader": {
            "script": "ai_factor_trader.py",
            "args": [],
            "timeout": 180,
            "label": "AI量化主脑决策",
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
        "daily_briefing": {
            "script": "daily_summary_and_backup.py",
            "args": [],
            "timeout": 180,
            "label": "每日战报生成",
        },
    }
    job_cfg = allowed_jobs.get(job_id)
    if not job_cfg:
        raise HTTPException(status_code=404, detail=f"未找到网关任务：{job_id}")

    script_path = SCRIPTS_DIR / job_cfg["script"]
    if not script_path.exists():
        raise HTTPException(status_code=500, detail=f"任务脚本不存在：{script_path}")

    cmd = [sys.executable, str(script_path), *job_cfg["args"]]
    try:
        result = subprocess.run(
            cmd,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=job_cfg["timeout"],
        )
    except subprocess.TimeoutExpired:
        audit_record(
            f"gateway.job.{job_id}.run",
            "timeout",
            {"actor": actor.get("username", "admin"), "timeout": job_cfg["timeout"]},
        )
        raise HTTPException(
            status_code=504,
            detail=f"任务执行超时（限时 {job_cfg['timeout']} 秒）",
        )

    audit_record(
        f"gateway.job.{job_id}.run",
        "success" if result.returncode == 0 else "failed",
        {"actor": actor.get("username", "admin"), "returncode": result.returncode},
    )
    if result.returncode != 0:
        err_detail = (
            result.stderr[-600:].strip()
            or result.stdout[-600:].strip()
            or "未知错误"
        )
        raise HTTPException(
            status_code=502,
            detail=f"任务执行异常（退出码 {result.returncode}）：{err_detail}",
        )

    return {
        "ok": True,
        "completed": True,
        "job_id": job_id,
        "detail": f"{job_cfg['label']}已顺利完成",
        "output": result.stdout[-2000:],
    }
