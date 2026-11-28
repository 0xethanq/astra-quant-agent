<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { RefreshCw } from 'lucide-vue-next';
import BaseTabs from '../../components/base/BaseTabs.vue';
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue';
import BaseSwitch from '../../components/base/BaseSwitch.vue';
import PageHeader from '../../components/admin/PageHeader.vue';
import { useApi } from '../../composables/useApi';
import { useI18n } from '../../composables/useI18n';
import { useToast } from '../../composables/useToast';
import { useAuthStore } from '../../stores/auth';
import StrategyRiskTab from './strategy/StrategyRiskTab.vue';
import StrategyCouncilTab from './strategy/StrategyCouncilTab.vue';
import StrategyPromptTab from './strategy/StrategyPromptTab.vue';
import StrategyEvolutionTab from './strategy/StrategyEvolutionTab.vue';
import StrategyScheduleTab from './strategy/StrategyScheduleTab.vue';

type StrategyTab = 'risk' | 'council' | 'prompt' | 'evolution' | 'schedule';
const VALID_TABS: StrategyTab[] = ['risk', 'council', 'prompt', 'evolution', 'schedule'];

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const { api } = useApi();
const { t } = useI18n();
const toast = useToast();

const activeTab = ref<StrategyTab>('risk');
const state = ref<Record<string, any> | null>(null);
const loading = ref(true);
const togglingPause = ref(false);

const tabItems = computed<{ key: StrategyTab; label: string }[]>(() => [
  { key: 'risk', label: t('admin.strategy.tabRisk') },
  { key: 'council', label: t('admin.strategy.tabCouncil') },
  { key: 'prompt', label: t('admin.strategy.tabPrompt') },
  { key: 'evolution', label: t('admin.strategy.tabEvolution') },
  { key: 'schedule', label: t('admin.strategy.tabSchedule') },
]);

const isPaused = computed(() => Boolean(state.value?.trading_paused));

function syncTabFromRoute() {
  const q = String(route.query.tab || '').toLowerCase() as StrategyTab;
  if (VALID_TABS.includes(q)) {
    activeTab.value = q;
  }
}

watch(
  () => route.query.tab,
  () => {
    syncTabFromRoute();
  },
  { immediate: true },
);

watch(activeTab, (next) => {
  if (String(route.query.tab || '') !== next) {
    router.replace({ path: '/admin/strategy', query: { ...route.query, tab: next } });
  }
});

