/**
 * 卡体内「标题下的说明行」：单一事实源（批 88）。
 *
 * ## 实测到的漂移
 *
 * 用「同属性集跨文件比对」扫全站页面 CSS，发现 7 条规则共享同一组属性
 * `{color, font-size, line-height, margin-top}` —— 即「标题下的一句说明」。
 * 其中三条是**同一个角色**（`<p>` 紧跟标题 / `</header>` 之后）：
 *
 * | 规则 | margin-top | font-size | line-height | color |
 * |---|---|---|---|---|
 * | `.nf-cat-desc`（NotifyPage） | 4px | `--text-3xs` | `leading-body` | `text-description` |
 * | `.pl-policy-desc`（PluginsPage） | 4px | `--text-3xs` | `leading-body` | `text-description` |
 * | `.ps-dict-desc`（PromptStudioPage） | **6px** | `--text-3xs` | `leading-body` | `text-description` |
 *
 * 前两条**逐字节相同**，第三条只差 `margin-top`（6px vs 4px）——
 * 同一个说明行在三个页面里两套取值。现收口为 `styles/components.css` 的 `.panel-desc`，
 * 取值取多数决（4px），三页改挂原件。
 *
 * ## 与既有 `.card-sub` / `.page-desc` 的分工（不是重复）
 *
 * | 原件 | 位置 | font-size | color | margin-top | line-height |
 * |---|---|---|---|---|---|
 * | `.card-sub` / `.section-desc` | `.card-head` 副标题 | `--text-3xs` | `text-placeholder` | 2px | `leading-dense`(1.45) |
 * | `.page-head .page-desc` | 页头说明 | `--text-xs` | `text-description` | 4px | — |
 * | **`.panel-desc`** | **卡体正文区说明** | `--text-3xs` | `text-description` | **4px** | `leading-body`(1.6) |
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const COMPONENTS_CSS = path.join(SRC, 'styles', 'components.css');

/** `.panel-desc` 的规范取值。 */
export const PANEL_DESC_PROPS = [
  'margin-top: 4px;',
  'font-size: var(--text-3xs);',
  'line-height: var(--leading-body);',
  'color: var(--ds-color-text-description);',
];

/** 使用 `.panel-desc` 的模板清册（数量不符即翻红）。 */
export const PANEL_DESC_USERS = {
  'views/admin/NotifyPage.vue': 1,
  'views/admin/PromptStudioPage.vue': 1,
  'views/admin/RiskPage.vue': 2,
};

/**
 * 允许各页自留「说明行形状」的例外（键=选择器，值=理由）。
 * 这些是**语义 delta**（警告色 / 更醒目字号），不是同一角色的重复实现。
 */
export const DESC_SHAPE_ALLOWED = {
  '.cn-macro p': '宏观解读段：刻意用 --text-xs 与 text-primary（比普通说明更醒目）',
  '.evo-verdict p': '自进化结论段：刻意用 --text-xs 与 text-secondary',
  '.evo-failure-note': '自进化**复盘失败横幅**内的说明行：与 .evo-verdict p 同形但属错误语义块（横幅已由 .evo-failure 给出 --down-* 边框/底色），不是卡体普通说明',
  '.gw-warn': '网关告警行：语义色 var(--warn) + 12px 间距（告警块需要更大分隔）',
  '.ph-desc': '页头说明（PageHeader 组件，70 处引用）：刻意用 --text-xs(12px) + max-width 80ch，属页头层级而非卡体说明',
  '.sc-note': '安全页提示块：带 border-top + padding-top 的独立块（不是一行说明），间距 16px 是分隔需要',
};

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

/** 剥注释（HTML / 块 / 行）。`//` 用 (?<!:) 保护 https:// —— 本会话已踩 5 次。 */
export function stripComments(text) {
  return text
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(?<!:)\/\/[^\n]*/g, '');
}

/** 解析 <style> 块里的规则，返回 {选择器, 行号, 声明表}。 */
export function styleRules(source) {
  const css = stripComments(source);
  const m = /<style[^>]*>([\s\S]*)<\/style>/.exec(css);
  if (!m) return [];
  const body = m[1];
  const out = [];
  for (const r of body.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const decls = {};
    for (const d of r[2].split(';')) {
      if (!d.includes(':')) continue;
      const i = d.indexOf(':');
      decls[d.slice(0, i).trim()] = d.slice(i + 1).trim();
    }
    out.push({
      selector: r[1].trim().split('\n').pop().trim(),
      line: css.slice(0, m.index + 7 + r.index).split('\n').length,
      decls,
    });
  }
  return out;
}

/** 「说明行形状」：同时含 margin-top / font-size / line-height / color，且字号是说明档。 */
export function isDescShaped(decls) {
  const need = ['margin-top', 'font-size', 'line-height', 'color'];
  if (!need.every((k) => k in decls)) return false;
  return /^var\(--text-(3xs|xs)\)$/.test(decls['font-size']);
}

