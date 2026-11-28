<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { Loader2, Play, Save, Sparkles, Users } from 'lucide-vue-next';
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

const councilEnabled = ref(true);
const consensusMode = ref('weighted_vote');
const timeoutSeconds = ref(240);
const roleDrafts = reactive<Record<string, any>>({});

const savingGlobals = ref(false);
const savingRoleId = ref('');
const applyingSuiteId = ref('');
const testing = ref(false);
const testOutput = ref('');

const councilState = computed(() => props.state?.council || {});
const availableSuites = computed<any[]>(() => councilState.value?.available_suites || []);

const healthByRole = computed<Record<string, any>>(() => {
  const map: Record<string, any> = {};
  for (const h of councilState.value?.model_health || []) {
    if (h?.role_id) map[h.role_id] = h;
  }
  return map;
});

const roleIds = computed(() => Object.keys(roleDrafts));

watch(
  councilState,
  (cfg) => {
    if (!cfg || typeof cfg !== 'object') return;
    councilEnabled.value = cfg.enabled !== false;
    consensusMode.value = String(cfg.consensus_mode || 'weighted_vote');
    timeoutSeconds.value = Number(cfg.timeout_seconds || 240);
    const roles = cfg.roles || {};
    for (const k of Object.keys(roleDrafts)) {
      if (!(k in roles)) delete roleDrafts[k];
    }
    for (const [id, role] of Object.entries<any>(roles)) {
      roleDrafts[id] = {
        name: role?.name || id,
        enabled: role?.enabled !== false,
        weight: Number(role?.weight ?? 0.3),
        model_id: String(role?.model_id || ''),
        reasoning_effort: String(role?.reasoning_effort || 'medium'),
        temperature: Number(role?.temperature ?? 0.3),
        prompt: String(role?.prompt || ''),
      };
    }
  },
  { immediate: true },
);

async function toggleMaster(enabled: boolean) {
  if (!props.isSuperadmin) return;
  try {
    await api('/api/v1/admin/control-plane/quick-toggle', {
      method: 'POST',
      body: JSON.stringify({ target: 'council_enabled', enabled, auto_snapshot: true }),
    });
    councilEnabled.value = enabled;
    toast.ok(t('admin.strategy.savedToast'));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  }
}

async function applySuite(suiteId: string) {
  if (!props.isSuperadmin || applyingSuiteId.value) return;
  applyingSuiteId.value = suiteId;
  try {
    await api('/api/v1/admin/council/apply-suite', {
      method: 'POST',
      body: JSON.stringify({ suite_id: suiteId }),
    });
    toast.ok(t('admin.strategy.councilSuiteApplied'));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.actionFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    applyingSuiteId.value = '';
  }
}

async function saveGlobals() {
  if (!props.isSuperadmin || savingGlobals.value) return;
  savingGlobals.value = true;
  try {
    const rolesPayload: Record<string, any> = {};
    for (const id of roleIds.value) {
      rolesPayload[id] = { ...roleDrafts[id] };
    }
    await api('/api/v1/admin/council/config', {
      method: 'PUT',
      body: JSON.stringify({
        enabled: councilEnabled.value,
        consensus_mode: consensusMode.value,
        timeout_seconds: Number(timeoutSeconds.value),
        roles: rolesPayload,
      }),
    });
    toast.ok(t('admin.strategy.councilConfigSaved'));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    savingGlobals.value = false;
  }
}

async function saveRole(roleId: string) {
  if (!props.isSuperadmin || savingRoleId.value) return;
  const r = roleDrafts[roleId];
  if (!r) return;
  savingRoleId.value = roleId;
  try {
    await api(`/api/v1/admin/control-plane/council/role/${encodeURIComponent(roleId)}`, {
      method: 'PATCH',
      body: JSON.stringify({
        enabled: Boolean(r.enabled),
        weight: Number(r.weight),
        model_id: String(r.model_id || ''),
        reasoning_effort: String(r.reasoning_effort || 'medium'),
        temperature: Number(r.temperature),
        prompt: String(r.prompt || ''),
        name: String(r.name || roleId),
        auto_snapshot: true,
      }),
    });
    toast.ok(t('admin.strategy.councilRoleSaved', undefined, { name: r.name }));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    savingRoleId.value = '';
  }
}

