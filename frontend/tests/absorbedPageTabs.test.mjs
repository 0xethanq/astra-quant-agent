/**
 * 「页面被吸收为宿主页页签」的契约闸（2026-09-30 后台精简 18 → 11 项）。
 *
 * ## 背景
 *
 * 后台侧栏从 18 项精简到 11 项。做法**不是删功能**，而是把同域页面收进宿主页的页签：
 *
 * | 宿主页 | 被吸收页 | 旧路径 |
 * |---|---|---|
 * | GatewayPage（运行单元） | AgentsPage / DecisionsPage | /admin/agents · /admin/decisions |
 * | RiskPage（风控与拦截） | InterceptorsPage | /admin/interceptors |
 * | AuditPage（账号与审计） | AdminSysPage | /admin/adminsys |
 * | BackupPage（系统与灾备） | PolicySnapshotPage / AboutPage | /admin/policy · /admin/about |
 *
 * 这类改动有三种**静默**失败形态，本闸逐条按住：
 *
 * 1. **被吸收页的按钮消失**：最省事的做法是"嵌入时把整个页头藏掉"，
 *    于是那一页自己的刷新/沙箱/新建/归档按钮全部无家可归 —— 界面还在，能力没了。
 *    判据：被吸收页必须声明 `embedded`，且把 `:embedded` 传给共享 `PageHeader`
 *    （PageHeader 在嵌入态只收起标题与说明，**动作插槽照渲染**）。
 * 2. **页签不可达/无标签**：宿主页必须用 `BaseTabs`（漫游 tabindex + `baseId`
 *    → `aria-controls` 配对，面板 `id`/`aria-labelledby`/`tabindex="0"` 与
 *    `dashboard/RadarDrawer.vue` 的既有消费方式一致）。
 *    ⚠️ 顺带钉住一条真事故：把宿主页正文包进 `v-if` 面板后，**页内原有**的
 *    `aria-controls` 目标可能落进"已卸载的子树"→ 必须改成条件输出
 *    （RiskPage 的折叠分组就是这一处，见 `tests/ariaControlsTarget.test.mjs`）。
 * 3. **导航项指向空气**：`nav.ts` 的每个后台项都必须给出 `component`，
 *    且该文件真实存在于 `src/views/admin/`。
 *
 * 运行：`node --test tests/*.test.mjs`
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, existsSync } from 'node:fs';
import path from 'node:path';

const SRC = path.resolve(import.meta.dirname, '..', 'src');
const read = (rel) => readFileSync(path.join(SRC, rel), 'utf8');

/** 宿主页 → 期望的页签数（含宿主自身那一个）。 */
const HOSTS = {
  'views/admin/GatewayPage.vue': 2,
  'views/admin/RiskPage.vue': 2,
  'views/admin/DecisionsPage.vue': 4,
  'views/admin/BackupPage.vue': 3,
};

/** 被吸收页 → 它必须被哪个宿主页渲染。 */
const ABSORBED = {
  'views/admin/AgentsPage.vue': 'views/admin/GatewayPage.vue',
  'views/admin/InterceptorsPage.vue': 'views/admin/RiskPage.vue',
  'views/admin/AuditPage.vue': 'views/admin/DecisionsPage.vue',
  'views/admin/PolicySnapshotPage.vue': 'views/admin/BackupPage.vue',
  'views/admin/AboutPage.vue': 'views/admin/BackupPage.vue',
};

test('被吸收页必须声明 embedded 并把它传给共享 PageHeader（按钮不能丢）', () => {
  const bad = [];
  for (const rel of Object.keys(ABSORBED)) {
    const text = read(rel);
    if (!/defineProps<\{\s*embedded\?: boolean\s*\}>/.test(text)) {
      bad.push(`${rel} 未声明 embedded prop`);
    }
    if (!/<PageHeader[^>]*:embedded="props\.embedded"/.test(text)) {
      bad.push(`${rel} 未把 :embedded="props.embedded" 传给 PageHeader`);
    }
  }
  assert.deepEqual(bad, [], `被吸收页的嵌入契约不完整：\n  ${bad.join('\n  ')}`);
});

