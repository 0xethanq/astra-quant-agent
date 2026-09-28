/**
 * `aria-controls` 不得指向「被 v-if 摘掉」的元素（批 85 建立，批 86 升级为 AST 判据）。
 *
 * ## 实测：16 处悬空引用（批 85）
 *
 * 用真实浏览器扫可达页面，逐个 `document.getElementById(ref)` 校验，发现
 * **16 处 `aria-controls` 指向不存在的元素** —— 同一成因：**目标用 `v-if` 渲染，
 * 收起时不在 DOM 里**。`BaseTabs.vue` 早就写明了正确做法并留了注释：
 * 「不传则不产出 aria-controls（避免指向不存在的 id）」。7 处照此改为
 * `COND ? ID : undefined`。实测 5 个页面 **16 → 0**。
 *
 * 站点：`BaseStat`（kpi-hint，一个组件贡献 9 处）、`SettingsPopover`、
 * `ChartWorkstation` ×2（币种/指标菜单）、`PromptStudioPage`、`CouncilPage`、`OverviewPage`。
 *
 * ## 批 86：漏网的那一处 —— 条件在**祖先**上
 *
 * 升级到全部 25 条路由（18 个 admin 页 + 7 个公开页）逐一实测后，仍剩 **1 处**：
 * `AdminLayout.vue` 的汉堡按钮 `aria-controls="admin-mobile-drawer"`，
 * 而 `#admin-mobile-drawer` 被包在 `<div v-if="drawerOpen">` 里 ——
 * **`v-if` 不在目标标签自己身上，而在它的祖先上**，所以批 85 只看「标签自身 v-if」的
 * 判据看不见它。本批已修为 `drawerOpen ? 'admin-mobile-drawer' : undefined`。
 *
 * 教训：手写的「往回退、数标签配对深度」的启发式会把**兄弟**当成祖先
 * （实测对 `BaseCollapse` / `DocsView` 等处误报，
 * 而 live 实测这 3 处都没问题）。本批改用 **`@vue/compiler-dom` 真解析器** 建 AST，
 * 沿 parents 走祖先链 —— 只会对真祖先的 `v-if` 报警。
 *
 * ⚠️ 区分 `v-if` 与 `v-show`：`v-show` 只是 `display:none`，元素**仍在 DOM**，
 * 引用不悬空（`BaseCollapse` 就是这种，正确，不该报）。AST 判据天然能区分。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';
import { parse as parseDom } from '@vue/compiler-dom';
import { parse as parseSFC } from '@vue/compiler-sfc';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

/** 允许「目标在 v-if 子树里却仍无条件输出」的例外（值=理由）。本批修完应为空。 */
export const UNGUARDED_ALLOWED = {};

const ELEMENT = 1;
const ATTRIBUTE = 6;
const DIRECTIVE = 7;

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

/**
 * 取 SFC 的 <template> 内容 —— 用 `@vue/compiler-sfc`（权威解析器）。
 * 手写正则不行：SFC 的块顺序可以是 `script → template → style`，
 * 要求 `</template>` 后面跟 `<script` 或 EOF 会直接漏掉带 `<style>` 的文件
 * （实测 `AdminLayout.vue` 就是这样被漏掉的）。
 */
export function templateOf(source, filename = 'x.vue') {
  const { descriptor } = parseSFC(source, { filename });
  return descriptor.template ? descriptor.template.content : null;
}

export function parseTemplate(source, filename = 'x.vue') {
  const tpl = templateOf(source, filename);
  if (tpl === null) return null;
  return parseDom(tpl, { comments: false });
}

/** 属性节点取值：静态属性 / 动态绑定 / 指令表达式。 */
export function attrExpr(node, name) {
  for (const p of node.props || []) {
    if (p.type === ATTRIBUTE && (p.name === name || p.name === ':' + name)) {
      return p.value ? p.value.content : '';
    }
    if (p.type === DIRECTIVE && p.name === 'bind' && p.arg && p.arg.content === name) {
      return p.exp ? p.exp.content : '';
    }
  }
  return null;
}

/** 节点自身的 v-if 条件（v-show 不算 —— 元素仍在 DOM）。 */
export function vIfOf(node) {
  for (const p of node.props || []) {
    if (p.type === DIRECTIVE && p.name === 'if') return p.exp ? p.exp.content : '';
  }
  return null;
}

/** 遍历 AST，回调每个元素节点及其**祖先 v-if 链**（由外到内）。 */
export function walk(node, visit, chain = []) {
  if (node.type === ELEMENT) {
    visit(node, chain);
    const c = vIfOf(node);
    const next = c === null ? chain : chain.concat([c]);
    for (const ch of node.children || []) walk(ch, visit, next);
    return;
  }
  for (const ch of node.children || []) walk(ch, visit, chain);
}

