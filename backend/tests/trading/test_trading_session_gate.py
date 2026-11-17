"""交易时段闸门的**行为契约**（2026-09-30）。

这一个纯函数决定的是"这个 15 分钟周期到底要不要花大模型的 token" ——
实测交易主脑占全系统模型消耗的 **94%**（≈4.2M token/天），所以闸门的每一个边界
都是钱：多判一次"运行中"就是一次 43k token 的调用，多判一次"休市"就可能漏掉一段行情。

本文件把四类语义钉死：

1. **区间语义**：`[start, end)`（左含右不含）、`end <= start` = 跨午夜、
   `days` 指**窗口开始那天**（`days=[0]` + `21:30–04:00` ⇒ 周二 03:00 在内）；
2. **失败方向**（最容易被"顺手改成安全值"的一条）：缺配置 / 坏配置 / 空时段
   ⇒ **按全天候 `full` 运行 + 告警**，绝不静默停掉实盘；只有 `mode_outside`
   取值本身拼错时才回落到更保守的 `manage_only`；
3. **模式映射**：窗口外按 `mode_outside` 得 `manage_only` / `off`；
4. **永不抛异常**：闸门自己不得成为新的单点故障。
"""

import datetime
import unittest

from scripts.trader import session as S

BJ = S.BJ_TZ


