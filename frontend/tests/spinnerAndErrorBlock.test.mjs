/**
 * 加载旋转与错误状态块：两处全站级收口（批 80）。
 *
 * ## A. 加载旋转：22 个文件各自手写了一份 spinner
 *
 * 每个页面都有一对**逐字节相同（仅 keyframes 名不同）**的规则：
 *
 *     .X-spin { animation: X-rotate 0.9s linear infinite; flex-shrink: 0; }
 *     @keyframes X-rotate { to { transform: rotate(360deg); } }
 *
 * 实测 22 个 `.X-spin` + 22 个 `@keyframes *-rotate`（其中 20 份多行写法、
 * 2 份单行写法，**语义完全相同**）。
 *
 * 同时项目里**另有**一套 spinner：Tailwind 的 `animate-spin`
 * （`--animate-spin: spin 1s linear infinite`），已被共享组件
 * `DataTable` / `ChartWorkstation` 使用。
 * 于是同一个"加载中"有两种转速（0.9s / 1s）。
 *
 * 收口到 Tailwind 的 `animate-spin` + `shrink-0`（后者补回原来那条
 * `flex-shrink: 0`），删掉 22 条规则与 22 个 keyframes。
 * 依据：项目既有方向（批 28 / 批 37）就是"把工具类修好、以工具类为机制"，
 * 且 22 份逐字节拷贝 + 每页一个 keyframes 名是**复制粘贴**的签名而非设计。
 * 代价：转速 0.9s → 1s（10%，肉眼几乎不可辨），换来全站单一 spinner。
 *
 * ## B. 错误状态块：13 个页面各补一份 delta，3 个页面漏了
 *
 * 错误态用的是既有 `.state-block.is-error`，但卡片外观（`border` +
 * `border-radius` + `background-color`）当初没进本体，而是**13 个页面各写一份**：
 *
 *     .X-error { border: 1px solid var(--down-line);
 *                border-radius: var(--r-card);
 *                background-color: var(--ds-color-bg-surface-card); }
 *
 * 于是 `SecurityPage` / `AdminSysPage` / `DecisionsPage` 三个页面
 * （模板里只写 `class="state-block is-error"`）**同一个错误状态是裸块、没有卡片边框**；
 * `DataGate` 那份还用着遗留 token `--surface-2`(#1c202b) 而非设计 token
 * `--ds-color-bg-surface-card`(#151821)。
 *
 * 修法：三条并入 `.state-block.is-error` 本体，13 份 delta 删除，
 * 3 个孤儿页**无需改模板**即自动对齐。
 *
 * 运行：`node --test tests/*.test.mjs`（**先 `npm run build`**：
 * `tests/deadUtilities.test.mjs` 需要新鲜的 dist 才不跳过）
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const COMPONENTS_CSS = path.join(SRC, 'styles', 'components.css');

/** 允许自带 spin 规则的例外（值=理由）。 */
export const SPIN_EXEMPT = {};

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

const FILES = vueFiles(SRC).map((f) => ({
  rel: path.relative(SRC, f),
  text: readFileSync(f, 'utf8'),
}));

const styleOf = (t) => (t.match(/<style[^>]*>([\s\S]*?)<\/style>/) || [null, ''])[1];
const tplOf = (t) => (t.includes('<style') ? t.slice(0, t.indexOf('<style')) : t);

test('不得再有页面自带 spinner 规则或 *-rotate 关键帧', () => {
  const bad = [];
  for (const { rel, text } of FILES) {
    if (SPIN_EXEMPT[rel]) continue;
    const css = styleOf(text);
    for (const m of css.matchAll(/\.([a-z]{2,4})-spin\b/g)) bad.push(`${rel} :: .${m[1]}-spin`);
    for (const m of css.matchAll(/@keyframes\s+([\w-]*rotate)\b/g)) bad.push(`${rel} :: @keyframes ${m[1]}`);
  }
  assert.deepEqual(
    bad,
    [],
    `以下页面仍自带 spinner —— 应改用 Tailwind 的 animate-spin + shrink-0：\n  ${bad.join('\n  ')}`,
  );
});

test('加载图标必须同时带 animate-spin 与 shrink-0（后者补回 flex-shrink: 0）', () => {
  const bad = [];
  let n = 0;
  for (const { rel, text } of FILES) {
    const tpl = tplOf(text);
    // 只看加载图标（Loader2 / RefreshCw），避免误判其它动效
    for (const m of tpl.matchAll(/<(Loader2|RefreshCw)\b[^>]*>/g)) {
      const tag = m[0];
      const dynamic = /:class="([^"]*)"/.exec(tag);
      const cls = /(?<!:)class="([^"]*)"/.exec(tag);
      const hay = (dynamic ? dynamic[1] : '') + ' ' + (cls ? cls[1] : '');
      if (!/animate-spin/.test(hay)) continue; // 未处于加载态的分支
      n += 1;
      if (!/shrink-0/.test(hay)) bad.push(`${rel} :: ${tag.slice(0, 90)}`);
    }
  }
  assert.ok(n >= 40, `识别到的加载图标过少（${n}），判据可能失效`);
  assert.deepEqual(bad, [], `加载图标缺 shrink-0（会被 flex 压扁）：\n  ${bad.join('\n  ')}`);
});

