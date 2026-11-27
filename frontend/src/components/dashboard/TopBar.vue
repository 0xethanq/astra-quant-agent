<script setup lang="ts">
/**
 * TopBar.vue · 交易工作台一体化顶栏导航
 * ---------------------------------------------------------------------------
 * 极简一体化设计（参考 Hyperliquid / dYdX / TradingView）：
 * 1. 移动端：轻量汉堡按钮
 * 2. 品牌标识与字标
 * 3. 核心交易频道横向导航选项卡（实盘矩阵 / AI推演 / 市场舆情 / 策略进化 / 交易台账 / 参考文档）
 * 4. 右侧：数据与资金环境状态 + 决策轨迹流 (⌘J) + 偏好设置
 */
import { computed } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  Activity,
  BookOpen,
  ArrowUpCircle,
  ExternalLink,
  Gift,
  Github,
} from 'lucide-vue-next';
import { publicTabs } from '../../config/nav';
import { SKILLHUB_SITE, OFFICIAL_REPO } from '../../config/version';
import { useI18n } from '../../composables/useI18n';
import { useUi } from '../../composables/useUi';
import { useUpdateNotice } from '../../composables/useUpdateNotice';
import { trackEvent } from '../../utils/analytics';
import DataStatus from './DataStatus.vue';
import SettingsPopover from './SettingsPopover.vue';

defineProps<{
  /** 移动端抽屉是否已打开 */
  navExpanded?: boolean;
}>();

const emit = defineEmits<{
  (e: 'toggleSidebar'): void;
}>();

const route = useRoute();
const router = useRouter();
const { t } = useI18n();
const { trajectoryOpen, rebateOpen } = useUi();
const { updateAvailable, behindCount } = useUpdateNotice();

const activeTabKey = computed(() => {
  const tabKey = (route.meta?.tab as string) || 'trading';
  return tabKey;
});

function go(path: string) {
  router.push(path);
}
</script>

