"""B3 第三块（`scripts/trader/protection.py`）的旧实现差分回归。

## 这个测试在守什么

结构优化阶段 4·B3 把 `manage_position_tp_and_trailing` 里**长空各抄一遍**的两段
纯计算搬进了 `scripts/trader/protection.py`。搬家允许、行为不许变 —— 而这两个
函数是**止损线**的计算，算错一个 `max`/`min` 方向就是实盘直接亏损。

因此这里不写"实现自证"式的断言，而是把**搬走前的原门面代码原样内联为 `_legacy_*`**，
用确定性随机输入做逐值对拍：只要新实现与原实现在任何一组输入上分叉，本测试就红。

对照面覆盖：
- `rounded ==` 的**恰好相等**（半值、跨 `prec` 边界、负价）；
- `peak_profit_px` 精确落在 tier1 / tier2 触发线上（`>=` 边界，非近似）；
- `old_sl` 为 0（"无保护"，不得被当成已推进）、为负、已高于目标（不得后退）；
- 长/空两条分支。

## 为什么可以钉住"旧实现"

`_legacy_*` 是**测试内的副本**，不是被删的生产代码路径 —— 它不会随重构漂移，
但会随"有人偷偷改了新实现"立刻报警。这与仓里既有的
`tests/ops/test_three_tier_ratchet_and_cloud_sync.py`（走真实 `aft` 集成路径）互补：
那条测"接线没错"，这条测"数学没漂"。
"""
from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

scripts_dir = str(Path(__file__).resolve().parent.parent.parent / "scripts")
if scripts_dir not in sys.path:
    sys.path.insert(0, scripts_dir)

from scripts.trader.protection import (
    ai_tightens_stop,
    close_fee,
    close_trade_payload,
    protection_signals,
    ratcheted_trailing_stop,
)


# --------------------------------------------------------------------------
# 搬走前的门面原样（务必逐字保留，包括 `0.0020` 与两处 round 的写法）
# --------------------------------------------------------------------------
def _legacy_hard_stop_hit(is_long, cur_px, hard_stop_px):
    return hard_stop_px > 0 and (
        (is_long and cur_px <= hard_stop_px) or (not is_long and cur_px >= hard_stop_px)
    )


def _legacy_tightens_stop(instruction, position):
    """搬走前门面 `execute_ai_position_management` 里的内联长空双分支（逐字原样）。"""
    new_sl = float(instruction.get("suggested_sl_price", 0) or 0)
    pos_side = str(position.get("posSide", "net")).lower()
    current_px = float(position.get("markPx", position.get("last", 0)) or 0)
    avg_px = float(position.get("avgPx", 0) or 0)
    atr_val = max(float(position.get("atr_1h", 0) or 0),
                  float(position.get("atr", 0) or 0), current_px * 0.012)
    if pos_side == "long":
        min_profit_reached = (current_px - avg_px) >= 1.2 * atr_val
        safe_buffer_from_current = (current_px - new_sl) >= 0.7 * atr_val
        tightens_risk = new_sl > 0 and avg_px <= new_sl < current_px and min_profit_reached and safe_buffer_from_current
    elif pos_side == "short":
        min_profit_reached = (avg_px - current_px) >= 1.2 * atr_val
        safe_buffer_from_current = (new_sl - current_px) >= 0.7 * atr_val
        tightens_risk = new_sl > 0 and current_px < new_sl <= avg_px and min_profit_reached and safe_buffer_from_current
    else:
        tightens_risk = False
    return tightens_risk


def _legacy_ratchet_long(entry_px, atr, prec, peak_profit_px, old_sl,
                         tier1_breakeven_trigger, tier2_lock_trigger):
    stage_desc = None
    dynamic_floor_sl = old_sl
    if peak_profit_px >= tier2_lock_trigger:
        dynamic_floor_sl = max(dynamic_floor_sl, round(entry_px + 1.0 * atr, prec))
        stage_desc = f"锁定大波段利润 (保底止损 {dynamic_floor_sl})"
    elif peak_profit_px >= tier1_breakeven_trigger:
        dynamic_floor_sl = max(dynamic_floor_sl, round(entry_px + 0.0020 * entry_px, prec))
        stage_desc = f"已推保本无风险 (保底止损 {dynamic_floor_sl})"
    return dynamic_floor_sl, stage_desc


