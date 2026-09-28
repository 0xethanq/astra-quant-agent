/**
 * 关键运维信息不得只挂在鼠标悬停的 `title` 上（批 73）。
 *
 * ## 为什么 `title` 不算"显示了"
 *
 * `title` 属性的可达性有三个硬伤：
 *
 *   1. **键盘够不到**：原生 tooltip 只在指针悬停时出现。宿主元素若不可聚焦，
 *      纯键盘用户**永远**看不到它；即使可聚焦，多数浏览器也不会在 focus 时弹 tooltip。
 *   2. **触摸够不到**：移动端没有 hover 这一状态。
 *   3. **读屏器读不到**：`title` 只映射为 accessible *description*，且不少读屏器默认
 *      不朗读它 —— 它不能替代 DOM 里的真实文本。
 *
 * 对于**装饰性补充**（完整文件名、原始时间戳）用 `title` 是合理的；
 * 对于**唯一的、安全相关的解释**（为什么熔断了 / 场所为什么不可用 / 后续几条错误是什么），
 * 把内容只放进 `title` 等于**这信息不存在**。
 *
 * 本闸钉住三类：
 *   A. `DataStatus` 的熔断原因 —— 全站唯一呈现熔断的地方，必须可达且可见；
 *   B. `ProviderListView` 失败链的第 2..n 条错误 —— 必须进 DOM（由 CSS 截断）。
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

/** 元素是否可被键盘聚焦：原生可聚焦标签，或带 tabindex。 */
const NATIVELY_FOCUSABLE = new Set(['button', 'a', 'input', 'select', 'textarea', 'summary']);

test('熔断原因必须可达且可见（全站唯一呈现熔断的位置）', () => {
  // ⚠️ 必须先剥注释：本文件在注释里逐字写了 `role="alert"` / `tabindex="0"` 作为说明，
  // 不剥注释的话，真实属性被删掉后断言仍会被注释"喂饱"（批 68 踩过同一个坑）。
  const text = stripComments(readFileSync(path.join(SRC, 'components/dashboard/DataStatus.vue'), 'utf8'));

  // 熔断是硬性安全停机 → 出现即通报
  assert.match(text, /role="alert"/, '熔断胶囊缺少 role="alert"，读屏器不会在熔断发生时通报');
  // 键盘可达
  assert.match(text, /tabindex="0"/, '熔断胶囊不可聚焦，键盘用户够不到原因');
  // 读屏器拿得到完整原因
  assert.match(text, /:aria-label="breaker\.reason/, '熔断胶囊缺少含原因的 aria-label');
  // 桌面端直接显示原因，不必悬停
  assert.match(
    text,
    /v-if="breaker\.active && breaker\.reason"[\s\S]{0,200}\{\{ breaker\.reason \}\}/,
    '熔断原因没有直接渲染到页面上',
  );
});

test('失败链的全部错误必须进入 DOM，而不是只留第一条可见', () => {
  const text = readFileSync(path.join(SRC, 'views/admin/llm/ProviderListView.vue'), 'utf8');

  assert.match(text, /function failoverErrText\(ev: any\): string/, '缺少 failoverErrText 助手');
  assert.match(text, /\.join\(' \| '\)/, 'failoverErrText 未把全部错误拼接起来');
  // 模板必须渲染它，且不得再用 errors[0] 这种"只给第一条"的写法
  assert.match(text, /\{\{ failoverErrText\(ev\) \}\}/, '模板未渲染完整错误文本');
  assert.ok(
    !text.includes('(ev.errors || [])[0]'),
    '模板仍在只渲染 errors[0] —— 第 2..n 条错误又变回不可达',
  );
});

/** 表达式里可以忽略的"不是数据"的标识符（方法名 / 全局构造器 / 常量）。 */
const NON_FIELDS = new Set([
  'String', 'Number', 'Boolean', 'Object', 'Array', 'JSON', 'Math', 'Date',
  'stringify', 'join', 'map', 'filter', 'length', 'value', 'trim', 'slice',
  'replace', 'toFixed', 'concat', 'toString', 'cleanReason', 'parseAuditContext',
  'statusLabel', 'statusTone', 'venueLabel', 'stageLabel', 'fmtDateTime',
]);

/**
 * 找出模板里所有「关键原因/错误挂在 :title 上」的位点，并标注是否够得到。
 *
 * 判据不是维护一份豁免名单，而是：**:title 引用的字段，模板里必须存在渲染它的
 * `{{ ... }}` 插值；或者宿主元素本身可聚焦。** 这样装饰性 tooltip 天然放行，
 * 「唯一解释只藏在悬停里」被精确拦下。
 */
function criticalTooltips(body) {
  // 只有"无条件渲染该字段"的插值才算文本出口。
  // 三元表达式 `{{ cond ? field : other }}` 把字段限制在单一分支里 ——
  // 而 tooltip 往往正是在**另一个**分支（告警态）才需要它，故不算出口。
  const interpolations = [...body.matchAll(/\{\{([\s\S]*?)\}\}/g)]
    .map((m) => m[1])
    .filter((expr) => !expr.includes('?'))
    .join('\n');
  const out = [];

  for (const m of body.matchAll(/<(\w[\w-]*)\b([^>]*?)>/g)) {
    const tag = m[1].toLowerCase();
    const attrs = m[2];
    const title = attrs.match(/(?:^|\s):?[\w-]*title="([^"]*)"/);
    if (!title) continue;
    const expr = title[1];
    if (!/reason|error|fail/i.test(expr)) continue;

    // 去掉字符串字面量，避免把引号里的词当成字段名
    const code = expr.replace(/'[^']*'/g, "''").replace(/"[^"]*"/g, '""');
    const fields = [...new Set([...code.matchAll(/[A-Za-z_$][\w$]{2,}/g)].map((x) => x[0]))].filter(
      (f) => !NON_FIELDS.has(f),
    );
    if (!fields.length) continue;

    const rendered = fields.some((f) => new RegExp(`\\b${f}\\b`).test(interpolations));
    const focusable =
      NATIVELY_FOCUSABLE.has(tag) || /\btabindex=/.test(attrs) || /role="(button|link|alert|status)"/.test(attrs);
    out.push({ tag, expr, unreachable: !rendered && !focusable });
  }
  return out;
}

