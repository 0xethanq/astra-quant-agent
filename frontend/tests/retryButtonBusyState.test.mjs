/**
 * 「重试 / 测试」类按钮的忙碌态守卫闸（批 71）。
 *
 * ## 守什么
 *
 * 一个不再显眼的细节：**重复触发**。
 *
 * 取数失败后的「重试」按钮、通知通道的「诊断 / 发送测试」按钮，此前有一批
 * **完全没有忙碌态** —— 既不禁用、也没有任何进行中的视觉反馈。后果有两个：
 *
 *   1. **请求风暴**：用户在慢网络下连点三次，就发出三个并发请求；而结果区只保留
 *      最后一次的响应，用户看到的"重试"实际是三次叠加，排查时难以理解；
 *   2. **无反馈的等待**：点了没反应，用户会以为按钮坏了，于是继续点 —— 与第 1 点互为因果。
 *
 * 本闸要求：**所有以 `common.retry` 为文案的按钮必须声明 `:disabled`**（运行时绑定），
 * 以及所有触发 `diagnose` / `sendTest` 的按钮必须在测试进行中禁用。
 *
 * 批 71 实测并修复 5 处：`AdminSysPage`（并取回被判定为"死状态"而删掉的 busy）、
 * `DecisionsPage` 错误块、`GatewayPage` 陈旧数据条、`RiskPage` 空态、`NotifyPage` 双按钮。
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

function templateBody(file) {
  const text = stripComments(readFileSync(file, 'utf8'));
  const tm = text.match(/<template>([\s\S]*)<\/template>/);
  return tm ? tm[1] : null;
}

test('所有「重试」按钮必须声明运行时 :disabled 忙碌态', () => {
  const bad = [];
  let total = 0;

  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const body = templateBody(file);
    if (!body) continue;

    for (const m of body.matchAll(/<button\b([^>]*?)>([\s\S]*?)<\/button>/g)) {
      const attrs = m[1];
      const inner = m[2];
      if (!inner.includes('common.retry')) continue;
      total += 1;
      if (!/:disabled=/.test(attrs)) {
        bad.push(`${rel} :: ${attrs.replace(/\s+/g, ' ').trim().slice(0, 70)}`);
      }
    }
  }

  assert.ok(total >= 10, `扫描到的重试按钮过少（${total}），疑似判据失效`);
  assert.deepEqual(bad, [], `以下重试按钮可被连点，造成并发请求风暴：\n  ${bad.join('\n  ')}`);
});

test('进行中必须给出视觉反馈：重试按钮至少要有一个忙碌态图标或文案', () => {
  const bad = [];
  const files = ['views/admin/AdminSysPage.vue', 'views/admin/BackupPage.vue', 'views/admin/SecurityPage.vue'];

  for (const rel of files) {
    const text = readFileSync(path.join(SRC, rel), 'utf8');
    const idx = text.indexOf('common.retry');
    assert.ok(idx !== -1, `${rel} 找不到重试按钮`);
    // 该按钮所在标签片段
    const tagStart = text.lastIndexOf('<button', idx);
    const tagEnd = text.indexOf('</button>', idx);
    const chunk = text.slice(tagStart, tagEnd);
    const hasBusyIcon = /Loader2[^>]*v-if=/.test(chunk) || /:class="[^"]*&&[^"]*spin/.test(chunk);
    if (!hasBusyIcon) bad.push(rel);
  }

  assert.deepEqual(bad, [], `以下重试按钮在被点击后没有任何"正在重试"的视觉反馈：\n  ${bad.join('\n  ')}`);
});

test('通知通道的诊断 / 发送测试按钮必须在测试进行中禁用', () => {
  const text = readFileSync(path.join(SRC, 'views/admin/NotifyPage.vue'), 'utf8');

  for (const fn of ['diagnose', 'sendTest']) {
    const idx = text.indexOf(`@click="${fn}(c.key)"`);
    assert.ok(idx !== -1, `NotifyPage 找不到 ${fn} 按钮`);
    const tagStart = text.lastIndexOf('<button', idx);
    const tag = text.slice(tagStart, idx);
    assert.match(
      tag,
      /:disabled="testResults\[c\.key\]\?\.status === 'testing'"/,
      `${fn} 按钮未在测试进行中禁用 —— 连点会并发发起多次请求`,
    );
  }
});

test('闸自检：能准确拦截无忙碌态的重试按钮', () => {
  const naive = '<button class="btn" @click="load"><span>{{ t(\'common.retry\') }}</span></button>';
  const guarded = '<button class="btn" :disabled="loading" @click="load"><span>{{ t(\'common.retry\') }}</span></button>';
  const check = (h) => h.includes('common.retry') && !/:disabled=/.test(h);

  assert.equal(check(naive), true, '应拦截无 :disabled 的重试按钮');
  assert.equal(check(guarded), false, '应放行已加忙碌态的重试按钮');
});
