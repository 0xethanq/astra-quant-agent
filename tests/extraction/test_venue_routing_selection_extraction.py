"""`astra_backend/venue_routing/selection.py`（阶段 4·B3 第四十三刀）回归。

## 抽了什么

`astra_backend/venue_router.py` 里**「选所质量」**域（141 行）：

| 成员 | 原位置 | 作用 |
|---|---|---|
| `_parse_iso_utc` | L76–85 | ISO-8601 → epoch；解析不了返回 `None` |
| `_hard_filters` | L96–169 | 第一层：逐候选所硬性淘汰 |
| `_balanced_pick` | L172–180 | 跨进程确定的均衡选所（审计 D7） |
| `_score` | L181–228 | 第二层：成本评分（bps，越低越好） |

| | 之前 | 之后 |
|---|---|---|
| `venue_router.py` | 393 行 | **268 行** |
| `venue_routing/selection.py` | — | 197 行（新） |

门面里剩下的 `split_allocation` / `_apply_hysteresis` / `route_signal` 属
**「分配」**域（另一件事），故不搬。

## ⚠️ 本刀踩的坑：`_parse_iso_utc` 的**位置**是被循环导入决定的

我第一版把 `_parse_iso_utc` 留在门面、由 selection **反向导入**。结果：

```
ImportError: cannot import name '_parse_iso_utc' from partially initialized
module 'astra_backend.venue_router' (most likely due to a circular import)
```

因为门面顶部要 `from .venue_routing.selection import _hard_filters`，
而 selection 又要 `from ..venue_router import _parse_iso_utc` —— 环。
故它**必须**住在 selection 里，门面通过再导出提供该名字。

> 与"哪些行被锚点钉住"无关：这是**模块图**层面的约束。
> `anchor_scan.py` 查文本锚点，查不出循环导入 —— 只能靠跑测试。
"""

from __future__ import annotations

import ast
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULE = ROOT / "astra_backend" / "venue_routing" / "selection.py"
FACADE = ROOT / "astra_backend" / "venue_router.py"

from astra_backend.exchanges import listing as listing_mod  # noqa: E402
from astra_backend.venue_router import RouterConfig  # noqa: E402
from astra_backend.venue_routing.selection import (  # noqa: E402
    _balanced_pick,
    _hard_filters,
    _parse_iso_utc,
    _score,
)

NOW_ISO = "2026-09-11T12:00:00Z"
NOW_EPOCH = datetime(2026, 9, 11, 12, 0, 0, tzinfo=timezone.utc).timestamp()


def _ok_listing(venue, environment, contract):
    return listing_mod.ListingCheck(ok=True, reason=None,
                                    checked_at=NOW_ISO, source="cache")


def _failopen_listing(venue, environment, contract):
    return listing_mod.ListingCheck(ok=True, reason="行情目录不可用，跳过对账",
                                    checked_at=NOW_ISO, source="cache")


def _cand(**kw):
    b = {"venue": "okx", "executable": True, "environment": "live",
         "min_notional": 0.0, "price": 100.0, "min_qty": 0.0, "precision": 0.0,
         "health_updated_utc": NOW_ISO, "health_max_age_s": 300.0}
    b.update(kw)
    return b


def _sig(**kw):
    b = {"symbol_canonical": "BTC-USDT-SWAP", "size_usdt": 1000.0,
         "side": "long", "price": 100.0}
    b.update(kw)
    return b


class ParseIsoTest(unittest.TestCase):
    def test_z_suffix(self):
        """带 `Z` 的输入必须解析出正确时刻。

        ⚠️ **如实记录一个"不可测"的注入**：负向验证把
        `if s.endswith("Z"): s = s[:-1] + "+00:00"` 去掉后**没有任何测试能区分** ——
        因为 `datetime.fromisoformat` 自 **Python 3.11** 起原生接受 `Z`。
        本仓参照运行时是 3.11.16，故那段是**3.8~3.10 的兼容垫**，
        在当前运行时是恒等变换。

        **保留**它（本仓 `from __future__ import annotations` 等写法表明
        仍在意 3.8+ 可运行性），但它是**契约而非可测行为**。
        """
        self.assertAlmostEqual(_parse_iso_utc("2026-09-11T12:00:00Z"), NOW_EPOCH, places=3)
        # 同时钉住"结果不因带不带 Z 而不同"，避免将来改坏成只有一种能解析
        self.assertAlmostEqual(_parse_iso_utc("2026-09-11T12:00:00Z"),
                               _parse_iso_utc("2026-09-11T12:00:00+00:00"), places=6)

    def test_offset_form(self):
        self.assertAlmostEqual(_parse_iso_utc("2026-09-11T20:00:00+08:00"), NOW_EPOCH, places=3)

    def test_invalid_returns_none(self):
        for bad in ("", None, "nonsense", "2026-13-45T99:99:99Z"):
            self.assertIsNone(_parse_iso_utc(bad), f"{bad!r} 应返回 None")

    def test_whitespace_tolerated(self):
        self.assertAlmostEqual(_parse_iso_utc("  2026-09-11T12:00:00Z  "), NOW_EPOCH, places=3)


