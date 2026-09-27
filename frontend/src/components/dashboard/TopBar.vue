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
} from 'lucide-vue-next';
import { publicTabs } from '../../config/nav';
import { useI18n } from '../../composables/useI18n';
import { useUi } from '../../composables/useUi';
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
const { trajectoryOpen } = useUi();

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
    class="relative z-[60] flex h-12 w-full shrink-0 items-center justify-between border-b px-3 sm:px-4 backdrop-blur-md transition-colors"
    style="background-color: var(--surface-header); border-color: var(--line-2); color: var(--ink-1)"
  >
    <!-- 左侧：品牌 Logo 与字标 + 桌面端一体化横向导航条 -->
    <div class="flex items-center gap-2.5 sm:gap-4 min-w-0">
      <!-- 品牌 Logo 与字标 -->
      <RouterLink
        to="/"
        class="flex items-center gap-2 cursor-pointer no-underline transition-opacity hover:opacity-85 shrink-0"
        style="color: inherit"
        :aria-label="t('brand.name')"
      >
        <img src="/favicon.svg" alt="" class="h-6 w-6 rounded shrink-0" />
        <span class="font-bold tracking-tight text-sm text-[var(--ink-strong)] font-mono">
          {{ t('brand.name') }}
        </span>
      </RouterLink>

      <span class="hidden md:block h-3.5 w-px opacity-30 shrink-0" style="background-color: var(--line-2)" />

      <!-- 桌面端一体化横向导航项（无缝融入顶栏） -->
      <nav class="hidden md:flex items-center gap-1 min-w-0" aria-label="Main Navigation">
        <button
          v-for="tab in publicTabs"
          :key="tab.key"
          type="button"
          class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium cursor-pointer transition-colors border border-transparent whitespace-nowrap"
          :class="activeTabKey === tab.key
            ? 'bg-[var(--surface-2)] text-[var(--ink-strong)] font-semibold border-white/10'
            : 'text-[var(--ink-2)] hover:bg-[var(--surface-2)] hover:text-[var(--ink-1)]'"
          :aria-current="activeTabKey === tab.key ? 'page' : undefined"
          @click="go(tab.path)"
        >
          <component :is="tab.icon" class="h-3.5 w-3.5" :class="activeTabKey === tab.key ? 'text-emerald-400' : 'opacity-70'" />
          <span>{{ t(tab.labelKey) }}</span>
        </button>

        <button
          type="button"
          class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-medium cursor-pointer transition-colors border border-transparent whitespace-nowrap"
          :class="route.path === '/docs'
            ? 'bg-[var(--surface-2)] text-[var(--ink-strong)] font-semibold border-white/10'
            : 'text-[var(--ink-2)] hover:bg-[var(--surface-2)] hover:text-[var(--ink-1)]'"
          :aria-current="route.path === '/docs' ? 'page' : undefined"
          @click="go('/docs')"
        >
          <BookOpen class="h-3.5 w-3.5" :class="route.path === '/docs' ? 'text-emerald-400' : 'opacity-70'" />
          <span>{{ t('dash.shell.nav.docs') }}</span>
        </button>
      </nav>
    </div>

    <!-- 右侧：数据状态 + 决策轨迹 + 偏好设置 -->
    <div class="flex items-center gap-1.5 shrink-0">
      <!-- 数据与引擎在线状态 -->
      <DataStatus class="hidden lg:flex" />

      <!-- 决策轨迹流入口 -->
      <button type="button"
        class="inline-flex h-7 items-center gap-1.5 rounded-lg border border-[var(--line-2)] px-2.5 text-xs font-medium cursor-pointer transition-colors hover:bg-[var(--surface-2)] text-[var(--ink-2)] hover:text-[var(--ink-strong)] hover:border-emerald-500/30"
        :title="`${t('dash.shell.trajectoryBtn')} (⌘J)`"
        @click="trajectoryOpen = true"
      >
        <Activity class="h-3.5 w-3.5 text-emerald-400" />
        <span class="hidden sm:inline">{{ t('dash.shell.trajectoryBtn') }}</span>
        <kbd class="hidden sm:inline-flex ml-0.5 text-4xs font-mono text-[var(--ink-3)] px-1 py-0.5 rounded border border-[var(--line-2)] bg-[var(--surface-1)]">⌘J</kbd>
      </button>

      <!-- 偏好设置 -->
      <SettingsPopover />
    </div>
  </header>
</template>
