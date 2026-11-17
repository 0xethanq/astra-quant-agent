"""`chartCountdown.ts` / `chartIndicators.ts`（阶段 3·F4 第三轮抽离）回归。

## 这个测试在守什么

两块从 `ChartWorkstation.vue` 抽出的**纯逻辑**：

1. **周期倒计时** —— 按当前周期算"距本根 K 线收线还有多久"，格式化成 `MM:SS`。
   四种周期口径不同（15m / 1H / 4H / 其余走"距今日结束"），且刻度处必须钳到 0。
2. **指标目录** —— 主图 5 项 + 副图 6 项 + 默认开启集合。

## ⚠️ 这个测试**不是**独立的正确性证明（如实记录）

黄金样本是我用 node 跑 `chartCountdown.ts` 生成的。若我在测试里把**同一条公式**
用 Python 再抄一遍去对照，那只是**转录**，不是独立验证：公式本身写错时两边会
一起错，测试照样绿。

所以本测试改为：**从 `.ts` 源码把算式解析出来，在 Python 里求值**，
再与黄金样本比对。这样

- 有人改 `chartCountdown.ts` 的算式 → 解析出的算式变 → 求值结果偏离黄金样本 → **翻红**；
- 源码与样本**不再能"各自静态地"同时为真**（这正是 §32.5 那次 7/7 不翻红的病根）。

至于"原始公式的业务口径对不对"，由**重构时的等价性**保证（原样搬运），
并由负向验证覆盖四种周期的分支串扰 —— 本文件不假装能证明业务口径。
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

# 仓库根（frontend/ 与 backend/ 的父目录）；测试已随后端收进 backend/tests。
ROOT = Path(__file__).resolve().parents[3]
DASH = ROOT / "frontend" / "src" / "components" / "dashboard"
COUNTDOWN = DASH / "chartCountdown.ts"
INDICATORS = DASH / "chartIndicators.ts"
COMPONENT = DASH / "ChartWorkstation.vue"
GOLDEN = ROOT / "backend" / "tests" / "data" / "chart_countdown_golden.json"


def _strip_ts_comments(src: str) -> str:
    """剥掉 `//` 与 `/* */` 注释，**保留字符串与代码**。

    只剥注释：判断"某算式/常量是否在代码里"时，文档串里的说明会造成假阳性
    （本模块文档串恰好列出了那张周期口径表）。但**不能连字符串一起剥** ——
    断言里要用到 `'15m'` 这类字面量（§32.6 已栽过一次）。
    """
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            if j == -1:
                break
            out.append("\n")
            i = j + 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            end = src.find("*/", i + 2)
            i = n if end == -1 else end + 2
            continue
        if c in "'\"`":
            quote = c
            start = i
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == quote:
                    i += 1
                    break
                i += 1
            out.append(src[start:i])
            continue
        out.append(c)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------- 算式求值

# ⚠️ 这个白名单我连踩三次：①`-` 写成 `+\-/` 会被 Python 读成「`+` 到 `/` 的区间」；
# ②标识符是 `remainSec`（大写 S），白名单全小写会拒掉 `S`；
# ③干脆**漏了字母 `a`**（`remainSec` 里有 `a`）。
# 三次症状完全相同（"算式含非算术字符"），每次只修一处就会再撞一次。
# 故这里改成**显式列出**允许的标识符与运算符，不再用"看起来对"的字符区间。
_ALLOWED_IDENT = re.compile(r"^[0-9]+$|^(remainSec|hr|min|sec)$|^[()+\-*/% ]+$")


def _tokens_ok(expr: str) -> bool:
    """把表达式按标识符/数字/运算符切开，逐段校验。

    比单个大字符类更容易读，也不会因为区间写法踩坑。
    """
    for tok in re.findall(r"[A-Za-z_][A-Za-z_0-9]*|\d+|[^\w\s]", expr):
        if not _ALLOWED_IDENT.match(tok):
            return False
    return True




def _eval_expr(expr: str, env: dict[str, int]) -> int:
    """求值一个只含数字与 hr/min/sec 的算术表达式。

    `Math.floor(x)` 会被剥掉外层：本模块里它**只用于非负量的取整**
    （`Math.floor(remainSec / 60)`、`Math.floor((remainSec % 3600) / 60)`），
    而 Python 的 `//` 与 `int()` 对这一类结果相同。若将来 floor 被用在
    可能为负的表达式上，这里会与实际分叉 —— 故剥之前先确认参数里没有负号,
    有负号就直接拒绝（宁可报错，不要悄悄算错）。
    """
    expr = expr.strip()
    m = re.fullmatch(r"Math\.floor\((.+)\)", expr)
    if m:
        inner = m.group(1)
        if "-" in inner:
            raise AssertionError(
                f"Math.floor 的参数含负号，Python 取整语义可能分叉，拒绝求值: {expr!r}")
        expr = inner

    # `//` 只在表达式本身就用整除了才出现；这里统一交给 Python 求值。
    py_expr = expr.replace("//", "//")
    if not _tokens_ok(py_expr):
        raise AssertionError(f"算式含非算术字符，拒绝求值: {py_expr!r}")
    return int(eval(py_expr, {"__builtins__": {}}, dict(env)))  # noqa: S307


REFERENCE_FORMAT = 'totalMinutes:pad2:sec'


def _parse_formatter(src: str) -> dict[str, str]:
    """从 `formatCountdown` 解析出它**怎么算分钟、怎么算秒、怎么补零**。

    返回 `{"minutes": <源码里的分钟表达式>, "seconds": <秒表达式>,
             "pad": <补零宽度>}`。

    ⚠️ 为什么要解析而不是直接认为"它就是对的"：本函数原先 ``remainSec % 3600``
    把小时丢掉，是一个**真实缺陷**（见模块文档串）。若测试只把黄金样本对着
    当前实现抄一遍，这个缺陷就会被**固化成"正确"**（我第一版差点如此——
    生成样本时用的就是带缺陷的实现，样本里 1H 整点是 `00:00`）。
    解析出算式、在 Python 里独立求值，才能让"改了算式"必然翻车。
    """
    code = _strip_ts_comments(src)
    start = code.index("export function formatCountdown(")
    nxt = code.find("\nexport function", start + 1)
    body = code[start:] if nxt == -1 else code[start:nxt]

    m_min = re.search(r"const totalMinutes\s*=\s*([^\n]+)", body)
    if not m_min:
        m_min = re.search(r"const m\s*=\s*([^\n]+)", body)
    m_sec = re.search(r"const s\s*=\s*([^\n]+)", body)
    m_pad = re.search(r"padStart\((\d+)", body)
    assert m_min and m_sec and m_pad, f"解析 formatCountdown 失败: {body!r}"
    return {"minutes": " ".join(m_min.group(1).split()),
            "seconds": " ".join(m_sec.group(1).split()),
            "pad": m_pad.group(1)}


def _eval_formatter(fmt: dict[str, str], remain: int) -> str:
    """按解析出的算式在 Python 里重算格式化结果。"""
    env = {"remainSec": remain}
    total_minutes = _eval_expr(_ts_to_py(fmt["minutes"]), env)
    seconds = _eval_expr(_ts_to_py(fmt["seconds"]), env)
    width = int(fmt["pad"])
    return f"{total_minutes:0{width}d}:{seconds:0{width}d}"


def _ts_to_py(expr: str) -> str:
    """把解析到的 TS 算式收敛成我们的算术子集（这里两者恰好同形）。"""
    return expr


def _parse_branches(src: str) -> dict[str, str]:
    """从 `remainingSeconds` 里解析每个周期对应的算式。

    接受三种形态（源码可能被格式化过）：
      `if (period === '15m') { remainSec = <expr> }`
      `} else if (period === '1H') {`
      `} else { remainSec = <expr> }`

    ⚠️ 分号必须是**可选**的（`;?`）：本仓的前端源码**普遍不写语句末尾分号**
    （`prettier` 风格），我第一版按"一定有分号"写，结果一个分支都解析不出来，
    三条用例直接 ERROR。**解析器对源码风格的假设越窄，测试越容易自己先红。**
    """
    code = _strip_ts_comments(src)
    start = code.index("export function remainingSeconds(")
    end = code.find("\nexport function", start + 1)
    body = code[start:] if end == -1 else code[start:end]

    branches: dict[str, str] = {}
    # 带周期名的分支
    # ⚠️ 必须在 `)` 与 `{` 之间、以及 `{` 与 `remainSec` 之间允许换行：
    # 源码是 `if (period === '15m') {\n    remainSec = (...)`。
    # 我第一版把 `\s*` 写成了同行匹配，结果一个分支都解析不出来（返回 {}），
    # 三条用例直接 ERROR —— 解析器写窄了，测试自己先红。
    for m in re.finditer(
        r"(?:if|else\s+if)\s*\(\s*period\s*===\s*'([^']+)'\s*\)\s*\{\s*"
        r"remainSec\s*=\s*([^;\n]+);?",
        body, flags=re.S,
    ):
        branches[m.group(1)] = " ".join(m.group(2).split())
    m = re.search(r"\}\s*else\s*\{\s*remainSec\s*=\s*([^;\n]+);?", body, flags=re.S)
    if m:
        branches["__else__"] = " ".join(m.group(1).split())
    return branches


class CountdownDerivedTest(unittest.TestCase):
    """从 `.ts` 解析算式 → Python 求值 → 与黄金样本对照。"""

    @classmethod
    def setUpClass(cls):
        cls.src = COUNTDOWN.read_text(encoding="utf-8")
        cls.golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
        cls.branches = _parse_branches(cls.src)
        cls.fmt = _parse_formatter(cls.src)

    def test_all_four_branches_parsed(self):
        self.assertEqual(set(self.branches),
                         {"15m", "1H", "4H", "__else__"},
                         f"解析出的分支: {sorted(self.branches)}")

    def test_every_golden_case_matches_derived_arithmetic(self):
        """核心用例：样本里每个结果都要能由**源码算式**算出来。"""
        for key, expect in self.golden.items():
            period, hms = key.split("|")
            hr, mi, se = (int(x) for x in hms.split(":"))
            expr = self.branches.get(period, self.branches["__else__"])
            remain = max(0, _eval_expr(expr, {"hr": hr, "min": mi, "sec": se}))
            derived = _eval_formatter(self.fmt, remain)
            self.assertEqual(derived, expect,
                             f"{key}: 算式 {expr!r} → {remain}s → {derived}")

    def test_guard_clamps_negative_to_zero(self):
        """`Math.max(0, …)` 必须在源码里 —— 刻度处不得出现负数。"""
        code = _strip_ts_comments(self.src)
        self.assertIn("Math.max(0, remainSec)", code)

    def _expect(self, period: str, hr: int, mi: int, se: int) -> str:
        """按**源码算式 + 源码格式化**推出该时点的期望标签。"""
        expr = self.branches.get(period, self.branches["__else__"])
        remain = max(0, _eval_expr(expr, {"hr": hr, "min": mi, "sec": se}))
        return _eval_formatter(self.fmt, remain)

    def test_exact_tick_gives_full_period(self):
        """恰好落在刻度上时，剩余应是**整个周期**（不是 0）。

        ⚠️ 首版这里我手写了样本键（`"1H|9:0:0"`），以为时分秒会补零 ——
        实际生成器写的是 `9:0:0`，直接 KeyError。改为**由算式推出期望值**，
        不再手写字符串键（手写键与生成器不一致时，测试会以 KeyError 的形式
        "看起来像实现有问题"，实际是我的键猜错了）。
        """
        self.assertEqual(self._expect("15m", 9, 15, 0), "15:00")
        self.assertEqual(self._expect("1H", 9, 0, 0), "60:00")
        self.assertEqual(self._expect("4H", 4, 0, 0), "240:00")
        self.assertEqual(self._expect("1D", 0, 0, 0), "1440:00")

    def test_one_second_before_tick(self):
        self.assertEqual(self._expect("15m", 9, 14, 59), "00:01")
        self.assertEqual(self._expect("1H", 9, 59, 59), "00:01")

    def test_day_end_for_unknown_period(self):
        """非 15m/1H/4H 一律走"距当天 24:00"。"""
        self.assertEqual(self._expect("1D", 23, 59, 59), "00:01")
        self.assertEqual(self._expect("anything", 0, 0, 0), "1440:00")

    def test_4h_uses_hour_modulo(self):
        """4H 按 `hr % 4` 对齐 —— 0 点与 4 点都是满周期。"""
        self.assertEqual(self._expect("4H", 0, 0, 0), "240:00")
        self.assertEqual(self._expect("4H", 4, 0, 0), "240:00")
        self.assertEqual(self._expect("4H", 0, 30, 0), "210:00")

    def test_4h_drifts_within_period(self):
        """4H 在同一段内递减；跨段回到满周期。"""
        self.assertGreater(self._expect("4H", 1, 0, 0), self._expect("4H", 1, 30, 0))
        self.assertEqual(self._expect("4H", 3, 59, 59), "00:01")
        self.assertEqual(self._expect("4H", 4, 0, 1), "239:59")

    def test_format_is_fixed_mm_ss(self):
        for v in self.golden.values():
            self.assertRegex(v, r"^\d{2,4}:\d{2}$")

    def test_golden_covers_all_five_periods_used_by_tests(self):
        periods = {k.split("|")[0] for k in self.golden}
        self.assertEqual(periods, {"15m", "1H", "4H", "1D", "anything"},
                         f"样本周期: {sorted(periods)}")

    def test_module_does_not_touch_timezone(self):
        """时间契约留在调用点：本模块不得出现 Date / 时区。"""
        code = _strip_ts_comments(self.src)
        for banned in ("new Date", "getHours", "toLocale", "TimeZone", "Intl"):
            self.assertNotIn(banned, code, f"倒计时模块不应处理时区/时间: {banned}")

    def test_component_still_resolves_beijing_time(self):
        """组件仍用 fmtClock 解析北京时间（契约未被搬走）。"""
        comp = COMPONENT.read_text(encoding="utf-8")
        self.assertIn("fmtClock(now).split(':')", comp)
        self.assertIn("countdownLabel(currentPeriod.value, { hr, min, sec })", comp)


class IndicatorCatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = INDICATORS.read_text(encoding="utf-8")
        cls.comp = COMPONENT.read_text(encoding="utf-8")

    def test_component_imports_and_uses_catalog(self):
        self.assertIn(
            "import { mainIndicators, subIndicators, DEFAULT_ACTIVE_INDICATORS } "
            "from './chartIndicators'", self.comp)
        self.assertIn("ref<Record<string, boolean>>({ ...DEFAULT_ACTIVE_INDICATORS })",
                      self.comp)
        self.assertEqual(self.comp.count("v-for=\"ind in mainIndicators\""), 1)
        self.assertEqual(self.comp.count("v-for=\"ind in subIndicators\""), 1)

    def test_component_no_longer_inlines_the_catalog(self):
        for gone in ("'成交量加权均价线'", "'随机摆动指标", "'能量潮累积线'",
                     "VWAP: true,"):
            self.assertNotIn(gone, self.comp, f"组件仍内联目录片段 {gone!r}")

    def test_catalog_shape_from_source(self):
        code = _strip_ts_comments(self.src)
        main = code[code.index("export const mainIndicators"):code.index("export const subIndicators")]
        sub = code[code.index("export const subIndicators"):code.index("export const DEFAULT_ACTIVE_INDICATORS")]
        self.assertEqual(main.count("isSub: false"), 5, "主图应 5 项")
        self.assertEqual(sub.count("isSub: true"), 6, "副图应 6 项")
        self.assertNotIn("isSub: true", main)
        self.assertNotIn("isSub: false", sub)

    def test_default_active_covers_exactly_the_catalog(self):
        """默认开启集合的键必须**恰好**是目录里的键 —— 多了是幽灵引用，少了会漏开关。"""
        code = _strip_ts_comments(self.src)
        catalog_keys = set(re.findall(r"key: '([A-Z]+)'", code))
        block = code[code.index("export const DEFAULT_ACTIVE_INDICATORS"):]
        default_keys = set(re.findall(r"^\s*([A-Z]+): (?:true|false),", block, flags=re.M))
        self.assertEqual(default_keys, catalog_keys,
                         f"目录 {sorted(catalog_keys)} vs 默认集合 {sorted(default_keys)}")

    def test_default_enables_exactly_vwap_and_vol(self):
        code = _strip_ts_comments(self.src)
        block = code[code.index("export const DEFAULT_ACTIVE_INDICATORS"):]
        on = set(re.findall(r"^\s*([A-Z]+): true,", block, flags=re.M))
        self.assertEqual(on, {"VWAP", "VOL"},
                         "默认只开启 VWAP 与 VOL（原实现如此）")

    def test_sar_and_obv_have_no_default_params(self):
        """`defaultParams` 的"有/无"必须原样保留，不得补成 `[]`。

        原实现用 `ind.defaultParams || []` 兜底；若这里补成 `[]`，`||` 结果虽同，
        但数据的"有无"变了 —— 将来若有人把 `||` 改成 `??` 就会分叉。
        """
        code = _strip_ts_comments(self.src)
        for key in ("SAR", "VWAP", "VOL", "OBV"):
            m = re.search(rf"key: '{key}',[^\n]*", code)
            self.assertIsNotNone(m, key)
            self.assertNotIn("defaultParams", m.group(0),
                             f"{key} 不应有 defaultParams")
        for key in ("MA", "EMA", "BOLL", "MACD", "RSI", "KDJ", "WR"):
            m = re.search(rf"key: '{key}',[^\n]*", code)
            self.assertIsNotNone(m, key)
            self.assertIn("defaultParams", m.group(0), f"{key} 应有 defaultParams")

    def test_all_indicator_keys_helper_matches_catalog(self):
        code = _strip_ts_comments(self.src)
        self.assertIn("export function allIndicatorKeys(", code)
        catalog = set(re.findall(r"key: '([A-Z]+)'", code))
        self.assertEqual(len(catalog), 11, f"目录共 11 项，实际 {sorted(catalog)}")

    def test_module_has_no_vue_dependency(self):
        code = _strip_ts_comments(self.src)
        imports = re.findall(r"import[^'\"\n]*['\"]([^'\"]+)['\"]", code)
        self.assertEqual(imports, [], f"纯数据模块不应 import 任何东西: {imports}")


if __name__ == "__main__":
    unittest.main()
