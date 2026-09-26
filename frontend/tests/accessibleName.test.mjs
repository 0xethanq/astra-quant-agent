/**
 * 可访问名判据（批 98）。
 *
 * ## 起因：全站审计里唯一非零的那一格
 *
 * 项目自带的 `plan_local/audit-tools/a11y-audit.js`（25 路由）报出
 * **「无可访问名: 6」** —— 这是我接手以来第一次看到该类非零。6 处全是同一个东西：
 *
 * ```html
 * <RouterLink to="/">                     <!-- DashboardLayout.vue:133 -->
 *   <img src="/favicon.svg" alt="" ... />  <!-- 空 alt = 明确声明「装饰性」 -->
 *   <div v-if="!navCompact">…字标…</div>   <!-- 折叠态整个不渲染 -->
 * </RouterLink>
 * ```
 *
 * **折叠态下字标不渲染，链接里只剩一个声明为装饰性的图标 → 链接没有名字。**
 * 批 43 把 `<div @click>` 改成真 `<RouterLink>` 时的初衷
 * （「屏幕阅读器也知道它是链接」）在折叠态其实落空了。
 * 修法：`:aria-label="t('brand.name')"` —— 展开态可访问名**恰好等于可见字标**，
 * 满足 WCAG 2.5.3（Label in Name）；未新造 i18n 键。
 *
 * ## ⚠️ 探针本身也被修了（工具 bug 4，已写进工具文件头）
 *
 * 旧规则只读 `textContent`，会把 `<a><img alt="ASTRA 首页"></a>` 判成无名 ——
 * 而 `img[alt]` 是**合法**的名字来源。正确的简化 accname 顺序：
 * `aria-labelledby` → `aria-label` → 后代 `img[alt]` / `svg > title` → 文本。
 * **但 `alt=""` 不算名字**（它就是「别读我」的声明）。
 *
 * 仪器自检：修好后 25 路由 / 11,638 元素 / **0 无名**；
 * 在浏览器里把那个 `aria-label` 属性删掉 → 立刻检出 **1** 处（阳性可检）。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

function walk(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

/** 取 `<template>` 内容并剥掉 HTML 注释 / Vue 注释。 */
function templateOf(raw) {
  const m = /<template>([\s\S]*)<\/template>/.exec(raw);
  if (!m) return '';
  return m[1].replace(/<!--[\s\S]*?-->/g, '').replace(/<!---->/g, '');
}

/** 找成对标签的内部内容（含嵌套同名标签的深度处理）。 */
export function innerOf(text, tag, from = 0) {
  const open = new RegExp(`<${tag}\\b`, 'g');
  open.lastIndex = from;
  const om = open.exec(text);
  if (!om) return null;
  // 找到起始标签的 `>`
  let i = om.index, depth = 0, start = -1;
  const scanner = new RegExp(`<${tag}\\b|</${tag}>`, 'g');
  scanner.lastIndex = om.index;
  let sm;
  while ((sm = scanner.exec(text))) {
    if (sm[0].startsWith('</')) {
      depth--;
      if (depth === 0) return { openStart: om.index, openEnd: start + 1, innerEnd: sm.index, closeEnd: sm.index + sm[0].length, inner: text.slice(start + 1, sm.index) };
    } else {
      depth++;
      if (depth === 1) {
        const gt = text.indexOf('>', sm.index);
        start = gt;
      }
    }
  }
  return null;
}

