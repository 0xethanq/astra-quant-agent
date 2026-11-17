"""`astra_backend/dashboard_payload/bills.py`（结构优化阶段 4·B3 第二十一刀）回归。

## 这个测试在守什么

`aggregate_bills` 把 OKX `account/bills` 的原始流水聚成仪表盘要用的量。它原先
内联在 `astra_backend/dashboard_cache.py::update_cache_cycle` 里（49 行）。

三个容易出错的细节，本文件逐个钉住：

1. **倒序遍历**。OKX 账单是倒序返回的，而 `funding_history_list` 与
   `orders_by_key` 都要按时间正序铺给前端。改成正序遍历，资金费历史会反序。
2. **`today_bj_str in dt_bj` 是子串判断**，不是相等。用 `==` 会让"当日"全部落空。
3. **资金费提前 `continue`**。删掉它，资金费行会被当成平仓单计入
   `orders_by_key`，当日盈亏凭空多出资金费。

## 差分口径

与搬走前的内联实现做逐值差分，并且**用"乱序账单"驱动** —— 只有乱序输入才能
让第 1 条（倒序遍历）的差异暴露；顺序输入下正序/倒序遍历结果相同，差分是盲的。
"""

from __future__ import annotations

import ast
import datetime
import random
import unittest
from pathlib import Path
from unittest.mock import patch

from astra_backend.dashboard_payload.bills import aggregate_bills

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "astra_backend" / "dashboard_cache.py"
MODULE = ROOT / "astra_backend" / "dashboard_payload" / "bills.py"
STATS = ROOT / "astra_backend" / "dashboard_payload" / "trade_stats.py"   # 第九十五刀：消费点现住此

TZ = datetime.timezone(datetime.timedelta(hours=8))
RESET = "2026-09-01 00:00:00"
TODAY = "2026-09-14"


def _legacy(bills_data, *, reset_time_str, today_bj_str, tz_beijing, datetime):
    """搬走前 update_cache_cycle 里的内联聚合段（逐字原样）。"""
    orders_by_key = {}
    today_realized_gross = 0.0
    today_fees = 0.0
    cum_total_fees = 0.0
    today_funding = 0.0
    funding_history_list = []

    if isinstance(bills_data, list):
        for b in reversed(bills_data):
            ts = int(b.get("ts", 0) or 0) / 1000.0
            dt_bj = datetime.datetime.fromtimestamp(ts, tz=tz_beijing).strftime("%Y-%m-%d %H:%M:%S")
            if dt_bj < reset_time_str:
                continue

            sub_type = str(b.get("subType", ""))
            b_type = str(b.get("type", ""))
            inst = b.get("instId", "").replace("-USDT-SWAP", "")
            pnl = float(b.get("pnl", 0) or 0)
            fee = float(b.get("fee", 0) or 0)
            bal_chg = float(b.get("balChg", 0) or 0)
            sz = float(b.get("sz", 0) or 0)

            cum_total_fees += fee
            if today_bj_str in dt_bj:
                today_fees += fee

            if b_type == "8" or sub_type in ["173", "174"]:
                funding_pnl = (bal_chg if bal_chg != 0 else pnl)
                if today_bj_str in dt_bj:
                    today_funding += funding_pnl
                funding_desc = "收取资金费 (+)" if sub_type == "174" or funding_pnl > 0 else "支付资金费 (-)"
                funding_history_list.append({
                    "time": dt_bj, "inst": inst, "type_desc": funding_desc,
                    "pnl": round(funding_pnl, 6), "pos_sz": f"{sz} 张",
                })
                continue

            if sub_type in ["5", "6"]:
                time_min = dt_bj[:16]
                agg_key = f"{time_min}_{inst}"
                if agg_key not in orders_by_key:
                    orders_by_key[agg_key] = {
                        "time": dt_bj, "inst": inst,
                        "gross_pnl": 0.0, "fee": 0.0, "pnl": 0.0,
                    }
                orders_by_key[agg_key]["gross_pnl"] += pnl
                orders_by_key[agg_key]["fee"] += fee
                orders_by_key[agg_key]["pnl"] += (pnl + fee)

    return {
        "orders_by_key": orders_by_key,
        "today_realized_gross": today_realized_gross,
        "today_fees": today_fees,
        "cum_total_fees": cum_total_fees,
        "today_funding": today_funding,
        "funding_history_list": funding_history_list,
    }


