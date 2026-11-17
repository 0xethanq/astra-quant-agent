"""`astra_backend/README.md` 里的测试基线数字必须与实测同量级（结构优化阶段 4·B3 第六十四刀）。

## 为什么需要它

`astra_backend/README.md` §6 写着"每次拆分后必须过的两道闸"，
里面有一行基线数字：

```
# 1) 全量离线套件（当前基线：1333 例 OK, skipped=1）
```

实测是 **2761 例** —— 已经漂到 **2 倍以上**，而且**没有任何测试看着它**。

> 这与第五十五刀在 `components/admin/README.md` 上抓到的问题是同一类，
> 且那条 README 当时还**声称 10 个组件"实测 0 个引用者"**（纯属误读）。
> 结论：**文档里的数字会静默腐烂，除非有测试盯着。**

## ⚠️ 判定口径（刻意不用"写死当前数字"）

不用"README 必须等于 N"：

1. 那需要每次加测试都改这里，维护成本高、且与"文档自证"无关；
2. runner 报的例数与 AST 数出的方法数**本来就不等**
   （2026-09-15：runner `2761`、AST `2710` —— 差值来自动态生成的用例），
   写哪个都会有一边对不上。

改用**自维护**判据：

- 用 AST 数出仓里 `test_*` 方法数 `N_ast`（不跑套件，快且无副作用）；
- 要求 README 里写的数字落在 `[0.9 × N_ast, 1.1 × N_ast]` 内。

于是：**小步增长不会翻红**（±10% 容差），
但**漂到两倍（如现在 1333 vs 2761）一定会被抓住**。
"""

from __future__ import annotations

import ast
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
README = ROOT / "astra_backend" / "README.md"
TESTS = ROOT / "tests"

#: README 里基线数字的写法：`当前基线：1333 例 OK`
BASELINE_RE = re.compile(r"当前基线[：:]\s*(\d+)\s*例")

#: 允许的偏差比例（自维护的核心：小步不红、大漂必红）
TOLERANCE = 0.10


def _count_test_methods() -> int:
    """AST 数出仓里 `test_*` 方法的数量。

    ⚠️ 不跑套件 —— 本用例会被"全量套件"包含，跑套件就是递归。
    也不 import 测试模块（那会触发它们的副作用）。
    """
    total = 0
    for p in sorted(TESTS.rglob("test_*.py")):   # 第 138 刀：tests/ 已按域分子目录
        try:
            tree = ast.parse(p.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            for item in node.body:
                if (isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                        and item.name.startswith("test")):
                    total += 1
    return total


class ReadmeBaselineTest(unittest.TestCase):
    def test_baseline_number_is_present(self):
        """这条断言本身用来防止"把那一行整段删掉"来绕过本测试。"""
        text = README.read_text(encoding="utf-8")
        self.assertRegex(
            text, BASELINE_RE,
            "astra_backend/README.md §6 里应保留 `当前基线：NNNN 例 OK` 这一行 —— "
            "它是新人判断'多少例算正常'的唯一依据")
        self.assertIn("unittest discover", text, "§6 应给出判绿命令")

    def test_baseline_number_tracks_the_real_suite(self):
        text = README.read_text(encoding="utf-8")
        m = BASELINE_RE.search(text)
        self.assertIsNotNone(m, "未解析到基线数字")
        documented = int(m.group(1))

        actual = _count_test_methods()
        self.assertGreater(actual, 500, f"AST 数出的用例数异常地少: {actual}")

        lo, hi = actual * (1 - TOLERANCE), actual * (1 + TOLERANCE)
        self.assertTrue(
            lo <= documented <= hi,
            f"astra_backend/README.md 的基线数字已漂移："
            f"写的是 {documented} 例，实际约 {actual} 例"
            f"（允许 ±{int(TOLERANCE * 100)}%）—— 请更新 §6 那一行")

    def test_stale_offline_suite_error_count_is_not_claimed(self):
        """⚠️ 曾经的"约 5 个报错"是错的（实测 git 16 / python 55）。

        不要求 README 写死数字，但**不得再出现"约 5 个"这种已被证伪的说法**。
        """
        text = README.read_text(encoding="utf-8")
        self.assertNotIn("会有约 5 个", text,
                         "该说法已被证伪（实测远多于 5 个）—— 见第六十四刀")
        self.assertIn("不是回归", text,
                      "应保留'那是守卫本身的产物，不是回归'的澄清（否则新人会误判）")


if __name__ == "__main__":
    unittest.main()
