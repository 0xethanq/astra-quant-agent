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
    <!-- 1. 全局清爽单行导航栏（不堆叠重复按钮） -->
    <header class="sticky top-0 z-50 h-16 w-full border-b border-white/[0.04] bg-[#07080c]/80 backdrop-blur-xl px-4 sm:px-8 flex items-center justify-between">
      <div class="flex items-center gap-8">
        <RouterLink to="/" class="flex items-center gap-2.5 no-underline cursor-pointer group" :aria-label="t('brand.name')">
          <img src="/favicon.svg" alt="AstraQuant Logo" class="h-6 w-6 rounded transition-opacity group-hover:opacity-80" />
          <span class="font-bold tracking-tight text-base text-white font-mono">
            AstraQuant
          </span>
        </RouterLink>

        <!-- 桌面端精炼高价值导航 -->
        <nav class="hidden md:flex items-center gap-6 text-xs text-zinc-400" aria-label="Landing Navigation">
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
            class="hover:text-white transition-colors cursor-pointer bg-transparent border-0 inline-flex items-center gap-1.5 text-xs text-zinc-400 p-0"
            @click="openExternal(OFFICIAL_REPO)"
          >
            <Github class="h-3.5 w-3.5" aria-hidden="true" />
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
    </header>

    <!-- 移动端优化后的折叠导航 -->
    <div
      v-if="mobileMenuOpen"
      class="md:hidden w-full bg-[#0b0d14] border-b border-white/[0.06] px-4 py-4 flex flex-col gap-3 text-xs font-medium text-zinc-300"
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
        class="py-1.5 hover:text-white text-zinc-300 flex items-center gap-2 bg-transparent border-0 cursor-pointer text-xs"
        @click="mobileMenuOpen = false; openExternal(OFFICIAL_REPO)"
      >
        <Github class="h-4 w-4" aria-hidden="true" />
        <span>{{ t('landing.nav.github') }}</span>
      </button>
    </div>

    <!-- 2. 主页面内容 -->
    <main class="flex-1 w-full flex flex-col items-center">
      <!-- HERO 首屏：居中开阔、从容自信 -->
      <section class="w-full max-w-4xl px-4 sm:px-6 pt-20 sm:pt-28 pb-20 flex flex-col items-center text-center">
        <!-- 主标题 -->
        <h1 class="text-3xl sm:text-4xl font-extrabold tracking-tight text-white leading-tight max-w-3xl">
          {{ t('landing.hero.titlePart1') }}
          <span class="text-emerald-400 block mt-2">
            {{ t('landing.hero.titleHighlight') }}
          </span>
        </h1>

        <!-- 副标题 -->
        <p class="mt-6 text-xs sm:text-sm text-zinc-400 leading-relaxed max-w-2xl">
          {{ t('landing.hero.subtitle') }}
        </p>

        <!-- 行动按钮：启动终端 + 跳转 GitHub -->
        <div class="mt-8 flex flex-wrap items-center justify-center gap-3.5">
          <button
            type="button"
            class="h-10 sm:h-11 px-6 sm:px-7 rounded-xl bg-emerald-400 hover:bg-emerald-300 text-black text-xs font-bold cursor-pointer inline-flex items-center gap-2 shadow-lg shadow-emerald-500/10 transition-all active:scale-95"
            @click="navTo('/trading')"
          >
            <span>{{ t('landing.hero.ctaPrimary') }}</span>
            <ArrowRight class="h-4 w-4" />
          </button>

          <button
            type="button"
            class="h-10 sm:h-11 px-5 sm:px-6 rounded-xl border border-white/[0.08] bg-zinc-900/40 hover:bg-zinc-800 text-zinc-200 text-xs font-medium transition-colors inline-flex items-center gap-2 cursor-pointer"
            @click="openExternal(OFFICIAL_REPO)"
          >
            <Github class="h-4 w-4" aria-hidden="true" />
            <span>{{ t('landing.hero.ctaGithub') }}</span>
          </button>
        </div>

        <!-- 平台支持轻标识 -->
        <div class="mt-6 text-4xs font-mono text-zinc-500">
          {{ t('landing.quickstart.platformSupport') }}
        </div>
      </section>

      <!-- 3. 三所原生平权直连遥测带 -->
      <section id="venues" class="w-full border-y border-white/[0.04] bg-[#090b10]/60 py-4 px-4 sm:px-6">
        <div class="max-w-4xl mx-auto flex flex-col sm:flex-row items-center justify-between gap-3 text-3xs font-mono">
          <div class="text-zinc-400 uppercase tracking-wider">
            {{ t('landing.venuesBar.title') }}
          </div>

          <div class="flex flex-wrap items-center justify-center gap-6 sm:gap-8 text-zinc-300">
            <div class="flex items-center gap-1.5">
              <span class="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
              <span>{{ t('landing.venuesBar.okx') }}</span>
              <span class="text-emerald-400 text-4xs ms-0.5">({{ t('landing.venuesBar.latencyOkx') }})</span>
            </div>

            <div class="flex items-center gap-1.5">
              <span class="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
              <span>{{ t('landing.venuesBar.binance') }}</span>
              <span class="text-emerald-400 text-4xs ms-0.5">({{ t('landing.venuesBar.latencyBinance') }})</span>
            </div>

            <div class="flex items-center gap-1.5">
              <span class="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
              <span>{{ t('landing.venuesBar.gate') }}</span>
              <span class="text-emerald-400 text-4xs ms-0.5">({{ t('landing.venuesBar.latencyGate') }})</span>
            </div>
          </div>
        </div>
      </section>

      <!-- 4. 为什么选择 AstraQuant (经典 6 宫格特性卡片) -->
      <section id="features" class="w-full max-w-4xl px-4 sm:px-6 py-20">
        <div class="text-center max-w-2xl mx-auto mb-14">
          <span class="rounded-full border border-white/[0.06] bg-zinc-900/40 px-3 py-1 text-3xs font-mono text-zinc-400 uppercase tracking-wider font-semibold">
            {{ t('landing.features.tag') }}
          </span>
          <h2 class="mt-4 text-2xl sm:text-3xl font-extrabold tracking-tight text-white leading-tight">
            {{ t('landing.features.title') }}
          </h2>
          <p class="mt-3 text-xs sm:text-sm text-zinc-400 leading-relaxed">
            {{ t('landing.features.subtitle') }}
          </p>
        </div>

        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5 text-left">
          <!-- 特性 1: 24/7 AI 自动化交易 -->
          <div class="rounded-2xl border border-white/[0.06] bg-[#0c0e15] p-6 hover:border-emerald-500/20 transition-colors">
            <div class="h-9 w-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-4">
              <Zap class="h-4.5 w-4.5" />
            </div>
            <h3 class="text-base font-bold text-white">{{ t('landing.features.f1Title') }}</h3>
            <p class="mt-2 text-xs text-zinc-400 leading-relaxed">{{ t('landing.features.f1Desc') }}</p>
          </div>

          <!-- 特性 2: 微积分与概率论数理引擎 -->
          <div class="rounded-2xl border border-white/[0.06] bg-[#0c0e15] p-6 hover:border-emerald-500/20 transition-colors">
            <div class="h-9 w-9 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400 mb-4">
              <Dna class="h-4.5 w-4.5" />
            </div>
            <h3 class="text-base font-bold text-white">{{ t('landing.features.f2Title') }}</h3>
            <p class="mt-2 text-xs text-zinc-400 leading-relaxed">{{ t('landing.features.f2Desc') }}</p>
          </div>

          <!-- 特性 3: 数理风控 -->
          <div class="rounded-2xl border border-white/[0.06] bg-[#0c0e15] p-6 hover:border-emerald-500/20 transition-colors">
            <div class="h-9 w-9 rounded-lg bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400 mb-4">
              <Crosshair class="h-4.5 w-4.5" />
            </div>
            <h3 class="text-base font-bold text-white">{{ t('landing.features.f3Title') }}</h3>
            <p class="mt-2 text-xs text-zinc-400 leading-relaxed">{{ t('landing.features.f3Desc') }}</p>
          </div>

          <!-- 特性 4: 主流交易所直连 -->
          <div class="rounded-2xl border border-white/[0.06] bg-[#0c0e15] p-6 hover:border-emerald-500/20 transition-colors">
            <div class="h-9 w-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-4">
              <Globe class="h-4.5 w-4.5" />
            </div>
            <h3 class="text-base font-bold text-white">{{ t('landing.features.f4Title') }}</h3>
            <p class="mt-2 text-xs text-zinc-400 leading-relaxed">{{ t('landing.features.f4Desc') }}</p>
          </div>

          <!-- 特性 5: 本地私有 -->
          <div class="rounded-2xl border border-white/[0.06] bg-[#0c0e15] p-6 hover:border-emerald-500/20 transition-colors">
            <div class="h-9 w-9 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400 mb-4">
              <ShieldCheck class="h-4.5 w-4.5" />
            </div>
            <h3 class="text-base font-bold text-white">{{ t('landing.features.f5Title') }}</h3>
            <p class="mt-2 text-xs text-zinc-400 leading-relaxed">{{ t('landing.features.f5Desc') }}</p>
          </div>

          <!-- 特性 6: 极客工程 -->
          <div class="rounded-2xl border border-white/[0.06] bg-[#0c0e15] p-6 hover:border-emerald-500/20 transition-colors">
            <div class="h-9 w-9 rounded-lg bg-amber-500/10 border border-amber-500/20 flex items-center justify-center text-amber-400 mb-4">
              <Landmark class="h-4.5 w-4.5" />
            </div>
            <h3 class="text-base font-bold text-white">{{ t('landing.features.f6Title') }}</h3>
            <p class="mt-2 text-xs text-zinc-400 leading-relaxed">{{ t('landing.features.f6Desc') }}</p>
          </div>
        </div>
      </section>

      <!-- 5. 专属交易所开户与手续费返现通道 (REFERRAL PROMO) -->
      <section id="referral" class="w-full max-w-4xl px-4 sm:px-6 py-20 border-t border-white/[0.04]">
        <div class="text-center max-w-2xl mx-auto mb-12">
          <span class="rounded-full border border-emerald-500/20 bg-emerald-500/5 px-3 py-1 text-3xs font-mono text-emerald-400 uppercase tracking-wider font-semibold">
            {{ t('landing.referral.tag') }}
          </span>
          <h2 class="mt-4 text-2xl sm:text-3xl font-extrabold tracking-tight text-white leading-tight">
            {{ t('landing.referral.title') }}
          </h2>
          <p class="mt-3 text-xs sm:text-sm text-zinc-400 leading-relaxed">
            {{ t('landing.referral.subtitle') }}
          </p>
        </div>

        <!-- 3 所专属返佣卡片网格 -->
        <div v-if="channels.length" class="grid grid-cols-1 md:grid-cols-3 gap-5 text-left">
          <div
            v-for="ch in channels"
            :key="ch.key"
            class="rounded-2xl border border-white/[0.06] bg-[#0c0e15] p-6 flex flex-col justify-between hover:border-emerald-500/30 transition-colors"
          >
            <div>
              <div class="flex items-center justify-between mb-4">
                <span class="font-bold text-base text-white font-mono">{{ ch.name }}</span>
                <span class="rounded bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-4xs font-mono px-2 py-0.5">
                  {{ t('landing.referral.rateTier') }}
                </span>
              </div>

              <!-- 邀请码展示（若存在） -->
              <div v-if="ch.code" class="text-3xs font-mono text-zinc-400 mb-4 bg-[#07080c] p-2.5 rounded-lg border border-white/[0.04] flex items-center justify-between">
                <span class="text-zinc-500">{{ t('landing.referral.codeLabel') }}</span>
                <span class="text-zinc-200 font-bold select-all">{{ ch.code }}</span>
              </div>
            </div>

            <!-- 操作动作：前往开户 + 复制链接 -->
            <div class="pt-4 border-t border-white/[0.04] flex items-center gap-2">
              <button
                type="button"
                class="flex-1 h-9 rounded-lg bg-emerald-400 hover:bg-emerald-300 text-black text-xs font-semibold inline-flex items-center justify-center gap-1.5 cursor-pointer transition-all active:scale-95"
                @click="openExternal(ch.invite_url)"
              >
                <span>{{ t('landing.referral.openAccount') }}</span>
                <ExternalLink class="h-3.5 w-3.5" aria-hidden="true" />
              </button>

              <button
                type="button"
                class="h-9 px-3 rounded-lg border border-white/[0.08] bg-zinc-900/60 hover:bg-zinc-800 text-zinc-300 hover:text-white text-xs font-mono cursor-pointer inline-flex items-center gap-1.5 transition-colors"
                :aria-label="copiedChannelKey === ch.key ? t('landing.referral.copied') : t('landing.referral.copyLink')"
                @click="copyChannelUrl(ch.invite_url, ch.key)"
              >
                <Check v-if="copiedChannelKey === ch.key" class="h-3.5 w-3.5 text-emerald-400" />
                <Copy v-else class="h-3.5 w-3.5" />
              </button>
            </div>
          </div>
        </div>

        <!-- 官方结算提示 -->
        <div class="mt-6 text-center text-4xs font-mono text-zinc-500">
          {{ t('landing.referral.note') }}
        </div>
      </section>

      <!-- 6. 极速部署开箱即用 (QUICKSTART) -->
      <section class="w-full max-w-4xl px-4 sm:px-6 py-16 border-t border-white/[0.04] text-center">
        <span class="rounded-full border border-white/[0.06] bg-zinc-900/40 px-3 py-1 text-3xs font-mono text-zinc-400 uppercase tracking-wider font-semibold">
          {{ t('landing.quickstart.tag') }}
        </span>
        <h2 class="mt-3 text-2xl sm:text-3xl font-extrabold tracking-tight text-white leading-tight">
          {{ t('landing.quickstart.title') }}
        </h2>
        <p class="mt-2.5 text-xs sm:text-sm text-zinc-400 max-w-lg mx-auto leading-relaxed">
          {{ t('landing.quickstart.subtitle') }}
        </p>

        <!-- 一键复制终端框 -->
        <div class="mt-6 w-full max-w-xl mx-auto rounded-xl border border-white/[0.06] bg-[#0c0e15] px-4 py-3 flex items-center justify-between gap-3 font-mono text-xs text-left">
          <div class="flex items-center gap-2 overflow-x-auto text-zinc-300">
            <span class="text-emerald-400 font-bold select-none">&gt;</span>
            <span class="text-zinc-200 select-all whitespace-nowrap">{{ DOCKER_CMD }}</span>
          </div>
          <button
            type="button"
            class="px-2.5 py-1 rounded bg-zinc-800/80 hover:bg-zinc-700 text-3xs text-zinc-300 hover:text-white transition-colors cursor-pointer flex items-center gap-1.5 shrink-0"
            :aria-label="copiedCmd ? t('landing.quickstart.copied') : t('landing.quickstart.copyCmd')"
            @click="copyCommand"
          >
            <Check v-if="copiedCmd" class="h-3 w-3 text-emerald-400" />
            <Copy v-else class="h-3 w-3" />
            <span>{{ copiedCmd ? t('landing.quickstart.copied') : t('landing.quickstart.copyCmd') }}</span>
          </button>
        </div>
      </section>

      <!-- 7. 行动召唤 (FINAL CTA) -->
      <section class="w-full max-w-4xl px-4 sm:px-6 py-16 border-t border-white/[0.04]">
        <div class="rounded-2xl border border-white/[0.06] bg-[#0c0e15] p-8 sm:p-12 text-center flex flex-col items-center">
          <h2 class="text-xl sm:text-3xl font-extrabold tracking-tight text-white">
            {{ t('landing.cta.title') }}
          </h2>
          <p class="mt-3 text-xs sm:text-sm text-zinc-400 max-w-lg leading-relaxed">
            {{ t('landing.cta.subtitle') }}
          </p>

          <div class="mt-6 flex flex-wrap items-center justify-center gap-3.5">
            <button
              type="button"
              class="h-10 sm:h-11 px-7 rounded-xl bg-emerald-400 hover:bg-emerald-300 text-black text-xs font-bold cursor-pointer inline-flex items-center gap-2 shadow-md transition-all active:scale-95"
              @click="navTo('/trading')"
            >
              <span>{{ t('landing.cta.launchBtn') }}</span>
              <ArrowRight class="h-4 w-4" />
            </button>

            <button
              type="button"
              class="h-10 sm:h-11 px-6 rounded-xl border border-white/[0.08] bg-zinc-900/40 hover:bg-zinc-800 text-zinc-200 text-xs font-medium inline-flex items-center gap-2 cursor-pointer transition-colors"
              @click="openExternal(OFFICIAL_REPO)"
            >
              <Github class="h-4 w-4" aria-hidden="true" />
              <span>{{ t('landing.cta.githubBtn') }}</span>
            </button>
          </div>

          <div class="mt-5 text-4xs font-mono text-zinc-500">
            {{ t('landing.cta.note') }}
          </div>
        </div>
      </section>
    </main>

    <!-- 8. 生态页脚 -->
    <footer class="w-full border-t border-white/[0.04] bg-[#050608] py-10 px-4 sm:px-8 text-xs text-zinc-400">
      <div class="max-w-4xl mx-auto flex flex-col md:flex-row items-start justify-between gap-8">
        <div class="max-w-sm">
          <div class="flex items-center gap-2">
            <img src="/favicon.svg" alt="AstraQuant Logo" class="h-5 w-5 rounded" />
            <span class="font-mono font-bold text-sm text-white">AstraQuant</span>
          </div>
          <p class="mt-2.5 text-3xs text-zinc-500 leading-relaxed">
            {{ t('landing.footer.brandDesc') }}
          </p>
          <div class="mt-3 text-4xs font-mono text-zinc-600">
            © 2026 AstraQuant. All rights reserved.
          </div>
        </div>

        <div class="flex flex-wrap gap-12 font-mono text-3xs">
          <div>
            <div class="font-bold text-white uppercase tracking-wider mb-2.5">
              {{ t('landing.footer.productTitle') }}
            </div>
            <ul class="space-y-1.5 list-none p-0 m-0">
              <li><RouterLink to="/trading" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.trading') }}</RouterLink></li>
              <li><RouterLink to="/factors" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.factors') }}</RouterLink></li>
              <li><RouterLink to="/news" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.news') }}</RouterLink></li>
              <li><RouterLink to="/lab" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.lab') }}</RouterLink></li>
              <li><RouterLink to="/history" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.ledger') }}</RouterLink></li>
            </ul>
          </div>

          <div>
            <div class="font-bold text-white uppercase tracking-wider mb-2.5">
              {{ t('landing.footer.platformTitle') }}
            </div>
            <ul class="space-y-1.5 list-none p-0 m-0">
              <li><RouterLink to="/docs" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.docs') }}</RouterLink></li>
              <li><RouterLink to="/admin" class="hover:text-white no-underline text-zinc-400">{{ t('landing.footer.console') }}</RouterLink></li>
              <li>
                <button
                  type="button"
                  class="hover:text-white text-zinc-400 bg-transparent border-0 p-0 cursor-pointer text-start"
                  @click="openExternal(OFFICIAL_REPO)"
                >
                  GitHub
                </button>
              </li>
            </ul>
          </div>
        </div>
      </div>

      <div class="max-w-4xl mx-auto mt-6 pt-5 border-t border-white/[0.04] text-4xs text-zinc-600 leading-relaxed">
        {{ t('landing.footer.securityNote') }}
      </div>
    </footer>
  </div>
</template>
