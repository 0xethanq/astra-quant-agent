/**
 * 多行文本域（textarea.field）高度挤压与拼写检查波浪线守卫闸（批 122）。
 *
 * ## 实测出来的真缺陷：
 *
 * 1. 全站多行文本框全部被压成 30px 单行缝隙：
 *    在 `src/styles/components.css` 中：
 *    ```css
 *    .field, .input, select.input, textarea.input { height: var(--h-md); padding: 0 10px; }
 *    textarea.input { height: auto; padding: 8px 10px; }
 *    ```
 *    旧样式只声明了 `textarea.input`，而全仓所有 textarea 均使用 `class="field"`！
 *    导致提示词工坊（rows="12"）、投委会席位提示词（rows="10"）、策略快照描述（rows="3"）等
 *    全部继承了 `.field` 的 `height: var(--h-md)`（实测 30px 高、上下 padding 0px）！
 *    一个 12 行的提示词编辑器被死死压进 30px 的单行缝隙里，用户只能像透过投信口一样读写长文案。
 *    实测修复前：`height: 30px`；修复后：`height: 248.25px`（完整展开 12 行，带 8px 内边距）。
 *
 * 2. 提示词与 JSON 文本域缺少 `spellcheck="false"`：
 *    规则 Prompt、策略上下文与 JSON 导入框中包含大量专业词汇、缩写与代码结构，
 *    浏览器默认开启 spellcheck 会在全屏标满红色波浪线，造成严重视觉干扰。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

test('components.css 必须为 textarea.field 声明 height: auto 与上下 padding', () => {
  const raw = readFileSync(path.join(SRC, 'styles/components.css'), 'utf8');
  // 剥除注释，确保检查的是真正的 CSS 规则
  const css = raw.replace(/\/\*[\s\S]*?\*\//g, ' ');
  assert.match(
    css,
    /textarea\.field[^{]*\{[^}]*height:\s*auto;[^}]*padding:\s*8px 10px;/,
    'components.css 缺少 textarea.field { height: auto; padding: 8px 10px } 规则，textarea 会被压成 30px',
  );
});

test('旧独立编辑器已退役且 Agent 指挥台多行输入域保持 class="field" 与 spellcheck="false"', () => {
  for (const retired of [
    'views/admin/PromptStudioPage.vue',
    'views/admin/CouncilPage.vue',
    'views/admin/EvolutionPage.vue',
  ]) {
    assert.equal(existsSync(path.join(SRC, retired)), false, `${retired} 应已在后台 12→6 精简中退役`);
  }

  const agentConsole = readFileSync(path.join(SRC, 'views/admin/AgentConsolePage.vue'), 'utf8');
  assert.match(
    agentConsole,
    /<textarea[\s\S]*?spellcheck="false"[\s\S]*?class="field\b/,
    'AgentConsolePage 对话输入域缺少 spellcheck="false" 或 class="field"',
  );
});