def _legacy_ratchet_short(entry_px, atr, prec, peak_profit_px, old_sl,
                          tier1_breakeven_trigger, tier2_lock_trigger):
    stage_desc = None
    dynamic_floor_sl = old_sl
    if peak_profit_px >= tier2_lock_trigger:
        dynamic_floor_sl = min(dynamic_floor_sl, round(entry_px - 1.0 * atr, prec))
        stage_desc = f"锁定大波段利润 (保底止损 {dynamic_floor_sl})"
    elif peak_profit_px >= tier1_breakeven_trigger:
        dynamic_floor_sl = min(dynamic_floor_sl, round(entry_px - 0.0020 * entry_px, prec))
        stage_desc = f"已推保本无风险 (保底止损 {dynamic_floor_sl})"
    return dynamic_floor_sl, stage_desc


class HardStopSignalParityTest(unittest.TestCase):
    """`protection_signals` 与旧内联表达式逐值对拍。"""

    def test_random_parity(self):
        rng = random.Random(20260914)
        cases = 0
        for _ in range(20000):
            is_long = rng.random() < 0.5
            cur_px = round(rng.uniform(0.0, 200000.0), rng.randint(0, 8))
            hard_stop_px = rng.choice([
                0.0, -1.0, rng.uniform(0.0, 200000.0), cur_px, cur_px * 0.999999,
            ])
            expected = _legacy_hard_stop_hit(is_long, cur_px, hard_stop_px)
            actual = protection_signals(is_long=is_long, cur_px=cur_px, hard_stop_px=hard_stop_px)
            self.assertEqual(actual, expected,
                             f"分叉: is_long={is_long} cur_px={cur_px} hard_stop_px={hard_stop_px}")
            cases += 1
        self.assertEqual(cases, 20000)

    def test_zero_stop_never_triggers(self):
        """"无保护"（stop=0）绝不能被当成击穿 —— 否则等于无止损强平。"""
        for is_long in (True, False):
            for cur_px in (0.0, 1.0, 50000.0):
                self.assertFalse(protection_signals(is_long=is_long, cur_px=cur_px, hard_stop_px=0.0))
                self.assertFalse(protection_signals(is_long=is_long, cur_px=cur_px, hard_stop_px=-5.0))

    def test_touch_is_inclusive_on_both_sides(self):
        """触及即触发（`<=` / `>=`），不是"穿过"。"""
        self.assertTrue(protection_signals(is_long=True, cur_px=100.0, hard_stop_px=100.0))
        self.assertTrue(protection_signals(is_long=False, cur_px=100.0, hard_stop_px=100.0))
        self.assertFalse(protection_signals(is_long=True, cur_px=100.01, hard_stop_px=100.0))
        self.assertFalse(protection_signals(is_long=False, cur_px=99.99, hard_stop_px=100.0))


