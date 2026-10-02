/**
 * 因子矩阵（FactorMatrix）全部可排序列视觉提示（ArrowUpDown）与布局抖动守卫闸（批 125）。
 *
 * ## 实测缺陷与背景：
 *
 * 在实盘矩阵（`/trading`）桌面端数据表格中，共有 8 列支持点击客户端排序：
 * `name`（标的）、`price`（现价）、`chg24h`（24H 涨跌）、`macd`（1H MACD 柱）、
 * `macdAccel`（1H MACD 柱加速度）、`adx`（ADX）、`ls`（多空比）、`conf`（AI 结论）。
 *
 * ★ 2026-10：原来这两列是 `velocity`（速度 v）/`accel`（加速度 a）—— 随数理系统
 * 退场改成 1H MACD 柱与其加速度；**排序键改名必须与组件、本闸、locales 同批改**，
 * 否则闸会红（这正是它存在的意义）。
 *
 * 缺陷：
 * 此前仅 `name` 列声明了 `<ArrowUpDown v-else class="h-3 w-3 opacity-40" />`；
 * 其余 7 列在非当前排序列时（未排序或排他列时）均未渲染任何图标（svgCount: 0）。
 * 造成双重体验缺陷：
 * 1. 可用性暗示缺失（Affordance Gap）：用户无法直观看出其余 7 列均可点击排序，
 *    误以为只有标的一列能排；
 * 2. 布局突变抖动（Layout Shift）：一旦用户点击某列排序，原本没有图标的表头突然凭空
 *    插入 12px 的箭头图标，导致表头文字和列宽瞬时向左跳变挤压。
 *
 * 修复后：8 个可排序列统一具备 `ArrowUpDown v-else` 闲置态图标，提前预留排版宽度，
 * 视觉提示一致且切换排序零抖动。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

const SORT_KEYS = ['name', 'price', 'chg24h', 'macd', 'macdAccel', 'adx', 'ls', 'conf'];

test('FactorMatrix 全部 8 个可排序列必须统一具备 ArrowUpDown 闲置态图标', () => {
  const vue = readFileSync(path.join(SRC, 'components/dashboard/FactorMatrix.vue'), 'utf8');
  const theadMatch = vue.match(/<thead>([\s\S]*?)<\/thead>/);
  assert.ok(theadMatch, 'FactorMatrix 中未找到 thead 结构');
  const thead = theadMatch[1];

  const missing = [];
  for (const key of SORT_KEYS) {
    const btnMatch = thead.match(new RegExp(`<button[^>]*toggleSort\\(['"]${key}['"]\\)[\\s\\S]*?<\\/button>`));
    if (!btnMatch || !/ArrowUpDown\s+v-else/.test(btnMatch[0])) {
      missing.push(key);
    }
  }

  assert.deepEqual(
    missing,
    [],
    `FactorMatrix 以下排序列缺少 ArrowUpDown v-else 闲置提示（会导致可用性缺失与排版抖动）：${missing.join(', ')}`,
  );
});

test('自检：能准确拦截缺少 ArrowUpDown 的排序列', () => {
  const mockWithMissing = `
    <button @click="toggleSort('name')">
      <ArrowUp v-if="sortKey === 'name'" />
      <ArrowUpDown v-else />
    </button>
    <button @click="toggleSort('price')">
      <ArrowUp v-if="sortKey === 'price'" />
    </button>
  `;
  const hasName = /toggleSort\(['"]name['"]\)[\s\S]*?ArrowUpDown\s+v-else/.test(mockWithMissing);
  const hasPrice = /toggleSort\(['"]price['"]\)[\s\S]*?ArrowUpDown\s+v-else/.test(mockWithMissing);
  assert.equal(hasName, true);
  assert.equal(hasPrice, false);
});
