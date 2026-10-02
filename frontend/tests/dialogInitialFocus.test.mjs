/**
 * 危险操作确认弹窗的初始焦点守卫闸（批 69）。
 *
 * ## 背景：默认落点是对的，但有一类弹窗适用例外
 *
 * `useModalFocus` 的默认落点是**面板容器**（`tabindex="-1"`）而非第一个可聚焦项 ——
 * 这是刻意的：否则鼠标用户打开任何弹窗，确认/关闭按钮上就会多出一圈蓝环，
 * 视觉上像"已经按下了什么"。
 *
 * 但批 69 实测发现另一类弹窗：**它存在的唯一目的就是让用户输入一段文本**。
 * 全站 7 处属于此类 —— 危险操作的确认短语（逐字门禁）、紧急平仓的管理员密码、
 * 新建插件的文件名、源码编辑器的代码区。对这些弹窗而言：
 *
 *   - 焦点落在面板容器上意味着键盘用户**必须先 Tab 一次**才能开始输入；
 *   - 移动端意味着软键盘不会自动弹出，用户要先点一下输入框；
 *   - 而"落到面板"想避免的误触后果在这里根本不存在 —— 打字不会造成破坏。
 *
 * 所以本闸钉两件事：
 *   A. 该例外必须由调用方**显式**声明（`initial-focus`），不得改成全局默认；
 *   B. 全站所有以「输入确认短语/凭证」为目的的弹窗都必须声明它。
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

const stripComments = (t) => t.replace(/<!--[\s\S]*?-->/g, '');

/** 该弹窗内部是否含"确认短语 / 密码"这类必须立刻输入的控件。 */
function needsInitialFocus(body, startIdx, endIdx) {
  const inner = body.slice(startIdx, endIdx);
  return /v-model="(confirmPhrase|replayPhrase|closePassword|closePhraseInput|capitalConfirm|gateExecPhrase|newFilename|editingCode|runDialog\.phrase|typed)"/.test(inner);
}

test('useModalFocus 必须支持显式初始焦点，且找不到时回落面板容器', () => {
  const text = readFileSync(path.join(SRC, 'composables/useModalFocus.ts'), 'utf8');

  assert.match(text, /initialFocus\?: \(\) => HTMLElement \| null \| undefined/, '未声明 initialFocus 选项');
  assert.match(
    text,
    /\(initialFocus\?\.\(\) \|\| panel\.value\)\?\.focus\?\.\(\)/,
    'initialFocus 未优先于面板容器，或缺少回落',
  );
  // 默认落点不得被改成第一个可聚焦项
  assert.ok(
    !/focusables\(\)\[0\]\?\.focus\(\)/.test(text.split('async function sync')[1] || ''),
    '默认落点被改成了第一个可聚焦项 —— 会让鼠标用户看到多余焦点环',
  );
});

test('BaseDialog 必须透出 initialFocus 并在面板内部解析选择器', () => {
  const text = readFileSync(path.join(SRC, 'components/base/BaseDialog.vue'), 'utf8');

  assert.match(text, /initialFocus\?: string/, 'BaseDialog 未声明 initialFocus 属性');
  assert.match(
    text,
    /panel\.value\?\.querySelector<HTMLElement>\(props\.initialFocus\)/,
    'BaseDialog 未在面板内部查找初始焦点元素',
  );
});

test('所有确认短语/凭证类弹窗必须声明 initial-focus', () => {
  const bad = [];
  const seen = [];

  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const text = stripComments(readFileSync(file, 'utf8'));
    const tm = text.match(/<template>([\s\S]*)<\/template>/);
    if (!tm) continue;
    const body = tm[1];

    for (const m of body.matchAll(/<BaseDialog\b([^>]*?)>/g)) {
      const end = body.indexOf('</BaseDialog>', m.index);
      const inner = body.slice(m.index, end === -1 ? body.length : end);
      if (!needsInitialFocus(body, m.index, end === -1 ? body.length : end)) continue;

      seen.push(rel);
      if (!/initial-focus=/.test(m[1])) {
        bad.push(`${rel} :: 该弹窗以输入确认短语/凭证为目的，却未声明 initial-focus`);
      }
    }
  }

  // 下限是"防止判据失效导致一个都没识别到"的防空转护栏。
  // 2026-10：InterceptorsPage（新建插件 + 源码编辑器两个弹窗）随策略插件系统删除，
  // 识别数由 6 降为 4。
  assert.ok(seen.length >= 4, `识别到的确认类弹窗过少（${seen.length}），疑似判据失效`);
  assert.deepEqual(bad, [], `以下弹窗键盘用户打开后还要多按一次 Tab：\n  ${bad.join('\n  ')}`);
});

test('initial-focus 是显式例外，不得大面积铺开', () => {
  let declared = 0;
  for (const file of vueFiles(SRC)) {
    const text = readFileSync(file, 'utf8');
    for (const m of text.matchAll(/<BaseDialog\b([^>]*?)>/g)) {
      if (/initial-focus=/.test(m[1])) declared += 1;
    }
  }
  // 2026-10：InterceptorsPage 的两个弹窗（新建插件 / 源码编辑器）随策略插件系统
  // 整套裁撤而删除 ⇒ 使用处由 7 降为 5，与上一条（识别数 ≥4）一致。
  assert.equal(declared, 5, `initial-focus 使用处应为 5（实测 ${declared}）；若确需增减请同步复核本条与上一条`);
});

test('闸自检：能准确拦截漏声明 initial-focus 的确认弹窗', () => {
  const phraseDialog = '<BaseDialog :open="x"><input v-model="confirmPhrase" /></BaseDialog>';
  const goodDialog = '<BaseDialog :open="x" initial-focus="input"><input v-model="confirmPhrase" /></BaseDialog>';

  const check = (html) => {
    const m = html.match(/<BaseDialog\b([^>]*?)>/);
    const hasField = /v-model="(confirmPhrase|replayPhrase|closePassword)"/.test(html);
    return hasField && !/initial-focus=/.test(m[1]);
  };

  assert.equal(check(phraseDialog), true, '应拦截漏声明初始焦点的确认弹窗');
  assert.equal(check(goodDialog), false, '应放行已声明的确认弹窗');
  assert.equal(check('<BaseDialog :open="x"><p>纯说明</p></BaseDialog>'), false, '纯说明弹窗不应被要求');
});
