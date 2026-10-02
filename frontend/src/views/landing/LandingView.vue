<script setup lang="ts">
/**
 * LandingView.vue · AstraQuant 官方落地页
 * ---------------------------------------------------------------------------
 * 极简开源调性重构（对标 ccswitch.io 清爽干净、零冗余装饰）：
 * - 顶栏移除与主页重复的跳转按钮，导航精简高价值入口（实盘/文档/后台/返佣/GitHub）
 * - 汉堡菜单优化：移除空泛锚点，只保留关键业务与资源导航
 * - Hero 核心行动：主按钮启动终端，副按钮直达 GitHub 开源仓库
 * - 引入官方专属交易所开户与手续费返现通道（动态自后端加载，安全合规）
 * - 6 宫格核心能力、Docker 一键启动卡片与极简生态页脚
 */
import { ref, onMounted } from 'vue';
import { useRouter } from 'vue-router';
import {
  ArrowRight,
  ShieldCheck,
  Globe,
  Landmark,
  Crosshair,
  Dna,
  Zap,
  Copy,
  Check,
  Menu,
  X,
  Github,
  ExternalLink,
} from 'lucide-vue-next';
import { useI18n } from '../../composables/useI18n';
import { OFFICIAL_REPO } from '../../config/version';
import { useReferralChannels } from '../../composables/useReferralChannels';

const router = useRouter();
const { t, currentLocale, toggleLocale } = useI18n();
const { channels, load: loadChannels } = useReferralChannels();

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
const DOCKER_CMD = 'git clone https://github.com/AstraQuant/AstraQuant.git && cd AstraQuant && docker compose up -d';

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

// 返佣通道链接复制
const copiedChannelKey = ref<string | null>(null);

async function copyChannelUrl(url: string, key: string) {
  try {
    if (navigator?.clipboard?.writeText) {
      await navigator.clipboard.writeText(url);
    }
  } catch {
    // 降级兜底静默处理
  }
  copiedChannelKey.value = key;
  setTimeout(() => {
    if (copiedChannelKey.value === key) {
      copiedChannelKey.value = null;
    }
  }, 2000);
}

onMounted(() => {
  loadChannels();
});
</script>

