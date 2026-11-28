<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue';
import { Activity, Clock, Loader2, PauseCircle, Play, Plus, Save, Trash2 } from 'lucide-vue-next';
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
const { t } = useI18n();
const toast = useToast();

const tradingPaused = ref(false);
const togglingPause = ref(false);

const sessEnabled = ref(false);
const modeOutside = ref<'manage_only' | 'off'>('manage_only');
const windows = ref<{ days: number[]; start: string; end: string }[]>([]);
const savingSession = ref(false);

const jobsCatalog = ref<any[]>([]);
const jobRuns = ref<any[]>([]);
const triggeringJobId = ref('');
let pollTimer: ReturnType<typeof setTimeout> | null = null;

const hasRunningJob = computed(() => jobRuns.value.some((r) => r.status === 'running'));

watch(
  () => props.state,
  (s) => {
    if (!s) return;
    tradingPaused.value = Boolean(s.trading_paused);
    const ts = s.trading_session || {};
    sessEnabled.value = Boolean(ts.enabled);
    modeOutside.value = ts.mode_outside === 'off' ? 'off' : 'manage_only';
    windows.value = Array.isArray(ts.windows)
      ? ts.windows.map((w: any) => ({
          days: Array.isArray(w.days) ? [...w.days] : [],
          start: String(w.start || '09:00'),
          end: String(w.end || '23:00'),
        }))
      : [];
    if (s.jobs?.catalog) jobsCatalog.value = s.jobs.catalog;
    if (s.jobs?.recent_runs) jobRuns.value = s.jobs.recent_runs;
  },
  { immediate: true },
);

async function toggleTradingPaused(paused: boolean) {
  if (!props.isSuperadmin || togglingPause.value) return;
  togglingPause.value = true;
  try {
    await api('/api/v1/admin/control-plane/quick-toggle', {
      method: 'POST',
      body: JSON.stringify({ target: 'trading_paused', enabled: paused, auto_snapshot: false }),
    });
    tradingPaused.value = paused;
    window.dispatchEvent(new CustomEvent('astra:control-plane-changed', { detail: { trading_paused: paused } }));
    toast.ok(t('admin.strategy.savedToast'));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    togglingPause.value = false;
  }
}

function addWindow() {
  if (windows.value.length >= 12) return;
  windows.value = [...windows.value, { days: [], start: '08:00', end: '22:00' }];
}

function removeWindow(idx: number) {
  windows.value = windows.value.filter((_, i) => i !== idx);
}

async function saveSession() {
  if (!props.isSuperadmin || savingSession.value) return;
  savingSession.value = true;
  try {
    await api('/api/v1/admin/gateway/trading-session', {
      method: 'PUT',
      body: JSON.stringify({
        enabled: sessEnabled.value,
        mode_outside: modeOutside.value,
        windows: windows.value,
      }),
    });
    toast.ok(t('admin.strategy.sessionSaved'));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    savingSession.value = false;
  }
}

async function refreshRuns() {
  try {
    const res = await api('/api/v1/admin/control-plane/jobs/runs?limit=15');
    if (Array.isArray(res?.jobs)) jobsCatalog.value = res.jobs;
    if (Array.isArray(res?.runs)) jobRuns.value = res.runs;
    if (hasRunningJob.value) schedulePoll();
  } catch {
    /* ignore transient poll failures */
  }
}

function schedulePoll() {
  if (pollTimer) clearTimeout(pollTimer);
  pollTimer = setTimeout(() => {
    void refreshRuns();
  }, 2000);
}