class RatchetedTrailingStopParityTest(unittest.TestCase):
    """`ratcheted_trailing_stop` 与旧长短两份内联实现逐值对拍。"""

    TRIGGERS = (1.5, 2.2)  # (tier1_breakeven_trigger, tier2_lock_trigger) 由调用方按 ATR 传入

    def _assert_parity(self, *, is_long, entry_px, atr, prec, peak_profit_px, old_sl):
        tier1, tier2 = self.TRIGGERS
        legacy_long = _legacy_ratchet_long(entry_px, atr, prec, peak_profit_px, old_sl, tier1, tier2)
        legacy_short = _legacy_ratchet_short(entry_px, atr, prec, peak_profit_px, old_sl, tier1, tier2)
        # 旧实现里长空是**同一个函数体里的两个分支**；空头分支只算 min 那份。
        # 因此按 is_long 选择对应副本，而不是把两份都当期望。
        expected = legacy_long if is_long else legacy_short
        actual = ratcheted_trailing_stop(
            is_long=is_long, entry_px=entry_px, atr=atr, prec=prec,
            peak_profit_px=peak_profit_px, old_sl=old_sl,
            tier1_breakeven_trigger=tier1, tier2_lock_trigger=tier2,
        )
        ctx = (f"is_long={is_long} entry_px={entry_px} atr={atr} prec={prec} "
               f"peak_profit_px={peak_profit_px} old_sl={old_sl}")
        self.assertEqual(actual[0], expected[0], f"止损线分叉: {ctx}")
        self.assertEqual(actual[1], expected[1], f"stage_desc 分叉: {ctx}")

    def test_random_parity(self):
        rng = random.Random(20260915)
        for _ in range(20000):
            is_long = rng.random() < 0.5
            entry_px = rng.uniform(0.01, 120000.0)
            atr = rng.uniform(0.0, entry_px * 0.2)
            prec = rng.randint(0, 8)
            tier1, tier2 = 1.5 * atr, 2.2 * atr
            peak_profit_px = rng.uniform(-entry_px, entry_px)
            old_sl = rng.choice([
                0.0, entry_px, entry_px * 0.9, entry_px * 1.1, rng.uniform(0, 200000.0),
            ])
            self._assert_parity(is_long=is_long, entry_px=entry_px, atr=atr, prec=prec,
                                peak_profit_px=peak_profit_px, old_sl=old_sl)

    def test_exact_tier_boundaries(self):
        """恰好落在触发线上必须**进入该档**（`>=`），这是最容易抄错的一处。"""
        entry_px, atr, prec = 30000.0, 100.0, 2
        for is_long in (True, False):
            for peak, tier in ((1.5 * atr, "tier1"), (2.2 * atr, "tier2")):
                self._assert_parity(is_long=is_long, entry_px=entry_px, atr=atr, prec=prec,
                                    peak_profit_px=peak, old_sl=entry_px)
                floor, desc = ratcheted_trailing_stop(
                    is_long=is_long, entry_px=entry_px, atr=atr, prec=prec,
                    peak_profit_px=peak, old_sl=entry_px,
                    tier1_breakeven_trigger=1.5 * atr, tier2_lock_trigger=2.2 * atr)
                self.assertIsNotNone(desc, f"{tier} 边界未进入锁定档")
                if tier == "tier2":
                    self.assertEqual(floor, round(entry_px + (atr if is_long else -atr), prec))

    def test_stop_never_retreats(self):
        """单向棘轮：新止损绝不允许朝不利方向后退（长只能上、空只能下）。"""
        rng = random.Random(20260916)
        for _ in range(5000):
            is_long = rng.random() < 0.5
            entry_px = rng.uniform(1.0, 50000.0)
            atr = rng.uniform(0.0, entry_px * 0.2)
            prec = rng.randint(0, 8)
            peak_profit_px = rng.uniform(0.0, entry_px)
            old_sl = rng.uniform(0.0, entry_px * 2)
            floor, _ = ratcheted_trailing_stop(
                is_long=is_long, entry_px=entry_px, atr=atr, prec=prec,
                peak_profit_px=peak_profit_px, old_sl=old_sl,
                tier1_breakeven_trigger=1.5 * atr, tier2_lock_trigger=2.2 * atr)
            if is_long:
                self.assertGreaterEqual(floor, old_sl, "多头止损后退了")
            else:
                self.assertLessEqual(floor, old_sl, "空头止损后退了")

    def test_zero_old_stop_still_computes_floor(self):
        """`old_sl == 0`（无保护）时：算出的保底线就是目标值本身，不被 0 夹住。

        对应原门面的 `max(0, target)` / `min(0, target)` —— 多头为 target、空头为 0。
        这里同时钉住"门面只在 old_sl > 0 时才同步云端"的前提不被误改。
        """
        floor_long, _ = ratcheted_trailing_stop(
            is_long=True, entry_px=30000.0, atr=100.0, prec=2, peak_profit_px=300.0,
            old_sl=0.0, tier1_breakeven_trigger=150.0, tier2_lock_trigger=220.0)
        self.assertEqual(floor_long, 30100.0)
        floor_short, _ = ratcheted_trailing_stop(
            is_long=False, entry_px=30000.0, atr=100.0, prec=2, peak_profit_px=300.0,
            old_sl=0.0, tier1_breakeven_trigger=150.0, tier2_lock_trigger=220.0)
        self.assertEqual(floor_short, 0.0)


