<script setup lang="ts">
/**
 * ProviderDetailView · 供应商详情（配置 / 模型 双 Tab）
 * ---------------------------------------------------------------------------
 * 骨架（推倒重来）：
 *   旧 = 顶部返回条 + 配置卡（**两段 peer/after 手搓开关**）
 *        + 模型卡（**8 处硬编码 rgba 胶囊** + `Sparkles` 彩色圆标）
 *        + **悬浮 fixed 底部双 Tab 条**（带 `0 2px 10px rgba(37,99,235,.35)` 辉光）
 *        + **悬浮 fixed 椭圆动作气泡**（获取 / 添加 / 清空）
 *   新 = **详情头**（返回 + 单字头像 + 名称 + 共享 `.seg` 双 Tab）
 *        → 配置 Tab：管理 kv 行（BaseSwitch）+ 凭据与端点表单
 *        → 模型 Tab：模型行清单（中性图标 + 语义徽章 + 能力 chip）+ 动作工具条
 *        → 测试结果面板
 *
 * ⚠️ 逻辑模块 `useLlmConfig.ts` / `llmLogic.ts` 未触碰；本组件只接 `useLlmCtx()`。
 */
import { useI18n } from '../../../composables/useI18n'
import { useToast } from '../../../composables/useToast'
import { useApi } from '../../../composables/useApi'
import { useRovingTabs } from '../../../composables/useRovingTabs'
import { useLlmCtx } from './injection'
import BaseSwitch from '../../../components/base/BaseSwitch.vue'
import BaseEmpty from '../../../components/base/BaseEmpty.vue'
import { AlertCircle, ArrowLeft, CheckCircle2, DownloadCloud, Eye, EyeOff,
  Layers, Plus, RefreshCw, Settings, Cpu, Trash2, Wrench, Brain, ImageIcon, Sparkles } from 'lucide-vue-next'

const { t } = useI18n()
const toast = useToast()
const { api } = useApi()
const {
  activateModel,
  cfg,
  clearCurrentProviderModels,
  deleteSingleModel,
  detailTab,
  goBackToList,
  loadConfig,
  onApiFormatChange,
  openAddModelModal,
  openEditModelModal,
  openFetchDialog,
  providerForm,
  removeProvider,
  runTestModel,
  saveProviderConfig,
  selectedProvider,
  showApiKey,
  testLoading,
  testResult,
  testingModelId,
} = useLlmCtx()

interface ProviderPreset {
  id: string
  name: string
  base_url: string
  api_format: string
  api_path: string
  recommended_models: Array<{
    id: string
    name: string
    capabilities: string[]
    reasoning_type: string
  }>
}

