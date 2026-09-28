/**
 * 非组件模块的用户可见文案不得硬编码中文（批 76）。
 *
 * ## 续批 75
 *
 * 批 75 钉住了「模板文本」与「toast / 确认框实参」。本批补上**另外两条通路**：
 *
 *   1. **HTTP / store 层的错误与回落文案** —— 这些字符串会被各页
 *      `catch (e) { toast.err(e.message) }` 直接展示，或写进 `error.value` 渲染成错误块。
 *      切到英文后它们仍是中文，且是**用户最需要看懂**的那类文字。
 *      批 76 实测修复 7 处：`api/http.ts`（网络失败 / 会话过期 / 422 拼接符与回落）、
 *      `stores/dashboard.ts`（扫描中 / 取数失败）、`stores/auth.ts`（登录失败 / 网络错误）。
 *   2. **纯工具模块里的枚举文案** —— `utils/` 下的纯逻辑模块（批 76 原文举的是
 *      已随「全站收口 OKX」删除的 `utils/venueMeta.stageLabel` 阶段名表）。
 *
 * ## 判定边界（哪些中文是**合理**的，不得误伤）
 *
 *   - **数据匹配**：`/\(401\)|401|会话|登录/`、`s.includes('空')`、`d === '多'` ——
 *     这些是在**解析后端返回的中文值**，改成英文反而会匹配失败；
 *   - 注释里的中文是说明，不是界面文案；
 *   - 后端**配置键**（`conf['交易场所与路由']`）是协议的一部分。
 *
 * 故本闸只扫**字符串字面量**，且跳过注释与正则字面量。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const CJK = /[\u4e00-\u9fff]/;

/** 去掉注释块、行注释与正则字面量，只留"会被求值的代码"。 */
export function codeOnly(src) {
  return src
    .replace(/\/\*[\s\S]*?\*\//g, '')
    .replace(/<!--[\s\S]*?-->/g, '')
    .replace(/^\s*\/\/.*$/gm, '')
    // 正则字面量：前置字符决定 `/` 是正则还是除号
    .replace(/(^|[(,=:[!&|?{};]\s*)\/(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\\\n])+\/[gimsuy]*/g, '$1REGEX');
}

/**
 * 抽出「用户可见文案」位置的字符串字面量内容：
 *   - `throw new X('...')` / `throw new X(...)` 的实参
 *   - `error.value = '...'` / `error.value || '...'`
 *   - `title:` / `desc:` / `detail:` / `okText:` / `message:` 的值
 */
export function userFacingLiterals(code) {
  const out = [];
  const LIT = `(?:'(?:[^'\\\\]|\\\\.)*'|"(?:[^"\\\\]|\\\\.)*"|\`(?:[^\`\\\\]|\\\\.)*\`)`;

  // ① 兜底字面量：`… || '中文'` / `… ?? '中文'` / `x = '中文'` / `return '中文'`
  //
  //    ⚠️ 必须要求字面量**紧跟**运算符出现。放宽成"运算符后面的整个表达式里含中文"
  //    会误伤 `return s.includes('空') ? 'short' : 'long'` 这类**数据匹配**
  //    （`'空'` 是函数实参，不是界面文案）。
  //    `=` 需排除 `===` / `!==` / `<=` / `>=`，否则 `d === '多'` 会被误判。
  const fallback = new RegExp(`(?:\\|\\||\\?\\?|(?<![=!<>])=(?!=)|\\breturn\\s)\\s*(${LIT})`, 'g');
  for (const m of code.matchAll(fallback)) {
    if (CJK.test(m[1])) out.push({ text: m[1], why: 'fallback' });
  }

  // ② 抛错实参（可能是拼接/模板串，故整段取）
  for (const m of code.matchAll(/throw new [\w.]*Error\(([^)]*)\)/g)) {
    const lit = m[1].match(/'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`/);
    if (lit && CJK.test(lit[0])) out.push({ text: lit[0], why: 'throw' });
  }

  // ③ 弹窗 / 提示对象里的文案字段
  for (const m of code.matchAll(/\b(?:title|desc|detail|okText|message)\s*:\s*([^,\n}]*)/g)) {
    const lit = m[1].match(/'(?:[^'\\]|\\.)*'|"(?:[^"\\]|\\.)*"|`(?:[^`\\]|\\.)*`/);
    if (lit && CJK.test(lit[0])) out.push({ text: lit[0], why: 'label' });
  }

  return out;
}

function sourceFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) sourceFiles(p, out);
    else if (/\.(vue|ts)$/.test(n)) out.push(p);
  }
  return out;
}

test('api / stores 层不得把用户可见文案硬编码成中文', () => {
  const bad = [];
  let examined = 0;

  for (const scope of ['api', 'stores']) {
    for (const file of sourceFiles(path.join(SRC, scope))) {
      const rel = path.relative(SRC, file);
      const code = codeOnly(readFileSync(file, 'utf8'));
      examined += 1;
      for (const hit of userFacingLiterals(code)) {
        bad.push(`${rel} [${hit.why}] :: ${hit.text}`);
      }
    }
  }

  // 2026-10：`stores/listingStatus` 与 `stores/venueAccounts` 随全站收口 OKX 删除，
  // api + stores 现存 3 个 .ts 模块；下限随之收紧为 3。
  assert.ok(examined >= 3, `扫描到的模块过少（${examined}），疑似判据失效`);
  assert.deepEqual(
    bad,
    [],
    `以下用户可见文案硬编码中文，切到英文后仍是中文：\n  ${bad.join('\n  ')}`,
  );
});

