/**
 * 双站视觉语言同步与去落地页守卫测试（TradeSkill / SkillHub 统一基准）。
 *
 * 锁定以下核心不变量，防止后续迭代发生品牌回退或材质漂移：
 * 1. Signal Orange 品牌主色与 Swiss Carbon / Warm Paper 中性表面色阶
 * 2. 扁平化精度材质（卡片与主按钮去 backdrop-filter、去炫光阴影、去 --ds-bg-gradient）
 * 3. 收敛圆角刻度（8 / 12 / 14 / 100px）且金融红绿/CVD 色盲令牌不被误改
 * 4. 兄弟品牌 SVG 标识与 AstraQuant 双色字标、ChartWorkstation 几何水印
 * 5. LandingView 与 locales/{zh,en}/landing.ts 已彻底移除，根路由 `/` 直达实盘工作台
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { existsSync, readFileSync, readdirSync, statSync } from 'node:fs';
import path from 'node:path';

const FRONTEND = path.resolve(import.meta.dirname, '..');
const SRC = path.join(FRONTEND, 'src');

function collectSourceFiles(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const full = path.join(dir, name);
    if (statSync(full).isDirectory()) collectSourceFiles(full, out);
    else if (name.endsWith('.vue') || name.endsWith('.ts') || name.endsWith('.css')) out.push(full);
  }
  return out;
}

test('核心令牌严格对齐 TradeSkill Signal Orange 与 Swiss Carbon / Warm Paper 色阶', () => {
  const tokens = readFileSync(path.join(SRC, 'styles', 'tokens.css'), 'utf8');
  const indexCss = readFileSync(path.join(SRC, 'styles', 'index.css'), 'utf8');

  // 暗色主品牌 & Swiss Carbon 底阶
  for (const expected of [
    '--ds-color-brand: #ff5e2b;',
    '--ds-color-brand-deep: #e04819;',
    '--ds-color-bg-page: #0a0a0b;',
    '--ds-color-bg-surface-1: #111113;',
    '--ds-color-bg-surface-2: #18181b;',
    '--ds-color-bg-surface-3: #222226;',
    '--ds-color-bg-surface-4: #27272a;',
    '--ds-btn-primary-bg: #ff5e2b;',
    '--ds-btn-primary-text: #ffffff;',
    '--ds-btn-primary-hover-bg: #ff7347;',
    '--ds-bg-gradient: none;',
    '--grad-surface: none;',
    '--astra-brand-bg: rgba(255, 94, 43, 0.14);',
    '--astra-brand-line: rgba(255, 94, 43, 0.34);',
  ]) {
    assert.ok(tokens.includes(expected), `tokens.css 缺少预期暗色同步令牌: ${expected}`);
  }

  // 浅色 Warm Paper & Signal Orange
  for (const expected of [
    '--ds-color-brand: #e04819;',
    '--ds-color-brand-deep: #c93d12;',
    '--ds-color-bg-page: #f6f5f2;',
    '--ds-color-bg-surface-1: #ffffff;',
    '--ds-color-bg-surface-2: #eceae4;',
    '--ds-color-bg-surface-3: #e3e0d8;',
    '--ds-btn-primary-bg: #e04819;',
    '--ds-btn-primary-hover-bg: #c93d12;',
  ]) {
    assert.ok(tokens.includes(expected), `tokens.css 缺少预期浅色同步令牌: ${expected}`);
  }

  // 收敛圆角刻度（tokens.css + @theme index.css）
  assert.ok(tokens.includes('--ds-radius-sm: 8px;'));
  assert.ok(tokens.includes('--ds-radius-card: 12px;'));
  assert.ok(tokens.includes('--r-float: 14px;'));
  assert.ok(indexCss.includes('--radius-md: 8px;'));
  assert.ok(indexCss.includes('--radius-lg: 12px;'));
  assert.ok(indexCss.includes('--radius-xl: 14px;'));

  // 金融涨跌与 CVD 模式保持独立语义，不被品牌改色误伤
  assert.ok(tokens.includes('--astra-up: #48c78e;'));
  assert.ok(tokens.includes(":root[data-cvd='true']"));
  assert.ok(tokens.includes('--astra-up: #7aa6ff;'));
});

test('扁平精密材质：卡片/侧栏/登录卡去除 backdrop-filter 与翡翠炫光阴影', () => {
  const components = readFileSync(path.join(SRC, 'styles', 'components.css'), 'utf8');
  const baseCss = readFileSync(path.join(SRC, 'styles', 'base.css'), 'utf8');
  const login = readFileSync(path.join(SRC, 'views', 'admin', 'LoginPage.vue'), 'utf8');
  const adminLayout = readFileSync(path.join(SRC, 'layouts', 'AdminLayout.vue'), 'utf8');
  const chart = readFileSync(path.join(SRC, 'components', 'dashboard', 'ChartWorkstation.vue'), 'utf8');

  assert.ok(!components.includes('16, 185, 129'), 'components.css 不得保留硬编码翡翠 RGB');
  assert.ok(!components.includes('--grad-surface'), 'components.css 不得再叠加表面材质渐变');
  assert.ok(!baseCss.includes('--ds-bg-gradient'), 'base.css body 不得渲染页面级环境渐变');
  assert.ok(!login.includes('.auth-page::before'), 'LoginPage 不得保留径向光晕伪元素');
  assert.ok(!login.includes('16, 185, 129'), 'LoginPage 不得保留翡翠发光阴影');
  assert.ok(!chart.includes('wm-emerald-glow'), 'ChartWorkstation 水印不得保留旧版翡翠光晕');

  const cardRule = components.match(/\.card,\s*\.dsh-card,\s*\.section\s*\{[\s\S]*?\}/)?.[0] || '';
  assert.ok(!cardRule.includes('backdrop-filter'), '.card 不得再启用 backdrop-filter 磨砂');
  const authCardRule = login.match(/\.auth-card\s*\{[\s\S]*?\}/)?.[0] || '';
  assert.ok(!authCardRule.includes('backdrop-filter'), '.auth-card 不得再启用 backdrop-filter 磨砂');
  const wbRailRule = adminLayout.match(/\.wb-rail\s*\{[\s\S]*?\}/)?.[0] || '';
  assert.ok(!wbRailRule.includes('backdrop-filter'), '.wb-rail 不得再启用 backdrop-filter 磨砂');
});

test('兄弟品牌图标、双色字标与主题元信息保持一致', () => {
  const favicon = readFileSync(path.join(FRONTEND, 'public', 'favicon.svg'), 'utf8');
  const topBar = readFileSync(path.join(SRC, 'components', 'dashboard', 'TopBar.vue'), 'utf8');
  const adminLayout = readFileSync(path.join(SRC, 'layouts', 'AdminLayout.vue'), 'utf8');
  const indexHtml = readFileSync(path.join(FRONTEND, 'index.html'), 'utf8');
  const useTheme = readFileSync(path.join(SRC, 'composables', 'useTheme.ts'), 'utf8');

  assert.ok(favicon.includes('#0A0A0B') && favicon.includes('#27272A') && favicon.includes('#FF5E2B'));
  assert.ok(!favicon.includes('10b981') && !favicon.includes('34d399'));
  assert.ok(topBar.includes('Astra<span class="text-[var(--ds-color-brand)]">Quant</span>'));
  assert.ok(topBar.includes('OFFICIAL_REPO'), 'TopBar 需保留精简 GitHub 仓库入口');
  assert.ok(adminLayout.includes('Astra<span class="text-[var(--ds-color-brand)]">Quant</span>'));
  assert.ok(indexHtml.includes('<meta name="theme-color" content="#0a0a0b"'));
  assert.ok(useTheme.includes('colorScheme') && useTheme.includes('meta[name="theme-color"]'));
});

test('LandingView 与 landing 语言包已彻底移除，根路由 `/` 直达实盘矩阵', () => {
  assert.equal(existsSync(path.join(SRC, 'views', 'landing')), false, 'src/views/landing 必须删除');
  assert.equal(existsSync(path.join(SRC, 'locales', 'zh', 'landing.ts')), false, 'locales/zh/landing.ts 必须删除');
  assert.equal(existsSync(path.join(SRC, 'locales', 'en', 'landing.ts')), false, 'locales/en/landing.ts 必须删除');

  const router = readFileSync(path.join(SRC, 'router', 'index.ts'), 'utf8');
  assert.ok(!router.includes('LandingView'), 'router 不得再引用 LandingView');
  assert.match(router, /path:\s*'\/'[\s\S]*?DashboardLayout\.vue/);

  for (const file of collectSourceFiles(SRC)) {
    const content = readFileSync(file, 'utf8');
    assert.ok(!content.includes("t('landing."), `${path.relative(SRC, file)} 存在残留 landing.* 翻译键`);
  }
});
