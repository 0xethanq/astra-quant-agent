<script setup lang="ts">
/**
 * AdminLayout.vue · ASTRA 现代量化控制台外壳 (v9.2.0)
 * ---------------------------------------------------------------------------
 * · 左侧 248px 精度导航栏（surface-1 柔和阶差，无 backdrop-filter，左橙条选中指示）
 * · 底部常驻当前管理员身份卡 + 一键退出
 * · 56px 顶部工具栏：面包屑 / 全局交易暂停态徽章 / 更新提醒 / 语言直切 / 北京时间 / 主题 / 返回大屏
 * · 沉浸模式（/admin/agent）自动铺满视口、消除多余外边距
 */
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import {
  PanelLeftClose,
  PanelLeftOpen,
  Menu,
  X,
  LogOut,
  MonitorPlay,
  Sun,
  Moon,
  ArrowUpCircle,
  PauseCircle,
  Activity,
  Languages,
} from 'lucide-vue-next';
import { useAuthStore } from '../stores/auth';
import { useI18n } from '../composables/useI18n';
import { useTheme } from '../composables/useTheme';
import { useLocalStorage } from '../composables/useLocalStorage';
import { useUpdateNotice } from '../composables/useUpdateNotice';
import { useApi } from '../composables/useApi';
import { useRouteFocus } from '../composables/useRouteFocus';
import { adminGroups } from '../config/nav';
import { APP_VERSION } from '../config/version';
import BeijingClock from '../components/base/BeijingClock.vue';
import SkipLink from '../components/base/SkipLink.vue';

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const { t, toggleLocale } = useI18n();
const { theme, toggleTheme } = useTheme();
const { updateAvailable, behindCount } = useUpdateNotice();
const { api } = useApi();
useRouteFocus();

const collapsed = useLocalStorage('astra_admin_sidebar', false);
const drawerOpen = ref(false);
const tradingPaused = ref<boolean | null>(null);

const currentKey = computed(() => (route.name as string) || 'admin-agent');
const isImmersiveAgent = computed(() => route.path === '/admin/agent');
const currentMeta = computed(() => {
  for (const g of adminGroups) {
    const hit = g.items.find((i) => i.key === currentKey.value);
    if (hit) return { group: g, item: hit };
  }
  return null;
});

const operatorInitial = computed(() => (auth.user?.username || 'A').slice(0, 1).toUpperCase());

function go(path: string) {
  drawerOpen.value = false;
  if (route.path !== path) router.push(path);
}

function logout() {
  auth.logout();
  router.push('/admin/login');
}

async function refreshEngineBadge() {
  if (!auth.isAuthenticated) return;
  try {
    const data = await api('/api/v1/admin/control-plane/state');
    if (typeof data?.trading_paused === 'boolean') {
      tradingPaused.value = data.trading_paused;
    }
  } catch {
    // Non-blocking header indicator
  }
}

function onControlPlaneChanged(ev: Event) {
  const detail = (ev as CustomEvent)?.detail;
  if (detail && typeof detail.trading_paused === 'boolean') {
    tradingPaused.value = detail.trading_paused;
  } else {
    void refreshEngineBadge();
  }
}

onMounted(() => {
  void refreshEngineBadge();
  window.addEventListener('astra:control-plane-changed', onControlPlaneChanged);
  const prefetch = () =>
    adminGroups
      .flatMap((g) => g.items)
      .forEach((i) => {
        if (i.component) import(`../views/admin/${i.component}.vue`).catch(() => {});
      });
  if ('requestIdleCallback' in window) (window as any).requestIdleCallback(prefetch);
  else setTimeout(prefetch, 400);
});

onBeforeUnmount(() => {
  window.removeEventListener('astra:control-plane-changed', onControlPlaneChanged);
});

watch(() => route.path, () => (drawerOpen.value = false));
</script>

