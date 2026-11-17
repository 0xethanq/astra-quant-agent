"""因子装配的剩余路径（第二百五十六刀）。

`fetch_single_instrument_data` 每个标的每周期跑一次，四个依赖（`fetch_candles_direct` /
`news_sentiment_file` / `instrument_profile` / `load_adaptive_config`）由门面注入
—— 正因为注入了，才能在这里安全地造 K 线序列。

本刀覆盖四类此前没走到的路径：

| 路径 | 语义 |
|---|---|
| 持仓快照 | 只认**同 instId 且非零**的仓（零仓不算持仓）|
| `structure_1h` | 近 5 根 vs 前 10 根：`HH_HL` / `LH_LL` / 其余 `CHOP` |
| `market_regime` | 1H 与 15M **必须同向**才叫趋势；1H 空但 15M 反弹 ⇒ 锁 `CHOP`（防惯性误判）|
| `sz` 兜底 | `ctVal`/ATR 不可用时退回 `base_sz * 乘数`；行情不完整 ⇒ **归零**（不放大成 1 张）|
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from scripts.trader.factors import fetch_single_instrument_data

INST = "BTC-USDT-SWAP"


def _candle(close, *, high=None, low=None, open_=None, vol=1.0):
    """[ts, open, high, low, close, vol] —— 索引 2/3/4/5 与生产代码一致。"""
    return [0, open_ if open_ is not None else close,
            high if high is not None else close,
            low if low is not None else close,
            close, vol]


def _rising(n, start=100.0, step=0.5):
    return [_candle(start + i * step) for i in range(n)]


def _falling(n, start=200.0, step=0.5):
    return [_candle(start - i * step) for i in range(n)]


class _Base(unittest.TestCase):
    def setUp(self):
        # ⚠️ 生产代码在 15M 分支里会**真的发 HTTPS 请求**取 BBO 盘口价
        # （urllib → okx.com）⇒ 测试必须打桩，否则既慢又依赖网络。
        self._net = patch("urllib.request.urlopen", side_effect=RuntimeError("测试内不出网"))
        self._net.start()
        self.addCleanup(self._net.stop)
        self.tmp = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        self.tmp.write(json.dumps({"score": 0.0}))
        self.tmp.close()
        self.addCleanup(lambda: os.unlink(self.tmp.name))

    def _call(self, *, candles_15m=None, candles_1h=None, candles_4h=None,
              positions=(), ctVal=1.0, adaptive=None, news_file=None):
        """返回装配好的因子字典 `f`。K 线按**由旧到新**传入，内部自动翻转成交易所的
        「最新在前」顺序（生产代码会 `reversed()`）。"""
        # ★ 2026-10：15M 默认 45 → 60 根。生产取数已改 60（`ema55` 需 ≥55 根，45 根时
        #   它会退化成现价），且 `market_data_valid` 现在要求 `ema55` 真的算出来 ——
        #   夹具必须与生产同源，否则测的就不是生产形态。
        books = {"15m": list(reversed(candles_15m if candles_15m is not None else _rising(60))),
                 "1H": list(reversed(candles_1h if candles_1h is not None else _rising(35))),
                 "4H": list(reversed(candles_4h if candles_4h is not None else _rising(25)))}
        item = {"instId": INST, "name": "BTC", "type": "crypto", "base_sz": 2.0,
                "precision": 2, "ctVal": ctVal, "minSz": 0.01}
        return fetch_single_instrument_data(
            item, list(positions), 1000.0,
            news_sentiment_file=news_file or self.tmp.name,
            fetch_candles_direct=lambda inst, bar, n: books.get(bar, []),
            instrument_profile=lambda f, asset_type: {"sl_atr_mult": 1.3},
            load_adaptive_config=lambda: (adaptive or {}))




class VolumeRatioUsesTheClosedBarTest(_Base):
    """★ 2026-10 实盘修复：量比必须用**已收盘**的那根 15M。

    交易周期固定在 :00/:15/:30/:45 触发，此刻 OKX 返回的 `vols[-1]` 是**刚开盘**的
    当前根（累积量 ≈ 整根的 1%）⇒ 旧实现下实盘 `vol_ratio` 长期在 0.01~0.06x，
    而 `signals.py` 的量能子分要 `>= 1.25`、「动量爆发/空头加速」两个形态要 `>= 1.3`
    ⇒ **量能证据被静默关掉**。实测同标的 80 秒内旧口径从 0.53 漂到 0.72（跟着当前根涨），
    新口径恒定 —— 即旧值跟踪的是"采集时刻"而不是市场。

    （与 `tests/ops/test_brain_packages.py::MicrostructureTests::
      test_volume_ratio_ignores_the_still_forming_bar` 同族；那边修的是大脑侧。）
    """

    def test_forming_bar_is_excluded_from_the_ratio(self):
        rows = [_candle(100.0, vol=10.0) for _ in range(30)]      # 30 根已收盘，量恒 10
        rows[-1] = _candle(100.0, vol=40.0)                      # 最近一根**已收盘**：放量 4 倍
        rows.append(_candle(100.0, vol=0.4))                     # 正在形成的当前根：累积量极小
        f = self._call(candles_15m=rows)
        # 40 / mean(前 20 根已收盘=10) = 4.0；若误用当前根则是 0.4/… ≈ 0.04
        self.assertAlmostEqual(f["vol_ratio"], 4.0, places=2)

    def test_ratio_is_stable_while_the_forming_bar_grows(self):
        """当前根量变化**不得**影响量比（旧实现下它会跟着变）。"""
        base = [_candle(100.0, vol=10.0) for _ in range(30)]
        base[-1] = _candle(100.0, vol=20.0)
        first = self._call(candles_15m=base + [_candle(100.0, vol=1.0)])
        later = self._call(candles_15m=base + [_candle(100.0, vol=9.0)])
        self.assertEqual(first["vol_ratio"], later["vol_ratio"])
        self.assertAlmostEqual(first["vol_ratio"], 2.0, places=2)


class CandleShapeUsesTheClosedBarTest(_Base):
    """★ 2026-10 实盘修复：`is_bull/bear_candle_15m`、上下影线比取自**已闭合**的 15M。

    原取 `candles_15m[-1]`（OKX 正在形成的当前根）。交易周期固定在 :00/:15/:30/:45
    触发，此刻该根刚开盘 ⇒ 开≈收、影线≈0，形态标志与影线比是**采样时刻的函数**：
    实测同一根内 91 秒从"非阳非阴/下影 0.577"翻成"阳线/下影 0.462"，而已收盘根恒定。
    `signals.py` 的形态闸正是"收阳/收阴**或**长影线"，条文也明确要求"已闭合 K 线给出的
    确认信号" ⇒ 必须用已收盘根。
    """

    def test_flags_come_from_the_closed_bar_not_the_forming_bar(self):
        rows = [_candle(100.0) for _ in range(20)]
        rows[-2] = _candle(101.0, open_=100.0, high=102.0, low=99.0)   # 已收盘：阳线
        rows[-1] = _candle(99.0, open_=100.0, high=100.2, low=98.8)    # 形成中：阴线
        f = self._call(candles_15m=rows)
        self.assertTrue(f["is_bull_candle_15m"], "应取已收盘根（阳）")
        self.assertFalse(f["is_bear_candle_15m"])

    def test_closed_bar_bear_is_reported_even_if_the_forming_bar_is_bull(self):
        rows = [_candle(100.0) for _ in range(20)]
        rows[-2] = _candle(99.0, open_=100.0, high=100.5, low=98.5)    # 已收盘：阴线
        rows[-1] = _candle(101.0, open_=100.0, high=101.5, low=99.9)   # 形成中：阳线
        f = self._call(candles_15m=rows)
        self.assertTrue(f["is_bear_candle_15m"])
        self.assertFalse(f["is_bull_candle_15m"])

    def test_wick_ratios_come_from_the_closed_bar(self):
        rows = [_candle(100.0) for _ in range(20)]
        # 已收盘：实体 100→101，下影到 98 ⇒ 下影 2 / 全幅 4 = 0.5
        rows[-2] = _candle(101.0, open_=100.0, high=102.0, low=98.0)
        # 形成中：下影极小
        rows[-1] = _candle(100.0, open_=100.0, high=100.05, low=99.95)
        f = self._call(candles_15m=rows)
        self.assertAlmostEqual(f["lower_wick_ratio"], 0.5, places=2)

class FifteenMinuteDepthSupportsEma55Test(_Base):
    """★ 2026-10：15M 取数必须够算 `ema55`（≥55 根）。

    实盘原取 45 根 ⇒ `calc_ema(closes, 55)` 退化返回最后一根收盘价 ⇒ EMA55 恒等于现价
    ⇒ `signals.py` 的 `px >= ema55*0.994` 位置下限几何上恒真（实测 22.4% 的 K 线上
    错误放行）。本门正向钉住取数深度，防止有人"省一次取数"把它改回去。
    """

    def test_requested_15m_depth_is_at_least_55(self):
        asked = {}

        def spy(inst, bar, n):
            asked[bar] = n
            return _rising(n) if bar == "15m" else _rising(n)

        item = {"instId": INST, "name": "BTC", "type": "crypto", "base_sz": 1.0,
                "precision": 2, "ctVal": 1.0, "minSz": 0.01}
        fetch_single_instrument_data(
            item, [], 1000.0, news_sentiment_file=self.tmp.name,
            fetch_candles_direct=spy,
            instrument_profile=lambda f, t: {"sl_atr_mult": 1.3},
            load_adaptive_config=lambda: {})
        self.assertGreaterEqual(asked["15m"], 55,
                                "15M 取数少于 55 根 ⇒ EMA55 退化等于现价，位置闸失去下限")

    def test_ema55_is_a_real_indicator_not_the_last_close(self):
        f = self._call()
        self.assertIsNotNone(f["ema55"])
        closes = [float(c[4]) for c in reversed(_rising(60))]
        self.assertNotAlmostEqual(f["ema55"], closes[-1], places=9)

class BboTickerTest(_Base):
    """盘口取价（BBO）：成功 ⇒ 用**真实 bid/ask**（限价精度靠它）。"""

    class _Resp:
        def __init__(self, payload):
            self._body = json.dumps(payload).encode("utf-8")

        def read(self):
            return self._body

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def test_successful_ticker_uses_real_bid_ask(self):
        self._net.stop()          # 放开 setUp 的「不出网」桩，换成受控响应
        payload = {"code": "0", "data": [{"bidPx": "79999.5", "askPx": "80000.5"}]}
        with patch("urllib.request.urlopen", return_value=self._Resp(payload)):
            f = self._call()
        self.assertEqual(f["bidPx"], 79999.5, "盘口价取到就用它，而不是退回最新价")
        self.assertEqual(f["askPx"], 80000.5)
        self.assertGreaterEqual(f["askPx"], f["bidPx"], "行情有效性判定要求 ask ≥ bid")

    def test_non_zero_code_keeps_fallback_prices(self):
        """`code != "0"`（交易所侧异常）⇒ 退回最新价，**不抛**（降级但已留痕）。"""
        self._net.stop()
        payload = {"code": "51001", "data": []}
        with patch("urllib.request.urlopen", return_value=self._Resp(payload)):
            f = self._call()
        self.assertEqual(f["bidPx"], f["price"])
        self.assertEqual(f["askPx"], f["price"])


class SentimentTest(_Base):
    """舆情：**「情绪=0（真中性）」与「没读到」必须分开**（本仓红线「缺失 ≠ 0」）。"""

    def _news_file(self, payload):
        fh = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        fh.write(payload)
        fh.close()
        self.addCleanup(lambda: os.unlink(fh.name))
        return fh.name

    def test_score_is_picked_up_and_marked_available(self):
        path = self._news_file(json.dumps(
            {"coins_sentiment": {"BTC": {"sentiment_factor_score": 0.7}}}))
        f = self._call(news_file=path)
        self.assertEqual(f["sentiment_score"], 0.7)
        self.assertIs(f["sentiment_available"], True)

    def test_true_neutral_is_available_not_missing(self):
        """真的读到 0 分 ⇒ `available=True`（有数据、就是中性），不得与「没读到」混淆。"""
        path = self._news_file(json.dumps(
            {"coins_sentiment": {"BTC": {"sentiment_factor_score": 0.0}}}))
        f = self._call(news_file=path)
        self.assertEqual(f["sentiment_score"], 0.0)
        self.assertIs(f["sentiment_available"], True, "0 分是**中性**，不是缺失")

    def test_unreadable_file_marks_unavailable_and_warns(self):
        """文件在、但读不出来 ⇒ `available=False` **且必须告警**（不许静默当 0）。"""
        path = self._news_file("{不是 json")
        import warnings as _w
        with _w.catch_warnings(record=True) as caught:
            _w.simplefilter("always")
            f = self._call(news_file=path)
        self.assertIs(f["sentiment_available"], False)
        self.assertEqual(f["sentiment_score"], 0.0)
        self.assertTrue(any(issubclass(w.category, RuntimeWarning) for w in caught),
                        "读失败必须留痕（原先静默 pass 会把「没数据」当「中性」）")


class CalculusTest(_Base):
    """⚠️ 反向断言（2026-10 重钉）：多周期动力学已**整链退场**。

    原来这两条守的是「引擎成功 ⇒ 整包采纳 / 引擎失败 ⇒ 保留 `valid=False` 的
    诚实形状 + `error` + 告警」。数理链退场后，真正要守的性质变成了三条：
    ① 门面**不再调用引擎**（AST 判据，不被文档串误伤）；
    ② `f["calculus"]` 仍是一个**键位完整的占位**（老读者不炸），但 `valid=False`；
    ③ 占位里**不许再有 `error`** —— 出现 `error` 说明还有人真的去调了引擎。
    """

    def test_the_engine_is_no_longer_called(self):
        import ast
        from pathlib import Path
        tree = ast.parse(Path(
            __import__("scripts.trader.factors", fromlist=["x"]).__file__
        ).read_text(encoding="utf-8"))
        self.assertNotIn("calculus_engine", {n.module for n in ast.walk(tree)
                                             if isinstance(n, ast.ImportFrom)})
        names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        self.assertNotIn("calculate_multi_timeframe", names)

    def test_the_placeholder_is_completely_stripped(self):
        """★ 反向守卫（2026-10）：数理退役后，f 中不再留 calculus 占位键。"""
        f = self._call()
        self.assertNotIn("calculus", f, "calculus 占位已彻底移除")


class PositionSnapshotTest(_Base):
    """持仓快照：**只认同 instId 且非零**的仓（零仓不是持仓）。"""

    def test_non_zero_position_of_this_instrument_is_snapshotted(self):
        f = self._call(positions=[{"instId": INST, "pos": 5.0, "posSide": "long",
                                   "avgPx": 80000.0, "markPx": 81000.0, "upl": 100.0,
                                   "uplRatio": 0.01, "lever": "3"}])
        self.assertIsNotNone(f["position"])
        self.assertEqual(f["position"]["pos"], 5.0)
        self.assertEqual(f["position"]["side"], "long")
        self.assertEqual(f["position"]["avgPx"], 80000.0)

    def test_zero_position_is_not_a_position(self):
        """平掉的仓（`pos=0`）**不得**被当成持仓 —— 否则后续会按"有仓"做移损等动作。"""
        f = self._call(positions=[{"instId": INST, "pos": 0.0, "posSide": "long"}])
        self.assertIsNone(f["position"])

    def test_other_instrument_is_ignored(self):
        f = self._call(positions=[{"instId": "ETH-USDT-SWAP", "pos": 9.0}])
        self.assertIsNone(f["position"])


class StructureAndRegimeTest(_Base):
    """结构（近 5 根 vs 前 10 根）与 regime（1H+15M 必须同向）。"""

    # ⚠️ 序列长度要**足够算 EMA21**：实测 15 根时 `calc_ema(closes, 21)` 会退化成末位
    # 收盘价，于是 `e9_1h >= e21_1h` 判成 False、趋势方向**整个反过来**（我第一版就踩了：
    # 上涨序列被判成空头）。生产传的是 35 根 ⇒ 夹具也用 35 根（30 根基底 + 5 根新段）。
    _BASE = 30

    def _hh_hl_1h(self):
        # 前 30 根低位窄幅，后 5 根整体抬高 ⇒ 近 5 根高点更高、低点也更高（HH_HL）
        old = [_candle(100.0, high=101.0, low=99.0) for _ in range(self._BASE)]
        new = [_candle(110.0 + i, high=112.0 + i, low=108.0 + i) for i in range(5)]
        return old + new

    def _lh_ll_1h(self):
        old = [_candle(200.0, high=201.0, low=199.0) for _ in range(self._BASE)]
        new = [_candle(190.0 - i, high=192.0 - i, low=188.0 - i) for i in range(5)]
        return old + new

    def test_structure_hh_hl(self):
        f = self._call(candles_1h=self._hh_hl_1h())
        self.assertEqual(f["structure_1h"], "HH_HL")

    def test_structure_lh_ll(self):
        f = self._call(candles_1h=self._lh_ll_1h(), candles_15m=_falling(45, 200.0))
        self.assertEqual(f["structure_1h"], "LH_LL")

    def test_structure_chop_when_neither_direction(self):
        """高不成低不就（近 5 根与前面重叠）⇒ `CHOP`。"""
        flat = [_candle(100.0, high=101.0, low=99.0) for _ in range(35)]
        f = self._call(candles_1h=flat)
        self.assertEqual(f["structure_1h"], "CHOP")

    def test_bull_trend_requires_15m_and_1h_aligned(self):
        f = self._call(candles_1h=self._hh_hl_1h(), candles_15m=_rising(45, 100.0))
        self.assertEqual(f["market_regime"], "BULL_TREND")

    def test_bearish_1h_with_rebounding_15m_is_locked_to_chop(self):
        """★ 防惯性误判：1H 说空、但 15M 正在反弹 ⇒ **锁 `CHOP`**，不许叫 BEAR_TREND。

        （否则会在 V 型反转里按"空头趋势"给反向信号。）
        """
        f = self._call(candles_1h=self._lh_ll_1h(), candles_15m=_rising(45, 100.0))
        self.assertEqual(f["market_regime"], "CHOP")


class SizeFallbackTest(_Base):
    def test_size_falls_back_to_base_multiplier_without_ctval(self):
        """`ctVal<=0`（或 ATR 不可用）⇒ 退回 `base_sz * 位置乘数`，而不是按风险额硬算。"""
        f = self._call(ctVal=0.0, adaptive={"position_size_multipliers": {"BTC": 2.0}})
        self.assertEqual(f["sz"], 4.0, "base_sz 2.0 × 乘数 2.0")

    def test_size_multiplier_zero_means_no_trade(self):
        f = self._call(ctVal=0.0, adaptive={"position_size_multipliers": {"BTC": 0.0}})
        self.assertEqual(f["sz"], 0.0)

    def test_incomplete_market_data_forces_size_to_zero(self):
        """行情不完整 ⇒ 张数**归零**（上层跳过），**绝不放大成 1 张**。"""
        f = self._call(candles_15m=[], candles_1h=[], candles_4h=[])
        self.assertFalse(f["market_data_valid"])
        self.assertEqual(f["sz"], 0.0)


class PartialMarketDataTest(_Base):
    """**部分**取数失败（2026-09-30 真机 429 事故）。

    真实形态与上面那条不同：OKX 对 15M 蜡烛返回 **429**，而 1H/4H 成功 ——
    此时 `price` 保持默认 0，但 1H 分支照样执行，于是 `atr / price` 把
    **整个交易周期**炸掉（`ZeroDivisionError` 冒到 `execute_portfolio`）。
    代价不是"少算一个指标"，而是**连持仓的追踪止损都不再执行** ——
    最危险的失败形态，故单独钉住。
    """

    def test_missing_15m_candles_with_1h_available_must_not_raise(self):
        f = self._call(candles_15m=[], candles_1h=_rising(35), candles_4h=_rising(25))
        self.assertEqual(f["price"], 0.0, "价格不可用时保持默认，不臆造")
        self.assertIsNone(f["atr_pct"], "价格不可用 ⇒ ATR 百分比缺失（None，不臆造）")
        self.assertFalse(f["market_data_valid"])
        self.assertEqual(f["sz"], 0.0, "行情无效 ⇒ 张数归零（上层跳过该标的）")

    def test_zero_last_close_is_treated_as_unavailable(self):
        """K 线存在但收盘价是 0（坏数据）⇒ 同样不得除零。"""
        zeros = [_candle(0.0) for _ in range(45)]
        f = self._call(candles_15m=zeros, candles_1h=_rising(35), candles_4h=_rising(25))
        self.assertEqual(f["price"], 0.0)
        self.assertIsNone(f["atr_pct"])
        self.assertFalse(f["market_data_valid"])


if __name__ == "__main__":
    unittest.main()
