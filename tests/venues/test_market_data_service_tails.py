"""行情数据服务（`scripts/market_data_service.py`）的分支收口（OKX 专用）。

覆盖：
- OKX 双域直连（GET / POST）
- 批量行情 / 深度
- 本地指标数学计算
- 批量与单指标获取（MCP + 本地数学兜底）
- 蜡烛获取与边界限制
- 资金费率与持仓量获取
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import scripts.market_data_service as mds  # noqa: E402


def _http(status=200, payload=None, *, json_exc=None):
    resp = MagicMock()
    resp.status_code = status
    if json_exc is not None:
        resp.json.side_effect = json_exc
    else:
        resp.json.return_value = payload if payload is not None else {"code": "0", "data": []}
    return resp


def _candles(n=80, start=100.0):
    """升序蜡烛（OKX 契约是「最新在前」，本模块内部会 reverse）。"""
    return [[str(i), str(start + i), str(start + i + 1), str(start + i - 1),
             str(start + i), "10", "10", "10", "1"] for i in range(n)]


# ───────────────────── OKX 双域直连 ─────────────────────
class PublicGetTests(unittest.TestCase):
    def test_primary_host_used_when_it_works(self):
        sess = MagicMock()
        sess.get.return_value = _http(payload={"code": "0", "data": [1]})
        with patch.object(mds, "get_market_session", return_value=sess):
            out = mds._public_get("/api/v5/x")
        self.assertEqual(out["data"], [1])
        self.assertTrue(sess.get.call_args.args[0].startswith(mds.OKX_PUBLIC_HOSTS[0]))

    def test_secondary_host_tried_when_primary_returns_bad_status(self):
        sess = MagicMock()
        sess.get.side_effect = [
            _http(status=500),
            _http(status=200, payload={"code": "0", "data": ["sec"]}),
        ]
        with patch.object(mds, "get_market_session", return_value=sess):
            out = mds._public_get("/api/v5/x")
        self.assertEqual(out["data"], ["sec"])
        self.assertTrue(sess.get.call_args_list[1].args[0].startswith(mds.OKX_PUBLIC_HOSTS[1]))

    def test_secondary_host_tried_when_primary_raises(self):
        sess = MagicMock()
        sess.get.side_effect = [
            RuntimeError("conn drop"),
            _http(status=200, payload={"code": "0", "data": ["sec"]}),
        ]
        with patch.object(mds, "get_market_session", return_value=sess):
            out = mds._public_get("/api/v5/x")
        self.assertEqual(out["data"], ["sec"])

    def test_secondary_host_tried_when_primary_has_bad_json(self):
        sess = MagicMock()
        sess.get.side_effect = [
            _http(status=200, json_exc=ValueError("bad json")),
            _http(status=200, payload={"code": "0", "data": ["sec"]}),
        ]
        with patch.object(mds, "get_market_session", return_value=sess):
            out = mds._public_get("/api/v5/x")
        self.assertEqual(out["data"], ["sec"])

    def test_all_hosts_failing_yields_none(self):
        sess = MagicMock()
        sess.get.side_effect = [RuntimeError("p-drop"), RuntimeError("s-drop")]
        with patch.object(mds, "get_market_session", return_value=sess):
            self.assertIsNone(mds._public_get("/api/v5/x"))

    def test_non_zero_code_yields_none(self):
        sess = MagicMock()
        sess.get.return_value = _http(payload={"code": "50001", "msg": "err"})
        with patch.object(mds, "get_market_session", return_value=sess):
            self.assertIsNone(mds._public_get("/api/v5/x"))

    def test_non_dict_json_payload_yields_none(self):
        sess = MagicMock()
        sess.get.return_value = _http(payload=["not", "a", "dict"])
        with patch.object(mds, "get_market_session", return_value=sess):
            self.assertIsNone(mds._public_get("/api/v5/x"))


class PublicPostTests(unittest.TestCase):
    def test_primary_host_used_when_it_works(self):
        sess = MagicMock()
        sess.post.return_value = _http(payload={"code": "0", "data": ["ok"]})
        with patch.object(mds, "get_market_session", return_value=sess):
            out = mds._public_post("/api/v5/x", {"a": 1})
        self.assertEqual(out["data"], ["ok"])

    def test_a_json_content_type_header_is_sent(self):
        sess = MagicMock()
        sess.post.return_value = _http(payload={"code": "0", "data": []})
        with patch.object(mds, "get_market_session", return_value=sess):
            mds._public_post("/api/v5/x", {"a": 1})
        self.assertEqual(sess.post.call_args.kwargs["headers"]["Content-Type"],
                         "application/json")


# ───────────────────── 公开取数入口 ─────────────────────
class FetchTickersBulkTests(unittest.TestCase):
    def test_a_good_response_is_keyed_by_inst_id(self):
        with patch.object(mds, "_public_get", return_value={"data": [
                {"instId": "BTC-USDT-SWAP", "last": "1"},
                {"instId": "ETH-USDT-SWAP", "last": "2"}]}):
            out = mds.fetch_tickers_bulk()
        self.assertEqual(sorted(out), ["BTC-USDT-SWAP", "ETH-USDT-SWAP"])

    def test_a_row_without_an_inst_id_is_dropped(self):
        with patch.object(mds, "_public_get", return_value={"data": [
                {"instId": "BTC-USDT-SWAP"}, {"last": "1"}]}):
            self.assertEqual(list(mds.fetch_tickers_bulk()), ["BTC-USDT-SWAP"])

    def test_a_failure_yields_an_empty_dict(self):
        with patch.object(mds, "_public_get", return_value=None):
            self.assertEqual(mds.fetch_tickers_bulk(), {})

    def test_a_response_without_data_yields_an_empty_dict(self):
        with patch.object(mds, "_public_get", return_value={"code": "0"}):
            self.assertEqual(mds.fetch_tickers_bulk(), {})


class FetchOrderbookDepthTests(unittest.TestCase):
    def test_a_good_response_is_returned(self):
        with patch.object(mds, "_public_get", return_value={"data": [
                {"bids": [["1", "2"]], "asks": [["3", "4"]]}]}):
            self.assertEqual(mds.fetch_orderbook_depth("BTC-USDT-SWAP")["bids"], [["1", "2"]])

    def test_a_failure_yields_none(self):
        with patch.object(mds, "_public_get", return_value=None):
            self.assertIsNone(mds.fetch_orderbook_depth("BTC-USDT-SWAP"))

    def test_the_size_is_forwarded(self):
        with patch.object(mds, "_public_get", return_value={"data": [{}]}) as pg:
            mds.fetch_orderbook_depth("BTC-USDT-SWAP", sz=25)
        self.assertEqual(pg.call_args.kwargs["params"]["sz"], 25)


class LocalMathIndicatorsTests(unittest.TestCase):
    def test_no_candles_yields_an_empty_dict(self):
        with patch.object(mds, "fetch_candles", return_value=[]):
            self.assertEqual(mds._local_math_indicators("BTC-USDT-SWAP", ["ADX"]), {})

    def test_malformed_candles_yield_an_empty_dict(self):
        with patch.object(mds, "fetch_candles", return_value=[["a", "b", "c"]]):
            self.assertEqual(mds._local_math_indicators("BTC-USDT-SWAP", ["ADX"]), {})

    def test_an_index_error_in_the_candles_is_swallowed(self):
        with patch.object(mds, "fetch_candles", return_value=[["1", "2"]]):
            self.assertEqual(mds._local_math_indicators("BTC-USDT-SWAP", ["ADX"]), {})

    def test_adx_is_computed_from_enough_candles(self):
        with patch.object(mds, "fetch_candles", return_value=_candles(80)):
            out = mds._local_math_indicators("BTC-USDT-SWAP", ["ADX"])
        self.assertIn("ADX", out)
        self.assertIn("adx", out["ADX"])

    def test_too_few_candles_leaves_a_given_indicator_out(self):
        with patch.object(mds, "fetch_candles", return_value=_candles(5)):
            self.assertEqual(mds._local_math_indicators("BTC-USDT-SWAP", ["ADX"]), {})

    def test_an_unknown_indicator_is_ignored(self):
        with patch.object(mds, "fetch_candles", return_value=_candles(80)):
            self.assertEqual(mds._local_math_indicators("BTC-USDT-SWAP", ["NOPE"]), {})

    def test_a_per_indicator_failure_does_not_kill_the_others(self):
        with patch.object(mds, "fetch_candles", return_value=_candles(80)), \
             patch.object(mds, "_indicator_key", side_effect=lambda n: "ADX"):
            out = mds._local_math_indicators("BTC-USDT-SWAP", ["ADX", "ADX"])
        self.assertIn("ADX", out)


class FetchIndicatorsBatchTests(unittest.TestCase):
    def test_the_mcp_batch_result_is_used_when_present(self):
        payload = {"data": [{"data": [{"timeframes": {"1H": {"indicators": {
            "ADX": [{"values": {"adx": "20.1"}}]}}}}]}]}
        with patch.object(mds, "_public_post", return_value=payload):
            out = mds.fetch_indicators_batch("BTC-USDT-SWAP", ["ADX"])
        self.assertEqual(out["ADX"]["adx"], "20.1")

    def test_a_malformed_mcp_body_is_swallowed(self):
        with patch.object(mds, "_public_post", return_value={"data": [{"junk": 1}]}), \
             patch.object(mds, "fetch_single_indicator", return_value={}), \
             patch.object(mds, "_local_math_indicators", return_value={}):
            self.assertEqual(mds.fetch_indicators_batch("BTC-USDT-SWAP", ["ADX"]), {})

    def test_an_mcp_data_entry_without_nested_data_is_swallowed(self):
        with patch.object(mds, "_public_post", return_value={"data": [{}]}), \
             patch.object(mds, "fetch_single_indicator", return_value={}), \
             patch.object(mds, "_local_math_indicators", return_value={}):
            self.assertEqual(mds.fetch_indicators_batch("BTC-USDT-SWAP", ["ADX"]), {})

    def test_an_empty_nested_data_list_is_swallowed(self):
        with patch.object(mds, "_public_post", return_value={"data": [{"data": []}]}), \
             patch.object(mds, "fetch_single_indicator", return_value={}), \
             patch.object(mds, "_local_math_indicators", return_value={}):
            self.assertEqual(mds.fetch_indicators_batch("BTC-USDT-SWAP", ["ADX"]), {})

    def test_a_non_dict_timeframes_value_is_swallowed(self):
        with patch.object(mds, "_public_post", return_value={
                "data": [{"data": [{"timeframes": "junk"}]}]}), \
             patch.object(mds, "fetch_single_indicator", return_value={}), \
             patch.object(mds, "_local_math_indicators", return_value={}):
            self.assertEqual(mds.fetch_indicators_batch("BTC-USDT-SWAP", ["ADX"]), {})

    def test_the_rest_fallback_is_used_per_indicator(self):
        with patch.object(mds, "_public_post", return_value=None), \
             patch.object(mds, "fetch_single_indicator",
                          return_value={"adx": "1.0"}) as fs, \
             patch.object(mds, "_local_math_indicators", return_value={}):
            out = mds.fetch_indicators_batch("BTC-USDT-SWAP", ["ADX", "KDJ"])
        self.assertEqual(fs.call_count, 2)
        self.assertEqual(out["ADX"]["adx"], "1.0")

    def test_the_local_math_is_the_last_resort(self):
        with patch.object(mds, "_public_post", return_value=None), \
             patch.object(mds, "fetch_single_indicator", return_value={}), \
             patch.object(mds, "_local_math_indicators",
                          return_value={"ADX": {"adx": "9.9"}}) as lm:
            out = mds.fetch_indicators_batch("BTC-USDT-SWAP", ["ADX"])
        self.assertEqual(out["ADX"]["adx"], "9.9")
        self.assertEqual(lm.call_args.args[1], ["ADX"], "只补缺失的指标")

    def test_the_local_math_result_never_overwrites_a_good_value(self):
        with patch.object(mds, "_public_post", return_value=None), \
             patch.object(mds, "fetch_single_indicator",
                          return_value={"adx": "from-rest"}), \
             patch.object(mds, "_local_math_indicators",
                          return_value={"ADX": {"adx": "from-math"}}):
            out = mds.fetch_indicators_batch("BTC-USDT-SWAP", ["ADX"])
        self.assertEqual(out["ADX"]["adx"], "from-rest")

    def test_no_missing_indicators_skips_the_local_math(self):
        payload = {"data": [{"data": [{"timeframes": {"1H": {"indicators": {
            "ADX": [{"values": {"adx": "1"}}]}}}}]}]}
        with patch.object(mds, "_public_post", return_value=payload), \
             patch.object(mds, "_local_math_indicators") as lm:
            mds.fetch_indicators_batch("BTC-USDT-SWAP", ["ADX"])
        lm.assert_not_called()


class FetchSingleIndicatorTests(unittest.TestCase):
    def test_a_good_mcp_response_is_returned(self):
        payload = {"data": [{"data": [{"timeframes": {"1H": {"indicators": {
            "ADX": [{"values": {"adx": "33.3"}}]}}}}]}]}
        with patch.object(mds, "_public_post", return_value=payload):
            self.assertEqual(mds.fetch_single_indicator("BTC-USDT-SWAP", "ADX"),
                             {"adx": "33.3"})

    def test_a_malformed_body_falls_through_to_local_math(self):
        with patch.object(mds, "_public_post", return_value={"data": [{"junk": 1}]}), \
             patch.object(mds, "_local_math_indicators",
                          return_value={"ADX": {"adx": "7"}}):
            self.assertEqual(mds.fetch_single_indicator("BTC-USDT-SWAP", "ADX"),
                             {"adx": "7"})

    def test_a_missing_data_key_falls_through(self):
        with patch.object(mds, "_public_post", return_value=None), \
             patch.object(mds, "_local_math_indicators", return_value={}):
            self.assertEqual(mds.fetch_single_indicator("BTC-USDT-SWAP", "ADX"), {})

    def test_an_empty_nested_data_list_is_swallowed(self):
        with patch.object(mds, "_public_post", return_value={"data": [{"data": []}]}), \
             patch.object(mds, "_local_math_indicators", return_value={}):
            self.assertEqual(mds.fetch_single_indicator("BTC-USDT-SWAP", "ADX"), {})

    def test_an_empty_items_list_falls_through(self):
        payload = {"data": [{"data": [{"timeframes": {"1H": {"indicators": {"ADX": []}}}}]}]}
        with patch.object(mds, "_public_post", return_value=payload), \
             patch.object(mds, "_local_math_indicators", return_value={}):
            self.assertEqual(mds.fetch_single_indicator("BTC-USDT-SWAP", "ADX"), {})

    def test_the_indicator_key_is_normalised_in_the_payload(self):
        with patch.object(mds, "_public_post", return_value=None) as pp, \
             patch.object(mds, "_local_math_indicators", return_value={}):
            mds.fetch_single_indicator("BTC-USDT-SWAP", "ema-20")
        self.assertIn("EMA20", pp.call_args.args[1]["indicators"])


class FetchCandlesTests(unittest.TestCase):
    def test_a_good_response_is_returned(self):
        with patch.object(mds, "_public_get", return_value={"data": [["1"]]}):
            self.assertEqual(mds.fetch_candles("BTC-USDT-SWAP"), [["1"]])

    def test_a_failure_returns_empty_list(self):
        with patch.object(mds, "_public_get", return_value=None):
            self.assertEqual(mds.fetch_candles("BTC-USDT-SWAP"), [])

    def test_a_non_numeric_limit_falls_back_to_forty_five(self):
        with patch.object(mds, "_public_get", return_value={"data": []}) as pg:
            mds.fetch_candles("BTC-USDT-SWAP", limit="abc")
        self.assertEqual(pg.call_args.kwargs["params"]["limit"], 45)

    def test_the_limit_is_clamped_to_the_okx_ceiling(self):
        with patch.object(mds, "_public_get", return_value={"data": []}) as pg:
            mds.fetch_candles("BTC-USDT-SWAP", limit=10_000)
        self.assertEqual(pg.call_args.kwargs["params"]["limit"], 300)

    def test_the_limit_is_clamped_to_at_least_one(self):
        with patch.object(mds, "_public_get", return_value={"data": []}) as pg:
            mds.fetch_candles("BTC-USDT-SWAP", limit=0)
        self.assertEqual(pg.call_args.kwargs["params"]["limit"], 1)

    def test_the_bar_is_normalised(self):
        with patch.object(mds, "_public_get", return_value={"data": []}) as pg:
            mds.fetch_candles("BTC-USDT-SWAP", bar="1h")
        self.assertEqual(pg.call_args.kwargs["params"]["bar"], "1H")


class FetchFundingRateTests(unittest.TestCase):
    def test_a_good_rate_is_converted_to_a_percentage(self):
        with patch.object(mds, "_public_get", return_value={
                "data": [{"fundingRate": "0.0002"}]}):
            self.assertEqual(mds.fetch_funding_rate("BTC-USDT-SWAP"), 0.02)

    def test_an_unparsable_rate_returns_none(self):
        with patch.object(mds, "_public_get", return_value={
                "data": [{"fundingRate": "not-a-number"}]}):
            self.assertIsNone(mds.fetch_funding_rate("BTC-USDT-SWAP"))

    def test_a_missing_rate_field_silently_becomes_zero(self):
        with patch.object(mds, "_public_get", return_value={"data": [{}]}):
            out = mds.fetch_funding_rate("BTC-USDT-SWAP")
        self.assertEqual(out, 0.0)

    def test_a_failure_returns_none(self):
        with patch.object(mds, "_public_get", return_value=None):
            self.assertIsNone(mds.fetch_funding_rate("BTC-USDT-SWAP"))


class FetchOpenInterestTests(unittest.TestCase):
    def test_a_good_response_is_returned(self):
        with patch.object(mds, "_public_get", return_value={
                "data": [{"oi": "12345", "oiCcy": "1"}]}):
            out = mds.fetch_open_interest("BTC-USDT-SWAP")
        self.assertEqual(out["oi"], "12345")

    def test_a_failure_yields_none(self):
        with patch.object(mds, "_public_get", return_value=None):
            self.assertIsNone(mds.fetch_open_interest("BTC-USDT-SWAP"))

    def test_an_empty_data_list_yields_none(self):
        with patch.object(mds, "_public_get", return_value={"data": []}):
            self.assertIsNone(mds.fetch_open_interest("BTC-USDT-SWAP"))


if __name__ == "__main__":
    unittest.main()
