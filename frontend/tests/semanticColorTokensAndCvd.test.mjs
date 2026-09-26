/**
 * 语义色与色盲友好模式（CVD）令牌守卫闸（批 74）。
 *
 * ## 背景：CVD 模式是一个**已发布、用户可达**的功能
 *
 * `SettingsPopover` 里有「色盲友好配色」开关，打开后 `useTheme.applyCvd` 会给
 * `<html>` 打上 `data-cvd="true"`，`tokens.css` 据此把
 * `--astra-up` 从绿 `#48c78e` 换成蓝 `#7aa6ff`、`--astra-down` 从红 `#f07178`
 * 换成橙 `#e8923f`，并同步替换 `--astra-up-bg` / `--astra-up-line` 等成对令牌。
 *
 * ⚠️ 上行蓝在**批 105** 由 `#6799fe` 提亮为 `#7aa6ff`：全站回归审计抓到
 * `/news` 的「做多」11px 小标签只有 **4.40:1**（AA 要 4.5）—— 语义色除了铺在卡片上，
 * 还会以「文字 + 12~13% 同色淡底」的形态出现，淡底把背景抬亮，对比度远低于裸卡片。
 * 提亮后为 4.96:1。**别再改回去**：`cvdPalette.test.mjs` 里有专门一条判据守着这件事。
 *
 * ## 缺陷：只吃了一半令牌
 *
 * 全站形态是「前景用令牌、底/边用同色硬编码 rgba」，例如：
 *
 * ```css
 * .ov-act-tag.is-long {
 *   color: var(--up);                           ← 跟随 CVD
 *   background: rgba(72, 199, 142, 0.12);       ← 不跟随 CVD，永远绿色
 *   border: 1px solid rgba(72, 199, 142, 0.25); ← 不跟随 CVD，永远绿色
 * }
 * ```
 *
 * `rgba(72,199,142)` 与 `--astra-up`（`#48c78e`）**色相完全相同** —— 深色主题下
 * 肉眼看不出区别，所以这个缺陷在默认主题里是隐形的。但开启 CVD 后前景变蓝、
 * 底与边仍是绿，得到「蓝字配绿底」；`--down` 一侧同理得到「橙字配红底」。
 *
 * 批 74 实测并修复 18 处，分布在 `OverviewPage`（16）与 `LoginPage`（2）。
 *
 * 本闸钉住：**任何与 `--up/--down/--warn` 同 RGB 的硬编码 rgba 都不允许存在**。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

/** 深色主题下与语义令牌同 RGB 的硬编码色值（令牌定义见 tokens.css 285-293）。 */
const TOKEN_RGB = {
  up: [72, 199, 142], // == #48c78e
  down: [240, 113, 120], // == #f07178
  warn: [224, 177, 85], // == #e0b155
};

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

/** 找出文件里所有与语义令牌同 RGB 的硬编码 rgba()/rgb()。 */
export function hardcodedTokenColors(raw, tokenRgb = TOKEN_RGB) {
  const hits = [];
  const re = /rgba?\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*(?:,\s*[\d.]+\s*)?\)/g;
  for (const m of raw.matchAll(re)) {
    const rgb = [Number(m[1]), Number(m[2]), Number(m[3])];
    for (const [name, val] of Object.entries(tokenRgb)) {
      if (rgb[0] === val[0] && rgb[1] === val[1] && rgb[2] === val[2]) {
        hits.push({ text: m[0], token: name, index: m.index, line: raw.slice(0, m.index).split('\n').length });
      }
    }
  }
  return hits;
}

test('不得硬编码与 --up / --down / --warn 同色的 rgba（会绕过 CVD 模式）', () => {
  const bad = [];

  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    for (const hit of hardcodedTokenColors(readFileSync(file, 'utf8'))) {
      bad.push(`${rel}:${hit.line}  ${hit.text}  → 应改用 var(--${hit.token}-bg) / var(--${hit.token}-line)`);
    }
  }

  assert.deepEqual(
    bad,
    [],
    `以下硬编码色与语义令牌同色相、却不跟随色盲友好模式，开启 CVD 后会出现「字与底不同色系」：\n  ${bad.join('\n  ')}`,
  );
});