def at(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime.datetime:
    return datetime.datetime(year, month, day, hour, minute, tzinfo=BJ)


#: 2026-09-28 是周一（本文件大量跨午夜用例都从这一周取时刻）。
MON_2300 = at(2026, 9, 28, 23, 0)
TUE_0300 = at(2026, 9, 29, 3, 0)
TUE_0400 = at(2026, 9, 29, 4, 0)
TUE_1200 = at(2026, 9, 29, 12, 0)


class HhmmParsingTest(unittest.TestCase):
    def test_loose_input_is_canonicalised(self):
        windows, errors = S.normalize_windows([{"days": [], "start": "7:5", "end": "09:05"}])
        self.assertEqual(errors, [])
        self.assertEqual(windows[0]["start"], "07:05")
        self.assertEqual(windows[0]["end"], "09:05")

    def test_illegal_time_skips_only_that_window(self):
        windows, errors = S.normalize_windows([
            {"start": "25:00", "end": "26:00"},
            {"start": "09:00", "end": "10:30"},
            {"start": "09:00", "end": "09:00"},
            "junk",
            {"start": "09:00", "end": None},
        ])
        self.assertEqual([w["start"] for w in windows], ["09:00"])
        self.assertEqual(len(errors), 4)
        self.assertIn("25:00", errors[0])
        self.assertIn("无法判定运行区间", errors[1])
        self.assertIn("不是对象", errors[2])

    def test_days_are_deduped_sorted_and_range_checked(self):
        windows, errors = S.normalize_windows([{"days": [5, 0, 0, "x", 9, 3], "start": "08:00", "end": "09:00"}])
        self.assertEqual(windows[0]["days"], [0, 3, 5])
        self.assertEqual(len(errors), 2)
        self.assertTrue(any("星期取值非法" in e for e in errors))
        self.assertTrue(any("越界" in e for e in errors))

    def test_empty_days_means_every_day(self):
        windows, _ = S.normalize_windows([{"days": [], "start": "08:00", "end": "09:00"}])
        self.assertEqual(windows[0]["days"], [])

    def test_duplicate_windows_are_collapsed(self):
        windows, errors = S.normalize_windows([
            {"days": [0], "start": "07:05", "end": "09:05"},
            {"days": [0], "start": "7:5", "end": "9:5"},
        ])
        self.assertEqual(len(windows), 1, "规范化后完全相同的段必须去重")
        self.assertEqual(errors, [])

    def test_windows_are_sorted_by_start(self):
        windows, _ = S.normalize_windows([
            {"start": "21:30", "end": "04:00"},
            {"start": "09:00", "end": "11:00"},
        ])
        self.assertEqual([w["start"] for w in windows], ["09:00", "21:30"])

    def test_garbage_shapes_never_raise(self):
        for raw in (None, "", 123, {"a": 1}, "abc", [None], [{"start": [], "end": {}}]):
            with self.subTest(raw=raw):
                windows, errors = S.normalize_windows(raw)
                self.assertIsInstance(windows, list)
                self.assertIsInstance(errors, list)


class ResolveSessionTest(unittest.TestCase):
    def test_disabled_means_full_time_running(self):
        state = S.resolve_session({"enabled": False, "windows": [{"start": "09:00", "end": "10:00"}]},
                                  now_bj=TUE_1200)
        self.assertEqual(state["mode"], S.MODE_FULL)
        self.assertFalse(state["restricted"])
        self.assertEqual(state["errors"], [])

    def test_in_window_is_full(self):
        cfg = {"enabled": True, "windows": [{"days": [1], "start": "09:00", "end": "11:00"}]}
        state = S.resolve_session(cfg, now_bj=at(2026, 9, 29, 10, 0))
        self.assertEqual(state["mode"], S.MODE_FULL)
        self.assertTrue(state["in_window"])
        self.assertEqual(state["matched_index"], 0)
        self.assertIn("#1", state["reason"])

    def test_out_of_window_uses_manage_only_by_default(self):
        cfg = {"enabled": True, "windows": [{"days": [1], "start": "09:00", "end": "11:00"}]}
        state = S.resolve_session(cfg, now_bj=at(2026, 9, 29, 20, 0))
        self.assertEqual(state["mode"], S.MODE_MANAGE_ONLY)
        self.assertTrue(state["restricted"])
        self.assertFalse(state["in_window"])

    def test_out_of_window_honours_off_mode(self):
        cfg = {"enabled": True, "mode_outside": "off",
               "windows": [{"days": [1], "start": "09:00", "end": "11:00"}]}
        state = S.resolve_session(cfg, now_bj=at(2026, 9, 29, 20, 0))
        self.assertEqual(state["mode"], S.MODE_OFF)

    def test_unknown_outside_mode_falls_back_to_manage_only(self):
        cfg = {"enabled": True, "mode_outside": "whatever",
               "windows": [{"days": [1], "start": "09:00", "end": "11:00"}]}
        state = S.resolve_session(cfg, now_bj=at(2026, 9, 29, 20, 0))
        self.assertEqual(state["mode"], S.MODE_MANAGE_ONLY,
                         "收不到明确指令时选保留机械风控的那一侧")
        self.assertTrue(any("模式未知" in e for e in state["errors"]))

    def test_force_overrides_the_window(self):
        cfg = {"enabled": True, "mode_outside": "off",
               "windows": [{"days": [1], "start": "09:00", "end": "11:00"}]}
        state = S.resolve_session(cfg, now_bj=at(2026, 9, 29, 20, 0), force=True)
        self.assertEqual(state["mode"], S.MODE_FULL)
        self.assertFalse(state["restricted"])
        self.assertIn("ASTRA_SESSION_FORCE", state["reason"])


class FailOpenTest(unittest.TestCase):
    """★ 失败方向：配不全 ⇒ 按**全天候运行**（读不到 ≠ 停实盘）。

    这几条是刻意的：把"读不到配置"渲染成"休市"，等于让一个坏文件把实盘静默关掉 ——
    那正是 `_slot_guard_should_skip` 的 docstring 明令禁止的方向。
    """

    def test_missing_config_runs_full_time(self):
        for raw in (None, {}, "", 0, False):
            with self.subTest(raw=raw):
                state = S.resolve_session(raw, now_bj=TUE_1200)
                self.assertEqual(state["mode"], S.MODE_FULL)
                self.assertFalse(state["restricted"])

    def test_enabled_but_no_windows_runs_full_time_with_a_loud_warning(self):
        state = S.resolve_session({"enabled": True, "windows": []}, now_bj=TUE_1200)
        self.assertEqual(state["mode"], S.MODE_FULL)
        self.assertTrue(state["errors"], "空时段必须留告警，否则调参错误静默无声")
        self.assertIn("没有任何有效时段", " ".join(state["errors"]))

    def test_enabled_but_all_windows_illegal_runs_full_time(self):
        state = S.resolve_session({"enabled": True, "windows": [{"start": "99:99", "end": "x"}]},
                                  now_bj=TUE_1200)
        self.assertEqual(state["mode"], S.MODE_FULL)
        self.assertGreaterEqual(len(state["errors"]), 1)

    def test_reason_is_human_readable_and_says_full_time(self):
        state = S.resolve_session({"enabled": True, "windows": []}, now_bj=TUE_1200)
        self.assertIn("全天候", state["reason"])
        line = S.session_state_summary(state)
        self.assertIn("[交易时段]", line)
        self.assertIn("全天候", line)


class CrossMidnightTest(unittest.TestCase):
    """跨午夜与星期掩码：`days` 指**窗口开始那天**。"""

    CFG_MON = {"enabled": True, "windows": [{"days": [0], "start": "21:30", "end": "04:00"}]}

    def test_monday_evening_is_inside(self):
        state = S.resolve_session(self.CFG_MON, now_bj=MON_2300)
        self.assertTrue(state["in_window"])
        self.assertEqual(state["mode"], S.MODE_FULL)

    def test_tuesday_early_morning_belongs_to_monday(self):
        state = S.resolve_session(self.CFG_MON, now_bj=TUE_0300)
        self.assertTrue(state["in_window"], "跨午夜的后半段属于**开始那天**的星期掩码")

    def test_end_is_exclusive(self):
        state = S.resolve_session(self.CFG_MON, now_bj=TUE_0400)
        self.assertFalse(state["in_window"], "右开：04:00 整已不在窗口内")

    def test_start_is_inclusive(self):
        cfg = {"enabled": True, "windows": [{"days": [0], "start": "21:30", "end": "23:00"}]}
        self.assertTrue(S.resolve_session(cfg, now_bj=at(2026, 9, 28, 21, 30))["in_window"])

    def test_same_clock_time_on_a_non_mask_day_is_outside(self):
        """周二 23:00 不在"仅周一"的窗口里（掩码按开始日判，不能连成一片）。"""
        state = S.resolve_session(self.CFG_MON, now_bj=at(2026, 9, 29, 23, 0))
        self.assertFalse(state["in_window"])

    def test_tuesday_mask_does_not_claim_the_monday_overnight_tail(self):
        cfg = {"enabled": True, "windows": [{"days": [1], "start": "21:30", "end": "04:00"}]}
        self.assertFalse(S.resolve_session(cfg, now_bj=TUE_0300)["in_window"],
                         "days=[1] 的跨午夜段从周二 21:30 起，不含周二凌晨")
        self.assertTrue(S.resolve_session(cfg, now_bj=at(2026, 9, 29, 22, 0))["in_window"])
        self.assertTrue(S.resolve_session(cfg, now_bj=at(2026, 9, 30, 2, 0))["in_window"])

    def test_days_empty_means_every_day_for_a_wrapping_window(self):
        cfg = {"enabled": True, "windows": [{"days": [], "start": "21:30", "end": "04:00"}]}
        for moment in (MON_2300, TUE_0300, at(2026, 10, 3, 23, 0), at(2026, 10, 4, 1, 0)):
            with self.subTest(moment=moment):
                self.assertTrue(S.resolve_session(cfg, now_bj=moment)["in_window"])

    def test_first_matching_window_wins(self):
        cfg = {"enabled": True, "windows": [
            {"start": "09:00", "end": "11:00"},
            {"start": "10:00", "end": "12:00"},
        ]}
        state = S.resolve_session(cfg, now_bj=at(2026, 9, 29, 10, 30))
        self.assertEqual(state["matched_index"], 0, "多段重叠时取排在前面的那段即可（并集语义）")


class NextChangeTest(unittest.TestCase):
    def test_inside_a_wrapping_window_the_next_change_is_its_end(self):
        cfg = {"enabled": True, "windows": [{"days": [0], "start": "21:30", "end": "04:00"}]}
        state = S.resolve_session(cfg, now_bj=MON_2300)
        self.assertEqual(state["next_change_bj"], "2026-09-29 04:00",
                         "跨午夜段的结束点在**次日**，不能被星期掩码过滤掉")

    def test_outside_the_window_the_next_change_is_its_start(self):
        cfg = {"enabled": True, "windows": [{"days": [0], "start": "21:30", "end": "04:00"}]}
        state = S.resolve_session(cfg, now_bj=TUE_1200)
        self.assertEqual(state["next_change_bj"], "2026-10-05 21:30")

    def test_no_windows_means_no_boundary(self):
        self.assertEqual(S.resolve_session({"enabled": True, "windows": []}, now_bj=TUE_1200)["next_change_bj"], "")


class SummaryAndCoverageTest(unittest.TestCase):
    def test_summary_tolerates_garbage(self):
        for raw in (None, "x", 5, [], {"mode": None}, {"errors": [None, 1]}):
            with self.subTest(raw=raw):
                line = S.session_state_summary(raw)
                self.assertTrue(line.startswith("[交易时段]"))

    def test_summary_names_the_degradation(self):
        manage = S.resolve_session({"enabled": True, "windows": [{"days": [1], "start": "09:00", "end": "11:00"}]},
                                   now_bj=at(2026, 9, 29, 20, 0))
        self.assertIn("机械风控照常", S.session_state_summary(manage))
        off = S.resolve_session({"enabled": True, "mode_outside": "off",
                                 "windows": [{"days": [1], "start": "09:00", "end": "11:00"}]},
                                now_bj=at(2026, 9, 29, 20, 0))
        self.assertIn("随后退出", S.session_state_summary(off))

    def test_disabled_coverage_is_full_time(self):
        cov = S.coverage_estimate({"enabled": False, "windows": [{"start": "09:00", "end": "10:00"}]})
        self.assertEqual(cov["saved_brain_calls_per_day"], 0)
        self.assertEqual(cov["estimated_brain_calls_per_day"], S.SLOTS_PER_DAY)

    def test_coverage_counts_days(self):
        cov = S.coverage_estimate({"enabled": True,
                                   "windows": [{"days": [0, 1, 2, 3, 4], "start": "21:30", "end": "04:00"}]})
        self.assertEqual(cov["hours_per_week"], 32.5, "5 天 × 6.5 小时")
        self.assertLess(cov["estimated_brain_calls_per_day"], S.SLOTS_PER_DAY)
        self.assertGreater(cov["saved_brain_calls_per_day"], 0)

    def test_coverage_never_raises(self):
        for raw in (None, "x", {"windows": "junk"}, {"enabled": True, "windows": [{"start": 1, "end": 2}]}):
            with self.subTest(raw=raw):
                self.assertIn("hours_per_week", S.coverage_estimate(raw))


class NaiveAndForeignClockTest(unittest.TestCase):
    def test_naive_now_is_treated_as_beijing(self):
        naive = datetime.datetime(2026, 9, 28, 23, 0)
        cfg = {"enabled": True, "windows": [{"days": [0], "start": "21:30", "end": "04:00"}]}
        self.assertTrue(S.resolve_session(cfg, now_bj=naive)["in_window"])

    def test_utc_now_is_converted_to_beijing(self):
        utc = datetime.datetime(2026, 9, 28, 15, 0, tzinfo=datetime.timezone.utc)  # = 北京 23:00
        cfg = {"enabled": True, "windows": [{"days": [0], "start": "21:30", "end": "04:00"}]}
        self.assertTrue(S.resolve_session(cfg, now_bj=utc)["in_window"])


if __name__ == "__main__":
    unittest.main()
