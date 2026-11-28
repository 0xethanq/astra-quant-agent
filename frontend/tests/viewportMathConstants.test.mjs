/**
 * 视口高度算式不得用「猜出来的常量」（批 84）。
 *
 * ## 起因：两处 `calc(100vh - Npx)` 都被实测证伪
 *
 * ### A. 图表全屏：`calc(100vh - 108px)` —— 既过时、又**完全无效**
 *
 * 全屏时卡片是 `fixed inset-0` + flex 列，画布带 `flex-1`（`flex-basis: 0%`），
 * 内联 `height` 会被 flex 直接覆盖。实测（1440×900 / 1024×800）：
 *
 *     画布高 = 835 / 735 = 视口 − 真实 chrome
 *     而内联 calc(100vh-108) = 792 / 692   ← 从未生效
 *
 * 且 `108` 与真实 chrome 对不上，因为 `dsh-card-header` 会**换行**：
 *
 * | 视口宽 | 顶栏高 | 真实 chrome | 108 的偏差 |
 * |---|---|---|---|
 * | 1440 | 63 | 65 | −43 |
 * | 1024 | 63 | 65 | −43 |
 * | 700 | **99** | **101** | −7 |
 *
 * 常量在两个方向上都错，而 flex 天然自适应。故删掉该内联高度，
 * 全屏态也拿 `flex-1 min-h-0`。
 * **改后三个视口逐值复核：835 / 735 / 599 —— 与改前完全一致**，
 * 且画布恒等于「视口 − 真实 chrome」（顶栏换行到 99px 时依然成立）。
 *
 * ### B. 工位沉浸模式：`h-[calc(100vh-140px)]` —— 窄屏把面板**整块弄没**
 *
 * 该常量是按 `xl` 的 12 栏并排布局算的。在 <1280px（单栏堆叠）下容器高被钉死，
 * 实测 1024×760：
 *
 *     子项1（图表） 高 760、底 888 → 越出容器/视口
 *     子项2（持仓） 高 **0**、top **900** → **整个面板消失**
 *     容器自身溢出 140px
 *
 * 改为 `xl:h-[…]` 后同视口实测：容器溢出 **0**，两子项 441 / 257，0 高度子项 **0**，
 * 且 `main` 可滚（maxScrollTop=102, 滚到底后面板底=736 ≤ 视口 760，**完整可见**）。
 * 在 ≥xl（1440×900）复核仍为 gridH 760 = 100vh−140、12 栏、两子项各 760 —— **逐项一致**。
 *
 * ## 本闸怎么管
 *
 * 全站每一处「视口尺寸 ± 常量」都必须登记在 `VIEWPORT_MATH` 里并写明理由
 * （常量为何是这个数、随宽度变不变）。新增未登记的算式即报错。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

/**
 * 登记表：键 = `相对路径::片段`，值 = { why }。
 * 只登记**算术里含常量**的视口算式；`min-height: 100vh` 这种无常量的不登记。
 */
export const VIEWPORT_MATH = {
  'views/dashboard/MatrixView.vue::calc(100vh-140px)':
    { why: '工位沉浸模式：**只在 xl 生效**（12 栏并排才装得下）。140 = 实测上方 128（顶栏+页头）+ 页底 12 留白；窄屏不再钉高，回归自然文档流' },
  'views/docs/DocsView.vue::calc(100vh-5rem)':
    { why: '文档侧栏高度：5rem(80px) = 顶栏 48 + 32，用 rem 而非 px，随根字号缩放' },
  'components/base/ToastHost.vue::calc(100vw-24px)':
    { why: '浮层宽度上限的 12px×2 视口留白；是 max-w 不是高度，偏差不会裁内容' },
  'components/dashboard/SettingsPopover.vue::calc(100vw-24px)':
    { why: '同上：浮层宽度上限的视口留白' },
};

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

/**
 * 去注释 —— **扫描前必须做**。
 * 本会话已第 5 次踩同一个坑：说明性注释里往往**原样写着**被删掉的坏代码
 * （本批的 `calc(100vh - 108px)` 就写在 ChartWorkstation 的说明注释里），
 * 不剥离就会把"已经改好的文件"判红。
 * `//` 用 `(?<!:)` 保护 `https://`。
 */
export function stripComments(text) {
  return text
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(?<!:)\/\/[^\n]*/g, '');
}

/** 收集「视口尺寸 ± 常量」的算式（含 px/rem 常量）。 */
export function viewportMath(text) {
  const hits = [];
  for (const m of stripComments(text).matchAll(/calc\(\s*100(?:d)?(?:vh|vw)\s*[-+]\s*[\d.]+(?:px|rem)\s*\)/g)) {
    hits.push(m[0].replace(/\s+/g, ''));
  }
  return hits;
}

