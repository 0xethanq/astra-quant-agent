/**
 * Strategy & Schedule Control Center (`/admin/strategy`) 契约测试。
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

function walkVue(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) walkVue(p, out);
    else if (name.endsWith('.vue')) out.push(p);
  }
  return out;
}

const STRATEGY_FILES = [
  'views/admin/StrategyCenterPage.vue',
  'views/admin/strategy/StrategyRiskTab.vue',
  'views/admin/strategy/StrategyCouncilTab.vue',
  'views/admin/strategy/StrategyPromptTab.vue',
  'views/admin/strategy/StrategyEvolutionTab.vue',
  'views/admin/strategy/StrategyScheduleTab.vue',
];

function stripComments(text) {
  return text
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/(?<!:)\/\/[^\n]*/g, '');
}

test('router 与 nav 已注册 /admin/strategy 及 5 个标签页', () => {
  const router = readFileSync(path.join(SRC, 'router', 'index.ts'), 'utf8');
  const nav = readFileSync(path.join(SRC, 'config', 'nav.ts'), 'utf8');
  assert.match(router, /path:\s*['"]strategy['"]/);
  assert.match(router, /name:\s*['"]admin-strategy['"]/);
  assert.match(nav, /path:\s*['"]\/admin\/strategy['"]/);

  const page = readFileSync(path.join(SRC, 'views/admin/StrategyCenterPage.vue'), 'utf8');
  for (const tab of ['risk', 'council', 'prompt', 'evolution', 'schedule']) {
    assert.ok(page.includes(`'${tab}'`), `StrategyCenterPage 缺少 ${tab} tab 定义`);
  }
});

test('StrategyCenterPage 与 5 个子标签均通过 useApi 访问后端且无硬编码中文', () => {
  const cjk = /[\u4e00-\u9fff]/;
  for (const rel of STRATEGY_FILES) {
    const raw = readFileSync(path.join(SRC, rel), 'utf8');
    assert.ok(raw.includes('useApi('), `${rel} 必须使用 useApi()`);
    const cleaned = stripComments(raw);
    assert.equal(cjk.test(cleaned), false, `${rel} 存在硬编码中文，请收口到 locales`);
  }
});

test('StrategyRiskTab 对 HIGH RISK 确认口令门控并绑定 .is-bad 与 :aria-invalid', () => {
  const risk = readFileSync(path.join(SRC, 'views/admin/strategy/StrategyRiskTab.vue'), 'utf8');
  assert.ok(risk.includes('HIGH RISK'), 'StrategyRiskTab 必须校验 HIGH RISK 短语');
  assert.ok(risk.includes('is-bad'), 'StrategyRiskTab 确认框必须绑定 .is-bad 状态');
  assert.ok(risk.includes(':aria-invalid'), 'StrategyRiskTab 确认框必须绑定 :aria-invalid');
});

test('BaseTabs 无默认插槽，全站 .vue 不得出现 </BaseTabs> 包裹 tabpanel', () => {
  const offenders = [];
  for (const file of walkVue(SRC)) {
    const raw = stripComments(readFileSync(file, 'utf8'));
    if (raw.includes('</BaseTabs>')) {
      offenders.push(path.relative(SRC, file).replace(/\\/g, '/'));
    }
  }
  assert.deepEqual(offenders, [], `BaseTabs 不支持默认 slot，请改用自闭合标签并将 tabpanel 移到外部: ${offenders.join(', ')}`);
});