const PROVIDER_PRESETS: ProviderPreset[] = [
  {
    id: 'deepseek',
    name: 'DeepSeek',
    base_url: 'https://api.deepseek.com',
    api_format: 'openai_chat',
    api_path: '/chat/completions',
    recommended_models: [
      { id: 'deepseek-chat', name: 'DeepSeek-V3', capabilities: ['chat', 'tools'], reasoning_type: 'none' },
      { id: 'deepseek-reasoner', name: 'DeepSeek-R1', capabilities: ['chat', 'reasoning'], reasoning_type: 'full' },
    ],
  },
  {
    id: 'openai',
    name: 'OpenAI',
    base_url: 'https://api.openai.com/v1',
    api_format: 'openai_chat',
    api_path: '/chat/completions',
    recommended_models: [
      { id: 'gpt-4o', name: 'GPT-4o', capabilities: ['chat', 'vision', 'tools'], reasoning_type: 'none' },
      { id: 'gpt-4o-mini', name: 'GPT-4o mini', capabilities: ['chat', 'vision', 'tools'], reasoning_type: 'none' },
      { id: 'o3-mini', name: 'o3-mini', capabilities: ['chat', 'reasoning'], reasoning_type: 'full' },
    ],
  },
  {
    id: 'claude',
    name: 'Anthropic Claude',
    base_url: 'https://api.anthropic.com/v1',
    api_format: 'claude_messages',
    api_path: '/messages',
    recommended_models: [
      { id: 'claude-3-7-sonnet-20250219', name: 'Claude 3.7 Sonnet', capabilities: ['chat', 'vision', 'tools', 'reasoning'], reasoning_type: 'hybrid' },
      { id: 'claude-3-5-haiku-20241022', name: 'Claude 3.5 Haiku', capabilities: ['chat', 'tools'], reasoning_type: 'none' },
    ],
  },
  {
    id: 'siliconflow',
    name: 'SiliconFlow',
    base_url: 'https://api.siliconflow.cn/v1',
    api_format: 'openai_chat',
    api_path: '/chat/completions',
    recommended_models: [
      { id: 'deepseek-ai/DeepSeek-V3', name: 'DeepSeek-V3', capabilities: ['chat', 'tools'], reasoning_type: 'none' },
      { id: 'deepseek-ai/DeepSeek-R1', name: 'DeepSeek-R1', capabilities: ['chat', 'reasoning'], reasoning_type: 'full' },
      { id: 'Qwen/Qwen2.5-72B-Instruct', name: 'Qwen 2.5 72B', capabilities: ['chat'], reasoning_type: 'none' },
    ],
  },
  {
    id: 'qwen',
    name: 'Qwen (DashScope)',
    base_url: 'https://dashscope.aliyuncs.com/compatible-mode/v1',
    api_format: 'openai_chat',
    api_path: '/chat/completions',
    recommended_models: [
      { id: 'qwen-plus', name: 'Qwen Plus', capabilities: ['chat', 'tools'], reasoning_type: 'none' },
      { id: 'qwen-turbo', name: 'Qwen Turbo', capabilities: ['chat'], reasoning_type: 'none' },
      { id: 'qwen-max', name: 'Qwen Max', capabilities: ['chat', 'tools'], reasoning_type: 'none' },
    ],
  },
  {
    id: 'ollama',
    name: 'Ollama',
    base_url: 'http://localhost:11434/v1',
    api_format: 'openai_chat',
    api_path: '/chat/completions',
    recommended_models: [
      { id: 'deepseek-r1:8b', name: 'DeepSeek R1 8B', capabilities: ['chat', 'reasoning'], reasoning_type: 'full' },
      { id: 'qwen2.5:7b', name: 'Qwen 2.5 7B', capabilities: ['chat'], reasoning_type: 'none' },
    ],
  },
]

function applyProviderPreset(p: ProviderPreset) {
  providerForm.value.name = p.name
  if (!providerForm.value.id || selectedProvider.value.is_new) {
    providerForm.value.id = p.id
  }
  providerForm.value.base_url = p.base_url
  providerForm.value.api_format = p.api_format
  providerForm.value.api_path = p.api_path
  toast.ok(t('admin.llm.presetApplied', undefined, { name: p.name }))
}

async function importRecommendedModels() {
  const provId = (selectedProvider.value.id || providerForm.value.id || '').toLowerCase()
  const preset = PROVIDER_PRESETS.find(p => p.id === provId || provId.includes(p.id) || p.name.toLowerCase().includes(provId))
  if (!preset) {
    toast.warn(t('admin.llm.noPresetModels'))
    return
  }
  const existingIds = new Set((selectedProvider.value.models || []).map((m: any) => m.id))
  const newModels = preset.recommended_models.filter(m => !existingIds.has(m.id))
  if (!newModels.length) {
    toast.ok(t('admin.llm.modelsAlreadyExist'))
    return
  }
  try {
    for (const m of newModels) {
      await api('/api/v1/admin/llm/models', {
        method: 'POST',
        body: JSON.stringify({
          id: m.id,
          name: m.name,
          capabilities: m.capabilities,
          reasoning_type: m.reasoning_type,
          provider_id: selectedProvider.value.id || preset.id,
          provider_name: selectedProvider.value.name || preset.name,
          base_url: selectedProvider.value.base_url || preset.base_url,
          api_format: selectedProvider.value.api_format || preset.api_format,
        }),
      })
    }
    await loadConfig()
    toast.ok(t('admin.llm.modelsImported', undefined, { n: newModels.length }))
  } catch (err: any) {
    toast.err(err.message)
  }
}