test('.panel-desc 原件必须存在且四条取值齐全', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  const m = css.match(/\.panel-desc\s*\{([^}]*)\}/);
  assert.ok(m, 'components.css 里找不到 .panel-desc');
  for (const p of PANEL_DESC_PROPS) {
    assert.ok(m[1].includes(p), `.panel-desc 缺少 ${p}`);
  }
});

test('三页必须挂 .panel-desc（清册逐文件钉数量）', () => {
  const bad = [];
  let total = 0;
  for (const [rel, expected] of Object.entries(PANEL_DESC_USERS)) {
    const text = readFileSync(path.join(SRC, rel), 'utf8');
    const actual = (text.match(/class="[^"]*\bpanel-desc\b[^"]*"/g) || []).length;
    total += actual;
    if (actual !== expected) bad.push(`${rel} 应挂 ${expected} 处 panel-desc，实测 ${actual} 处`);
  }
  assert.deepEqual(bad, [], `说明行丢了 .panel-desc：\n  ${bad.join('\n  ')}`);
  // 2026-09-30 后台精简：内置插件清单页（PluginsPage）删除，其 1 处 .panel-desc 随之移除（5 → 4）。
  assert.equal(total, 4, `全站说明行实例应为 4 个（批 88 并入 RiskPage 2 处；2026-09-30 删 PluginsPage 1 处），实测 ${total} 个`);
});

test('被收口的三个旧类名不得回潮', () => {
  const bad = [];
  for (const f of vueFiles(SRC)) {
    const text = stripComments(readFileSync(f, 'utf8'));
    for (const old of ['nf-cat-desc', 'pl-policy-desc', 'ps-dict-desc', 'rk-row-desc']) {
      if (text.includes(old)) bad.push(`${path.relative(SRC, f)} 又出现 .${old}`);
    }
  }
  assert.deepEqual(bad, [], `已收口的说明行类名回潮：\n  ${bad.join('\n  ')}`);
});

test('各页不得再自造「说明行形状」的规则（未登记者一律翻红）', () => {
  const bad = [];
  for (const f of vueFiles(SRC)) {
    const rel = path.relative(SRC, f);
    for (const r of styleRules(readFileSync(f, 'utf8'))) {
      if (!isDescShaped(r.decls)) continue;
      if (DESC_SHAPE_ALLOWED[r.selector]) continue;
      bad.push(`${rel}:${r.line} ${r.selector} → ${r.decls['font-size']} / ${r.decls.color} / mt ${r.decls['margin-top']}`);
    }
  }
  assert.deepEqual(
    bad,
    [],
    `又出现自造的说明行规则（应改用 .panel-desc，或在 DESC_SHAPE_ALLOWED 登记语义 delta）：\n  ${bad.join('\n  ')}`,
  );
});

test('闸自检：形状判据认全四条、拒绝缺项与无关字号', () => {
  const good = { 'margin-top': '4px', 'font-size': 'var(--text-3xs)', 'line-height': 'var(--leading-body)', color: 'var(--ds-color-text-description)' };
  assert.equal(isDescShaped(good), true);
  // 缺 color → 不是说明行
  const { color, ...noColor } = good;
  assert.equal(isDescShaped(noColor), false, '缺 color 不该被判成说明行');
  // 字号不在说明档 → 不是说明行
  assert.equal(isDescShaped({ ...good, 'font-size': 'var(--text-md)' }), false, '--text-md 不该被判成说明行');
  // 剥注释：注释里的样例行不得被当成真规则
  assert.equal(styleRules('<style>/* .x { margin-top: 4px; } */</style>').length, 0, '注释里的规则不该被解析');
  assert.equal(styleRules('<style>// .y { margin-top: 4px; }</style>').length, 0, '行注释里的规则不该被解析');
  // 真规则要被解析出来
  assert.equal(styleRules('<style>.z { margin-top: 4px; color: red; }</style>').length, 1);
});

test('已删的死 CSS `.page-head` 家族不得回潮（批 88 实测全站零引用）', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  for (const sel of ['.page-head', '.page-desc', '.page-actions']) {
    assert.ok(
      !new RegExp(`\\${sel}\\s*[,{]`).test(css),
      `components.css 又出现死 CSS ${sel}（页头由 PageHeader.vue 提供）`,
    );
  }
  // 也确认没人悄悄用起来（若将来要用，本断言会先提醒去审核）
  for (const f of vueFiles(SRC)) {
    const text = stripComments(readFileSync(f, 'utf8'));
    assert.ok(
      !/class="[^"]*\bpage-(head|desc|actions)\b/.test(text),
      `${path.relative(SRC, f)} 引用了已删的 .page-head 家族`,
    );
  }
});

test('闸自检：说明行清册与形状判据一致（不会把 .panel-desc 自身当成违规）', () => {
  // .panel-desc 在 components.css 里，不在 .vue 内，故形状判据不该扫到它
  const hits = styleRules('<style>.x { margin-top: 4px; font-size: var(--text-3xs); line-height: var(--leading-body); color: var(--ds-color-text-description); }</style>');
  assert.equal(hits.length, 1);
  assert.equal(isDescShaped(hits[0].decls), true, '样例应被判成说明行形状');
});
