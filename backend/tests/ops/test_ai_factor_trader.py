"""实盘交易主循环门面（ai_factor_trader.py）收口 —— 第 303 刀。

本模块是**实盘下单的主入口**（调度器每 15 分钟拉起一次）。拆分后它主要剩两类东西：

1. **薄壳** —— 把 `scripts/trader/*` 的实现按**调用期同名注入**装配起来。这类"缝"
   一旦被改回 import 期绑定就会**静默失效**（函数照跑、结果照对，只是不再受测试控制，
   而且会真的出网/真的下单）。
2. **编排** —— `execute_portfolio()` 按固定顺序调用各 stage，任何一步返回 `None`
   都必须**立刻中止本轮**（fail-closed），不许带着"读不到"的账户态继续往下走。

另外钉住两处模块级导入兜底与 `single_trader_cycle` 的双重防重（锁 + 同槽去重）。

⚠️ **OKX 专用化**：跨所保护巡检 stage（`venue_protection_watchdog_stage` 及其防抖
状态读写）与 `ASTRA_VENUE_PROTECTION_WATCHDOG_*` 环境变量已随多所执行面整体移除 ——
本系统只在 OKX 上持仓，`execute_portfolio` 的 stage 序列里**不再有** watchdog 一步。
"""
from __future__ import annotations

import ast
import fcntl
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent.parent
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import scripts.ai_factor_trader as aft  # noqa: E402

_SRC = Path(aft.__file__).read_text(encoding="utf-8")
_TREE = ast.parse(_SRC)


def _try_with(marker: str) -> ast.Try:
    """按**内容标记**定位模块级 `try` 兜底块，不按绝对行号。

    2026-09-28：这里原本钉的是 `_try_at(33/234/254)`。三所平权期间在文件顶部
    增删了一行 import，三处行号整体移位 ⇒ 本组用例全部 `AssertionError`；同一
    个坑在改名那一刀已经踩过一次（`test_ai_brain_trader` 的 `lineno == 1012`）。
    行号不是契约，块里那段代码才是。
    """
    hits = [n for n in _TREE.body
            if isinstance(n, ast.Try) and marker in ast.unparse(n)]
    if len(hits) != 1:
        raise AssertionError(f"标记 {marker!r} 命中 {len(hits)} 个模块级 try（应为恰好 1 个）")
    return hits[0]


# 两个兜底块各自的**内容标记**（在块内唯一出现，改行号不会失效）
_TRY_VERSION = "astra_backend.version"
_TRY_BACKEND = "from db_manager import"


