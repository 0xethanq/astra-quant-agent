<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { Loader2, Play, Plus, RotateCcw, Save, Sparkles, Trash2 } from 'lucide-vue-next';
import BaseSwitch from '../../../components/base/BaseSwitch.vue';
import { useApi } from '../../../composables/useApi';
import { useConfirm } from '../../../composables/useConfirm';
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
const { ask } = useConfirm();

const evoEnabled = ref(true);
const modelId = ref('auto');
const reasoningEffort = ref('high');
const thinkingTimeout = ref(300);
const analysisDepth = ref('deep');
const startTime = ref('2026-09-01 00:00:00');
const activeTradesCount = ref(0);
const availableModels = ref<any[]>([]);

const lessons = ref<any[]>([]);
const memoryVersion = ref('');
const newLessonText = ref('');
const testMessage = ref('');

const saving = ref(false);
const testing = ref(false);
const addingLesson = ref(false);
const togglingId = ref('');

async function loadEvolutionAndMemory() {
  try {
    const [evoRes, memRes] = await Promise.all([
      api('/api/v1/admin/evolution/config'),
      api('/api/v1/admin/memory'),
    ]);
    evoEnabled.value = props.state?.evolution?.enabled !== false;
    modelId.value = String(evoRes?.model_id || 'auto');
    reasoningEffort.value = String(evoRes?.reasoning_effort || 'high');
    thinkingTimeout.value = Number(evoRes?.thinking_timeout || 300);
    analysisDepth.value = String(evoRes?.analysis_depth || 'deep');
    startTime.value = String(evoRes?.evolution_start_time || '2026-09-01 00:00:00');
    activeTradesCount.value = Number(evoRes?.active_trades_count || 0);
    availableModels.value = Array.isArray(evoRes?.available_models) ? evoRes.available_models : [];

    lessons.value = Array.isArray(memRes?.structured_lessons) ? memRes.structured_lessons : [];
    memoryVersion.value = String(memRes?.version || '');
  } catch (e: any) {
    toast.err(t('admin.strategy.loadFailed', undefined, { msg: e.message || 'error' }));
  }
}

async function toggleEvolutionMaster(enabled: boolean) {
  if (!props.isSuperadmin) return;
  try {
    await api('/api/v1/admin/control-plane/quick-toggle', {
      method: 'POST',
      body: JSON.stringify({ target: 'evolution_enabled', enabled, auto_snapshot: true }),
    });
    evoEnabled.value = enabled;
    toast.ok(t('admin.strategy.savedToast'));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  }
}

async function saveEvolution() {
  if (!props.isSuperadmin || saving.value) return;
  saving.value = true;
  try {
    const res = await api('/api/v1/admin/evolution/config', {
      method: 'PUT',
      body: JSON.stringify({
        model_id: modelId.value,
        reasoning_effort: reasoningEffort.value,
        thinking_timeout: Number(thinkingTimeout.value),
        analysis_depth: analysisDepth.value,
        start_time: startTime.value.trim(),
      }),
    });
    activeTradesCount.value = Number(res?.active_trades_count ?? activeTradesCount.value);
    toast.ok(t('admin.strategy.evoSaved'));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    saving.value = false;
  }
}

