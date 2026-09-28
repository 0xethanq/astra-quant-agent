<script setup lang="ts">
/**
 * EvolutionPage.vue · 自进化与心法工位
 * ---------------------------------------------------------------------------
 * 骨架（推倒重来）：
 *   旧 = 页头 + 自绘标签栏 + 三张互不相干的面板堆叠
 *        （复盘报告卡 / 4 张总览卡 / 心法卡列表 / 模版卡列表）
 *        + 原生 prompt() 做"RUN EVOLUTION"确认
 *   新 = 共享 PageHeader（动作集中）→ `.seg` 标签栏
 *        → 复盘报告（统计行 + 裁定理由 + **洞见日志面板**）
 *        → 运行状态带（护栏 / 节律 / 心法规模 / 半衰期，发丝分隔单卡）
 *        → 心法库（单一面板内的行式清单，开关改 BaseSwitch）
 *        → 模版模块序列（单一面板内的可编辑行）
 *        → 立即复盘确认改 BaseDialog
 *
 * 后端契约（逐字未改）：
 *   GET  /api/v1/prompt-library        （失败回落 /api/v1/admin/prompt-library）
 *   GET  /api/v1/admin/memory
 *   GET  /api/v1/cache/self-improvement （失败忽略）
 *   POST /api/v1/admin/memory/toggle/{lessonId}?expected_version=…
 *   POST /api/v1/admin/memory/rollback?expected_version=…
 *   POST /api/v1/admin/memory   { text, expected_version }
 *   DELETE /api/v1/admin/memory/{idx}?lesson_id=…&expected_version=…
 *   PUT  /api/v1/admin/prompt-profiles/{id}  { name, description, pipelines }
 *   POST /api/v1/admin/gateway/jobs/self_improvement/run  { confirmation: 'RUN JOB' }
 *
 * ⚠️ 乐观并发纪律未动：任一次写失败都会把 `memoryVersion` 置空，
 *    后续写操作必须先显式「重新加载心法」（expectedMemoryVersion 会抛错）。
 */
import { fmtDateTime } from '../../utils/format';
import { resolveEvolutionStatus } from '../../utils/evolutionStatus';
import { useToast } from '../../composables/useToast';
import { useConfirm } from '../../composables/useConfirm';
const toast = useToast();
const { ask } = useConfirm();
import { ref, computed, onMounted } from 'vue';
import PageHeader from '../../components/admin/PageHeader.vue';
import BaseDialog from '../../components/base/BaseDialog.vue';
import BaseSwitch from '../../components/base/BaseSwitch.vue';
import BaseEmpty from '../../components/base/BaseEmpty.vue';
import { useI18n } from '../../composables/useI18n';
import { useRovingTabs } from '../../composables/useRovingTabs';
import { useApi } from '../../composables/useApi';
import { useAuthStore } from '../../stores/auth';
import { Brain, Sparkles, RefreshCw, Clock, Plus, Trash2, Save,
  PlayCircle, BookOpen, Sliders, Terminal, ShieldCheck, RotateCcw,
  Loader2, AlertTriangle } from 'lucide-vue-next';
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue';

const { api } = useApi();
const auth = useAuthStore();
const { t } = useI18n();

const loading = ref(true);
const loadError = ref('');
const busy = ref<'save' | 'run' | 'add' | 'delete' | 'toggle' | 'rollback' | ''>('');

// Pipelines state (evolution_system & evolution_user)
const activeTab = ref<'settings' | 'evolution_system' | 'evolution_user'>('settings');
const lib = ref<any>(null);
const selectedProfileId = ref('stable');
const workingModules = ref<any[]>([]);

// Structured White-Box Memory state
const structuredLessons = ref<any[]>([]);
const memoryVersion = ref<string | null>(null);
/** 结构化记忆是否启用（后端 legacy_read_only=False 表示走结构化 v1 护栏；缺失不猜） */
const memoryStructured = ref<boolean | null>(null);
const newMemoryText = ref('');
const evolutionReport = ref<any>(null);
const evolutionStartTime = ref('2026-09-01 00:00:00');
const activeTradesCount = ref<number | null>(null);
const savingStartTime = ref(false);

// 自进化独立模型配置
const evoConfig = ref<{
  model_id: string;
  effective_model_id: string;
  reasoning_effort: string;
  thinking_timeout: number;
  analysis_depth: string;
  available_models: Array<{
    id: string;
    name: string;
    provider_name: string;
    capabilities: string[];
    reasoning_effort: string;
    has_key: boolean;
  }>;
}>({
  model_id: 'auto',
  effective_model_id: 'auto',
  reasoning_effort: 'high',
  thinking_timeout: 300,
  analysis_depth: 'deep',
  available_models: [],
});
const savingEvoModel = ref(false);
const testingEvoModel = ref(false);
const testModelResult = ref<any>(null);

async function loadEvolutionConfig() {
  try {
    const res = await api<any>('/api/v1/admin/evolution/config');
    if (res?.evolution_start_time) {
      evolutionStartTime.value = res.evolution_start_time;
      activeTradesCount.value = res.active_trades_count ?? null;
    }
    if (res) {
      evoConfig.value.model_id = res.model_id || 'auto';
      evoConfig.value.effective_model_id = res.effective_model_id || 'auto';
      evoConfig.value.reasoning_effort = res.reasoning_effort || 'high';
      evoConfig.value.thinking_timeout = Number(res.thinking_timeout) || 300;
      evoConfig.value.analysis_depth = res.analysis_depth || 'deep';
      evoConfig.value.available_models = Array.isArray(res.available_models) ? res.available_models : [];
    }
  } catch {
    // ignore
  }
}

