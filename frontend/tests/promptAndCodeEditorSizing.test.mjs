/**
 * 提示词工坊与物理拦截器代码编辑器尺寸与等宽字体守卫闸（批 131）。
 *
 * ## 实测缺陷与背景：
 *
 * 1. 提示词工坊（PromptStudioPage）：
 *    此前单模块编辑器高度仅 `rows="12"`（实际测量高度仅约 248px），且使用了普通非等宽正文字体
 *    （font-family: inherit），在桌面大屏上呈现为一个极其局促、别扭的小输入框，无法胜任长篇
 *    提示词工程和 Markdown 规则的编排与审阅。
 *    优化后：textarea 行数扩至 24 行，设置 min-height >= 500px，统一采用 var(--ds-font-mono)
 *    并挂载代码块背景色，右侧预览同步维持 500px 均衡高度。
 *
 * 2. 决策插件源码编辑器（`InterceptorsPage`，2026-10 已随策略插件系统整套裁撤删除）：
 *    当初为它把 BaseDialog 从 xl(960px) 扩充出 2xl(1160px) 变体。页面删除后：
 *    - 该用例一并移除；
 *    - **2xl 变体保留**（通用能力，下面 CouncilPage 那条继续钉住它存在），
 *      当前无调用方，属"预留档位"而非界面缺陷。
 *
 * 3. 投委会席位提示词（CouncilPage）：
 *    参谋席位系统提示词同样扩展至 rows="20"，min-height >= 400px，统一采用等宽字体。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

test('PromptStudioPage 提示词主编辑区必须具备宽敞高度与等宽字体排版', () => {
  const vue = readFileSync(path.join(SRC, 'views/admin/PromptStudioPage.vue'), 'utf8');

  // 行数检查
  const rowsMatch = vue.match(/<textarea[^>]*class="[^"]*ps-textarea[^"]*"[^>]*rows="(\d+)"/) ||
                    vue.match(/<textarea[^>]*rows="(\d+)"[^>]*class="[^"]*ps-textarea[^"]*"/);
  assert.ok(rowsMatch, '未找到 ps-textarea 元素');
  const rows = parseInt(rowsMatch[1], 10);
  assert.ok(rows >= 20, `ps-textarea 行数过小 (${rows} < 20)，必须为长提示词预留宽敞视口`);

  // CSS 样式检查
  assert.match(
    vue,
    /\.ps-textarea\s*\{[^}]*min-height:\s*5\d\dpx/,
    'ps-textarea CSS 缺少 min-height >= 500px 声明',
  );
  assert.match(
    vue,
    /\.ps-textarea\s*\{[^}]*font-family:\s*var\(--ds-font-mono\)/,
    'ps-textarea 必须使用 var(--ds-font-mono) 等宽字体',
  );
});

test('CouncilPage 席位提示词编辑区与 BaseDialog 2xl 规范守卫', () => {
  const councilVue = readFileSync(path.join(SRC, 'views/admin/CouncilPage.vue'), 'utf8');
  const baseDialogVue = readFileSync(path.join(SRC, 'components/base/BaseDialog.vue'), 'utf8');

  // CouncilPage 检查
  assert.match(
    councilVue,
    /\.cn-textarea\s*\{[^}]*min-height:\s*[34]\d\dpx/,
    'cn-textarea CSS 缺少 min-height >= 380px 声明',
  );
  assert.match(
    councilVue,
    /\.cn-textarea\s*\{[^}]*font-family:\s*var\(--ds-font-mono\)/,
    'cn-textarea 必须使用 var(--ds-font-mono) 等宽字体',
  );

  // BaseDialog 2xl 检查
  assert.match(
    baseDialogVue,
    /'2xl':\s*'1160px'/,
    'BaseDialog 必须支持 2xl (1160px) 扩展尺寸',
  );
});
