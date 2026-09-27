r"""自进化复盘上下文装配抽取对拍门（第一百零五刀）。

`self_improvement_engine.py::compose_evolution_prompts`（95 行）里两段 → `scripts/evolution/review_context.py`：
- `summarize_closed_trades(...)`：平仓统计 + 可观测性审计摘要（8 输出）；
- `build_host_constitution(...)`：**宿主宪章**（Code is Law 代码层硬约束）。

## 本门的重点不是"搬对了"，而是"**宪章不能被悄悄改坏**"

宿主宪章是安全语义文本：它要求模型"字段缺失不得解读为证据""基准心法不得静默删除"
"证据不足必须 NO_CHANGE"。埋在 95 行提示词装配里时，删掉一条没人会注意；
本门把四条硬约束**逐条**断言，并验证 `observability_brief` 真的被插值。

基线：`78c4da1`（本刀动工前最后提交）。
"""
from __future__ import annotations

import ast
import builtins
import subprocess
import sys
import unittest
from pathlib import Path
from tests.extraction.rename_baseline import legacy_rev_path, normalize

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

PRE = "78c4da1"
FACADE = ROOT / "scripts" / "self_improvement_engine.py"
MOD = ROOT / "scripts" / "evolution" / "review_context.py"
OWNER = "compose_evolution_prompts"
SPECS = {"summarize_closed_trades": (3, 10), "build_host_constitution": (20, 20)}


