/**
 * 语言切换下的硬编码中文守卫闸（批 75）。
 *
 * ## 背景：`en-US` 是一个**用户可达**的界面语言
 *
 * `SettingsPopover` 与 `LoginPage` 都有语言开关，`useI18n.t()` 会按当前语言查表。
 * 但有一批**用户可见**的文案被写死成中文，切到英文后原样显示中文。
 *
 * ## 批 75 实测并修复（21 处 / 4 文件）
 *
 * | 位置 | 后果 |
 * |---|---|
 * | `LedgerDrawer` 模板 | `{{ t('dash.ledger.lifecycle.grossPnl') }} & 财务指标` → 英文下渲染成「Gross PnL & 财务指标」 |
 * | `LedgerDrawer` 模板 | `{{ t('common.total') }} 费用合计` → 英文下「Total 费用合计」，**且中文下是「合计 费用合计」的重复标签** |
 * | `useLlmConfig` 11 处 | 保存/清空/删除的 toast 与确认框、供应商类型与分组标签 |
 * | `useLlmConfig` 3 处 | **模板字符串**形式的 toast（单引号扫描会漏，本次实测才抓到） |
 * | `llmLogic` 2 处 | 「从远端一键自动收录」「其名下 N 个模型将一并删除」 |
 *
 * ## 判定边界（写清楚，避免把合理的中文误伤）
 *
 * **允许**中文出现在：
 *   - 数据**匹配**：`d === '多'`、`/会话|登录/`、后端配置键 `conf['交易场所与路由']`
 *     —— 这些是解析后端中文值，不是界面文案；
 *   - 语言开关里该语言**自己的名字**（`中文` / `English`）；
 *   - `DocsView.vue`：整页是**中文长文文档**，其正文不在本次范围内（需单独决策）。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const CJK = /[\u4e00-\u9fff]/;

/** 整页中文长文文档：正文中文化是一个**独立的产品决策**，不属本闸范围。 */
const DOCS_PAGE = 'views/docs/DocsView.vue';

function sourceFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) sourceFiles(p, out);
    else if (/\.(vue|ts)$/.test(n)) out.push(p);
  }
  return out;
}

