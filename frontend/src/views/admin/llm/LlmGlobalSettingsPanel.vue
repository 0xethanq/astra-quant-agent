<script setup lang="ts">
import { AlertCircle, CheckCircle2, Clock, RefreshCw, Save } from 'lucide-vue-next';
import { useI18n } from '../../../composables/useI18n';
import { useLlmCtx } from './injection';

const { t } = useI18n();
const {
  cfg,
  reasoningEffortInput,
  saveGlobalSettings,
  savingSettings,
  setPresetTimeout,
  settingsResult,
  thinkingTimeoutInput,
} = useLlmCtx()

const TIMEOUT_PRESETS = [
  { sec: 30, labelKey: 'admin.llm.presetFast' },
  { sec: 60, labelKey: 'admin.llm.presetStd' },
  { sec: 120, labelKey: 'admin.llm.presetRec' },
  { sec: 180, labelKey: 'admin.llm.presetDeep' },
  { sec: 300, labelKey: 'admin.llm.presetLong' },
];

const EFFORT_PRESETS = [
  { value: 'high', label: 'HIGH' },
  { value: 'medium', label: 'MEDIUM' },
  { value: 'low', label: 'LOW' },
  { value: 'minimal', label: 'MINIMAL' },
  { value: 'none', label: 'NONE' },
  { value: 'auto', label: 'AUTO' },
];
</script>

<template>
  <section class="card">
    <header class="card-head">
      <div>
        <h2 class="card-title"><Clock :size="15" />{{ t('admin.llm.globalTimeoutTitle') }}</h2>
      </div>
      <div class="lg-head-actions">
        <span class="badge mono">{{ t('admin.llm.currentLimit', undefined, { n: cfg?.thinking_timeout || 120 }) }}</span>
        <button type="button" class="btn btn-primary btn-sm" :disabled="savingSettings" @click="saveGlobalSettings">
          <RefreshCw v-if="savingSettings" :size="14" class="animate-spin shrink-0" />
          <Save v-else :size="14" />
          <span>{{ savingSettings ? t('admin.llm.saving') : t('admin.llm.saveReasoning') }}</span>
        </button>
      </div>
    </header>

    <div class="lg-body">
      <div class="lg-kv">
        <span class="form-label">{{ t('admin.llm.activeModel') }}</span>
        <span class="lg-kv-v mono" :class="cfg?.active_model_id ? 'is-accent' : 'is-off'">
          {{ cfg?.active_model_id || t('admin.llm.notSelected') }}
        </span>
      </div>
      <div class="lg-kv">
        <span class="form-label">{{ t('admin.llm.effort') }}</span>
        <span class="lg-kv-v mono">{{ (reasoningEffortInput || cfg?.active_reasoning_effort || 'HIGH').toUpperCase() }}</span>
      </div>
    </div>

    <div class="lg-field">
      <div class="lg-field-head">
        <span class="form-label">{{ t('admin.llm.effort') }}</span>
      </div>
      <div class="lg-presets">
        <span class="form-label">{{ t('admin.llm.presetLabel') }}</span>
        <button
          v-for="opt in EFFORT_PRESETS"
          :key="opt.value"
          type="button"
          class="lg-preset"
          :class="{ 'is-on': (reasoningEffortInput || 'high').toLowerCase() === opt.value }"
          @click="reasoningEffortInput = opt.value"
        >
          {{ opt.label }}
        </button>
      </div>
    </div>

    <div class="lg-field">
      <div class="lg-field-head">
        <span class="form-label">{{ t('admin.llm.timeoutLabel') }}</span>
        <span class="lg-hint">{{ t('admin.llm.validRange') }}</span>
      </div>
      <div class="lg-field-row">
        <div class="lg-num focus-ring">
          <input
            v-model.number="thinkingTimeoutInput"
            type="number"
            inputmode="numeric"
            min="10"
            max="1800"
            step="5"
            placeholder="120"
            class="lg-num-input"
            :aria-label="t('admin.llm.timeoutLabel')"
          />
          <span class="lg-num-unit">{{ t('admin.llm.secondsUnit') }}</span>
        </div>
        <div class="lg-presets">
          <span class="form-label">{{ t('admin.llm.presetLabel') }}</span>
          <button
            v-for="p in TIMEOUT_PRESETS"
            :key="p.sec"
            type="button"
            class="lg-preset"
            :class="{ 'is-on': thinkingTimeoutInput === p.sec }"
            @click="setPresetTimeout(p.sec)"
          >
            {{ t(p.labelKey) }}
          </button>
        </div>
      </div>
    </div>

    <div
      v-if="settingsResult"
      class="lg-result"
      :role="settingsResult.ok ? 'status' : 'alert'"
      :class="settingsResult.ok ? 'is-ok' : 'is-error'"
    >
      <CheckCircle2 v-if="settingsResult.ok" :size="14" />
      <AlertCircle v-else :size="14" />
      <span>{{ settingsResult.message || settingsResult.error }}</span>
    </div>
  </section>
</template>

<style scoped>
.lg-head-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.lg-body {
  display: grid;
  grid-template-columns: 1fr;
  border-bottom: 1px solid var(--ds-color-border-subtle);
}
@media (min-width: 700px) {
  .lg-body {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.lg-kv {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3) var(--ds-space-5);
}
@media (min-width: 700px) {
  .lg-kv + .lg-kv {
    border-left: 1px solid var(--ds-color-border-subtle);
  }
}
.lg-kv-v {
  font-size: var(--text-base);
  color: var(--ds-color-text-primary);
  overflow-wrap: anywhere;
}
.lg-kv-v.is-accent {
  color: var(--ds-color-brand);
}
.lg-kv-v.is-off {
  color: var(--ds-color-text-placeholder);
}
.lg-field {
  padding: var(--ds-space-4) var(--ds-space-5);
}
.lg-field + .lg-field {
  border-top: 1px solid var(--ds-color-border-subtle);
}
.lg-field-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--ds-space-3);
  flex-wrap: wrap;
  margin-bottom: var(--ds-space-2);
}
.lg-field-row {
  display: flex;
  align-items: center;
  gap: var(--ds-space-4);
  flex-wrap: wrap;
}
.lg-hint {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.lg-num {
  display: flex;
  align-items: center;
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-input);
  overflow: hidden;
  flex-shrink: 0;
}
.lg-num-input {
  width: 82px;
  padding: var(--ds-space-2) var(--sp-5);
  border: 0;
  outline: none;
  background: transparent;
  color: var(--ds-color-text-primary);
  font-size: var(--text-base);
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.lg-num-unit {
  padding: 0 var(--sp-5) 0 var(--sp-1);
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
  white-space: nowrap;
}
.lg-presets {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
  min-width: 0;
}
.lg-preset {
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
.lg-preset:hover {
  background-color: var(--ds-color-bg-hover);
  color: var(--ds-color-text-primary);
}
.lg-preset.is-on {
  background-color: var(--astra-brand-bg);
  border-color: var(--astra-brand-line);
  color: var(--ds-color-brand);
  font-weight: 600;
}
.lg-result {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin: 0 var(--ds-space-5) var(--ds-space-4);
  padding: var(--ds-space-2) var(--ds-space-3);
  border-radius: var(--r-ctl);
  font-size: var(--text-base);
}
.lg-result.is-ok {
  background-color: var(--up-bg);
  color: var(--up);
}
.lg-result.is-error {
  background-color: var(--down-bg);
  color: var(--down);
}
</style>
