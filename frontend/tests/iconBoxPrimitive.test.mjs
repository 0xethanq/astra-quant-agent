/**
 * 26px 方形图标盒：单一事实源 + 盒内图标尺寸一致（批 78）。
 *
 * ## 实测到的重复与漂移
 *
 * 全站有 7 处「26px 方形图标盒」，其中 **6 处是逐字节相同的 9 属性规则**：
 *
 *   `.ag-icon`（AgentsPage）/ `.bk-archive-icon`（BackupPage）/
 *   `.cn-avatar`（CouncilPage）/ `.nf-cat-icon`（NotifyPage）/
 *   `.pl-icon`（PluginsPage）/ `.pol-unit-icon`（PolicySnapshotPage）
 *
 * 另有 `.dz-icon`（DangerZone）只是配色换成危险色。
 * 改一次盒径要改 7 个地方 —— 而且**已经漂移了**：
 * 同样大的盒子里，图标有 **13 / 14 / 15px 三种**尺寸
 * （BackupPage 13、DangerZone 15、其余 14）。多数决 + 与 `.btn-sm`
 * 的图标契约同值 ⇒ 统一 14px。
 *
 * 现收口为 `styles/components.css` 的 `.icon-box`，
 * 各页只在模板挂 `icon-box`，有差异的才另写 delta（`.dz-icon` 危险色、
 * `.cn-avatar.is-lg` 大号 34px + 16px 图标）。
 *
 * ## 顺带删掉的死 CSS（48 行）
 *
 * `.trace` / `.trace-step` / `.trace-marker` 及其 4 个语义变体
 * （`.is-brand` / `.is-up` / `.is-down` / `.is-warn`）实测在 `src/` 下
 * **任何** `.vue` / `.ts` 都不引用，是上一版设计的遗留。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const COMPONENTS_CSS = path.join(SRC, 'styles', 'components.css');

const BOX_PROPS = [
  'display: flex;',
  'align-items: center;',
  'justify-content: center;',
  'width: 26px;',
  'height: 26px;',
  'border-radius: var(--r-ctl);',
  'background-color: var(--ds-color-bg-surface-1);',
  'color: var(--ds-color-text-description);',
  'flex-shrink: 0;',
];

function styleFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) styleFiles(p, out);
    else if (/\.(vue|css)$/.test(n)) out.push(p);
  }
  return out;
}

/**
 * 找出所有「图标盒形状」的规则。
 *
 * 批 78 只认 26×26，于是**漏掉了另外三个手写的图标盒**：
 * `.pd-avatar`(32) / `.pd-model-icon`(32) / `.pv-avatar`(34) ——
 * 同一枚供应商字母组合头像在列表与详情里差 2px，且 `.pv-avatar` 还多一条
 * `letter-spacing: 0.02em`（它的孪生 `.pd-avatar` 没有）。
 *
 * 批 87 把判据泛化为「flex 居中 + 固定宽高 + `--r-ctl` 圆角 + surface-1 底」，
 * 与具体像素无关。用 `--r-ctl` 而不是任意圆角来区分**圆形**徽标
 * （`.pv-chain-n` 是 `border-radius: 50%` 的计数圆点，本就不是图标盒）。
 */
export function iconBoxShapedRules(text) {
  const out = [];
  for (const m of text.matchAll(/([^{}]+)\{([^{}]*)\}/g)) {
    const body = m[2];
    const shaped =
      /display:\s*flex/.test(body) &&
      /align-items:\s*center/.test(body) &&
      /justify-content:\s*center/.test(body) &&
      /width:\s*\d+px/.test(body) &&
      /height:\s*\d+px/.test(body) &&
      /border-radius:\s*var\(--r-ctl\)/.test(body) &&
      /background-color:\s*var\(--ds-color-bg-surface-1\)/.test(body);
    if (shaped) {
      out.push({
        selector: m[1].trim().split('\n').pop().trim(),
        line: text.slice(0, m.index).split('\n').length,
      });
    }
  }
  return out;
}

/**
 * 允许在原件之外存在的「图标盒形状」规则（值=理由）。
 * 原件的变体（`.icon-box.is-md` / `.is-mono`）只补尺寸/描边，本身不是完整形状，故不入此表。
 */
export const SHAPE_ALLOWED = {
  '.state-block .state-icon':
    '状态占位的图标位：与 .icon-box.is-md 同为 32px，写在原件同一个文件里，属原件的另一形态',
};

test('图标盒形状的规则只允许出现在原件里（任意尺寸，不再只查 26px）', () => {
  const bad = [];
  const found = [];
  for (const file of styleFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const inPrimitive = rel === path.join('styles', 'components.css');
    for (const r of iconBoxShapedRules(readFileSync(file, 'utf8'))) {
      found.push(`${rel}::${r.selector}`);
      if (SHAPE_ALLOWED[r.selector] && inPrimitive) continue;
      if (inPrimitive && r.selector === '.icon-box') continue;
      bad.push(`${rel}:${r.line} ${r.selector}`);
    }
  }
  assert.deepEqual(
    bad,
    [],
    `图标盒被各页重复定义（应改用全站 .icon-box 原件 + .is-md / .is-mono 变体）：\n  ${bad.join('\n  ')}`,
  );
  // 原件 + 已登记的例外
  assert.equal(
    found.length,
    1 + Object.keys(SHAPE_ALLOWED).length,
    `全站图标盒形状定义数应为 1+例外，实测 ${found.length} 处：${found.join(' / ')}`,
  );
});

