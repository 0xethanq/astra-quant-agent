/**
 * 「加载中」必须能播报 守卫闸（批 113）。
 *
 * ## 实测出来的缺口
 *
 * 全站 **18 个文件**渲染 `.skeleton` 骨架，但**只有 `DataGate` 会播报**
 * （它有可见的"正在加载"文案 + `aria-busy="true"`）。其余 17 个管理页首屏加载时
 * 只画骨架 —— 骨架是**空 div**，读屏器读到的就是"页头之后什么都没有"：
 * 用户既不知道在加载，也不知道内容何时到位。`RefreshCw`/`Loader2` 转圈只是视觉的。
 *
 * ## 修法
 *
 * 收敛成一个组件 `BaseLoadingAnnounce`（骨架容器多是 `<template v-if>`，
 * 而 `<template>` **挂不了 ARIA**），在 **28 个加载分支**各插一处。
 * 实机（延迟 API 定格加载态，`/admin/security`）：
 * ```
 * 骨架 6 个 ｜ [role="status"] 恰好 1 个，文本"加载中…"，盒子 1×1，position absolute
 * 布局 A/B：把这个 span 摘掉 → 骨架几何变化 0 项，容器高度 244 → 244（零布局影响）
 * 加载完成后：骨架 0 个，含"加载中"的状态区 0 个（不会误报）
 * ```
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

/** 豁免名单：这些文件自带等同的播报，不能再插（否则同一页播报两遍）。 */
const EXEMPT = {
  'components/dashboard/DataGate.vue': "自带可见的\"正在加载\"文案 + aria-busy=true",
};

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

const rel = (p) => path.relative(SRC, p).split(path.sep).join('/');

/** 找出每个播报点所在的最近 `v-if/v-else-if/v-else` 开启标签。导出以便自检。 */
export function announceAncestors(source) {
  const lines = source.split('\n');
  const out = [];
  for (let i = 0; i < lines.length; i += 1) {
    if (!lines[i].includes('BaseLoadingAnnounce />')) continue;
    for (let j = i - 1; j >= 0; j -= 1) {
      if (/^\s*<(template|div|section|span)\b[^>]*\b(v-if|v-else-if|v-else)\b/.test(lines[j])) {
        out.push({ line: i + 1, opener: lines[j].trim() });
        break;
      }
    }
  }
  return out;
}

test('凡是渲染骨架的页面都必须接上播报（DataGate 豁免）', () => {
  const missing = [];
  for (const p of vueFiles(SRC)) {
    const src = readFileSync(p, 'utf8');
    if (!src.includes('class="skeleton')) continue;
    const r = rel(p);
    if (EXEMPT[r]) continue;
    // ⚠️ 必须查**标签用法**而不是名字：变异 M75 证明，只删标签、留下 import，
    //    用 includes('BaseLoadingAnnounce') 判据仍然是绿的（import 里也有这个名字）。
    if (!/BaseLoadingAnnounce\s*\/>/.test(src)) missing.push(r);
  }
  assert.deepEqual(missing, [], '这些页的骨架没有播报，读屏用户只看到空白：\n  ' + missing.join('\n  '));
});

test('豁免名单不能烂掉：DataGate 必须仍有 aria-busy 与可见加载文案', () => {
  for (const r of Object.keys(EXEMPT)) {
    const src = readFileSync(path.join(SRC, r), 'utf8');
    assert.match(src, /aria-busy="true"/, r + ' 不再有 aria-busy，豁免理由不成立');
    assert.match(src, /gateLoading/, r + ' 不再有可见加载文案，豁免理由不成立');
    assert.ok(!/BaseLoadingAnnounce\s*\/>/.test(src), r + ' 既豁免又插了播报，会播报两遍');
  }
});

test('播报点必须落在 v-if 分支里（绝不能是 v-else —— 那样不加载时也会说"加载中"）', () => {
  const bad = [];
  let total = 0;
  for (const p of vueFiles(SRC)) {
    const src = readFileSync(p, 'utf8');
    if (!src.includes('BaseLoadingAnnounce />')) continue;
    for (const a of announceAncestors(src)) {
      total += 1;
      if (!a.opener.includes('v-if') || /v-else/.test(a.opener)) bad.push(rel(p) + ':' + a.line + '  ' + a.opener);
    }
  }
  assert.ok(total >= 10, '播报点只有 ' + total + ' 处，像是被删掉了');
  assert.deepEqual(bad, [], '播报点不在 v-if 加载分支里：\n  ' + bad.join('\n  '));
});

test('组件本身：sr-only + role=status + 取自 i18n，且注明豁免分工', () => {
  const src = readFileSync(path.join(SRC, 'components/base/BaseLoadingAnnounce.vue'), 'utf8');
  assert.match(src, /class="sr-only"/, '没有用 sr-only（会破坏页面视觉）');
  assert.match(src, /role="status"/, '没有 role=status，读屏不会播报');
  assert.match(src, /t\('common\.loading'\)/, '文案没走 i18n');
  assert.match(src, /DataGate/, '头注里没写清与 DataGate 的分工，后人容易插重复');
});

test('两种语言的加载文案都在', () => {
  for (const loc of ['zh', 'en']) {
    const src = readFileSync(path.join(SRC, 'locales', loc, 'common.ts'), 'utf8');
    assert.match(src, /loading:\s*'[^']+'/, loc + ' 缺少 common.loading');
  }
});

test('判据自检：v-else 里的播报要能被发现', () => {
  const okCase = '<template v-if="loading">\n  <BaseLoadingAnnounce />\n</template>';
  assert.equal(announceAncestors(okCase).length, 1);
  assert.ok(!/v-else/.test(announceAncestors(okCase)[0].opener));
  const badCase = '<div v-else>\n  <BaseLoadingAnnounce />\n</div>';
  assert.ok(/v-else/.test(announceAncestors(badCase)[0].opener), 'v-else 没被识别出来');
});
