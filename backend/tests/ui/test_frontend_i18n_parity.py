"""前端 i18n 键位回归闸：中英必须结构对称，且代码里用到的键必须真的存在。

两个真实缺陷催生了本测试：
1. **D1（阶段 0，commit f201478）**：zh 把 `promptElided` 放在 `col:` 下，
   en 放在 `detail:` 下，而组件调用的是 `dash.radar.detail.promptElided`。
   useI18n 的 t() 缺键回退链末位是「键路径」→ **中文界面直接显示裸键名**
   `（dash.radar.detail.promptElided）`，英文界面正常，故长期未被发现。
   两侧结构不对称是这类 bug 的温床。
2. **legacy 层残留（阶段 0 已清）**：迁移期兼容层会掩盖缺失键，使问题不可见。

因此本测试钉两件事：
  A. 结构对称：zh 与 en 的同名 locale 文件，键路径集合必须**完全一致**；
  B. 键位可解析：源码里所有静态 `t('a.b')` / `tm('a.b')` 的键，必须在 zh 树里存在。

实现说明：locale 文件是纯对象字面量（只有 `key: '字符串'` / `key: { … }` /
`key: [ 字符串 ]`），故用一个字符级扫描器解析，正确处理字符串内的引号、
冒号、花括号与注释。纯静态、无 node 依赖、无网络。
"""
from __future__ import annotations
import re
import unittest
from pathlib import Path

# 仓库根（frontend/ 与 backend/ 的父目录）；测试已随后端收进 backend/tests。
ROOT = Path(__file__).resolve().parents[3]
SRC = ROOT / "frontend" / "src"
LOCALES = SRC / "locales"
LANGS = ("zh", "en")

# 防空阈值：解析器一旦失效会把键集算空，进而"对称且都能解析"地假通过
MIN_TREE_KEYS = 1000
MIN_LEAF_FILES = 20
MIN_USED_KEYS = 800

_QUOTES = "'\"`"


def _skip_string(text: str, i: int) -> int:
    """text[i] 是引号，返回闭合引号之后的下标。"""
    quote = text[i]
    i += 1
    n = len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == quote:
            return i + 1
        i += 1
    return n


def _strip_comments(text: str) -> str:
    out: list[str] = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in _QUOTES:
            j = _skip_string(text, i)
            out.append(text[i:j])
            i = j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _skip_group(text: str, i: int) -> int:
    """text[i] 是 '{' 或 '['，跳过整个配对组，返回其后的下标。"""
    opener = text[i]
    closer = "}" if opener == "{" else "]"
    depth = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c in _QUOTES:
            i = _skip_string(text, i)
            continue
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _object_keys(text: str, i: int) -> tuple[set[str], int]:
    """解析 text[i] == '{' 的对象，返回 (点分键路径集合, 结束下标)。"""
    keys: set[str] = set()
    n = len(text)
    i += 1
    while i < n:
        while i < n and text[i] in " \t\r\n,":
            i += 1
        if i >= n or text[i] == "}":
            return keys, i + 1
        if text[i] in _QUOTES:
            j = _skip_string(text, i)
            key = text[i + 1:j - 1]
            i = j
        else:
            m = re.match(r"[A-Za-z_$][\w$]*", text[i:])
            if not m:
                i += 1
                continue
            key = m.group(0)
            i += len(key)
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n or text[i] != ":":
            continue
        i += 1
        while i < n and text[i] in " \t\r\n":
            i += 1
        if i >= n:
            return keys, i
        if text[i] == "{":
            sub, i = _object_keys(text, i)
            keys.add(key)
            keys.update(f"{key}.{s}" for s in sub)
        elif text[i] == "[":
            keys.add(key)
            i = _skip_group(text, i)
        else:
            keys.add(key)
            if text[i] in _QUOTES:
                i = _skip_string(text, i)
            else:
                while i < n and text[i] not in ",\n}":
                    i += 1
    return keys, i


def _leaf_keys(path: Path) -> set[str]:
    """取该 locale 文件里导出的那个对象的键路径集合。"""
    text = _strip_comments(path.read_text(encoding="utf-8"))
    m = re.search(r"export\s+const\s+\w+\s*=\s*\{", text)
    if not m:
        raise AssertionError(f"{path} 里找不到 `export const X = {{`")
    brace = text.index("{", m.start())
    keys, _ = _object_keys(text, brace)
    return keys


def _resolve_import(base: Path, rel: str) -> Path | None:
    """'./dash' → dash.ts 或 dash/index.ts。"""
    for cand in (base / f"{rel}.ts", base / rel / "index.ts"):
        if cand.exists():
            return cand
    return None


