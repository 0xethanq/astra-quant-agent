/**
 * `LlmPage` 的状态与动作（结构优化阶段 3·F3 抽离）。
 *
 * 原 `LlmPage.vue` 是 1762 行：script 636 行 + template 1124 行。这里把
 * **状态与所有与服务端交互的动作**整体搬出来，页面只保留"模板 + 编排"。
 *
 * 抽离方式刻意选**整体搬迁**（不是拆成若干小组件）：这些动作彼此共享
 * `cfg` / `providerForm` / `modelForm` 等状态，拆散会立刻产生大量参数传递；
 * 而整体搬进一个 composable 后，闭包关系原地保留、行为零变化。
 * 模板所需的绑定由页面解构取得（`<script setup>` 顶层绑定对模板可见）。
 *
 * 不在页面里直接写逻辑的收益：这段逻辑不再依赖模板上下文，可被
 * `vue-tsc` 独立检查，也为后续按域再拆（provider / model / failover）留了位置。
 */
import { computed, onMounted, ref } from 'vue'
import { useI18n } from './useI18n'
import { useApi } from './useApi'
import { useConfirm } from './useConfirm'
import { useToast } from './useToast'
import {
  apiFormatEffect,
  buildActivatePayload,
  buildRemoteModelPayload,
  effortOptions,
  fallbackOptionsFor,
  filterProviders,
  filterRemoteModels,
  modelDisplayName,
  moveInArray,
  providerDeleteCascadeHint,
  providerIdFromName,
  toggleInArray,
} from './llmLogic'

