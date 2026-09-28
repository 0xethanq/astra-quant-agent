/**
 * 下拉选择器可访问名称覆盖与卡片头部 HTML5 语义化守卫闸（批 64）。
 *
 * ## 守什么
 *
 * 1. **全站 <select> 下拉选择器 100% 可访问名称覆盖（WCAG 4.1.2 Name, Role, Value）**：
 *    全站模板中出现的所有 `<select>` 标签必须显式声明 `:aria-label` 或 `aria-label`。
 *    杜绝视障屏幕阅读器在遇到原生下拉菜单时仅报读裸 option 值而缺少控制项名称的问题。
 *
 * 2. **卡片头部语义化（HTML5 <header class="dsh-card-header">）**：
 *    全站所有声明了 `.dsh-card-header` 类名的卡片顶栏容器必须使用语义化 `<header>` 元素，
 *    严禁退化为无地标语义的普通 `<div>` 容器。
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

test('全站所有 <select> 元素必须显式声明 aria-label', () => {
  const badSelects = [];

  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const text = stripComments(readFileSync(file, 'utf8'));
    const tm = text.match(/<template>([\s\S]*)<\/template>/);
    if (!tm) continue;
    const body = tm[1];

    for (const m of body.matchAll(/<select\b([^>]*)>/g)) {
      const attrs = m[1];
      const hasLabel = attrs.includes('aria-label=') || attrs.includes(':aria-label=');
      if (!hasLabel) {
        const line = text.slice(0, tm.index).split('\n').length + body.slice(0, m.index).split('\n').length;
        badSelects.push(`${rel}:${line} <select> 缺少 aria-label 属性`);
      }
    }
  }

  assert.deepEqual(badSelects, [], `发现未提供 aria-label 的 <select> 控件：\n  ${badSelects.join('\n  ')}`);
});

test('所有 dsh-card-header 必须使用语义化 <header> 标签', () => {
  const badHeaders = [];

  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const text = stripComments(readFileSync(file, 'utf8'));
    const tm = text.match(/<template>([\s\S]*)<\/template>/);
    if (!tm) continue;
    const body = tm[1];

    for (const m of body.matchAll(/<([a-zA-Z][\w.-]*)\b([^>]*class="[^"]*dsh-card-header[^"]*"[^>]*)>/g)) {
      const tag = m[1].toLowerCase();
      if (tag !== 'header') {
        const line = text.slice(0, tm.index).split('\n').length + body.slice(0, m.index).split('\n').length;
        badHeaders.push(`${rel}:${line} <${tag} class="...dsh-card-header..."> 应使用 <header>`);
      }
    }
  }

  assert.deepEqual(badHeaders, [], `发现使用非 <header> 标签的卡片头部：\n  ${badHeaders.join('\n  ')}`);
});

test('LedgerView 筛选下拉菜单必须使用语义化筛选器名称（而非默认选项值）', () => {
  const vue = readFileSync(path.join(SRC, 'views/dashboard/LedgerView.vue'), 'utf8');
  assert.match(vue, /v-model="fMode"[^>]*:aria-label="t\('dash\.ledger\.filters\.mode'\)"/);
  assert.match(vue, /v-model="fInst"[^>]*:aria-label="t\('dash\.ledger\.filters\.symbol'\)"/);
  // 2026-10 全站收口 OKX：台账不再有场所筛选下拉（历史行仅只读降级展示）
  assert.doesNotMatch(vue, /fVenue/, '场所筛选下拉已移除，不得回潮');
});

test('闸自检：能准确拦截无 aria-label 的 select 与非 header 卡片头', () => {
  const badSel = '<select v-model="role"><option>admin</option></select>';
  const goodSel = '<select v-model="role" :aria-label="label"><option>admin</option></select>';
  const badHead = '<div class="dsh-card-header">Title</div>';
  const goodHead = '<header class="dsh-card-header">Title</header>';

  const checkSel = (html) => html.includes('<select') && !html.includes('aria-label=');
  const checkHead = (html) => html.includes('dsh-card-header') && !html.includes('<header');

  assert.equal(checkSel(badSel), true, '应拦截缺少 aria-label 的 select');
  assert.equal(checkSel(goodSel), false, '应放行合规 select');
  assert.equal(checkHead(badHead), true, '应拦截使用 div 的 card-header');
  assert.equal(checkHead(goodHead), false, '应放行使用 header 的 card-header');
});