async function saveEvolutionModelConfig() {
  savingEvoModel.value = true;
  try {
    const res = await api<any>('/api/v1/admin/evolution/config', {
      method: 'PUT',
      body: JSON.stringify({
        model_id: evoConfig.value.model_id,
        reasoning_effort: evoConfig.value.reasoning_effort,
        thinking_timeout: evoConfig.value.thinking_timeout,
        analysis_depth: evoConfig.value.analysis_depth,
      }),
    });
    if (res?.effect) {
      toast.ok(res.effect);
    } else {
      toast.ok(t('admin.evolution.modelSaved'));
    }
    await loadEvolutionConfig();
  } catch (e: any) {
    toast.err(e.message);
  } finally {
    savingEvoModel.value = false;
  }
}

async function probeEvolutionModel() {
  testingEvoModel.value = true;
  testModelResult.value = null;
  try {
    const res = await api<any>('/api/v1/admin/evolution/test-model', {
      method: 'POST',
      body: JSON.stringify({
        model_id: evoConfig.value.model_id,
        reasoning_effort: evoConfig.value.reasoning_effort,
        thinking_timeout: 45,
      }),
    });
    testModelResult.value = res;
    if (res?.ok) {
      toast.ok(res.message || t('admin.evolution.testModelOk'));
    } else {
      toast.err(res?.message || t('admin.evolution.testModelFailed'));
    }
  } catch (e: any) {
    testModelResult.value = { ok: false, message: e.message };
    toast.err(e.message);
  } finally {
    testingEvoModel.value = false;
  }
}

async function saveEvolutionStartTime() {
  savingStartTime.value = true;
  try {
    const res = await api('/api/v1/admin/evolution/config', {
      method: 'PUT',
      body: JSON.stringify({ start_time: evolutionStartTime.value }),
    });
    activeTradesCount.value = res?.active_trades_count ?? null;
    toast.ok(t('admin.evolution.filterSaved', undefined, { time: evolutionStartTime.value, n: activeTradesCount.value ?? 0 }));
  } catch (e: any) {
    toast.err(e.message);
  } finally {
    savingStartTime.value = false;
  }
}

function setPresetStartTime(type: 'sep' | '7d' | '30d') {
  if (type === 'sep') {
    evolutionStartTime.value = '2026-09-01 00:00:00';
  } else {
    const d = new Date();
    const days = type === '7d' ? 7 : 30;
    d.setDate(d.getDate() - days);
    const y = d.getFullYear();
    const m = String(d.getMonth() + 1).padStart(2, '0');
    const day = String(d.getDate()).padStart(2, '0');
    evolutionStartTime.value = `${y}-${m}-${day} 00:00:00`;
  }
}

const selectedProfile = computed(() => (lib.value?.profiles || []).find((p: any) => p.id === selectedProfileId.value) || null);
const enabledLessonCount = computed(() => structuredLessons.value.filter((l: any) => l.enabled).length);
/** 正在删除的心法下标（仅用于按钮 loading 态） */
const deletingIdx = ref<number | null>(null);

type TabId = 'settings' | 'evolution_system' | 'evolution_user';
const tabs = computed<{ id: TabId; label: string; icon: any }[]>(() => [
  { id: 'settings', label: t('admin.evolution.tabOverview'), icon: Brain },
  { id: 'evolution_system', label: t('admin.evolution.tabSystem'), icon: BookOpen },
  { id: 'evolution_user', label: t('admin.evolution.tabUser'), icon: Terminal },
]);

async function loadData() {
  loading.value = true;
  loadError.value = '';
  memoryVersion.value = null;
  try {
    const [libRes, memRes, reportRes] = await Promise.all([
      api('/api/v1/prompt-library').catch(() => api('/api/v1/admin/prompt-library')),
      api('/api/v1/admin/memory'),
      api('/api/v1/cache/self-improvement').catch(() => null),
    ]);
    lib.value = libRes;
    selectedProfileId.value = libRes?.active_profile_id || 'stable';
    structuredLessons.value = memRes?.structured_lessons || [];
    memoryVersion.value = memRes?.version || null;
    memoryStructured.value = memRes && 'legacy_read_only' in memRes ? !memRes.legacy_read_only : null;
    evolutionReport.value = reportRes || null;
    loadEvolutionConfig();
    syncWorkingModules();
  } catch (e: any) {
    loadError.value = e.message;
    toast.err(t('admin.evolution.loadFailed', undefined, { msg: e.message }));
  } finally {
    loading.value = false;
  }
}

function syncWorkingModules() {
  if (activeTab.value === 'settings') return;
  const views = selectedProfile.value?.pipeline_views?.[activeTab.value] || [];
  workingModules.value = JSON.parse(JSON.stringify(views));
}

/* 批 66：标签栏的漫游 tabindex 与方向键导航。 */
const { setRef: setEvoTabRef, onKeydown: onEvoTabKey, roving: evoTabRoving } = useRovingTabs(
  () => tabs.value.length,
  (i) => { switchTab(tabs.value[i].id) },
)

function switchTab(tab: 'settings' | 'evolution_system' | 'evolution_user') {
  activeTab.value = tab;
  syncWorkingModules();
}

// Never retry writes: on failure require an explicit reload before another attempt.
function expectedMemoryVersion() {
  if (!memoryVersion.value) throw new Error(t('admin.evolution.reloadFirst'));
  return memoryVersion.value;
}

async function refreshMemory() {
  memoryVersion.value = null;
  const res = await api('/api/v1/admin/memory');
  structuredLessons.value = res.structured_lessons || [];
  memoryVersion.value = res.version || null;
  memoryStructured.value = 'legacy_read_only' in res ? !res.legacy_read_only : null;
}

