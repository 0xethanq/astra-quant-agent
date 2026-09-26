/**
 * 全站防呆二次确认弹窗短语实时校验与动作按钮门禁守卫闸（批 127）。
 *
 * ## 实测缺陷与背景：
 *
 * 在管理后台的网关重试（GatewayPage）、自进化心法复盘（EvolutionPage）与系统更新（AboutPage）中：
 * 用户需要输入指定的短语（如 `REPLAY {id}`、`RUN EVOLUTION`、`UPDATE ASTRA`）以确认高危操作。
 *
 * 缺陷：
 * 1. `GatewayPage.vue`：提交按钮此前仅检查 `:disabled="!replayPhrase.trim() || replaying"`，
 *    即使短语输入错误（`!replayMatched`），按钮仍然可点，点击后向后端派发必然失败的 400 请求；
 *    且输入框无 `.is-bad` 与 `:aria-invalid`。
 * 2. `EvolutionPage.vue`：提交按钮此前仅检查 `:disabled="!runDialog.phrase.trim() || busy === 'run'"`，
 *    输入错误时按钮可点并直接弹 toast 报错；输入框无 `.is-bad` 与 `:aria-invalid`。
 * 3. `AboutPage.vue`：更新短语输入框在未匹配时缺少 `.is-bad` 与 `:aria-invalid` 动态状态。
 *
 * 修复后：
 * - 按钮严格受 `replayMatched`、`runPhraseOk` 前置门禁控制，短语不匹配时不可点击；
 * - 3 个短语输入框在有输入但不匹配时统一提供 `.is-bad` 红色警示与 `:aria-invalid="true"` 无障碍反馈。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

test('GatewayPage 重放确认对话框按钮必须受 replayMatched 门禁控制且输入框具备校验反馈', () => {
  const vue = readFileSync(path.join(SRC, 'views/admin/GatewayPage.vue'), 'utf8');

  assert.match(
    vue,
    /:disabled="!replayMatched\s*\|\|\s*replaying"/,
    'GatewayPage 重放按钮未对 replayMatched 设置前置门禁',
  );
  assert.match(
    vue,
    /:class="\{\s*'is-bad':\s*!!replayPhrase\s*&&\s*!replayMatched\s*\}"/,
    'GatewayPage replayPhrase 输入框缺少 is-bad 动态类',
  );
  assert.match(
    vue,
    /:aria-invalid="!!replayPhrase\s*&&\s*!replayMatched\s*\?\s*'true'\s*:\s*undefined"/,
    'GatewayPage replayPhrase 输入框缺少 aria-invalid 动态无障碍状态',
  );
});

test('EvolutionPage 复盘确认对话框按钮必须受 runPhraseOk 门禁控制且输入框具备校验反馈', () => {
  const vue = readFileSync(path.join(SRC, 'views/admin/EvolutionPage.vue'), 'utf8');

  assert.match(
    vue,
    /:disabled="!runPhraseOk\s*\|\|\s*busy\s*===\s*'run'"/,
    'EvolutionPage 复盘按钮未对 runPhraseOk 设置前置门禁',
  );
  assert.match(
    vue,
    /:class="\{\s*'is-bad':\s*!!runDialog\.phrase\s*&&\s*!runPhraseOk\s*\}"/,
    'EvolutionPage runDialog.phrase 输入框缺少 is-bad 动态类',
  );
  assert.match(
    vue,
    /:aria-invalid="!!runDialog\.phrase\s*&&\s*!runPhraseOk\s*\?\s*'true'\s*:\s*undefined"/,
    'EvolutionPage runDialog.phrase 输入框缺少 aria-invalid 动态无障碍状态',
  );
});

test('AboutPage 更新确认对话框输入框必须具备 is-bad 与 aria-invalid 校验反馈', () => {
  const vue = readFileSync(path.join(SRC, 'views/admin/AboutPage.vue'), 'utf8');

  assert.match(
    vue,
    /:class="\{\s*'is-bad':\s*!!confirmPhrase\s*&&\s*!phaseOk\s*\}"/,
    'AboutPage confirmPhrase 输入框缺少 is-bad 动态类',
  );
  assert.match(
    vue,
    /:aria-invalid="!!confirmPhrase\s*&&\s*!phaseOk\s*\?\s*'true'\s*:\s*undefined"/,
    'AboutPage confirmPhrase 输入框缺少 aria-invalid 动态无障碍状态',
  );
});
