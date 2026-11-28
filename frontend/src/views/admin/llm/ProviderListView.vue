<script setup lang="ts">
import PageHeader from '../../../components/admin/PageHeader.vue';
import BaseSwitch from '../../../components/base/BaseSwitch.vue';
import BaseLoadingAnnounce from '../../../components/base/BaseLoadingAnnounce.vue';
import LlmGlobalSettingsPanel from './LlmGlobalSettingsPanel.vue';
import LlmDiagnosticsPanel from './LlmDiagnosticsPanel.vue';
import { fmtDateTime } from '../../../utils/format';
import { useI18n } from '../../../composables/useI18n';
import { useLlmCtx } from './injection';
import {
  ArrowDown,
  ArrowUp,
  Brain,
  History,
  Plus,
  RefreshCw,
  Route,
  Save,
  Search,
  Server,
  ShieldAlert,
  Timer,
  X,
} from 'lucide-vue-next';

const { t } = useI18n();
const {
  cfg,
  failoverEvents,
  fallbackIds,
  fallbackOptions,
  filteredProviders,
  cfgError,
  loadConfig,
  loadFailoverEvents,
  loading,
  modelNameOf,
  moveFallback,
  openAddProviderModal,
  requestAttemptsInput,
  saveGlobalSettings,
  savingSettings,
  searchQuery,
  selectProvider,
  toggleFallback,
  toggleProviderQuick,
  testAllLoading,
  testAllModels,
  cleanupDeadModels,
  cleanupLoading,
  deadModelIds,
  providerHealth,
} = useLlmCtx();

const cfgFirstLoad = () => loading.value && !cfg.value;
const cfgFailed = () => !loading.value && !cfg.value;

function failoverErrText(ev: any): string {
  const joined = (ev?.errors || []).filter(Boolean).join(' | ');
  return joined || String(ev?.chain || '');
}

const ATTEMPT_PRESETS = [1, 2, 3, 5];

function monogram(name: string): string {
  return String(name || '?').trim().slice(0, 2).toUpperCase();
}

function onToggleProvider(prov: any) {
  const evt = { stopPropagation() {} } as unknown as Event;
  void toggleProviderQuick(prov, evt);
}

const bandFacts = () => [
  {
    icon: Server,
    label: t('admin.llm.bandProviders'),
    value: String(cfg.value?.providers?.length ?? '--'),
    foot: `${(cfg.value?.providers || []).filter((p: any) => p.enabled).length} ${t('admin.llm.enabledOnList')}`,
    tone: '',
  },
  {
    icon: Brain,
    label: t('admin.llm.bandActiveModel'),
    value: cfg.value?.active_model_id || t('admin.llm.notSelected'),
    foot: cfg.value?.active_reasoning_effort ? String(cfg.value.active_reasoning_effort).toUpperCase() : 'HIGH',
    tone: cfg.value?.active_model_id ? 'is-accent' : 'is-off',
  },
  {
    icon: Timer,
    label: t('admin.llm.bandTimeout'),
    value: `${cfg.value?.thinking_timeout || 120}s`,
    foot: t('admin.llm.validRangeFoot'),
    tone: '',
  },
  {
    icon: Route,
    label: t('admin.llm.bandFallback'),
    value: String(fallbackIds.value.length),
    foot: fallbackIds.value.length ? modelNameOf(fallbackIds.value[0]) : t('admin.llm.noFallbackFoot'),
    tone: fallbackIds.value.length ? '' : 'is-off',
  },
];
</script>

