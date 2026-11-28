<script setup lang="ts">
import { computed, ref } from 'vue';
import {
  RefreshCw,
  ShieldCheck,
  FileText,
  Users,
  Layers,
  History,
  Sparkles,
  AlertTriangle,
  CheckCircle2,
} from 'lucide-vue-next';
import BaseSegmented from '../../../components/base/BaseSegmented.vue';
import { useI18n } from '../../../composables/useI18n';
import type { AgentInspectorPayload } from './agentLogic';

type InspectorTab = 'overview' | 'risk' | 'prompt' | 'council' | 'snapshots';

const props = defineProps<{
  summary: Record<string, any> | null;
  inspector?: AgentInspectorPayload | null;
  loading?: boolean;
}>();

const emit = defineEmits<{
  (e: 'refresh'): void;
  (e: 'ask', promptText: string): void;
}>();

const { t } = useI18n();
const activeTab = ref<InspectorTab>('overview');

const tabOptions = computed(() => [
  { value: 'overview' as InspectorTab, label: t('admin.agent.tabOverview') },
  { value: 'risk' as InspectorTab, label: t('admin.agent.tabRisk') },
  { value: 'prompt' as InspectorTab, label: t('admin.agent.tabPrompt') },
  { value: 'council' as InspectorTab, label: t('admin.agent.tabCouncil') },
  { value: 'snapshots' as InspectorTab, label: t('admin.agent.tabSnapshots') },
]);

const ov = computed<Record<string, any>>(() => props.inspector?.overview || props.summary || {});
const riskAudit = computed<Record<string, any>>(
  () => props.inspector?.risk?.risk_audit || ov.value?.risk?.risk_audit || {},
);
const auditBadgeClass = computed(() => {
  const s = riskAudit.value?.status;
  if (s === 'critical') return 'badge-down';
  if (s === 'warning') return 'badge-warn';
  return 'badge-up';
});
const auditBadgeLabel = computed(() => {
  const crit = Number(riskAudit.value?.critical_count || 0);
  const warn = Number(riskAudit.value?.warning_count || 0);
  if (crit > 0) return t('admin.agent.inspectorAuditCritical', undefined, { count: crit });
  if (warn > 0) return t('admin.agent.inspectorAuditWarning', undefined, { count: warn });
  return t('admin.agent.inspectorAuditHealthy');
});

const tradingSystemModules = computed<any[]>(() => {
  const mods = props.inspector?.prompt?.pipelines?.trading_system;
  return Array.isArray(mods) ? mods : [];
});

const councilRoles = computed<any[]>(() => {
  const inspRoles = props.inspector?.council?.config?.roles;
  if (inspRoles && typeof inspRoles === 'object') {
    const healthMap: Record<string, any> = {};
    for (const h of props.inspector?.council?.model_health || []) {
      healthMap[h.role_id] = h;
    }
    return Object.entries(inspRoles).map(([id, r]: [string, any]) => ({
      id,
      name: r?.name || id,
      enabled: r?.enabled !== false,
      weight: r?.weight ?? 0.3,
      model_id: r?.model_id || '',
      registered: healthMap[id]?.registered ?? true,
    }));
  }
  return ov.value?.council?.roles || [];
});

const archiveList = computed<any[]>(() => {
  const arr = props.inspector?.snapshots?.archives;
  if (Array.isArray(arr) && arr.length) return arr.slice(0, 6);
  return ov.value?.policy?.latest_archive ? [ov.value.policy.latest_archive] : [];
});

function askQuick(key: string) {
  emit('ask', t(key));
}
</script>

