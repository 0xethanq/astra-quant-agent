"""`astra_backend/council/role_normalizer.py`（B3 第二十八刀）回归。

## 这个测试在守什么

CIO 模型被要求在每个标的决策里给出 `adopted_role`（采纳了哪位交易员的提案）。
**模型经常漏填、填空串、或填字符串 `"none"`** —— `role_normalizer` 把"没填"
变成可追溯的值。四处易错点：

| # | 细节 | 错了会怎样 |
|---|---|---|
| 1 | `WAIT` 直接给 `"REJECT_ALL"`，**不走文本反查** | 观望被错误归因到某位交易员 |
| 2 | "没填"有**三个**判据：`None` / 空串 / `"none"`（去空格、大小写不敏感） | 漏一个就让某形态溜过去，留 `None` |
| 3 | 别名 = `[r_k, r_name]` + 按关键字 `extend` **一支**（`if/elif`） | 用 `if/if/if` 会追加多支，改变命中优先级 |
| 4 | **命中即 `break`，按 `trader_keys` 顺序取第一个** —— 不是"最匹配者胜" | 多个别名同时出现时归因结果改变 |

另有 **`if alias and ...` 的空串守卫**：`r_name` 为空时不能拿 `""` 去比，
因为 `"" in text` **恒真**，会把"没有名字"误判成"命中"。

## 为什么用"大差分"而不是只写几个例子

关键是 `resolve_adopted_role` 是个**嵌套判定 + 文本反查**的小决策器，
各分支的**组合**远多于我手工能枚举的例子（三个"没填"形态 × action 大小写 ×
别名命中位置 × trader_keys 顺序 × roles 里 name 缺失）。
故除了针对性用例，另跑 **20000 组与搬走前内联实现的随机差分**。
"""

from __future__ import annotations

import ast
import copy
import random
import unittest
from pathlib import Path

from astra_backend.council.role_normalizer import (
    ROLE_KEYWORD_ALIASES,
    build_alias_candidates,
    normalize_decisions,
    process_brain_output,
    resolve_adopted_role,
)

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "astra_backend" / "council" / "role_normalizer.py"
DEBATE = ROOT / "astra_backend" / "council" / "debate.py"

KEYS = ["trader_trend", "trader_momentum", "trader_quant"]
ROLES = {k: {"name": n} for k, n in zip(KEYS, ["趋势跟踪", "动能突破", "量化套利"])}


def _legacy_normalize(brain_output, roles, trader_keys):
    """搬走前 debate.py 里的内联实现（逐字原样）。"""
    decisions = brain_output.get("decisions")
    if isinstance(decisions, dict):
        for sym, dec in decisions.items():
            if isinstance(dec, dict):
                act = str(dec.get("action", "")).upper()
                ar = dec.get("adopted_role")
                if ar is None or str(ar).strip() == "" or str(ar).strip().lower() == "none":
                    if act == "WAIT":
                        dec["adopted_role"] = "REJECT_ALL"
                    else:
                        reasoning_text = str(dec.get("reasoning", ""))
                        matched_role = None
                        for r_k in trader_keys:
                            r_name = roles.get(r_k, {}).get("name", "")
                            alias_candidates = [r_k, r_name]
                            if "trend" in r_k:
                                alias_candidates.extend(["交易员 A", "交易员A", "Trader A", "trader a", "稳健型"])
                            elif "momentum" in r_k:
                                alias_candidates.extend(["交易员 B", "交易员B", "Trader B", "trader b", "动能型"])
                            elif "quant" in r_k:
                                alias_candidates.extend(["交易员 C", "交易员C", "Trader C", "trader c", "量化型"])
                            if any(alias and alias.lower() in reasoning_text.lower() for alias in alias_candidates):
                                matched_role = r_k
                                break
                        dec["adopted_role"] = matched_role
                else:
                    dec["adopted_role"] = str(ar).strip()


