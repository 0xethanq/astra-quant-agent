/**
 * 内联样式不得绕过设计刻度（批 82）。
 *
 * ## 实测：34 处内联裸 px 绕过 token
 *
 * 全站 276 个内联 `style="…"`，其中 34 个属性值是**裸 px**，而设计系统里
 * 每一个都有对应刻度（`--ds-space-1..4` = 4/8/12/16、`--spacing` = 4px、
 * `--r-pill`、`--r-xs`）。最集中的两处：
 *
 * | 内联值 | 出现 | 实际含义 | 收口为 |
 * |---|---|---|---|
 * | `margin-top: 4px` | **15 处**（重试按钮） | `--ds-space-1` / `--spacing`×1 | Tailwind `mt-1` |
 * | `height: 16px` | **11 处**（骨架「值」行） | `--ds-space-4` | `.skeleton-value` |
 * | `padding: 16px` | 2 处 | `--ds-space-4` | `p-4` |
 * | `width+height: 5px` | 2 处（`.dot` 覆盖） | `.dot` 本是 6px | 去掉覆盖 |
 * | `margin-top: 8/10/12px` | 4 处 | `--ds-space-2` / 2.5× / `-3` | `mt-2` / `mt-2.5` / `mt-3` |
 * | `width+height: 6px` + `50%` | 1 处 | `.dot` 的几何 | `.skeleton-dot` |
 * | `width+height: 24px` + `--r-xs` | 1 处 | 头像几何 | `.skeleton-avatar` |
 *
 * ## 唯一保留：`border-width: 1px`
 *
 * 1px 发丝线是**全站约定** —— `css` 里 `1px solid` 出现 **135 次**，
 * 且 `tokens.css` 另有 `--sp-hair: 1px` 却未被 CSS 采用。故内联里这一处
 * 与其他 CSS 写法一致，不算绕过刻度。
 *
 * ## ⚠️ 本批的验证方式：**真实浏览器实测 computed style**
 *
 * 内联 px → token 类**不能只靠"构建通过"**：Tailwind 的 `mt-1` 是
 * `var(--spacing)` = `.25rem`，而 `rem` 取决于**根字号**；本仓 `html` 未设
 * `font-size`（`body` 才是 13px），故根为浏览器默认 16px、`.25rem` 才是 4px。
 * 这一串推理任一环节变了都会静默改变视觉。
 *
 * 故批 82 把改动注入**正在运行的 app**（:8080 提供的就是本地 `frontend/dist`，
 * 已核对 CSS 资产名一致），逐个读 `getComputedStyle` 与原内联值比对：
 *
 *     mt-1 → 4px ✓   p-4 → 16px ✓   .skeleton-value → 16px ✓
 *     .skeleton-dot → 6px ✓   .skeleton-avatar → 24px ✓
 *     mt-2 → 8px ✓   mt-3 → 12px ✓   mt-2.5 → 10px ✓
 *     .dot → 6px（原 5px，有意统一）
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const COMPONENTS_CSS = path.join(SRC, 'styles', 'components.css');

/** 会吃刻度值的属性 —— 内联写裸 px 即为绕过 token。 */
const SCALED_PROPS = new Set([
  'margin', 'margin-top', 'margin-bottom', 'margin-left', 'margin-right',
  'padding', 'padding-top', 'padding-bottom', 'padding-left', 'padding-right',
  'gap', 'row-gap', 'column-gap', 'width', 'height', 'font-size',
]);

/**
 * 已核实为「与全站 CSS 写法一致」的内联裸 px（值=理由）。
 * 只有 1px 发丝线：`src/**\/*.css` 里 `1px solid` 出现 135 次。
 */
export const INLINE_PX_ALLOWED = {
  'border-width: 1px': '1px 发丝线是全站约定（CSS 里 1px solid 出现 135 次）',
};

/** 骨架形状类（值=应有的尺寸声明）。
 * 2026-11-28 后台 12→6 精简：唯一消费者退役后，零引用 `.skeleton-dot` / `.skeleton-avatar` 已从 components.css 移除。
 */
export const SKELETON_SHAPES = {
  '.skeleton-value': 'height: var(--ds-space-4);',
};

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
  raw: readFileSync(f, 'utf8'),
}));

/** 去掉注释与 `:style` 动态绑定，只留静态 `style="…"`。 */
export function staticInlineStyles(text) {
  const noComment = text
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '');
  return [...noComment.matchAll(/(?<!:)\bstyle="([^"]*)"/g)].map((m) => m[1]);
}

test('内联 style 不得出现未登记的裸 px 值', () => {
  // ⚠️ 判据是「属性值是**纯** px」而非「值里含 px」——
  // `border: 1px solid var(--line-1)` 的 1px 是发丝线、颜色走 token（全站 22 处），
  // 若按「含 px」判就会被误伤。故只拦 `^[\d.]+px$` 这种整值。
  const bad = [];
  const allowedUsed = new Set();

  for (const { rel, raw } of FILES) {
    for (const body of staticInlineStyles(raw)) {
      // ⚠️ matchAll 的每项是 [完整匹配, 组1, 组2, …] —— 必须 `[, prop, val]`。
      // 写成 `[prop, val]` 会把完整匹配当成 prop，白名单永远匹配不上（静默失效）。
      for (const [, prop, val] of body.matchAll(/([a-z-]+)\s*:\s*([^;]*)/g)) {
        if (!/^\s*[\d.]+px\s*$/.test(val)) continue;
        const sig = `${prop}: ${val.trim()}`;
        if (INLINE_PX_ALLOWED[sig]) {
          allowedUsed.add(sig);
          continue;
        }
        bad.push(`${rel} :: ${sig}${SCALED_PROPS.has(prop) ? '  ← 吃刻度的属性' : ''}`);
      }
    }
  }

  assert.deepEqual(
    bad,
    [],
    `以下内联样式用裸 px 绕过设计刻度（应改用 token / Tailwind 刻度类）：\n  ${bad.join('\n  ')}`,
  );
  for (const sig of Object.keys(INLINE_PX_ALLOWED)) {
    assert.ok(allowedUsed.has(sig), `白名单 ${sig} 已无人使用，请删除该条`);
  }
});

