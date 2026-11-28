<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { AlertTriangle, CheckCircle2, Loader2, Save, ShieldCheck, Sparkles } from 'lucide-vue-next';
import BaseSegmented from '../../../components/base/BaseSegmented.vue';
import BaseSwitch from '../../../components/base/BaseSwitch.vue';
import { useApi } from '../../../composables/useApi';
import { useI18n } from '../../../composables/useI18n';
import { useToast } from '../../../composables/useToast';

const props = defineProps<{
  state: Record<string, any> | null;
  isSuperadmin: boolean;
}>();

const emit = defineEmits<{
  (e: 'refresh'): void;
}>();

const { api } = useApi();
const { t, isEn } = useI18n();
const toast = useToast();

const formValues = reactive<Record<string, number | boolean>>({});
const confirmPhrase = ref('');
const previewResult = ref<any>(null);
const previewing = ref(false);
const saving = ref(false);
const applyingSuiteId = ref('');
const switchingOrderMode = ref(false);
const togglingScaleOut = ref(false);
const lastSnapshotHash = ref('');

let previewTimer: ReturnType<typeof setTimeout> | null = null;

const riskState = computed(() => props.state?.risk || {});
const schema = computed(() => riskState.value?.schema || { groups: [], params: [], high_risk_phrase: 'HIGH RISK' });
const suites = computed<any[]>(() => riskState.value?.suites || []);
const activeSuiteId = computed(() => String(riskState.value?.active_suite_id || 'custom'));
const currentOrderMode = computed(() => String(riskState.value?.order_mode || 'limit'));

const orderModeOptions = computed(() => [
  { value: 'limit', label: t('admin.strategy.riskOrderLimit') },
  { value: 'market', label: t('admin.strategy.riskOrderMarket') },
  { value: 'smart', label: t('admin.strategy.riskOrderSmart') },
]);

const isScaleOutEnabled = computed(() => Boolean(formValues.ASTRA_SCALE_OUT_ENABLED ?? riskState.value?.values?.ASTRA_SCALE_OUT_ENABLED));

const activeAudit = computed(() => previewResult.value?.risk_audit || riskState.value?.risk_audit || {});
const requiresHighRiskPhrase = computed(() => Boolean(previewResult.value?.high_risk));
const expectedPhrase = computed(() => String(previewResult.value?.high_risk_phrase || schema.value?.high_risk_phrase || 'HIGH RISK'));

const isPhraseInvalid = computed(() => {
  const v = confirmPhrase.value.trim();
  if (!v || !requiresHighRiskPhrase.value) return false;
  return v.toUpperCase() !== expectedPhrase.value.toUpperCase();
});

const canSave = computed(() => {
  if (!props.isSuperadmin || saving.value) return false;
  if (previewResult.value && previewResult.value.valid === false) return false;
  if (requiresHighRiskPhrase.value) {
    return confirmPhrase.value.trim().toUpperCase() === expectedPhrase.value.toUpperCase();
  }
  return true;
});

watch(
  () => riskState.value?.values,
  (vals) => {
    if (!vals || typeof vals !== 'object') return;
    for (const [k, v] of Object.entries(vals)) {
      formValues[k] = v as number | boolean;
    }
    previewResult.value = null;
    confirmPhrase.value = '';
  },
  { immediate: true },
);

function groupedParams(groupId: string): any[] {
  return (schema.value?.params || []).filter((p: any) => p.group === groupId && p.type !== 'bool');
}

function displayValue(param: any): number {
  const raw = Number(formValues[param.key] ?? 0);
  const scale = Number(param.display_scale || 1);
  return Number((raw * scale).toFixed(4));
}

function updateDisplayValue(param: any, rawInput: string) {
  const num = Number(rawInput);
  if (!Number.isFinite(num)) return;
  const scale = Number(param.display_scale || 1);
  formValues[param.key] = param.type === 'int' ? Math.round(num / scale) : Number((num / scale).toFixed(6));
  schedulePreview();
}

