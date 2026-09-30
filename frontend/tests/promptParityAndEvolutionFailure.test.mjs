/**
 * 工坊/实发一致性 + 自进化失败可见性（2026-09-30）。
 *
 * ## 用户报障原文
 *
 * 「提示词工坊的提示词怎么和决策透视的提示词不一样，是不是有什么 bug，
 *   还有自进化看起来也没更新啊？」
 *
 * 两句都是**真缺陷**，根因见各自用例的注释。本门把两条修复的**前端侧**契约钉住：
 * 工坊默认给"生效视图"（后端装配的 基座 + 方案，与实发同源），
 * 复盘失败必须在页面上显式可见（而不是显示成 `NO_CHANGE`）。
 *
 * ⚠️ 断言的文本里含 `evoStatusLabel` / `llm_error` 等名字，而**本仓注释里也会写这些词**
 * （本次修复就把原因写进了注释）。故所有读取一律先剥注释 —— 否则改注释就能让门变红/变绿。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const STUDIO = path.join(SRC, 'views/admin/PromptStudioPage.vue');
const EVOLUTION = path.join(SRC, 'views/admin/EvolutionPage.vue');

/** 剥掉 HTML / 块 / 行注释（`//` 用 (?<!:) 保护 https://）。 */
function stripComments(text) {
  return text
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(?<!:)\/\/[^\n]*/g, '');
}

const read = (p) => stripComments(readFileSync(p, 'utf8'));

/** 取 `<style>` 块里的规则 → [{selector, decls}]。 */
function styleRules(source) {
  const m = /<style[^>]*>([\s\S]*)<\/style>/.exec(source);
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

// ═══════════════════════════ 一、工坊 = 实发 ═══════════════════════════

test('工坊预览默认必须是「生效视图」（与实发同源），而不是只看本方案模块', () => {
  const src = read(STUDIO);
  assert.match(
    src,
    /const previewMode = ref<'effective' \| 'rendered' \| 'template'>\('effective'\)/,
    'previewMode 的默认值必须含 effective 模式且以它开头 —— 用户第一眼就该是实发口径',
  );
});

test('「生效视图」取的是后端装配的 effective_templates（基座 + 方案）', () => {
  const src = read(STUDIO);
  assert.match(src, /const PREVIEW_MODES = \['effective', 'rendered', 'template'\] as const/,
    '三模式登记表');
  const eff = /if \(previewMode\.value === 'effective'\) \{([\s\S]*?)\n  \}/.exec(src);
  assert.ok(eff, 'compiledPreview 里找不到 effective 分支');
  assert.match(eff[1], /effective_templates/,
    '生效视图必须读后端装配结果，不得本地重拼（本地重拼就又会和实发分叉）');
});

test('三个预览页签都要有漫游 tabindex 与方向键（键盘可达）', () => {
  const src = read(STUDIO);
  for (const i of [0, 1, 2]) {
    assert.match(src, new RegExp(`:ref="setPrevRef\\(${i}\\)"`), `第 ${i} 个页签缺 ref`);
    assert.match(src, new RegExp(`@keydown="onPrevKey\\(\\$event, ${i}\\)"`), `第 ${i} 个页签缺方向键`);
  }
});

test('基座模块必须显式告知"改了会落成覆盖层"（不再让人以为改了没生效）', () => {
  const src = read(STUDIO);
  assert.match(src, /const selectedIsBase = computed\(\(\) => selectedModule\.value\?\.source === 'base'\)/,
    '缺 selectedIsBase 判据');
  // ⚠️ 2026-09-30：`selectedIsBase` 那条说明现在是**链式分支的第二档**
  // （`v-if="selectedIsLocked"` → `v-else-if="selectedIsBase"`），因为只读契约模块
  // 需要一句更准确的说明（"不可改"而不是"改了会落成覆盖层"）。判据因此接受
  // `v-if` / `v-else-if` 两种形态，但**分支顺序也被钉住**：只读必须排在基座之前，
  // 否则只读模块会错误地显示"改了会落成覆盖层"（那是另一种误导）。
  assert.match(src, /v-(?:else-)?if="selectedIsBase"[\s\S]{0,160}?source\.baseEditNote/,
    '基座模块编辑区必须渲染 baseEditNote 说明（role="note"）');
  const lockedIdx = src.indexOf('v-if="selectedIsLocked"');
  const baseIdx = src.indexOf('v-else-if="selectedIsBase"');
  assert.ok(lockedIdx >= 0, '只读模块必须有自己的说明分支');
  assert.ok(baseIdx > lockedIdx, '只读分支必须排在基座分支之前（否则只读模块显示错误说明）');
  assert.match(src, /class="ps-base-note"[^>]*role="note"|role="note"[^>]*class="ps-base-note"/,
    '说明条需要 role="note" 以便读屏');
});

test('工坊新增文案在中英文案里都存在（词条结构对称）', () => {
  const zh = readFileSync(path.join(SRC, 'locales/zh/admin/promptStudio.ts'), 'utf8');
  const en = readFileSync(path.join(SRC, 'locales/en/admin/promptStudio.ts'), 'utf8');
  for (const key of ['effective', 'hintEffective', 'baseEditNote']) {
    assert.match(zh, new RegExp(`\\b${key}:`), `zh 缺 ${key}`);
    assert.match(en, new RegExp(`\\b${key}:`), `en 缺 ${key}`);
  }
});

// ═════════════════════ 二、复盘失败必须可见 ═════════════════════

test('复盘失败时徽章文案必须是「失败」，不能照抄 change_status', () => {
  const src = read(EVOLUTION);
  assert.match(src, /function evoStatusLabel\(/, '缺 evoStatusLabel');
  assert.match(src, /resolveEvolutionStatus\(status, error\)/,
    '必须复用唯一事实源 resolveEvolutionStatus');
  assert.match(src, /if \(resolved\.category === 'FAILED'\)/,
    '必须按 resolveEvolutionStatus 判出的 FAILED 类别分支（而不是自己再判一次 llm_error）');
  assert.match(src, /statusFailed/, '必须返回 statusFailed 文案');
  assert.match(src, /\{\{ evoStatusLabel\(evolutionReport\.change_status, evolutionReport\.llm_error\) \}\}/,
    '模板必须改用 evoStatusLabel（旧实现直接把 change_status 打出来 ⇒ 失败显示成 NO_CHANGE）');
  assert.doesNotMatch(src, /\{\{ evolutionReport\.change_status \|\| 'NO_CHANGE' \}\}/,
    '旧的"直出 change_status"不得回潮');
});

test('失败详情必须在 insights 为空时**也**渲染（旧实现整块隐藏）', () => {
  const src = read(EVOLUTION);
  // 从 <div> 开标签**之前**切起：`v-if` 写在 class 之前，只从 class 切会看不到它。
  const open = src.indexOf('<div v-if="evolutionReport.llm_error"');
  assert.ok(open > 0, '找不到 `v-if="evolutionReport.llm_error"` 的失败横幅开标签');
  // 切到横幅**自己的**闭合 `</div>` 为止：切到 `class="evo-insights"` 会把洞察面板的
  // 开标签也包含进来（它的 `v-if` 写在 class 之前），从而误判"横幅嵌在洞察块里"。
  const close = src.indexOf('</div>', open);
  const insights = src.indexOf('class="evo-insights"');
  assert.ok(close > open, '失败横幅没有闭合标签');
  assert.ok(insights > close, '失败横幅应排在洞察面板之前');
  const block = src.slice(open, close);
  assert.match(block, /class="evo-failure"/, '开标签应挂 .evo-failure');
  assert.match(block, /role="alert"/, '失败横幅必须是 alert（读屏即时播报）');
  assert.match(block, /failedTitle/, '横幅要有标题文案');
  assert.match(block, /evolutionReport\.llm_error \}\}/, '横幅要显示原始错误');
  // 关键：横幅不能被套在 `insights.length` 的条件块内部
  assert.doesNotMatch(block, /insights && evolutionReport\.insights\.length/,
    '失败横幅不得嵌在"有洞察才显示"的块里 —— 那正是旧实现让失败不可见的原因');
});

