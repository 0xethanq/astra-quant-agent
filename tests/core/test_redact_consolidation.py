"""`astra_backend/redact.py` 凭证脱敏单一事实源（阶段 4·B3 第四十九刀）。

## 修了什么

跨文件重复扫描发现两个**逐字相同**的凭证脱敏函数：

| 位置 | 名字 | 消费者 |
|---|---|---|
| `astra_backend/settings_store.py` L65 | `mask(value, visible=4)` | 后台设置页（`routers/gateway/notifications.py`） |
| `astra_backend/llm/util.py` L32 | `mask_secret(value, visible=4)` | LLM 配置页（`llm/store.py`、`llm_manager.py`） |

函数体各 6 行、**逐字节相同**，签名一致；行为对拍 50 组用例**零差异**。

**此刻不是 bug**，但它是**安全敏感**的漂移风险：两处都在决定"密钥能露出几个
字符"。任何一处被改动（把 `'*' * 8` 改成 `'*' * 4`、或改掉 `visible * 2`
边界），另一处不会跟着改 —— **后台设置页与 LLM 配置页会对密钥做不同强度的
脱敏，弱的那一侧成为泄露面**。

现收敛到 `astra_backend/redact.py::mask`，两个名字都转发到它。

## ⚠️ 为什么保留两个"壳"而不是直接别名

两个消费方各保留**自己的**薄壳，而不是 `mask_secret = mask` 这种别名赋值：

1. `tests/audit/test_audit_batch1_credentials_trust_boundary.py` 直接
   `from astra_backend.settings_store import mask`；
2. `tests/test_llm_seam_discipline.py` 的公开面清单里钉着 `"mask_secret"`；
3. 本仓约定：`patch.object(模块, "名字")` 是重要接缝，别名赋值会让
   "门面全局"这个概念失效（见 `scripts/trader/signals.py` 模块文档）。

故本文件的测试**不**断言"两个名字是同一个对象"，而是断言
**"两者的可执行体都只是转发到同一个共享实现"** —— 那才是真正的不漂移保证。

## ⚠️ 8 个星与 `is_masked` 是一对契约

`settings_store.is_masked()` 靠"含连续 8 个星"识别脱敏产物，
用于「脱敏读 ↔ 明文写回环」防线（掩码串回传一律视为未改动、绝不落盘）。
故中段星号数**固定 8**不得改 —— 改了会让防线失效（把真密钥当掩码存进去，
或把掩码当真密钥落盘）。本文件把该常数钉住。
"""

from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULE = ROOT / "astra_backend" / "redact.py"
SETTINGS_STORE = ROOT / "astra_backend" / "settings_store.py"
LLM_UTIL = ROOT / "astra_backend" / "llm" / "util.py"

from astra_backend.redact import MASK_STARS, mask  # noqa: E402
from astra_backend.llm.util import mask_secret  # noqa: E402
from astra_backend.settings_store import mask as store_mask  # noqa: E402


class MaskSemanticsTest(unittest.TestCase):
    def test_empty_returns_empty(self):
        """⚠️ 空值必须返回空串 —— 调用方据此判"没有配置密钥"。"""
        self.assertEqual(mask(""), "")
        self.assertEqual(mask("", visible=8), "")

    def test_short_secret_fully_starred(self):
        """⚠️ `len <= visible*2` 时**整体遮住**，不泄露长度以外的信息。"""
        self.assertEqual(mask("abcd", visible=2), "****")
        self.assertEqual(mask("abc", visible=4), "***")

    def test_boundary_is_inclusive(self):
        """边界 `len == visible*2` 归入"全星"分支。"""
        self.assertEqual(mask("abcdefgh", visible=4), "*" * 8)
        self.assertEqual(mask("abcdefghi", visible=4),
                         "abcd" + "*" * 8 + "efghi"[-4:])

    def test_long_secret_keeps_head_and_tail(self):
        out = mask("sk-1234567890abcdef", visible=4)
        self.assertTrue(out.startswith("sk-1"))
        self.assertTrue(out.endswith("cdef"))
        self.assertIn("*" * 8, out)

    def test_middle_star_count_is_fixed_eight(self):
        """⚠️ 中段恒为 8 个星，**不随密钥长度变化**（不泄露长度）。"""
        self.assertEqual(MASK_STARS, 8)
        for n in (10, 20, 100, 500):
            out = mask("a" * n, visible=4)
            self.assertIn("*" * 8, out)
            self.assertNotIn("*" * 9, out, f"n={n} 出现了 9 连星")

    def test_default_visible_is_four(self):
        self.assertEqual(mask("abcdefghijkl"), mask("abcdefghijkl", visible=4))

    def test_secret_never_appears_whole(self):
        """核心安全性质：长密钥不得原样出现在输出里。"""
        for secret in ("sk-live-abcdefghijklmnop", "x" * 64, "ASTRAadmin888888"):
            out = mask(secret, visible=4)
            self.assertNotEqual(out, secret)
            if len(secret) > 8:
                self.assertNotIn(secret, out)

    def test_output_is_str(self):
        for v in ("", "a", "abcdefghijklmnop"):
            self.assertIsInstance(mask(v), str)


