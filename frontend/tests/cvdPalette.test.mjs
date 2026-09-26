/**
 * 色觉辅助（CVD）调色板 —— 开关一开，语义色必须**仍然分得开**，而且机制不能悄悄失效
 *
 * ## 为什么值得单独建一条闸
 *
 * `useTheme()` 里的 `setCvd()` 往 `<html>` 打 `data-cvd="true"`，`tokens.css` 的
 * `:root[data-cvd='true']` 换掉 6 个 `--astra-up… / --astra-down…`。而全站 188 处用的是
 * **旧名** `var(--up)` / `var(--down)` —— 它们靠一句别名 `--up: var(--astra-up)` 才跟得上。
 * **这句别名一断（比如有人把 `--up` 改成字面量颜色），色觉辅助就会静默失效**：
 * 开关还能点、`data-cvd` 也照打，但颜色一个都不变。这种「看起来在工作」的失效最难发现，
 * 批 103 之前没有任何判据盯着它。
 *
 * ## 批 103 真正修掉的问题
 *
 * 开了色觉辅助后「跌」从红粉挪到橙色 `#e8923f`，而「警告」还是琥珀 `#e0b155`：
 * 感知距离从 **ΔE 54.7 塌到 20.0** —— 为「让人分得清」而开的开关，
 * 反而让「跌」和「警告」糊成一色。修法是把 CVD 下的警告改成更亮更偏黄的金色。
 *
 * ## 判据做四件事
 *
 * 1. `--up/--down/--warn` 系列必须仍然**别名**到 `--astra-*`（机制不可断）；
 * 2. `--astra-up… / --astra-down…` 在基准调色板里定义了几个，CVD 块就得覆盖几个（不许半覆盖）；
 * 3. CVD 模式下「跌」与「警告」、「涨」与「警告」的 ΔE 必须 ≥ 25；
 * 4. CVD 的涨/跌色作为**图形**对卡片底色 ≥ 3:1（WCAG 1.4.11）。
 *
 * ## 边界
 *
 * ΔE 用 CIE76（不做色适应），作为「是否糊在一起」的粗筛足够；
 * 阈值 25 是按「暗色 54.7 正常、塌到 20.0 有问题」这段实测定的，不是标准值。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

const TOKENS = path.resolve(import.meta.dirname, '..', 'src', 'styles', 'tokens.css');
const CSS = readFileSync(TOKENS, 'utf8');

/** 取某个选择器的声明块。⚠️ 必须**合并同名选择器的所有块**：
 *  基础令牌和 `--up: var(--astra-up)` 那组别名分别在 tokens.css 的两个 `:root { }` 里，
 *  只读第一个会得到一堆「找不到」，判据会以看不懂的方式挂掉（第一版就是这样）。 */
function block(selector) {
  const esc = selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const re = new RegExp(esc + '\\s*\\{([^}]*)\\}', 'g');
  let merged = '';
  for (const m of CSS.matchAll(re)) merged += m[1] + ';';
  assert.notEqual(merged, '', `tokens.css 里找不到选择器 ${selector}`);
  return merged;
}

function decls(text) {
  const out = {};
  for (const m of text.matchAll(/(--[\w-]+)\s*:\s*([^;]+);/g)) out[m[1]] = m[2].trim();
  return out;
}

const toRgb = (v) => {
  const h = v.trim().replace('#', '');
  const n = parseInt(h.length === 3 ? h.replace(/./g, (c) => c + c) : h, 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
};
const toLab = (rgb) => {
  const f = (v) => { v /= 255; return v > 0.04045 ? ((v + 0.055) / 1.055) ** 2.4 : v / 12.92; };
  const [r, g, b] = rgb.map(f);
  const X = (r * 0.4124 + g * 0.3576 + b * 0.1805) / 0.95047;
  const Y = r * 0.2126 + g * 0.7152 + b * 0.0722;
  const Z = (r * 0.0193 + g * 0.1192 + b * 0.9505) / 1.08883;
  const gg = (t) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  const [fx, fy, fz] = [gg(X), gg(Y), gg(Z)];
  return [116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz)];
};
const deltaE = (a, b) => {
  const [x, y] = [toLab(toRgb(a)), toLab(toRgb(b))];
  return Math.sqrt(x.reduce((s, v, i) => s + (v - y[i]) ** 2, 0));
};
const relLum = (v) => {
  const f = (c) => { c /= 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; };
  const [r, g, b] = toRgb(v).map(f);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};