async function testModel() {
  if (testing.value) return;
  testing.value = true;
  testMessage.value = '';
  try {
    const res = await api('/api/v1/admin/evolution/test-model', {
      method: 'POST',
      body: JSON.stringify({
        model_id: modelId.value || 'auto',
        reasoning_effort: reasoningEffort.value,
        thinking_timeout: Math.min(Number(thinkingTimeout.value || 60), 120),
      }),
    });
    testMessage.value = String(res?.message || '');
    if (res?.ok) toast.ok(testMessage.value);
    else toast.err(testMessage.value || 'Probe failed');
  } catch (e: any) {
    toast.err(t('admin.strategy.actionFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    testing.value = false;
  }
}

async function toggleLesson(lesson: any, enabled: boolean) {
  if (!props.isSuperadmin || togglingId.value) return;
  togglingId.value = lesson.id;
  try {
    await api('/api/v1/admin/control-plane/quick-toggle', {
      method: 'POST',
      body: JSON.stringify({ target: 'memory_lesson_enabled', item_id: lesson.id, enabled, auto_snapshot: false }),
    });
    lesson.enabled = enabled;
    toast.ok(t('admin.strategy.savedToast'));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    togglingId.value = '';
  }
}

async function addLesson() {
  const txt = newLessonText.value.trim();
  if (!props.isSuperadmin || !txt || addingLesson.value) return;
  addingLesson.value = true;
  try {
    await api('/api/v1/admin/memory', {
      method: 'POST',
      body: JSON.stringify({ text: txt, expected_version: memoryVersion.value || undefined }),
    });
    newLessonText.value = '';
    toast.ok(t('admin.strategy.memAdded'));
    await loadEvolutionAndMemory();
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.actionFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    addingLesson.value = false;
  }
}

async function deleteLesson(idx: number, lessonId: string) {
  if (!props.isSuperadmin) return;
  try {
    const qs = new URLSearchParams();
    if (lessonId) qs.set('lesson_id', lessonId);
    if (memoryVersion.value) qs.set('expected_version', memoryVersion.value);
    await api(`/api/v1/admin/memory/${idx}?${qs.toString()}`, { method: 'DELETE' });
    toast.ok(t('admin.strategy.memDeleted'));
    await loadEvolutionAndMemory();
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.actionFailed', undefined, { msg: e.message || 'error' }));
  }
}

async function resetMemory() {
  if (!props.isSuperadmin) return;
  const ok = await ask({
    title: t('admin.strategy.memResetConfirmTitle'),
    desc: t('admin.strategy.memResetConfirmDesc'),
    danger: true,
    okText: t('admin.strategy.memResetBtn'),
  });
  if (!ok) return;
  try {
    const qs = memoryVersion.value ? `?expected_version=${encodeURIComponent(memoryVersion.value)}` : '';
    await api(`/api/v1/admin/memory/reset${qs}`, { method: 'POST' });
    toast.ok(t('admin.strategy.memResetDone'));
    await loadEvolutionAndMemory();
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.actionFailed', undefined, { msg: e.message || 'error' }));
  }
}

onMounted(loadEvolutionAndMemory);
</script>

<template>
  <div class="st-tab-stack">
    <!-- Evolution Engine Settings -->
    <section class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title">{{ t('admin.strategy.tabEvolution') }}</h2>
          <p class="card-sub">{{ t('admin.strategy.evoMasterDesc') }}</p>
        </div>
        <span class="badge mono num">{{ t('admin.strategy.evoActiveTrades') }}: {{ activeTradesCount }}</span>
      </header>
      <div class="wb-panel-body">
        <div class="wb-toggle-row">
          <span class="wb-setting-title">{{ t('admin.strategy.evoMasterLabel') }}</span>
          <BaseSwitch
            :modelValue="evoEnabled"
            :disabled="!isSuperadmin"
            :label="t('admin.strategy.evoMasterLabel')"
            @update:modelValue="toggleEvolutionMaster"
          />
        </div>

        <div class="st-evo-grid">
          <label class="field-stack">
            <span class="form-label">{{ t('admin.strategy.evoModelLabel') }}</span>
            <select v-model="modelId" class="field" :aria-label="t('admin.strategy.evoModelLabel')" :disabled="!isSuperadmin">
              <option value="auto">{{ t('admin.strategy.evoModelAuto') }}</option>
              <option v-for="m in availableModels" :key="m.id" :value="m.id">
                {{ m.name }} ({{ m.provider_name }})
              </option>
            </select>
          </label>
          <label class="field-stack">
            <span class="form-label">{{ t('admin.strategy.evoReasoningLabel') }}</span>
            <select v-model="reasoningEffort" class="field" :aria-label="t('admin.strategy.evoReasoningLabel')" :disabled="!isSuperadmin">
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
            </select>
          </label>
          <label class="field-stack">
            <span class="form-label">{{ t('admin.strategy.evoTimeoutLabel') }}</span>
            <input v-model.number="thinkingTimeout" type="number" inputmode="numeric" min="60" max="600" step="30" class="field mono num" :disabled="!isSuperadmin" />
          </label>
          <label class="field-stack">
            <span class="form-label">{{ t('admin.strategy.evoDepthLabel') }}</span>
            <select v-model="analysisDepth" class="field" :aria-label="t('admin.strategy.evoDepthLabel')" :disabled="!isSuperadmin">
              <option value="standard">standard</option>
              <option value="deep">deep</option>
            </select>
          </label>
          <label class="field-stack">
            <span class="form-label">{{ t('admin.strategy.evoStartTimeLabel') }}</span>
            <input v-model="startTime" type="text" class="field mono" :disabled="!isSuperadmin" />
          </label>
        </div>

        <p v-if="testMessage" class="st-muted mono">{{ testMessage }}</p>

        <div class="wb-toolbar">
          <button type="button" class="btn btn-ghost btn-sm" :disabled="testing" @click="testModel">
            <Loader2 v-if="testing" :size="13" class="animate-spin shrink-0" />
            <Play v-else :size="13" />
            <span>{{ testing ? t('admin.strategy.evoTesting') : t('admin.strategy.evoTestBtn') }}</span>
          </button>
          <button type="button" class="btn btn-primary btn-sm" :disabled="!isSuperadmin || saving" @click="saveEvolution">
            <Loader2 v-if="saving" :size="13" class="animate-spin shrink-0" />
            <Save v-else :size="13" />
            <span>{{ t('admin.strategy.evoSaveBtn') }}</span>
          </button>
        </div>
      </div>
    </section>

    <!-- Memory Lessons -->
    <section class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title">{{ t('admin.strategy.memLessonsTitle') }}</h2>
          <p class="card-sub">{{ t('admin.strategy.memLessonsDesc') }}</p>
        </div>
        <Sparkles :size="16" class="st-head-icon" />
      </header>
      <div class="wb-panel-body">
        <div class="st-add-row">
          <input
            v-model="newLessonText"
            type="text"
            class="field"
            :aria-label="t('admin.strategy.memAddPlaceholder')"
            :placeholder="t('admin.strategy.memAddPlaceholder')"
            :disabled="!isSuperadmin"
          />
          <button
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="!isSuperadmin || !newLessonText.trim() || addingLesson"
            @click="addLesson"
          >
            <Loader2 v-if="addingLesson" :size="13" class="animate-spin shrink-0" />
            <Plus v-else :size="13" />
            <span>{{ t('admin.strategy.memAddBtn') }}</span>
          </button>
        </div>

        <p v-if="!lessons.length" class="st-muted">{{ t('admin.strategy.memEmpty') }}</p>

        <div v-else class="st-lesson-list">
          <div v-for="(item, idx) in lessons" :key="item.id || idx" class="st-lesson-row">
            <div class="st-lesson-text">{{ item.rule_text || item.text || '' }}</div>
            <div class="st-lesson-actions">
              <BaseSwitch
                v-if="item.id"
                :modelValue="item.enabled !== false"
                :disabled="!isSuperadmin || togglingId === item.id"
                :label="item.rule_text || item.id"
                @update:modelValue="toggleLesson(item, $event)"
              />
              <button
                type="button"
                class="btn btn-quiet btn-icon btn-sm is-danger"
                :aria-label="t('common.remove')"
                :disabled="!isSuperadmin"
                @click="deleteLesson(idx, item.id)"
              >
                <Trash2 :size="13" />
              </button>
            </div>
          </div>
        </div>

        <div v-if="lessons.length" class="wb-toolbar">
          <span />
          <button type="button" class="btn btn-ghost btn-sm is-danger" :disabled="!isSuperadmin" @click="resetMemory">
            <RotateCcw :size="13" />
            <span>{{ t('admin.strategy.memResetBtn') }}</span>
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
.st-evo-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: var(--ds-space-3);
}
.st-add-row {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
}
.st-add-row .field {
  flex: 1;
}
.st-muted {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.st-lesson-list {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
}
.st-lesson-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-radius: var(--r-ctl);
  border: 1px solid var(--ds-color-border-subtle);
  background-color: var(--ds-color-bg-surface-inset);
}
.st-lesson-text {
  font-size: var(--text-base);
  line-height: 1.5;
  color: var(--ds-color-text-primary);
  flex: 1;
  min-width: 0;
}
.st-lesson-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-shrink: 0;
}
</style>
