/**
 * 悬停反馈判据（批 100）。
 *
 * ## 怎么发现的：又一个审计工具不覆盖的维度
 *
 * 前几批把 `a11y-audit.js` 的各类指标压到 0 之后，换量「**可点但悬停毫无反馈**」。
 * 做法不用逐个 hover：把 CSS 里所有 `:hover` 选择器**剥掉伪类**，再对每个
 * `cursor: pointer` 的最外层元素跑 `el.matches(stripped)` —— 完整且极快。
 *
 * 25 路由 **901 个可点元素 / 139 个无任何 hover 规则**。逐个复核后：
 *
 * | 组 | 数量 | 判定 |
 * |---|---|---|
 * | `button.w-full.flex`（侧栏频道） | 30 | **真缺陷**：同列表下面的「文档」按钮有 hover，相邻两项行为不同 |
 * | `button.sort-btn` | 16 | **真缺陷**：实测悬停 computed style **零变化** |
 * | `button.switch` | 16 | **真缺陷**：全站开关只有「点击后旋钮位移」 |
 * | `A.skip-link` | 24 | 不是缺陷：平时移出视口，靠 `:focus` 显现 |
 * | `button.seg-on` | 17 | 不是缺陷：`.seg button:hover:not(.seg-on)` **明确排除**选中项 |
 * | `button.w-full.text-left`（DocsView） | 11 | **假阳性**：子元素有 `group-hover:opacity-100` |
 *
 * ## 修法
 *
 * ① 侧栏频道按钮：活动/非活动态原本写在内联 `:style` —— **内联样式优先级高于工具类**，
 *    直接加 `hover:` 类不会生效。改为 `:class`，hover 只加在**非活动**项上（与
 *    `.seg button:hover:not(.seg-on)` 同一约定）。
 * ② `.sort-btn:hover` 用既有语汇 `--ds-color-text-primary` + `--dur-fast`。
 * ③ `.switch:hover:not([aria-checked="true"])` 用 `--ds-color-border-hover`；
 *    **显式 `:not()` 是必须的**：否则与 `.switch[aria-checked="true"]` 同权重，
 *    靠书写顺序决胜（行为对，但改一处顺序就静默失效）。
 *
 * 实机复核（hover 前后 diff computed style）：
 * 排序按钮 2 项变化；侧栏**非当前**频道 2 项变化、当前频道 0 项（符合约定）；
 * **关**的开关边色 `rgb(40,48,66)` → `rgb(59,69,94)`、**开**的开关 0 项（符合约定）；
 * 对照 `.btn-ghost` 2 项变化（证明仪器能检出阳性）。
 *
 * ⚠️ 遍历样式表时：**CSS 嵌套让 `CSSStyleRule` 也有 `cssRules`（通常是空列表）**，
 * 写成 `if (rule.cssRules) { walk(); continue }` 会把**每条样式规则都跳过**
 * （实测 899 条规则里 0 条 hover）。必须先看 `selectorText`。
 *
 * ## ⚠️ 本判据的覆盖边界（别误以为它管全部）
 *
 * 它只抓 **「inline style + transition」** 这一种形态。**改成 `:class` 之后就不在它管辖内了**
 * —— 元素上已经没有 inline style 可查。两个已知盲区：
 *
 * 1. **`:class` 形态**（MobileTabBar）：`transition-colors` + `:class` 三元，静态无法判定
 *    「非活动分支该不该有 hover」（试写过通用规则，全仓只会命中 2 处布局/变体类，**全是假阳性**）。
 * 2. **静态 `style=""` 之外**：已修好的元素再「删掉 hover 类」它也不会红。
 *
 * 这两类的回归由**实机审计工具**的「悬停无反馈」一类兜底；
 * 而**移动端专属组件**（MobileTabBar 等）必须用**窄屏视口**跑审计才会被量到
 * —— 批 101 就是这么发现「展开卡片列表」那个按钮的（该组件已随全站收口 OKX 删除）。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');

function walk(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) walk(p, out);
    else out.push(p);
  }
  return out;
}
const CSS = readFileSync(path.join(SRC, 'styles', 'components.css'), 'utf8');
const DASH = readFileSync(path.join(SRC, 'layouts', 'DashboardLayout.vue'), 'utf8');

/** 找到含指定选择器的规则体（注释先剥掉）。 */
function ruleBody(css, selector) {
  const clean = css.replace(/\/\*[\s\S]*?\*\//g, '');
  const re = new RegExp(`(?:^|\\})\\s*${selector.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\s*\\{([^}]*)\\}`);
  const m = re.exec(clean);
  return m ? m[1] : null;
}

test('表格排序按钮必须有 hover 反馈（批 100 修的 16 处）', () => {
  const body = ruleBody(CSS, '.sort-btn:hover');
  assert.ok(body, '找不到 .sort-btn:hover —— 表头又会变成「看不出可点」');
  assert.match(body, /color\s*:\s*var\(--ds-color-text-primary\)/, 'hover 应改文字色（全站既有语汇）');
  const base = ruleBody(CSS, '.sort-btn');
  assert.match(base, /transition:\s*color\s+var\(--dur-fast\)/, 'hover 变色要接动效令牌，否则硬切');
});

test('开关的 hover 必须显式排除「开着」的状态（去掉顺序依赖）', () => {
  // 批 102 又加了 `:not(:disabled)`（禁用时不该有悬停反馈），故两个 :not 都要在。
  const body = ruleBody(CSS, '.switch:hover:not(:disabled):not([aria-checked="true"])');
  assert.ok(
    body,
    '找不到 .switch:hover:not(:disabled):not([aria-checked="true"]) —— ' +
      '退回成裸 `.switch:hover` 会同时踩两个坑：与 `.switch[aria-checked="true"]` 同权重、' +
      '只能靠书写顺序决胜；且被禁用的开关照样亮起悬停边色',
  );
  assert.match(body, /border-color\s*:\s*var\(--ds-color-border-hover\)/);
});

test('侧栏频道按钮不得再用内联样式写活动态（否则 hover 类永远不生效）', () => {
  const m = /<button\s+v-for="tab in publicTabs"[\s\S]*?>/.exec(DASH);
  assert.ok(m, '找不到 publicTabs 的按钮');
  const tag = m[0];
  assert.ok(
    !/:style="[\s\S]*backgroundColor/.test(tag),
    '活动态又写回了内联 `:style` —— **内联样式优先级高于工具类**，hover 类会失效',
  );
  assert.match(tag, /:class="[\s\S]*hover:bg-\[var\(--surface-2\)\]/, '非活动态缺少 hover 类');
  assert.match(tag, /activeTab === tab\.key[\s\S]*?\?[\s\S]*?:\s*'[^']*hover:/, 'hover 只应加在非活动分支上');
});

/** 数据驱动的条形/进度元素：`:style` 里同时绑了 width/height/transform，
 *  颜色随**数值**变化（不是随选中态）—— 这种 transition 是合理的动画，必须放过。 */
function isDataDriven(style) {
  return /(width|height|transform|left|right|top|bottom)\s*:/.test(style);
}

/** 静态判不出来、已人工核实的例外（每条都写清理由，便于将来复核）。 */
export const LEGIT = [
  {
    file: 'components/dashboard/TopBar.vue',
    styleHas: '--surface-header',
    why: '顶栏 `<header>` 的 `transition-colors` 服务于**主题切换**：它的 style 引用了 ' +
      '`--surface-header` / `--line-1` / `--ink-1`，换肤时这些变量变化需要过渡。' +
      '它不是交互元素，本就不该有 hover。',
  },
];

/** 全仓扫描「挂了 transition 却不可能被悬停触发」的内联状态样式。 */
export function deadInlineTransitions() {
  const HOVER_FOR = { backgroundColor: 'hover:bg-', color: 'hover:text-', borderColor: 'hover:border-', opacity: 'hover:opacity-' };
  const bad = [];
  for (const f of walk(SRC)) {
    if (!f.endsWith('.vue')) continue;
    const src = readFileSync(f, 'utf8');
    // ⚠️ 静态 `style="..."` 也要扫：移动端「展开卡片列表」按钮就是静态 style，
    // 第一版只扫 `:style` 于是漏了它。
    const re = /class="([^"]*transition-(?:colors|all)[^"]*)"\s*\n\s*:?style="([^"]*)"/g;
    let m;
    while ((m = re.exec(src))) {
      const [, cls, style] = m[1] === undefined ? [] : [m[0], m[1], m[2]];
      const controlled = Object.keys(HOVER_FOR).filter((prop) => new RegExp(prop + '\\s*:').test(style));
      if (!controlled.length) continue;              // 只管颜色类状态
      if (isDataDriven(style)) continue;             // 数据驱动的条形：动画合理
      // 反馈挂在**子元素**上（`group-hover:`）也算有反馈 —— DocsView 目录按钮就是这种：
      // 按钮自身类里只有 `group`，靠子元素 ChevronRight 的 `group-hover:opacity-100` 变化。
      const blockEnd = src.indexOf('</button>', m.index);
      const block = src.slice(m.index, blockEnd === -1 ? m.index + 1500 : blockEnd);
      if (/group\b/.test(cls) && /group-hover:/.test(block)) continue;
      const hovered = Object.entries(HOVER_FOR).filter(([, util]) => cls.includes(util)).map(([prop]) => prop);
      // 「死」的精确判据是**一个状态变体都没有**：`transition-colors` 也可能服务于
      // `focus:` / `active:` —— 搜索框、下拉框、乃至 TopBar 的 `<header>` 都属此类，
      // 第一版只看 `hover:` 把它们误报成死动效（5 处假阳性）。
      const anyStateVariant = /(hover|focus|focus-visible|focus-within|active|checked|disabled|group-hover):/.test(cls);
      const dead = !anyStateVariant;
      const overridden = controlled.some((prop) => hovered.includes(prop));
      const legit = LEGIT.find((L) => path.relative(SRC, f) === L.file && style.includes(L.styleHas));
      if (legit) continue;
      if (dead || overridden) {
        bad.push({
          file: path.relative(SRC, f),
          line: src.slice(0, m.index).split('\n').length,
          why: dead ? '挂了 transition 却一个 hover: 都没有' : `内联 :style 控制 ${controlled.join('/')}，hover 又去改同一属性（会被内联吃掉）`,
        });
      }
    }
  }
  return bad;
}

