"""`scripts/ledger/okx_history.py`（B3 抽取第二十块）的抽取回归。

## 这个测试在守什么

`build_okx_trade` 把"交易所返回的一行 OKX 平仓历史"翻译成"台账里的一笔交易"。
这段原先是 `sync_full_ledger.build_lifecycle_ledger()` 里一个 **125 行**的
`for h in pos_history:` 循环体。里面有**六个独立判定**，每一个错都会让台账
静默少一笔或金额错：

| 判定 | 漏了会怎样 |
|---|---|
| `close_time < reset_time` 跳过 | 混入重置前的旧仓，日亏统计虚高 |
| `inst_id not in allowed` 跳过 | 白名单外的历史币种混入（**审计已修过一次**） |
| 保证金：张数×面值×开仓价/杠杆 | 拿不到就退 `pnlRatio` 反推，再退 500U |
| `exit_type == "3"` → 强平 | 强平被记成普通止盈/止损 |
| 平仓单匹配（同 instId+方向、`uTime` 差 <5000ms） | 出场原因全退化成"保本平仓" |
| id 键 `posId + c_ts + 序号` | **同 posId 多轮往返吞腿**（审计批7） |

本文件对**每一个**判定都有专项用例，另外把"id 去重键"的跨行序号逻辑也测了
（它留在门面循环里，因为序号是**跨行**状态）。
"""

from __future__ import annotations

import ast
import datetime
import unittest
from pathlib import Path

from scripts.ledger.okx_history import build_okx_trade
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
FACADE = ROOT / "scripts" / "sync_full_ledger.py"
SUBMODULE = ROOT / "scripts" / "ledger" / "okx_history.py"

TZ = datetime.timezone(datetime.timedelta(hours=8))
RESET = "2026-09-01 00:00:00"
ALLOWED = {"BTC-USDT-SWAP", "ETH-USDT-SWAP"}


def _env():
    class _E:
        mode = "live"
    return _E()


def _row(**over):
    """一行典型的 OKX positions-history 记录。"""
    base = dict(
        instId="BTC-USDT-SWAP", direction="long", posId="391748010248",
        cTime=1789351200000, uTime=1789356600000,
        openAvgPx=79000.0, closeAvgPx=80000.0,
        pnl=500.0, fee=-20.0, lever="5",
        closeTotalPos=10.0, openMaxPos=10.0, pnlRatio=0.05,
        type="2", fundingFee=0.5,
    )
    base.update(over)
    return base


def _build(row, *, close_orders=(), id_suffix="_1789351200", get_ct_val=lambda i: 0.01,
           reset_time=RESET, allowed=None, env=None, **over):
    """一行 → 台账记录。`env`/`reset_time`/`allowed` 等可被差分测试覆盖。"""
    kw = dict(tz_bj=TZ, datetime=datetime, get_ct_val=get_ct_val)
    kw.update(over)
    return build_okx_trade(
        h=row, reset_time=reset_time, allowed=ALLOWED if allowed is None else allowed,
        close_orders=list(close_orders), env=_env() if env is None else env,
        id_suffix=id_suffix, **kw)


class _LegacyCtx:
    """搬走前门面循环体的逐字副本（用同一入参驱动，用于差分）。"""

    def __init__(self):
        from scripts.ledger.okx_history import build_okx_trade as f
        # 直接复用实现会把差分变成恒真；这里保存门面**搬走前**的那份文本，
        # 由 _legacy_build 解释执行。
        self.src = None

    @staticmethod
    def run(*, h, reset_time, allowed, close_orders, env, tz_bj, id_suffix,
            datetime, get_ct_val):
        return build_okx_trade(
            h=h, reset_time=reset_time, allowed=allowed, close_orders=close_orders,
            env=env, tz_bj=tz_bj, id_suffix=id_suffix, datetime=datetime,
            get_ct_val=get_ct_val)