const FILES = [
  ...vueFiles(SRC).map((f) => ({ rel: path.relative(SRC, f).replace(/\\/g, '/'), text: readFileSync(f, 'utf8') })),
  ...['styles/base.css', 'styles/components.css', 'styles/tokens.css'].map((r) => ({
    rel: r,
    text: readFileSync(path.join(SRC, r), 'utf8'),
  })),
];

test('每一处「视口 ± 常量」算式都必须登记并写明理由', () => {
  const found = new Set();
  const problems = [];
  for (const { rel, text } of FILES) {
    for (const expr of viewportMath(text)) {
      const key = `${rel}::${expr}`;
      // 归一化：源码里可能写成 `calc(100vh-140px)` 或 `calc(100vh - 140px)`
      const hit = Object.keys(VIEWPORT_MATH).find((k) => k === key);
      if (hit) found.add(hit);
      else problems.push(`${key}（未登记）`);
    }
  }
  for (const k of Object.keys(VIEWPORT_MATH)) {
    if (!found.has(k)) problems.push(`${k}（登记表里的这条已不存在，请删除）`);
  }
  assert.deepEqual(problems, [], `视口算式登记表不一致：\n  ${problems.join('\n  ')}`);
});

test('图表画布：全屏不得再写死视口高度，必须交给 flex', () => {
  const t = readFileSync(path.join(SRC, 'components/dashboard/ChartWorkstation.vue'), 'utf8');
  // 回归锚点：这个签名正是批 84 删掉的失效常量
  assert.doesNotMatch(
    t,
    /isFullscreen\s*\?\s*'calc\(100vh - \d+px\)'/,
    '全屏画布又写回了猜出来的视口常量（flex-basis 会覆盖它，是死代码且数值也不对）',
  );
  assert.match(t, /isFullscreen \? 'flex-1 min-h-0'/, '全屏画布应走 flex-1 min-h-0');
  assert.match(t, /height: isFullscreen \? undefined/, '全屏时不应给内联 height');
});

test('工位沉浸模式的固定高度必须限定在 xl（窄屏不得钉高）', () => {
  const t = readFileSync(path.join(SRC, 'views/dashboard/MatrixView.vue'), 'utf8');
  // 回归锚点：无条件 h-[calc(100vh-140px)] 会在 <xl 单栏时让第二个面板塌成 0 高度
  assert.doesNotMatch(
    t,
    /class="grid grid-cols-1 gap-3 xl:grid-cols-12 h-\[calc\(100vh-140px\)\]"/,
    '沉浸模式又变成无条件固定高度 —— <xl 单栏时持仓面板会塌成 0 高度并移出视口',
  );
  assert.match(
    t,
    /class="grid grid-cols-1 gap-3 xl:grid-cols-12 xl:h-\[calc\(100vh-140px\)\]"/,
    '沉浸模式高度应为 xl: 限定',
  );
});

test('登记表每条都要有实质理由，且不得出现空的 why', () => {
  for (const [k, v] of Object.entries(VIEWPORT_MATH)) {
    assert.ok(v.why && v.why.length >= 12, `${k} 的理由过短`);
  }
  assert.ok(Object.keys(VIEWPORT_MATH).length <= 6, '登记表过长，考虑收口而不是继续加条');
});

test('闸自检：能识别算式并容忍空格写法，不误伤无常量用法', () => {
  assert.deepEqual(viewportMath("h-[calc(100vh-140px)]"), ['calc(100vh-140px)']);
  assert.deepEqual(viewportMath("style=\"height: calc(100vh - 108px)\""), ['calc(100vh-108px)']);
  assert.deepEqual(viewportMath('calc(100dvh - 5rem)'), ['calc(100dvh-5rem)']);
  // 不误伤：无常量的 min-height / 纯 var 算式
  assert.deepEqual(viewportMath('min-height: 100vh;'), []);
  assert.deepEqual(viewportMath('calc(100vh - var(--h-topbar))'), []);
  assert.deepEqual(viewportMath('max-w-[calc(100vw-24px)]').length, 1);
  // 登记表键的写法须与归一化后的算式一致
  assert.ok(VIEWPORT_MATH['views/dashboard/MatrixView.vue::calc(100vh-140px)']);
  // 注释里的算式**不得**计入（本会话第 5 次踩这个坑，故固化断言）
  assert.deepEqual(viewportMath('<!-- 原为 calc(100vh - 108px) -->'), [], 'HTML 注释里的算式被误计');
  assert.deepEqual(viewportMath('/* 原为 calc(100vh - 108px) */'), [], '块注释里的算式被误计');
  assert.deepEqual(viewportMath('// 原为 calc(100vh - 108px)'), [], '行注释里的算式被误计');
  // 但不误伤真的代码
  assert.deepEqual(viewportMath('h-[calc(100vh-140px)]'), ['calc(100vh-140px)']);
  // https:// 不被 `//` 规则截断后误判
  assert.deepEqual(stripComments('const u = "https://x/y"'), 'const u = "https://x/y"');
});