class AiTightensStopParityTest(unittest.TestCase):
    """`ai_tightens_stop` 与旧内联判定逐值对拍。

    这条路径在重构前**全仓零测试覆盖**，却决定"要不要动真实止损单"。
    """

    def _assert_parity(self, instruction, position):
        got = ai_tightens_stop(instruction, position)
        expected = _legacy_tightens_stop(instruction, position)
        self.assertEqual(got, bool(expected),
                         f"判定分叉: instruction={instruction} position={position}")

    def test_random_parity(self):
        rng = random.Random(20260918)
        for _ in range(20000):
            pos_side = rng.choice(["long", "short", "net", "LONG", "Short"])
            avg_px = rng.uniform(0.0001, 100000.0)
            current_px = avg_px * rng.uniform(0.5, 1.8)
            position = {
                "posSide": pos_side,
                "avgPx": avg_px,
                "markPx": current_px,
                "atr": rng.choice([0.0, rng.uniform(0.0, avg_px * 0.05)]),
            }
            if rng.random() < 0.4:
                position["atr_1h"] = rng.uniform(0.0, avg_px * 0.05)
            if rng.random() < 0.1:
                del position["markPx"]
                position["last"] = current_px
            instruction = {"suggested_sl_price": rng.choice([
                0.0, -1.0, current_px, avg_px,
                avg_px + (current_px - avg_px) * rng.uniform(-0.5, 1.5),
            ])}
            self._assert_parity(instruction, position)

    def test_long_accepts_safe_tightening(self):
        # 入场 100、现价 110、ATR 2 → 浮盈 10 >= 1.2*2；新止损 108，缓冲 2 >= 0.7*2
        self.assertTrue(ai_tightens_stop(
            {"suggested_sl_price": 108.0},
            {"posSide": "long", "avgPx": 100.0, "markPx": 110.0, "atr": 2.0}))

    def test_short_accepts_safe_tightening(self):
        # 入场 110、现价 100、ATR 2 → 浮盈 10；新止损 102，缓冲 2 >= 1.4
        self.assertTrue(ai_tightens_stop(
            {"suggested_sl_price": 102.0},
            {"posSide": "short", "avgPx": 110.0, "markPx": 100.0, "atr": 2.0}))

    def test_rejects_when_profit_too_small(self):
        """浮盈不足 1.2x ATR → 拒绝（原注释说的"有意义的盈利"门槛）。"""
        self.assertFalse(ai_tightens_stop(
            {"suggested_sl_price": 100.5},
            {"posSide": "long", "avgPx": 100.0, "markPx": 100.8, "atr": 2.0}))

    def test_rejects_when_buffer_too_close(self):
        """新止损贴现价太近（< 0.7x ATR）→ 拒绝，防噪声打到。"""
        self.assertFalse(ai_tightens_stop(
            {"suggested_sl_price": 109.9},
            {"posSide": "long", "avgPx": 100.0, "markPx": 110.0, "atr": 2.0}))

    def test_rejects_when_stop_would_loosen(self):
        """新止损低于入场价（等于放松风险）→ 必须拒绝。"""
        self.assertFalse(ai_tightens_stop(
            {"suggested_sl_price": 95.0},
            {"posSide": "long", "avgPx": 100.0, "markPx": 110.0, "atr": 2.0}))
        self.assertFalse(ai_tightens_stop(
            {"suggested_sl_price": 115.0},
            {"posSide": "short", "avgPx": 110.0, "markPx": 100.0, "atr": 2.0}))

    def test_rejects_non_positive_or_missing_stop(self):
        for bad in (0.0, -1.0, None):
            inst = {} if bad is None else {"suggested_sl_price": bad}
            self.assertFalse(ai_tightens_stop(
                inst, {"posSide": "long", "avgPx": 100.0, "markPx": 110.0, "atr": 2.0}))

    def test_unknown_side_is_false(self):
        for side in ("net", "", "LONGER", "both"):
            self.assertFalse(ai_tightens_stop(
                {"suggested_sl_price": 108.0},
                {"posSide": side, "avgPx": 100.0, "markPx": 110.0, "atr": 2.0}))

    def test_atr_falls_back_to_price_ratio(self):
        """ATR 与 atr_1h 都缺失时用 现价*1.2% 兜底（不是 0，否则门槛失效）。"""
        # 现价 1000 → ATR 地板 12；浮盈 20 >= 14.4 通过；止损 990 缓冲 10 < 8.4? 否 → 10 >= 8.4 通过
        self.assertTrue(ai_tightens_stop(
            {"suggested_sl_price": 990.0},
            {"posSide": "long", "avgPx": 980.0, "markPx": 1000.0}))
        # 同一组但止损贴到 998（缓冲 2 < 8.4）→ 拒绝
        self.assertFalse(ai_tightens_stop(
            {"suggested_sl_price": 998.0},
            {"posSide": "long", "avgPx": 980.0, "markPx": 1000.0}))