class MissingFormsTest(unittest.TestCase):
    """"没填"的**三个**判据都必须覆盖。"""

    def test_none_is_missing(self):
        self.assertEqual(
            resolve_adopted_role({"action": "WAIT", "adopted_role": None}, ROLES, KEYS),
            "REJECT_ALL")

    def test_empty_string_is_missing(self):
        self.assertEqual(
            resolve_adopted_role({"action": "WAIT", "adopted_role": ""}, ROLES, KEYS),
            "REJECT_ALL")

    def test_whitespace_only_is_missing(self):
        self.assertEqual(
            resolve_adopted_role({"action": "WAIT", "adopted_role": "   "}, ROLES, KEYS),
            "REJECT_ALL")

    def test_string_none_is_missing(self):
        self.assertEqual(
            resolve_adopted_role({"action": "WAIT", "adopted_role": "none"}, ROLES, KEYS),
            "REJECT_ALL")

    def test_string_none_case_insensitive(self):
        for form in ("NONE", "None", "nOnE", " none "):
            self.assertEqual(
                resolve_adopted_role({"action": "WAIT", "adopted_role": form}, ROLES, KEYS),
                "REJECT_ALL", form)

    def test_absent_key_is_missing(self):
        self.assertEqual(
            resolve_adopted_role({"action": "WAIT"}, ROLES, KEYS), "REJECT_ALL")


class ExplicitRoleTest(unittest.TestCase):
    def test_explicit_role_preserved(self):
        self.assertEqual(
            resolve_adopted_role({"action": "BUY_LONG", "adopted_role": "trader_quant"},
                                 ROLES, KEYS),
            "trader_quant")

    def test_explicit_role_is_stripped(self):
        self.assertEqual(
            resolve_adopted_role({"action": "BUY_LONG", "adopted_role": "  trader_trend  "},
                                 ROLES, KEYS),
            "trader_trend")

    def test_explicit_reject_all_preserved(self):
        """`REJECT_ALL` 非空也不是 `none` → 原样保留（即使 action 不是 WAIT）。"""
        self.assertEqual(
            resolve_adopted_role({"action": "BUY_LONG", "adopted_role": "REJECT_ALL"},
                                 ROLES, KEYS),
            "REJECT_ALL")

    def test_explicit_role_is_not_validated(self):
        """**不校验**是不是合法 role_id —— 模型给的怪值原样保留（既有行为）。"""
        self.assertEqual(
            resolve_adopted_role({"action": "BUY_LONG", "adopted_role": "totally_bogus"},
                                 ROLES, KEYS),
            "totally_bogus")


class WaitTest(unittest.TestCase):
    def test_wait_gives_reject_all(self):
        self.assertEqual(
            resolve_adopted_role({"action": "WAIT", "reasoning": "采纳交易员 A"},
                                 ROLES, KEYS),
            "REJECT_ALL",
            "WAIT 必须直接 REJECT_ALL，不因 reasoning 里提到交易员就归因给他")

    def test_wait_lowercase_also(self):
        self.assertEqual(
            resolve_adopted_role({"action": "wait"}, ROLES, KEYS), "REJECT_ALL")

    def test_non_wait_without_reasoning_gives_none(self):
        self.assertIsNone(
            resolve_adopted_role({"action": "BUY_LONG", "reasoning": ""}, ROLES, KEYS))

    def test_hold_is_not_wait(self):
        """`HOLD` 不是 `WAIT` → 走文本反查（这里查不到 → None）。"""
        self.assertIsNone(
            resolve_adopted_role({"action": "HOLD", "reasoning": "无"}, ROLES, KEYS))


