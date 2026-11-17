r"""脚本入口 bootstrap 门（结构优化阶段 4·B3 第七十九刀）。

## 在防什么（本刀抓到的**实盘**停摆事故）

第四十四刀把 `news_sentiment_harvester.py` 的纯逻辑外提到
`scripts/news/importance.py`，门面顶层改成 `from scripts.news.importance import …`
—— 但**没抄 `factor_library.py` 同款的 sys.path bootstrap**。该脚本的日常运行
形态是**被调度器以子进程拉起**（`python scripts/news_sentiment_harvester.py`），
此时 `sys.path[0]` 是 `scripts/`，仓库根**不在路径上** ⇒

```
ModuleNotFoundError: No module named 'scripts'
```

快讯采集**静默停摆**（`news_sentiment.json` mtime 停在 02:34，
03:00–04:33 的 9 轮 `job=news` 全部 rc=0 假象？——不，是**旧文件时间戳
看起来还在被别的步骤刷新**，实测 04:43 修复后的下一轮才真正恢复采集）。

## 为什么这个判据可以是静态的（与第七十五刀的区分）

§91/§92 证明"**这条路径会不会写生产**"不能靠静态形状回答（效果问题）。
但"**脚本自己的 import 是否语法自洽**"是**纯静态可判定**的：
> 顶层 `from scripts.X import …`（或 `import scripts.X`）必须出现在
> 把仓库根塞进 `sys.path` 的语句**之后** —— 顺序即因果，无环境依赖。

## 判据

对 `scripts/` 下**同时满足**①顶层引用 `scripts.` 包②存在 `__main__` 或被
`run_script`/scheduler 以脚本方式拉起的文件：检查在**第一条** `scripts.`
顶层 import 之前，存在 `sys.path.insert(...)`/`append(...)` 且入参含
`__file__` 推导的仓库根。

⚠️ 自检用例先钉判据本身有效（§82.3 规矩）。
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"

#: 被以 `python <script>` 子进程方式拉起的入口（实测调用方：
#: scheduler JOBS / ai_factor_trader / sync_instruments_state 扇出 / daemon_web_sync）。
#: 新增 spawn 入口时必须加进这张表 —— 漏了就会复刻本刀的停摆。
SPAWNED_ENTRIES = (
    "news_sentiment_harvester.py",
    "factor_library.py",
    "sync_full_ledger.py",
    "ai_factor_trader.py",
)


def _first_scripts_import_line(tree: ast.Module) -> int | None:
    """第一条顶层 `scripts.` import 的行号（无则 None）。"""
    for n in tree.body:
        if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("scripts.") and n.level == 0:
            return n.lineno
        if isinstance(n, ast.Import):
            for a in n.names:
                if a.name.startswith("scripts."):
                    return n.lineno
    return None


def _bootstrap_line(tree: ast.Module) -> int | None:
    """首条**顶层** `sys.path.insert/append(...)` 调用的行号。

    ⚠️ 第一版是文本行匹配，当场被真实代码打脸两种合法写法：
    ① bootstrap 分多行（`_ROOT = Path(__file__)...` 一行、`insert` 一行，
       `__file__` 与 `sys.path.insert` 不同行）；
    ② import 用了别名（`import sys as _sys` ⇒ `_sys.path.insert`）。
    文本判据追不上写法多样性 —— 用 AST（判"调用形状"，别名免疫）。
    """
    best = None
    for sub in ast.walk(tree):
        # ⚠️ 只认**模块顶层语句（含其 if/try 包裹）内**的调用：
        # walk 会连函数体一起扫，但函数里的 sys.path 操作救不了顶层 import。
        # 用行号过滤：bootstrap 必须早于所有 def/class —— 由调用方比较 lineno
        # 与首条 scripts import 即可（import 必在顶层），这里先取最早命中。
        if (isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute)
                and sub.func.attr in ("insert", "append")
                and isinstance(sub.func.value, ast.Attribute)
                and sub.func.value.attr == "path"
                and isinstance(sub.func.value.value, ast.Name)
                and sub.func.value.value.id in ("sys", "_sys")):
            if best is None or sub.lineno < best:
                best = sub.lineno
    return best


class ScriptEntryBootstrapTest(unittest.TestCase):
    def test_spawned_entries_have_bootstrap_before_scripts_imports(self):
        missing = []
        for rel in SPAWNED_ENTRIES:
            f = SCRIPTS / rel
            self.assertTrue(f.is_file(), f"spawn 入口 {rel} 不存在（改名了？表要同步）")
            src = f.read_text(encoding="utf-8")
            tree = ast.parse(src)
            imp = _first_scripts_import_line(tree)
            if imp is None:
                continue                      # 不引用 scripts. 顶层包 ⇒ 无需 bootstrap
            boot = _bootstrap_line(tree)
            if boot is None or boot > imp:
                missing.append(f"{rel}: import@{imp} 先于 bootstrap@{boot}")
        self.assertEqual(
            missing, [],
            "这些**被子进程拉起的脚本**在 sys.path bootstrap 之前就 import 了 "
            "`scripts.` 顶层包 —— `python scripts/x.py` 形态必炸 "
            "ModuleNotFoundError（第四十四刀的 news 停摆事故形状）。"
            "修法：抄 factor_library.py 的 bootstrap 块到 import 之前:\n  "
            + "\n  ".join(missing))

    def test_judgment_actually_catches_the_pattern(self):
        """⚠️ 自检：判据必须**真能**抓住"import 先于 bootstrap"（防假绿）。"""
        bad = "\n".join([
            "import os",
            "from scripts.news.importance import x",
            "import sys",
            "sys.path.insert(0, str(__import__('pathlib').Path(__file__).parents[1]))",
        ])
        tree = ast.parse(bad)
        imp = _first_scripts_import_line(tree)
        boot = _bootstrap_line(tree)
        self.assertEqual(imp, 2)
        self.assertEqual(boot, 4)
        self.assertTrue(boot > imp, "自检失败：判据没识别出坏顺序")

        good = "\n".join(bad.splitlines()[::-1][:4][::-1])
        # 构造好顺序：bootstrap 在前
        good = "\n".join([
            "import sys",
            "sys.path.insert(0, str(__import__('pathlib').Path(__file__).parents[1]))",
            "from scripts.news.importance import x",
        ])
        tree2 = ast.parse(good)
        imp2 = _first_scripts_import_line(tree2)
        boot2 = _bootstrap_line(tree2)
        self.assertTrue(boot2 < imp2, "自检失败：好顺序被误报")

    def test_all_scripts_level_importers_are_known(self):
        """登记表覆盖率哨兵：出现**新的**"顶层 import scripts. 的
        scripts/ 直跑脚本"而没进 SPAWNED_ENTRIES ⇒ 提醒归类。"""
        known = set(SPAWNED_ENTRIES)
        new_ones = []
        for f in sorted(SCRIPTS.glob("*.py")):
            if f.name in known:
                continue
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                continue
            has_main = any(
                isinstance(n, ast.If) and "name" in ast.dump(n.test) and "__main__" in ast.dump(n.test)
                for n in tree.body)
            if has_main:
                imp = _first_scripts_import_line(tree)
                boot = _bootstrap_line(tree)
                if imp is not None and (boot is None or boot > imp):
                    new_ones.append(
                        f"{f.name}: import@{imp} 先于 bootstrap@{boot}")
        self.assertEqual(
            new_ones, [],
            "这些 scripts/ 直跑脚本顶层 import `scripts.` 却没有先行 bootstrap —— "
            "被以脚本方式拉起必炸（news 停摆形状）。补 factor_library 同款块:\n  "
            + "\n  ".join(new_ones))


if __name__ == "__main__":
    unittest.main()
