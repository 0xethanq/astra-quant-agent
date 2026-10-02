/**
 * 字阶契约（批 28）。
 *
 * ## 守什么
 *
 * 批 28 实测出一个**静默失效**：模板里 385 个节点写着 `text-3xs`、29 个写着
 * `text-2xs`，但 `@theme` 从未声明这三个档位 —— Tailwind 一个工具类都没生成，
 * 那些节点实际继承父级 12px。于是"同一类小字在公开页 12px、在后台 11.5px"，
 * 肉眼只看到"不统一"，查起来却毫无线索：类名写对了、CSS 里就是没有这条规则。
 *
 * 这类缺陷本文件钉四条，全部是**静态可判**的：
 *
 *   1. **地板**：`--text-*` 最小档 ≥ 11px（方案 §3.2）。
 *      9.5px 在实际屏幕上就是"看不清"，不是"密度高"。
 *
 *   2. **可达性**：每个 `--text-*` 档位都要能被 Tailwind 工具类取到 ——
 *      要么名字在 Tailwind 默认主题里（xs/sm/base/lg/xl/2xl/3xl），
 *      要么在 `styles/index.css` 的 `@theme` 块里声明过。
 *      漏声明 = 工具类被静默吞掉（就是本批修的那个 bug）。
 *
 *   3. **不许写死字号**：`font-size: 13px` / `text-[10px]` 一律不许。
 *      实测残留过 9px、10px、16px、9.36px 四种刻度外尺寸，
 *      正是"跨页不统一"的另一半来源。
 *
 *   4. **工具类回落到令牌**：`text-3xs` 生成的 CSS 必须是
 *      `font-size: var(--text-3xs)`（而非内联数字），否则 tokens.css 改不动它。
 *      这一条只能查 `@theme inline` 的写法：值写成 `var(--text-3xs)`。
 *
 *   5. **不许有亚像素档位**（批 89，用户确认）：去重后的相邻档差必须 ≥ 1px。
 *      实测曾有 11 / 11.5 / 12 / 12.5 四档挤在 1.5px 内（三对相邻档只差 0.5px），
 *      0.5px 在屏幕上不可辨 —— 等于同一视觉档位有四个名字。已把 11.5 与 12.5
 *      并入 12px，生效字阶去重后为 11/12/13/14/15/18/22/26。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const ROOT = path.resolve(import.meta.dirname, '..');
const SRC = path.join(ROOT, 'src');
const TOKENS = path.join(SRC, 'styles', 'tokens.css');
const INDEX = path.join(SRC, 'styles', 'index.css');

/** Tailwind v4 默认主题自带的字号名（不需要我们在 @theme 里声明） */
const TAILWIND_DEFAULT_TEXT = new Set(['xs', 'sm', 'base', 'lg', 'xl', '2xl', '3xl', '4xl']);

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = path.join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}

/** `--text-4xs: 11px;` → { '4xs': 11, … } */
function readScale() {
  const css = readFileSync(TOKENS, 'utf8');
  const scale = {};
  for (const m of css.matchAll(/--text-([a-z0-9]+)\s*:\s*([0-9.]+)px/g)) {
    scale[m[1]] = Number(m[2]);
  }
  return scale;
}

test('字阶：最小档不低于 11px（方案 §3.2 地板）', () => {
  const scale = readScale();
  const min = Math.min(...Object.values(scale));
  assert.ok(Object.keys(scale).length >= 10, `档位数量异常：${Object.keys(scale).length}`);
  assert.ok(min >= 11, `最小档 ${min}px < 11px：${JSON.stringify(scale)}`);
});

test('字阶：每个档位都能被 Tailwind 工具类取到（漏声明 = 工具类被静默吞掉）', () => {
  const scale = readScale();
  const index = readFileSync(INDEX, 'utf8');
  const declared = new Set();
  for (const m of index.matchAll(/--text-([a-z0-9]+)\s*:/g)) declared.add(m[1]);

  const missing = Object.keys(scale).filter((k) => !TAILWIND_DEFAULT_TEXT.has(k) && !declared.has(k));
  assert.deepEqual(
    missing,
    [],
    `这些档位没在 styles/index.css 的 @theme 里声明，text-<name> 工具类不会生成：${missing.join(', ')}`,
  );
});

