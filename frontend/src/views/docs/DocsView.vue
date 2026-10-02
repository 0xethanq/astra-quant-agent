<script setup lang="ts">
/**
 * DocsView.vue · AstraQuant 技术与量化策略文档中心 (v8.5.1)
 * 包含：双轨工作台骨架、目录大纲索引树 (TOC) 与平滑滚动侦测、全功能架构透视、
 * 7 梯队因子与硬防线技术规范、Prompt Caching 提示词缓存体系、AGPL-3.0 + Commons Clause 许可说明
 */
import { ref, onMounted, onUnmounted, onBeforeUnmount, watch } from 'vue';
import { useModalFocus } from '../../composables/useModalFocus';
import { useRouter } from 'vue-router';
import {
  ShieldCheck,
  Cpu,
  FileText,
  ArrowLeft,
  Terminal,
  Users,
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
  Zap,
} from 'lucide-vue-next';
import { APP_VERSION, APP_NAME, OFFICIAL_REPO } from '../../config/version';
import { useI18n } from '../../composables/useI18n';

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
  { id: 'overview', title: '1. 系统架构与量化哲学', icon: TrendingUp },
  { id: 'dashboard', title: '2. 量化工作台与资产控制舱', icon: Terminal },
  { id: 'council', title: '3. 对冲基金投委会 (Trading Desk)', icon: Users },
  { id: 'policy_snapshot', title: '4. 策略版本快照控制台 (Policy Snapshot)', icon: Layers },
  { id: 'prompt_studio', title: '5. 提示词策略与语义变量插槽', icon: FileText },
  { id: 'execution_gate', title: '6. 大模型全权直通与执行层物理校验', icon: ShieldCheck },
  { id: 'risk_control', title: '7. 执行层风控与分批止盈双腿', icon: Lock },
  { id: 'llm_caching', title: '8. 模型连接、协议与 Prompt Caching', icon: Cpu },
  { id: 'self_evolution', title: '9. 自进化认知与长期记忆闭环', icon: Brain },
  { id: 'deployment', title: '10. 极速开箱部署与多通道通知', icon: Server },
  { id: 'license_rider', title: '11. 开源协议与反割韭菜特约附则', icon: Scale },
  { id: 'faq', title: '12. 常见问题解答与风控底线 (FAQ)', icon: BookOpen },
];

