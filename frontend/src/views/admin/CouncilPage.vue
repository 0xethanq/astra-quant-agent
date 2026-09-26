<script setup lang="ts">
/**
 * CouncilPage.vue · 投委会工位
 * ---------------------------------------------------------------------------
 * 骨架（推倒重来）：
 *   旧 = 一张巨型控制卡（页头 + 3 张共识模式卡 + 超时行）
 *        + 每席位一张大卡（展开式手风琴）
 *        + 辩论实录（3 列顾问卡 + 3 列质询卡 + 6 张标的卡）
 *   新 = 共享 PageHeader → 议事状态带（4 项事实，含总开关）
 *        → 议事规则卡（共识模式 + 超时 + 阵容动作）
 *        → **席位列 / 席位编辑器 主从双栏**（替代逐席大卡手风琴）
 *        → 辩论实录：轮次分区 + CIO 裁定 + **六标的点位矩阵表**（替代 6 张卡）
 *
 * 对话框化：导入从「页内展开面板」改为 BaseDialog；总开关改用 BaseSwitch。
 * 三态：首屏骨架 · 无席位空态 · 载入失败（可重试）
 *
 * 后端契约（逐字未改）：
 *   GET  /api/v1/admin/council/config        GET  /api/v1/admin/llm/models
 *   PUT  /api/v1/admin/council/config        { buildCouncilSavePayload(cfg) }
 *   POST /api/v1/admin/council/apply-suite   { suite_id }
 *   POST /api/v1/admin/council/reset-role    { role_id }
 *   POST /api/v1/admin/council/test          {}
 *   GET  /api/v1/admin/council/export
 *   POST /api/v1/admin/council/import        { buildCouncilImportPayload(parsed) }
 *
 * ⚠️ 配色：本页**不再使用** councilLogic.roleColorOf / ROLE_COLORS 的五色轮盘
 *    （绿/琥珀/青/紫/蓝 —— 与「单一强调色 + 语义色」的工作台语言冲突）。
 *    新设计改为中性席位牌 + CIO 走品牌强调色。该模块与其 mjs 契约测试
 *    （frontend/tests/councilLogic.test.mjs 钉住了配色字符串）**未被改动**。
 */
import { fmtDate } from '../../utils/format';
import { useToast } from '../../composables/useToast';
import { useConfirm } from '../../composables/useConfirm';
const toast = useToast();
const { ask } = useConfirm();
import { computed, ref, onMounted } from 'vue';
import PageHeader from '../../components/admin/PageHeader.vue';
import BaseSwitch from '../../components/base/BaseSwitch.vue';
import BaseDialog from '../../components/base/BaseDialog.vue';
import { useI18n } from '../../composables/useI18n';
import { useApi } from '../../composables/useApi';
import { useAuthStore } from '../../stores/auth';
import {
  CONSENSUS_MODES,
  DATA_SLOTS,
  buildCouncilImportPayload,
  buildCouncilSavePayload,
  isBuiltinTrader,
  isCioSeat,
  isModelMissing,
  nextExpandedRole,
  roleDisplayName,
  roleIconKeyOf,
  roleIdOf,
  roleTitleOf,
} from './council/councilLogic';
import { Users,
  Shield,
  Zap,
  Cpu,
  Save,
  RotateCcw,
  Play,
  Plus,
  Trash2,
  CheckCircle2,
  ChevronRight,
  AlertTriangle,
  Sliders,
  Download,
  Upload,
  Loader2,
  Scale,
  Clock } from 'lucide-vue-next';
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue';

const { api } = useApi();
const auth = useAuthStore();
const { t } = useI18n();

const loading = ref(true);
const saving = ref(false);
const testing = ref(false);
const loadError = ref('');

const councilConfig = ref<any>({
  enabled: false,
  consensus_mode: 'standard',
  timeout_seconds: 240.0,
  roles: {},
});

const availableSuites = ref<any[]>([]);
const availableModels = ref<any[]>([]);
/** 审计 P1-4b：席位绑定的 model_id 不在模型库 → 后端会静默回落主脑，UI 必须说出来 */
function modelMissing(role: any): boolean {
  return isModelMissing(role, availableModels.value);
}
/** 当前选中的席位（原 `expandedRole`；加载时经 nextExpandedRole 回落） */
const expandedRole = ref<string>('trader_trend');
const testResult = ref<any>(null);
const expandedReasoning = ref<Record<string, boolean>>({});

/** 图标表：键由 councilLogic.roleIconKeyOf() 决定（未知席位 → 'custom'）。 */
const roleIcons: Record<string, any> = {
  trader_trend: Shield,
  trader_momentum: Zap,
  trader_quant: Cpu,
  cio: Users,
  custom: Sliders,
};

/* ── 派生视图状态 ── */
const seatEntries = computed<[string, any][]>(
  () => Object.entries(councilConfig.value.roles || {}) as [string, any][],
);
const traderCount = computed(
  () => seatEntries.value.filter(([id, r]) => !isCioSeat(r, id)).length,
);
const selectedRole = computed<any>(() => councilConfig.value.roles?.[expandedRole.value] || null);
/**
 * 议事模式的展示文案（批 40）。
 *
 * 缺陷：模式卡与 HUD 此前直接渲染 `CONSENSUS_MODES` 里的中文 `name/tag/desc`，
 * 英文界面因此显示「标准提案模式 / 交叉质询模式」。locale 里 `modeStandard*`、
 * `modeCross*` 六个键只有 `modeStandardName` 被当作回落文案用到，其余无人用，
 * 且文案与常量已经分叉 —— 两份真源。
 *
 * 修法：查表取**完整键路径**（不使用拼接键名，拼接键无法被 i18n 静态校验识别），
 * 缺键时回落到常量原值；未登记的 id 原样透出。
 */
