"""ASTRA 交易所适配层（OKX 专用）。

⚠️ 下表带 `.py` 后缀是**刻意的**：`tests/audit/test_directory_docs_current.py`
把"文档里出现过带后缀的模块名"当作登记凭据。

| 模块 | 内容 |
|---|---|
| `base.py` | `ExchangeCapabilities` 能力表 / `InstrumentSpec` / `BaseExchangeAdapter` |
| `okx.py` | OKX V5 公共行情只读适配器 |
| `env_profiles.py` | `(venue, environment)` → 端点档单一入口（US-001） |
| `identity.py` | `AccountKey` 三元身份 (venue, environment, credential fingerprint)（US-002） |
| `registry.py` | venue 注册表 + 执行门禁 `require_execution()`（双轴开关，US-002） |
| `diagnostics.py` | 场所连通性诊断 |
| `listing.py` | 上币/交易对目录读取 |
| `routing_policy.py` | 选所路由策略 |
"""
from . import env_profiles
from .base import (
    BaseExchangeAdapter,
    ExchangeCapabilities,
    ExchangeCapabilityError,
    InstrumentSpec,
    canonical_base,
)
from .diagnostics import diagnose_venue_connection
from .identity import (
    ANON_CREDENTIAL,
    AccountKey,
    credential_fingerprint,
    is_sandbox_environment,
)
from .okx import OKXAdapter, OKXPublicAdapter
from astra_backend.sandbox.adapter import SandboxExchangeAdapter
from .registry import (
    ADAPTER_EXECUTION_ENABLED,
    clear_instances,
    execution_open,
    get_adapter,
    is_registered,
    registered_venues,
    require_execution,
    resolve_symbol,
    venue_credentials,
    venue_passphrase,
    venue_testnet_enabled,
)

__all__ = [
    "BaseExchangeAdapter", "ExchangeCapabilities", "ExchangeCapabilityError",
    "InstrumentSpec", "canonical_base",
    "OKXAdapter", "OKXPublicAdapter", "SandboxExchangeAdapter", "ADAPTER_EXECUTION_ENABLED", "execution_open",
    "get_adapter", "is_registered", "registered_venues", "require_execution",
    "resolve_symbol", "clear_instances", "venue_credentials", "venue_passphrase",
    "venue_testnet_enabled", "env_profiles", "diagnose_venue_connection",
    "AccountKey", "ANON_CREDENTIAL", "credential_fingerprint",
    "is_sandbox_environment",
]
