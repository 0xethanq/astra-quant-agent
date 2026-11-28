/**
 * 键盘可达闸（批 43）。
 *
 * ## 守什么
 *
 * 一个挂着 `@click` 的**非原生**元素（`div`/`tr`/`article`/`th`/`span`…）默认是
 * 鼠标专享：键盘用户 Tab 不到、`Enter` 不响应，屏幕阅读器也不播报它可操作。
 * 本仓实测有 25 处（可排序表头 9、可点击行 5、供应商卡/模块列表/审计行/品牌区…），
 * 全部只有鼠标能操作。
 *
 * 判据（逐个 `<tag ... @click>` 静态检查）：
 *   - 原生可聚焦标签（`button` / `a` / `input` / `select` / `textarea` / `label` / `summary`）→ 天然满足；
 *   - 非原生 → 必须同时具备 `tabindex` **且** 有 `@keydown` 处理；
 *   - **遮罩层例外**：点击遮罩关闭是纯鼠标的便利操作（键盘走 Escape，已由
 *     `useModalFocus` 统一），故点击表达式为"关掉自己"的遮罩进白名单。
 *
 * 遮罩白名单**逐条登记**（文件 + 计数），不是正则放水 —— 多一处遮罩就会红，
 * 逼着后来者确认"这里确实只是遮罩"。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

/** 天然可聚焦/可操作的原生标签 */
const NATIVE = new Set(['button', 'a', 'input', 'select', 'textarea', 'label', 'summary']);

/**
 * 遮罩层白名单：文件 → 允许的"关闭自己"表达式集合。
 * 这些点击处理只服务于鼠标，且对应模态的键盘路径是 Escape（见 useModalFocus）。
 */
const SCRIM_ALLOWLIST = {
  'components/dashboard/TrajectoryPanel.vue': ["emit('close')"],
  'layouts/AdminLayout.vue': ['drawerOpen = false'],
  'layouts/DashboardLayout.vue': ['mobileNavOpen = false'],
  'views/admin/agent/AgentSessionDrawer.vue': ["emit('close')"],
  'views/docs/DocsView.vue': ['mobileMenuOpen = false', 'zoomImage = null'],
};

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

const stripComments = (text) =>
  text
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/^\s*\/\/.*$/gm, '');

/** 抽出所有非原生 `@click` 元素及其属性串 */
function nonNativeClicks(file, body) {
  const out = [];
  const re = /<([a-z][a-z0-9-]*)\b((?:[^>"]|"[^"]*")*?)@click(?:\.\w+)*="([^"]*)"((?:[^>"]|"[^"]*")*?)>/g;
  for (const m of body.matchAll(re)) {
    const [, tag, pre, expr, post] = m;
    if (NATIVE.has(tag)) continue;
    out.push({ tag, attrs: pre + post, expr });
  }
  return out;
}

function violations() {
  const bad = [];
  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file).replace(/\\/g, '/');
    const text = stripComments(readFileSync(file, 'utf8'));
    const tpl = text.match(/<template>([\s\S]*)<\/template>/);
    if (!tpl) continue;
    for (const { tag, attrs, expr } of nonNativeClicks(rel, tpl[1])) {
      const allowed = SCRIM_ALLOWLIST[rel] || [];
      if (allowed.includes(expr)) continue;
      const hasTab = /\btabindex\b/.test(attrs);
      const hasKey = /@keydown/.test(attrs);
      if (!hasTab || !hasKey) {
        bad.push(`${rel}: <${tag} @click="${expr.slice(0, 30)}"> tabindex=${hasTab} keydown=${hasKey}`);
      }
    }
  }
  return bad;
}

test('非原生 @click 元素必须键盘可达（tabindex + keydown）', () => {
  const bad = violations();
  assert.deepEqual(
    bad,
    [],
    `这些元素只有鼠标能操作（键盘 Tab 不到、Enter 无效）：\n  ${bad.join('\n  ')}\n` +
      '修法：改成 <button>/<a>，或补 tabindex="0" + @keydown.enter/@keydown.space.prevent；' +
      '若确实只是遮罩，请登记到 SCRIM_ALLOWLIST。',
  );
});

test('可排序表头不得把 @click 挂在 <th> 上', () => {
  const bad = [];
  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file).replace(/\\/g, '/');
    const text = stripComments(readFileSync(file, 'utf8'));
    const tpl = text.match(/<template>([\s\S]*)<\/template>/);
    if (!tpl) continue;
    for (const m of tpl[1].matchAll(/<th\b((?:[^>"]|"[^"]*")*?)>/g)) {
      if (/@click/.test(m[1])) bad.push(`${rel}: <th @click=…>（${m[1].trim().slice(0, 40)}）`);
    }
  }
  assert.deepEqual(
    bad,
    [],
    `表头排序必须落在真按钮上（<th> 不可聚焦）：\n  ${bad.join('\n  ')}`,
  );
});

test('遮罩白名单不空转：登记的文件确实存在且用了该表达式', () => {
  for (const [rel, exprs] of Object.entries(SCRIM_ALLOWLIST)) {
    const text = stripComments(readFileSync(path.join(SRC, rel), 'utf8'));
    for (const e of exprs) {
      assert.ok(text.includes(e), `${rel} 不再包含遮罩表达式 ${e}，请更新白名单`);
    }
  }
});

test('闸自检：判据能真的命中', () => {
  const check = (attrs) => /\btabindex\b/.test(attrs) && /@keydown/.test(attrs);
  assert.equal(check(''), false, '裸 @click 应判失败');
  assert.equal(check('tabindex="0"'), false, '只有 tabindex 不够（Enter 仍无响应）');
  assert.equal(check('tabindex="0" @keydown.enter="f()"'), true);
});
