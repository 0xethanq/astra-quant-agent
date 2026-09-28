/**
 * 键值行：单一事实源 `.kv-row`（批 90）。
 *
 * ## 实测到的漂移（跨文件近似规则聚类）
 *
 * 把全站 405 条「≥4 条声明」的页面级规则两两比对（同属性同值 / 并集），
 * 找出相似度 ≥0.8 的跨文件簇。其中一个簇里 **5 条规则其实是同一个组件** ——
 * 除 `padding` 外**逐字节相同**：
 *
 *   `display:flex; align-items:center; justify-content:space-between;
 *    gap: var(--ds-space-3); border-bottom: 1px solid var(--ds-color-border-default)`
 *
 * | 规则 | padding | 实测行高 |
 * |---|---|---|
 * | `.ag-kv-row`（AgentsPage，11 个元素） | 10px 16px | 40px |
 * | `.ab-comp`（AboutPage，3 个） | 10px 16px | 40px |
 * | `.bk-kv-row`（BackupPage，2 个） | **12px** 16px | **44px** ← 离群 |
 * | `.ps-history-row`（PromptStudioPage，5 个） | **10px 0** | — |
 *
 * 同一个组件在四个页面渲染出 **36 / 40 / 44** 三种行高。
 * 收口为原件 `.kv-row`（多数决 10px / 16px：16 个可见元素里 14 个已是此值），
 * `.bk-kv-row` 的 12px 一并对齐 → 实测改后所有 `.kv-row` 都是 `10px 16px`。
 *
 * 两个**真正的形态差异**保留为 delta（不是漂移）：
 *   · `.vc-env`：凭证卡内更紧凑（8/12，36px）；
 *   · `.ps-history-row`：历史行左右贴边（外侧容器已有横向内边距），实测 10px 0。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const COMPONENTS_CSS = path.join(SRC, 'styles', 'components.css');

/** `.kv-row` 的规范取值。 */
export const KV_ROW_PROPS = [
  'display: flex;',
  'align-items: center;',
  'justify-content: space-between;',
  'gap: var(--ds-space-3);',
  'padding: 10px var(--ds-space-4);',
  'border-bottom: 1px solid var(--ds-color-border-default);',
];

/** 挂 `.kv-row` 的模板清册（数量不符即翻红）。 */
export const KV_ROW_USERS = {
  'views/admin/AgentsPage.vue': 3,
  'views/admin/AboutPage.vue': 5,
  'views/admin/BackupPage.vue': 2,
  'views/admin/PromptStudioPage.vue': 1,
  'views/admin/llm/ProviderDetailView.vue': 5,
  // 2026-10：多交易所凭证卡删除后，其键值行随 OKX 凭证区迁入 SecurityPage
  'views/admin/SecurityPage.vue': 1,
};

/** 允许保留的形态 delta（值=理由）。它们只许写 padding，不许再抄整份形状。 */
export const KV_DELTAS = {
  '.ps-history-row': { reason: '历史行左右贴边（外侧容器已有横向内边距）', padding: 'padding: 10px 0;' },
};

/** 键值行的「非 padding 形状」指纹。 */
const SHAPE = {
  display: 'flex',
  'align-items': 'center',
  'justify-content': 'space-between',
  'border-bottom': '1px solid var(--ds-color-border-default)',
};
/**
 * ⚠️ 指纹里**故意不含 gap**：`.pd-kv-row` 正是靠 `gap: var(--ds-space-4)`（而非
 * 原件的 `--ds-space-3`）逃过了前一版判据 —— 只差一个属性就不算「同形状」，
 * 于是又一个键值行漏网。gap 与 padding 一并纳入「必须与原件一致」的取值检查。
 */
export const KV_ROW_SPACING = { gap: 'var(--ds-space-3)', padding: '10px var(--ds-space-4)' };

/**
 * 形状相同但**不是**键值行的（值=理由）。
 * 判据只按 CSS 形状匹配，叫「flex 行 + 底分隔线」的还有表头与卡片列表行 —— 逐个登记。
 */
export const NOT_KV = {
  '.pol-arc': '归档卡片行：主体是 .pol-arc-main 块 + 操作区，且带 hover 过渡（可点列表项），不是标签-值行',
};

/** 键值行必须有**纵向**内边距：表头/工具条通常是 `padding: 0 …` + 固定高度。 */
export function hasVerticalPadding(decls) {
  const pad = decls.padding;
  if (!pad) return false;
  const first = pad.trim().split(/\s+/)[0];
  return first !== '0' && first !== '0px';
}

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

/** 剥注释。`//` 用 (?<!:) 保护 https:// —— 本会话已踩 5 次。 */
export function stripComments(text) {
  return text
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(?<!:)\/\/[^\n]*/g, '');
}

/** 解析 `<style>` 里的规则。 */
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
    out.push({ selector: r[1].trim().split('\n').pop().trim(), line: css.slice(0, r.index).split('\n').length, decls });
  }
  return out;
}

/** 这条规则的「非 padding 形状」是否等于键值行。 */
export function isKvShaped(decls) {
  return Object.entries(SHAPE).every(([k, v]) => decls[k] === v);
}

test('.kv-row 原件必须存在且六条取值齐全', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  const m = css.match(/\.kv-row\s*\{([^}]*)\}/);
  assert.ok(m, 'components.css 里找不到 .kv-row');
  for (const p of KV_ROW_PROPS) {
    assert.ok(m[1].includes(p), `.kv-row 缺少 ${p}`);
  }
});

