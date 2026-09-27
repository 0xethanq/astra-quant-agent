"""备份上传簇抽离（结构优化阶段 4·B3 第五十二刀）。

## 背景

`scripts/backup_runtime.py`（628 行）里有三块职责清晰但混住的内容：

| 簇 | 函数 | 行数 |
|---|---|---|
| **上传目标** | `calculate_sha256` + 4 个 `upload_*` + 3 个私有辅助 | **212 行（34%）** |
| 归档与加解密 | `create_archive` / `encrypt_archive` / `decrypt_archive` / `verify_archive` / `_derive_key` | 130 行 |
| 作业编排 | `run_backup_job` / `deliver_target` / `sqlite_hot_backups` / 保留与清理 | 183 行 |

本刀抽出**上传目标**簇到 `scripts/backup_upload.py`（282 行），
门面 `backup_runtime.py` **628 → 481 行**，保留同名薄壳。

选这一簇的依据（两条判据实测）：**上传簇是唯一不读任何模块级路径常量的**
（`ROOT` / `LOCAL_DIR` / `MANIFEST_DIR` / `SQLITE_DIR` / `SCOPE_PATHS`
在四个 `upload_*` 与三个私有辅助里**零出现**），故独立成模块不影响门面的路径接缝。

## ⚠️ 本刀最关键的约束：两个 patch 缝必须仍然生效

门面有两个**被测试 patch 的名字**：

| 缝 | 用到它的测试 |
|---|---|
| `_urlencoded_json` / `_multipart_upload` | `test_audit_batch5_d_tails.py`（百度 OAuth） |
| `calculate_sha256` | `test_open_source_control.py`（`run_backup_job`） |

若这些函数在 import 期从共享模块取名字，补丁就**静默失效**。故：

- 共享模块的 `upload_s3` 用**形参** `calculate_sha256`；
- 四个 `upload_*` 用**形参** `_credentials`；
- `upload_baidu_oauth` 另用形参 `_urlencoded_json` / `_multipart_upload`；
- 门面薄壳在**调用时**解析自己的全局并传入。

`InjectionStillWorksTest` 专门用 `patch.object(br, …)` 把这条钉住 ——
它会在"烘焙副本"的改法下立刻翻红。
"""

from __future__ import annotations

import ast
import hashlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

FACADE = ROOT / "scripts" / "backup_runtime.py"
SHARED = ROOT / "scripts" / "backup_upload.py"
PRE_EXTRACTION_COMMIT = "1aa40bd"

MOVED = ["calculate_sha256", "_credentials", "_urlencoded_json", "_multipart_upload",
         "upload_baidu_oauth", "upload_s3", "upload_oss", "upload_webdav", "upload_baidu"]

import backup_runtime as br  # noqa: E402
import backup_upload as bu  # noqa: E402
from tests.extraction.rename_baseline import legacy_rev_path, normalize


class FacadeSurfaceTest(unittest.TestCase):
    def test_facade_still_exposes_every_moved_name(self):
        """门面必须**继续提供**全部既有名字（外部 import 与测试按门面名解析）。"""
        for name in MOVED:
            self.assertTrue(callable(getattr(br, name, None)), f"门面缺少 {name}")

    def test_facade_also_keeps_the_untouched_clusters(self):
        """未搬动的簇不得受影响。"""
        for name in ("create_archive", "encrypt_archive", "decrypt_archive",
                     "verify_archive", "deliver_target", "run_backup_job",
                     "sqlite_hot_backups", "retain_local_archive", "prune",
                     "clean_stale_staging"):
            self.assertTrue(callable(getattr(br, name, None)), f"门面缺少 {name}")

    def test_shells_are_definitions_not_aliases(self):
        """⚠️ 薄壳必须是**定义**：别名赋值会让 `patch.object(br, …)` 之类接缝失效。"""
        for name in MOVED:
            self.assertIsNot(getattr(br, name), getattr(bu, name),
                             f"{name} 在门面里是别名而非薄壳")

    def test_every_shell_delegates_to_the_shared_module(self):
        tree = ast.parse(FACADE.read_text(encoding="utf-8"))
        by_name = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        for name in MOVED:
            n = by_name.get(name)
            self.assertIsNotNone(n, f"门面未定义 {name}")
            body = [s for s in n.body
                    if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))]
            self.assertEqual(len(body), 1, f"{name} 壳不止一条语句")
            self.assertIn("_up_", ast.unparse(body[0]), f"{name} 未转调共享实现")