async function reloadMemory() {
  if (busy.value || loading.value) return;
  loading.value = true;
  try {
    await refreshMemory();
  } catch (e: any) {
    toast.err(t('admin.evolution.reloadFailed', undefined, { msg: e.message }));
  } finally {
    loading.value = false;
  }
}

async function toggleLessonStatus(lessonId: string) {
  if (busy.value || loading.value) return;
  busy.value = 'toggle';
  try {
    await api(`/api/v1/admin/memory/toggle/${encodeURIComponent(lessonId)}?expected_version=${encodeURIComponent(expectedMemoryVersion())}`, { method: 'POST' });
    await refreshMemory();
    toast.ok(t('admin.evolution.toggleOk'));
  } catch (e: any) {
    memoryVersion.value = null;
    toast.err(t('admin.evolution.toggleFailed', undefined, { msg: e.message }));
  } finally {
    busy.value = '';
  }
}

async function rollbackToBaseline() {
  // 批C(2026-09-13)·破坏性操作收口：本操作清除非基准心法（含当日自进化成果），
  // 原生 confirm 在移动端易误触；改逐字短语确认。
  const _ok = await ask({
    title: t('admin.evolution.rollbackConfirmTitle'),
    desc: t('admin.evolution.rollbackConfirmDesc'),
    danger: true,
    confirmPhrase: 'ROLLBACK',
    okText: t('common.rollbackRun'),
  });
  if (!_ok) return;
  if (busy.value || loading.value) return;
  busy.value = 'rollback';
  try {
    await api(`/api/v1/admin/memory/rollback?expected_version=${encodeURIComponent(expectedMemoryVersion())}`, { method: 'POST' });
    await refreshMemory();
    toast.ok(t('admin.evolution.rollbackOk'));
  } catch (e: any) {
    memoryVersion.value = null;
    toast.err(t('admin.evolution.rollbackFailed', undefined, { msg: e.message }));
  } finally {
    busy.value = '';
  }
}

async function addMemoryItem() {
  const text = newMemoryText.value.trim();
  if (!text) return;
  if (busy.value || loading.value) return;
  busy.value = 'add';
  try {
    await api('/api/v1/admin/memory', {
      method: 'POST',
      body: JSON.stringify({ text, expected_version: expectedMemoryVersion() }),
    });
    // Reload full structured list
    await refreshMemory();
    newMemoryText.value = '';
    toast.ok(t('admin.evolution.addOk'));
  } catch (e: any) {
    memoryVersion.value = null;
    toast.err(t('admin.evolution.addFailed', undefined, { msg: e.message }));
  } finally {
    busy.value = '';
  }
}

async function deleteMemoryItem(idx: number, lessonId: string) {
  const _ok = await ask({
    title: t('admin.evolution.deleteConfirmTitle'),
    desc: t('admin.evolution.deleteConfirmDesc'),
    danger: true,
    okText: t('common.del'),
  });
  if (!_ok) return;
  if (busy.value || loading.value) return;
  busy.value = 'delete';
  deletingIdx.value = idx;
  try {
    await api(`/api/v1/admin/memory/${idx}?lesson_id=${encodeURIComponent(lessonId)}&expected_version=${encodeURIComponent(expectedMemoryVersion())}`, { method: 'DELETE' });
    await refreshMemory();
    toast.ok(t('admin.evolution.deleteOk'));
  } catch (e: any) {
    memoryVersion.value = null;
    toast.err(t('admin.evolution.deleteFailed', undefined, { msg: e.message }));
  } finally {
    busy.value = '';
    deletingIdx.value = null;
  }
}

async function savePipelineModules() {
  if (!selectedProfile.value) return;
  busy.value = 'save';
  try {
    const pipelinesMap: Record<string, any[]> = {}
    pipelinesMap[activeTab.value] = workingModules.value.map((m) => ({
      id: m.id,
      title: m.title,
      content: m.content,
      enabled: m.enabled,
      locked: m.locked,
      source: m.source,
    }));

    await api(`/api/v1/admin/prompt-profiles/${selectedProfile.value.id}`, {
      method: 'PUT',
      body: JSON.stringify({
        name: selectedProfile.value.name,
        description: selectedProfile.value.description,
        pipelines: pipelinesMap,
      }),
    })
    toast.ok(t('admin.evolution.layoutSaved'))
    await loadData()
  } catch (e: any) {
    toast.err(t('admin.evolution.saveFailed', undefined, { msg: e.message }))
  } finally {
    busy.value = ''
  }
}

/* ── 立即复盘：原生 prompt() → 对话框（确认短语校验与请求体逐字保留） ── */
const RUN_PHRASE = 'RUN EVOLUTION';
const runDialog = ref<{ open: boolean; phrase: string }>({ open: false, phrase: '' });
const runPhraseOk = computed(() => runDialog.value.phrase.trim().toUpperCase() === RUN_PHRASE);

function openRunDialog() {
  runDialog.value = { open: true, phrase: '' };
}
function closeRunDialog() {
  runDialog.value = { open: false, phrase: '' };
}

async function confirmRun() {
  const phrase = runDialog.value.phrase;
  // 与旧版等价：空输入视为取消
  if (!phrase) return;
  if (phrase.trim().toUpperCase() !== RUN_PHRASE) {
    toast.err(t('admin.evolution.phraseWrong'));
    closeRunDialog();
    return;
  }
  busy.value = 'run';
  try {
    const res = await api('/api/v1/admin/gateway/jobs/self_improvement/run', {
      method: 'POST',
      body: JSON.stringify({ confirmation: 'RUN JOB' }),
    });
    toast.ok(t('admin.evolution.runOk', undefined, { detail: res.detail || '' }));
    closeRunDialog();
    await loadData();
  } catch (e: any) {
    toast.err(t('admin.evolution.runFailed', undefined, { msg: e.message }));
  } finally {
    busy.value = '';
  }
}

