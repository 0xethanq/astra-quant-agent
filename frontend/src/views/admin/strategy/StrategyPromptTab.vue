<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { Check, ChevronDown, ChevronRight, FileText, Loader2, Plus, Save, Trash2 } from 'lucide-vue-next';
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

const profiles = ref<any[]>([]);
const activeProfileId = ref('');
const cloneName = ref('');
const cloneSourceId = ref('allpattern_swing');
const overrideText = ref('');

const expandedModules = ref<Record<string, boolean>>({});
const moduleEdits = ref<Record<string, string>>({});
const togglingMod = ref('');
const savingModules = ref(false);
const savingOverride = ref(false);
const activatingId = ref('');
const creating = ref(false);

const activeProfileObj = computed(() =>
  profiles.value.find((p) => p.id === activeProfileId.value) || null,
);

const tradingModules = computed<any[]>(() => {
  const mods = activeProfileObj.value?.pipelines?.trading_system;
  if (Array.isArray(mods)) return mods;
  return props.state?.prompt?.trading_system_modules || [];
});

async function loadPromptDetails() {
  try {
    const [profRes, ovRes] = await Promise.all([
      api('/api/v1/admin/prompt-profiles'),
      api('/api/v1/admin/prompts'),
    ]);
    activeProfileId.value = String(profRes?.active_profile_id || '');
    profiles.value = Array.isArray(profRes?.profiles) ? profRes.profiles : [];
    overrideText.value = String(ovRes?.content || '');
    for (const m of tradingModules.value) {
      if (m?.id && !(m.id in moduleEdits.value)) {
        moduleEdits.value[m.id] = String(m.content || '');
      }
    }
  } catch (e: any) {
    toast.err(t('admin.strategy.loadFailed', undefined, { msg: e.message || 'error' }));
  }
}

async function activateProfile(profile: any) {
  if (!props.isSuperadmin || activatingId.value) return;
  activatingId.value = profile.id;
  try {
    await api(`/api/v1/admin/prompt-profiles/${encodeURIComponent(profile.id)}/activate`, {
      method: 'POST',
    });
    toast.ok(t('admin.strategy.promptActivated', undefined, { name: profile.name || profile.id }));
    await loadPromptDetails();
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.actionFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    activatingId.value = '';
  }
}

async function createProfile() {
  const name = cloneName.value.trim();
  if (!props.isSuperadmin || !name || creating.value) return;
  creating.value = true;
  try {
    await api('/api/v1/admin/prompt-profiles', {
      method: 'POST',
      body: JSON.stringify({
        name,
        description: '',
        source_id: cloneSourceId.value || 'allpattern_swing',
      }),
    });
    cloneName.value = '';
    toast.ok(t('admin.strategy.promptCreated', undefined, { name }));
    await loadPromptDetails();
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.actionFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    creating.value = false;
  }
}

async function deleteProfile(id: string) {
  if (!props.isSuperadmin) return;
  try {
    await api(`/api/v1/admin/prompt-profiles/${encodeURIComponent(id)}`, { method: 'DELETE' });
    toast.ok(t('admin.strategy.promptDeleted'));
    await loadPromptDetails();
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.actionFailed', undefined, { msg: e.message || 'error' }));
  }
}

async function toggleModule(mod: any, enabled: boolean) {
  if (!props.isSuperadmin || mod.locked || togglingMod.value) return;
  togglingMod.value = mod.id;
  try {
    await api('/api/v1/admin/control-plane/quick-toggle', {
      method: 'POST',
      body: JSON.stringify({ target: 'prompt_module_enabled', item_id: mod.id, enabled, auto_snapshot: true }),
    });
    toast.ok(t('admin.strategy.savedToast'));
    await loadPromptDetails();
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    togglingMod.value = '';
  }
}

function toggleExpandModule(mod: any) {
  expandedModules.value[mod.id] = !expandedModules.value[mod.id];
  if (expandedModules.value[mod.id] && moduleEdits.value[mod.id] === undefined) {
    moduleEdits.value[mod.id] = String(mod.content || '');
  }
}

