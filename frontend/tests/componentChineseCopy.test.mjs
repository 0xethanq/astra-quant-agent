/**
 * 组件层的用户可见文案不得硬编码中文（批 77，续批 75 / 76）。
 *
 * ## 三条通路已逐个封口
 *
 *   - 批 75：**模板静态文本** + `toast.*()` / `ask({})` 实参；
 *   - 批 76：**`api/` 与 `stores/` 的**错误与回落文案；
 *   - 批 77（本文件）：**组件脚本里的**文案字段、**剪贴板文本**、兜底字面量。
 *
 * 批 77 实测并修复：
 *
 * | 位置 | 后果 |
 * |---|---|
 * | `ChartWorkstation.copySimulationSummary` | 剪贴板文案硬编码 `【ASTRA 风控测算】入场: SL: TP:` —— 英文界面复制出中英混排 |
 * | `CouncilPage` 席位号位 ×3 | 回落值硬编码**英文** `'Senior Trader'` —— **中文**界面下显示英文 |
 * | `CouncilPage.addNewCustomTrader` | 新席位 `name` / `role_title` / `description` 硬编码 |
 * | `chartIndicators.ts` | 11 条中文 `desc` **全站无人渲染** —— 死数据，与 `confTier.label` 同类隐雷，已删 |
 *
 * ## 明确边界（已逐个核实为"合理"，故豁免；文件被改名时本闸会报错）
 *
 * 这些不是漏改，而是**有意不国际化**或**不是界面文案**：
 *
 *   - `views/docs/DocsView.vue` —— 整页中文长文文档，正文中文化是独立产品决策；
 *   - `config/version.ts` —— 品牌名与官方仓库公告；
 *   - `router/index.ts` —— SEO 文档标题，注释明写"中文为主（与后端钉扎测试与 CF 缓存语义一致）"；
 *   - `views/admin/council/councilLogic.ts` —— `CONSENSUS_MODES` 的中文是**回落值**，
 *     `CouncilPage` 有 `MODE_TEXT_KEY` 覆盖层（批 40），且内置席位的 prompt 本身是中文，
 *     自定义席位沿用中文才与之一致；
 *   - `views/admin/InterceptorsPage.vue` —— Python 插件**脚手架代码模板**，
 *     是用户要编辑的代码起点，不是界面 chrome。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync, existsSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const CJK = /[\u4e00-\u9fff]/;
const LIT = `(?:'(?:[^'\\\\]|\\\\.)*'|"(?:[^"\\\\]|\\\\.)*"|\`(?:[^\`\\\\]|\\\\.)*\`)`;

/** 已逐个核实的豁免（值是豁免理由；文件必须仍然存在）。 */
export const BOUNDARIES = {
  'views/docs/DocsView.vue': '整页中文长文文档，正文中文化是独立产品决策',
  'config/version.ts': '品牌名与官方仓库公告',
  'router/index.ts': 'SEO 文档标题，注释明写中文为主（后端钉扎 + CF 缓存语义）',
  'views/admin/council/councilLogic.ts': 'CONSENSUS_MODES 是回落值，CouncilPage 有 MODE_TEXT_KEY 覆盖层；且内置席位 prompt 为中文',
  'views/admin/InterceptorsPage.vue': 'Python 插件脚手架代码模板（用户要编辑的代码起点）',
};

export function codeOnly(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/([^:]|^)\/\/[^\n]*/g, '$1');
}

/** 组件脚本里的文案字段 / 剪贴板文本 / 兜底字面量。 */
export function componentCopyHits(code) {
  const out = [];
  const collect = (pattern, why) => {
    for (const m of code.matchAll(pattern)) {
      for (const lit of m[1].match(new RegExp(LIT, 'g')) || []) {
        if (CJK.test(lit)) out.push({ why, text: lit.slice(0, 70) });
      }
    }
  };
  collect(/writeText\(([^)]*)\)/g, 'clipboard');
  // `name` 也在列：席位/插件等处它会直接渲染成标题。
  // 实测加入后全仓 0 处误报（其余 `name` 都是英文标识符），故保留以扩大覆盖面。
  collect(
    /\b(?:title|desc|detail|okText|message|role_title|description|name)\s*:\s*([^,\n}]*)/g,
    'label',
  );
  collect(
    new RegExp(`(?:\\\\|\\\\||\\\\?\\\\?|(?<![=!<>])=(?!=)|\\\\breturn\\\\s)\\\\s*(${LIT})`, 'g'),
    'fallback',
  );
  return out;
}

function scriptSections(rel, raw) {
  const code = codeOnly(raw);
  if (!rel.endsWith('.vue')) return code;
  const m = code.match(/<script[^>]*>([\s\S]*?)<\/script>/);
  return m ? m[1] : '';
}

