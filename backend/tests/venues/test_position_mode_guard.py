"""持仓模式只读体检（OKX 专用化）。

凡声明了 `position_modes` 的适配器，必须实现 `detect_position_mode`，
且 OKX 仅在 long_short 模式准入开仓。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))


class OkxInterpretPositionModeTest(unittest.TestCase):
    """第一百九十三刀：OKX 持仓模式探测。

    本类钉住解释器（`/api/v5/account/config` 回包）。
    """

    def test_long_short_mode(self):
        from astra_backend.exchanges.okx import interpret_position_mode
        self.assertEqual(interpret_position_mode({"data": [{"posMode": "long_short_mode"}]}),
                         "long_short")

    def test_net_mode(self):
        from astra_backend.exchanges.okx import interpret_position_mode
        self.assertEqual(interpret_position_mode({"data": [{"posMode": "net_mode"}]}), "net")

    def test_unreadable_is_unknown_not_a_default(self):
        """读不出**绝不**给默认值（闸对 unknown 的处置是禁新开仓）。"""
        from astra_backend.exchanges.okx import interpret_position_mode
        for payload in (None, {}, {"data": []}, {"data": [None]}, {"data": "x"},
                        {"data": [{"posMode": ""}]}, {"data": [{"posMode": "??"}]},
                        {"data": [{"posMode": "LONG_SHORT"}]}):
            with self.subTest(payload=payload):
                self.assertEqual(interpret_position_mode(payload), "unknown")

    def test_accepts_bare_list_too(self):
        from astra_backend.exchanges.okx import interpret_position_mode
        self.assertEqual(interpret_position_mode([{"posMode": "net_mode"}]), "net")


class OkxDetectPositionModeTest(unittest.TestCase):
    def _adapter(self):
        from astra_backend.exchanges.okx import OKXAdapter
        ad = OKXAdapter.__new__(OKXAdapter)          # 不跑 __init__（避免读凭证/环境）
        ad._get_okx_env = lambda: None               # type: ignore[method-assign]
        return ad

    def test_reads_through_the_signed_config_endpoint(self):
        from scripts import okx_rest
        seen = {}

        def _req(method, path, params=None, **kw):
            seen["call"] = (method, path)
            return [{"posMode": "long_short_mode"}]

        original = okx_rest.request
        okx_rest.request = _req
        try:
            ad = self._adapter()
            mode = ad.detect_position_mode()
            self.assertEqual(mode, "long_short")
            self.assertEqual(seen["call"], ("GET", "/api/v5/account/config"))
        finally:
            okx_rest.request = original

    def test_endpoint_error_fails_soft_to_unknown(self):
        from scripts import okx_rest

        def _boom(*a, **k):
            raise RuntimeError("50001: simulated network drop")

        original = okx_rest.request
        okx_rest.request = _boom
        try:
            ad = self._adapter()
            self.assertEqual(ad.detect_position_mode(), "unknown",
                             "探测失败必须 fail-soft 成 unknown，绝不抛（抛了会打断整轮）")
        finally:
            okx_rest.request = original


class ModeDeclarationConsistencyTest(unittest.TestCase):
    """**声明了持仓模式却没有探测方法 = 闸静默失效**（本刀发现的正是这一形态）。

    闸的判据是 `if declared_modes and callable(probe)` ⇒ 缺探测的所**整段跳过**，
    于是"声明"看起来像有护栏，实际没有。故：凡声明了 `position_modes` 的适配器，
    必须实现 `detect_position_mode`。
    """

    def test_every_adapter_declaring_modes_can_be_probed(self):
        from astra_backend.exchanges import get_adapter, registry
        offenders = []
        for venue in registry.registered_venues():
            ad = get_adapter(venue, environment="demo")
            declared = tuple(getattr(ad.capabilities, "position_modes", ()) or ())
            if declared and not callable(getattr(ad, "detect_position_mode", None)):
                offenders.append(f"{venue} 声明了 {declared} 但没有 detect_position_mode")
        self.assertEqual(offenders, [], "声明了持仓模式却无法探测 ⇒ 模式闸对该所静默失效：\n"
                                        + "\n".join(offenders))

    def test_teeth_on_a_probe_less_declaration(self):
        """牙齿：造一个"声明了模式却没有探测"的适配器，判据必须能识别。"""

        def offenders_of(pairs):
            out = []
            for venue, (declared, has_probe) in pairs.items():
                if declared and not has_probe:
                    out.append(venue)
            return out

        self.assertEqual(offenders_of({"x": (("net",), False)}), ["x"])
        self.assertEqual(offenders_of({"x": (("net",), True)}), [])

    def test_okx_is_now_entry_ready_in_long_short(self):
        from astra_backend.exchanges import get_adapter
        caps = get_adapter("okx", environment="demo").capabilities
        self.assertEqual(tuple(caps.entry_ready_position_modes), ("long_short",))
        self.assertIn("long_short", tuple(caps.position_modes))
        self.assertNotIn("net", tuple(caps.entry_ready_position_modes),
                         "净持仓模式的载荷未核验 ⇒ 不得列为准入（保守）")


if __name__ == "__main__":
    unittest.main()