async function saveModules() {
  if (!props.isSuperadmin || !activeProfileId.value || savingModules.value) return;
  savingModules.value = true;
  try {
    const nextMods = tradingModules.value.map((m) => ({
      ...m,
      content: moduleEdits.value[m.id] ?? m.content ?? '',
    }));
    await api(`/api/v1/admin/prompt-profiles/${encodeURIComponent(activeProfileId.value)}`, {
      method: 'PUT',
      body: JSON.stringify({
        pipelines: { trading_system: nextMods },
        note: 'Strategy Center prompt modules save',
      }),
    });
    toast.ok(t('admin.strategy.promptModulesSaved'));
    await loadPromptDetails();
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    savingModules.value = false;
  }
}

async function saveOverride() {
  if (!props.isSuperadmin || savingOverride.value) return;
  savingOverride.value = true;
  try {
    await api('/api/v1/admin/prompts', {
      method: 'PUT',
      body: JSON.stringify({ content: overrideText.value }),
    });
    toast.ok(t('admin.strategy.promptOverrideSaved'));
    emit('refresh');
  } catch (e: any) {
    toast.err(t('admin.strategy.saveFailed', undefined, { msg: e.message || 'error' }));
  } finally {
    savingOverride.value = false;
  }
}

onMounted(loadPromptDetails);
</script>