test('错误状态块的卡片外观必须在 .state-block.is-error 本体里', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  const m = css.match(/\.state-block\.is-error\s*\{([^}]*)\}/);
  assert.ok(m, 'components.css 缺少 .state-block.is-error 本体规则');
  assert.ok(m[1].includes('border: 1px solid var(--down-line);'), '缺边框');
  assert.ok(m[1].includes('border-radius: var(--r-card);'), '缺圆角');
  // 必须用设计 token，不得回到遗留的 --surface-2
  assert.ok(
    m[1].includes('background-color: var(--ds-color-bg-surface-card);'),
    '背景色应为设计 token --ds-color-bg-surface-card',
  );
  assert.ok(!/--surface-2/.test(m[1]), '又用回了遗留 token --surface-2');
});

test('页面不得再自带 <X>-error 卡片 delta', () => {
  const bad = [];
  for (const { rel, text } of FILES) {
    const css = styleOf(text);
    for (const m of css.matchAll(/^[ \t]*\.([a-z]{2,4})-error\s*\{([^{}]*)\}/gm)) {
      const body = m[2];
      if (/var\(--down-line\)/.test(body) && /border-radius: var\(--r-card\)/.test(body)) {
        bad.push(`${rel} :: .${m[1]}-error`);
      }
    }
  }
  assert.deepEqual(bad, [], `以下页面仍自带错误卡片 delta（应并入 .state-block.is-error）：\n  ${bad.join('\n  ')}`);
});

test('模板里的错误状态块只允许挂"本页真有规则"的 delta 类', () => {
  // ⚠️ 不能一刀切禁止页面类：`ProviderListView` 的 `.pv-gate-err` 是**合理 delta**
  // （在清单里给错误块加一条上分隔线）。判据改为：额外类必须在**本页**有规则，
  // 否则就是"写了类名却没有样式"的静默失效。
  const bad = [];
  const legitimate = [];
  let n = 0;
  for (const { rel, text } of FILES) {
    const css = styleOf(text);
    for (const m of tplOf(text).matchAll(/class="([^"]*\bstate-block\b[^"]*\bis-error\b[^"]*)"/g)) {
      n += 1;
      const extra = m[1].split(/\s+/).filter((c) => c !== 'state-block' && c !== 'is-error');
      for (const cls of extra) {
        if (new RegExp(`\\.${cls}\\b`).test(css)) legitimate.push(`${rel} :: .${cls}`);
        else bad.push(`${rel} :: ${m[1]}`);
      }
    }
  }
  assert.ok(n >= 14, `识别到的错误状态块过少（${n}）`);
  assert.deepEqual(
    bad,
    [],
    `错误状态块挂了没有规则的类（静默失效）：\n  ${bad.join('\n  ')}`,
  );
  // 有规则的 delta 应已被上面计入而不是被误判
  assert.deepEqual(legitimate.sort(), ['views/admin/llm/ProviderListView.vue :: .pv-gate-err']);
});

test('闸自检：识别 spinner 与错误 delta，不误伤其它动画', () => {
  // spinner 判据
  const css = '.ag-spin {\n  animation: ag-rotate 0.9s linear infinite;\n}\n@keyframes ag-rotate {\n  to { transform: rotate(360deg); }\n}';
  assert.equal([...css.matchAll(/\.([a-z]{2,4})-spin\b/g)].length, 1);
  assert.equal([...css.matchAll(/@keyframes\s+([\w-]*rotate)\b/g)].length, 1);
  // 不误伤：非旋转动画（ov-pulse）不该被 spin 判据命中
  const pulse = '@keyframes ov-pulse {\n  0%, 100% { opacity: 1; }\n  50% { opacity: 0.4; }\n}';
  assert.equal([...pulse.matchAll(/@keyframes\s+([\w-]*rotate)\b/g)].length, 0, 'ov-pulse 不该被当作旋转动画');
  // 不误伤：仍在使用 animate-spin 的组件
  assert.ok(/animate-spin/.test('<RefreshCw :class="isLoading && \'animate-spin\'" />'));

  // 错误 delta 判据
  const delta = '.ab-error {\n  border: 1px solid var(--down-line);\n  border-radius: var(--r-card);\n  background-color: var(--ds-color-bg-surface-card);\n}';
  assert.ok(/var\(--down-line\)/.test(delta) && /border-radius: var\(--r-card\)/.test(delta));
  // 不误伤：另一种错误样式（OverviewPage 的内联横幅）
  const banner = '.ov-error-banner {\n  display: flex;\n  background: var(--down-bg);\n  border: 1px solid var(--down-line);\n}';
  assert.equal(/var\(--down-line\)/.test(banner) && /border-radius: var\(--r-card\)/.test(banner), false,
    '内联错误横幅不该被当作卡片 delta');
});
