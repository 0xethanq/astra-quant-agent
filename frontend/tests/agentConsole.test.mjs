/**
 * AI Console (`AgentConsolePage.vue` + `agentLogic.ts` + `AgentProposalCard.vue`) contract tests.
 *
 * Run: `node --test tests/agentConsole.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const ROOT = path.resolve(import.meta.dirname, '..');
const SRC = path.join(ROOT, 'src');

const logic = await import(
  pathToFileURL(path.join(SRC, 'views', 'admin', 'agent', 'agentLogic.ts')).href
);
const md = await import(
  pathToFileURL(path.join(SRC, 'utils', 'markdown.ts')).href
);

test('parseSseBuffer parses complete multi-line SSE frames and keeps trailing partial buffer', () => {
  const chunk1 = 'data: {"type":"text_delta","text":"Hel"}\r\n\r\ndata: {"type":"tool_start","id":"t1"';
  const r1 = logic.parseSseBuffer(chunk1);
  assert.equal(r1.events.length, 1);
  assert.deepEqual(r1.events[0], { type: 'text_delta', text: 'Hel' });
  assert.equal(r1.rest, 'data: {"type":"tool_start","id":"t1"');

  const r2 = logic.parseSseBuffer(r1.rest + ',"name":"get_risk_config"}\n\ndata: {"type":"done"}\n\n');
  assert.equal(r2.events.length, 2);
  assert.equal(r2.events[0].name, 'get_risk_config');
  assert.equal(r2.events[1].type, 'done');
  assert.equal(r2.rest, '');
});

test('collectRequiredPhrases & missingConfirmations enforce high-risk phrase gating per selection', () => {
  const items = [
    { id: 'i1', domain: 'risk', title: 'Update lev', required_phrase: 'CONFIRM HIGH RISK' },
    { id: 'i2', domain: 'prompt', title: 'Update prompt', required_phrase: '' },
    { id: 'i3', domain: 'risk', title: 'Reset', required_phrase: 'RESET RISK' },
  ];

  assert.deepEqual(logic.collectRequiredPhrases(items, ['i2']), []);
  assert.deepEqual(logic.collectRequiredPhrases(items, ['i1', 'i3']), ['CONFIRM HIGH RISK', 'RESET RISK']);

  assert.deepEqual(
    logic.missingConfirmations(items, ['i1', 'i2'], { 'CONFIRM HIGH RISK': 'confirm high risk' }),
    [],
  );
  assert.deepEqual(
    logic.missingConfirmations(items, ['i1', 'i3'], { 'CONFIRM HIGH RISK': 'CONFIRM HIGH RISK' }),
    ['RESET RISK'],
  );
});

test('AgentProposalCard enforces confirmation gating, superadmin guard, and CopyButton snapshot hash', () => {
  const vue = readFileSync(path.join(SRC, 'views', 'admin', 'agent', 'AgentProposalCard.vue'), 'utf8');
  assert.match(vue, /canApply/, 'Missing canApply computed guard');
  assert.match(vue, /missingConfirmations/, 'Missing phrase check integration');
  assert.match(vue, /auth\.isSuperadmin/, 'Missing superadmin UI gate');
  assert.match(vue, /<CopyButton/, 'Snapshot hash should provide CopyButton');
  assert.doesNotMatch(vue, /[\u4e00-\u9fff]+/, 'Keep zero hardcoded CJK in AgentProposalCard');
});

test('AgentConsolePage binds SSE stream, model selector, session controls, and zero hardcoded CJK', () => {
  const vue = readFileSync(path.join(SRC, 'views', 'admin', 'AgentConsolePage.vue'), 'utf8');
  assert.match(vue, /streamPost\(/, 'AgentConsolePage must use http.ts streamPost');
  assert.match(vue, /\/api\/v1\/admin\/agent\/config/, 'Missing agent config endpoint');
  assert.match(vue, /\/api\/v1\/admin\/agent\/state-summary/, 'Missing state summary endpoint');
  assert.match(vue, /\/api\/v1\/admin\/agent\/sessions/, 'Missing agent sessions endpoint');
  assert.match(vue, /stopGeneration/, 'Missing SSE abort handler');
  assert.doesNotMatch(
    vue.replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '').replace(/(?<!:)\/\/[^\n]*/g, ''),
    /[\u4e00-\u9fff]+/,
    'No hardcoded CJK allowed outside comments',
  );
});

test('renderSafeMarkdown sanitizes XSS and renders GFM tables, lists and code blocks', () => {
  const malicious = '<script>alert(1)</script> [bad](javascript:alert(2)) [good](https://astraquant.top)';
  const safeHtml = md.renderSafeMarkdown(malicious);
  assert.doesNotMatch(safeHtml, /<script/i);
  assert.doesNotMatch(safeHtml, /javascript:/i);
  assert.match(safeHtml, /&lt;script&gt;/);
  assert.match(safeHtml, /href="https:\/\/astraquant\.top"/);

  const tableMd = [
    '## Funnel Summary',
    '| Metric | Value |',
    '| --- | --- |',
    '| Order Mode | **smart** |',
    '',
    '```json',
    '{"ok": true}',
    '```',
  ].join('\n');
  const rendered = md.renderSafeMarkdown(tableMd);
  assert.match(rendered, /<h3>Funnel Summary<\/h3>/);
  assert.match(rendered, /<table><thead><tr><th>Metric<\/th>/);
  assert.match(rendered, /<td><strong>smart<\/strong><\/td>/);
  assert.match(rendered, /<pre><code class="language-json">/);
});

test('parseUnifiedDiff classifies hunk, add, del and context lines', () => {
  const diff = [
    '--- a/prompt.txt',
    '+++ b/prompt.txt',
    '@@ -1,3 +1,3 @@',
    ' context',
    '-old rule',
    '+new rule',
  ].join('\n');
  const parsed = logic.parseUnifiedDiff(diff);
  assert.deepEqual(parsed.map((l) => l.kind), ['hunk', 'hunk', 'hunk', 'ctx', 'del', 'add']);
  assert.equal(parsed[4].text, '-old rule');
  assert.equal(parsed[5].text, '+new rule');
});
