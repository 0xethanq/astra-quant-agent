/**
 * 焦点指示器与图层层级闸（批 47）。
 *
 * ## 守什么
 *
 * 1. **不可见焦点（Invisible Focus）漏洞防护**：
 *    实测发现 `FactorMatrix.vue` 的搜索输入框和 `LedgerView.vue` 的 3 个下拉筛选框
 *    同时写了 `outline-none` 和内联 `style="border-color: var(--line-1)"`。
 *    因为内联样式优先级高于所有 Tailwind 工具类（`focus:border-...` 无效），
 *    导致键盘 Tab 聚焦时既没有 outline 也没有 border/shadow 变化，
 *    有视力障碍的键盘操作者完全不知道焦点落在哪里。
 *    规则：禁止表单控件在使用 `outline-none` 时直接在 style 写死 `border-color`，
 *    必须配齐 `focus:border-...` 与 `focus:ring-...` 或由 `.focus-ring` 包裹。
 *
 * 2. **z-index 令牌体系对齐**：
 *    全站令牌系统（`tokens.css`）定义了 5 级层级：
 *    --z-header: 40, --z-float: 50, --z-drawer: 60, --z-dialog: 70, --z-toast: 80。
 *    浮动条（.rk-savebar）必须使用 `--z-float`；
 *    全屏模态弹窗（如 DocsView 的图片放大）属于 dialog 级，必须使用 `var(--z-dialog)`，
 *    严禁写死 `z-50` 导致被同层抽屉遮挡或层级颠倒。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

const stripComments = (t) => t.replace(/<!--[\s\S]*?-->/g, '');

test('表单控件不能在写死内联 border-color 的同时 outline-none（否则焦点完全不可见）', () => {
  const bad = [];
  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const content = stripComments(readFileSync(file, 'utf8'));
    const templateMatch = content.match(/<template>([\s\S]*)<\/template>/);
    if (!templateMatch) continue;
    const body = templateMatch[1];

    for (const m of body.matchAll(/<(input|select|textarea)\b([^>]*)>/g)) {
      const tag = m[1];
      const attrs = m[2];
      // 检查是否同时有 outline-none 和内联 style 中的 border-color
      const hasOutlineNone = attrs.includes('outline-none');
      const hasInlineBorderColor = /style="[^"]*border-color\s*:[^"]*"/.test(attrs);
      if (hasOutlineNone && hasInlineBorderColor) {
        bad.push(`${rel} <${tag}> 同时写了 outline-none 和内联 border-color，导致聚焦反馈被抑制`);
      }
    }
  }

  assert.deepEqual(bad, [], `发现失去焦点反馈的控件：\n  ${bad.join('\n  ')}`);
});

test('DocsView 弹层必须对齐 z-index 令牌', () => {
  const docsText = readFileSync(path.join(SRC, 'views/docs/DocsView.vue'), 'utf8');
  assert.match(
    docsText,
    /z-\[var\(--z-dialog\)\]/,
    'DocsView 图片放大模态弹窗未对齐 --z-dialog (70)'
  );
});

test('闸自检：判据能有效命中违规写法', () => {
  const badAttrs = 'class="outline-none" style="border-color: var(--line-1)"';
  const goodAttrs = 'class="outline-none border-[var(--line-1)] focus:ring-1" style="color: var(--ink-1)"';

  const checkBad = badAttrs.includes('outline-none') && /style="[^"]*border-color\s*:[^"]*"/.test(badAttrs);
  const checkGood = goodAttrs.includes('outline-none') && /style="[^"]*border-color\s*:[^"]*"/.test(goodAttrs);

  assert.equal(checkBad, true, '应识别违规控件');
  assert.equal(checkGood, false, '合规控件不应误报');
});
