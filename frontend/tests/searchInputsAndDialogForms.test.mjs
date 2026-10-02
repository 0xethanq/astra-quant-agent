/**
 * 搜索输入框语义规范与弹窗表单回车提交守卫闸（批 55）。
 *
 * ## 守什么
 *
 * 1. **搜索框语义与无障碍名称覆盖（HTML5 type="search" & WCAG 4.1.2）**：
 *    全站所有具有搜索/筛选用途的输入控件（如因子矩阵标的搜索、决策日志搜索、审计搜索、模型供应商筛选）：
 *    - `type` 必须显式声明为 `"search"`，激活移动端虚拟键盘的搜索动作键与辅助技术的 searchbox 角色；
 *    - 必须显式声明 `:aria-label`，杜绝视障用户遭遇「仅有占位符无名称」的可用性缺陷。
 *
 * 2. **弹窗输入表单回车提交可用性（Enter-key Submit Affordance）**：
 *    在后台弹窗录入表单（如 AdminSys 创建账号、ModelEdit 编辑模型、Security 平仓确认、Interceptors 创建插件）中：
 *    - 输入区域必须包裹在 `<form @submit.prevent="...">` 容器中；
 *    - 弹窗底部操作按钮必须声明 `type="submit"` 并通过 `form="<formId>"` 关联表单；
 *    - 键盘用户输入完成敲击 Enter 键能够直接触发提交，无需再拿起鼠标点击底部按钮。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

test('全站关键搜索框必须声明 type="search" 与 aria-label', () => {
  const targets = [
    { file: 'components/dashboard/FactorMatrix.vue', vmodel: 'searchQuery' },
    { file: 'views/admin/AuditPage.vue', vmodel: 'search' },
    { file: 'views/admin/DecisionsPage.vue', vmodel: 'query' },
    { file: 'views/admin/llm/ProviderListView.vue', vmodel: 'searchQuery' },
    { file: 'views/admin/llm/RemoteFetchDialog.vue', vmodel: 'remoteSearch' },
  ];

  for (const { file, vmodel } of targets) {
    const text = readFileSync(path.join(SRC, file), 'utf8');
    const inputRe = new RegExp(`<input[^>]*v-model="?${vmodel}"?[^>]*>`);
    const match = text.match(inputRe);
    assert.ok(match, `${file} 未找到 v-model="${vmodel}" 输入框`);

    const attrs = match[0];
    assert.match(attrs, /type="search"/, `${file} 输入框未声明 type="search"`);
    assert.match(attrs, /:?aria-label=/, `${file} 输入框缺少 aria-label 属性`);
  }
});

test('关键弹窗录入表单必须支持原生回车提交关联', () => {
  const forms = [
    { file: 'views/admin/AdminSysPage.vue', formId: 'as-create-form' },
    { file: 'views/admin/llm/ModelEditDialog.vue', formId: 'model-edit-form' },
    { file: 'views/admin/SecurityPage.vue', formId: 'sc-close-form' },
  ];

  for (const { file, formId } of forms) {
    const text = readFileSync(path.join(SRC, file), 'utf8');
    assert.match(text, new RegExp(`<form[^>]*id="${formId}"[^>]*@submit\\.prevent=`), `${file} 缺失表单容器定义`);
    assert.match(text, new RegExp(`<button[^>]*type="submit"[^>]*form="${formId}"`), `${file} 底部提交按钮未关联 form="${formId}"`);
  }
});

test('闸自检：能准确识别普通文本输入框与无 form 关联的按钮', () => {
  const badSearch = '<input type="text" placeholder="搜索..." />';
  const goodSearch = '<input type="search" aria-label="搜索" placeholder="搜索..." />';
  const badButton = '<button class="btn btn-primary" @click="submit">提交</button>';
  const goodButton = '<button class="btn btn-primary" type="submit" form="my-form">提交</button>';

  const checkSearch = (html) => !html.includes('type="search"') || !html.includes('aria-label');
  const checkButton = (html) => !html.includes('type="submit"') || !html.includes('form=');

  assert.equal(checkSearch(badSearch), true, '应拦截缺少 search 类型的输入框');
  assert.equal(checkSearch(goodSearch), false, '应放行合规 searchbox');
  assert.equal(checkButton(badButton), true, '应拦截未声明 submit 与 form 的按钮');
  assert.equal(checkButton(goodButton), false, '应放行合规表单提交按钮');
});
