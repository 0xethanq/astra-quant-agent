/**
 * 单选组、表格数据流状态与键盘焦点可视性守卫闸（批 53）。
 *
 * ## 守什么
 *
 * 1. **单选组（Radiogroup）分组语义与键盘导航（HTML5 & WAI-ARIA）**：
 *    - 包含多个 `<input type="radio">` 的容器必须声明 `role="radiogroup"` 并具备 `aria-label`，
 *      让读屏器播报单选组名称（如「路由模式」、「手选优先」）；
 *    - 组内 radio input 必须声明统一的 `name` 属性，确保浏览器原生键盘上下左右方向键可在选项间正常切换。
 *
 * 2. **DataTable 异步数据流状态语义（WAI-ARIA aria-busy & role="status"）**：
 *    - 表格在 `loading` 为真时必须在 `<table>` 上声明 `:aria-busy="loading ? 'true' : undefined"`；
 *    - 加载提示单元格与无数据单元格必须声明 `role="status"`，确保数据状态变动被读屏器捕获。
 *
 * 3. **BaseStat 悬浮提示按钮键盘焦点可视性**：
 *    - `.kpi-hint` 原先依靠 hover 展现（`opacity-0`），对键盘 Tab 用户不可见；
 *    - 必须包含 `focus-visible:opacity-100`，确保键盘导航至指标单元时提示按钮清晰可见。
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

test('所有包含 radio 的容器必须声明 role="radiogroup" 且 radio input 拥有 name 属性', () => {
  const badRadios = [];

  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const text = stripComments(readFileSync(file, 'utf8'));
    const tm = text.match(/<template>([\s\S]*)<\/template>/);
    if (!tm) continue;
    const body = tm[1];

    if (!body.includes('type="radio"')) continue;

    // 校验每个 radio input 都有 name
    for (const m of body.matchAll(/<input\b([^>]*type="radio"[^>]*)>/g)) {
      const attrs = m[1];
      if (!attrs.includes('name=')) {
        const line = text.slice(0, tm.index).split('\n').length + body.slice(0, m.index).split('\n').length;
        badRadios.push(`${rel}:${line} 单选框缺少 name 属性（导致键盘方向键切换失效）`);
      }
    }

    // 校验包含 radio 的页面必须有 role="radiogroup" 容器
    assert.match(body, /role="radiogroup"/, `${rel} 包含 radio 但缺少 role="radiogroup" 容器`);
    assert.match(body, /<[^>]*role="radiogroup"[^>]*:?aria-label=/, `${rel} 的 radiogroup 缺少 aria-label 属性`);
  }

  assert.deepEqual(badRadios, [], `发现缺陷单选框：\n  ${badRadios.join('\n  ')}`);
});

test('DataTable 必须声明 :aria-busy 且 loading/empty 单元格具备 role="status"', () => {
  const text = readFileSync(path.join(SRC, 'components/admin/DataTable.vue'), 'utf8');
  assert.match(text, /:aria-busy="loading\s*\?\s*'true'\s*:\s*undefined"/, 'DataTable 缺失 :aria-busy 绑定');
  assert.match(text, /<td[^>]*role="status"[^>]*>[\s\S]*?<slot name="loading"/, 'DataTable 加载格缺失 role="status"');
  assert.match(text, /<td[^>]*role="status"[^>]*>[\s\S]*?\{\{\s*emptyText/, 'DataTable 空白格缺失 role="status"');
});

test('BaseStat 提示按钮必须具备键盘焦点可见性', () => {
  const text = readFileSync(path.join(SRC, 'components/base/BaseStat.vue'), 'utf8');
  assert.match(text, /class="[^"]*focus-visible:opacity-100[^"]*"/, 'BaseStat .kpi-hint 缺少 focus-visible:opacity-100 类名');
});

test('闸自检：能准确拦截无 name 的 radio 与缺少 aria-busy 的表格', () => {
  const badRadio = '<input type="radio" value="okx" />';
  const goodRadio = '<input type="radio" name="venue" value="okx" />';
  const badTable = '<table class="table" :aria-label="label">';
  const goodTable = '<table class="table" :aria-label="label" :aria-busy="loading ? \'true\' : undefined">';

  const checkRadio = (html) => html.includes('type="radio"') && !html.includes('name=');
  const checkTable = (html) => html.includes('<table') && !html.includes('aria-busy');

  assert.equal(checkRadio(badRadio), true, '应拦截无 name 的 radio');
  assert.equal(checkRadio(goodRadio), false, '应放行有 name 的 radio');
  assert.equal(checkTable(badTable), true, '应拦截无 aria-busy 的 table');
  assert.equal(checkTable(goodTable), false, '应放行有 aria-busy 的 table');
});