test('批 87 归一：供应商头像与模型图标不得再各页自造（32/34px 漂移的回归锚点）', () => {
  const pv = readFileSync(path.join(SRC, 'views/admin/llm/ProviderListView.vue'), 'utf8');
  const pd = readFileSync(path.join(SRC, 'views/admin/llm/ProviderDetailView.vue'), 'utf8');
  for (const [rel, text] of [['ProviderListView', pv], ['ProviderDetailView', pd]]) {
    assert.doesNotMatch(text, /\.pv-avatar\s*\{|\.pd-avatar\s*\{|\.pd-model-icon\s*\{/, `${rel} 仍自带自造的图标盒规则`);
  }
  // 34px 曾经只出现在这里，全站不该再有
  assert.doesNotMatch(pv + pd, /\b34px\b/, '供应商页不该再出现 34px（应统一为原件的 .is-md=32px）');
  // 原件的两个变体必须存在且取值正确
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  const md = css.match(/\.icon-box\.is-md\s*\{([^}]*)\}/);
  assert.ok(md, 'components.css 缺少 .icon-box.is-md');
  assert.match(md[1], /width:\s*32px/);
  assert.match(md[1], /height:\s*32px/);
  const mono = css.match(/\.icon-box\.is-mono\s*\{([^}]*)\}/);
  assert.ok(mono, 'components.css 缺少 .icon-box.is-mono');
  assert.match(mono[1], /border:\s*1px solid var\(--ds-color-border-default\)/);
  assert.match(mono[1], /font-size:\s*var\(--text-4xs\)/);
  // 字距不得再被某个页面单独改掉
  assert.doesNotMatch(mono[1], /letter-spacing/, '.is-mono 不得带 letter-spacing（列表与详情必须一致）');
});

/**
 * 图标盒用户的**清册**。
 *
 * ⚠️ 变异 M1 暴露的缺口：只校验"CSS 里有没有重复定义"是拦不住模板**丢掉**
 * `icon-box` 的 —— 那样元素会静默失去全部盒样式（尺寸、居中、底色都没了），
 * 而任何规则层面的断言都不会响。故逐个文件钉死数量。
 *
 * 新增图标盒时在这里登记；数量不符即翻红。
 */
export const BOX_USERS = {
  'views/admin/llm/ProviderListView.vue': 1,
  'views/admin/llm/ProviderDetailView.vue': 2,
  'components/admin/page-parts/DangerZone.vue': 1,
  'views/admin/AgentsPage.vue': 1,
  'views/admin/BackupPage.vue': 1,
  'views/admin/CouncilPage.vue': 2,
  'views/admin/NotifyPage.vue': 1,
  'views/admin/PolicySnapshotPage.vue': 1,
};

test('每个图标盒用户都必须挂着 icon-box（清册逐文件钉数量）', () => {
  const bad = [];
  let total = 0;

  for (const [rel, expected] of Object.entries(BOX_USERS)) {
    const text = readFileSync(path.join(SRC, rel), 'utf8');
    const actual = (text.match(/class="[^"]*\bicon-box\b[^"]*"/g) || []).length;
    total += actual;
    if (actual !== expected) {
      bad.push(`${rel} 应挂 ${expected} 处 icon-box，实测 ${actual} 处`);
    }
  }

  assert.deepEqual(bad, [], `图标盒用户在模板上丢了 icon-box：\n  ${bad.join('\n  ')}`);
  // 2026-09-30 后台精简：内置插件清单页（PluginsPage）删除，其 1 处图标盒随之移除（11 → 10）。
  assert.equal(total, 10, `全站图标盒实例应为 10 个（批 87 并入 3 个；2026-09-30 删 PluginsPage 1 处），实测 ${total} 个`);
});

test('.icon-box 原件必须完整（9 条属性一个不少）', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  const m = css.match(/\.icon-box\s*\{([^}]*)\}/);
  assert.ok(m, 'components.css 里找不到 .icon-box');
  for (const p of BOX_PROPS) {
    assert.ok(m[1].includes(p), `.icon-box 缺少属性 ${p}`);
  }
});