function evoStatusBadgeClass(status?: string, error?: string): string {
  return resolveEvolutionStatus(status, error).adminBadgeClass;
}

onMounted(loadData);
</script>

<template>
  <div class="evo">
    <PageHeader :title="t('nav.admin.evolution')" :description="t('admin.evolution.desc')">
      <template #actions>
        <span class="dsh-pill">
          <span class="dsh-status-dot active" aria-hidden="true" />
          {{ t('admin.evolution.guardChip') }}
        </span>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="busy !== '' || loading" @click="reloadMemory">
          <RefreshCw :size="14" :class="loading && 'animate-spin shrink-0'" />
          <span>{{ t('admin.evolution.reloadMemory') }}</span>
        </button>
        <button type="button"
          v-if="auth.isSuperadmin"
          class="btn btn-ghost btn-sm"
          :disabled="busy !== ''"
          :title="t('admin.evolution.rollbackTitle')"
          @click="rollbackToBaseline"
        >
          <RotateCcw :size="14" />
          <span>{{ t('admin.evolution.rollback') }}</span>
        </button>
        <button type="button" v-if="auth.isSuperadmin" class="btn btn-primary btn-sm" :disabled="busy !== ''" @click="openRunDialog">
          <PlayCircle :size="14" />
          <span>{{ busy === 'run' ? t('admin.evolution.runningReview') : t('admin.evolution.reviewNow') }}</span>
        </button>
      </template>
    </PageHeader>

    <!-- 拉取失败 -->
    <div v-if="loadError" role="alert" class="state-block is-error">
      <span class="state-icon"><AlertTriangle :size="17" /></span>
      <p class="state-title">{{ t('common.loadFailed') }}</p>
      <p class="state-desc">{{ loadError }}</p>
      <button type="button" class="btn btn-ghost btn-sm mt-1" :disabled="loading" @click="loadData">
        <RefreshCw :size="14" :class="loading && 'animate-spin shrink-0'" />
        <span>{{ t('common.retry') }}</span>
      </button>
    </div>

    <template v-else>
      <!-- 标签栏 -->
      <div class="seg evo-tabs" role="tablist" :aria-label="t('admin.evolution.tabsLabel')">
        <button
          v-for="(tb, ti) in tabs"
          :key="tb.id"
          :ref="setEvoTabRef(ti)"
          type="button"
          role="tab"
          :aria-selected="activeTab === tb.id"
          :tabindex="evoTabRoving(activeTab === tb.id)"
          :class="{ 'seg-on': activeTab === tb.id }"
          @click="switchTab(tb.id)"
          @keydown="onEvoTabKey($event, ti)"
        >
          <component :is="tb.icon" :size="13" aria-hidden="true" />
          <span>{{ tb.label }}</span>
        </button>
      </div>

      <!-- ═══════ TAB 1 ═══════ -->
      <div v-if="activeTab === 'settings'" class="evo-tab">
        <!-- 复盘报告 -->
        <section v-if="evolutionReport" class="card">
          <header class="card-head">
            <div class="evo-rep-head">
              <h2 class="card-title"><Sparkles :size="14" />{{ t('admin.evolution.reportTitle') }}</h2>
              <span
                class="badge"
                :class="evoStatusBadgeClass(evolutionReport.change_status, evolutionReport.llm_error)"
              >
                {{ evolutionReport.change_status || 'NO_CHANGE' }}
              </span>
              <span v-if="evoConfig.effective_model_id" class="badge mono text-3xs">
                {{ t('admin.evolution.usedModel') }} {{ evoConfig.effective_model_id }}
              </span>
            </div>
            <span class="evo-rep-time mono">
              {{ t('admin.evolution.reviewTime') }} {{ fmtDateTime(evolutionReport.timestamp) }}
            </span>
          </header>

          <div class="evo-rep-stats">
            <div class="evo-rep-stat">
              <span class="label-caps">{{ t('admin.evolution.sampleCount') }}</span>
              <span class="evo-stat-v">{{ t('admin.evolution.closedTrades', undefined, { n: evolutionReport.total_trades }) }}</span>
            </div>
            <div class="evo-rep-stat">
              <span class="label-caps">{{ t('admin.evolution.winRate') }}</span>
              <span class="evo-stat-v num is-up">{{ evolutionReport.win_rate }}%</span>
            </div>
            <div class="evo-rep-stat">
              <span class="label-caps">{{ t('admin.evolution.profitFactor') }}</span>
              <span class="evo-stat-v num">{{ evolutionReport.profit_factor }}</span>
            </div>
            <div class="evo-rep-stat">
              <span class="label-caps">{{ t('admin.evolution.memoryGuard') }}</span>
              <span class="evo-stat-v" :class="evolutionReport.memory_preserved ? 'is-up' : 'is-warn'">
                {{ evolutionReport.memory_preserved ? t('admin.evolution.guardOn') : t('admin.evolution.guardRebuild') }}
              </span>
            </div>
          </div>

          <div v-if="evolutionReport.memory_overwrites_reason" class="evo-verdict">
            <span class="label-caps">{{ t('admin.evolution.verdictReason') }}</span>
            <p>{{ evolutionReport.memory_overwrites_reason }}</p>
          </div>

          <!-- 洞见日志面板 -->
          <div v-if="evolutionReport.insights && evolutionReport.insights.length" class="evo-insights">
            <span class="label-caps">
              {{ t('admin.evolution.insightsTitle', undefined, { n: evolutionReport.insights.length }) }}
            </span>
            <div class="log-panel is-flush evo-insight-panel">
              <div v-for="(ins, idx) in evolutionReport.insights" :key="idx" class="evo-insight">
                <span class="evo-insight-n mono">#{{ Number(idx) + 1 }}</span>
                <span class="evo-insight-text">{{ ins }}</span>
              </div>
            </div>
          </div>
        </section>

        <!-- 运行状态带 -->
        <section class="card band">
          <template v-if="loading">
            <BaseLoadingAnnounce />
            <div v-for="i in 4" :key="i" class="fact">
              <div class="skeleton skeleton-text" style="width: 48%" />
              <div class="skeleton skeleton-text skeleton-value" style="width: 66%" />
              <div class="skeleton skeleton-text" style="width: 34%" />
            </div>
          </template>

          <template v-else>
            <div class="fact">
              <span class="fact-label"><ShieldCheck :size="12" />{{ t('admin.evolution.guardrailStatus') }}</span>
              <span
                class="fact-value"
                :class="memoryStructured === false ? 'is-warn' : memoryStructured === true ? 'is-up' : ''"
              >
                {{ memoryStructured === true ? t('admin.evolution.guardrailActive')
                  : memoryStructured === false ? t('admin.evolution.guardrailLegacy')
                  : t('admin.evolution.unknown') }}
              </span>
              <span class="fact-foot">
                {{ memoryStructured === true ? t('admin.evolution.guardrailSub') : t('admin.evolution.guardrailSubLegacy') }}
              </span>
            </div>

            <div class="fact">
              <span class="fact-label"><Clock :size="12" />{{ t('admin.evolution.cadence') }}</span>
              <span class="fact-value">{{ t('admin.evolution.cadenceValue') }}</span>
              <span class="fact-foot mono">02:00, 08:00, 14:00, 20:00 (UTC+8)</span>
            </div>

            <div class="fact">
              <span class="fact-label"><Sliders :size="12" />{{ t('admin.evolution.currentLessons') }}</span>
              <span class="fact-value num">
                {{ enabledLessonCount }}<span class="fact-sub"> / {{ structuredLessons.length }}</span>
              </span>
              <span class="fact-foot">{{ t('admin.evolution.lessonsSub') }}</span>
            </div>

            <div class="fact">
              <span class="fact-label"><Sparkles :size="12" />{{ t('admin.evolution.halfLife') }}</span>
              <span class="fact-value">{{ t('admin.evolution.halfLifeValue') }}</span>
              <span class="fact-foot">{{ t('admin.evolution.halfLifeSub') }}</span>
            </div>
          </template>
        </section>

        <!-- 自进化专属推理引擎配置 -->
        <section class="card">
          <header class="card-head">
            <div>
              <h2 class="card-title"><Brain :size="14" />{{ t('admin.evolution.modelSectionTitle') }}</h2>
              <p class="card-sub">{{ t('admin.evolution.modelSectionDesc') }}</p>
            </div>
            <div class="flex items-center gap-2">
              <button
                type="button"
                class="btn btn-quiet btn-sm"
                :disabled="testingEvoModel || savingEvoModel"
                @click="probeEvolutionModel"
              >
                <Loader2 v-if="testingEvoModel" :size="14" class="animate-spin shrink-0" />
                <Terminal v-else :size="14" />
                <span>{{ testingEvoModel ? t('admin.evolution.testingModel') : t('admin.evolution.testModelBtn') }}</span>
              </button>
              <button
                type="button"
                class="btn btn-primary btn-sm"
                :disabled="savingEvoModel || testingEvoModel"
                @click="saveEvolutionModelConfig"
              >
                <Loader2 v-if="savingEvoModel" :size="14" class="animate-spin shrink-0" />
                <Save v-else :size="14" />
                <span>{{ savingEvoModel ? t('admin.evolution.savingModelConfig') : t('admin.evolution.saveModelConfig') }}</span>
              </button>
            </div>
          </header>

          <div class="space-y-4 p-4">
            <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
              <div class="space-y-1.5">
                <label class="label-caps">{{ t('admin.evolution.modelSelectLabel') }}</label>
                <select
                  v-model="evoConfig.model_id"
                  class="field text-xs mono"
                  :aria-label="t('admin.evolution.modelSelectAria')"
                >
                  <option value="auto">⚡ {{ t('admin.evolution.followMainBrain') }}</option>
                  <option
                    v-for="m in evoConfig.available_models"
                    :key="m.id"
                    :value="m.id"
                  >
                    {{ m.name }} · {{ m.provider_name }} ({{ m.reasoning_effort || 'high' }})
                  </option>
                </select>
                <p class="text-4xs text-[var(--ink-3)] font-mono">
                  {{ t('admin.evolution.effectiveModelTag') }} <b>{{ evoConfig.effective_model_id || 'auto' }}</b>
                </p>
              </div>

              <div class="space-y-1.5">
                <label class="label-caps">{{ t('admin.evolution.reasoningEffortLabel') }}</label>
                <select
                  v-model="evoConfig.reasoning_effort"
                  class="field text-xs"
                  :aria-label="t('admin.evolution.reasoningEffortLabel')"
                >
                  <option value="low">{{ t('admin.evolution.effortLow') }}</option>
                  <option value="medium">{{ t('admin.evolution.effortMed') }}</option>
                  <option value="high">{{ t('admin.evolution.effortHigh') }}</option>
                  <option value="max">{{ t('admin.evolution.effortMax') }}</option>
                </select>
              </div>
            </div>

            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 pt-1">
              <div class="space-y-1.5">
                <label class="label-caps">{{ t('admin.evolution.timeoutLabel') }} ({{ t('admin.evolution.timeoutUnit') }})</label>
                <input
                  v-model.number="evoConfig.thinking_timeout"
                  type="number"
                  inputmode="numeric"
                  min="60"
                  max="600"
                  step="30"
                  class="field num text-xs"
                  :aria-label="t('admin.evolution.timeoutLabel')"
                />
              </div>

              <div class="space-y-1.5">
                <label class="label-caps">{{ t('admin.evolution.depthLabel') }}</label>
                <select
                  v-model="evoConfig.analysis_depth"
                  class="field text-xs"
                  :aria-label="t('admin.evolution.depthLabel')"
                >
                  <option value="deep">{{ t('admin.evolution.depthDeep') }}</option>
                  <option value="standard">{{ t('admin.evolution.depthStandard') }}</option>
                </select>
              </div>
            </div>

            <div
              v-if="testModelResult"
              class="p-2.5 rounded text-xs"
              :class="testModelResult.ok ? 'bg-emerald-500/10 border border-emerald-500/20 text-emerald-400' : 'bg-rose-500/10 border border-rose-500/20 text-rose-400'"
            >
              <div class="flex items-center gap-1.5">
                <span class="font-medium">{{ testModelResult.message }}</span>
                <span v-if="testModelResult.reply_sample" class="ml-2 font-mono text-3xs text-[var(--ink-2)] truncate">
                  ↳ {{ testModelResult.reply_sample }}
                </span>
              </div>
            </div>
          </div>
        </section>

        <!-- 复盘样本时间范围过滤 -->
        <section class="card">
          <header class="card-head">
            <div>
              <h2 class="card-title"><Sliders :size="14" />{{ t('admin.evolution.filterTitle') }}</h2>
              <p class="card-sub">{{ t('admin.evolution.filterDesc') }}</p>
            </div>
            <span v-if="activeTradesCount !== null" class="badge">
              {{ t('admin.evolution.activeTrades', undefined, { n: activeTradesCount }) }}
            </span>
          </header>

          <div class="space-y-3 p-4">
            <div class="flex flex-wrap items-center gap-2">
              <label class="label-caps">{{ t('admin.evolution.startTimeLabel') }}</label>
              <div class="flex items-center gap-2 flex-1 min-w-[280px]">
                <input
                  v-model="evolutionStartTime"
                  type="text"
                  class="input mono flex-1"
                  :aria-label="t('admin.evolution.startTimeLabel')"
                  placeholder="2026-09-01 00:00:00"
                />
                <button
                  type="button"
                  class="btn btn-primary btn-sm"
                  :disabled="savingStartTime || !evolutionStartTime"
                  @click="saveEvolutionStartTime"
                >
                  <Loader2 v-if="savingStartTime" :size="14" class="animate-spin shrink-0" />
                  <Save v-else :size="14" />
                  <span>{{ t('admin.evolution.saveFilter') }}</span>
                </button>
              </div>
            </div>

            <!-- 快捷预设按钮 -->
            <div class="flex flex-wrap items-center gap-1.5 pt-1">
              <span class="text-3xs text-[var(--ink-3)] mr-1">{{ t('admin.evolution.quickPreset') }}</span>
              <button
                type="button"
                class="btn btn-ghost btn-sm"
                @click="setPresetStartTime('sep')"
              >
                {{ t('admin.evolution.presetSep') }}
              </button>
              <button
                type="button"
                class="btn btn-ghost btn-sm"
                @click="setPresetStartTime('7d')"
              >
                {{ t('admin.evolution.preset7d') }}
              </button>
              <button
                type="button"
                class="btn btn-ghost btn-sm"
                @click="setPresetStartTime('30d')"
              >
                {{ t('admin.evolution.preset30d') }}
              </button>
            </div>

            <p class="text-3xs text-[var(--ink-3)] leading-normal">
              {{ t('admin.evolution.startTimeHint') }}
            </p>
          </div>
        </section>

        <!-- 心法库 -->
        <section class="card">
          <header class="card-head">
            <div>
              <h2 class="card-title"><Brain :size="14" />{{ t('admin.evolution.lifecycle') }}</h2>
              <p class="card-sub">{{ t('admin.evolution.lifecycleHint') }}</p>
            </div>
          </header>

          <!-- 新增心法 -->
          <div class="evo-add">
            <input
              v-model="newMemoryText"
              :aria-label="t('admin.evolution.memoryInputAria')"
              class="field"
              :placeholder="t('admin.evolution.addPlaceholder')"
              @keydown.enter="addMemoryItem"
            />
            <button type="button"
              class="btn btn-primary btn-sm"
              :disabled="busy !== '' || !newMemoryText.trim()"
              @click="addMemoryItem"
            >
              <Plus :size="14" />
              <span>{{ busy === 'add' ? t('admin.evolution.auditing') : t('admin.evolution.submitReview') }}</span>
            </button>
          </div>

          <!-- 骨架 -->
          <div v-if="loading" class="evo-skel">
            <BaseLoadingAnnounce />
            <div v-for="i in 4" :key="i" class="skeleton skeleton-row" />
          </div>

          <!-- 空态 -->
          <BaseEmpty v-else-if="!structuredLessons.length" :text="t('admin.evolution.emptyLessons')" />

          <!-- 心法清单 -->
          <div v-else class="evo-lessons">
            <article
              v-for="(item, idx) in structuredLessons"
              :key="item.id || idx"
              class="evo-lesson"
              :class="{ 'is-off': !item.enabled }"
            >
              <div class="evo-lesson-head">
                <span class="badge" :class="item.is_baseline ? 'badge-accent' : 'badge-up'">
                  {{ item.is_baseline ? t('admin.evolution.baselineBadge') : t('admin.evolution.aiBadge') }}
                </span>
                <span class="badge">{{ item.category }}</span>
                <span class="badge badge-up mono">{{ t('admin.evolution.score') }} {{ item.health_score }}</span>

                <span class="evo-lesson-spacer" />

                <BaseSwitch
                  :model-value="item.enabled === true"
                  :disabled="busy !== '' || loading || !auth.isSuperadmin"
                  :label="`${item.category} · ${t('admin.evolution.score')} ${item.health_score}`"
                  @update:model-value="() => toggleLessonStatus(item.id)"
                />
                <button type="button"
                  class="btn btn-quiet btn-icon btn-sm evo-del"
                  :title="t('admin.evolution.removeTitle')"
                  :disabled="busy !== '' || loading || !auth.isSuperadmin"
                  @click="deleteMemoryItem(idx, item.id)"
                >
                  <Loader2 v-if="busy === 'delete' && deletingIdx === idx" :size="13" class="animate-spin shrink-0" />
                  <Trash2 v-else :size="13" />
                </button>
              </div>

              <p class="evo-lesson-text" :class="{ 'is-struck': !item.enabled }">{{ item.rule_text }}</p>

              <div class="evo-lesson-foot mono">
                <span>
                  {{ t('admin.evolution.createdAt') }} {{ fmtDateTime(item.created_at) }}
                  · {{ t('admin.evolution.sampleSupport') }}
                  {{ typeof item.sample_size === 'number' ? `${item.sample_size} ${t('admin.evolution.sampleUnit')}` : t('admin.evolution.unknown') }}
                </span>
                <span
                  class="evo-shield"
                  :class="{ 'is-up': typeof item.shield_status === 'string' && item.shield_status }"
                >
                  <ShieldCheck :size="12" />
                  {{ t('admin.evolution.shieldAudit') }}
                  {{ typeof item.shield_status === 'string' && item.shield_status ? item.shield_status : t('admin.evolution.unknown') }}
                </span>
              </div>
            </article>
          </div>
        </section>
      </div>

      <!-- ═══════ TAB 2 / 3 ═══════ -->
      <div v-else class="evo-tab">
        <section class="card">
          <header class="card-head">
            <div>
              <h2 class="card-title">
                {{ activeTab === 'evolution_system' ? t('admin.evolution.systemTitle') : t('admin.evolution.userTitle') }}
              </h2>
              <p class="card-sub">
                {{ activeTab === 'evolution_system' ? t('admin.evolution.systemDesc') : t('admin.evolution.userDesc') }}
              </p>
            </div>
            <button type="button"
              v-if="auth.isSuperadmin"
              class="btn btn-primary btn-sm"
              :disabled="busy !== ''"
              @click="savePipelineModules"
            >
              <Save :size="14" />
              <span>{{ busy === 'save' ? t('admin.evolution.saving') : t('admin.evolution.saveTemplate') }}</span>
            </button>
          </header>

          <div v-if="loading" class="evo-skel">
            <BaseLoadingAnnounce />
            <div v-for="i in 3" :key="i" class="skeleton skeleton-row" />
          </div>

          <BaseEmpty v-else-if="!workingModules.length" :text="t('common.noData')" />

          <div v-else class="evo-mods">
            <article v-for="(mod, mIdx) in workingModules" :key="mod.id || mIdx" class="evo-mod">
              <header class="evo-mod-head">
                <span class="evo-mod-n mono">#{{ mIdx + 1 }}</span>
                <span class="evo-mod-title truncate" :title="mod.title">{{ mod.title }}</span>
                <span v-if="mod.locked" class="badge" :title="t('admin.evolution.lockedBadge')">
                  {{ t('admin.evolution.lockedBadge') }}
                </span>
                <span class="evo-mod-spacer" />
                <BaseSwitch
                  :model-value="mod.enabled === true"
                  :disabled="!auth.isSuperadmin"
                  :label="mod.title"
                  @update:model-value="(v: boolean) => (mod.enabled = v)"
                />
                <span class="evo-mod-state">
                  {{ mod.enabled ? t('admin.evolution.moduleOn') : t('admin.evolution.moduleOff') }}
                </span>
              </header>

              <textarea
                v-model="mod.content"
                :disabled="!auth.isSuperadmin || mod.locked"
                :aria-label="t('admin.evolution.moduleContentAria')"
                rows="6"
                spellcheck="false"
                class="field evo-textarea"
                :placeholder="t('common.notConfigured')"
              />
            </article>
          </div>
        </section>
      </div>
    </template>

    <!-- ══ 立即复盘确认 ══ -->
    <BaseDialog
      :open="runDialog.open"
      :title="t('admin.evolution.runConfirmTitle')"
      :desc="t('admin.evolution.runConfirmDesc')"
      size="sm"
      initial-focus="input"
      @close="closeRunDialog"
    >
      <div v-if="evoConfig.effective_model_id" class="mb-3 p-2.5 rounded bg-[var(--surface-sunken)] border border-[var(--border-subtle)] text-xs space-y-1">
        <div class="flex items-center justify-between">
          <span class="text-[var(--ink-3)]">{{ t('admin.evolution.executingModel') }}</span>
          <span class="font-mono font-medium text-[var(--ink-1)]">{{ evoConfig.effective_model_id }}</span>
        </div>
        <div class="flex items-center justify-between">
          <span class="text-[var(--ink-3)]">{{ t('admin.evolution.timeoutLabel') }}</span>
          <span class="font-mono text-[var(--ink-2)]">{{ evoConfig.thinking_timeout }}s ({{ evoConfig.reasoning_effort }})</span>
        </div>
      </div>

      <label class="field-stack">
        <span class="form-label">{{ t('admin.evolution.runConfirmPhrase') }}</span>
        <code class="evo-phrase">{{ RUN_PHRASE }}</code>
        <input
          v-model="runDialog.phrase"
          type="text"
          class="field mono"
          autocomplete="off"
          spellcheck="false"
          :class="{ 'is-bad': !!runDialog.phrase && !runPhraseOk }"
          :aria-invalid="!!runDialog.phrase && !runPhraseOk ? 'true' : undefined"
          :placeholder="RUN_PHRASE"
          @keyup.enter="confirmRun"
        />
      </label>

      <template #footer>
        <button type="button" class="btn btn-ghost btn-sm" @click="closeRunDialog">{{ t('common.cancel') }}</button>
        <button type="button"
          class="btn btn-primary btn-sm"
          :disabled="!runPhraseOk || busy === 'run'"
          @click="confirmRun"
        >
          <Loader2 v-if="busy === 'run'" :size="14" class="animate-spin shrink-0" />
          <PlayCircle v-else :size="14" />
          <span>{{ t('admin.evolution.runConfirmSubmit') }}</span>
        </button>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.evo {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}