def _baseline_fn() -> ast.FunctionDef:
    r = subprocess.run(["git", "show", legacy_rev_path(f"{PRE}:scripts/self_improvement_engine.py")],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
    return next(n for n in ast.parse(normalize(r.stdout)).body
                if isinstance(n, ast.FunctionDef) and n.name == OWNER)


def _impl(name: str) -> ast.FunctionDef:
    t = ast.parse(MOD.read_text(encoding="utf-8"))
    return next(n for n in t.body if isinstance(n, ast.FunctionDef) and n.name == name)


def _facade_calls() -> dict:
    out = {}
    for n in ast.walk(ast.parse(FACADE.read_text(encoding="utf-8"))):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in SPECS:
            out.setdefault(n.func.id, n)
    return out


class EvolutionReviewContextTest(unittest.TestCase):
    def test_calls_pass_every_parameter_once_same_name(self):
        calls = _facade_calls()
        for name in SPECS:
            with self.subTest(fn=name):
                params = [a.arg for a in _impl(name).args.kwonlyargs]
                call = calls[name]
                self.assertEqual(call.args, [])
                self.assertEqual([k.arg for k in call.keywords], params)
                for k in call.keywords:
                    self.assertEqual(ast.unparse(k.value), k.arg)

    def test_statistics_call_unpacks_all_eight_in_natural_order(self):
        tree = ast.parse(FACADE.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == OWNER)
        tgt = [n.targets[0] for n in ast.walk(fn) if isinstance(n, ast.Assign)
               and isinstance(n.value, ast.Call) and getattr(n.value.func, "id", "") == "summarize_closed_trades"]
        self.assertEqual(len(tgt), 1)
        self.assertEqual([e.id for e in tgt[0].elts],
                         ["total", "wins", "losses", "win_rate", "total_net", "total_fees",
                          "snapshot_audit", "observability_brief"])

    def test_no_undeclared_free_names(self):
        module = ast.parse(MOD.read_text(encoding="utf-8"))
        mod_names = {n.name for n in module.body if isinstance(n, ast.FunctionDef)}
        for name in SPECS:
            with self.subTest(fn=name):
                fn = _impl(name)
                local = {a.arg for a in fn.args.kwonlyargs}
                for n in ast.walk(fn):
                    if isinstance(n, ast.Lambda):
                        local |= {a.arg for a in n.args.args}
                    if isinstance(n, ast.comprehension):
                        tg = n.target
                        for e in (tg.elts if isinstance(tg, (ast.Tuple, ast.List)) else [tg]):
                            if isinstance(e, ast.Name):
                                local.add(e.id)
                    if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                        local.add(n.id)
                    if isinstance(n, ast.ExceptHandler) and n.name:
                        local.add(n.name)
                    if isinstance(n, (ast.Import, ast.ImportFrom)):
                        for a in n.names:
                            local.add(a.asname or a.name.split(".")[0])
                reads = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)
                         and isinstance(n.ctx, ast.Load)}
                missing = sorted(reads - local - set(dir(builtins)) - mod_names)
                self.assertEqual(missing, [], f"{name} 解析不到: {missing}")

    # ---------- 行为例：统计 ----------

    def _sum(self, trades, audit=None, render=None):
        from scripts.evolution.review_context import summarize_closed_trades
        return summarize_closed_trades(
            closed_trades=trades,
            audit_snapshot_observability=audit or (lambda ts: {"n": len(ts)}),
            render_observability_brief=render or (lambda a: f"brief:{a['n']}"))

    def test_statistics_classify_and_round(self):
        # 用**二进制可精确表示**的数，避免浮点舍入让断言变得不可复现
        trades = [{"net_pnl": 10.5, "fee": 0.1}, {"net_pnl": -3.25, "fee": 0.2},
                  {"net_pnl": 0.0, "fee": 0.3}]
        total, wins, losses, win_rate, total_net, total_fees, audit, brief = self._sum(trades)
        self.assertEqual(total, 3)
        self.assertEqual(len(wins), 1)
        self.assertEqual(len(losses), 2, "净利为 0 计入亏损侧（`<= 0`，既有口径）")
        self.assertEqual(win_rate, 33.3)
        self.assertEqual(total_net, 7.25, "净利求和后保留 2 位（10.5 − 3.25）")
        self.assertEqual(total_fees, 0.6)
        self.assertEqual(audit, {"n": 3})
        self.assertEqual(brief, "brief:3")

    def test_statistics_empty_input_is_safe(self):
        total, wins, losses, win_rate, total_net, total_fees, _a, brief = self._sum([])
        self.assertEqual((total, len(wins), len(losses), win_rate, total_net, total_fees),
                         (0, 0, 0, 0.0, 0.0, 0.0), "空输入必须零除安全")

    # ---------- 行为例：宿主宪章（安全语义） ----------

    def test_constitution_contains_all_four_hard_rules(self):
        from scripts.evolution.review_context import build_host_constitution
        text = build_host_constitution(observability_brief="BRIEF-XYZ")
        self.assertIn("宿主宪章·代码层硬约束", text)
        self.assertIn("BRIEF-XYZ", text, "可观测性摘要必须被插值")
        # ① 逐单标注含义（数据源缺失不得当证据）
        self.assertIn("DYNAMICS_OBSERVED", text)
        self.assertIn("PARTIAL", text)
        self.assertIn("PRICE_ONLY / NONE", text)
        self.assertIn("字段缺失本身不得解读为任何证据", text)
        # ② 基准心法保护（不得静默删除）
        self.assertIn("is_baseline", text)
        self.assertIn("原样补回并留痕", text)
        self.assertIn("禁止静默删除", text)
        # ③ 证据不足必须 NO_CHANGE
        self.assertIn("NO_CHANGE 永不覆盖或清空长期记忆", text)
        # ④ 编号四条齐全（防误删一整条）
        for n in ("1.", "2.", "3.", "4."):
            self.assertIn(n, text)

    def test_constitution_is_pure_and_deterministic(self):
        from scripts.evolution.review_context import build_host_constitution
        self.assertEqual(build_host_constitution(observability_brief="X"),
                         build_host_constitution(observability_brief="X"))
        self.assertNotEqual(build_host_constitution(observability_brief="X"),
                            build_host_constitution(observability_brief="Y"))

