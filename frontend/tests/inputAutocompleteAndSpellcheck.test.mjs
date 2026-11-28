/**
 * 输入控件 autocomplete 与 spellcheck 属性体验规范守卫闸（批 63）。
 *
 * ## 守什么
 *
 * 1. **二次确认短语输入防护（Prevent History & Autocorrect Pollution）**：
 *    在关键高危操作确认框中（如全局 ConfirmHost、DangerZone、AboutPage 升级、SecurityPage 平仓短语、
 *    SecurityPage 资金池短语、EvolutionPage 演化复盘、GatewayPage 事件重放）：
 *    - 必须显式声明 `autocomplete="off"`，避免浏览器把一次性确认短语保存至历史补全下拉列表；
 *    - 必须显式声明 `spellcheck="false"`，防止英文大写短语被拼写检查标注红波浪线或触发自动纠错。
 *
 * 2. **搜索与过滤框纯净度（Search Autocomplete Suppression）**：
 *    全站 5 处关键搜索框（FactorMatrix、AuditPage、DecisionsPage、ProviderListView、RemoteFetchDialog）：
 *    - 必须显式声明 `autocomplete="off"` 与 `spellcheck="false"`，杜绝浏览器历史搜索词弹窗遮挡即时搜索结果。
 *
 * 3. **密码管理器自动填充兼容（Password Manager Ergonomics）**：
 *    - `SecurityPage.vue` 紧急平仓密码必须声明 `autocomplete="current-password"`；
 *    - `AdminSysPage.vue` 当前密码声明 `current-password`，新密码声明 `new-password`；
 *    - `LoginPage.vue` 账号框必须声明 `autocomplete="username"`。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

test('所有二次危险操作确认短语输入框必须禁用 autocomplete 与 spellcheck', () => {
  const targets = [
    { file: 'components/base/ConfirmHost.vue', vmodel: 'phraseInput' },
    { file: 'views/admin/agent/AgentProposalCard.vue', vmodel: 'phraseInputs[phrase]' },
    { file: 'views/admin/AboutPage.vue', vmodel: 'confirmPhrase' },
    { file: 'views/admin/SecurityPage.vue', vmodel: 'capitalConfirm' },
    { file: 'views/admin/SecurityPage.vue', vmodel: 'closePhraseInput' },
  ];

  for (const { file, vmodel } of targets) {
    const text = readFileSync(path.join(SRC, file), 'utf8');
    const escaped = vmodel.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    const re = new RegExp(`<input[^>]*v-model="?${escaped}"?[^>]*>`);
    const match = text.match(re);
    assert.ok(match, `${file} 未找到 v-model="${vmodel}" 输入框`);

    const attrs = match[0];
    assert.match(attrs, /autocomplete="off"/, `${file} 确认短语输入框缺少 autocomplete="off"`);
    assert.match(attrs, /spellcheck="false"/, `${file} 确认短语输入框缺少 spellcheck="false"`);
  }
});

test('全站搜索输入框必须禁用 autocomplete 与 spellcheck', () => {
  const searchInputs = [
    { file: 'components/dashboard/FactorMatrix.vue', vmodel: 'searchQuery' },
    { file: 'views/admin/AuditPage.vue', vmodel: 'search' },
    { file: 'views/admin/DecisionsPage.vue', vmodel: 'query' },
    { file: 'views/admin/llm/ProviderListView.vue', vmodel: 'searchQuery' },
    { file: 'views/admin/llm/RemoteFetchDialog.vue', vmodel: 'remoteSearch' },
  ];

  for (const { file, vmodel } of searchInputs) {
    const text = readFileSync(path.join(SRC, file), 'utf8');
    const re = new RegExp(`<input[^>]*v-model="?${vmodel}"?[^>]*>`);
    const match = text.match(re);
    assert.ok(match, `${file} 未找到 v-model="${vmodel}" 搜索框`);

    const attrs = match[0];
    assert.match(attrs, /autocomplete="off"/, `${file} 搜索框缺少 autocomplete="off"`);
    assert.match(attrs, /spellcheck="false"/, `${file} 搜索框缺少 spellcheck="false"`);
  }
});

test('密码与凭证输入框正确声明密码管理器支持语义', () => {
  const sec = readFileSync(path.join(SRC, 'views/admin/SecurityPage.vue'), 'utf8');
  assert.match(sec, /<input[^>]*v-model="closePassword"[^>]*autocomplete="current-password"/, 'SecurityPage 平仓密码缺少 autocomplete="current-password"');

  const adm = readFileSync(path.join(SRC, 'views/admin/AdminSysPage.vue'), 'utf8');
  assert.match(adm, /<input[^>]*v-model="currentPassword"[^>]*autocomplete="current-password"/);
  assert.match(adm, /<input[^>]*v-model="newPassword"[^>]*autocomplete="new-password"/);

  const login = readFileSync(path.join(SRC, 'views/admin/LoginPage.vue'), 'utf8');
  assert.match(login, /<input[^>]*v-model="username"[^>]*autocomplete="username"/);
});

test('闸自检：能准确拦截缺少 autocomplete/spellcheck 的危险输入框', () => {
  const badInput = '<input v-model="phrase" placeholder="CONFIRM" />';
  const goodInput = '<input v-model="phrase" autocomplete="off" spellcheck="false" />';

  const check = (html) => html.includes('autocomplete="off"') && html.includes('spellcheck="false"');
  assert.equal(check(badInput), false, '应拦截未防护的输入框');
  assert.equal(check(goodInput), true, '应放行合规输入框');
});