test('宿主页必须真的渲染被吸收页（且不是条件永假的死分支）', () => {
  const bad = [];
  for (const [child, host] of Object.entries(ABSORBED)) {
    const childName = path.basename(child, '.vue');
    const hostText = read(host);
    if (!hostText.includes(`import ${childName} from './${childName}.vue'`)) {
      bad.push(`${host} 未 import ${childName}`);
      continue;
    }
    // 模板里必须有 `<ChildName embedded />`（允许其后还有其它属性）
    if (!new RegExp(`<${childName}\\s+embedded\\b`).test(hostText)) {
      bad.push(`${host} 模板里没有以 embedded 渲染 <${childName}>`);
    }
  }
  assert.deepEqual(bad, [], `宿主页未真正吸收子页：\n  ${bad.join('\n  ')}`);
});

test('宿主页页签必须用 BaseTabs + panel 配对（ARIA Tabs 契约）', () => {
  const bad = [];
  for (const [rel, tabCount] of Object.entries(HOSTS)) {
    const text = read(rel);
    if (!/import BaseTabs from '\.\.\/\.\.\/components\/base\/BaseTabs\.vue'/.test(text)) {
      bad.push(`${rel} 未使用 BaseTabs（漫游 tabindex 单一事实源）`);
      continue;
    }
    if (!/<BaseTabs[^>]*baseId="/.test(text)) {
      bad.push(`${rel} 的 BaseTabs 缺 baseId（无法产出 aria-controls）`);
    }
    // 页签栏本身：恰好一处
    const tablists = (text.match(/<BaseTabs\b/g) || []).length;
    if (tablists !== 1) bad.push(`${rel} 的 BaseTabs 出现 ${tablists} 处，应为 1 处`);
    // 面板：每个页签一个 role="tabpanel"，都带 aria-labelledby 回指页签，且可键盘聚焦
    const panels = text.match(/<div[^>]*role="tabpanel"[^>]*>/g) || [];
    const ok = panels.filter((p) => /aria-labelledby="[^"]+"/.test(p) && /tabindex="0"/.test(p));
    if (panels.length !== tabCount) {
      bad.push(`${rel} 的 tabpanel 数量 ${panels.length}，应为 ${tabCount}`);
    }
    if (ok.length !== panels.length) {
      bad.push(`${rel} 有 ${panels.length - ok.length} 个 tabpanel 缺 aria-labelledby 或 tabindex="0"`);
    }
  }
  assert.deepEqual(bad, [], `宿主页页签契约不完整：\n  ${bad.join('\n  ')}`);
});

test('nav.ts 的每个后台项都必须给出真实存在的 component', () => {
  const navText = read('config/nav.ts');
  const items = [...navText.matchAll(/key:\s*'(admin-[^']+)'[^}]*?component:\s*'([A-Za-z0-9_]+)'/gs)]
    .map((m) => ({ key: m[1], component: m[2] }));
  assert.ok(items.length >= 11, `带 component 的后台导航项不足：${items.length}`);
  const bad = [];
  for (const it of items) {
    if (!existsSync(path.join(SRC, 'views/admin', `${it.component}.vue`))) {
      bad.push(`${it.key} → views/admin/${it.component}.vue 不存在`);
    }
  }
  assert.deepEqual(bad, [], `导航项指向不存在的组件：\n  ${bad.join('\n  ')}`);
});

test('已删除页面不得复活，旧路径必须有重定向', () => {
  // 内置插件清单页：15 天 0 动作、只读静态清单 → 直接删除（不是吸收）
  assert.equal(existsSync(path.join(SRC, 'views/admin/PluginsPage.vue')), false,
    'PluginsPage.vue 已删除，不应复活');
  assert.equal(existsSync(path.join(SRC, 'views/admin/LegacyRedirect.vue')), false,
    'LegacyRedirect.vue 是零引用死文件，已删除');

  const routerText = read('router/index.ts');
  for (const oldPath of ['plugins', 'policy', 'about', 'agents', 'interceptors', 'audit']) {
    assert.ok(routerText.includes(`path: '${oldPath}', redirect`),
      `/admin/${oldPath} 缺少重定向（旧书签会 404）`);
  }
});