<template>
  <div class="min-h-screen w-full bg-[#07080c] text-zinc-100 flex flex-col font-sans selection:bg-emerald-500 selection:text-black relative overflow-x-hidden">
    <!-- 顶部量子暗色微光晕环境光（增强进深与科技质感，防止高分屏下纯黑死板） -->
    <div class="pointer-events-none absolute top-0 left-1/2 -translate-x-1/2 w-[1100px] h-[640px] bg-gradient-to-b from-emerald-500/10 via-cyan-500/5 to-transparent blur-3xl opacity-60" aria-hidden="true" />

    <!-- 1. 全局清爽单行导航栏（不堆叠重复按钮） -->
    <header class="sticky top-0 z-50 h-16 w-full border-b border-white/[0.04] bg-[#07080c]/80 backdrop-blur-xl px-4 sm:px-8 flex items-center justify-between">
      <div class="w-full max-w-7xl mx-auto flex items-center justify-between">
        <div class="flex items-center gap-8">
          <RouterLink to="/" class="flex items-center gap-2.5 no-underline cursor-pointer group" :aria-label="t('brand.name')">
            <img src="/favicon.svg" alt="AstraQuant Logo" class="h-6 w-6 rounded transition-opacity group-hover:opacity-80" />
            <span class="font-bold tracking-tight text-base sm:text-lg text-white font-mono">
              AstraQuant
            </span>
          </RouterLink>

          <!-- 桌面端精炼高价值导航 -->
          <nav class="hidden md:flex items-center gap-6 text-sm text-zinc-400" aria-label="Landing Navigation">
            <RouterLink to="/trading" class="hover:text-white transition-colors no-underline">
              {{ t('landing.nav.trading') }}
            </RouterLink>
            <RouterLink to="/docs" class="hover:text-white transition-colors no-underline">
              {{ t('landing.nav.docs') }}
            </RouterLink>
            <a href="#referral" class="hover:text-white transition-colors no-underline">
              {{ t('landing.nav.referral') }}
            </a>
            <RouterLink to="/admin/login" class="hover:text-white transition-colors no-underline">
              {{ t('landing.nav.console') }}
            </RouterLink>
            <button
              type="button"
              class="hover:text-white transition-colors cursor-pointer bg-transparent border-0 inline-flex items-center gap-1.5 text-sm text-zinc-400 p-0"
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
            class="h-8 px-2.5 text-xs font-mono cursor-pointer text-zinc-400 hover:text-white bg-transparent border-0 transition-colors"
            :aria-label="currentLocale === 'zh-CN' ? 'Switch to English' : '切换至中文'"
            @click="toggleLocale"
          >
            {{ currentLocale === 'zh-CN' ? 'EN' : '中文' }}
          </button>

          <!-- 移动端汉堡切换 -->
          <button
            type="button"
            class="md:hidden p-1.5 rounded-lg text-zinc-400 hover:text-white cursor-pointer bg-transparent border-0"
            aria-label="Toggle Navigation Menu"
            @click="mobileMenuOpen = !mobileMenuOpen"
          >
            <Menu v-if="!mobileMenuOpen" class="h-5 w-5" />
            <X v-else class="h-5 w-5" />
          </button>
        </div>
      </div>
    </header>

    <!-- 移动端优化后的折叠导航 -->
    <div
      v-if="mobileMenuOpen"
      class="md:hidden w-full bg-[#0b0d14] border-b border-white/[0.06] px-4 py-4 flex flex-col gap-3 text-sm font-medium text-zinc-300"
    >
      <RouterLink to="/trading" class="py-1.5 hover:text-white no-underline" @click="mobileMenuOpen = false">
        {{ t('landing.nav.trading') }}
      </RouterLink>
      <RouterLink to="/docs" class="py-1.5 hover:text-white no-underline" @click="mobileMenuOpen = false">
        {{ t('landing.nav.docs') }}
      </RouterLink>
      <a href="#referral" class="py-1.5 hover:text-white no-underline" @click="mobileMenuOpen = false">
        {{ t('landing.nav.referral') }}
      </a>
      <RouterLink to="/admin/login" class="py-1.5 hover:text-white no-underline" @click="mobileMenuOpen = false">
        {{ t('landing.nav.console') }}
      </RouterLink>
      <button
        type="button"
        class="py-1.5 hover:text-white text-zinc-300 flex items-center gap-2 bg-transparent border-0 cursor-pointer text-sm"
        @click="mobileMenuOpen = false; openExternal(OFFICIAL_REPO)"
      >
        <Github class="h-4 w-4" aria-hidden="true" />
        <span>{{ t('landing.nav.github') }}</span>
      </button>
    </div>

    <!-- 2. 主页面内容 -->
    <main class="flex-1 w-full flex flex-col items-center">
      <!-- HERO 首屏：居中开阔、从容自信（解封 max-w-4xl 锁死，大屏从容展布） -->
      <section class="w-full max-w-5xl lg:max-w-6xl px-4 sm:px-8 pt-24 sm:pt-36 pb-24 flex flex-col items-center text-center relative z-10">
        <!-- 主标题 -->
        <h1 class="text-4xl sm:text-5xl md:text-6xl lg:text-7xl font-extrabold tracking-tight text-white leading-[1.12] max-w-5xl">
          {{ t('landing.hero.titlePart1') }}
          <span class="text-emerald-400 block mt-3">
            {{ t('landing.hero.titleHighlight') }}
          </span>
        </h1>

        <!-- 副标题 -->
        <p class="mt-8 text-base sm:text-lg md:text-xl text-zinc-400 leading-relaxed max-w-3xl">
          {{ t('landing.hero.subtitle') }}
        </p>

        <!-- 行动按钮：启动终端 + 跳转 GitHub -->
        <div class="mt-10 flex flex-wrap items-center justify-center gap-4">
          <button
            type="button"
            class="h-12 sm:h-13 px-8 sm:px-9 rounded-xl bg-emerald-400 hover:bg-emerald-300 text-black text-sm sm:text-base font-bold cursor-pointer inline-flex items-center gap-2.5 shadow-xl shadow-emerald-500/15 transition-all active:scale-95"
            @click="navTo('/trading')"
          >
            <span>{{ t('landing.hero.ctaPrimary') }}</span>
            <ArrowRight class="h-4.5 w-4.5" />
          </button>

          <button
            type="button"
            class="h-12 sm:h-13 px-7 sm:px-8 rounded-xl border border-white/[0.1] bg-zinc-900/60 hover:bg-zinc-800 text-zinc-200 text-sm sm:text-base font-medium transition-colors inline-flex items-center gap-2.5 cursor-pointer"
            @click="openExternal(OFFICIAL_REPO)"
          >
            <Github class="h-4.5 w-4.5" aria-hidden="true" />
            <span>{{ t('landing.hero.ctaGithub') }}</span>
          </button>
        </div>

        <!-- 平台支持轻标识 -->
        <div class="mt-8 text-xs font-mono text-zinc-500">
          {{ t('landing.quickstart.platformSupport') }}
        </div>
      </section>

      <!-- 3. OKX 原生直连遥测带（单一交易所执行通道） -->
      <section id="execution" class="w-full border-y border-white/[0.04] bg-[#090b10]/60 py-5 px-4 sm:px-8">
        <div class="max-w-6xl xl:max-w-7xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 text-xs sm:text-sm font-mono">
          <div class="text-zinc-400 uppercase tracking-wider font-medium">
            {{ t('landing.executionBar.title') }}
          </div>

          <div class="flex flex-wrap items-center justify-center gap-6 sm:gap-10 text-zinc-300">
            <div class="flex items-center gap-2">
              <span class="h-2 w-2 rounded-full bg-emerald-400 animate-pulse" aria-hidden="true" />
              <span class="font-semibold">{{ t('landing.executionBar.okx') }}</span>
              <span class="text-emerald-400 text-xs ms-0.5">({{ t('landing.executionBar.latencyOkx') }})</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 4. 为什么选择 AstraQuant (经典 6 宫格特性卡片) -->
      <section id="features" class="w-full max-w-6xl xl:max-w-7xl px-4 sm:px-8 py-24 sm:py-32">
        <div class="text-center max-w-3xl mx-auto mb-16">
          <span class="rounded-full border border-white/[0.08] bg-zinc-900/60 px-3.5 py-1.5 text-xs font-mono text-zinc-300 uppercase tracking-wider font-semibold">
            {{ t('landing.features.tag') }}
          </span>
          <h2 class="mt-5 text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight text-white leading-tight">
            {{ t('landing.features.title') }}
          </h2>
          <p class="mt-4 text-sm sm:text-base md:text-lg text-zinc-400 leading-relaxed">
            {{ t('landing.features.subtitle') }}
          </p>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6 lg:gap-8 text-left">
          <!-- 特性 1: 24/7 AI 自动化交易 -->
          <div class="rounded-2xl border border-white/[0.08] bg-[#0c0e15] p-7 sm:p-8 hover:border-emerald-500/30 hover:shadow-xl hover:shadow-emerald-500/5 transition-all">
            <div class="h-11 w-11 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-5">
              <Zap class="h-5 w-5" />
            </div>
            <h3 class="text-lg sm:text-xl font-bold text-white">{{ t('landing.features.f1Title') }}</h3>
            <p class="mt-3 text-sm text-zinc-400 leading-relaxed">{{ t('landing.features.f1Desc') }}</p>
          </div>

          <!-- 特性 2: 7 梯队量化因子引擎 -->
          <div class="rounded-2xl border border-white/[0.08] bg-[#0c0e15] p-7 sm:p-8 hover:border-emerald-500/30 hover:shadow-xl hover:shadow-emerald-500/5 transition-all">
            <div class="h-11 w-11 rounded-xl bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400 mb-5">
              <Dna class="h-5 w-5" />
            </div>
            <h3 class="text-lg sm:text-xl font-bold text-white">{{ t('landing.features.f2Title') }}</h3>
            <p class="mt-3 text-sm text-zinc-400 leading-relaxed">{{ t('landing.features.f2Desc') }}</p>
          </div>

          <!-- 特性 3: 数理风控 -->
          <div class="rounded-2xl border border-white/[0.08] bg-[#0c0e15] p-7 sm:p-8 hover:border-emerald-500/30 hover:shadow-xl hover:shadow-emerald-500/5 transition-all">
            <div class="h-11 w-11 rounded-xl bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400 mb-5">
              <Crosshair class="h-5 w-5" />
            </div>
            <h3 class="text-lg sm:text-xl font-bold text-white">{{ t('landing.features.f3Title') }}</h3>
            <p class="mt-3 text-sm text-zinc-400 leading-relaxed">{{ t('landing.features.f3Desc') }}</p>
          </div>

          <!-- 特性 4: OKX 原生深度直连与统一账户 -->
          <div class="rounded-2xl border border-white/[0.08] bg-[#0c0e15] p-7 sm:p-8 hover:border-emerald-500/30 hover:shadow-xl hover:shadow-emerald-500/5 transition-all">
            <div class="h-11 w-11 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-5">
              <Globe class="h-5 w-5" />
            </div>
            <h3 class="text-lg sm:text-xl font-bold text-white">{{ t('landing.features.f4Title') }}</h3>
            <p class="mt-3 text-sm text-zinc-400 leading-relaxed">{{ t('landing.features.f4Desc') }}</p>
          </div>

          <!-- 特性 5: 本地私有 -->
          <div class="rounded-2xl border border-white/[0.08] bg-[#0c0e15] p-7 sm:p-8 hover:border-emerald-500/30 hover:shadow-xl hover:shadow-emerald-500/5 transition-all">
            <div class="h-11 w-11 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-5">
              <ShieldCheck class="h-5 w-5" />
            </div>
            <h3 class="text-lg sm:text-xl font-bold text-white">{{ t('landing.features.f5Title') }}</h3>
            <p class="mt-3 text-sm text-zinc-400 leading-relaxed">{{ t('landing.features.f5Desc') }}</p>
          </div>

          <!-- 特性 6: 极客工程 -->
          <div class="rounded-2xl border border-white/[0.08] bg-[#0c0e15] p-7 sm:p-8 hover:border-emerald-500/30 hover:shadow-xl hover:shadow-emerald-500/5 transition-all">
            <div class="h-11 w-11 rounded-xl bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 mb-5">
              <Landmark class="h-5 w-5" />
            </div>
            <h3 class="text-lg sm:text-xl font-bold text-white">{{ t('landing.features.f6Title') }}</h3>
            <p class="mt-3 text-sm text-zinc-400 leading-relaxed">{{ t('landing.features.f6Desc') }}</p>
          </div>
        </div>
      </section>

      <!-- 5. OKX 专属开户与手续费返现通道 (REFERRAL PROMO) -->
      <section id="referral" class="w-full max-w-6xl xl:max-w-7xl px-4 sm:px-8 py-24 sm:py-32 border-t border-white/[0.04]">
        <div class="text-center max-w-3xl mx-auto mb-16">
          <span class="rounded-full border border-emerald-500/20 bg-emerald-500/10 px-3.5 py-1.5 text-xs font-mono text-emerald-400 uppercase tracking-wider font-semibold">
            {{ t('landing.referral.tag') }}
          </span>
          <h2 class="mt-5 text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight text-white leading-tight">
            {{ t('landing.referral.title') }}
          </h2>
          <p class="mt-4 text-sm sm:text-base md:text-lg text-zinc-400 leading-relaxed">
            {{ t('landing.referral.subtitle') }}
          </p>
        </div>

        <!-- OKX 专属返佣卡片网格（单通道时居中收窄） -->
        <div
          v-if="channels.length"
          class="grid grid-cols-1 gap-6 text-left"
          :class="channels.length === 1 ? 'max-w-lg mx-auto' : 'md:grid-cols-2 lg:grid-cols-3'"
        >
          <div
            v-for="ch in channels"
            :key="ch.key"
            class="rounded-2xl border border-white/[0.08] bg-[#0c0e15] p-7 sm:p-8 flex flex-col justify-between hover:border-emerald-500/30 hover:shadow-xl hover:shadow-emerald-500/5 transition-all"
          >
            <div>
              <div class="flex items-center justify-between mb-5">
                <span class="font-bold text-lg text-white font-mono">{{ ch.name }}</span>
                <span class="rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-xs font-mono px-2.5 py-0.5">
                  {{ t('landing.referral.rateTier') }}
                </span>
              </div>

              <!-- 邀请码展示（若存在） -->
              <div v-if="ch.code" class="text-sm font-mono text-zinc-400 mb-5 bg-[#07080c] p-3 rounded-xl border border-white/[0.06] flex items-center justify-between">
                <span class="text-zinc-500">{{ t('landing.referral.codeLabel') }}</span>
                <span class="text-zinc-200 font-bold select-all">{{ ch.code }}</span>
              </div>
            </div>

            <!-- 操作动作：前往开户 + 复制链接 -->
            <div class="pt-5 border-t border-white/[0.06] flex items-center gap-3">
              <button
                type="button"
                class="flex-1 h-11 rounded-xl bg-emerald-400 hover:bg-emerald-300 text-black text-sm font-semibold inline-flex items-center justify-center gap-2 cursor-pointer transition-all active:scale-95"
                @click="openExternal(ch.invite_url)"
              >
                <span>{{ t('landing.referral.openAccount') }}</span>
                <ExternalLink class="h-4 w-4" aria-hidden="true" />
              </button>

              <button
                type="button"
                class="h-11 px-4 rounded-xl border border-white/[0.1] bg-zinc-900/60 hover:bg-zinc-800 text-zinc-300 hover:text-white text-sm font-mono cursor-pointer inline-flex items-center gap-2 transition-colors"
                :aria-label="copiedChannelKey === ch.key ? t('landing.referral.copied') : t('landing.referral.copyLink')"
                @click="copyChannelUrl(ch.invite_url, ch.key)"
              >
                <Check v-if="copiedChannelKey === ch.key" class="h-4 w-4 text-emerald-400" />
                <Copy v-else class="h-4 w-4" />
              </button>
            </div>
          </div>
        </div>

        <!-- 官方结算提示 -->
        <div class="mt-8 text-center text-xs font-mono text-zinc-500">
          {{ t('landing.referral.note') }}
        </div>
      </section>

      <!-- 6. 极速部署开箱即用 (QUICKSTART) -->
      <section class="w-full max-w-6xl xl:max-w-7xl px-4 sm:px-8 py-20 sm:py-28 border-t border-white/[0.04] text-center">
        <span class="rounded-full border border-white/[0.08] bg-zinc-900/60 px-3.5 py-1.5 text-xs font-mono text-zinc-300 uppercase tracking-wider font-semibold">
          {{ t('landing.quickstart.tag') }}
        </span>
        <h2 class="mt-4 text-3xl sm:text-4xl lg:text-5xl font-extrabold tracking-tight text-white leading-tight">
          {{ t('landing.quickstart.title') }}
        </h2>
        <p class="mt-3.5 text-sm sm:text-base md:text-lg text-zinc-400 max-w-xl mx-auto leading-relaxed">
          {{ t('landing.quickstart.subtitle') }}
        </p>

        <!-- 一键复制终端框 -->
        <div class="mt-8 w-full max-w-2xl mx-auto rounded-2xl border border-white/[0.08] bg-[#0c0e15] px-5 py-4 flex items-center justify-between gap-4 font-mono text-sm text-left shadow-2xl">
          <div class="flex items-center gap-3 overflow-x-auto text-zinc-300">
            <span class="text-emerald-400 font-bold select-none text-base">&gt;</span>
            <span class="text-zinc-200 select-all whitespace-nowrap">{{ DOCKER_CMD }}</span>
          </div>
          <button
            type="button"
            class="px-3.5 py-1.5 rounded-lg bg-zinc-800 hover:bg-zinc-700 text-xs font-semibold text-zinc-200 hover:text-white transition-colors cursor-pointer flex items-center gap-2 shrink-0 border border-white/[0.06]"
            :aria-label="copiedCmd ? t('landing.quickstart.copied') : t('landing.quickstart.copyCmd')"
            @click="copyCommand"
          >
            <Check v-if="copiedCmd" class="h-3.5 w-3.5 text-emerald-400" />
            <Copy v-else class="h-3.5 w-3.5" />
            <span>{{ copiedCmd ? t('landing.quickstart.copied') : t('landing.quickstart.copyCmd') }}</span>
          </button>
        </div>
      </section>
    </main>

    <!-- 8. 生态页脚 -->
    <footer class="w-full border-t border-white/[0.04] bg-[#050608] py-12 px-4 sm:px-8 text-sm text-zinc-400">
      <div class="max-w-6xl xl:max-w-7xl mx-auto flex flex-col md:flex-row items-start justify-between gap-10">
        <div class="max-w-md">
          <div class="flex items-center gap-2.5">
            <img src="/favicon.svg" alt="AstraQuant Logo" class="h-6 w-6 rounded" />
            <span class="font-mono font-bold text-base text-white">AstraQuant</span>
          </div>
          <p class="mt-3 text-xs sm:text-sm text-zinc-500 leading-relaxed">
            {{ t('landing.footer.brandDesc') }}
          </p>
          <div class="mt-4 text-xs font-mono text-zinc-600">
            © 2026 AstraQuant. All rights reserved.
          </div>
        </div>

        <div class="flex flex-wrap gap-14 font-mono text-xs sm:text-sm">
          <div>
            <div class="font-bold text-white uppercase tracking-wider mb-3">
              {{ t('landing.footer.productTitle') }}
            </div>
            <ul class="space-y-2 list-none p-0 m-0">
              <li><RouterLink to="/trading" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.trading') }}</RouterLink></li>
              <li><RouterLink to="/factors" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.factors') }}</RouterLink></li>
              <li><RouterLink to="/news" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.news') }}</RouterLink></li>
              <li><RouterLink to="/lab" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.lab') }}</RouterLink></li>
              <li><RouterLink to="/history" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.ledger') }}</RouterLink></li>
            </ul>
          </div>

          <div>
            <div class="font-bold text-white uppercase tracking-wider mb-3">
              {{ t('landing.footer.platformTitle') }}
            </div>
            <ul class="space-y-2 list-none p-0 m-0">
              <li><RouterLink to="/docs" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.docs') }}</RouterLink></li>
              <li><RouterLink to="/admin" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.console') }}</RouterLink></li>
              <li>
                <button
                  type="button"
                  class="hover:text-white text-zinc-400 bg-transparent border-0 p-0 cursor-pointer text-start text-xs sm:text-sm"
                  @click="openExternal(OFFICIAL_REPO)"
                >
                  GitHub
                </button>
              </li>
            </ul>
          </div>
        </div>
      </div>

      <div class="max-w-6xl xl:max-w-7xl mx-auto mt-8 pt-6 border-t border-white/[0.04] text-xs text-zinc-600 leading-relaxed">
        {{ t('landing.footer.securityNote') }}
      </div>
    </footer>
  </div>
</template>
