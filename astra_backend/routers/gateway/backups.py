"""备份目标/凭据/作业/归档（含上传下载与恢复）端点。

从 `routers/gateway.py` 按域拆出；URL/方法/处理器名/tags 一字未改。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from fastapi import File, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from astra_backend.config import refresh_settings
from astra_backend.audit import record as audit_record
from astra_backend.dependencies import ROOT, SCRIPTS_DIR, BACKUP_LOG_FILE, require_admin_header, require_superadmin
from astra_backend.schemas import BackupRequest, BackupRestoreRequest, SimpleBackupUpdateRequest, BackupCredentialUpdateRequest, BackupJobCreateRequest, BackupJobUpdateRequest, BackupJobRunRequest, BackupJobImportRequest, BackupVerifyRequest, BackupMethodsUpdate
from astra_backend.backup_store import create_job as create_backup_job, delete_job as delete_backup_job, export_job as export_backup_job, get_job as get_backup_job, import_job as import_backup_job, list_jobs as list_backup_jobs, load_backup_methods, save_backup_methods, update_job as update_backup_job, validate_backup_job
from astra_backend.backup_secrets import credential_status as backup_credential_status, save_credentials as save_backup_credentials
from astra_backend.routers.gateway._shared import _get_root

from fastapi import APIRouter

router = APIRouter(tags=["gateway"])


@router.get("/api/v1/admin/backups/simple")
def simple_backup_config(x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token)
    jobs = list_backup_jobs()
    job = next((x for x in jobs if x.get("id") == "nightly-default"), jobs[0] if jobs else None)
    if not job:
        raise HTTPException(status_code=404, detail="主灾备任务不存在")
    target = next((x for x in job.get("targets", []) if x.get("enabled")), None)
    if not target:
        target = next((x for x in job.get("targets", []) if x.get("type") == "local"), None)
    target_type = str((target or {}).get("type") or "local")
    auth_mode = str((target or {}).get("auth_mode") or "")
    legacy_bypy = target_type == "baidu" and auth_mode != "oauth"
    destination = "baidu_oauth" if target_type == "baidu" and not legacy_bypy else target_type if target_type in {"local","s3","oss","webdav"} else "local"
    # 审计①#5(2026-09-13)：configured 曾读 target.credential_status——该键只在
    # GET /backup-jobs 处理器里读时注入（:683），list_jobs() 本体不带 → 本端点
    # 恒判「未配置」。现按同款函数现算（已修系列的漏网兄弟端点）。
    if target:
        target = dict(target)
        target.setdefault("credential_status",
                          backup_credential_status(str(target.get("credential_ref") or "")))
    validation = validate_backup_job(job)
    latest = None
    manifests_dir = _get_root() / "backups" / "manifests"
    for path in sorted(manifests_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:30] if manifests_dir.exists() else []:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if item.get("job_id") == job["id"]:
                latest = item
                break
        except (OSError, json.JSONDecodeError):
            pass
    return {"job_id": job["id"], "target": target or {}, "enabled": job["enabled"], "schedule_time": job["schedule_times"][0], "destination": destination, "retention": int((target or {}).get("retention") or 3), "legacy_bypy": legacy_bypy, "migration_note": "当前为旧版 ByPy 配置，请选择新的保存位置后保存完成迁移" if legacy_bypy else "", "configured": bool((target or {}).get("credential_status",{}).get("configured")) if target else destination=="local", "validation": validation, "latest": latest, "advanced_preserved": True}


@router.put("/api/v1/admin/backups/simple")
def update_simple_backup(payload: SimpleBackupUpdateRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    jobs = list_backup_jobs()
    job = next((x for x in jobs if x.get("id") == "nightly-default"), jobs[0] if jobs else None)
    if not job:
        raise HTTPException(status_code=404, detail="主灾备任务不存在")
    wanted_type = "baidu" if payload.destination == "baidu_oauth" else payload.destination
    existing = next((x for x in job.get("targets", []) if x.get("type") == wanted_type and (wanted_type != "baidu" or x.get("auth_mode") == "oauth")), None)
    if not existing:
        target_id = f"{wanted_type}-{__import__('uuid').uuid4().hex[:10]}"
        labels = {"local": "本地归档", "s3": "S3存储", "oss": "阿里云OSS", "webdav": "WebDAV/OpenList", "baidu": "百度网盘"}
        existing = {
            "id": target_id,
            "type": wanted_type,
            "label": labels.get(wanted_type, wanted_type.upper()),
            "credential_ref": f"backup:{target_id}",
            "enabled": False,
            "remote_path": "ASTRA_Backups",
            "path": "backups/local",
            "retention": 3,
            "retries": 3,
            "auth_mode": "oauth" if wanted_type == "baidu" else "native",
        }
        job.setdefault("targets", []).append(existing)
    for target in job.get("targets", []):
        target["enabled"] = (target is existing)
    existing["retention"] = payload.retention if wanted_type == "local" else 0
    if wanted_type in {"s3", "oss", "webdav"}:
        existing["endpoint"] = payload.endpoint.strip()
    if wanted_type in {"s3", "oss"}:
        existing["bucket"] = payload.bucket.strip()
    if wanted_type == "baidu":
        existing["auth_mode"] = "oauth"
    if payload.credentials:
        save_backup_credentials(existing["credential_ref"], payload.credentials)
    job["enabled"] = payload.enabled
    job["schedule_times"] = [payload.schedule_time]
    try:
        saved = update_backup_job(job["id"], job)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_record("backup.simple.update", "success", {"actor": actor["username"], "destination": payload.destination, "enabled": payload.enabled})
    return {"saved": True, "job": saved}


@router.post("/api/v1/admin/backups/simple/test")
def test_simple_backup(payload: SimpleBackupUpdateRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    require_superadmin(x_astra_session)
    if payload.destination == "local":
        directory = (_get_root() / "backups" / "local").resolve()
        if not directory.is_relative_to((_get_root() / "backups").resolve()):
            raise HTTPException(status_code=400, detail="本地灾备目录无效：必须位于 backups/ 目录下")
        try:
            directory.mkdir(parents=True, exist_ok=True)
            test_file = directory / ".test_write.tmp"
            test_file.write_text("ok", encoding="utf-8")
            test_file.unlink(missing_ok=True)
        except OSError as exc:
            raise HTTPException(status_code=400, detail=f"本地灾备目录不可写：{exc}")
        return {"status": "ready", "sent": False, "detail": "本地目录可写；未生成或上传归档"}

    wanted_type = "baidu" if payload.destination == "baidu_oauth" else payload.destination
    req_map = {
        "s3": {"access_key_id", "secret_access_key"},
        "oss": {"access_key_id", "secret_access_key"},
        "webdav": set(),
        "baidu": {"app_key", "app_secret", "refresh_token"},
    }
    if wanted_type not in req_map:
        raise HTTPException(status_code=400, detail=f"不支持的灾备目标：{payload.destination}")

    required = req_map[wanted_type]
    jobs = list_backup_jobs()
    job = next((x for x in jobs if x.get("id") == "nightly-default"), jobs[0] if jobs else None)
    existing = next((x for x in (job.get("targets", []) if job else []) if x.get("type") == wanted_type and (wanted_type != "baidu" or x.get("auth_mode") == "oauth")), None)
    saved_creds = {}
    if existing and existing.get("credential_ref"):
        try:
            from astra_backend.backup_secrets import load_credentials
            saved_creds = load_credentials(existing["credential_ref"])
        except Exception:
            saved_creds = {}

    target = {
        "type": wanted_type,
        "endpoint": (payload.endpoint or (existing.get("endpoint", "") if existing else "")).strip(),
        "bucket": (payload.bucket or (existing.get("bucket", "") if existing else "")).strip(),
        "auth_mode": "oauth" if wanted_type == "baidu" else "native",
    }
    combined_creds = {**saved_creds, **{k: v for k, v in (payload.credentials or {}).items() if str(v).strip()}}
    missing = sorted(key for key in required if not str(combined_creds.get(key) or "").strip())
    if missing:
        raise HTTPException(status_code=400, detail=f"连接信息不完整：{', '.join(missing)}")

    if wanted_type in {"s3", "oss", "webdav"}:
        if not target["endpoint"]:
            raise HTTPException(status_code=400, detail=f"{wanted_type.upper()} Endpoint 不能为空")
        try:
            from astra_backend.net_security import validate_outbound_url
            target["endpoint"] = validate_outbound_url(target["endpoint"])
        except (ValueError, Exception) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if wanted_type in {"s3", "oss"} and not target["bucket"]:
        raise HTTPException(status_code=400, detail=f"{wanted_type.upper()} Bucket 不能为空")

    return {"status": "ready", "sent": False, "detail": "配置格式与目标地址校验通过；未上传任何文件", "destination": payload.destination}


@router.get("/api/v1/admin/backup-target-types")
def backup_target_types(x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token)
    return {"target_types": [
        {"type":"local","label":"本地归档","auth":"none","description":"项目 backups/ 内滚动保留"},
        {"type":"baidu","label":"百度网盘","auth":"oauth","description":"仅支持官方 OAuth，新配置不再提供 ByPy"},
        {"type":"s3","label":"S3 兼容存储","auth":"access-key","description":"AWS S3、R2、MinIO、COS 等 S3 兼容端点"},
        {"type":"oss","label":"阿里云 OSS","auth":"access-key","description":"官方 oss2 SDK"},
        {"type":"webdav","label":"WebDAV / NAS / OpenList","auth":"basic","description":"标准 WebDAV PUT/MKCOL"},
        {"type":"aliyundrive","label":"阿里云盘","auth":"webdav-or-oauth","description":"推荐开放平台或 OpenList WebDAV 桥接"},
        {"type":"quark","label":"夸克网盘（实验性）","auth":"webdav-or-experimental-oauth","description":"官方开放平台仍在内测，推荐 OpenList WebDAV 桥接"},
    ]}


@router.put("/api/v1/admin/backup-credentials")
def update_backup_credentials(payload: BackupCredentialUpdateRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        status = save_backup_credentials(payload.credential_ref, payload.credentials)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_record("backup.credentials.update", "success", {"actor": actor["username"], "credential_ref": payload.credential_ref, "fields": status["fields"]})
    return {"saved": True, "credential_ref": payload.credential_ref, "status": status}


@router.get("/api/v1/admin/backup-jobs")
def backup_jobs_api(x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token)
    manifests_dir = _get_root() / "backups" / "manifests"
    manifests = []
    for path in sorted(manifests_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:50] if manifests_dir.exists() else []:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            item["manifest_file"] = path.name
            manifests.append(item)
        except (OSError, json.JSONDecodeError):
            pass
    jobs = list_backup_jobs()
    for job in jobs:
        for target in job.get("targets", []):
            target["credential_status"] = backup_credential_status(str(target.get("credential_ref") or ""))
    return {"jobs": jobs, "validations": {job["id"]: validate_backup_job(job) for job in jobs}, "recent_manifests": manifests, "timezone": "Asia/Shanghai", "limits": {"maximum_jobs": 12}}


@router.post("/api/v1/admin/backup-jobs")
def create_backup_job_api(payload: BackupJobCreateRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        job = create_backup_job(payload.name, payload.source_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_record("backup.job.create", "success", {"actor": actor["username"], "job_id": job["id"]})
    return {"job": job}


@router.put("/api/v1/admin/backup-jobs/{job_id}")
def update_backup_job_api(job_id: str, payload: BackupJobUpdateRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        job = update_backup_job(job_id, payload.job)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_record("backup.job.update", "success", {"actor": actor["username"], "job_id": job_id, "enabled": job["enabled"]})
    return {"job": job, "validation": validate_backup_job(job)}


@router.delete("/api/v1/admin/backup-jobs/{job_id}")
def delete_backup_job_api(job_id: str, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        delete_backup_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_record("backup.job.delete", "success", {"actor": actor["username"], "job_id": job_id})
    return {"deleted": True}


@router.post("/api/v1/admin/backup-jobs/validate")
def validate_backup_job_api(payload: BackupJobUpdateRequest, x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token)
    return validate_backup_job(payload.job)


@router.post("/api/v1/admin/backup-jobs/{job_id}/run")
def run_backup_job_api(job_id: str, payload: BackupJobRunRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    if payload.confirmation.strip().upper() != f"BACKUP {job_id}".upper():
        raise HTTPException(status_code=400, detail=f"确认短语必须精确为：BACKUP {job_id}")
    try:
        get_backup_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    script = SCRIPTS_DIR / "nightly_backup_and_clean.py"
    result = subprocess.run([sys.executable, str(script), "--job-id", job_id], cwd=ROOT, text=True, capture_output=True, timeout=1800)
    BACKUP_LOG_FILE.parent.mkdir(exist_ok=True)
    BACKUP_LOG_FILE.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    audit_record("backup.job.run", "success" if result.returncode == 0 else "failed", {"actor": actor["username"], "job_id": job_id, "returncode": result.returncode})
    if result.returncode:
        raise HTTPException(status_code=502, detail=f"灾备任务失败：{result.stderr[-800:] or result.stdout[-800:]}")
    return {"completed": True, "output": result.stdout[-4000:]}


@router.get("/api/v1/admin/backup-jobs/{job_id}/export")
def export_backup_job_api(job_id: str, x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    require_admin_header(x_astra_admin_token)
    try:
        return export_backup_job(job_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/api/v1/admin/backup-jobs/import")
def import_backup_job_api(payload: BackupJobImportRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    try:
        job = import_backup_job(payload.payload, payload.name_override)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    audit_record("backup.job.import", "success", {"actor": actor["username"], "job_id": job["id"]})
    return {"job": job}


@router.post("/api/v1/admin/backup-jobs/verify")
def verify_backup_archive_api(payload: BackupVerifyRequest, x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    actor = require_superadmin(x_astra_session)
    candidate = (_get_root() / payload.archive_path).resolve()
    if not candidate.is_relative_to((_get_root() / "backups").resolve()):
        raise HTTPException(status_code=400, detail="只能验证项目 backups/ 目录内的归档")
    from scripts.backup_runtime import verify_archive
    try:
        result = verify_archive(candidate, payload.expected_sha256, payload.key_env)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit_record("backup.archive.verify", "success", {"actor": actor["username"], "archive": str(candidate.relative_to(_get_root())), "members": result["members"]})
    return result


@router.put("/api/v1/admin/backups/methods")
def update_backup_methods(payload: BackupMethodsUpdate, x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token)
    methods = {
        "baidu": {"enabled": payload.baidu_enabled, "retention": 0},
        "local": {"enabled": payload.local_enabled, "retention": payload.local_retention},
        "sqlite": {"enabled": payload.sqlite_enabled, "retention": payload.sqlite_retention},
    }
    if not any(item["enabled"] for item in methods.values()):
        raise HTTPException(status_code=400, detail="至少启用一种灾备方式")
    save_backup_methods(methods)
    audit_record("backup.methods.update", "success", {key: value["enabled"] for key, value in methods.items()})
    return {"saved": True, "methods": load_backup_methods()}


@router.get("/api/v1/admin/backups")
def backup_status(x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token)
    backups_dir = _get_root() / "backups"
    archive_paths = list(backups_dir.glob("*.tar.gz")) + list((backups_dir / "local").glob("*.tar.gz")) if backups_dir.exists() else []
    local_archives = [{"name": str(item.relative_to(backups_dir)), "bytes": item.stat().st_size, "mtime": int(item.stat().st_mtime)} for item in archive_paths if item.is_file()]
    sqlite_files = list((backups_dir / "sqlite").glob("*.db")) + list((backups_dir / "sqlite").glob("*/*.db")) if (backups_dir / "sqlite").exists() else []
    sqlite_snapshots = [{"name": str(item.relative_to(backups_dir / "sqlite")), "bytes": item.stat().st_size, "mtime": int(item.stat().st_mtime)} for item in sqlite_files if item.is_file()]
    return {
        "schedule": "每天北京时间 02:00，由 Gateway Scheduler 执行全部已启用灾备方式",
        "script": str(SCRIPTS_DIR / "nightly_backup_and_clean.py"),
        "methods": load_backup_methods(),
        "jobs": list_backup_jobs(),
        "local_archives": sorted(local_archives, key=lambda item: item["mtime"], reverse=True),
        "sqlite_snapshots": sorted(sqlite_snapshots, key=lambda item: item["mtime"], reverse=True),
        "last_log": BACKUP_LOG_FILE.read_text(encoding="utf-8")[-4000:] if BACKUP_LOG_FILE.exists() else "尚无后台手动灾备日志",
    }


@router.post("/api/v1/admin/backups/run")
def run_backup(payload: BackupRequest, x_astra_admin_token: str | None = Header(default=None)) -> dict[str, Any]:
    refresh_settings()
    require_admin_header(x_astra_admin_token)
    if payload.confirmation.strip().upper() != "BACKUP ASTRA":
        raise HTTPException(status_code=400, detail="确认短语必须精确为：BACKUP ASTRA")
    script = SCRIPTS_DIR / "nightly_backup_and_clean.py"
    result = subprocess.run([sys.executable, str(script)], cwd=ROOT, text=True, capture_output=True, timeout=600)
    BACKUP_LOG_FILE.parent.mkdir(exist_ok=True)
    BACKUP_LOG_FILE.write_text(result.stdout + "\n" + result.stderr, encoding="utf-8")
    if result.returncode:
        audit_record("backup.run", "failed", {"returncode": result.returncode})
        raise HTTPException(status_code=502, detail=f"灾备任务失败：{result.stderr[-800:] or result.stdout[-800:]}")
    audit_record("backup.run", "success", {})
    return {"completed": True, "output": result.stdout[-2500:]}


@router.get("/api/v1/admin/backups/download/{filename:path}")
def download_backup_archive(
    filename: str,
    token: str | None = Query(default=None),
    session: str | None = Query(default=None),
    x_astra_admin_token: str | None = Header(default=None),
    x_astra_session: str | None = Header(default=None, alias="X-Astra-Session"),
) -> FileResponse:
    refresh_settings()
    effective_session = (
        (x_astra_session if isinstance(x_astra_session, str) else None)
        or (token if isinstance(token, str) else None)
        or (session if isinstance(session, str) else None)
    )
    effective_admin_token = x_astra_admin_token if isinstance(x_astra_admin_token, str) else None
    require_admin_header(effective_admin_token, effective_session)
    if ".." in Path(filename).parts:
        raise HTTPException(status_code=400, detail="非法文件路径：不能包含 ..")
    clean_name = Path(filename).name
    backups_dir = _get_root() / "backups"
    candidate = backups_dir / clean_name
    if not candidate.exists():
        candidate = backups_dir / "local" / clean_name
    if not candidate.exists():
        rel_candidate = (backups_dir / filename).resolve()
        if rel_candidate.is_relative_to(backups_dir.resolve()) and rel_candidate.exists():
            candidate = rel_candidate
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="备份文件不存在或已清理")
    if not candidate.resolve().is_relative_to(backups_dir.resolve()):
        raise HTTPException(status_code=400, detail="非法文件路径")
    audit_record("backup.download", "success", {"filename": clean_name})
    return FileResponse(
        path=str(candidate),
        media_type="application/gzip",
        filename=clean_name,
        headers={"Content-Disposition": f'attachment; filename="{clean_name}"'}
    )


@router.post("/api/v1/admin/backups/upload")
async def upload_backup_archive(file: UploadFile = File(...), x_astra_admin_token: str | None = Header(default=None), x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    refresh_settings()
    require_superadmin(x_astra_session)
    if not file.filename or not (file.filename.endswith(".tar.gz") or file.filename.endswith(".tgz")):
        raise HTTPException(status_code=400, detail="仅支持上传 .tar.gz 或 .tgz 格式备份包")
    clean_name = Path(file.filename).name
    if not clean_name or clean_name in {".", ".."} or ".." in clean_name:
        raise HTTPException(status_code=400, detail="非法文件名")
    target_dir = _get_root() / "backups" / "local"
    target_dir.mkdir(parents=True, exist_ok=True)
    dest_path = target_dir / clean_name
    if not dest_path.resolve().is_relative_to(target_dir.resolve()):
        raise HTTPException(status_code=400, detail="非法文件上传路径")
    content = await file.read()
    dest_path.write_bytes(content)
    audit_record("backup.upload", "success", {"filename": clean_name, "bytes": len(content)})
    return {"uploaded": True, "filename": clean_name, "bytes": len(content), "path": str(dest_path.relative_to(_get_root()))}


@router.post("/api/v1/admin/backups/restore")
def restore_backup_archive(payload: BackupRestoreRequest, x_astra_admin_token: str | None = Header(default=None), x_astra_session: str | None = Header(default=None, alias="X-Astra-Session")) -> dict[str, Any]:
    refresh_settings()
    require_superadmin(x_astra_session)
    if payload.confirmation.strip().upper() != "RESTORE ASTRA":
        raise HTTPException(status_code=400, detail="确认短语必须精确为：RESTORE ASTRA")
    if ".." in Path(payload.archive_name).parts:
        raise HTTPException(status_code=400, detail="非法归档文件名：不能包含 ..")
    clean_name = Path(payload.archive_name).name
    backups_dir = _get_root() / "backups"
    candidate = backups_dir / clean_name
    if not candidate.exists():
        candidate = backups_dir / "local" / clean_name
    if not candidate.exists():
        rel_candidate = (backups_dir / payload.archive_name).resolve()
        if rel_candidate.is_relative_to(backups_dir.resolve()) and rel_candidate.is_file():
            candidate = rel_candidate
    if not candidate.exists() or not candidate.is_file():
        raise HTTPException(status_code=404, detail="指定的备份归档文件不存在")
    if not candidate.resolve().is_relative_to(backups_dir.resolve()):
        raise HTTPException(status_code=400, detail="指定的备份文件路径不合法")

    is_encrypted = candidate.name.endswith(".aes256")
    temp_decrypted: Path | None = None
    actual_tar = candidate
    if is_encrypted:
        key_env = getattr(payload, "key_env", "") or "ASTRA_BACKUP_ENCRYPTION_KEY"
        if not key_env or not os.getenv(key_env):
            raise HTTPException(status_code=400, detail=f"恢复加密归档需要有效的加密密钥环境变量 ({key_env})")
        from scripts.backup_runtime import decrypt_archive
        fd, temp_name = tempfile.mkstemp(prefix="astra-restore-", suffix=".tar.gz", dir=backups_dir)
        os.close(fd)
        temp_decrypted = Path(temp_name)
        try:
            actual_tar = decrypt_archive(candidate, key_env, temp_decrypted)
        except Exception as exc:
            temp_decrypted.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail=f"解密归档失败：{exc}") from exc

    import tarfile
    restored_files = []
    try:
        try:
            tar = tarfile.open(actual_tar, "r:gz")
        except (tarfile.TarError, OSError, EOFError) as exc:
            raise HTTPException(status_code=400, detail=f"无效或损坏的归档文件：{exc}") from exc

        with tar:
            members = tar.getmembers()
            for member in members:
                member_path = Path(member.name)
                if member.name.startswith("/") or member_path.is_absolute() or os.path.isabs(member.name):
                    raise HTTPException(status_code=400, detail=f"非法不安全归档路径 (绝对路径): {member.name}")
                if ".." in member_path.parts or ".." in member.name.replace("\\", "/").split("/"):
                    raise HTTPException(status_code=400, detail=f"非法不安全归档路径 (路径逃逸): {member.name}")
                dest_path = (_get_root() / member.name).resolve()
                if not dest_path.is_relative_to(_get_root().resolve()):
                    raise HTTPException(status_code=400, detail=f"非法越界归档路径: {member.name}")
                if member.issym() or member.islnk():
                    link_target = member.linkname
                    if os.path.isabs(link_target) or ".." in Path(link_target).parts:
                        raise HTTPException(status_code=400, detail=f"非法不安全符号链接: {member.name} -> {link_target}")
                    resolved_link = (_get_root() / Path(member.name).parent / link_target).resolve()
                    if not resolved_link.is_relative_to(_get_root().resolve()):
                        raise HTTPException(status_code=400, detail=f"符号链接指向项目外部: {member.name} -> {link_target}")
                if member.isdev() or member.ischr() or member.isblk() or member.isfifo():
                    raise HTTPException(status_code=400, detail=f"归档包含特殊设备节点: {member.name}")

            extract_kwargs = {"filter": "data"} if hasattr(tarfile, "data_filter") else {}
            for member in members:
                tar.extract(member, path=_get_root(), **extract_kwargs)
                restored_files.append(member.name)
    finally:
        if temp_decrypted and temp_decrypted.exists():
            temp_decrypted.unlink(missing_ok=True)

    audit_record("backup.restore", "success", {"filename": clean_name, "files_count": len(restored_files)})
    return {"restored": True, "filename": clean_name, "restored_count": len(restored_files), "sample_files": restored_files[:10]}