const MODE_TEXT_KEY: Record<string, { name: string; tag: string; desc: string }> = {
  standard: {
    name: 'admin.council.modeStandardName',
    tag: 'admin.council.modeStandardTag',
    desc: 'admin.council.modeStandardDesc',
  },
  cross_examination: {
    name: 'admin.council.modeCrossName',
    tag: 'admin.council.modeCrossTag',
    desc: 'admin.council.modeCrossDesc',
  },
  debate: {
    name: 'admin.council.modeDebateName',
    tag: 'admin.council.modeDebateTag',
    desc: 'admin.council.modeDebateDesc',
  },
};
function modeNameOf(mode: any): string {
  const k = MODE_TEXT_KEY[String(mode?.id ?? '')];
  return k ? t(k.name, mode?.name) : String(mode?.name ?? '--');
}
function modeTagOf(mode: any): string {
  const k = MODE_TEXT_KEY[String(mode?.id ?? '')];
  return k ? t(k.tag, mode?.tag) : String(mode?.tag ?? '--');
}
function modeDescOf(mode: any): string {
  const k = MODE_TEXT_KEY[String(mode?.id ?? '')];
  return k ? t(k.desc, mode?.desc) : String(mode?.desc ?? '--');
}
function consensusModeLabel(modeId: string): string {
  const found = CONSENSUS_MODES.find((m) => m.id === modeId);
  return found ? modeNameOf(found) : t('admin.council.modeStandardName');
}
const consensusName = computed(() => consensusModeLabel(councilConfig.value.consensus_mode));
const consensusTag = computed(() => {
  const found = CONSENSUS_MODES.find((m) => m.id === councilConfig.value.consensus_mode);
  return found ? modeTagOf(found) : '--';
});

/** 席位牌着色：CIO 走强调色，静音席位降一档，其余中性 */
function seatTone(roleId: string, role: any): string {
  if (isCioSeat(role, roleId)) return 'is-cio';
  if (role?.enabled === false) return 'is-muted';
  return '';
}

async function loadData() {
  loading.value = true;
  loadError.value = '';
  try {
    const [cRes, mRes] = await Promise.all([
      api('/api/v1/admin/council/config'),
      api('/api/v1/admin/llm/models'),
    ]);
    councilConfig.value = cRes;
    availableSuites.value = cRes.available_suites || [];
    availableModels.value = mRes.models || [];
    expandedRole.value = nextExpandedRole(Object.keys(cRes.roles || {}), expandedRole.value);
  } catch (e: any) {
    loadError.value = e.message;
    toast.err(t('admin.council.loadFailed', undefined, { msg: e.message }));
  } finally {
    loading.value = false;
  }
}

async function saveConfig() {
  if (!auth.isSuperadmin) {
    toast.err(t('admin.council.superadminOnly'));
    return;
  }
  saving.value = true;
  try {
    const res = await api('/api/v1/admin/council/config', {
      method: 'PUT',
      body: JSON.stringify(buildCouncilSavePayload(councilConfig.value)),
    });
    councilConfig.value = res.config;
    toast.ok(
      councilConfig.value.enabled
        ? t('admin.council.saveOkConsensus', undefined, {
            mode: consensusModeLabel(councilConfig.value.consensus_mode),
          })
        : t('admin.council.saveOkDirect'),
    );
  } catch (e: any) {
    toast.err(t('admin.council.saveFailed', undefined, { msg: e.message }));
  } finally {
    saving.value = false;
  }
}

// ===== 投委会配置导入 / 导出（对齐提示词工坊策略包体验） =====
const importVisible = ref(false);
const importRawJson = ref('');
const importFileError = ref('');
const importing = ref(false);

