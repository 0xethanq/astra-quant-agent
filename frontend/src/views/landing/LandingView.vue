<script setup lang="ts">
/**
 * LandingView.vue · AstraQuant 官方落地页
 * ---------------------------------------------------------------------------
 * 极简机构级量化终端视觉重构：
 * - 剔除 AI 模板化瑕疵（去除彩虹渐变字、头顶模糊光斑、交通灯假终端）
 * - 引入高保真 AstraQuant 交易终端全景工作台视口模型 (Hero Workstation Showcase)
 * - 全面接入设计系统 Tokens，支持明暗主题自适应与统一工业级微倒角
 * - 保留官方交易所动态通道加载与安全合规防硬编码逻辑
 */
import { ref, computed, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import {
  ArrowRight,
  ShieldCheck,
  Globe,
  Crosshair,
  Dna,
  Zap,
  Copy,
  Check,
  Menu,
  X,
  Github,
  ExternalLink,
  Lock,
  Cpu,
  TrendingUp,
  Gift,
} from 'lucide-vue-next';
import { useI18n } from '../../composables/useI18n';
import { OFFICIAL_REPO, SKILLHUB_REBATES_URL, SKILLHUB_REPO, SKILLHUB_SITE } from '../../config/version';
import { resolveChannelUrl, useReferralChannels, type MirrorRegion } from '../../composables/useReferralChannels';
import { trackEvent } from '../../utils/analytics';

const router = useRouter();
const { t, currentLocale, toggleLocale } = useI18n();
const { channels, partnerChannels, load: loadChannels } = useReferralChannels();

const mirrorRegion = ref<MirrorRegion>(currentLocale.value === 'zh-CN' ? 'cn' : 'global');

interface PromoChannel {
  key: string;
  name: string;
  badge: string;
  isApiSupported: boolean;
  invite_url: string;
  code: string;
  rebate: string;
  rateTier: string;
  note: string;
}

const promoChannels = computed<PromoChannel[]>(() => {
  const dynamicOkx = channels.value.find((c) => c.key === 'okx');
  const binance = partnerChannels.value.find((c) => c.key === 'binance');
  const gate = partnerChannels.value.find((c) => c.key === 'gate');
  const bitget = partnerChannels.value.find((c) => c.key === 'bitget');

  const list: PromoChannel[] = [];
  if (dynamicOkx && resolveChannelUrl(dynamicOkx, mirrorRegion.value)) {
    list.push({
      key: 'okx',
      name: 'OKX',
      badge: t('landing.referral.okxBadge'),
      isApiSupported: true,
      invite_url: resolveChannelUrl(dynamicOkx, mirrorRegion.value),
      code: dynamicOkx.code,
      rebate: dynamicOkx.rebate || '20%',
      rateTier: `${dynamicOkx.rebate || '20%'} ${t('landing.referral.rebateRateSuffix')}`,
      note: t('landing.referral.okxOldUserNote'),
    });
  }
  for (const ch of [binance, gate, bitget]) {
    if (!ch) continue;
    const href = resolveChannelUrl(ch, mirrorRegion.value);
    if (!href) continue;
    list.push({
      key: ch.key,
      name: ch.name,
      badge: t('landing.referral.partnerBadge'),
      isApiSupported: false,
      invite_url: href,
      code: ch.code,
      rebate: ch.rebate || '20%',
      rateTier: `${ch.rebate || '20%'} ${t('landing.referral.rebateRateSuffix')}`,
      note: t('landing.referral.partnerNote'),
    });
  }
  return list;
});

const VOLUME_PRESETS = [100000, 500000, 2000000, 10000000] as const;
const calcVolumeUsd = ref<number>(500000);
const calcVenueKey = ref<string>('okx');

const REBATE_RATES: Record<string, number> = {
  okx: 0.2,
  binance: 0.2,
  gate: 0.2,
  bitget: 0.15,
};

const activeCalcVenue = computed(
  () => promoChannels.value.find((c) => c.key === calcVenueKey.value) || promoChannels.value[0] || null,
);
const calcMonthlyFee = computed(() => Math.round(calcVolumeUsd.value * 0.0005));
const calcMonthlyRebate = computed(() =>
  Math.round(calcMonthlyFee.value * (REBATE_RATES[calcVenueKey.value] ?? 0.2)),
);
const calcAnnualRebate = computed(() => calcMonthlyRebate.value * 12);

function formatUsd(amount: number): string {
  return `$${amount.toLocaleString('en-US')}`;
}

function formatPreset(amount: number): string {
  return amount >= 1000000 ? `$${amount / 1000000}M` : `$${amount / 1000}K`;
}

function scrollToReferral() {
  if (typeof document === 'undefined') return;
  const el = document.getElementById('referral');
  if (!el) return;
  const reduced =
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  el.scrollIntoView({ behavior: reduced ? 'auto' : 'smooth' });
  trackEvent('hero_rebate_scroll');
}

// 移动端菜单控制
const mobileMenuOpen = ref(false);

function navTo(path: string) {
  router.push(path);
}

function openExternal(url: string) {
  if (typeof window !== 'undefined') {
    window.open(url, '_blank', 'noopener,noreferrer');
  }
}

// 终端部署命令复制
const copiedCmd = ref(false);
const DOCKER_CMD = 'git clone https://github.com/0xethanq/astra-quant-agent.git && cd astra-quant-agent && ./setup.sh';

async function copyCommand() {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(DOCKER_CMD);
    }
  } catch {
    // 降级兜底静默处理
  }
  copiedCmd.value = true;
  setTimeout(() => {
    copiedCmd.value = false;
  }, 2000);
}

// 返佣通道链接与邀请码复制
const copiedChannelKey = ref<string | null>(null);
const copiedCodeKey = ref<string | null>(null);

async function copyChannelUrl(url: string, key: string) {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
    }
  } catch {
    // 降级兜底静默处理
  }
  trackEvent('rebate_copy_link', { exchange: key, mirror: mirrorRegion.value });
  copiedChannelKey.value = key;
  setTimeout(() => {
    if (copiedChannelKey.value === key) {
      copiedChannelKey.value = null;
    }
  }, 2000);
}

async function copyChannelCode(code: string, key: string) {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(code);
    }
  } catch {
    // 降级兜底静默处理
  }
  trackEvent('rebate_copy_code', { exchange: key });
  copiedCodeKey.value = key;
  setTimeout(() => {
    if (copiedCodeKey.value === key) {
      copiedCodeKey.value = null;
    }
  }, 2000);
}

onMounted(() => {
  loadChannels();
});
</script>