async function runTestDebate() {
  if (testing.value) return;
  testing.value = true;
  testOutput.value = '';
  try {
    const res = await api('/api/v1/admin/council/test', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    if (res?.status === 'ok') {
      testOutput.value = String(res?.brain_output || '');
      toast.ok(t('admin.strategy.councilTestDone'));
    } else {
      toast.err(t('admin.strategy.actionFailed', undefined, { msg: res?.error || 'error' }));
    }
  } catch (e: any) {
    toast.err(t('admin.strategy.actionFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    testing.value = false;
  }
}
</script>

<template>
  <div class="st-tab-stack">
    <!-- Master Config & Presets -->
    <section class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title">{{ t('admin.strategy.tabCouncil') }}</h2>
          <p class="card-sub">{{ t('admin.strategy.councilMasterDesc') }}</p>
        </div>
        <Users :size="16" class="st-head-icon" />
      </header>
      <div class="wb-panel-body">
        <div class="wb-toggle-row">
          <span class="wb-setting-title">{{ t('admin.strategy.councilMasterLabel') }}</span>
          <BaseSwitch
            :modelValue="councilEnabled"
            :disabled="!isSuperadmin"
            :label="t('admin.strategy.councilMasterLabel')"
            @update:modelValue="toggleMaster"
          />
        </div>

        <div class="wb-setting-row">
          <div class="wb-setting-meta">
            <label for="st-consensus" class="wb-setting-title">{{ t('admin.strategy.councilConsensusMode') }}</label>
          </div>
          <div class="st-inline-controls">
            <select id="st-consensus" v-model="consensusMode" class="field" :aria-label="t('admin.strategy.councilConsensusMode')" :disabled="!isSuperadmin">
              <option value="weighted_vote">weighted_vote</option>
              <option value="majority">majority</option>
              <option value="cio_arbitrate">cio_arbitrate</option>
            </select>
            <input
              v-model.number="timeoutSeconds"
              type="number"
              inputmode="numeric"
              min="30"
              max="600"
              step="10"
              class="field mono num st-num-sm"
              :aria-label="t('admin.strategy.councilTimeout')"
              :disabled="!isSuperadmin"
            />
            <button
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="!isSuperadmin || savingGlobals"
              @click="saveGlobals"
            >
              <Loader2 v-if="savingGlobals" :size="13" class="animate-spin shrink-0" />
              <Save v-else :size="13" />
              <span>{{ t('admin.strategy.councilSaveConfig') }}</span>
            </button>
          </div>
        </div>

        <div v-if="availableSuites.length" class="st-suites-bar">
          <span class="form-label">{{ t('admin.strategy.councilSuitesTitle') }}</span>
          <div class="st-chip-wrap">
            <button
              v-for="s in availableSuites"
              :key="s.id"
              type="button"
              class="btn btn-ghost btn-sm"
              :disabled="!isSuperadmin || applyingSuiteId === s.id"
              @click="applySuite(s.id)"
            >
              <Loader2 v-if="applyingSuiteId === s.id" :size="13" class="animate-spin shrink-0" />
              <Sparkles v-else :size="13" />
              <span>{{ s.name || s.id }}</span>
            </button>
          </div>
        </div>

        <div class="wb-toolbar">
          <button
            type="button"
            class="btn btn-ghost"
            :disabled="testing"
            @click="runTestDebate"
          >
            <Loader2 v-if="testing" :size="14" class="animate-spin shrink-0" />
            <Play v-else :size="14" />
            <span>{{ testing ? t('admin.strategy.councilTestRunning') : t('admin.strategy.councilTestBtn') }}</span>
          </button>
        </div>

        <div v-if="testOutput" class="st-test-output mono">
          <div class="form-label">{{ t('admin.strategy.councilTestOutputLabel') }}</div>
          <pre tabindex="0">{{ testOutput }}</pre>
        </div>
      </div>
    </section>

    <!-- Seat Editors -->
    <section v-for="id in roleIds" :key="id" class="card">
      <header class="card-head">
        <div class="st-role-head">
          <h3 class="card-title">{{ roleDrafts[id].name }}</h3>
          <span class="badge mono">{{ id }}</span>
          <span
            class="badge mono"
            :class="healthByRole[id]?.registered !== false ? 'badge-up' : 'badge-warn'"
          >
            {{ healthByRole[id]?.registered !== false ? t('admin.strategy.councilModelRegistered') : t('admin.strategy.councilModelFallback') }}
          </span>
        </div>
        <BaseSwitch
          v-model="roleDrafts[id].enabled"
          :disabled="!isSuperadmin"
          :label="t('admin.strategy.councilRoleEnabled')"
        />
      </header>
      <div class="wb-panel-body">
        <div class="st-role-grid">
          <label class="field-stack">
            <span class="form-label">{{ t('admin.strategy.councilRoleModel') }}</span>
            <input v-model="roleDrafts[id].model_id" type="text" class="field mono" :disabled="!isSuperadmin" />
          </label>
          <label class="field-stack">
            <span class="form-label">{{ t('admin.strategy.councilRoleWeight') }}</span>
            <input
              v-model.number="roleDrafts[id].weight"
              type="number"
              inputmode="decimal"
              step="0.05"
              min="0.05"
              max="1"
              class="field mono num"
              :disabled="!isSuperadmin"
            />
          </label>
          <label class="field-stack">
            <span class="form-label">{{ t('admin.strategy.councilRoleReasoning') }}</span>
            <select v-model="roleDrafts[id].reasoning_effort" class="field" :aria-label="t('admin.strategy.councilRoleReasoning')" :disabled="!isSuperadmin">
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </label>
          <label class="field-stack">
            <span class="form-label">{{ t('admin.strategy.councilRoleTemp') }}</span>
            <input
              v-model.number="roleDrafts[id].temperature"
              type="number"
              inputmode="decimal"
              step="0.05"
              min="0"
              max="1"
              class="field mono num"
              :disabled="!isSuperadmin"
            />
          </label>
        </div>

        <label class="field-stack">
          <span class="form-label">{{ t('admin.strategy.councilRolePrompt') }}</span>
          <textarea v-model="roleDrafts[id].prompt" rows="3" class="field" :disabled="!isSuperadmin" />
        </label>

        <div class="wb-toolbar">
          <span />
          <button
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="!isSuperadmin || savingRoleId === id"
            @click="saveRole(id)"
          >
            <Loader2 v-if="savingRoleId === id" :size="13" class="animate-spin shrink-0" />
            <Save v-else :size="13" />
            <span>{{ t('admin.strategy.councilSaveRole') }}</span>
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
.st-head-icon {
  color: var(--ds-color-text-muted);
}
.st-inline-controls {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.st-num-sm {
  width: 100px;
}
.st-suites-bar {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
}
.st-chip-wrap {
  display: flex;
  flex-wrap: wrap;
  gap: var(--ds-space-2);
}
.st-test-output {
  padding: var(--ds-space-3);
  border-radius: var(--r-ctl);
  border: 1px solid var(--ds-color-border-subtle);
  background-color: var(--ds-color-bg-surface-inset);
  font-size: var(--text-xs);
}
.st-test-output pre {
  margin: var(--ds-space-2) 0 0;
  white-space: pre-wrap;
  max-height: 280px;
  overflow-y: auto;
}
.st-role-head {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.st-role-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
  gap: var(--ds-space-3);
}
</style>