async function exportConfig() {
  try {
    const res = await api('/api/v1/admin/council/export');
    const blob = new Blob([JSON.stringify(res, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `astra-council-config-${fmtDate(new Date())}.json`;
    a.click();
    URL.revokeObjectURL(url);
    toast.ok(t('admin.council.exportOk'));
  } catch (e: any) {
    toast.err(t('admin.council.exportFailed', undefined, { msg: e.message }));
  }
}

function pickImportFile(ev: Event) {
  const file = (ev.target as HTMLInputElement).files?.[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = () => {
    importRawJson.value = String(reader.result || '');
    importFileError.value = '';
  };
  reader.onerror = () => { importFileError.value = t('admin.council.importReadFileFailed'); };
  reader.readAsText(file);
}

function closeImport() {
  importVisible.value = false;
  importRawJson.value = '';
  importFileError.value = '';
}

async function doImportConfig() {
  importFileError.value = '';
  let payload: any;
  try {
    payload = JSON.parse(importRawJson.value);
  } catch {
    importFileError.value = t('admin.council.importJsonInvalid');
    return;
  }
  importing.value = true;
  try {
    const res = await api('/api/v1/admin/council/import', {
      method: 'POST',
      body: JSON.stringify(buildCouncilImportPayload(payload)),
    });
    await loadData();
    closeImport();
    const roles = (res.roles || []).join(' / ');
    const backup = res.backup_file
      ? t('admin.council.importOkBackup', undefined, { file: res.backup_file })
      : '';
    toast.ok(t('admin.council.importOk', undefined, { roles }) + backup);
  } catch (e: any) {
    importFileError.value = t('admin.council.importFailed', undefined, { msg: e.message });
  } finally {
    importing.value = false;
  }
}

async function applySuite(suiteId: string) {
  if (!auth.isSuperadmin) return;
  const _ok = await ask({ title: t('admin.council.confirmLoadTitle'), desc: t('admin.council.confirmLoadDesc'), danger: true, okText: t('common.load') });
  if (!_ok) return;
  try {
    const res = await api('/api/v1/admin/council/apply-suite', {
      method: 'POST',
      body: JSON.stringify({ suite_id: suiteId }),
    });
    councilConfig.value = res.config;
    toast.ok(t('admin.council.suiteLoaded'));
  } catch (e: any) {
    toast.err(t('admin.council.suiteFailed', undefined, { msg: e.message }));
  }
}

function addNewCustomTrader() {
  if (!auth.isSuperadmin) return;
  const roleId = roleIdOf();
  councilConfig.value.roles[roleId] = {
    id: roleId,
    name: t('admin.council.customTraderName'),
    role_title: t('admin.council.customTraderRoleTitle'),
    description: t('admin.council.customTraderDesc'),
    prompt:
      '【角色：自定义资深交易员】\n' +
      '你作为对冲基金交易台的一线交易员，请核验账户可用资金、现有持仓与挂单，并对 6 大标的输出你的实战作战提案：\n' +
      '1. 现有持仓与挂单：逐一给出 HOLD/CLOSE_MARKET 或 CANCEL/KEEP 建议。\n' +
      '2. 作战提案：对 6 大币种逐一给出明确方向、限价、止损、止盈与拟用保证金。\n' +
      '3. 指出同行方案中的致命风险漏洞（50字内/币种）。',
    weight: 0.3,
    enabled: true,
    reasoning_effort: 'medium',
    temperature: 0.2,
    is_arbitrator: false,
    model_id: '',
  };
  expandedRole.value = roleId;
  toast.ok(t('admin.council.addedCustom'));
}

async function removeRole(roleId: string) {
  if (!auth.isSuperadmin) return;
  const role = councilConfig.value.roles[roleId];
  if (isCioSeat(role, roleId)) {
    toast.warn(t('admin.council.cioUndeletable'));
    return;
  }
  const _ok = await ask({ title: t('admin.council.confirmRemoveTitle'), desc: t('admin.council.confirmRemoveDesc', undefined, { name: roleDisplayName(role, roleId) }), danger: true, okText: t('common.remove') });
  if (!_ok) return;
  delete councilConfig.value.roles[roleId];
  expandedRole.value = nextExpandedRole(Object.keys(councilConfig.value.roles || {}), '');
  toast.warn(t('admin.council.removedSeat'));
}

async function resetRole(roleId: string) {
  const _ok = await ask({ title: t('admin.council.confirmRestoreTitle'), desc: t('admin.council.confirmRestoreDesc', undefined, { name: roleDisplayName(councilConfig.value.roles[roleId], roleId) }), danger: true, okText: t('common.restore') });
  if (!_ok) return;
  try {
    const res = await api('/api/v1/admin/council/reset-role', {
      method: 'POST',
      body: JSON.stringify({ role_id: roleId }),
    });
    councilConfig.value = res.config;
    toast.ok(t('admin.council.resetOk'));
  } catch (e: any) {
    toast.err(t('admin.council.resetFailed', undefined, { msg: e.message }));
  }
}

async function runDebateTest() {
  testing.value = true;
  testResult.value = null;
  expandedReasoning.value = {};
  toast.warn(t('admin.council.testRunning'));
  try {
    const res = await api('/api/v1/admin/council/test', {
      method: 'POST',
      body: JSON.stringify({}),
    });
    if (res.status === 'ok') {
      testResult.value = res;
      toast.ok(t('admin.council.testOk', undefined, { ms: res.transcript?.total_duration_ms || 0 }));
    } else {
      toast.err(t('admin.council.testFailed', undefined, { msg: res.error || t('admin.council.unknownError') }));
    }
  } catch (e: any) {
    toast.err(t('admin.council.testError', undefined, { msg: e.message }));
  } finally {
    testing.value = false;
  }
}

/* ── 六标的落盘点位矩阵（把旧版 6 张卡摊成一张表） ── */
const matrixRows = computed<[string, any][]>(() => {
  const dec = testResult.value?.brain_output?.decisions;
  return dec ? (Object.entries(dec) as [string, any][]) : [];
});

function adoptedLabel(dec: any): string {
  if (!dec?.adopted_role) return '--';
  if (dec.adopted_role === 'REJECT_ALL') return t('admin.council.rejectAll');
  return t('admin.council.adoptFrom', undefined, {
    name: councilConfig.value.roles?.[dec.adopted_role]?.name || dec.adopted_role,
  });
}
function actionTone(action: string): string {
  if (action?.includes('BUY')) return 'badge-up';
  if (action?.includes('SELL')) return 'badge-down';
  return '';
}
function priceOf(dec: any): string {
  return dec?.limit_price || dec?.entry_price || '--';
}

onMounted(loadData);
</script>

<template>
  <div class="cn">
    <PageHeader :title="t('nav.admin.council')" :description="t('admin.council.desc')">
      <template #actions>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="!auth.isSuperadmin" @click="exportConfig">
          <Download :size="14" />
          <span>{{ t('admin.council.export') }}</span>
        </button>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="!auth.isSuperadmin" @click="importVisible = true">
          <Upload :size="14" />
          <span>{{ t('admin.council.import') }}</span>
        </button>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="testing || !auth.isSuperadmin" @click="runDebateTest">
          <Play :size="14" />
          <span>{{ testing ? t('admin.council.testing') : t('admin.council.runTest') }}</span>
        </button>
        <button type="button" class="btn btn-primary btn-sm" :disabled="saving || !auth.isSuperadmin" @click="saveConfig">
          <Save :size="14" />
          <span>{{ saving ? t('admin.council.saving') : t('admin.council.save') }}</span>
        </button>
      </template>
    </PageHeader>

    <!-- 载入失败 -->
    <div v-if="loadError" role="alert" class="state-block is-error">
      <span class="state-icon"><AlertTriangle :size="17" /></span>
      <p class="state-title">{{ t('common.loadFailed') }}</p>
      <p class="state-desc">{{ loadError || t('common.networkError') }}</p>
      <button type="button" class="btn btn-ghost btn-sm mt-1" :disabled="loading" @click="loadData">
        <Loader2 v-if="loading" :size="14" class="animate-spin shrink-0" />
        <RotateCcw v-else :size="14" />
        <span>{{ t('common.retry') }}</span>
      </button>
    </div>

    <template v-else>
      <!-- ══ 议事状态带 ══ -->
      <section class="card band">
        <template v-if="loading">
          <BaseLoadingAnnounce />
          <div v-for="i in 4" :key="i" class="fact">
            <div class="skeleton skeleton-text" style="width: 48%" />
            <div class="skeleton skeleton-text skeleton-value" style="width: 68%" />
            <div class="skeleton skeleton-text" style="width: 36%" />
          </div>
        </template>

        <template v-else>
          <!-- 总开关 -->
          <div class="fact">
            <span class="fact-label"><Scale :size="12" />{{ t('admin.council.bandStatus') }}</span>
            <span class="fact-value" :class="councilConfig.enabled ? 'is-up' : ''">
              {{ councilConfig.enabled ? t('admin.council.chipInSession') : t('admin.council.chipDirect') }}
            </span>
            <span class="fact-foot">
              <BaseSwitch
                v-model="councilConfig.enabled"
                :disabled="!auth.isSuperadmin"
                :label="t('admin.council.bandStatus')"
              />
              <span>{{ councilConfig.enabled ? t('admin.council.enabledOn') : t('admin.council.enabledOff') }}</span>
            </span>
          </div>

          <div class="fact">
            <span class="fact-label"><Users :size="12" />{{ t('admin.council.consensusLabel') }}</span>
            <span class="fact-value truncate">{{ consensusName }}</span>
            <span class="fact-foot mono">
              {{ consensusTag }}
            </span>
          </div>

          <div class="fact">
            <span class="fact-label"><Clock :size="12" />{{ t('admin.council.fieldTimeout') }}</span>
            <span class="fact-value num">{{ councilConfig.timeout_seconds }}<span class="fact-sub">s</span></span>
            <span class="fact-foot">{{ t('admin.council.timeoutFoot') }}</span>
          </div>

          <div class="fact">
            <span class="fact-label"><Shield :size="12" />{{ t('admin.council.bandSeats') }}</span>
            <span class="fact-value num">{{ seatEntries.length }}</span>
            <span class="fact-foot">{{ t('admin.council.bandSeatsFoot', undefined, { n: traderCount }) }}</span>
          </div>
        </template>
      </section>

      <!-- ══ 议事规则 ══ -->
      <section class="card">
        <header class="card-head">
          <div>
            <h2 class="card-title">{{ t('admin.council.consensusLabel') }}</h2>
            <p class="card-sub">{{ t('admin.council.timeoutHint') }}</p>
          </div>
          <div class="cn-head-actions">
            <button type="button" class="btn btn-ghost btn-sm" :disabled="!auth.isSuperadmin" @click="applySuite('hedge_fund_desk')">
              <RotateCcw :size="14" />
              <span>{{ t('admin.council.restoreSuite') }}</span>
            </button>
            <button type="button" class="btn btn-ghost btn-sm" :disabled="!auth.isSuperadmin" @click="addNewCustomTrader">
              <Plus :size="14" />
              <span>{{ t('admin.council.addTrader') }}</span>
            </button>
          </div>
        </header>

        <div class="cn-modes">
          <button type="button"
            v-for="mode in CONSENSUS_MODES"
            :key="mode.id"
            class="cn-mode"
            :class="{ 'is-on': councilConfig.consensus_mode === mode.id }"
            :disabled="!auth.isSuperadmin"
            @click="councilConfig.consensus_mode = mode.id"
          >
            <span class="cn-mode-top">
              <span class="cn-mode-name">{{ modeNameOf(mode) }}</span>
              <span class="badge">{{ modeTagOf(mode) }}</span>
            </span>
            <span class="cn-mode-desc">{{ modeDescOf(mode) }}</span>
          </button>
        </div>

        <div class="cn-rules-foot">
          <label class="cn-inline">
            <span class="label-caps">{{ t('admin.council.fieldTimeout') }}</span>
            <input
              v-model="councilConfig.timeout_seconds"
              type="number"
              inputmode="numeric"
              :min="30"
              :max="420"
              step="10"
              class="field cn-num-input"
              :disabled="!auth.isSuperadmin"
            />
            <span class="cn-unit">s</span>
          </label>
          <span class="cn-foot-hint">{{ t('admin.council.unsavedHint') }}</span>
        </div>
      </section>

      <!-- ══ 席位列 / 编辑器 ══ -->
      <div class="cn-split">
        <!-- 席位列 -->
        <aside class="card cn-seatlist">
          <header class="card-head">
            <h2 class="card-title">{{ t('admin.council.seatsTitle') }}</h2>
            <span class="badge">{{ t('admin.council.seatsCount', undefined, { n: seatEntries.length }) }}</span>
          </header>

          <div v-if="loading" class="cn-seats">
            <BaseLoadingAnnounce />
            <div v-for="i in 4" :key="i" class="cn-seat">
              <span class="skeleton skeleton-avatar" />
              <span class="skeleton skeleton-text" style="flex: 1" />
            </div>
          </div>

          <BaseEmpty v-else-if="!seatEntries.length" :text="t('admin.council.noSeats')" />

          <div v-else class="cn-seats">
            <button type="button"
              v-for="[roleId, role] in seatEntries"
              :key="roleId"
              class="cn-seat"
              :class="{ 'is-on': expandedRole === roleId }"
              @click="expandedRole = String(roleId)"
            >
              <span class="icon-box cn-avatar" :class="seatTone(String(roleId), role)">
                <component :is="roleIcons[roleIconKeyOf(String(roleId))]" :size="14" />
              </span>
              <span class="cn-seat-text">
                <span class="cn-seat-name truncate" :title="role.name || String(roleId)">{{ role.name || roleId }}</span>
                <span
                  class="cn-seat-sub truncate"
                  :title="roleTitleOf(role, isCioSeat(role, String(roleId)) ? t('admin.council.cioTitle') : t('admin.council.seniorTrader'))"
                >
                  {{ roleTitleOf(role, isCioSeat(role, String(roleId)) ? t('admin.council.cioTitle') : t('admin.council.seniorTrader')) }}
                </span>
              </span>
              <span v-if="isCioSeat(role, String(roleId))" class="badge badge-accent">
                {{ t('admin.council.cioTitle') }}
              </span>
              <span v-else class="cn-seat-w num">{{ role.weight }}</span>
              <ChevronRight :size="13" class="cn-seat-arrow" />
            </button>
          </div>
        </aside>

        <!-- 席位编辑器 -->
        <section class="card cn-editor">
          <BaseEmpty v-if="!selectedRole" :text="t('admin.council.editorEmpty')" />

          <template v-else>
            <header class="card-head">
              <div class="cn-editor-id">
                <span class="icon-box cn-avatar is-lg" :class="seatTone(expandedRole, selectedRole)">
                  <component :is="roleIcons[roleIconKeyOf(expandedRole)]" :size="16" />
                </span>
                <div class="cn-editor-text">
                  <input
                    v-model="selectedRole.name"
                    :aria-label="t('admin.council.seatNamePlaceholder')"
                    class="cn-name-input"
                    :readonly="!auth.isSuperadmin"
                    :placeholder="t('admin.council.seatNamePlaceholder')"
                  />
                  <span class="cn-editor-sub">
                    {{ roleTitleOf(selectedRole, isCioSeat(selectedRole, expandedRole) ? t('admin.council.cioTitle') : t('admin.council.seniorTrader')) }}
                    <template v-if="isCioSeat(selectedRole, expandedRole)"> · {{ t('admin.council.arbitratorBadge') }}</template>
                  </span>
                </div>
              </div>

              <div class="cn-editor-head-right">
                <span
                  class="badge"
                  :class="isCioSeat(selectedRole, expandedRole) ? 'badge-accent' : (selectedRole.enabled !== false ? 'badge-up' : '')"
                >
                  {{ isCioSeat(selectedRole, expandedRole)
                    ? t('admin.council.arbitratorBadge')
                    : (selectedRole.enabled !== false ? t('admin.council.seatActive') : t('admin.council.seatMuted')) }}
                </span>
                <button type="button"
                  v-if="!isCioSeat(selectedRole, expandedRole) && !isBuiltinTrader(expandedRole)"
                  class="btn btn-danger btn-sm"
                  :disabled="!auth.isSuperadmin"
                  :title="t('admin.council.removeSeatTitle')"
                  @click="removeRole(expandedRole)"
                >
                  <Trash2 :size="13" />
                  <span>{{ t('common.del') }}</span>
                </button>
              </div>
            </header>

            <p class="cn-desc">
              {{ selectedRole.description || t('admin.council.seatDescFallback') }}
            </p>
            <p v-if="modelMissing(selectedRole)" class="cn-warn">
              <AlertTriangle :size="13" />
              <span>{{ t('admin.council.modelMissingHint') }}</span>
            </p>

            <!-- 运行参数 -->
            <div class="cn-params">
              <h3 class="cn-section-title">{{ t('admin.council.paramsTitle') }}</h3>
              <div class="cn-param-grid">
                <label class="cn-param">
                  <span class="label-caps">{{ t('admin.council.fieldModel') }}</span>
                  <select
                    v-model="selectedRole.model_id"
                    class="field"
                    :class="{ 'is-warn': modelMissing(selectedRole) }"
                    :aria-invalid="modelMissing(selectedRole) ? 'true' : undefined"
                    :aria-label="t('admin.council.fieldModel')"
                    :disabled="!auth.isSuperadmin"
                  >
                    <option value="">{{ t('admin.council.inheritGlobalBrain') }}</option>
                    <!-- 审计 P1-4b：席位绑了模型库里没有的 id 时，旧下拉会显示成空白（等于骗人）；
                         这里保留原值并显式标注"未登记 · 实际由主脑代答"。 -->
                    <option v-if="modelMissing(selectedRole)" :value="selectedRole.model_id" disabled>
                      {{ selectedRole.model_id }} · {{ t('admin.council.modelMissing') }}
                    </option>
                    <option v-for="m in availableModels" :key="m.id" :value="m.id">
                      {{ m.name || m.id }}
                    </option>
                  </select>
                </label>

                <label v-if="!isCioSeat(selectedRole, expandedRole)" class="cn-param">
                  <span class="label-caps" :title="t('admin.council.weightHint')">{{ t('admin.council.fieldWeight') }}</span>
                  <input
                    v-model="selectedRole.weight"
                    type="number"
                    inputmode="decimal"
                    step="0.05"
                    min="0.1"
                    max="1.0"
                    class="field"
                    :disabled="!auth.isSuperadmin"
                  />
                </label>

                <label class="cn-param">
                  <span class="label-caps">{{ t('admin.council.fieldTemperature') }}</span>
                  <input
                    v-model="selectedRole.temperature"
                    type="number"
                    inputmode="decimal"
                    step="0.05"
                    min="0.0"
                    max="1.0"
                    class="field"
                    :disabled="!auth.isSuperadmin"
                  />
                  <span class="cn-param-hint">{{ t('admin.council.temperatureHint') }}</span>
                </label>

                <div v-if="!isCioSeat(selectedRole, expandedRole)" class="cn-param">
                  <span class="label-caps">{{ t('admin.council.seatActive') }}</span>
                  <div class="cn-param-switch">
                    <BaseSwitch
                      :model-value="selectedRole.enabled !== false"
                      :disabled="!auth.isSuperadmin"
                      :label="t('admin.council.seatActive')"
                      @update:model-value="(v: boolean) => (selectedRole.enabled = v)"
                    />
                    <span>{{ selectedRole.enabled !== false ? t('admin.council.seatActive') : t('admin.council.seatMuted') }}</span>
                  </div>
                </div>
              </div>
            </div>

            <!-- 提示词 -->
            <div class="cn-prompt">
              <div class="cn-prompt-head">
                <h3 class="cn-section-title">{{ t('admin.council.promptTitle') }}</h3>
                <div class="cn-slots">
                  <span class="label-caps" :title="t('admin.council.insertSlotHint')">
                    {{ t('admin.council.insertSlotLabel') }}
                  </span>
                  <button
                    v-for="slot in DATA_SLOTS"
                    :key="slot.k"
                    type="button"
                    class="cn-slot"
                    :disabled="!auth.isSuperadmin"
                    @click="selectedRole.prompt = selectedRole.prompt ? `${String(selectedRole.prompt).trim()}\n${t('admin.council.slotVerifyLine')}{{${slot.k}}}` : `{{${slot.k}}}`"
                  >
                    +&#123;&#123;{{ slot.k }}&#125;&#125;
                  </button>
                  <button type="button"
                    class="btn btn-quiet btn-sm"
                    :disabled="!auth.isSuperadmin"
                    @click="resetRole(expandedRole)"
                  >
                    <RotateCcw :size="13" />
                    <span>{{ t('admin.council.restorePrompt') }}</span>
                  </button>
                </div>
              </div>

              <textarea
                v-model="selectedRole.prompt"
                rows="20"
                spellcheck="false"
                :aria-label="t('admin.council.seatPromptAria')"
                class="field cn-textarea"
                :disabled="!auth.isSuperadmin"
                :placeholder="t('admin.council.promptPlaceholder')"
              />
            </div>
          </template>
        </section>
      </div>

      <!-- ══ 辩论实录 ══ -->
      <section v-if="testResult" class="card cn-transcript">
        <header class="card-head">
          <div class="cn-tr-head">
            <h2 class="card-title"><CheckCircle2 :size="14" />{{ t('admin.council.transcriptTitle') }}</h2>
            <span class="badge badge-accent">
              {{ t('admin.council.consensusLabel') }} {{ testResult.transcript?.consensus_mode }}
            </span>
            <span class="badge badge-up">
              {{ t('admin.council.totalDuration') }} {{ testResult.transcript?.total_duration_ms }}ms
            </span>
            <!-- 审计 P1-4c：本轮辩论的行情/资金到底来自哪里、缺了什么 -->
            <span
              v-if="testResult.market_context"
              class="badge"
              :class="(testResult.market_context.missing || []).length ? 'badge-warn' : ''"
              :title="(testResult.market_context.missing || []).join(t('admin.council.listSep'))"
            >
              {{ testResult.market_context.source === 'manual_mock'
                ? t('admin.council.ctxManualMock')
                : t('admin.council.ctxLive', undefined, { n: testResult.market_context.instruments ?? 0 }) }}
              <template v-if="(testResult.market_context.missing || []).length">
                · {{ t('admin.council.ctxMissing', undefined, { n: testResult.market_context.missing.length }) }}
              </template>
            </span>
          </div>
          <button type="button" class="btn btn-ghost btn-sm" @click="testResult = null">
            {{ t('admin.council.collapse') }}
          </button>
        </header>

        <div class="cn-body">
          <!-- 第一轮 -->
          <div class="cn-round">
            <h3 class="cn-round-title">{{ t('admin.council.round1Title') }}</h3>
            <div class="cn-adv-grid">
              <article
                v-for="(adv, key) in testResult.transcript?.advisors || {}"
                :key="key"
                class="cn-adv"
              >
                <header class="cn-adv-head">
                  <span class="cn-adv-name">{{ adv.role_name }}</span>
                  <span
                    class="cn-adv-model mono truncate"
                    :class="{ 'is-warn': adv.model_fallback }"
                    :title="adv.model_note || ''"
                  >
                    {{ adv.model_fallback ? t('admin.council.modelFallbackTag', undefined, { model: adv.model_requested }) : adv.model_used }}
                  </span>
                </header>
                <div class="cn-adv-meta mono">
                  <span>{{ t('admin.council.responseLabel') }} {{ adv.latency_ms }}ms</span>
                  <span v-if="adv.proposal_id">ID: {{ adv.proposal_id }}</span>
                </div>
                <p class="cn-adv-body">{{ adv.content }}</p>
                <div v-if="adv.reasoning" class="cn-adv-reason">
                  <button type="button"
                    class="btn btn-quiet btn-sm"
                    :aria-expanded="Boolean(expandedReasoning[String(key)])"
                    :aria-controls="expandedReasoning[String(key)] ? `cn-reasoning-${key}` : undefined"
                    @click="expandedReasoning[String(key)] = !expandedReasoning[String(key)]"
                  >
                    {{ expandedReasoning[String(key)] ? t('admin.council.collapseReasoning') : t('admin.council.expandReasoning') }}
                  </button>
                  <pre
                    v-if="expandedReasoning[String(key)]"
                    :id="`cn-reasoning-${key}`"
                    class="code-block"
                    tabindex="0"
                  >{{ adv.reasoning }}</pre>
                </div>
              </article>
            </div>
          </div>

          <!-- 第二轮 -->
          <div
            v-if="testResult.transcript?.cross_examinations && Object.keys(testResult.transcript.cross_examinations).length > 0"
            class="cn-round"
          >
            <h3 class="cn-round-title is-warn">{{ t('admin.council.round2Title') }}</h3>
            <div class="cn-adv-grid">
              <article
                v-for="(crit, cKey) in testResult.transcript.cross_examinations"
                :key="cKey"
                class="cn-adv"
              >
                <header class="cn-adv-head">
                  <span class="cn-adv-name">
                    {{ t('admin.council.critiqueBy', undefined, { name: crit.role_name || cKey }) }}
                  </span>
                  <span class="cn-adv-model mono" :class="{ 'is-warn': crit.status === 'ok' }">
                    {{ crit.status === 'ok'
                      ? `${crit.latency_ms}ms`
                      : (crit.status === 'skipped' ? t('admin.council.critiqueSkipped') : t('admin.council.critiqueError')) }}
                  </span>
                </header>
                <p class="cn-adv-body">{{ crit.content }}</p>
              </article>
            </div>
          </div>

          <!-- CIO 终审判定 -->
          <div class="cn-verdict">
            <header class="cn-verdict-head">
              <h3 class="cn-round-title">{{ t('admin.council.verdictTitle') }}</h3>
              <span
                class="cn-adv-model mono"
                :class="{ 'is-warn': testResult.transcript?.arbitrator?.model_fallback }"
                :title="testResult.transcript?.arbitrator?.model_note || ''"
              >
                {{ testResult.transcript?.arbitrator?.model_fallback
                  ? t('admin.council.modelFallbackTag', undefined, { model: testResult.transcript?.arbitrator?.model_requested })
                  : testResult.transcript?.arbitrator?.model_used }}
                · {{ t('admin.council.reviewDuration') }} {{ testResult.transcript?.arbitrator?.latency_ms }}ms
              </span>
            </header>

            <div class="cn-macro">
              <span class="label-caps">{{ t('admin.council.capitalSummary') }}</span>
              <p>{{ testResult.brain_output?.macro_assessment }}</p>
            </div>

            <!-- 六标的点位矩阵 -->
            <div v-if="matrixRows.length" class="cn-matrix">
              <h4 class="cn-section-title">{{ t('admin.council.matrixTitle') }}</h4>
              <div class="cn-table-wrap">
                <table class="table" :aria-label="t('admin.council.matrixTitle')">
                  <thead>
                    <tr>
                      <th scope="col">{{ t('admin.council.matrixColSymbol') }}</th>
                      <th scope="col">{{ t('admin.council.matrixColAdopted') }}</th>
                      <th scope="col">{{ t('admin.council.matrixColAction') }}</th>
                      <th scope="col" class="col-num">{{ t('admin.council.matrixColConf') }}</th>
                      <th scope="col" class="col-num">{{ t('admin.council.matrixColEntry') }}</th>
                      <th scope="col" class="col-num">{{ t('admin.council.matrixColStop') }}</th>
                      <th scope="col" class="col-num">{{ t('admin.council.matrixColTp') }}</th>
                      <th scope="col">{{ t('admin.council.matrixColReason') }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="[sym, dec] in matrixRows" :key="sym">
                      <td class="cn-sym">{{ sym }}</td>
                      <td>
                        <span class="badge" :class="dec.adopted_role === 'REJECT_ALL' ? '' : 'badge-accent'">
                          {{ adoptedLabel(dec) }}
                        </span>
                      </td>
                      <td>
                        <span class="badge" :class="actionTone(dec.action)">
                          {{ dec.action || 'WAIT' }}
                        </span>
                      </td>
                      <td class="col-num">{{ dec.confidence || 0 }}%</td>
                      <td class="col-num mono">{{ dec.action === 'WAIT' ? '--' : '$' + priceOf(dec) }}</td>
                      <td class="col-num mono cn-down">{{ dec.action === 'WAIT' ? '--' : '$' + (dec.stop_loss || '--') }}</td>
                      <td class="col-num mono cn-up">{{ dec.action === 'WAIT' ? '--' : '$' + (dec.take_profit || '--') }}</td>
                      <td class="cn-reason" :title="dec.reasoning || dec.reason || ''">
                        {{ dec.action === 'WAIT'
                          ? t('admin.council.waitNote')
                          : (dec.reasoning || dec.reason || t('admin.council.defaultReason')) }}
                      </td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        </div>
      </section>
    </template>

    <!-- ══ 导入配置对话框 ══ -->
    <BaseDialog
      :open="importVisible"
      :title="t('admin.council.import')"
      :desc="t('admin.council.importHint')"
      size="lg"
      @close="closeImport"
    >
      <div class="cn-import">
        <input
          type="file"
          accept="application/json,.json"
          class="cn-file"
          @change="pickImportFile"
        />
        <textarea
          v-model="importRawJson"
          rows="10"
          spellcheck="false"
          :aria-label="t('admin.council.importJsonAria')"
          class="field cn-textarea mono"
          :placeholder="t('admin.council.importPlaceholder')"
        />
        <p v-if="importFileError" role="alert" class="cn-warn">
          <AlertTriangle :size="13" />
          <span>{{ importFileError }}</span>
        </p>
      </div>

      <template #footer>
        <button type="button" class="btn btn-ghost btn-sm" @click="closeImport">{{ t('admin.council.cancel') }}</button>
        <button type="button"
          class="btn btn-primary btn-sm"
          :disabled="importing || !importRawJson.trim()"
          @click="doImportConfig"
        >
          <Upload :size="14" />
          <span>{{ importing ? t('admin.council.importing') : t('admin.council.confirmImport') }}</span>
        </button>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.cn {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}

/* ══ 议事状态带 ══ */









/* ══ 议事规则 ══ */
.cn-head-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.cn-modes {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1px;
  background-color: var(--ds-color-border-default);
}
@media (min-width: 900px) {
  .cn-modes {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
.cn-mode {
  display: flex;
  flex-direction: column;
  gap:6px;
  padding: var(--ds-space-4);
  text-align: left;
  background-color: var(--ds-color-bg-surface-card);
  border-left: 2px solid transparent;
  cursor: pointer;
  transition: background-color var(--dur-fast);
}
.cn-mode:hover:not(:disabled) {
  background-color: var(--ds-color-bg-hover);
}
.cn-mode.is-on {
  background-color: var(--ds-color-bg-surface-inset);
  border-left-color: var(--ds-color-brand);
}
.cn-mode:disabled {
  cursor: not-allowed;
  opacity: 0.6;
}
.cn-mode-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
}
.cn-mode-name {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.cn-mode-desc {
  font-size: var(--text-3xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-description);
}

.cn-rules-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-3);
  flex-wrap: wrap;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface-inset);
}
.cn-inline {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
}
.cn-num-input {
  width: 76px;
  text-align: center;
  font-variant-numeric: tabular-nums;
}
.cn-unit {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
}
.cn-foot-hint {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
}

/* ══ 主从双栏 ══ */
.cn-split {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-4);
  align-items: start;
}
@media (min-width: 1024px) {
  .cn-split {
    grid-template-columns: 300px minmax(0, 1fr);
  }
}

/* 席位列 */
.cn-seats {
  display: flex;
  flex-direction: column;
  padding: var(--ds-space-1) 0;
}
.cn-seat {
  display: flex;
  align-items: center;
  gap: var(--ds-space-3);
  min-height: 46px;
  padding: 6px var(--ds-space-4);
  text-align: left;
  border-left: 2px solid transparent;
  cursor: pointer;
  transition: background-color var(--dur-fast);
}
.cn-seat:hover {
  background-color: var(--ds-color-bg-hover);
}
.cn-seat.is-on {
  background-color: var(--ds-color-bg-surface-1);
  border-left-color: var(--ds-color-brand);
}
.cn-seat-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}
.cn-seat-name {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--ds-color-text-primary);
}
.cn-seat-sub {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.cn-seat-w {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
}
.cn-seat-arrow {
  color: var(--ds-color-text-placeholder);
  flex-shrink: 0;
}

/* 席位牌 */
.cn-avatar.is-lg {
  width: 34px;
  height: 34px;
}
.cn-avatar.is-cio {
  color: var(--brand);
  background-color: var(--astra-brand-bg);
}
.cn-avatar.is-muted {
  opacity: 0.45;
}

/* 编辑器 */
.cn-editor {
  min-width: 0;
}
.cn-editor-id {
  display: flex;
  align-items: center;
  gap: var(--ds-space-3);
  min-width: 0;
}
.cn-editor-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.cn-name-input {
  background: transparent;
  border: 0;
  border-bottom: 1px dashed var(--ds-color-border-strong);
  outline: none;
  /* 批 99：12px 字号 + `padding: 0 0 2px` 实测只有 **173×22.2**，
     不到 WCAG 2.5.8 的 24px。补 `--h-sm` 后只长高 1.8px，外观无感。 */
  min-height: var(--h-sm);
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ds-color-text-primary);
  padding: 0 0 2px;
  max-width: 260px;
  letter-spacing: var(--track-title);
}
.cn-name-input:read-only {
  border-bottom-color: transparent;
}
/* 批 22：这些内联输入框都写了 outline:none，此前没有任何焦点提示。
   席位名是虚线底框，焦点改成实线 + 品牌色，局部可见即可。 */
.cn-name-input:focus {
  border-bottom-style: solid;
  border-bottom-color: var(--ds-color-border-input-focus);
}
.cn-editor-sub {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.cn-editor-head-right {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}

.cn-desc {
  padding: var(--ds-space-3) var(--ds-space-4) 0;
  font-size: var(--text-xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-description);
}
.cn-warn {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  margin: var(--ds-space-3) var(--ds-space-4) 0;
  padding: 8px 10px;
  border-radius: var(--r-ctl);
  background-color: var(--warn-bg);
  color: var(--warn);
  font-size: var(--text-3xs);
  line-height: var(--leading-body);
}
.cn-warn > svg {
  flex-shrink: 0;
  margin-top: 2px;
}

.cn-section-title {
  font-size: var(--text-3xs);
  font-weight: 500;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ds-color-text-placeholder);
}

.cn-params {
  padding: var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  margin-top: var(--ds-space-3);
}
.cn-param-grid {
  margin-top: var(--ds-space-3);
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-4);
  align-items: start;
}
@media (min-width: 640px) {
  .cn-param-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (min-width: 1280px) {
  .cn-param-grid {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}
.cn-param {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}
.cn-param-hint {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.cn-param-switch {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  font-size: var(--text-xs);
  color: var(--ds-color-text-secondary);
  min-height: 32px;
}
.field.is-warn {
  border-color: var(--warn-line);
  color: var(--warn);
}

/* 提示词 */
.cn-prompt {
  padding: var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
}
.cn-prompt-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-3);
  flex-wrap: wrap;
}
.cn-slots {
  display: flex;
  align-items: center;
  gap:6px;
  flex-wrap: wrap;
}
.cn-slot {
  padding:4px 8px;
  border-radius: var(--r-xs);
  border: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface-1);
  font-family: var(--ds-font-mono);
  font-size: var(--text-4xs);
  color: var(--ds-color-text-secondary);
  cursor: pointer;
  transition: border-color var(--dur-fast), color var(--dur-fast);
}
.cn-slot:hover:not(:disabled) {
  border-color: var(--ds-color-brand);
  color: var(--ds-color-brand);
}
.cn-slot:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
.cn-textarea {
  margin-top: var(--ds-space-3);
  width: 100%;
  min-height: 420px;
  resize: vertical;
  font-family: var(--ds-font-mono);
  font-size: var(--text-base);
  line-height: 1.6;
  tab-size: 2;
  padding: var(--ds-space-3-5) var(--ds-space-4);
  background-color: var(--ds-color-bg-code);
  border-radius: var(--r-ctl);
}