function schedulePreview() {
  if (previewTimer) clearTimeout(previewTimer);
  previewTimer = setTimeout(() => {
    void runPreview();
  }, 260);
}

async function runPreview() {
  previewing.value = true;
  try {
    previewResult.value = await api('/api/v1/admin/control-plane/risk/preview', {
      method: 'POST',
      body: JSON.stringify({ values: { ...formValues } }),
    });
  } catch {
    /* non-blocking preview */
  } finally {
    previewing.value = false;
  }
}

async function applySuite(suiteId: string) {
  if (!props.isSuperadmin || applyingSuiteId.value) return;
  applyingSuiteId.value = suiteId;
  try {
    const res = await api('/api/v1/admin/control-plane/risk/save', {
      method: 'POST',
      body: JSON.stringify({ suite_id: suiteId, values: {}, auto_snapshot: true, note: `Apply suite ${suiteId}` }),
    });
    lastSnapshotHash.value = String(res?.snapshot_hash || '');
    toast.ok(t('admin.strategy.riskSuiteApplied'));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.actionFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    applyingSuiteId.value = '';
  }
}

async function handleOrderModeChange(mode: string) {
  if (!props.isSuperadmin || switchingOrderMode.value || mode === currentOrderMode.value) return;
  switchingOrderMode.value = true;
  try {
    const res = await api('/api/v1/admin/control-plane/order-mode', {
      method: 'PUT',
      body: JSON.stringify({ order_mode: mode, auto_snapshot: true }),
    });
    lastSnapshotHash.value = String(res?.snapshot_hash || '');
    toast.ok(t('admin.strategy.savedToast'));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    switchingOrderMode.value = false;
  }
}

async function toggleScaleOut(enabled: boolean) {
  if (!props.isSuperadmin || togglingScaleOut.value) return;
  togglingScaleOut.value = true;
  try {
    const res = await api('/api/v1/admin/control-plane/quick-toggle', {
      method: 'POST',
      body: JSON.stringify({ target: 'scale_out_enabled', enabled, auto_snapshot: true }),
    });
    formValues.ASTRA_SCALE_OUT_ENABLED = enabled;
    lastSnapshotHash.value = String(res?.snapshot_hash || '');
    toast.ok(t('admin.strategy.savedToast'));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    togglingScaleOut.value = false;
  }
}

async function saveRisk() {
  if (!canSave.value) return;
  saving.value = true;
  try {
    const res = await api('/api/v1/admin/control-plane/risk/save', {
      method: 'POST',
      body: JSON.stringify({
        values: { ...formValues },
        confirmation: confirmPhrase.value.trim(),
        auto_snapshot: true,
      }),
    });
    lastSnapshotHash.value = String(res?.snapshot_hash || '');
    confirmPhrase.value = '';
    previewResult.value = null;
    toast.ok(t('admin.strategy.savedToast'));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    saving.value = false;
  }
}
</script>

