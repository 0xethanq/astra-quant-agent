<script setup lang="ts">
/**
 * DocsView.vue · AstraQuant 系统文档与使用教程 (v9.2.0)
 * 包含：双轨工作台布局、左侧目录索引 (TOC) 与滚动高亮、图集放大预览灯箱，
 * 覆盖公开大屏、AI 助手控制台、5 标签策略配置、智能路由与分批止盈、安全隔离及部署排障。
 */
import { ref, onMounted, onUnmounted, onBeforeUnmount, watch } from 'vue';
import { useModalFocus } from '../../composables/useModalFocus';
import { useRouter } from 'vue-router';
import {
  ShieldCheck,
  Cpu,
  ArrowLeft,
  Terminal,
  Brain,
  TrendingUp,
  Layers,
  Lock,
  ChevronRight,
  Menu,
  X,
  Server,
  BookOpen,
  Github,
  Scale,
  SlidersHorizontal,
  ExternalLink,
} from 'lucide-vue-next';
import {
  APP_VERSION,
  APP_NAME,
  OFFICIAL_REPO,
  SKILLHUB_SITE,
  SKILLHUB_REPO,
} from '../../config/version';
import { useI18n } from '../../composables/useI18n';
import { trackEvent } from '../../utils/analytics';

const router = useRouter();
const { t } = useI18n();

const activeSection = ref('overview');
const mobileMenuOpen = ref(false);
const zoomImage = ref<string | null>(null);
const zoomPanel = ref<HTMLElement | null>(null);
const { sync: syncZoomFocus, release: releaseZoomFocus } = useModalFocus(
  zoomPanel,
  () => { zoomImage.value = null; },
);
watch(() => Boolean(zoomImage.value), syncZoomFocus);
onBeforeUnmount(releaseZoomFocus);

const sections = [
  { id: 'overview', title: '1. 系统架构与核心工作流', icon: TrendingUp },
  { id: 'dashboard', title: '2. 公开看板：实盘工作台与复盘审计', icon: Terminal },
  { id: 'agent_console', title: '3. 后台控制：AI 助手与 Diff 回滚', icon: Brain },
  { id: 'strategy_center', title: '4. 策略配置：32 项风控、智能路由与分批止盈', icon: SlidersHorizontal },
  { id: 'llm_council', title: '5. 模型连接与多席位决策协同', icon: Cpu },
  { id: 'security_okx', title: '6. OKX V5 接入与 DEMO/LIVE 安全隔离', icon: ShieldCheck },
  { id: 'notify_backup', title: '7. 通知网关、自动备份与恢复排障', icon: Layers },
  { id: 'deployment', title: '8. Docker 部署与常见配置问题', icon: Server },
  { id: 'license_rider', title: '9. 开源协议与条款说明', icon: Scale },
  { id: 'faq', title: '10. 常见问题与返佣说明 (FAQ)', icon: BookOpen },
];

function scrollToSection(id: string) {
  activeSection.value = id;
  mobileMenuOpen.value = false;
  const el = document.getElementById(id);
  if (el) {
    // base.css 的 prefers-reduced-motion 只能关掉 CSS 滚动，
    // 关不掉 JS 的 behavior:'smooth' —— 前庭敏感用户仍会被强制平滑滚动。
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false;
    el.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' });
  }
}

function onScroll() {
  const scrollPos = window.scrollY + 120;
  for (let i = sections.length - 1; i >= 0; i--) {
    const el = document.getElementById(sections[i].id);
    if (el && el.offsetTop <= scrollPos) {
      activeSection.value = sections[i].id;
      break;
    }
  }
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') {
    if (zoomImage.value) {
      zoomImage.value = null;
    } else if (mobileMenuOpen.value) {
      mobileMenuOpen.value = false;
    }
  }
}

watch(mobileMenuOpen, (menu) => {
  if (typeof document !== 'undefined') {
    if (menu) {
      document.body.style.overflow = 'hidden';
    } else if (!zoomImage.value) {
      document.body.style.overflow = '';
    }
  }
});

onMounted(() => {
  window.addEventListener('keydown', onKeydown);
  window.addEventListener('scroll', onScroll, { passive: true });
});

onUnmounted(() => {
  window.removeEventListener('scroll', onScroll);
  window.removeEventListener('keydown', onKeydown);
  if (typeof document !== 'undefined') {
    document.body.style.overflow = '';
  }
});
</script>

