"""策略指纹计算：文件/布局哈希、四单元指纹、规范化投影与整包标识。

三个 extract_* 在未显式传 root_dir 时会回退到模块级 ROOT。原实现在
policy_snapshot.py 里，测试用 `patch.object(policy_snapshot, "ROOT", 沙箱根)` 重定向它；
搬家后若在导入期绑定 ROOT，该补丁就会**静默失效**并回落到真实项目根
（回滚会写生产 data/）—— 故改为「门面薄壳注入 ROOT、核心以 root 参数接收」。
结构优化阶段 2（B6）。
"""
from __future__ import annotations

import hashlib
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional

from astra_backend.policy.schema import (
    DEFAULT_BASE_VERSION,
    _COUNCIL_ROLE_FIELDS,
    _PACKAGE_UNITS,
    _PROFILE_IDENTITY_FIELDS,
    _TEMPLATE_KEYS,
)

logger = logging.getLogger(__name__)


def compute_layout_hash(profile: Dict[str, Any]) -> str:
    """Computes a deterministic hash for a prompt profile layout."""
    parts: List[str] = []
    mode = str(profile.get("editor_mode", "modules"))
    parts.append(f"mode:{mode}")

    if mode == "modules":
        # Support both flat modules list and pipeline dictionary
        modules = profile.get("modules")
        if modules is None and isinstance(profile.get("pipelines"), dict):
            modules = []
            for pipe_key in sorted(profile["pipelines"].keys()):
                pipe_mods = profile["pipelines"][pipe_key]
                if isinstance(pipe_mods, list):
                    modules.extend(pipe_mods)
        if isinstance(modules, list):
            for m in modules:
                if isinstance(m, dict):
                    m_id = str(m.get("id", ""))
                    enabled = "1" if m.get("enabled", True) else "0"
                    content = str(m.get("content", "")).strip()
                    c_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()[:8]
                    parts.append(f"{m_id}:{enabled}:{c_hash}")
    elif mode == "simple":
        simple_pol = profile.get("simple_policy")
        if isinstance(simple_pol, dict):
            for k in sorted(simple_pol.keys()):
                v = str(simple_pol[k]).strip()
                v_hash = hashlib.sha256(v.encode("utf-8")).hexdigest()[:8]
                parts.append(f"{k}:{v_hash}")
        else:
            parts.append("empty_simple")
    else:
        template_found = False
        for tk in ("trading_system", "trading_user", "evolution_system", "evolution_user"):
            if tk in profile:
                val = str(profile.get(tk, "")).strip()
                v_hash = hashlib.sha256(val.encode("utf-8")).hexdigest()[:8]
                parts.append(f"{tk}:{v_hash}")
                template_found = True
        if not template_found:
            full_content = str(profile.get("full_system_prompt", "")).strip()
            f_hash = hashlib.sha256(full_content.encode("utf-8")).hexdigest()[:8]
            parts.append(f"full:{f_hash}")

    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:8]


def compute_file_hash(file_path: Path) -> str:
    """Computes an 8-char SHA256 hex digest for a file if it exists."""
    if not file_path.is_file():
        return "missing"
    try:
        content = file_path.read_bytes()
        return hashlib.sha256(content).hexdigest()[:8]
    except Exception:
        return "err_read"


