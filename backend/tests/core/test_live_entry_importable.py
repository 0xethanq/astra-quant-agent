"""实盘入口的**可导入性**守卫（结构优化阶段 4·B3 事故回归）。

## 这个文件是为一次真实事故写的

2026-09-14 10:00，实盘交易员周期**静默消失**：gateway 日志有
`scheduled job=trader`，但 `logs/ai_factor_trader.log` 不新增任何行（**连 traceback 都没有**）。
根因：我在给 `scripts/trader/__init__.py` 追加文档时漏了 docstring 闭合，
把 Markdown 当**代码**留在了模块顶层 →

    SyntaxError: invalid character '（' (U+FF08)

`scripts/ai_factor_trader.py` 第 41 行就 `from scripts.trader.signals import ...`，
于是整个交易员进程在 **import 阶段**就死了。

## 为什么全套测试当时是绿的

因为**抽取类测试几乎都不 import 门面**：
- 它们用 `Path(...).read_text()` 读源码做 `assertIn` / `count`（纯文本）；
- 或用 `ast.parse` + `exec` 把单个函数节点拼成临时模块执行；
- 或 `patch.object(abt, ...)` —— 而 `abt` 是**测试自己构造的假模块**。

所以"源码里有语法错误"这类**只要不 import 就完全不可见**的缺陷，
测试全绿也发现不了。本文件补上这一格：**真的去 import**。

## 守的是什么

1. 抽取子包（`scripts.trader` / `scripts.brain`）与门面都能 import —— 即实盘入口活着；
2. 子包每个 `.py` 文件都能 `ast.parse`（import 只覆盖被引用到的模块，
   `ast.parse` 覆盖全部文件，能抓"暂时没被 import 但下次会被 import"的文件）；
3. 门面里所有 `from scripts.<x> import ...` 的目标都真实存在（抓改名/移动后的漏改）；
4. 包内文档没有被误写成顶层代码（本次事故的具体形态）。
"""
from __future__ import annotations

import ast
import importlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

# 实盘进程的 import 根：任何一个挂了，交易员周期都会静默消失
LIVE_ENTRY_MODULES = ("scripts.ai_factor_trader", "scripts.ai_brain_trader")
EXTRACTED_PACKAGES = ("scripts.trader", "scripts.brain")


class LiveEntryImportableTest(unittest.TestCase):
    def test_extracted_packages_import(self):
        """子包必须可 import —— 这是实盘进程 import 链上的第一个环节。"""
        for name in EXTRACTED_PACKAGES:
            with self.subTest(module=name):
                importlib.import_module(name)

    def test_live_entry_modules_import(self):
        """门面脚本必须可 import。

        这条是本文件的核心：事故当天，只要有任何一条测试 import 过门面就会翻红。
        """
        for name in LIVE_ENTRY_MODULES:
            with self.subTest(module=name):
                importlib.import_module(name)