def _ms(dt_text: str) -> int:
    dt = datetime.datetime.strptime(dt_text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
    return int(dt.timestamp() * 1000)


def _bill(*, when="2026-09-14 10:00:00", subType="5", type="2", instId="BTC-USDT-SWAP",
          pnl=0.0, fee=0.0, balChg=0.0, sz=0.0):
    return dict(ts=_ms(when), subType=subType, type=type, instId=instId,
                pnl=pnl, fee=fee, balChg=balChg, sz=sz)


def _call(bills_data, *, reset=RESET, today=TODAY):
    return aggregate_bills(bills_data, reset_time_str=reset, today_bj_str=today,
                           tz_beijing=TZ, datetime=datetime)


def _legacy_call(bills_data, *, reset=RESET, today=TODAY):
    return _legacy(bills_data, reset_time_str=reset, today_bj_str=today,
                   tz_beijing=TZ, datetime=datetime)


class BasicTest(unittest.TestCase):
    def test_non_list_input_yields_empty_defaults(self):
        for bad in (None, 42, "x", {}):
            out = _call(bad)
            self.assertEqual(out["orders_by_key"], {})
            self.assertEqual(out["funding_history_list"], [])
            self.assertEqual(out["today_fees"], 0.0)
            self.assertEqual(out["cum_total_fees"], 0.0)
            self.assertEqual(out["today_funding"], 0.0)

    def test_empty_list(self):
        out = _call([])
        self.assertEqual(out["orders_by_key"], {})
        self.assertEqual(out["cum_total_fees"], 0.0)

    def test_closed_order_aggregated_by_minute_and_inst(self):
        out = _call([_bill(subType="5", pnl=10.0, fee=-1.0)])
        self.assertEqual(len(out["orders_by_key"]), 1)
        key = next(iter(out["orders_by_key"]))
        self.assertEqual(key, "2026-09-14 10:00_BTC")
        agg = out["orders_by_key"][key]
        self.assertEqual(agg["gross_pnl"], 10.0)
        self.assertEqual(agg["fee"], -1.0)
        self.assertEqual(agg["pnl"], 9.0)

    def test_two_orders_same_minute_and_inst_merge(self):
        out = _call([
            _bill(when="2026-09-14 10:00:10", subType="5", pnl=10.0, fee=-1.0),
            _bill(when="2026-09-14 10:00:50", subType="6", pnl=-4.0, fee=-1.0),
        ])
        self.assertEqual(len(out["orders_by_key"]), 1)
        agg = next(iter(out["orders_by_key"].values()))
        self.assertEqual(agg["gross_pnl"], 6.0)
        self.assertEqual(agg["pnl"], 4.0, "(-1)+(-1) 手续费合并")

    def test_different_minutes_do_not_merge(self):
        out = _call([
            _bill(when="2026-09-14 10:00:10", subType="5", pnl=10.0),
            _bill(when="2026-09-14 10:01:10", subType="5", pnl=20.0),
        ])
        self.assertEqual(len(out["orders_by_key"]), 2)

    def test_different_instruments_do_not_merge(self):
        out = _call([
            _bill(subType="5", instId="BTC-USDT-SWAP", pnl=10.0),
            _bill(subType="5", instId="ETH-USDT-SWAP", pnl=20.0),
        ])
        self.assertEqual(len(out["orders_by_key"]), 2)

    def test_inst_suffix_stripped(self):
        out = _call([_bill(subType="5", instId="BTC-USDT-SWAP")])
        self.assertEqual(next(iter(out["orders_by_key"].values()))["inst"], "BTC")

    def test_today_realized_gross_is_always_zero_placeholder(self):
        """原实现里这一项从未被本段写入 —— 照抄保留，不做"顺手修正"。"""
        out = _call([_bill(subType="5", pnl=999.0)])
        self.assertEqual(out["today_realized_gross"], 0.0)


class ResetFilterTest(unittest.TestCase):
    def test_bill_before_reset_is_ignored_for_aggregation(self):
        out = _call([_bill(when="2026-08-01 10:00:00", subType="5", pnl=10.0, fee=-2.0)])
        self.assertEqual(out["orders_by_key"], {})
        self.assertEqual(out["today_fees"], 0.0)

    def test_cum_total_fees_also_obeys_reset_filter(self):
        """⚠️ 累计手续费**同样**受重置时间限制 —— 起初我把它读成了"账户历史总量"。

        真相：`if dt_bj < reset_time_str: continue` 在**循环最顶部**，它守卫的是
        整段处理，`cum_total_fees += fee` 也在其后。所以"累计"指的是
        **本次策略周期内**的累计，不是账户开天辟地以来的累计。
        这条写下来是因为按字面理解极易读反，而读反就会做出错误的"修正"。
        """
        before = _call([_bill(when="2026-08-01 10:00:00", subType="5", fee=-2.0)])
        self.assertEqual(before["cum_total_fees"], 0.0,
                         "重置前的费用**不**计入累计手续费")
        after = _call([_bill(when="2026-09-10 10:00:00", subType="5", fee=-2.0)])
        self.assertEqual(after["cum_total_fees"], -2.0, "重置后计入")
        self.assertEqual(after["today_fees"], 0.0, "但不是今天，故不进当日")

    def test_cum_total_fees_spans_days_within_the_period(self):
        """"累计"跨越周期内的多日，但不跨越重置点。"""
        out = _call([
            _bill(when="2026-09-10 10:00:00", subType="5", fee=-2.0),
            _bill(when="2026-09-14 10:00:00", subType="5", fee=-3.0),
        ])
        self.assertEqual(out["cum_total_fees"], -5.0)
        self.assertEqual(out["today_fees"], -3.0)


class TodaySubstringTest(unittest.TestCase):
    def test_today_matching_is_substring_not_equality(self):
        """`today_bj_str in dt_bj` —— 用相等判断会让"当日"全部落空。"""
        out = _call([_bill(when="2026-09-14 10:00:00", subType="5", fee=-3.0)])
        self.assertEqual(out["today_fees"], -3.0)
        # 若实现写成 ==，下面这条会失败
        self.assertIn(TODAY, "2026-09-14 10:00:00")

    def test_yesterday_not_counted_as_today(self):
        out = _call([_bill(when="2026-09-13 23:59:59", subType="5", fee=-3.0)])
        self.assertEqual(out["today_fees"], 0.0)
        self.assertEqual(out["cum_total_fees"], -3.0, "但仍进累计")

    def test_today_boundary_at_midnight(self):
        out = _call([
            _bill(when="2026-09-14 00:00:00", subType="5", fee=-1.0),
            _bill(when="2026-09-14 23:59:59", subType="5", fee=-2.0),
        ])
        self.assertEqual(out["today_fees"], -3.0)


class FundingTest(unittest.TestCase):
    def test_type_8_is_funding(self):
        out = _call([_bill(type="8", balChg=-1.5, sz=10.0)])
        self.assertEqual(len(out["funding_history_list"]), 1)
        self.assertEqual(out["funding_history_list"][0]["pnl"], -1.5)
        self.assertEqual(out["orders_by_key"], {}, "资金费不得进入平仓聚合")

    def test_subtype_173_and_174_are_funding(self):
        for st in ("173", "174"):
            out = _call([_bill(subType=st, balChg=2.0)])
            self.assertEqual(len(out["funding_history_list"]), 1, f"subType={st}")

    def test_funding_falls_back_to_pnl_when_bal_chg_zero(self):
        out = _call([_bill(type="8", balChg=0.0, pnl=7.0)])
        self.assertEqual(out["funding_history_list"][0]["pnl"], 7.0)

    def test_funding_prefers_bal_chg_when_nonzero(self):
        out = _call([_bill(type="8", balChg=3.0, pnl=99.0)])
        self.assertEqual(out["funding_history_list"][0]["pnl"], 3.0)

    def test_funding_desc_received_when_positive(self):
        out = _call([_bill(type="8", balChg=1.0)])
        self.assertEqual(out["funding_history_list"][0]["type_desc"], "收取资金费 (+)")

    def test_funding_desc_paid_when_negative(self):
        out = _call([_bill(type="8", balChg=-1.0)])
        self.assertEqual(out["funding_history_list"][0]["type_desc"], "支付资金费 (-)")

    def test_subtype_174_desc_is_received_even_when_negative(self):
        """`subType == "174"` **或** `funding_pnl > 0` → 收取。

        即 174 的判定优先级高于金额符号 —— 174 是"收取"方向码，
        但金额可能为负（冲销）。原实现如此，照抄。
        """
        out = _call([_bill(subType="174", balChg=-5.0)])
        self.assertEqual(out["funding_history_list"][0]["type_desc"], "收取资金费 (+)")

    def test_funding_does_not_enter_orders_by_key(self):
        """删掉那个 `continue` 的后果：资金费被当成平仓单。"""
        out = _call([_bill(type="8", subType="173", balChg=1.0, pnl=1.0, fee=-9.0)])
        self.assertEqual(out["orders_by_key"], {})

    def test_funding_today_accumulation(self):
        out = _call([
            _bill(when="2026-09-14 10:00:00", type="8", balChg=1.0),
            _bill(when="2026-09-14 11:00:00", type="8", balChg=-0.25),
        ])
        self.assertEqual(out["today_funding"], 0.75)

    def test_funding_before_today_not_in_today_total(self):
        out = _call([_bill(when="2026-09-10 10:00:00", type="8", balChg=5.0)])
        self.assertEqual(out["today_funding"], 0.0)
        self.assertEqual(len(out["funding_history_list"]), 1, "但仍进明细列表")

    def test_funding_pos_sz_format(self):
        out = _call([_bill(type="8", balChg=1.0, sz=12.0)])
        self.assertEqual(out["funding_history_list"][0]["pos_sz"], "12.0 张")

    def test_funding_pnl_rounded_to_6dp(self):
        out = _call([_bill(type="8", balChg=0.1234567891)])
        self.assertEqual(out["funding_history_list"][0]["pnl"], 0.123457)


class OrderIterationDirectionTest(unittest.TestCase):
    def test_funding_history_is_chronological_despite_reversed_input(self):
        """**倒序遍历**：OKX 账单倒序返回，明细必须正序输出。"""
        bills = [
            _bill(when="2026-09-14 12:00:00", type="8", balChg=3.0),   # 最新在前
            _bill(when="2026-09-14 10:00:00", type="8", balChg=1.0),
            _bill(when="2026-09-14 08:00:00", type="8", balChg=2.0),   # 最早在尾
        ]
        times = [r["time"] for r in _call(bills)["funding_history_list"]]
        self.assertEqual(times, ["2026-09-14 08:00:00", "2026-09-14 10:00:00",
                                 "2026-09-14 12:00:00"],
                         "资金费明细必须按时间正序")
        # 正序遍历会得到完全相反的顺序 —— 证明这条断言是承重的
        flipped = _legacy_call(list(reversed(bills)))
        self.assertEqual([r["time"] for r in flipped["funding_history_list"]],
                         list(reversed(times)))

    def test_agg_key_first_seen_time_is_the_earliest(self):
        """聚合键的 `time` 取**首次出现**，倒序遍历下应是最早那一笔。"""
        bills = [
            _bill(when="2026-09-14 10:00:50", subType="5", pnl=1.0),
            _bill(when="2026-09-14 10:00:10", subType="5", pnl=2.0),
        ]
        agg = next(iter(_call(bills)["orders_by_key"].values()))
        self.assertEqual(agg["time"], "2026-09-14 10:00:10",
                         "倒序遍历下首个遇到的是最早那笔")


class LegacyParityTest(unittest.TestCase):
    def test_random_parity_with_shuffled_bills(self):
        """**乱序**驱动 —— 顺序输入下正/倒序遍历结果相同，差分是盲的。"""
        rng = random.Random(20260928)
        subs = ["5", "6", "173", "174", "7", ""]
        types = ["2", "8", ""]
        insts = ["BTC-USDT-SWAP", "ETH-USDT-SWAP", "DOGE-USDT-SWAP"]
        whens = ["2026-09-14 08:00:00", "2026-09-14 10:00:10", "2026-09-14 10:00:50",
                 "2026-09-14 12:00:00", "2026-09-13 23:59:59", "2026-08-01 00:00:00"]
        for _ in range(4000):
            n = rng.randint(0, 6)
            bills = [
                _bill(when=rng.choice(whens), subType=rng.choice(subs),
                      type=rng.choice(types), instId=rng.choice(insts),
                      pnl=rng.choice([-100.0, 0.0, 1.0, 5.0, 50.0]),
                      fee=rng.choice([-2.0, 0.0, 1.5]),
                      balChg=rng.choice([-3.0, 0.0, 2.0]),
                      sz=rng.choice([0.0, 7.0]))
                for _k in range(n)
            ]
            today = rng.choice(["2026-09-14", "2026-09-13", "2026-01-01"])
            reset = rng.choice(["2026-01-01 00:00:00", "2026-09-14 00:00:00"])
            got = _call(bills, reset=reset, today=today)
            exp = _legacy_call(bills, reset=reset, today=today)
            self.assertEqual(got, exp, f"分叉: reset={reset} today={today} bills={bills}")

    def test_parity_for_non_list_and_empty(self):
        for bad in (None, 0, "x", {}, ()):
            self.assertEqual(_call(bad), _legacy_call(bad))
        self.assertEqual(_call([]), _legacy_call([]))


class WiringTest(unittest.TestCase):
    def test_impl_lives_in_payload_module_not_facade(self):
        app_src = APP.read_text(encoding="utf-8")
        mod_src = MODULE.read_text(encoding="utf-8")
        self.assertIn("def aggregate_bills(", mod_src)
        self.assertNotIn("def aggregate_bills(", app_src)
        # 第九十五刀：调用点随相位 4 聚合段迁入 trade_stats.aggregate_bills_and_metrics
        stats_src = STATS.read_text(encoding="utf-8")
        self.assertIn("_core_aggregate_bills(", stats_src)
        self.assertIn("_core_aggregate_bills=_core_aggregate_bills", app_src,
                      "门面仍须注入实现（调用期解析 ⇒ patch 面有效）")

    def test_facade_no_longer_contains_the_inline_loop(self):
        app_src = APP.read_text(encoding="utf-8")
        for gone in ('dt_bj = datetime.datetime.fromtimestamp(ts, tz=tz_beijing)',
                     '"收取资金费 (+)"', 'agg_key = f"{time_min}_{inst}"'):
            self.assertNotIn(gone, app_src, f"门面仍残留内联片段 {gone!r}")

    def test_module_does_not_import_dashboard_app(self):
        """载荷模块不得反向 import dashboard 包（会与 routers 构成循环）。"""
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertFalse(a.name == "astra_backend.dashboard_cache" or a.name.startswith("astra_backend.dashboard_cache."),
                                     f"反向 import {a.name}")
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                self.assertFalse(mod == "astra_backend.dashboard_cache" or mod.startswith("astra_backend.dashboard_cache."),
                                 f"反向 import {mod}")

    def test_datetime_is_injected_not_bound_at_import(self):
        """`datetime` 必须调用期注入 —— 门面的同名名字会被 patch。"""
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = {(a.asname or a.name) for a in node.names}
                self.assertNotIn("datetime", names,
                                 "子模块不得 import datetime（须调用期注入）")

    def test_facade_injects_all_four_params_by_name(self):
        # 第九十五刀：调用点迁入 STATS ⇒ 判定对象随实现迁移
        tree = ast.parse(STATS.read_text(encoding="utf-8"))
        call = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                    and n.func.id == "_core_aggregate_bills")
        kw = {k.arg for k in call.keywords}
        self.assertEqual(kw, {"reset_time_str", "today_bj_str", "tz_beijing", "datetime"})

    def test_result_keys_are_consumed_by_facade(self):
        """门面必须把六个返回键都接出来 —— 漏一个就是静默丢数据。"""
        # 第九十五刀：六个键的接出点随聚合段迁入 trade_stats（原意不变：一个都不能漏）
        stats_src = STATS.read_text(encoding="utf-8")
        for key in ("orders_by_key", "today_realized_gross", "today_fees",
                    "cum_total_fees", "today_funding", "funding_history_list"):
            self.assertIn(f'_bills["{key}"]', stats_src, f"聚合段未取用 {key}")

    def test_patch_seam_still_selects_the_core(self):
        """经 `astra_backend.dashboard_cache` 打到核心的补丁必须生效（薄壳接缝）。"""
        import astra_backend.dashboard_cache as app
        sentinel = {"orders_by_key": {"SENTINEL": {}}, "today_realized_gross": 0.0,
                    "today_fees": 0.0, "cum_total_fees": 0.0, "today_funding": 0.0,
                    "funding_history_list": []}
        calls = []

        def fake(*a, **k):
            calls.append((a, k))
            return sentinel

        with patch.object(app, "_core_aggregate_bills", fake):
            out = app._core_aggregate_bills([], reset_time_str=RESET,
                                            today_bj_str=TODAY, tz_beijing=TZ,
                                            datetime=datetime)
        self.assertEqual(out, sentinel)
        self.assertEqual(len(calls), 1, "补丁未被走到")


