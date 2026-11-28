/**
 * BaseDialog 2xl 尺寸变体守卫闸（原 PromptStudio/Council 页面已并入 AI 指挥台）。
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

test('BaseDialog 2xl 规范守卫', () => {
  const baseDialogVue = readFileSync(path.join(SRC, 'components/base/BaseDialog.vue'), 'utf8');
  assert.match(
    baseDialogVue,
    /'2xl':\s*'1160px'/,
    'BaseDialog 必须支持 2xl (1160px) 扩展尺寸',
  );
});
