"""ASTRA 多交易所适配层（Phase 1）。

⚠️ 下表带 `.py` 后缀是**刻意的**：`tests/audit/test_directory_docs_current.py`
把"文档里出现过带后缀的模块名"当作登记凭据（第五十九刀把本子包纳入受管名单时
发现原来的 `- base: …` 写法不带后缀，门禁识别不到）。

| 模块 | 内容 |
|---|---|
| `base.py` | `ExchangeCapabilities` 能力表 / `InstrumentSpec` / `BaseExchangeAdapter` |
| `binance.py` | 币安 USDT-M 只读行情适配器（`BinanceAdapter` / `BinanceAPIError`） |
| `binance_algo.py` | 币安 Algo Service 请求构造器混入（US-004 双轨契约；纯 dict 构造、零 I/O、零凭证） |
| `binance_orders.py` | 币安下单参数构建的两条判定：`build_order_params(...)`（数量/价格按 `step`/`tick` 向下取整、LIMIT/MARKET 选择、**`reduceOnly`×`positionSide` 互斥契约**）、`apply_protective_qty_policy(...)`（保护单数量策略：有数量限仓、无数量整仓平）、`send_protective_order(...)`（TP/SL 发单统一入口：触发价无效不发、返回 algoId→orderId→""，第一百一十六刀合并两段重复代码） —— 纯函数、零 `self`、零 I/O |
| `binance_signing.py` | `build_signed_query(...)` —— Binance 私有请求的**签名串构建**：补齐毫秒 `timestamp` 与 `recvWindow=5000`、**剔除空值但保留 `0`/`False`**、`HMAC-SHA256(secret, query_string)` 十六进制 —— 纯字符串构建；HTTP 传送与 `urlopen` 接缝仍在 `binance.py` |
| `gate.py` | Gate.io V4 永续只读行情适配器 |
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
from .binance import BinanceAdapter, BinanceAPIError
from .diagnostics import diagnose_venue_connection
from .gate import GateAdapter, GateAPIError
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
    gate_environment_axis,
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
    "BinanceAPIError", "GateAPIError",
    "InstrumentSpec", "canonical_base", "BinanceAdapter", "GateAdapter",
    "OKXAdapter", "OKXPublicAdapter", "SandboxExchangeAdapter", "ADAPTER_EXECUTION_ENABLED", "execution_open",
    "get_adapter", "is_registered", "registered_venues", "require_execution",
    "resolve_symbol", "clear_instances", "venue_credentials", "venue_passphrase",
    "venue_testnet_enabled", "env_profiles", "diagnose_venue_connection",
    "AccountKey", "ANON_CREDENTIAL", "credential_fingerprint",
    "is_sandbox_environment", "gate_environment_axis",
]