def _compose(index_file: Path, prefix: str, out: set[str]) -> None:
    """按 index.ts 的组装关系展开键空间（叶子文件按 prefix 加前缀）。"""
    raw = index_file.read_text(encoding="utf-8")
    text = _strip_comments(raw)
    base = index_file.parent

    imports: dict[str, Path] = {}
    for m in re.finditer(r"import\s*\{([^}]+)\}\s*from\s*'(\.[^']+)'", text):
        for part in m.group(1).split(","):
            var = part.strip().split(" as ")[-1].strip()
            target = _resolve_import(base, m.group(2))
            if var and target:
                imports[var] = target

    body = text[text.index("= {"):]
    # ...spread → 同级合并（用 var 指向的模块，前缀不变）
    for var in re.findall(r"\.\.\.(\w+)", body):
        target = imports.get(var)
        if target is None:
            continue
        if target.name == "index.ts":
            _compose(target, prefix, out)
        else:
            out.update(f"{prefix}.{k}" if prefix else k for k in _leaf_keys(target))
    # key: Var → 加一层前缀
    for key, var in re.findall(r"(\w+)\s*:\s*(\w+)\s*,", body):
        target = imports.get(var)
        if target is None:
            continue
        sub = f"{prefix}.{key}" if prefix else key
        if target.name == "index.ts":
            _compose(target, sub, out)
        else:
            out.update(f"{sub}.{k}" for k in _leaf_keys(target))


def _tree(lang: str) -> set[str]:
    out: set[str] = set()
    _compose(LOCALES / lang / "index.ts", "", out)
    return out


def _leaf_files(lang: str) -> dict[str, Path]:
    return {
        str(p.relative_to(LOCALES / lang)): p
        for p in (LOCALES / lang).rglob("*.ts")
        if p.name != "index.ts"
    }


def _used_keys() -> set[str]:
    used: set[str] = set()
    for path in SRC.rglob("*"):
        if not path.is_file() or path.suffix not in (".vue", ".ts"):
            continue
        if LOCALES in path.parents:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for m in re.finditer(r"\b(?:t|tm)\(\s*['\"]([A-Za-z0-9_.]+)['\"]", text):
            used.add(m.group(1))
    return used


class I18nParityTests(unittest.TestCase):
    def test_parser_sanity(self):
        """防空自检：解析失效必须响亮失败，不能"对称且都能解析"地假通过。"""
        for lang in LANGS:
            tree = _tree(lang)
            self.assertGreater(len(tree), MIN_TREE_KEYS, f"{lang} 键位仅 {len(tree)}，疑似解析失败")
            leaves = _leaf_files(lang)
            self.assertGreater(len(leaves), MIN_LEAF_FILES, f"{lang} 叶子文件仅 {len(leaves)}")
        self.assertGreater(len(_used_keys()), MIN_USED_KEYS, "源码里静态 t() 键位过少，疑似扫描失败")

    def test_zh_and_en_key_sets_are_identical(self):
        zh, en = _tree("zh"), _tree("en")
        only_zh = sorted(zh - en)
        only_en = sorted(en - zh)
        self.assertEqual(
            (only_zh, only_en),
            ([], []),
            "中英键位不对称（D1 那类「单侧键位错位」就是由此产生）：\n"
            f"  仅 zh 有: {only_zh[:10]}\n  仅 en 有: {only_en[:10]}",
        )

    def test_each_locale_file_is_structurally_symmetric(self):
        zh_files = _leaf_files("zh")
        en_files = _leaf_files("en")
        self.assertEqual(
            sorted(zh_files), sorted(en_files),
            "中英 locale 文件清单不一致（有一侧缺文件或多文件）",
        )
        problems: list[str] = []
        for rel, zh_path in sorted(zh_files.items()):
            zh_keys = _leaf_keys(zh_path)
            en_keys = _leaf_keys(en_files[rel])
            only_zh = sorted(zh_keys - en_keys)
            only_en = sorted(en_keys - zh_keys)
            if only_zh or only_en:
                problems.append(f"  {rel}: 仅 zh {only_zh[:5]} / 仅 en {only_en[:5]}")
        self.assertEqual(
            problems, [],
            "同名 locale 文件的中英键结构不一致：\n" + "\n".join(problems),
        )

    def test_every_static_key_used_in_code_resolves(self):
        zh = _tree("zh")
        missing = sorted(k for k in _used_keys() if k not in zh)
        self.assertEqual(
            missing, [],
            "代码里用到的英文键位在 zh 树中不存在 —— useI18n 的 t() 缺键时会**渲染出"
            "裸键名**（用户在界面上看到 a.b.c），必须补齐：\n  " + "\n  ".join(missing[:20]),
        )

    def test_every_used_key_is_a_leaf_value(self):
        """`t()` 取到**分支**键同样会渲染出裸键名（批 44 实测）。

        `_tree()` 返回的路径里既有叶子也有分支，所以"键位存在"并不能保证 `t()` 拿到字符串：
        `t('dash.news.source')` 在树上**存在**（那是个对象），运行时却渲染成
        `aria-label="dash.news.source"` —— 静态闸放行、界面上露键名。
        这条把判据收紧到"用到必须是叶子"。
        """
        zh = _tree("zh")
        branches = {k.rsplit(".", 1)[0] for k in zh if "." in k}
        leaves = zh - branches
        object_keys = sorted(k for k in _used_keys() if k in zh and k not in leaves)
        self.assertEqual(
            object_keys, [],
            "代码里 t() 取到的是**对象（分支）键**，运行时会渲染出裸键名，请改取叶子：\n  "
            + "\n  ".join(object_keys[:20]),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