class AliasLookupTest(unittest.TestCase):
    def test_role_id_in_reasoning(self):
        self.assertEqual(
            resolve_adopted_role({"action": "BUY_LONG", "reasoning": "采纳 trader_quant"},
                                 ROLES, KEYS),
            "trader_quant")

    def test_role_display_name_in_reasoning(self):
        self.assertEqual(
            resolve_adopted_role({"action": "BUY_LONG", "reasoning": "采用动能突破的思路"},
                                 ROLES, KEYS),
            "trader_momentum")

    def test_chinese_alias_forms(self):
        for text, want in (("采纳交易员 A", "trader_trend"),
                           ("采纳交易员B", "trader_momentum"),
                           ("采纳交易员C", "trader_quant")):
            self.assertEqual(
                resolve_adopted_role({"action": "BUY_LONG", "reasoning": text}, ROLES, KEYS),
                want, text)

    def test_style_aliases(self):
        for text, want in (("稳健型", "trader_trend"),
                           ("动能型", "trader_momentum"),
                           ("量化型", "trader_quant")):
            self.assertEqual(
                resolve_adopted_role({"action": "BUY_LONG", "reasoning": text}, ROLES, KEYS),
                want, text)

    def test_english_alias_case_insensitive(self):
        self.assertEqual(
            resolve_adopted_role({"action": "BUY_LONG", "reasoning": "TRADER A"},
                                 ROLES, KEYS),
            "trader_trend")

    def test_first_hit_by_trader_keys_order_wins(self):
        """**核心**：多个别名同时出现时，按 `trader_keys` 顺序取第一个，不是"最匹配"。"""
        text = "交易员 A 与交易员 C 都有道理"
        self.assertEqual(
            resolve_adopted_role({"action": "BUY_LONG", "reasoning": text}, ROLES, KEYS),
            "trader_trend", "KEYS 顺序里 trend 在 quant 之前")

    def test_order_reversal_changes_winner(self):
        text = "交易员 A 与交易员 C 都有道理"
        rev = list(reversed(KEYS))
        self.assertEqual(
            resolve_adopted_role({"action": "BUY_LONG", "reasoning": text}, ROLES, rev),
            "trader_quant", "反转 trader_keys 后 quant 先被试探")

    def test_empty_role_name_does_not_match_everything(self):
        """**空串守卫**：`{"name": ""}` 时 `"" in text` 恒真，必须靠 `if alias` 挡住。"""
        roles = {"trader_trend": {"name": ""}}
        self.assertIsNone(
            resolve_adopted_role({"action": "BUY_LONG", "reasoning": "完全无关的文字"},
                                 roles, ["trader_trend"]),
            "空 name 不得被当成命中")

    def test_missing_role_entry_is_tolerated(self):
        self.assertIsNone(
            resolve_adopted_role({"action": "BUY_LONG", "reasoning": "x"},
                                 {}, ["trader_trend"]))

    def test_unknown_role_key_without_keyword(self):
        """不含 trend/momentum/quant 的 role_id 只有两件套别名。"""
        self.assertEqual(
            resolve_adopted_role({"action": "BUY_LONG", "reasoning": "采纳 trader_other"},
                                 {"trader_other": {"name": "其他"}}, ["trader_other"]),
            "trader_other")


class AliasCandidatesTest(unittest.TestCase):
    def test_base_two_plus_one_branch(self):
        self.assertEqual(
            build_alias_candidates("trader_trend", "趋势跟踪"),
            ["trader_trend", "趋势跟踪"] + ROLE_KEYWORD_ALIASES["trend"])

    def test_elif_semantics_only_one_branch(self):
        """role_id 同时含 trend 与 quant → **只**追加 trend 那一支（`if/elif`）。"""
        got = build_alias_candidates("trader_trend_quant", "混合")
        self.assertIn("交易员 A", got)
        self.assertNotIn("交易员 C", got, "elif 语义：只追加第一支")

    def test_all_three_keyword_map_present(self):
        self.assertEqual(set(ROLE_KEYWORD_ALIASES), {"trend", "momentum", "quant"})

    def test_no_keyword_yields_two(self):
        self.assertEqual(build_alias_candidates("trader_other", "其他"),
                         ["trader_other", "其他"])


