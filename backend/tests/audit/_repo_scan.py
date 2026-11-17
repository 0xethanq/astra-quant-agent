"""进程级共享的仓库扫描缓存（audit 门禁专用）。

## 为什么需要它（有实测依据）

`tests/audit/` 在整套测试里占 4% 的用例、却吃掉 **43% 的运行时间**（166s / 394s）。
定位下来根因不是用例多，而是**二十多道门各自把全仓 `.py` 解析一遍**。本机实测
（773 个 `.py`，含 `tests/` 525 个）：

| 阶段 | 耗时 |
|---|---:|
| 走目录 `rglob` | 0.01s |
| 读全部文本 | 0.06s |
| **解析全部 AST** | **5.41s** |
| 合计 | 5.48s |

也就是说成本**几乎全在 `ast.parse`**。每道门各解一遍 ⇒ 23 道 ≈ 124s。
这里把"走目录 / 读文本 / 解析 AST"三层都做成进程级缓存：整套 audit 只付
**一次** 5.4s，其余门禁全部复用。

## 为什么缓存是安全的

- 门禁**只读**源码，从不在测试运行期间改写仓库里的 `.py` ⇒ 一份进程内快照就是一致的。
- 缓存键是**绝对路径**；`.venv/` `node_modules/` `.git/` `.archive/` `__pycache__/`
  等非源码目录一律不纳入扫描范围（否则会把第三方包装进判据）。
- 返回的 AST 是**共享对象**：调用方只许读、不许改。要改自己的树请自己 `ast.parse`
  （例如"故意改坏再断言报红"的负向验证用例）。

## 用法

```python
from tests.audit import _repo_scan as scan

for path in scan.py_files("tests"):          # 一次走目录，之后全进程复用
    tree = scan.tree(path)                   # 一次解析，之后全进程复用
    src = scan.text(path)                    # 一次读盘，之后全进程复用
```
"""
from __future__ import annotations

import ast
from functools import lru_cache
from pathlib import Path

#: 仓库根（本文件在 tests/audit/ 下，向上两级）。
REPO = Path(__file__).resolve().parents[2]

#: 扫描时**一律跳过**的目录名（按路径组件匹配）。
SKIP_DIRS = frozenset({
    "__pycache__", ".git", ".venv", "node_modules", ".archive",
    ".mypy_cache", ".pytest_cache", ".ruff_cache", "backups", "dist", "build",
})


def _under_repo(path: Path) -> Path:
    """把相对路径（如 `"tests"`）挂到仓库根上；已是绝对路径则原样返回。"""
    return path if path.is_absolute() else REPO / path


@lru_cache(maxsize=None)
def py_files(root: str = "") -> "tuple[Path, ...]":
    """`root` 下的全部 `.py`（排序、去重、跳过 `SKIP_DIRS`）。`root=""` 表示整个仓库。"""
    base = _under_repo(Path(root)) if root else REPO
    if not base.is_dir():
        return ()
    return tuple(sorted(
        p for p in base.rglob("*.py")
        if not (SKIP_DIRS & set(p.parts))
    ))


@lru_cache(maxsize=None)
def text(path) -> str:
    """文件文本（UTF-8）。读不到时返回空串 —— 与门禁们既有的"读不到就跳过"语义一致。"""
    try:
        return _under_repo(Path(path)).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


@lru_cache(maxsize=None)
def tree(path) -> "ast.Module | None":
    """已解析的 AST。语法坏 / 读不到返回 `None`（调用方自行跳过）。

    ⚠️ 返回的是**共享对象**：只读。要变形请自己 `ast.parse(scan.text(path))`。
    """
    src = text(path)
    if not src:
        return None
    try:
        return ast.parse(src)
    except SyntaxError:
        return None


def report_cache_stats() -> str:
    """一行人类可读的缓存命中情况（供需要自证"缓存真的生效"的门禁用）。"""
    return (f"py_files: {py_files.cache_info()}, "
            f"text: {text.cache_info()}, tree: {tree.cache_info()}")
