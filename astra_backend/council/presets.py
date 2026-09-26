"""委员会预设套件与角色模板复位。

apply_preset_suite / reset_role_template 会调用**必须留在门面**的
load_council_config / save_council_config（测试接缝与 isolated() 钉在门面），
故由薄壳在调用时解析后注入，核心只调用注入的可调用对象。
结构优化阶段 2（B5 第二刀）。
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List

from astra_backend.council.policy import (
    ALL_AVAILABLE_PRESETS,
    COUNCIL_PRESET_SUITES,
    DEFAULT_CONSENSUS_MODE,
    DEFAULT_PRESET_TEMPLATES,
)


def get_available_presets() -> List[Dict[str, Any]]:
    return list(ALL_AVAILABLE_PRESETS.values())


def get_preset_suites() -> List[Dict[str, Any]]:
    return list(COUNCIL_PRESET_SUITES.values())


def apply_preset_suite(load_config: Callable[[], Dict[str, Any]], save_config: Callable[[Dict[str, Any]], Dict[str, Any]], suite_id: str) -> Dict[str, Any]:
    suite = COUNCIL_PRESET_SUITES.get(suite_id)
    if not suite:
        suite = list(COUNCIL_PRESET_SUITES.values())[0]

    config = load_config()
    new_roles: Dict[str, Any] = {}
    for r_id in suite["roles"]:
        if r_id in ALL_AVAILABLE_PRESETS:
            preset = dict(ALL_AVAILABLE_PRESETS[r_id])
            old_model = config.get("roles", {}).get(r_id, {}).get("model_id", "")
            preset["model_id"] = old_model
            new_roles[r_id] = preset

    config["consensus_mode"] = suite.get("consensus_mode", DEFAULT_CONSENSUS_MODE)
    config["roles"] = new_roles
    return save_config(config)


def reset_role_template(load_config: Callable[[], Dict[str, Any]], save_config: Callable[[Dict[str, Any]], Dict[str, Any]], role_id: str) -> Dict[str, Any]:
    config = load_config()
    roles = config.get("roles", {})
    if role_id not in roles:
        raise ValueError(f"未找到角色 ID: {role_id}")

    preset = ALL_AVAILABLE_PRESETS.get(role_id)
    if not preset:
        if role_id in {"cio", "arbitrator"} or roles[role_id].get("is_arbitrator"):
            preset = DEFAULT_PRESET_TEMPLATES["cio"]
        else:
            raise ValueError(f"该角色无内置出厂模板: {role_id}")

    old_model = roles[role_id].get("model_id", "")
    new_role = dict(preset)
    new_role["model_id"] = old_model
    roles[role_id] = new_role
    config["roles"] = roles
    return save_config(config)
