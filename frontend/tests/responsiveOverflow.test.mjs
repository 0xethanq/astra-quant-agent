/**
 * 移动端（390px）与外语扩展下的布局防截断防溢出守卫闸（批 114）。
 *
 * ## 实测出来的 3 处窄屏缺陷（共 38 个越界截断元素）：
 *
 * 1. `/news` 信源状态胶囊越界 68px：
 *    `sourceReason` 为长文本（446px 宽）时，父级 flex 容器无 `max-w-full min-w-0`，
 *    胶囊撑破视口直接横向溢出视口 68px。
 *    修法：容器与胶囊均设 `max-w-full min-w-0`，文字 span 设 `truncate`，配合既有 `:title`。
 *
 * 2. `/admin/overview` 决策流与审计表格在移动端被硬性截断（33 处元素出界）：
 *    `.ov-stream-card` 与 `.ov-audit-card` 宽度 346px，但内部网格各列合计分别达 480px 与 520px；
 *    卡片设置了 `overflow: hidden`，而列表容器此前未声明 `overflow-x: auto`，
 *    导致右侧时间戳（位于 [375px, 445px]）、置信度与状态指示在移动端完全被切掉且不可横向滑动。
 *    修法：`.ov-stream-list` 与 `.ov-audit-table` 声明 `overflow-x: auto`，子项设保底 `min-width`。
 *
 * 3. `/admin/decisions` 分段条英文下溢出卡片 60px：
 *    英文下 `Trader patrol (Trader)` 与 `Task scheduler (Celery/Cron)` 达 413px，
 *    `.seg` 无 `max-width: 100%`，超出 346px 卡片被外层裁切。
 *    修法：全站 `.seg` 统一声明 `max-width: 100%; overflow-x: auto; scrollbar-width: none;`，
 *    按钮声明 `flex-shrink: 0;`。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

test('全站分段控件 .seg 必须具备自适应窄屏与外语滚动的能力', () => {
  const css = readFileSync(path.join(SRC, 'styles/components.css'), 'utf8');
  // 提取 .seg 规则块
  const segMatch = css.match(/\.seg\s*\{([^}]+)\}/);
  assert.ok(segMatch, '找不到 .seg 规则');
  const segBody = segMatch[1];
  assert.match(segBody, /max-width:\s*100%/, '.seg 缺少 max-width: 100%，会在窄屏被撑破');
  assert.match(segBody, /overflow-x:\s*auto/, '.seg 缺少 overflow-x: auto，按钮过多或文字变长时无法横向滑动');

  // .seg button 必须禁止挤压缩水
  const btnMatch = css.match(/\.seg\s+button\s*\{([^}]+)\}/);
  assert.ok(btnMatch, '找不到 .seg button 规则');
  assert.match(btnMatch[1], /flex-shrink:\s*0/, '.seg button 缺少 flex-shrink: 0，窄屏下按钮文字会被挤瘪');
});

test('新闻页信源胶囊容器必须限制最大宽度并在内部截断长文本', () => {
  const vue = readFileSync(path.join(SRC, 'views/dashboard/NewsView.vue'), 'utf8');
  // 必须存在 max-w-full min-w-0 组合防 flex 溢出
  assert.match(vue, /class="[^"]*dsh-pill[^"]*max-w-full[^"]*min-w-0/, 'NewsView 中的 dsh-pill 缺少 max-w-full min-w-0 防溢出保护');
  assert.match(vue, /class="[^"]*truncate[^"]*min-w-0/, 'NewsView 中信源文本缺少 truncate min-w-0 截断保护');
});