test('骨架形状类必须存在（11 处 height:16px 的收口点）', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  for (const [sel, decl] of Object.entries(SKELETON_SHAPES)) {
    const m = css.match(new RegExp(`${sel.replace('.', '\\.')}\\s*\\{([^}]*)\\}`));
    assert.ok(m, `components.css 缺少 ${sel}`);
    assert.ok(m[1].includes(decl), `${sel} 缺少 ${decl}`);
  }
  // 骨架「值」行必须走类，不得回到内联 height
  const bad = [];
  for (const { rel, raw } of FILES) {
    if (/class="skeleton[^"]*"\s+style="[^"]*height:/.test(raw)) bad.push(rel);
  }
  assert.deepEqual(bad, [], `骨架仍用内联 height：\n  ${bad.join('\n  ')}`);
});

test('.dot 尺寸只由原件决定，不得内联覆盖', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  const m = css.match(/\.dot\s*\{([^}]*)\}/);
  assert.ok(m, 'components.css 缺少 .dot');
  assert.ok(m[1].includes('width: 6px;'), '.dot 宽度应为 6px');
  assert.equal((css.match(/^\.dot\s*\{/gm) || []).length, 1, '.dot 应只有一处定义');

  const bad = [];
  for (const { rel, raw } of FILES) {
    for (const m2 of raw.matchAll(/class="([^"]*\bdot\b[^"]*)"\s+style="([^"]*)"/g)) {
      if (/\b(width|height)\s*:/.test(m2[2])) bad.push(`${rel} :: ${m2[1]} style="${m2[2]}"`);
    }
  }
  assert.deepEqual(bad, [], `.dot 被内联改尺寸：\n  ${bad.join('\n  ')}`);
});

test('内联裸 px 的总量基线（防回潮）', () => {
  let n = 0;
  for (const { raw } of FILES) {
    for (const body of staticInlineStyles(raw)) {
      for (const m of body.matchAll(/([a-z-]+)\s*:\s*([^;]*)/g)) {
        if (/^\s*[\d.]+px\s*$/.test(m[2])) n += 1;
      }
    }
  }
  // 批 82 收官时为 1（仅 RadarDrawer 的 border-width: 1px 发丝线）。
  // 留 2 的余量以便合理新增，但一旦超过就必须显式复核。
  assert.ok(n <= 2, `内联裸 px 增至 ${n} 处，请复核是否又有刻度绕过（批 82 收官时为 1）`);
  assert.ok(n >= 1, `内联裸 px 为 0 —— 白名单那条发丝线似乎也消失了，请同步清理白名单`);
});

test('闸自检：识别内联裸 px，不误伤 var()/百分比/动态绑定', () => {
  assert.deepEqual(
    staticInlineStyles('<div style="margin-top: 4px">').map((b) => b),
    ['margin-top: 4px'],
  );
  // 不误伤：var() 与百分比、以及非刻度属性
  const ok = staticInlineStyles('<div style="margin-top: var(--ds-space-1); width: 62%; border-width: 1px">');
  assert.deepEqual(ok, ['margin-top: var(--ds-space-1); width: 62%; border-width: 1px']);
  const props = [...ok[0].matchAll(/([a-z-]+)\s*:\s*([^;]+)/g)];
  const flagged = props.filter(([, v]) => /^\s*[\d.]+px\s*$/.test(v) && SCALED_PROPS.has(props[0][0]));
  assert.deepEqual(flagged, [], 'var()/百分比/非刻度属性不该被拦');
  // 不误伤：`:style` 动态绑定（本闸只看静态 style）
  assert.deepEqual(staticInlineStyles('<div :style="{ height: isFullscreen ? \'100vh\' : \'340px\' }">'), []);
  // 不误伤：注释里的 style
  assert.deepEqual(staticInlineStyles('<!-- <div style="margin-top: 4px"> -->'), []);
  // 白名单生效
  assert.ok(INLINE_PX_ALLOWED['border-width: 1px'], '发丝线白名单应存在');
  // 捕获组索引自检：matchAll 的 [0] 是完整匹配，写成 [prop, val] 会静默失效
  const sample = 'border-width: 1px';
  const got = [...sample.matchAll(/([a-z-]+)\s*:\s*([^;]*)/g)].map(([, p2, v2]) => `${p2}: ${v2.trim()}`);
  assert.deepEqual(got, ['border-width: 1px'], '捕获组索引写错（应为 [, prop, val]）');
  assert.equal(SCALED_PROPS.has('border-width'), false, 'border-width 不该在刻度属性集里');
});
