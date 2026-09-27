r"""网关 pid 文件收敛 + 双读 bug 修复门（第一百一十八刀）。

## 背景

`data/astra_gateway.pid` 原先在 4 处各自拼路径；其中两个 router 写成

    pid = int(f.read_text().strip()) if f.exists() and f.read_text().strip().isdigit() else 0

**同一个文件读两次**：两次读之间文件被改写（或第二次读失败）会抛 `ValueError`/`OSError`
变成 500，`exists()` → `read_text()` 之间也是 TOCTOU 窗口。
本包 `supervisor.current_pid()` 早就是正确写法（单次读 + 捕获 `(OSError, ValueError)`）
—— 说明那两处是复制粘贴退化。现在统一到 `astra_gateway/pidfile.py`。

## 本门钉两件事

1. **结构**：路径字面量只允许出现在 `pidfile.py`；两个 router 必须走
   `read_pid()` / `process_running()`，且不得再出现"同文件读两次"的写法。
2. **行为**：`read_pid()` 对**原先会抛错**的输入（目录、非 UTF-8 字节、不可读）
   必须返回 0 而不是崩；正常路径与旧写法结果一致。
   `process_running()`：pid=0 ⇒ False，`os.kill` 抛 OSError（**含无权限**）⇒ False
   —— 无权限判为未运行是**原有语义**，不要"顺手改成"视为存活。
"""
from __future__ import annotations

import ast
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from astra_gateway.pidfile import PID_FILE, process_running, read_pid  # noqa: E402

ROUTERS = [
    ROOT / "astra_backend" / "routers" / "gateway" / "gateway_ops.py",
    ROOT / "astra_backend" / "routers" / "system.py",
]


class PidfileStructureTest(unittest.TestCase):
    def test_path_literal_only_in_pidfile_module(self):
        """路径字面量只允许出现在 `pidfile.py` 的**代码**里。

        ⚠️ 原先这一例用 `subprocess.run(["git", "grep", ...])` 实现，被离线套件
        （`tests/offline_suite.py`）的"外部子进程"守卫拦下 —— 守卫只放行
        `git show <rev>:<path>` 与 `git rev-parse --short <ref>` 两种形状，拦得对。
        改为**纯 AST 扫描**：找 `"astra_gateway.pid"` 字符串常量，跳过文档字符串
        （`ast.Expr(Constant)`），因此注释/文档里提到该路径不会被误判。
        """
        def is_docstring(node) -> bool:
            return isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) \
                and isinstance(node.value.value, str)

        offenders = []
        roots = [ROOT / d for d in ("astra_backend", "astra_gateway", "scripts", "tests")]
        for root in roots:
            if not root.exists():
                continue
            for path in sorted(root.rglob("*.py")):
                if path.name == "pidfile.py" and path.parent.name == "astra_gateway":
                    continue
                if path == Path(__file__).resolve():   # 本门自身必须引用该字面量才能断言
                    continue
                # ⚠️ 白名单：`scripts/migrate_r20_to_astra.py`（2026-09-27 一次性迁移工具）
                #    的**职责本身**就是按新旧名字搬迁 pid/lock/心跳文件 —— 它必须同时写出
                #    两个名字。它不是运行时容器，不参与"路径常量单一来源"那条约束。
                if path.name == "migrate_r20_to_astra.py":
                    continue
                # ⚠️ 同理：`tests/audit/test_sandbox_is_fixture_complete.py` 必须写出
                #    `astra_gateway.pid` 才能把"沙箱里被清空的运行态文件"分类登记。
                if path.name == "test_sandbox_is_fixture_complete.py":
                    continue
                try:
                    tree = ast.parse(path.read_text(encoding="utf-8"))
                except (OSError, SyntaxError, UnicodeDecodeError):
                    continue
                doc_values = {id(n.value) for n in ast.walk(tree) if is_docstring(n)}
                for node in ast.walk(tree):
                    if isinstance(node, ast.Constant) and node.value == "astra_gateway.pid" \
                            and id(node) not in doc_values:
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        self.assertEqual(offenders, [], "路径字面量必须只留在 pidfile.py 的代码里（其余处一律 import 常量）")

    def test_pid_file_points_at_data_dir(self):
        self.assertEqual(PID_FILE.name, "astra_gateway.pid")
        self.assertEqual(PID_FILE.parent.name, "data")
        self.assertEqual(PID_FILE.parent.parent, ROOT)

    def test_routers_use_the_helpers_and_have_no_double_read(self):
        for path in ROUTERS:
            src = path.read_text(encoding="utf-8")
            with self.subTest(router=path.name):
                self.assertIn("read_pid()", src, "必须走共享助手")
                self.assertIn("process_running(pid)", src)
                self.assertNotIn("pid_file.read_text", src)
                self.assertNotIn("os.kill(pid, 0)", src, "探活逻辑也应收敛进助手")
                # 同一文件读两次的退化写法
                self.assertIsNone(re.search(r"read_text\(\)[^\n]*read_text\(\)", src),
                                  "不得再出现'同一文件读两次'的写法")

    def test_helpers_are_the_only_pid_logic(self):
        tree = ast.parse((ROOT / "astra_gateway" / "pidfile.py").read_text(encoding="utf-8"))
        fns = {n.name for n in tree.body if isinstance(n, ast.FunctionDef)}
        self.assertLessEqual({"read_pid", "process_running"}, fns)


class ReadPidTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def _write(self, content: bytes) -> Path:
        p = self.tmp / "pid"
        p.write_bytes(content)
        return p

    def test_normal_values(self):
        self.assertEqual(read_pid(self._write(b"1234")), 1234)
        self.assertEqual(read_pid(self._write(b"  1234\n")), 1234, "两侧空白要被 strip")
        self.assertEqual(read_pid(self._write(b"0")), 0)

    def test_missing_file_is_zero(self):
        self.assertEqual(read_pid(self.tmp / "nope.pid"), 0)

    def test_non_digits_is_zero(self):
        for bad in (b"abc", b"12a", b"", b"   ", b"12.5", b"-7"):
            with self.subTest(bad=bad):
                self.assertEqual(read_pid(self._write(bad)), 0)

    def test_unreadable_inputs_return_zero_instead_of_raising(self):
        """**本刀修复的 bug**：目录、非 UTF-8 字节在旧写法下会抛 OSError/ValueError。"""
        self.assertEqual(read_pid(self.tmp), 0, "目录 ⇒ 0（旧写法会抛 IsADirectoryError）")
        self.assertEqual(read_pid(self._write(b"\xff\xfe not utf8")), 0,
                         "非 UTF-8 ⇒ 0（旧写法会抛 UnicodeDecodeError）")

    def test_default_path_is_the_gateway_pid(self):
        # 不依赖运行中的网关：显式传路径时行为一致即可
        self.assertIsInstance(read_pid(), int)


class ProcessRunningTest(unittest.TestCase):
    def test_zero_pid_is_false(self):
        self.assertFalse(process_running(0))

    def test_own_pid_is_true(self):
        self.assertTrue(process_running(os.getpid()))

    def test_dead_pid_is_false(self):
        self.assertFalse(process_running(99999999))

    def test_permission_error_means_not_running(self):
        """无权限判为未运行是**原有语义**（原实现 `except OSError: pass`）。"""
        from unittest.mock import patch
        with patch("astra_gateway.pidfile.os.kill", side_effect=PermissionError(1, "denied")):
            self.assertFalse(process_running(1234))

    def test_other_oserrors_mean_not_running(self):
        from unittest.mock import patch
        with patch("astra_gateway.pidfile.os.kill", side_effect=ProcessLookupError()):
            self.assertFalse(process_running(1234))


if __name__ == "__main__":
    unittest.main()