class ParseReviewJsonTest(unittest.TestCase):
    """第一百一十三刀：`call_llm_evolution_review` 里的**围栏剥离 + JSON 解析**出表。

    该段原先在 63 行 `try` 的深处（103 行函数内），剥离 ```json 围栏这种"经典 bug 源"
    只能靠读代码确认。抽成 `parse_review_json` 后可逐条钉住。

    ⚠️ 助手**同时返回清洗后的 content**：门面随后用 `len(content)` 记 `output_chars`，
    若只返回解析结果，那个长度就会把围栏算进去（静默改变遥测语义）。
    """

    PRE = "d301f31"
    OWNER = "call_llm_evolution_review"

    def _baseline(self) -> ast.FunctionDef:
        r = subprocess.run(["git", "show", legacy_rev_path(f"{self.PRE}:scripts/self_improvement_engine.py")],
                           capture_output=True, text=True, cwd=str(ROOT))
        assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
        return next(n for n in ast.parse(normalize(r.stdout)).body
                    if isinstance(n, ast.FunctionDef) and n.name == self.OWNER)

    def test_module_defines_it_and_imports_json_itself(self):
        mod = ast.parse(MOD.read_text(encoding="utf-8"))
        self.assertIn("parse_review_json", {n.name for n in mod.body if isinstance(n, ast.FunctionDef)})
        imported = set()
        for n in mod.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                imported |= {a.asname or a.name.split(".")[0] for a in n.names}
        self.assertIn("json", imported,
                      "标准库名应由子模块自己 import（分析器第 11 条），不要当作参数注入")

    def test_call_site_unpacks_two_values_in_order(self):
        tree = ast.parse(FACADE.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
                  and n.name == self.OWNER)
        assigns = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
                   and isinstance(n.value, ast.Call)
                   and getattr(n.value.func, "id", "") == "parse_review_json"]
        self.assertEqual(len(assigns), 1, "应当恰好一处调用")
        call = assigns[0].value
        self.assertEqual([k.arg for k in call.keywords], ["content"])
        self.assertEqual(ast.unparse(call.keywords[0].value), "content")
        self.assertEqual([e.id for e in assigns[0].targets[0].elts], ["content", "review_json"],
                         "解包顺序必须是 (清洗后的 content, review_json)")

    def _parse(self, content):
        from scripts.evolution.review_context import parse_review_json
        return parse_review_json(content=content)

    def test_plain_json(self):
        cleaned, obj = self._parse('{"action": "NO_CHANGE"}')
        self.assertEqual(obj, {"action": "NO_CHANGE"})
        self.assertEqual(cleaned, '{"action": "NO_CHANGE"}')

    def test_fenced_json_is_stripped_and_cleaned_content_returned(self):
        """**只去围栏、不去空白**：返回的 content 保留内层换行，解析时才 `.strip()`。

        这个区别是实测出来的（我最初以为返回的是 trim 过的）：门面用 `len(cleaned)`
        记 `output_chars`，因此那 2 个换行**照旧计入** —— 与抽取前逐字一致。
        顺手钉住"解析用 strip、返回不 strip"这条容易在重构时被"顺手改统一"的差异。
        """
        raw = '```json\n{"a": 1}\n```'
        cleaned, obj = self._parse(raw)
        self.assertEqual(obj, {"a": 1})
        self.assertEqual(cleaned, '\n{"a": 1}\n', "只裁围栏，保留内层空白")
        self.assertEqual(cleaned.strip(), '{"a": 1}', "解析前才 strip")

    def test_bare_fence_and_trailing_fence(self):
        self.assertEqual(self._parse('```\n{"a": 1}```')[1], {"a": 1})
        self.assertEqual(self._parse('{"a": 1}```')[1], {"a": 1})

    def test_non_dict_json_becomes_empty_dict(self):
        self.assertEqual(self._parse('[1, 2, 3]')[1], {},
                         "解析成功但非对象 ⇒ 归一成 {}（既有行为）")

    def test_invalid_json_propagates(self):
        """不得在这里吞异常：门面靠 except 把它变成 `__llm_error__` 上报。"""
        with self.assertRaises(Exception):
            self._parse("not json at all")


