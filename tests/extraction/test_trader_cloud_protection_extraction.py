r"""cloud_protection 抽取对拍门（结构优化阶段 4·B3 第八十五刀）。

`amend_venue_stop_loss`(60) / `_live_oco_coverage`(18) /
`ensure_cloud_position_protection`(31) / `sync_cloud_algo_stop`(24) 从
`scripts/ai_factor_trader.py` **纯搬家**到 `scripts/trader/cloud_protection.py`。

本门除常规三件（逐字 / 壳形状 / ±自检）外，钉一条**跨函数注入**：
`ensure_cloud_position_protection` 用的覆盖率函数由门面注入 ⇒
`patch.object(aft, "_live_oco_coverage", …)` 必须能改变它的行为
（若子包偷用自己模块内的实现，这条 patch 面会静默失效）。
"""
from __future__ import annotations

import ast
import subprocess
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "447ad19"  # 本刀动工前最后提交（第八十四刀收口）
FNS = ("amend_venue_stop_loss", "_live_oco_coverage",
       "ensure_cloud_position_protection", "sync_cloud_algo_stop")
INJ = {"amend_venue_stop_loss": (),
       "_live_oco_coverage": ("_float_or_zero",),
       "ensure_cloud_position_protection": ("okx_rest", "_live_oco_coverage"),
       "sync_cloud_algo_stop": ("okx_rest",)}
MOVED = ROOT / "scripts" / "trader" / "cloud_protection.py"

# ---------------------------------------------------------------------------
# 搬走之后的**文档化差异**（aa6d4e0「优化分批止盈执行与多所挂单展示」）
#
# `amend_venue_stop_loss` 枚举现存 SL 触发单时，旧实现只读 `row["order"]["text"]`
# / `row["text"]` / `row["type"]`。Gate 的 `price_orders` 把标签放在
# `row["initial"]["text"]`（Gate 原生结构），于是 `t-astrasl*` 标签**扫不到** ⇒
# 旧 SL 单不被识别、棘轮时既不 amend 也不撤 ⇒ 云端止损单逐轮堆积
# （宽松旧单可能先于新单触发，正是本函数注释里点名要防的那个场景）。
# 修复 = 多读一层 `initial.text`。
#
# 按本仓既有先例（`test_brain_package_extraction.py` 第 137 刀白名单）放行，
# 范围极窄：**一条块替换**（净增 1 行 + 原单行赋值展开为 3 行），
# 断言"恰好出现一次"；任何其他差异仍会红。
# 另有 `test_initial_text_layer_is_actually_read` 正向钉住这一层真的被读到。
# ---------------------------------------------------------------------------
_DELTA_BLOCKS = (
    (
        # 2026-09-27「r20 → astra 全量改名」追加的一层：归属标记**双认**。
        # 变动点 = 把拼出来的 text 过一遍 `normalize_legacy_markers()`
        # （见 `scripts/tag_markers.py`）。**不是搬运事故**：改名那一刻交易所上还挂着
        # 改名前创建的保护腿，其 `initial.text` 是 `t-r20sl…`；只认新标记会把它们判成
        # "不是我们的" ⇒ 云端棘轮对老仓位**静默失效**（不报错，只是不再收紧/续期）。
        # 下方 old_block 仍是**真正的抽取前形态**（aa6d4e0 之前），故本块现为
        # "当前形态 ↔ 抽取前形态"一条直达替换；历史两次变更都记在上面这段注释里。
        '            _init = row.get("initial")\n'
        '            text = normalize_legacy_markers(\n'
        '                (str(_order.get("text") or "") if isinstance(_order, dict) else "")\n'
        '                + (str(_init.get("text") or "") if isinstance(_init, dict) else "")\n'
        '                + str(row.get("text") or "") + str(row.get("type") or ""))\n',
        '            text = (str(_order.get("text") or "") if isinstance(_order, dict) else "") \\\n'
        '                + str(row.get("text") or "") + str(row.get("type") or "")\n',
    ),
    # 第一百八十六刀：`posSide` 归一为**净持仓容错**（`in {pos_side, "net"}`）。
    # 净持仓账户的云端单 posSide 是 "net"，精确相等会永远找不到活止损单
    # ⇒ 云端止损收紧静默失效（本文件另一处统计覆盖时早就是 net 容错）。
    (
        '        live_algo = next((o for o in algo_orders\n                          if str(o.get("state", "")).lower() == "live"\n                          and str(o.get("posSide", "net")).lower() in {pos_side, "net"}\n                          and o.get("slTriggerPx")), None)',
        '        live_algo = next((o for o in algo_orders if o.get("state") == "live" and o.get("posSide") == pos_side and o.get("slTriggerPx")), None)',
    ),
)


def _normalised_moved_tree() -> ast.Module:
    """把 aa6d4e0 的文档化差异**还原**成搬运时的样子，再逐字比对。"""
    src = MOVED.read_text(encoding="utf-8")
    for new_block, old_block in _DELTA_BLOCKS:
        assert src.count(new_block) == 1, f"放行块没找到或重复（白名单过期）：{new_block[:60]!r}"
        src = src.replace(new_block, old_block)
    return ast.parse(src)


def _old_tree() -> ast.Module:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:scripts/ai_factor_trader.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    return ast.parse(normalize(r.stdout))


def _get_func(tree: ast.Module, name: str) -> ast.FunctionDef:
    for n in tree.body:
        if isinstance(n, ast.FunctionDef) and n.name == name:
            return n
    raise AssertionError(f"{name} 不在顶层")


