/**
 * 账户与安全工位（SecurityPage）高危操作按钮门禁与实时短语校验守卫闸（批 126）。
 *
 * ## 实测缺陷与背景：
 *
 * 在安全配置页（`/admin/security`）中，包含两项最高风险的不可逆或强风控操作：
 * 1. 修改初始本金基线（`saveCapital`）：需要超管并键入 `UPDATE CAPITAL` 短语；
 * 2. 紧急手动平仓（`confirmClose`）：需要管理员密码并键入一次性仓位确认短语。
 *
 * 缺陷：
 * 此前两处的提交按钮在短语未输入或输错时均保持可用（`:disabled` 仅检查了 loading 态）；
 * 用户若在未键入短语时点击或敲回车，系统直接抛出 toast 报错，缺乏前端表单的前置状态门禁；
 * 且确认短语输入框在输入错误时没有任何视觉反馈（没有 `.is-bad`）与无障碍错误提示（没有 `aria-invalid`）。
 *
 * 修复后：
 * 1. 初始本金保存按钮严格绑定 `:disabled="savingCapital || !auth.isSuperadmin || !capitalAmountOk || !capitalConfirmOk"`；
 * 2. 紧急平仓按钮严格绑定 `:disabled="closing || !closeReady"`；
 * 3. 两个危险确认短语输入框均具备长度大于 0 且短语不匹配时的 `.is-bad` 红色警示与 `:aria-invalid="true"` 无障碍反馈。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

test('SecurityPage 本金保存与紧急平仓按钮必须受短语与密码前置门禁保护', () => {
  const vue =
    readFileSync(path.join(SRC, 'views/admin/security/SecurityPortfolioTab.vue'), 'utf8')
    + '\n'
    + readFileSync(path.join(SRC, 'views/admin/security/SecurityEmergencyTab.vue'), 'utf8');

  // 1. 本金保存按钮门禁
  assert.match(
    vue,
    /:disabled="savingCapital\s*\|\|\s*!auth\.isSuperadmin\s*\|\|\s*!capitalAmountOk\s*\|\|\s*!capitalConfirmOk"/,
    '本金保存按钮未对 capitalAmountOk 与 capitalConfirmOk 设置前置 :disabled 门禁',
  );

  // 2. 本金短语实时校验与无障碍属性
  assert.match(
    vue,
    /:class="\{\s*'is-bad':\s*!!capitalConfirm\s*&&\s*!capitalConfirmOk\s*\}"/,
    'capitalConfirm 输入框缺少 is-bad 动态类',
  );
  assert.match(
    vue,
    /:aria-invalid="!!capitalConfirm\s*&&\s*!capitalConfirmOk\s*\?\s*'true'\s*:\s*undefined"/,
    'capitalConfirm 输入框缺少 aria-invalid 动态无障碍状态',
  );

  // 3. 紧急平仓按钮门禁
  assert.match(
    vue,
    /:disabled="closing\s*\|\|\s*!closeReady"/,
    '紧急平仓按钮未对 closeReady 设置前置 :disabled 门禁',
  );

  // 4. 平仓短语实时校验与无障碍属性
  assert.match(
    vue,
    /:class="\{\s*'is-bad':\s*!!closePhraseInput\s*&&\s*!closePhraseOk\s*\}"/,
    'closePhraseInput 输入框缺少 is-bad 动态类',
  );
  assert.match(
    vue,
    /:aria-invalid="!!closePhraseInput\s*&&\s*!closePhraseOk\s*\?\s*'true'\s*:\s*undefined"/,
    'closePhraseInput 输入框缺少 aria-invalid 动态无障碍状态',
  );
});

test('自检：能准确识别未受保护的危险动作按钮与输入框', () => {
  const badBtn = '<button :disabled="savingCapital || !auth.isSuperadmin" @click="saveCapital">';
  const goodBtn = '<button :disabled="savingCapital || !auth.isSuperadmin || !capitalAmountOk || !capitalConfirmOk" @click="saveCapital">';
  const checkBtn = (s) => /:disabled="savingCapital\s*\|\|\s*!auth\.isSuperadmin\s*\|\|\s*!capitalAmountOk\s*\|\|\s*!capitalConfirmOk"/.test(s);
  assert.equal(checkBtn(badBtn), false);
  assert.equal(checkBtn(goodBtn), true);
});