class SubpackageSyntaxTest(unittest.TestCase):
    def test_every_subpackage_file_parses(self):
        """子包**每个** .py 文件都要能 ast.parse。

        比 import 更严：能抓到"当前没被 import、下次改完才会被 import"的文件。
        """
        checked = 0
        for pkg in EXTRACTED_PACKAGES:
            pkg_dir = SCRIPTS / pkg.split(".")[-1]
            for path in sorted(pkg_dir.glob("*.py")):
                with self.subTest(file=str(path.relative_to(ROOT))):
                    src = path.read_text(encoding="utf-8")
                    ast.parse(src)  # SyntaxError 即失败
                checked += 1
        self.assertGreaterEqual(checked, 8, f"只检查到 {checked} 个文件，疑似目录定位错误")

    def test_subpackage_docs_are_inside_docstrings_not_code(self):
        """包内文档必须包在 docstring 里。

        事故的**形态**特征：Markdown 文档裸露在模块顶层（`## 标题`、`| 表格 |`、
        全角括号等）。这里直接检查顶层 AST 里只有期望的节点类型，
        而不是"文件里出现了中文字符"这种容易误伤的口径。
        """
        allowed = (ast.Expr, ast.Import, ast.ImportFrom, ast.Assign, ast.FunctionDef,
                   ast.ClassDef, ast.If, ast.Try, ast.AnnAssign)
        for pkg in EXTRACTED_PACKAGES:
            pkg_dir = SCRIPTS / pkg.split(".")[-1]
            for path in sorted(pkg_dir.glob("*.py")):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for index, node in enumerate(tree.body):
                    with self.subTest(file=path.name, line=node.lineno):
                        self.assertIsInstance(
                            node, allowed,
                            f"{path.name}:{node.lineno} 顶层出现非代码节点（文档疑似漏了 "
                            f"docstring 闭合）: {ast.dump(node)[:80]}")
                        # 顶层裸字符串只允许是**模块 docstring**，即恰好第一个语句。
                        # 事故形态正是"文档续写在 docstring 之后"，会成为第 2 个及以后的
                        # 裸字符串常量 —— 这一条正好抓住它。
                        if (isinstance(node, ast.Expr)
                                and isinstance(node.value, ast.Constant)
                                and isinstance(node.value.value, str)):
                            self.assertEqual(
                                index, 0,
                                f"{path.name}:{node.lineno} 顶层裸字符串出现在第 {index + 1} 个语句，"
                                f"不是模块 docstring —— 文档多半脱出了三引号")


class FacadeSubpackageImportTest(unittest.TestCase):
    _IMPORT_RE = re.compile(r"^from (scripts\.[a-z_.]+) import (.+)$", re.M)

    def test_facade_package_imports_resolve(self):
        """门面里 `from scripts.<pkg> import a, b` 的每个名字都必须真实存在。

        抓的是"搬家后漏改导入"这类错误：改名/挪窝后 import 会 ImportError，
        但读取源码文本的断言看不出来。
        """
        for facade in LIVE_ENTRY_MODULES:
            src = (SCRIPTS / (facade.split(".")[-1] + ".py")).read_text(encoding="utf-8")
            for module, names in self._IMPORT_RE.findall(src):
                if "(" in names:  # 括号包裹的多行导入由 import 本身覆盖
                    continue
                mod = importlib.import_module(module)
                for raw in names.split("#")[0].split(","):
                    name = raw.strip().split(" as ")[0].strip()
                    if not name or name == "*":
                        continue
                    with self.subTest(facade=facade, module=module, name=name):
                        self.assertTrue(hasattr(mod, name),
                                        f"{module} 里没有 {name}（搬家漏改导入？）")


class SubpackageImportCostTest(unittest.TestCase):
    """子包 import 期**不得**产生副作用（碰盘/起线程）。

    这条与 README §5 的"调用期注入"是同一件事的两面：
    import 期一旦读配置或绑常量，门面重载就失效、测试缝也被关掉。
    """

    def test_importing_subpackages_creates_no_files(self):
        import tempfile
        import os
        before = set(os.listdir(ROOT / "data")) if (ROOT / "data").is_dir() else set()
        for name in EXTRACTED_PACKAGES:
            importlib.import_module(name)
        after = set(os.listdir(ROOT / "data")) if (ROOT / "data").is_dir() else set()
        self.assertEqual(before, after, "import 子包时 data/ 目录被写入了新文件")

    def test_subpackages_do_not_call_load_dotenv_or_start_threads(self):
        for pkg in EXTRACTED_PACKAGES:
            pkg_dir = SCRIPTS / pkg.split(".")[-1]
            for path in sorted(pkg_dir.glob("*.py")):
                src = path.read_text(encoding="utf-8")
                for banned in ("load_dotenv(", "Thread(", "threading.Thread", "os.environ["):
                    with self.subTest(file=path.name, banned=banned):
                        self.assertNotIn(banned, src,
                                         f"{path.name} 在模块作用域出现 {banned}，疑似 import 期副作用")


if __name__ == "__main__":
    unittest.main()