<template>
  <div class="min-h-screen font-sans selection:bg-[var(--ds-color-brand)] selection:text-white" style="background-color: var(--surface-0); color: var(--ink-1);">
    <!-- Top Header Navigation -->
    <header
      class="sticky top-0 z-[var(--z-header)] border-b px-3 sm:px-6 h-12 flex items-center justify-between"
      style="background-color: var(--surface-header); border-color: var(--line-1);"
    >
      <div class="flex items-center space-x-2 sm:space-x-3 min-w-0">
        <button type="button"
          @click="router.push('/')"
          class="btn btn-quiet h-7 px-2.5 text-xs font-medium cursor-pointer inline-flex items-center gap-1.5 rounded-md"
          :title="t('docs.backTerminal')"
        >
          <ArrowLeft class="w-3.5 h-3.5" />
          <span class="hidden sm:inline">{{ t('docs.backTerminalShort') }}</span>
        </button>
        <div class="h-4 w-px hidden sm:block shrink-0" style="background-color: var(--line-1);" />
        <div class="flex items-center space-x-2 min-w-0">
          <BookOpen class="h-4 w-4 text-[var(--ink-strong)] shrink-0" />
          <h1 class="font-bold text-xs sm:text-sm tracking-[-0.02em] shrink-0 whitespace-nowrap text-[var(--ink-strong)]">
            {{ APP_NAME }}
          </h1>
          <span class="font-mono text-3xs text-[var(--ink-3)]">
            {{ APP_VERSION }} 使用教程与系统文档
          </span>
        </div>
      </div>

      <div class="flex items-center space-x-2 shrink-0">
        <button type="button"
          @click="mobileMenuOpen = !mobileMenuOpen"
          class="sm:hidden btn btn-quiet btn-icon h-7 w-7 cursor-pointer rounded-md"
          :title="t('docs.tocBtn')"
          :aria-label="t('docs.tocBtn')"
          :aria-expanded="mobileMenuOpen"
          :aria-controls="'docs-mobile-drawer'"
        >
          <Menu v-if="!mobileMenuOpen" class="w-3.5 h-3.5" />
          <X v-else class="w-3.5 h-3.5" />
        </button>

        <button type="button"
          @click="router.push('/admin')"
          class="hidden sm:inline-flex btn btn-ghost h-7 px-3 text-xs font-medium cursor-pointer items-center gap-1.5 rounded-md border-[var(--line-1)] hover:border-[var(--line-2)]"
        >
          <Lock class="w-3.5 h-3.5 text-[var(--ink-2)]" />
          <span>控制台</span>
        </button>

        <a
          :href="OFFICIAL_REPO"
          target="_blank"
          rel="noopener noreferrer"
          class="btn btn-primary h-7 px-3 text-xs font-medium inline-flex items-center gap-1.5 rounded-md"
        >
          <Github class="w-3.5 h-3.5" aria-hidden="true" />
          <span class="hidden sm:inline">GitHub</span>
          <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
        </a>
      </div>
    </header>

    <!-- Mobile TOC Backdrop Overlay -->
    <div
      v-if="mobileMenuOpen"
      class="fixed inset-0 bg-black/60 z-40 sm:hidden"
      @click="mobileMenuOpen = false"
    />

    <!-- Main Container -->
    <div class="max-w-7xl mx-auto px-4 sm:px-6 py-6 sm:py-8 flex gap-8">
      <!-- Left Sticky Sidebar (TOC) -->
      <aside
        id="docs-mobile-drawer"
        class="w-64 shrink-0 fixed inset-y-12 left-0 z-50 sm:z-30 sm:bg-transparent p-4 sm:p-0 border-r sm:border-r-0 transition-transform duration-200 sm:translate-x-0 sm:sticky sm:top-16 sm:h-[calc(100vh-5rem)] overflow-y-auto"
        :class="mobileMenuOpen ? 'translate-x-0 bg-[var(--surface-1)]' : '-translate-x-full sm:translate-x-0 invisible sm:visible'"
        style="border-color: var(--line-1);"
      >
        <div class="flex items-center justify-between mb-3 px-2">
          <div class="text-3xs font-bold uppercase tracking-wider text-[var(--ink-3)]">
            {{ t('docs.tocBtn') }} (TOC)
          </div>
          <button type="button"
            @click="mobileMenuOpen = false"
            class="sm:hidden btn btn-quiet btn-icon h-6 w-6"
            :title="t('docs.closeToc')"
            :aria-label="t('docs.closeToc')"
          >
            <X class="w-3.5 h-3.5" />
          </button>
        </div>
        <nav class="space-y-1">
          <button type="button"
            v-for="s in sections"
            :key="s.id"
            @click="scrollToSection(s.id)"
            :aria-current="activeSection === s.id ? 'location' : undefined"
            class="w-full text-left px-3 py-2 rounded-md text-xs font-medium transition-all flex items-center justify-between group cursor-pointer border"
            :style="activeSection === s.id
              ? { backgroundColor: 'var(--surface-2)', color: 'var(--ink-strong)', borderColor: 'var(--line-2)', fontWeight: 'bold' }
              : { backgroundColor: 'transparent', borderColor: 'transparent', color: 'var(--ink-2)' }"
          >
            <div class="flex items-center space-x-2.5 truncate" :title="s.title">
              <component :is="s.icon" class="w-3.5 h-3.5 shrink-0 transition-colors" :class="activeSection === s.id ? 'text-[var(--ink-strong)]' : 'opacity-70 group-hover:opacity-100'" />
              <span class="truncate">{{ s.title }}</span>
            </div>
            <ChevronRight class="w-3 h-3 transition-opacity" :class="activeSection === s.id ? 'opacity-100 text-[var(--ink-strong)]' : 'opacity-0 group-hover:opacity-100'" />
          </button>
        </nav>

        <div class="dsh-card-sub mt-6 p-3.5 text-xs space-y-2">
          <div class="text-3xs uppercase font-bold text-[var(--ink-3)]">OKX AI 量化开源方案</div>
          <div class="font-bold flex items-center justify-between text-[var(--ink-1)]">
            <span>{{ APP_NAME }}</span>
            <span class="font-mono font-bold text-3xs text-[var(--ink-2)]">{{ APP_VERSION }}</span>
          </div>
          <p class="text-3xs text-[var(--ink-3)] leading-body">
            遵循 GNU AGPL-3.0 + Commons Clause v1.0 + Anti-Scam 附加条款开源发布，支持自托管运行与全链路审计。
          </p>
        </div>
      </aside>

      <!-- Right Content Area -->
      <main class="min-w-0 flex-1 space-y-12 pb-24">
        <!-- 1. 系统架构与核心工作流 -->
        <section id="overview" class="space-y-4 pt-2 scroll-mt-14">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 01</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">系统架构与核心工作流</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body font-sans text-[var(--ink-2)]">
            <strong>AstraQuant</strong> 是一套私有化部署的 <strong>OKX USDT 永续合约 AI 量化决策与执行系统</strong>。系统以 Python 直接签发 OKX V5 接口请求、基于北京时间（UTC+8）自然日统计账本绩效，将多周期因子计算、大模型交易研判与 32 项硬风控拦截拆解为独立可验证的阶段。
          </p>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
            <div class="dsh-card-sub p-4 space-y-2">
              <div class="flex items-center space-x-2 text-xs font-bold text-[var(--up)]">
                <TrendingUp class="w-4 h-4" />
                <span>7 梯队微结构因子输入</span>
              </div>
              <p class="text-3xs text-[var(--ink-2)] leading-body">
                <code>market_radar.py</code> 按 15m/1H/4H 维度聚合均线结构、VWAP 价值区偏离、CVD 背离、资金费率与盘口失衡深度，以结构化上下文交付给模型，不依赖模型盲看裸价。
              </p>
            </div>
            <div class="dsh-card-sub p-4 space-y-2">
              <div class="flex items-center space-x-2 text-xs font-bold text-[var(--ds-color-brand)]">
                <Brain class="w-4 h-4" />
                <span>单模型主脑 / 多席位协同</span>
              </div>
              <p class="text-3xs text-[var(--ink-2)] leading-body">
                默认使用低延迟主模型每 15 分钟推演决策，亦可在策略配置中一键启用模型委员会（宏观、技术、风控、CIO 终审）完成多视角交叉研判。
              </p>
            </div>
            <div class="dsh-card-sub p-4 space-y-2">
              <div class="flex items-center space-x-2 text-xs font-bold text-[var(--ink-strong)]">
                <ShieldCheck class="w-4 h-4" />
                <span>32 项物理风控与分批止盈</span>
              </div>
              <p class="text-3xs text-[var(--ink-2)] leading-body">
                单笔 1R 预算、最小盈亏比、杠杆上下限、日亏熔断与 DEMO/LIVE 开关全部在 Python 执行层刚性校验；开启 Scale-Out 后可自动分批落袋 TP1 并将止损推至保本。
              </p>
            </div>
            <div class="dsh-card-sub p-4 space-y-2">
              <div class="flex items-center space-x-2 text-xs font-bold text-[var(--ink-strong)]">
                <SlidersHorizontal class="w-4 h-4" />
                <span>对话式 AI 助手控制台</span>
              </div>
              <p class="text-3xs text-[var(--ink-2)] leading-body">
                在 <code>/admin/agent</code> 通过自然语言即可查询持仓、开单漏斗拦截与历史胜率，生成的参数调整统一展示 Diff 审批卡，应用前自动归档快照支持一键回滚。
              </p>
            </div>
          </div>

          <div class="dsh-card p-3 space-y-2">
            <button type="button"
              @click="zoomImage = '/images/v920_dashboard.png'"
              class="block w-full text-left cursor-zoom-in group"
              :title="t('docs.zoomHint')"
            >
              <img
                src="/images/v920_dashboard.png"
                alt="AstraQuant v9.2 实盘看板主界面"
                class="w-full rounded-md border border-[var(--line-1)]"
              />
            </button>
            <div class="flex items-center justify-between text-3xs text-[var(--ink-3)] px-1">
              <span>图 1：AstraQuant 实盘看板（K 线标线、TP1/TP2 分批止盈、活动持仓与最新决策）</span>
              <span class="font-mono">{{ t('docs.zoomHint') }}</span>
            </div>
          </div>
        </section>

        <!-- 2. 公开看板：实盘工作台与复盘审计 -->
        <section id="dashboard" class="space-y-4 scroll-mt-14">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 02</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">公开看板：实盘工作台与复盘审计</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body text-[var(--ink-2)]">
            公开前端（<code>/</code>、<code>/factors</code>、<code>/news</code>、<code>/lab</code>、<code>/history</code>）与 <code>/docs</code> 面向交易与复盘查阅，全部接口仅暴露脱敏行情与脱敏统计，无写操作入口：
          </p>

          <ul class="space-y-2 text-xs text-[var(--ink-2)] list-disc pl-5 leading-body">
            <li><strong>实盘看板 (<code>/</code>)</strong>：顶部展示账户总权益、当日已实现盈亏（按 UTC+8）、当前持仓浮盈、多空比、保证金占用与止损保护覆盖率；主图表实时标注进场均价、云端止损价 SL 与两段式分批止盈线 <code>TP1 / TP2</code>，点击右上「试算」可在本地预估单笔强平距离与期望盈亏。</li>
            <li><strong>AI 决策 (<code>/factors</code>)</strong>：按北京时间倒序记录最近推演周期的市场总结与币种信号；点击任意周期条目可在右侧打开<strong>决策详情抽屉</strong>，逐项核对原始提示词长度、市场分析、单币建议与委员会表决理由。</li>
            <li><strong>策略复盘 (<code>/lab</code>)</strong>：展示每批已平仓样本归因摘要（战绩归因、风控审查、节奏审计、动能分析）与当前生效的自进化经验规则。</li>
            <li><strong>交易台账 (<code>/history</code>) 与 市场快讯 (<code>/news</code>)</strong>：核对每笔成交的开平仓均价、手续费/资金费率净扣、持仓时长与出场归因（如 <code>AI 主动止盈</code>、<code>超时保本</code>、<code>TP1 触发</code>），支持导出 CSV 与查看 OKX 多空比分布及宏观快讯。</li>
          </ul>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1">
            <div class="dsh-card p-3 space-y-2">
              <button type="button"
                @click="zoomImage = '/images/v920_decisions.png'"
                class="block w-full text-left cursor-zoom-in"
                :title="t('docs.zoomHint')"
              >
                <img
                  src="/images/v920_decisions.png"
                  alt="AI 决策推演时序流界面"
                  class="w-full rounded-md border border-[var(--line-1)]"
                />
              </button>
              <div class="text-3xs text-[var(--ink-3)]">图 2：AI 决策时序流（/factors）— 按周期追踪建仓、移损与观望信号</div>
            </div>
            <div class="dsh-card p-3 space-y-2">
              <button type="button"
                @click="zoomImage = '/images/v920_cot_drawer.png'"
                class="block w-full text-left cursor-zoom-in"
                :title="t('docs.zoomHint')"
              >
                <img
                  src="/images/v920_cot_drawer.png"
                  alt="决策详情与思维链抽屉"
                  class="w-full rounded-md border border-[var(--line-1)]"
                />
              </button>
              <div class="text-3xs text-[var(--ink-3)]">图 3：点击决策行打开详情抽屉 — 查看完整分析上下文与模型输出</div>
            </div>
            <div class="dsh-card p-3 space-y-2">
              <button type="button"
                @click="zoomImage = '/images/v920_review.png'"
                class="block w-full text-left cursor-zoom-in"
                :title="t('docs.zoomHint')"
              >
                <img
                  src="/images/v920_review.png"
                  alt="策略复盘与经验规则页"
                  class="w-full rounded-md border border-[var(--line-1)]"
                />
              </button>
              <div class="text-3xs text-[var(--ink-3)]">图 4：策略复盘页（/lab）— 自动归因统计与自进化规则沉淀</div>
            </div>
            <div class="dsh-card p-3 space-y-2">
              <button type="button"
                @click="zoomImage = '/images/v920_ledger.png'"
                class="block w-full text-left cursor-zoom-in"
                :title="t('docs.zoomHint')"
              >
                <img
                  src="/images/v920_ledger.png"
                  alt="全量平仓交易台账页"
                  class="w-full rounded-md border border-[var(--line-1)]"
                />
              </button>
              <div class="text-3xs text-[var(--ink-3)]">图 5：交易台账页（/history）— 净盈亏、手续费、资金费率与 CSV 导出</div>
            </div>
          </div>
        </section>

        <!-- 3. 后台控制：AI 助手与 Diff 回滚 -->
        <section id="agent_console" class="space-y-4 scroll-mt-14">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 03</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">后台控制：AI 助手与 Diff 回滚</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body text-[var(--ink-2)]">
            登录后默认进入 <strong>AI 助手</strong>（<code>/admin/agent</code>），右侧挂载实时「策略状态」面板（总览、风控、提示词、委员会、快照）。你无需手动对照多个文件，即可在对话中完成排障与安全调参：
          </p>

          <div class="grid grid-cols-1 md:grid-cols-3 gap-3">
            <div class="dsh-card-sub p-4 space-y-1.5">
              <div class="text-xs font-bold text-[var(--ink-strong)]">1. 只读深度体检</div>
              <p class="text-3xs text-[var(--ink-2)] leading-body">
                Agent 可自动调用只读工具统计近 48 周期开单漏斗（为何某币被观望或风控拒单）、费率磨损、模型耗时以及风控冲突。
              </p>
            </div>
            <div class="dsh-card-sub p-4 space-y-1.5">
              <div class="text-xs font-bold text-[var(--ink-strong)]">2. Diff 变更提案审批</div>
              <p class="text-3xs text-[var(--ink-2)] leading-body">
                所有写操作不直接静默落盘，而是输出结构化键值 Diff 提案卡片，明确标出改动前后值与风险提示，由管理员审阅确认。
              </p>
            </div>
            <div class="dsh-card-sub p-4 space-y-1.5">
              <div class="text-xs font-bold text-[var(--ink-strong)]">3. 前置快照与一键回滚</div>
              <p class="text-3xs text-[var(--ink-2)] leading-body">
                确认应用前系统自动保存策略包哈希快照；如调参后发现实盘节奏不如预期，点击卡片左下角「回滚」按钮或切至「快照」栏即可恢复原状。
              </p>
            </div>
          </div>

          <div class="dsh-card-sub p-4 space-y-2 border-l-4 border-[var(--ds-color-brand)]">
            <div class="text-xs font-bold text-[var(--ink-strong)]">Agent 安全边界（硬编码拒绝越权）</div>
            <p class="text-3xs text-[var(--ink-2)] leading-body">
              Agent 仅允许管理策略风控、标的池、交易时段、提示词与委员会参数；系统层<strong>严格禁止</strong> Agent 读取/导出交易所或模型 API 密钥、切换 DEMO/LIVE 账户环境、主动替你手工开平仓，或变更管理员账号口令。
            </p>
          </div>

          <div class="dsh-card p-3 space-y-2">
            <button type="button"
              @click="zoomImage = '/images/v920_admin_agent.png'"
              class="block w-full text-left cursor-zoom-in"
              :title="t('docs.zoomHint')"
            >
              <img
                src="/images/v920_admin_agent.png"
                alt="AI 助手控制台与原子变更 Diff 提案卡片"
                class="w-full rounded-md border border-[var(--line-1)]"
              />
            </button>
            <div class="flex items-center justify-between text-3xs text-[var(--ink-3)] px-1">
              <span>图 6：AI 助手控制台（/admin/agent）— 工具调用诊断、结构化配置 Diff 卡片、一键回滚与右侧策略状态栏</span>
              <span class="font-mono">{{ t('docs.zoomHint') }}</span>
            </div>
          </div>
        </section>

        <!-- 4. 策略配置：32 项风控、智能路由与分批止盈 -->
        <section id="strategy_center" class="space-y-4 scroll-mt-14">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 04</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">策略配置：32 项风控、智能路由与分批止盈</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body text-[var(--ink-2)]">
            <strong>策略配置页</strong>（<code>/admin/strategy</code>）将以往分散的运维面板整合为 5 个标签页，右上角常驻全局<strong>开仓开关</strong>（开启暂停后拦截所有新开仓，已持仓止损/止盈继续守护）：
          </p>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div class="dsh-card-sub p-4 space-y-2">
              <div class="text-xs font-bold text-[var(--ink-strong)]">委托路由模式 (Order Mode)</div>
              <ul class="text-3xs text-[var(--ink-2)] space-y-1 list-disc pl-4 leading-body">
                <li><strong>限价挂单 (<code>limit</code>)</strong>：以挂单为主降低滑点，超时未成交则自动撤单放弃本轮机会。</li>
                <li><strong>市价成交 (<code>market</code>)</strong>：立即按盘口最优价格吃单进场，确保信号不踏空，手续费略高。</li>
                <li><strong>智能混合 (<code>smart</code>)</strong>：先发送 Post-Only 只挂单限价博取 Maker 低费率，等待超时后对未成交余额用 IOC 补齐（推荐配合 <code>0.15</code> 分钟轮询使用）。</li>
              </ul>
            </div>
            <div class="dsh-card-sub p-4 space-y-2">
              <div class="text-xs font-bold text-[var(--ink-strong)]">两段式分批止盈 (Scale-Out TP1/TP2)</div>
              <ul class="text-3xs text-[var(--ink-2)] space-y-1 list-disc pl-4 leading-body">
                <li>建仓成交后在 OKX 云端自动维护保护单，当价格触发第一目标位 <strong>TP1</strong> 时自动落袋设定比例（默认 <code>35%~50%</code>）。</li>
                <li>TP1 成交或达到保本 ATR 阈值后，追踪程序自动把剩余仓位的云端止损线移至<strong>开仓均价保本位</strong>，再由 <strong>TP2 / 追踪止盈</strong>吃下后续波段。</li>
              </ul>
            </div>
          </div>

          <div class="dsh-card-sub p-4 space-y-2">
            <div class="text-xs font-bold text-[var(--ink-strong)]">三大风控预设套件与物理底线</div>
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-2 pt-1 text-3xs text-[var(--ink-2)]">
              <div class="p-3 rounded border border-[var(--line-1)] bg-[var(--surface-0)] space-y-1">
                <div class="font-bold text-[var(--ink-strong)]">保守 (conservative)</div>
                <p>2x~3x 杠杆，单笔保证金 ≤ 10%，最小盈亏比 ≥ 2.2:1，日亏 3% 触发熔断，禁用顺势加仓。</p>
              </div>
              <div class="p-3 rounded border border-[var(--ds-color-brand)] bg-[var(--surface-0)] space-y-1">
                <div class="font-bold text-[var(--ds-color-brand)]">平衡 (balanced · 出厂推荐)</div>
                <p>2x~5x 杠杆，单笔 1R 2%，仓位上限 20%，2.0:1~3.5:1 R:R，日亏 5% 熔断，默认启用 TP1 分批锁利。</p>
              </div>
              <div class="p-3 rounded border border-[var(--line-1)] bg-[var(--surface-0)] space-y-1">
                <div class="font-bold text-[var(--ink-strong)]">激进 (aggressive)</div>
                <p>最高 6x~9.9x 杠杆，单笔 1R 4.5%，允许顺势金字塔加仓，10% 日亏熔断，适合波动扩张行情。</p>
              </div>
            </div>
          </div>

          <div class="dsh-card p-3 space-y-2">
            <button type="button"
              @click="zoomImage = '/images/v920_admin_strategy.png'"
              class="block w-full text-left cursor-zoom-in"
              :title="t('docs.zoomHint')"
            >
              <img
                src="/images/v920_admin_strategy.png"
                alt="策略配置 5 标签控制面"
                class="w-full rounded-md border border-[var(--line-1)]"
              />
            </button>
            <div class="flex items-center justify-between text-3xs text-[var(--ink-3)] px-1">
              <span>图 7：策略配置（/admin/strategy）— 预设风险套件、smart 智能路由、分批止盈开关与无冲突校验</span>
              <span class="font-mono">{{ t('docs.zoomHint') }}</span>
            </div>
          </div>
        </section>

        <!-- 5. 模型连接与多席位决策协同 -->
        <section id="llm_council" class="space-y-4 scroll-mt-14">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 05</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">模型连接与多席位决策协同</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body text-[var(--ink-2)]">
            模型接口统一在 <strong>模型连接</strong>（<code>/admin/llm</code>）管理，支持 OpenAI、Anthropic 及兼容 OpenAI Chat/Responses 协议的第三方或本地网关：
          </p>

          <ul class="space-y-2 text-xs text-[var(--ink-2)] list-disc pl-5 leading-body">
            <li><strong>自动拉取与连通自检</strong>：填写 Base URL 与 API Key 后可一键拉取远端模型列表并发送测试请求，核验延迟、推理力度（<code>reasoning_effort</code>）及结构化 JSON 返回能力。</li>
            <li><strong>多模型降级容灾 (Failover)</strong>：可指定 1~3 个备用模型；主模型连续超时或限流时，决策脚本按顺序切换备用链路，仍全败时触发 Fail-Closed 跳过当轮开仓。</li>
            <li><strong>单模型 vs 模型委员会 (Council)</strong>：若希望追求 15 秒内极速出单并节省 Token，可在 <code>/admin/strategy?tab=council</code> 关闭多席位，由单一主模型直接依据完整系统提示词出单；需要多维度校验时再开启宏观 / 技术 / 风控 / CIO 席位。</li>
            <li><strong>提示词模块化组装</strong>：系统提示词拆分为安全基线与可插拔策略模块（核心边界模块处于锁定状态不可关闭），支持保存多套命名档案随时切换。</li>
          </ul>
        </section>

        <!-- 6. OKX V5 接入与 DEMO/LIVE 安全隔离 -->
        <section id="security_okx" class="space-y-4 scroll-mt-14">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 06</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">OKX V5 接入与 DEMO / LIVE 安全隔离</h2>
          </div>

          <div class="dsh-card-sub p-4 space-y-2">
            <div class="text-xs font-bold text-[var(--ink-strong)]">推荐上线验证流程（模拟盘优先）</div>
            <ol class="text-3xs text-[var(--ink-2)] list-decimal pl-4 space-y-1.5 leading-body">
              <li>在 OKX 网页端切换至「模拟交易」，创建一组独立 Demo API Key（权限仅勾选<strong>读取 + 交易</strong>，切勿开启提币）。</li>
              <li>登录 AstraQuant <code>/admin/security</code>（<strong>账户与应急</strong>），在环境区选择 <code>DEMO（模拟盘）</code>，填入 API Key / Secret Key / Passphrase 并点击「测试连接」验证余额与持仓读取成功。</li>
              <li>至少完整运行 24~48 小时，结合 <code>/admin/agent</code> 与 <code>/lab</code> 检查止损云端挂单、TP1 分批止盈及手续费净额后再考虑小资金切换 <code>LIVE</code> 实盘。</li>
            </ol>
          </div>

          <div class="dsh-card-sub p-4 space-y-1.5">
            <div class="text-xs font-bold text-[var(--ink-strong)]">密钥加密与静态边界</div>
            <p class="text-3xs text-[var(--ink-2)] leading-body">
              API 密钥与通道凭证保存在受权限掩码（<code>0600</code>）保护的持久化目录中，前端接口与系统日志均只返回脱敏后缀。所有管理员操作写入独立审计日志，可在 <strong>系统日志</strong>（<code>/admin/decisions</code>）按时间溯源。
            </p>
          </div>
        </section>

        <!-- 7. 通知网关、自动备份与恢复排障 -->
        <section id="notify_backup" class="space-y-4 scroll-mt-14">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 07</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">通知网关、自动备份与恢复排障</h2>
          </div>

          <ul class="space-y-2 text-xs text-[var(--ink-2)] list-disc pl-5 leading-body">
            <li><strong>多通道通知 (<code>/admin/notify</code>)</strong>：支持 Telegram Bot、QQ 网关、企业微信 / 飞书 / 钉钉 Webhook 与 SMTP 邮件；开平仓成交通知、日亏熔断与异常告警分事件独立开关，并自带测试发送按钮。</li>
            <li><strong>加密异地备份 (<code>/admin/backup</code>)</strong>：支持将台账数据库、策略快照与配置目录打包为 AES-256-GCM 加密归档，定时推送至 WebDAV / S3 / Telegram / 邮箱，支持在控制面直接校验口令并执行一键恢复。</li>
            <li><strong>系统管理与更新 (<code>/admin/backup?tab=adminsys</code> / <code>about</code>)</strong>：可添加只读观察员子账号（不可改动风控与开仓开关）、一键安全退出所有管理员会话，以及查看当前版本与仓库更新状态。</li>
          </ul>
        </section>

        <!-- 8. Docker 部署与常见配置问题 -->
        <section id="deployment" class="space-y-4 scroll-mt-14">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 08</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">Docker 部署与常见配置问题</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body text-[var(--ink-2)]">
            生产环境建议使用官方 <code>docker-compose.yml</code> 启动（Node 26 构建静态资源，Python 3.14 运行控制面与交易调度器，外网建议前置 Nginx / Caddy HTTPS 反代）：
          </p>

          <pre tabindex="0" class="p-4 rounded-lg text-3xs font-mono leading-relaxed overflow-x-auto border bg-[var(--surface-1)] border-[var(--line-1)] text-[var(--ink-1)]"><code>git clone https://github.com/0xethanq/astra-quant-agent.git