<template>
  <div class="landing-page min-h-screen w-full flex flex-col font-sans relative overflow-x-hidden selection:bg-emerald-500 selection:text-black">
    <!-- 顶部微发丝工业网格纹理（精密仪式感，替代廉价发光球） -->
    <div class="landing-grid-bg pointer-events-none absolute inset-0 z-0 opacity-40" aria-hidden="true" />

    <!-- 1. 全局单行导航栏 -->
    <header class="sticky top-0 z-50 h-16 w-full border-b backdrop-blur-xl px-4 sm:px-8 flex items-center justify-between landing-nav">
      <div class="w-full max-w-7xl mx-auto flex items-center justify-between">
        <div class="flex items-center gap-8">
          <RouterLink to="/" class="flex items-center gap-2.5 no-underline cursor-pointer group" :aria-label="t('brand.name')">
            <img src="/favicon.svg" alt="AstraQuant Logo" class="h-6 w-6 rounded transition-opacity group-hover:opacity-80" />
            <span class="font-bold tracking-tight text-base sm:text-lg font-mono text-[var(--ds-color-text-primary)]">
              AstraQuant
            </span>
          </RouterLink>

          <!-- 桌面端精炼导航 -->
          <nav class="hidden md:flex items-center gap-6 text-sm text-[var(--ds-color-text-description)]" aria-label="Landing Navigation">
            <RouterLink to="/trading" class="hover:text-[var(--ds-color-text-primary)] transition-colors no-underline">
              {{ t('landing.nav.trading') }}
            </RouterLink>
            <RouterLink to="/docs" class="hover:text-[var(--ds-color-text-primary)] transition-colors no-underline">
              {{ t('landing.nav.docs') }}
            </RouterLink>
            <a href="#referral" class="hover:text-[var(--ds-color-text-primary)] transition-colors no-underline">
              {{ t('landing.nav.referral') }}
            </a>
            <a
              :href="SKILLHUB_SITE"
              target="_blank"
              rel="noopener noreferrer"
              class="hover:text-[var(--ds-color-text-primary)] transition-colors no-underline inline-flex items-center gap-1"
              @click="trackEvent('crosslink_click', { target: 'skillhub', placement: 'landing_nav' })"
            >
              <span>{{ t('landing.nav.skills') }}</span>
              <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
              <ExternalLink class="h-3.5 w-3.5 opacity-70" aria-hidden="true" />
            </a>
            <RouterLink to="/admin/login" class="hover:text-[var(--ds-color-text-primary)] transition-colors no-underline">
              {{ t('landing.nav.console') }}
            </RouterLink>
            <button
              type="button"
              class="hover:text-[var(--ds-color-text-primary)] transition-colors cursor-pointer bg-transparent border-0 inline-flex items-center gap-1.5 text-sm text-[var(--ds-color-text-description)] p-0"
              @click="openExternal(OFFICIAL_REPO)"
            >
              <Github class="h-4 w-4" aria-hidden="true" />
              <span>{{ t('landing.nav.github') }}</span>
            </button>
          </nav>
        </div>

        <div class="flex items-center gap-3">
          <!-- 语言切换 -->
          <button
            type="button"
            class="h-8 px-2.5 text-xs font-mono cursor-pointer text-[var(--ds-color-text-description)] hover:text-[var(--ds-color-text-primary)] bg-transparent border-0 transition-colors"
            :aria-label="currentLocale === 'zh-CN' ? 'Switch to English' : '切换至中文'"
            @click="toggleLocale"
          >
            {{ currentLocale === 'zh-CN' ? 'EN' : '中文' }}
          </button>

          <!-- 移动端汉堡切换 -->
          <button
            type="button"
            class="md:hidden p-1.5 rounded-lg text-[var(--ds-color-text-description)] hover:text-[var(--ds-color-text-primary)] cursor-pointer bg-transparent border-0"
            aria-label="Toggle Navigation Menu"
            @click="mobileMenuOpen = !mobileMenuOpen"
          >
            <Menu v-if="!mobileMenuOpen" class="h-5 w-5" />
            <X v-else class="h-5 w-5" />
          </button>
        </div>
      </div>
    </header>

    <!-- 移动端折叠导航 -->
    <div
      v-if="mobileMenuOpen"
      class="md:hidden w-full border-b px-4 py-4 flex flex-col gap-3 text-sm font-medium z-50 bg-[var(--ds-color-bg-overlay)] border-[var(--ds-color-border-default)]"
    >
      <RouterLink to="/trading" class="py-1.5 hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-secondary)]" @click="mobileMenuOpen = false">
        {{ t('landing.nav.trading') }}
      </RouterLink>
      <RouterLink to="/docs" class="py-1.5 hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-secondary)]" @click="mobileMenuOpen = false">
        {{ t('landing.nav.docs') }}
      </RouterLink>
      <a href="#referral" class="py-1.5 hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-secondary)]" @click="mobileMenuOpen = false">
        {{ t('landing.nav.referral') }}
      </a>
      <a
        :href="SKILLHUB_SITE"
        target="_blank"
        rel="noopener noreferrer"
        class="py-1.5 hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-secondary)] inline-flex items-center gap-1.5"
        @click="mobileMenuOpen = false; trackEvent('crosslink_click', { target: 'skillhub', placement: 'landing_mobile_nav' })"
      >
        <span>{{ t('landing.nav.skills') }}</span>
        <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
        <ExternalLink class="h-3.5 w-3.5 opacity-70" aria-hidden="true" />
      </a>
      <RouterLink to="/admin/login" class="py-1.5 hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-secondary)]" @click="mobileMenuOpen = false">
        {{ t('landing.nav.console') }}
      </RouterLink>
      <button
        type="button"
        class="py-1.5 hover:text-[var(--ds-color-text-primary)] text-[var(--ds-color-text-secondary)] flex items-center gap-2 bg-transparent border-0 cursor-pointer text-sm"
        @click="mobileMenuOpen = false; openExternal(OFFICIAL_REPO)"
      >
        <Github class="h-4 w-4" aria-hidden="true" />
        <span>{{ t('landing.nav.github') }}</span>
      </button>
    </div>

    <!-- 2. 主页面内容 -->
    <main class="flex-1 w-full flex flex-col items-center relative z-10">
      <!-- HERO 首屏：机构级科技质感 -->
      <section class="w-full max-w-6xl px-4 sm:px-8 pt-16 sm:pt-24 pb-14 flex flex-col items-center text-center">
        <!-- 顶部硬件仪器规格微标签 -->
        <div class="inline-flex items-center gap-2 rounded-full border border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-2)] px-3.5 py-1 text-xs font-mono text-[var(--ds-color-text-secondary)] mb-6 shadow-sm">
          <span class="h-2 w-2 rounded-full bg-[var(--ds-color-brand)] animate-pulse" />
          <span>{{ t('landing.terminal.tag') }} · {{ t('landing.terminal.badge') }}</span>
        </div>

        <!-- 主标题：纯净高反差排版 -->
        <h1 class="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-extrabold tracking-tight text-[var(--ds-color-text-primary)] leading-[1.12] max-w-5xl">
          {{ t('landing.hero.titlePart1') }}
          <span class="block mt-2 text-[var(--ds-color-brand)]">
            {{ t('landing.hero.titleHighlight') }}
          </span>
        </h1>

        <!-- 副标题 -->
        <p class="mt-6 text-base sm:text-lg md:text-xl text-[var(--ds-color-text-secondary)] leading-relaxed max-w-3xl font-light">
          {{ t('landing.hero.subtitle') }}
        </p>

        <!-- 三重安全信任承诺 -->
        <div class="mt-6 flex flex-wrap items-center justify-center gap-3 text-xs font-mono text-[var(--ds-color-text-description)]">
          <span class="px-3 py-1 rounded-md bg-[var(--ds-color-bg-surface-2)] border border-[var(--ds-color-border-default)] flex items-center gap-1.5">
            <ShieldCheck class="h-3.5 w-3.5 text-[var(--ds-color-brand)]" /> {{ t('landing.hero.trust1') }}
          </span>
          <span class="px-3 py-1 rounded-md bg-[var(--ds-color-bg-surface-2)] border border-[var(--ds-color-border-default)] flex items-center gap-1.5">
            <Lock class="h-3.5 w-3.5 text-[var(--ds-color-brand)]" /> {{ t('landing.hero.trust2') }}
          </span>
          <span class="px-3 py-1 rounded-md bg-[var(--ds-color-bg-surface-2)] border border-[var(--ds-color-border-default)] flex items-center gap-1.5">
            <Globe class="h-3.5 w-3.5 text-[var(--ds-color-brand)]" /> {{ t('landing.hero.trust3') }}
          </span>
        </div>

        <!-- 行动按钮：启动终端 + 跳转 GitHub -->
        <div class="mt-9 flex flex-wrap items-center justify-center gap-4">
          <button
            type="button"
            class="btn btn-primary h-12 sm:h-13 px-8 sm:px-9 rounded-xl text-sm sm:text-base font-bold cursor-pointer inline-flex items-center gap-2.5 shadow-xl transition-all active:scale-95"
            @click="navTo('/trading')"
          >
            <span>{{ t('landing.hero.ctaPrimary') }}</span>
            <ArrowRight class="h-4.5 w-4.5" />
          </button>

          <button
            type="button"
            class="btn btn-ghost h-12 sm:h-13 px-6 sm:px-7 rounded-xl text-sm sm:text-base font-semibold inline-flex items-center gap-2 cursor-pointer border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/10"
            @click="scrollToReferral"
          >
            <Gift class="h-4.5 w-4.5" aria-hidden="true" />
            <span>{{ t('landing.hero.ctaRebates') }}</span>
          </button>

          <button
            type="button"
            class="btn btn-ghost h-12 sm:h-13 px-7 sm:px-8 rounded-xl text-sm sm:text-base font-medium inline-flex items-center gap-2.5 cursor-pointer backdrop-blur-md"
            @click="openExternal(OFFICIAL_REPO)"
          >
            <Github class="h-4.5 w-4.5" aria-hidden="true" />
            <span>{{ t('landing.hero.ctaGithub') }}</span>
          </button>
        </div>

        <!-- 平台支持轻标识 -->
        <div class="mt-7 text-xs font-mono text-[var(--ds-color-text-placeholder)]">
          {{ t('landing.quickstart.platformSupport') }}
        </div>
      </section>

      <!-- ═══ 核心高阶视口：AstraQuant 机构级交易终端工作台全景展示 (Hero Workstation Showcase) ═══ -->
      <section class="w-full max-w-6xl xl:max-w-7xl px-4 sm:px-8 pb-20">
        <div class="card rounded-2xl border border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-card)] shadow-2xl overflow-hidden text-left relative group">
          <!-- 1. 工作台顶栏控制条 -->
          <div class="px-4 sm:px-6 py-3 border-b border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-inset)] flex flex-wrap items-center justify-between gap-4 font-mono text-xs">
            <div class="flex items-center gap-3 sm:gap-4 flex-wrap">
              <div class="flex items-center gap-2">
                <span class="font-bold text-sm text-[var(--ds-color-text-primary)]">{{ t('landing.terminal.terminalTitle') }}</span>
                <span class="text-3xs px-2 py-0.5 rounded bg-[var(--ds-color-bg-surface-2)] text-[var(--ds-color-text-description)] border border-[var(--ds-color-border-default)] font-semibold">OKX V5 NATIVE</span>
              </div>
            </div>

            <!-- 遥测就绪状态 -->
            <div class="flex items-center gap-3 sm:gap-4 text-3xs text-[var(--ds-color-text-description)]">
              <span class="flex items-center gap-1.5">
                <span class="h-1.5 w-1.5 rounded-full bg-[var(--ds-color-brand)] animate-pulse" />
                <span>{{ t('landing.terminal.wsLatency') }}</span>
              </span>
              <span class="hidden sm:flex items-center gap-1.5">
                <Cpu class="h-3 w-3 text-cyan-400" />
                <span>{{ t('landing.terminal.councilStatus') }}</span>
              </span>
              <span class="hidden sm:flex items-center gap-1.5">
                <ShieldCheck class="h-3 w-3 text-[var(--ds-color-brand)]" />
                <span>{{ t('landing.terminal.riskStatus') }}</span>
              </span>
            </div>

            <!-- 快速启动终端按钮 -->
            <button
              type="button"
              class="btn btn-primary h-8 px-3.5 text-xs font-semibold rounded-lg inline-flex items-center gap-1.5 cursor-pointer shadow-sm"
              @click="navTo('/trading')"
            >
              <span>{{ t('landing.terminal.openTerminal') }}</span>
              <ArrowRight class="h-3.5 w-3.5" />
            </button>
          </div>

          <!-- 2. 真实超清工作台全景画面（真实实盘 K 线与投委会决策工作台） -->
          <RouterLink
            to="/trading"
            class="relative w-full overflow-hidden bg-black/40 block group no-underline"
            :aria-label="t('landing.terminal.openTerminal')"
          >
            <img
              src="/images/dashboard_preview.png"
              :alt="t('landing.terminal.terminalTitle')"
              class="w-full h-auto block transition-transform duration-700 ease-out group-hover:scale-[1.008]"
              loading="eager"
            />
            <!-- 悬浮微徽标提示 -->
            <div class="absolute bottom-4 right-4 pointer-events-none opacity-90 group-hover:opacity-100 transition-opacity">
              <span class="px-3.5 py-1.5 rounded-lg border border-white/20 bg-black/75 backdrop-blur-md text-xs font-mono text-white flex items-center gap-2 shadow-2xl">
                <span class="h-2 w-2 rounded-full bg-[var(--ds-color-brand)] animate-pulse" />
                <span>{{ t('landing.terminal.clickToLaunch') }}</span>
              </span>
            </div>
          </RouterLink>

          <!-- 3. 工作台底栏：三大核心支柱直达 -->
          <div class="p-5 sm:p-6 border-t border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-inset)] grid grid-cols-1 md:grid-cols-3 gap-6 font-mono text-xs">
            <div class="flex items-start gap-3">
              <div class="h-8 w-8 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 shrink-0 mt-0.5">
                <Dna class="h-4 w-4" />
              </div>
              <div>
                <div class="font-bold text-[var(--ds-color-text-primary)] text-sm mb-1">{{ t('landing.workflow.step1Title') }}</div>
                <p class="text-3xs text-[var(--ds-color-text-description)] leading-relaxed m-0">{{ t('landing.workflow.step1Desc') }}</p>
              </div>
            </div>

            <div class="flex items-start gap-3">
              <div class="h-8 w-8 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400 shrink-0 mt-0.5">
                <Zap class="h-4 w-4" />
              </div>
              <div>
                <div class="font-bold text-[var(--ds-color-text-primary)] text-sm mb-1">{{ t('landing.workflow.step2Title') }}</div>
                <p class="text-3xs text-[var(--ds-color-text-description)] leading-relaxed m-0">{{ t('landing.workflow.step2Desc') }}</p>
              </div>
            </div>

            <div class="flex items-start gap-3">
              <div class="h-8 w-8 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 shrink-0 mt-0.5">
                <Crosshair class="h-4 w-4" />
              </div>
              <div>
                <div class="font-bold text-[var(--ds-color-text-primary)] text-sm mb-1">{{ t('landing.workflow.step3Title') }}</div>
                <p class="text-3xs text-[var(--ds-color-text-description)] leading-relaxed m-0">{{ t('landing.workflow.step3Desc') }}</p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 3. OKX 专线遥测带 -->
      <section id="execution" class="w-full border-y border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-inset)] py-4 px-4 sm:px-8">
        <div class="max-w-6xl xl:max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-xs sm:text-sm font-mono">
          <div class="text-[var(--ds-color-text-description)] tracking-wider font-medium flex items-center gap-2">
            <span class="h-1.5 w-1.5 rounded-full bg-[var(--ds-color-brand)]" />
            <span>{{ t('landing.executionBar.title') }}</span>
          </div>

          <div class="flex flex-wrap items-center justify-center gap-6 text-[var(--ds-color-text-secondary)]">
            <div class="flex items-center gap-2 px-3 py-1 rounded-full bg-[var(--ds-color-bg-surface-card)] border border-[var(--ds-color-border-default)]">
              <span class="h-2 w-2 rounded-full bg-[var(--ds-color-brand)] animate-pulse" aria-hidden="true" />
              <span class="font-semibold text-[var(--ds-color-text-primary)]">{{ t('landing.executionBar.okx') }}</span>
              <span class="text-[var(--ds-color-brand)] text-xs ms-0.5">({{ t('landing.executionBar.latencyOkx') }})</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 4. 为什么选择 AstraQuant (精密 Bento Grid 特性架构) -->
      <section id="features" class="w-full max-w-6xl xl:max-w-7xl px-4 sm:px-8 py-20 sm:py-28">
        <div class="text-center max-w-3xl mx-auto mb-14">
          <span class="rounded-full border border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-2)] px-3.5 py-1 text-xs font-mono text-[var(--ds-color-text-secondary)] uppercase tracking-wider font-semibold">
            {{ t('landing.features.tag') }}
          </span>
          <h2 class="mt-4 text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight text-[var(--ds-color-text-primary)] leading-tight">
            {{ t('landing.features.title') }}
          </h2>
          <p class="mt-3.5 text-sm sm:text-base md:text-lg text-[var(--ds-color-text-description)] leading-relaxed">
            {{ t('landing.features.subtitle') }}
          </p>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-3 gap-6 text-left">
          <!-- 特性 1: 7 梯队微观因子引擎 (Span 2) -->
          <div class="card md:col-span-2 rounded-2xl p-7 sm:p-8 flex flex-col justify-between group">
            <div>
              <div class="flex items-center justify-between mb-4">
                <span class="text-3xs font-mono font-bold tracking-wider text-cyan-400 uppercase bg-cyan-500/10 border border-cyan-500/20 px-2.5 py-0.5 rounded-full">
                  T0 - T4 MICROSTRUCTURE
                </span>
                <span class="text-xs font-mono text-[var(--ds-color-text-placeholder)]">T0 / T0.5 / T1 / T4</span>
              </div>
              <h3 class="text-xl sm:text-2xl font-bold text-[var(--ds-color-text-primary)] flex items-center gap-2.5">
                <Dna class="h-6 w-6 text-cyan-400 shrink-0" />
                <span>{{ t('landing.features.f2Title') }}</span>
              </h3>
              <p class="mt-3 text-sm text-[var(--ds-color-text-description)] leading-relaxed max-w-2xl">
                {{ t('landing.features.f2Desc') }}
              </p>
            </div>
            <!-- Mini Matrix Visualizer -->
            <div class="mt-6 pt-5 border-t border-[var(--ds-color-border-default)] grid grid-cols-2 sm:grid-cols-4 gap-3 font-mono text-xs">
              <div class="p-3 rounded-xl bg-[var(--ds-color-bg-surface-inset)] border border-[var(--ds-color-border-default)]">
                <div class="text-[var(--ds-color-text-placeholder)] text-3xs">T0 Funding</div>
                <div class="text-emerald-400 font-semibold mt-1">+0.0042%</div>
              </div>
              <div class="p-3 rounded-xl bg-[var(--ds-color-bg-surface-inset)] border border-[var(--ds-color-border-default)]">
                <div class="text-[var(--ds-color-text-placeholder)] text-3xs">T0.5 CVD</div>
                <div class="text-emerald-400 font-semibold mt-1">+8.5M U</div>
              </div>
              <div class="p-3 rounded-xl bg-[var(--ds-color-bg-surface-inset)] border border-[var(--ds-color-border-default)]">
                <div class="text-[var(--ds-color-text-placeholder)] text-3xs">T1 OBI</div>
                <div class="text-emerald-400 font-semibold mt-1">+32.5%</div>
              </div>
              <div class="p-3 rounded-xl bg-[var(--ds-color-bg-surface-inset)] border border-[var(--ds-color-border-default)]">
                <div class="text-[var(--ds-color-text-placeholder)] text-3xs">T4 MACD a</div>
                <div class="text-emerald-400 font-semibold mt-1">+12.8 a</div>
              </div>
            </div>
          </div>

          <!-- 特性 2: 24/7 AI 全自动量化交易 (Span 1) -->
          <div class="card rounded-2xl p-7 sm:p-8 flex flex-col justify-between group">
            <div>
              <div class="h-11 w-11 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-5">
                <Zap class="h-5 w-5" />
              </div>
              <h3 class="text-lg sm:text-xl font-bold text-[var(--ds-color-text-primary)]">{{ t('landing.features.f1Title') }}</h3>
              <p class="mt-3 text-sm text-[var(--ds-color-text-description)] leading-relaxed">{{ t('landing.features.f1Desc') }}</p>
            </div>
            <div class="mt-6 pt-4 border-t border-[var(--ds-color-border-default)] text-xs font-mono text-emerald-400 flex items-center gap-2">
              <span class="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span>24/7 AI AUTONOMOUS LOOP</span>
            </div>
          </div>

          <!-- 特性 3: 数理物理风控硬防线 (Span 1) -->
          <div class="card rounded-2xl p-7 sm:p-8 flex flex-col justify-between group">
            <div>
              <div class="h-11 w-11 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400 mb-5">
                <Crosshair class="h-5 w-5" />
              </div>
              <h3 class="text-lg sm:text-xl font-bold text-[var(--ds-color-text-primary)]">{{ t('landing.features.f3Title') }}</h3>
              <p class="mt-3 text-sm text-[var(--ds-color-text-description)] leading-relaxed">{{ t('landing.features.f3Desc') }}</p>
            </div>
            <div class="mt-6 pt-4 border-t border-[var(--ds-color-border-default)] text-xs font-mono text-[var(--ds-color-text-description)] flex items-center justify-between">
              <span>Fail-Closed</span>
              <span class="text-emerald-400 font-semibold">100% OCO</span>
            </div>
          </div>

          <!-- 特性 4: OKX 原生直连 & 本地私有化自部署 (Span 2) -->
          <div class="card md:col-span-2 rounded-2xl p-7 sm:p-8 flex flex-col justify-between group">
            <div>
              <div class="flex items-center justify-between mb-4">
                <span class="text-3xs font-mono font-bold tracking-wider text-emerald-400 uppercase bg-emerald-500/10 border border-emerald-500/20 px-2.5 py-0.5 rounded-full">
                  OKX NATIVE V5 · PRIVATE DEPLOYMENT
                </span>
                <span class="text-xs font-mono text-emerald-400">100% Self-Hosted</span>
              </div>
              <h3 class="text-xl sm:text-2xl font-bold text-[var(--ds-color-text-primary)] flex items-center gap-2.5">
                <Globe class="h-6 w-6 text-emerald-400 shrink-0" />
                <span>{{ t('landing.features.f4Title') }} · {{ t('landing.features.f5Title') }}</span>
              </h3>
              <p class="mt-3 text-sm text-[var(--ds-color-text-description)] leading-relaxed max-w-2xl">
                {{ t('landing.features.f4Desc') }}
              </p>
            </div>
            <div class="mt-6 pt-4 border-t border-[var(--ds-color-border-default)] flex flex-wrap items-center gap-6 text-xs font-mono text-[var(--ds-color-text-description)]">
              <span class="flex items-center gap-1.5"><Globe class="h-3.5 w-3.5 text-emerald-400" /> OKX V5 REST/WS</span>
              <span class="flex items-center gap-1.5"><ShieldCheck class="h-3.5 w-3.5 text-emerald-400" /> AES-256 Local</span>
              <span class="flex items-center gap-1.5"><TrendingUp class="h-3.5 w-3.5 text-emerald-400" /> TP1 / TP2 OCO</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 5. 交易所直连与手续费返现通道 -->
      <section id="referral" class="w-full max-w-6xl xl:max-w-7xl px-4 sm:px-8 py-20 sm:py-28 border-t border-[var(--ds-color-border-default)]">
        <div class="text-center max-w-3xl mx-auto mb-10">
          <span class="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3.5 py-1 text-xs font-mono text-emerald-400 uppercase tracking-wider font-semibold">
            {{ t('landing.referral.tag') }}
          </span>
          <h2 class="mt-4 text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight text-[var(--ds-color-text-primary)] leading-tight">
            {{ t('landing.referral.title') }}
          </h2>
          <p class="mt-3.5 text-sm sm:text-base md:text-lg text-[var(--ds-color-text-description)] leading-relaxed">
            {{ t('landing.referral.subtitle') }}
          </p>

          <!-- 访问线路切换（国内镜像 / 海外官网） -->
          <div class="mt-6 inline-flex items-center gap-2 rounded-xl border border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-2)] p-1 text-xs font-mono">
            <span class="px-2.5 text-[var(--ds-color-text-description)]">{{ t('landing.referral.mirrorLabel') }}</span>
            <button
              type="button"
              class="h-8 px-3 rounded-lg cursor-pointer transition-colors"
              :class="mirrorRegion === 'cn' ? 'bg-[var(--ds-color-bg-surface-card)] text-emerald-400 font-semibold border border-emerald-500/30' : 'text-[var(--ds-color-text-description)] hover:text-[var(--ds-color-text-primary)]'"
              @click="mirrorRegion = 'cn'"
            >
              {{ t('landing.referral.mirrorCn') }}
            </button>
            <button
              type="button"
              class="h-8 px-3 rounded-lg cursor-pointer transition-colors"
              :class="mirrorRegion === 'global' ? 'bg-[var(--ds-color-bg-surface-card)] text-emerald-400 font-semibold border border-emerald-500/30' : 'text-[var(--ds-color-text-description)] hover:text-[var(--ds-color-text-primary)]'"
              @click="mirrorRegion = 'global'"
            >
              {{ t('landing.referral.mirrorGlobal') }}
            </button>
          </div>
        </div>

        <!-- 量化返佣试算器 -->
        <div class="card rounded-2xl border border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-card)] p-6 sm:p-7 mb-10 text-left">
          <div class="flex flex-col lg:flex-row lg:items-center justify-between gap-6">
            <div class="space-y-4 flex-1">
              <div>
                <h3 class="text-lg font-bold text-[var(--ds-color-text-primary)]">
                  {{ t('landing.referral.calcTitle') }}
                </h3>
                <p class="mt-1 text-xs text-[var(--ds-color-text-description)]">
                  {{ t('landing.referral.calcSubtitle') }}
                </p>
              </div>

              <div class="flex flex-col sm:flex-row sm:items-center gap-4">
                <div class="space-y-1.5">
                  <div class="text-xs font-mono text-[var(--ds-color-text-placeholder)]">
                    {{ t('landing.referral.calcVolumeLabel') }}
                  </div>
                  <div class="flex flex-wrap gap-1.5">
                    <button
                      v-for="preset in VOLUME_PRESETS"
                      :key="preset"
                      type="button"
                      class="h-8 px-3 rounded-lg border text-xs font-mono cursor-pointer transition-colors"
                      :class="calcVolumeUsd === preset
                        ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400 font-semibold'
                        : 'border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-2)] text-[var(--ds-color-text-secondary)] hover:text-[var(--ds-color-text-primary)]'"
                      @click="calcVolumeUsd = preset"
                    >
                      {{ formatPreset(preset) }}
                    </button>
                  </div>
                </div>

                <div class="space-y-1.5">
                  <div class="text-xs font-mono text-[var(--ds-color-text-placeholder)]">
                    {{ t('landing.referral.calcVenueLabel') }}
                  </div>
                  <div class="flex flex-wrap gap-1.5">
                    <button
                      v-for="ch in promoChannels"
                      :key="ch.key"
                      type="button"
                      class="h-8 px-3 rounded-lg border text-xs font-mono cursor-pointer transition-colors"
                      :class="calcVenueKey === ch.key
                        ? 'border-emerald-500/40 bg-emerald-500/10 text-emerald-400 font-semibold'
                        : 'border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-2)] text-[var(--ds-color-text-secondary)] hover:text-[var(--ds-color-text-primary)]'"
                      @click="calcVenueKey = ch.key"
                    >
                      {{ ch.name }} ({{ ch.rebate }})
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <div class="grid grid-cols-3 gap-3 sm:gap-4 shrink-0 lg:min-w-[420px]">
              <div class="rounded-xl border border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-inset)] p-3.5">
                <div class="text-3xs font-mono text-[var(--ds-color-text-placeholder)]">
                  {{ t('landing.referral.calcMonthlyFee') }}
                </div>
                <div class="mt-1 text-lg sm:text-xl font-bold font-mono text-[var(--ds-color-text-primary)]">
                  {{ formatUsd(calcMonthlyFee) }}
                </div>
              </div>
              <div class="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3.5">
                <div class="text-3xs font-mono text-emerald-400">
                  {{ t('landing.referral.calcMonthlyRebate') }}
                </div>
                <div class="mt-1 text-lg sm:text-xl font-bold font-mono text-emerald-400">
                  +{{ formatUsd(calcMonthlyRebate) }}
                </div>
              </div>
              <div class="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3.5">
                <div class="text-3xs font-mono text-emerald-400">
                  {{ t('landing.referral.calcAnnualRebate') }}
                </div>
                <div class="mt-1 text-lg sm:text-xl font-bold font-mono text-emerald-400">
                  +{{ formatUsd(calcAnnualRebate) }}
                </div>
              </div>
            </div>
          </div>

          <div v-if="activeCalcVenue" class="mt-4 pt-4 border-t border-[var(--ds-color-border-default)] flex justify-end">
            <a
              :href="activeCalcVenue.invite_url"
              target="_blank"
              rel="noopener noreferrer"
              class="btn btn-primary h-10 px-5 rounded-xl text-sm font-semibold inline-flex items-center gap-2"
              @click="trackEvent('rebate_click', { exchange: activeCalcVenue.key, placement: 'landing_calculator', mirror: mirrorRegion })"
            >
              <span>{{ t('landing.referral.calcCta', undefined, { venue: activeCalcVenue.name }) }}</span>
              <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
              <ExternalLink class="h-4 w-4" aria-hidden="true" />
            </a>
          </div>
        </div>

        <!-- 专属通道卡片网格 (4 交易所) -->
        <div class="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-5 text-left">
          <div
            v-for="ch in promoChannels"
            :key="ch.key"
            class="card rounded-2xl p-6 flex flex-col justify-between transition-all"
            :class="ch.isApiSupported ? 'border-emerald-500/30' : ''"
          >
            <div>
              <div class="flex items-center justify-between mb-4 gap-2">
                <div class="flex items-center gap-2 flex-wrap">
                  <span class="font-bold text-lg font-mono text-[var(--ds-color-text-primary)]">{{ ch.name }}</span>
                  <span
                    class="rounded text-3xs font-mono px-2 py-0.5 border"
                    :class="ch.isApiSupported
                      ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                      : 'bg-[var(--ds-color-bg-surface-2)] border-[var(--ds-color-border-default)] text-[var(--ds-color-text-description)]'"
                  >
                    {{ ch.badge }}
                  </span>
                </div>
                <span
                  class="rounded-md text-xs font-mono font-semibold px-2.5 py-1 border shrink-0"
                  :class="ch.isApiSupported
                    ? 'bg-emerald-500/10 border-emerald-500/20 text-emerald-400'
                    : 'bg-[var(--ds-color-bg-surface-2)] border-[var(--ds-color-border-default)] text-[var(--ds-color-text-secondary)]'"
                >
                  {{ ch.rateTier }}
                </span>
              </div>

              <!-- 特殊说明说明行 -->
              <p class="text-xs text-[var(--ds-color-text-description)] mb-5 leading-relaxed min-h-8">
                {{ ch.note }}
              </p>

              <!-- 邀请码展示与快捷复制 -->
              <div v-if="ch.code" class="text-sm font-mono text-[var(--ds-color-text-secondary)] mb-5 bg-[var(--ds-color-bg-surface-inset)] p-3 rounded-xl border border-[var(--ds-color-border-default)] flex items-center justify-between gap-2">
                <span class="text-[var(--ds-color-text-placeholder)] text-xs">{{ t('landing.referral.codeLabel') }}</span>
                <div class="flex items-center gap-2 min-w-0">
                  <span
                    class="font-bold tracking-wider select-all truncate"
                    :class="ch.isApiSupported ? 'text-emerald-400' : 'text-[var(--ds-color-text-primary)]'"
                  >
                    {{ ch.code }}
                  </span>
                  <button
                    type="button"
                    class="h-7 px-2 rounded-md border border-[var(--ds-color-border-default)] hover:bg-[var(--ds-color-bg-hover)] text-3xs font-mono cursor-pointer inline-flex items-center gap-1"
                    :aria-label="copiedCodeKey === ch.key ? t('landing.referral.copiedCode') : t('landing.referral.copyCode')"
                    @click="copyChannelCode(ch.code, ch.key)"
                  >
                    <Check v-if="copiedCodeKey === ch.key" class="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
                    <Copy v-else class="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </div>
              </div>
            </div>

            <!-- 操作动作：前往开户 + 复制链接 -->
            <div class="pt-4 border-t border-[var(--ds-color-border-default)] flex items-center gap-2.5">
              <a
                :href="ch.invite_url"
                target="_blank"
                rel="noopener noreferrer"
                class="flex-1 h-11 rounded-xl text-sm font-semibold inline-flex items-center justify-center gap-2 transition-all shadow-md"
                :class="ch.isApiSupported ? 'btn btn-primary' : 'btn btn-ghost'"
                @click="trackEvent('rebate_click', { exchange: ch.key, placement: 'landing_card', mirror: mirrorRegion })"
              >
                <span>{{ t('landing.referral.openAccount') }}</span>
                <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
                <ExternalLink class="h-4 w-4" aria-hidden="true" />
              </a>

              <button
                type="button"
                class="h-11 px-3.5 rounded-xl border border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-2)] hover:bg-[var(--ds-color-bg-hover)] text-[var(--ds-color-text-secondary)] hover:text-[var(--ds-color-text-primary)] text-sm font-mono cursor-pointer inline-flex items-center gap-2 transition-colors"
                :aria-label="copiedChannelKey === ch.key ? t('landing.referral.copied') : t('landing.referral.copyLink')"
                @click="copyChannelUrl(ch.invite_url, ch.key)"
              >
                <Check v-if="copiedChannelKey === ch.key" class="h-4 w-4 text-emerald-400" aria-hidden="true" />
                <Copy v-else class="h-4 w-4" aria-hidden="true" />
              </button>
            </div>
          </div>
        </div>

        <!-- 兼容性声明警示框 -->
        <div class="mt-8 p-4 rounded-xl border border-amber-500/20 bg-amber-500/5 text-xs text-amber-500 text-center font-mono max-w-3xl mx-auto leading-relaxed">
          {{ t('landing.referral.compatibilityNotice') }}
        </div>

        <!-- 官方结算提示 -->
        <div class="mt-4 text-center text-xs font-mono text-[var(--ds-color-text-placeholder)]">
          {{ t('landing.referral.note') }}
        </div>
      </section>

      <!-- 5.5 姊妹项目联动：TradeSkill (astraquant.tech) -->
      <section id="ecosystem" class="w-full max-w-6xl xl:max-w-7xl px-4 sm:px-8 pb-20">
        <div class="card rounded-2xl border border-emerald-500/25 bg-[var(--ds-color-bg-surface-card)] p-7 sm:p-10 text-left flex flex-col lg:flex-row lg:items-center justify-between gap-8">
          <div class="space-y-4 max-w-2xl">
            <span class="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3 py-1 text-xs font-mono text-emerald-400 uppercase tracking-wider font-semibold inline-block">
              {{ t('landing.ecosystem.tag') }}
            </span>
            <h2 class="text-2xl sm:text-3xl font-extrabold tracking-tight text-[var(--ds-color-text-primary)] leading-snug">
              {{ t('landing.ecosystem.title') }}
            </h2>
            <p class="text-sm sm:text-base text-[var(--ds-color-text-description)] leading-relaxed">
              {{ t('landing.ecosystem.subtitle') }}
            </p>
            <div class="pt-2 flex flex-wrap items-center gap-3">
              <a
                :href="SKILLHUB_SITE"
                target="_blank"
                rel="noopener noreferrer"
                class="btn btn-primary h-11 px-5 rounded-xl text-sm font-semibold inline-flex items-center gap-2"
                @click="trackEvent('crosslink_click', { target: 'skillhub', placement: 'landing_ecosystem' })"
              >
                <Cpu class="h-4 w-4" aria-hidden="true" />
                <span>{{ t('landing.ecosystem.ctaPrimary') }}</span>
                <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
                <ExternalLink class="h-4 w-4" aria-hidden="true" />
              </a>
              <a
                :href="SKILLHUB_REPO"
                target="_blank"
                rel="noopener noreferrer"
                class="btn btn-ghost h-11 px-5 rounded-xl text-sm font-semibold inline-flex items-center gap-2"
                @click="trackEvent('crosslink_click', { target: 'crypto_trading_skills_repo', placement: 'landing_ecosystem' })"
              >
                <Github class="h-4 w-4" aria-hidden="true" />
                <span>{{ t('landing.ecosystem.ctaGithub') }}</span>
                <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
                <ExternalLink class="h-4 w-4" aria-hidden="true" />
              </a>
            </div>
          </div>

          <div class="grid grid-cols-3 gap-3 sm:gap-4 shrink-0">
            <div class="rounded-xl border border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-inset)] p-4 text-center">
              <div class="text-2xl sm:text-3xl font-extrabold font-mono text-emerald-400">
                {{ t('landing.ecosystem.stat1Val') }}
              </div>
              <div class="mt-1 text-xs font-mono text-[var(--ds-color-text-description)]">
                {{ t('landing.ecosystem.stat1Label') }}
              </div>
            </div>
            <div class="rounded-xl border border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-inset)] p-4 text-center">
              <div class="text-2xl sm:text-3xl font-extrabold font-mono text-[var(--ds-color-text-primary)]">
                {{ t('landing.ecosystem.stat2Val') }}
              </div>
              <div class="mt-1 text-xs font-mono text-[var(--ds-color-text-description)]">
                {{ t('landing.ecosystem.stat2Label') }}
              </div>
            </div>
            <div class="rounded-xl border border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-inset)] p-4 text-center">
              <div class="text-2xl sm:text-3xl font-extrabold font-mono text-emerald-400">
                {{ t('landing.ecosystem.stat3Val') }}
              </div>
              <div class="mt-1 text-xs font-mono text-[var(--ds-color-text-description)]">
                {{ t('landing.ecosystem.stat3Label') }}
              </div>
            </div>
          </div>
        </div>
      </section>

      <!-- 6. 极速部署开箱即用 (QUICKSTART) -->
      <section class="w-full max-w-6xl xl:max-w-7xl px-4 sm:px-8 py-20 sm:py-28 border-t border-[var(--ds-color-border-default)] text-center">
        <span class="rounded-full border border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-2)] px-3.5 py-1 text-xs font-mono text-[var(--ds-color-text-secondary)] uppercase tracking-wider font-semibold">
          {{ t('landing.quickstart.tag') }}
        </span>
        <h2 class="mt-4 text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight text-[var(--ds-color-text-primary)] leading-tight">
          {{ t('landing.quickstart.title') }}
        </h2>
        <p class="mt-3.5 text-sm sm:text-base md:text-lg text-[var(--ds-color-text-description)] max-w-xl mx-auto leading-relaxed">
          {{ t('landing.quickstart.subtitle') }}
        </p>

        <!-- 极客终端工位卡片 -->
        <div class="card mt-8 w-full max-w-2xl mx-auto rounded-2xl border border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-card)] overflow-hidden shadow-2xl text-left">
          <!-- 终端标题条 -->
          <div class="px-4 py-2.5 bg-[var(--ds-color-bg-surface-inset)] border-b border-[var(--ds-color-border-default)] flex items-center justify-between text-3xs font-mono text-[var(--ds-color-text-placeholder)] select-none">
            <span class="flex items-center gap-1.5">
              <span class="h-2 w-2 rounded-full bg-[var(--ds-color-brand)]" />
              <span>bash — astraquant@localhost:~</span>
            </span>
            <span class="text-3xs uppercase">DOCKER COMPOSE READY</span>
          </div>

          <!-- 终端内容区 -->
          <div class="p-5 flex items-center justify-between gap-4 font-mono text-xs sm:text-sm bg-black/30">
            <div class="flex items-center gap-3 overflow-x-auto text-[var(--ds-color-text-secondary)]">
              <span class="text-emerald-400 font-bold select-none text-base">&gt;</span>
              <span class="text-[var(--ds-color-text-primary)] select-all whitespace-nowrap">{{ DOCKER_CMD }}</span>
            </div>
            <button
              type="button"
              class="btn btn-ghost h-9 px-3.5 text-xs font-semibold cursor-pointer flex items-center gap-2 shrink-0"
              :aria-label="copiedCmd ? t('landing.quickstart.copied') : t('landing.quickstart.copyCmd')"
              @click="copyCommand"
            >
              <Check v-if="copiedCmd" class="h-3.5 w-3.5 text-emerald-400" />
              <Copy v-else class="h-3.5 w-3.5" />
              <span>{{ copiedCmd ? t('landing.quickstart.copied') : t('landing.quickstart.copyCmd') }}</span>
            </button>
          </div>
        </div>
      </section>
    </main>

    <!-- 7. 生态页脚 -->
    <footer class="w-full border-t border-[var(--ds-color-border-default)] bg-[var(--ds-color-bg-surface-inset)] py-12 px-4 sm:px-8 text-sm text-[var(--ds-color-text-description)]">
      <div class="max-w-6xl xl:max-w-7xl mx-auto flex flex-col md:flex-row items-start justify-between gap-10">
        <div class="max-w-md">
          <div class="flex items-center gap-2.5">
            <img src="/favicon.svg" alt="AstraQuant Logo" class="h-6 w-6 rounded" />
            <span class="font-mono font-bold text-base text-[var(--ds-color-text-primary)]">AstraQuant</span>
          </div>
          <p class="mt-3 text-xs sm:text-sm text-[var(--ds-color-text-placeholder)] leading-relaxed">
            {{ t('landing.footer.brandDesc') }}
          </p>
          <div class="mt-4 text-xs font-mono text-[var(--ds-color-text-placeholder)]">
            © 2026 AstraQuant. All rights reserved.
          </div>
        </div>

        <div class="flex flex-wrap gap-14 font-mono text-xs sm:text-sm">
          <div>
            <div class="font-bold text-[var(--ds-color-text-primary)] uppercase tracking-wider mb-3">
              {{ t('landing.footer.productTitle') }}
            </div>
            <ul class="space-y-2 list-none p-0 m-0">
              <li><RouterLink to="/trading" class="hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-description)]">{{ t('landing.footer.trading') }}</RouterLink></li>
              <li><RouterLink to="/factors" class="hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-description)]">{{ t('landing.footer.factors') }}</RouterLink></li>
              <li><RouterLink to="/news" class="hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-description)]">{{ t('landing.footer.news') }}</RouterLink></li>
              <li><RouterLink to="/lab" class="hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-description)]">{{ t('landing.footer.lab') }}</RouterLink></li>
              <li><RouterLink to="/history" class="hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-description)]">{{ t('landing.footer.ledger') }}</RouterLink></li>
            </ul>
          </div>

          <div>
            <div class="font-bold text-[var(--ds-color-text-primary)] uppercase tracking-wider mb-3">
              {{ t('landing.footer.platformTitle') }}
            </div>
            <ul class="space-y-2 list-none p-0 m-0">
              <li><RouterLink to="/docs" class="hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-description)]">{{ t('landing.footer.docs') }}</RouterLink></li>
              <li><RouterLink to="/admin" class="hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-description)]">{{ t('landing.footer.console') }}</RouterLink></li>
              <li>
                <button
                  type="button"
                  class="hover:text-[var(--ds-color-text-primary)] text-[var(--ds-color-text-description)] bg-transparent border-0 p-0 cursor-pointer text-start text-xs sm:text-sm"
                  @click="openExternal(OFFICIAL_REPO)"
                >
                  GitHub
                </button>
              </li>
            </ul>
          </div>

          <div>
            <div class="font-bold text-[var(--ds-color-text-primary)] uppercase tracking-wider mb-3">
              {{ t('landing.footer.ecosystemTitle') }}
            </div>
            <ul class="space-y-2 list-none p-0 m-0">
              <li>
                <a
                  :href="SKILLHUB_SITE"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-description)] inline-flex items-center gap-1"
                  @click="trackEvent('crosslink_click', { target: 'skillhub', placement: 'landing_footer' })"
                >
                  <span>{{ t('landing.footer.tradeSkill') }}</span>
                  <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
                  <ExternalLink class="h-3.5 w-3.5 opacity-60" aria-hidden="true" />
                </a>
              </li>
              <li>
                <a
                  :href="SKILLHUB_REBATES_URL"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-description)] inline-flex items-center gap-1"
                  @click="trackEvent('crosslink_click', { target: 'skillhub_rebates', placement: 'landing_footer' })"
                >
                  <span>{{ t('landing.footer.rebatesGuide') }}</span>
                  <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
                  <ExternalLink class="h-3.5 w-3.5 opacity-60" aria-hidden="true" />
                </a>
              </li>
              <li>
                <a
                  :href="SKILLHUB_REPO"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="hover:text-[var(--ds-color-text-primary)] no-underline text-[var(--ds-color-text-description)] inline-flex items-center gap-1"
                  @click="trackEvent('crosslink_click', { target: 'crypto_trading_skills_repo', placement: 'landing_footer' })"
                >
                  <span>{{ t('landing.footer.skillsRepo') }}</span>
                  <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
                  <ExternalLink class="h-3.5 w-3.5 opacity-60" aria-hidden="true" />
                </a>
              </li>
            </ul>
          </div>
        </div>
      </div>

      <div class="max-w-6xl xl:max-w-7xl mx-auto mt-8 pt-6 border-t border-[var(--ds-color-border-default)] text-xs text-[var(--ds-color-text-placeholder)] leading-relaxed">
        {{ t('landing.footer.securityNote') }}
      </div>
    </footer>
  </div>
</template>

<style scoped>
.landing-page {
  background-color: var(--ds-color-bg-page);
  color: var(--ds-color-text-secondary);
}

.landing-nav {
  background-color: var(--ds-color-bg-overlay);
  border-color: var(--ds-color-border-default);
}

.landing-grid-bg {
  background-image:
    linear-gradient(to right, var(--ds-color-border-default) 1px, transparent 1px),
    linear-gradient(to bottom, var(--ds-color-border-default) 1px, transparent 1px);
  background-size: 48px 48px;
}
</style>
