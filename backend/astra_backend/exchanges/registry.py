"""交易所适配器注册表：场所选择与能力门禁的单一入口（OKX 专用）。

上层（因子聚合 / 执行路由 / 后台配置）只认 venue 字符串；任何执行类请求
先过 ``require_execution``，未开闸场所 fail-closed 显式拒绝。未登记场所
（本系统已移除的场所）一律显式拒答，绝不静默返回空值。

凭证与网络档位（US-001 起 = env_profiles 单一入口；US-002 起 = AccountKey 三元键）：
- ``venue_credentials(venue)``：从加密密钥库读 API Key/Secret（只读行情用不到，
  执行与更高限频档消费；后台凭证面板负责录入）；
- 端点档由 ``env_profiles`` 按 (venue, environment) 解析；
- ``_INSTANCES`` 缓存键 = AccountKey (venue, environment, credential_fingerprint)：
  同所不同环境、同环境不同凭证代际**永不互串**；密钥轮换后自动重建实例。
- 执行开闸双轴（US-002）：live 档与沙盒档各自独立，任一缺失 fail-closed。
"""
from __future__ import annotations

import os
from typing import Dict, Optional, Tuple

from .base import BaseExchangeAdapter, ExchangeCapabilityError, canonical_base
from .identity import (AccountKey, credential_fingerprint,
                       is_sandbox_environment)
from .okx import OKXAdapter, OKXPublicAdapter
from astra_backend.sandbox.adapter import SandboxExchangeAdapter

_ADAPTERS: Dict[str, type] = {
    "okx": OKXAdapter,
}

# 经「适配器」下单的场所开闸——单一事实 = 各所能力表 ``adapter_execution_flag`` 声明
# （okx 实盘执行走 ai_factor_trader 直签链路 → 未声明，恒关）。
# 本映射仅为向后兼容再导出保留，由能力表推导，勿再手改。
ADAPTER_EXECUTION_ENABLED: Dict[str, bool] = {}


_TRUE_VALUES = ("1", "true", "yes", "on")


def _env_on(name: str) -> bool:
    return str(os.environ.get(name, "0")).strip().lower() in _TRUE_VALUES


def _unsupported_venue(venue: str) -> ExchangeCapabilityError:
    """未登记场所的显式拒绝（fail-closed，绝不静默降级）。"""
    return ExchangeCapabilityError(
        f"未知交易所 venue={venue!r}，可用: {sorted(_ADAPTERS)}"
    )


def execution_open(venue: str, environment: str = "live") -> bool:
    """场所执行开闸的统一判定（运行时读 env，支持热切换无需改码）。

    单源判定 = 能力表 ``adapter_execution_flag`` 声明 AND 环境双轴旗标：
    - 能力表未声明旗标（OKX 实盘执行走 ai_factor_trader 直签链路）→ 结构性恒关，
      与 env 无关；
    - 已声明：live 档读声明旗标原样，沙盒档（sandbox/demo/testnet）读
      ``<前缀>DEMO_EXECUTION`` 变体——打开只放行**模拟盘真实发送**，绝不标示/
      充当 LIVE 实盘。
    单参调用 ``execution_open(venue)`` = live 档语义，逐字节兼容旧判定。
    """
    key = str(venue or "").strip().lower()
    cls = _ADAPTERS.get(key)
    base_flag = getattr(getattr(cls, "capabilities", None), "adapter_execution_flag", "")
    if not base_flag:
        return False
    if is_sandbox_environment(environment):
        return _env_on(base_flag.replace("EXECUTION", "DEMO_EXECUTION"))
    return _env_on(base_flag)


def _derive_adapter_execution_enabled() -> Dict[str, bool]:
    """由能力表推导兼容映射：仅反映「该所是否声明了 env 开闸路径」。"""
    return {v: bool(getattr(getattr(cls, "capabilities", None),
                            "adapter_execution_flag", "")) for v, cls in _ADAPTERS.items()}


