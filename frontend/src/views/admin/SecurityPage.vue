<script setup lang="ts">
import { computed, provide, watch } from 'vue';
import { useRoute, useRouter } from 'vue-router';
import { AlertTriangle, Loader2, RefreshCw } from 'lucide-vue-next';
import PageHeader from '../../components/admin/PageHeader.vue';
import BaseTabs from '../../components/base/BaseTabs.vue';
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue';
import { useI18n } from '../../composables/useI18n';
import { SECURITY_KEY, useSecurityAdmin, type SecurityTabKey } from './security/useSecurityAdmin';
import SecurityVenueTab from './security/SecurityVenueTab.vue';
import SecurityPortfolioTab from './security/SecurityPortfolioTab.vue';
import SecurityEmergencyTab from './security/SecurityEmergencyTab.vue';

const route = useRoute();
const router = useRouter();
const { t } = useI18n();

const ctx = useSecurityAdmin();
provide(SECURITY_KEY, ctx);

const {
  activeTab,
  bandFacts,
  config,
  ensurePositionsLoaded,
  isUnifiedLive,
  loadAll,
  loadError,
  loading,
  orderMode,
} = ctx;

const TABS = computed<{ key: SecurityTabKey; label: string }[]>(() => [
  { key: 'venues', label: t('admin.security.tabVenues') },
  { key: 'pool', label: t('admin.security.tabPool') },
  { key: 'emergency', label: t('admin.security.tabEmergency') },
]);

function syncFromRoute() {
  const raw = String(route.query.tab || '').toLowerCase();
  const normalized: SecurityTabKey | '' = raw === 'venue' ? 'venues' : (raw as SecurityTabKey);
  if (normalized === 'venues' || normalized === 'pool' || normalized === 'emergency') {
    activeTab.value = normalized;
    if (normalized === 'emergency') ensurePositionsLoaded();
  }
}

watch(
  () => route.query.tab,
  () => {
    syncFromRoute();
  },
  { immediate: true },
);

watch(activeTab, (next) => {
  if (next === 'emergency') ensurePositionsLoaded();
  if (String(route.query.tab || '') !== next) {
    router.replace({ path: '/admin/security', query: { ...route.query, tab: next } });
  }
});
</script>

<template>
  <div class="sc">
    <PageHeader :title="t('nav.admin.security')">
      <template #actions>
        <span class="badge mono" :class="isUnifiedLive ? 'badge-warn' : 'badge-accent'">
          {{ isUnifiedLive ? t('admin.security.envLive') : t('admin.security.optDemo') }}
        </span>
        <span class="badge badge-accent mono">
          {{ orderMode === 'smart' ? t('admin.security.optSmart') : orderMode === 'market' ? t('admin.security.optMarket') : t('admin.security.optLimit') }}
        </span>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="loading" @click="loadAll">
          <Loader2 v-if="loading && config" :size="14" class="animate-spin shrink-0" />
          <RefreshCw v-else :size="14" />
          <span>{{ t('common.refresh') }}</span>
        </button>
      </template>
    </PageHeader>

    <div v-if="loading && !config" class="sc-skel">
      <BaseLoadingAnnounce />
      <div v-for="i in 6" :key="i" class="skeleton skeleton-row" />
    </div>

    <div v-else-if="loadError && !config" role="alert" class="state-block is-error">
      <span class="state-icon"><AlertTriangle :size="17" /></span>
      <p class="state-title">{{ t('common.loadFailed') }}</p>
      <p class="state-desc">{{ loadError }}</p>
      <button type="button" class="btn btn-ghost btn-sm mt-1" :disabled="loading" @click="loadAll">
        <Loader2 v-if="loading" :size="14" class="animate-spin shrink-0" />
        <RefreshCw v-else :size="14" />
        <span>{{ t('common.retry') }}</span>
      </button>
    </div>

    <template v-else-if="config">
      <section class="card band">
        <div v-for="f in bandFacts" :key="f.label" class="fact">
          <span class="fact-label"><component :is="f.icon" :size="12" />{{ f.label }}</span>
          <span class="fact-value" :class="f.tone">{{ f.value }}</span>
          <span class="fact-foot mono">{{ f.foot }}</span>
        </div>
      </section>

      <div class="wb-tabs-wrap">
        <BaseTabs v-model="activeTab" baseId="sc" :label="t('admin.security.tabsLabel')" :items="TABS">
          <div
            id="sc-panel-venues"
            role="tabpanel"
            aria-labelledby="sc-tab-venues"
            v-show="activeTab === 'venues'"
          >
            <SecurityVenueTab />
          </div>
          <div
            id="sc-panel-pool"
            role="tabpanel"
            aria-labelledby="sc-tab-pool"
            v-show="activeTab === 'pool'"
          >
            <SecurityPortfolioTab />
          </div>
          <div
            id="sc-panel-emergency"
            role="tabpanel"
            aria-labelledby="sc-tab-emergency"
            v-show="activeTab === 'emergency'"
          >
            <SecurityEmergencyTab />
          </div>
        </BaseTabs>
      </div>
    </template>
  </div>
</template>

<style scoped>
.sc {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}
.sc-skel {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
}
</style>
