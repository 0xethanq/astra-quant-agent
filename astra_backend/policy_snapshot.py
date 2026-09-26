"""ASTRA Strategy Policy Snapshot & Version Control Workbench Engine.

Provides immutable snapshot fingerprinting, persistent archiving, one-click rollback,
and export/import capabilities across all 4 strategy units:
1. Prompt Profile (Prompt Studio)
2. Evolution Mind (Evolution Shield)
3. Physical Interceptors (Interceptors Plugin Pipeline)
4. Model Council (Council Desk)
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from astra_backend.version import __version__

# ── 结构优化阶段 2（B6）：指纹/规范化/整包标识已迁至 policy/fingerprints.py ──
# 门面重导出以保持既有 `from astra_backend.policy_snapshot import X` 不变。
from astra_backend.policy.capture import (
    capture_full_strategy_package as _core_capture_full_strategy_package,
    format_policy_snapshot_summary,
    generate_policy_snapshot as _core_generate_policy_snapshot,
    get_current_policy_snapshot as _core_get_current_policy_snapshot,
)
from astra_backend.policy.io import _atomic_write_json, _index_lock
from astra_backend.policy.archive import (
    _resolve_archive_file as _core__resolve_archive_file,
    delete_archived_policy as _core_delete_archived_policy,
    load_archive_index as _core_load_archive_index,
    save_archive_index,
)
from astra_backend.policy.restore import (
    _review_restored_lessons,
    restore_archived_policy as _core_restore_archived_policy,
)
from astra_backend.policy.fingerprints import (
    _canon_council_config,
    _canon_evolution_memory,
    _canon_prompt_config,
    _projection_digest,
    canonical_package_projection,
    compute_file_hash,
    compute_layout_hash,
    extract_council_fingerprint,
    extract_evolution_mind_fingerprint as _core_extract_evolution_mind_fingerprint,
    extract_interceptors_fingerprint as _core_extract_interceptors_fingerprint,
    extract_prompt_profile_fingerprint as _core_extract_prompt_profile_fingerprint,
    package_identity,
    package_restore_diff,
)
from astra_backend.policy.paths import ARCHIVE_DIR, ARCHIVE_INDEX_FILE, DATA_DIR, ROOT
from astra_backend.policy.schema import (
    DEFAULT_BASE_VERSION,
    _COUNCIL_ROLE_FIELDS,
    _PACKAGE_UNITS,
    _PROFILE_IDENTITY_FIELDS,
    _TEMPLATE_KEYS,
)

# ── 薄壳（B6）：以下入口在未显式传 root_dir 时回退到模块级 ROOT ──
# 测试用 `patch.object(policy_snapshot, "ROOT", 沙箱根)` 重定向它。若核心在导入期绑定
# ROOT，该补丁会**静默失效**并回落到真实项目根（回滚会写生产 data/）—— 故一律在
# **调用时**解析门面全局 ROOT 后注入核心。公开签名与拆分前逐字一致。

def extract_prompt_profile_fingerprint(profile: Optional[Dict[str, Any]] = None,
                                       root_dir: Optional[Path] = None) -> Dict[str, Any]:
    return _core_extract_prompt_profile_fingerprint(ROOT, profile, root_dir)


def extract_evolution_mind_fingerprint(memory_snapshot: Optional[Dict[str, Any]] = None,
                                       root_dir: Optional[Path] = None) -> Dict[str, Any]:
    return _core_extract_evolution_mind_fingerprint(ROOT, memory_snapshot, root_dir)


def extract_interceptors_fingerprint(interceptor_plugins: Optional[List[Dict[str, Any]]] = None,
                                     plugins_dir: Optional[Path] = None,
                                     root_dir: Optional[Path] = None) -> Dict[str, Any]:
    return _core_extract_interceptors_fingerprint(ROOT, interceptor_plugins, plugins_dir, root_dir)


def generate_policy_snapshot(root_dir: Optional[Path] = None,
                             prompt_profile: Optional[Dict[str, Any]] = None,
                             memory_snapshot: Optional[Dict[str, Any]] = None,
                             interceptor_plugins: Optional[List[Dict[str, Any]]] = None,
                             council_config: Optional[Dict[str, Any]] = None,
                             plugins_dir: Optional[Path] = None,
                             base_version: str = DEFAULT_BASE_VERSION) -> Dict[str, Any]:
    return _core_generate_policy_snapshot(ROOT, root_dir, prompt_profile, memory_snapshot,
                                          interceptor_plugins, council_config, plugins_dir, base_version)


def get_current_policy_snapshot() -> Dict[str, Any]:
    return _core_get_current_policy_snapshot(ROOT)


def capture_full_strategy_package(root_dir: Optional[Path] = None) -> Dict[str, Any]:
    return _core_capture_full_strategy_package(ROOT, root_dir)


_BJ = timezone(timedelta(hours=8))

logger = logging.getLogger(__name__)


# =========================================================================
# 归档包标识（审计 P0-3，2026-09-13）
# =========================================================================
# 病灶：policy_hash 只覆盖 4 个单元（提示词/心法/拦截器/委员会），而归档包实际装 6 个
# （另含 risk_config 与 venue_routing），归档文件名却只用 policy_hash 命名 →
# **仅风控/路由不同的两个版本被判为同一版本**，第二次归档静默覆盖第一次；
# 回滚后的哈希校验也因此对风控/路由的恢复失败完全失明。
# 修复：另算一个「整包标识」用于文件命名与恢复后校验，并对易变字段做规范化
# （时间戳/评分/revision 每次写都会变，绝不能进标识，否则校验必然误报）。


# =========================================================================
# Policy Version Workbench: Archive, Rollback, Export & Import
# =========================================================================


def _rebuild_index_from_archives(a_dir: Path) -> List[Dict[str, Any]]:
    """Scans all policy_*.json files in archive_dir and reconstructs index entries."""
    entries: List[Dict[str, Any]] = []
    if not a_dir.is_dir():
        return entries

    for f in a_dir.glob("policy_*.json"):
        if not f.is_file() or f.name.endswith(".tmp"):
            continue
        try:
            with open(f, "r", encoding="utf-8") as handle:
                package = json.load(handle)
            meta = package.get("metadata") or {}
            policy_hash = package.get("policy_hash") or f.stem.replace("policy_", "")
            policy_version = package.get("policy_version") or f"unknown@{policy_hash}"
            entry = {
                "policy_version": policy_version,
                "policy_hash": policy_hash,
                "name": str(meta.get("name") or f"策略归档-{policy_hash}"),
                "description": str(meta.get("description") or ""),
                "author": str(meta.get("author") or "admin"),
                "archived_at": str(
                    meta.get("archived_at")
                    or datetime.fromtimestamp(f.stat().st_mtime, _BJ).isoformat(sep=" ", timespec="seconds")
                ),
                "summary": str(package.get("summary") or ""),
                "archive_file": f.name,
            }
            entries.append(entry)
        except Exception as err:
            logger.warning("Failed to parse archive file %s during index rebuild: %s", f.name, err)

    entries.sort(key=lambda x: str(x.get("archived_at", "")), reverse=True)
    return entries


def load_archive_index(archive_dir: Optional[Path] = None) -> List[Dict[str, Any]]:
    """薄壳：调用时解析门面模块全局（结构优化阶段 2 / B6 第二刀 b）。"""
    return _core_load_archive_index(_rebuild_index_from_archives, archive_dir)




def archive_current_policy(
    name: str,
    description: str = "",
    author: str = "admin",
    archive_dir: Optional[Path] = None,
    root_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Archives the live strategy state into an immutable policy version package."""
    a_dir = archive_dir or ARCHIVE_DIR
    a_dir.mkdir(parents=True, exist_ok=True)

    with _index_lock(a_dir, shared=False):
        package = capture_full_strategy_package(root_dir=root_dir)
        policy_hash = package["policy_hash"]
        policy_version = package["policy_version"]
        # 审计 P0-3：文件标识改用「整包标识」——policy_hash 看不到 risk_config/venue_routing，
        # 只差风控的两个版本会同名互相覆盖。
        package_hash = package_identity(package.get("package") or {})

        safe_name = name.strip() or f"策略归档-{policy_hash}"
        archive_file = a_dir / f"policy_{package_hash or policy_hash}.json"

        package["package_hash"] = package_hash
        package["metadata"] = {
            "name": safe_name,
            "description": description.strip(),
            "author": author,
            "archived_at": datetime.now(_BJ).isoformat(sep=" ", timespec="seconds"),
            "archive_file": archive_file.name,
            "package_hash": package_hash,
        }

        _atomic_write_json(archive_file, package)

        # Update index：去重键 = 整包标识（同包重归档才替换）；无 package_hash 的历史
        # 条目退回 policy_hash 判等，保持旧行为。
        index_data = load_archive_index(archive_dir=a_dir)

        def _same_archive(item: Dict[str, Any]) -> bool:
            item_pkg = str(item.get("package_hash") or "")
            if item_pkg:
                return item_pkg == package_hash
            return str(item.get("policy_hash") or "") == policy_hash

        index_data = [item for item in index_data if not _same_archive(item)]

        entry = {
            "policy_version": policy_version,
            "policy_hash": policy_hash,
            "package_hash": package_hash,
            "name": safe_name,
            "description": description.strip(),
            "author": author,
            "archived_at": package["metadata"]["archived_at"],
            "summary": package["summary"],
            "archive_file": archive_file.name,
        }
        index_data.insert(0, entry)
        save_archive_index(index_data, archive_dir=a_dir)

        return entry