test('挂了 icon-box 的元素，盒内图标必须是 14px（.is-lg 大号变体除外）', () => {
  const bad = [];
  let checked = 0;

  for (const file of styleFiles(SRC)) {
    if (!file.endsWith('.vue')) continue;
    const rel = path.relative(SRC, file);
    const lines = readFileSync(file, 'utf8').split('\n');
    lines.forEach((line, i) => {
      const m = line.match(/class="([^"]*\bicon-box\b[^"]*)"/);
      if (!m) return;
      const classes = m[1].split(/\s+/);
      // `.is-mono` 盒里是**文字**（字母组合 monogram），没有图标 —— 无 :size 可核对。
      if (classes.includes('is-mono')) return; // forEach 回调里只能用 return
      // 图标可能在同行，也可能在下一行（子元素换行）
      const window = line + ' ' + (lines[i + 1] || '');
      const size = window.match(/:size="(\d+)"/);
      if (!size) {
        bad.push(`${rel}:${i + 1} 图标盒内找不到 :size（无法核对尺寸一致性）`);
        return;
      }
      checked += 1;
      const expected = classes.includes('is-lg') ? 16 : 14;
      if (Number(size[1]) !== expected) {
        bad.push(`${rel}:${i + 1} [${classes.join(' ')}] :size="${size[1]}"，应为 ${expected}`);
      }
    });
  }

  // 2026-09-30 后台精简：PluginsPage 删除后下限由 9 调到 8（防"空转通过"的下限，不是产品承诺）。
  assert.ok(checked >= 8, `核对到的图标盒过少（${checked}）`);
  assert.deepEqual(bad, [], `图标盒内图标尺寸不一致：\n  ${bad.join('\n  ')}`);
});

test('每个挂了 icon-box 的模板都必须真有对应的样式或 delta', () => {
  // 反向：.icon-box 不能被删掉却在模板里继续挂着（样式会整体丢失）
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  assert.match(css, /\.icon-box\s*\{/, '模板挂着 icon-box 但 components.css 里没有该规则');

  // 危险色 delta 必须显式存在（否则危险图标会退回中性底色）
  const dz = readFileSync(path.join(SRC, 'components/admin/page-parts/DangerZone.vue'), 'utf8');
  assert.match(dz, /\.dz-icon\s*\{[^}]*background-color:\s*var\(--down-bg\)/s, '.dz-icon 危险色 delta 丢失');
  assert.match(dz, /\.dz-icon\s*\{[^}]*color:\s*var\(--down\)/s, '.dz-icon 危险色 delta 丢失');
  // 大号变体必须显式存在
  const cn = readFileSync(path.join(SRC, 'views/admin/CouncilPage.vue'), 'utf8');
  assert.match(cn, /\.cn-avatar\.is-lg\s*\{[^}]*width:\s*34px/s, '.cn-avatar.is-lg 大号变体丢失');
});

test('已删的死 CSS（.trace 家族）不得回潮', () => {
  const css = readFileSync(COMPONENTS_CSS, 'utf8');
  for (const sel of ['.trace', '.trace-step', '.trace-marker']) {
    assert.ok(
      !new RegExp(`\\${sel}\\s*[,{]`).test(css),
      `components.css 又出现死 CSS ${sel}（全站零引用）`,
    );
  }
  // 也确认它真的没人用（若将来有人要用，本断言会先提醒去审核）
  for (const file of styleFiles(SRC)) {
    if (file.endsWith('components.css')) continue;
    const text = readFileSync(file, 'utf8');
    assert.ok(!/trace-(step|marker)|class="trace\b/.test(text), `${path.relative(SRC, file)} 引用了已删的 .trace 家族`);
  }
});

test('闸自检：能识别任意尺寸的重复图标盒，且不误伤圆形徽标/缩略图', () => {
  const BOX = 'display: flex; align-items: center; justify-content: center; border-radius: var(--r-ctl); background-color: var(--ds-color-bg-surface-1);';
  const dup = `
.icon-box { ${BOX} width: 26px; height: 26px; }
.other-icon { ${BOX} width: 26px; height: 26px; }
.big-box { ${BOX} width: 32px; height: 32px; }`;
  const hits = iconBoxShapedRules(dup);
  assert.equal(hits.length, 3, '应识别出三处图标盒形状的规则（含 32px 的大号）');
  assert.deepEqual(hits.map((h) => h.selector), ['.icon-box', '.other-icon', '.big-box']);

  // 不误伤：有尺寸和圆角但没有 flex 居中的（例如图片缩略图）
  assert.deepEqual(
    iconBoxShapedRules('.thumb { width: 26px; height: 26px; border-radius: var(--r-ctl); background-color: var(--ds-color-bg-surface-1); }'),
    [],
    '不带 flex 居中的盒子不该被当作图标盒',
  );
  // 不误伤：圆形计数徽标（.pv-chain-n 是 border-radius: 50% 的 18px 圆点，本就不是图标盒）
  assert.deepEqual(
    iconBoxShapedRules('.chain-n { display: flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; background-color: var(--ds-color-bg-surface-1); }'),
    [],
    '圆形徽标不该被当作图标盒（用 --r-ctl 而非任意圆角来区分）',
  );
  // 不误伤：没有 surface-1 底色的
  assert.deepEqual(
    iconBoxShapedRules('.ghost { display: flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: var(--r-ctl); }'),
    [],
    '没有 surface-1 底色的不该被当作图标盒',
  );
});