<template>
  <div class="wb">
    <SkipLink />

    <!-- ═══ 桌面侧边导航 ═══ -->
    <aside id="admin-desktop-sidebar" class="wb-rail" :class="{ 'is-collapsed': collapsed }">
      <div class="wb-brand">
        <img src="/favicon.svg" class="wb-logo" alt="" />
        <div v-if="!collapsed" class="wb-brand-text">
          <span class="wb-brand-name">Astra<span class="text-[var(--ds-color-brand)]">Quant</span></span>
          <span class="wb-version">{{ APP_VERSION }}</span>
        </div>
        <button
          v-if="!collapsed"
          type="button"
          class="wb-icon-btn wb-collapse"
          :title="t('admin.shell.collapse')"
          :aria-expanded="!collapsed"
          :aria-controls="'admin-desktop-sidebar'"
          @click="collapsed = true"
        >
          <PanelLeftClose :size="15" />
        </button>
      </div>

      <nav class="wb-nav scroll-area">
        <div v-for="g in adminGroups" :key="g.key" class="wb-group">
          <div v-if="!collapsed" class="wb-group-label">{{ t(g.labelKey) }}</div>
          <div v-else class="wb-group-sep" />
          <button
            v-for="item in g.items"
            :key="item.key"
            type="button"
            class="wb-item"
            :class="{ 'is-active': currentKey === item.key }"
            :title="collapsed ? t(item.labelKey) : undefined"
            :aria-current="currentKey === item.key ? 'page' : undefined"
            @click="go(item.path)"
          >
            <component :is="item.icon" :size="16" class="wb-item-icon" />
            <span v-if="!collapsed" class="wb-item-text">{{ t(item.labelKey) }}</span>
          </button>
        </div>
      </nav>

      <div class="wb-rail-foot">
        <button
          v-if="collapsed"
          type="button"
          class="wb-icon-btn wb-expand"
          :title="t('admin.shell.expand')"
          :aria-expanded="!collapsed"
          :aria-controls="'admin-desktop-sidebar'"
          @click="collapsed = false"
        >
          <PanelLeftOpen :size="16" />
        </button>

        <div v-if="auth.user && !collapsed" class="wb-user-card">
          <span class="wb-user-avatar mono">{{ operatorInitial }}</span>
          <div class="wb-user-meta">
            <span class="wb-user-name truncate">{{ auth.user.username }}</span>
            <span v-if="!auth.isSuperadmin" class="wb-user-role mono">
              {{ t('admin.shell.roleAdmin') }}
            </span>
          </div>
        </div>

        <button type="button" class="wb-item wb-item-danger" :title="t('nav.actions.logout')" @click="logout">
          <LogOut :size="16" class="wb-item-icon" />
          <span v-if="!collapsed" class="wb-item-text">{{ t('nav.actions.logout') }}</span>
        </button>
      </div>
    </aside>

    <!-- ═══ 主工位 ═══ -->
    <div class="wb-stage">
      <header class="wb-topbar">
        <button
          type="button"
          class="wb-icon-btn wb-burger"
          :title="drawerOpen ? t('admin.shell.collapse') : t('admin.shell.expand')"
          :aria-label="drawerOpen ? t('admin.shell.collapse') : t('admin.shell.expand')"
          :aria-expanded="drawerOpen"
          :aria-controls="drawerOpen ? 'admin-mobile-drawer' : undefined"
          @click="drawerOpen = !drawerOpen"
        >
          <Menu :size="16" />
        </button>

        <nav class="wb-crumbs" aria-label="Breadcrumb">
          <span class="wb-crumb-root">{{ t('admin.shell.breadcrumbRoot') }}</span>
          <template v-if="currentMeta">
            <span class="wb-crumb-sep sm:inline hidden">/</span>
            <span class="wb-crumb-dim">{{ t(currentMeta.group.labelKey) }}</span>
            <span class="wb-crumb-sep">/</span>
            <span class="wb-crumb-cur">
              <component :is="currentMeta.item.icon" :size="15" />
              <span>{{ t(currentMeta.item.labelKey) }}</span>
            </span>
          </template>
        </nav>

        <div class="wb-topbar-right">
          <button
            v-if="tradingPaused !== null"
            type="button"
            class="badge wb-engine-pill"
            :class="tradingPaused ? 'badge-warn' : 'badge-up'"
            :title="t('admin.shell.engineStatusTip')"
            @click="router.push('/admin/strategy?tab=schedule')"
          >
            <PauseCircle v-if="tradingPaused" :size="13" />
            <Activity v-else :size="13" />
            <span>{{ tradingPaused ? t('admin.shell.enginePaused') : t('admin.shell.engineRunning') }}</span>
          </button>

          <button
            v-if="updateAvailable"
            type="button"
            class="badge badge-warn wb-update-pill"
            :title="t('dash.shell.updateTooltip', undefined, { n: behindCount })"
            @click="router.push('/admin/backup?tab=version')"
          >
            <ArrowUpCircle :size="13" />
            <span class="hidden sm:inline">{{ t('dash.shell.updateAvailable') }}</span>
            <span class="mono num">{{ behindCount }}</span>
          </button>

          <BeijingClock class="wb-clock" />

          <button
            type="button"
            class="wb-icon-btn wb-lang-btn"
            :title="t('admin.shell.switchLanguage')"
            :aria-label="t('admin.shell.switchLanguage')"
            @click="toggleLocale"
          >
            <Languages :size="15" />
          </button>

          <button
            type="button"
            class="wb-icon-btn"
            :title="t('nav.actions.theme')"
            :aria-label="t('nav.actions.theme')"
            @click="toggleTheme"
          >
            <Sun v-if="theme === 'dark'" :size="15" />
            <Moon v-else :size="15" />
          </button>

          <button
            type="button"
            class="btn btn-ghost btn-sm wb-screen-btn"
            :title="t('nav.actions.backToScreen')"
            @click="router.push('/')"
          >
            <MonitorPlay :size="14" />
            <span class="hidden md:inline">{{ t('nav.actions.backToScreen') }}</span>
          </button>
        </div>
      </header>

      <main
        id="main-content"
        tabindex="-1"
        class="wb-main scroll-area outline-none"
        :class="{ 'is-immersive': isImmersiveAgent }"
      >
        <div class="wb-content">
          <router-view />
        </div>
      </main>
    </div>

    <!-- ═══ 移动端抽屉 ═══ -->
    <div v-if="drawerOpen" class="wb-drawer-root">
      <div class="wb-scrim" @click="drawerOpen = false" />
      <aside id="admin-mobile-drawer" class="wb-drawer" :aria-label="t('admin.shell.brand')">
        <div class="wb-drawer-head">
          <span class="wb-brand-name">Astra<span class="text-[var(--ds-color-brand)]">Quant</span> {{ t('admin.shell.brand') }}</span>
          <button
            type="button"
            class="wb-icon-btn"
            :title="t('common.close')"
            :aria-label="t('common.close')"
            @click="drawerOpen = false"
          >
            <X :size="15" />
          </button>
        </div>
        <nav class="wb-nav scroll-area">
          <div v-for="g in adminGroups" :key="g.key" class="wb-group">
            <div class="wb-group-label">{{ t(g.labelKey) }}</div>
            <button
              v-for="item in g.items"
              :key="item.key"
              type="button"
              class="wb-item"
              :class="{ 'is-active': currentKey === item.key }"
              :aria-current="currentKey === item.key ? 'page' : undefined"
              @click="go(item.path)"
            >
              <component :is="item.icon" :size="16" class="wb-item-icon" />
              <span class="wb-item-text">{{ t(item.labelKey) }}</span>
            </button>
          </div>
        </nav>
        <div class="wb-rail-foot">
          <button type="button" class="wb-item wb-item-danger" @click="logout">
            <LogOut :size="16" class="wb-item-icon" />
            <span class="wb-item-text">{{ t('nav.actions.logout') }}</span>
          </button>
        </div>
      </aside>
    </div>
  </div>
