"""聪明钱单源采集（factors/smart_money.py）收口 —— 第 310 刀（OKX 专用化修订）。

多所移除后本模块只剩**单源**：OKX Rubik 公开统计端点，不存在任何备源链
（``_fetch_from_binance`` 已随多所执行面一并删除）。

本模块的**全部价值**在模块 docstring 的第 2 条：

> 数据源不可用时优雅返回 `None`，保留**显式缺失语义，绝不伪造虚假中性信号**。

这条不是修辞 —— 下游 `brain/packages.py` 的 `smart_money.available` 就是据此判断的，
而提示词里对"数据源缺失"与"多空均衡"给出的是**完全不同**的指令
（前者明写"本项不构成任何方向的证据，禁止臆测填充"）。所以本刀第一条就是把这个
"取不到就得说取不到"的边界钉死。

第二条钉的是 OKX 路径的口径：taker 是**合约张数差**、**不乘价格** —— 不是笔误，
是被保留的既有行为，但必须写进测试，否则下一个人"顺手补上 price"就会静默改变
产出的数字含义。
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from scripts.factors import smart_money as sm  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


OKX_POS_RATIO = {"code": "0", "data": [["t", "1.63"]]}
OKX_TAKER = {"code": "0", "data": [["t", "30000", "10000"]]}


class _HttpMixin:
    def setUp(self):
        self.urls: list[str] = []

    def _opener(self, routes):
        def opener(req, timeout=None):
            url = req.full_url
            self.urls.append(url)
            for key, value in routes.items():
                if key in url:
                    if isinstance(value, Exception):
                        raise value
                    return _Resp(value)
            raise AssertionError(f"未路由的 URL: {url}")
        return opener

    def _run(self, routes, ccy="BTC", **kw):
        with patch.object(sm.urllib.request, "urlopen", self._opener(routes)):
            return sm.fetch_smart_money_for_symbol(ccy, price=100.0, **kw)


class SourcePreferenceTests(_HttpMixin, unittest.TestCase):
    """★ OKX Rubik 单源：命中即返回、取不到即 None（无备源链可兜底）。"""

    def test_okx_rubik_is_the_only_source_queried(self):
        res = self._run({"long-short-pos-ratio": OKX_POS_RATIO,
                         "taker-volume": OKX_TAKER})
        self.assertEqual(res["lsRatio"], 1.63)
        self.assertAlmostEqual(res["weighted_long_pct"], 62.0)
        self.assertTrue(all("okx.com" in u for u in self.urls), self.urls)

    def test_single_source_down_returns_none_not_a_neutral_stub(self):
        # ★★ 模块 docstring 第 2 条：**绝不伪造虚假中性信号**
        res = self._run({"okx.com": OSError("down")})
        self.assertIsNone(res)
        # 反证：返回的不能是一个"看起来中性"的完整字典
        self.assertNotIsInstance(res, dict)

    def test_result_without_long_short_ratio_returns_none(self):
        # 判据是 `res and res.get("longShortRatio")` —— 真值 + 键存在，两者都要
        with patch.object(sm, "_fetch_from_okx_rubik", lambda *a, **k: {"notional": {}}):
            self.assertIsNone(sm.fetch_smart_money_for_symbol("BTC"))

    def test_truthy_result_with_long_short_ratio_is_returned_verbatim(self):
        payload = {"longShortRatio": {"weightedLongRatio": 0.5}}
        with patch.object(sm, "_fetch_from_okx_rubik", lambda *a, **k: payload):
            self.assertIs(sm.fetch_smart_money_for_symbol("BTC"), payload)

    def test_no_fallback_source_hook_remains(self):
        # 多所移除后不存在任何备源 `_fetch_from_*`：单源失败即 None，绝不换所重试。
        self.assertFalse(hasattr(sm, "_fetch_from_binance"))

    def test_blank_currency_short_circuits_without_any_request(self):
        for ccy in ("", "   ", None):
            with self.subTest(ccy=ccy):
                self.urls = []
                self.assertIsNone(self._run({}, ccy))
                self.assertEqual(self.urls, [], "空币种不许发请求")


class OkxRubikSourceTests(_HttpMixin, unittest.TestCase):
    def _okx(self, routes, price=0.0):
        with patch.object(sm.urllib.request, "urlopen", self._opener(routes)):
            return sm._fetch_from_okx_rubik("BTC", price=price)

    def test_position_ratio_is_tried_first_and_derives_weighted_long(self):
        res = self._okx({"long-short-pos-ratio": {"code": "0", "data": [["t", "3.0"]]}})
        # 3.0 / (1 + 3.0) = 0.75
        self.assertEqual(res["longShortRatio"]["weightedLongRatio"], 0.75)
        self.assertEqual(res["lsRatio"], 3.0)

    def test_account_ratio_is_the_fallback_endpoint(self):
        res = self._okx({"long-short-pos-ratio": {"code": "0", "data": []},
                         "long-short-account-ratio": {"code": "0", "data": [["t", "1.0"]]}})
        self.assertEqual(res["lsRatio"], 1.0)
        self.assertTrue(any("long-short-account-ratio" in u for u in self.urls))

    def test_none_when_both_ratio_endpoints_fail(self):
        self.assertIsNone(self._okx({"long-short-pos-ratio": OSError("x"),
                                     "long-short-account-ratio": OSError("x")}))

    def test_nonzero_code_is_not_parsed(self):
        self.assertIsNone(self._okx({"long-short-pos-ratio": {"code": "51001", "data": [["t", "2"]]},
                                     "long-short-account-ratio": {"code": "51001", "data": []}}))

    def test_taker_net_is_the_bare_difference_never_multiplied_by_price(self):
        # ★★ OKX 口径：taker 是**合约张数差**，**不乘价格**（既有行为，不是笔误）。
        #    钉住它以免被"顺手统一"成金额加权口径。
        res = self._okx({"long-short-pos-ratio": {"code": "0", "data": [["t", "3.0"]]},
                         "taker-volume": {"code": "0", "data": [["t", "30000", "10000"]]}},
                        price=100.0)
        self.assertEqual(res["notional"]["netNotionalUsdt"], 20000.0)
        self.assertEqual(res["takerNetUsd"], "2.0万 U")

    def test_taker_uses_the_second_and_third_columns(self):
        res = self._okx({"long-short-pos-ratio": {"code": "0", "data": [["t", "1.0"]]},
                         "taker-volume": {"code": "0", "data": [["t", "600", "100"]]}})
        self.assertEqual(res["notional"]["netNotionalUsdt"], 500.0)
        # 小额分支走 `round(x, 0)` ⇒ float ⇒ 带 ".0"
        self.assertEqual(res["takerNetUsd"], "500.0 U")

    def test_taker_failure_leaves_the_placeholder(self):
        res = self._okx({"long-short-pos-ratio": {"code": "0", "data": [["t", "3.0"]]},
                         "taker-volume": OSError("x")})
        self.assertEqual(res["takerNetUsd"], "--")
        self.assertEqual(res["notional"]["netNotionalUsdt"], 0.0)

    def test_long_short_ratio_is_not_derived_when_the_exchange_gave_one(self):
        # OKX 把交易所给的比值**原样**放进 longShortRatio（不做推导）。
        res = self._okx({"long-short-pos-ratio": {"code": "0", "data": [["t", "2.5"]]}})
        self.assertEqual(res["longShortRatio"],
                         {"weightedLongRatio": res["longShortRatio"]["weightedLongRatio"],
                          "longShortRatio": 2.5})

    def test_returned_keys_match_the_contract(self):
        res = self._okx({"long-short-pos-ratio": {"code": "0", "data": [["t", "3.0"]]}})
        self.assertEqual(set(res), {"longShortRatio", "notional", "winRate",
                                    "takerNetUsd", "lsRatio", "weighted_long_pct"})

    def test_price_argument_does_not_affect_anything_here(self):
        # 显式钉住：该函数收了 price 但**从不使用** —— 上面那条口径的来源
        a = self._okx({"long-short-pos-ratio": {"code": "0", "data": [["t", "3.0"]]}}, price=1.0)
        b = self._okx({"long-short-pos-ratio": {"code": "0", "data": [["t", "3.0"]]}}, price=99999.0)
        self.assertEqual(a, b)


class PoolTests(unittest.TestCase):
    """池采集：并发 + **只保留真正取到的**（取不到的不许留成 None 占位）。"""

    def _pool(self, instruments, results, **kw):
        seen = []

        def fake(ccy, price=0.0, *, timeout=3.5):
            seen.append((ccy, price, timeout))
            return results.get(ccy)

        with patch.object(sm, "fetch_smart_money_for_symbol", fake):
            out = sm.fetch_smart_money_pool(instruments, **kw)
        return out, seen

    def test_empty_instrument_list_returns_an_empty_pool(self):
        out, seen = self._pool([], {})
        self.assertEqual(out, {})
        self.assertEqual(seen, [], "空池不许建线程池、不许发请求")

    def test_currency_is_taken_from_ccy_then_name_then_inst_id(self):
        instruments = [{"ccy": "BTC"}, {"name": "ETH"}, {"instId": "SOL-USDT-SWAP"}]
        out, seen = self._pool(instruments, {"BTC": {"a": 1}, "ETH": {"a": 1},
                                             "SOL": {"a": 1}})
        self.assertEqual(sorted(c for c, _, _ in seen), ["BTC", "ETH", "SOL"])
        self.assertEqual(sorted(out), ["BTC", "ETH", "SOL"])

    def test_inst_id_without_a_dash_yields_an_empty_currency(self):
        out, seen = self._pool([{"instId": "WEIRD"}], {"": {"a": 1}})
        self.assertEqual(seen[0][0], "")
        self.assertEqual(out, {}, "空币种的结果不许进池")

    def test_failed_symbols_are_omitted_not_stored_as_none(self):
        # ★★ "保留显式缺失语义"：取不到就是**没有这个键**，
        #    而不是 `{"DOGE": None}`（后者会让下游以为"查过了，是中性"）
        out, _ = self._pool([{"ccy": "BTC"}, {"ccy": "DOGE"}], {"BTC": {"a": 1}})
        self.assertEqual(out, {"BTC": {"a": 1}})
        self.assertNotIn("DOGE", out)

    def test_a_falsy_result_is_also_omitted(self):
        out, _ = self._pool([{"ccy": "BTC"}], {"BTC": {}})
        self.assertEqual(out, {})

    def test_price_is_forwarded_as_a_float(self):
        _, seen = self._pool([{"ccy": "BTC", "price": "123.5"}], {"BTC": {"a": 1}})
        self.assertEqual(seen[0][1], 123.5)

    def test_missing_price_becomes_zero(self):
        _, seen = self._pool([{"ccy": "BTC"}], {"BTC": {"a": 1}})
        self.assertEqual(seen[0][1], 0.0)

    def test_timeout_is_forwarded(self):
        _, seen = self._pool([{"ccy": "BTC"}], {"BTC": {"a": 1}}, timeout=9.5)
        self.assertEqual(seen[0][2], 9.5)

    def test_workers_are_capped_by_the_instrument_count(self):
        # `min(max_workers, len(instruments))` —— 单标的池不该开 6 个线程
        with patch.object(sm, "ThreadPoolExecutor") as pool:
            pool.return_value.__enter__.return_value.map.return_value = iter([])
            sm.fetch_smart_money_pool([{"ccy": "BTC"}], max_workers=6)
        pool.assert_called_once_with(max_workers=1)

    def test_workers_use_the_requested_value_when_instruments_are_plenty(self):
        items = [{"ccy": f"C{i}"} for i in range(10)]
        with patch.object(sm, "ThreadPoolExecutor") as pool:
            pool.return_value.__enter__.return_value.map.return_value = iter([])
            sm.fetch_smart_money_pool(items, max_workers=3)
        pool.assert_called_once_with(max_workers=3)

    def test_real_concurrency_collects_every_symbol(self):
        # 不打桩线程池：真跑一次并发，确认结果与串行等价
        instruments = [{"ccy": c, "name": c} for c in ("BTC", "ETH", "SOL", "DOGE", "XRP")]
        payload = {"longShortRatio": {"weightedLongRatio": 0.6}, "winRate": {}}
        out, _ = self._pool(instruments, {c: dict(payload) for c in
                                          ("BTC", "ETH", "SOL", "DOGE", "XRP")})
        self.assertEqual(sorted(out), ["BTC", "DOGE", "ETH", "SOL", "XRP"])


if __name__ == "__main__":
    unittest.main()
