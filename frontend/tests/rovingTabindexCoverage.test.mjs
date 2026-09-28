/**
 * 全站 tablist 漫游 tabindex 与方向键导航覆盖守卫闸（批 66）。
 *
 * ## 为什么要守
 *
 * `role="tab"` 只是给读屏器"这是页签"的语义，并不自动带来键盘行为。
 * WAI-ARIA APG 的 Tabs 模式要求两件模板层面必须成立的事：
 *
 *   1. **漫游 tabindex（roving tabindex）**：仅当前选中页签 `tabindex="0"`，
 *      其余 `tabindex="-1"`。整条 tablist 在 Tab 键顺序里只占一格，
 *      组内切换交给方向键。若每个 `role="tab"` 都是默认 tabindex，
 *      一条 4 项筛选条就要按 4 次 Tab 才能穿过去（WCAG 2.1.1 实质不达标）。
 *   2. **方向键导航**：←/→（上下排布时 ↑/↓）环绕移动焦点并同步激活，Home/End 跳首尾。
 *
 * 批 66 实测：全站 9 个页面共 21 个 `role="tab"` 按钮，**无一条具备上述任一行为**。
 * 逻辑已收敛到 `src/composables/useRovingTabs.ts`，此闸确保没有任何 tablist 再退回裸按钮。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const ROVING = path.join(SRC, 'composables', 'useRovingTabs.ts');

function vueFiles(dir, out = []) {
  for (const n of readdirSync(dir)) {
    const p = path.join(dir, n);
    if (statSync(p).isDirectory()) vueFiles(p, out);
    else if (n.endsWith('.vue')) out.push(p);
  }
  return out;
}

const stripComments = (t) => t.replace(/<!--[\s\S]*?-->/g, '');

/** 抓出所有含 role="tab" 的开始标签（容忍多行属性）。 */
function tabTags(body) {
  const out = [];
  for (const m of body.matchAll(/<button\b([^>]*?)>/g)) {
    if (/\brole="tab"/.test(m[1])) out.push(m[1]);
  }
  return out;
}

test('每个 role="tab" 按钮必须绑定漫游 tabindex', () => {
  const bad = [];

  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const text = stripComments(readFileSync(file, 'utf8'));
    const tm = text.match(/<template>([\s\S]*)<\/template>/);
    if (!tm) continue;

    for (const attrs of tabTags(tm[1])) {
      if (!/:tabindex=/.test(attrs)) {
        bad.push(`${rel} :: role="tab" 缺少 :tabindex 漫游绑定 -> ${attrs.replace(/\s+/g, ' ').trim().slice(0, 90)}`);
      }
    }
  }

  assert.deepEqual(bad, [], `以下页签未接入漫游 tabindex：\n  ${bad.join('\n  ')}`);
});

test('每个含 role="tab" 的组件必须接入方向键导航（@keydown）', () => {
  const bad = [];

  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const text = stripComments(readFileSync(file, 'utf8'));
    const tm = text.match(/<template>([\s\S]*)<\/template>/);
    if (!tm) continue;

    const tags = tabTags(tm[1]);
    const missing = tags.filter((a) => !/@keydown=/.test(a));
    if (missing.length) bad.push(`${rel} :: ${missing.length}/${tags.length} 个页签没有 @keydown 方向键处理`);
  }

  assert.deepEqual(bad, [], `以下页签缺失方向键导航：\n  ${bad.join('\n  ')}`);
});

test('所有 tablist 必须复用 useRovingTabs 单一事实源', () => {
  const bad = [];

  for (const file of vueFiles(SRC)) {
    const rel = path.relative(SRC, file);
    const text = readFileSync(file, 'utf8');
    if (!/role="tab"/.test(text)) continue;
    // 基准件自身即定义方，必须 import；其余任何含页签的组件同样必须 import。
    if (!/useRovingTabs/.test(text)) bad.push(`${rel} :: 含 role="tab" 但未使用 useRovingTabs`);
  }

  assert.deepEqual(bad, [], `以下文件绕过了统一的漫游键盘实现：\n  ${bad.join('\n  ')}`);
});