test('组件脚本的文案字段 / 剪贴板 / 兜底字面量不得硬编码中文', () => {
  const bad = [];
  let examined = 0;

  for (const file of (function walk(dir, out = []) {
    for (const n of readdirSync(dir)) {
      const p = path.join(dir, n);
      if (statSync(p).isDirectory()) walk(p, out);
      else if (/\.(vue|ts)$/.test(n)) out.push(p);
    }
    return out;
  })(SRC)) {
    const rel = path.relative(SRC, file);
    if (rel.startsWith('locales')) continue;
    if (BOUNDARIES[rel]) continue;
    const code = scriptSections(rel, readFileSync(file, 'utf8'));
    if (!code.trim()) continue;
    examined += 1;
    for (const hit of componentCopyHits(code)) {
      bad.push(`${rel} [${hit.why}] :: ${hit.text}`);
    }
  }

  assert.ok(examined >= 40, `扫描到的组件过少（${examined}），疑似判据失效`);
  assert.deepEqual(
    bad,
    [],
    `以下用户可见文案硬编码中文，切到英文后仍是中文：\n  ${bad.join('\n  ')}`,
  );
});

test('豁免名单必须都是有理由的、且文件真实存在（防止静默漏网）', () => {
  for (const [rel, why] of Object.entries(BOUNDARIES)) {
    assert.ok(existsSync(path.join(SRC, rel)), `豁免的 ${rel} 已不存在 —— 请复核并删除该豁免`);
    assert.ok(why && why.length > 6, `豁免 ${rel} 缺少理由`);
  }
  assert.ok(Object.keys(BOUNDARIES).length <= 6, '豁免名单过长，应优先修代码而不是加豁免');
});

test('回落文案不得硬编码为某一种语言（中英都会翻车）', () => {
  // 批 77：席位号位回落值写死英文 'Senior Trader' —— 中文界面下显示英文。
  // 这是"硬编码中文"的镜像缺陷，同样属于 i18n 漏洞。
  for (const rel of ['views/admin/CouncilPage.vue']) {
    const text = readFileSync(path.join(SRC, rel), 'utf8');
    for (const word of ['Senior Trader', 'Custom Trader']) {
      assert.ok(
        !new RegExp(`[:?]\\s*'${word}'`).test(text),
        `${rel} 仍在把 '${word}' 硬编码为回落值（应为 t() 取值）`,
      );
    }
  }
  // 反向锚点：这三处必须走 t()
  const cp = readFileSync(path.join(SRC, 'views/admin/CouncilPage.vue'), 'utf8');
  assert.equal(
    (cp.match(/t\('admin\.council\.seniorTrader'\)/g) || []).length,
    3,
    'CouncilPage 的 3 处席位号位回落必须都走 t(admin.council.seniorTrader)',
  );
  for (const key of ['customTraderName', 'customTraderRoleTitle', 'customTraderDesc']) {
    assert.ok(cp.includes(`t('admin.council.${key}')`), `新席位缺少 ${key}`);
  }
});

test('剪贴板文案必须整体走一个带参数的词条', () => {
  const cw = readFileSync(path.join(SRC, 'components/dashboard/ChartWorkstation.vue'), 'utf8');
  assert.match(cw, /t\('dash\.matrix\.chart\.sim\.copySummary'/, '剪贴板文案未走 i18n');
  for (const p of ['sym', 'entry', 'sl', 'tp', 'rr']) {
    assert.ok(new RegExp(`\\b${p}:`).test(cw), `copySummary 缺少 {${p}} 参数`);
  }
  // 词条两侧都要有，且参数占位符齐备
  for (const loc of ['zh', 'en']) {
    const f = readFileSync(path.join(SRC, `locales/${loc}/dash/matrix.ts`), 'utf8');
    assert.match(f, /copySummary:/, `${loc} 缺少 copySummary`);
    for (const p of ['{sym}', '{entry}', '{sl}', '{tp}', '{rr}']) {
      assert.ok(f.includes(p), `${loc} 的 copySummary 缺少占位符 ${p}`);
    }
  }
});

test('已删的死中文数据不得回潮', () => {
  const ci = readFileSync(path.join(SRC, 'components/dashboard/chartIndicators.ts'), 'utf8');
  assert.ok(!/\bdesc\s*:/.test(ci), 'chartIndicators 又把 desc 加回来了（全站无人渲染的死数据）');
  assert.ok(!CJK.test(codeOnly(ci)), 'chartIndicators 脚本里又出现中文');
});

test('闸自检：识别组件文案与剪贴板中文，不误伤数据匹配', () => {
  assert.deepEqual(
    componentCopyHits(codeOnly("navigator.clipboard.writeText(`【ASTRA 风控测算】`)")).map((h) => h.why),
    ['clipboard'],
    '应拦截剪贴板中文',
  );
  assert.deepEqual(
    componentCopyHits(codeOnly("name: '自定义交易员', role_title: 'Custom Trader',")).map((h) => h.text),
    ["'自定义交易员'"],
    '应拦截 name 中文（role_title 是英文，不算）',
  );
  assert.deepEqual(
    componentCopyHits(codeOnly("role_title: '自定义'")).map((h) => h.why),
    ['label'],
    '应拦截 role_title 中文',
  );
  assert.deepEqual(
    componentCopyHits(codeOnly("const x = d === '多' ? 'long' : 'short'")),
    [],
    '数据匹配（=== 后的中文）不该被拦',
  );
  assert.deepEqual(
    componentCopyHits(codeOnly("const x = t('admin.council.seniorTrader')")),
    [],
    '已走 t() 的不该被拦',
  );
  assert.deepEqual(
    componentCopyHits(codeOnly("// 说明：中文\nconst a = 1")),
    [],
    '注释中文不该被拦',
  );
});