.evo-tabs {
  align-self: flex-start;
  /* 批 21：窄屏（<430px）标签条实测 428px 宽、且**没有任何裁剪或滚动祖先**，
     于是它把 .wb-main 整个撑出 64px，整页可以横向拖动。
     改为标签条自己在内部横向滚动，页面不再被撑宽。 */
  max-width: 100%;
  overflow-x: auto;
  scrollbar-width: none;
}
.evo-tabs::-webkit-scrollbar {
  display: none;
}
.evo-tabs button {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.evo-tab {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}

/* ══ 复盘报告 ══ */
.evo-rep-head {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.evo-rep-time {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
  white-space: nowrap;
}
.evo-rep-stats {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  border-bottom: 1px solid var(--ds-color-border-default);
}
@media (min-width: 900px) {
  .evo-rep-stats {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
.evo-rep-stat {
  display: flex;
  flex-direction: column;
  gap:4px;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-right: 1px solid var(--ds-color-border-default);
}
.evo-rep-stat:last-child {
  border-right: 0;
}
.evo-stat-v {
  font-size: var(--text-md);
  font-weight: 500;
  color: var(--ds-color-text-primary);
  font-variant-numeric: tabular-nums;
}
.evo-stat-v.is-up {
  color: var(--up);
}
.evo-stat-v.is-warn {
  color: var(--warn);
}
.evo-verdict {
  padding: var(--ds-space-3) var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
}
.evo-verdict p {
  margin-top: 4px;
  font-size: var(--text-xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-secondary);
}
.evo-insights {
  padding: var(--ds-space-3) var(--ds-space-4) var(--ds-space-4);
}
.evo-insight-panel {
  padding: 6px 0 0;
  max-height: 200px;
}
.evo-insight {
  display: grid;
  grid-template-columns: 30px minmax(0, 1fr);
  gap: var(--ds-space-2);
  padding: 2px 0;
  font-family: var(--ds-font-mono);
  font-size: var(--text-2xs);
  line-height: var(--leading-dense);
}
.evo-insight-n {
  color: var(--ds-color-brand);
}
.evo-insight-text {
  color: var(--ds-color-text-secondary);
  overflow-wrap: anywhere;
}

/* ══ 运行状态带 ══ */










/* ══ 心法库 ══ */
.evo-add {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface-inset);
}
.evo-add .field {
  flex: 1;
}
.evo-skel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: var(--ds-space-4);
}
.evo-lessons {
  display: flex;
  flex-direction: column;
}
.evo-lesson {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
  transition: background-color var(--dur-fast);
}
.evo-lesson:last-child {
  border-bottom: 0;
}
.evo-lesson:hover {
  background-color: var(--ds-color-bg-hover);
}
.evo-lesson.is-off {
  opacity: 0.6;
}
.evo-lesson-head {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.evo-lesson-spacer {
  flex: 1;
}
.evo-del {
  color: var(--down);
}
.evo-lesson-text {
  font-size: var(--text-xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-primary);
  overflow-wrap: anywhere;
}
.evo-lesson-text.is-struck {
  color: var(--ds-color-text-placeholder);
  text-decoration: line-through;
}
.evo-lesson-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-3);
  flex-wrap: wrap;
  padding-top: 6px;
  border-top: 1px solid var(--ds-color-border-default);
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.evo-shield {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}
.evo-shield.is-up {
  color: var(--up);
}

/* ══ 模版模块序列 ══ */
.evo-mods {
  display: flex;
  flex-direction: column;
}
.evo-mod {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
}
.evo-mod:last-child {
  border-bottom: 0;
}
.evo-mod-head {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  min-width: 0;
}
.evo-mod-n {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.evo-mod-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
  min-width: 0;
}
.evo-mod-spacer {
  flex: 1;
}
.evo-mod-state {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
  white-space: nowrap;
}
.evo-textarea {
  width: 100%;
  resize: vertical;
  line-height: var(--leading-body);
  font-family: var(--ds-font-mono);
  font-size: var(--text-2xs);
}

/* 复盘确认对话框 */

.evo-phrase {
  align-self: flex-start;
  padding:2px 8px;
  border-radius: var(--r-xs);
  background-color: var(--ds-color-bg-surface-1);
  font-family: var(--ds-font-mono);
  font-size: var(--text-3xs);
  color: var(--ds-color-text-primary);
}
</style>