class NoDriftPossibleTest(unittest.TestCase):
    """⚠️ 本刀的核心：两个消费方**不可能**再各自漂移。"""

    def test_both_consumers_agree_over_a_grid(self):
        cases = ["", "a", "abcd", "abcde", "abcdefgh", "abcdefghi", "x" * 40,
                 "sk-1234567890abcdef", "中文密钥甲乙丙丁戊己庚辛"]
        for v in cases:
            for vis in (1, 2, 4, 6, 8):
                self.assertEqual(store_mask(v, vis), mask(v, vis),
                                 f"settings_store.mask 偏离: {v!r}/{vis}")
                self.assertEqual(mask_secret(v, vis), mask(v, vis),
                                 f"llm.util.mask_secret 偏离: {v!r}/{vis}")

    def test_consumers_no_longer_hold_their_own_implementation(self):
        """两个消费方里都**不该**再有原来的实现体（只看可执行语句）。"""
        for path in (SETTINGS_STORE, LLM_UTIL):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for n in tree.body:
                if isinstance(n, ast.FunctionDef) and n.name in ("mask", "mask_secret"):
                    body = ast.unparse(ast.Module(body=n.body, type_ignores=[]))
                    self.assertNotIn("visible * 2", body,
                                     f"{path.name}::{n.name} 仍内联着边界判断")
                    self.assertNotIn("'*' * 8", body,
                                     f"{path.name}::{n.name} 仍内联着星号拼接")

    def test_consumers_delegate_to_the_shared_implementation(self):
        """两者的可执行体都必须只有"转发到 `_redact_mask`"。"""
        for path in (SETTINGS_STORE, LLM_UTIL):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for n in tree.body:
                if isinstance(n, ast.FunctionDef) and n.name in ("mask", "mask_secret"):
                    body = [s for s in n.body
                            if not (isinstance(s, ast.Expr)
                                    and isinstance(s.value, ast.Constant))]
                    self.assertEqual(len(body), 1,
                                     f"{path.name}::{n.name} 壳不止一条语句")
                    self.assertIn("_redact_mask", ast.unparse(body[0]))

    def test_only_one_implementation_repo_wide(self):
        """全仓（非测试/非归档）只应有一处**实现**。"""
        offenders = []
        for p in ROOT.rglob("*.py"):
            if any(x in p.parts for x in (".venv", "plan_local", "__pycache__",
                                          "node_modules", ".git", ".archive", "tests")):
                continue
            if p == MODULE:
                continue
            try:
                tree = ast.parse(p.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for n in tree.body:
                if isinstance(n, ast.FunctionDef) and n.name in ("mask", "mask_secret"):
                    body = ast.unparse(ast.Module(body=n.body, type_ignores=[]))
                    if "visible * 2" in body:
                        offenders.append(f"{p}::{n.name}")
        self.assertEqual(offenders, [], f"仍有内联实现: {offenders}")

    def test_shared_module_depends_only_on_stdlib(self):
        """⚠️ `redact` 不得 import `settings_store`（带 config/file_locks）
        或 `llm` —— 否则会给两个消费方引入新的模块耦合。"""
        tree = ast.parse(MODULE.read_text(encoding="utf-8"))
        imported = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                imported |= {a.name.split(".")[0] for a in n.names}
            elif isinstance(n, ast.ImportFrom):
                imported.add((n.module or "").split(".")[0])
        self.assertEqual(imported - {"__future__"}, set(),
                         f"redact 不该有任何运行时依赖，实际: {imported}")


class IsMaskedContractTest(unittest.TestCase):
    """⚠️ 8 个星与 `is_masked` 是一对契约（脱敏读↔明文写回环防线）。"""

    def test_is_masked_recognises_our_output(self):
        from astra_backend.settings_store import is_masked
        for secret in ("abcdefg1234567", "sk-live-abcdefghijklmnop", "x" * 40):
            self.assertTrue(is_masked(mask(secret)),
                            f"is_masked 未识别 mask({secret!r}) 的产物")

    def test_changing_star_count_would_break_is_masked(self):
        """反证：若中段星数不是 8，`is_masked` 就认不出（故这个 8 不可改）。"""
        from astra_backend.settings_store import is_masked
        self.assertEqual(MASK_STARS, 8)
        self.assertFalse(is_masked("abcd" + "*" * 7 + "efgh"),
                         "7 连星不应被识别 —— 说明 8 这个数是有意义的")
        self.assertTrue(is_masked("abcd" + "*" * 8 + "efgh"))

    def test_is_masked_unchanged(self):
        """`is_masked` 本身不在本刀改动范围内（只确认它没被牵连）。"""
        from astra_backend.settings_store import is_masked
        self.assertFalse(is_masked(""))
        self.assertFalse(is_masked("https://oapi.example/hook?key=REAL"))
        self.assertFalse(is_masked("short*star"))
        self.assertTrue(is_masked("********"))
        self.assertTrue(is_masked("****"))


class PublicSurfaceTest(unittest.TestCase):
    def test_settings_store_still_exports_mask(self):
        import astra_backend.settings_store as ss
        self.assertTrue(callable(ss.mask))
        self.assertTrue(callable(ss.mask_url))
        self.assertTrue(callable(ss.is_masked))

    def test_llm_manager_still_exports_mask_secret(self):
        """`test_llm_seam_discipline` 的公开面清单钉着 `mask_secret`。"""
        import astra_backend.llm_manager as lm
        self.assertTrue(callable(getattr(lm, "mask_secret", None)))

    def test_llm_util_still_exports_mask_secret(self):
        import astra_backend.llm.util as lu
        self.assertTrue(callable(lu.mask_secret))


if __name__ == "__main__":
    unittest.main()