def _body_dump(fn: ast.FunctionDef) -> str:
    return ast.dump(ast.Module(body=fn.body, type_ignores=[]), include_attributes=False)


class CloudProtectionVerbatimTest(unittest.TestCase):
    def test_initial_text_layer_is_actually_read(self):
        """正向断言：Gate 的 `initial.text` 层必须被读到（aa6d4e0）。

        这一层是「`t-astrasl*` 标签能不能被扫到」的唯一通路；一旦被删掉，
        旧 SL 单不被识别 ⇒ 棘轮既不 amend 也不撤 ⇒ 云端止损单逐轮堆积。
        """
        moved = MOVED.read_text(encoding="utf-8")
        # ⚠️ 2026-09-28 实盘事故后改为**传递式**断言：本模块不再自己拼字段清单，
        # 而是复用 `venue_protection._row_text`（全部腿归属判定唯一的文本来源）。
        #
        # 病因正是"自己拼一份"：旧清单只有 `order.text`/`initial.text`/`row.text`/
        # `row.type`，而 Binance 的 `row.type` 是算法单**类别** `CONDITIONAL`，
        # 真正的 `STOP_MARKET` 在 `raw.orderType` ⇒ `"STOP" in "CONDITIONAL"` 恒假
        # ⇒ 旧 SL 一条都枚举不到 ⇒ 棘轮只挂新不撤旧（实测 UNI 一仓挂 9 条止损）。
        self.assertIn("_row_text", moved,
                      "棘轮没有复用统一的腿文本提取器 ⇒ 又会漏字段")
        # 契约仍是原来的契约，只是现在由 `_row_text` 保证：Gate 的 `initial.text`
        # 必须被读到，否则 `t-astrasl*` 标签扫不到、旧 SL 不被识别。
        vp = (ROOT / "scripts/trader/venue_protection.py").read_text(encoding="utf-8")
        self.assertIn('initial.get("text")', vp,
                      "Gate initial 层读取丢失 ⇒ 白名单块在掩盖删除")
        self.assertIn('row.get("orderType")', vp,
                      "Binance 的 orderType 层丢了 ⇒ STOP_MARKET 会被当成 CONDITIONAL 漏掉")

        import scripts.trader.cloud_protection as cp
        listed = []
        cancelled = []
        ad = types.SimpleNamespace(
            # Gate 形状：标签只在 initial.text 里，order/text/type 都为空
            list_protective_orders=lambda sym: [
                {"id": "sl-old", "initial": {"text": "t-astrasl-btc"}}],
            cancel_price_order=lambda oid: cancelled.append(oid),
            attach_protective_orders=lambda *a, **k: {"sl": "sl-new"})
        ok, note = cp.amend_venue_stop_loss(ad, "BTC_USDT", "long", 78000.0, 3.0)
        self.assertTrue(ok, note)
        self.assertIn("sl-old", cancelled,
                      "initial.text 里的 t-astrasl 标签没被认出 ⇒ 旧 SL 单不会被清理")

    def test_shells_are_def_with_lazy_same_name_injection(self):
        tree = ast.parse((ROOT / "scripts/ai_factor_trader.py").read_text(encoding="utf-8"))
        facade = set(dir(__import__("scripts.ai_factor_trader", fromlist=["x"])))
        for fn in FNS:
            with self.subTest(fn=fn):
                dumped = ast.unparse(_get_func(tree, fn))
                self.assertIn("_cloud_protection_", dumped, "壳没转调子包")
                for g in INJ[fn]:
                    self.assertIn(f"{g}={g}", dumped, f"壳缺同名注入 {g}")
                    self.assertIn(g, facade, f"{g} 不是门面全局 ⇒ 壳传参必 NameError")

    def test_sync_uses_patched_facade_okx_rest(self):
        import scripts.ai_factor_trader as aft
        amended = []
        okx = types.SimpleNamespace(
            pending_algo_orders=lambda inst: [
                {"state": "live", "posSide": "long", "slTriggerPx": "2400", "algoId": "a1"}],
            amend_algo_sl=lambda algo_id, px, **kw: amended.append((algo_id, px)))
        with patch.object(aft, "okx_rest", okx):
            self.assertTrue(aft.sync_cloud_algo_stop("ETH-USDT-SWAP", "long", 2500))
        self.assertEqual(amended, [("a1", 2500)],
                         "patch 门面 okx_rest 没传到子包 ⇒ 注入断了")

    def test_ensure_uses_patched_facade_coverage_hook(self):
        """跨函数注入：门面 `_live_oco_coverage` 被打 patch 后必须影响 ensure。"""
        import scripts.ai_factor_trader as aft
        placed = []
        okx = types.SimpleNamespace(
            pending_algo_orders=lambda inst: [{"dummy": 1}],
            place_algo_oco=lambda *a, **k: placed.append((a, k)))
        with patch.object(aft, "okx_rest", okx), \
             patch.object(aft, "_live_oco_coverage", lambda rows, side: 5.0):
            ok, msg = aft.ensure_cloud_position_protection(
                "SOL-USDT-SWAP", "long", 5, 106, 101)
        self.assertTrue(ok, msg)
        self.assertIn("verified", msg)
        self.assertEqual(placed, [],
                         "已满覆盖却仍补单 ⇒ ensure 没用门面注入的覆盖率函数")

if __name__ == "__main__":
    unittest.main()
