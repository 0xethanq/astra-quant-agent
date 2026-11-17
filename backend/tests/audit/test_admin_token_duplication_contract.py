"""`require_admin_token` 的**刻意重复**契约（阶段 4·B3 第四十七刀）。

## 这不是"忘了删的重复"，是**承重的重复**

`require_admin_token` 在 `app.py` 与 `dependencies.py` 里**逐字相同**（各 6 行，
可执行体逐字比对 `== True`）。跨文件重复扫描把它报成"去重候选"，
我据此删掉了 `app.py` 里的那份、改为从 `dependencies` 导入 ——
**结果 23 个测试全红**。

原因：`tests/test_memory_routes_isolated.py` 用 **AST 抽出 `app.py` 的
顶层函数/类定义**，再 `exec` 到一个**隔离作用域**里跑内存路由的端到端测试。
那个作用域**显式提供了 `hmac` 与 `settings`**：

```python
self.scope = dict(app=..., hmac=hmac,
                  settings=SimpleNamespace(admin_token='', setup_token=''), ...)
...
nodes = [n for n in tree.body
         if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
         and n.name in names]
self.assertEqual({n.name for n in nodes}, names)   # ← 名字集合必须恰好相等
exec(compile(ast.Module(body=nodes, type_ignores=[]), str(SOURCE), 'exec'), self.scope)
```

一旦 `require_admin_token` 变成 import：

1. AST 抽不到它 → 断言 `{n.name ...} == names` 失败；
2. 即使断言放宽，隔离作用域里调用它也会 `NameError`。

即 `app.py` 的**「可隔离执行」是既有契约**，而 `require_admin_token` 是
该契约的一部分。**删除这份重复会破坏契约，不是改进。**

## 本文件的作用

把这条约束**钉住**，并顺带守住重复不会**漂移**：

1. 两处都**必须定义**（不是 import）；
2. 两处的**可执行体必须逐字相同**（只允许 docstring 不同）；
3. 隔离执行契约仍成立（直接跑那个测试模块）；
4. 404/403 的**语义**（admin_token 优先于 setup_token、503 vs 403）不变。

> **教训：去重前先问「这份重复有没有承重」。**
> 重复扫描只能告诉你"两处一样"，不能告诉你"两处为什么一样"。
> 第四十七刀我先删后测才发现，本文件是补上的护栏。
"""

from __future__ import annotations

import ast
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

APP = ROOT / "astra_backend" / "app.py"
DEPS = ROOT / "astra_backend" / "dependencies.py"


def _fn(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for n in tree.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def _executable_body(fn) -> str:
    """函数体的**可执行**部分（剥掉 docstring），归一化成源码文本。"""
    body = [s for s in fn.body
            if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
    return ast.unparse(ast.Module(body=body, type_ignores=[]))


class LoadBearingDuplicationTest(unittest.TestCase):
    def test_defined_in_both_modules(self):
        """⚠️ 两处都必须是**定义**，不能有一处改成 import。"""
        self.assertIsNotNone(_fn(APP, "require_admin_token"),
                             "app.py 必须**定义**它（隔离执行契约）")
        self.assertIsNotNone(_fn(DEPS, "require_admin_token"),
                             "dependencies.py 必须**定义**它")

    def test_app_does_not_import_it_from_dependencies(self):
        """app.py **不得**从 dependencies 导入这个名字（那会抽不到 AST 节点）。"""
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module and "dependencies" in n.module:
                imported = {a.name for a in n.names}
                self.assertNotIn("require_admin_token", imported,
                                 "app.py 不能 import require_admin_token —— "
                                 "test_memory_routes_isolated 靠 AST 抽取它的定义")

    def test_bodies_are_byte_identical(self):
        """⚠️ 重复只有在**不漂移**时才是可接受的。这里守住同步。"""
        a = _executable_body(_fn(APP, "require_admin_token"))
        b = _executable_body(_fn(DEPS, "require_admin_token"))
        self.assertEqual(a, b,
                         "两处 require_admin_token 已漂移 —— 任一处改了鉴权逻辑，"
                         "另一处必须同步改（否则两套路由的鉴权行为会不一致）")

    def test_signature_identical(self):
        a = _fn(APP, "require_admin_token")
        b = _fn(DEPS, "require_admin_token")
        self.assertEqual(ast.unparse(a.args), ast.unparse(b.args))

    def test_both_use_timing_safe_comparison(self):
        """安全要求：令牌比较必须是 `hmac.compare_digest`，不能用 `==`。"""
        for path in (APP, DEPS):
            body = _executable_body(_fn(path, "require_admin_token"))
            self.assertIn("hmac.compare_digest", body,
                          f"{path.name} 没用计时安全比较")
            self.assertNotIn("token ==", body)
            self.assertNotIn("== token", body)

    def test_both_prefer_admin_token_over_setup_token(self):
        """⚠️ 语义：`admin_token or setup_token` —— admin 优先，setup 只是兜底。"""
        for path in (APP, DEPS):
            body = _executable_body(_fn(path, "require_admin_token"))
            self.assertIn("settings.admin_token or settings.setup_token", body)

    def test_status_codes_unchanged(self):
        """⚠️ 503（未配置）与 403（令牌无效）的区分是**运维可诊断性**，勿合并。"""
        for path in (APP, DEPS):
            body = _executable_body(_fn(path, "require_admin_token"))
            self.assertIn("status_code=503", body)
            self.assertIn("status_code=403", body)

    def test_both_files_import_hmac(self):
        """删掉重复时顺手删了 `import hmac` —— 恢复定义后必须也恢复导入。"""
        for path in (APP, DEPS):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            has = any(isinstance(n, ast.Import) and
                      any(a.name == "hmac" for a in n.names) for n in tree.body)
            self.assertTrue(has, f"{path.name} 缺少顶层 import hmac")


class IsolationContractStillGreenTest(unittest.TestCase):
    # 「该模块单独跑也绿」这条判据**已合并**到
    # `tests/audit/test_standalone_modules_stay_green.py`（一次子进程跑完所有这类模块，
    # 原先每个模块各起一次解释器）。原用例名：test_memory_routes_isolated_passes。

    def test_ast_extraction_finds_the_name(self):
        """复现该测试的抽取方式，确认 `require_admin_token` 在节点集合里。"""
        names = {"require_admin_token", "current_admin", "require_admin_header",
                 "admin_session_context", "get_admin_memory"}
        tree = ast.parse(APP.read_text(encoding="utf-8"))
        nodes = [n for n in tree.body
                 if isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name in names]
        self.assertIn("require_admin_token", {n.name for n in nodes})


if __name__ == "__main__":
    unittest.main()