<template>
  <div class="pv">
    <PageHeader :title="t('nav.admin.llm')">
      <template #actions>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="loading" @click="loadConfig">
          <RefreshCw :size="14" :class="loading && 'animate-spin shrink-0'" />
          <span>{{ t('admin.llm.refreshStatus') }}</span>
        </button>
        <button
          type="button"
          class="btn btn-ghost btn-sm"
          :disabled="testAllLoading"
          :title="t('admin.llm.testAllTitle')"
          @click="testAllModels()"
        >
          <ShieldAlert :size="14" :class="testAllLoading && 'animate-spin shrink-0'" />
          <span>{{ testAllLoading ? t('admin.llm.testingAll') : t('admin.llm.testAll') }}</span>
        </button>
        <button
          v-if="deadModelIds.length"
          type="button"
          class="btn btn-ghost btn-sm is-danger"
          :disabled="cleanupLoading"
          :title="t('admin.llm.cleanupDeadTitle')"
          @click="cleanupDeadModels()"
        >
          <X :size="14" />
          <span>{{ t('admin.llm.cleanupDead', undefined, { n: deadModelIds.length }) }}</span>
        </button>
        <button type="button" class="btn btn-primary btn-sm" :title="t('admin.llm.addProviderTitle')" @click="openAddProviderModal">
          <Plus :size="14" />
          <span>{{ t('admin.llm.addProvider') }}</span>
        </button>
      </template>
    </PageHeader>

    <!-- Status Band -->
    <section class="card band">
      <div v-for="f in bandFacts()" :key="f.label" class="fact">
        <span class="fact-label"><component :is="f.icon" :size="12" />{{ f.label }}</span>
        <span class="fact-value" :class="f.tone">{{ f.value }}</span>
        <span class="fact-foot truncate" :title="f.foot">{{ f.foot }}</span>
      </div>
    </section>

    <LlmGlobalSettingsPanel />

    <!-- Request Resilience & Failover -->
    <section class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title"><ShieldAlert :size="15" />{{ t('admin.llm.resilienceTitle') }}</h2>
        </div>
        <div class="pv-head-actions">
          <span class="badge mono">
            {{ t('admin.llm.attemptsChip', undefined, { n: cfg?.request_attempts || 3, m: (cfg?.fallback_model_ids || []).length }) }}
          </span>
          <button type="button" class="btn btn-primary btn-sm" :disabled="savingSettings" @click="saveGlobalSettings">
            <RefreshCw v-if="savingSettings" :size="14" class="animate-spin shrink-0" />
            <Save v-else :size="14" />
            <span>{{ savingSettings ? t('admin.llm.saving') : t('admin.llm.saveResilience') }}</span>
          </button>
        </div>
      </header>

      <div class="pv-resilience">
        <div class="pv-sub">
          <div class="pv-field-head">
            <span class="form-label">{{ t('admin.llm.attemptsLabel') }}</span>
            <span class="pv-hint">{{ t('admin.llm.attemptsRange') }}</span>
          </div>
          <div class="pv-field-row">
            <div class="pv-num focus-ring">
              <input
                v-model.number="requestAttemptsInput"
                type="number"
                inputmode="numeric"
                min="1"
                max="10"
                step="1"
                class="pv-num-input"
                :aria-label="t('admin.llm.attemptsLabel')"
              />
              <span class="pv-num-unit">{{ requestAttemptsInput === 1 ? t('admin.llm.timesUnitSingular') : t('admin.llm.timesUnit') }}</span>
            </div>
            <div class="pv-presets">
              <button
                v-for="n in ATTEMPT_PRESETS"
                :key="n"
                type="button"
                class="pv-preset"
                :class="{ 'is-on': requestAttemptsInput === n }"
                @click="requestAttemptsInput = n"
              >
                {{ n === 1 ? t('admin.llm.times1', undefined, { n }) : t('admin.llm.timesN', undefined, { n }) }}
              </button>
            </div>
          </div>
        </div>

        <div class="pv-sub">
          <div class="pv-field-head">
            <span class="form-label">{{ t('admin.llm.fallbackLabel') }}</span>
            <span class="pv-hint">{{ t('admin.llm.currentBrain') }} {{ cfg?.active_model_id || '--' }}</span>
          </div>

          <p v-if="!fallbackIds.length" class="pv-empty">{{ t('admin.llm.noFallback') }}</p>
          <ol v-else class="pv-chain">
            <li v-for="(fid, idx) in fallbackIds" :key="fid" class="pv-chain-row">
              <span class="pv-chain-n mono">{{ idx + 1 }}</span>
              <span class="pv-chain-name truncate">{{ modelNameOf(fid) }}</span>
              <button type="button" class="btn btn-quiet btn-icon btn-sm" :title="t('admin.llm.moveUp')" :disabled="idx === 0" @click="moveFallback(idx, -1)">
                <ArrowUp :size="12" />
              </button>
              <button type="button" class="btn btn-quiet btn-icon btn-sm" :title="t('admin.llm.moveDown')" :disabled="idx === fallbackIds.length - 1" @click="moveFallback(idx, 1)">
                <ArrowDown :size="12" />
              </button>
              <button type="button" class="btn btn-quiet btn-icon btn-sm is-danger" :title="t('admin.llm.remove')" @click="toggleFallback(fid)">
                <X :size="12" />
              </button>
            </li>
          </ol>

          <div class="pv-pool">
            <span class="form-label">{{ t('admin.llm.toggleFallbackHint') }}</span>
            <div class="pv-pool-items">
              <button
                v-for="m in fallbackOptions"
                :key="m.id"
                type="button"
                class="pv-preset"
                :class="{ 'is-on': fallbackIds.includes(m.id) }"
                :title="m.description || m.id"
                @click="toggleFallback(m.id)"
              >
                {{ m.name || m.id }}
              </button>
              <span v-if="!fallbackOptions.length" class="pv-empty">{{ t('admin.llm.noSpareModels') }}</span>
            </div>
          </div>
        </div>
      </div>

      <div class="pv-audit-head">
        <span class="form-label pv-audit-title"><History :size="12" />{{ t('admin.llm.recentFailover') }}</span>
        <button type="button" class="btn btn-ghost btn-sm" @click="loadFailoverEvents">
          <RefreshCw :size="14" />
          <span>{{ t('admin.llm.refresh') }}</span>
        </button>
      </div>

      <p v-if="!failoverEvents.length" class="pv-empty pad">{{ t('admin.llm.noFailover') }}</p>

      <div v-else class="log-panel is-flush pv-audit">
        <div v-for="(ev, i) in failoverEvents.slice(0, 8)" :key="i" class="pv-audit-row">
          <span class="badge" :class="ev.succeeded ? 'badge-up' : 'badge-down'">
            {{ ev.type === 'fallback_hit' ? t('admin.llm.fallbackHit') : t('admin.llm.chainDead') }}
          </span>
          <span class="pv-audit-chain mono truncate" :title="`${ev.from_model}${ev.to_model ? ' -> ' + ev.to_model : ''}`">
            {{ ev.from_model }}<template v-if="ev.to_model"> -> {{ ev.to_model }}</template>
          </span>
          <span class="pv-audit-time mono">{{ fmtDateTime(ev.ts || ev.time_str) }} · {{ ev.elapsed_seconds }}s</span>
          <span class="pv-audit-err truncate" :title="failoverErrText(ev)">
            {{ failoverErrText(ev) }}
          </span>
        </div>
      </div>
    </section>

    <LlmDiagnosticsPanel />

    <!-- Provider Matrix -->
    <section class="card">
      <header class="card-head">
        <h2 class="card-title"><Server :size="15" />{{ t('admin.llm.providersTitle') }}</h2>
        <div class="pv-head-actions">
          <div class="pv-search focus-ring">
            <Search :size="14" />
            <input
              v-model="searchQuery"
              type="search"
              autocomplete="off"
              spellcheck="false"
              :aria-label="t('admin.llm.searchPlaceholder')"
              :placeholder="t('admin.llm.searchPlaceholder')"
              class="pv-search-input"
            />
          </div>
          <span class="badge mono">{{ filteredProviders.length }}</span>
        </div>
      </header>

      <div v-if="cfgFirstLoad()" class="pv-skel">
        <BaseLoadingAnnounce />
        <div v-for="i in 4" :key="i" class="skeleton skeleton-row" />
      </div>

      <div v-else-if="cfgFailed()" role="alert" class="state-block is-error pv-gate-err">
        <span class="state-icon"><ShieldAlert :size="17" /></span>
        <p class="state-title">{{ t('common.loadFailed') }}</p>
        <p class="state-desc">{{ cfgError || t('common.networkError') }}</p>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="loading" @click="loadConfig">
          <RefreshCw :size="14" />
          <span>{{ t('common.retry') }}</span>
        </button>
      </div>

      <p v-else-if="!filteredProviders.length" class="pv-empty pad">{{ t('common.noRecords') }}</p>

      <div v-else class="pv-rows">
        <article
          v-for="prov in filteredProviders"
          :key="prov.id"
          class="pv-row clickable"
          :class="{ 'is-off': !prov.enabled }"
          role="button"
          tabindex="0"
          @click="selectProvider(prov)"
          @keydown.enter="selectProvider(prov)"
          @keydown.space.prevent="selectProvider(prov)"
        >
          <span class="icon-box is-md is-mono mono">{{ monogram(prov.name) }}</span>

          <div class="pv-main">
            <div class="pv-title">
              <span class="pv-name">{{ prov.name }}</span>
              <span v-if="prov.models?.some((m: any) => m.id === cfg?.active_model_id)" class="badge badge-up">
                {{ t('admin.llm.brainActive') }}
              </span>
              <span v-if="providerHealth(prov).dead" class="badge badge-down">
                {{ t('admin.llm.deadModels', undefined, { n: providerHealth(prov).dead }) }}
              </span>
              <span v-else-if="providerHealth(prov).warn" class="badge badge-warn">
                {{ t('admin.llm.warnModels', undefined, { n: providerHealth(prov).warn }) }}
              </span>
            </div>
            <span class="pv-meta mono">
              {{ prov.id }} · {{ prov.models_count || 0 }} {{ t('admin.llm.modelsSuffix') }} · {{ prov.group || t('admin.llm.groupOther') }}
            </span>
          </div>

          <div class="pv-actions" @click.stop>
            <span class="pv-state" :class="prov.enabled ? 'is-on' : ''">
              {{ prov.enabled ? t('admin.llm.enabledOnList') : t('admin.llm.disabledOnList') }}
            </span>
            <BaseSwitch
              :model-value="prov.enabled === true"
              :disabled="false"
              :label="`${prov.name || prov.id} · ${t('admin.llm.enabledField')}`"
              @update:model-value="() => onToggleProvider(prov)"
            />
          </div>
        </article>
      </div>
    </section>
  </div>