test('失败横幅里的 <pre> 要可键盘滚动，且复用 .log-panel 原件', () => {
  const src = read(EVOLUTION);
  const pre = /<pre class="([^"]*evo-failure-detail[^"]*)"[^>]*>/.exec(src);
  assert.ok(pre, '找不到失败详情 <pre>');
  assert.match(pre[0], /tabindex="0"/, '<pre> 必须显式 tabindex="0"');
  assert.match(pre[1], /\blog-panel\b/, '等宽块本体应复用 .log-panel 原件');
});

test('失败详情不得自造「说明行形状」（否则 panelDescPrimitive 门翻红）', () => {
  const rule = styleRules(readFileSync(EVOLUTION, 'utf8')).find((r) => r.selector === '.evo-failure-detail');
  assert.ok(rule, '找不到 .evo-failure-detail 规则');
  for (const banned of ['font-size', 'line-height', 'color', 'margin-top']) {
    if (banned === 'margin-top') continue; // margin-top 单独出现不会被判成说明行
    assert.ok(!(banned in rule.decls),
      `.evo-failure-detail 不得声明 ${banned}（四条同现即被判成"又自造了一条说明行"）`);
  }
});

test('复盘失败文案中英对称', () => {
  const zh = readFileSync(path.join(SRC, 'locales/zh/admin/evolution.ts'), 'utf8');
  const en = readFileSync(path.join(SRC, 'locales/en/admin/evolution.ts'), 'utf8');
  for (const key of ['statusFailed', 'failedTitle', 'failedNote']) {
    assert.match(zh, new RegExp(`\\b${key}:`), `zh 缺 ${key}`);
    assert.match(en, new RegExp(`\\b${key}:`), `en 缺 ${key}`);
  }
});