/* ══ 辩论实录 ══ */
.cn-tr-head {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.cn-body {
  display: flex;
  flex-direction: column;
}
.cn-round {
  padding: var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
}
.cn-round-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
  margin-bottom: var(--ds-space-3);
}
.cn-round-title.is-warn {
  color: var(--warn);
}

.cn-adv-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-3);
}
@media (min-width: 1100px) {
  .cn-adv-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
.cn-adv {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
  min-width: 0;
}
.cn-adv-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--ds-space-2);
  min-width: 0;
}
.cn-adv-name {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.cn-adv-model {
  font-size: var(--text-4xs);
  color: var(--ds-color-brand);
  max-width: 150px;
}
.cn-adv-model.is-warn {
  color: var(--warn);
}
.cn-adv-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.cn-adv-body {
  font-size: var(--text-xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-secondary);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  max-height: 220px;
  overflow-y: auto;
}
.cn-adv-reason {
  padding-top: var(--ds-space-2);
  border-top: 1px solid var(--ds-color-border-default);
}

/* CIO 裁定 */
.cn-verdict {
  padding: var(--ds-space-4);
}
.cn-verdict-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--ds-space-3);
  flex-wrap: wrap;
}
.cn-macro {
  margin-top: var(--ds-space-3);
  padding: var(--ds-space-3);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
  border-left: 2px solid var(--ds-color-brand);
}
.cn-macro p {
  margin-top: 4px;
  font-size: var(--text-xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-primary);
}
.cn-matrix {
  margin-top: var(--ds-space-4);
}
.cn-table-wrap {
  margin-top: var(--ds-space-3);
  overflow-x: auto;
}
.cn-sym {
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.cn-up {
  color: var(--up);
}
.cn-down {
  color: var(--down);
}
.cn-reason {
  max-width: 320px;
  font-size: var(--text-3xs);
  color: var(--ds-color-text-description);
}

/* 导入对话框 */
.cn-import {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-3);
}
.cn-file {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
</style>