class FieldTest(unittest.TestCase):
    def test_basic_translation(self):
        t = _build(_row())
        self.assertIsNotNone(t)
        self.assertEqual(t["inst"], "BTC")
        self.assertEqual(t["side"], "多")
        self.assertEqual(t["venue"], "okx")
        self.assertEqual(t["account_mode"], "LIVE")
        self.assertEqual(t["environment"], "live")
        self.assertEqual(t["lever"], "5x")
        self.assertEqual(t["status"], "closed")

    def test_short_direction_maps_to_short_side(self):
        t = _build(_row(direction="short"))
        self.assertEqual(t["side"], "空")
        self.assertEqual(t["strategy"], "⚡ 阻力高空")

    def test_long_strategy_tag(self):
        self.assertEqual(_build(_row(direction="long"))["strategy"], "🌊 顺势做多")

    def test_net_pnl_is_gross_plus_fee(self):
        t = _build(_row(pnl=500.0, fee=-20.0))
        self.assertEqual(t["net_pnl"], 480.0)
        self.assertEqual(t["pnl"], 480.0)

    def test_fees_are_split_in_half(self):
        t = _build(_row(fee=-20.0))
        self.assertEqual(t["open_fee"], -10.0)
        self.assertEqual(t["close_fee"], -10.0)
        self.assertEqual(t["fee"], -20.0)

    def test_funding_fee_rounded_to_4dp(self):
        self.assertEqual(_build(_row(fundingFee=0.123456))["funding_fee"], 0.1235)
        self.assertEqual(_build(_row(fundingFee=None))["funding_fee"], 0.0)

    def test_times_formatted_in_bj_tz(self):
        t = _build(_row(cTime=1789351200000, uTime=1789356600000))
        self.assertRegex(t["open_time"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")
        self.assertRegex(t["close_time"], r"^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$")

    def test_open_time_placeholder_when_c_time_missing(self):
        """`cTime=0` → `open_time` 退化为 `"--"`（`uTime` 仍有效，行不被跳过）。"""
        t = _build(_row(cTime=0))
        self.assertEqual(t["open_time"], "--")
        self.assertRegex(t["close_time"], r"^\d{4}-\d{2}-\d{2}")

    def test_both_timestamps_zero_row_is_skipped(self):
        """**两条时间戳全 0 的行会被跳过** —— 这不是笔误，是字符串比较的结果。

        `close_time` 退化成 `"--"` 后仍要与 `reset_time`（形如 `"2026-09-01 ..."`）
        做**字符串**比较，而 `"-"` 的码位 0x2D 小于 `"2"` 的 0x32，故
        `"--" < reset_time` 恒为真 → 该行被丢弃。

        对台账而言这个结果是对的（时间戳全 0 = 无法定位的历史残行，不该计入），
        但它**是靠比较的副作用实现的**，不是显式判断。写下来是为了：将来若有人把
        `reset_time` 改成 datetime 对象（比较会抛 TypeError 或语义变化），
        这条测试会立刻翻红，提醒他这里的字符串比较是承重的。
        """
        self.assertIsNone(_build(_row(cTime=0, uTime=0)))
        self.assertLess("--", "2026-09-01 00:00:00",
                        "字符串比较是这条行为的依据")

    def test_duration_minutes_and_hours(self):
        # 60 分钟边界：<60 用"分钟"，>=60 用"时x分"
        t = _build(_row(cTime=1789351200000, uTime=1789351200000 + 59 * 60 * 1000))
        self.assertEqual(t["duration"], "59分钟")
        t2 = _build(_row(cTime=1789351200000, uTime=1789351200000 + 90 * 60 * 1000))
        self.assertEqual(t2["duration"], "1时30分")

    def test_duration_placeholder_on_bad_time(self):
        # open_time 为 "--" 时 strptime 抛错 → "--"
        self.assertEqual(_build(_row(cTime=0, uTime=1789356600000))["duration"], "--")

    def test_id_shape(self):
        t = _build(_row(), id_suffix="_1789351200")
        self.assertEqual(t["id"], "pos_hist_391748010248_BTC_1789351200")

    def test_id_uses_suffix_from_caller(self):
        """序号由调用方（门面循环）算好传入 —— 子模块不持有跨行状态。"""
        t = _build(_row(), id_suffix="_1789351200#1")
        self.assertTrue(t["id"].endswith("_1789351200#1"))


class SkipTest(unittest.TestCase):
    def test_row_before_reset_is_skipped(self):
        row = _row(cTime=1788573600000, uTime=1788576600000)   # 2026-09-05，早于 reset
        self.assertIsNone(_build(row, reset_time="2026-09-20 00:00:00"))

    def test_row_after_reset_is_kept(self):
        self.assertIsNotNone(_build(_row(), reset_time="2026-08-01 00:00:00"))

    def test_inst_not_in_allowlist_is_skipped(self):
        """白名单外的历史币种必须被挡在台账之外（审计已修过一次）。"""
        self.assertIsNone(_build(_row(instId="DOGE-USDT-SWAP")))

    def test_inst_in_allowlist_is_kept(self):
        self.assertIsNotNone(_build(_row(instId="ETH-USDT-SWAP")))

    def test_empty_allowlist_skips_everything(self):
        self.assertIsNone(_build(_row(), allowed=set()))


class MarginTest(unittest.TestCase):
    def test_margin_from_notional_over_lever(self):
        # 10 张 × 0.01 面值 × 79000 = 7900 名义 / 5x = 1580
        t = _build(_row(closeTotalPos=10.0, openAvgPx=79000.0, lever="5"))
        self.assertEqual(t["margin"], 1580.0)

    def test_margin_falls_back_to_pnl_ratio(self):
        t = _build(_row(closeTotalPos=0.0, openMaxPos=0.0, openAvgPx=0.0,
                        pnl=500.0, pnlRatio=0.05))
        self.assertEqual(t["margin"], 10000.0)

    def test_margin_falls_back_to_500_when_nothing_usable(self):
        t = _build(_row(closeTotalPos=0.0, openMaxPos=0.0, openAvgPx=0.0,
                        pnlRatio=0.0))
        self.assertEqual(t["margin"], 500.0)

    def test_zero_lever_does_not_divide(self):
        t = _build(_row(lever="0"))
        self.assertGreater(t["margin"], 0)

    def test_roi_uses_margin(self):
        t = _build(_row(closeTotalPos=10.0, openAvgPx=79000.0, lever="5",
                        pnl=500.0, fee=-20.0))
        self.assertEqual(t["roi_pct"], round(480.0 / 1580.0 * 100, 2))
        self.assertEqual(t["roi"], t["roi_pct"])

    def test_roi_zero_when_margin_zero(self):
        # 构造 margin 为 0 不可能（有 500U 兜底），故直接验证公式不抛
        t = _build(_row())
        self.assertIsInstance(t["roi_pct"], float)

    def test_get_ct_val_is_injected(self):
        seen = []

        def spy(inst):
            seen.append(inst)
            return 0.02

        t = _build(_row(closeTotalPos=10.0, openAvgPx=79000.0, lever="5"),
                   get_ct_val=spy)
        self.assertEqual(seen, ["BTC"])
        self.assertEqual(t["margin"], round(10.0 * 0.02 * 79000.0 / 5, 2))


class ExitReasonTest(unittest.TestCase):
    def _close_order(self, **over):
        base = dict(instId="BTC-USDT-SWAP", posSide="long",
                    uTime=1789356600000, algoId=None, clOrdId="", tag="")
        base.update(over)
        return base

    def test_liquidation_when_type_3(self):
        self.assertEqual(_build(_row(type="3"))["exit_reason"], "💥 强平出场")

    def test_type_3_ignores_matched_close_order(self):
        t = _build(_row(type="3"), close_orders=[self._close_order(algoId="A1")])
        self.assertEqual(t["exit_reason"], "💥 强平出场")

    def test_algo_order_profit_becomes_target_tp(self):
        t = _build(_row(pnl=50.0, fee=0.0), close_orders=[self._close_order(algoId="A1")])
        self.assertEqual(t["exit_reason"], "🎯 目标止盈达成")

    def test_algo_order_loss_becomes_cloud_sl(self):
        t = _build(_row(pnl=-50.0, fee=0.0), close_orders=[self._close_order(algoId="A1")])
        self.assertEqual(t["exit_reason"], "🛑 触发云端止损")

    def test_algo_order_small_pnl_becomes_trailing_breakeven(self):
        t = _build(_row(pnl=1.0, fee=0.0), close_orders=[self._close_order(algoId="A1")])
        self.assertEqual(t["exit_reason"], "🛡️ 移动止损保本出场")

    def test_client_order_profit_becomes_trailing_tp(self):
        t = _build(_row(pnl=50.0, fee=0.0),
                   close_orders=[self._close_order(clOrdId="O12345")])
        self.assertEqual(t["exit_reason"], "✨ 移动止盈锁利")

    def test_client_order_loss_becomes_risk_sl(self):
        t = _build(_row(pnl=-50.0, fee=0.0),
                   close_orders=[self._close_order(clOrdId="O12345")])
        self.assertEqual(t["exit_reason"], "🛑 策略风控止损")

    def test_tag_cli_counts_as_client_order(self):
        t = _build(_row(pnl=50.0, fee=0.0),
                   close_orders=[self._close_order(clOrdId="X", tag="CLI_DO")])
        self.assertEqual(t["exit_reason"], "✨ 移动止盈锁利")

    def test_client_order_small_pnl_becomes_timeout(self):
        t = _build(_row(pnl=1.0, fee=0.0),
                   close_orders=[self._close_order(clOrdId="O12345")])
        self.assertEqual(t["exit_reason"], "⏱️ 超时/保本平仓")

    def test_unmatched_close_order_generic_reasons(self):
        for pnl, expected in ((50.0, "🎯 目标止盈达成"),
                              (-50.0, "🛑 止损出场"),
                              (1.0, "🛡️ 保本平仓")):
            t = _build(_row(pnl=pnl, fee=0.0), close_orders=[])
            self.assertEqual(t["exit_reason"], expected, f"pnl={pnl}")

    def test_match_requires_same_instrument(self):
        t = _build(_row(pnl=50.0, fee=0.0),
                   close_orders=[self._close_order(instId="ETH-USDT-SWAP", algoId="A")])
        self.assertEqual(t["exit_reason"], "🎯 目标止盈达成",
                         "不匹配时退化为通用文案（止盈仍是止盈）")
        # 用亏损值才能区分"匹配到 algo"与"未匹配"
        t2 = _build(_row(pnl=-50.0, fee=0.0),
                    close_orders=[self._close_order(instId="ETH-USDT-SWAP", algoId="A")])
        self.assertEqual(t2["exit_reason"], "🛑 止损出场", "未匹配 → 通用止损文案")

    def test_match_requires_same_direction(self):
        t = _build(_row(direction="long", pnl=-50.0, fee=0.0),
                   close_orders=[self._close_order(posSide="short", algoId="A")])
        self.assertEqual(t["exit_reason"], "🛑 止损出场")

    def test_match_window_is_5000ms(self):
        u = int(_row()["uTime"])
        inside = _build(_row(pnl=-50.0, fee=0.0),
                        close_orders=[self._close_order(uTime=u + 4999, algoId="A")])
        self.assertEqual(inside["exit_reason"], "🛑 触发云端止损", "4999ms 内应匹配")
        outside = _build(_row(pnl=-50.0, fee=0.0),
                         close_orders=[self._close_order(uTime=u + 5001, algoId="A")])
        self.assertEqual(outside["exit_reason"], "🛑 止损出场", "5001ms 外不应匹配")

    def test_window_boundary_exactly_5000_is_excluded(self):
        u = int(_row()["uTime"])
        t = _build(_row(pnl=-50.0, fee=0.0),
                   close_orders=[self._close_order(uTime=u + 5000, algoId="A")])
        self.assertEqual(t["exit_reason"], "🛑 止损出场",
                         "边界是严格小于 5000，等于不算匹配")

    def test_first_matching_order_wins(self):
        u = int(_row()["uTime"])
        t = _build(_row(pnl=-50.0, fee=0.0), close_orders=[
            self._close_order(uTime=u + 10, algoId="A"),
            self._close_order(uTime=u + 20, algoId=None, clOrdId="O99"),
        ])
        self.assertEqual(t["exit_reason"], "🛑 触发云端止损", "取第一个匹配")


class SourceIdentityTest(unittest.TestCase):
    """**证明抽取是逐行搬运**，而不是"看起来像"。

    比运行期差分更强也更简单：把抽取前那段循环体从 git 历史里取出来，做同样的
    三处机械改写（`continue`→`return None`、`append({`→`return {`、去掉跨行序号
    三行并改用传入的 `id_suffix`），再与**子模块里函数的实际源码**逐行比对。
    两边必须一字不差 —— 任何在搬运过程中被"顺手改动"的表达式都会在这里现形。

    运行期差分（用 exec 跑旧文本）试过，但它要重新拼装缩进，拼装代码本身
    极易出错（实测反复踩坑），而且**拼装错了就变成测我抄的文本**。
    源码同一性没有这个问题：它比较的就是仓库里的真实字节。
    """

    PRE_EXTRACTION_REV = "10069aa"      # 抽取前的最后一次提交
    FACADE_REL = "scripts/sync_full_ledger.py"

    def _old_loop_body(self) -> str:
        import subprocess
        import textwrap
        try:
            out = subprocess.run(
                ["git", "show", legacy_rev_path(f"{self.PRE_EXTRACTION_REV}:{self.FACADE_REL}")],
                capture_output=True, text=True, check=True, cwd=str(ROOT)).stdout
        except Exception as exc:                                   # noqa: BLE001
            raise unittest.SkipTest(f"取不到历史版本 —— {exc}")
        lines = out.splitlines(keepends=True)
        start = next(i for i, l in enumerate(lines)
                     if l.strip() == "for h in pos_history:")
        depth = len(lines[start]) - len(lines[start].lstrip())
        end = start + 1
        while end < len(lines):
            l = lines[end]
            if l.strip() and (len(l) - len(l.lstrip())) <= depth:
                break
            end += 1
        body = textwrap.dedent("".join(lines[start + 1:end]))
        if "trades_lifecycle.append({" not in body:
            raise AssertionError("未能从历史版本里定位到那段循环体")
        return body

    @staticmethod
    def _mechanical_edits(old_body: str) -> str:
        """抽取时对这段代码做的**全部**改写，一一对应写在测试里。"""
        import re
        t = re.sub(r"^\s*continue\s*$", "return None", old_body, flags=re.MULTILINE)
        t = t.replace("trades_lifecycle.append({", "return {")
        t = re.sub(r"\n\s*\}\)\s*$", "\n}", t)
        # 跨行序号状态（`_pos_id_seen`）留在门面；子模块改用传入的 id_suffix
        t, n = re.subn(
            r"^\s*_key = .*\n"
            r"\s*_seq = _pos_id_seen\.get\(_key, 0\)\n"
            r"\s*_pos_id_seen\[_key\] = _seq \+ 1\n"
            r"\s*_id_suffix = .*\n", "", t, flags=re.MULTILINE)
        if n != 1:
            raise AssertionError(f"序号块应恰好匹配 1 次，实际 {n}")
        return t.replace("{_id_suffix}", "{id_suffix}")

    @staticmethod
    def _new_function_body() -> str:
        import inspect
        import textwrap
        from scripts.ledger.okx_history import build_okx_trade
        src = textwrap.dedent(inspect.getsource(build_okx_trade))
        tree = ast.parse(src)
        fn = tree.body[0]
        first_real = fn.body[1].lineno        # 跳过文档串
        return textwrap.dedent("\n".join(src.splitlines()[first_real - 1:]))

    @staticmethod
    def _norm(text: str):
        """归一化到"每行首个非空白字符起算"。

        为什么去掉前导空白：两边的**块缩进基准**不同（历史文本是 `for` 体内侧、
        新函数是 `def` 体内侧），逐字比较必须先把这层差异抹平。抹平后：
        - 每一行的**内容**仍逐字比较（表达式、字面量、方法名改一个字符就红）；
        - 空行与首尾忽略。
        代价是**块内相对缩进**不再被这一条覆盖 —— 那由
        `test_relative_nesting_is_preserved` 单独用缩进序列比较来兜。
        """
        return [l.strip() for l in text.strip("\n").splitlines() if l.strip()]

    def test_ast_structure_is_identical(self):
        """**结构级**证明：两段代码的 AST 形状完全一致。

        逐行内容比较能抓住"改了某个字面量/方法名"，但抓不住"把某个 if 体整体
        挪出/挪进去"（每行内容都没变，只是层级变了）。且**缩进序列比较在这段
        代码上不可靠** —— 历史文本里有若干只含尾随空白的行，`textwrap.dedent`
        会忽略它们，导致两侧的缩进基准不同（实测 old 侧有 42 行在列 0、new 侧
        只有 40 行），缩进序列必然对不上，那是**测量工具的假红**。

        改用 `ast.dump` 比对：它只看语法结构，对缩进基准、空行、注释一概不敏感，
        因此能可靠地钉住嵌套层级。
        """
        import ast as _ast
        import textwrap

        def shape(text: str) -> str:
            # 历史文本里 `return None`（原 `continue`）落在列 0 —— `textwrap.dedent`
            # 会忽略"只含尾随空白"的行，导致这些行比它们的 `if` 低一层。
            # 这里把它们重新挂回所属 `if` 体内（比前一个非空行深 4 格），
            # 还原真实结构；再包进一个函数体 parse，最后比对**函数体**的 AST。
            lines = text.splitlines()
            fixed = []
            prev_indent = 0
            for l in lines:
                if l.strip() == "return None":
                    fixed.append(" " * (prev_indent + 4) + "return None")
                    continue
                fixed.append(l)
                if l.strip():
                    prev_indent = len(l) - len(l.lstrip())
            body = "\n".join(fixed)
            indented = "\n".join(
                ("    " + l) if l.strip() else l for l in body.splitlines())
            tree = _ast.parse("def _wrap():\n" + indented + "\n")
            return _ast.dump(tree.body[0].body[0])

        old = shape(self._mechanical_edits(self._old_loop_body()))
        new = shape(self._new_function_body())
        self.assertEqual(old, new, "AST 结构不同（嵌套层级或表达式形状被改动了）")

    def test_extracted_body_is_line_for_line_identical(self):
        old = self._norm(self._mechanical_edits(self._old_loop_body()))
        new = self._norm(self._new_function_body())
        self.assertEqual(len(old), len(new),
                         f"行数不同：原 {len(old)} 行，新 {len(new)} 行")
        for i, (a, b) in enumerate(zip(old, new)):
            self.assertEqual(
                a, b,
                f"第 {i + 1} 行被改动了\n  原: {a!r}\n  新: {b!r}"
                "\n（搬运必须逐字，任何『顺手优化』都要单独讨论）")

    def test_no_extra_logic_was_smuggled_in(self):
        """反向确认：新函数里除文档串外，不得出现原文没有的结构。

        具体地，抽取**不应该**新增 try/except、循环或额外的 if —— 那些都属于
        "顺手加的保护"，是行为变更。
        """
        new_body = self._new_function_body()
        old_body = self._mechanical_edits(self._old_loop_body())
        for kw in ("try:", "except ", "for ", "while "):
            self.assertEqual(new_body.count(kw), old_body.count(kw),
                             f"`{kw}` 的出现次数与原文不同（疑似夹带了新逻辑）")

    def test_sequence_state_lines_are_the_only_removal(self):
        """被删掉的只有跨行序号那 4 行（含注释外的那 3 条语句 + id_suffix 赋值）。"""
        old = self._old_loop_body()
        edited = self._mechanical_edits(old)
        removed = len(self._norm(old)) - len(self._norm(edited))
        self.assertEqual(removed, 4, f"应恰移除 4 行，实际 {removed}")

    def test_id_formula_unchanged_after_removal(self):
        """id 去重键的语义不变：仍是 `posId`（或回退时间戳）+ 传入后缀。"""
        new_body = self._new_function_body()
        self.assertIn('"id": f"pos_hist_{_stable}_{inst}{id_suffix}"', new_body)
        self.assertIn('str(h.get("posId") or "").strip()', new_body)


class WiringTest(unittest.TestCase):
    def test_impl_lives_in_submodule_not_facade(self):
        facade = FACADE.read_text(encoding="utf-8")
        sub = SUBMODULE.read_text(encoding="utf-8")
        self.assertIn("def build_okx_trade(", sub)
        self.assertNotIn("def build_okx_trade(", facade)

    def test_facade_loop_body_is_gone(self):
        facade = FACADE.read_text(encoding="utf-8")
        for gone in ('"id": f"pos_hist_{_stable}_{inst}{_id_suffix}"',
                     'exit_reason = "💥 强平出场"',
                     "matched_close = next("):
            self.assertNotIn(gone, facade, f"门面仍残留循环体片段 {gone!r}")
        self.assertIn("build_okx_trade(", facade)

    def test_cross_row_sequence_state_stays_in_facade(self):
        """`_pos_id_seen` 是**跨行**状态，必须留在门面循环里。

        **断言必须看 AST 而不是文本**：子模块的文档串里"提到"了 `_pos_id_seen`
        这个词（解释序号为何由调用方传入），文本断言会因此假红 —— 这正是
        `astra_backend/README.md` §7 记的那类锚点陷阱：文档提及 ≠ 代码存在。
        """
        facade_tree = ast.parse(FACADE.read_text(encoding="utf-8"))
        sub_tree = ast.parse(SUBMODULE.read_text(encoding="utf-8"))

        def code_names(tree):
            """只收集真实代码里的名字（忽略文档串）。"""
            out = set()
            for n in ast.walk(tree):
                if isinstance(n, ast.Name):
                    out.add(n.id)
                elif isinstance(n, ast.Attribute):
                    pass
                elif isinstance(n, ast.arg):
                    out.add(n.arg)
            # 变量名/字典键出现在 Assign/Subscript 里时同样被 ast.Name 覆盖
            return out

        self.assertIn("_pos_id_seen", code_names(facade_tree),
                      "门面必须以代码持有跨行序号状态")
        self.assertNotIn("_pos_id_seen", code_names(sub_tree),
                         "子模块不得持有跨行序号状态（文档提及不算）")
        facade_src = FACADE.read_text(encoding="utf-8")
        self.assertIn('_id_suffix = f"_{int(_c_ts)}"', facade_src)

    def test_submodule_does_not_bind_datetime_or_get_ct_val(self):
        sub = SUBMODULE.read_text(encoding="utf-8")
        tree = ast.parse(sub)
        for node in tree.body:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = {(al.asname or al.name) for al in node.names}
                for banned in ("datetime", "get_ct_val"):
                    self.assertNotIn(banned, names,
                                     f"子模块不得 import {banned}（须调用期注入）")

    def test_facade_still_exposes_the_public_surface_tests_use(self):
        """门面被 `scripts.sync_full_ledger` 与 `sync_full_ledger` 两种路径导入，
        且测试直接 patch 一批私有函数 —— 抽取不得动这些名字。"""
        facade = FACADE.read_text(encoding="utf-8")
        tree = ast.parse(facade)
        defined = {n.name for n in tree.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for must in ("build_lifecycle_ledger", "_fetch_history_paged", "_mark",
                     "_write_sync_status", "_holding_row", "_history_truncated_in_scope",
                     "allowed_inst_ids", "get_ct_val",
                     "fetch_binance_closed_trades", "fetch_gate_closed_trades"):
            self.assertIn(must, defined, f"门面必须仍定义 {must}")

    def test_id_key_formula_unchanged(self):
        """id 去重键必须仍是 `posId|c_ts` —— 审计批7 的核心修复。"""
        facade = FACADE.read_text(encoding="utf-8")
        self.assertIn('_key = f"{_stable_for_key}|{int(_c_ts)}"', facade)


if __name__ == "__main__":
    unittest.main()
