/**
 * 全站所有 Vue 模板按钮类型显式化与表单提交隔离守卫闸（批 121，原批 120 升级全仓覆盖）。
 *
 * ## 规则背景
 *
 * 在复杂交易控制台与前台看板中，存在大量带有输入框、卡片操作、抽屉或弹窗的视图：
 * HTML 规范中，任何未显式声明 `type` 的 `<button>` 元素都会被浏览器默认当成 `type="submit"`。
 * 当用户在任何输入框聚焦并按下 Enter 键，或者在复杂的 DOM 树中触发回车时，
 * 缺省 `type` 的按钮会被当作提交按钮意外派发，造成误操作、页面刷新或非预期并发请求。
 *
 * 在批 115 中我们发现了由于按钮语义模糊导致的表单双重派发重大缺陷，
 * 在批 119 中治理了 LLM 模块的 24 处遗留，
 * 在批 120 中治理了管理后台其余 18 个视图的 140 余处遗留。
 * 本闸将此守卫扩展覆盖到 `src/` 下的**全仓全部 53 个 Vue 组件与页面**（涵盖 base 原语、
 * dashboard 看板视图、layouts 外壳与 admin 全部管理视图），
 * 确保全站 270+ 个 `<button>` 每一个都显式具有 `type="button"` 或 `type="submit"`，
 * 彻底终结隐式提交遗留。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC_DIR = path.resolve(import.meta.dirname, '..', 'src');

/** 递归获取目录下的所有 .vue 文件 */
function getVueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) getVueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

/** 剥除注释，避免注释示例干扰 */
const stripComments = (s) =>
  s
    .replace(/<!--[\s\S]*?-->/g, ' ')
    .replace(/\/\*[\s\S]*?\*\//g, ' ')
    .replace(/(^|\s)\/\/[^\n]*/g, ' ');

export function findUntypedButtons(source) {
  const code = stripComments(source);
  const bad = [];
  const btnRegex = /<button\b([^>]*?)>/gs;
  let m;
  while ((m = btnRegex.exec(code)) !== null) {
    const attrs = m[1];
    if (!/\btype=["'][^"']+["']/.test(attrs)) {
      bad.push(attrs.replace(/\s+/g, ' ').trim().slice(0, 80));
    }
  }
  return bad;
}

test('全仓全部 53 个 Vue 文件内所有按钮必须显式声明 type 属性', () => {
  const files = getVueFiles(SRC_DIR);
  assert.ok(files.length >= 45, `检索到的 Vue 组件与页面数异常少: ${files.length}`);

  const violations = [];
  let totalButtonsChecked = 0;

  for (const f of files) {
    const rel = path.relative(SRC_DIR, f);
    const content = readFileSync(f, 'utf8');
    const hits = findUntypedButtons(content);
    const allBtns = [...stripComments(content).matchAll(/<button\b/g)];
    totalButtonsChecked += allBtns.length;

    if (hits.length) {
      violations.push(`${rel}: ${hits.length} / ${allBtns.length} 处缺少 type [${hits.join('; ')}]`);
    }
  }

  assert.ok(totalButtonsChecked >= 200, `全仓检查的按钮总数过少: ${totalButtonsChecked}`);
  assert.deepEqual(
    violations,
    [],
    '全仓发现未显式指定 type 的按钮（会默认为 submit 造成误提交）：\n  ' + violations.join('\n  '),
  );
});

test('判据自检：能准确识别缺失 type 的 button，显式 button 均通过', () => {
  const bad1 = '<button class="btn btn-primary" @click="save">保存</button>';
  assert.equal(findUntypedButtons(bad1).length, 1);

  const bad2 = '<button\n  class="btn btn-primary"\n  @click="save"\n>保存</button>';
  assert.equal(findUntypedButtons(bad2).length, 1);

  const ok1 = '<button type="button" class="btn" @click="save">保存</button>';
  assert.equal(findUntypedButtons(ok1).length, 0);

  const ok2 = '<button type="submit" form="as-form">提交</button>';
  assert.equal(findUntypedButtons(ok2).length, 0);
});