class NormalizeAssetMultipliersTest(unittest.TestCase):
    """第一百一十四刀：`run_self_evolution` 里的**资产乘数归一**出表。

    7 行段，钉的是一条**影响仓位规模**的安全规则：只认标的池内的币、
    每档夹到 [0.5, 1.5]、缺值/不可比较一律回落到 1.0（等价"不调整"）。
    原先夹在 157 行编排函数中段（前后都是 LLM 调用与落盘），无法单独验证。
    """

    PRE = "25f6a69"
    OWNER = "run_self_evolution"

    def _baseline(self) -> ast.FunctionDef:
        r = subprocess.run(["git", "show", legacy_rev_path(f"{self.PRE}:scripts/self_improvement_engine.py")],
                           capture_output=True, text=True, cwd=str(ROOT))
        assert r.returncode == 0, f"基线取不到：{r.stderr[:200]}"
        return next(n for n in ast.parse(normalize(r.stdout)).body
                    if isinstance(n, ast.FunctionDef) and n.name == self.OWNER)

    def test_call_site_passes_every_parameter_once_same_name(self):
        params = [a.arg for a in _impl("normalize_asset_multipliers").args.kwonlyargs]
        tree = ast.parse(FACADE.read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == self.OWNER)
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "normalize_asset_multipliers"]
        self.assertEqual(len(calls), 1)
        self.assertEqual([k.arg for k in calls[0].keywords], params)
        for k in calls[0].keywords:
            self.assertEqual(ast.unparse(k.value), k.arg)

    def test_no_undeclared_free_names(self):
        mod = ast.parse(MOD.read_text(encoding="utf-8"))
        mod_names = set()
        for n in mod.body:
            if isinstance(n, (ast.FunctionDef, ast.ClassDef)):
                mod_names.add(n.name)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                mod_names |= {a.asname or a.name.split(".")[0] for a in n.names}
        fn = _impl("normalize_asset_multipliers")
        local = {a.arg for a in fn.args.kwonlyargs}
        for n in ast.walk(fn):
            if isinstance(n, ast.comprehension):
                tg = n.target
                for e in (tg.elts if isinstance(tg, (ast.Tuple, ast.List)) else [tg]):
                    if isinstance(e, ast.Name):
                        local.add(e.id)
            if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
                local.add(n.id)
        reads = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
        self.assertEqual(sorted(reads - local - set(dir(builtins)) - mod_names), [])

    # ---------- 行为例：安全规则 ----------

    def _norm(self, llm_review, targets=("BTC", "ETH")):
        from scripts.evolution.review_context import normalize_asset_multipliers
        from astra_backend.math_utils import clamp
        return normalize_asset_multipliers(TARGET_INSTRUMENTS=list(targets), clamp=clamp,
                                           llm_review=llm_review)

    def test_facade_clamp_is_the_math_utils_one(self):
        """门面的 `clamp` 只是别名（名字必须留在门面：`patch.object(模块,"clamp")` 是既有接缝）。"""
        src = (ROOT / "scripts" / "self_improvement_engine.py").read_text(encoding="utf-8")
        self.assertIn("from astra_backend.math_utils import clamp as _clamp", src)
        self.assertIn("return _clamp(value, lower, upper, default)", src)

    def test_only_pool_assets_and_default_one(self):
        got = self._norm({"asset_multipliers": {"BTC": 0.8, "DOGE": 9.9}})
        self.assertEqual(got, {"BTC": 0.8, "ETH": 1.0},
                         "只认标的池内的币；池内缺值 ⇒ 1.0（等价不调整）")

    def test_values_are_clamped_to_half_and_one_point_five(self):
        got = self._norm({"asset_multipliers": {"BTC": 0.01, "ETH": 99}})
        self.assertEqual(got, {"BTC": 0.5, "ETH": 1.5}, "乘数必须夹在 [0.5, 1.5]")

    def test_non_dict_multipliers_falls_back_to_all_ones(self):
        for bad in ("nope", [1, 2], None, 3):
            with self.subTest(bad=bad):
                self.assertEqual(self._norm({"asset_multipliers": bad}), {"BTC": 1.0, "ETH": 1.0})

    def test_missing_key_entirely(self):
        self.assertEqual(self._norm({}), {"BTC": 1.0, "ETH": 1.0})

    def test_uncomparable_value_falls_back_to_default(self):
        self.assertEqual(self._norm({"asset_multipliers": {"BTC": "abc"}}), {"BTC": 1.0, "ETH": 1.0},
                         "不可比较 ⇒ clamp 的 default（1.0），不得抛错")

    def test_returns_exactly_the_pool_keys(self):
        got = self._norm({"asset_multipliers": {"BTC": 1.0}}, targets=("BTC",))
        self.assertEqual(list(got), ["BTC"])

if __name__ == "__main__":
    unittest.main()
