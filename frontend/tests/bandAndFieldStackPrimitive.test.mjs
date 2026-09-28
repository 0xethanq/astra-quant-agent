/**
 * 统计带（band）与表单字段栈（field-stack）收口为单一原件（批 81）。
 *
 * ## A. `band`：14 个文件的 block 逐字节相同
 *
 * 每个后台页都有一块 `<section class="card X-band">`，其样式是**同一个响应式网格**：
 *
 *     1 列 → ≥640px 2 列 → ≥1280px 4 列
 *
 * 14 个文件的 block **逐字节相同**，共 **42 条规则**（每文件 base + 2 个断点）。
 * `RiskPage` 的 `.rk-band` 是**另一种刻度**（1 → 2 → 3 → 6 列，因为它有 6 个统计格），
 * 故显式豁免 —— 并入会改它的视觉。
 *
 * ## B. `field-stack`：12 个文件同形，但漂移出三种写法
 *
 * `<label class="X-field">` 是「标签 + 输入」的竖排栈。实测：
 *
 * | 属性 | 分布 |
 * |---|---|
 * | `gap` | **6px × 10 个文件** ／ 8px × 2 个文件 |
 * | `min-width: 0` | **只有 6 个文件有**，另 6 个**没有** |
 *
 * 缺 `min-width: 0` 的字段在 flex/grid 父级里**无法收缩**，长内容（长模型名、
 * 长 URL）会顶破容器 —— 与批 80 的「加载图标缺 `shrink-0`」属同一类
 * 「flex 子项不收缩」缺陷。取多数且更紧凑的 6px（与既有 `--sp-3` 刻度一致）
 * 并把 `min-width: 0` 补齐。
 *
 * `ProviderListView` 的 `.pv-field` 是**面板**（带 `.pv-field-head` / `-row`），
 * 不是表单字段，故豁免。
 *
 * ## 保留的页面 delta / 复合选择器（不是漏删）
 *
 *   - `.dz-field { flex: 1 }`（DangerZone）—— 原件不含 `flex`；
 *   - `.ip-field + .ip-field`（InterceptorsPage）—— 相邻字段的上间距，仅本页要；
 *   - `.nf-field.is-span`（NotifyPage）—— 跨列变体；
 *   - `.me-field .field.is-readonly`（ModelEditDialog）—— 只读态微调；
 *   - `.pd-field-hint` / `.pv-field*` —— 别的类，名字里带 `field` 而已。
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

/** 允许自带 band 规则的页面（另一种刻度或另一种组件）。 */
export const BAND_EXEMPT = {
  'views/admin/RiskPage.vue': '.rk-band 是 1→2→3→6 列（6 个统计格），与默认 1→2→4 不同刻度',
};

/** 允许保留的 field 规则（页面 delta / 复合选择器），值=理由。 */
export const FIELD_ALLOWED = {
  '.dz-field': 'danger 区字段需要 flex: 1（原件不含 flex）',
  '.ip-field + .ip-field': '相邻字段上间距，仅本页需要',
  '.nf-field.is-span': '跨列变体',
  '.me-field .field.is-readonly': '只读态微调',
  '.pd-field-hint': '另一个类（提示文字）',
  '.pv-field': 'ProviderListView 的面板容器（带 -head/-row 子元素），不是表单字段',
  '.pv-field-head': 'ProviderListView 面板的标题行，属该面板而非字段栈',
  '.pv-field-row': 'ProviderListView 面板的内容行，属该面板而非字段栈',
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
  text: readFileSync(f, 'utf8'),
}));
const cssOf = (t) => (t.match(/<style[^>]*>([\s\S]*?)<\/style>/) || [null, ''])[1];

test('.band 原件：1 列 → 640px 2 列 → 1280px 4 列', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  assert.match(css, /\.band\s*\{\s*display: grid;\s*grid-template-columns: 1fr;/, '缺 .band 基座');
  assert.match(css, /@media \(min-width: 640px\)[\s\S]{0,120}\.band\s*\{\s*grid-template-columns: repeat\(2, minmax\(0, 1fr\)\);/, '缺 640px 两列');
  assert.match(css, /@media \(min-width: 1280px\)[\s\S]{0,120}\.band\s*\{\s*grid-template-columns: repeat\(4, minmax\(0, 1fr\)\);/, '缺 1280px 四列');
});

test('页面不得再自带 band 规则（原件已覆盖；例外须登记）', () => {
  const bad = [];
  for (const { rel, text } of FILES) {
    if (BAND_EXEMPT[rel]) continue;
    const css = cssOf(text);
    for (const m of css.matchAll(/^[ \t]*\.([a-z]{2,4})-band\b/gm)) {
      bad.push(`${rel} :: .${m[1]}-band`);
    }
  }
  assert.deepEqual(bad, [], `以下页面仍自带 band 规则：\n  ${bad.join('\n  ')}`);
});

test('统计带模板必须用 `card band`（15 处基线）', () => {
  const bad = [];
  let n = 0;
  for (const { rel, text } of FILES) {
    if (BAND_EXEMPT[rel]) continue; // RiskPage 用的是自己的刻度，不属本原件
    const tpl = text.includes('<style') ? text.slice(0, text.indexOf('<style')) : text;
    for (const m of tpl.matchAll(/class="([^"]*)"/g)) {
      const cls = m[1].split(/\s+/);
      if (!cls.some((c) => /^[a-z]{2,4}-band$/.test(c))) continue;
      bad.push(`${rel} :: ${m[1]}`);
    }
    n += (tpl.match(/class="card band"/g) || []).length;
  }
  assert.deepEqual(bad, [], `统计带仍用页面前缀类：\n  ${bad.join('\n  ')}`);
  assert.equal(n, 15, `\`card band\` 应为 15 处，实测 ${n}`);
});

test('.field-stack 原件：竖排 + gap 6px + min-width: 0', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  const m = css.match(/\.field-stack\s*\{([^}]*)\}/);
  assert.ok(m, 'components.css 缺少 .field-stack');
  for (const p of ['display: flex;', 'flex-direction: column;', 'gap: 6px;', 'min-width: 0;']) {
    assert.ok(m[1].includes(p), `.field-stack 缺少 ${p}`);
  }
  // min-width: 0 是本批修的缺陷（6 个文件原先没有），必须留在原件里
  assert.match(m[1], /min-width: 0;/, 'min-width: 0 丢失 —— 字段在 flex 父级里会无法收缩');
});

