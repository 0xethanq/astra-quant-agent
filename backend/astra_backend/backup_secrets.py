"""Encrypted per-target credentials for open-source backup adapters."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping
from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = ROOT / "data" / ".astra_backup_secret_key"
STORE_FILE = ROOT / "data" / "astra_backup_secrets.enc"
ALLOWED_FIELDS = {
    "access_key_id", "secret_access_key", "session_token", "app_key", "app_secret",
    "refresh_token", "access_token", "username", "password", "client_id", "client_secret", "sign_key",
}


def _atomic(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content); handle.flush(); os.fsync(handle.fileno())
        os.chmod(tmp, 0o600); os.replace(tmp, path); os.chmod(path, 0o600)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)


def _fernet(create: bool = False) -> Fernet | None:
    if not KEY_FILE.exists():
        if not create: return None
        _atomic(KEY_FILE, Fernet.generate_key())
    return Fernet(KEY_FILE.read_bytes().strip())


def _load_all() -> dict[str, dict[str, str]]:
    f = _fernet(False)
    if not f or not STORE_FILE.exists(): return {}
    try:
        raw = json.loads(f.decrypt(STORE_FILE.read_bytes()).decode("utf-8"))
        return {str(ref): {str(k): str(v) for k,v in values.items() if k in ALLOWED_FIELDS and v} for ref,values in raw.items() if isinstance(values,dict)}
    except (InvalidToken, OSError, json.JSONDecodeError): return {}


def save_credentials(ref: str, values: Mapping[str, Any]) -> dict[str, Any]:
    ref = str(ref).strip()
    if not ref or len(ref) > 100: raise ValueError("无效凭证引用")
    current = _load_all(); existing = current.get(ref, {})
    for key,value in values.items():
        if key not in ALLOWED_FIELDS: continue
        if value is None: continue
        if str(value): existing[key] = str(value)
    current[ref] = existing
    f = _fernet(True); assert f
    _atomic(STORE_FILE, f.encrypt(json.dumps(current, ensure_ascii=False, sort_keys=True).encode("utf-8")))
    return credential_status(ref)


def load_credentials(ref: str) -> dict[str, str]:
    return dict(_load_all().get(str(ref), {}))


def delete_credentials(ref: str) -> None:
    current = _load_all(); current.pop(str(ref), None)
    f = _fernet(True); assert f
    _atomic(STORE_FILE, f.encrypt(json.dumps(current, ensure_ascii=False, sort_keys=True).encode("utf-8")))


def credential_status(ref: str) -> dict[str, Any]:
    values = load_credentials(ref)
    return {"configured": bool(values), "fields": sorted(values), "count": len(values)}
