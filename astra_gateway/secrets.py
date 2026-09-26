"""Local encrypted secret store with explicit migration only."""
from __future__ import annotations
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Mapping

from cryptography.fernet import Fernet, InvalidToken

ROOT = Path(__file__).resolve().parents[1]
KEY_FILE = ROOT / "data" / ".astra_secret_key"
STORE_FILE = ROOT / "data" / "astra_secrets.enc"
SECRET_KEYS = {
    "OKX_API_KEY", "OKX_SECRET_KEY", "OKX_PASSPHRASE",
    "OKX_LIVE_API_KEY", "OKX_LIVE_SECRET_KEY", "OKX_LIVE_PASSPHRASE",
    "OKX_DEMO_API_KEY", "OKX_DEMO_SECRET_KEY", "OKX_DEMO_PASSPHRASE", "LLM_API_KEY",
    "ASTRA_NOTIFICATION_WEBHOOK", "ASTRA_WECHAT_WEBHOOK",
    "ASTRA_TELEGRAM_BOT_TOKEN", "ASTRA_QQ_CLIENT_SECRET",
    "ASTRA_ADMIN_TOKEN", "ASTRA_SETUP_TOKEN",
    # 多交易所凭证（US-003：三所 6 账户独立凭证加密存储）
    "BINANCE_API_KEY", "BINANCE_SECRET_KEY",
    "BINANCE_LIVE_API_KEY", "BINANCE_LIVE_SECRET_KEY",
    "BINANCE_DEMO_API_KEY", "BINANCE_DEMO_SECRET_KEY",
    "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_SECRET_KEY",
    "GATE_API_KEY", "GATE_SECRET_KEY",
    "GATE_LIVE_API_KEY", "GATE_LIVE_SECRET_KEY",
    "GATE_DEMO_API_KEY", "GATE_DEMO_SECRET_KEY",
    "GATE_TESTNET_API_KEY", "GATE_TESTNET_SECRET_KEY",
    "GATE_SANDBOX_API_KEY", "GATE_SANDBOX_SECRET_KEY",
}


def _atomic_write(path: Path, content: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=f".{path.name}-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, path)
        os.chmod(path, mode)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def _fernet(create: bool = False) -> Fernet | None:
    if not KEY_FILE.exists():
        if not create:
            return None
        _atomic_write(KEY_FILE, Fernet.generate_key())
    return Fernet(KEY_FILE.read_bytes().strip())


class SecretsStoreError(RuntimeError):
    """密文库存在但不可解读（key 丢失/损坏）。写路径遇到即拒绝，防止
    『解密失败→按空库合并→覆盖写回』静默团灭全部凭证（审计修复C·2026-09-13）。"""


_CORRUPT_REPORTED = False


def _report_corrupt(reason: str) -> None:
    global _CORRUPT_REPORTED
    if not _CORRUPT_REPORTED:
        _CORRUPT_REPORTED = True
        print(f"[secrets] CRITICAL 加密凭证库不可解读（写入路径已熔断拒写）：{reason}；"
              f"上一版密文备份可能在 {STORE_FILE}.bak", file=sys.stderr)


def _decrypt_store(strict: bool) -> dict[str, str]:
    """strict=False（读面）：损坏时告警并回退空 dict，保持既有 fail-soft 契约；
    strict=True（写面 RMW 基底）：损坏即抛 SecretsStoreError，绝不以空库为底覆盖。"""
    if not STORE_FILE.exists():
        return {}
    if not KEY_FILE.exists():
        if strict:
            raise SecretsStoreError("store 存在但 key 文件缺失，拒绝以空库覆盖")
        _report_corrupt("store 存在但 key 文件缺失")
        return {}
    try:
        fernet = Fernet(KEY_FILE.read_bytes().strip())
        payload = json.loads(fernet.decrypt(STORE_FILE.read_bytes()).decode("utf-8"))
    except (InvalidToken, OSError, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        if strict:
            raise SecretsStoreError(f"store/key 损坏无法解密: {exc}") from exc
        _report_corrupt(f"无法解密: {exc.__class__.__name__}")
        return {}
    return {key: str(value) for key, value in payload.items() if key in SECRET_KEYS and value}


def load_secrets() -> dict[str, str]:
    return _decrypt_store(strict=False)


def _backup_store_file() -> None:
    if STORE_FILE.exists():
        try:
            shutil.copy2(STORE_FILE, STORE_FILE.with_name(STORE_FILE.name + ".bak"))
            os.chmod(STORE_FILE.with_name(STORE_FILE.name + ".bak"), 0o600)
        except OSError:
            pass


def save_secrets(values: Mapping[str, str]) -> None:
    global _CORRUPT_REPORTED
    current = _decrypt_store(strict=True)  # 损坏 → 抛错拒写，现场保全
    current.update({key: value for key, value in values.items() if key in SECRET_KEYS and value})
    fernet = _fernet(True)
    assert fernet is not None
    _backup_store_file()
    ciphertext = fernet.encrypt(json.dumps(current, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    _atomic_write(STORE_FILE, ciphertext)
    _CORRUPT_REPORTED = False  # 写成功说明库恢复健康，重置告警位


def delete_secrets(keys: list[str] | tuple[str, ...] | set[str]) -> None:
    current = _decrypt_store(strict=True)  # 同上：损坏拒做 RMW
    for key in keys:
        current.pop(str(key), None)
        os.environ.pop(str(key), None)
    fernet = _fernet(True)
    assert fernet is not None
    _backup_store_file()
    ciphertext = fernet.encrypt(json.dumps(current, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    _atomic_write(STORE_FILE, ciphertext)


def inject_into_environment() -> int:
    secrets = load_secrets()
    for key, value in secrets.items():
        os.environ[key] = value
    return len(secrets)


def status() -> dict[str, object]:
    secrets = load_secrets()
    return {
        "initialized": KEY_FILE.exists() and STORE_FILE.exists(),
        "count": len(secrets),
        "keys": sorted(secrets),
        "key_mode": oct(KEY_FILE.stat().st_mode & 0o777) if KEY_FILE.exists() else "",
        "store_mode": oct(STORE_FILE.stat().st_mode & 0o777) if STORE_FILE.exists() else "",
        "source_priority": "encrypted-store-over-env",
    }