cd astra-quant-agent
cp backend/env.example backend/.env &amp;&amp; chmod 600 backend/.env
docker compose up -d --build
curl -sS http://127.0.0.1:8080/api/v1/health</code></pre>

          <div class="dsh-card-sub p-4 space-y-2">
            <div class="text-xs font-bold text-[var(--ink-strong)]">部署后快速自检项</div>
            <ul class="text-3xs text-[var(--ink-2)] space-y-1 list-disc pl-4 leading-body">
              <li>确认宿主机上 <code>backend/.env</code> 是<strong>文件</strong>而不是目录；若初次直接 <code>docker compose up</code> 导致生成了同名目录，启动脚本会自动报错拦截，按提示删目录并复制 <code>env.example</code> 后重建即可。</li>
              <li>确认服务器系统时钟已开启 NTP 对时（与 OKX 服务器时间差超过 30s 会触发签名拒收）。</li>
              <li>若使用 Cloudflare / CDN 反代大屏，注意对 <code>/api/*</code> 禁用静态缓存以确保实时权益与持仓毫秒级刷新。</li>
            </ul>
          </div>
        </section>

        <!-- 9. 开源协议与条款说明 -->
        <section id="license_rider" class="space-y-4 scroll-mt-14">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 09</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">开源协议与条款说明</h2>
          </div>

          <div class="dsh-card-sub p-4 space-y-2 text-xs text-[var(--ink-2)] leading-body">
            <p>
              <strong>GNU AGPL-3.0 + Commons Clause v1.0 + Anti-Scam 附加条款</strong>：个人研究、内部自部署及透明代码审计完全免费；未经书面授权不得将本系统打包为商业 SaaS 订阅服务对外售卖，亦严禁利用本系统或衍生界面进行虚假喊单与资金盘欺诈。完整原文见仓库根目录 <code>LICENSE</code> 文件。
            </p>
          </div>
        </section>

        <!-- 10. 常见问题与返佣说明 (FAQ) -->
        <section id="faq" class="space-y-4 scroll-mt-14">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 10</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">常见问题与返佣说明 (FAQ)</h2>
          </div>

          <div class="space-y-3 text-xs">
            <div class="dsh-card-sub p-3 space-y-1">
              <h3 class="font-bold text-[var(--ink-strong)]">Q: 模拟盘 (DEMO) 与实盘 (LIVE) 数据会混用吗？</h3>
              <p class="text-[var(--ink-2)] leading-body">
                A: 不会。两套环境的密钥、开闸标志与前端环境徽章完全隔离。切换环境时控制面会按所选环境单独鉴权拉取余额与持仓。
              </p>
            </div>
            <div class="dsh-card-sub p-3 space-y-1">
              <h3 class="font-bold text-[var(--ink-strong)]">Q: AI 助手或模型请求临时失败时，当前持仓还受保护吗？</h3>
              <p class="text-[var(--ink-2)] leading-body">
                A: 会。每一笔开仓的止损/止盈单均挂在 OKX 云端条件单上，同时本地追踪循环与日亏熔断独立于 LLM 接口运行；LLM 全链不可用时自动保持 Fail-Closed，仅跳过新开仓。
              </p>
            </div>
            <div class="dsh-card-sub p-3 space-y-1">
              <h3 class="font-bold text-[var(--ink-strong)]">Q: 如何配合 TradeSkill（Claude Code / Cursor 技能库）与 OKX 20% 手续费返佣？</h3>
              <p class="text-[var(--ink-2)] leading-body">
                A: 若你想在日常使用 Claude Code、Cursor 或 Codex 对话看盘与手动调单，可访问姊妹开源项目 <strong>TradeSkill (tradeskill.si)</strong> 获取 16 家交易所/DEX 的官方 Skill；同时可在返佣专区绑定 OKX 官方 <strong>20% 永久返佣</strong> 渠道，配合 AstraQuant 的 <code>smart</code> Post-Only 路由显著降低自动交易长期手续费损耗。
              </p>
              <div class="flex flex-wrap items-center gap-2 pt-1">
                <a
                  :href="SKILLHUB_SITE"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="btn btn-primary btn-sm inline-flex items-center gap-1.5"
                  @click="trackEvent('crosslink_click', { target: 'skillhub', placement: 'docs_faq' })"
                >
                  <Cpu class="w-3.5 h-3.5" aria-hidden="true" />
                  <span>TradeSkill 技能中心</span>
                  <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
                  <ExternalLink class="w-3.5 h-3.5" aria-hidden="true" />
                </a>
                <a
                  :href="SKILLHUB_REPO"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="btn btn-quiet btn-sm inline-flex items-center gap-1.5"
                  @click="trackEvent('crosslink_click', { target: 'crypto_trading_skills_repo', placement: 'docs_faq' })"
                >
                  <Github class="w-3.5 h-3.5" aria-hidden="true" />
                  <span>crypto-trading-skills</span>
                  <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
                  <ExternalLink class="w-3.5 h-3.5" aria-hidden="true" />
                </a>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>

    <!-- Zoom Image Modal -->
    <div
      v-if="zoomImage"
      ref="zoomPanel"
      role="dialog"
      aria-modal="true"
      :aria-label="t('docs.zoomModalAria')"
      tabindex="-1"
      class="fixed inset-0 z-[var(--z-dialog)] flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm cursor-zoom-out outline-none"
      @click="zoomImage = null"
    >
      <img
        :src="zoomImage"
        alt="放大的文档插图"
        class="max-w-full max-h-[90vh] rounded-lg shadow-2xl cursor-default"
        @click.stop
      />
      <button
        type="button"
        class="absolute top-4 right-4 btn btn-quiet btn-icon text-white hover:bg-white/20"
        :title="`${t('common.close')} (Esc)`"
        :aria-label="t('common.close')"
        @click="zoomImage = null"
      >
        <X class="w-5 h-5" />
      </button>
    </div>
  </div>
</template>