ADAPTER_EXECUTION_ENABLED.update(_derive_adapter_execution_enabled())

#: US-002：缓存键 = AccountKey (venue, environment, credential_fingerprint)
_INSTANCES: Dict[AccountKey, BaseExchangeAdapter] = {}


def venue_testnet_enabled(venue: str) -> bool:
    key = str(venue or "").strip().lower()
    return str(os.environ.get(f"ASTRA_{key.upper()}_TESTNET", "0")).strip().lower() in ("1", "true", "yes", "on")


def _account_key(venue_key: str, environment: str) -> AccountKey:
    """组装三元身份键；凭证读取 fail-soft——密钥库异常按 anon，不抛穿上层。"""
    try:
        api_key, _secret = venue_credentials(venue_key, environment)
    except Exception:
        api_key = ""
    return AccountKey(venue=venue_key, environment=environment,
                      fingerprint=credential_fingerprint(api_key))


def get_adapter(venue: str, environment: Optional[str] = None) -> BaseExchangeAdapter:
    """按 AccountKey (venue, environment, credential_fingerprint) 取适配器实例。

    environment=None → 旧 ASTRA_{VENUE}_TESTNET 布尔兼容映射（见 env_profiles）。
    凭证代际入键：``venue_credentials`` 返回的 api_key 变化（轮换/清空）后
    fingerprint 失配 → 自动重建实例，旧凭证连接不残留；读取密钥库异常按
    anon 指纹降级（fail-soft，只读行情面不受牵连）。

    未登记场所（本系统已移除的场所）→ 显式 ``ExchangeCapabilityError``。
    """
    from . import env_profiles
    key = str(venue or "").strip().lower()
    if key == "sandbox":
        if "sandbox_instance" not in _INSTANCES:
            _INSTANCES["sandbox_instance"] = SandboxExchangeAdapter(environment="sandbox")
        return _INSTANCES["sandbox_instance"]
    cls = _ADAPTERS.get(key)
    if cls is None:
        raise _unsupported_venue(venue)
    env = str(environment or "").strip().lower() or env_profiles.legacy_environment_for(key)
    cache_key = _account_key(key, env)
    if cache_key not in _INSTANCES:
        _INSTANCES[cache_key] = cls(environment=env)
    return _INSTANCES[cache_key]


def adapter_environment(venue: str) -> str:
    """该场所当前布尔开关解析出的档位名（观测/诊断用，纯读）。"""
    from . import env_profiles
    return env_profiles.legacy_environment_for(str(venue or "").strip().lower())


def clear_instances() -> None:
    """档位/凭证热切换后丢弃全部 AccountKey 缓存实例，下次 get_adapter 重建。"""
    _INSTANCES.clear()


def venue_credentials(venue: str, environment: Optional[str] = None) -> Tuple[str, str]:
    """从加密密钥库读该场所 (api_key, secret_key)。

    只登记场所可答；未登记（已移除）场所**显式拒答** ``ExchangeCapabilityError``
    ——绝不静默返回空串让上层以为"未配置凭证"。

    环境维凭证档：
    - environment 归属于沙盒/模拟（demo/sandbox/testnet）时：
      优先尝试 {VENUE}_DEMO_* / {VENUE}_TESTNET_* / {VENUE}_SANDBOX_*，未配时回退通用 {VENUE}_*。
    - environment 归属于实盘（live）时：
      优先尝试 {VENUE}_LIVE_*，未配时回退通用 {VENUE}_*。
    - environment 为 None 时：回退当前默认/通用凭证。
    """
    vkey = str(venue or "").strip().lower()
    if vkey not in _ADAPTERS:
        raise _unsupported_venue(venue)
    key = vkey.upper()
    try:
        from astra_gateway.secrets import load_secrets
        vals = load_secrets()
    except Exception:
        vals = {}

    env = str(environment or "").strip().lower() if environment is not None else ""
    if env:
        # 审计 A3：按「原子凭证档」解析——key 与 secret 必须同档成对命中，绝不逐
        # 字段跨档借位（否则不同档的 key 与 secret 会拼成混合身份）。档位优先级链
        # 保持原契约（含沙盒→generic 优雅回退）。
        if is_sandbox_environment(env):
            tiers = [f"{key}_DEMO", f"{key}_TESTNET", f"{key}_SANDBOX", key]
        else:
            tiers = [f"{key}_LIVE", key]
        for tier in tiers:
            api_key = str(vals.get(f"{tier}_API_KEY") or "").strip()
            secret_key = str(vals.get(f"{tier}_SECRET_KEY") or "").strip()
            if api_key and secret_key:
                return (api_key, secret_key)
            if api_key or secret_key:
                # 该档半配：不得用另一档补齐另一半——视作该档不可用，继续下一档
                continue
        return ("", "")

    return (str(vals.get(f"{key}_API_KEY") or "").strip(), str(vals.get(f"{key}_SECRET_KEY") or "").strip())


