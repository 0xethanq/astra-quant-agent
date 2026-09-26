"""`frontend/src/views/admin/promptStudioLogic.ts`（阶段 4·B3 第三十五刀）回归。

## 抽了什么

`PromptStudioPage.vue` 的 script setup（357 行）里六段**纯函数**：

| 函数 | 决定什么 |
|---|---|
| `renderSourceBadge` | 模块来源徽标（base/legacy/custom，**其它一律 `null`**） |
| `cloneModulesForEditing` | 载入编辑区：**深拷贝 + 全量解锁** |
| `compileWorkingModules` | 编译「渲染后 Prompt」 |
| `buildTemplatePreview` | 编译「模板视图」（**另一种排版**） |
| `computeInsertTarget` | 一键插变量时**双向钳制**下标 |
| `appendVariableSlot` | 插槽去重与追加（空内容不加前导换行） |
| `deriveImportName` | 从文件名推默认方案名 |

## 为什么值得单测

这是**提示词编译**：`compileWorkingModules` 的输出就是**实际发给主脑的文本**。
排版差一个换行、或把两种预览合并，都不会报错 —— 只会让实盘用的提示词静默变形。

而 `PromptStudioPage` **此前没有任何单测**。

## ⚠️ 两种预览**排版不同**，这是最容易被"顺手统一"改错的地方

- 渲染视图：各模块 `content` trim 后 `\n\n` 连接（**无模块标题**）；
- 模板视图：每块包 `======================= 【标题】 =======================`。

本测试**分别**钉住两种排版，并有一条断言专门证明"两者输出不相等"。

## 测试手段

与 `test_frontend_security_logic.py` 同法：用 `node --experimental-strip-types`
**直接执行那个 `.ts`** 当 oracle，与 Python 侧的手写规则比对。
写死期望值只会把我"以为的语义"抄一遍，实现改了测试仍绿。

离线套件下**在 spawn 之前**跳过（见 `tests/offline_suite.py` 的
`OFFLINE_SUITE_RUNNING` 标记）；不依赖 node 的规则断言**始终执行**。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "frontend" / "src" / "views" / "admin" / "promptStudioLogic.ts"
PAGE = ROOT / "frontend" / "src" / "views" / "admin" / "PromptStudioPage.vue"

NODE = shutil.which("node")

_PROBE_JS = r"""
const t = (p) => p;
const M = (over) => ({ title: 'T', content: 'C', enabled: true, ...over });
const out = {};
try {
  out.badge = [
    m.renderSourceBadge({source:'base'}, t),
    m.renderSourceBadge({source:'legacy'}, t),
    m.renderSourceBadge({source:'custom'}, t),
    m.renderSourceBadge({source:'other'}, t),
    m.renderSourceBadge({}, t),
    m.renderSourceBadge(null, t),
  ];
  out.clone = [
    m.cloneModulesForEditing([{title:'A', content:'x', locked:true, source:'base'}]),
    m.cloneModulesForEditing(null),
    m.cloneModulesForEditing(undefined),
    m.cloneModulesForEditing('nope'),
    m.cloneModulesForEditing({}),
    m.cloneModulesForEditing([]),
  ];
  out.compile = [
    m.compileWorkingModules([M({title:'A',content:'  a1  '}), M({title:'B',content:'b1'})]),
    m.compileWorkingModules([M({title:'A',content:'a'}), M({title:'B',content:'',enabled:true})]),
    m.compileWorkingModules([M({title:'A',content:'a'}), M({title:'B',content:'b',enabled:false})]),
    m.compileWorkingModules([M({title:'A',content:'   '})]),
    m.compileWorkingModules([]),
    m.compileWorkingModules(null),
    m.compileWorkingModules([M({title:'A',content:'a',enabled:undefined})]),
  ];
  out.template = [
    m.buildTemplatePreview([M({title:'甲',content:'  x  '})]),
    m.buildTemplatePreview([M({title:'甲',content:'x'}), M({title:'乙',content:'y'})]),
    m.buildTemplatePreview([M({title:'甲',content:''})]),
    m.buildTemplatePreview([]),
    m.buildTemplatePreview(null),
  ];
  out.insertTarget = [
    m.computeInsertTarget([M({}),M({}),M({})], 0),
    m.computeInsertTarget([M({}),M({}),M({})], 2),
    m.computeInsertTarget([M({}),M({}),M({})], 5),
    m.computeInsertTarget([M({}),M({}),M({})], -3),
    m.computeInsertTarget([M({})], 0),
    m.computeInsertTarget([], 0),
    m.computeInsertTarget(null, 0),
  ];
  out.appendSlot = [
    m.appendVariableSlot('abc', 'K'),
    m.appendVariableSlot('  abc  ', 'K'),
    m.appendVariableSlot('', 'K'),
    m.appendVariableSlot(null, 'K'),
    m.appendVariableSlot(undefined, 'K'),
    m.appendVariableSlot('has {{K}} inside', 'K'),
    m.appendVariableSlot('x{{KK}}y', 'K'),
  ];
  out.importName = [
    m.deriveImportName('astra-strategy-alpha.json'),
    m.deriveImportName('alpha.JSON'),
    m.deriveImportName('alpha.json'),
    m.deriveImportName('astra-strategy-我的方案.json'),
    m.deriveImportName(''),
    m.deriveImportName(null),
    m.deriveImportName('a.json.json'),
    m.deriveImportName('astra-strategy-.json'),
  ];
  process.stdout.write(JSON.stringify(out));
} catch (e) {
  process.stderr.write('PROBE_ERR ' + e.message);
  process.exit(3);
}
"""


def _run_probe():
    if not NODE:
        return None, "找不到 node"
    script = ("import('" + MODULE.as_uri() + "').then(m => {" + _PROBE_JS + "})."
              "catch(e => { process.stderr.write('IMPORT_ERR ' + e.message); process.exit(4); });")
    try:
        proc = subprocess.run(
            [NODE, "--experimental-strip-types", "--input-type=module", "-e", script],
            capture_output=True, text=True, timeout=90, cwd=str(ROOT))
    except (OSError, subprocess.SubprocessError) as exc:
        return None, f"node 执行失败: {exc}"
    if proc.returncode != 0:
        err = (proc.stderr or "").strip().splitlines()
        return None, f"node 退出码 {proc.returncode}: {err[-1] if err else '无 stderr'}"
    try:
        return json.loads(proc.stdout), None
    except json.JSONDecodeError as exc:
        return None, f"node 输出不是 JSON: {exc}"


_CACHE: dict = {}


def _probe():
    if not _CACHE:
        data, why = _run_probe()
        _CACHE["data"] = data
        _CACHE["why"] = why
    return _CACHE["data"], _CACHE["why"]


def _guard_offline(case: unittest.TestCase) -> None:
    """离线套件下跳过（**必须在 spawn 之前**）。

    判据是 `tests/offline_suite.py::main` 显式设的 `OFFLINE_SUITE_RUNNING`
    —— 它在装 audit hook 之前就设好，所以这里一定来得及。

    教训（上一刀，§44.4）：把跳过判定写在 `setUp`、而 spawn 在 `setUpClass`，
    等于**没跳过** —— 副作用已经发生了。
    """
    if os.environ.get("OFFLINE_SUITE_RUNNING"):
        # ⚠️ 必须 `raise`，不能 `case.skipTest(...)`：
        # `setUpClass` 收到的是**类**，`TestClass.skipTest(reason)` 会把 reason
        # 绑到 `self` 上 → `TypeError: missing 1 required positional argument: 'reason'`。
        # 我上一版正是这么写的，于是离线套件多出 1 个 ERROR（11 而不是 10）。
        # `raise unittest.SkipTest` 在 setUpClass 与 setUp 里**都**正确。
        raise unittest.SkipTest("离线套件禁用外部子进程（node 不在白名单）—— 见 tests/offline_suite.py")


def _fn_body(src: str, name: str) -> str:
    """取出函数体 —— 支持 `export function` 与**非导出**的 `function`。

    我第一版只匹配 `export function`，于是 `_activeModules`（模块私有辅助）
    直接 `AssertionError: 源码里找不到 export function _activeModules(`。
    `export ` 是可选的。
    """
    m = re.search(r"(?:export )?function " + re.escape(name) + r"\((.*?)\n\}", src, re.S)
    if not m:
        raise AssertionError(f"源码里找不到 function {name}(")
    return m.group(1)


# ------------------------------------------------------------- 源码事实


class SourceFactsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = MODULE.read_text(encoding="utf-8")

    def test_exports(self):
        for name in ("renderSourceBadge", "cloneModulesForEditing", "compileWorkingModules",
                     "buildTemplatePreview", "computeInsertTarget", "appendVariableSlot",
                     "deriveImportName"):
            self.assertIn(f"export function {name}(", self.src, name)

    def test_badge_returns_null_for_unknown(self):
        body = _fn_body(self.src, "renderSourceBadge")
        self.assertIn("return null", body, "未知来源必须返回 null")
        self.assertEqual(body.count("return {"), 3, "恰好三个已知来源")

    def test_clone_deep_copies_and_unlocks(self):
        body = _fn_body(self.src, "cloneModulesForEditing")
        self.assertIn("JSON.parse(JSON.stringify(", body, "必须深拷贝")
        self.assertIn("locked: false", body, "必须全量解锁")

    def test_two_previews_have_different_layout(self):
        """**核心**：渲染视图不含模块标题，模板视图含标题标头。"""
        comp = _fn_body(self.src, "compileWorkingModules")
        tpl = _fn_body(self.src, "buildTemplatePreview")
        self.assertNotIn("【", comp, "渲染视图不得带模块标题")
        self.assertIn("=======================", tpl, "模板视图必须带标头")
        self.assertIn("【", tpl)

    def test_both_filter_disabled_and_blank(self):
        for name in ("_activeModules",):
            body = _fn_body(self.src, name)
            self.assertIn("m.enabled", body)
            self.assertIn(".trim()", body)

    def test_insert_target_clamps_both_sides(self):
        body = _fn_body(self.src, "computeInsertTarget")
        self.assertIn("Math.max(0,", body, "必须钳下界")
        self.assertIn("Math.min(", body, "必须钳上界")
        self.assertIn("return null", body, "空列表返回 null")

    def test_append_slot_dedupes(self):
        body = _fn_body(self.src, "appendVariableSlot")
        self.assertIn("includes(tag)", body, "必须判重")
        self.assertIn("duplicate: true", body)

    def test_no_vue_or_network_dependency(self):
        self.assertNotIn("from 'vue'", self.src)
        self.assertNotIn("useApi", self.src)
        self.assertNotIn("fetch(", self.src)


class WiringTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = PAGE.read_text(encoding="utf-8")

    def test_page_imports_module(self):
        self.assertIn("from './promptStudioLogic'", self.page)

    def test_page_uses_helpers(self):
        for call in ("renderSourceBadge(", "cloneModulesForEditing(", "compileWorkingModules(",
                     "buildTemplatePreview(", "computeInsertTarget(", "appendVariableSlot(",
                     "deriveImportName("):
            self.assertIn(call, self.page, f"组件未使用 {call}")

    def test_page_no_longer_inlines_them(self):
        for gone in ("JSON.parse(JSON.stringify(views))",
                     "======================= 【",
                     "replace(/\\.json$/i"):
            self.assertNotIn(gone, self.page, f"组件仍保留内联实现 {gone!r}")


class InvariantRulesTest(unittest.TestCase):
    """不依赖 node，**始终执行**。"""

    def test_template_header_format_is_exact(self):
        """标头必须恰好是 23 个 `=` + 空格 + 【标题】 + 空格 + 23 个 `=`。"""
        src = MODULE.read_text(encoding="utf-8")
        body = _fn_body(src, "buildTemplatePreview")
        m = re.search(r"`(=+) 【\$\{m\.title\}】 (=+)", body)
        self.assertIsNotNone(m, "找不到标头模板")
        self.assertEqual(len(m.group(1)), 23, "左侧等号个数变了")
        self.assertEqual(len(m.group(2)), 23, "右侧等号个数变了")
        self.assertEqual(m.group(1), m.group(2), "两侧等号必须等长")

    def test_import_prefix_strip_is_case_sensitive_on_prefix_only(self):
        body = _fn_body(MODULE.read_text(encoding="utf-8"), "deriveImportName")
        self.assertIn(r"/\.json$/i", body, ".json 剥除大小写不敏感")
        self.assertNotIn(r"/^astra-strategy-/i", body,
                         "前缀 `astra-strategy-` 是**大小写敏感**的，不得悄悄加 i")


# --------------------------------------------------- node oracle 对表


class NodeOracleTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _guard_offline(cls)          # 先判，再决定 spawn
        cls.data, cls.why = _probe()
        if cls.data is None:
            raise unittest.SkipTest(f"拿不到 node oracle：{cls.why}（规则断言仍执行，本项未验证）")

    def test_source_badge(self):
        got = self.data["badge"]
        self.assertEqual(got[0], {"text": "admin.promptStudio.source.base", "tone": "base"})
        self.assertEqual(got[1], {"text": "admin.promptStudio.source.legacy", "tone": "legacy"})
        self.assertEqual(got[2], {"text": "admin.promptStudio.source.custom", "tone": "custom"})
        self.assertIsNone(got[3], "未知来源 'other' → null")
        self.assertIsNone(got[4], "缺少 source → null")
        self.assertIsNone(got[5], "null → null")

    def test_clone_for_editing(self):
        got = self.data["clone"]
        self.assertEqual(got[0], [{"title": "A", "content": "x", "locked": False, "source": "base"}],
                         "locked 必须被置 false，其它字段原样")
        for i, why in ((1, "null"), (2, "undefined"), (3, "字符串"), (4, "对象")):
            self.assertEqual(got[i], [], f"{why} 输入 → 空数组")
        self.assertEqual(got[5], [])

    def test_compile_working_modules(self):
        got = self.data["compile"]
        self.assertEqual(got[0], "a1\n\nb1", "各模块 trim 后空行连接，且**无标题**")
        self.assertEqual(got[1], "a", "空内容模块被过滤")
        self.assertEqual(got[2], "a", "enabled=false 被过滤")
        self.assertEqual(got[3], "", "全空白 → 空串")
        self.assertEqual(got[4], "")
        self.assertEqual(got[5], "", "null → 空串（不抛）")
        self.assertEqual(got[6], "", "enabled 缺省（undefined）视为**关闭** → 过滤")

    def test_build_template_preview(self):
        got = self.data["template"]
        header = "======================= 【"
        self.assertEqual(got[0], f"{header}甲】 =======================\nx")
        self.assertEqual(got[1], f"{header}甲】 =======================\nx\n\n{header}乙】 =======================\ny")
        self.assertEqual(got[2], "", "空内容模块被过滤 → 空串")
        self.assertEqual(got[3], "")
        self.assertEqual(got[4], "")

    def test_two_previews_differ(self):
        """同一个模块列表，两种预览输出**必须不同** —— 证明它们是两种排版。"""
        self.assertNotEqual(self.data["compile"][0], self.data["template"][0])

    def test_compute_insert_target(self):
        got = self.data["insertTarget"]
        self.assertEqual(got, [0, 2, 2, 0, 0, None, None],
                         "双向钳制；空/null → null（**不是 0**）")

    def test_append_variable_slot(self):
        got = self.data["appendSlot"]
        self.assertEqual(got[0], {"content": "abc\n\n{{K}}", "duplicate": False, "tag": "{{K}}"})
        self.assertEqual(got[1], {"content": "abc\n\n{{K}}", "duplicate": False, "tag": "{{K}}"},
                         "已有内容会 trim，故前后空白消失")
        self.assertEqual(got[2], {"content": "{{K}}", "duplicate": False, "tag": "{{K}}"},
                         "空内容**不加**前导换行")
        self.assertEqual(got[3], {"content": "{{K}}", "duplicate": False, "tag": "{{K}}"})
        self.assertEqual(got[4], {"content": "{{K}}", "duplicate": False, "tag": "{{K}}"})
        self.assertEqual(got[5], {"content": "has {{K}} inside", "duplicate": True, "tag": "{{K}}"},
                         "已含插槽 → duplicate，内容**原样**")
        # ⚠️ 我原本以为 `{{KK}}` **含** `{{K}}`（当成"子串重合"），据此写了
        # `duplicate: True` —— **错了**。实测 `'{{K}}' in 'x{{KK}}y'` 为 **False**：
        # tag 是 `{{K}}`，而串里对应位置是 `{{KK}` —— 第 4 个字符是 `K` 而不是 `}`，
        # 故**不匹配**，于是**追加**。我又在修正注释里写成"子串确实是"，
        # 一句话里错了两次，两次都靠实跑纠正。这是既有行为
        # （原实现同样是 `m.content.includes(tag)`），如实钉住。
        self.assertEqual(got[6], {"content": "x{{KK}}y\n\n{{K}}", "duplicate": False, "tag": "{{K}}"},
                         "`{{KK}}` 不包含 `{{K}}` → 判为未包含，故追加")

    def test_derive_import_name(self):
        got = self.data["importName"]
        self.assertEqual(got[0], "alpha", "剥前缀 + 剥 .json")
        self.assertEqual(got[1], "alpha", "扩展名剥除大小写不敏感")
        self.assertEqual(got[2], "alpha")
        self.assertEqual(got[3], "我的方案", "中文名原样保留")
        self.assertEqual(got[4], "")
        self.assertEqual(got[5], "")
        self.assertEqual(got[6], "a.json", "只剥最后一个 .json")
        self.assertEqual(got[7], "", "前缀剥除后为空")

    def test_probe_keys_covered(self):
        self.assertEqual(set(self.data),
                         {"badge", "clone", "compile", "template", "insertTarget",
                          "appendSlot", "importName"})


if __name__ == "__main__":
    unittest.main()