<template>
  <div class="st-tab-stack">
    <!-- Preset Suites -->
    <section class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title">{{ t('admin.strategy.riskPresetsTitle') }}</h2>
          <p class="card-sub">{{ t('admin.strategy.riskPresetsDesc') }}</p>
        </div>
        <span class="badge mono">{{ activeSuiteId }}</span>
      </header>
      <div class="wb-panel-body">
        <div class="st-suite-grid">
          <div
            v-for="s in suites"
            :key="s.id"
            class="st-suite-card"
            :class="{ 'is-active': activeSuiteId === s.id }"
          >
            <div class="st-suite-top">
              <strong>{{ isEn ? (s.label_en || s.name || s.id) : (s.label || s.name || s.id) }}</strong>
              <span class="badge mono">{{ s.id }}</span>
            </div>
            <p class="st-muted">{{ isEn ? (s.desc_en || s.description || '') : (s.desc || s.description || '') }}</p>
            <button
              type="button"
              class="btn btn-ghost btn-sm"
              :disabled="!isSuperadmin || applyingSuiteId === s.id"
              @click="applySuite(s.id)"
            >
              <Loader2 v-if="applyingSuiteId === s.id" :size="13" class="animate-spin shrink-0" />
              <Sparkles v-else :size="13" />
              <span>{{ t('admin.strategy.riskApplySuite') }}</span>
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- Order Mode & Scale-Out -->
    <section class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title">{{ t('admin.strategy.riskOrderModeTitle') }}</h2>
          <p class="card-sub">{{ t('admin.strategy.riskOrderModeDesc') }}</p>
        </div>
      </header>
      <div class="wb-panel-body">
        <div class="wb-setting-row">
          <div class="wb-setting-meta">
            <span class="wb-setting-title">{{ t('admin.strategy.kpiOrderMode') }}</span>
          </div>
          <div>
            <BaseSegmented
              :modelValue="currentOrderMode"
              :options="orderModeOptions"
              :label="t('admin.strategy.kpiOrderMode')"
              @update:modelValue="handleOrderModeChange"
            />
          </div>
        </div>

        <div class="wb-toggle-row">
          <div class="wb-setting-meta">
            <span class="wb-setting-title">{{ t('admin.strategy.riskScaleOutLabel') }}</span>
            <span class="wb-setting-desc">{{ t('admin.strategy.riskScaleOutDesc') }}</span>
          </div>
          <BaseSwitch
            :modelValue="isScaleOutEnabled"
            :disabled="!isSuperadmin || togglingScaleOut"
            :label="t('admin.strategy.riskScaleOutLabel')"
            @update:modelValue="toggleScaleOut"
          />
        </div>
      </div>
    </section>

    <!-- Live Risk Consistency Audit Banner -->
    <section
      class="card st-audit-card"
      :class="{
        'is-critical': activeAudit?.status === 'critical',
        'is-warning': activeAudit?.status === 'warning',
      }"
    >
      <div class="wb-panel-body">
        <div class="wb-toolbar">
          <div class="st-audit-head">
            <AlertTriangle v-if="activeAudit?.status === 'critical' || activeAudit?.status === 'warning'" :size="18" />
            <CheckCircle2 v-else :size="18" />
            <strong>
              <template v-if="previewing">{{ t('admin.strategy.riskAuditChecking') }}</template>
              <template v-else-if="activeAudit?.critical_count > 0">
                {{ t('admin.strategy.riskAuditCritical', undefined, { count: activeAudit.critical_count }) }}
              </template>
              <template v-else-if="activeAudit?.warning_count > 0">
                {{ t('admin.strategy.riskAuditWarning', undefined, { count: activeAudit.warning_count }) }}
              </template>
              <template v-else>{{ t('admin.strategy.riskAuditHealthy') }}</template>
            </strong>
          </div>
          <span v-if="activeAudit?.theoretical_max_rr" class="badge mono num">
            {{ t('admin.strategy.riskAuditTheoreticalRr') }}: {{ activeAudit.theoretical_max_rr }}
          </span>
        </div>

        <p v-if="previewResult?.error" role="alert" class="st-err-line">{{ previewResult.error }}</p>
        <ul v-if="(activeAudit?.issues || []).length" class="st-issue-list">
          <li v-for="iss in activeAudit.issues" :key="iss.code">
            <strong>{{ iss.title }}</strong> — <span>{{ iss.detail }}</span>
          </li>
        </ul>
      </div>
    </section>

    <!-- Parameter Groups -->
    <section v-for="grp in schema.groups" :key="grp.id" class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title">{{ isEn ? (grp.label_en || grp.label) : grp.label }}</h2>
          <p v-if="grp.desc" class="card-sub">{{ grp.desc }}</p>
        </div>
        <ShieldCheck :size="16" class="st-head-icon" />
      </header>
      <div class="wb-panel-body">
        <div v-for="param in groupedParams(grp.id)" :key="param.key" class="wb-setting-row">
          <div class="wb-setting-meta">
            <label :for="`rk-${param.key}`" class="wb-setting-title">
              {{ isEn ? (param.label_en || param.label) : param.label }}
            </label>
            <span class="wb-setting-desc">{{ param.desc }}</span>
            <code class="mono st-env-key">{{ param.key }}</code>
          </div>
          <div class="st-input-wrap">
            <input
              :id="`rk-${param.key}`"
              type="number"
              inputmode="decimal"
              class="field mono num"
              :aria-label="isEn ? (param.label_en || param.label) : param.label"
              :value="displayValue(param)"
              :step="Number(param.step || 1) * Number(param.display_scale || 1)"
              :min="param.min !== undefined ? Number(param.min) * Number(param.display_scale || 1) : undefined"
              :max="param.max !== undefined ? Number(param.max) * Number(param.display_scale || 1) : undefined"
              :disabled="!isSuperadmin"
              @input="updateDisplayValue(param, ($event.target as HTMLInputElement).value)"
            />
            <span v-if="param.unit" class="badge mono">{{ param.unit }}</span>
          </div>
        </div>
      </div>
    </section>

    <!-- Save Footer with HIGH RISK gate -->
    <section class="card">
      <div class="wb-panel-body">
        <div v-if="requiresHighRiskPhrase" class="st-danger-gate">
          <label for="rk-confirm-phrase" class="wb-setting-title">
            {{ t('admin.strategy.riskPhraseLabel') }}: <code class="mono">{{ expectedPhrase }}</code>
          </label>
          <input
            id="rk-confirm-phrase"
            v-model="confirmPhrase"
            type="text"
            autocomplete="off"
            spellcheck="false"
            class="field mono"
            :class="{ 'is-bad': isPhraseInvalid }"
            :aria-invalid="isPhraseInvalid ? 'true' : undefined"
            :placeholder="t('admin.strategy.riskPhrasePlaceholder', undefined, { phrase: expectedPhrase })"
          />
        </div>

        <div class="wb-toolbar">
          <span v-if="lastSnapshotHash" class="badge badge-up mono">
            {{ t('admin.strategy.riskSnapshotTag', undefined, { hash: lastSnapshotHash.slice(0, 12) }) }}
          </span>
          <span v-else />
          <button
            type="button"
            class="btn btn-primary"
            :disabled="!canSave"
            @click="saveRisk"
          >
            <Loader2 v-if="saving" :size="14" class="animate-spin shrink-0" />
            <Save v-else :size="14" />
            <span>{{ saving ? t('admin.strategy.riskSaving') : t('admin.strategy.riskSaveBtn') }}</span>
          </button>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.st-tab-stack {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}