function scrollToSection(id: string) {
  activeSection.value = id;
  mobileMenuOpen.value = false;
  const el = document.getElementById(id);
  if (el) {
    // 批 68：base.css 的 prefers-reduced-motion 只能关掉 CSS 滚动，
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
  <div class="min-h-screen font-sans selection:bg-emerald-500 selection:text-black" style="background-color: var(--surface-0); color: var(--ink-1);">
    <!-- Top Header Navigation -->
    <header
      class="sticky top-0 z-[var(--z-header)] border-b px-3 sm:px-6 h-12 flex items-center justify-between backdrop-blur-xl"
      style="background-color: var(--surface-header); border-color: var(--line-1);"
    >
      <div class="flex items-center space-x-2 sm:space-x-3 min-w-0">
        <button type="button"
          @click="router.push('/')"
          class="btn btn-quiet h-7 px-2.5 text-xs font-medium cursor-pointer inline-flex items-center gap-1.5 rounded-lg"
          :title="t('docs.backTerminal')"
        >
          <ArrowLeft class="w-3.5 h-3.5" />
          <span class="hidden sm:inline">{{ t('docs.backTerminalShort') }}</span>
        </button>
        <div class="h-4 w-px hidden sm:block shrink-0" style="background-color: var(--line-1);" />
        <div class="flex items-center space-x-2 min-w-0">
          <BookOpen class="h-4 w-4 text-emerald-400 shrink-0" />
          <h1 class="font-bold text-xs sm:text-sm tracking-wide shrink-0 whitespace-nowrap text-[var(--ink-strong)] font-mono">
            {{ APP_NAME }}
          </h1>
          <span
            class="dsh-pill font-mono text-3xs border border-white/10 bg-zinc-900/60 text-zinc-400"
          >
            {{ APP_VERSION }} 官方技术文档
          </span>
        </div>
      </div>

      <div class="flex items-center space-x-2 shrink-0">
        <button type="button"
          @click="mobileMenuOpen = !mobileMenuOpen"
          class="sm:hidden btn btn-quiet btn-icon h-7 w-7 cursor-pointer rounded-lg"
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
          class="hidden sm:inline-flex btn btn-ghost h-7 px-3 text-xs font-medium cursor-pointer items-center gap-1.5 rounded-lg border-white/10 hover:border-emerald-500/30"
        >
          <Lock class="w-3.5 h-3.5 text-emerald-400" />
          <span>控制台</span>
        </button>

        <a
          :href="OFFICIAL_REPO"
          target="_blank"
          rel="noopener noreferrer"
          class="btn btn-primary h-7 px-3 text-xs font-medium inline-flex items-center gap-1.5 rounded-lg"
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
      class="fixed inset-0 bg-black/60 backdrop-blur-xs z-40 sm:hidden"
      @click="mobileMenuOpen = false"
    />

    <!-- Main Container -->
    <div class="max-w-7xl mx-auto px-4 sm:px-6 py-6 sm:py-8 flex gap-8">
      <!-- Left Sticky Sidebar (TOC) -->
      <aside
        id="docs-mobile-drawer"
        class="w-64 shrink-0 fixed inset-y-12 left-0 z-50 sm:z-30 sm:bg-transparent p-4 sm:p-0 border-r sm:border-r-0 transition-transform duration-200 sm:translate-x-0 sm:sticky sm:top-16 sm:h-[calc(100vh-5rem)] overflow-y-auto"
        :class="mobileMenuOpen ? 'translate-x-0 bg-[var(--surface-1)] shadow-2xl' : '-translate-x-full sm:translate-x-0 invisible sm:visible'"
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
            class="w-full text-left px-3 py-2 rounded-lg text-xs font-medium transition-all flex items-center justify-between group cursor-pointer border"
            :style="activeSection === s.id
              ? { backgroundColor: 'var(--surface-3)', color: 'var(--ink-strong)', borderColor: 'rgba(16, 185, 129, 0.3)', fontWeight: 'bold' }
              : { backgroundColor: 'transparent', borderColor: 'transparent', color: 'var(--ink-2)' }"
          >
            <div class="flex items-center space-x-2.5 truncate" :title="s.title">
              <component :is="s.icon" class="w-3.5 h-3.5 shrink-0 transition-colors" :class="activeSection === s.id ? 'text-emerald-400' : 'opacity-70 group-hover:opacity-100'" />
              <span class="truncate">{{ s.title }}</span>
            </div>
            <ChevronRight class="w-3 h-3 transition-opacity" :class="activeSection === s.id ? 'opacity-100 text-emerald-400' : 'opacity-0 group-hover:opacity-100'" />
          </button>
        </nav>

        <div class="dsh-card-sub mt-6 p-3.5 text-xs space-y-2">
          <div class="text-3xs uppercase font-bold text-[var(--ink-3)]">开源技术社区与极客讨论</div>
          <div class="font-bold flex items-center justify-between text-[var(--ink-1)]">
            <span>LINUX DO 社区</span>
            <span class="dsh-pill font-mono font-bold text-3xs text-emerald-400">linux.do</span>
          </div>
          <p class="text-3xs text-[var(--ink-3)] leading-body">
            遵循 GNU AGPL-3.0 + Commons Clause v1.0 + Anti-Scam 特约附则，打造透明可信的量化基础设施。
          </p>
        </div>
      </aside>

      <!-- Right Content Area -->
      <main class="min-w-0 flex-1 space-y-12 pb-24">
        <!-- 1. 系统概览与量化哲学 -->
        <section id="overview" class="space-y-4 pt-2 scroll-mt-14">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 01</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">系统架构与量化哲学</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body font-sans text-[var(--ink-2)]">
            <strong>AstraQuant</strong> 是一套专为高波动加密货币（Crypto）设计的<strong>OKX 原生全自动波段量化决策与执行操作系统</strong>。系统通过 OKX V5 REST API 纯 Python 直签执行私有账户与交易请求，运行在严格的北京时间（UTC+8）自然日财务基准之上，聚焦 1H~4H 大级别顺势波段，践行<strong>“认知交给大模型，微结构交给7层微积分，底线交给确定性物理风控”</strong>的工程哲学。
          </p>

          <!-- 4 Core Pillars Grid -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-2">
            <div class="dsh-card-sub p-4 space-y-2">
              <div class="flex items-center space-x-2 text-xs font-bold text-[var(--up)]">
                <ShieldCheck class="w-4 h-4" />
                <span>Fail-Closed 物理硬防线</span>
              </div>
              <p class="text-xs text-[var(--ink-2)] leading-body">
                风控绝不寄托于大模型提示词自我约束。底座设立不可逾越的确定性 Python 物理风控管线：行情完整性、反向持仓防冲突、报价几何合法性、单日亏损熔断、杠杆上限与 100% 交易所云端双腿 OCO 挂单保护。
              </p>
            </div>

            <div class="dsh-card-sub p-4 space-y-2">
              <div class="flex items-center space-x-2 text-xs font-bold text-[var(--accent)]">
                <Users class="w-4 h-4" />
                <span>多模型决策委员会 (Council Pro)</span>
              </div>
              <p class="text-xs text-[var(--ink-2)] leading-body">
                调度宏观分析师、盘口微结构官、技术动量官等独立参谋席位并发质询，支持一票否决、加权共识与动能突破三种裁决机制，由首席终审仲裁官 (CIO) 收口输出严格机器可读契约。
              </p>
            </div>

            <div class="dsh-card-sub p-4 space-y-2">
              <div class="flex items-center space-x-2 text-xs font-bold text-[var(--ink-strong)]">
                <Zap class="w-4 h-4" />
                <span>Prompt Caching & 会话亲和体系</span>
              </div>
              <p class="text-xs text-[var(--ink-2)] leading-body">
                2026-10 升级：单前缀广播让共享市场事实占比超 90%，Zone 0~4 单调波动分级与 Claude/OpenAI/DeepSeek KV 缓存深度对齐，结合浮点防抖与 L1 查询缓存，延迟降低 70%+，成本大幅缩减。
              </p>
            </div>

            <div class="dsh-card-sub p-4 space-y-2">
              <div class="flex items-center space-x-2 text-xs font-bold text-[var(--warn)]">
                <Brain class="w-4 h-4" />
                <span>自进化认知复盘闭环</span>
              </div>
              <p class="text-xs text-[var(--ink-2)] leading-body">
                每日 4 次（02:00/08:00/14:00/20:00）全自动读取真实平仓台账流水进行归因反思与数学验证，更新 <code>structured_trading_memory.json</code> 实战心法，具备时效半衰期淘汰与防虚构机制。
              </p>
            </div>
          </div>
        </section>

        <!-- 2. 量化工作台与资产控制舱 -->
        <section id="dashboard" class="space-y-4 pt-6 border-t scroll-mt-14" style="border-color: var(--line-1);">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 02</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">量化工作台与资产控制舱</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body font-sans text-[var(--ink-2)]">
            前台终端运行在默认原生端口 <code>http://localhost:8080/trading</code>，采用机构级双轨工作台设计，首屏无赛博朋克光污染，采用半透明微晶磨砂玻璃与双倒角高精微光界面：
          </p>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1 text-xs">
            <div class="dsh-card-sub p-3.5 space-y-1.5">
              <div class="font-bold text-xs text-[var(--ink-strong)]">主工位操盘中心</div>
              <p class="text-[var(--ink-2)] leading-body">
                • <strong>6 单元资产 HUD</strong>：OKX 总权益、走势折线、今日已结、持仓浮盈、多空敞口与云端防线解耦呈现。<br>
                • <strong>资金费与手续费明细透传</strong>：实时汇总跨周期永续合约资金费与手续费，彻底消除浮盈与净盈亏之间的认知差。<br>
                • <strong>轻量原生 K 线操盘工作站</strong>：本地打包集成，0 外部依赖免外部网络秒开；支持 150 根 K 线全屏铺满、MA/BOLL/VOL/MACD 多指标共存。
              </p>
            </div>
            <div class="dsh-card-sub p-3.5 space-y-1.5">
              <div class="font-bold text-xs text-[var(--ink-strong)]">7 梯队量化微积分矩阵</div>
              <p class="text-[var(--ink-2)] leading-body">
                • <strong>微结构全景透视</strong>：T0 费率/OI 与精英多空比、T0.5 CVD 累计成交量差与大单净流入、T1 L2 深度与 OBI 盘口失衡度、T1.5 期权 IV 波动率曲面与 Max Pain、T2 期限基差、T3 VWAP 筹码中枢与 VPVR、T4 MACD 加速度与 ADX 动量。<br>
                • <strong>数据白盒下钻</strong>：点击任一行标的即可呼出全因子微积分白盒抽屉与完整思考轨迹 (CoT)。
              </p>
            </div>
          </div>
        </section>

        <!-- 3. 多模型决策委员会 -->
        <section id="council" class="space-y-4 pt-6 border-t scroll-mt-14" style="border-color: var(--line-1);">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 03</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">对冲基金投委会 (Trading Desk & Council Pro)</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body font-sans text-[var(--ink-2)]">
            为了彻底消除单一模型的幻觉与思考盲区，系统支持配置任意大模型席位（支持 DeepSeek、Claude、GPT、Qwen 等）组成对抗质询投委会：
          </p>

          <div class="dsh-card-sub p-4 text-xs space-y-2.5">
            <div class="font-bold text-xs text-[var(--ink-strong)]">三大投委会共识仲裁机制：</div>
            <div class="grid grid-cols-1 md:grid-cols-3 gap-2.5 pt-1">
              <div class="p-2.5 rounded border" style="background-color: var(--surface-2); border-color: var(--line-1);">
                <div class="font-bold text-[var(--down)]">1. 一票否决制 (Paranoid Veto)</div>
                <div class="text-3xs mt-1 text-[var(--ink-3)]">只要任一参谋提出宏观风险或流动性断崖预警，CIO 仲裁官无条件强制降级为 WAIT。</div>
              </div>
              <div class="p-2.5 rounded border" style="background-color: var(--surface-2); border-color: var(--line-1);">
                <div class="font-bold text-[var(--accent)]">2. 加权共识制 (Weighted Majority)</div>
                <div class="text-3xs mt-1 text-[var(--ink-3)]">按各席位置信度与历史准确率加权投票，仅在同向权重绝对占优时准许发单。</div>
              </div>
              <div class="p-2.5 rounded border" style="background-color: var(--surface-2); border-color: var(--line-1);">
                <div class="font-bold text-[var(--up)]">3. 动能突破优先 (Alpha Hunter)</div>
                <div class="text-3xs mt-1 text-[var(--ink-3)]">当 MACD 柱加速度与订单流 CVD 同向共振时，赋予突破分析师优先裁决权。</div>
              </div>
            </div>
          </div>
        </section>

        <!-- 4. 策略版本快照控制台 -->
        <section id="policy_snapshot" class="space-y-4 pt-6 border-t scroll-mt-14" style="border-color: var(--line-1);">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 04</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">策略版本快照控制台 (Policy Snapshot)</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body font-sans text-[var(--ink-2)]">
            实时聚合提示词工程、自进化心法库、执行层风控基线与投委会席位配置四大单元，生成唯一不可变的 SHA256 哈希指纹（<code>policy_hash</code>）：
          </p>

          <div class="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
            <div class="dsh-card-sub p-3">
              <div class="font-bold text-[var(--accent)]">1. 不可变哈希指纹</div>
              <p class="text-3xs mt-1 text-[var(--ink-3)]">四大单元参数发生哪怕一个字变动，即时生成全新唯一指纹，交易台账严格关联此指纹。</p>
            </div>
            <div class="dsh-card-sub p-3">
              <div class="font-bold text-[var(--accent)]">2. 具名版本归档</div>
              <p class="text-3xs mt-1 text-[var(--ink-3)]">一键将实盘表现优异的全盘策略打包归档，支持版本备注、比对与跨环境导出。</p>
            </div>
            <div class="dsh-card-sub p-3">
              <div class="font-bold text-[var(--up)]">3. 秒级原子回滚</div>
              <p class="text-3xs mt-1 text-[var(--ink-3)]">调优参数偏差导致胜率波动时，一键原子恢复历史最佳策略版本，下一周期即刻生效。</p>
            </div>
          </div>
        </section>

        <!-- 5. 提示词策略与变量插槽 -->
        <section id="prompt_studio" class="space-y-4 pt-6 border-t scroll-mt-14" style="border-color: var(--line-1);">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 05</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">提示词策略与 8 大语义变量插槽</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body font-sans text-[var(--ink-2)]">
            <strong>全代码库零散落提示词</strong>：所有策略提示词集中管理于 <code>data/prompt_library.json</code>。输出严格采用只读的 <strong>JSON Schema 契约</strong>，彻底消除 Markdown 代码块未闭合或多余客套话带来的解析崩溃。
          </p>

          <!-- Variable Table -->
          <div class="dsh-card overflow-x-auto">
            <table class="table w-full text-xs" aria-label="8 大核心实时语义变量插槽说明">
              <thead>
                <tr>
                  <th scope="col">变量插槽</th>
                  <th scope="col">分类</th>
                  <th scope="col">注入内容与实战用途</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td class="font-mono font-bold text-[var(--accent)]">&#123;&#123;account_balance&#125;&#125;</td>
                  <td>资产</td>
                  <td class="text-[var(--ink-2)]">OKX 私有接口实时拉取的可用 USDT 现金余额与账户总权益</td>
                </tr>
                <tr>
                  <td class="font-mono font-bold text-[var(--accent)]">&#123;&#123;risk_budget&#125;&#125;</td>
                  <td>风控</td>
                  <td class="text-[var(--ink-2)]">自适应推导的单笔保证金限额、杠杆区间、单日亏损熔断线与 R:R 底线</td>
                </tr>
                <tr>
                  <td class="font-mono font-bold text-[var(--warn)]">&#123;&#123;account_positions&#125;&#125;</td>
                  <td>持仓</td>
                  <td class="text-[var(--ink-2)]">在途活跃持仓方向、均价、未结浮盈 ROI、最高浮盈点（HWM）及极值回撤百分比</td>
                </tr>
                <tr>
                  <td class="font-mono font-bold text-[var(--warn)]">&#123;&#123;pending_orders&#125;&#125;</td>
                  <td>挂单</td>
                  <td class="text-[var(--ink-2)]">在途未成交 Maker 限价挂单 ID、价位、数量及挂单时长，供模型执行 KEEP 或 CANCEL</td>
                </tr>
                <tr>
                  <td class="font-mono font-bold text-[var(--ink-strong)]">&#123;&#123;market_matrix&#125;&#125;</td>
                  <td>行情</td>
                  <td class="text-[var(--ink-2)]">全标的 7 梯队因子（T0 费率/OI · T0.5 CVD · T1 OBI · T1.5 IV · T2 基差 · T3 VWAP · T4 MACD/RSI）</td>
                </tr>
                <tr>
                  <td class="font-mono font-bold text-[var(--accent)]">&#123;&#123;news_intelligence&#125;&#125;</td>
                  <td>快讯</td>
                  <td class="text-[var(--ink-2)]">全网最新重大突发要闻、央行决议与宏观情绪打分标签</td>
                </tr>
                <tr>
                  <td class="font-mono font-bold text-[var(--up)]">&#123;&#123;trading_memory&#125;&#125;</td>
                  <td>心法</td>
                  <td class="text-[var(--ink-2)]">真实平仓台账反思提炼的核心教训与实战避坑铁律（源自 structured_trading_memory.json）</td>
                </tr>
                <tr>
                  <td class="font-mono font-bold text-[var(--ink-3)]">&#123;&#123;decision_timestamp&#125;&#125;</td>
                  <td>时间</td>
                  <td class="text-[var(--ink-2)]">当前决策周期的精确北京时间戳（UTC+8），杜绝模型时间认知漂移</td>
                </tr>
              </tbody>
            </table>
          </div>

          <!-- 5 Rules -->
          <div class="dsh-card-sub p-4 space-y-3">
            <h3 class="text-xs font-bold text-[var(--ink-strong)] flex items-center space-x-1.5">
              <BookOpen class="w-3.5 h-3.5 text-[var(--accent)]" />
              <span>💡 高胜率提示词编写五大核心军规（破解“小赚大亏”实战秘诀）</span>
            </h3>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5 text-xs">
              <div class="p-2.5 rounded border" style="background-color: var(--surface-2); border-color: var(--line-1);">
                <div class="font-bold text-[var(--up)]">1. 科学波段呼吸，严禁过早提损保本</div>
                <div class="text-3xs mt-1 text-[var(--ink-3)]">浮盈 &lt; 1.2R 坚决给足 1.8x~2.2x ATR 宽止损呼吸空间；稳固达到 ≥ 1.5R 且波段确立后再移损保本。</div>
              </div>
              <div class="p-2.5 rounded border" style="background-color: var(--surface-2); border-color: var(--line-1);">
                <div class="font-bold text-[var(--accent)]">2. 杜绝惊慌市价平仓，让主升浪充分奔跑</div>
                <div class="text-3xs mt-1 text-[var(--ink-3)]">严禁在轻度浮盈后因正常日内回抽而市价恐慌平仓；结构未破坏前坚持 HOLD，单笔盈亏比瞄准 2.0R~2.8R。</div>
              </div>
              <div class="p-2.5 rounded border" style="background-color: var(--surface-2); border-color: var(--line-1);">
                <div class="font-bold text-[var(--warn)]">3. 资产敞口自律，防范系统性 Beta 踩踏</div>
                <div class="text-3xs mt-1 text-[var(--ink-3)]">全账户同向持仓达 2 笔以上时，自动收紧新开仓门槛至 85%+，严格禁止强相关币种同向开仓。</div>
              </div>
              <div class="p-2.5 rounded border" style="background-color: var(--surface-2); border-color: var(--line-1);">
                <div class="font-bold text-[var(--down)]">4. 止损后坚决冷静，杜绝绞肉市逆势接刀</div>
                <div class="text-3xs mt-1 text-[var(--ink-3)]">标的一旦被扫损，系统强制执行冷静期；未出现大级别真突破前严禁在同一区间重复抄底摸顶。</div>
              </div>
            </div>
          </div>
        </section>

        <!-- 6. 大模型全权直通与执行层物理校验 -->
        <section id="execution_gate" class="space-y-4 pt-6 border-t scroll-mt-14" style="border-color: var(--line-1);">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 06</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">大模型全权直通与执行层物理校验</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body font-sans text-[var(--ink-2)]">
            <strong>2026-10 策略插件系统全面裁撤</strong>：开不开单由大模型（单模型或投委会 CIO）自主裁决，底座不再做主观策略性否决，模型给出的方向、点位、杠杆与保证金<strong>原样直通执行层</strong>。
          </p>

          <div class="dsh-card-sub p-3.5 space-y-2">
            <h3 class="text-xs font-bold text-[var(--ink-strong)]">底座仅保留确定性物理必然性校验（Fail-Closed）：</h3>
            <ul class="list-disc list-inside text-xs text-[var(--ink-2)] space-y-1">
              <li><strong>数据完整性校验</strong>：关键行情、深度或资金费缺失时拒绝开仓，绝不拿残缺数据冒险。</li>
              <li><strong>反向持仓防冲突</strong>：同一标的已有在途反向持仓时禁止开仓，防范净持仓模式下意外自我对冲损耗手续费。</li>
              <li><strong>报价几何合法性</strong>：买多必须满足 <code>止损 &lt; 入场 &lt; 止盈</code>，卖空反向对称，且三价均为有限正数（防范 OKX 51001 拒单）。</li>
              <li><strong>动态盈亏比底线</strong>：入场前物理核算期望 R:R，低于底线且无高置信度放行时物理拦截。</li>
              <li><strong>100% 交易所云端 OCO 保护</strong>：每笔成交瞬间，原子挂出交易所侧条件止损单，遭遇断网或进程崩溃依然受到交易所保护。</li>
            </ul>
          </div>
        </section>

        <!-- 7. 执行层风控与分批止盈双腿 -->
        <section id="risk_control" class="space-y-4 pt-6 border-t scroll-mt-14" style="border-color: var(--line-1);">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 07</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">执行层风控与分批止盈双腿 (Scale-Out)</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body font-sans text-[var(--ink-2)]">
            系统具备行业领先的<strong>分批止盈 (Scale-Out) 交易所侧双腿机制</strong>，解决了“单档止盈容易坐过山车、多档止盈容易丢失止损覆盖”的技术痛点：
          </p>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-3 pt-1 text-xs">
            <div class="dsh-card-sub p-3.5 space-y-1.5">
              <div class="font-bold text-xs text-[var(--up)]">首批止盈腿 (TP1 - 锁定利润)</div>
              <p class="text-[var(--ink-2)] leading-body">
                建仓成交后，系统自动在交易所挂出一条独立带量（<code>sz</code>）的 <code>reduceOnly</code> 算法腿（TP1 = 建仓价 ± 1.8x ATR）。由撮合引擎瞬时触发执行，不需要等待 15 分钟轮询。
              </p>
            </div>
            <div class="dsh-card-sub p-3.5 space-y-1.5">
              <div class="font-bold text-xs text-[var(--accent)]">终点止盈腿 (TP2 - 捕捉主升浪)</div>
              <p class="text-[var(--ink-2)] leading-body">
                剩余仓位挂出 TP2 终点目标单。<strong>两条腿各自绑定全额止损</strong>，无论哪一条腿触发，止损覆盖率恒定保持 100%。首批达成后，系统自动将剩余仓位止损抬升至开仓均价（移损保本）。
              </p>
            </div>
          </div>
        </section>

        <!-- 8. 模型连接、协议与 Prompt Caching -->
        <section id="llm_caching" class="space-y-4 pt-6 border-t scroll-mt-14" style="border-color: var(--line-1);">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 08</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">模型连接、协议与 Prompt Caching 提示词缓存</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body font-sans text-[var(--ink-2)]">
            <strong>2026-10 核心技术突破</strong>：AstraQuant 实现了专为多模型量化投委会设计的 <strong>Prompt Caching 提示词缓存与会话亲和架构</strong>，大幅削减大模型推理开销与响应延迟：
          </p>

          <div class="space-y-3 text-xs">
            <div class="dsh-card-sub p-3.5 space-y-2">
              <div class="font-bold text-xs text-[var(--accent)]">1. 单前缀广播 (Shared Market/Rules Prefix)</div>
              <p class="text-[var(--ink-2)] leading-body">
                投委会宏观官、微结构官、动量官并发质询时，系统将共享规则、常态化风控契约与多标的 7 层因子矩阵沉淀在前缀（占比超 90%）。通过代理会话亲和（Session Affinity）将多席位请求路由至同节点，下游直接命中已热身的 KV Cache，模型首字延迟降低 70%+。
              </p>
            </div>

            <div class="dsh-card-sub p-3.5 space-y-2">
              <div class="font-bold text-xs text-[var(--accent)]">2. 单调波动分级架构 (Monotonic Volatility Hierarchy)</div>
              <p class="text-[var(--ink-2)] leading-body">
                彻底重构提示词编排顺序，按数据变动频率严格分层：<strong>Zone 0 不变宪法</strong>（角色设定与只读 Schema）→ <strong>Zone 1 慢变心法</strong>（6 小时复盘记忆）→ <strong>Zone 2 中变舆情</strong>（10 分钟快讯）→ <strong>Zone 3 低频因子</strong>（1H 指标）→ <strong>Zone 4 极高频状态</strong>（当前毫秒与动态秒级盘口）。确保前缀绝不被末尾高频变动打碎。
              </p>
            </div>

            <div class="dsh-card-sub p-3.5 space-y-2">
              <div class="font-bold text-xs text-[var(--accent)]">3. Claude Ephemeral 显式断点与浮点防抖</div>
              <p class="text-[var(--ink-2)] leading-body">
                针对 Anthropic Claude 原生注入 <code>cache_control: {"type": "ephemeral"}</code> 边界标记；针对 DeepSeek/OpenAI 严格按 64/128 token 边界对齐。配合<strong>浮点防抖 (Float Anti-Jitter)</strong>，消除末尾微小浮点扰动对哈希命中率的影响。
              </p>
            </div>
          </div>
        </section>

        <!-- 9. 自进化认知与长期记忆闭环 -->
        <section id="self_evolution" class="space-y-4 pt-6 border-t scroll-mt-14" style="border-color: var(--line-1);">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 09</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">自进化认知与长期记忆闭环</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body font-sans text-[var(--ink-2)]">
            系统具备真正闭环的实盘自我进化机制，严格杜绝凭空臆测，只认真实交易台账：
          </p>

          <div class="grid grid-cols-1 sm:grid-cols-2 gap-3 text-xs">
            <div class="dsh-card-sub p-3 space-y-1">
              <div class="font-bold text-[var(--ink-strong)]">真实流水对齐</div>
              <p class="text-[var(--ink-2)] leading-body">
                每日 4 次（02:00/08:00/14:00/20:00）自动对齐 OKX 真实平仓账单，将开仓时投委会辩论记录与平仓结果无缝关联。
              </p>
            </div>
            <div class="dsh-card-sub p-3 space-y-1">
              <div class="font-bold text-[var(--ink-strong)]">记忆半衰期淘汰</div>
              <p class="text-[var(--ink-2)] leading-body">
                自动归纳核心胜负因，经验条目注入心法库。若市场风格迁移导致某条旧规则在近期持续失准，系统自动启动半衰期弱化与淘汰机制。
              </p>
            </div>
          </div>
        </section>

        <!-- 10. 极速开箱部署与多通道通知 -->
        <section id="deployment" class="space-y-4 pt-6 border-t scroll-mt-14" style="border-color: var(--line-1);">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 10</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">极速开箱部署与多通道通知</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body font-sans text-[var(--ink-2)]">
            AstraQuant 提供最简极速部署体验，开箱 2 分钟完成全链路环境配置：
          </p>

          <div class="dsh-card-sub p-4 space-y-3 text-xs">
            <div class="font-bold text-[var(--accent)]">推荐部署方式：</div>
            <div class="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <div class="p-2.5 rounded border" style="background-color: var(--surface-2); border-color: var(--line-1);">
                <div class="font-bold text-[var(--up)]">1. 交互式向导 (最快)</div>
                <div class="text-3xs mt-1 text-[var(--ink-3)] font-mono">./setup.sh</div>
                <div class="text-3xs mt-1 text-[var(--ink-2)]">2分钟引导配置交易所、模型、风控基线与密码。</div>
              </div>
              <div class="p-2.5 rounded border" style="background-color: var(--surface-2); border-color: var(--line-1);">
                <div class="font-bold text-[var(--accent)]">2. Docker 一键启动</div>
                <div class="text-3xs mt-1 text-[var(--ink-3)] font-mono">./deploy/docker-start.sh</div>
                <div class="text-3xs mt-1 text-[var(--ink-2)]">0 宿主机依赖，自带双向看门狗与 .env 目录陷阱拦截。</div>
              </div>
              <div class="p-2.5 rounded border" style="background-color: var(--surface-2); border-color: var(--line-1);">
                <div class="font-bold text-[var(--ink-strong)]">3. 裸机守护 (Systemd)</div>
                <div class="text-3xs mt-1 text-[var(--ink-3)] font-mono">deploy/install.sh</div>
                <div class="text-3xs mt-1 text-[var(--ink-2)]">生产级常驻后台与网关，Prometheus 指标开箱即用。</div>
              </div>
            </div>

            <div class="pt-2 text-[var(--ink-2)] leading-body">
              <strong>多通道通知推送</strong>：集成 Telegram Bot、飞书 Webhook、企业微信、Discord Webhook，开仓、止盈、移损、熔断秒级推送至手机。
            </div>
          </div>
        </section>

        <!-- 11. 开源协议与反割韭菜特约附则 -->
        <section id="license_rider" class="space-y-4 pt-6 border-t scroll-mt-14" style="border-color: var(--line-1);">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 11</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">开源协议与反割韭菜特约附则</h2>
          </div>

          <p class="text-xs sm:text-sm leading-body font-sans text-[var(--ink-2)]">
            AstraQuant 自 v8.5.0 正式版起，正式采用 <strong>GNU AGPL-3.0 + Commons Clause v1.0 + 专有反割韭菜特约附则 (Anti-Scam Rider)</strong> 授权：
          </p>

          <div class="dsh-card-sub p-4 space-y-3 text-xs">
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div class="space-y-1">
                <div class="font-bold text-[var(--up)]">网络服务强传染开源 (AGPL-3.0)</div>
                <p class="text-[var(--ink-3)] leading-body">
                  任何个人或组织修改本项目并通过网络提供服务（SaaS/Web），必须无条件向所有网络用户完整公开修改后的全部源代码。
                </p>
              </div>
              <div class="space-y-1">
                <div class="font-bold text-[var(--accent)]">严禁商业转售与收费带单 (Commons Clause)</div>
                <p class="text-[var(--ink-3)] leading-body">
                  严禁以任何形式直接或间接转售、分发代码或提供收费订阅与收费跟单服务。个人与机构内部自营交易完全免费。
                </p>
              </div>
              <div class="space-y-1">
                <div class="font-bold text-[var(--warn)]">严禁反向闭源与混淆改名</div>
                <p class="text-[var(--ink-3)] leading-body">
                  必须在所有分发和界面中显著保留原作者署名及官方仓库链接，严禁换皮打包为收费商业闭源软件。
                </p>
              </div>
              <div class="space-y-1">
                <div class="font-bold text-[var(--down)]">绝对禁止欺诈与非法集资 (Anti-Scam Rider)</div>
                <p class="text-[var(--ink-3)] leading-body">
                  严禁将本项目用于承诺收益、非法吸储、收费带单群、代客理财等金融黑灰产，保护社区开源极客不受欺诈侵害。
                </p>
              </div>
            </div>
          </div>
        </section>

        <!-- 12. FAQ -->
        <section id="faq" class="space-y-4 pt-6 border-t scroll-mt-14" style="border-color: var(--line-1);">
          <div class="flex items-center space-x-2">
            <span class="dsh-pill font-mono font-bold text-3xs">CHAPTER 12</span>
            <h2 class="text-lg sm:text-xl font-bold tracking-tight text-[var(--ink-strong)]">常见问题解答与风控底线 (FAQ)</h2>
          </div>

          <div class="space-y-3 text-xs">
            <div class="dsh-card-sub p-3 space-y-1">
              <h3 class="font-bold text-[var(--ink-strong)]">Q: 系统如何保证资金安全？</h3>
              <p class="text-[var(--ink-2)] leading-body">
                A: API Key 凭证本地 Fernet 加密存储；绝不开启提现权限；所有订单均有云端双腿 OCO 止损物理保护；全盘具备单日亏损熔断保护。
              </p>
            </div>
            <div class="dsh-card-sub p-3 space-y-1">
              <h3 class="font-bold text-[var(--ink-strong)]">Q: 模型请求失败或超时会怎样？</h3>
              <p class="text-[var(--ink-2)] leading-body">
                A: 系统自动触发配置的 Failover 备用模型链；若全链不可用，系统自动保持 Fail-Closed 状态（不执行任何新开仓动作）。
              </p>
            </div>
            <div class="dsh-card-sub p-3 space-y-1">
              <h3 class="font-bold text-[var(--ink-strong)]">Q: 为什么系统只专注 OKX 单一交易所？</h3>
              <p class="text-[var(--ink-2)] leading-body">
                A: 单一交易所使得 API 签约路径单一、订单状态机极简高内聚，完全消除了跨交易所抽象层带来的执行延迟与对账分歧。
              </p>
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
