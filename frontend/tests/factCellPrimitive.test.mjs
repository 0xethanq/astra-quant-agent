/**
 * 统计单元（fact cell）收口为单一原件（批 79）。
 *
 * ## 实测：13 个页面各自重写了一份完全同构的统计单元
 *
 * `.X-fact` / `.X-fact-label` / `.X-fact-value` / `.X-fact-foot` / `.X-fact-sub`
 * 外加 `:first-child` 与两个断点的头发丝网格 —— 结构逐字节相同，
 * 合计 **161 条规则 / 约 560 行**，散落在 13 个 `<style scoped>` 里。
 * 编译产物 CSS 实测从 **224,517 → 210,269 字节（−14,248 / −6.3%）**。
 *
 * 更糟的是**字阶已经漂移**：
 *   - `.X-fact-value` 8 个页面 `--text-md`(14px) / 6 个页面 `--text-lg`(15px)；
 *   - `.X-fact-foot` 7 个页面 `--text-4xs`(11px) / 7 个页面 `--text-3xs`(11.5px)（平局）；
 *   - `font-variant-numeric: tabular-nums` 只有 6/14 开着 —— 而全站其它数字位
 *     （`.stat dd` / `.table .col-num` / `.kv dd`）本来就开着，统计单元漏了会让
 *     数字随取值横向抖动。
 *
 * 已按确认统一到**更紧凑的一档**：数值 `--text-md` + 脚注 `--text-4xs`
 * （脚注比标签 `--text-3xs` 小一档，层次正确），`tabular-nums` 补全。
 *
 * ## 为什么 `.rk-fact` 不并入
 *
 * `RiskPage` 的 `.rk-fact` / `.rk-fact-v` 是**另一种组件**：常驻左框、
 * 单行省略（`white-space: nowrap` + `text-overflow: ellipsis`）、没有
 * `:first-child` 也没有断点网格。强行合并会改变它的视觉，故显式豁免。
 *
 * 运行：`node --test tests/*.test.mjs`（**先 `npm run build`**：
 * `tests/deadUtilities.test.mjs` 需要新鲜的 dist 才不跳过）
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const COMPONENTS_CSS = path.join(SRC, 'styles', 'components.css');

/** 原件提供的 5 个类（模板只允许用这些）。 */
const PRIMITIVE = ['fact', 'fact-label', 'fact-value', 'fact-foot', 'fact-sub'];

/** 允许自带 fact 规则的页面（值=理由）。 */
export const FACT_EXEMPT = {
  'views/admin/RiskPage.vue': '.rk-fact / .rk-fact-v 是另一种组件（常驻左框 + 单行省略，无断点网格）',
};

/** `.fact` 必须有的结构属性。 */
const FACT_STRUCT = [
  'display: flex;', 'flex-direction: column;', 'gap: 4px;', 'min-width: 0;',
  'padding: var(--ds-space-4);', 'border-top: 1px solid var(--ds-color-border-default);',
];

function allFiles(dir, ext, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) allFiles(p, ext, out);
    else if (ext.test(n)) out.push(p);
  }
  return out;
}

const cssOf = (text) => (text.match(/<style[^>]*>([\s\S]*?)<\/style>/) || [null, ''])[1];
const tplOf = (text) => (text.includes('<style') ? text.slice(0, text.indexOf('<style')) : text);

test('.fact 原件必须存在且结构完整', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  const m = css.match(/\.fact\s*\{([^}]*)\}/);
  assert.ok(m, 'components.css 里找不到 .fact 原件');
  for (const p of FACT_STRUCT) assert.ok(m[1].includes(p), `.fact 缺少属性 ${p}`);
  // 断点网格（头发丝分隔线）必须齐
  assert.match(css, /\.fact:first-child\s*\{\s*border-top:\s*0;/, '缺 .fact:first-child');
  assert.match(css, /@media \(min-width: 640px\)[\s\S]{0,200}\.fact:nth-child\(2\)/, '缺 640px 断点');
  assert.match(css, /@media \(min-width: 640px\)[\s\S]{0,300}\.fact:nth-child\(even\)/, '缺 640px 偶数列分隔线');
  assert.match(css, /@media \(min-width: 1280px\)[\s\S]{0,300}\.fact \+ \.fact/, '缺 1280px 相邻分隔线');
});