/** 归一化 id 表达式：去掉包裹的引号/反引号。`'x'` → `x`；`` `a-${b}` `` → `a-${b}` */
export function normalizeId(expr) {
  return expr.trim().replace(/^['"`]/, '').replace(/['"`]$/, '').trim();
}

/**
 * 命中目标 id 表达式的候选。
 *
 * ⚠️ 必须**打分取最优**，不能「先命中先返回」：取 `'admin-mobile-drawer'` 时，
 * 文档顺序更靠前的 `admin-desktop-sidebar` 也含 `admin` 子串，先命中就会解析到**错的**目标
 * （批 86 实测：于是 `#admin-mobile-drawer` 的祖先 v-if 被读成空，闸假绿）。
 */
export function matchTarget(byId, targetExpr) {
  if (byId.has(targetExpr)) return byId.get(targetExpr);
  const norm = normalizeId(targetExpr);
  if (byId.has(norm)) return byId.get(norm);
  const toks = (norm.match(/[A-Za-z_$][\w$]*/g) || []).filter((t) => t.length >= 2 && !['undefined', 'String'].includes(t));
  let best = null;
  let bestScore = 0;
  for (const [id, info] of byId) {
    const idNorm = normalizeId(id);
    let score = 0;
    for (const tk of toks) if (idNorm.includes(tk) || tk.includes(idNorm)) score += 1;
    if (score > bestScore) { bestScore = score; best = info; }
  }
  return bestScore > 0 ? best : null;
}

/** 收集一个文件里所有 :aria-controls 绑定与其目标元素。 */
export function controlsSites(rel, source, globalIds = null) {
  const ast = parseTemplate(source, rel);
  if (!ast) return [];

  const byId = new Map();
  walk(ast, (n, chain) => {
    const id = attrExpr(n, 'id');
    if (id === null || id === '') return;
    byId.set(id, { chain, self: vIfOf(n) });
  });
  // 目标可能在**别的文件**里（如 TopBar 控制 DashboardLayout 渲染的侧栏）
  const lookup = (expr) => matchTarget(byId, expr) ?? (globalIds ? matchTarget(globalIds, expr) : null);

  const sites = [];
  const seen = new Set();
  walk(ast, (n, chain) => {
    const expr = attrExpr(n, 'aria-controls');
    if (expr === null) return;
    const q = expr.indexOf('?');
    let targetExpr = expr;
    if (q !== -1) {
      const rest = expr.slice(q + 1);
      const colon = rest.lastIndexOf(':');
      targetExpr = colon === -1 ? rest : rest.slice(0, colon);
    }
    targetExpr = targetExpr.trim();
    const target = lookup(targetExpr);
    // ⚠️ 必须同时算**目标自身**的 v-if 与**祖先**的 v-if：
    //   · 目标自身  → 批 85 的那 7 处（`<p v-if="hint && showHint" :id="hintId">`）
    //   · 祖先      → 批 86 的 AdminLayout（`<div v-if="drawerOpen"><aside id=…>`）
    // 只算祖先会漏掉前者（批 86 实测：漏掉后 M2–M6、M9 五重变异全变假绿）。
    const conds = target ? target.chain.concat(target.self === null ? [] : [target.self]) : null;
    const key = expr + '|' + (conds ? conds.join(',') : '?');
    if (seen.has(key)) return;
    seen.add(key);
    sites.push({
      rel,
      expr,
      guarded: expr.includes('?') && expr.includes('undefined'),
      ancestorChain: target ? target.chain : null,
      vIfConds: conds,
      targetFound: !!target,
      triggerChain: chain,
    });
  });
  return sites;
}

function allSites() {
  const files = vueFiles(SRC).map((f) => ({ rel: path.relative(SRC, f), src: readFileSync(f, 'utf8') }));
  // 全局 id 索引（跨文件引用解析用）
  const globalIds = new Map();
  for (const { rel, src } of files) {
    const ast = parseTemplate(src, rel);
    if (!ast) continue;
    walk(ast, (n, chain) => {
      const id = attrExpr(n, 'id');
      if (id === null || id === '') return;
      if (!globalIds.has(id)) globalIds.set(id, { chain, self: vIfOf(n) });
    });
  }
  const out = [];
  for (const { rel, src } of files) out.push(...controlsSites(rel, src, globalIds));
  return out;
}

test('目标落在 v-if 子树里的 aria-controls，必须做成条件输出', () => {
  const problems = [];
  for (const s of allSites()) {
    if (!s.targetFound) {
      problems.push(`${s.rel} :: ${s.expr} —— 找不到它引用的 id 绑定（无法判定目标是否存在）`);
      continue;
    }
    const inVIf = s.vIfConds.length > 0;
    if (!inVIf) continue;
    if (UNGUARDED_ALLOWED[`${s.rel}::${s.expr}`]) continue;
    const where = s.vIfConds.join(' ∧ ');
    if (!s.guarded) {
      problems.push(`${s.rel} :: ${s.expr}\n      目标在 v-if 子树里（${where}）→ 收起时不在 DOM，引用悬空，应改为「目标存在时才输出」`);
      continue;
    }
    const toks = (where.match(/[A-Za-z_$][\w$]{2,}/g) || []).filter((t) => !['undefined', 'String', 'Boolean'].includes(t));
    if (toks.length && !toks.some((t) => s.expr.includes(t))) {
      problems.push(`${s.rel} :: ${s.expr}\n      守卫条件未引用目标的 v-if 状态（${toks.join('/')}），可能守卫错了目标`);
    }
  }
  assert.deepEqual(problems, [], `aria-controls 悬空引用：\n  ${problems.join('\n  ')}`);
});

test('全站 aria-controls 不得存在「目标在 v-if 子树里却无条件输出」', () => {
  const sites = allSites();
  assert.ok(sites.length >= 15, `识别到的 aria-controls 站点过少（${sites.length}），判据可能失效`);
  const bad = sites.filter((s) => s.targetFound && s.vIfConds.length > 0 && !s.guarded);
  assert.deepEqual(bad.map((s) => `${s.rel} :: ${s.expr}`), []);
});

test('AdminLayout 汉堡按钮：抽屉收起时不得输出 aria-controls（批 86 回归锚点）', () => {
  // 目标的 v-if 在**祖先** <div v-if="drawerOpen"> 上，而不是 <aside> 自己身上 ——
  // 这正是批 85 的「只看标签自身 v-if」判据漏掉它的原因。
  const sites = controlsSites('layouts/AdminLayout.vue', readFileSync(path.join(SRC, 'layouts/AdminLayout.vue'), 'utf8'));
  const burger = sites.find((s) => s.expr.includes('admin-mobile-drawer'));
  assert.ok(burger, '未找到汉堡按钮的 aria-controls');
  assert.equal(burger.guarded, true, '汉堡按钮的 aria-controls 必须条件输出');
  assert.deepEqual(burger.ancestorChain, ['drawerOpen'], '目标应位于 v-if="drawerOpen" 子树中');
  assert.deepEqual(burger.vIfConds, ['drawerOpen'], '综合条件应来自祖先');
});

test('目标**自身**的 v-if 也算数（批 85 的 7 处形态，不得被批 86 的改写丢掉）', () => {
  const sites = controlsSites('components/base/BaseStat.vue', readFileSync(path.join(SRC, 'components/base/BaseStat.vue'), 'utf8'));
  const hint = sites.find((s) => s.expr.includes('hintId'));
  assert.ok(hint, '未找到 BaseStat 的 aria-controls');
  assert.deepEqual(hint.vIfConds, ['hint && showHint'], '目标的自身 v-if 必须计入条件');
  assert.equal(hint.guarded, true);
});

test('判据必须区分 v-if（元素被摘掉）与 v-show（元素仍在 DOM）', () => {
  const vIfSrc = `<template><div v-if="a"><span id="t1" :aria-controls="'t1'"/></div></template>`;
  const vShowSrc = `<template><div v-show="a"><span id="t2" :aria-controls="'t2'"/></div></template>`;
  const s1 = controlsSites('a.vue', vIfSrc);
  const s2 = controlsSites('b.vue', vShowSrc);
  assert.deepEqual(s1[0].ancestorChain, ['a'], 'v-if 祖先应被识别');
  assert.deepEqual(s2[0].ancestorChain, [], 'v-show 不摘元素，不应被当成 v-if');

  // BaseCollapse 用 v-show —— 本就正确，不得被误报
  const bc = controlsSites('components/base/BaseCollapse.vue', readFileSync(path.join(SRC, 'components/base/BaseCollapse.vue'), 'utf8'));
  const site = bc.find((s) => s.expr === 'contentId');
  assert.ok(site, '未找到 BaseCollapse 的 aria-controls');
  assert.deepEqual(site.ancestorChain, [], 'BaseCollapse 的 v-show 不应被当成 v-if（批 86 曾在此误报）');
});

test('任何 .vue 都不得把 HTML 注释写进标签内部', () => {
  // 批 85 实测踩到：把说明注释插在属性之间，`vue-tsc` 静默通过、
  // `vite build` 直接失败（Attribute name cannot contain U+0022 / U+0027 / U+003C）。
  const bad = [];
  for (const f of vueFiles(SRC)) {
    const raw = readFileSync(f, 'utf8');
    let i = 0;
    while (i < raw.length) {
      if (raw.startsWith('<!--', i)) i += 4;
      else if (raw[i] === '<' && /[A-Za-z]/.test(raw[i + 1] || '')) {
        let j = i + 1, q = null;
        while (j < raw.length && raw[j] !== '>') {
          if (q) { if (raw[j] === q) q = null; }
          else if (raw[j] === '"' || raw[j] === "'") q = raw[j];
          else if (raw.startsWith('<!--', j)) {
            bad.push(`${path.relative(SRC, f)}:${raw.slice(0, j).split('\n').length} 标签内部出现 <!--`);
            break;
          }
          j += 1;
        }
        i = j + 1;
      } else i += 1;
    }
  }
  assert.deepEqual(bad, [], `HTML 注释被写进了标签内部（vite build 会失败）：\n  ${bad.join('\n  ')}`);
});