class InjectionStillWorksTest(unittest.TestCase):
    """⚠️ 本刀的核心回归：两个 patch 缝必须仍然生效。

    做法是**行为注入证明**：把门面全局换成会抛哨兵异常的替身，
    若这个哨兵从共享实现里冒出来，就证明**被 patch 的对象真的被传进去了**
    （而不是共享模块在 import 期烘焙了自己的副本）。

    ⚠️ 我第一版写成了"跑完整个 upload 再看副作用"，结果两条都失败 ——
    **是测试写错，不是代码错**：
      ① `upload_baidu_oauth` 会调 `_urlencoded_json` **三次**
         （token 端点 + precreate + …），我断言的"最后一次 url"是 precreate 的；
      ② `upload_oss` **先** `import oss2`（可选依赖，本机没装），
         在调到 `_credentials` 之前就抛了。
    改用哨兵后既不依赖网络、也不依赖可选依赖。
    """

    class _Sentinel(Exception):
        pass

    def setUp(self):
        import tempfile
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)
        self.src = self.tmp / "a.bin"
        self.src.write_bytes(b"payload")
        self.target = {"id": "t1", "credential_ref": "backup:t1"}

    def test_urlencoded_json_patch_reaches_the_moved_core(self):
        """`patch.object(br, "_urlencoded_json", …)` 必须拦住共享实现里的网络调用。

        这正是 `tests/audit/test_audit_batch5_d_tails.py` 的做法（拦百度 OAuth）。
        """
        def boom(*a, **k):
            raise self._Sentinel("patched _urlencoded_json was called")

        with patch.object(br, "_credentials",
                          return_value={"app_key": "k", "app_secret": "s",
                                        "refresh_token": "r"}), \
             patch.object(br, "_urlencoded_json", side_effect=boom):
            with self.assertRaises(self._Sentinel) as ctx:
                br.upload_baidu_oauth(self.src, self.target)
        self.assertIn("patched _urlencoded_json", str(ctx.exception))

    def test_credentials_patch_reaches_upload_baidu_oauth(self):
        """`_credentials` 必须由门面注入共享实现。"""
        def boom(*a, **k):
            raise self._Sentinel("patched _credentials was called")

        with patch.object(br, "_credentials", side_effect=boom):
            with self.assertRaises(self._Sentinel):
                br.upload_baidu_oauth(self.src, self.target)

    def test_multipart_upload_patch_reaches_the_moved_core(self):
        """`_multipart_upload` 同样是 `test_audit_batch5_d_tails` 的 patch 目标。

        ⚠️ 走通到它需要 precreate 返回 `uploadid`（否则在更早一步就
        `RuntimeError: 百度网盘预创建未返回 uploadid`）—— 我第一版漏了，
        又是一次"期望值靠猜"。
        """
        def boom(*a, **k):
            raise self._Sentinel("patched _multipart_upload was called")

        with patch.object(br, "_credentials",
                          return_value={"app_key": "k", "app_secret": "s",
                                        "refresh_token": "r"}), \
             patch.object(br, "_urlencoded_json",
                          return_value={"access_token": "tok",
                                        "uploadid": "uid-1"}), \
             patch.object(br, "_multipart_upload", side_effect=boom):
            with self.assertRaises(self._Sentinel):
                br.upload_baidu_oauth(self.src, self.target)

    def test_calculate_sha256_patch_reaches_upload_s3(self):
        """`patch.object(br, "calculate_sha256")` 必须影响 `upload_s3` 的取值。"""
        def boom(*a, **k):
            raise self._Sentinel("patched calculate_sha256 was called")

        with patch.object(br, "_credentials",
                          return_value={"access_key_id": "ak",
                                        "secret_access_key": "sk"}), \
             patch.object(br, "calculate_sha256", side_effect=boom):
            with self.assertRaises(self._Sentinel):
                br.upload_s3(self.src, {"id": "t2", "bucket": "b",
                                        "endpoint": "https://e.example"})

    def test_calculate_sha256_is_injected_not_imported(self):
        """⚠️ 结构性反证：共享模块的 `upload_s3` 必须**收**一个 `calculate_sha256` 形参。"""
        import inspect
        params = inspect.signature(bu.upload_s3).parameters
        self.assertIn("calculate_sha256", params,
                      "upload_s3 没有 calculate_sha256 形参 —— 说明它只能靠 import 取，"
                      "那门面的 patch 就会静默失效")

    def test_all_upload_cores_take_credentials_as_a_parameter(self):
        """⚠️ 四个 `upload_*` 都必须**收** `_credentials` 形参（同上理由）。"""
        import inspect
        for name in ("upload_baidu_oauth", "upload_s3", "upload_oss", "upload_webdav"):
            params = inspect.signature(getattr(bu, name)).parameters
            self.assertIn("_credentials", params, f"{name} 缺少 _credentials 形参")


