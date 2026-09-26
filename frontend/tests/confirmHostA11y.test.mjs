/**
 * 全局二次确认弹窗（ConfirmHost）可访问性与命名契约守卫闸（批 118）。
 *
 * ## 实测出来的重大可访问性缺陷：
 *
 * 1. 弹窗无 accessible name（未命名对话框）：
 *    在 `ConfirmHost.vue` 中，此前未给 `BaseDialog` 传递 `:title="state.title"` 或 `<template #title>`，
 *    而是把标题与描述作为普通 slot 内容放在默认插槽的自定义 `<h3>` 里。
 *    后果是 `BaseDialog` 的 `:aria-labelledby="title || $slots.title ? titleId : undefined"`
 *    计算为 `undefined`，`aria-describedby` 同样为 `undefined`！
 *    屏幕阅读器与自动化辅助工具读取 `role="dialog"` 时完全读不出标题与描述内容，
 *    实测实机：`labelledby: null, describedby: null`。
 *
 * 2. 破坏性操作短语输入缺乏动态 `aria-invalid` 反馈：
 *    当弹窗要求输入特定短语确认（如 `BACKUP ASTRA`、`LIVE`）时，
 *    输入中途未对齐阶段缺少 `aria-invalid="true"` 辅助播报。
 *
 * 3. 模态框底部按钮缺少 `type="button"` 声明。
 *
 * ## 修法
 *
 * 1. `ConfirmHost.vue` 显式向 `BaseDialog` 传递 `:title="state.title"` 与 `:desc="state.desc"`，
 *    并通过 `<template #title>` 挂载危险警示图标与标题文本。
 *    `BaseDialog` 正确输出 `:aria-labelledby` 与 `:aria-describedby` 引用。
 * 2. 输入框增加 `:aria-invalid="phraseInput.length > 0 && !phraseOk"`。
 * 3. 底部取消与确认按钮显式标注 `type="button"`。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

test('ConfirmHost 必须向 BaseDialog 显式传递 title 与 desc，并具备 template #title', () => {
  const vue = readFileSync(path.join(SRC, 'components/base/ConfirmHost.vue'), 'utf8');

  // 必须绑定 :title="state.title"
  assert.match(
    vue,
    /<BaseDialog\b[^>]*:title="state\.title"/,
    'ConfirmHost 缺少 :title="state.title"，会导致 BaseDialog 无法生成 aria-labelledby',
  );

  // 必须绑定 :desc="state.desc"
  assert.match(
    vue,
    /<BaseDialog\b[^>]*:desc="state\.desc"/,
    'ConfirmHost 缺少 :desc="state.desc"，会导致 BaseDialog 无法生成 aria-describedby',
  );

  // 必须有 <template #title>
  assert.match(vue, /<template\s+#title>/, 'ConfirmHost 缺少 <template #title> 插槽挂载');

  // 默认插槽内不得再留存孤立未关联的 <h3> 假标题
  const defaultSlotContent = vue.replace(/<template\s+#(?:title|footer)>[\s\S]*?<\/template>/g, '');
  assert.doesNotMatch(
    defaultSlotContent,
    /<h3\b/,
    'ConfirmHost 默认插槽中仍有孤立未关联的 <h3>，应统一通过 #title 插槽挂载',
  );
});

test('ConfirmHost 确认短语输入框必须具有动态 aria-invalid 校验反馈', () => {
  const vue = readFileSync(path.join(SRC, 'components/base/ConfirmHost.vue'), 'utf8');
  assert.match(
    vue,
    /:aria-invalid="phraseInput\.length > 0 && !phraseOk"/,
    'ConfirmHost 输入框缺少 :aria-invalid="phraseInput.length > 0 && !phraseOk" 动态校验反馈',
  );
});

test('ConfirmHost 底部按钮必须显式声明 type="button"', () => {
  const vue = readFileSync(path.join(SRC, 'components/base/ConfirmHost.vue'), 'utf8');
  const footerMatch = vue.match(/<template\s+#footer>([\s\S]*?)<\/template>/);
  assert.ok(footerMatch, '找不到 #footer 模板块');
  const footerContent = footerMatch[1];
  const btnMatches = [...footerContent.matchAll(/<button\b([^>]*)>/g)];
  assert.ok(btnMatches.length >= 2, '未在 #footer 中找到预期数量的按钮');
  for (const m of btnMatches) {
    assert.match(m[1], /type=["']button["']/, `按钮缺少 type="button": ${m[0]}`);
  }
});
