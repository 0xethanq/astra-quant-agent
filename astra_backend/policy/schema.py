"""策略快照的结构常量（包单元、模板键、身份字段、基线版本）。

结构优化阶段 2（B6）。
"""
from __future__ import annotations

from typing import Any, Dict, List

# DEFAULT_BASE_VERSION 依赖版本号；原在 policy_snapshot.py 顶部导入，
# 常量搬家时必须一并带上，否则本模块 import 即 NameError。
from astra_backend.version import __version__


DEFAULT_BASE_VERSION = f"v{__version__}"


_PACKAGE_UNITS = ("prompt_config", "evolution_memory", "interceptor_config",
                  "council_config", "risk_config", "venue_routing")


_TEMPLATE_KEYS = ("trading_system", "trading_user", "evolution_system", "evolution_user")


_PROFILE_IDENTITY_FIELDS = ("id", "name", "description", "enabled", "editor_mode",
                            "simple_policy", "pipelines", *_TEMPLATE_KEYS)


_COUNCIL_ROLE_FIELDS = ("id", "name", "role_title", "enabled", "is_arbitrator", "prompt",
                        "weight", "temperature", "reasoning_effort", "model_id")