test('字阶口径：数值 --text-md + 脚注 --text-4xs + tabular-nums（已确认的统一值）', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  const val = css.match(/\.fact-value\s*\{([^}]*)\}/)[1];
  const foot = css.match(/\.fact-foot\s*\{([^}]*)\}/)[1];

  assert.match(val, /font-size:\s*var\(--text-md\);/, '.fact-value 应为 --text-md');
  assert.ok(!/--text-lg/.test(val), '.fact-value 又回到 --text-lg（15px）');
  assert.match(foot, /font-size:\s*var\(--text-4xs\);/, '.fact-foot 应为 --text-4xs');
  assert.ok(!/--text-3xs/.test(foot), '.fact-foot 又回到 --text-3xs（11.5px）');
  // 数字位必须开等宽数位，否则数值变化时整行横向抖动
  assert.match(val, /font-variant-numeric:\s*tabular-nums;/, '.fact-value 缺少 tabular-nums');
  // 批 91：脚注行同样承载数字，口径必须与数值行一致。
  // 实测（25 条路由）：`.fact-value` 含数字 41 处全部声明，
  // 而 `.fact-foot` 含数字 18 处里 7 处没声明 —— 同一统计单元两行口径不一致。
  // ⚠️ 本环境该属性**不可见**（实际字体数位本就等宽，tabular-nums 对
  // Georgia/Times 也无效），此判据守的是「口径一致 + 换字体兜底」，不是抖动。
  assert.match(
    foot,
    /font-variant-numeric:\s*tabular-nums;/,
    '.fact-foot 缺少 tabular-nums（脚注里的「1 启用」「20 / 200」「65%」等会横向抖动）',
  );

  // 脚注要比标签小一档，层次才成立
  const label = css.match(/\.fact-label\s*\{([^}]*)\}/)[1];
  assert.match(label, /font-size:\s*var\(--text-3xs\);/, '.fact-label 应为 --text-3xs');
});

test('页面不得再自带 fact 规则（原件已覆盖；例外须登记）', () => {
  const bad = [];
  for (const file of allFiles(SRC, /\.vue$/)) {
    const rel = path.relative(SRC, file);
    if (FACT_EXEMPT[rel]) continue;
    const css = cssOf(readFileSync(file, 'utf8'));
    for (const m of css.matchAll(/^[ \t]*([^{}\n]*\bfact[\w-]*[^{}\n]*)\{/gm)) {
      bad.push(`${rel} :: ${m[1].trim()}`);
    }
  }
  assert.deepEqual(
    bad,
    [],
    `以下页面仍自带 fact 规则（应改用全站 .fact 原件）：\n  ${bad.join('\n  ')}`,
  );
});

test('模板只允许使用原件提供的 5 个 fact 类名', () => {
  const bad = [];
  const counts = new Map();
  for (const file of allFiles(SRC, /\.vue$/)) {
    const rel = path.relative(SRC, file);
    if (FACT_EXEMPT[rel]) continue; // 豁免页用的是自己的组件，不属本原件
    const tpl = tplOf(readFileSync(file, 'utf8'));
    for (const m of tpl.matchAll(/class="([^"]*)"/g)) {
      for (const cls of m[1].split(/\s+/)) {
        if (!/(^|-)fact($|-)/.test(cls)) continue;
        counts.set(cls, (counts.get(cls) || 0) + 1);
        if (!PRIMITIVE.includes(cls)) bad.push(`${rel} :: ${cls}`);
      }
    }
  }
  assert.deepEqual(bad, [], `模板用了原件没有的 fact 类（会静默无样式）：\n  ${bad.join('\n  ')}`);
  // 现状基线：44 个单元 / 34 组 label+value+foot（防"改着改着少了一片"）。
  // 2026-09-30 后台精简：内置插件清单页（PluginsPage）删除，其 5 个统计单元随之移除
  //（49 → 44；label/value/foot 38 → 34）。
  assert.equal(counts.get('fact'), 44, `统计单元实例应为 44 个，实测 ${counts.get('fact')}`);
  for (const k of ['fact-label', 'fact-value', 'fact-foot']) {
    assert.equal(counts.get(k), 34, `${k} 应为 34 个，实测 ${counts.get(k)}`);
  }
});

test('豁免名单必须有理由，且仍在用 fact', () => {
  for (const [rel, why] of Object.entries(FACT_EXEMPT)) {
    const text = readFileSync(path.join(SRC, rel), 'utf8');
    assert.ok(why && why.length > 8, `豁免 ${rel} 缺少理由`);
    assert.ok(/\bfact/.test(text), `豁免的 ${rel} 已不再使用 fact，请删除该豁免`);
  }
  assert.ok(Object.keys(FACT_EXEMPT).length <= 2, '豁免名单过长，应先考虑并入原件');
});

test('闸自检：识别页面自带的 fact 规则与未知类名', () => {
  const css = '.ag-fact {\n  display: flex;\n}\n.ag-band {\n  display: grid;\n}\n';
  const found = [...css.matchAll(/^[ \t]*([^{}\n]*\bfact[\w-]*[^{}\n]*)\{/gm)].map((m) => m[1].trim());
  assert.deepEqual(found, ['.ag-fact'], '应只识别出 fact 规则，不该误伤 .ag-band');

  const tpl = '<div class="fact"><span class="fact-label"/><span class="fact-labl"/></div>';
  const toks = [...tpl.matchAll(/class="([^"]*)"/g)]
    .flatMap((m) => m[1].split(/\s+/))
    .filter((c) => /(^|-)fact($|-)/.test(c));
  assert.deepEqual(toks, ['fact', 'fact-label', 'fact-labl']);
  assert.ok(!PRIMITIVE.includes('fact-labl'), '拼错的类名应被判为非法');

  // 不误伤：`rk-fact` 属于豁免文件；`factual` 不是 fact 类
  assert.equal(/(^|-)fact($|-)/.test('factual'), false, "'factual' 不该被当作 fact 类");
  assert.equal(/(^|-)fact($|-)/.test('rk-fact'), true, "'rk-fact' 应被识别（由豁免名单放行）");
  assert.equal(/(^|-)fact($|-)/.test('fact-value'), true);
});