const contrast = (a, b) => {
  const [x, y] = [relLum(a), relLum(b)];
  return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
};

const CVD_DARK = decls(block(":root[data-cvd='true']"));
const CVD_LIGHT = decls(block(":root[data-cvd='true'][data-theme='light']"));
const ROOT = decls(block(':root'));
const DARK = decls(block(":root[data-theme='dark']"));
const LIGHT = decls(block(":root[data-theme='light']"));

const DARK_CARD = DARK['--astra-surface-1'] ?? '#151821';

test('语义色必须仍然别名到 --astra-*（别名一断，色觉辅助会静默失效）', () => {
  // 全站 188 处用的是 var(--up)/var(--down)。它们必须继续指向 --astra-*，
  // 否则 data-cvd 打上去了、颜色却一个都不变 —— 最难发现的那种坏法。
  for (const [legacy, target] of [
    ['--up', '--astra-up'],
    ['--up-bg', '--astra-up-bg'],
    ['--down', '--astra-down'],
    ['--down-bg', '--astra-down-bg'],
    ['--warn', '--astra-warn'],
  ]) {
    assert.equal(
      ROOT[legacy],
      `var(${target})`,
      `--${legacy.replace(/^--/, '')} 不再是 var(${target}) —— 色觉辅助会静默失效。`,
    );
  }
});

test('CVD 调色板必须完整覆盖基准涨跌色（不许半覆盖）', () => {
  const base = Object.keys(DARK).filter((k) => /^--astra-(up|down|warn)/.test(k));
  assert.ok(base.length >= 6, `基准涨跌令牌太少（${base.length}），测试可能失配`);
  for (const [name, blk] of [['暗色', CVD_DARK], ['浅色', CVD_LIGHT]]) {
    const missing = base.filter((k) => !(k in blk));
    assert.deepEqual(
      missing,
      [],
      `${name}的 [data-cvd] 块漏了这些令牌：${missing.join(', ')} —— ` +
        `漏掉的那个在色觉辅助下会继续用普通配色，两套色混着显示。`,
    );
  }
});