.st-suite-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(230px, 1fr));
  gap: var(--ds-space-3);
}
.st-suite-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: var(--ds-space-2);
  padding: var(--ds-space-4);
  border-radius: var(--r-ctl);
  border: 1px solid var(--ds-color-border-subtle);
  background-color: var(--ds-color-bg-surface-inset);
}
.st-suite-card.is-active {
  border-color: var(--accent-line);
  background-color: var(--ds-color-brand-subtle);
}
.st-suite-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
}
.st-muted {
  margin: 0;
  font-size: var(--text-xs);
  line-height: 1.5;
  color: var(--ds-color-text-description);
}
.st-audit-card.is-critical {
  border-color: var(--down-line);
}
.st-audit-card.is-warning {
  border-color: var(--warn-line);
}
.st-audit-head {
  display: inline-flex;
  align-items: center;
  gap: var(--ds-space-2);
  font-size: var(--text-base);
}
.st-err-line {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--down);
}
.st-issue-list {
  margin: 0;
  padding-left: var(--ds-space-4);
  font-size: var(--text-xs);
  color: var(--ds-color-text-secondary);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.st-head-icon {
  color: var(--ds-color-text-muted);
}
.st-env-key {
  font-size: var(--text-xs);
  color: var(--ds-color-text-placeholder);
}
.st-input-wrap {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  max-width: 320px;
}
.st-danger-gate {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3);
  border: 1px solid var(--warn-line);
  border-radius: var(--r-ctl);
  background-color: var(--warn-bg);
}
</style>