export function useLlmConfig() {
  const { t } = useI18n()
  const { ask } = useConfirm()
  const toast = useToast()

const { api } = useApi()

// State
const cfg = ref<any>(null)
/** 批 72：配置拉取失败的真实原因（此前只进 console，界面只能显示通用文案） */
const cfgError = ref('')
const loading = ref(true)
const searchQuery = ref('')

// Navigation: 'list' (一级：供应商列表) | 'detail' (二级：供应商配置与模型详情)
const currentView = ref<'list' | 'detail'>('list')
const selectedProvider = ref<any>(null)
const detailTab = ref<'config' | 'models'>('config')

// Password visibility toggles
const showApiKey = ref(false)

// Edit / Add Provider Form
const providerForm = ref<any>({
  id: '',
  name: '',
  type: 'OpenAI',
  group: t('admin.llm.providerGroupOther'),
  enabled: true,
  multi_key_enabled: false,
  response_api_enabled: false,
  base_url: '',
  api_key: '',
  api_path: '/chat/completions',
  description: '',
})

// Test Connection State
const testResult = ref<any>(null)
const testLoading = ref(false)
const testingModelId = ref<string | null>(null)

// ── 模型条目结构自检（2026-09-29）────────────────────────────────────────
// 后台此前把三条模型并列显示、其中两条是死的（无密钥 / 供应商不存在）却毫无标记，
// 且 `fallback_model_ids` 为空（等于没有回退）。这里把后端下发的 `model_health`
// 接到界面：可用性徽标 + 「全部测试」真机自检 + 「清理失效条目」。
const testAllLoading = ref(false)
const testAllResult = ref<any>(null)
const cleanupLoading = ref(false)
const cleanupResult = ref<any>(null)
const modelHealth = computed<any>(() => cfg.value?.model_health || { models: {}, warnings: [], counts: {} })
const healthWarnings = computed<any[]>(() => modelHealth.value.warnings || [])
const deadModelIds = computed<string[]>(() =>
  Object.entries(modelHealth.value.models || {})
    .filter(([, h]: any) => h?.status === 'dead')
    .map(([id]) => id))
function healthOf(modelId: string) {
  return modelHealth.value.models?.[modelId] || null
}
function providerHealth(prov: any) {
  const rows = (prov?.models || []).map((m: any) => healthOf(m.id)).filter(Boolean)
  // ⚠️ 刻意不用内联 `return { … }`：`tests/llm/test_frontend_llm_config_baseline.py`
  // 用非贪婪正则 `return \{(.*?)\n  \}` 解析本模块的**导出面**，多一个内联 return
  // 对象就会让那道门禁解析到错误的块（实测：导出面被判"缺 7 个键"）。
  const summary = {
    dead: rows.filter((h: any) => h.status === 'dead').length,
    warn: rows.filter((h: any) => h.status === 'warn').length,
    total: rows.length,
  }
  return summary
}

// Remote Fetch State & Modal
const fetchModalVisible = ref(false)
const fetchingRemote = ref(false)
const remoteFetchResult = ref<any>(null)
const remoteSearch = ref('')
const customFetchUrl = ref('')
const customFetchKey = ref('')

// Add / Edit Single Model Modal
const modelModalVisible = ref(false)
const editingModel = ref<any>(null)
const modelForm = ref<any>({
  id: '',
  name: '',
  provider_id: '',
  capabilities: ['chat'],
  reasoning_effort: 'high',
  context_length: 128000,
  description: '',
})

// Copied feedback

// Global Reasoning & Thinking Timeout State
const thinkingTimeoutInput = ref<number>(120)
const reasoningEffortInput = ref<string>('high')
const savingSettings = ref(false)
const settingsResult = ref<any>(null)

// ── LLM 韧性配置：单模型请求次数 + 回退模型链 ──
const requestAttemptsInput = ref<number>(3)
const fallbackIds = ref<string[]>([])
const failoverEvents = ref<any[]>([])

const fallbackOptions = computed(() => fallbackOptionsFor(cfg.value))

function toggleFallback(id: string) {
  // 上限判定留在门面：它要写 settingsResult + 起定时器，属"编排"不是纯逻辑。
  // 数组增删本身走纯函数（`toggleInArray` 原地改，vue 仍能追踪）。
  const idx = fallbackIds.value.indexOf(id)
  if (idx === -1 && fallbackIds.value.length >= (cfg.value?.max_fallback_models || 5)) {
    settingsResult.value = { ok: false, error: t('admin.llm.fallbackLimitErr') }
    setTimeout(() => { settingsResult.value = null }, 3500)
    return
  }
  toggleInArray(fallbackIds.value, id)
}

function moveFallback(idx: number, dir: -1 | 1) {
  moveInArray(fallbackIds.value, idx, dir)
}

function modelNameOf(id: string) {
  return modelDisplayName(cfg.value?.models, id)
}

async function loadFailoverEvents() {
  try {
    const res = await api('/api/v1/admin/llm/failover-events')
    failoverEvents.value = res?.events || []
  } catch {
    failoverEvents.value = []
  }
}

function setPresetTimeout(sec: number) {
  thinkingTimeoutInput.value = sec
}

async function saveGlobalSettings() {
  savingSettings.value = true
  settingsResult.value = null
  try {
    await api('/api/v1/admin/llm/settings', {
      method: 'POST',
      body: JSON.stringify({
        thinking_timeout: Number(thinkingTimeoutInput.value) || 120,
        active_model_id: cfg.value?.active_model_id,
        reasoning_effort: reasoningEffortInput.value || cfg.value?.active_reasoning_effort || 'high',
        request_attempts: Number(requestAttemptsInput.value) || 3,
        fallback_model_ids: fallbackIds.value,
      }),
    })
    await loadConfig()
    await loadFailoverEvents()
    settingsResult.value = {
      ok: true,
      message: t(
        'admin.llm.settingsSaved',
        undefined,
        { sec: thinkingTimeoutInput.value, n: requestAttemptsInput.value, m: fallbackIds.value.length },
      ),
    }
    setTimeout(() => {
      settingsResult.value = null
    }, 3500)
  } catch (err: any) {
    settingsResult.value = { ok: false, error: err.message }
  } finally {
    savingSettings.value = false
  }
}

// ----------------- Data Loading -----------------
async function loadConfig() {
  loading.value = true
  // 批 72：此前失败只 console.error，真实原因被丢弃 —— 三个消费方页面的错误块
  // 因此只能显示一句通用的「网络异常」，运维看不到 401/500 之类的真实原因。
  cfgError.value = ''
  try {
    cfg.value = await api('/api/v1/admin/llm/models')
    if (cfg.value?.active_reasoning_effort) {
      reasoningEffortInput.value = String(cfg.value.active_reasoning_effort).toLowerCase()
    }
    if (cfg.value?.thinking_timeout) {
      thinkingTimeoutInput.value = Number(cfg.value.thinking_timeout)
    }
    if (cfg.value?.request_attempts) {
      requestAttemptsInput.value = Number(cfg.value.request_attempts)
    }
    if (Array.isArray(cfg.value?.fallback_model_ids)) {
      fallbackIds.value = [...cfg.value.fallback_model_ids]
    }
    if (selectedProvider.value) {
      const updated = cfg.value.providers?.find((p: any) => p.id === selectedProvider.value.id)
      if (updated) {
        selectedProvider.value = updated
      }
    }
  } catch (e: any) {
    cfgError.value = String(e?.message || e)
    console.error('Failed to load LLM config:', e)
  } finally {
    loading.value = false
  }
}

// ----------------- 2026 大模型前缀缓存与 L1 查询缓存 -----------------
const cacheStatus = ref<any>(null)
const cacheLoading = ref(false)

async function loadCacheStatus() {
  try {
    cacheStatus.value = await api('/api/v1/admin/llm/cache/status')
  } catch (e: any) {
    console.error('Failed to load LLM cache status:', e)
  }
}

async function clearL1Cache() {
  cacheLoading.value = true
  try {
    const res = await api('/api/v1/admin/llm/cache/clear', { method: 'POST' })
    toast.ok(res?.message || t('admin.llm.toastL1Cleared'))
    await loadCacheStatus()
  } catch (e: any) {
    toast.err(String(e?.message || e))
  } finally {
    cacheLoading.value = false
  }
}

// Model Effort Options depending on model family
const availableEffortOptions = computed(() => effortOptions(modelForm.value.id, t))

// ----------------- Filtered Providers -----------------
const filteredProviders = computed(() => filterProviders(cfg.value?.providers, searchQuery.value))

// ----------------- Provider Actions -----------------
function openAddProviderModal() {
  selectedProvider.value = { id: '', name: t('admin.llm.newProviderName'), is_new: true }
  providerForm.value = {
    id: '',
    name: '',
    type: t('admin.llm.providerTypeCompat'),
    group: t('admin.llm.providerGroupCustom'),
    enabled: true,
    multi_key_enabled: false,
    response_api_enabled: false,
    api_format: 'openai_chat',
    base_url: '',
    api_key: '',
    api_path: '/chat/completions',
    description: '',
  }
  detailTab.value = 'config'
  currentView.value = 'detail'
  testResult.value = null
  showApiKey.value = false
}

function selectProvider(p: any) {
  selectedProvider.value = p
  const format = p.api_format || (p.id === 'claude' ? 'claude_messages' : 'openai_chat')
  providerForm.value = {
    id: p.id,
    name: p.name,
    type: p.type || p.name,
    group: p.group || t('admin.llm.providerGroupOther'),
    enabled: !!p.enabled,
    multi_key_enabled: !!p.multi_key_enabled,
    response_api_enabled: !!p.response_api_enabled,
    api_format: format,
    base_url: p.base_url || '',
    api_key: '',
    api_path: p.api_path || (format === 'claude_messages' ? '/messages' : (format === 'openai_responses' ? '/responses' : '/chat/completions')),
    description: p.description || '',
  }
  detailTab.value = 'config'
  currentView.value = 'detail'
  testResult.value = null
  showApiKey.value = false
}

function onApiFormatChange() {
  const effect = apiFormatEffect(providerForm.value.api_format, providerForm.value.api_path)
  providerForm.value.api_path = effect.apiPath
  providerForm.value.response_api_enabled = effect.responseApiEnabled
}

function goBackToList() {
  currentView.value = 'list'
  selectedProvider.value = null
  testResult.value = null
}

async function toggleProviderQuick(p: any, e: Event) {
  e.stopPropagation()
  try {
    const res = await api(`/api/v1/admin/llm/providers/${encodeURIComponent(p.id)}/toggle`, {
      method: 'POST',
      body: JSON.stringify({ enabled: !p.enabled }),
    })
    p.enabled = res.enabled
    await loadConfig()
  } catch (err: any) {
    toast.err(err.message)
  }
}

async function saveProviderConfig() {
  try {
    const payload = { ...providerForm.value }
    if (!payload.id) {
      payload.id = providerIdFromName(payload.name)
    }
    if (!payload.api_key) delete payload.api_key
    await api('/api/v1/admin/llm/providers', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    toast.ok(t('admin.llm.toastProviderSaved'))
    await loadConfig()
    if (selectedProvider.value?.is_new) {
      const created = cfg.value.providers?.find((p: any) => p.id === payload.id)
      if (created) {
        selectedProvider.value = created
      }
    }
  } catch (err: any) {
    toast.err(err.message)
  }
}

async function clearCurrentProviderModels() {
  if (!selectedProvider.value) return
  // 批C(2026-09-13)：破坏性操作统一走项目确认服务（原生 confirm 在移动端易误触）
  const _ok = await ask({
    title: t('admin.llm.confirmClearProviderTitle'),
    desc: t('admin.llm.confirmClearProviderDesc', undefined, { name: selectedProvider.value.name }),
    danger: true,
    okText: t('admin.llm.confirmClearProviderOk'),
  })
  if (!_ok) return
  try {
    await api(`/api/v1/admin/llm/providers/${encodeURIComponent(selectedProvider.value.id)}/models`, {
      method: 'DELETE',
    })
    toast.ok(t('admin.llm.toastProviderCleared'))
    await loadConfig()
  } catch (err: any) {
    toast.err(err.message)
  }
}

async function removeProvider() {
  const p = selectedProvider.value
  if (!p || p.is_new) return
  // 级联提示文案由纯函数 providerDeleteCascadeHint 产出
  // 批C(2026-09-13)：删供应商可能带走主脑激活模型 → danger + 提示先切换模型
  // 批2(2026-09-13)：原先这里算出 warn 却从未使用（vue-tsc TS6133），模型联删提示形同丢失，
  // 现直接并入确认文案，保证「删之前知道会带走什么」。
  const cascade = providerDeleteCascadeHint(p, t)
  const _ok = await ask({
    title: t('admin.llm.confirmDeleteProviderTitle'),
    desc: t('admin.llm.confirmDeleteProviderDesc', undefined, { name: p.name, cascade }),
    detail: t('admin.llm.confirmDeleteProviderDetail'),
    danger: true,
    okText: t('admin.llm.confirmDeleteOk'),
  })
  if (!_ok) return
  try {
    await api(`/api/v1/admin/llm/providers/${encodeURIComponent(p.id)}`, {
      method: 'DELETE',
    })
    toast.ok(t('admin.llm.toastProviderDeleted', undefined, { name: p.name }))
    goBackToList()
    await loadConfig()
  } catch (err: any) {
    toast.err(err.message)
  }
}

// ----------------- Remote Fetch -----------------
function openFetchDialog() {
  if (!selectedProvider.value) return
  customFetchUrl.value = selectedProvider.value.base_url || ''
  customFetchKey.value = ''
  remoteFetchResult.value = null
  remoteSearch.value = ''
  fetchModalVisible.value = true
  // 优化：若当前供应商已配置好 Base URL，弹窗打开时自动发起探测拉取，免除重复输入与多次点击
  executeRemoteFetch()
}

async function executeRemoteFetch() {
  if (!selectedProvider.value) return
  fetchingRemote.value = true
  remoteFetchResult.value = null
  try {
    const payload: any = {
      provider_id: selectedProvider.value.id,
      base_url: customFetchUrl.value.trim() || selectedProvider.value.base_url,
    }
    if (customFetchKey.value.trim()) {
      payload.api_key = customFetchKey.value.trim()
    }
    const res = await api('/api/v1/admin/llm/fetch-models', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    remoteFetchResult.value = res
  } catch (err: any) {
    remoteFetchResult.value = { ok: false, error: err.message }
  } finally {
    fetchingRemote.value = false
  }
}

const filteredRemoteModels = computed(() =>
  filterRemoteModels(remoteFetchResult.value?.models, remoteSearch.value),
)

async function importRemoteModel(m: any, autoActivate = false) {
  if (!selectedProvider.value) return
  try {
    const payload = buildRemoteModelPayload(m, selectedProvider.value, t)
    await api('/api/v1/admin/llm/models', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    if (autoActivate) {
      await api('/api/v1/admin/llm/activate', {
        method: 'POST',
        body: JSON.stringify(buildActivatePayload(
          m.id, selectedProvider.value.id, payload.reasoning_effort,
        )),
      })
    }
    await loadConfig()
    toast.ok(
      autoActivate
        ? t('admin.llm.toastModelActivated', undefined, { id: m.id })
        : t('admin.llm.toastModelAdded', undefined, { id: m.id }),
    )
  } catch (err: any) {
    toast.err(err.message)
  }
}

async function importAllFilteredRemoteModels() {
  if (!selectedProvider.value || !filteredRemoteModels.value.length) return
  const list = filteredRemoteModels.value
  let successCount = 0
  for (const m of list) {
    try {
      // ⚠️ 本刀之前这里与 importRemoteModel 各写了一份**逐字相同**的 payload
      //    字面量（11 个字段的回落链）。现统一走 buildRemoteModelPayload。
      const payload = buildRemoteModelPayload(m, selectedProvider.value, t)
      await api('/api/v1/admin/llm/models', {
        method: 'POST',
        body: JSON.stringify(payload),
      })
      successCount++
    } catch (e) {
      console.warn('Import model failed:', m.id, e)
    }
  }
  await loadConfig()
  toast.ok(t('admin.llm.toastModelsImported', undefined, { n: successCount, name: selectedProvider.value.name }))
}

// ----------------- Model Management -----------------
function openAddModelModal() {
  if (!selectedProvider.value) return
  editingModel.value = null
  modelForm.value = {
    id: '',
    name: '',
    provider_id: selectedProvider.value.id,
    capabilities: ['chat'],
    reasoning_effort: 'high',
    context_length: 128000,
    description: '',
  }
  modelModalVisible.value = true
}

function openEditModelModal(m: any) {
  editingModel.value = m
  modelForm.value = {
    id: m.id,
    name: m.name || m.id,
    provider_id: selectedProvider.value?.id || m.provider_id,
    capabilities: m.capabilities || ['chat'],
    reasoning_effort: m.reasoning_effort || 'high',
    context_length: m.context_length || 128000,
    description: m.description || '',
  }
  modelModalVisible.value = true
}

async function saveModelForm() {
  if (!selectedProvider.value) return
  try {
    const payload = {
      ...modelForm.value,
      provider_id: selectedProvider.value.id,
      provider_name: selectedProvider.value.name,
      base_url: selectedProvider.value.base_url,
      api_format: selectedProvider.value.api_format || 'openai_chat',
    }
    await api('/api/v1/admin/llm/models', {
      method: 'POST',
      body: JSON.stringify(payload),
    })
    modelModalVisible.value = false
    await loadConfig()
  } catch (err: any) {
    toast.err(err.message)
  }
}

async function activateModel(m: any) {
  try {
    await api('/api/v1/admin/llm/activate', {
      method: 'POST',
      body: JSON.stringify({
        model_id: m.id,
        provider_id: selectedProvider.value?.id || m.provider_id || 'custom',
        reasoning_effort: m.reasoning_effort || 'high',
      }),
    })
    await loadConfig()
  } catch (err: any) {
    toast.err(err.message)
  }
}

async function deleteSingleModel(m: any) {
  const pid = selectedProvider.value?.id
  const pname = selectedProvider.value?.name || pid || ''
  const _ok = await ask({
    title: t('admin.llm.confirmDeleteModelTitle'),
    desc: t('admin.llm.confirmDeleteModelDesc', undefined, { name: pname, id: m.id }),
    danger: true,
    okText: t('admin.llm.confirmDeleteOk'),
  })
  if (!_ok) return
  try {
    const url = pid
      ? `/api/v1/admin/llm/providers/${encodeURIComponent(pid)}/models/${encodeURIComponent(m.id)}`
      : `/api/v1/admin/llm/models/${encodeURIComponent(m.id)}`
    await api(url, {
      method: 'DELETE',
    })
    await loadConfig()
  } catch (err: any) {
    toast.err(err.message)
  }
}

// ----------------- Test Connection -----------------
async function testAllModels() {
  testAllLoading.value = true
  testAllResult.value = null
  cleanupResult.value = null
  try {
    testAllResult.value = await api('/api/v1/admin/llm/test-all', { method: 'POST' })
  } catch (e: any) {
    testAllResult.value = { rows: [], error: String(e?.message || e) }
  } finally {
    testAllLoading.value = false
  }
}

async function cleanupDeadModels() {
  cleanupLoading.value = true
  cleanupResult.value = null
  try {
    const res = await api('/api/v1/admin/llm/models/cleanup', { method: 'POST' })
    cleanupResult.value = res
    await loadConfig()
  } catch (e: any) {
    cleanupResult.value = { removed: [], failed: [{ model: '-', reason: String(e?.message || e) }] }
  } finally {
    cleanupLoading.value = false
  }
}

async function runTestModel(m: any) {
  testLoading.value = true
  testingModelId.value = m.id
  testResult.value = null
  try {
    const prov = selectedProvider.value || cfg.value?.providers?.find((p: any) => p.id === m.provider_id)
    testResult.value = await api('/api/v1/admin/llm/test', {
      method: 'POST',
      body: JSON.stringify({
        model: m.id,
        base_url: prov?.base_url || m.base_url,
        api_format: prov?.api_format || m.api_format || 'openai_chat',
        reasoning_effort: m.reasoning_effort || 'auto',
      }),
    })
  } catch (e: any) {
    testResult.value = { ok: false, error: e.message }
  } finally {
    testLoading.value = false
    testingModelId.value = null
  }
}

function toggleCapability(cap: string) {
  const caps = modelForm.value.capabilities
  const idx = caps.indexOf(cap)
  if (idx > -1) {
    caps.splice(idx, 1)
  } else {
    caps.push(cap)
  }
}

onMounted(() => {
  loadConfig()
  loadFailoverEvents()
  loadCacheStatus().catch(() => {})
})

  return {
    activateModel,
    availableEffortOptions,
    cfg,
    cfgError,
    clearCurrentProviderModels,
    currentView,
    customFetchKey,
    customFetchUrl,
    deleteSingleModel,
    detailTab,
    editingModel,
    executeRemoteFetch,
    failoverEvents,
    fallbackIds,
    fallbackOptions,
    fetchModalVisible,
    fetchingRemote,
    filteredProviders,
    filteredRemoteModels,
    goBackToList,
    importAllFilteredRemoteModels,
    importRemoteModel,
    loadConfig,
    loadFailoverEvents,
    loading,
    modelForm,
    modelModalVisible,
    modelNameOf,
    moveFallback,
    onApiFormatChange,
    openAddModelModal,
    openAddProviderModal,
    openEditModelModal,
    openFetchDialog,
    providerForm,
    remoteFetchResult,
    remoteSearch,
    removeProvider,
    requestAttemptsInput,
    reasoningEffortInput,
    runTestModel,
    saveGlobalSettings,
    saveModelForm,
    saveProviderConfig,
    savingSettings,
    searchQuery,
    selectProvider,
    selectedProvider,
    setPresetTimeout,
    settingsResult,
    showApiKey,
    testAllLoading,
    testAllModels,
    testAllResult,
    testLoading,
    testResult,
    testingModelId,
    cleanupDeadModels,
    cleanupLoading,
    cleanupResult,
    deadModelIds,
    healthOf,
    healthWarnings,
    modelHealth,
    providerHealth,
    thinkingTimeoutInput,
    toggleCapability,
    toggleFallback,
    toggleProviderQuick,
    // 2026 缓存效能与状态
    cacheStatus,
    cacheLoading,
    loadCacheStatus,
    clearL1Cache,
  }
}
