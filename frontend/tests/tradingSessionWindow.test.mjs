/**
 * 「交易时段」设置卡的守卫闸（2026-09-30）。
 *
 * ## 为什么这张卡值得单独一道闸
 *
 * 它是**唯一**能改变交易进程跑不跑的用户界面：窗口识别错一位、星期语义反了，
 * 代价不是"界面不好看"，而是「该休市时烧掉 ~4M token/天」或「该跑的时候不下单」。
 * 界面层有三件事必须钉死：
 *
 * 1. **星期文案必须走 i18n 查表**，不能在模板里硬编码一个中文数组 ——
 *    硬编码数组在英文界面下会显示中文，且后端 `days` 语义（0=周一）会与文案漂移；
 * 2. **判定结果只能渲染后端给的 `state`**：前端不得自己比时间（判定口径只有一份实现，
 *    见 `scripts/trader/session.py`），否则会出现"页面说在窗口内、引擎按窗口外跑"；
 * 3. **文案双向齐全 + 按钮显式 type + 错误必须被通报**（WCAG 4.1.3）。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { zhAdminGateway } from '../src/locales/zh/admin/gateway.ts';
import { enAdminGateway } from '../src/locales/en/admin/gateway.ts';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const PAGE = path.join(SRC, 'views/admin/GatewayPage.vue');
const CJK = /[\u4e00-\u9fff]/;

/** 递归取键路径集合（值类型不参与比较，只比结构）。 */
function keyPaths(node, prefix = '') {
  const out = [];
  for (const [key, value] of Object.entries(node)) {
    const here = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      out.push(...keyPaths(value, here));
    } else {
      out.push(here);
    }
  }
  return out.sort();
}

test('交易时段文案中英双语必须逐键对齐', () => {
  const zh = keyPaths(zhAdminGateway.session);
  const en = keyPaths(enAdminGateway.session);
  assert.deepEqual(en, zh, 'en/zh 的 admin.gateway.session 键集合必须完全一致');
  assert.ok(zh.length >= 25, `键数量异常偏少（${zh.length}）—— 闸可能解析失效`);
});

test('星期文案必须齐备 7 天，且与后端 0=周一 的口径对齐', () => {
  for (const [locale, pack] of [['zh', zhAdminGateway], ['en', enAdminGateway]]) {
    for (let day = 0; day <= 6; day += 1) {
      const text = pack.session.weekdays[day];
      assert.equal(typeof text, 'string', `${locale} 缺少 weekdays.${day}`);
      assert.ok(text.length > 0, `${locale} 的 weekdays.${day} 是空串`);
    }
  }
  assert.equal(zhAdminGateway.session.weekdays[0], '周一', '0 必须是周一（Python weekday() 口径）');
  assert.equal(zhAdminGateway.session.weekdays[6], '周日');
});

test('三种模式的文案必须齐备（full / manage_only / off）', () => {
  for (const [locale, pack] of [['zh', zhAdminGateway], ['en', enAdminGateway]]) {
    for (const mode of ['full', 'manage_only', 'off']) {
      assert.ok(pack.session.mode[mode], `${locale} 缺少 mode.${mode}`);
    }
  }
});

/** 与既有门禁同款：先剥注释再扫描，避免"注释里的中文"造成假红。 */
const stripComments = (source) => source
  .replace(/<!--[\s\S]*?-->/g, ' ')
  .replace(/\/\*[\s\S]*?\*\//g, ' ')
  .replace(/(^|\s)\/\/[^\n]*/g, ' ');

test('页面不得硬编码星期数组或中文界面文案', () => {
  const vue = readFileSync(PAGE, 'utf8');
  assert.doesNotMatch(
    vue, /\[\s*'周一'[\s\S]{0,120}?\]/,
    "星期文案不得硬编码成中文字面量数组 —— 必须走 t('admin.gateway.session.weekdays.N')",
  );
  assert.match(vue, /admin\.gateway\.session\.weekdays\.\$\{day\}/,
               '星期标签必须按 day 索引查 i18n 表');
  const bare = stripComments(vue);
  const cjkLines = bare.split('\n')
    .map((line, index) => [line.trim(), index + 1])
    .filter(([line]) => CJK.test(line) && !/^\s*\*/.test(line));
  assert.deepEqual(cjkLines, [],
                   'GatewayPage 的 .vue 里不得出现中文界面文案（注释除外）：' + JSON.stringify(cjkLines));
});

test('判定结果必须来自后端 state，前端不得自己比时间', () => {
  const vue = readFileSync(PAGE, 'utf8');
  assert.match(vue, /session\.value\?\.state\?\.mode/, '模式必须读后端 state.mode');
  assert.match(vue, /session\.value\?\.state\?\.next_change_bj/, '下一切换时刻必须读后端 state');
  assert.match(vue, /session\.value\?\.state\?\.errors/, '配置告警必须读后端 state.errors');
  assert.doesNotMatch(vue, /new Date\(\).*draftWindows|toLocaleTimeString\(\)\s*<|\.weekday\(\)/,
                      '前端不得自行判定窗口（判定口径只有 scripts/trader/session.py 一份实现）');
});

test('时段卡片里的按钮必须显式声明 type', () => {
  const vue = readFileSync(PAGE, 'utf8');
  const start = vue.indexOf('gw-sess-windows');
  const end = vue.indexOf('gw-sess-actions');
  assert.ok(start > 0 && end > start, '定位不到时段卡片模板片段（选择器需要更新）');
  const fragment = vue.slice(vue.lastIndexOf('<!--', start), vue.indexOf('</section>', end));
  const buttons = fragment.match(/<button\b[^>]*>/g) || [];
  assert.ok(buttons.length >= 4, `时段卡片里按钮数量异常偏少（${buttons.length}）`);
  for (const button of buttons) {
    assert.match(button, /type="(button|submit)"/,
                 `时段卡片的按钮缺少显式 type：${button}`);
  }
});

test('条件渲染的配置告警必须被读屏器通报', () => {
  const vue = readFileSync(PAGE, 'utf8');
  assert.match(vue, /v-if="sessionErrors\.length"\s+role="status"\s+aria-live="polite"/,
               '配置告警容器需要 role=status + aria-live=polite');
  assert.match(vue, /v-if="sessionError"\s+role="alert"/,
               '保存失败容器需要 role=alert');
});

test('恢复全天候运行必须走确认框（放松方向的操作）', () => {
  const vue = readFileSync(PAGE, 'utf8');
  const body = vue.slice(vue.indexOf('async function resumeFullTime'), vue.indexOf('const sessionMode'));
  assert.match(body, /await ask\(/, '放松方向（恢复 7×24 与开新仓）必须二次确认');
  assert.match(body, /if \(!ok\) return/, '取消确认时不得写入');
  assert.match(body, /danger: true/, '该操作应标注为危险方向（relax）');
});