test('全仓不得再有「内联 :style 写状态 + transition」的死动效（批 100/101 共修 8 处）', () => {
  const bad = deadInlineTransitions();
  const list = bad.map((b) => `${b.file}:${b.line}  ${b.why}`);
  assert.deepEqual(list, [], `这些地方的 transition 永远不会触发，改用 :class：\n  ${list.join('\n  ')}`);
});

test('移动端底部标签栏必须标出当前页（aria-current）', () => {
  // 侧栏一直有 `:aria-current="... ? 'page' : undefined"`，移动端标签栏却漏了 ——
  // 后果有两层：读屏用户在窄屏下**分不清当前在哪一页**；
  // 且「选中项不因悬停变样」的自动化豁免也认不出它（审计里因此残留假阳性）。
  const src = readFileSync(path.join(SRC, 'components/dashboard/MobileTabBar.vue'), 'utf8');
  assert.match(
    src,
    /:aria-current="activeKey === tab\.key \? 'page' : undefined"/,
    'MobileTabBar 缺少 aria-current（与 DashboardLayout 侧栏的做法保持一致）',
  );
});

test('豁免项不得空转（改了文件就该把豁免删掉，别留死豁免）', () => {
  for (const L of LEGIT) {
    const src = readFileSync(path.join(SRC, L.file), 'utf8');
    assert.ok(
      src.includes(L.styleHas),
      `豁免项已失效（${L.file} 里找不到 ${L.styleHas}）—— 请从 LEGIT 删掉，别留死豁免。理由原本是：${L.why}`,
    );
  }
});