test('页面不得再自带 field-stack 基座规则（保留的 delta 须登记）', () => {
  const bad = [];
  for (const { rel, text } of FILES) {
    const css = cssOf(text);
    for (const m of css.matchAll(/^[ \t]*(\.[a-z]{2,4}-field)\s*\{([^{}]*)\}/gm)) {
      const sel = m[1];
      if (FIELD_ALLOWED[sel]) continue;
      // 基座规则的签名：竖排 + gap + （可选）min-width
      if (/flex-direction: column/.test(m[2]) && /gap:/.test(m[2])) {
        bad.push(`${rel} :: ${sel}`);
      }
    }
  }
  assert.deepEqual(bad, [], `以下页面仍自带字段栈基座规则：\n  ${bad.join('\n  ')}`);
});

test('字段栈模板用法必须在白名单内（防漂移出新写法）', () => {
  const counts = new Map();
  let total = 0;
  for (const { text } of FILES) {
    const tpl = text.includes('<style') ? text.slice(0, text.indexOf('<style')) : text;
    for (const m of tpl.matchAll(/class="([^"]*)"/g)) {
      const cls = m[1].split(/\s+/);
      if (!cls.includes('field-stack')) continue;
      total += 1;
      counts.set(m[1], (counts.get(m[1]) || 0) + 1);
    }
  }
  const allowed = new Set([
    'field-stack',
    'field-stack me-field',
    'field-stack ip-field',
    'field-stack nf-field',
    'field-stack nf-field is-span',
    'field-stack dz-field',
  ]);
  const bad = [...counts.keys()].filter((k) => !allowed.has(k));
  assert.deepEqual(bad, [], `出现未登记的字段栈写法：\n  ${bad.join('\n  ')}`);
  // 2026-10：SecurityPage 的凭证区随「全站收口 OKX」精简（去掉 Binance/Gate
  // 两组字段），field-stack 实例由 44 降为 42。
  assert.equal(total, 42, `field-stack 实例应为 42 个，实测 ${total}`);
});

test('豁免/白名单必须都有理由，且文件真实存在', () => {
  for (const [rel, why] of Object.entries(BAND_EXEMPT)) {
    assert.ok(statSync(path.join(SRC, rel)).isFile(), `豁免的 ${rel} 不存在`);
    assert.ok(why.length > 8, `豁免 ${rel} 缺少理由`);
  }
  for (const [sel, why] of Object.entries(FIELD_ALLOWED)) {
    assert.ok(why.length >= 4, `白名单 ${sel} 缺少理由`); // 中文四字已足够说明
  }
  assert.ok(Object.keys(BAND_EXEMPT).length <= 2, 'band 豁免名单过长');
  assert.ok(Object.keys(FIELD_ALLOWED).length <= 9, 'field 白名单过长');
});

test('闸自检：识别 band/field 基座规则，不误伤 delta 与同名字段', () => {
  const band = '.ab-band {\n  display: grid;\n  grid-template-columns: 1fr;\n}';
  assert.equal([...band.matchAll(/^[ \t]*\.([a-z]{2,4})-band\b/gm)].length, 1);
  // 不误伤：`band` 原件本身没有页面前缀
  assert.equal([...'.band {\n  display: grid;\n}'.matchAll(/^[ \t]*\.([a-z]{2,4})-band\b/gm)].length, 0);

  const base = '.as-field {\n  display: flex;\n  flex-direction: column;\n  gap:6px;\n  min-width: 0;\n}';
  assert.ok(/flex-direction: column/.test(base) && /gap:/.test(base), '应识别为基座规则');
  const delta = '.dz-field {\n  flex: 1;\n}';
  assert.equal(/flex-direction: column/.test(delta) && /gap:/.test(delta), false, 'delta 不该被当作基座');
  const compound = '.ip-field + .ip-field {\n  margin-top: var(--ds-space-4);\n}';
  assert.equal(/flex-direction: column/.test(compound) && /gap:/.test(compound), false, '复合选择器不该被当作基座');
});