# Canonical alias
archive_policy_snapshot = archive_current_policy


def _resolve_archive_file(a_dir: Path, key: str) -> Path:
    """薄壳：调用时解析门面模块全局（结构优化阶段 2 / B6 第二刀 b）。"""
    return _core__resolve_archive_file(load_archive_index, a_dir, key)


def restore_archived_policy(
    policy_hash: str,
    archive_dir: Optional[Path] = None,
    root_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """薄壳：调用时解析门面模块全局，使测试的 patch / 直接赋值生效。

    实现已迁往 astra_backend.policy.restore（结构优化阶段 2 / B6 第二刀）。
    """
    return _core_restore_archived_policy(_resolve_archive_file, ROOT, policy_hash, archive_dir, root_dir)


# Canonical alias
restore_policy_snapshot = restore_archived_policy


def delete_archived_policy(
    policy_hash: str,
    archive_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """薄壳：调用时解析门面模块全局（结构优化阶段 2 / B6 第二刀 b）。"""
    return _core_delete_archived_policy(load_archive_index, _resolve_archive_file, policy_hash, archive_dir)


# Canonical alias
delete_policy_archive = delete_archived_policy


__all__ = [
    "DEFAULT_BASE_VERSION",
    "compute_layout_hash",
    "compute_file_hash",
    "extract_prompt_profile_fingerprint",
    "extract_evolution_mind_fingerprint",
    "extract_interceptors_fingerprint",
    "extract_council_fingerprint",
    "format_policy_snapshot_summary",
    "generate_policy_snapshot",
    "get_current_policy_snapshot",
    "capture_full_strategy_package",
    "load_archive_index",
    "save_archive_index",
    "archive_current_policy",
    "archive_policy_snapshot",
    "restore_archived_policy",
    "restore_policy_snapshot",
    "delete_archived_policy",
    "delete_policy_archive",
]