def _exec_node(node, extra=None):
    """按真实文件路径执行单个 AST 节点，命中行号归属本模块。

    `extra` 用来补上被抽取节点所依赖的模块级名字（`os` / `sys`）—— 抽出来的
    只是那一个 `try`，不是整个模块，所以这些名字得由调用方给。
    """
    module = ast.Module(body=[node], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace: dict = {"os": aft.os, "sys": sys}
    if extra:
        namespace.update(extra)
    exec(compile(module, aft.__file__, "exec"), namespace)  # noqa: S102
    return namespace


class ImportFallbackTests(unittest.TestCase):
    """两处模块级兜底：失败时也必须留下**可用**对象，而不是让整模块炸掉。"""

    def test_version_falls_back_when_version_module_unavailable(self):
        with patch.dict(sys.modules, {"astra_backend.version": None}):
            ns = _exec_node(_try_with(_TRY_VERSION))
        self.assertEqual(ns["__version__"], "7.6.0")

    def test_backend_facade_missing_leaves_six_none_sentinels(self):
        # 六件套缺失时必须是 None 哨兵（调用点据此决定"跳过/降级"），而不是 AttributeError
        poisoned = {"db_manager": None, "qq_notifier": None, "ai_brain_trader": None}
        with patch.dict(sys.modules, poisoned):
            ns = _exec_node(_try_with(_TRY_BACKEND))
        for name in ("record_trade_sqlite", "notify_trade_open", "notify_trade_close",
                     "execute_batch_ai_brain_cycle", "get_latest_ai_decision",
                     "read_cycle_health"):
            self.assertIn(name, ns, name)
            self.assertIsNone(ns[name], name)


class ThinShellInjectionTests(unittest.TestCase):
    """薄壳必须在**调用时**从本模块全局取名，否则既有补丁缝静默失效。"""

    def test_fetch_candles_direct_delegates_to_module_global(self):
        seen = []
        with patch.object(aft, "fetch_candles",
                          lambda inst, bar="15m", limit=45: seen.append((inst, bar, limit))
                          or {"candles": True}):
            result = aft.fetch_candles_direct("BTC-USDT-SWAP", bar="1H", limit=7)
        self.assertEqual(result, {"candles": True})
        self.assertEqual(seen, [("BTC-USDT-SWAP", "1H", 7)])

    def test_read_stop_cooldowns_state_resolves_path_at_call_time(self):
        seen = []
        with patch.object(aft, "STOP_COOLDOWN_FILE", "/tmp/sandbox-cooldown.json"), \
             patch.object(aft, "_cooldowns_read_state",
                          lambda path: seen.append(path) or ({"k": 1}, False)):
            self.assertEqual(aft._read_stop_cooldowns_state(), ({"k": 1}, False))
        self.assertEqual(seen, ["/tmp/sandbox-cooldown.json"])

    def test_run_captured_uses_shared_spawn_helper(self):
        import astra_backend.spawn as spawn
        seen = {}
        with patch.object(spawn, "run_script",
                          lambda script, timeout=15, label=None: seen.update(
                              script=script, timeout=timeout, label=label) or "OUT"):
            self.assertEqual(aft._run_captured("/x/y.py", "标签", timeout=42), "OUT")
        self.assertEqual(seen, {"script": "/x/y.py", "timeout": 42, "label": "标签"})

    def test_run_captured_auto_widens_sync_full_ledger_timeout(self):
        import astra_backend.spawn as spawn
        seen = {}
        with patch.object(spawn, "run_script",
                          lambda script, timeout=15, label=None: seen.update(
                              script=script, timeout=timeout, label=label) or "OUT"):
            self.assertEqual(aft._run_captured("/scripts/sync_full_ledger.py"), "OUT")
        self.assertEqual(seen, {"script": "/scripts/sync_full_ledger.py", "timeout": 60, "label": None})

    def test_utc_age_seconds_delegates(self):
        with patch.object(aft, "_rr_utc_age_seconds", lambda ts, now: 123.5):
            self.assertEqual(aft._utc_age_seconds("2026-01-01", 1.0), 123.5)

    def test_fetch_single_instrument_data_injects_all_dependencies(self):
        seen = {}

        def fake(item, positions, usdt, *, news_sentiment_file, fetch_candles_direct,
                 instrument_profile, load_adaptive_config):
            seen.update(item=item, positions=positions, usdt=usdt,
                        news=news_sentiment_file,
                        candles=fetch_candles_direct,
                        profile=instrument_profile,
                        adaptive=load_adaptive_config)
            return {"ok": True}

        with patch.object(aft, "_fetch_single_instrument_data", fake):
            result = aft.fetch_single_instrument_data({"instId": "X"}, [1], 100.0)
        self.assertEqual(result, {"ok": True})
        self.assertEqual(seen["item"], {"instId": "X"})
        self.assertEqual(seen["usdt"], 100.0)
        self.assertEqual(seen["news"], aft.NEWS_SENTIMENT_FILE)
        # 四处注入必须都是本门面的当前对象（不是子模块 import 期烘焙的旧副本）
        self.assertIs(seen["candles"], aft.fetch_candles_direct)
        self.assertIs(seen["profile"], aft.instrument_profile)
        self.assertIs(seen["adaptive"], aft.load_adaptive_config)


class InstrumentProfileTests(unittest.TestCase):
    """池条目 > 资产类别档 > 代码兜底：三处（提示词/下单/复算）同源。"""

    def test_pool_values_override_asset_class(self):
        profile = aft.instrument_profile({"sl_atr_mult": "2.5", "entry_threshold": 0.8},
                                         "crypto")
        self.assertEqual(profile["sl_atr_mult"], 2.5)
        self.assertEqual(profile["entry_threshold"], 0.8)

    def test_blank_and_missing_values_keep_asset_class_default(self):
        base = aft.instrument_profile({}, "crypto")
        profile = aft.instrument_profile({"sl_atr_mult": "", "tp_atr_mult": None,
                                          "trailing_kick_in": "   "}, "crypto")
        self.assertEqual(profile["sl_atr_mult"], base["sl_atr_mult"])
        self.assertEqual(profile["tp_atr_mult"], base["tp_atr_mult"])
        self.assertEqual(profile["trailing_kick_in"], base["trailing_kick_in"])

    def test_unparsable_value_is_skipped_without_aborting_the_rest(self):
        # 非空但转不成 float ⇒ 走 continue，后续键仍要处理
        profile = aft.instrument_profile({"sl_atr_mult": "abc", "tp_atr_mult": "3.5"},
                                         "crypto")
        base = aft.instrument_profile({}, "crypto")
        self.assertEqual(profile["sl_atr_mult"], base["sl_atr_mult"])
        self.assertEqual(profile["tp_atr_mult"], 3.5)

    def test_unknown_asset_class_falls_back_to_crypto(self):
        self.assertEqual(aft.instrument_profile({}, "does-not-exist"),
                         aft.instrument_profile({}, "crypto"))

    def test_none_inst_is_tolerated(self):
        self.assertEqual(aft.instrument_profile(None, "crypto"),
                         aft.instrument_profile({}, "crypto"))


class AtomicWriteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "state.json")

    def test_writes_json_with_0600_permissions(self):
        aft._atomic_write_json(self.path, {"a": 1})
        self.assertTrue(Path(self.path).exists())
        self.assertEqual(Path(self.path).stat().st_mode & 0o777, 0o600)
        self.assertIn('"a": 1', Path(self.path).read_text(encoding="utf-8"))

    def test_no_tmp_residue_on_success(self):
        aft._atomic_write_json(self.path, {"a": 1})
        self.assertEqual(list(Path(self.tmp.name).glob("*.tmp")), [])

    def test_failure_unlinks_tmp_and_reraises(self):
        with patch.object(aft.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                aft._atomic_write_json(self.path, {"a": 1})
        self.assertEqual(list(Path(self.tmp.name).glob("*.tmp")), [])
        self.assertFalse(Path(self.path).exists())

    def test_unlink_failure_is_swallowed_before_reraising(self):
        # 清理本身失败也不许掩盖原始异常（原始 OSError 必须冒出来）
        with patch.object(aft.os, "replace", side_effect=OSError("disk full")), \
             patch.object(aft.os, "unlink", side_effect=OSError("busy")):
            with self.assertRaises(OSError) as ctx:
                aft._atomic_write_json(self.path, {"a": 1})
        self.assertIn("disk full", str(ctx.exception))


class PruneTrackersTests(unittest.TestCase):
    """清理失效追踪器，但**任何一个真实在管持仓都不许被删**。"""

    def test_removes_trackers_without_live_position(self):
        # ★ 键的形状是 `f"{完整 instId}_{posSide小写}"` —— 用的是**池内 instId**，不是 base
        trackers = {"A-USDT-SWAP_long": {}, "B-USDT-SWAP_short": {}, "GONE-USDT-SWAP_long": {}}
        real = {"A-USDT-SWAP": {"posSide": "long", "pos": 3},
                "B-USDT-SWAP": {"posSide": "short", "pos": 1}}
        self.assertEqual(aft.prune_trackers(trackers, real), 1)
        self.assertEqual(sorted(trackers), ["A-USDT-SWAP_long", "B-USDT-SWAP_short"])

    def test_base_name_alone_does_not_match(self):
        # base 形态的键**不算**有效（会被当失效清掉）—— 钉住"必须用完整 instId"
        trackers = {"A_long": {}}
        real = {"A-USDT-SWAP": {"posSide": "long", "pos": 3}}
        self.assertEqual(aft.prune_trackers(trackers, real), 1)
        self.assertEqual(trackers, {})

    def test_zero_position_is_not_a_live_position(self):
        trackers = {"A-USDT-SWAP_long": {}}
        self.assertEqual(aft.prune_trackers(
            trackers, {"A-USDT-SWAP": {"posSide": "long", "pos": 0}}), 1)
        self.assertEqual(trackers, {})

    def test_net_side_defaults_to_net(self):
        trackers = {"A-USDT-SWAP_net": {}}
        real = {"A-USDT-SWAP": {"pos": 2}}          # 无 posSide ⇒ net
        self.assertEqual(aft.prune_trackers(trackers, real), 0)
        self.assertEqual(list(trackers), ["A-USDT-SWAP_net"])

    def test_unparsable_pos_raises_instead_of_being_treated_as_flat(self):
        # ⚠️ 实测行为（本刀仅记录，**未改**）：`float(position.get("pos", 0) or 0)`
        #    在源码里**没有 try/except** —— 交易所回一个非数字的 `pos` 时，
        #    `prune_trackers` 会直接把 ValueError 抛给调用方（本轮清理整体中断），
        #    而不是把该仓位当平仓、进而**误删**它的追踪器。
        #    这个方向比"静默当平仓"安全，但异常会一路冒到 `execute_portfolio`。
        trackers = {"A-USDT-SWAP_long": {}}
        real = {"A-USDT-SWAP": {"posSide": "long", "pos": "not-a-number"}}
        with self.assertRaises(ValueError):
            aft.prune_trackers(trackers, real)
        self.assertEqual(list(trackers), ["A-USDT-SWAP_long"])   # 未被误删

    def test_empty_inputs_are_noops(self):
        self.assertEqual(aft.prune_trackers({}, {}), 0)


class ReservationManagerTests(unittest.TestCase):
    """每次取用都新建实例 ⇒ 风控页改预算**热生效**，不必重启进程。"""

    def test_positive_budget_is_passed_as_total_limit(self):
        from astra_backend import risk_reservation
        seen = {}
        with patch.object(aft, "portfolio_risk_budget_usdt", lambda: 250.0), \
             patch.object(risk_reservation, "get_manager",
                          lambda db_path, total_limit_usdt: seen.update(
                              db_path=db_path, limit=total_limit_usdt) or "MGR"):
            self.assertEqual(aft.reservation_manager(), "MGR")
        self.assertEqual(seen["limit"], 250.0)
        self.assertEqual(seen["db_path"], risk_reservation.DEFAULT_DB_PATH)

    def test_zero_budget_means_no_total_limit(self):
        from astra_backend import risk_reservation
        seen = {}
        with patch.object(aft, "portfolio_risk_budget_usdt", lambda: 0.0), \
             patch.object(risk_reservation, "get_manager",
                          lambda db_path, total_limit_usdt: seen.update(
                              limit=total_limit_usdt) or "MGR"):
            aft.reservation_manager()
        self.assertIsNone(seen["limit"])


class FloatOrZeroTests(unittest.TestCase):
    def test_absolute_value(self):
        self.assertEqual(aft._float_or_zero(-3.5), 3.5)
        self.assertEqual(aft._float_or_zero("4.25"), 4.25)

    def test_unparsable_and_none_yield_zero(self):
        self.assertEqual(aft._float_or_zero("abc"), 0.0)
        self.assertEqual(aft._float_or_zero(None), 0.0)
        self.assertEqual(aft._float_or_zero({}), 0.0)


class SingleTraderCycleTests(unittest.TestCase):
    """双重防重：**锁**（跨进程）+ **同槽去重**（15 分钟槽内只跑一次）。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.lock = str(Path(self.tmp.name) / ".trader.lock")
        for name, value in (("DATA_DIR", self.tmp.name),
                            ("TRADER_LOCK_FILE", self.lock),
                            ("TRADER_SLOT_FILE", str(Path(self.tmp.name) / "slot.json")),
                            ("_slot_guard_should_skip", lambda slot: False),
                            ("freeze_okx_environment", lambda: _Frozen()),
                            ("unfreeze_okx_environment", lambda: None)):
            patcher = patch.object(aft, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_skips_when_lock_held_elsewhere(self):
        holder = open(self.lock, "a+", encoding="utf-8")
        self.addCleanup(holder.close)
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        ran = []
        self.assertIsNone(aft.single_trader_cycle(lambda: ran.append(True))())
        self.assertEqual(ran, [])

    def test_skips_when_slot_already_used(self):
        with patch.object(aft, "_slot_guard_should_skip", lambda slot: True):
            ran = []
            self.assertIsNone(aft.single_trader_cycle(lambda: ran.append(True))())
        self.assertEqual(ran, [])

    def test_normal_run_writes_pid_and_releases_lock(self):
        def job():
            # 锁文件里应当已经写下本进程 pid
            written = Path(self.lock).read_text(encoding="utf-8")
            self.assertEqual(written, str(aft.os.getpid()))
            return "DONE"

        self.assertEqual(aft.single_trader_cycle(job)(), "DONE")
        # 锁已释放：换个 fd 能立刻抢到
        probe = open(self.lock, "a+", encoding="utf-8")
        self.addCleanup(probe.close)
        fcntl.flock(probe.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

    def test_force_bypasses_the_slot_dedup_but_still_records_the_slot(self):
        """`ASTRA_SESSION_FORCE=1`（后台「立即运行」）⇒ 不被同槽去重吞掉，但仍写槽文件。

        为什么必须绕过：休市周期会提前 return，槽文件却已经写下 —— 紧接着点
        「立即运行」就会撞上"同槽重复"而被静默忽略（实测的坑：点两次只有第一次有效）。
        为什么仍要写槽：写下去才能保证**下一轮定时周期**照旧按同槽去重。
        """
        ran = []
        slot_file = Path(aft.TRADER_SLOT_FILE)
        def job():
            ran.append(True)
            return "DONE"
        with patch.object(aft, "_slot_guard_should_skip", lambda slot: True), \
                patch.dict(os.environ, {"ASTRA_SESSION_FORCE": "1"}):
            self.assertEqual(aft.single_trader_cycle(job)(), "DONE")
        os.environ.pop("ASTRA_SESSION_FORCE", None)
        self.assertEqual(ran, [True], "强制运行必须真的跑起来")
        self.assertTrue(slot_file.exists(), "仍要写槽文件，供下一轮定时周期去重")
        self.assertIn("slot", json.loads(slot_file.read_text(encoding="utf-8")))

    def test_default_path_still_honours_the_slot_guard(self):
        with patch.object(aft, "_slot_guard_should_skip", lambda slot: True):
            ran = []
            self.assertIsNone(aft.single_trader_cycle(lambda: ran.append(True))())
        self.assertEqual(ran, [], "不设 ASTRA_SESSION_FORCE 时行为必须逐位不变")


class _Frozen:
    mode = "live"
    identity = "main"
    configured = True


class _PortfolioHarness(unittest.TestCase):
    """`execute_portfolio` 编排用例的**共享夹具**（本身不含用例）。

    2026-09-30：交易时段闸门需要在**同一套 stage 桩**上再验一遍"窗口外怎么走"，
    故把夹具提出来给 `ExecutePortfolioTests` 与 `SessionGateTests` 共用 ——
    复制一份 setUp 迟早会与这边漂移（本仓吃过太多次"同一语义两处写"）。
    """

    #: phase1 的 11 项输出（顺序即 `fetch_positions_and_reconcile` 的返回顺序）：
    #: active_pos_count / all_positions / entries_blocked / long_count /
    #: pending_inst_ids / real_pos_dict / reserved_long / reserved_short /
    #: reserved_slot / short_count / usdt_available
    PHASE1 = (2, [{"instId": "BTC-USDT-SWAP"}], False, 1, {"p1"}, {"BTC-USDT-SWAP": {}},
              0, 0, 0, 1, 5000.0)
    SCAN = (600.0, {"cache": 1}, False, "")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.calls: dict = {}
        self.stages: list[str] = []

        def record(name):
            def fn(**kwargs):
                self.stages.append(name)
                self.calls[name] = kwargs
                return None
            return fn

        self._record = record
        self._patch("DATA_DIR", self.tmp.name)
        self._patch("TRADER_LOCK_FILE", str(Path(self.tmp.name) / ".lock"))
        self._patch("TRADER_SLOT_FILE", str(Path(self.tmp.name) / "slot.json"))
        self._patch("_slot_guard_should_skip", lambda slot: False)
        self._patch("trading_session_state", lambda now_bj=None: {"mode": "full", "active": True, "reason": "test"})
        self._patch("freeze_okx_environment", lambda: _Frozen())
        self._patch("unfreeze_okx_environment", lambda: None)
        self._patch("current_environment", lambda: _Frozen())
        self._patch("pool_is_trustworthy", lambda: True)
        self._patch("write_market_data_health_snapshot", record("health_snapshot"))
        self._patch("cycle_disclosure_summary", lambda payload: "DISCLOSURE")
        self._patch("write_cycle_disclosure_snapshot", record("write_disclosure"))

    def _patch(self, name, value):
        patcher = patch.object(aft, name, value)
        patcher.start()
        self.addCleanup(patcher.stop)
        return value

    def _wire(self, *, preflight=("BLOCKED", "TS"), phase1=None, cb_active=False):
        self._patch("preflight_reconcile_and_housekeeping",
                    lambda **kw: (self.calls.__setitem__("preflight", kw), preflight)[1])
        self._patch("data_shape_preflight_stage",
                    lambda **kw: (self.calls.__setitem__("shape", kw), ["v"])[1])
        self._patch("fetch_positions_and_reconcile",
                    lambda **kw: (self.calls.__setitem__("phase1", kw),
                                  self.PHASE1 if phase1 is None else phase1)[1])
        self._patch("fetch_universe_and_manage_positions",
                    lambda **kw: (self.calls.__setitem__("universe", kw),
                                  (["F"], ["ACT"], {"T": 1}))[1])
        self._patch("scan_risk_gates_and_ai_brain",
                    lambda **kw: (self.calls.__setitem__("scan", kw),
                                  (self.SCAN[0], self.SCAN[1], cb_active, "reason"))[1])
        self._patch("execute_entry_scan",
                    lambda **kw: (self.stages.append("entry_scan"),
                                  self.calls.__setitem__("entry", kw))[0])
        self._patch("persist_state_and_sync_ledger",
                    lambda **kw: (self.stages.append("persist"),
                                  self.calls.__setitem__("persist", kw))[0])
        self._patch("cycle_disclosure_payload",
                    lambda **kw: (self.calls.__setitem__("disclosure", kw), {"d": 1})[1])

    def _run(self):
        return aft.execute_portfolio()

class ExecutePortfolioTests(_PortfolioHarness):
    """`execute_portfolio` 的 stage 编排：任何一步返回 None 都必须**立刻中止本轮**。

    ⚠️ OKX 专用化后 stage 序列为：
    preflight → 形状预检 → phase1（持仓/挂单/余额）→ 标的池与持仓管理 →
    熔断/主脑扫描 → 入场扫描（条件）→ 行情健康快照 → 状态落盘 →
    周期披露。原来的跨所保护巡检（watchdog）一步已整体移除。
    """

    def test_preflight_none_aborts_before_anything_else(self):
        self._patch("preflight_reconcile_and_housekeeping", lambda **kw: None)
        self._patch("fetch_positions_and_reconcile",
                    self._record("phase1_should_not_run"))
        self._patch("data_shape_preflight_stage", self._record("shape_should_not_run"))
        self.assertIsNone(self._run())
        self.assertEqual(self.stages, [])

    def test_phase1_none_aborts_before_universe_fetch(self):
        self._patch("preflight_reconcile_and_housekeeping",
                    lambda **kw: ("BLOCKED", "TS"))
        self._patch("data_shape_preflight_stage", lambda **kw: ["v"])
        self._patch("fetch_positions_and_reconcile", lambda **kw: None)
        self._patch("fetch_universe_and_manage_positions",
                    self._record("universe_should_not_run"))
        self.assertIsNone(self._run())
        self.assertNotIn("universe_should_not_run", self.stages)

    def test_happy_path_runs_every_stage_in_order(self):
        self._wire()
        self._run()
        self.assertEqual(self.stages,
                         ["entry_scan", "health_snapshot", "persist",
                          "write_disclosure"])

    def test_preflight_tuple_is_unpacked_into_shape_stage(self):
        self._wire()
        self._run()
        # preflight 返回的 entries_blocked 必须传给形状预检与后续 stage
        self.assertEqual(self.calls["shape"]["intents_path"], aft.OPEN_INTENT_FILE)
        self.assertEqual(self.calls["phase1"]["entries_blocked"], "BLOCKED")
        self.assertEqual(self.calls["universe"]["timestamp_full"], "TS")

    def test_phase1_unpacking_reaches_downstream_stages(self):
        self._wire()
        self._run()
        scan = self.calls["scan"]
        self.assertEqual(scan["active_pos_count"], 2)
        self.assertEqual(scan["long_count"], 1)
        self.assertEqual(scan["short_count"], 1)
        self.assertEqual(scan["usdt_available"], 5000.0)
        self.assertIs(scan["execute_batch_ai_brain_cycle"], aft.execute_batch_ai_brain_cycle)

    def test_entry_scan_is_skipped_when_circuit_breaker_active(self):
        self._wire(cb_active=True)
        self._run()
        self.assertNotIn("entry_scan", self.stages)
        # 但止损/持久化等后续 stage 仍要跑
        self.assertIn("persist", self.stages)

    def test_entry_scan_is_skipped_when_pool_untrustworthy(self):
        self._wire()
        self._patch("pool_is_trustworthy", lambda: False)
        self._run()
        self.assertNotIn("entry_scan", self.stages)
        # 池不可信只禁新开仓，持仓风控/落盘/披露仍必须跑完
        self.assertIn("persist", self.stages)
        self.assertIn("write_disclosure", self.stages)

    def test_disclosure_receives_shape_violations_and_recomputed_entries_blocked(self):
        self._wire(cb_active=True)
        self._run()
        disc = self.calls["disclosure"]
        self.assertEqual(disc["shape_violations"], ["v"])
        # ★ `entries_blocked` 在披露里是**持仓阶段重算后**的值（PHASE1[2]=False），
        #   不是 preflight 那个 —— 位置查询比预检更接近事实，后者只是初值
        self.assertIs(disc["entries_blocked"], False)
        # 坏所集合仍按原名注入（OKX 专用化后结构性为空，但注入面保留）
        self.assertIs(disc["broken_venues"], aft._BROKEN_VENUES)

    def test_lock_skip_prevents_the_whole_cycle(self):
        holder = open(aft.TRADER_LOCK_FILE, "a+", encoding="utf-8")
        self.addCleanup(holder.close)
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self._patch("preflight_reconcile_and_housekeeping", self._record("preflight_should_not_run"))
        self.assertIsNone(self._run())
        self.assertEqual(self.stages, [])


class SessionGateTests(_PortfolioHarness):
    """交易时段闸门在 `execute_portfolio` 里的编排契约（2026-09-30）。

    三条语义分别对应三种模式，任何一条走错都不是"少跑一点"，而是钱：

    | 模式 | 必须发生 | 绝不能发生 |
    |---|---|---|
    | `full`（默认/窗口内/强制） | 与改造前**逐位一致** | 被闸门改动任何一处 |
    | `manage_only`（窗口外默认） | 跳过主脑调用与入场扫描；持仓/落盘/披露照跑 | 叫大模型、开新仓 |
    | `off`（窗口外可选） | preflight（含**超时挂单回收**）+ 披露，然后退出 | 查持仓、动追踪止损、覆盖 trading_state |
    """

    MANAGE = {"mode": "manage_only", "restricted": True, "reason": "休市中（窗口外）：只做机械风控",
              "errors": [], "next_change_bj": "2026-09-30 21:30", "in_window": False,
              "matched_index": None, "enabled": True, "window_count": 1}
    OFF = {**MANAGE, "mode": "off", "reason": "休市中（窗口外）：完全停跑巡检"}
    FULL = {"mode": "full", "restricted": False, "reason": "未启用交易时段（全天候运行）",
            "errors": [], "next_change_bj": "", "in_window": False, "matched_index": None,
            "enabled": False, "window_count": 0}

    def _session(self, state):
        self._patch("trading_session_state", lambda now_bj=None: state)

    def test_full_mode_passes_the_real_brain_callable(self):
        self._wire()
        self._session(self.FULL)
        self._run()
        scan = self.calls["scan"]
        self.assertIs(scan["execute_batch_ai_brain_cycle"], aft.execute_batch_ai_brain_cycle,
                      "全天候时必须把真函数传下去（既有锚点也钉这一条）")
        self.assertIs(scan["session_restricted"], False)
        self.assertIn("entry_scan", self.stages)

    def test_manage_only_keeps_the_mechanical_carers_running(self):
        self._wire()
        self._session(self.MANAGE)
        self._run()
        scan = self.calls["scan"]
        self.assertIs(scan["session_restricted"], True)
        self.assertNotIn("entry_scan", self.stages, "窗口外不许尝试开新仓")
        for stage in ("persist", "health_snapshot", "write_disclosure"):
            self.assertIn(stage, self.stages,
                          f"{stage} 是持仓安全链路的一部分，窗口外必须照跑")
        self.assertIn("universe", self.calls, "追踪止损/分批止盈依赖因子装配，必须照跑")

    def test_manage_only_discloses_the_degradation(self):
        self._wire()
        self._session(self.MANAGE)
        self._run()
        self.assertIs(self.calls["disclosure"]["session"], self.MANAGE)

    def test_off_mode_stops_after_preflight_and_never_touches_positions(self):
        self._wire()
        self._session(self.OFF)
        self.assertIsNone(self._run())
        self.assertIn("preflight", self.calls, "相位 0/0a（含超时挂单回收）必须跑完")
        for stage in ("shape", "phase1", "universe", "scan", "persist", "health_snapshot"):
            self.assertNotIn(stage, self.calls, f"off 模式不得进入 {stage}")

    def test_off_mode_still_writes_one_disclosure_row(self):
        self._wire()
        self._session(self.OFF)
        self._run()
        self.assertIn("write_disclosure", self.stages,
                      "休市必须每轮留一行披露，否则「为什么什么都没发生」无从解释")
        self.assertIs(self.calls["disclosure"]["session"], self.OFF,
                      "离场前必须把时段状态交给披露载荷（session_* 键的单一来源）")

    def test_off_mode_disclosure_carries_the_preflight_block_state(self):
        self._wire(preflight=("BLOCKED", "TS"))
        self._session(self.OFF)
        self._run()
        self.assertTrue(self.calls["disclosure"]["entries_blocked"])

    def test_force_env_is_read_through_the_session_shell(self):
        """`trading_session_state` 是壳：`ASTRA_SESSION_FORCE=1` ⇒ 强制 full。

        这里直接验壳（编排侧已由上面几条覆盖），确保"后台立即运行"这条路真的有闸。
        """
        self._patch("_load_trading_session",
                    lambda: {"enabled": True, "mode_outside": "off",
                             "windows": [{"days": [0], "start": "00:00", "end": "00:01"}]})
        with patch.dict(os.environ, {"ASTRA_SESSION_FORCE": "1"}):
            self.assertEqual(aft.trading_session_state()["mode"], "full")
        os.environ.pop("ASTRA_SESSION_FORCE", None)


class MainGuardTests(unittest.TestCase):
    """`__main__`：未配置 API Key ⇒ 退出码 3，**不执行任何交易**。"""

    @staticmethod
    def _main_guard_node():
        """按**语义**定位 CLI 入口，不按绝对行号。

        2026-09-28：这里原来钉的是 `n.lineno == 1324`，任何在文件前段加一行的
        改动都会让本组用例 `StopIteration` 静默失效（同批 `test_ai_brain_trader`
        也踩过同一个坑）。行号不是契约，判据本身才是。
        """
        def _is_main_guard(n):
            if not isinstance(n, ast.If):
                return False
            t = n.test
            return (isinstance(t, ast.Compare)
                    and isinstance(t.left, ast.Name) and t.left.id == "__name__"
                    and len(t.comparators) == 1
                    and isinstance(t.comparators[0], ast.Constant)
                    and t.comparators[0].value == "__main__")
        return next(n for n in _TREE.body if _is_main_guard(n))

    def _run_guard(self, configured):
        node = self._main_guard_node()
        module = ast.Module(body=[node], type_ignores=[])
        ast.fix_missing_locations(module)
        ran = []
        namespace = {
            "__name__": "__main__",
            "selected_environment": lambda: _Frozen() if configured else _Unconfigured(),
            "execute_portfolio": lambda: ran.append(True),
            "sys": sys,
            "print": lambda *a, **k: None,
        }
        error = None
        try:
            exec(compile(module, aft.__file__, "exec"), namespace)  # noqa: S102
        except SystemExit as exc:
            error = exc
        return error, ran

    def test_unconfigured_exits_three_without_trading(self):
        error, ran = self._run_guard(False)
        self.assertIsInstance(error, SystemExit)
        self.assertEqual(error.code, 3)
        self.assertEqual(ran, [])

    def test_configured_runs_the_cycle(self):
        error, ran = self._run_guard(True)
        self.assertIsNone(error)
        self.assertEqual(ran, [True])


class _Unconfigured:
    configured = False


if __name__ == "__main__":
    unittest.main()
