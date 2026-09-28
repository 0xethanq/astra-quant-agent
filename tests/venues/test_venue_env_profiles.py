"""OKX 契约测试：环境 profile（同域 + simulated_trading 头开关）、别名对齐、
未知档 fail-closed、注册表 (venue, environment) 分键缓存。

封闭三律：全部 mock/注入，零真实网络、零真实文件。
OKX 专用化后多所 profile（binance/gate）与探测持久化机制已随多所拆除整体移除。
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from astra_backend.exchanges import env_profiles as ep
from astra_backend.exchanges import registry as reg
from astra_backend.exchanges.base import ExchangeCapabilityError
from astra_backend.exchanges.okx import OKXPublicAdapter


_ENV_GUARD = None


def setUpModule():
    """封闭三律：清掉宿主 .env 注入的 ASTRA_* 旗标（config.load_dotenv 在 import 时
    写入 os.environ），本模块测试不得依赖真实环境变量。"""
    global _ENV_GUARD
    import os as _os
    ambient = {k: "0" for k in _os.environ
               if k.startswith(("ASTRA_OKX_ENV", "ASTRA_OKX_TESTNET"))}
    _ENV_GUARD = patch.dict(_os.environ, ambient, clear=False)
    _ENV_GUARD.start()


def tearDownModule():
    if _ENV_GUARD is not None:
        _ENV_GUARD.stop()


class ProfileTableTest(unittest.TestCase):
    """审计 §2 事实钉：OKX 同域 + 头开关位；未知档绝不回退。"""

    def test_okx_demo_same_domain_simulated_bit(self):
        live = ep.get_profile("okx", "live")
        demo = ep.get_profile("okx", "demo")
        self.assertEqual(live.urls, demo.urls)             # 同域
        self.assertTrue(demo.simulated_trading)            # 头开关位（结构表达）
        self.assertFalse(live.simulated_trading)

    def test_only_okx_profiles_are_registered(self):
        self.assertEqual(sorted(ep.PROFILES), [("okx", "demo"), ("okx", "live")])
        self.assertEqual(ep.resolve_base_url("okx", "live"), "https://www.okx.com")
        self.assertEqual(ep.resolve_base_url("okx", "demo"), "https://www.okx.com")

    def test_unknown_environment_fail_closed(self):
        with self.assertRaises(ExchangeCapabilityError):
            ep.get_profile("okx", "mainnet")
        with self.assertRaises(ExchangeCapabilityError):
            ep.resolve_base_url("okx", "mainnet")

    def test_sandbox_alias_compatibility_has_env(self):
        # 注册档为 demo，传入 sandbox/testnet 别名必须被 has_env 认可并对齐同一 profile
        self.assertTrue(ep.has_env("okx", "demo"))
        self.assertTrue(ep.has_env("okx", "sandbox"))
        self.assertTrue(ep.has_env("okx", "testnet"))
        self.assertFalse(ep.has_env("okx", "unknown"))
        self.assertEqual(ep.get_profile("okx", "sandbox").urls,
                         ep.get_profile("okx", "demo").urls)

    def test_environments_of_okx(self):
        self.assertEqual(ep.environments_of("okx"), ["demo", "live"])
        self.assertEqual(ep.environments_of("unknown_venue"), [])


class LegacyFlagCompatTest(unittest.TestCase):
    """ASTRA_OKX_TESTNET 旧布尔开关无声明档 → 维持 live 现状，语义不破坏。"""

    def test_default_is_live_without_flag(self):
        import os
        env = {k: v for k, v in os.environ.items()
               if "TESTNET" not in k.upper()}
        with patch.dict("os.environ", env, clear=True):
            ad = OKXPublicAdapter()
        self.assertEqual(ad.base_url, "https://www.okx.com")
        self.assertEqual(ad.environment, "live")

    def test_okx_flag_has_no_effect_structurally(self):
        # OKX 从未声明沙盒适配器档：flag 开也维持 live（与旧实现一致）
        with patch.dict("os.environ", {"ASTRA_OKX_TESTNET": "1"}):
            ad = OKXPublicAdapter()
        self.assertEqual(ad.base_url, "https://www.okx.com")
        self.assertEqual(ep.legacy_environment_for("okx"), "live")

    def test_explicit_environment_wins_over_flag(self):
        with patch.dict("os.environ", {"ASTRA_OKX_TESTNET": "1"}):
            ad = OKXPublicAdapter(environment="demo")
        self.assertEqual(ad.environment, "demo", "显式档位优先于旧布尔开关解析")
        self.assertEqual(ad.base_url, "https://www.okx.com")


class RegistryEnvKeyingTest(unittest.TestCase):
    """registry：(venue, environment) 分键缓存，默认档与显式档并存不互串。"""

    def setUp(self):
        reg.clear_instances()
        self.addCleanup(reg.clear_instances)

    def test_okx_live_and_demo_separated(self):
        live_ad = reg.get_adapter("okx")                    # 默认 live
        demo_ad = reg.get_adapter("okx", "demo")            # 显式模拟盘档
        self.assertEqual(live_ad.environment, "live")
        self.assertEqual(demo_ad.environment, "demo")
        self.assertIs(live_ad, reg.get_adapter("okx"))      # 缓存命中
        self.assertIsNot(live_ad, demo_ad)

    def test_legacy_flag_via_registry(self):
        with patch.dict("os.environ", {"ASTRA_OKX_TESTNET": "1"}):
            ad = reg.get_adapter("okx")
            self.assertEqual(ad.environment, "live")
            self.assertEqual(reg.adapter_environment("okx"), "live")


class OkxOnlyRegistryTest(unittest.TestCase):
    """OKX 专用注册表：未登记（已移除）场所显式拒答，绝不静默降级。"""

    def test_registered_venues_is_okx_only(self):
        self.assertEqual(reg.registered_venues(), ["okx"])

    def test_removed_venues_are_rejected(self):
        for venue in ("binance", "gate"):
            with self.subTest(venue=venue):
                with self.assertRaises(ExchangeCapabilityError):
                    reg.get_adapter(venue)
                with self.assertRaises(ExchangeCapabilityError):
                    reg.venue_credentials(venue)


if __name__ == "__main__":
    unittest.main()