test('勾选行（.sc-check）必须有悬停反馈，且危险变体也要有', () => {
  const src = readFileSync(path.join(SRC, 'views/admin/SecurityPage.vue'), 'utf8');
  const clean = src.replace(/\/\*[\s\S]*?\*\//g, '');
  const hover = /\.sc-check:hover\s*\{([^}]*)\}/.exec(clean);
  assert.ok(hover, '找不到 .sc-check:hover —— 勾选行又会变得悬停毫无反应');
  assert.match(
    hover[1],
    /background-color\s*:\s*var\(--ds-color-bg-hover\)/,
    '应当用底色（与同页 .sc-radio:hover / .sc-row:hover 同语汇）',
  );
  // 危险变体：文字色被更具体的 `.sc-check.is-danger span` 占住，只改文字色等于没反馈
  const base = /\.sc-check\s*\{([^}]*)\}/.exec(clean);
  assert.match(base[1], /transition:\s*background-color\s+var\(--dur-fast\)/, '过渡要接动效令牌');
  assert.ok(
    /\.sc-check\.is-danger span\s*\{[^}]*var\(--down\)/.test(clean),
    '危险变体的红字规则不该被删（删了危险信号就没了）',
  );
});

test('抽屉内的日志过滤芯片必须有悬停反馈（页面审计看不到的地方）', () => {
  // 批 106：这三个芯片（all/warn/error）在**默认关闭的抽屉**里，
  // 页面级审计永远扫不到；它此前用内联 :style 写选中态、且**连 transition 都没有**，
  // 所以「内联 :style + transition」那条判据也抓不到。实测未选中项悬停零变化。
  const src = readFileSync(path.join(SRC, 'components/dashboard/TrajectoryPanel.vue'), 'utf8');
  const tag = /<button[\s\S]{0,700}?logFilter === filter[\s\S]{0,700}?>/.exec(src);
  assert.ok(tag, '找不到日志过滤芯片的模板');
  assert.match(tag[0], /hover:bg-\[var\(--ds-color-bg-hover\)\]/, '未选中芯片缺少悬停反馈');
  assert.match(tag[0], /hover:text-\[var\(--ink-1\)\]/, '未选中芯片缺少悬停文字色');
  assert.ok(!/:style=/.test(tag[0]), '不要再退回内联 :style 写选中态');
  assert.match(tag[0], /transition-colors/, '悬停变化要接过渡');
  // 常驻 border：否则选中时凭空多出 1px 边框，整排宽度会跳
  assert.match(tag[0], /\bborder\b[^"]*border-transparent/, '边框必须常驻（内联态时用border-transparent），否则选中会引起 1px 宽度跳动');
});

test('品牌 logo 链接必须有悬停反馈', () => {
  const m = /<RouterLink\s+to="\/"\s+class="([^"]*)"/.exec(DASH);
  assert.ok(m, '找不到品牌区 RouterLink');
  assert.match(m[1], /hover:opacity-\d+/, '品牌链接缺少 hover（logo 链接是唯一入口之一）');
  assert.match(m[1], /transition-opacity/, 'opacity 变化要接 transition，否则硬切');
});

test('判据自检：ruleBody 能取到规则、取不到时不误判', () => {
  assert.ok(ruleBody(CSS, '.sort-btn:hover'), '已知存在的选择器应取到');
  assert.equal(ruleBody(CSS, '.definitely-not-here:hover'), null, '不存在的选择器应返回 null');
  assert.match(ruleBody(CSS, '.seg button:hover:not(.seg-on)'), /background-color/, '选中态排除的既有语汇仍在');
});
