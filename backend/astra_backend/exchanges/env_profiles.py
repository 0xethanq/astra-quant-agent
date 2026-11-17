"""(venue, environment) → 端点环境 profile（OKX 专用）。

事实源：OKX V5 的 demo 是「同域 + x-simulated-trading 头」开关（独立 Demo Key
另论），不属域名切换——profile 用 ``simulated_trading`` 位结构性表达。

钉死铁律（本文件契约，测试逐条钉）：
1. 端点档唯一解析入口，任何调用方不得自行拼域名；
2. 未知 (venue, environment) 档 → 显式 ``ExchangeCapabilityError``，绝不回退；
3. 公共行情容灾（OKX www→aws 等）在适配器内部，属只读面，不在本文件范围。
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Tuple

from .base import ExchangeCapabilityError


@dataclass(frozen=True)
class EnvProfile:
    venue: str
    environment: str                 # live | demo | testnet | sandbox
    urls: Tuple[str, ...]            # 该档的候选域（OKX 为单域）
    simulated_trading: bool = False  # OKX demo 同域头开关

    @property
    def needs_probe(self) -> bool:
        return len(self.urls) > 1


PROFILES: Dict[Tuple[str, str], EnvProfile] = {
    ("okx", "live"): EnvProfile("okx", "live", ("https://www.okx.com",)),
    ("okx", "demo"): EnvProfile("okx", "demo", ("https://www.okx.com",), simulated_trading=True),
}

#: ASTRA_{VENUE}_TESTNET=1 旧布尔开关 → 沙盒档映射（US-001 兼容层）。
#: OKX 无旧沙盒档——flag 对其维持现状无效果（live_url 未声明，base 不动）。
LEGACY_FLAG_ENV: Dict[str, str] = {}

_TRUE = ("1", "true", "yes", "on")


def has_env(venue: str, environment: str) -> bool:
    vkey = str(venue).lower()
    ekey = str(environment).lower()
    if (vkey, ekey) in PROFILES:
        return True
    from .identity import is_sandbox_environment
    if is_sandbox_environment(ekey):
        return any((vkey, candidate) in PROFILES for candidate in ("demo", "sandbox", "testnet"))
    return False


def get_profile(venue: str, environment: str) -> EnvProfile:
    vkey = str(venue).lower()
    ekey = str(environment).lower()
    prof = PROFILES.get((vkey, ekey))
    if prof is None:
        # 沙盒环境名别名兼容（demo / sandbox / testnet 自动对齐）
        from .identity import is_sandbox_environment
        if is_sandbox_environment(ekey):
            for candidate in ("demo", "sandbox", "testnet"):
                if (vkey, candidate) in PROFILES:
                    return PROFILES[(vkey, candidate)]
        raise ExchangeCapabilityError(
            f"未知环境档 venue={venue!r} environment={environment!r}"
            f"，可用: {sorted(PROFILES)}")
    return prof


def environments_of(venue: str) -> List[str]:
    return sorted(env for (v, env) in PROFILES if v == str(venue).lower())


def resolve_base_url(venue: str, environment: str) -> str:
    """(venue, environment) → 唯一 base_url（未知档显式拒绝，绝不回退）。"""
    return get_profile(venue, environment).urls[0]


def legacy_environment_for(venue: str) -> str:
    """ASTRA_{VENUE}_TESTNET 布尔 → 档位名（无声明档 → 维持 live 现状）。"""
    vkey = str(venue or "").strip().lower()
    on = str(os.environ.get(f"ASTRA_{vkey.upper()}_TESTNET", "0")).strip().lower() in _TRUE
    if not on:
        return "live"
    env = LEGACY_FLAG_ENV.get(vkey)
    if env and has_env(vkey, env):
        return env
    return "live"