</template>

<style scoped>
.wb {
  display: flex;
  height: 100svh;
  width: 100%;
  overflow: hidden;
  background-color: var(--ds-color-bg-page);
  color: var(--ds-color-text-secondary);
}

/* ══ 侧边导航 ══ */
.wb-rail {
  display: none;
  flex-direction: column;
  flex-shrink: 0;
  width: 216px;
  border-right: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface-1);
  transition: width var(--dur-base) var(--ease-out);
}
.wb-rail.is-collapsed {
  width: 60px;
}
@media (min-width: 768px) {
  .wb-rail {
    display: flex;
  }
}

.wb-brand {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  height: var(--h-topbar);
  padding: 0 var(--ds-space-3);
  border-bottom: 1px solid var(--ds-color-border-subtle);
  flex-shrink: 0;
}
.wb-logo {
  width: 22px;
  height: 22px;
  border-radius: var(--r-xs);
  flex-shrink: 0;
}
.wb-brand-text {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  min-width: 0;
  flex: 1;
}
.wb-brand-name {
  font-size: var(--text-base);
  font-weight: 600;
  letter-spacing: var(--track-title);
  color: var(--ds-color-text-primary);
  white-space: nowrap;
}
.wb-version {
  font-family: var(--ds-font-mono);
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-xs);
  padding: 0 var(--sp-2);
  line-height: 16px;
}
.wb-collapse {
  margin-left: auto;
}

