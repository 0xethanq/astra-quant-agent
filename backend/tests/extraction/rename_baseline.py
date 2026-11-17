"""抽取门禁的**基线适配层**：2026-09-27 把内部代号 `r20` 全量改名为 `astra`。

## 为什么需要它

抽取门（`tests/extraction/*`）的判据是"当前模块的段体必须与**抽取前那次提交**里的
对应段体**逐字同一棵 AST**"。那个提交里的包名是 `r20_backend`、环境变量键是 `R20_*`、
会话头是 `X-R20-Session`…… 改名之后逐字对比必然全红。

**但"改名前后的段体不同"不是搬运事故，是一次有意的、全局的命名空间迁移。**
若每个门各写一遍特例，就会出现 22 份互相不一致的解释；所以把这件事收进本模块，
由每个门**显式调用**两个纯函数：

- `git_show(rev_path)` —— 取基线源码。它会把路径映射回**老提交里的路径**
  （`astra_backend/x.py` → `r20_backend/x.py`），因为老提交里只有旧名；
- `normalize(source)` —— 把基线源码里的旧记号归一成新记号，使 AST 在
  "除改名外逐字相同"时相等。

## 边界：只做**记号级**替换，且有三处**有意不动**

替换表只覆盖"命名空间"记号（包名 / 环境变量键前缀 / 会话头 / 文件名词干）。
下面三处在改名中被**有意冻结**（改了会破坏既有数据），因此**不在**替换表内，
`normalize()` 会原样保留它们：

| 冻结串 | 原因 |
|---|---|
| `R20GCM2` | 备份归档**魔数**；改了读不了用户已有的归档（代码改为双魔数识别） |
| `cpa.r20.cn` | 用户自有的 DNS，且是线上启用中模型的网关 —— 不是我们的命名空间 |
| `"r20-base-module::"` | base 模块 id 的 **sha1 种子**；改了用户按 id 存的提示词自定义会静默失效 |

## 用法

```python
from tests.extraction.rename_baseline import git_show, normalize

def _baseline_method() -> ast.FunctionDef:
    src = git_show(f"{PRE}:astra_backend/exchanges/binance.py")
    cls = next(... for n in ast.parse(normalize(src)).body ...)
```
"""
from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

#: 旧包名 → 新包名（`git show <老提交>:<路径>` 用的是**旧路径**）
LEGACY_PREFIXES = (
    ("astra_backend/", "r20_backend/"),
    ("astra_gateway/", "r20_gateway/"),
    ("astra_backend", "r20_backend"),
    ("astra_gateway", "r20_gateway"),
)

#: 有意冻结的串：先换成哨兵，替换完再还原（顺序敏感，长的在前）
_FROZEN = (
    ("cpa.r20.cn", "\x00F1\x00"),
    ("R20GCM2", "\x00F2\x00"),
    ('"r20-base-module::"', "\x00F3\x00"),
)

#: 命名空间记号替换表（**顺序敏感**，从上到下）
_RULES = (
    ("X-R20-Session", "X-Astra-Session"),
    ("X-R20-Admin-Token", "X-Astra-Admin-Token"),
    ("x_r20_session", "x_astra_session"),
    ("x_r20_admin_token", "x_astra_admin_token"),
    ("R20QuantumTrader", "AstraQuantumTrader"),
    ("r20-quantum-trader", "astra-quant-trader"),
    ("r20_backend", "astra_backend"),
    ("r20_gateway", "astra_gateway"),
    ("r20_backup", "astra_backup"),
    ("r20_watchdog", "astra_watchdog"),
    ("R20_", "ASTRA_"),
    ("R20", "ASTRA"),
    ("r20", "astra"),
)


def legacy_path(path: str) -> str:
    """把**当前树**的相对路径映射回**老提交**里的路径。

    老提交里只有旧名，所以 `git show <PRE>:astra_backend/...` 必然取不到；
    这是"改名"这件事的必然结果，不是路径写错了。
    """
    for new, old in LEGACY_PREFIXES:
        if path.startswith(new):
            return old + path[len(new):]
    return path


def legacy_rev_path(rev_path: str) -> str:
    """`"<rev>:<path>"` → 把 path 部分映射回旧名。无冒号时按纯路径处理。"""
    if ":" not in rev_path:
        return legacy_path(rev_path)
    rev, path = rev_path.split(":", 1)
    return f"{rev}:{legacy_path(path)}"


def normalize(source: str) -> str:
    """把基线源码里的旧命名空间记号归一成新记号（冻结串原样保留）。"""
    text = source
    for old, sent in _FROZEN:
        text = text.replace(old, sent)
    for old, new in _RULES:
        text = text.replace(old, new)
    for old, sent in _FROZEN:
        text = text.replace(sent, old)
    return text


def git_show(rev_path: str) -> str:
    """取基线源码：自动把路径映射回旧名。取不到就**大声失败**（不静默返回空串）。"""
    r = subprocess.run(["git", "show", legacy_rev_path(rev_path)],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert r.returncode == 0, (
        f"基线取不到（{legacy_rev_path(rev_path)}）：{r.stderr[:200]}\n"
        "  提示：老提交里只有 r20_* 旧名；本函数已自动映射，若仍失败说明该路径在"
        "老提交里压根不存在（改名前就不是这个位置）。")
    return r.stdout


if __name__ == "__main__":      # 自证：把当前树的一个文件按老名取回并归一
    import sys
    rel = sys.argv[1] if len(sys.argv) > 1 else "astra_backend/version.py"
    print(f"{rel} → 老路径 {legacy_path(rel)}")