test('数据匹配用的中文（正则 / includes）必须保留，不得被"翻译掉"', () => {
  // 反向守卫：这些是解析**后端中文值**的判据，改成英文会导致匹配失败。
  // 若哪天有人"为了 i18n"把它们清了，本断言会立刻翻红。
  const dirTag = readFileSync(path.join(SRC, 'components/base/DirTag.vue'), 'utf8');
  assert.match(dirTag, /d === '多'/, "DirTag 的方向匹配被改掉了（后端用中文方向）");
  const levels = readFileSync(path.join(SRC, 'components/dashboard/chartLiveLevels.ts'), 'utf8');
  assert.match(levels, /includes\('空'\)/, 'chartLiveLevels 的空头方向匹配被改掉了（后端用中文方向）');
});

test('纯工具模块不得内置中文文案表，也不得 import i18n', () => {
  // 批 76 的原始判据挂在 `utils/venueMeta.stageLabel` 上；该模块已随
  // 「全站收口 OKX」删除，判据改为对**全部存活的 utils 纯逻辑模块**生效 ——
  // 覆盖面更宽，且不会因为删掉一个模块就整条失效。
  const files = readdirSync(path.join(SRC, 'utils')).filter((n) => n.endsWith('.ts'));
  assert.ok(files.length >= 4, `utils 下只扫到 ${files.length} 个模块，疑似判据失效`);
  const bad = [];
  for (const f of files) {
    const src = readFileSync(path.join(SRC, 'utils', f), 'utf8');
    const code = codeOnly(src);
    for (const hit of userFacingLiterals(code)) bad.push(`utils/${f} [${hit.why}] :: ${hit.text}`);
    // 工具模块不得 import i18n（沿用 llmLogic 的既有约定：文案由调用方注入）
    assert.ok(!/from ['"]\.\.?\/composables\/useI18n/.test(code), `utils/${f} 不应 import i18n`);
  }
  assert.deepEqual(bad, [], `工具模块里出现硬编码中文文案（英文界面会漏中文）：\n  ${bad.join('\n  ')}`);
});

test('confTier 不得再返回死的中文 label 字段', () => {
  const fmt = readFileSync(path.join(SRC, 'utils/format.ts'), 'utf8');
  assert.match(
    fmt,
    /export function confTier\(v: number \| null \| undefined\): \{ tier: 'high' \| 'mid' \| 'low' \} \| null/,
    'confTier 仍在返回 label（该字段全站无人使用，却是一颗会在英文界面渲染出中文的隐雷）',
  );
  const fn = fmt.slice(fmt.indexOf('export function confTier'));
  assert.ok(!CJK.test(codeOnly(fn.slice(0, fn.indexOf('\n}')))), 'confTier 里仍有中文');
  // 消费方 ConfBadge 必须自己走 t()
  const badge = readFileSync(path.join(SRC, 'components/base/ConfBadge.vue'), 'utf8');
  assert.match(badge, /t\(`common\.conf\.\$\{tier\.tier\}`\)/, 'ConfBadge 未按 tier 走 t()');
});

test('useI18n 必须可在组件外调用（store / api 层依赖这一点）', () => {
  const t = readFileSync(path.join(SRC, 'composables/useI18n.ts'), 'utf8');
  assert.ok(!/\binject\(/.test(t), 'useI18n 用了 inject —— 组件外调用会失败');
  assert.ok(!/getCurrentInstance/.test(t), 'useI18n 依赖组件实例 —— store / api 层无法使用');
  // locale 导入必须是显式 /index：目录导入只有 Vite 认，node 测试的 loader 会解析失败
  assert.match(t, /from '\.\.\/locales\/zh\/index'/, 'useI18n 的 zh 词条导入应为显式 /index');
  assert.match(t, /from '\.\.\/locales\/en\/index'/, 'useI18n 的 en 词条导入应为显式 /index');
});

test('闸自检：识别用户可见中文，且不误伤数据匹配与正则', () => {
  assert.deepEqual(
    userFacingLiterals(codeOnly("throw new HttpError('网络错误', 0)")).map((h) => h.why),
    ['throw'],
    '应拦截 throw 里的中文',
  );
  assert.deepEqual(
    userFacingLiterals(codeOnly("error.value = err.message || '获取数据失败'")).map((h) => h.text),
    ["'获取数据失败'"],
    '应拦截 error.value 回落文案',
  );
  assert.deepEqual(
    userFacingLiterals(codeOnly("await ask({ title: '删除模型', danger: true })")).map((h) => h.why),
    ['label'],
    '应拦截 title 中文',
  );
  assert.deepEqual(
    userFacingLiterals(codeOnly("error.value = '请求失败'")).map((h) => h.text),
    ["'请求失败'"],
    '直接的 error.value 中文字面量应被拦截',
  );
  assert.deepEqual(
    userFacingLiterals(codeOnly("error.value = t('common.requestFailed')")),
    [],
    '已走 t() 的赋值不该被拦',
  );

  // 关键：正则里的中文必须被剥掉，不能被判为文案
  const regexCase = "error.value = /\\(401\\)|401|会话|登录/.test(msg)";
  assert.deepEqual(userFacingLiterals(codeOnly(regexCase)), [], '正则字面量里的中文不该被拦');
  // 块注释与行注释里的中文也不该被拦
  assert.deepEqual(userFacingLiterals(codeOnly("// 说明：获取数据失败\nerror.value = t('common.x')")), [], '注释中文不该被拦');
});