_CYCLE_PROBE = r'''
"""在**全新解释器**里跑一遍 update_cache_cycle，并打印载荷摘要。

为什么要另起进程：`update_cache_cycle()` 把结果写进**模块全局** `CACHE_DATA`，
而 `astra_backend.dashboard_cache` 是单例模块。全量套件里别的用例会 `patch.object(astra_backend.dashboard_cache,
"CACHE_DATA", ...)`（`unittest.mock` 在 unwinding 时**还原该属性**，从而丢掉函数
刚写好的载荷），于是断言读到的是别人塞进去的空 dict —— 与抽取正确性无关。
全新进程没有这些外部补丁，是唯一能稳定验证"端到端是否接通"的办法。
"""
import json
import sys
import datetime

sys.path.insert(0, ".")


def main():
    from unittest.mock import patch
    from tests.config_sandbox import isolate_config
    import unittest

    class _T(unittest.TestCase):
        def runTest(self):
            pass

    t = _T()
    isolate_config(t)
    import astra_backend.dashboard_cache as app

    TZ = datetime.timezone(datetime.timedelta(hours=8))

    # ⚠️ 第六十一刀修：账单日期必须取**执行时刻的北京日期**，不能写死。
    #    聚合按"今天"过滤（用的是真实 `time.time()`），写死日期后一旦跨过
    #    北京时间零点，三条账单就全部落到"昨天" → fees_paid 变 0.0 →
    #    `test_bills_values_reach_the_payload` 在 00:00 之后**必然翻红**
    #    （实测：2026-09-15 00:19 复现，`0.0 != -3.0`）。
    #    这是**本仓既有的时间依赖缺陷**，与结构优化无关；本刀顺手修掉。
    _TODAY = datetime.datetime.now(TZ).strftime("%Y-%m-%d")

    def ms(text):
        dt = datetime.datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TZ)
        return int(dt.timestamp() * 1000)

    def bill(when, subType, type_="2", instId="BTC-USDT-SWAP",
             pnl=0.0, fee=0.0, balChg=0.0, sz=0.0):
        return dict(ts=ms(when), subType=subType, type=type_, instId=instId,
                    pnl=pnl, fee=fee, balChg=balChg, sz=sz)

    bills = [
        bill(f"{_TODAY} 12:00:00", "173", type_="8", balChg=-1.25, sz=3.0),
        bill(f"{_TODAY} 10:00:20", "5", pnl=50.0, fee=-2.0),
        bill(f"{_TODAY} 11:30:40", "6", pnl=-10.0, fee=-1.0),
    ]
    bal = [{"details": [{"ccy": "USDT", "eq": "10000", "availBal": "9000",
                         "cashBal": "8000", "upl": "12.5"}]}]

    def fetch(fn, *a, **k):
        name = getattr(fn, "__name__", "")
        if name == "balances":
            return True, bal, ""
        if name == "bills":
            return True, bills, ""
        return True, [], ""

    local = {"adaptive_cfg": {}, "ai_history_list": [], "ai_last_prompt_text": "",
             "ai_memory_md_content": "", "disk_free_gb": 100.0,
             "factor_lib_snapshot": {}, "news_data": {}, "review_data": {},
             "snapshots_list": []}

    app.CACHE_DATA = {}
    app.LAST_CACHE_TIME = 0.0
    with patch.object(app, "_fetch_json", fetch), \
         patch.object(app, "load_position_trackers", lambda: {"insts": {}}), \
         patch.object(app, "_load_cross_venue_data", lambda: {}), \
         patch.object(app, "_load_local_factor_library", lambda: {}), \
         patch.object(app, "_build_factors_from_local_files", lambda p, ts: ([], {})), \
         patch.object(app, "build_ai_health", lambda ai: {}), \
         patch.object(app, "_core_load_ledger_lifecycle_trades", lambda *a, **k: ([], [])), \
         patch.object(app, "_core_load_local_reads", lambda *a, **k: dict(local)), \
         patch.object(app, "_core_collect_algo_protection", lambda *a, **k: None):
        app.update_cache_cycle()

    d = app.CACHE_DATA
    out = {
        "is_dict": isinstance(d, dict),
        "len": len(d or {}),
        "fees_paid": (d.get("today_stats") or {}).get("fees_paid"),
        "funding_paid": (d.get("today_stats") or {}).get("funding_paid"),
        "win_trades": (d.get("today_stats") or {}).get("win_trades"),
        "loss_trades": (d.get("today_stats") or {}).get("loss_trades"),
        "realized_gross": (d.get("today_stats") or {}).get("realized_gross"),
        "cum_total_fees": (d.get("account") or {}).get("cum_total_fees"),
        "funding_items": (d.get("funding_settlements") or {}).get("items"),
        "funding_total": (d.get("funding_settlements") or {}).get("total_funding_pnl"),
    }
    print("CYCLE_JSON " + json.dumps(out, ensure_ascii=False))


main()
'''


