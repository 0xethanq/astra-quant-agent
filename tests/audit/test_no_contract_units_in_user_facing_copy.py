"""口径门：用户可见与 AI 可见的文案**不得再用「张」表达仓位**。

## 为什么单独建门（2026-09-28 用户拍板）

三所的"数量"**不是同一个单位**：OKX 是张（1 张 XRP = 100 XRP）、币安是**币数**、
Gate 是自家张（1 张 XRP = 10 XRP）。更要命的是**各币种的合约面值算法都不一样**
（BTC 一张 0.01 币、XRP 一张 100 币），所以"张数"既不能跨场所比、也不能跨币种比，
用户根本无从判断"这笔占了我多少钱"。

保证金（+ 杠杆 / 名义额）是唯一跨场所、跨币种可比的量。故用户拍板：
**所有展示与提示词一律用保证金 + 杠杆，原生数量只在场所边界出现一次、永不外显。**

本门治的是真实事故形态：XRP 那一单文案写 `26.87 张｜预估保证金 ~6.72 U`，
而交易所实况是 `199.9 XRP｜49.9 U` —— 两个数都对不上。

## 扫描范围（**只扫字符串字面量**）

只检查人/AI 能看到的文案源，且只看字符串常量里的 `张`/`Cont`。
注释里的中文量词（"一张卡""一张表"）**不在此列** —— 那不是单位。
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: 用户可见 / AI 可见的文案源
COPY_SOURCES = (
    "scripts/qq_notifier.py",
    "scripts/trader/notifications.py",
    "scripts/trader/scale_out.py",
    "scripts/trader/pyramiding.py",
    "scripts/trader/entry_execution.py",
    "scripts/brain/account_text.py",
    "scripts/prompt_library.py",
)

#: 前端文案（locale 里的单位字）
LOCALE_SOURCES = (
    "frontend/src/locales/zh/dash/matrix.ts",
    "frontend/src/locales/en/dash/matrix.ts",
    "frontend/src/locales/zh/dash/ledger.ts",
    "frontend/src/locales/en/dash/ledger.ts",
)

#: 判断「张」是不是**计量单位**而非中文量词。
#: 量词用法一律紧跟"一/两/三/几/多"等数词并接名词（一张卡/两张表），
#: 或者出现在 `{…}` 格式化槽之后（`{sz}张@`）；单位用法是数字+张。
_UNIT_PATTERNS = (
    re.compile(r"\{[^}]*\}\s*张"),          # f-string: {sz}张
    re.compile(r"\d+\s*张"),                 # 5张 / 309.4张
    re.compile(r"张数"),                      # 张数不足以切分
    re.compile(r"\bCont\b"),                 # en locale 的 contractsUnit
)


def _docstring_ids(tree: ast.AST) -> set:
    """收集所有模块/类/函数 docstring 节点的 id —— 它们是**开发文档**，
    不是用户可见文案，其中正当地记录着历史缺陷形态（如 `26.87 张`）。"""
    out = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None)
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                out.add(id(body[0].value))
    return out


def _string_literals(path: Path):
    """产出该文件里所有**非 docstring** 字符串常量的 `(行号, 值)`。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docs = _docstring_ids(tree)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in docs:
                yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):   # f-string：逐段看
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    yield node.lineno, v.value


def find_contract_units(path: Path):
    out = []
    for lineno, text in _string_literals(path):
        for pat in _UNIT_PATTERNS:
            m = pat.search(text)
            if m:
                out.append((lineno, m.group(0), text.strip()[:90]))
                break
    return out


class NoContractUnitsInCopyTest(unittest.TestCase):
    def test_user_facing_copy_uses_no_contract_units(self):
        problems = []
        for rel in COPY_SOURCES:
            path = ROOT / rel
            self.assertTrue(path.exists(), f"文案源不存在（路径漂了）: {rel}")
            for lineno, hit, snippet in find_contract_units(path):
                problems.append(f"{rel}:{lineno} 命中「{hit}」 → {snippet}")
        self.assertEqual(
            problems, [],
            "用户可见/AI 可见文案又用「张」表达仓位了。\n"
            "三所数量单位不同、各币种合约面值算法也不同 ⇒ 张数无法横向比较；\n"
            "请改用 `notifications.money_size_text`（保证金 + 杠杆 [+ 名义额]）：\n"
            + "\n".join(problems))

    def test_locale_units_are_money_only(self):
        """locale 是 TypeScript，走原文扫描（值本身就是展示字符串）。"""
        for rel in LOCALE_SOURCES:
            path = ROOT / rel
            if not path.exists():
                continue
            text = path.read_text(encoding="utf-8")
            self.assertNotIn("contractsUnit", text,
                             f"{rel} 又把 contractsUnit 加回来了 ⇒ 前端会显示原生数量")
            for pat in _UNIT_PATTERNS:
                m = pat.search(text)
                self.assertIsNone(m, f"{rel} 命中「{m.group(0) if m else ''}」")

    def test_the_gate_actually_scans_something(self):
        """防空转：至少要在**改造前**的形态上命中，证明判据不是恒假。"""
        sample = ROOT / "scripts" / "trader" / "notifications.py"
        text = sample.read_text(encoding="utf-8")
        hits = [p.pattern for p in _UNIT_PATTERNS
                if p.search('f"{name} AI市价多单已提交 {sz}张@{px}"')]
        self.assertTrue(hits, "判据对历史缺陷形态零命中 ⇒ 本门是空转的")
        del text

    def test_the_gate_covers_every_declared_source(self):
        self.assertGreaterEqual(len(COPY_SOURCES), 7)
        self.assertGreaterEqual(len(LOCALE_SOURCES), 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