def venue_passphrase(venue: str, environment: Optional[str] = None) -> str:
    """从加密密钥库读该场所 Passphrase（OKX 专属；其他所返回空串）。"""
    key = str(venue or "").strip().upper()
    if key != "OKX":
        return ""
    try:
        from astra_gateway.secrets import load_secrets
        vals = load_secrets()
    except Exception:
        vals = {}

    env = str(environment or "").strip().lower() if environment is not None else ""
    if env:
        if is_sandbox_environment(env):
            cand_pass = ["OKX_DEMO_PASSPHRASE", "OKX_PASSPHRASE"]
        else:
            cand_pass = ["OKX_LIVE_PASSPHRASE", "OKX_PASSPHRASE"]
        for cp in cand_pass:
            v = str(vals.get(cp) or "").strip()
            if v:
                return v
        return ""
    return str(vals.get("OKX_PASSPHRASE") or "").strip()


def registered_venues() -> list:
    return sorted(_ADAPTERS)


def is_registered(venue: str) -> bool:
    return str(venue or "").strip().lower() in _ADAPTERS


def require_execution(venue: str, environment: Optional[str] = None) -> None:
    """执行门禁：任何场所经适配器下单前先问这里。未开闸一律 fail-closed。

    environment=None → 按解析出的适配器实例档位取轴。
    拒绝文案指向**当前档位实际缺的那把开关**，不误导去开另一档。
    """
    adapter = get_adapter(venue, environment)
    cap = adapter.capabilities
    env = str(getattr(adapter, "environment", "live") or "live")
    if not execution_open(cap.venue, env):
        raise ExchangeCapabilityError(
            f"{cap.display_name}: 适配器执行未开闸。当前该场所仅提供只读行情。"
            + ("注：OKX 实盘执行走 ai_factor_trader 遗留链路，不经本路由。"
               if cap.venue == "okx" else "")
        )
    if not cap.supports_orders:
        raise ExchangeCapabilityError(f"{cap.display_name}: supports_orders=False，适配器未实装下单")


def resolve_symbol(symbol: str, venue: str) -> str:
    """canonical/任意写法 → 指定场所原生 instId。"""
    return get_adapter(venue).native_symbol(symbol)


def native_symbol_pure(symbol: str, venue: str) -> str:
    """符号翻译的**纯元数据**版本：直接读适配器类的 symbol_template 拼接，
    绝不实例化（实例化会触发沙盒档域名探测 → 出网）。

    用途：选所硬筛等只需「把 canonical 币名转成本所合约码再去 listing 目录对账」，
    不需要任何连接态。未知场所回退 canonical（不抛、不猜所）。
    """
    cls = _ADAPTERS.get(str(venue or "").strip().lower())
    template = getattr(getattr(cls, "capabilities", None), "symbol_template", "")
    if not template:
        return canonical_base(symbol)
    return template.format(base=canonical_base(symbol))