class NormalizeDecisionsTest(unittest.TestCase):
    def test_non_dict_decision_skipped(self):
        decs = {"BTC": "not-a-dict", "ETH": {"action": "WAIT"}}
        normalize_decisions(decs, ROLES, KEYS)
        self.assertEqual(decs["BTC"], "not-a-dict", "非 dict 决策项原样不动")
        self.assertEqual(decs["ETH"]["adopted_role"], "REJECT_ALL")

    def test_returns_same_object(self):
        decs = {"BTC": {"action": "WAIT"}}
        self.assertIs(normalize_decisions(decs, ROLES, KEYS), decs)

    def test_process_brain_output_skips_non_dict_decisions(self):
        bo = {"decisions": ["a", "b"]}
        process_brain_output(bo, ROLES, KEYS)
        self.assertEqual(bo, {"decisions": ["a", "b"]}, "decisions 非 dict → 整段跳过")

    def test_process_brain_output_missing_decisions(self):
        bo = {"macro_assessment": "x"}
        process_brain_output(bo, ROLES, KEYS)
        self.assertEqual(bo, {"macro_assessment": "x"})

    def test_process_brain_output_none_decisions(self):
        bo = {"decisions": None}
        process_brain_output(bo, ROLES, KEYS)
        self.assertIsNone(bo["decisions"])

    def test_all_decisions_normalized(self):
        bo = {"decisions": {
            "BTC": {"action": "WAIT"},
            "ETH": {"action": "BUY_LONG", "adopted_role": "trader_quant"},
            "SOL": {"action": "BUY_LONG", "reasoning": "量化型最好"},
        }}
        process_brain_output(bo, ROLES, KEYS)
        self.assertEqual(bo["decisions"]["BTC"]["adopted_role"], "REJECT_ALL")
        self.assertEqual(bo["decisions"]["ETH"]["adopted_role"], "trader_quant")
        self.assertEqual(bo["decisions"]["SOL"]["adopted_role"], "trader_quant")

    def test_empty_trader_keys_gives_none_for_non_wait(self):
        bo = {"decisions": {"BTC": {"action": "BUY_LONG", "reasoning": "交易员 A"}}}
        process_brain_output(bo, ROLES, [])
        self.assertIsNone(bo["decisions"]["BTC"]["adopted_role"])


class RandomParityTest(unittest.TestCase):
    """与搬走前内联实现的**大差分** —— 组合远多于手工例子。"""

    ACTIONS = ["WAIT", "BUY_LONG", "SELL_SHORT", "wait", "", "HOLD"]
    ADOPTED = [None, "", "  ", "none", "NONE", "None", "trader_trend", "REJECT_ALL", "bogus"]
    REASONS = ["", "采纳交易员 A 的方案", "采纳交易员B", "Trader C wins", "稳健型",
               "动能型", "量化型", "全员驳回", "trend and momentum both", "trader_quant"]

    def test_random_parity_20000(self):
        rng = random.Random(777)
        diverged = 0
        for _ in range(20000):
            decs = {}
            for j in range(rng.randint(0, 4)):
                shape = rng.random()
                if shape < 0.15:
                    decs[f"S{j}"] = "not-a-dict"
                elif shape < 0.25:
                    decs[f"S{j}"] = rng.choice(self.ACTIONS)
                elif shape < 0.4:
                    decs[f"S{j}"] = {"action": rng.choice(self.ACTIONS),
                                     "reasoning": rng.choice(self.REASONS)}
                else:
                    decs[f"S{j}"] = {"action": rng.choice(self.ACTIONS),
                                     "adopted_role": rng.choice(self.ADOPTED),
                                     "reasoning": rng.choice(self.REASONS)}
            r = rng.random()
            bo = ({"decisions": decs} if r < 0.85
                  else ({"decisions": None} if r < 0.93 else {}))
            a, b = copy.deepcopy(bo), copy.deepcopy(bo)
            _legacy_normalize(a, ROLES, KEYS)
            process_brain_output(b, ROLES, KEYS)
            if a != b:
                diverged += 1
                if diverged <= 3:
                    self.fail(f"分叉: {bo}\n legacy={a}\n new={b}")
        self.assertEqual(diverged, 0)

    def test_random_parity_with_reversed_keys(self):
        rng = random.Random(778)
        rev = list(reversed(KEYS))
        for _ in range(3000):
            decs = {"X": {"action": rng.choice(self.ACTIONS),
                          "adopted_role": rng.choice(self.ADOPTED),
                          "reasoning": rng.choice(self.REASONS)}}
            bo = {"decisions": decs}
            a, b = copy.deepcopy(bo), copy.deepcopy(bo)
            _legacy_normalize(a, ROLES, rev)
            process_brain_output(b, ROLES, rev)
            self.assertEqual(a, b, f"分叉(rev): {bo}")

    def test_random_parity_with_sparse_roles(self):
        """roles 里缺 name / 缺 role 条目时也要一致。"""
        rng = random.Random(779)
        sparse_variants = [
            {},
            {"trader_trend": {}},
            {"trader_trend": {"name": ""}},
            {"trader_momentum": {"name": "动能"}},
        ]
        for _ in range(3000):
            roles = rng.choice(sparse_variants)
            decs = {"X": {"action": rng.choice(self.ACTIONS),
                          "adopted_role": rng.choice(self.ADOPTED),
                          "reasoning": rng.choice(self.REASONS)}}
            bo = {"decisions": decs}
            a, b = copy.deepcopy(bo), copy.deepcopy(bo)
            _legacy_normalize(a, roles, KEYS)
            process_brain_output(b, roles, KEYS)
            self.assertEqual(a, b, f"分叉(sparse {roles}): {bo}")


