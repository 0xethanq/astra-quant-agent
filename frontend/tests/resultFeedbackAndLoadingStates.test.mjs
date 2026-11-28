/**
 * 用户动作的内联结果反馈：通报语义与真假加载态守卫闸（批 70）。
 *
 * ## 一、通报语义（WCAG 4.1.3 Status Messages）
 *
 * 批 67 处理的是**错误容器**；本闸处理同一族里的另一半 —— **结果/成功容器**。
 *
 * `useAsyncAction` 的设计约定是「未给 `onError` 且未声明 `silent` 时默认弹 toast，
 * 避免静默失败」。但有几处**刻意**走另一条路：把错误出口一对一写进内联结果面板、
 * 明确不弹 toast。此时那块内联面板就成了**唯一反馈** —— 它若不声明 live 语义，
 * 视障用户按下按钮后收不到任何提示。
 *
 * 本闸要求：由结果/成败状态条件渲染、且承载用户动作反馈的容器，必须按成败分级通报 ——
 * 失败 `role="alert"`（断言式），其余 `role="status"`（礼貌式）。
 *
 * ## 二、真假加载态（视觉正确性）
 *
 * 更隐蔽的一类：**同一个状态字符串同时承载「正在加载」与「加载失败」**，
 * 而模板无条件渲染旋转图标 —— 失败时用户看到的是「转圈 + 报错」，
 * 视觉上像是在继续加载而不是已经失败。加载指示与错误指示必须分流。
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

test('内联结果面板按成败分级通报（回归锚点）', () => {
  const cases = [
    [
      'views/admin/AboutPage.vue',
      /:role="updateResult\.error \? 'alert' : 'status'"/,
      'AboutPage 系统更新结果面板',
    ],
    [
      'views/admin/NotifyPage.vue',
      /:role="testTone\(testResults\[c\.key\]\.status\) === 'badge-down' \? 'alert' : 'status'"/,
      'NotifyPage 通道测试结果',
    ],
    [
      'views/admin/security/SecurityEmergencyTab.vue',
      /:role="snapshotError \? 'alert' : 'status'"/,
      'SecurityPage 持仓刷新状态',
    ],
  ];

  for (const [rel, re, label] of cases) {
    const text = readFileSync(path.join(SRC, rel), 'utf8');
    assert.match(text, re, `${rel} 的「${label}」缺少按成败分级的通报语义`);
    assert.match(text, /aria-live="polite"/, `${rel} 的「${label}」缺少 aria-live`);
  }
});

test('刻意不弹 toast 的动作，其内联反馈必须自带通报语义', () => {
  const bad = [];

  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const raw = readFileSync(file, 'utf8');
    const script = raw.split('</script>')[0];
    if (!script.includes('useToast')) continue;

    // 只关心「用了 useAsyncAction 的 onError（即主动接管错误出口、不弹默认 toast）」
    if (!/onError:/.test(script)) continue;

    // 该文件的 onError 是否同时也弹了 toast —— 弹了就不必依赖内联面板
    const inlineOnly = [...script.matchAll(/onError:[^\n]*/g)].some((m) => !/toast\./.test(m[0]));
    if (!inlineOnly) continue;

    const body = stripComments(raw).match(/<template>([\s\S]*)<\/template>/);
    const has = body && /role="alert"|role="status"|aria-live/.test(body[1]);
    if (!has) bad.push(`${rel} :: onError 接管了错误出口但页面无任何 live 通报`);
  }

  assert.deepEqual(bad, [], `以下页面吞掉了错误出口且不通报：\n  ${bad.join('\n  ')}`);
});

test('加载态与失败态必须分流，不得共用旋转图标', () => {
  const logic = readFileSync(path.join(SRC, 'views/admin/security/useSecurityAdmin.ts'), 'utf8');
  const text = readFileSync(path.join(SRC, 'views/admin/security/SecurityEmergencyTab.vue'), 'utf8');

  // 分流标志
  assert.match(logic, /const snapshotError = ref\(false\)/, 'SecurityPage 未区分加载态与失败态');
  assert.match(logic, /snapshotError\.value = true/, '失败分支未置位 snapshotError');

  // 旋转图标必须受 !snapshotError 约束
  assert.match(
    text,
    /<Loader2 v-if="!snapshotError"/,
    '失败时仍会渲染旋转图标 —— 用户看到「转圈 + 报错」，误以为还在加载',
  );
  // 必须给失败态一个非旋转的图标
  assert.match(text, /<AlertTriangle v-else/, '失败态缺少静态警示图标');
  // 失败态要有区别于占位符灰的语义色
  assert.match(text, /\.sc-loading\.is-error/, '失败态缺少独立样式');
  assert.match(text, /border-left: 2px solid var\(--down\)/, '失败态未沿用本页「左竖线表语义」的语汇');
});

test('闸自检：能准确拦截静默结果面板与假加载态', () => {
  const silent = '<div v-if="updateResult" class="ab-result">ok</div>';
  const announced = '<div v-if="updateResult" :role="updateResult.error ? \'alert\' : \'status\'">ok</div>';
  // 注意：动态绑定写作 :role="x ? 'alert' : 'status'"，字面量用的是单引号，
  // 因此判据必须同时认 :role= 与静态 role="/role='。
  const hasLive = (h) => /(:?\brole="|aria-live)/.test(h);
  const checkLive = (h) => /v-if="[^"]*(Result|result)/.test(h) && !hasLive(h);
  assert.equal(checkLive(silent), true, '应拦截静默结果面板');
  assert.equal(checkLive(announced), false, '应放行已通报的结果面板');

  const fakeLoading = '<p v-if="state" class="sc-loading"><Loader2 class="sc-spin" />{{ state }}</p>';
  const realLoading = '<p v-if="state" class="sc-loading"><Loader2 v-if="!snapshotError" class="sc-spin" /><AlertTriangle v-else />{{ state }}</p>';
  const checkSpinner = (h) => /<Loader2 [^>]*class="sc-spin"/.test(h) && !/v-if="!snapshotError"/.test(h);
  assert.equal(checkSpinner(fakeLoading), true, '应拦截失败时仍转圈的加载态');
  assert.equal(checkSpinner(realLoading), false, '应放行已分流的加载态');
});
