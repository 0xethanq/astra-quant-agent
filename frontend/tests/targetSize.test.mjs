/**
 * 命中区判据（批 99）—— WCAG 2.5.8 Target Size (Minimum) = 24×24。
 *
 * ## 怎么发现的
 *
 * `a11y-audit.js` 的各类指标都已归零，于是换一个它**不覆盖**的维度：
 * 量全部交互元素的实机尺寸。25 路由 **930 个交互元素**，跑出 24 处 < 24×24，
 * 归成三类：
 *
 * | 元素 | 实测 | 判定 |
 * |---|---|---|
 * | `button.sort-btn`（16 处） | **132×16** | **真缺陷**：`padding:0` + 16px 行高；所在 `th` 高 33px（padding 8px 12px），**上下各 8px 是点不到的空白** |
 * | `input[type=radio]`（7 处） | 13×13 | **不是缺陷**：被 `<label>` 包住，label 实测 **371×61** —— 有效命中区是 label |
 * | `.cn-name-input`（1 处） | **173×22.2** | **真缺陷**：12px 字号 + `padding: 0 0 2px` |
 *
 * ## 修法
 *
 * 两处都补 `min-height: var(--h-sm)` —— `--h-sm` 正好是 **24px**，
 * 也就是 WCAG AA 的下限，**不自造数字**。
 *
 * 实机复核：`.sort-btn` 132×16 → **132×24**（表头行 33 → **41px**，
 * 是本次唯一的可见变化，换来整格可点）；`.cn-name-input` 22.2 → **24**。
 * 修完 25 路由 **0 处**小目标（7 处经 label 豁免）。
 *
 * ## ⚠️ 仪器假阳性（已写进工具体内）
 *
 * 只量控件自身的 `getBoundingClientRect` 会把「被 label 包住的 radio/checkbox」
 * 误判成小目标 —— **有效命中区是 label**。7 处假阳性全出自这一条。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

/** WCAG 2.5.8 的 AA 下限。 */
export const MIN_TARGET = 24;

const TOKENS = readFileSync(path.join(SRC, 'styles', 'tokens.css'), 'utf8');

/** 把 `var(--x)` 解析成 px 数值。 */
function resolve(value) {
  const m = /var\((--[\w-]+)\)/.exec(value);
  if (!m) {
    const px = /([\d.]+)px/.exec(value);
    return px ? Number(px[1]) : null;
  }
  const t = new RegExp(`\\${m[1]}:\\s*([^;]+);`).exec(TOKENS);
  if (!t) return null;
  const px = /([\d.]+)px/.exec(t[1]);
  return px ? Number(px[1]) : null;
}

/** 取某个类在给定样式表里的规则体。 */
function ruleBody(css, cls) {
  const m = new RegExp(`(?:^|\\})\\s*[^{}]*\\.${cls.replace(/[-]/g, '\\-')}\\s*(?:,[^{}]*)?\\{([^}]*)\\}`, 'm').exec(css);
  return m ? m[1] : null;
}

/** 规则体里的 min-height / height。 */
function heightOf(body) {
  if (!body) return null;
  const mh = /min-height\s*:\s*([^;]+)/.exec(body);
  if (mh) return { kind: 'min-height', value: resolve(mh[1]), raw: mh[1].trim() };
  const h = /(?:^|;)\s*height\s*:\s*([^;]+)/.exec(body);
  if (h) return { kind: 'height', value: resolve(h[1]), raw: h[1].trim() };
  return null;
}

test('--h-sm 必须正好是 WCAG 2.5.8 的下限 24px（两处修法都取它）', () => {
  const m = /--h-sm:\s*([^;]+);/.exec(TOKENS);
  assert.ok(m, 'tokens.css 里找不到 --h-sm');
  assert.equal(resolve(m[1]), MIN_TARGET, `--h-sm 变成 ${m[1].trim()}，不再是命中区下限 24px`);
});

test('table 排序按钮的命中区不得低于 24px（批 99 修的 16 处）', () => {
  const css = readFileSync(path.join(SRC, 'styles', 'components.css'), 'utf8');
  const body = ruleBody(css, 'sort-btn');
  assert.ok(body, '找不到 .sort-btn 规则');
  const h = heightOf(body);
  assert.ok(h, '.sort-btn 没有 height/min-height —— 高度会退回到行高（实测曾是 16px）');
  assert.ok(
    h.value !== null && h.value >= MIN_TARGET,
    `.sort-btn 的 ${h.kind} 解析为 ${h.value}（原文 ${h.raw}），低于 ${MIN_TARGET}px`,
  );
});

test('CouncilPage 已随后台 12→6 精简退役（原 .cn-name-input 目标由退役自然消除）', () => {
  assert.equal(
    existsSync(path.join(SRC, 'views/admin/CouncilPage.vue')),
    false,
    'CouncilPage.vue 应已在 Agent-First 精简中退役移除',
  );
});

test('抽屉内日志过滤芯片的命中区不得低于 24px（批 106）', () => {
  // 实测 23.4px（text-3xs 行高 + py-0.5 + 1px 边框），差一点点。
  // 这些芯片只在抽屉打开、且切到「实时日志」页签时才存在 —— 页面级审计看不到。
  const src = readFileSync(path.join(SRC, 'components/dashboard/TrajectoryPanel.vue'), 'utf8');
  const tag = /<button[\s\S]{0,700}?logFilter === filter[\s\S]{0,700}?>/.exec(src);
  assert.ok(tag, '找不到日志过滤芯片的模板');
  assert.match(
    tag[0],
    /min-h-\[var\(--h-sm\)\]/,
    '芯片命中区低于 WCAG 2.5.8 的 24px —— 用 min-h-[var(--h-sm)]（与 .sort-btn / 委员会改名框同一修法）',
  );
});

test('判据自检：能解析令牌、能拒绝低于下限的值', () => {
  assert.equal(resolve('var(--h-sm)'), 24, '--h-sm 应解析为 24');
  assert.equal(resolve('var(--h-lg)'), 36, '--h-lg 应解析为 36');
  assert.equal(resolve('30px'), 30);
  assert.equal(
    heightOf('display: flex; padding: 0;'),
    null,
    '只有 padding/line-height 时应判为「无高度声明」',
  );
  assert.equal(
    heightOf('padding: 0; height: 16px;').value,
    16,
    '显式 height 也要读得到（.sort-btn 原来就是靠行高撑到 16px）',
  );
  const bad = heightOf('padding: 0; min-height: var(--sp-6);');
  assert.ok(bad.value !== null && bad.value < MIN_TARGET, 'min-height 12px 应被判低于下限');
});