test('语义前景色必须与同名令牌的底/边配对使用', () => {
  // 回归锚点：批 74 修好的规则必须继续用令牌，而不是退回硬编码
  const cases = [
    ['views/admin/OverviewPage.vue', /\.ov-live-pill\s*\{[^}]*background:\s*var\(--up-bg\)/, '.ov-live-pill 底'],
    ['views/admin/OverviewPage.vue', /\.ov-live-pill\s*\{[^}]*border:\s*1px solid var\(--up-line\)/, '.ov-live-pill 边'],
    ['views/admin/OverviewPage.vue', /\.ov-error-banner\s*\{[^}]*background:\s*var\(--down-bg\)/, '.ov-error-banner 底'],
    ['views/admin/OverviewPage.vue', /\.ov-act-tag\.is-long\s*\{[^}]*background:\s*var\(--up-bg\)/, '.ov-act-tag.is-long 底'],
    ['views/admin/OverviewPage.vue', /\.ov-act-tag\.is-short\s*\{[^}]*background:\s*var\(--down-bg\)/, '.ov-act-tag.is-short 底'],
    ['views/admin/OverviewPage.vue', /\.ov-chip-status\.is-warn\s*\{[^}]*border:\s*1px solid var\(--warn-line\)/, '.ov-chip-status.is-warn 边'],
    ['views/admin/LoginPage.vue', /\.auth-alert\s*\{[^}]*background:\s*var\(--down-bg\)/, '.auth-alert 底'],
  ];

  for (const [rel, re, label] of cases) {
    const text = readFileSync(path.join(SRC, rel), 'utf8');
    assert.match(text, re, `${rel} 的「${label}」未使用语义令牌`);
  }
});

test('CVD 开关必须仍然可达（本闸的前提）', () => {
  // 若哪天 CVD 开关被撤掉，本闸的判据就失去意义 —— 那时应当连同本文件一起复核
  const theme = readFileSync(path.join(SRC, 'composables/useTheme.ts'), 'utf8');
  assert.match(theme, /data-cvd/, 'useTheme 不再设置 data-cvd，CVD 模式可能已下线');

  const tokens = readFileSync(path.join(SRC, 'styles/tokens.css'), 'utf8');
  // ⚠️ 必须带上 `{`：否则 `:root[data-cvd='true'][data-theme='light']` 这段
  // 浅色主题后缀也会匹配上，把断言"喂饱"（变异测试 M7 当场暴露了这一点）。
  assert.match(
    tokens,
    /:root\[data-cvd='true'\]\s*\{/,
    'tokens.css 缺少深色 CVD 令牌覆盖块',
  );
  // 值被批 105 调整过（AA 对比度），见文件头 ⚠️；改动前请先读 cvdPalette.test.mjs 的那条判据。
  assert.match(tokens, /--astra-up:\s*#7aa6ff/, 'CVD 模式未把上行色改为蓝（批 105 提亮后的值）');
  assert.match(tokens, /--astra-down:\s*#e8923f/, 'CVD 模式未把下行色改为橙');

  const popover = readFileSync(path.join(SRC, 'components/dashboard/SettingsPopover.vue'), 'utf8');
  // ⚠️ 只断言"文件里出现过 toggleCvd"是不够的 —— 导入语句就会满足它。
  // 必须校验 <BaseSwitch> 的取值与回调都真的接上了（变异测试 M8 暴露了这一点）。
  assert.match(
    popover,
    /<BaseSwitch[^>]*:model-value="cvd"[^>]*@update:model-value="toggleCvd\(\)"/,
    '设置面板的 CVD 开关未真正接线，用户已无法开启该模式',
  );
});

test('闸自检：能准确识别同色相硬编码', () => {
  const check = (css) => hardcodedTokenColors(css).map((h) => h.token);

  assert.deepEqual(check('background: rgba(72, 199, 142, 0.12);'), ['up'], '应识别上行的绿色硬编码');
  assert.deepEqual(check('border: 1px solid rgba(240, 113, 120, 0.25);'), ['down'], '应识别下行的红色硬编码');
  assert.deepEqual(check('background: rgba(224, 177, 85, 0.1);'), ['warn'], '应识别警示的琥珀硬编码');
  assert.deepEqual(check('background: rgba(72, 199, 142);'), ['up'], '不带 alpha 的 rgb() 也要识别');
  assert.deepEqual(check('background: var(--up-bg);'), [], '令牌写法不该被拦');
  // 相近但不同的色相不得误报（同色系不同明度）
  assert.deepEqual(check('background: rgba(26, 127, 90, 0.1);'), [], '浅色主题的下行色不该被误判为 dark 的 down');
  assert.deepEqual(check('background: rgba(103, 153, 254, 0.13);'), [], 'CVD 蓝不该被误判');
});
