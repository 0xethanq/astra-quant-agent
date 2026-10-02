/**
 * 表单提交单一事实源与防双重触发守卫闸（批 115）。
 *
 * ## 实测出来的缺陷
 *
 * 全站共有 4 处弹窗表单（平仓确认、模型编辑、新建用户、新建拦截器）：
 * `<form id="foo" @submit.prevent="handler">`
 * 底部确认按钮声明了：
 * `<button type="submit" form="foo" @click="handler">`
 *
 * 浏览器规范中，点击 `type="submit"` 按钮会先触发按钮自身的 click 事件，
 * 紧接着派发表单的 submit 事件。由于两者都绑定了同一个处理函数：
 * - 单次点击会**在同一个事件循环周期内同步派发两次**！
 * - 导致向后端连续发送两笔相同的请求（如平仓、新建用户），
 *   第二笔请求由于闭锁未完成直接撞上重复或失效凭据错误。
 *
 * ## 修法
 *
 * 1. 提交按钮保留 `type="submit" form="..."`，彻底移除冗余的 `@click`；
 *    点击按钮由表单的 `@submit.prevent` 统一收拢派发，同时保留 input 内按回车自然提交能力。
 * 2. 弹窗取消按钮显式标注 `type="button"`。
 * 3. 异步提交函数增加 `if (loading.value) return` 守卫闭锁。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

/** 剥除注释，避免注释示例被误检 */
const stripComments = (s) =>
  s
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|\s)\/\/[^\n]*/g, ' ');

/**
 * 找出所有既声明了 type="submit"（或带有 form="..." 属性）又绑定了 @click 的按钮
 * 导出以便自检。
 */
export function findDoubleSubmitButtons(source) {
  const code = stripComments(source);
  const bad = [];
  // 匹配所有 <button ...> 开启标签
  const btnRegex = /<button\b([^>]*?)>/gs;
  let m;
  while ((m = btnRegex.exec(code)) !== null) {
    const attrs = m[1];
    const isSubmit = /type=["']submit["']/.test(attrs) || /\bform=["'][^"']+["']/.test(attrs);
    const hasClick = /@click(?:\.[a-z]+)*=["'][^"']+["']/.test(attrs);
    if (isSubmit && hasClick) {
      bad.push(attrs.replace(/\s+/g, ' ').trim().slice(0, 80));
    }
  }
  return bad;
}

test('全仓禁止在 type="submit" 或 form 关联按钮上重复绑定 @click', () => {
  const violations = [];
  for (const f of vueFiles(SRC)) {
    const src = readFileSync(f, 'utf8');
    const hits = findDoubleSubmitButtons(src);
    if (hits.length) {
      const rel = path.relative(path.resolve(SRC, '..'), f);
      violations.push(`${rel}: ${hits.join('; ')}`);
    }
  }
  assert.deepEqual(
    violations,
    [],
    '以下按钮同时声明了表单提交和 @click，单次点击会触发两次提交：\n  ' + violations.join('\n  '),
  );
});

test('所有带 form 关联的按钮必须对应同模板内存在的 <form id="...">', () => {
  for (const f of vueFiles(SRC)) {
    const src = stripComments(readFileSync(f, 'utf8'));
    const formAttrRegex = /\bform=["']([^"']+)["']/g;
    let m;
    while ((m = formAttrRegex.exec(src)) !== null) {
      const targetId = m[1];
      const formExists = new RegExp(`<form\\b[^>]*\\bid=["']${targetId}["']`).test(src);
      assert.ok(
        formExists,
        `${path.relative(SRC, f)}: 按钮关联了 form="${targetId}"，但未找到对应的 <form id="${targetId}">`,
      );
    }
  }
});

test('弹窗操作表单的处理函数必须包含重入闭锁守卫', () => {
  // 1. SecurityPage::confirmClose
  const sec = stripComments(readFileSync(path.join(SRC, 'views/admin/SecurityPage.vue'), 'utf8'));
  assert.match(
    sec,
    /async\s+function\s+confirmClose\(\)\s*\{\s*if\s*\(\s*closing\.value\s*\)\s*return/,
    'SecurityPage.confirmClose 缺少 if (closing.value) return 闭锁',
  );

  // 2. AdminSysPage::createUser
  const as = stripComments(readFileSync(path.join(SRC, 'views/admin/AdminSysPage.vue'), 'utf8'));
  assert.match(
    as,
    /async\s+function\s+createUser\(\)\s*\{\s*if\s*\(\s*creating\.value\s*\)\s*return/,
    'AdminSysPage.createUser 缺少 if (creating.value) return 闭锁',
  );
});

test('判据自检：能准确捕获双重触发按钮，且正常按钮不误报', () => {
  // 违规：type="submit" 且带 @click
  const bad1 = '<button type="submit" form="as-form" @click="submit">提交</button>';
  assert.equal(findDoubleSubmitButtons(bad1).length, 1);

  // 违规：带 form 关联且带 @click
  const bad2 = '<button form="my-form" @click="save">保存</button>';
  assert.equal(findDoubleSubmitButtons(bad2).length, 1);

  // 合规：type="submit" 不带 @click
  const ok1 = '<button type="submit" form="as-form">提交</button>';
  assert.equal(findDoubleSubmitButtons(ok1).length, 0);

  // 合规：普通按钮带 @click
  const ok2 = '<button type="button" @click="cancel">取消</button>';
  assert.equal(findDoubleSubmitButtons(ok2).length, 0);

  // 注释中的违规不误报
  const commented = '<!-- <button type="submit" @click="foo">test</button> -->';
  assert.equal(findDoubleSubmitButtons(commented).length, 0);
});
