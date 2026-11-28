<script setup lang="ts">
import { RefreshCw, ShieldCheck, FileText, Users, Layers, History, Sparkles } from 'lucide-vue-next';
import { useI18n } from '../../../composables/useI18n';

const props = defineProps<{
  summary: Record<string, any> | null;
  loading?: boolean;
}>();

const emit = defineEmits<{
  (e: 'refresh'): void;
  (e: 'ask', promptText: string): void;
}>();

const { t } = useI18n();

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

    <div v-if="props.summary" class="ag-side-body">
      <section class="ag-sum-block">
        <div class="ag-sum-head">
          <span class="ag-sum-label"><ShieldCheck :size="12" />{{ t('admin.agent.summaryRisk') }}</span>
          <span class="badge mono">{{ props.summary.risk?.active_suite_id || 'custom' }}</span>
        </div>
        <div class="ag-kv-list mono num">
          <div>
            <span>MAX LEV</span>
            <strong>{{ props.summary.risk?.max_leverage ?? '—' }}x</strong>
          </div>
          <div>
            <span>MAX POS</span>
            <strong>{{ props.summary.risk?.max_positions ?? '—' }}</strong>
          </div>
          <div>
            <span>MIN RR</span>
            <strong>{{ props.summary.risk?.min_risk_reward ?? '—' }}</strong>
          </div>
          <div>
            <span>MIN CONF</span>
            <strong>{{ props.summary.risk?.min_entry_confidence ?? '—' }}%</strong>
          </div>
        </div>
        <button type="button" class="btn btn-ghost btn-sm ag-ask-btn" @click="askQuick('admin.agent.summaryAskRiskPrompt')">
          {{ t('admin.agent.summaryAskRisk') }}
        </button>
      </section>

      <section class="ag-sum-block">
        <div class="ag-sum-head">
          <span class="ag-sum-label"><FileText :size="12" />{{ t('admin.agent.summaryPrompt') }}</span>
        </div>
        <div class="ag-sum-val truncate">
          {{ props.summary.prompt?.active_profile_name || props.summary.prompt?.active_profile_id || '—' }}
        </div>
        <div class="ag-kv-list mono num">
          <div>
            <span>TRADING SYS</span>
            <strong>{{ props.summary.prompt?.pipelines?.trading_system?.enabled ?? 0 }}/{{ props.summary.prompt?.pipelines?.trading_system?.total ?? 0 }}</strong>
          </div>
          <div>
            <span>TRADING USR</span>
            <strong>{{ props.summary.prompt?.pipelines?.trading_user?.enabled ?? 0 }}/{{ props.summary.prompt?.pipelines?.trading_user?.total ?? 0 }}</strong>
          </div>
        </div>
        <button type="button" class="btn btn-ghost btn-sm ag-ask-btn" @click="askQuick('admin.agent.summaryAskPromptPrompt')">
          {{ t('admin.agent.summaryAskPrompt') }}
        </button>
      </section>

      <section class="ag-sum-block">
        <div class="ag-sum-head">
          <span class="ag-sum-label"><Users :size="12" />{{ t('admin.agent.summaryCouncil') }}</span>
          <span class="badge" :class="props.summary.council?.enabled ? 'badge-up' : ''">
            {{ props.summary.council?.enabled ? t('admin.agent.summaryEnabled') : t('admin.agent.summaryDisabled') }}
          </span>
        </div>
        <div class="ag-sum-meta mono">
          {{ props.summary.council?.consensus_mode || 'standard' }} · {{ (props.summary.council?.roles || []).filter((r: any) => r.enabled).length }} seats
        </div>
        <button type="button" class="btn btn-ghost btn-sm ag-ask-btn" @click="askQuick('admin.agent.summaryAskCouncilPrompt')">
          {{ t('admin.agent.summaryAskCouncil') }}
        </button>
      </section>

      <section class="ag-sum-block">
        <div class="ag-sum-head">
          <span class="ag-sum-label"><Layers :size="12" />{{ t('admin.agent.summaryInstruments') }}</span>
          <span class="badge mono num">{{ props.summary.instruments?.count ?? 0 }}/{{ props.summary.instruments?.max_pool_size ?? 20 }}</span>
        </div>
        <div class="ag-sum-head mt-1">
          <span class="ag-sum-label"><Sparkles :size="12" />{{ t('admin.agent.summaryEvolution') }}</span>
          <span class="badge mono num">{{ props.summary.evolution?.enabled_lessons ?? 0 }}/{{ props.summary.evolution?.total_lessons ?? 0 }}</span>
        </div>
        <div class="ag-sum-meta mono">
          {{ t('admin.agent.summarySessionWindow') }}: {{ props.summary.trading_session?.enabled ? t('admin.agent.summaryEnabled') : t('admin.agent.summaryDisabled') }}
        </div>
        <button type="button" class="btn btn-ghost btn-sm ag-ask-btn" @click="askQuick('admin.agent.summaryAskSessionPrompt')">
          {{ t('admin.agent.summaryAskSession') }}
        </button>
      </section>

      <section class="ag-sum-block">
        <div class="ag-sum-head">
          <span class="ag-sum-label"><History :size="12" />{{ t('admin.agent.summaryPolicy') }}</span>
        </div>
        <div v-if="props.summary.policy?.latest_archive" class="ag-sum-meta mono truncate">
          {{ props.summary.policy.latest_archive.name }} · {{ String(props.summary.policy.latest_archive.policy_hash || '').slice(0, 12) }}
        </div>
        <div v-else class="ag-sum-meta">
          {{ t('admin.agent.summaryNoSnapshot') }}
        </div>
      </section>
    </div>
  </aside>
</template>

<style scoped>
.ag-side {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-card);
  background-color: var(--ds-color-bg-surface);
  overflow: hidden;
}
.ag-side-title {
  margin: 0;
  font-size: var(--text-3xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ag-side-body {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3);
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
  background-color: var(--ds-color-bg-surface);
  color: var(--ds-color-text-placeholder);
}
.ag-kv-list strong {
  color: var(--ds-color-text-primary);
}
.ag-ask-btn {
  width: 100%;
  justify-content: center;
}
</style>