async function loadState() {
  loading.value = true;
  try {
    state.value = await api('/api/v1/admin/control-plane/state');
  } catch (e: any) {
    toast.err(t('admin.strategy.loadFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    loading.value = false;
  }
}

async function toggleGlobalPause(paused: boolean) {
  if (!auth.isSuperadmin || togglingPause.value) return;
  togglingPause.value = true;
  try {
    await api('/api/v1/admin/control-plane/quick-toggle', {
      method: 'POST',
      body: JSON.stringify({ target: 'trading_paused', enabled: paused, auto_snapshot: false }),
    });
    if (state.value) {
      state.value = { ...state.value, trading_paused: paused };
    }
    window.dispatchEvent(new CustomEvent('astra:control-plane-changed', { detail: { trading_paused: paused } }));
    toast.ok(t('admin.strategy.savedToast'));
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    togglingPause.value = false;
  }
}

onMounted(loadState);
</script>

<template>
  <div class="st-page">
    <PageHeader
      :title="t('admin.strategy.title')"
      :description="t('admin.strategy.desc')"
      :badge="t('admin.strategy.badge')"
    >
      <template #actions>
        <div class="st-header-actions">
          <div class="st-header-switch">
            <span class="st-switch-label">{{ t('admin.strategy.kpiEngineState') }}</span>
            <BaseSwitch
              :modelValue="isPaused"
              :disabled="!auth.isSuperadmin || togglingPause"
              :label="t('admin.strategy.pauseBannerTitle')"
              @update:modelValue="toggleGlobalPause"
            />
          </div>
          <button type="button" class="btn btn-ghost btn-sm" @click="loadState">
            <RefreshCw :size="14" :class="{ 'animate-spin shrink-0': loading }" />
            <span>{{ t('admin.strategy.refreshBtn') }}</span>
          </button>
        </div>
      </template>
    </PageHeader>

    <p v-if="!auth.isSuperadmin" role="status" class="st-readonly">
      {{ t('admin.strategy.readonlyNotice') }}
    </p>

    <BaseLoadingAnnounce :loading="loading" />

    <!-- KPI Strip -->
    <section v-if="state" class="card st-kpi-strip">
      <div class="st-kpi-cell">
        <span class="st-kpi-label">{{ t('admin.strategy.kpiEngineState') }}</span>
        <strong class="st-kpi-value" :class="isPaused ? 'is-warn' : 'is-up'">
          {{ isPaused ? t('admin.strategy.kpiEnginePaused') : t('admin.strategy.kpiEngineRunning') }}
        </strong>
      </div>
      <div class="st-kpi-cell">
        <span class="st-kpi-label">{{ t('admin.strategy.kpiOrderMode') }}</span>
        <strong class="st-kpi-value mono">{{ state.risk?.order_mode || 'limit' }}</strong>
      </div>
      <div class="st-kpi-cell">
        <span class="st-kpi-label">{{ t('admin.strategy.kpiCouncil') }}</span>
        <strong class="st-kpi-value">
          {{ state.council?.enabled !== false ? t('admin.strategy.enabledBadge') : t('admin.strategy.disabledBadge') }}
        </strong>
      </div>
      <div class="st-kpi-cell">
        <span class="st-kpi-label">{{ t('admin.strategy.kpiEvolution') }}</span>
        <strong class="st-kpi-value">
          {{ state.evolution?.enabled !== false ? t('admin.strategy.enabledBadge') : t('admin.strategy.disabledBadge') }}
        </strong>
      </div>
    </section>

    <div class="wb-tabs-wrap">
      <BaseTabs v-model="activeTab" baseId="st" :label="t('admin.strategy.title')" :items="tabItems">
        <div
          id="st-panel-risk"
          role="tabpanel"
          aria-labelledby="st-tab-risk"
          v-show="activeTab === 'risk'"
        >
          <StrategyRiskTab :state="state" :isSuperadmin="auth.isSuperadmin" @refresh="loadState" />
        </div>
        <div
          id="st-panel-council"
          role="tabpanel"
          aria-labelledby="st-tab-council"
          v-show="activeTab === 'council'"
        >
          <StrategyCouncilTab :state="state" :isSuperadmin="auth.isSuperadmin" @refresh="loadState" />
        </div>
        <div
          id="st-panel-prompt"
          role="tabpanel"
          aria-labelledby="st-tab-prompt"
          v-show="activeTab === 'prompt'"
        >
          <StrategyPromptTab :state="state" :isSuperadmin="auth.isSuperadmin" @refresh="loadState" />
        </div>
        <div
          id="st-panel-evolution"
          role="tabpanel"
          aria-labelledby="st-tab-evolution"
          v-show="activeTab === 'evolution'"
        >
          <StrategyEvolutionTab :state="state" :isSuperadmin="auth.isSuperadmin" @refresh="loadState" />
        </div>
        <div
          id="st-panel-schedule"
          role="tabpanel"
          aria-labelledby="st-tab-schedule"
          v-show="activeTab === 'schedule'"
        >
          <StrategyScheduleTab :state="state" :isSuperadmin="auth.isSuperadmin" @refresh="loadState" />
        </div>
      </BaseTabs>
    </div>
  </div>
</template>

<style scoped>
.st-page {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}
.st-header-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-3);
  flex-wrap: wrap;
}
.st-header-switch {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
}
.st-switch-label {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.st-readonly {
  margin: 0;
  padding: var(--ds-space-3) var(--ds-space-4);
  border: 1px solid var(--warn-line);
  border-radius: var(--r-ctl);
  background-color: var(--warn-bg);
  color: var(--warn);
  font-size: var(--text-base);
}
.st-kpi-strip {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
}
.st-kpi-cell {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--ds-space-4) var(--ds-space-5);
  border-right: 1px solid var(--ds-color-border-subtle);
}
.st-kpi-cell:last-child {
  border-right: 0;
}
.st-kpi-label {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.st-kpi-value {
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.st-kpi-value.is-up {
  color: var(--up);
}
.st-kpi-value.is-warn {
  color: var(--warn);
}
@media (max-width: 720px) {
  .st-kpi-cell {
    border-right: 0;
    border-bottom: 1px solid var(--ds-color-border-subtle);
  }
  .st-kpi-cell:last-child {
    border-bottom: 0;
  }
}
</style>