class HardFilterTest(unittest.TestCase):
    def _run(self, sig=None, cand=None, budget=None, now=NOW_EPOCH, listing=None):
        with patch("astra_backend.venue_routing.selection.listing.ensure_contract_listed",
                   side_effect=listing or _ok_listing):
            return _hard_filters(sig or _sig(), cand or _cand(),
                                 RouterConfig(), budget, now)

    def test_all_pass(self):
        self.assertEqual(self._run(), [])

    def test_not_executable(self):
        self.assertTrue(any("executable" in r for r in self._run(cand=_cand(executable=False))))

    def test_listing_reject(self):
        r = self._run(listing=lambda v, e, c: listing_mod.ListingCheck(
            ok=False, reason="合约下架", checked_at=NOW_ISO, source="cache"))
        self.assertTrue(any("listing gate 拒" in x for x in r))

    def test_listing_failopen_is_marked_not_dropped(self):
        """⚠️ fail-open **不淘汰**，但必须带 `__FAILOPEN__` 标记（由调用方拼进 reasons）。

        直接淘汰会变成 fail-closed，与既有契约不符。
        """
        r = self._run(listing=_failopen_listing)
        self.assertTrue(any(x.startswith("__FAILOPEN__") for x in r),
                        "fail-open 必须留标记")
        self.assertFalse(any("listing gate 拒" in x for x in r), "fail-open 不得当成拒")

    def test_min_notional(self):
        self.assertTrue(any("最小名义额不足" in x for x in self._run(cand=_cand(min_notional=5000.0))))

    def test_min_qty(self):
        self.assertTrue(any("最小量不足" in x for x in self._run(cand=_cand(min_qty=100.0))))

    def test_precision_misalignment(self):
        self.assertTrue(any("步进不符" in x for x in self._run(cand=_cand(precision=0.0000003))))

    def test_precision_aligned_passes(self):
        self.assertEqual(self._run(cand=_cand(precision=0.1)), [],
                         "1000/100 = 10 与 0.1 对齐，应通过")

    def test_no_price_yields_note_not_elimination(self):
        """⚠️ 无价格时只**注记**（`__NOTE__`），不淘汰。"""
        r = self._run(sig=_sig(price=None), cand=_cand(price=None, min_qty=1.0))
        self.assertTrue(any(x.startswith("__NOTE__") for x in r))
        self.assertEqual(len(r), 1, "只应有那一条注记")

    def test_no_price_and_no_limits_passes(self):
        self.assertEqual(self._run(sig=_sig(price=None), cand=_cand(price=None)), [])

    def test_missing_health_timestamp(self):
        self.assertTrue(any("无 health_updated_utc" in x
                            for x in self._run(cand=_cand(health_updated_utc=None))))

    def test_unparsable_health_timestamp(self):
        self.assertTrue(any("无法解析" in x
                            for x in self._run(cand=_cand(health_updated_utc="nonsense"))))

    def test_stale_health(self):
        self.assertTrue(any("数据年龄" in x for x in self._run(
            cand=_cand(health_updated_utc="2026-09-11T11:00:00Z"))))

    def test_fresh_health_uses_per_candidate_override(self):
        """候选自带 `health_max_age_s` 必须覆盖配置默认值。"""
        r = self._run(cand=_cand(health_updated_utc="2026-09-11T11:00:00Z",
                                 health_max_age_s=99999.0))
        self.assertEqual(r, [], "候选择覆盖后 1 小时不算过期")

    def test_budget_insufficient(self):
        class B:
            available = 500.0
        self.assertTrue(any("预算不足" in x for x in self._run(budget=B())))

    def test_budget_sufficient(self):
        class B:
            available = 5000.0
        self.assertEqual(self._run(budget=B()), [])

    def test_budget_view_without_available_attr_is_ignored(self):
        class B:
            pass
        self.assertEqual(self._run(budget=B()), [], "无 available 属性时不得判预算不足")

    def test_error_path_can_also_record_failopen(self):
        """拒 + fail-open 标记可以同时出现（两者是独立的 if/elif 之外的追加）。"""
        r = self._run(cand=_cand(executable=False), listing=_failopen_listing)
        self.assertTrue(any("executable" in x for x in r))
        self.assertTrue(any(x.startswith("__FAILOPEN__") for x in r))