async function triggerJob(job: any) {
  if (!props.isSuperadmin || triggeringJobId.value) return;
  triggeringJobId.value = job.job_id;
  try {
    await api(`/api/v1/admin/control-plane/jobs/${encodeURIComponent(job.job_id)}/trigger`, {
      method: 'POST',
    });
    toast.ok(t('admin.strategy.jobsTriggeredToast', undefined, { label: job.label || job.job_id }));
    await refreshRuns();
    schedulePoll();
  } catch (e: any) {
    toast.err(t('admin.strategy.actionFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    triggeringJobId.value = '';
  }
}

function runStatusClass(status: string): string {
  if (status === 'success') return 'badge-up';
  if (status === 'failed' || status === 'timeout') return 'badge-down';
  if (status === 'running') return 'badge-accent';
  return '';
}

function runStatusLabel(status: string): string {
  if (status === 'success') return t('admin.strategy.jobsSuccessBadge');
  if (status === 'failed') return t('admin.strategy.jobsFailedBadge');
  if (status === 'timeout') return t('admin.strategy.jobsTimeoutBadge');
  if (status === 'running') return t('admin.strategy.jobsRunningBadge');
  return t('admin.strategy.jobsIdleBadge');
}

onMounted(() => {
  void refreshRuns();
});

onBeforeUnmount(() => {
  if (pollTimer) clearTimeout(pollTimer);
});
</script>

<template>
  <div class="st-tab-stack">
    <!-- Global Entry Pause Gate -->
    <section class="card st-pause-card" :class="{ 'is-paused': tradingPaused }">
      <div class="wb-panel-body">
        <div class="wb-toggle-row">
          <div class="wb-setting-meta">
            <span class="wb-setting-title st-pause-title">
              <PauseCircle v-if="tradingPaused" :size="18" />
              <Activity v-else :size="18" />
              <span>{{ t('admin.strategy.pauseBannerTitle') }}</span>
            </span>
            <span class="wb-setting-desc">{{ t('admin.strategy.pauseBannerDesc') }}</span>
            <span class="badge mono" :class="tradingPaused ? 'badge-warn' : 'badge-up'">
              {{ tradingPaused ? t('admin.strategy.pauseBannerPaused') : t('admin.strategy.pauseBannerRunning') }}
            </span>
          </div>
          <BaseSwitch
            :modelValue="tradingPaused"
            :disabled="!isSuperadmin || togglingPause"
            :label="t('admin.strategy.pauseBannerTitle')"
            @update:modelValue="toggleTradingPaused"
          />
        </div>
      </div>
    </section>

    <!-- Trading Session Windows -->
    <section class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title">{{ t('admin.strategy.sessionTitle') }}</h2>
          <p class="card-sub">{{ t('admin.strategy.sessionDesc') }}</p>
        </div>
        <Clock :size="16" class="st-head-icon" />
      </header>
      <div class="wb-panel-body">
        <div class="wb-toggle-row">
          <span class="wb-setting-title">{{ t('admin.strategy.sessionEnableLabel') }}</span>
          <BaseSwitch v-model="sessEnabled" :disabled="!isSuperadmin" :label="t('admin.strategy.sessionEnableLabel')" />
        </div>

        <div class="wb-setting-row">
          <div class="wb-setting-meta">
            <label for="st-mode-outside" class="wb-setting-title">{{ t('admin.strategy.sessionModeOutsideLabel') }}</label>
          </div>
          <select id="st-mode-outside" v-model="modeOutside" class="field st-mode-select" :aria-label="t('admin.strategy.sessionModeOutsideLabel')" :disabled="!isSuperadmin">
            <option value="manage_only">{{ t('admin.strategy.sessionModeManage') }}</option>
            <option value="off">{{ t('admin.strategy.sessionModeHold') }}</option>
          </select>
        </div>

        <div class="wb-toolbar">
          <span class="form-label">{{ t('admin.strategy.sessionWindowsTitle') }}</span>
          <button
            type="button"
            class="btn btn-ghost btn-sm"
            :disabled="!isSuperadmin || windows.length >= 12"
            @click="addWindow"
          >
            <Plus :size="13" />
            <span>{{ t('admin.strategy.sessionAddWindow') }}</span>
          </button>
        </div>

        <div v-if="windows.length" class="st-win-list">
          <div v-for="(w, idx) in windows" :key="idx" class="st-win-row">
            <label class="st-time-field">
              <span class="form-label">{{ t('admin.strategy.sessionStartLabel') }}</span>
              <input v-model="w.start" type="text" class="field mono" :disabled="!isSuperadmin" />
            </label>
            <label class="st-time-field">
              <span class="form-label">{{ t('admin.strategy.sessionEndLabel') }}</span>
              <input v-model="w.end" type="text" class="field mono" :disabled="!isSuperadmin" />
            </label>
            <button
              type="button"
              class="btn btn-quiet btn-icon btn-sm is-danger"
              :aria-label="t('admin.strategy.sessionRemoveWindow')"
              :disabled="!isSuperadmin"
              @click="removeWindow(idx)"
            >
              <Trash2 :size="13" />
            </button>
          </div>
        </div>

        <div class="wb-toolbar">
          <span class="badge mono">{{ t('admin.strategy.sessionTimezoneLabel') }}: Asia/Shanghai</span>
          <button type="button" class="btn btn-primary btn-sm" :disabled="!isSuperadmin || savingSession" @click="saveSession">
            <Loader2 v-if="savingSession" :size="13" class="animate-spin shrink-0" />
            <Save v-else :size="13" />
            <span>{{ t('admin.strategy.sessionSaveBtn') }}</span>
          </button>
        </div>
      </div>
    </section>

    <!-- Background Jobs -->
    <section class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title">{{ t('admin.strategy.jobsTitle') }}</h2>
          <p class="card-sub">{{ t('admin.strategy.jobsDesc') }}</p>
        </div>
      </header>
      <div class="wb-panel-body">
        <div class="st-jobs-grid">
          <div v-for="j in jobsCatalog" :key="j.job_id" class="st-job-card">
            <div class="st-job-top">
              <strong>{{ j.label || j.job_id }}</strong>
              <span class="badge mono" :class="j.running ? 'badge-accent' : ''">
                {{ j.running ? t('admin.strategy.jobsRunningBadge') : j.timeout + 's' }}
              </span>
            </div>
            <code class="mono st-muted">{{ j.script }}</code>
            <button
              type="button"
              class="btn btn-ghost btn-sm"
              :disabled="!isSuperadmin || j.running || triggeringJobId === j.job_id"
              @click="triggerJob(j)"
            >
              <Loader2 v-if="j.running || triggeringJobId === j.job_id" :size="13" class="animate-spin shrink-0" />
              <Play v-else :size="13" />
              <span>{{ t('admin.strategy.jobsTriggerBtn') }}</span>
            </button>
          </div>
        </div>

        <div class="st-runs-block">
          <div class="form-label">{{ t('admin.strategy.jobsRunsTitle') }}</div>
          <p v-if="!jobRuns.length" class="st-muted">{{ t('admin.strategy.jobsNoRuns') }}</p>
          <div v-else class="st-runs-list">
            <div v-for="r in jobRuns" :key="r.run_id" class="st-run-row">
              <div class="st-run-meta">
                <strong>{{ r.label || r.job_id }}</strong>
                <span class="badge mono" :class="runStatusClass(r.status)">{{ runStatusLabel(r.status) }}</span>
                <span class="st-muted mono num">{{ r.started_at }}</span>
                <span v-if="typeof r.duration_ms === 'number'" class="st-muted mono num">{{ (r.duration_ms / 1000).toFixed(1) }}s</span>
              </div>
              <pre v-if="r.error || r.output_tail" tabindex="0" class="st-run-log mono">{{ r.error || r.output_tail }}</pre>
            </div>
          </div>
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
.st-head-icon {
  color: var(--ds-color-text-muted);
}
.st-pause-card.is-paused {
  border-color: var(--warn-line);
}
.st-pause-title {
  display: inline-flex;
  align-items: center;
  gap: var(--ds-space-2);
}
.st-mode-select {
  max-width: 340px;
}
.st-win-list {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
}
.st-win-row {
  display: flex;
  align-items: flex-end;
  gap: var(--ds-space-3);
  flex-wrap: wrap;
  padding: var(--ds-space-3);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
}
.st-time-field {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  width: 120px;
}
.st-jobs-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: var(--ds-space-3);
}
.st-job-card {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding: var(--ds-space-4);
  border-radius: var(--r-ctl);
  border: 1px solid var(--ds-color-border-subtle);
  background-color: var(--ds-color-bg-surface-inset);
}
.st-job-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
}
.st-muted {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.st-runs-block {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding-top: var(--ds-space-3);
  border-top: 1px solid var(--ds-color-border-subtle);
}
.st-runs-list {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
}
.st-run-row {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
}
.st-run-meta {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.st-run-log {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
  white-space: pre-wrap;
  max-height: 120px;
  overflow-y: auto;
}
</style>