test('开了色觉辅助后，「跌」与「警告」仍必须分得开（批 103 修的 ΔE 20.0）', () => {
  const MIN = 25;
  for (const [name, blk] of [['暗色', CVD_DARK], ['浅色', CVD_LIGHT]]) {
    const down = blk['--astra-down'];
    const warn = blk['--astra-warn'];
    const up = blk['--astra-up'];
    assert.ok(/^#/.test(down) && /^#/.test(warn), `${name}的 down/warn 必须是纯色值`);
    const dDown = deltaE(down, warn);
    const dUp = deltaE(up, warn);
    assert.ok(
      dDown >= MIN,
      `${name}：色觉辅助下「跌」(${down}) 与「警告」(${warn}) 的 ΔE 只有 ${dDown.toFixed(1)}（需 ≥ ${MIN}）—— ` +
        `为「让人分得清」而开的开关，不该把两个语义糊成一色。`,
    );
    assert.ok(dUp >= MIN, `${name}：「涨」与「警告」也糊在一起了（ΔE ${dUp.toFixed(1)}）`);
  }
});

test('色觉辅助色作为**文字**落在自己的淡色底上也要达 AA（批 105 修的 4.40:1）', () => {
  // ⚠️ 这是判据此前漏掉的一格，也是**全站回归审计**才抓到的那处：
  // 语义色除了直接铺在卡片上，还会以「文字 + 12~13% 同色淡底」的小标签形态出现
  // （/news 的「做多」11px 标签）。淡底把背景抬亮，对比度比裸卡片低得多 ——
  // #6799fe 裸卡片上 5.86:1 合格，落到自己的淡底上只剩 **4.40:1**（AA 要 4.5）。
  //
  // 合成顺序：淡底 over 卡内层底色（实测卡内层是 #212634，比 --surface-1 亮）。
  const CARDS = ['#151821', '#212634'];
  const alphaOf = (v) => {
    const m = /rgba\([^)]*,\s*([\d.]+)\s*\)/.exec(v);
    return m ? +m[1] : 1;
  };
  const over = (tint, bg) => [0, 1, 2].map((i) => tint[i] * tint[3] + bg[i] * (1 - tint[3]));
  const bad = [];
  for (const [key, bgKey, alphaKey] of [
    ['--astra-up', null, '--astra-up-bg'],
    ['--astra-down', null, '--astra-down-bg'],
    ['--astra-warn', null, '--astra-warn-bg'],
  ]) {
    const fg = CVD_DARK[key];
    const bgDecl = CVD_DARK[alphaKey];
    assert.ok(/^#/.test(fg) && /^rgba/.test(bgDecl), `${key} / ${alphaKey} 取值形态不对`);
    const tint = [...toRgb(fg), alphaOf(bgDecl)];
    for (const card of CARDS) {
      const composed = over(tint, toRgb(card));
      const hex = '#' + composed.map((v) => Math.round(v).toString(16).padStart(2, '0')).join('');
      const r = contrast(fg, hex);
      if (r < 4.5) bad.push(`${key} ${fg} 落在自己的淡底(${bgDecl}) 上、卡片 ${card} → ${r.toFixed(2)}:1`);
    }
  }
  assert.deepEqual(
    bad,
    [],
    `色觉辅助下这些小标签文字达不到 AA 4.5:1（基准色够亮，但被自己的淡底抬亮了背景）：\n  ${bad.join('\n  ')}\n` +
      '把语义色提亮，或把对应 `-bg` 的透明度调低。',
  );
});

test('（记录，不断言）浅色主题的语义色淡底标签目前达不到 AA', () => {
  // 浅色主题整套**已写好但不可达**（useTheme 是暗色专用桩，见批 103 的计划记录）。
  // 实测浅色下「文字 + 同色淡底」无论开不开色觉辅助都不到 4.5:1：
  //   非 CVD —— 涨 3.84 / 跌 4.18 / 警告 3.82
  //   CVD   —— 涨 3.46 / 跌 3.97 / 警告 3.86
  // 也就是说：**若将来要接通浅色主题，这套色得整体重算**，不是只补 CVD 那一档。
  // 这里只做存在性检查（值还在），避免哪天被误删后无人知晓这段结论。
  for (const k of ['--astra-up', '--astra-down', '--astra-warn']) {
    assert.ok(/^#/.test(LIGHT[k]), `浅色主题缺少 ${k}`);
    assert.ok(/^#/.test(CVD_LIGHT[k]), `浅色+CVD 缺少 ${k}`);
  }
});

test('色觉辅助下的涨跌色，作为图形也要能看清（WCAG 1.4.11 非文本对比度 ≥3:1）', () => {
  for (const [name, blk, card] of [['暗色', CVD_DARK, DARK_CARD]]) {
    for (const key of ['--astra-up', '--astra-down']) {
      const r = contrast(blk[key], card);
      assert.ok(
        r >= 3,
        `${name}：${key} (${blk[key]}) 对卡片底色 ${card} 只有 ${r.toFixed(2)}:1 —— ` +
          `K 线、圆点、进度条这类图形会看不清（<3:1）。`,
      );
    }
  }
});