/** 去掉注释：注释里的中文是说明，不是界面文案。 */
export function stripComments(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    .replace(/([^:'"\\])\/\/[^\n]*/g, '$1');
}

/**
 * 模板里会**渲染出来**的静态中文文本。
 *
 * 做法：先删掉所有标签与所有 `{{ }}` 插值，剩下的就是浏览器真正渲染的静态文本。
 *
 * ⚠️ 不能写成「取 `>` 与 `<` 之间的内容」——那样会漏掉**紧跟插值之后**的那类中文，
 * 而批 75 最典型的缺陷正是这个形状：
 *   `{{ t('dash.ledger.lifecycle.grossPnl') }} & 财务指标`
 * 这里的 `& 财务指标` 前面是 `}}` 而不是 `>`，初版判据因此完全漏判（自检当场暴露）。
 */
export function templateChineseTextNodes(templateBody) {
  const staticText = templateBody
    .replace(/<[^>]*>/g, '\n')        // 标签
    .replace(/\{\{[\s\S]*?\}\}/g, '\n'); // 插值
  const out = [];
  for (const seg of staticText.split('\n')) {
    const s = seg.trim();
    if (s && CJK.test(s)) out.push(s);
  }
  return out;
}

/**
 * `toast.*()` / `ask({...})` 实参里的中文（含**反引号模板串**）。
 *
 * 用括号配平扫描实参，而不是正则截到行尾 —— 后者会漏掉跨行的多行调用，
 * 也会把 `toast.ok('x)')` 这种带右括号的文案截错。
 */
export function messageCallChinese(code) {
  const out = [];

  const collect = (pattern, openChar, closeChar) => {
    const re = new RegExp(pattern, 'g');
    for (const m of code.matchAll(re)) {
      let depth = 0;
      let i = m.index + m[0].length - 1; // 指向开括号/开花括号
      const from = i;
      for (; i < code.length; i += 1) {
        const ch = code[i];
        if (ch === openChar) depth += 1;
        else if (ch === closeChar) {
          depth -= 1;
          if (depth === 0) break;
        }
      }
      const args = code.slice(from, i + 1);
      if (CJK.test(args)) out.push(args.replace(/\s+/g, ' ').trim().slice(0, 90));
    }
  };

  collect('toast\\.(?:ok|err|warn|info)\\(', '(', ')');
  collect('ask\\(', '(', ')');
  return [...new Set(out)];
}

test('模板文本节点里不得出现硬编码中文（DocsView 长文正文除外）', () => {
  const bad = [];

  for (const file of sourceFiles(SRC)) {
    const rel = path.relative(SRC, file).replace(/\\/g, '/');
    if (rel === DOCS_PAGE) continue; // 整页中文文档，单独决策
    const raw = readFileSync(file, 'utf8');
    // ⚠️ 先剥 script/style 再取模板块：本仓有文件的**脚本注释里写着裸的 template 开标签**，
    //    贪婪正则会从那里起匹配，把注释文字当成模板文本（批 113 实测踩到）。
    const sfcOnly = raw.replace(/<script[\s\S]*?<\/script>/g, '').replace(/<style[\s\S]*?<\/style>/g, '');
    const tm = sfcOnly.match(/<template>([\s\S]*)<\/template>/);
    if (!tm) continue;
    for (const seg of templateChineseTextNodes(stripComments(tm[1]))) {
      bad.push(`${rel} :: ${JSON.stringify(seg)}`);
    }
  }

  assert.deepEqual(
    bad,
    [],
    `以下模板文本在英文界面下会原样显示中文：\n  ${bad.join('\n  ')}`,
  );
});

test('toast / 确认框的文案不得硬编码中文', () => {
  const bad = [];
  let examined = 0;

  for (const file of sourceFiles(SRC)) {
    const rel = path.relative(SRC, file).replace(/\\/g, '/');
    const code = stripComments(readFileSync(file, 'utf8'));
    if (!/toast\.|ask\(/.test(code)) continue;
    examined += 1;
    for (const hit of messageCallChinese(code)) {
      bad.push(`${rel} :: ${hit}`);
    }
  }

  assert.ok(examined >= 5, `扫描到的消息调用过少（${examined}），疑似判据失效`);
  assert.deepEqual(
    bad,
    [],
    `以下用户可见消息硬编码中文，切到英文后不会翻译：\n  ${bad.join('\n  ')}`,
  );
});

test('批 75 修复的文案必须继续走 i18n（回归锚点）', () => {
  const cfg = readFileSync(path.join(SRC, 'composables/useLlmConfig.ts'), 'utf8');
  // ⚠️ 按**出现次数**断言，而不是 `includes`。`providerGroupOther` 在文件里有两处
  // （新建表单的默认值 + 编辑时的回落），只把其中一处改回硬编码中文时，
  // `includes` 仍会被另一处满足 —— 变异测试 M5 当场暴露了这个漏洞。
  const EXPECTED = {
    providerGroupOther: 2,
    providerGroupCustom: 1,
    providerTypeCompat: 1,
    toastProviderSaved: 1,
    toastProviderCleared: 1,
    toastProviderDeleted: 1,
    toastModelActivated: 1,
    toastModelAdded: 1,
    toastModelsImported: 1,
    confirmClearProviderTitle: 1,
    confirmClearProviderDesc: 1,
    confirmDeleteProviderTitle: 1,
    confirmDeleteProviderDesc: 1,
    confirmDeleteModelTitle: 1,
    confirmDeleteModelDesc: 1,
  };
  for (const [key, n] of Object.entries(EXPECTED)) {
    const actual = cfg.split(`admin.llm.${key}`).length - 1;
    assert.equal(actual, n, `useLlmConfig 里 admin.llm.${key} 应出现 ${n} 次，实测 ${actual} 次`);
  }
  // 这些键原本的位置是硬编码中文 —— 顺带钉死"不得回潮"
  assert.ok(!/group:\s*'其他'/.test(cfg), "providerForm 的分组回落又变回 '其他'");
  assert.ok(!/type:\s*'OpenAI 兼容'/.test(cfg), "providerForm 的类型又变回 'OpenAI 兼容'");
  assert.ok(!/toast\.\w+\(\s*['"`]/.test(cfg.replace(/toast\.\w+\(\s*t\(/g, '')), '仍有直接传字符串字面量的 toast');

  // llmLogic 保持「不依赖 vue / i18n，文案由调用方注入」的既有约定
  const logic = readFileSync(path.join(SRC, 'composables/llmLogic.ts'), 'utf8');
  assert.ok(!/from ['"]\.\.?\/composables\/useI18n|from ['"]vue['"]/.test(logic), 'llmLogic 不应引入 vue / i18n 依赖');
  assert.match(logic, /t: \(key: string\) => string,/, 'buildRemoteModelPayload 未注入 t');
  assert.match(logic, /admin\.llm\.remoteAutoCollected/, 'remoteAutoCollected 未走 t');
  assert.match(logic, /admin\.llm\.cascadeModelsDeleted/, 'cascadeModelsDeleted 未走 t');

  // 语言名必须来自唯一来源（M9 暴露：此前没有任何断言钉住 LOCALE_OPTIONS）
  const i18n = readFileSync(path.join(SRC, 'composables/useI18n.ts'), 'utf8');
  assert.match(i18n, /export const LOCALE_OPTIONS/, 'useI18n 未导出 LOCALE_OPTIONS');
  assert.match(i18n, /\bLOCALE_OPTIONS,/, 'useI18n 的返回值未暴露 LOCALE_OPTIONS');
  // ⚠️ 断言必须落在**模板的渲染处**，而不是"文件里出现过这个词" ——
  // 只写 `includes('LOCALE_OPTIONS')` 的话，`const { …, LOCALE_OPTIONS } = useI18n()`
  // 这一句导入就足以满足它（变异 M9b 当场暴露）。
  assert.match(
    readFileSync(path.join(SRC, 'views/admin/LoginPage.vue'), 'utf8'),
    /v-for="\(opt, i\) in LOCALE_OPTIONS"/,
    'LoginPage 的语言按钮未按共享常量渲染，语言名会再次硬编码',
  );
  assert.match(
    readFileSync(path.join(SRC, 'components/dashboard/SettingsPopover.vue'), 'utf8'),
    /:options="LOCALE_OPTIONS"/,
    'SettingsPopover 的语言分段未按共享常量渲染',
  );

  // LedgerDrawer 的标签必须整体走 t（不得再把中文贴在 t() 后面）
  const drawer = readFileSync(path.join(SRC, 'components/dashboard/LedgerDrawer.vue'), 'utf8');
  assert.match(drawer, /\{\{ t\('dash\.ledger\.lifecycle\.metricsTitle'\) \}\}/, '指标矩阵标题未整体走 t');
  assert.match(drawer, /\{\{ t\('dash\.ledger\.lifecycle\.totalFees'\) \}\}/, '费用合计未整体走 t');
});

test('en 词条的值里不得残留中文（漏译 / 直接拷贝 zh 的值）', () => {
  // ⚠️ 批 77 的变异 M6 暴露的缺口：把 en 的 copySummary 改成中文，
  // 而 `copySummary:` 存在、占位符也在 —— 只断言"键存在 + 占位符齐"是拦不住的。
  // 这条规则覆盖**全部** en 词条（约 700 个键），是漏译的兜底网。
  const bad = [];
  let scanned = 0;

  for (const file of (function walk(dir, out = []) {
    for (const n of readdirSync(dir)) {
      const p = path.join(dir, n);
      if (statSync(p).isDirectory()) walk(p, out);
      else if (n.endsWith('.ts')) out.push(p);
    }
    return out;
  })(path.join(SRC, 'locales/en'))) {
    const rel = path.relative(SRC, file);
    rel.split('/').length; // 仅用于可读性
    const lines = readFileSync(file, 'utf8').split('\n');
    lines.forEach((line, i) => {
      const s = line.trim();
      if (s.startsWith('//') || s.startsWith('*') || s.startsWith('/*')) return;
      // 只查**值**位置：`key: '值'`
      for (const m of line.matchAll(/^\s*[\w$]+:\s*(['"`])([\s\S]*?)\1\s*,?\s*$/g)) {
        scanned += 1;
        if (CJK.test(m[2])) bad.push(`${rel}:${i + 1}  ${m[2]}`);
      }
    });
  }

  assert.ok(scanned >= 400, `扫描到的 en 词条过少（${scanned}），疑似判据失效`);
  assert.deepEqual(bad, [], `以下 en 词条未翻译（仍是中文）：\n  ${bad.join('\n  ')}`);
});

test('中英词条结构必须对称（新增键两侧都要有）', () => {
  const zh = readFileSync(path.join(SRC, 'locales/zh/admin/llm.ts'), 'utf8');
  const en = readFileSync(path.join(SRC, 'locales/en/admin/llm.ts'), 'utf8');
  const keysOf = (s) => [...s.matchAll(/^\s{2}(\w+):/gm)].map((m) => m[1]).sort();
  assert.deepEqual(keysOf(zh), keysOf(en), 'admin.llm 中英词条键位不对称');

  for (const key of ['metricsTitle', 'totalFees']) {
    for (const loc of ['zh', 'en']) {
      assert.ok(
        readFileSync(path.join(SRC, `locales/${loc}/dash/ledger.ts`), 'utf8').includes(`${key}:`),
        `${loc}/dash/ledger.ts 缺少 ${key}`,
      );
    }
  }
});

test('闸自检：能准确拦截硬编码中文，且不误伤合理中文', () => {
  // 文本节点
  assert.deepEqual(templateChineseTextNodes('<p>合计 费用合计</p>'), ['合计 费用合计'], '应拦截中文文本节点');
  assert.deepEqual(templateChineseTextNodes('<p>{{ t(\'a.b\') }}</p>'), [], '纯插值不该被拦');
  assert.deepEqual(templateChineseTextNodes('<p>{{ t(\'a.b\') }} & 财务指标</p>'), ['& 财务指标'], '应拦截贴在 t() 后的中文');

  // 消息调用（含反引号模板串 —— 单引号扫描会漏掉这一类）
  assert.deepEqual(messageCallChinese("toast.ok('保存成功')"), ["('保存成功')"], '应拦截单引号中文 toast');
  assert.deepEqual(
    messageCallChinese('toast.ok(`供应商 ${p.name} 已删除`)'),
    ['(`供应商 ${p.name} 已删除`)'],
    '应拦截反引号模板串 toast —— 单引号扫描会漏掉这一类',
  );
  assert.deepEqual(messageCallChinese("toast.ok(t('admin.llm.saved'))"), [], '走 t() 的消息不该被拦');
  assert.deepEqual(
    messageCallChinese("ask({ title: '删除模型', danger: true })"),
    ["({ title: '删除模型', danger: true })"],
    '应拦截确认框中文',
  );
  assert.deepEqual(
    messageCallChinese("toast.ok(`收录 ${n} 个`)\nawait load()"),
    ['(`收录 ${n} 个`)'],
    '多行调用后紧跟语句时不得截错',
  );

  // 注释里的中文是说明，不该被拦
  assert.equal(CJK.test(stripComments('// 这是说明\nconst a = 1')), false, '注释中文不该被拦');
  assert.equal(CJK.test(stripComments('/* 说明 */ const a = 1')), false, '块注释中文不该被拦');
});
