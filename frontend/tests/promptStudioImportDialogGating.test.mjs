/**
 * 提示词导入弹窗按钮门禁与错误态无障碍守卫闸（批 129）。
 *
 * ## 实测缺陷与背景：
 *
 * `PromptStudioPage.vue`（导入提示词方案弹窗）：
 *   - 导入按钮此前没有任何 `:disabled` 校验（裸可点），在未选择文件也未输入 JSON 时点击直接报错；
 *   - 缺少 `importing` 防重入与加载态；
 *   - JSON 文本域在解析失败或接口报错时，缺少 `.is-bad` 红色警示与 `:aria-invalid="true"` 无障碍同步。
 *
 * 修复后：
 * - 提示词导入按钮绑定 `:disabled="importing || !importRawJson.trim()"` 并增加加载态动画；
 * - 提示词 JSON 文本域在报错时呈现 `.is-bad` 红色边框并同步 `:aria-invalid="true"`。
 *
 * ⚠️ 2026-10：`InterceptorsPage`（决策插件工位）随策略插件系统整套裁撤而删除，
 * 原「新建插件弹窗」用例一并移除。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

test('PromptStudioPage 方案导入弹窗必须受 importRawJson 门禁控制且具备错误态反馈', () => {
  const vue = readFileSync(path.join(SRC, 'views/admin/PromptStudioPage.vue'), 'utf8');

  assert.match(
    vue,
    /:disabled="importing\s*\|\|\s*!importRawJson\.trim\(\)"/,
    'PromptStudioPage 导入按钮缺少 !importRawJson.trim() 前置门禁',
  );
  assert.match(
    vue,
    /:class="\{\s*'is-bad':\s*!!importFileError\s*\}"/,
    'PromptStudioPage importRawJson 文本域缺少 is-bad 动态类',
  );
  assert.match(
    vue,
    /:aria-invalid="!!importFileError\s*\?\s*'true'\s*:\s*undefined"/,
    'PromptStudioPage importRawJson 文本域缺少 aria-invalid 动态无障碍状态',
  );
});