class WiringTest(unittest.TestCase):
    def test_impl_in_submodule_not_facade(self):
        debate_src = DEBATE.read_text(encoding="utf-8")
        mod_src = MODULE.read_text(encoding="utf-8")
        self.assertIn("def resolve_adopted_role(", mod_src)
        self.assertNotIn("def resolve_adopted_role(", debate_src)
        self.assertIn("_normalize_cio_adopted_roles(brain_output, roles, trader_keys)",
                      debate_src)

    def test_facade_no_longer_contains_inline_normalizer(self):
        """只剩**代码**层面的片段判定。

        ⚠️ 我第一版把 `"交易员 A"` 也放进"必须消失"的清单里 —— 误报。
        因为它**合法地**存在于 CIO 系统提示词的示例文本中：

            - 在 reasoning 中明确写出你的仲裁依据（如「【CPI批复】采纳交易员 A 对 BTC …」）

        即"字符串存在"不等于"代码还在"。判定内联实现是否搬干净，要看
        **代码构造**（别名列表、匹配变量、关键字分支），不能看提示词散文。
        """
        debate_src = DEBATE.read_text(encoding="utf-8")
        # 只取**该内联实现独有**的标识符与语句形态。
        # ⚠️ 我第一版还加了 `"trader_keys:"` —— 误报（命中 6 次）：
        # 它匹配的是**类型注解** `trader_keys: List[str]`、dict 字面量
        # `"trader_keys": [...]` 等，与本刀搬走的那段毫无关系。
        # 判"内联代码是否搬干净"必须用**该实现独有的**记号，不能用通用标识符。
        for gone in ("alias_candidates", "matched_role"):
            self.assertNotIn(gone, debate_src, f"门面仍残留内联代码片段 {gone!r}")
        for gone in ('if "trend" in r_k:', 'elif "momentum" in r_k:',
                     'elif "quant" in r_k:'):
            self.assertNotIn(gone, debate_src, f"门面仍残留关键字分支 {gone!r}")
        self.assertNotIn("reasoning_text.lower()", debate_src)

    def test_trader_keys_type_annotation_still_exists(self):
        """反向确认：`trader_keys` 是**函数签名/局部变量**，不该被当成"残留"。

        这条正是在钉住上面那次误报 —— 防止后人又把它加回"必须消失"的清单。
        """
        debate_src = DEBATE.read_text(encoding="utf-8")
        self.assertIn("trader_keys = [", debate_src)
        self.assertIn("roles, trader_keys)", debate_src)

    def test_module_does_not_import_debate_or_council_manager(self):
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    self.assertNotIn("council_manager", a.name)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn("council_manager", node.module or "")

    def test_module_is_pure_no_module_level_side_effects(self):
        """模块级只允许：docstring、import、常量赋值、def。

        ⚠️ 我第一版写 `assertNotIsInstance(node, ast.Expr)` —— 误报，
        因为**模块文档串本身就是一条 `ast.Expr`**（`Expr(Constant(str))`）。
        要排除的是**非文档串**的裸表达式。
        """
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        body = list(tree.body)
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]          # 去掉模块文档串
        for node in body:
            self.assertNotIsInstance(
                node, ast.Expr,
                f"模块级不应有裸表达式（副作用）: L{node.lineno}")
            self.assertTrue(
                isinstance(node, (ast.Import, ast.ImportFrom, ast.Assign,
                                  ast.AnnAssign, ast.FunctionDef, ast.ClassDef)),
                f"模块级不允许 {type(node).__name__}: L{node.lineno}")
        self.assertIn("__all__", MODULE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