def extract_prompt_profile_fingerprint(
    root: Path,
    profile: Optional[Dict[str, Any]] = None,
    root_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Extracts immutable fingerprint of the active prompt profile."""
    prof = profile
    if prof is None:
        sys_path_added = False
        scripts_dir = str((root_dir or root) / "scripts")
        try:
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
                sys_path_added = True
            try:
                from prompt_library import active_profile
                prof = active_profile()
            except (ImportError, AttributeError):
                from prompt_library import load_active_profile
                prof = load_active_profile()
        except Exception as e:
            logger.warning("Failed to load active profile: %s", e)
            prof = {
                "id": "stable",
                "name": "全维度波段强化版",
                "editor_mode": "modules",
            }
        finally:
            if sys_path_added and scripts_dir in sys.path:
                try:
                    sys.path.remove(scripts_dir)
                except ValueError:
                    pass

    p_id = str(prof.get("id", "stable"))
    p_name = str(prof.get("name", "全维度波段强化版"))
    editor_mode = str(prof.get("editor_mode", "modules"))
    layout_hash = compute_layout_hash(prof)

    return {
        "active_profile_id": p_id,
        "active_profile_name": p_name,
        "editor_mode": editor_mode,
        "layout_hash": layout_hash,
    }


def extract_evolution_mind_fingerprint(
    root: Path,
    memory_snapshot: Optional[Dict[str, Any]] = None,
    root_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Extracts immutable fingerprint of the structured self-evolution mind."""
    snap = memory_snapshot
    if snap is None:
        sys_path_added = False
        scripts_dir = str((root_dir or root) / "scripts")
        try:
            if scripts_dir not in sys.path:
                sys.path.insert(0, scripts_dir)
                sys_path_added = True
            from evolution_shield import read_memory_snapshot
            snap = read_memory_snapshot()
        except Exception as e:
            logger.warning("Failed to read memory snapshot: %s", e)
            snap = {"exists": False, "version": "missing", "lessons": []}
        finally:
            if sys_path_added and scripts_dir in sys.path:
                try:
                    sys.path.remove(scripts_dir)
                except ValueError:
                    pass

    version = str(snap.get("version", "missing"))
    lessons = snap.get("lessons") or []
    if not isinstance(lessons, list):
        lessons = []
    enabled_count = len([item for item in lessons if isinstance(item, dict) and item.get("enabled", True)])
    total_count = len(lessons)

    return {
        "version": version,
        "enabled_count": enabled_count,
        "total_count": total_count,
    }


def extract_interceptors_fingerprint(
    root: Path,
    interceptor_plugins: Optional[List[Dict[str, Any]]] = None,
    plugins_dir: Optional[Path] = None,
    root_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Extracts immutable fingerprint of the physical interceptors pipeline."""
    p_dir = plugins_dir or ((root_dir or root) / "plugins" / "interceptors")
    plugins = interceptor_plugins

    if plugins is None:
        try:
            from astra_backend.interceptor_manager import list_plugins
            plugins = list_plugins(create_if_missing=False)
        except Exception as e:
            logger.warning("Failed to list plugins: %s", e)
            plugins = []

    pipeline_info: List[Dict[str, Any]] = []
    enabled_plugins: List[str] = []

    for idx, item in enumerate(plugins if isinstance(plugins, list) else []):
        if not isinstance(item, dict):
            continue
        filename = str(item.get("filename", ""))
        enabled = bool(item.get("enabled", False))
        f_hash = str(item.get("file_hash") or "")
        if not f_hash:
            file_path = p_dir / filename
            f_hash = compute_file_hash(file_path)

        if enabled:
            enabled_plugins.append(filename)
            pipeline_info.append({
                "order": idx,
                "filename": filename,
                "file_hash": f_hash,
            })

    sorted_pipeline = sorted(pipeline_info, key=lambda x: x["order"])
    pipe_str = ";".join([f"{p['order']}:{p['filename']}:{p['file_hash']}" for p in sorted_pipeline])
    plugins_hash = hashlib.sha256(pipe_str.encode("utf-8")).hexdigest()[:8]

    return {
        "plugins_hash": plugins_hash,
        "enabled_count": len(enabled_plugins),
        "total_count": len(plugins) if isinstance(plugins, list) else 0,
        "enabled_plugins": enabled_plugins,
        "pipeline": sorted_pipeline,
    }


def extract_council_fingerprint(
    council_config: Optional[Dict[str, Any]] = None,
    root_dir: Optional[Path] = None,
) -> Dict[str, Any]:
    """Extracts immutable fingerprint of the trading desk council."""
    cfg = council_config
    if cfg is None:
        try:
            from astra_backend.council_manager import load_council_config
            cfg = load_council_config()
        except Exception as e:
            logger.warning("Failed to load council config: %s", e)
            cfg = {"enabled": False, "consensus_mode": "standard", "roles": {}}

    enabled = bool(cfg.get("enabled", False))
    raw_mode = str(cfg.get("consensus_mode", "standard")).lower()
    consensus_mode = "cross_examination" if raw_mode in {"cross_examination", "cross-exam", "cross"} else "standard"
    roles = cfg.get("roles") or {}
    if not isinstance(roles, dict):
        roles = {}

    active_roles: List[str] = []
    role_models: Dict[str, str] = {}

    for r_id, r_data in sorted(roles.items()):
        if isinstance(r_data, dict):
            r_enabled = bool(r_data.get("enabled", True))
            if r_enabled or r_data.get("is_arbitrator"):
                active_roles.append(r_id)
                role_models[r_id] = str(r_data.get("model_id") or "default")

    council_ident = {
        "enabled": enabled,
        "mode": consensus_mode,
        "roles": active_roles,
        "models": role_models,
    }
    ident_bytes = json.dumps(council_ident, sort_keys=True, separators=(",", ":")).encode("utf-8")
    council_hash = hashlib.sha256(ident_bytes).hexdigest()[:8]

    return {
        "enabled": enabled,
        "consensus_mode": consensus_mode,
        "active_roles": active_roles,
        "role_models": role_models,
        "council_hash": council_hash,
    }


def _canon_prompt_config(cfg: Any) -> Any:
    if not isinstance(cfg, dict):
        return cfg or {}
    profiles = cfg.get("profiles") if isinstance(cfg.get("profiles"), dict) else {}
    return {
        "active_profile_id": cfg.get("active_profile_id"),
        "active_style": cfg.get("active_style"),
        "profiles": {
            str(pid): {k: prof.get(k) for k in _PROFILE_IDENTITY_FIELDS}
            for pid, prof in sorted(profiles.items()) if isinstance(prof, dict)
        },
    }


def _canon_evolution_memory(mem: Any) -> Any:
    lessons = mem
    if isinstance(mem, dict):
        lessons = mem.get("lessons") if isinstance(mem.get("lessons"), list) else []
    elif not isinstance(mem, list):
        return []
    out = []
    for item in lessons:
        if isinstance(item, dict):
            out.append({k: item.get(k) for k in ("id", "category", "rule_text", "enabled", "is_baseline")})
        else:
            out.append(str(item))
    return out


def _canon_council_config(cfg: Any) -> Any:
    if not isinstance(cfg, dict):
        return cfg or {}
    roles = cfg.get("roles") if isinstance(cfg.get("roles"), dict) else {}
    return {
        "enabled": bool(cfg.get("enabled", False)),
        "consensus_mode": cfg.get("consensus_mode"),
        "timeout_seconds": cfg.get("timeout_seconds"),
        "roles": {
            str(rid): ({k: role.get(k) for k in _COUNCIL_ROLE_FIELDS} if isinstance(role, dict) else role)
            for rid, role in sorted(roles.items())
        },
    }


def canonical_package_projection(payload: Mapping[str, Any]) -> Dict[str, Any]:
    """归档包的规范化投影：只保留「策略身份」字段，剔除每次写都会变的易变字段。"""
    src = payload if isinstance(payload, Mapping) else {}
    return {
        "prompt_config": _canon_prompt_config(src.get("prompt_config")),
        "evolution_memory": _canon_evolution_memory(src.get("evolution_memory")),
        "interceptor_config": src.get("interceptor_config") or {},
        "council_config": _canon_council_config(src.get("council_config")),
        "risk_config": {str(k): v for k, v in sorted((src.get("risk_config") or {}).items())}
        if isinstance(src.get("risk_config"), Mapping) else {},
        "venue_routing": src.get("venue_routing") or {},
    }


def _projection_digest(projection: Mapping[str, Any]) -> str:
    blob = json.dumps(projection, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def package_identity(payload: Mapping[str, Any]) -> str:
    """整包标识（16 hex）：用于归档文件命名，保证「只差风控/路由」的版本不再同名。"""
    return _projection_digest(canonical_package_projection(payload))


def package_restore_diff(archived_payload: Mapping[str, Any],
                         current_payload: Mapping[str, Any]) -> List[str]:
    """恢复后核对：返回「归档里承诺、但恢复后没对上」的单元名。

    - 归档**没装**的单元（空/None）无从承诺，一律跳过——不能因为「当前有、归档没有」
      就判恢复失败（旧包无法清空它诞生之后才出现的内容）；
    - 已装的顺序性单元（提示词/心法/拦截器/委员会）要求全等；
    - 已装的字典类单元（风控/路由）只核对归档里出现过的键；归档之后新增的键由
      `restore_archived_policy` 以 `uncovered_risk_keys` 如实披露。
    """
    archived = canonical_package_projection(archived_payload)
    current = canonical_package_projection(current_payload)
    bad: List[str] = []
    for unit in ("prompt_config", "evolution_memory", "interceptor_config", "council_config"):
        want = archived.get(unit)
        if not want:
            continue
        if want != current.get(unit):
            bad.append(unit)
    for unit in ("risk_config", "venue_routing"):
        want, got = archived.get(unit) or {}, current.get(unit) or {}
        if not want:
            continue
        if not isinstance(want, Mapping) or not isinstance(got, Mapping):
            if want != got:
                bad.append(unit)
            continue
        for key, value in want.items():
            if got.get(key) != value:
                bad.append(f"{unit}.{key}")
    return bad
