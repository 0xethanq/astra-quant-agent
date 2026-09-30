/**
 * 运行单元页的前缀缓存可观测（2026-09-29）。
 *
 * ## 为什么需要这道门
 *
 * 事故是"**永远显示 0 缓存**"却没人能判断真假：上游 `/chat/completions` 在没有命中时
 * 会把缓存字段**整段省略**，旧遥测把它与"上报为 0"一起印成「缓存: 0」。现在三态分开
 * （hit / miss / unreported），并且必须在面板上**看得见**，否则等于又回到不可判定。
 *
 * 本门钉三条：
 *   1. 模板里真的渲染三态文案（且用的是 i18n key，不是硬编码中文）；
 *   2. 四种状态都有对应的 i18n key，中英双语**键集合一致**；
 *   3. 表格列数与 CSS 网格列数一致（加列最容易只改一半，结果整行错位）。
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const PAGE = path.join(SRC, 'views', 'admin', 'AgentsPage.vue');
const ZH = path.join(SRC, 'locales', 'zh', 'admin', 'agents.ts');
const EN = path.join(SRC, 'locales', 'en', 'admin', 'agents.ts');

const page = readFileSync(PAGE, 'utf8');
const zh = readFileSync(ZH, 'utf8');
const en = readFileSync(EN, 'utf8');

const CACHE_KEYS = ['cacheHitRate', 'cacheHit', 'cacheMiss', 'cacheUnreported',
  'cacheHitTitle', 'cacheMissTitle', 'cacheUnreportedTitle'];

const keyDefs = (text) => new Set(
  [...text.matchAll(/^\s{2}([A-Za-z][A-Za-z0-9_]*):/gm)].map((m) => m[1]),
);

test('三态缓存文案必须在页面里被真正引用（含命中率 KPI）', () => {
  for (const key of ['cacheHit', 'cacheMiss', 'cacheUnreported', 'cacheHitRate']) {
    assert.ok(
      page.includes(`t('admin.agents.${key}')`),
      `AgentsPage 未引用 admin.agents.${key} —— 三态/命中率在界面上不可见`,
    );
  }
  for (const key of ['cacheHitTitle', 'cacheMissTitle', 'cacheUnreportedTitle']) {
    assert.ok(page.includes(`t('admin.agents.${key}', undefined, { n: c.cached_tokens ?? 0 })`)
      || page.includes(`t('admin.agents.${key}')`),
    `AgentsPage 未引用 admin.agents.${key} —— 悬停看不到"命中多少/为何不可判定"`);
  }
});

test('中文与英文的缓存键集合必须一致（缺一个就是某种语言下露出 key）', () => {
  const zhKeys = keyDefs(zh);
  const enKeys = keyDefs(en);
  for (const key of CACHE_KEYS) {
    assert.ok(zhKeys.has(key), `zh/admin/agents.ts 缺 ${key}`);
    assert.ok(enKeys.has(key), `en/admin/agents.ts 缺 ${key}`);
  }
});

test('表格列数与 CSS 网格列数必须对齐（加缓存列最容易只改一半）', () => {
  const row = page.match(/<div v-for="c in calls"[^>]*class="ag-call">([\s\S]*?)<\/div>/);
  assert.ok(row, '找不到调用流水行模板');
  const cells = [...row[1].matchAll(/<span\b/g)].length;
  const grid = page.match(/\.ag-call \{[\s\S]*?grid-template-columns:\s*([^;]+);/);
  assert.ok(grid, '找不到 .ag-call 的网格列定义');
  // 逐个匹配列规格（`minmax(...)` 内部含空格，不能按空白切分）
  const columns = [...grid[1].matchAll(/minmax\([^)]*\)|auto|[\d.]+(?:px|rem|fr|%)/g)].length;
  assert.equal(cells, columns,
    `行内有 ${cells} 个格子，网格只声明了 ${columns} 列 ⇒ 整行错位`);
});

test('缓存格必须带三态色调类，命中率 KPI 必须存在', () => {
  assert.match(page, /class="ag-call-cache"\s*:class="cacheTone\(c\)"/,
    '缓存格缺三态色调绑定');
  assert.match(page, /\.ag-call-cache\.is-up \{[^}]*color: var\(--up\)/,
    '命中的绿色态没定义');
  assert.match(page, /\.ag-call-cache\.is-warn \{[^}]*color: var\(--warn\)/,
    '未命中的琥珀态没定义');
  assert.match(page, /grid-template-columns:\s*repeat\(4, minmax\(0, 1fr\)\)/,
    '统计带必须放得下第 4 项（缓存命中率）');
});