class CloseFeeParityTest(unittest.TestCase):
    """`close_fee` 与旧内联 `(pos_sz * ct_val * cur_px) * TAKER_FEE_RATE` 逐值对拍。"""

    def test_random_parity(self):
        rng = random.Random(20260917)
        for _ in range(10000):
            pos_sz = float(rng.uniform(0.001, 5000.0))
            ct_val = rng.choice([1.0, 0.01, 0.0001, 0.5])
            cur_px = rng.uniform(0.0001, 120000.0)
            rate = rng.choice([0.0005, 0.0004, 0.0])
            got = close_fee(pos_sz, ct_val, cur_px, rate)
            expected = (pos_sz * ct_val * cur_px) * rate
            self.assertEqual(got, expected,
                             f"手续费分叉: {pos_sz} {ct_val} {cur_px} {rate}")


class CloseTradePayloadParityTest(unittest.TestCase):
    """7 处 `record_trade({...})` 的字段与逐字节顺序必须与旧载荷完全一致。"""

    # 旧门面 7 处的 action_type / side 后缀 / remark 生成器（长空镜像）。
    CASES = (
        ("硬止损", "硬止损", lambda side, c: f"价格 {c['cur_px']} 触及保护止损 {c['level']}，交易所确认平仓"),
        ("保护失效退出", "保护失效退出", lambda side, c: f"云端 OCO 无法达到全仓覆盖，交易所确认安全平仓：{c['detail']}"),
        ("时间止损", "无波动出场", lambda side, c: f"持仓超 {c['hours']:g} 小时无突破，主动平仓释放配比"),
        ("阶梯锁利", "阶梯锁利平仓", lambda side, c: f"{'最高' if side == '多' else '最低'} {c['watermark']} 触发阶梯利润锁定线 {c['level']}"),
        ("移动止盈", "高点回撤止盈", lambda side, c: f"{'最高' if side == '多' else '最低'} {c['watermark']} 动能{'回撤' if side == '多' else '反弹'}触及移动止盈线"),
    )

    def _legacy_payload(self, *, is_long, timestamp_full, name, action_type, side_suffix,
                        pos_sz, cur_px, fee, pnl, remark):
        """搬走前门面里 7 处逐字相同的字段表。"""
        return {
            "is_trade": True,
            "time": timestamp_full,
            "inst": name,
            "name": name,
            "action": "平仓",
            "action_type": action_type,
            "direction": f"平{'多' if is_long else '空'}",
            "side": f"{'多' if is_long else '空'}单{side_suffix}",
            "size": pos_sz,
            "sz": pos_sz,
            "price": cur_px,
            "fee": fee,
            "pnl": pnl,
            "remark": remark,
        }

    def test_all_seven_cases_byte_identical(self):
        for is_long in (True, False):
            side = "多" if is_long else "空"
            for action_type, suffix, make_remark in self.CASES:
                ctx = {
                    "cur_px": 12345.678, "level": 11000.25, "detail": "覆盖 60%",
                    "hours": 24.0, "watermark": 13000.5,
                }
                remark = make_remark(side, ctx)
                kwargs = dict(
                    is_long=is_long, timestamp_full="2026-09-14 08:15:00", name="BTC",
                    action_type=action_type, side_suffix=suffix, pos_sz=0.5,
                    cur_px=ctx["cur_px"], fee=0.3, pnl=12.5, remark=remark)
                got = close_trade_payload(**kwargs)
                expected = self._legacy_payload(**kwargs)
                self.assertEqual(got, expected, f"载荷分叉: is_long={is_long} {action_type}")
                # dict 顺序也必须是同一套（旧载荷是字面量，顺序固定）
                self.assertEqual(list(got.keys()), list(expected.keys()),
                                 f"字段顺序变了: is_long={is_long} {action_type}")

    def test_direction_and_side_mirrors(self):
        """长空镜像必须完全对称 —— 抄错一个方向字就是台账错误。"""
        long_p = close_trade_payload(
            is_long=True, timestamp_full="t", name="ETH", action_type="阶梯锁利",
            side_suffix="阶梯锁利平仓", pos_sz=1.0, cur_px=2.0, fee=0.0, pnl=0.0, remark="r")
        short_p = close_trade_payload(
            is_long=False, timestamp_full="t", name="ETH", action_type="阶梯锁利",
            side_suffix="阶梯锁利平仓", pos_sz=1.0, cur_px=2.0, fee=0.0, pnl=0.0, remark="r")
        self.assertEqual(long_p["direction"], "平多")
        self.assertEqual(short_p["direction"], "平空")
        self.assertEqual(long_p["side"], "多单阶梯锁利平仓")
        self.assertEqual(short_p["side"], "空单阶梯锁利平仓")

    def test_no_venue_key_added_by_assembler(self):
        """`venue` 必须仍由 `record_trade()` 的 setdefault 补 —— 在此写死会改变载荷键集。"""
        payload = close_trade_payload(
            is_long=True, timestamp_full="t", name="BTC", action_type="硬止损",
            side_suffix="硬止损", pos_sz=1.0, cur_px=2.0, fee=0.0, pnl=0.0, remark="r")
        self.assertNotIn("venue", payload)
        self.assertEqual(len(payload), 14)


