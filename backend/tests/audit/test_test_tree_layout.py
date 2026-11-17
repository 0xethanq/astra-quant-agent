r"""测试树布局门（第一百三十八刀）。

## 为什么有这条门

把 219 个测试按域分子目录时，我踩了**同一个地雷两次**：

1. `tests/platform/` —— 测试常把 `tests/` 放进 `sys.path`，于是它**遮蔽标准库 `platform`**，
   pydantic/requests 一票依赖连锁崩（报错却是 `cannot import name 'BaseModel'`，极难定位）；
2. `tests/dashboard/` —— 因为目录里有 `__init__.py`（常规包），它在 `sys.path` 上
   **优先于仓库根的 `dashboard/`**（常规包胜过命名空间包）⇒ 任何"从 tests/ 起的脚本"
   再 `import astra_backend.dashboard_cache` 都会 `ModuleNotFoundError`。

两者都不是测试逻辑问题，而是**目录命名**问题，且症状离病因很远。故用门钉死：
`tests/` 下的域目录名**不得**与标准库模块名或仓库顶层包名重名。
"""
from __future__ import annotations

import sys
import sysconfig
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

STDLIB_NAMES = set(getattr(sys, "stdlib_module_names", ()))


class TestTreeBucketNamesTest(unittest.TestCase):
    def _buckets(self):
        return sorted(d.name for d in (ROOT / "tests").iterdir()
                      if d.is_dir() and d.name not in {"__pycache__", "data"})

    def test_buckets_do_not_shadow_stdlib(self):
        clashes = sorted(set(self._buckets()) & STDLIB_NAMES)
        self.assertEqual(clashes, [], "tests/ 子目录名与标准库模块重名 ⇒ 会把 tests/ 加进 "
                                      "sys.path 的测试/脚本连锁搞崩（platform 踩过）")
        # 顺带确认判据本身有效（当前解释器确实认识 platform）
        self.assertIn("platform", STDLIB_NAMES)

    def test_buckets_do_not_shadow_top_level_packages(self):
        top = sorted(d.name for d in ROOT.iterdir()
                     if d.is_dir() and (d / "__init__.py").exists())
        clashes = sorted(set(self._buckets()) & set(top))
        self.assertEqual(clashes, [], "tests/ 子目录名与仓库顶层包重名 ⇒ 常规包会抢在命名空间包"
                                      "之前被 import 到（dashboard 踩过）")

    def test_bucket_names_are_recognised(self):
        buckets = self._buckets()
        self.assertGreaterEqual(len(buckets), 6, f"域目录数量异常：{buckets}")
        for expected in ("extraction", "audit", "venues", "llm", "ui", "ops", "trading", "core"):
            self.assertIn(expected, buckets, f"预期域目录缺失：{expected}")


if __name__ == "__main__":
    unittest.main()
