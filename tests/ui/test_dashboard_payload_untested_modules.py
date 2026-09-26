"""`dashboard_payload` 三个「零测试引用」模块的补测（结构优化阶段 4·B3 第六十八刀）。

## 为什么补这三个

到第六十七刀为止，本阶段共抽出 **72 个模块**。用
`git log --diff-filter=A --grep=第.*刀` 取出这份清单，再逐个到 `tests/` 里找 ——
**69 个有测试引用，3 个一次都没被提到**：

| 模块 | 行数 | 此前测试引用 |
|---|---|---|
| `dashboard_payload/factors_view.py` | 141 | **0** |
| `dashboard_payload/reset_state.py` | 27 | **0** |
| `dashboard_payload/ledger_view.py` | 79 | 1（仅间接） |

它们**只经 `astra_backend/dashboard_cache.py` 门面**被间接调用，而门面级用例只验证
"载荷非空 / 某几个键在"（`test_dashboard_payload_seam.py` 等），
**从不验证这些模块内部的取值优先级**。

> ⚠️ 这正是"抽出来了但没测"的典型：
> 拆分时把 `data_dir` / 三个文件路径都做成**入参注入**（docstring 里也写了
> "测试会把 DATA_DIR 指向沙箱"），**为可测性做了准备，却始终没人测**。

## 这两个函数值得测的地方

`build_factors_list` 内部有一整张**取值优先级链**，例如：

```
action   : ai_decisions.action   → state.instruments[].action       → "WAIT"
price    : state.price（非 --）  → factor_library.price             → "--"
rsi      : state.rsi（非 None）  → factor_library.trend_momentum    → 50.0
funding  : ai.raw_funding_rate   → factor_library.smart_money       → "--"
```

这类链是**"改一处漏一处"的高发区**，而且错了不会报错，只会让面板显示旧值或空值。

`read_reset_initial_state` 则有一处**极易被"顺手清理"掉的细节**：
`INITIAL_CAPITAL` 环境变量与文件值的**优先级**，以及
`float(... or 10000.0)` 里那个 `or`（文件写了 `0` 时要回落 10000 而不是取 0）。
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from astra_backend.dashboard_payload import factors_view, ledger_view, reset_state  # noqa: E402


class _Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="r68-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)

    def _write(self, name: str, payload) -> str:
        p = os.path.join(self.tmp, name)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        return p


class ReadResetInitialStateTest(_Base):
    """`read_reset_initial_state(data_dir)` —— 27 行，此前 0 测试。"""

    def test_env_is_read_before_the_file(self):
        """⚠️ 真实的优先级是 **env 先于文件** —— 与直觉相反，实测确认。

        实现是：

            initial_capital_val = float(os.getenv("INITIAL_CAPITAL", "10000.0"))
            ...
            initial_capital_val = float(acc_init.get("initial_capital", 10000.0) or 10000.0)

        第二行用的是 `acc_init.get(key, <常量>)` —— **默认值是写死的 10000.0，
        不是 env 的值**。所以：

        - 文件里**有** `initial_capital` → 用文件值（env 被忽略）；
        - 文件里**没有**该键 → 用 **10000.0**，env 同样被忽略。

        ⇒ `INITIAL_CAPITAL` 只在**第二条语句整体没走到**时才有意义
        （即 `reset_time` 那一行先抛异常）。
        本测试把这条真实语义钉住 —— 我第一版按"文件缺失→用 env"写，
        当场被实测否掉。
        """
        with patch.dict(os.environ, {"INITIAL_CAPITAL": "12345.0"}):
            reset, cap = reset_state.read_reset_initial_state(self.tmp)
        self.assertEqual(reset, "1970-01-01 00:00:00")
        self.assertEqual(cap, 10000.0,
                         "文件缺键时用的是写死的 10000.0，不是 env")

    def test_env_only_takes_effect_when_the_file_read_raises(self):
        """env 生效的唯一路径：`acc_init` 不是 dict，导致第二行整体抛异常。"""
        p = os.path.join(self.tmp, "account_initial_state.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("[1, 2, 3]")          # 合法 JSON，但不是 dict
        with patch.dict(os.environ, {"INITIAL_CAPITAL": "12345.0"}):
            _, cap = reset_state.read_reset_initial_state(self.tmp)
        self.assertEqual(cap, 12345.0, "到不了第二条语句时才轮到 env 生效")

    def test_defaults_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INITIAL_CAPITAL", None)
            reset, cap = reset_state.read_reset_initial_state(self.tmp)
        self.assertEqual(reset, "1970-01-01 00:00:00")
        self.assertEqual(cap, 10000.0)

    def test_file_values_win_over_env(self):
        """文件里显式写了值 → 用文件值（env 不参与）。"""
        self._write("account_initial_state.json",
                    {"reset_time": "2026-09-11 12:00:00", "initial_capital": 5000.0})
        with patch.dict(os.environ, {"INITIAL_CAPITAL": "99999.0"}):
            reset, cap = reset_state.read_reset_initial_state(self.tmp)
        self.assertEqual(reset, "2026-09-11 12:00:00")
        self.assertEqual(cap, 5000.0, "文件值应覆盖环境变量")

    def test_zero_capital_falls_back_to_10000(self):
        """⚠️ `float(x or 10000.0)` 的 `or`：文件写 0 时必须回落 10000，不能取 0。

        取 0 会让所有按"初始资金"算的百分比/收益率除零或显示 0%。
        这是最容易被"顺手简化成 float(x)"改坏的一处。
        """
        self._write("account_initial_state.json", {"initial_capital": 0})
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INITIAL_CAPITAL", None)
            reset, cap = reset_state.read_reset_initial_state(self.tmp)
        self.assertEqual(cap, 10000.0, "0 应回落 10000（`or` 语义），而不是取 0")

    def test_null_capital_falls_back(self):
        self._write("account_initial_state.json", {"initial_capital": None})
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INITIAL_CAPITAL", None)
            _, cap = reset_state.read_reset_initial_state(self.tmp)
        self.assertEqual(cap, 10000.0)

    def test_missing_keys_use_defaults(self):
        self._write("account_initial_state.json", {"unrelated": 1})
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INITIAL_CAPITAL", None)
            reset, cap = reset_state.read_reset_initial_state(self.tmp)
        self.assertEqual(reset, "1970-01-01 00:00:00")
        self.assertEqual(cap, 10000.0)

    def test_non_numeric_capital_does_not_raise(self):
        """`float("abc")` 会抛 → 被 try/except 吞掉，整体回落。"""
        self._write("account_initial_state.json",
                    {"reset_time": "2026-01-02 03:04:05", "initial_capital": "abc"})
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INITIAL_CAPITAL", None)
            reset, cap = reset_state.read_reset_initial_state(self.tmp)
        self.assertEqual(cap, 10000.0, "非数字应回落，而不是抛异常")
        # ⚠️ 实测行为（我第一版猜错了，这里是订正后的结论）：
        #    `reset_time_str` 的赋值在 `float(...)` **之前**且**已经生效**，
        #    所以 `float("abc")` 抛异常被吞掉后，**reset_time 保留新值**，
        #    只有 initial_capital 回落。
        #    ⇒ 结果是一个**半应用**状态：新 reset_time + 默认资金。
        #    这是原实现的既有行为，本测试把它钉住（不是我认为它"对"）。
        self.assertEqual(reset, "2026-01-02 03:04:05",
                         "reset_time 的赋值先于 float() 生效，异常不会回滚它")

    def test_corrupt_file_does_not_raise(self):
        p = os.path.join(self.tmp, "account_initial_state.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{not json")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("INITIAL_CAPITAL", None)
            reset, cap = reset_state.read_reset_initial_state(self.tmp)
        self.assertEqual(cap, 10000.0)
        self.assertEqual(reset, "1970-01-01 00:00:00")


class BuildFactorsListTest(_Base):
    """`build_factors_list(...)` —— 141 行，此前 0 测试。

    `load_instruments` 走纯导入（docstring 明说"无需注入"），
    故这里 patch 它，把标的池固定成可预期的两条。
    """

    POOL = [{"instId": "BTC-USDT-SWAP", "name": "BTC", "type": "crypto"},
            {"instId": "ETH-USDT-SWAP", "name": "ETH", "type": "crypto"}]

    def _build(self, *, decisions=None, state=None, lib=None, positions=None,
               ts="2026-09-15 01:00:00"):
        d = self._write("ai_brain_decisions.json", decisions or {})
        s = self._write("trading_state.json", state or {})
        f = self._write("factor_library.json", lib or {})
        with patch.object(factors_view, "load_instruments", lambda: list(self.POOL)):
            return factors_view.build_factors_list(d, s, f, positions or [], ts)

    # ---- 形状 ----
    def test_returns_tuple_of_list_and_state(self):
        out, state = self._build()
        self.assertIsInstance(out, list)
        self.assertIsInstance(state, dict)
        self.assertEqual(len(out), 2, "标的池有 2 条 → 输出 2 条")

    def test_missing_files_yield_defaults(self):
        out, _ = self._build()
        for row in out:
            with self.subTest(inst=row["instId"]):
                self.assertEqual(row["action"], "WAIT")
                self.assertEqual(row["score"], 0.0)
                self.assertEqual(row["strategy_tag"], "⚪ AI观望")
                self.assertEqual(row["rsi"], 50.0)
                self.assertEqual(row["fundingRate"], "--")
                self.assertEqual(row["leverage"], 3)
                self.assertEqual(row["reason"], "新组合标的，雷达与量化特征已接入")

    # ---- 优先级链 ----
    def test_action_priority_ai_over_state(self):
        out, _ = self._build(
            decisions={"BTC-USDT-SWAP": {"decision": {"action": "BUY_LONG"}}},
            state={"instruments": [{"instId": "BTC-USDT-SWAP", "action": "SELL_SHORT"}]})
        btc = next(r for r in out if r["instId"] == "BTC-USDT-SWAP")
        self.assertEqual(btc["action"], "BUY_LONG", "ai_decisions 应压过 state")

    def test_action_falls_back_to_state(self):
        out, _ = self._build(
            state={"instruments": [{"instId": "BTC-USDT-SWAP", "action": "SELL_SHORT"}]})
        btc = next(r for r in out if r["instId"] == "BTC-USDT-SWAP")
        self.assertEqual(btc["action"], "SELL_SHORT")

    def test_score_and_tag_follow_action(self):
        out, _ = self._build(decisions={
            "BTC-USDT-SWAP": {"decision": {"action": "BUY_LONG"}},
            "ETH-USDT-SWAP": {"decision": {"action": "SELL_SHORT"}}})
        b = {r["instId"]: r for r in out}
        self.assertEqual(b["BTC-USDT-SWAP"]["score"], 2.5)
        self.assertEqual(b["BTC-USDT-SWAP"]["strategy_tag"], "🟢 建议做多")
        self.assertEqual(b["ETH-USDT-SWAP"]["score"], -2.5)
        self.assertEqual(b["ETH-USDT-SWAP"]["strategy_tag"], "🔴 建议做空")

    def test_price_priority_state_then_lib(self):
        out, _ = self._build(
            state={"instruments": [{"instId": "BTC-USDT-SWAP", "price": 111.0}]},
            lib={"instruments": [{"instId": "BTC-USDT-SWAP", "price": 222.0},
                                 {"instId": "ETH-USDT-SWAP", "price": 333.0}]})
        b = {r["instId"]: r for r in out}
        self.assertEqual(b["BTC-USDT-SWAP"]["price"], 111.0, "state 优先")
        self.assertEqual(b["ETH-USDT-SWAP"]["price"], 333.0, "state 没有则用因子库")

    def test_placeholder_price_in_state_is_skipped(self):
        """⚠️ `state.price` 为 `"--"` 时必须**不能用**，要落到因子库。

        原实现是 `ins.get("price") if ins.get("price") not in (None, "--") else ...`
        —— 这个 `"--"` 判定很容易被"简化"掉，然后面板价格就变成字符串 "--"。
        """
        out, _ = self._build(
            state={"instruments": [{"instId": "BTC-USDT-SWAP", "price": "--"}]},
            lib={"instruments": [{"instId": "BTC-USDT-SWAP", "price": 222.0}]})
        btc = next(r for r in out if r["instId"] == "BTC-USDT-SWAP")
        self.assertEqual(btc["price"], 222.0, "'--' 是占位符，应被跳过")

    def test_rsi_priority_and_zero_is_kept(self):
        """⚠️ `rsi` 用 `is not None` 判定 —— 所以 **0 是合法值**，必须保留。"""
        out, _ = self._build(
            state={"instruments": [{"instId": "BTC-USDT-SWAP", "rsi": 0.0}]},
            lib={"instruments": [{"instId": "BTC-USDT-SWAP",
                                  "trend_momentum": {"rsi_14": 88.0}}]})
        btc = next(r for r in out if r["instId"] == "BTC-USDT-SWAP")
        self.assertEqual(btc["rsi"], 0.0, "RSI 0 是合法值（不是占位符），应保留")

    def test_rsi_falls_back_to_lib(self):
        out, _ = self._build(lib={"instruments": [
            {"instId": "BTC-USDT-SWAP", "trend_momentum": {"rsi_14": 88.0}}]})
        btc = next(r for r in out if r["instId"] == "BTC-USDT-SWAP")
        self.assertEqual(btc["rsi"], 88.0)

    def test_funding_rate_priority(self):
        out, _ = self._build(
            decisions={"BTC-USDT-SWAP": {"raw_funding_rate": "0.01%"}},
            lib={"instruments": [{"instId": "BTC-USDT-SWAP",
                                  "smart_money_derivatives": {"funding_rate_pct": 1.2345}}]})
        btc = next(r for r in out if r["instId"] == "BTC-USDT-SWAP")
        self.assertEqual(btc["fundingRate"], "0.01%", "ai 的原始值优先")

    def test_funding_rate_formatted_from_lib(self):
        """因子库里的 funding_rate_pct 会被格式化成 4 位小数的百分号串。"""
        out, _ = self._build(lib={"instruments": [
            {"instId": "BTC-USDT-SWAP",
             "smart_money_derivatives": {"funding_rate_pct": 1.23456}}]})
        btc = next(r for r in out if r["instId"] == "BTC-USDT-SWAP")
        self.assertEqual(btc["fundingRate"], "1.2346%", "应保留 4 位小数")

    def test_position_is_attached_by_instid(self):
        out, _ = self._build(positions=[{"instId": "BTC-USDT-SWAP", "pos": "1"}])
        b = {r["instId"]: r for r in out}
        self.assertEqual(b["BTC-USDT-SWAP"]["position"], {"instId": "BTC-USDT-SWAP", "pos": "1"})
        self.assertIsNone(b["ETH-USDT-SWAP"]["position"], "无仓应为 None")

    def test_positions_not_a_list_does_not_raise(self):
        out, _ = self._build(positions="oops")
        self.assertTrue(all(r["position"] is None for r in out))

    def test_change24h_falls_back_to_lib(self):
        out, _ = self._build(
            decisions={"BTC-USDT-SWAP": {"raw_ticker": {"chg24h": None}}},
            lib={"instruments": [{"instId": "BTC-USDT-SWAP", "chg24h": 7.5}]})
        btc = next(r for r in out if r["instId"] == "BTC-USDT-SWAP")
        # raw_ticker 里是 None → 落到 lib
        self.assertEqual(btc["chg24h"], 7.5)
        self.assertEqual(btc["change24h"], 7.5, "两个字段应同值")

    def test_time_str_priority(self):
        """`ai.time_str` → `state.timestamp` → 入参 timestamp_full。"""
        out, _ = self._build(ts="FALLBACK-TS")
        self.assertTrue(all(r["time_str"] == "FALLBACK-TS" for r in out))

        out, _ = self._build(state={"timestamp": "STATE-TS"}, ts="FALLBACK-TS")
        self.assertTrue(all(r["time_str"] == "STATE-TS" for r in out))

        out, _ = self._build(decisions={"BTC-USDT-SWAP": {"time_str": "AI-TS"}},
                             state={"timestamp": "STATE-TS"}, ts="FALLBACK-TS")
        btc = next(r for r in out if r["instId"] == "BTC-USDT-SWAP")
        eth = next(r for r in out if r["instId"] == "ETH-USDT-SWAP")
        self.assertEqual(btc["time_str"], "AI-TS", "ai.time_str 最优先")
        self.assertEqual(eth["time_str"], "STATE-TS", "没有 ai 值则用 state")

    def test_state_data_is_returned_verbatim(self):
        _, state = self._build(state={"timestamp": "T", "instruments": []})
        self.assertEqual(state["timestamp"], "T")

    def test_malformed_instruments_are_ignored(self):
        """state/lib 里的 `instruments` 不是 list、或元素不是 dict，都不应抛。"""
        out, _ = self._build(state={"instruments": "nope"},
                             lib={"instruments": [None, 1, "x"]})
        self.assertEqual(len(out), 2)

    def test_instrument_without_instid_is_skipped_in_maps(self):
        out, _ = self._build(state={"instruments": [{"no_instId": 1}]},
                             lib={"instruments": [{"no_instId": 1}]})
        self.assertEqual(len(out), 2)

    def test_calculus_block_is_assembled(self):
        out, _ = self._build(lib={"instruments": [{
            "instId": "BTC-USDT-SWAP",
            "calculus_dynamics": {"velocity": 1, "acceleration": 2,
                                  "jerk": 3, "impulse": 4}}]})
        btc = next(r for r in out if r["instId"] == "BTC-USDT-SWAP")
        self.assertEqual(btc["calculus"],
                         {"velocity_1h": 1, "accel_1h": 2, "jerk_1h": 3, "impulse_1h": 4})

    def test_leverage_defaults_to_3(self):
        out, _ = self._build(decisions={"BTC-USDT-SWAP": {"decision": {"leverage": 10}}})
        b = {r["instId"]: r for r in out}
        self.assertEqual(b["BTC-USDT-SWAP"]["leverage"], 10)
        self.assertEqual(b["ETH-USDT-SWAP"]["leverage"], 3)


class LedgerViewSmokeTest(_Base):
    """`load_ledger_lifecycle_trades(...)` —— 仅 1 处间接引用，补最小直测与可观测性因果契约。"""

    #: 返回的是**二元组** `(valid_ledger_trades, trades_table)`（实测，不是 list）
    def test_missing_ledger_returns_empty_pair(self):
        out = ledger_view.load_ledger_lifecycle_trades(
            os.path.join(self.tmp, "nope.json"), self.tmp, False, "1970-01-01 00:00:00")
        self.assertIsInstance(out, tuple)
        self.assertEqual(len(out), 2)
        self.assertEqual(out, ([], []))

    def test_corrupt_ledger_returns_empty_pair(self):
        p = os.path.join(self.tmp, "bad.json")
        with open(p, "w", encoding="utf-8") as f:
            f.write("{not json")
        out = ledger_view.load_ledger_lifecycle_trades(
            p, self.tmp, False, "1970-01-01 00:00:00")
        self.assertEqual(out, ([], []))

    def test_causal_join_attaches_snapshot_and_preserves_discipline(self):
        """因果铁律贯通：有效快照挂接 DYNAMICS_OBSERVED，历史无快照严格保持 NONE。"""
        full_snap = {k: 0.5 for k in (
            "velocity", "acceleration", "jerk", "impulse", "curvature", "power",
            "power_regime", "regime", "dynamics_quality",
            "continuation_prob_pct", "breakdown_prob_pct", "var_95_pct", "cvar_95_pct",
            "prob_regime", "is_fat_tail", "energy_integral", "deviation_area_integral"
        )}
        full_snap.update({"price": 100.0, "atr": 2.0, "null_field": None})

        # 写入测试 journal
        journal_data = [
            {
                "name": "SOL",
                "side": "long",
                "entryTime": "2026-09-18 10:05:00",
                "snapshot": full_snap,
            },
            {
                "name": "BTC",
                "side": "short",
                "entryTime": "2026-09-18 01:00:00",  # 早于开仓 > 6h，过期证据
                "snapshot": full_snap,
            },
            {
                "name": "ETH",
                "side": "long",
                "entryTime": "2026-09-18 10:45:00",  # 晚于开仓 > 20m，未来伪造
                "snapshot": full_snap,
            }
        ]
        with open(os.path.join(self.tmp, "signal_journal.json"), "w", encoding="utf-8") as f:
            json.dump(journal_data, f)

        ledger_data = [
            # 1. 正常匹配：SOL 10:00 开仓，10:05 journal 捕获 → DYNAMICS_OBSERVED
            {
                "id": "trade_sol",
                "inst": "SOL",
                "side": "多",
                "open_time": "2026-09-18 10:00:00",
                "close_time": "2026-09-18 12:00:00",
                "status": "closed",
            },
            # 2. 过期证据：BTC 08:00 开仓，快照早于 6h → NONE
            {
                "id": "trade_btc",
                "inst": "BTC",
                "side": "空",
                "open_time": "2026-09-18 08:00:00",
                "close_time": "2026-09-18 09:00:00",
                "status": "closed",
            },
            # 3. 未来快照：ETH 10:00 开仓，快照晚于 20m → NONE
            {
                "id": "trade_eth",
                "inst": "ETH",
                "side": "多",
                "open_time": "2026-09-18 10:00:00",
                "close_time": "2026-09-18 11:00:00",
                "status": "closed",
            },
            # 4. 远古历史单（无快照记录）→ 严格 NONE
            {
                "id": "trade_legacy",
                "inst": "ADA",
                "side": "多",
                "open_time": "2026-09-11 10:00:00",
                "close_time": "2026-09-11 11:00:00",
                "status": "closed",
            },
        ]
        ledger_path = os.path.join(self.tmp, "trading_ledger.json")
        with open(ledger_path, "w", encoding="utf-8") as f:
            json.dump(ledger_data, f)

        valid, table = ledger_view.load_ledger_lifecycle_trades(
            ledger_path, self.tmp, False, "1970-01-01 00:00:00")

        by_id = {t["id"]: t for t in table}
        sol = by_id["trade_sol"]
        self.assertEqual(sol["snapshot_observability"], "DYNAMICS_OBSERVED")
        self.assertIsNotNone(sol.get("entry_snapshot"))
        self.assertEqual(sol["entry_snapshot"]["velocity"], 0.5)
        self.assertNotIn("null_field", sol["entry_snapshot"])  # null 字段被 prune

        self.assertEqual(by_id["trade_btc"]["snapshot_observability"], "NONE")
        self.assertIsNone(by_id["trade_btc"].get("entry_snapshot"))

        self.assertEqual(by_id["trade_eth"]["snapshot_observability"], "NONE")
        self.assertIsNone(by_id["trade_eth"].get("entry_snapshot"))

        self.assertEqual(by_id["trade_legacy"]["snapshot_observability"], "NONE")
        self.assertIsNone(by_id["trade_legacy"].get("entry_snapshot"))


if __name__ == "__main__":
    unittest.main()