/** 批 66：详情页两页签的漫游 tabindex 与方向键导航（此前全在 Tab 键顺序里）。 */
const DETAIL_TABS: Array<'config' | 'models'> = ['config', 'models']
const { setRef: setDetailRef, onKeydown: onDetailKey, roving: detailRoving } = useRovingTabs(
  () => DETAIL_TABS.length,
  (i) => { detailTab.value = DETAIL_TABS[i] },
)

function monogram(name: string): string {
  return String(name || '?').trim().slice(0, 2).toUpperCase()
}
</script>

<template>
  <div class="pd">
    <!-- ══ 详情头 ══ -->
    <section class="card pd-head">
      <button type="button" class="btn btn-ghost btn-sm" @click="goBackToList">
        <ArrowLeft :size="14" />
        <span>{{ t('admin.llm.back') }}</span>
      </button>

      <div class="pd-id">
        <span class="icon-box is-md is-mono mono">{{ monogram(selectedProvider.name) }}</span>
        <div class="pd-id-text">
          <span class="pd-name">{{ selectedProvider.name }}</span>
          <span class="pd-sub mono">{{ selectedProvider.id || providerForm.id }}</span>
        </div>
      </div>

      <div class="pd-tabs">
        <div class="seg seg-lg" role="tablist" :aria-label="t('admin.llm.detailTabsAria')">
          <button
            type="button"
            role="tab"
            :ref="setDetailRef(0)"
            :aria-selected="detailTab === 'config'"
            :tabindex="detailRoving(detailTab === 'config')"
            :class="{ 'seg-on': detailTab === 'config' }"
            @click="detailTab = 'config'"
            @keydown="onDetailKey($event, 0)"
          >
            <Settings :size="13" aria-hidden="true" />
            <span>{{ t('admin.llm.tabConfig') }}</span>
          </button>
          <button
            type="button"
            role="tab"
            :ref="setDetailRef(1)"
            :aria-selected="detailTab === 'models'"
            :tabindex="detailRoving(detailTab === 'models')"
            :class="{ 'seg-on': detailTab === 'models' }"
            @click="detailTab = 'models'"
            @keydown="onDetailKey($event, 1)"
          >
            <Layers :size="13" aria-hidden="true" />
            <span>{{ t('admin.llm.tabModels') }} ({{ selectedProvider.models?.length || 0 }})</span>
          </button>
        </div>
      </div>
    </section>

    <!-- ══════════ Tab A：配置 ══════════ -->
    <template v-if="detailTab === 'config'">
      <!-- 快捷预设横条 -->
      <section class="card">
        <div class="pd-presets-bar">
          <span class="pd-presets-label">{{ t('admin.llm.quickPresets') }}:</span>
          <div class="pd-presets-list">
            <button
              v-for="p in PROVIDER_PRESETS"
              :key="p.id"
              type="button"
              class="btn btn-ghost btn-sm"
              @click="applyProviderPreset(p)"
            >
              {{ p.name }}
            </button>
          </div>
        </div>
      </section>

      <section class="card">
        <header class="card-head">
          <h2 class="card-title"><Settings :size="14" />{{ t('admin.llm.manage') }}</h2>
        </header>

        <div class="pd-kv">
          <div class="kv-row">
            <span class="pd-kv-k">{{ t('admin.llm.providerType') }}</span>
            <span class="pd-kv-v mono">{{ providerForm.type }}</span>
          </div>

          <div class="kv-row">
            <div class="pd-kv-k-block">
              <span class="pd-kv-k">{{ t('admin.llm.apiProtocol') }}</span>
            </div>
            <select
              v-model="providerForm.api_format"
              class="field pd-select"
              :aria-label="t('admin.llm.apiProtocol')"
              @change="onApiFormatChange"
            >
              <option value="openai_chat">OpenAI Chat (/chat/completions)</option>
              <option value="claude_messages">Claude Messages (/messages)</option>
              <option value="openai_responses">OpenAI Responses (/responses)</option>
            </select>
          </div>

          <div class="kv-row">
            <span class="pd-kv-k">{{ t('admin.llm.group') }}</span>
            <span class="pd-kv-v mono">{{ providerForm.group || '--' }}</span>
          </div>

          <div class="kv-row">
            <span class="pd-kv-k">{{ t('admin.llm.enabledField') }}</span>
            <BaseSwitch v-model="providerForm.enabled" :label="t('admin.llm.enabledField')" />
          </div>

          <div class="kv-row">
            <span class="pd-kv-k">{{ t('admin.llm.multiKey') }}</span>
            <BaseSwitch v-model="providerForm.multi_key_enabled" :label="t('admin.llm.multiKey')" />
          </div>
        </div>
      </section>

      <section class="card">
        <header class="card-head">
          <h2 class="card-title">{{ t('admin.llm.credentialsTitle') }}</h2>
          <span v-if="selectedProvider.has_key" class="badge badge-up">{{ t('admin.llm.keyReady') }}</span>
        </header>

        <div class="pd-form">
          <label v-if="selectedProvider.is_new" class="field-stack">
            <span class="form-label">{{ t('admin.llm.providerId') }}</span>
            <input v-model="providerForm.id" :placeholder="t('admin.llm.providerIdPlaceholder')" class="field mono" />
          </label>

          <label class="field-stack">
            <span class="form-label">{{ t('admin.llm.name') }}</span>
            <input v-model="providerForm.name" placeholder="OpenAI" class="field" />
          </label>

          <label class="field-stack">
            <span class="form-label">API Key</span>
            <div class="pd-key">
              <input
                v-model="providerForm.api_key"
                :type="showApiKey ? 'text' : 'password'"
                placeholder="••••••••••••••••••••••••"
                class="field mono"
              />
              <button
                type="button"
                class="btn btn-quiet btn-icon btn-sm pd-eye"
                :title="showApiKey ? t('admin.llm.hideApiKey') : t('admin.llm.showApiKey')"
                :aria-label="showApiKey ? t('admin.llm.hideApiKey') : t('admin.llm.showApiKey')"
                @click="showApiKey = !showApiKey"
              >
                <EyeOff v-if="showApiKey" :size="14" />
                <Eye v-else :size="14" />
              </button>
            </div>
          </label>

          <label class="field-stack">
            <span class="form-label">API Base URL</span>
            <input v-model="providerForm.base_url" :placeholder="t('admin.llm.baseUrlPlaceholder')" class="field mono" />
          </label>

          <label class="field-stack">
            <span class="form-label">{{ t('admin.llm.apiPath') }}</span>
            <input v-model="providerForm.api_path" placeholder="/chat/completions" class="field mono" />
          </label>
        </div>

        <footer class="pd-foot">
          <button
            v-if="!selectedProvider.is_new"
            type="button"
            class="btn btn-danger btn-sm"
            @click="removeProvider"
          >
            <Trash2 :size="13" />
            <span>{{ t('admin.llm.deleteProvider') }}</span>
          </button>
          <span class="pd-foot-spacer" />
          <button type="button" class="btn btn-primary btn-sm" @click="saveProviderConfig">
            {{ t('admin.llm.saveProvider') }}
          </button>
        </footer>
      </section>
    </template>

    <!-- ══════════ Tab B：模型 ══════════ -->
    <template v-else-if="detailTab === 'models'">
      <section class="card">
        <header class="card-head">
          <h2 class="card-title"><Cpu :size="14" />{{ t('admin.llm.tabModels') }}</h2>
          <span class="badge mono">{{ selectedProvider.models?.length || 0 }}</span>
        </header>

        <BaseEmpty v-if="!selectedProvider.models?.length" :text="t('admin.llm.noModels')" />

        <div v-else class="pd-models">
          <article v-for="m in selectedProvider.models" :key="m.id" class="pd-model">
            <span class="icon-box is-md"><Cpu :size="14" /></span>

            <div class="pd-model-main">
              <div class="pd-model-title">
                <span class="pd-model-id mono truncate">{{ m.id }}</span>
                <span v-if="m.id === cfg?.active_model_id" class="badge badge-up">
                  {{ t('admin.llm.brainActiveModel') }}
                </span>
              </div>

              <div class="pd-caps">
                <span v-if="m.capabilities?.includes('chat')" class="badge">{{ t('admin.llm.capChat') }}</span>
                <span v-if="m.capabilities?.includes('vision')" class="badge">
                  <ImageIcon :size="11" />{{ t('admin.llm.capVision') }}
                </span>
                <span v-if="m.capabilities?.includes('tools')" class="badge" :title="t('admin.llm.capToolsTitle')">
                  <Wrench :size="11" />tools
                </span>
                <span
                  v-if="m.capabilities?.includes('reasoning') || m.reasoning_type !== 'none'"
                  class="badge"
                  :title="t('admin.llm.capReasonTitle')"
                >
                  <Brain :size="11" />{{ t('admin.llm.capThink') }}
                </span>
                <span v-if="m.context_length" class="pd-ctx mono">{{ (m.context_length / 1000).toFixed(0) }}k</span>
              </div>
            </div>

            <div class="pd-model-actions">
              <button
                v-if="m.id !== cfg?.active_model_id"
                type="button"
                class="btn btn-primary btn-sm"
                :title="t('admin.llm.setBrainTitle')"
                @click="activateModel(m)"
              >
                {{ t('admin.llm.enable') }}
              </button>

              <button
                type="button"
                class="btn btn-ghost btn-icon btn-sm"
                :disabled="testLoading && testingModelId === m.id"
                :title="t('admin.llm.testConnTitle')"
                @click="runTestModel(m)"
              >
                <RefreshCw :size="14" :class="testLoading && testingModelId === m.id ? 'animate-spin shrink-0' : ''" />
              </button>

              <button type="button" class="btn btn-ghost btn-icon btn-sm" :title="t('admin.llm.editParamsTitle')" @click="openEditModelModal(m)">
                <Settings :size="13" />
              </button>

              <button type="button" class="btn btn-quiet btn-icon btn-sm is-danger" :title="t('admin.llm.deleteModelTitle')" @click="deleteSingleModel(m)">
                <Trash2 :size="13" />
              </button>
            </div>
          </article>
        </div>

        <footer class="pd-toolbar">
          <button type="button" class="btn btn-ghost btn-sm" :title="t('admin.llm.importRecommendedModelsTitle')" @click="importRecommendedModels">
            <Sparkles :size="13" />
            <span>{{ t('admin.llm.importRecommendedModels') }}</span>
          </button>
          <button type="button" class="btn btn-ghost btn-sm" @click="openFetchDialog">
            <DownloadCloud :size="13" />
            <span>{{ t('admin.llm.fetch') }}</span>
          </button>
          <button type="button" class="btn btn-ghost btn-sm" @click="openAddModelModal">
            <Plus :size="13" />
            <span>{{ t('admin.llm.addNewModel') }}</span>
          </button>
          <button type="button" class="btn btn-quiet btn-sm is-danger" :title="t('admin.llm.clearModelsTitle')" @click="clearCurrentProviderModels">
            <Trash2 :size="13" />
            <span>{{ t('admin.llm.clearModelsTitle') }}</span>
          </button>
        </footer>
      </section>

      <!-- 连通性诊断结果 -->
      <section v-if="testResult" class="card pd-test" :role="testResult.ok ? 'status' : 'alert'" :class="testResult.ok ? 'is-ok' : 'is-error'">
        <header class="pd-test-head">
          <span class="pd-test-icon">
            <CheckCircle2 v-if="testResult.ok" :size="15" />
            <AlertCircle v-else :size="15" />
          </span>
          <span class="pd-test-title">
            {{ testResult.ok
              ? t('admin.llm.testPassed', undefined, { ms: testResult.latency_ms })
              : t('admin.llm.testFailed') }}
          </span>
          <span class="badge mono">{{ t('admin.llm.status') }} {{ testResult.status_code || 0 }}</span>
        </header>

        <div v-if="testResult.ok" class="pd-test-body">
          <p>{{ t('admin.llm.outputPreview') }} <b>{{ testResult.response_preview }}</b></p>
          <p v-if="testResult.reasoning_detected" class="pd-test-cot">{{ t('admin.llm.reasoningDetected') }}</p>
        </div>
        <p v-else class="pd-test-body pd-test-err">{{ testResult.error || t('admin.llm.testTimeoutErr') }}</p>
      </section>
    </template>
  </div>