<template>
  <div class="st-tab-stack">
    <!-- Profiles Library -->
    <section class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title">{{ t('admin.strategy.promptProfilesTitle') }}</h2>
        </div>
        <span class="badge mono">{{ activeProfileId || '—' }}</span>
      </header>
      <div class="wb-panel-body">
        <div class="st-profile-list">
          <div
            v-for="p in profiles"
            :key="p.id"
            class="st-profile-row"
            :class="{ 'is-active': p.id === activeProfileId }"
          >
            <div class="wb-setting-meta">
              <div class="st-title-line">
                <strong>{{ p.name || p.id }}</strong>
                <span class="badge mono">{{ p.id }}</span>
                <span v-if="p.id === activeProfileId" class="badge badge-up">{{ t('admin.strategy.promptActiveBadge') }}</span>
              </div>
              <span v-if="p.description" class="wb-setting-desc">{{ p.description }}</span>
            </div>
            <div class="st-row-actions">
              <button
                v-if="p.id !== activeProfileId"
                type="button"
                class="btn btn-primary btn-sm"
                :disabled="!isSuperadmin || activatingId === p.id"
                @click="activateProfile(p)"
              >
                <Loader2 v-if="activatingId === p.id" :size="13" class="animate-spin shrink-0" />
                <Check v-else :size="13" />
                <span>{{ t('admin.strategy.promptActivateBtn') }}</span>
              </button>
              <button
                v-if="p.id !== activeProfileId && !p.built_in"
                type="button"
                class="btn btn-quiet btn-icon btn-sm is-danger"
                :aria-label="t('admin.strategy.promptDeleteBtn')"
                :disabled="!isSuperadmin"
                @click="deleteProfile(p.id)"
              >
                <Trash2 :size="13" />
              </button>
            </div>
          </div>
        </div>

        <div class="wb-setting-row">
          <div class="wb-setting-meta">
            <span class="wb-setting-title">{{ t('admin.strategy.promptCloneTitle') }}</span>
          </div>
          <div class="st-clone-bar">
            <input
              v-model="cloneName"
              type="text"
              class="field"
              :aria-label="t('admin.strategy.promptCloneNamePlaceholder')"
              :placeholder="t('admin.strategy.promptCloneNamePlaceholder')"
              :disabled="!isSuperadmin"
            />
            <select v-model="cloneSourceId" class="field" :aria-label="t('admin.strategy.promptCloneSource')" :disabled="!isSuperadmin">
              <option v-for="p in profiles" :key="p.id" :value="p.id">{{ p.name || p.id }}</option>
            </select>
            <button
              type="button"
              class="btn btn-ghost btn-sm"
              :disabled="!isSuperadmin || !cloneName.trim() || creating"
              @click="createProfile"
            >
              <Loader2 v-if="creating" :size="13" class="animate-spin shrink-0" />
              <Plus v-else :size="13" />
              <span>{{ t('admin.strategy.promptCloneBtn') }}</span>
            </button>
          </div>
        </div>
      </div>
    </section>

    <!-- Modules Pipeline -->
    <section class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title">{{ t('admin.strategy.promptModulesTitle') }}</h2>
          <p class="card-sub">{{ t('admin.strategy.promptModulesDesc') }}</p>
        </div>
        <FileText :size="16" class="st-head-icon" />
      </header>
      <div class="wb-panel-body">
        <div v-for="m in tradingModules" :key="m.id" class="st-mod-card">
          <div class="st-mod-head">
            <div class="st-title-line">
              <strong>{{ m.title || m.id }}</strong>
              <span class="badge mono">{{ m.id }}</span>
              <span v-if="m.locked" class="badge badge-warn">{{ t('admin.strategy.promptLockedBadge') }}</span>
            </div>
            <div class="st-row-actions">
              <button
                type="button"
                class="btn btn-quiet btn-sm"
                :aria-expanded="Boolean(expandedModules[m.id])"
                :aria-controls="expandedModules[m.id] ? `st-mod-${m.id}` : undefined"
                @click="toggleExpandModule(m)"
              >
                <ChevronDown v-if="expandedModules[m.id]" :size="13" />
                <ChevronRight v-else :size="13" />
                <span>{{ expandedModules[m.id] ? t('admin.strategy.promptCloseEditorBtn') : t('admin.strategy.promptEditContentBtn') }}</span>
              </button>
              <BaseSwitch
                v-if="!m.locked"
                :modelValue="Boolean(m.enabled)"
                :disabled="!isSuperadmin || togglingMod === m.id"
                :label="m.title || m.id"
                @update:modelValue="toggleModule(m, $event)"
              />
            </div>
          </div>

          <div v-if="expandedModules[m.id]" :id="`st-mod-${m.id}`" class="st-mod-editor">
            <textarea
              v-model="moduleEdits[m.id]"
              rows="6"
              class="field mono"
              :aria-label="m.title || m.id"
              :disabled="!isSuperadmin || m.locked"
            />
          </div>
        </div>

        <div class="wb-toolbar">
          <span />
          <button
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="!isSuperadmin || savingModules"
            @click="saveModules"
          >
            <Loader2 v-if="savingModules" :size="13" class="animate-spin shrink-0" />
            <Save v-else :size="13" />
            <span>{{ t('admin.strategy.promptSaveModulesBtn') }}</span>
          </button>
        </div>
      </div>
    </section>

    <!-- System Override Layer -->
    <section class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title">{{ t('admin.strategy.promptOverrideTitle') }}</h2>
          <p class="card-sub">{{ t('admin.strategy.promptOverrideDesc') }}</p>
        </div>
      </header>
      <div class="wb-panel-body">
        <textarea
          v-model="overrideText"
          rows="4"
          class="field"
          :aria-label="t('admin.strategy.promptOverrideTitle')"
          :placeholder="t('admin.strategy.promptOverridePlaceholder')"
          :disabled="!isSuperadmin"
        />
        <div class="wb-toolbar">
          <span />
          <button
            type="button"
            class="btn btn-primary btn-sm"
            :disabled="!isSuperadmin || savingOverride"
            @click="saveOverride"
          >
            <Loader2 v-if="savingOverride" :size="13" class="animate-spin shrink-0" />
            <Save v-else :size="13" />
            <span>{{ t('admin.strategy.promptOverrideSave') }}</span>
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
.st-profile-list {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
}
.st-profile-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-radius: var(--r-ctl);
  border: 1px solid var(--ds-color-border-subtle);
  background-color: var(--ds-color-bg-surface-inset);
}
.st-profile-row.is-active {
  border-color: var(--accent-line);
  background-color: var(--ds-color-brand-subtle);
}
.st-title-line {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.st-row-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-shrink: 0;
}
.st-clone-bar {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.st-mod-card {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-radius: var(--r-ctl);
  border: 1px solid var(--ds-color-border-subtle);
  background-color: var(--ds-color-bg-surface-inset);
}
.st-mod-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-3);
  flex-wrap: wrap;
}
.st-mod-editor {
  padding-top: var(--ds-space-2);
}
</style>