/** 一个元素的可访问名是否可能为空（简化 accname，静态版）。 */
export function nameInfo(tagText, inner) {
  const hasLabelAttr = /\b(aria-label|aria-labelledby|title)\s*=|\B:(aria-label|aria-labelledby|title)\s*=/.test(tagText);
  if (hasLabelAttr) return { named: true, why: 'aria-label/title' };
  // 文本内容（去掉所有标签）
  const text = inner.replace(/<[^>]*>/g, '').replace(/\{\{[\s\S]*?\}\}/g, 'X').trim();
  if (text) return { named: true, why: '文本' };
  // 有插值的属性绑定（:alt 等）——静态无法判定，放过
  if (/<img[^>]*\s:alt\s*=/.test(inner)) return { named: true, why: '动态 alt' };
  // <slot>：名字由**调用方**的插槽内容提供（BaseCollapse 的 head 槽就是按钮文字），
  // 静态看不到，必须放过，否则会把组件误判成无名控件
  if (/<slot\b/.test(inner)) return { named: true, why: '插槽内容' };
  // 动态组件同理
  if (/<component\b[^>]*\s:is\s*=/.test(inner)) return { named: true, why: '动态组件' };
  const imgs = [...inner.matchAll(/<img\b[^>]*>/g)].map((m) => m[0]);
  const meaningfulAlt = imgs.some((t) => {
    const m = /\balt\s*=\s*"([^"]*)"/.exec(t);
    return m ? m[1].trim().length > 0 : false;   // alt="" 是装饰，不算名字
  });
  if (meaningfulAlt) return { named: true, why: 'img[alt]' };
  if (/<svg\b[^>]*>[\s\S]*?<title>/.test(inner)) return { named: true, why: 'svg>title' };
  if (/aria-label\s*=/.test(inner)) return { named: true, why: '后代 aria-label' };
  return { named: false, why: imgs.length ? '只有装饰性图标' : '空内容' };
}

/** 扫描所有 .vue，返回可能的「无名交互元素」。 */
export function namelessControls() {
  const bad = [];
  for (const f of walk(SRC)) {
    if (!f.endsWith('.vue')) continue;
    const tpl = templateOf(readFileSync(f, 'utf8'));
    if (!tpl) continue;
    const rel = path.relative(SRC, f);
    for (const tag of ['RouterLink', 'a', 'button']) {
      let from = 0, hit;
      while ((hit = innerOf(tpl, tag, from))) {
        from = hit.closeEnd;
        const tagText = tpl.slice(hit.openStart, hit.openEnd);
        const info = nameInfo(tagText, hit.inner);
        if (!info.named) {
          bad.push({ file: rel, tag, why: info.why, snippet: tagText.replace(/\s+/g, ' ').slice(0, 70) });
        }
      }
    }
  }
  return bad;
}

test('交互元素（链接/按钮）不得没有可访问名（批 98 回归）', () => {
  const bad = namelessControls();
  const list = bad.map((b) => `${b.file}  <${b.tag}> ${b.why}  ${b.snippet}`);
  assert.deepEqual(
    list,
    [],
    '这些交互元素算不出可访问名（WCAG 4.1.2 / 2.4.4）—— 补 aria-label，' +
      `或让内容含真实文本 / img[alt]（注意 alt="" 是装饰性，不算名字）：\n  ${list.join('\n  ')}`,
  );
});

test('DashboardLayout 品牌链接必须带 aria-label（本次修的那一处）', () => {
  const s = readFileSync(path.join(SRC, 'layouts', 'DashboardLayout.vue'), 'utf8');
  const hit = innerOf(templateOf(s), 'RouterLink');
  assert.ok(hit, '找不到品牌区 RouterLink');
  const tagText = templateOf(s).slice(hit.openStart, hit.openEnd);
  assert.match(tagText, /:aria-label="t\('brand\.name'\)"/, '品牌链接的 aria-label 不见了');
  assert.ok(/v-if="!navCompact"/.test(hit.inner), '字标不再受 navCompact 控制 —— 请复核本判据的前提');
});

test('判据自检：accname 的几种来源与 alt="" 的例外', () => {
  const 有文本 = nameInfo('<a class="x">', '<span>首页</span>');
  assert.equal(有文本.named, true);
  const 只有装饰图标 = nameInfo('<a to="/" class="x">', '<img src="/f.svg" alt="" class="h-6 w-6" />');
  assert.equal(只有装饰图标.named, false, 'alt="" 的图标不该算名字');
  const 有实义alt = nameInfo('<a href="/x">', '<img src="/f.svg" alt="首页" />');
  assert.equal(有实义alt.named, true, 'img[alt] 是合法名字来源');
  const 有aria = nameInfo('<a to="/" :aria-label="t(\'brand.name\')">', '<img src="/f.svg" alt="" />');
  assert.equal(有aria.named, true);
  const 动态alt = nameInfo('<a href="/x">', '<img :alt="label" src="/f.svg" />');
  assert.equal(动态alt.named, true, '动态 alt 静态无法判定，应放过');
  const svg标题 = nameInfo('<button class="x">', '<svg><title>关闭</title><path /></svg>');
  assert.equal(svg标题.named, true);
});