test('关键原因不得只挂在 :title 上：同字段必须在模板里有文本出口', () => {
  let examined = 0;
  const bad = [];

  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const body = stripComments(readFileSync(file, 'utf8'));
    for (const hit of criticalTooltips(body)) {
      examined += 1;
      if (hit.unreachable) bad.push(`${rel} <${hit.tag}> :: ${hit.expr.slice(0, 60)}`);
    }
  }

  assert.ok(examined >= 6, `检查到的关键 tooltip 过少（${examined}），疑似判据失效`);
  assert.deepEqual(
    bad,
    [],
    '以下位置把「原因 / 错误」只挂在 title 上，模板里没有任何文本出口 —— ' +
      `键盘与触摸用户拿不到：\n  ${bad.join('\n  ')}`,
  );
});

test('闸自检：能准确拦截无文本出口的关键 tooltip', () => {
  const cases = [
    ['<span :title="breaker.reason">熔断</span>', 1, '应拦截没有文本出口的熔断原因'],
    ['<span tabindex="0" role="alert" :title="breaker.reason">熔断</span>', 0, '应放行已补可达性的熔断胶囊'],
    ["<td :title=\"String(r.reason || '')\">{{ r.reason || '--' }}</td>", 0, '应放行「单元格文本 === tooltip」的截断型单元格'],
    ['<span :title="fileName">a.txt</span>', 0, '装饰性 tooltip 不该被拦'],
    ["<span :title=\"sourceReason\">{{ t('status.attention') }}</span>", 1, '应拦截「警告态只显示需注意、原因只在悬停」的写法'],
    ["<span :title=\"sourceReason\">{{ sourceReason }}</span>", 0, '应放行已另有文本出口的写法'],
    ['<span :title="String(councilStatus.reason || \'\')">降级</span><p>{{ councilStatus.reason }}</p>', 0, '应放行同文件内另有出口的写法'],
  ];

  for (const [html, expected, why] of cases) {
    const unreachable = criticalTooltips(html).filter((h) => h.unreachable);
    assert.equal(unreachable.length, expected, why);
  }
});
