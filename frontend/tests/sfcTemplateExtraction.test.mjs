/**
 * 模板块提取守卫闸（批 113）。
 *
 * ## 为什么要单独守这一条
 *
 * 本仓约 20 个判据都用同一个写法取 SFC 的模板块：
 * ```js
 * const m = raw.match(/<template>([\s\S]*)<\/template>/);
 * ```
 * 这是**贪婪**匹配，起点是文件里**第一个**裸 `<template>`。只要 `<script>`/`<style>`
 * 区域（含注释、含示例字符串）里出现一个裸 `<template>`，匹配就会**从那里开始**，
 * 判据从此看的是注释文字而不是模板 —— **静默失效，不报错**。
 *
 * 批 113 实测踩到：新组件的头注里写了裸的 template 开标签，
 * `hardcodedChineseUiText` 当场把注释里的中文当成"模板硬编码中文"报了出来。
 * 全仓扫下来，真正会劫持的只有这一个文件（`DataTable.vue` / `LlmPage.vue` 里那几处
 * 都带属性或位于根模板块之后，不会改变匹配区间）。
 *
 * 结论：不改 20 个判据（改动面大且当前无误报），而是**守住写法约定**：
 *   · 根模板块**之前**不得有裸的 `<template>`（会劫持匹配起点）
 *   · 根模板块**之后**不得有裸的 `</template>`（会把匹配终点推后）
 * 带属性的写法（`<template v-if>`、`<template #head>`）不受影响，可以照写。
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

/**
 * 导出以便自检：直接对比「判据实际抓到的模板块」与「按深度配平得到的根模板块」。
 * 两者不一致 = 抓错了地方（这才是那些判据真正的失效方式，比检查标签位置更忠实）。
 */
export function extractionHijacked(raw) {
  const src = raw.replace(/\r\n/g, '\n');
  const naive = src.match(/<template>([\s\S]*)<\/template>/);
  const root = balancedRoot(src);
  if (!naive || !root) return null;
  if (naive[1] === root.inner) return null;
  return {
    裸匹配起始行: src.slice(0, naive.index).split('\n').length,
    根模块起始行: src.slice(0, root.start).split('\n').length,
    裸匹配多出的开头: naive[1].slice(0, 40).replace(/\n/g, ' '),
  };
}

/** 按标签深度配平找根模板块（`<template v-if>` / `<template #slot>` 都算一层）。 */
function balancedRoot(raw) {
  const rm = raw.match(/^<template>\s*$/m);
  if (!rm) return null;
  const start = rm.index + rm[0].length;
  const re = /<template[\s>]|<\/template>/g;
  re.lastIndex = start;
  let depth = 1;
  let m;
  while ((m = re.exec(raw))) {
    if (m[0].startsWith('</')) {
      depth -= 1;
      if (depth === 0) return { start, inner: raw.slice(start, m.index) };
    } else depth += 1;
  }
  return null;
}

test('根模板块之外不得出现裸 template 标签（会劫持约 20 个判据的贪婪正则）', () => {
  const bad = [];
  for (const p of vueFiles(SRC)) {
    const raw = readFileSync(p, 'utf8');
    if (extractionHijacked(raw)) bad.push(path.relative(SRC, p) + '  ' + JSON.stringify(extractionHijacked(raw)));
  }
  assert.deepEqual(bad, [], '这些文件的脚本/样式区里有裸的 template 标签，会让判据看错地方：\n  ' + bad.join('\n  '));
});

test('判据自检：带属性的写法不受影响，裸的必须被抓到', () => {
  const clean = '<script>\n * 例子：<template #head><th/></template>\n</script>\n\n<template>\n  <div/>\n</template>\n';
  assert.equal(extractionHijacked(clean), null, '带属性的写法被误报了（它本来不该影响匹配）');
  const bare = '<script>\n * 例子：<template> 不能挂 ARIA\n</script>\n\n<template>\n  <div/>\n</template>\n';
  assert.ok(extractionHijacked(bare), '脚本区里裸的开标签没被抓到');
  const nested = '<template>\n  <div>\n    <template v-if="a"><i/></template>\n  </div>\n</template>\n';
  assert.equal(extractionHijacked(nested), null, '正常的嵌套 <template v-if> 被误报了');
});

test('加固后的提取方式仍能取到真正的模板块（非空、且不含注释文字）', () => {
  const raw = readFileSync(path.join(SRC, 'components/base/BaseLoadingAnnounce.vue'), 'utf8');
  const sfcOnly = raw.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<style[\s\S]*?<\/style>/g, '');
  const m = sfcOnly.match(/<template>([\s\S]*)<\/template>/);
  assert.ok(m, '取不到模板块');
  assert.match(m[1], /role="status"/, '取到的不是真模板');
  assert.ok(!/为什么/.test(m[1]), '把注释文字也当成模板了');
});