class TraderFacadeWiringTest(unittest.TestCase):
    """门面必须真的用上新模块，而不是把旧内联代码悄悄留在原地。"""

    def setUp(self):
        self.facade = Path(__file__).resolve().parent.parent.parent / "scripts" / "ai_factor_trader.py"
        self.src = self.facade.read_text(encoding="utf-8")

    def test_facade_imports_protection_module(self):
        self.assertIn("from scripts.trader.protection import (", self.src)
        for name in ("protection_signals", "ratcheted_trailing_stop",
                     "close_fee as _close_fee", "close_trade_payload as _close_trade_payload"):
            self.assertIn(name, self.src, f"门面未导入 {name}")

    def test_facade_calls_new_helpers(self):
        """这些调用点原在 `manage_position_tp_and_trailing` 体内；第八十九刀该函数
        搬入 `scripts/trader/position_exit.py` ⇒ **作用域收敛到实现体**
        （数字与语义一字不改），并加反证：门面自身不得再内联这些调用。

        ⚠️ 不能用"域合并文本"计数：`scripts/trader/protection.py` 里的
        `def ratcheted_trailing_stop(` 会把计数从 2 顶到 3（首版改法实测）。"""
        import ast as _ast
        from tests import source_scan
        node, path = source_scan.find_function_node(
            "scripts/ai_factor_trader.py", "manage_position_tp_and_trailing",
            pkg_name="trader")
        self.assertEqual(path.name, "position_exit.py",
                         f"持仓退出主流程应住在子包实现里，实际 {path.name}")
        impl = _ast.get_source_segment(path.read_text(encoding="utf-8"), node)
        self.assertIsNotNone(impl)
        self.assertIn("hard_stop_hit = protection_signals(", impl)
        self.assertEqual(impl.count("ratcheted_trailing_stop("), 2,
                         "长/空两个分支都必须走新模块")
        # 7 处平仓台账（硬止损1 + 保护失效1 + 时间止损1 + 阶梯锁利2 + 移动止盈2）
        self.assertEqual(impl.count("_close_trade_payload("), 7,
                         "7 处平仓台账都必须走公共装配器")
        self.assertEqual(impl.count("fee=_close_fee(") + impl.count("close_fee = _close_fee("), 7,
                         "7 处手续费计算都必须走 close_fee（6 处赋值 + 1 处直接传参）")
        # 反证：门面自己不得残留这些调用（否则上面定位到的可能不是真实现）
        for frag in ("ratcheted_trailing_stop(", "_close_trade_payload("):
            self.assertNotIn(frag, self.src, f"门面残留 {frag} ⇒ 定位可能虚 Hits")

    def test_no_inline_record_trade_dict_left(self):
        """反向哨：内联 `record_trade({` 字面量载荷不得复活。"""
        self.assertNotIn("record_trade({", self.src)
        self.assertNotIn("peak_profit_px >= tier2_lock_trigger:\n            dynamic_floor_sl", self.src)


if __name__ == "__main__":
    unittest.main()
