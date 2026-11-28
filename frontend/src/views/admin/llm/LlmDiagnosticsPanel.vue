<script setup lang="ts">
import { computed } from 'vue';
import { ArrowDown, ArrowUp, Brain, Cpu, ShieldAlert, Sparkles } from 'lucide-vue-next';
import { useI18n } from '../../../composables/useI18n';
import { useLlmCtx } from './injection';

const { t } = useI18n();
const { cacheStatus, cleanupResult, healthWarnings, testAllResult } = useLlmCtx();

function fmtTokensCompact(val: number | string | null | undefined): string {
  const n = Number(val || 0);
  if (!Number.isFinite(n) || n <= 0) return '0';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 10_000) return `${(n / 1_000).toFixed(1)}K`;
  return Number(n).toLocaleString();
}

const inputTokenPct = computed(() => {
  const total = cacheStatus.value?.model_stats?.total_tokens || 1;
  const inp = cacheStatus.value?.model_stats?.input_tokens_total || 0;
  return Math.min(100, Math.max(0, Math.round((inp / total) * 100)));
});

const outputTokenPct = computed(() => {
  const total = cacheStatus.value?.model_stats?.total_tokens || 1;
  const out = cacheStatus.value?.model_stats?.output_tokens_total || 0;
  return Math.min(100, Math.max(0, Math.round((out / total) * 100)));
});

const reasoningTokenPct = computed(() => {
  const total = cacheStatus.value?.model_stats?.total_tokens || 1;
  const rea = cacheStatus.value?.model_stats?.reasoning_tokens_total || 0;
  return Math.min(100, Math.max(0, Math.round((rea / total) * 100)));
});
</script>

<template>
  <div class="ld-stack">
    <section v-if="healthWarnings.length || testAllResult || cleanupResult" class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title"><ShieldAlert :size="15" />{{ t('admin.llm.selfCheckTitle') }}</h2>
        </div>
      </header>

      <div v-if="healthWarnings.length" class="ld-kv-list">
        <div v-for="w in healthWarnings" :key="w.code" class="ld-item">
          <span class="badge badge-warn">{{ t('admin.llm.selfCheckWarn') }}</span>
          <span class="ld-kv-val">{{ w.detail }}</span>
        </div>
      </div>

      <div v-if="cleanupResult" class="ld-kv-list">
        <div class="ld-item">
          <span class="form-label">{{ t('admin.llm.cleanupResult') }}</span>
          <span class="ld-kv-val mono">
            {{ t('admin.llm.cleanupRemoved', undefined, { n: (cleanupResult.removed || []).length }) }}
            <template v-if="(cleanupResult.failed || []).length">
              · {{ t('admin.llm.cleanupFailed', undefined, { n: cleanupResult.failed.length }) }}
            </template>
          </span>
        </div>
      </div>

      <div v-if="testAllResult" class="ld-kv-list">
        <div v-for="row in testAllResult.rows || []" :key="row.model" class="ld-item">
          <span class="form-label mono">{{ row.model }}</span>
          <span class="ld-probe-meta mono">
            <span class="badge" :class="row.ok ? 'badge-up' : (row.skipped ? 'badge-warn' : 'badge-down')">
              {{ row.ok ? t('admin.llm.selfCheckOk') : (row.skipped ? t('admin.llm.selfCheckSkipped') : t('admin.llm.selfCheckFail')) }}
            </span>
            <span class="ld-dim">{{ row.api_format }}</span>
            <span v-if="row.latency_ms" class="ld-dim">{{ row.latency_ms }}ms</span>
            <span v-if="row.error" role="status" aria-live="polite" class="ld-err truncate" :title="row.error">
              {{ row.error }}
            </span>
          </span>
        </div>
      </div>
    </section>

    <section v-if="cacheStatus" class="card">
      <header class="card-head">
        <h2 class="card-title">
          <Cpu :size="15" class="ld-icon-brand" />
          {{ t('admin.llm.tokenUsageTitle') }}
        </h2>
        <span class="badge mono badge-up" :title="`Total: ${Number(cacheStatus.model_stats?.total_tokens || 0).toLocaleString()} Tokens`">
          {{ t('admin.llm.totalTokensBadge') }}: {{ fmtTokensCompact(cacheStatus.model_stats?.total_tokens) }}
        </span>
      </header>

      <div class="ld-stat-grid">
        <div class="ld-stat-tile">
          <div class="ld-stat-label">
            <ArrowDown :size="12" class="ld-icon-brand" />
            <span>{{ t('admin.llm.inputTokensLabel') }}</span>
          </div>
          <div class="ld-stat-val">{{ fmtTokensCompact(cacheStatus.model_stats?.input_tokens_total) }}</div>
          <div class="ld-stat-sub">{{ t('admin.llm.inputTokensSub', undefined, { pct: inputTokenPct }) }}</div>
        </div>

        <div class="ld-stat-tile">
          <div class="ld-stat-label">
            <ArrowUp :size="12" class="ld-icon-brand" />
            <span>{{ t('admin.llm.outputTokensLabel') }}</span>
          </div>
          <div class="ld-stat-val is-accent">{{ fmtTokensCompact(cacheStatus.model_stats?.output_tokens_total) }}</div>
          <div class="ld-stat-sub">{{ t('admin.llm.outputTokensSub', undefined, { pct: outputTokenPct }) }}</div>
        </div>

        <div class="ld-stat-tile">
          <div class="ld-stat-label">
            <Brain :size="12" />
            <span>{{ t('admin.llm.reasoningTokensLabel') }}</span>
          </div>
          <div class="ld-stat-val">{{ fmtTokensCompact(cacheStatus.model_stats?.reasoning_tokens_total) }}</div>
          <div class="ld-stat-sub">{{ t('admin.llm.reasoningTokensSub', undefined, { pct: reasoningTokenPct }) }}</div>
        </div>

        <div class="ld-stat-tile">
          <div class="ld-stat-label">
            <Sparkles :size="12" class="ld-icon-brand" />
            <span>{{ t('admin.llm.cachedTokensLabel') }}</span>
          </div>
          <div class="ld-stat-val is-up">{{ fmtTokensCompact(cacheStatus.total_saved_tokens ?? 0) }}</div>
          <div class="ld-stat-sub is-up">
            {{ t('admin.llm.cachedTokensSub', undefined, { rate: `${cacheStatus.model_stats?.token_cache_rate ?? 2.3}%` }) }}
          </div>
        </div>
      </div>

      <div class="ld-breakdown">
        <div class="ld-breakdown-head">
          <span class="form-label">{{ t('admin.llm.tokenDistributionTitle') }}</span>
          <span class="ld-dim mono">{{ Number(cacheStatus.model_stats?.total_tokens || 0).toLocaleString() }} Tokens</span>
        </div>
        <div class="ld-track">
          <div class="ld-bar-input" :style="{ width: `${inputTokenPct}%` }" />
          <div class="ld-bar-output" :style="{ width: `${outputTokenPct}%` }" />
          <div class="ld-bar-reasoning" :style="{ width: `${reasoningTokenPct}%` }" />
        </div>
        <div class="ld-legend">
          <span class="ld-legend-item"><span class="ld-dot is-input" />Input ({{ inputTokenPct }}%)</span>
          <span class="ld-legend-item"><span class="ld-dot is-output" />Output ({{ outputTokenPct }}%)</span>
          <span class="ld-legend-item"><span class="ld-dot is-reasoning" />Reasoning ({{ reasoningTokenPct }}%)</span>
          <span class="ld-legend-item ld-legend-cached">
            <span class="ld-dot is-cached" />Cached ({{ fmtTokensCompact(cacheStatus.total_saved_tokens ?? 0) }})
          </span>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.ld-stack {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}