test('字阶：小字号工具类必须回落到令牌（@theme inline 写 var()）', () => {
  const index = readFileSync(INDEX, 'utf8');
  for (const name of ['4xs', '3xs', '2xs', 'md']) {
    const re = new RegExp(`--text-${name}\\s*:\\s*var\\(--text-${name}\\)`);
    assert.ok(re.test(index), `@theme 里的 --text-${name} 没写成 var(--text-${name})，改了令牌它不会跟着变`);
  }
  assert.ok(/@theme\s+inline\s*\{/.test(index), '@theme 需要 inline 才会把值内联成 var()');
});

test('字号：源码里不许写死 px（含 Tailwind 任意值）', () => {
  const offenders = [];
  for (const f of walk(SRC)) {
    if (!/\.(vue|css)$/.test(f)) continue;
    const text = readFileSync(f, 'utf8');
    text.split('\n').forEach((line, i) => {
      const m = line.match(/font-size:\s*([0-9.]+)px/);
      if (m) offenders.push(`${path.relative(ROOT, f)}:${i + 1} font-size: ${m[1]}px`);
      const a = line.match(/text-\[([0-9.]+)px\]/);
      if (a) offenders.push(`${path.relative(ROOT, f)}:${i + 1} text-[${a[1]}px]`);
    });
  }
  assert.deepEqual(offenders, [], `写死字号（应改用 var(--text-*) 或 text-* 工具类）：\n${offenders.join('\n')}`);
});

test('字号：模板里用到的"像档位"的字号类都真实存在', () => {
  const scale = readScale();
  const declared = new Set();
  for (const m of readFileSync(INDEX, 'utf8').matchAll(/--text-([a-z0-9]+)\s*:/g)) declared.add(m[1]);
  const known = new Set([...Object.keys(scale), ...TAILWIND_DEFAULT_TEXT, ...declared]);
  // 只挑"看起来是档位名"的：xs/sm/base/lg/xl/2xl/3xl + 4xs/3xs/2xs/md
  const sizeLike = /^([0-9]?xs|[0-9]xl|base|sm|md|lg|xl)$/;

  const offenders = [];
  for (const f of walk(SRC)) {
    if (!f.endsWith('.vue')) continue;
    const text = readFileSync(f, 'utf8');
    const m = text.match(/<template>([\s\S]*)<\/template>/);
    if (!m) continue;
    for (const mm of m[1].matchAll(/(?:^|[\s"':-])text-([a-z0-9]+)(?=[\s"'])/g)) {
      const name = mm[1];
      if (!sizeLike.test(name)) continue; // 颜色类等不在此列（由对比度闸负责）
      if (!known.has(name)) offenders.push(`${path.relative(ROOT, f)}: text-${name}`);
    }
  }
  assert.deepEqual(
    [...new Set(offenders)],
    [],
    `模板里出现刻度外的字号工具类（生成不出 CSS，会被静默吞掉）：\n${offenders.join('\n')}`,
  );
});


test('字阶：不许有亚像素档位（去重后相邻档差 ≥ 1px，批 89）', () => {
  const scale = readScale();
  const uniq = [...new Set(Object.values(scale))].sort((a, b) => a - b);
  const tooClose = [];
  for (let i = 1; i < uniq.length; i++) {
    const gap = uniq[i] - uniq[i - 1];
    if (gap < 1) tooClose.push(`${uniq[i - 1]}px → ${uniq[i]}px（差 ${gap}px）`);
  }
  assert.deepEqual(
    tooClose,
    [],
    `字阶里出现亚像素相邻档（0.5px 级差肉眼不可辨，等于同一档位多个名字）：\n  ${tooClose.join('\n  ')}`,
  );
  // 生效字阶钉死：改动这里必须是有意的（2026-10 升级高分屏舒适字阶）
  assert.deepEqual(uniq, [12, 13, 14, 15, 16, 20, 24, 30, 36, 48, 60, 76], `生效字阶变化：${uniq.join('/')}`);
});

test('字阶：13px 同值别名组必须保持（批 89 有意保留的语义名，2026-10 升级）', () => {
  const scale = readScale();
  const aliases = Object.entries(scale).filter(([, v]) => v === 13).map(([k]) => k).sort();
  assert.deepEqual(
    aliases,
    ['2xs', '3xs', 'sm', 'xs'],
    `13px 别名组变化（增删都要有意为之，并同步 tokens.css 的说明）：${aliases.join('/')}`,
  );
  // 曾经的亚像素档不得回潮
  for (const [name, v] of Object.entries(scale)) {
    assert.equal(
      Number.isInteger(v),
      true,
      `--text-${name} = ${v}px 是亚像素值，字阶只允许整像素档`,
    );
  }
});