.wb-nav {
  flex: 1;
  padding: var(--ds-space-4) var(--ds-space-2);
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}
.wb-group {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.wb-group-label {
  padding: 0 var(--ds-space-3) var(--sp-2);
  font-size: var(--text-4xs);
  font-weight: 600;
  letter-spacing: var(--track-label);
  color: var(--ds-color-text-placeholder);
}
.wb-group-sep {
  height: 1px;
  margin: var(--ds-space-2) var(--ds-space-2);
  background-color: var(--ds-color-border-default);
}

.wb-item {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  width: 100%;
  height: var(--h-lg);
  padding: 0 var(--ds-space-3);
  border: 1px solid transparent;
  border-radius: var(--r-ctl);
  background-color: transparent;
  color: var(--ds-color-text-description);
  font-family: inherit;
  font-size: var(--text-xs);
  font-weight: 500;
  text-align: left;
  cursor: pointer;
  transition: background-color var(--dur-fast) var(--ease-out),
    color var(--dur-fast) var(--ease-out),
    border-color var(--dur-fast) var(--ease-out);
}
.wb-item:hover {
  background-color: var(--ds-color-bg-hover);
  color: var(--ds-color-text-primary);
}
.wb-item.is-active {
  background-color: var(--astra-brand-bg);
  color: var(--ds-color-text-primary);
  font-weight: 600;
  border-color: var(--astra-brand-line);
}
.wb-item-icon {
  flex-shrink: 0;
  opacity: 0.72;
}
.wb-item.is-active .wb-item-icon {
  opacity: 1;
  color: var(--ds-color-brand);
}
.wb-item-text {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.wb-item-danger:hover {
  background-color: var(--down-bg);
  color: var(--down);
}

.wb-rail-foot {
  flex-shrink: 0;
  padding: var(--ds-space-3) var(--ds-space-2);
  border-top: 1px solid var(--ds-color-border-subtle);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.wb-expand {
  align-self: center;
  margin-bottom: var(--ds-space-1);
}

.wb-user-card {
  display: flex;
  align-items: center;
  gap: var(--sp-5);
  padding: var(--ds-space-2) var(--ds-space-3);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-2);
}
.wb-user-avatar {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--r-pill);
  background-color: var(--astra-brand-bg);
  color: var(--ds-color-brand);
  font-size: var(--text-xs);
  font-weight: 600;
  flex-shrink: 0;
}
.wb-user-meta {
  display: flex;
  flex-direction: column;
  min-width: 0;
  gap: var(--sp-1);
}
.wb-user-name {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
  line-height: 1.2;
}
.wb-user-role {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
  letter-spacing: 0.04em;
  line-height: 1.1;
}

.wb-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: var(--h-md);
  height: var(--h-md);
  border: 1px solid transparent;
  border-radius: var(--r-ctl);
  background: transparent;
  color: var(--ds-color-text-description);
  cursor: pointer;
  flex-shrink: 0;
  transition: background-color var(--dur-fast), color var(--dur-fast),
    border-color var(--dur-fast);
}
.wb-icon-btn:hover {
  background-color: var(--ds-btn-ghost-hover-bg);
  border-color: var(--ds-btn-ghost-hover-border);
  color: var(--ds-color-text-primary);
}

/* ══ 主工位 ══ */
.wb-stage {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-width: 0;
  overflow: hidden;
}

.wb-topbar {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  height: var(--h-topbar);
  padding: 0 var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-page);
  flex-shrink: 0;
}
@media (min-width: 768px) {
  .wb-topbar {
    padding: 0 var(--ds-space-4);
  }
}
.wb-burger {
  display: inline-flex;
}
@media (min-width: 768px) {
  .wb-burger {
    display: none;
  }
}

.wb-crumbs {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  min-width: 0;
  font-size: var(--text-xs);
}
.wb-crumb-root {
  font-weight: 600;
  color: var(--ds-color-text-primary);
  letter-spacing: var(--track-title);
}
.wb-crumb-sep {
  color: var(--ds-color-text-placeholder);
}
.wb-crumb-dim {
  color: var(--ds-color-text-description);
  display: none;
}
@media (min-width: 640px) {
  .wb-crumb-dim {
    display: inline;
  }
}
.wb-crumb-cur {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  color: var(--ds-color-text-primary);
  font-weight: 600;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.wb-topbar-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
}
.wb-engine-pill,
.wb-update-pill {
  cursor: pointer;
}
.wb-lang-btn {
  width: var(--h-md);
  height: var(--h-md);
}
.wb-screen-btn {
  margin-left: var(--ds-space-1);
}
.wb-clock {
  display: none;
}
@media (min-width: 1024px) {
  .wb-clock {
    display: block;
    margin: 0 var(--ds-space-1);
  }
}

/* 内容区 */
.wb-main {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  padding: var(--ds-space-4) var(--ds-space-5);
}
.wb-main.is-immersive {
  overflow: hidden;
  padding: 0;
}
.wb-content {
  flex: 1;
  min-height: 0;
  max-width: 1440px;
  width: 100%;
  margin: 0 auto;
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-5);
}
.wb-main.is-immersive .wb-content {
  max-width: 100%;
  gap: 0;
}

/* ══ 移动端抽屉 ══ */
.wb-drawer-root {
  position: fixed;
  inset: 0;
  z-index: var(--z-drawer);
  display: flex;
}
.wb-scrim {
  position: absolute;
  inset: 0;
  background-color: var(--overlay-scrim);
  backdrop-filter: blur(2px);
}
.wb-drawer {
  position: relative;
  display: flex;
  flex-direction: column;
  width: 268px;
  max-width: 82vw;
  background-color: var(--ds-color-bg-surface-1);
  border-right: 1px solid var(--ds-color-border-default);
}
.wb-drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
  height: var(--h-topbar);
  padding: 0 var(--ds-space-3);
  border-bottom: 1px solid var(--ds-color-border-default);
  flex-shrink: 0;
}
</style>
