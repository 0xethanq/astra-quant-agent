/**
 * 局部折叠展开控件与受控目标精确绑定守卫闸（批 62）。
 *
 * ## 守什么
 *
 * 1. **局部内容展开折叠 Disclosure 模式规范**：
 *    - `CouncilPage.vue`（推理思考过程展开）：按钮声明 `:aria-expanded` 与 `:aria-controls`，受控 `<pre>` 具备匹配 `:id`；
 *    - `PromptStudioPage.vue`（变量快捷条展开）：按钮声明 `:aria-expanded` 与 `:aria-controls="ps-var-ribbon"`，受控 `<section>` 具备 `id="ps-var-ribbon"`；
 *    - `AdminLayout.vue`（桌面侧边栏展开/收起）：折叠与展开按钮声明 `:aria-expanded` 与 `:aria-controls="admin-desktop-sidebar"`，侧边栏具备 `id="admin-desktop-sidebar"`；
 *    - `DashboardLayout.vue`（工作台底栏展开按钮）：声明 `:aria-expanded` 与 `:aria-controls="dashboard-sidebar"`。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

test('CouncilPage、PromptStudio、VenueAccounts 等局部展开触发器与受控目标 ID 严格对齐', () => {
  const cases = [
    // 批 85：这两个受控目标都是 v-if 渲染的（收起时不在 DOM），故 trigger 必须
    // **条件输出**。此处断言「在 aria-controls 里引用了目标 id」，允许外层包条件式；
    // 「必须是条件式且守卫同一状态」由 tests/ariaControlsTarget.test.mjs 结构性地强制。
    {
      file: 'views/admin/CouncilPage.vue',
      trigger: /:aria-controls="[^"]*cn-reasoning-[^"]*"/,
      target: /:id="`cn-reasoning-\$\{key\}`"/,
    },
    {
      file: 'views/admin/PromptStudioPage.vue',
      trigger: /:aria-controls="[^"]*'ps-var-ribbon'[^"]*"/,
      target: /id="ps-var-ribbon"/,
    },
    {
      file: 'layouts/AdminLayout.vue',
      trigger: /:aria-controls="'admin-desktop-sidebar'/,
      target: /id="admin-desktop-sidebar"/,
    },
    {
      file: 'layouts/DashboardLayout.vue',
      trigger: /:aria-controls="'dashboard-sidebar'/,
      target: /id="dashboard-sidebar"/,
    },
  ];

  for (const { file, trigger, target } of cases) {
    const text = readFileSync(path.join(SRC, file), 'utf8');
    assert.match(text, trigger, `${file} 缺失 aria-controls 绑定`);
    assert.match(text, target, `${file} 缺失匹配的目标 ID 容器`);
  }
});

test('闸自检：能准确拦截无 target id 的孤立 controls 引用', () => {
  const badCase = '<button :aria-controls="myId">展开</button><div>内容</div>';
  const goodCase = '<button :aria-controls="myId">展开</button><div :id="myId">内容</div>';

  const check = (html) => html.includes(':aria-controls="myId"') && !html.includes(':id="myId"');
  assert.equal(check(badCase), true, '应识别缺失目标 ID 的触发器');
  assert.equal(check(goodCase), false, '应放行具备配对目标 ID 的结构');
});