<template>
  <aside class="ag-side" :aria-label="t('admin.agent.summaryTitle')">
    <header class="card-head">
      <h2 class="ag-side-title">{{ t('admin.agent.summaryTitle') }}</h2>
      <button
        type="button"
        class="btn btn-quiet btn-icon btn-sm"
        :aria-label="t('admin.agent.summaryRefreshAria')"
        :title="t('admin.agent.summaryRefreshTitle')"
        @click="emit('refresh')"
      >
        <RefreshCw :size="14" class="shrink-0" :class="{ 'animate-spin': props.loading }" />
      </button>
    </header>

    <div class="ag-side-tabs">
      <BaseSegmented
        v-model="activeTab"
        :options="tabOptions"
        :label="t('admin.agent.inspectorTabsLabel')"
      />
    </div>

    <div v-if="ov && Object.keys(ov).length" class="ag-side-body scroll-area">
      <!-- Tab 1: Overview -->
      <template v-if="activeTab === 'overview'">
        <section class="ag-sum-block">
          <div class="ag-sum-head">
            <span class="ag-sum-label"><ShieldCheck :size="12" />{{ t('admin.agent.summaryRisk') }}</span>
            <span class="badge mono">{{ ov.risk?.active_suite_id || 'custom' }}</span>
          </div>
          <div class="ag-kv-list mono num">
            <div>
              <span>{{ t('admin.agent.inspectorOrderMode') }}</span>
              <strong>{{ ov.risk?.order_mode || 'limit' }}</strong>
            </div>
            <div>
              <span>MAX LEV</span>
              <strong>{{ ov.risk?.max_leverage ?? '—' }}x</strong>
            </div>
            <div>
              <span>MIN RR</span>
              <strong>{{ ov.risk?.min_risk_reward ?? '—' }}</strong>
            </div>
            <div>
              <span>MIN CONF</span>
              <strong>{{ ov.risk?.min_entry_confidence ?? '—' }}%</strong>
            </div>
          </div>
          <div class="ag-sum-head">
            <span class="ag-sum-meta">{{ t('admin.agent.inspectorRiskAudit') }}</span>
            <span class="badge mono" :class="auditBadgeClass">
              <AlertTriangle v-if="riskAudit?.status === 'critical' || riskAudit?.status === 'warning'" :size="11" />
              <CheckCircle2 v-else :size="11" />
              <span>{{ auditBadgeLabel }}</span>
            </span>
          </div>
          <button type="button" class="btn btn-ghost btn-sm ag-ask-btn" @click="askQuick('admin.agent.summaryAskRiskPrompt')">
            {{ t('admin.agent.summaryAskRisk') }}
          </button>
        </section>

        <section class="ag-sum-block">
          <div class="ag-sum-head">
            <span class="ag-sum-label"><Layers :size="12" />{{ t('admin.agent.summaryInstruments') }}</span>
            <span class="badge mono num">{{ ov.instruments?.count ?? 0 }}/{{ ov.instruments?.max_pool_size ?? 20 }}</span>
          </div>
          <div class="ag-sum-head">
            <span class="ag-sum-label"><Sparkles :size="12" />{{ t('admin.agent.summaryEvolution') }}</span>
            <span class="badge mono num">{{ ov.evolution?.enabled_lessons ?? 0 }}/{{ ov.evolution?.total_lessons ?? 0 }}</span>
          </div>
          <div class="ag-sum-meta mono">
            {{ t('admin.agent.summarySessionWindow') }}: {{ ov.trading_session?.enabled ? t('admin.agent.summaryEnabled') : t('admin.agent.summaryDisabled') }}
          </div>
          <button type="button" class="btn btn-ghost btn-sm ag-ask-btn" @click="askQuick('admin.agent.summaryAskSessionPrompt')">
            {{ t('admin.agent.summaryAskSession') }}
          </button>
        </section>
      </template>

      <!-- Tab 2: Risk -->
      <template v-else-if="activeTab === 'risk'">
        <section class="ag-sum-block">
          <div class="ag-sum-head">
            <span class="ag-sum-label"><ShieldCheck :size="12" />{{ t('admin.agent.inspectorRiskAudit') }}</span>
            <span class="badge mono" :class="auditBadgeClass">{{ auditBadgeLabel }}</span>
          </div>
          <div class="ag-kv-list mono num">
            <div>
              <span>{{ t('admin.agent.inspectorMaxTheoreticalRr') }}</span>
              <strong>{{ riskAudit.theoretical_max_rr ?? '—' }}</strong>
            </div>
            <div>
              <span>SL ATR</span>
              <strong>{{ riskAudit.sl_atr_mult ?? '—' }}x</strong>
            </div>
            <div>
              <span>TP CAP ATR</span>
              <strong>{{ riskAudit.max_take_profit_atr ?? '—' }}x</strong>
            </div>
            <div>
              <span>MIN RR</span>
              <strong>{{ riskAudit.min_risk_reward ?? ov.risk?.min_risk_reward ?? '—' }}</strong>
            </div>
          </div>
          <ul v-if="(riskAudit.issues || []).length" class="ag-issue-list">
            <li v-for="iss in riskAudit.issues" :key="iss.code" class="ag-issue-item">
              <strong>{{ iss.title }}</strong>
              <span>{{ iss.detail }}</span>
            </li>
          </ul>
          <button type="button" class="btn btn-ghost btn-sm ag-ask-btn" @click="emit('ask', t('admin.agent.inspectorAskCancelCheck'))">
            {{ t('admin.agent.inspectorAskCancelCheck') }}
          </button>
        </section>
      </template>

      <!-- Tab 3: Prompt -->
      <template v-else-if="activeTab === 'prompt'">
        <section class="ag-sum-block">
          <div class="ag-sum-head">
            <span class="ag-sum-label"><FileText :size="12" />{{ t('admin.agent.summaryPrompt') }}</span>
            <span class="badge mono">{{ ov.prompt?.active_profile_id || '—' }}</span>
          </div>
          <div class="ag-sum-val truncate">
            {{ ov.prompt?.active_profile_name || ov.prompt?.active_profile_id || '—' }}
          </div>
          <div class="ag-sum-meta mono">
            {{ t('admin.agent.inspectorModulesCount', undefined, {
              enabled: ov.prompt?.pipelines?.trading_system?.enabled ?? 0,
              total: ov.prompt?.pipelines?.trading_system?.total ?? 0,
            }) }}
          </div>
          <div v-if="tradingSystemModules.length" class="ag-mod-list">
            <div v-for="m in tradingSystemModules" :key="m.id" class="ag-mod-row">
              <div class="ag-mod-top">
                <span class="ag-mod-name truncate">{{ m.title }}</span>
                <span class="badge mono" :class="m.locked ? 'badge-warn' : m.enabled ? 'badge-up' : ''">
                  {{ m.id }}
                </span>
              </div>
              <p v-if="m.preview" class="ag-mod-prev">{{ m.preview }}</p>
            </div>
          </div>
          <button type="button" class="btn btn-ghost btn-sm ag-ask-btn" @click="askQuick('admin.agent.summaryAskPromptPrompt')">
            {{ t('admin.agent.summaryAskPrompt') }}
          </button>
        </section>
      </template>

      <!-- Tab 4: Council -->
      <template v-else-if="activeTab === 'council'">
        <section class="ag-sum-block">
          <div class="ag-sum-head">
            <span class="ag-sum-label"><Users :size="12" />{{ t('admin.agent.summaryCouncil') }}</span>
            <span class="badge" :class="ov.council?.enabled ? 'badge-up' : ''">
              {{ ov.council?.enabled ? t('admin.agent.summaryEnabled') : t('admin.agent.summaryDisabled') }}
            </span>
          </div>
          <div class="ag-sum-meta mono">
            {{ ov.council?.consensus_mode || 'standard' }} · {{ ov.council?.timeout_seconds ?? 240 }}s
          </div>
          <div class="ag-mod-list">
            <div v-for="role in councilRoles" :key="role.id" class="ag-mod-row">
              <div class="ag-mod-top">
                <span class="ag-mod-name truncate">{{ role.name }}</span>
                <span class="badge mono" :class="role.enabled ? (role.registered ? 'badge-up' : 'badge-warn') : ''">
                  w={{ role.weight }}
                </span>
              </div>
              <span class="ag-sum-meta mono truncate">{{ role.model_id || 'auto-brain' }}</span>
            </div>
          </div>
          <button type="button" class="btn btn-ghost btn-sm ag-ask-btn" @click="askQuick('admin.agent.summaryAskCouncilPrompt')">
            {{ t('admin.agent.summaryAskCouncil') }}
          </button>
        </section>
      </template>

      <!-- Tab 5: Snapshots -->
      <template v-else>
        <section class="ag-sum-block">
          <div class="ag-sum-head">
            <span class="ag-sum-label"><History :size="12" />{{ t('admin.agent.summaryPolicy') }}</span>
          </div>
          <div v-if="archiveList.length" class="ag-mod-list">
            <div v-for="arch in archiveList" :key="arch.policy_hash || arch.name" class="ag-mod-row">
              <span class="ag-mod-name truncate">{{ arch.name }}</span>
              <span class="ag-sum-meta mono truncate">
                {{ String(arch.policy_hash || '').slice(0, 12) }} · {{ arch.archived_at || '' }}
              </span>
            </div>
          </div>
          <div v-else class="ag-sum-meta">
            {{ t('admin.agent.summaryNoSnapshot') }}
          </div>
        </section>
      </template>
    </div>
  </aside>
