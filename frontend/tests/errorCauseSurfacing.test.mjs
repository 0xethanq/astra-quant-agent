/**
 * 内联错误块必须透出真实原因、且不得把「无数据」谎报为「故障」守卫闸（批 72）。
 *
 * ## 一、通用文案不得掩盖真实原因
 *
 * 自建交易控制台的运维看的就是**真实错误码与后端原文**（401 未授权 / 500 表缺失 /
 * 连接被拒）。批 72 实测：5 个页面的内联错误块把真实原因丢掉，一律硬写
 * `t('common.networkError')`（「网络异常，请检查连接后重试」）——
 * 而真实原因只出现在一条会自己消失的 toast 里，用户错过就无从查起。
 *
 * 更深的根因：`useLlmConfig.loadConfig` 的 catch **只 `console.error`**，
 * 真实原因在数据层就被丢弃，三个消费方页面根本没得显示。
 *
 * 本闸要求：`common.networkError` 只能作为 **`||` 回退**出现，不得单独充当错误描述。
 *
 * ## 二、「无数据」不得谎报为「故障」
 *
 * `PolicySnapshotPage` 的分支顺序是 `loading → 有快照 → else`，于是
 * **一次成功响应但后台尚无快照**也会落进 else，页面声称
 * 「获取策略版本快照失败 + 网络异常」—— 把正常响应谎报成故障，
 * 运维会去排查根本不存在的网络问题。失败态与无数据态必须分流。
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

test('common.networkError 只能作为回退文案，不得掩盖真实原因', () => {
  const bad = [];
  let seen = 0;

  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const body = stripComments(readFileSync(file, 'utf8'));

    // 覆盖两种写法：插值 {{ ... }} 与属性绑定 :desc="..." / :text="..."
    // （初版只扫了插值，漏掉 RiskPage 的 :desc 绑定 —— 变异测试当场发现）
    const expressions = [
      ...[...body.matchAll(/\{\{\s*([^}]*?)\s*\}\}/g)].map((m) => m[1]),
      ...[...body.matchAll(/:([\w-]+)="([^"]*)"/g)].map((m) => m[2]),
    ];

    for (const expr of expressions) {
      if (!expr.includes('common.networkError')) continue;
      seen += 1;
      if (!expr.includes('||')) bad.push(`${rel} :: ${expr.trim()}`);
    }
  }

  assert.ok(seen >= 1, `命中 common.networkError 的表达式过少（${seen}），疑似判据失效`);
  assert.deepEqual(bad, [], `以下位置只用通用文案、丢掉了真实错误原因：\n  ${bad.join('\n  ')}`);
});

test('数据层不得吞掉真实错误：loadConfig 必须记录失败原因', () => {
  const text = readFileSync(path.join(SRC, 'composables/useLlmConfig.ts'), 'utf8');

  assert.match(text, /const cfgError = ref\(''\)/, 'useLlmConfig 未记录配置拉取失败原因');
  assert.match(text, /cfgError\.value = ''/, '成功路径未清空上一次的失败原因');
  assert.match(text, /cfgError\.value = String\(e\?\.message \|\| e\)/, 'catch 未写入真实原因');
  assert.match(text, /\r?\n\s+cfgError,\r?\n/, 'cfgError 未暴露给消费方');

  // 必须只 console.error 的老毛病不得回潮：catch 里除了日志还要有状态写入
  const catchBlock = text.slice(text.indexOf('async function loadConfig'));
  const end = catchBlock.indexOf('} finally');
  assert.match(catchBlock.slice(0, end), /cfgError\.value/, 'catch 里没有把原因写进状态');
});

test('拉取失败态与「无数据」态必须分流（PolicySnapshotPage）', () => {
  const text = readFileSync(path.join(SRC, 'views/admin/PolicySnapshotPage.vue'), 'utf8');

  // 失败态：真实原因
  assert.match(
    text,
    /v-else-if="errorMsg"[\s\S]{0,200}:desc="errorMsg"/,
    '失败分支未透出真实错误原因',
  );
  // 无数据态：独立文案，不再复用「拉取失败」
  assert.match(
    text,
    /v-else[\s\S]{0,200}:text="t\('admin\.policySnapshot\.emptySnapshot'\)"/,
    '「尚无快照」未从失败态分流出来',
  );
  // 失败态绝不能出现在 else 分支上（那才是谎报的根源）
  const elseBlock = text.slice(text.indexOf('v-else-if="errorMsg"'));
  assert.ok(
    !/v-else\s[\s\S]{0,120}err\.fetchFailed/.test(elseBlock),
    'else 分支仍在声称「拉取失败」—— 会把成功响应谎报成故障',
  );
});

test('闸自检：能准确拦截丢原因的通用文案与混用的失败/空态', () => {
  const masking = `<p class="state-desc">{{ t('common.networkError') }}</p>`;
  const fallback = `<p class="state-desc">{{ loadError || t('common.networkError') }}</p>`;
  const check = (h) => {
    const exprs = [
      ...[...h.matchAll(/\{\{\s*([^}]*?)\s*\}\}/g)].map((m) => m[1]),
      ...[...h.matchAll(/:([\w-]+)="([^"]*)"/g)].map((m) => m[2]),
    ].filter((e) => e.includes('common.networkError'));
    return exprs.length > 0 && exprs.some((e) => !e.includes('||'));
  };
  assert.equal(check(masking), true, '应拦截只用通用文案的错误块');
  assert.equal(check(fallback), false, '应放行带真实原因回退的错误块');
  assert.equal(
    check('<BaseEmpty :desc="t(\'common.networkError\')" />'),
    true,
    '应拦截只用通用文案的属性绑定（初版漏掉的就是这一类）',
  );
  assert.equal(
    check('<BaseEmpty :desc="loadError || t(\'common.networkError\')" />'),
    false,
    '应放行带回退的属性绑定',
  );

  const lyingElse = '<BaseEmpty v-else :text="t(\'admin.policySnapshot.err.fetchFailed\')">';
  const honest = '<BaseEmpty v-else :text="t(\'admin.policySnapshot.emptySnapshot\')">';
  const liesAsFailure = (h) => /v-else\s[\s\S]{0,120}err\.fetchFailed/.test(h);
  assert.equal(liesAsFailure(lyingElse), true, '应拦截把无数据谎报为失败的 else 分支');
  assert.equal(liesAsFailure(honest), false, '应放行已分流的空态');
});