<template>
  <header
    class="sticky top-0 z-[60] h-14 w-full shrink-0 border-b"
    style="background-color: var(--surface-header); border-color: var(--line-3); color: var(--ink-1)"
  >
    <div class="mx-auto flex h-full w-full max-w-[1440px] items-center justify-between px-5 sm:px-8">
      <!-- 左侧：品牌 Logo 与字标 + 下划线终端频道导航 -->
      <div class="flex items-center gap-6 sm:gap-8 min-w-0 h-full">
        <!-- 品牌 Logo 与字标 -->
        <RouterLink
          to="/"
          class="flex items-center gap-2 cursor-pointer no-underline transition-opacity hover:opacity-85 shrink-0"
          style="color: inherit"
          :aria-label="t('brand.name')"
        >
          <img src="/favicon.svg" alt="" class="h-5 w-5 rounded shrink-0" />
          <span class="font-bold tracking-[-0.03em] text-base text-[var(--ink-strong)]">
            Astra<span class="text-[var(--ds-color-brand)]">Quant</span>
          </span>
        </RouterLink>

        <!-- 桌面端全高下划线导航项 -->
        <nav class="hidden md:flex items-center gap-1.5 min-w-0 h-full" aria-label="Main Navigation">
          <button
            v-for="tab in publicTabs"
            :key="tab.key"
            type="button"
            class="relative inline-flex items-center h-full px-2.5 text-xs font-medium cursor-pointer transition-colors whitespace-nowrap"
            :class="activeTabKey === tab.key
              ? 'text-[var(--ink-strong)] font-semibold'
              : 'text-[var(--ink-3)] hover:text-[var(--ink-1)]'"
            :aria-current="activeTabKey === tab.key ? 'page' : undefined"
            @click="go(tab.path)"
          >
            <span>{{ t(tab.labelKey) }}</span>
            <span
              v-if="activeTabKey === tab.key"
              class="absolute inset-x-2.5 bottom-0 h-0.5 bg-[var(--ds-color-brand)]"
              aria-hidden="true"
            />
          </button>

          <button
            type="button"
            class="relative inline-flex items-center gap-1.5 h-full px-2.5 text-xs font-medium cursor-pointer transition-colors whitespace-nowrap"
            :class="route.path === '/docs'
              ? 'text-[var(--ink-strong)] font-semibold'
              : 'text-[var(--ink-3)] hover:text-[var(--ink-1)]'"
            :aria-current="route.path === '/docs' ? 'page' : undefined"
            @click="go('/docs')"
          >
            <BookOpen class="h-3.5 w-3.5 opacity-70" />
            <span>{{ t('dash.shell.nav.docs') }}</span>
            <span
              v-if="route.path === '/docs'"
              class="absolute inset-x-2.5 bottom-0 h-0.5 bg-[var(--ds-color-brand)]"
              aria-hidden="true"
            />
          </button>

          <a
            :href="SKILLHUB_SITE"
            target="_blank"
            rel="noopener noreferrer"
            class="inline-flex items-center gap-1 h-full px-2.5 text-xs font-medium transition-colors whitespace-nowrap text-[var(--ink-3)] hover:text-[var(--ink-1)]"
            @click="trackEvent('crosslink_click', { target: 'skillhub', placement: 'dashboard_topbar' })"
          >
            <span>{{ t('dash.shell.nav.skills') }}</span>
            <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
            <ExternalLink class="h-3 w-3 opacity-60" aria-hidden="true" />
          </a>
        </nav>
      </div>

      <!-- 右侧：无边框极简控制动作 + 内联行情心跳 -->
      <div class="flex items-center gap-1.5 shrink-0">
        <DataStatus class="hidden lg:flex mr-2" />

        <button
          type="button"
          class="inline-flex h-7 items-center gap-1.5 rounded-md border-0 px-2.5 text-3xs font-medium cursor-pointer transition-colors bg-transparent text-[var(--ink-2)] hover:bg-[var(--surface-2)] hover:text-[var(--ink-strong)]"
          :title="t('dash.about.rebateModal.title')"
          @click="rebateOpen = true; trackEvent('rebate_modal_open', { placement: 'dashboard_topbar' })"
        >
          <Gift class="h-3.5 w-3.5 text-[var(--ink-3)]" aria-hidden="true" />
          <span class="hidden sm:inline">{{ t('dash.shell.rebateBtn') }}</span>
        </button>

        <!-- 远端新版本更新提醒 -->
        <button
          v-if="updateAvailable"
          type="button"
          class="inline-flex h-7 items-center gap-1.5 rounded-md border-0 px-2 text-3xs font-semibold cursor-pointer transition-colors bg-[var(--warn-bg)] text-[var(--warn)] hover:bg-[var(--surface-2)]"
          :title="t('dash.shell.updateTooltip', undefined, { n: behindCount })"
          @click="router.push('/admin/backup?tab=version')"
        >
          <ArrowUpCircle class="h-3.5 w-3.5" />
          <span class="hidden sm:inline">{{ t('dash.shell.updateAvailable') }}</span>
          <span class="num text-4xs font-mono">{{ behindCount }}</span>
        </button>

        <!-- 决策轨迹流入口 -->
        <button type="button"
          class="inline-flex h-7 items-center gap-1.5 rounded-md border-0 px-2.5 text-3xs font-medium cursor-pointer transition-colors bg-transparent hover:bg-[var(--surface-2)] text-[var(--ink-2)] hover:text-[var(--ink-strong)]"
          :title="`${t('dash.shell.trajectoryBtn')} (⌘J)`"
          @click="trajectoryOpen = true"
        >
          <Activity class="h-3.5 w-3.5 text-[var(--ds-color-brand)]" />
          <span class="hidden sm:inline">{{ t('dash.shell.trajectoryBtn') }}</span>
          <kbd class="hidden sm:inline-flex ml-0.5 text-4xs font-mono text-[var(--ink-3)]">⌘J</kbd>
        </button>

        <!-- 开源代码仓库 -->
        <a
          :href="OFFICIAL_REPO"
          target="_blank"
          rel="noopener noreferrer"
          class="inline-flex h-7 w-7 items-center justify-center rounded-md border-0 text-[var(--ink-3)] hover:bg-[var(--surface-2)] hover:text-[var(--ink-strong)] transition-colors"
          :title="t('dash.about.repo.visit')"
          :aria-label="t('dash.about.repo.visit')"
          @click="trackEvent('external_click', { target: 'github', placement: 'dashboard_topbar' })"
        >
          <Github class="h-3.5 w-3.5" aria-hidden="true" />
          <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
        </a>

        <!-- 偏好设置 -->
        <SettingsPopover />
      </div>
    </div>
  </header>
</template>