</template>

<style scoped>
.ag-side {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-card);
  background-color: var(--ds-color-bg-surface-1);
  overflow: hidden;
  max-height: 100%;
}
.ag-side-title {
  margin: 0;
  font-size: var(--text-3xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ag-side-tabs {
  padding: var(--ds-space-2) var(--ds-space-3);
  border-bottom: 1px solid var(--ds-color-border-subtle);
  overflow-x: auto;
}
.ag-side-body {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3);
  overflow-y: auto;
}
.ag-sum-block {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3);
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
}
.ag-sum-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
}
.ag-sum-label {
  display: inline-flex;
  align-items: center;
  gap: var(--ds-space-1);
  font-size: var(--text-4xs);
  font-weight: 600;
  color: var(--ds-color-text-description);
}
.ag-sum-val {
  font-size: var(--text-3xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ag-sum-meta {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.ag-kv-list {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--ds-space-2);
  font-size: var(--text-4xs);
}
.ag-kv-list > div {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--ds-space-1) var(--ds-space-2);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-1);
  color: var(--ds-color-text-placeholder);
}
.ag-kv-list strong {
  color: var(--ds-color-text-primary);
}
.ag-issue-list,
.ag-mod-list {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-1);
  margin: 0;
  padding: 0;
  list-style: none;
}
.ag-issue-item,
.ag-mod-row {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: var(--ds-space-2);
  border-radius: var(--r-ctl);
  border: 1px solid var(--ds-color-border-subtle);
  background: var(--ds-color-bg-surface-1);
  font-size: var(--text-4xs);
}
.ag-mod-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-1);
}
.ag-mod-name {
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ag-mod-prev {
  margin: 0;
  color: var(--ds-color-text-description);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.ag-ask-btn {
  width: 100%;
  justify-content: center;
}
</style>
