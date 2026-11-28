/**
 * 间距刻度判据（批 97）。
 *
 * ## 起因：设计文档自己指认了「不精致」的物理成因
 *
 * `tokens.css` 的密集尺度一节写着：
 *
 * > 实测：归一前全仓用了 1/2/3/4/5/6/7/8/9/10/11 共 11 种取值、约 300 处，
 * > 其中 3/5/7/9 这些**离格值约 115 处**。每个元素疏密都差一点，
 * > 整页因此没有共同网格 —— 这是"不精致"的物理成因。
 * >
 * > 规则：**1–12px 一律走本节；16px 以上继续用 `--ds-space-4` 及以上。**
 *
 * 那次归一**做了一半**：全局样式表（components/base/index.css）实测 **0 处离格**，
 * 但页面 `<style>` 里仍留着 20 处离格值。
 *
 * ## 本批做了什么
 *
 * 16 处**装饰性**离格值 → 落到刻度上（多数同时改用 `--sp-*` 令牌）：
 * 3→2 / 5→4 / 9→8 / 11→12 / 13→12 / 14→12 或 16 / 18→16 / 28→24。
 * 其中 `.ov-card-header` 由 `14px 20px` 归到 `16px 20px`，**与共享原件
 * `.dsh-card-header`（`var(--sp-7) var(--sp-8)`）完全一致**。
 *
 * ## 4 处「推导几何」刻意保留在刻度外（已逐条注明理由）
 *
 * | 选择器 | 值 | 推导 |
 * |---|---|---|
 * | `.dz-input` | `padding-left: 27px` | 图标 `left 9` + 宽 12 + 隙 6 |
 * | `.auth-input-pwd-wrap .auth-input` | `padding-right: 36px` | 按钮 `right 6` + 宽 24 + 隙 6 |
 * | `.pd-key .field` | `padding-right: 38px` | `.pd-eye`（`right 4`）宽 + 隙 |
 * | `.rk` | `padding-bottom: 72px` | 固定保存条（`bottom 16` + 高约 46）+ 隙 |
 *
 * 这些值**由被覆盖子元素的几何决定**，强行落到 2px 刻度上会导致重叠
 * （实测 `.dz-input`：图标占 x 9~21、文字从 28 起，正好不重叠）。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

/** 允许的字面间距值（px）：`--sp-hair` + 2px 网格至 12px，再并入 `--ds-space` 台阶。 */
export const ON_GRID = [1, 2, 4, 6, 8, 10, 12, 16, 20, 24, 32, 40, 56, 80];

/** 密集尺度令牌的期望值（tokens.css 的单一事实源）。 */
export const MICRO_TOKENS = {
  '--sp-hair': '1px',
  '--sp-1': '2px',
  '--sp-2': '4px',
  '--sp-3': '6px',
  '--sp-4': '8px',
  '--sp-5': '10px',
  '--sp-6': '12px',
  '--sp-7': '16px',
  '--sp-8': '20px',
  '--sp-9': '24px',
  '--sp-10': '32px',
};

/** 「推导几何」白名单：key = `文件 basename|选择器|声明`。
 * 2026-11-28 后台精简：DangerZone.vue 与 RiskPage.vue 退役，移除对应历史豁免。
 */
export const DERIVED = new Set([
  'LoginPage.vue|.auth-input-pwd-wrap .auth-input|padding-right: 36px',
  'ProviderDetailView.vue|.pd-key .field|padding-right: 38px',
]);

const SPACING_PROPS = /^(padding|padding-(top|bottom|left|right)|margin|margin-(top|bottom|left|right)|gap|row-gap|column-gap)$/;

function stripComments(t) {
  return t
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(?<!:)\/\/[^\n]*/g, '');
}

