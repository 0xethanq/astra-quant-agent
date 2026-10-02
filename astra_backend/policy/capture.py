"""策略快照生成与整包抓取。

不引用任何被测试重定向的"留在门面"的符号（只依赖 policy.paths / policy.schema /
policy.fingerprints 的纯数据与纯函数），故门面直接重导出，无需薄壳。
结构优化阶段 2（B6 第二刀）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

from astra_backend.policy.fingerprints import (
    extract_council_fingerprint,
    extract_evolution_mind_fingerprint,
    extract_prompt_profile_fingerprint,
)
from astra_backend.policy.schema import DEFAULT_BASE_VERSION

logger = logging.getLogger(__name__)


def generate_policy_snapshot(
    root: Path,
    root_dir: Optional[Path] = None,
    prompt_profile: Optional[Dict[str, Any]] = None,
    memory_snapshot: Optional[Dict[str, Any]] = None,
    council_config: Optional[Dict[str, Any]] = None,
    base_version: str = DEFAULT_BASE_VERSION,
) -> Dict[str, Any]:
    """Generates an immutable snapshot fingerprint across the 3 core strategy units.

    2026-10：策略插件系统（决策插件管线）整套裁撤，`physical_interceptors`
    单元随之移除 —— 快照现在覆盖「提示词 / 心法 / 模型委员会」三单元。
    """
    prompt_info = extract_prompt_profile_fingerprint(root, prompt_profile, root_dir=root_dir)
    evolution_info = extract_evolution_mind_fingerprint(root, memory_snapshot, root_dir=root_dir)
    council_info = extract_council_fingerprint(council_config, root_dir=root_dir)

    canonical_fingerprint = {
        "prompt_profile": {
            "id": prompt_info["active_profile_id"],
            "layout_hash": prompt_info["layout_hash"],
            "editor_mode": prompt_info["editor_mode"],
        },
        "evolution_mind": {
            "version": evolution_info["version"],
            "enabled_count": evolution_info["enabled_count"],
        },
        "model_council": {
            "enabled": council_info["enabled"],
            "consensus_mode": council_info["consensus_mode"],
            "active_roles": council_info["active_roles"],
            "role_models": council_info["role_models"],
        },
    }

    canon_bytes = json.dumps(canonical_fingerprint, sort_keys=True, separators=(",", ":")).encode("utf-8")
    policy_hash = hashlib.sha256(canon_bytes).hexdigest()[:8]
    policy_version = f"{base_version}@{policy_hash}"

    mind_ver_short = evolution_info["version"][:8] if evolution_info["version"] != "missing" else "missing"
    summary = (
        f"Policy[{policy_version}] "
        f"prompt:{prompt_info['active_profile_id']}#{prompt_info['layout_hash']} "
        f"mind:{mind_ver_short}({evolution_info['enabled_count']}) "
        f"council:{'on' if council_info['enabled'] else 'off'}({council_info['consensus_mode']})"
    )

    return {
        "policy_version": policy_version,
        "policy_hash": policy_hash,
        "base_version": base_version,
        "timestamp": int(time.time()),
        "summary": summary,
        "units": {
            "prompt_profile": prompt_info,
            "evolution_mind": evolution_info,
            "model_council": council_info,
        },
    }


def get_current_policy_snapshot(root: Path) -> Dict[str, Any]:
    """Convenience accessor for live current policy snapshot."""
    return generate_policy_snapshot(root)


def format_policy_snapshot_summary(snapshot: Dict[str, Any]) -> str:
    """Formats a concise single-line summary of a policy snapshot."""
    return str(snapshot.get("summary") or snapshot.get("policy_version") or "unknown_policy")


def capture_full_strategy_package(root: Path, root_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Captures complete runtime data payload across all remaining units for rollback/export.

    2026-10：策略插件系统裁撤 ⇒ 归档单元由 4 个（提示词/心法/插件/委员会）变为
    3 个（提示词/心法/委员会）+ 风控配置。
    """
    r_dir = root_dir or root
    sys_path_added = False
    scripts_dir = str(r_dir / "scripts")
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
        sys_path_added = True

    try:
        try:
            from prompt_library import load_library
            prompt_full = load_library()
        except (ImportError, AttributeError):
            from prompt_library import load_prompt_config
            prompt_full = load_prompt_config()
    except Exception as e:
        logger.warning("Failed to capture prompt library: %s", e)
        prompt_full = {}

    try:
        from evolution_shield import STRUCTURED_MEMORY_FILE
        if STRUCTURED_MEMORY_FILE.is_file():
            raw_text = STRUCTURED_MEMORY_FILE.read_text(encoding="utf-8")
            memory_full = json.loads(raw_text)
        else:
            from evolution_shield import read_memory_snapshot
            memory_full = read_memory_snapshot()
    except Exception as e:
        logger.warning("Failed to capture evolution memory: %s", e)
        memory_full = {"version": "missing", "lessons": []}

    try:
        from astra_backend.council_manager import load_council_config
        council_full = load_council_config()
    except Exception as e:
        logger.warning("Failed to capture council config: %s", e)
        council_full = {}

    try:
        from astra_backend import risk_config
        risk_full = risk_config.current_values()
    except Exception as e:
        logger.warning("Failed to capture risk config: %s", e)
        risk_full = {}

    finally:
        if sys_path_added and scripts_dir in sys.path:
            try:
                sys.path.remove(scripts_dir)
            except ValueError:
                pass

    snapshot = generate_policy_snapshot(root, root_dir=r_dir)

    return {
        "format": "astra_policy_package_v1",
        "policy_version": snapshot["policy_version"],
        "policy_hash": snapshot["policy_hash"],
        "captured_at": snapshot["timestamp"],
        "summary": snapshot["summary"],
        "snapshot": snapshot,
        "package": {
            "prompt_config": prompt_full,
            "evolution_memory": memory_full,
            "council_config": council_full,
            "risk_config": risk_full,
        },
    }