test('useRovingTabs 覆盖 APG 要求的全部按键与环绕语义', () => {
  const text = readFileSync(ROVING, 'utf8');

  assert.match(text, /'ArrowRight'/, '缺少 ArrowRight');
  assert.match(text, /'ArrowLeft'/, '缺少 ArrowLeft');
  assert.match(text, /'ArrowDown'/, '缺少 ArrowDown（纵向排布）');
  assert.match(text, /'ArrowUp'/, '缺少 ArrowUp（纵向排布）');
  assert.match(text, /'Home'/, '缺少 Home');
  assert.match(text, /'End'/, '缺少 End');
  assert.match(text, /e\.preventDefault\(\)/, '未阻止默认滚动行为');
  assert.match(text, /\.focus\(\)/, '未把焦点搬到新选中项');
  assert.match(text, /return selected \? 0 : -1/, '漫游 tabindex 语义不正确');
});

test('BaseTabs 的 aria-controls 必须与消费端 tabpanel id 双向配对', () => {
  const tabs = readFileSync(path.join(SRC, 'components/base/BaseTabs.vue'), 'utf8');
  const drawer = readFileSync(path.join(SRC, 'components/dashboard/RadarDrawer.vue'), 'utf8');

  // 基准件在拿到 baseId 时才产出与消费端约定好的 id 命名
  assert.match(tabs, /:aria-controls="baseId \? `\$\{baseId\}-panel-\$\{it\.key\}` : undefined"/, 'BaseTabs 未按约定产出 aria-controls');
  assert.match(tabs, /:id="baseId \? `\$\{baseId\}-tab-\$\{it\.key\}` : undefined"/, 'BaseTabs 未产出页签 id');

  // 消费端确实传了 baseId
  assert.match(drawer, /base-id="radar-detail"/, 'RadarDrawer 未给 BaseTabs 传 base-id');

  const keys = ['macro', 'quotes', 'council', 'raw'];
  for (const key of keys) {
    assert.ok(drawer.includes(`id="radar-detail-panel-${key}"`), `面板 ${key} 缺少 id，aria-controls 会指向空节点`);
    assert.ok(drawer.includes(`aria-labelledby="radar-detail-tab-${key}"`), `面板 ${key} 缺少 aria-labelledby 回指页签`);
  }

  // 反向：模板里出现的每个 radar-detail-panel-* 都要有对应页签
  const ids = [...new Set([...drawer.matchAll(/id="radar-detail-panel-([a-z]+)"/g)].map((m) => m[1]))].sort();
  assert.deepEqual(ids, [...keys].sort(), '面板 id 集合与页签 key 集合不一致');

  // 四个面板都必须是 role="tabpanel" 且可聚焦
  const panels = [...drawer.matchAll(/<div\s[^>]*id="radar-detail-panel-[a-z]+"[^>]*>/g)].map((m) => m[0]);
  assert.equal(panels.length, 4, '未找到 4 个面板根节点');
  for (const tag of panels) {
    assert.match(tag, /role="tabpanel"/, '面板缺少 role="tabpanel"');
    assert.match(tag, /tabindex="0"/, '面板缺少 tabindex="0"（内容区不可键盘聚焦）');
  }
});

test('闸自检：能准确拦截缺 tabindex / 缺 keydown 的裸页签', () => {
  const naive = '<button role="tab" :aria-selected="x">A</button>';
  const full = '<button role="tab" :tabindex="roving(x)" @keydown="onKey($event, 0)">A</button>';

  const checkIndex = (a) => !/:tabindex=/.test(a);
  const checkKeys = (a) => !/@keydown=/.test(a);

  assert.equal(checkIndex(naive), true, '应拦截缺漫游 tabindex 的页签');
  assert.equal(checkIndex(full), false, '应放行合规页签');
  assert.equal(checkKeys(naive), true, '应拦截缺方向键处理的页签');
  assert.equal(checkKeys(full), false, '应放行合规页签');
});