function walk(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

/** 扫描所有样式（全局 + 页面 scoped），返回离格间距声明。 */
export function offGridSpacing() {
  const files = [];
  for (const f of walk(SRC)) {
    if (f.endsWith('.css')) files.push({ f, css: readFileSync(f, 'utf8') });
    else if (f.endsWith('.vue')) {
      const raw = readFileSync(f, 'utf8');
      for (const m of raw.matchAll(/<style[^>]*>([\s\S]*?)<\/style>/g)) files.push({ f, css: m[1] });
    }
  }
  const off = [];
  for (const { f, css } of files) {
    const clean = stripComments(css);
    for (const rule of clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      const sel = rule[1].trim().split('\n').pop().trim();
      for (const decl of rule[2].matchAll(/([a-z-]+)\s*:\s*([^;{}]+)/g)) {
        if (!SPACING_PROPS.test(decl[1])) continue;
        for (const px of decl[2].matchAll(/(?<![\w-])(\d+)px/g)) {
          if (ON_GRID.includes(Number(px[1]))) continue;
          off.push({
            key: `${path.basename(f)}|${sel}|${decl[0].trim()}`,
            file: path.relative(SRC, f),
            sel,
            decl: decl[0].trim(),
            value: Number(px[1]),
          });
        }
      }
    }
  }
  return off;
}

test('密集尺度令牌保持设计文档里的原值', () => {
  const tokens = readFileSync(path.join(SRC, 'styles', 'tokens.css'), 'utf8');
  for (const [name, value] of Object.entries(MICRO_TOKENS)) {
    const m = new RegExp(`\\${name}:\\s*([^;]+);`).exec(tokens);
    assert.ok(m, `tokens.css 里找不到 ${name}`);
    assert.equal(m[1].trim(), value, `${name} 被改成 ${m[1].trim()}，文档写的是 ${value}`);
  }
});

test('样式里不得出现离格的间距字面值（4 处推导几何已登记豁免）', () => {
  const off = offGridSpacing().filter((o) => !DERIVED.has(o.key));
  const list = off.map((o) => `${o.file}  ${o.sel}  ${o.decl}`);
  assert.deepEqual(
    list,
    [],
    '这些间距值不在刻度上（1/2/4/6/8/10/12/16/20/24/32/40/56/80）—— 请落到刻度或改用 ' +
      `--sp-* / --ds-space-* 令牌；若确属「推导几何」请在 DERIVED 里登记理由：\n  ${list.join('\n  ')}`,
  );
});

test('豁免名单不得失效（防止白名单悄悄空转）', () => {
  const off = offGridSpacing();
  const keys = new Set(off.map((o) => o.key));
  for (const k of DERIVED) {
    assert.ok(
      keys.has(k),
      `豁免项已不再离格（或选择器/声明改了）：${k} —— 请从 DERIVED 中删掉，别留死豁免`,
    );
  }
});

test('批 97 归一的 8 个代表性离格值不得回潮', () => {
  const src = [];
  for (const f of walk(SRC)) if (f.endsWith('.vue')) src.push(readFileSync(f, 'utf8'));
  const all = stripComments(src.join('\n'));
  const anchors = [
    'margin-bottom: 18px',
    'margin-top: 5px',
    'padding: 3px 8px',
    'padding: 32px 28px',
    'padding: 16px 18px',
    'padding: 14px 20px',
    'gap: 14px',
    'padding: 11px 20px',
    'gap: 9px',
    'padding: 13px 16px',
    'padding: 12px 14px',
  ];
  const back = anchors.filter((a) => all.includes(a));
  assert.deepEqual(back, [], `已归一掉的离格值又回来了：${back.join(' / ')}`);
});

test('判据自检：能识别离格值、放过刻度值与令牌', () => {
  const probe = (decl) => {
    const fake = `.x { ${decl} }`;
    const clean = stripComments(fake);
    for (const rule of clean.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
      for (const d of rule[2].matchAll(/([a-z-]+)\s*:\s*([^;{}]+)/g)) {
        if (!SPACING_PROPS.test(d[1])) continue;
        for (const px of d[2].matchAll(/(?<![\w-])(\d+)px/g)) {
          if (!ON_GRID.includes(Number(px[1]))) return true;
        }
      }
    }
    return false;
  };
  assert.equal(probe('gap: 9px'), true, '9px 应判为离格');
  assert.equal(probe('gap: 8px'), false, '8px 应在刻度上');
  assert.equal(probe('gap: var(--sp-4)'), false, '令牌应放过');
  assert.equal(probe('padding: 12px var(--ds-space-4)'), false, '混合写法应放过');
  assert.equal(probe('border-width: 1px'), false, '非间距属性不参与判定');
});