</template>

<style scoped>
.pv {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
  width: 100%;
  min-width: 0;
}
.pv-head-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.pv-field-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--ds-space-3);
  flex-wrap: wrap;
  margin-bottom: var(--ds-space-2);
}
.pv-field-row {
  display: flex;
  align-items: center;
  gap: var(--ds-space-4);
  flex-wrap: wrap;
}
.pv-hint {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.pv-num {
  display: flex;
  align-items: center;
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-input);
  overflow: hidden;
  flex-shrink: 0;
}
.pv-num-input {
  width: 78px;
  padding: var(--ds-space-2) var(--sp-5);
  border: 0;
  outline: none;
  background: transparent;
  color: var(--ds-color-text-primary);
  font-size: var(--text-base);
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.pv-num-unit {
  padding: 0 var(--sp-5) 0 var(--sp-1);
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
  white-space: nowrap;
}
.pv-presets {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  min-width: 0;
}
.pv-preset {
  display: inline-flex;
  align-items: center;
  min-height: 28px;
  padding: var(--sp-2) var(--sp-5);
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: transparent;
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
  cursor: pointer;
  transition: all var(--dur-fast);
}
.pv-preset:hover {
  background-color: var(--ds-color-bg-hover);
  color: var(--ds-color-text-primary);
}
.pv-preset.is-on {
  background-color: var(--astra-brand-bg);
  border-color: var(--astra-brand-line);
  color: var(--ds-color-brand);
  font-weight: 600;
}
.pv-resilience {
  display: grid;
  grid-template-columns: 1fr;
}
@media (min-width: 1000px) {
  .pv-resilience {
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  }
}
.pv-sub {
  padding: var(--ds-space-5);
  border-top: 1px solid var(--ds-color-border-subtle);
}
@media (min-width: 1000px) {
  .pv-sub {
    border-top: 0;
  }
  .pv-sub + .pv-sub {
    border-left: 1px solid var(--ds-color-border-subtle);
  }
}
.pv-empty {
  font-size: var(--text-base);
  color: var(--ds-color-text-description);
  line-height: var(--leading-body);
}
.pv-empty.pad {
  padding: var(--ds-space-5);
}
.pv-skel {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--ds-space-5);
}
.pv-gate-err {
  border-top: 1px solid var(--ds-color-border-subtle);
}
.pv-chain {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.pv-chain-row {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  padding: var(--sp-3) var(--ds-space-2);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
}
.pv-chain-n {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  border-radius: 50%;
  background-color: var(--ds-color-bg-surface-1);
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
  flex-shrink: 0;
}
.pv-chain-name {
  flex: 1;
  min-width: 0;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.pv-pool {
  margin-top: var(--ds-space-3);
  padding-top: var(--ds-space-3);
  border-top: 1px solid var(--ds-color-border-subtle);
}
.pv-pool-items {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
  margin-top: var(--sp-3);
  max-height: 120px;
  overflow-y: auto;
}
.pv-audit-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3) var(--ds-space-5) var(--sp-3);
  border-top: 1px solid var(--ds-color-border-subtle);
}
.pv-audit-title {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-3);
}
.pv-audit {
  max-height: 260px;
}
.pv-audit-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1.1fr) auto minmax(0, 1.4fr);
  align-items: center;
  gap: var(--ds-space-3);
  padding: var(--sp-3) var(--ds-space-5);
  font-size: var(--text-xs);
}
.pv-audit-row:hover {
  background-color: var(--ds-color-bg-hover);
}
.pv-audit-chain {
  color: var(--ds-color-text-secondary);
  min-width: 0;
}
.pv-audit-time {
  color: var(--ds-color-text-description);
  white-space: nowrap;
}
.pv-audit-err {
  color: var(--ds-color-text-description);
  min-width: 0;
}
@media (max-width: 900px) {
  .pv-audit-row {
    grid-template-columns: auto minmax(0, 1fr);
  }
  .pv-audit-err {
    grid-column: 2;
  }
}
.pv-search {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: 0 var(--sp-5);
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-input);
  color: var(--ds-color-text-placeholder);
}
.pv-search-input {
  width: 220px;
  padding: var(--sp-3) 0;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--ds-color-text-primary);
  font-size: var(--text-base);
}
@media (max-width: 760px) {
  .pv-search-input {
    width: 120px;
  }
}
.pv-rows {
  display: flex;
  flex-direction: column;
}
.pv-row {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--ds-space-3);
  padding: var(--ds-space-4) var(--ds-space-5);
  border-bottom: 1px solid var(--ds-color-border-subtle);
  cursor: pointer;
  transition: background-color var(--dur-fast);
}
.pv-row:last-child {
  border-bottom: 0;
}
.pv-row:hover {
  background-color: var(--ds-color-bg-hover);
}
.pv-row.is-off {
  opacity: 0.6;
}
.pv-main {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  min-width: 0;
}
.pv-title {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}
.pv-name {
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.pv-meta {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.pv-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-shrink: 0;
}
.pv-state {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-placeholder);
}
.pv-state.is-on {
  color: var(--up);
}
@media (max-width: 720px) {
  .pv-row {
    grid-template-columns: 32px minmax(0, 1fr);
  }
  .pv-actions {
    grid-column: 2;
    justify-content: flex-end;
  }
}
</style>