class UpdateCacheCycleIntegrationTest(unittest.TestCase):
    """**端到端**验证 `update_cache_cycle()` 真的把 bills 产物接到了载荷上。

    ## 为什么必须补这一条

    本仓有过一次真实生产事故：抽取后所有"抽取测试"全绿，但**门面从未被 import**，
    于是语法错误让一整个交易周期静默消失。教训是"读源码的测试"证明不了"能跑"。

    抽取 bills 后我查了一遍：**没有任何测试真正调用 `update_cache_cycle()`**
    （只有一处把它替换成 `lambda: None`）。也就是说本刀之前，"bills 段是否真的接上、
    门面拼装是否还活着"全靠人读 —— 正是上面那类盲区。

    ## 为什么另起进程

    `update_cache_cycle()` 把结果写进**模块全局** `CACHE_DATA`，而 `astra_backend.dashboard_cache`
    是单例模块。全量套件里别的用例会 `patch.object(astra_backend.dashboard_cache, "CACHE_DATA", ...)`，
    而 `unittest.mock` 在 unwinding 时**还原该属性**，等于把函数刚写好的载荷丢掉 ——
    实测现象极具误导性：单独跑全绿、全量跑读到空 dict，看起来像"跨测试污染"，
    根因却是 patch 语义本身吃掉了赋值（我为此绕了很久）。

    另起进程没有这些外部补丁，是唯一能稳定验"端到端接通"的办法。
    """

    def _run_probe(self):
        import json
        import subprocess
        import sys

        script = ROOT / "tests" / "_dashboard_cycle_probe.py"
        # 探针内嵌在本文件里，运行时写到一个临时脚本再执行（保持单一事实源：
        # 探针正文就写在下面，读代码的人不必再跳一个文件）。
        script.write_text(_CYCLE_PROBE, encoding="utf-8")
        self.addCleanup(lambda: script.unlink(missing_ok=True))
        proc = subprocess.run([sys.executable, str(script)], capture_output=True,
                              text=True, cwd=str(ROOT))
        line = next((l for l in proc.stdout.splitlines()
                     if l.startswith("CYCLE_JSON ")), None)
        self.assertIsNotNone(
            line,
            "探针未产出载荷摘要 —— 端到端可能已断。\n"
            f"stdout:\n{proc.stdout[-2000:]}\nstderr:\n{proc.stderr[-2000:]}")
        return json.loads(line[len("CYCLE_JSON "):])

    def test_cycle_produces_payload(self):
        # 第七十八刀：以 spawn 为被测行为，离线守护下如实 skip（守卫在 spawn 前）。
        from tests.config_sandbox import skip_if_offline_suite
        skip_if_offline_suite(self)
        out = self._run_probe()
        self.assertTrue(out["is_dict"], "载荷不是 dict")
        self.assertGreater(out["len"], 0, "载荷为空 —— 门面拼装可能已失效")

    def test_bills_values_reach_the_payload(self):
        # 第七十八刀：以 spawn 为被测行为，离线守护下如实 skip（守卫在 spawn 前）。
        from tests.config_sandbox import skip_if_offline_suite
        skip_if_offline_suite(self)
        out = self._run_probe()
        # 手续费：-2.0 + -1.0 = -3.0（两笔平仓单，分属不同分钟故不合并）
        self.assertEqual(out["fees_paid"], -3.0, "bills 的当日手续费未到达载荷")
        # 资金费：-1.25（当日）
        self.assertEqual(out["funding_paid"], -1.25, "bills 的资金费未到达载荷")
        self.assertEqual(out["cum_total_fees"], -3.0, "累计手续费未到达载荷")

        # 资金费明细
        self.assertEqual(len(out["funding_items"]), 1)
        self.assertEqual(out["funding_items"][0]["inst"], "BTC")
        self.assertEqual(out["funding_items"][0]["pnl"], -1.25)
        self.assertAlmostEqual(out["funding_total"], -1.25, places=6)

        # 平仓聚合：两笔分属不同分钟 → 2 条记录 → 1 盈 1 亏
        self.assertEqual(out["win_trades"], 1, "平仓聚合应算出 1 笔盈利")
        self.assertEqual(out["loss_trades"], 1, "平仓聚合应算出 1 笔亏损")
        # bills 返回的 today_realized_gross 恒为 0（占位），门面尾段用 Σ gross_pnl
        # 覆盖它 → 50 + (-10) = 40。这正是"占位值只是占位"的实证。
        self.assertEqual(out["realized_gross"], 40.0,
                         "门面尾段应以 Σ gross_pnl 覆盖 bills 的占位值")


if __name__ == "__main__":
    unittest.main()
