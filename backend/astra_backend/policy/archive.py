"""归档索引读写、归档文件解析与删除。

`load_archive_index` 在无索引或需重建时调用 `_rebuild_index_from_archives` ——
后者被 tests/core/test_beijing_time_producers.py 的 isolated() 按 AST 钉在门面，
**不能搬走**（薄壳会因命名空间缺 open/logger 而 NameError）。故由门面薄壳在
调用时解析后注入；`_resolve_archive_file` / `delete_archived_policy` 同理注入
门面的 load_archive_index，使整条链都走门面的可打桩绑定。
结构优化阶段 2（B6 第二刀 b）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from astra_backend.policy.io import _atomic_write_json, _index_lock
from astra_backend.policy.paths import ARCHIVE_DIR

logger = logging.getLogger(__name__)


def load_archive_index(rebuild: Callable[..., List[Dict[str, Any]]], archive_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """Loads metadata index of archived policies with locking and corruption recovery."""
    a_dir = archive_dir or ARCHIVE_DIR
    idx_file = a_dir / "index.json"

    with _index_lock(a_dir, shared=True):
        if not idx_file.is_file():
            reconstructed = rebuild(a_dir)
            if reconstructed:
                try:
                    save_archive_index(reconstructed, archive_dir=a_dir)
                except Exception:
                    pass
            return reconstructed

        needs_rebuild = False
        data: Any = None
        try:
            with open(idx_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if not content:
                    needs_rebuild = True
                else:
                    data = json.loads(content)
                    if not isinstance(data, list):
                        needs_rebuild = True
        except Exception as e:
            logger.warning("Corrupt policy archive index detected: %s", e)
            needs_rebuild = True

        if needs_rebuild:
            try:
                backup_file = a_dir / f"index.json.corrupt.{int(time.time())}"
                if idx_file.is_file():
                    os.replace(idx_file, backup_file)
                    logger.info("Backed up corrupted index to %s", backup_file.name)
            except Exception as e:
                logger.error("Failed to backup corrupt index: %s", e)

            reconstructed = rebuild(a_dir)
            try:
                save_archive_index(reconstructed, archive_dir=a_dir)
            except Exception:
                pass
            return reconstructed

        valid_entries = []
        for item in data:
            if isinstance(item, dict) and "policy_hash" in item:
                valid_entries.append(item)
        return valid_entries


def save_archive_index(index_data: List[Dict[str, Any]], archive_dir: Optional[Path] = None) -> None:
    """Saves metadata index of archived policies with atomic write and locking."""
    a_dir = archive_dir or ARCHIVE_DIR
    idx_file = a_dir / "index.json"
    with _index_lock(a_dir, shared=False):
        _atomic_write_json(idx_file, index_data)


def _resolve_archive_file(load_index: Callable[..., List[Dict[str, Any]]], a_dir: Path, key: str) -> Path:
    """按标识解析归档文件：键可以是整包标识（新命名）或四单元 policy_hash（历史命名）。

    审计 P0-3 配套：文件名改由整包标识命名后，删除/回滚都必须经索引解析，否则会出现
    「索引已删、文件还在」或反过来「文件在、却报 404」的半途状态。
    """
    direct = a_dir / f"policy_{key}.json"
    if direct.is_file():
        return direct
    for item in load_index(archive_dir=a_dir):
        if str(item.get("policy_hash") or "") != key and str(item.get("package_hash") or "") != key:
            continue
        candidate = a_dir / str(item.get("archive_file") or "")
        if candidate.is_file():
            return candidate
    return direct


def delete_archived_policy(load_index: Callable[..., List[Dict[str, Any]]], resolve_file: Callable[..., Path], 
    policy_hash: str,
    archive_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Deletes an archived policy file and removes its metadata from index."""
    if not policy_hash or not isinstance(policy_hash, str) or not re.match(r"^[a-zA-Z0-9_-]+$", policy_hash):
        raise ValueError(f"无效的策略哈希标识: {policy_hash}")

    a_dir = archive_dir or ARCHIVE_DIR
    archive_file = resolve_file(a_dir, policy_hash)

    with _index_lock(a_dir, shared=False):
        deleted_file = False
        if archive_file.is_file():
            archive_file.unlink(missing_ok=True)
            deleted_file = True

        index_data = load_index(archive_dir=a_dir)
        original_len = len(index_data)
        new_index = [item for item in index_data
                     if str(item.get("policy_hash") or "") != policy_hash
                     and str(item.get("package_hash") or "") != policy_hash]

        if len(new_index) < original_len or deleted_file:
            save_archive_index(new_index, archive_dir=a_dir)
            return {"deleted": True, "policy_hash": policy_hash}

        raise FileNotFoundError(f"未找到指定的策略归档: {policy_hash}")