test('末行不画底边框必须由原件提供（4 页各自写过，改类名时丢过一次）', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  assert.match(
    css,
    /\.kv-row:last-child\s*\{[^}]*border-bottom:\s*0/,
    '.kv-row:last-child { border-bottom: 0 } 不见了 —— 末行会多出一条封口线',
  );
  // 各页不得再各自写一遍
  const bad = [];
  for (const f of vueFiles(SRC)) {
    const rel = path.relative(SRC, f);
    for (const r of styleRules(readFileSync(f, 'utf8'))) {
      if (/:last-child$/.test(r.selector) && r.decls['border-bottom'] === '0' && /(kv-row|history-row)/.test(r.selector)) {
        bad.push(`${rel} ${r.selector}`);
      }
    }
  }
  assert.deepEqual(bad, [], `末行规则应由原件提供，不该各页再写：\n  ${bad.join('\n  ')}`);
});

test('必须挂 .kv-row（清册逐文件钉数量）', () => {
  const bad = [];
  let total = 0;
  for (const [rel, expected] of Object.entries(KV_ROW_USERS)) {
    const text = readFileSync(path.join(SRC, rel), 'utf8');
    const actual = (text.match(/class="[^"]*\bkv-row\b[^"]*"/g) || []).length;
    total += actual;
    if (actual !== expected) bad.push(`${rel} 应挂 ${expected} 处 kv-row，实测 ${actual} 处`);
  }
  assert.deepEqual(bad, [], `键值行丢了 .kv-row：\n  ${bad.join('\n  ')}`);
  assert.equal(total, 17, `全站键值行模板实例应为 17 个（批 90 为 17；2026-10 凭证卡删除但键值行迁入 SecurityPage，总数不变），实测 ${total} 个`);
});

test('被收口的旧类名（ag-kv-row / bk-kv-row / ab-kv-row / ab-comp）都不得回潮', () => {
  const bad = [];
  for (const f of vueFiles(SRC)) {
    const text = stripComments(readFileSync(f, 'utf8'));
    const rel = path.relative(SRC, f);
    for (const old of ['ag-kv-row', 'bk-kv-row', 'ab-kv-row', 'pd-kv-row', 'ab-comp"']) {
      if (text.includes(old)) bad.push(`${rel} 又出现 ${old}`);
    }
  }
  assert.deepEqual(bad, [], `已收口的键值行类名回潮：\n  ${bad.join('\n  ')}`);
});

test('各页不得再自造「键值行形状」的规则（未登记的 padding 一律翻红）', () => {
  const bad = [];
  for (const f of vueFiles(SRC)) {
    const rel = path.relative(SRC, f);
    for (const r of styleRules(readFileSync(f, 'utf8'))) {
      if (!isKvShaped(r.decls)) continue;
      if (NOT_KV[r.selector]) continue;
      // 表头/工具条：`padding: 0 …` + 固定高度，纵向没有内边距
      if (!hasVerticalPadding(r.decls)) continue;
      const delta = KV_DELTAS[r.selector];
      if (delta) {
        // delta 只许写 padding —— 不许把整份形状再抄一遍
        const extra = Object.keys(r.decls).filter((k) => k !== 'padding');
        if (extra.length) bad.push(`${rel}:${r.line} ${r.selector} 是 delta，却多写了 ${extra.join('/')}（应交给 .kv-row）`);
        else if (r.decls.padding !== delta.padding) bad.push(`${rel}:${r.line} ${r.selector} 的 padding 与登记不符：${r.decls.padding}`);
        continue;
      }
      bad.push(`${rel}:${r.line} ${r.selector} → gap ${r.decls.gap} / padding ${r.decls.padding}（与原件 ${KV_ROW_SPACING.gap} / ${KV_ROW_SPACING.padding} 不同，且未登记）`);
    }
  }
  assert.deepEqual(
    bad,
    [],
    `又出现自造的键值行规则（应改用 .kv-row，或在 KV_DELTAS 登记形态 delta）：\n  ${bad.join('\n  ')}`,
  );
});

test('闸自检：形状判据认全五项、拒绝缺项与不同取值', () => {
  const good = { ...SHAPE, padding: '10px var(--ds-space-4)' };
  assert.equal(isKvShaped(good), true);
  // gap 不在指纹里 —— 正因如此 .pd-kv-row（gap 16px）才会被判成键值行
  assert.equal(isKvShaped({ ...good, gap: 'var(--ds-space-4)' }), true, 'gap 不同仍应被判成键值行（gap 由取值检查负责）');
  const { 'border-bottom': bb, ...noBorder } = good;
  assert.equal(isKvShaped(noBorder), false, '没有底边框不该被判成键值行');
  assert.equal(isKvShaped({ ...good, 'justify-content': 'flex-end' }), false, 'justify-content 不同不该被判成键值行');
  assert.equal(isKvShaped({ ...good, 'border-bottom': '0' }), false, '没有底边框不该被判成键值行');
  // 注释里的样例行不得被解析
  assert.equal(styleRules('<style>/* .x { display: flex; } */</style>').length, 0);
  // 表头（纵向无内边距）不得被判成键值行
  assert.equal(hasVerticalPadding({ padding: '0 var(--ds-space-3)' }), false, 'padding: 0 … 是表头/工具条');
  assert.equal(hasVerticalPadding({ padding: '10px 0' }), true, 'padding: 10px 0 是贴边键值行，纵向有内边距');
});
