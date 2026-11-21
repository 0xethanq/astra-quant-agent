/**
 * 预筛漏斗第四态 `screened_out` 的展示契约（2026-11）。
 *
 * ## 为什么需要这个门
 *
 * 后端把「确定性预筛落选」与「模型漏答（omitted）」「模型主动观望（WAIT）」
 * 分开输出。展示层最容易出的两类错，本门把它们钉死：
 *
 * 1. **把落选画成模型裁决** —— 落选标的本轮根本没有进入深度分析，
 *    即使兜底 WAIT 也不是模型看过之后的选择；
 * 2. **四态优先级错位** —— `screened_out` 必须先于 `omitted` / `gate_blocked` /
 *    模型 WAIT 判断，否则会被更靠前的分支吞掉。
 *
 * 另外钉住：评分/原因只在悬停提示里展示，字段缺失（旧缓存）时不得伪造数值。
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';

const TYPES = 'src/types/dashboard.ts';
const STORE = 'src/stores/dashboard.ts';
const DRAWER = 'src/components/dashboard/FactorDrawer.vue';
const TRAJECTORY = 'src/components/dashboard/TrajectoryPanel.vue';
const ZH = 'src/locales/zh/dash/matrix.ts';
const EN = 'src/locales/en/dash/matrix.ts';

const types = readFileSync(TYPES, 'utf8');
const store = readFileSync(STORE, 'utf8');
const drawer = readFileSync(DRAWER, 'utf8');
const trajectory = readFileSync(TRAJECTORY, 'utf8');
const zh = readFileSync(ZH, 'utf8');
const en = readFileSync(EN, 'utf8');

test('类型契约：decision_source 四态 + screen_* 可选字段', () => {
  const unions = types.match(/decision_source\?: 'model' \| 'omitted' \| 'screened_out'/g) || [];
  assert.equal(unions.length, 2, 'InstrumentFactor 与 decision 两处联合类型都必须含 screened_out');
  assert.match(types, /screen_score\?: number \| null/, '缺少 screen_score');
  assert.match(types, /screen_signal\?: string \| null/, '缺少 screen_signal');
  assert.match(types, /screen_reason\?: string/, '缺少 screen_reason');
});

test('store：screen_* 透传且旧缓存安全回落', () => {
  assert.match(
    store,
    /screen_score:\s*f\.decision\?\.screen_score \?\? f\.screen_score \?\? null/,
    'store 未透传 screen_score（旧缓存应回落 null）',
  );
  assert.match(
    store,
    /screen_signal:\s*f\.decision\?\.screen_signal \?\? f\.screen_signal \?\? null/,
    'store 未透传 screen_signal（旧缓存应回落 null）',
  );
  assert.match(
    store,
    /screen_reason:\s*f\.decision\?\.screen_reason \?\? f\.screen_reason \?\? ''/,
    'store 未透传 screen_reason（旧缓存应回落空串）',
  );
});

test('FactorDrawer：徽章优先级 screened_out → omitted → gate_blocked → WAIT', () => {
  const iScreened = drawer.indexOf(`v-if="d.decision_source === 'screened_out'"`);
  const iOmitted = drawer.indexOf(`v-else-if="d.decision_source === 'omitted'"`);
  const iGate = drawer.indexOf('v-else-if="d.gate_blocked"');
  const iWait = drawer.indexOf(`v-else-if="(d.action || f.action) === 'WAIT'"`);
  assert.ok(iScreened >= 0, 'FactorDrawer 缺少 screened_out 徽章');
  assert.ok(iScreened < iOmitted, 'screened_out 必须在 omitted 之前判断');
  assert.ok(iOmitted < iGate, 'omitted 必须在 gate_blocked 之前判断（既有顺序不得被打乱）');
  assert.ok(iGate < iWait, 'gate_blocked 必须在模型 WAIT 之前判断（既有顺序不得被打乱）');
  assert.match(drawer, /:title="screenedOutTitle"/, 'screened_out 徽章缺少评分/原因悬停提示');
  assert.match(drawer, /screen_score \?\? f\.value\.screen_score/, '悬停提示未读取评分');
  assert.match(drawer, /screen_reason \?\? f\.value\.screen_reason/, '悬停提示未读取原因');
  assert.match(drawer, /filter\(\(v\) => v !== null && v !== undefined && v !== ''\)/,
    '悬停提示必须过滤缺失字段，不得伪造数值');
});

test('TrajectoryPanel：徽章优先级与悬停提示同 FactorDrawer', () => {
  assert.match(trajectory, /screenScore:\s*d\.screen_score \?\? f\.screen_score/, '未映射 screen_score');
  assert.match(trajectory, /screenSignal:\s*d\.screen_signal \?\? f\.screen_signal/, '未映射 screen_signal');
  assert.match(trajectory, /screenReason:\s*d\.screen_reason \?\? f\.screen_reason \?\? ''/, '未映射 screen_reason');
  const iScreened = trajectory.indexOf(`v-if="item.decisionSource === 'screened_out'"`);
  const iOmitted = trajectory.indexOf(`v-else-if="item.decisionSource === 'omitted'"`);
  const iGate = trajectory.indexOf('v-else-if="item.gateBlocked"');
  const iWait = trajectory.indexOf(`v-else-if="item.action === 'WAIT'"`);
  assert.ok(iScreened >= 0, 'TrajectoryPanel 缺少 screened_out 徽章');
  assert.ok(iScreened < iOmitted, 'screened_out 必须在 omitted 之前判断');
  assert.ok(iOmitted < iGate, 'omitted 必须在 gate_blocked 之前判断（既有顺序不得被打乱）');
  assert.ok(iGate < iWait, 'gate_blocked 必须在模型 WAIT 之前判断（既有顺序不得被打乱）');
  assert.match(trajectory, /:title="screenedOutTitle\(item\)"/, 'screened_out 徽章缺少评分/原因悬停提示');
});

test('中英文案齐全且语义一致', () => {
  assert.match(zh, /sourceScreenedOut: '预筛落选 · 未深度分析'/, '中文缺少 sourceScreenedOut');
  assert.match(en, /sourceScreenedOut: 'Screened out · not deep-analyzed'/, '英文缺少 sourceScreenedOut');
  for (const [loc, text] of [['zh', zh], ['en', en]]) {
    assert.match(text, /sourceOmitted:/, `${loc} 既有 omitted 文案被误删`);
    assert.match(text, /sourceGateBlocked:/, `${loc} 既有 gate_blocked 文案被误删`);
    assert.match(text, /sourceModelWait:/, `${loc} 既有模型 WAIT 文案被误删`);
  }
});