</template>

<style scoped>
.pd {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}

/* ══ 详情头 ══ */
.pd-head {
  display: flex;
  align-items: center;
  gap: var(--ds-space-3);
  flex-wrap: wrap;
  padding: var(--ds-space-3) var(--ds-space-4);
}
.pd-id {
  display: flex;
  align-items: center;
  gap: 10px;
  min-width: 0;
}
.pd-id-text {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.pd-name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.pd-sub {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.pd-tabs {
  margin-left: auto;
}

/* ══ 快捷预设横条 ══ */
.pd-presets-bar {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
  padding: var(--ds-space-2) var(--ds-space-4);
  background-color: var(--ds-color-bg-surface-inset);
}
.pd-presets-label {
  font-size: var(--text-3xs);
  font-weight: 600;
  color: var(--ds-color-text-secondary);
  text-transform: uppercase;
  letter-spacing: var(--tracking-wider);
}
.pd-presets-list {
  display: flex;
  align-items: center;
  gap: var(--ds-space-1);
  flex-wrap: wrap;
}

/* ══ 配置 kv ══ */
.pd-kv {
  display: flex;
  flex-direction: column;
}
.pd-kv-k {
  font-size: var(--text-xs);
  color: var(--ds-color-text-primary);
}
.pd-kv-k-block {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.pd-kv-v {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-description);
  text-align: right;
}
.pd-select {
  max-width: 260px;
  cursor: pointer;
}

/* ══ 表单 ══ */
.pd-form {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
  padding: var(--ds-space-4);
}

.pd-key {
  position: relative;
  display: flex;
  align-items: center;
}
/* 批 97：38px = 右侧 `.pd-eye`（absolute right 4）按钮宽 + 间隙
   —— 推导几何，刻意离格。 */
.pd-key .field {
  padding-right: 38px;
}
.pd-eye {
  position: absolute;
  right: 4px;
}
.pd-foot {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface-inset);
}
.pd-foot-spacer {
  flex: 1;
}

/* ══ 模型 ══ */
.pd-models {
  display: flex;
  flex-direction: column;
}
.pd-model {
  display: grid;
  grid-template-columns: 32px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
  transition: background-color var(--dur-fast);
}
.pd-model:hover {
  background-color: var(--ds-color-bg-hover);
}
.pd-model-main {
  display: flex;
  flex-direction: column;
  gap:6px;
  min-width: 0;
}
.pd-model-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  min-width: 0;
}
.pd-model-id {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
  min-width: 0;
}
.pd-caps {
  display: flex;
  align-items: center;
  gap:6px;
  flex-wrap: wrap;
}
.pd-caps .badge {
  gap: 4px;
}
.pd-ctx {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
  margin-left:4px;
}
.pd-model-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-shrink: 0;
}
.pd-toolbar {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface-inset);
}

@media (max-width: 820px) {
  .pd-model {
    grid-template-columns: 32px minmax(0, 1fr);
  }
  .pd-model-actions {
    grid-column: 2;
    justify-content: flex-end;
  }
}

/* ══ 测试结果 ══ */
.pd-test {
  border-left: 2px solid var(--up);
}
.pd-test.is-error {
  border-left-color: var(--down);
}
.pd-test-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
}
.pd-test.is-ok .pd-test-head {
  color: var(--up);
}
.pd-test.is-error .pd-test-head {
  color: var(--down);
}
.pd-test-icon {
  display: flex;
  flex-shrink: 0;
}
.pd-test-title {
  font-size: var(--text-xs);
  font-weight: 600;
}
.pd-test-body {
  padding: var(--ds-space-3) var(--ds-space-4);
  font-size: var(--text-3xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-secondary);
  overflow-wrap: anywhere;
}
.pd-test-body b {
  color: var(--ds-color-text-primary);
  font-weight: 600;
}
.pd-test-cot {
  margin-top: 4px;
  color: var(--up);
}
.pd-test-err {
  color: var(--down);
}
</style>
