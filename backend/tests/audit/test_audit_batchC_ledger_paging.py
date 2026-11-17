"""批C 回归钉（2026-09-13 · 台账截断：data_health 常驻「触顶 limit=100」告警）。

取证：sync_full_ledger 拉 OKX 平仓历史用 `positions_history(limit=100)` **单页即止**，
`_mark(... truncated_at=100)` 由 `len >= 100` 反推。后果有二：
① 平仓笔数越 100 后，更早的记录永远取不到——台账只能靠 trading_ledger.json 旧行
   合并续命，一旦重算/迁移/换机即静默丢历史（历史是回测与归因的地基）；
② 告警语义被污染：每轮都挂 PARTIAL，真正需要警惕的「取数失败」淹没在常驻噪声里。
修：okx_rest 两个历史接口补 after/before；sync 侧新增 _fetch_history_paged 分页取尽，
truncated 只由分页器「未能证取尽」时诚实给出。

⚠️ 游标语义实测校正（demo 实号 2026-09-13，本钉据此固定行为）：
   after=<posId> → `51000 Parameter after error`；after=<毫秒 uTime> → 200 且正确回溯
   （首页与次页 posId 重叠 4 条，故必须按 (id,uTime) 去重）。官方文档措辞为 posId，
   与实现不符——若有人"照文档"把游标改回 posId，本文件第二组钉会立刻变红。
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
for _p in (str(ROOT), str(ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import sync_full_ledger as sfl  # noqa: E402


def _pos(pos_id: str, u_time: int) -> dict:
    return {"posId": pos_id, "uTime": str(u_time), "instId": "BTC-USDT-SWAP"}


class TestFetchHistoryPaged(unittest.TestCase):
    """分页器：防漏（累加+去重）·防死循环（游标不推进即停）·诚实（未证取尽才标 truncated）。"""

    def test_two_pages_then_short_page_is_complete(self):
        calls = []

        def fetch(*, limit, after):
            calls.append(after)
            if after is None:
                return [_pos(f"p{i}", 1000 + i) for i in range(100)]
            return [_pos(f"q{i}", 500 + i) for i in range(30)]

        rows, truncated = sfl._fetch_history_paged(fetch, id_field="posId")
        self.assertEqual(len(rows), 130)
        self.assertFalse(truncated, "页未满即证明取尽，不得标截断")
        self.assertEqual(calls, [None, "1099"], "第二页游标必须取上页末条的 uTime（毫秒时间戳）")

    def test_boundary_overlap_between_pages_deduped(self):
        """实测首页/次页 posId 重叠 4 条：靠 (id,uTime) 去重，不得重复计入。"""
        def fetch(*, limit, after):
            if after is None:
                return [_pos(f"p{i}", 1000 + i) for i in range(100)]
            # 次页含 4 条与首页同 (posId,uTime) 的重叠 + 26 条新记录
            return [_pos(f"p{i}", 1000 + i) for i in range(96, 100)] + [_pos(f"q{i}", 500 + i) for i in range(26)]

        rows, truncated = sfl._fetch_history_paged(fetch, id_field="posId")
        self.assertEqual(len(rows), 126)
        self.assertFalse(truncated)

    def test_exactly_full_last_page_still_complete(self):
        # 边界：末页恰好 100 条 → 仍需再探一页，探到空页才算取尽
        def fetch(*, limit, after):
            if after is None:
                return [_pos(f"a{i}", 3000 + i) for i in range(100)]
            if after == "3099":
                return [_pos(f"b{i}", 2000 + i) for i in range(100)]
            return []

        rows, truncated = sfl._fetch_history_paged(fetch, id_field="posId")
        self.assertEqual(len(rows), 200)
        self.assertFalse(truncated, "空页=已取尽")

    def test_cursor_ignored_stops_and_marks_truncated(self):
        """服务端忽略 after（同页反复返回）→ 游标不再变旧即停，且诚实标截断。"""
        calls = []

        def fetch(*, limit, after):
            calls.append(after)
            return [_pos(f"p{i}", 1000 + i) for i in range(100)]

        rows, truncated = sfl._fetch_history_paged(fetch, id_field="posId")
        self.assertEqual(len(rows), 100, "重复页不得重复计入")
        self.assertTrue(truncated, "无法推进 = 未证取尽，必须标截断")
        self.assertEqual(len(calls), 2, "游标不推进须立即停，不得耗尽页数上限")

    def test_max_pages_exhausted_marks_truncated(self):
        def fetch(*, limit, after):
            base = 0 if after is None else int(after) // 1  # 每页 uTime 递减一档
            start = 5000 - (0 if after is None else 100 * ((5000 - base) // 100 + 1))
            return [_pos(f"p{start - i}", start - i) for i in range(100)]

        rows, truncated = sfl._fetch_history_paged(fetch, id_field="posId", max_pages=3)
        self.assertEqual(len(rows), 300)
        self.assertTrue(truncated, "页页全满且用尽上限 → 未证取尽")

    def test_empty_first_page_is_empty_not_truncated(self):
        rows, truncated = sfl._fetch_history_paged(lambda *, limit, after: [], id_field="posId")
        self.assertEqual(rows, [])
        self.assertFalse(truncated)

    def test_within_page_duplicates_deduped(self):
        def fetch(*, limit, after):
            if after is None:
                return [_pos("dup", 1), _pos("dup", 1), _pos("x", 2)]
            return []

        rows, _ = sfl._fetch_history_paged(fetch, id_field="posId")
        self.assertEqual(len(rows), 2, "(posId,uTime) 同键只计一次")

    def test_missing_cursor_field_marks_truncated_without_looping(self):
        """记录缺 uTime（异常数据）→ 无法推进，当页即停并标截断。"""
        calls = []

        def fetch(*, limit, after):
            calls.append(after)
            return [{"posId": f"p{i}"} for i in range(100)]

        rows, truncated = sfl._fetch_history_paged(fetch, id_field="posId")
        self.assertEqual(len(rows), 100, "无 uTime → 去重键唯一化不成立，按 posId 各计一次")
        self.assertTrue(truncated)
        self.assertEqual(len(calls), 1, "游标为空无法推进 → 当页即停，不得空转重取同页")


class TestInScopeTruncation(unittest.TestCase):
    """截断判定必须按「在册窗口」收口（台账只收 close_time >= reset_time）。

    实测（2026-09-13）：分页拿到 500 条、最早 05-15，而基线 reset_time=2026-09-11 11:50:47
    → 台账其实一条不漏；若仍按「分页未取尽」报 PARTIAL，就是永久假告警。反之若取到的最早
    记录仍晚于基线，则在册记录可能真的缺，必须报。
    """

    TZ = __import__("datetime").timezone(__import__("datetime").timedelta(hours=8))
    RESET = "2026-09-11 11:50:47"

    def _ms(self, s: str) -> int:
        import datetime as _d
        t = _dt = _d.datetime.strptime(s, "%Y-%m-%d %H:%M:%S").replace(tzinfo=self.TZ)
        return int(_dt.timestamp() * 1000)

    def test_not_truncated_never_flags(self):
        self.assertFalse(sfl._history_truncated_in_scope(False, self._ms("2026-09-12 00:00:00"), self.RESET, self.TZ))

    def test_fetched_below_baseline_is_not_truncated_in_scope(self):
        self.assertFalse(
            sfl._history_truncated_in_scope(True, self._ms("2026-05-15 18:03:00"), self.RESET, self.TZ),
            "已取到基线之前 → 在册窗口已覆盖，不得报截断",
        )

    def test_stopped_above_baseline_flags_truncated(self):
        self.assertTrue(
            sfl._history_truncated_in_scope(True, self._ms("2026-09-12 10:00:00"), self.RESET, self.TZ),
            "停在基线之后 → 在册记录可能缺失，必须报",
        )

    def test_unknown_oldest_is_conservative(self):
        for bad in (0, None, "abc"):
            self.assertTrue(
                sfl._history_truncated_in_scope(True, bad, self.RESET, self.TZ),
                f"最早时间不可知({bad!r})时必须保守报截断",
            )


class TestOkxHistoryPagingWiring(unittest.TestCase):
    """防漂移源码钉：sync 必须走分页器，游标必须是时间戳，且不得再用 len>=100 反推截断。"""

    def setUp(self):
        self.src = (ROOT / "scripts" / "sync_full_ledger.py").read_text(encoding="utf-8")
        self.rest = (ROOT / "scripts" / "okx_rest.py").read_text(encoding="utf-8")

    def test_sync_uses_paged_fetch_for_both_histories(self):
        self.assertIn('_fetch_history_paged(okx_rest.positions_history, id_field="posId")', self.src)
        self.assertIn('_fetch_history_paged(okx_rest.orders_history, id_field="ordId")', self.src)
        self.assertNotIn("okx_rest.positions_history(limit=100)", self.src, "单页调用不得复活")

    def test_cursor_is_timestamp_not_posid(self):
        """实测：posId 作游标被 OKX 拒（51000）。默认游标字段必须是 uTime。"""
        self.assertIn('cursor_field="uTime"', self.src)
        self.assertNotIn('cursor_field="posId"', self.src, "游标改回 posId 会 100% 报 51000")

    def test_truncation_flag_is_scope_aware(self):
        self.assertIn("_history_truncated_in_scope(_ph_trunc", self.src)
        self.assertIn("reset_time, tz_bj", self.src)
        self.assertNotIn('"partial" if (len(pos_history) >= 100', self.src)

    def test_okx_rest_exposes_cursor_params(self):
        for fn in ("def positions_history(", "def orders_history("):
            seg = self.rest[self.rest.index(fn):]
            seg = seg[:seg.index(")\n") + 1]
            self.assertIn("after", seg, f"{fn} 缺 after 游标")
            self.assertIn("before", seg, f"{fn} 缺 before 游标")


if __name__ == "__main__":
    unittest.main()
