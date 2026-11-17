"""US-002 契约测试：AccountKey 三元缓存键 + 双轴执行门禁 + routing_policy。

OKX 专用化（多所移除）后本文件的锚点：
- ``registry`` 只登记 ``okx``（外加 ``get_adapter("sandbox")`` 的合成实例），
  未登记场所（已移除的所）一律显式 ``ExchangeCapabilityError``，绝不静默降级；
- ``_INSTANCES`` 缓存键 = AccountKey(venue, environment, credential_fingerprint)；
- ``execution_open`` 双轴判定仍是**通用机制**：能力表声明 ``adapter_execution_flag``
  的场所才有闸，OKX 未声明（实盘执行走 ai_factor_trader 直签链路）⇒ 结构性恒关；
- ``routing_policy`` 只剩 ``preferred_venue`` / ``routing_mode`` 读写（多所资产池
  与 effective_mode 已随多所执行面移除）。

封闭三律：全 mock/注入，零真实网络、零真实凭证库、零生产文件。
- 凭证：patch registry.venue_credentials（_account_key 走模块全局，可钉）；
- 密钥库：绝不触达（本文件不 patch astra_gateway.secrets，因为不再有任何用例
  需要真读密钥库）。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from astra_backend.exchanges import env_profiles as ep
from astra_backend.exchanges import registry as reg
from astra_backend.exchanges import routing_policy as rp
from astra_backend.exchanges.identity import (ANON_CREDENTIAL, AccountKey,
                                            credential_fingerprint,
                                            is_sandbox_environment)

OKX_LIVE_URL = "https://www.okx.com"


def setUpModule():
    """封闭三律：排除宿主 .env 注入的 ambient ASTRA_* 旗标——环境只由用例自设。

    OKX 专用化后真正生效的旗标是 ``ASTRA_OKX_*``；``ASTRA_SHADOW_*`` 是合成
    场所（钉双轴机制用）的旗标，一并清掉避免外部环境串台。
    """
    _backup = {k: v for k, v in os.environ.items()
               if k.startswith(("ASTRA_OKX_", "ASTRA_SHADOW_"))}
    for k in _backup:
        os.environ.pop(k, None)
    _AMBIENT_BACKUP.append(_backup)


_AMBIENT_BACKUP: list = []


def tearDownModule():
    while _AMBIENT_BACKUP:
        os.environ.update(_AMBIENT_BACKUP.pop())


def _fp(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


class _IsolatedRegistryMixin(unittest.TestCase):
    """每个用例：AccountKey 缓存清空 + 密钥库空打桩（零真实凭证库、零 IO）。

    注意只钉 ``load_secrets`` 而**不**钉 ``registry.venue_credentials``：后者本身
    就是被测契约（未登记场所必须显式抛 ``ExchangeCapabilityError``）。
    """

    def setUp(self):
        reg.clear_instances()
        self.addCleanup(reg.clear_instances)
        self.enterContext(patch("astra_gateway.secrets.load_secrets",
                                return_value={}))


# ----------------------------------------------------------------------
# fingerprint 纯函数与键模型
# ----------------------------------------------------------------------
class CredentialFingerprintTest(unittest.TestCase):
    def test_sha256_prefix12(self):
        self.assertEqual(credential_fingerprint("KEY123"), _fp("KEY123"))
        self.assertEqual(len(credential_fingerprint("anything")), 12)

    def test_anon_sentinel_never_impersonates_account(self):
        self.assertEqual(credential_fingerprint(""), _fp(ANON_CREDENTIAL))
        self.assertEqual(credential_fingerprint(None), _fp(ANON_CREDENTIAL))
        self.assertEqual(credential_fingerprint("   "), _fp(ANON_CREDENTIAL))

    def test_distinct_keys_distinct_fingerprints(self):
        self.assertNotEqual(credential_fingerprint("KEY-A"),
                            credential_fingerprint("KEY-B"))

    def test_account_key_frozen_hashable_dict_key(self):
        k1 = AccountKey("okx", "live", _fp("KEY-A"))
        k2 = AccountKey("okx", "live", _fp("KEY-A"))
        self.assertEqual(k1, k2)
        self.assertEqual(hash(k1), hash(k2))
        bag = {k1: "v"}
        self.assertEqual(bag[k2], "v")
        with self.assertRaises(Exception):
            k1.venue = "sandbox"      # frozen：不可变
        self.assertIn("okx:live:", str(k1))

    def test_sandbox_environment_vocabulary(self):
        for e in ("sandbox", "demo", "testnet", "DEMO", " Sandbox "):
            self.assertTrue(is_sandbox_environment(e), e)
        for e in ("live", "", None, "mainnet"):
            self.assertFalse(is_sandbox_environment(e), e)


# ----------------------------------------------------------------------
# AccountKey 缓存隔离 / 轮换重建 / 兼容签名
# ----------------------------------------------------------------------
class AccountKeyCacheTest(_IsolatedRegistryMixin):
    def test_environment_axis_isolation_base_url_and_session(self):
        live = reg.get_adapter("okx", "live")
        demo = reg.get_adapter("okx", "demo")
        self.assertIsNot(live, demo)
        # OKX demo 是「同域 + x-simulated-trading 头」，不换域名。
        self.assertEqual(live.base_url, OKX_LIVE_URL)
        self.assertEqual(demo.base_url, OKX_LIVE_URL)
        self.assertEqual(live.environment, "live")
        self.assertEqual(demo.environment, "demo")
        # session/规格缓存互不串台
        live._session = "SESSION-LIVE"
        demo._session = "SESSION-DEMO"
        live._specs_cache["BTC-USDT-SWAP"] = "X"
        self.assertEqual(demo._session, "SESSION-DEMO")
        self.assertEqual(demo._specs_cache, {})

    def test_same_account_key_returns_cached_singleton(self):
        a = reg.get_adapter("okx", "live")
        self.assertIs(reg.get_adapter("okx", "live"), a)
        self.assertIs(reg.get_adapter(" OKX ", "LIVE"), a)   # 归一化同键

    def test_credential_rotation_rebuilds_instance(self):
        with patch.object(reg, "venue_credentials",
                          return_value=("KEY-A", "sec")) as vc:
            first = reg.get_adapter("okx", "live")
            self.assertIs(reg.get_adapter("okx", "live"), first)  # 同键命中缓存
            self.assertEqual(vc.call_count, 2)
            vc.return_value = ("KEY-B", "sec")                     # 密钥轮换
            second = reg.get_adapter("okx", "live")
            self.assertIsNot(second, first)                        # 新代际新实例
            self.assertIs(reg.get_adapter("okx", "live"), second)  # 新键命中
        # 缓存键真的含指纹：三键并存
        keys = {str(k) for k in reg._INSTANCES}
        self.assertTrue(any(k.startswith("okx:live:") for k in keys), keys)
        self.assertEqual(len([k for k in keys if k.startswith("okx:live:")]), 2)

    def test_same_key_different_environment_never_collides(self):
        live = reg.get_adapter("okx", "live")
        sandbox = reg.get_adapter("okx", "sandbox")
        self.assertIsNot(live, sandbox)
        self.assertEqual(live.base_url, OKX_LIVE_URL)
        # 沙盒别名档（sandbox/testnet）归并到 demo 档：同域 + 模拟盘头开关。
        self.assertEqual(sandbox.base_url, OKX_LIVE_URL)
        self.assertEqual(sandbox.environment, "sandbox")
        self.assertTrue(ep.get_profile("okx", "sandbox").simulated_trading)

    def test_secrets_failure_failsoft_anon_fingerprint(self):
        def boom(_venue, _environment=None):
            raise RuntimeError("密钥库不可读")
        with patch.object(reg, "venue_credentials", boom):
            ad = reg.get_adapter("okx", "live")
        key = AccountKey("okx", "live", _fp(ANON_CREDENTIAL))
        self.assertIn(key, reg._INSTANCES)   # 降级 anon 哨兵，不冒充账户
        self.assertIsNotNone(ad)

    def test_clear_instances_drops_all_generations(self):
        with patch.object(reg, "venue_credentials", return_value=("K1", "s")):
            a = reg.get_adapter("okx", "live")
            b = reg.get_adapter("okx", "demo")
        self.assertEqual(len(reg._INSTANCES), 2)
        reg.clear_instances()
        self.assertEqual(reg._INSTANCES, {})
        with patch.object(reg, "venue_credentials", return_value=("K1", "s")):
            self.assertIsNot(reg.get_adapter("okx", "live"), a)   # 重建
            self.assertIsNot(reg.get_adapter("okx", "demo"), b)

    def test_legacy_positional_calls_zero_signature_break(self):
        # 现有调用点全部 venue 单参；OKX 无旧沙盒布尔档 ⇒ 单参恒 live。
        live = reg.get_adapter("okx")                 # 位置参数
        self.assertEqual(live.base_url, OKX_LIVE_URL)
        self.assertEqual(live.environment, "live")
        # 旧布尔 ASTRA_OKX_TESTNET=1 不改变 OKX 档位（无声明档 → 维持现状）。
        with patch.dict("os.environ", {"ASTRA_OKX_TESTNET": "1"}):
            self.assertEqual(reg.get_adapter("okx").base_url, OKX_LIVE_URL)
            self.assertEqual(reg.adapter_environment("okx"), "live")
        self.assertEqual(reg.resolve_symbol("BTC-USDT-SWAP", "okx"), "BTC-USDT-SWAP")

    def test_clear_instances_hot_switch_semantics_preserved(self):
        # 后台保存路由后 clear_instances 热切换。三元键下「环境轴或凭证代际变化」
        # 天然生成新键新实例；clear 仍承担全量作废——旧语义保留不放松。
        before = reg.get_adapter("okx", "live")
        self.assertIs(reg.get_adapter("okx", "live"), before)   # 同键必命中缓存
        hot = reg.get_adapter("okx", "demo")                    # 轴变→键变→新实例
        self.assertIsNot(hot, before)
        self.assertEqual(hot.environment, "demo")
        self.assertEqual(hot.base_url, OKX_LIVE_URL)
        reg.clear_instances()
        after = reg.get_adapter("okx", "demo")                  # 清后重建同档
        self.assertIsNot(after, hot)
        self.assertEqual(after.environment, "demo")

    def test_removed_venues_are_rejected_and_read_only_rows_tolerated(self):
        # 已移除场所：执行/凭证面显式拒绝……
        for gone in ("binance", "gate"):
            with self.subTest(venue=gone):
                self.assertFalse(reg.is_registered(gone))
                with self.assertRaises(reg.ExchangeCapabilityError):
                    reg.get_adapter(gone)
                with self.assertRaises(reg.ExchangeCapabilityError):
                    reg.venue_credentials(gone)
        self.assertEqual(reg.registered_venues(), ["okx"])
        # ……但**只读**符号翻译（历史台账行消费面）不得崩，回退 canonical。
        self.assertEqual(reg.native_symbol_pure("BTC-USDT-SWAP", "binance"), "BTC")


# ----------------------------------------------------------------------
# execution_open / require_execution 门禁
# ----------------------------------------------------------------------
class _SyntheticGateAdapter:
    """合成场所：钉住 ``execution_open`` 的**通用双轴**机制。

    当前真实注册表只有 OKX，而 OKX 能力表未声明 ``adapter_execution_flag``
    （实盘执行走 ai_factor_trader 直签链路）⇒ 双轴分支没有真实场所可触发。
    用合成场所把它钉住，避免 live/sandbox 互不越权的判定变成无覆盖的死代码。
    """

    capabilities = SimpleNamespace(
        venue="shadow",
        display_name="Shadow 合成场所",
        supports_orders=True,
        adapter_execution_flag="ASTRA_SHADOW_EXECUTION",
    )

    def __init__(self, environment="live"):
        self.environment = environment


class ExecutionGateMatrixTest(unittest.TestCase):
    SHADOW = "ASTRA_SHADOW_EXECUTION"
    SHADOW_DEMO = "ASTRA_SHADOW_DEMO_EXECUTION"

    def setUp(self):
        reg.clear_instances()
        self.addCleanup(reg.clear_instances)
        self.enterContext(patch.dict(reg._ADAPTERS, {"shadow": _SyntheticGateAdapter},
                                     clear=False))

    def _flag(self, live=None, demo=None):
        env = {}
        if live is not None:
            env[self.SHADOW] = live
        if demo is not None:
            env[self.SHADOW_DEMO] = demo
        return patch.dict("os.environ", env, clear=False)

    def test_default_both_axes_closed(self):
        with self._flag("0", "0"):
            self.assertFalse(reg.execution_open("shadow"))            # 单参=live
            self.assertFalse(reg.execution_open("shadow", "live"))
            self.assertFalse(reg.execution_open("shadow", "sandbox"))
            self.assertFalse(reg.execution_open("shadow", "demo"))

    def test_live_flag_does_not_open_sandbox(self):
        with self._flag("1", "0"):
            self.assertTrue(reg.execution_open("shadow", "live"))
            self.assertFalse(reg.execution_open("shadow", "sandbox"))  # 互不越权

    def test_sandbox_flag_does_not_open_live(self):
        with self._flag("0", "1"):
            self.assertTrue(reg.execution_open("shadow", "demo"))
            self.assertTrue(reg.execution_open("shadow", "testnet"))
            self.assertTrue(reg.execution_open("shadow", "SANDBOX"))   # 归一化
            self.assertFalse(reg.execution_open("shadow"))             # live 仍关

    def test_demo_flag_default_zero_when_unset(self):
        # AC：沙盒闸默认 0——变量完全未设置亦视为关
        saved = {k: os.environ.pop(k, None) for k in (self.SHADOW, self.SHADOW_DEMO)}
        try:
            self.assertFalse(reg.execution_open("shadow"))            # live 默认关
            self.assertFalse(reg.execution_open("shadow", "demo"))    # 沙盒默认关
            self.assertFalse(reg.execution_open("shadow", "testnet"))
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v

    def test_okx_declares_no_gate_axis_so_stays_structurally_closed(self):
        # OKX 未声明 adapter_execution_flag ⇒ 无论怎么设环境旗标都不开闸。
        with patch.dict("os.environ", {"ASTRA_OKX_EXECUTION": "1",
                                       "ASTRA_OKX_DEMO_EXECUTION": "1"}):
            for env in ("live", "demo", "sandbox", "testnet"):
                with self.subTest(environment=env):
                    self.assertFalse(reg.execution_open("okx", env))
            self.assertFalse(reg.execution_open("okx"))

    def test_removed_venues_are_closed_and_rejected(self):
        with self._flag("1", "1"):
            for gone in ("binance", "gate"):
                with self.subTest(venue=gone):
                    self.assertFalse(reg.execution_open(gone))
                    self.assertFalse(reg.execution_open(gone, "demo"))
                    with self.assertRaises(reg.ExchangeCapabilityError):
                        reg.get_adapter(gone)
        # 合成场所只在本人用例内登记，真实注册表仍是 OKX 专用（见 AccountKeyCacheTest）。

    def test_require_execution_okx_message_points_at_read_only_reality(self):
        with patch.object(reg, "venue_credentials", return_value=("", "")):
            with self.assertRaises(reg.ExchangeCapabilityError) as cm:
                reg.require_execution("okx")
            msg = str(cm.exception)
            self.assertIn("只读行情", msg)
            # OKX 实盘走直签链路，拒绝文案必须点明，不能诱导去开一把不存在的闸。
            self.assertIn("ai_factor_trader", msg)
            self.assertNotIn("ASTRA_", msg)
            # 未登记场所先于门禁显式拒答（fail-closed，绝不静默）。
            with self.assertRaises(reg.ExchangeCapabilityError) as cm2:
                reg.require_execution("gate")
        self.assertIn("未知交易所", str(cm2.exception))


# ----------------------------------------------------------------------
# routing_policy：保留面（preferred_venue / routing_mode 读写）
# ----------------------------------------------------------------------
class RoutingPolicyConfigTest(unittest.TestCase):
    """多所资产池与 ``effective_mode`` 双轴已随多所执行面移除，本类只钉保留面。

    ``VALID_PREFERRED_VENUES`` 由注册表派生 ⇒ OKX 专用化后只剩 ``auto`` + ``okx``，
    已移除场所既不可读、也不可写。
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.file = Path(self._tmp.name) / "venue_routing.json"
        self.enterContext(patch.object(rp, "ROUTING_FILE", self.file))

    def test_valid_preferred_venues_are_okx_only(self):
        self.assertEqual(rp.VALID_PREFERRED_VENUES, ("auto", "okx"))

    def test_removed_venue_is_rejected_and_never_written(self):
        for gone in ("binance", "gate"):
            with self.subTest(venue=gone):
                self.assertFalse(rp.save_preferred_venue(gone))
        self.assertFalse(self.file.exists(), "非法场所不得落盘")

    def test_missing_file_falls_back_to_auto(self):
        self.assertEqual(rp.load_preferred_venue(), "auto")

    def test_preferred_venue_roundtrip(self):
        self.assertTrue(rp.save_preferred_venue("okx"))
        self.assertEqual(rp.load_preferred_venue(), "okx")

    def test_corrupt_file_never_raises_and_falls_back(self):
        self.file.write_text("{ corrupt", encoding="utf-8")
        self.assertEqual(rp.load_preferred_venue(), "auto")
        self.assertEqual(rp.load_routing_mode(), "balanced")

    def test_removed_venue_value_in_file_falls_back_to_auto(self):
        # 历史配置文件里的已移除场所值 → fail-safe 回 auto，绝不猜所、绝不崩。
        self.file.write_text(json.dumps({"preferred_venue": "binance"}),
                             encoding="utf-8")
        self.assertEqual(rp.load_preferred_venue(), "auto")

    def test_routing_mode_roundtrip_and_illegal_rejection(self):
        self.assertTrue(rp.save_routing_mode("split"))
        self.assertEqual(rp.load_routing_mode(), "split")
        self.assertFalse(rp.save_routing_mode("nonsense"))
        self.assertEqual(rp.load_routing_mode(), "split")


if __name__ == "__main__":
    unittest.main()
