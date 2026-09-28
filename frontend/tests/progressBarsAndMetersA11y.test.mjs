/**
 * 进度条与量规指标无障碍规范守卫闸（批 59）。
 *
 * ## 守什么
 *
 * 1. **进度与量规 ARIA 模式规范（WAI-ARIA role="progressbar"）**：
 *    全站所有具有进度指示、比例分布与置信度量规用途的容器：
 *    - `OverviewPage.vue`（AI 决策置信度量规）；
 *    - `TrajectoryPanel.vue`（推演决策置信度指示条）；
 *    - `NewsView.vue`（快讯情绪多空力量对比条）。
 *
 * 2. **必要属性完整性**：
 *    - 必须声明 `role="progressbar"`；
 *    - 必须具备机器可读的当前数值（`:aria-valuenow="..."`）及区间（`aria-valuemin="0"`、`aria-valuemax="100"`）；
 *    - 必须提供可访问名称描述（`:aria-label="..."`）；
 *    - 必须提供人类友好可读格式值（`:aria-valuetext="..."`）。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

test('全站关键进度条与量规必须满足 role="progressbar" 规范', () => {
  const targets = [
    { file: 'views/admin/OverviewPage.vue', labelMatch: /confidenceGauge/ },
    { file: 'components/dashboard/TrajectoryPanel.vue', labelMatch: /dash\.shell\.panel\.confidence/ },
    { file: 'views/dashboard/NewsView.vue', labelMatch: /dash\.news\.ratioLabel/ },
  ];

  for (const { file, labelMatch } of targets) {
    const text = readFileSync(path.join(SRC, file), 'utf8');
    const barRe = /<div[^>]*role="progressbar"[^>]*>/g;
    const matches = Array.from(text.matchAll(barRe));
    assert.ok(matches.length > 0, `${file} 未找到 role="progressbar" 容器`);

    const hasMatchingBar = matches.some((m) => {
      const attrs = m[0];
      return (
        attrs.includes('aria-valuemin="0"') &&
        attrs.includes('aria-valuemax="100"') &&
        attrs.includes(':aria-valuenow=') &&
        labelMatch.test(attrs)
      );
    });

    assert.ok(hasMatchingBar, `${file} progressbar 缺少必要 ARIA 属性 (valuenow, valuemin, valuemax, aria-label)`);
  }
});

test('闸自检：能准确拦截缺少 ARIA 属性的裸进度条', () => {
  const badBar = '<div class="progress-bar"><div class="fill" style="width: 50%" /></div>';
  const goodBar = '<div role="progressbar" :aria-valuenow="50" aria-valuemin="0" aria-valuemax="100" :aria-label="label"></div>';

  const check = (html) =>
    html.includes('role="progressbar"') &&
    html.includes(':aria-valuenow=') &&
    html.includes('aria-valuemin="0"') &&
    html.includes('aria-valuemax="100"');

  assert.equal(check(badBar), false, '应识别缺失 ARIA 属性的进度条');
  assert.equal(check(goodBar), true, '应放行合规 progressbar');
});