class BalancedPickTest(unittest.TestCase):
    def test_deterministic_and_in_set(self):
        venues = ["binance", "gate", "okx"]
        first = _balanced_pick("BTC", venues)
        self.assertIn(first, venues)
        for _ in range(5):
            self.assertEqual(_balanced_pick("BTC", venues), first, "必须可复现")

    def test_empty_list(self):
        self.assertEqual(_balanced_pick("BTC", []), "")

    def test_single_venue(self):
        self.assertEqual(_balanced_pick("ANY", ["okx"]), "okx")

    def test_distribution_is_not_all_one_venue(self):
        """均衡轮换：不同标的应落到不同所（否则"均衡"名不副实）。"""
        venues = ["binance", "gate", "okx"]
        picks = {_balanced_pick(s, venues)
                 for s in ("BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "LINK", "AVAX")}
        self.assertGreater(len(picks), 1, "8 个标的全落同一所说明哈希退化了")

    def test_uses_sha256_not_python_hash(self):
        """审计 D7：不得依赖 `hash()`（受 PYTHONHASHSEED 影响）。

        ⚠️ 必须**剥掉 docstring** 再看 —— 该函数的 docstring 里正解释着
        "旧式 `abs(hash(x))%n`"，我第一版直接对源码做字符串处理，
        于是被自己文档里的 `hash(` 触发假红。
        """
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "_balanced_pick")
        body = list(fn.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]                      # 去掉 docstring
        code = ast.unparse(ast.Module(body=body, type_ignores=[]))
        self.assertIn("sha256", code, "必须用 sha256 摘要取模")
        self.assertNotIn("hash(", code.replace("sha256(", ""), "不得用内置 hash()")


class ScoreTest(unittest.TestCase):
    def _run(self, sig=None, cand=None, cfg=None):
        reasons = []
        val = _score(cand or _cand(), sig or _sig(), cfg or RouterConfig(), reasons)
        return val, reasons

    def test_spread_is_additive_baseline(self):
        val, reasons = self._run(cand=_cand(spread_bps=2.0, depth_usd=1e9,
                                            fee_rate=0.0, funding_rate=0.0))
        self.assertAlmostEqual(val, 2.0, places=9)
        self.assertTrue(any("价差" in r for r in reasons))

    def test_fee_counts_both_legs(self):
        """手续费 = rate × **2 腿** × 10000。"""
        val, _ = self._run(cand=_cand(spread_bps=0.0, depth_usd=1e9,
                                      fee_rate=0.0005, funding_rate=0.0))
        self.assertAlmostEqual(val, 0.0005 * 2 * 10000.0, places=6)

    def test_depth_penalty_scales_with_shortfall(self):
        """深度不足按缺口比例惩罚；完全无深度时达上限。"""
        cfg = RouterConfig()
        full, _ = self._run(cand=_cand(spread_bps=0.0, depth_usd=0.0,
                                       fee_rate=0.0, funding_rate=0.0), cfg=cfg)
        self.assertAlmostEqual(full, cfg.depth_penalty_max_bps, places=6)

    def test_depth_penalty_scales_proportionally(self):
        """⚠️ 负向验证暴露的**真覆盖盲区**：此前只测了
        `depth=0`（惩罚=上限）与 `depth` 充足（惩罚=0），
        故"把 `ratio * 上限` 改成恒等于上限"也能通过。

        这里补中间档：`depth_need = size*10 = 10000`，取 `depth=5000` →
        缺口比 0.5 → 惩罚 = 0.5 × `depth_penalty_max_bps`。
        """
        cfg = RouterConfig()
        val, reasons = self._run(cand=_cand(spread_bps=0.0, depth_usd=5000.0,
                                            fee_rate=0.0, funding_rate=0.0), cfg=cfg)
        self.assertAlmostEqual(val, 0.5 * cfg.depth_penalty_max_bps, places=6)
        self.assertTrue(any("深度不足惩罚" in r for r in reasons))

    def test_depth_penalty_scales_with_size_too(self):
        """同样 depth 下，单子越大缺口越大 → 惩罚越重。"""
        cfg = RouterConfig()
        small, _ = self._run(sig=_sig(size_usdt=100.0),
                             cand=_cand(spread_bps=0.0, depth_usd=5000.0,
                                        fee_rate=0.0, funding_rate=0.0), cfg=cfg)
        big, _ = self._run(sig=_sig(size_usdt=1000.0),
                           cand=_cand(spread_bps=0.0, depth_usd=5000.0,
                                      fee_rate=0.0, funding_rate=0.0), cfg=cfg)
        self.assertGreater(big, small, "大单在同样深度下惩罚应更重")

    def test_depth_sufficient_has_no_penalty(self):
        cfg = RouterConfig()
        val, reasons = self._run(cand=_cand(spread_bps=0.0, depth_usd=1e9,
                                            fee_rate=0.0, funding_rate=0.0), cfg=cfg)
        self.assertAlmostEqual(val, 0.0, places=9)
        self.assertTrue(any("深度充足" in r for r in reasons))

    def test_funding_sign_follows_side(self):
        """⚠️ 多头正资金费**付费**（+），空头反向（−）。"""
        long_val, _ = self._run(sig=_sig(side="long"),
                                cand=_cand(spread_bps=0.0, depth_usd=1e9,
                                           fee_rate=0.0, funding_rate=0.0003))
        short_val, _ = self._run(sig=_sig(side="short"),
                                 cand=_cand(spread_bps=0.0, depth_usd=1e9,
                                            fee_rate=0.0, funding_rate=0.0003))
        self.assertGreater(long_val, 0.0, "多头付费应为正成本")
        self.assertLess(short_val, 0.0, "空头在正资金费下应为负成本（收费）")
        self.assertAlmostEqual(long_val, -short_val, places=9)

    def test_incumbent_bonus_is_subtracted(self):
        cfg = RouterConfig()
        base, _ = self._run(cand=_cand(spread_bps=0.0, depth_usd=1e9,
                                       fee_rate=0.0, funding_rate=0.0), cfg=cfg)
        inc, reasons = self._run(cand=_cand(spread_bps=0.0, depth_usd=1e9,
                                            fee_rate=0.0, funding_rate=0.0,
                                            current_venue=True), cfg=cfg)
        self.assertAlmostEqual(inc, base - cfg.incumbent_bonus_bps, places=9)
        self.assertTrue(any("bonus" in r for r in reasons))

    def test_stability_penalty_added(self):
        val, _ = self._run(cand=_cand(spread_bps=0.0, depth_usd=1e9, fee_rate=0.0,
                                      funding_rate=0.0, stability_penalty=7.5))
        self.assertAlmostEqual(val, 7.5, places=9)

    def test_reasons_include_venue_and_total(self):
        val, reasons = self._run()
        self.assertTrue(reasons, "必须写 reasons（调用方据此解释选所）")
        self.assertIn("[okx]", reasons[-1])
        self.assertIn(f"{val:.2f}bps", reasons[-1])


class FacadeWiringTest(unittest.TestCase):
    def test_facade_reexports_every_moved_name(self):
        import astra_backend.venue_router as vr
        for name in ("_hard_filters", "_balanced_pick", "_score", "_parse_iso_utc",
                     "_LISTING_FAILOPEN_MARK"):
            self.assertTrue(hasattr(vr, name), f"门面丢了 {name}")

    def test_facade_identity_matches_module(self):
        import astra_backend.venue_router as vr
        import astra_backend.venue_routing.selection as sel
        self.assertIs(vr._hard_filters, sel._hard_filters)
        self.assertIs(vr._balanced_pick, sel._balanced_pick)

    def test_allocation_domain_stays_in_facade(self):
        """「分配」域（拆单 / 滞回 / 编排）**不得**被搬进 selection。"""
        src = MODULE.read_text(encoding="utf-8")
        for name in ("def split_allocation", "def _apply_hysteresis",
                     "def route_signal"):
            self.assertNotIn(name, src, f"{name} 不该在 selection 里")
        import astra_backend.venue_router as vr
        for name in ("split_allocation", "_apply_hysteresis", "route_signal"):
            self.assertTrue(hasattr(vr, name))

    def test_public_api_unchanged(self):
        import astra_backend.venue_router as vr
        for name in ("RouteDecision", "RouterConfig", "route_signal", "split_allocation"):
            self.assertTrue(hasattr(vr, name))

    def test_facade_no_longer_defines_the_moved_functions(self):
        src = FACADE.read_text(encoding="utf-8")
        self.assertNotIn("def _hard_filters(", src)
        self.assertNotIn("def _score(", src)
        self.assertNotIn("def _balanced_pick(", src)
        self.assertIn("from .venue_routing.selection import", src)

    def test_module_has_no_module_level_side_effects(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        bare = [n for n in tree.body
                if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)]
        self.assertEqual(bare, [], "模块层不应有裸调用")


if __name__ == "__main__":
    unittest.main()