class VerbatimCopyTest(unittest.TestCase):
    """⚠️ 搬移只允许**复制**，不允许重写（第五十刀的教训）。

    从 `PRE_EXTRACTION_COMMIT` 取旧实现（**不是** `HEAD:` ——
    那会在下一次提交后自我失效，第四十六刀踩过这个坑）。
    """

    def _old_body(self, name):
        import subprocess
        src = subprocess.run(
            ["git", "show", legacy_rev_path(f"{PRE_EXTRACTION_COMMIT}:scripts/backup_runtime.py")],
            capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(src.returncode, 0, src.stderr)
        tree = ast.parse(normalize(src.stdout))
        n = next(x for x in tree.body
                 if isinstance(x, ast.FunctionDef) and x.name == name)
        return ast.unparse(ast.Module(
            body=[s for s in n.body
                  if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))],
            type_ignores=[]))

    def _new_body(self, name):
        tree = ast.parse(SHARED.read_text(encoding="utf-8"))
        n = next(x for x in tree.body
                 if isinstance(x, ast.FunctionDef) and x.name == name)
        return ast.unparse(ast.Module(
            body=[s for s in n.body
                  if not (isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant))],
            type_ignores=[]))

class SharedModuleHygieneTest(unittest.TestCase):
    def test_shared_module_reads_no_path_constants(self):
        """⚠️ 上传簇**不读任何模块级路径常量** —— 这正是它能独立成模块的依据。

        若将来有人往里塞 `ROOT` / `LOCAL_DIR` 之类，本用例会翻红并提醒
        "那就不是可独立的一块了"。
        """
        tree = ast.parse(SHARED.read_text(encoding="utf-8"))
        assigned = {t.id for n in tree.body if isinstance(n, ast.Assign)
                    for t in n.targets if isinstance(t, ast.Name)}
        for banned in ("ROOT", "LOCAL_DIR", "MANIFEST_DIR", "SQLITE_DIR",
                       "SCOPE_PATHS", "BACKUPS"):
            self.assertNotIn(banned, assigned,
                             f"backup_upload 定义了路径常量 {banned} —— 它不该有")

    def test_shared_module_does_not_import_the_facade(self):
        """反向依赖会成环。"""
        tree = ast.parse(SHARED.read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Import):
                for a in n.names:
                    self.assertNotEqual(a.name, "backup_runtime")
            elif isinstance(n, ast.ImportFrom):
                self.assertNotEqual(n.module, "backup_runtime")

    def test_calculate_sha256_still_matches_hashlib(self):
        import tempfile
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, tmp, ignore_errors=True)
        f = tmp / "x.bin"
        payload = b"hello ASTRA backup"
        f.write_bytes(payload)
        self.assertEqual(br.calculate_sha256(f),
                         hashlib.sha256(payload).hexdigest())
        self.assertEqual(bu.calculate_sha256(f),
                         hashlib.sha256(payload).hexdigest())


if __name__ == "__main__":
    unittest.main()