.ld-kv-list {
  display: flex;
  flex-direction: column;
}
.ld-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3) var(--ds-space-5);
  border-bottom: 1px solid var(--ds-color-border-subtle);
}
.ld-item:last-child {
  border-bottom: 0;
}
.ld-kv-val {
  font-size: var(--text-base);
  color: var(--ds-color-text-primary);
}
.ld-probe-meta {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  min-width: 0;
}
.ld-dim {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.ld-err {
  max-width: 24ch;
  font-size: var(--text-xs);
  color: var(--down);
}
.ld-icon-brand {
  color: var(--ds-color-brand);
}
.ld-stat-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--ds-space-3);
  padding: var(--ds-space-5);
}
@media (max-width: 900px) {
  .ld-stat-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
    padding: var(--ds-space-4);
  }
}
.ld-stat-tile {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
  border: 1px solid var(--ds-color-border-subtle);
  min-width: 0;
}
.ld-stat-label {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-description);
}
.ld-stat-val {
  font-size: var(--text-xl);
  font-weight: 700;
  font-family: var(--font-mono);
  color: var(--ds-color-text-primary);
  font-variant-numeric: tabular-nums;
}
.ld-stat-val.is-up {
  color: var(--up);
}
.ld-stat-val.is-accent {
  color: var(--ds-color-brand);
}
.ld-stat-sub {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.ld-stat-sub.is-up {
  color: var(--up);
}
.ld-breakdown {
  margin: 0 var(--ds-space-5) var(--ds-space-5);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
  border: 1px solid var(--ds-color-border-subtle);
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
}
.ld-breakdown-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
}
.ld-track {
  width: 100%;
  height: 8px;
  border-radius: var(--r-pill);
  background-color: var(--ds-color-bg-card);
  overflow: hidden;
  display: flex;
}
.ld-bar-input {
  height: 100%;
  background-color: var(--brand);
}
.ld-bar-output {
  height: 100%;
  background-color: var(--ds-color-brand);
}
.ld-bar-reasoning {
  height: 100%;
  background-color: var(--brand);
  opacity: 0.65;
}
.ld-legend {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sp-3) var(--ds-space-4);
  font-size: var(--text-xs);
  color: var(--ds-color-text-secondary);
}
.ld-legend-item {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-3);
}
.ld-legend-cached {
  margin-left: auto;
}
.ld-dot {
  width: 8px;
  height: 8px;
  border-radius: var(--r-pill);
  display: inline-block;
}
.ld-dot.is-input {
  background-color: var(--brand);
}
.ld-dot.is-output {
  background-color: var(--ds-color-brand);
}
.ld-dot.is-reasoning {
  background-color: var(--brand);
  opacity: 0.65;
}
.ld-dot.is-cached {
  background-color: var(--up);
}
</style>
