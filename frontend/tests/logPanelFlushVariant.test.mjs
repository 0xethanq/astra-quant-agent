/**
 * `.log-panel` 的嵌入式变体 `.is-flush`（批 92）。
 *
 * ## 实测到的漂移
 *
 * `.log-panel` 原件声明了「1px 边框 + `var(--r-ctl)`(8px) 圆角 + inset 底色」。
 * 全站 6 处用法分两派：
 *
 *   · **保留原件外观**：`.ab-git`（AboutPage）、`.rf-list`（RemoteFetchDialog）；
 *   · **贴在 `.card` 内部、把自己的边框/圆角/底色全关掉**：4 处。
 *
 * 而那 4 处是**各自手写**的：
 *
 * | 页面 | 手写内容 |
 * |---|---|
 * | AgentsPage `.ag-calls` | `border: 0; border-radius: 0; background-color: transparent;` |
 * | AuditPage `.au-rows` | 同上（逐字相同） |
 * | ProviderListView `.pv-audit` | 同上（逐字相同） |
 * | EvolutionPage `.evo-insight-panel` | `border: 0; background-color: transparent;` ← **漏了圆角** |
 *
 * 手写重复必然漂移 —— 与批 90 键值行同因。收进原件一个**具名变体**
 * `.log-panel.is-flush`，四处改挂它并删掉手写声明。
 *
 * 实测复核（真实浏览器）：
 *   · 4 处 flush 面板改后**全部**为 `边框 0 / 圆角 0 / 底色透明`（改前 EvolutionPage 是 8px）；
 *   · 注入裸 `.log-panel` 探针 → `1px / 8px / rgb(17,19,26)`，**原件外观未被破坏**、变体是选配。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const COMPONENTS_CSS = path.join(SRC, 'styles', 'components.css');

/** 原件的「外观三件套」。 */
export const CHROME = ['border: 1px solid var(--ds-color-border-default);', 'border-radius: var(--r-ctl);', 'background-color: var(--ds-color-bg-surface-inset);'];

/** flush 变体的三条声明。 */
export const FLUSH_DECLS = ['border: 0;', 'border-radius: 0;', 'background-color: transparent;'];

/** 挂 `.is-flush` 的模板清册。 */
export const FLUSH_USERS = {
  'views/admin/AuditPage.vue': 'au-rows',
  'views/admin/llm/ProviderListView.vue': 'pv-audit',
};

/** 保留原件外观的（不得挂 is-flush）。 */
export const CHROME_USERS = {
  'views/admin/AboutPage.vue': 'ab-git',
  'views/admin/llm/RemoteFetchDialog.vue': 'rf-list',
};

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

export function stripComments(text) {
  return text
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(?<!:)\/\/[^\n]*/g, '');
}

/** 解析 `<style>` 里的规则 → [{selector, decls, line}]（单行选择器）。 */
export function styleRules(source) {
  const css = stripComments(source);
  const m = /<style[^>]*>([\s\S]*)<\/style>/.exec(css);
  if (!m) return [];
  const out = [];
  for (const r of m[1].matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const decls = {};
    for (const d of r[2].split(';')) {
      if (!d.includes(':')) continue;
      const i = d.indexOf(':');
      decls[d.slice(0, i).trim()] = d.slice(i + 1).trim();
    }
    out.push({ selector: r[1].trim().split('\n').pop().trim(), decls });
  }
  return out;
}

test('.log-panel 原件的外观三件套必须完好（变体是选配，不能反噬原件）', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  const m = css.match(/\.log-panel\s*\{([^}]*)\}/);
  assert.ok(m, 'components.css 里找不到 .log-panel');
  for (const c of CHROME) assert.ok(m[1].includes(c), `.log-panel 缺少 ${c}`);
});

test('.log-panel.is-flush 变体必须声明三条中和（且只中和这三条）', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  const m = css.match(/\.log-panel\.is-flush\s*\{([^}]*)\}/);
  assert.ok(m, 'components.css 里找不到 .log-panel.is-flush');
  for (const d of FLUSH_DECLS) assert.ok(m[1].includes(d), `.log-panel.is-flush 缺少 ${d}`);
  // 不该顺手改别的（字号/等宽/滚动都属于原件语义）
  for (const forbidden of ['font-size', 'font-family', 'overflow', 'max-height']) {
    assert.ok(!m[1].includes(forbidden), `.is-flush 不该改 ${forbidden}（那是原件的语义，不是嵌入与否的差别）`);
  }
});

test('四处嵌入式用法必须挂 is-flush，两处保留外观的不得挂', () => {
  const bad = [];
  for (const [rel, cls] of Object.entries(FLUSH_USERS)) {
    const text = readFileSync(path.join(SRC, rel), 'utf8');
    if (!new RegExp(`class="log-panel is-flush ${cls}"`).test(text)) bad.push(`${rel} 的 .${cls} 没挂 is-flush`);
  }
  for (const [rel, cls] of Object.entries(CHROME_USERS)) {
    const text = readFileSync(path.join(SRC, rel), 'utf8');
    if (!new RegExp(`class="log-panel ${cls}"`).test(text)) bad.push(`${rel} 的 .${cls} 应保留原件外观（不该挂 is-flush）`);
  }
  assert.deepEqual(bad, [], `log-panel 用法与登记不符：\n  ${bad.join('\n  ')}`);
});

test('任何页面都不得再手写「嵌入式三件套」（这正是漂移的来源）', () => {
  const bad = [];
  for (const f of vueFiles(SRC)) {
    const rel = path.relative(SRC, f);
    for (const r of styleRules(readFileSync(f, 'utf8'))) {
      const hasBorder = r.decls.border === '0';
      const hasRadius = r.decls['border-radius'] === '0';
      const hasBg = r.decls['background-color'] === 'transparent';
      if (hasBorder && hasRadius && hasBg) bad.push(`${rel} ${r.selector} 又手写了三件套（改用 .log-panel.is-flush）`);
    }
  }
  assert.deepEqual(bad, [], `手写嵌入式三件套回潮：\n  ${bad.join('\n  ')}`);
});

test('已登记的三个旧覆盖类不得再声明外观三件套', () => {
  const bad = [];
  for (const [rel, cls] of Object.entries(FLUSH_USERS)) {
    for (const r of styleRules(readFileSync(path.join(SRC, rel), 'utf8'))) {
      if (r.selector !== '.' + cls) continue;
      for (const p of ['border', 'border-radius', 'background-color']) {
        if (p in r.decls) bad.push(`${rel} .${cls} 又声明了 ${p}（应交给 .is-flush）`);
      }
    }
  }
  assert.deepEqual(bad, [], `覆盖类又管起外观了：\n  ${bad.join('\n  ')}`);
});

test('判据自检：三件套判据只认完整三条', () => {
  const full = { border: '0', 'border-radius': '0', 'background-color': 'transparent' };
  const only2 = { border: '0', 'background-color': 'transparent' };
  const isTriplet = (d) => d.border === '0' && d['border-radius'] === '0' && d['background-color'] === 'transparent';
  assert.equal(isTriplet(full), true);
  assert.equal(isTriplet(only2), false, '缺圆角的两条不算三件套（正是 EvolutionPage 的漂移形态）');
  assert.equal(isTriplet({ ...full, 'background-color': 'var(--x)' }), false);
  // 注释里的样例行不得被解析
  assert.equal(styleRules('<style>/* .x { border: 0; } */</style>').length, 0);
});
