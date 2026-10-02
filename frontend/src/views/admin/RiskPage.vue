<script setup lang="ts">
/**
 * RiskPage.vue · 风控参数工位
 * ---------------------------------------------------------------------------
 * 骨架（推倒重来）：
 *   旧 = 页头徽章 + 提示条 + 6 个 card-flat 小格 + 3 张预设卡
 *        + 每组一张分组卡（内含参数行）+ DangerZone + 悬浮保存条
 *   新 = 共享 PageHeader（同步态徽章 + 保存 + 重载）
 *        → 生效说明条 → **引擎此刻的口径 → 6 项运行状态带**
 *        → **预设套件 → 发丝分隔的三联选择条**（选中态走左侧品牌竖线）
 *        → **风控参数 → 单一面板内的分组区块 + 参数行**
 *        → DangerZone（共享）→ 悬浮保存条
 *
 * 后端契约（逐字未改）：
 *   GET  /api/v1/admin/risk[?equity=N]        ← 权益可用时带上，让后端派生"引擎此刻的口径"
 *   POST /api/v1/admin/risk        { suite_id } | { values, confirmation }
 *   POST /api/v1/admin/risk/reset  { confirmation: 'RESET RISK' }
 *
 * ⚠️ 高风险门禁未动：越界校验、杠杆下限>上限校验、极端值（≥ high_risk_at）
 *    要求逐字短语 `HIGH RISK`、重置要求逐字短语 `RESET RISK`，全部保留原样。
 */
import { useToast } from '../../composables/useToast';
import { useConfirm } from '../../composables/useConfirm';
const toast = useToast();
const { ask } = useConfirm();
import { ref, reactive, computed, onMounted } from 'vue';
import { useI18n } from '../../composables/useI18n';
const { t } = useI18n();

import { useApi } from '../../composables/useApi';
import { useAsyncAction } from '../../composables/useAsyncAction';
import { useDashboardStore } from '../../stores/dashboard';
import PageHeader from '../../components/admin/PageHeader.vue';

import DangerZone from '../../components/admin/page-parts/DangerZone.vue';
import BaseEmpty from '../../components/base/BaseEmpty.vue';
import BaseSwitch from '../../components/base/BaseSwitch.vue';
import { ShieldAlert, Save, RotateCcw, Loader2, Info, Layers,
  Target, RefreshCw, AlertTriangle, Zap, Shield } from 'lucide-vue-next';
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue';

const { api } = useApi();
const store = useDashboardStore();

const busy = ref<'save' | 'reset' | ''>('');

const schema = ref<{ groups: any[]; params: any[]; high_risk_phrase?: string } | null>(null);
/** 引擎此刻的口径（审计未完成清单#3）：文件值 = 下一周期生效；进程内值 = 长驻进程正在用的 */
const processValues = ref<Record<string, number>>({});
const processFresh = ref<{ stale: boolean; note: string; env_file_mtime: number | null; loaded_at: number | null } | null>(null);
const engineValues = ref<Record<string, any> | null>(null);
const driftCount = computed(() => {
  const keys = Object.keys(processValues.value || {})
  return keys.filter((k) => {
    const file = serverValues.value[k]
    const proc = processValues.value[k]
    return typeof file === 'number' && typeof proc === 'number' && Math.abs(file - proc) > 1e-9
  })
})
const suites = ref<any[]>([]);
const effectText = ref('');
const serverValues = ref<Record<string, number>>({});
const draft = reactive<Record<string, number>>({});       // 原生值（比例类为小数）
const disp = reactive<Record<string, string>>({});        // 显示值字符串（用户编辑）

const activeSuiteId = computed(() => {
  if (dirtyKeys.value.length || !suites.value.length) return ''
  for (const s of suites.value) {
    const match = Object.entries(s.values as Record<string, number>).every(
      ([k, v]) => Math.abs((serverValues.value[k] ?? NaN) - v) < 1e-9)
    if (match) return s.id
  }
  return ''
});

async function applySuite(s: any) {
  if (busy.value) return
  busy.value = 'save'
  try {
    const res = await api('/api/v1/admin/risk', { method: 'POST', body: JSON.stringify({ suite_id: s.id }) })
    syncFromServer(res.values)
    toast.ok(t('admin.risk.applyOk', undefined, { name: s.name, effect: res.effect }))
  } catch (e: any) {
    toast.err(t('admin.risk.applyFailed', undefined, { msg: e.message }))
  } finally {
    busy.value = ''
  }
}

// 杠杆区间合并行的参数引用（schema 缺失时自动退回通用行渲染，不炸页面）
const levMinP = computed<any>(() => schema.value?.params.find((x: any) => x.key === 'ASTRA_MIN_LEVERAGE') || null)
const levMaxP = computed<any>(() => schema.value?.params.find((x: any) => x.key === 'ASTRA_MAX_LEVERAGE') || null)
const levInverted = computed(() => !!levMinP.value && !!levMaxP.value
  && (draft[levMinP.value.key] ?? 0) > (draft[levMaxP.value.key] ?? 0));

function toDisplay(p: any, native: number): string {
  const v = native * (p.display_scale || 1)
  // 去掉浮点噪声，最多保留 4 位小数
  return String(Math.round(v * 10000) / 10000)
}

function fromDisplay(p: any, display: string): number | null {
  const raw = parseFloat(display)
  if (Number.isNaN(raw)) return null
  let native = raw / (p.display_scale || 1)
  if (p.type === 'int') native = Math.round(native)
  else native = Math.round(native * 1e6) / 1e6
  return native
}

function syncFromServer(values: Record<string, number>) {
  serverValues.value = { ...values }
  for (const p of schema.value!.params) {
    const v = values[p.key]
    draft[p.key] = v
    disp[p.key] = toDisplay(p, v)
  }
}

// F2：动作类样板（busy + 统一错误出口）。error → toast 与原实现一致；
// initialBusy: true 保持"首帧即加载态"（原为 loading = ref(true)）。
const { run: loadData, busy: loading, error: loadError } = useAsyncAction(async () => {
  // 带上页面上展示的可用权益，让后端派生"引擎此刻的口径"（权益未知时后端会如实标 None）
  const eq = Number((store as any)?.data?.account?.avail_eq)
  const query = Number.isFinite(eq) && eq > 0 ? `?equity=${eq}` : ''
  const res = await api<any>(`/api/v1/admin/risk${query}`)
  schema.value = res.schema
  suites.value = res.suites || []
  effectText.value = res.effect || ''
  processValues.value = res.process_values || {}
  processFresh.value = res.process_freshness || null
  engineValues.value = res.engine_values || null
  syncFromServer(res.values)
}, { onError: (e) => toast.err(t('admin.risk.loadFailed', undefined, { msg: e.message })), initialBusy: true });

const dirtyKeys = computed(() => {
  if (!schema.value) return []
  return schema.value.params
    .filter((p: any) => draft[p.key] !== undefined && serverValues.value[p.key] !== undefined
      && Math.abs((draft[p.key] ?? 0) - (serverValues.value[p.key] ?? 0)) > 1e-9)
    .map((p: any) => p.key)
})

function isCustomized(p: any): boolean {
  return serverValues.value[p.key] !== undefined
    && Math.abs(serverValues.value[p.key] - p.default) > 1e-9
}

function onFieldInput(p: any) {
  const native = fromDisplay(p, disp[p.key])
  if (native !== null) draft[p.key] = native
}

function revertOne(p: any) {
  draft[p.key] = p.default
  disp[p.key] = toDisplay(p, p.default)
}

function outOfRange(p: any): boolean {
  const v = draft[p.key]
  return v !== undefined && (v < p.min || v > p.max)
}

/** 分组内除杠杆两键外的参数（支持按核心/高级分级过滤） */
const showAdvanced = ref(false);

const advancedParamsCount = computed(() => {
  return (schema.value?.params || []).filter((p: any) => p.tier === 'advanced').length;
});

const coreParamsCount = computed(() => {
  return (schema.value?.params || []).filter(
    (p: any) => p.tier === 'core' && p.key !== 'ASTRA_MIN_LEVERAGE' && p.key !== 'ASTRA_MAX_LEVERAGE',
  ).length + 1; // +1 计入杠杆合并行
});

const coreKeys = [
  'ASTRA_MAX_CONCURRENT_POSITIONS',
  'ASTRA_MAX_SAME_DIRECTION_POSITIONS',
  'ASTRA_MAX_MARGIN_EQUITY_RATIO',
  'ASTRA_DAILY_LOSS_EQUITY_RATIO',
  'ASTRA_TIME_STOP_HOURS',
  'ASTRA_MIN_ENTRY_CONFIDENCE',
  'ASTRA_MAX_SCALE_IN_COUNT',
  'ASTRA_SCALE_OUT_ENABLED',
];

const visibleParams = computed(() => {
  const all = schema.value?.params || [];
  const core = coreKeys.map((k) => all.find((p: any) => p.key === k)).filter(Boolean);
  if (!showAdvanced.value) {
    return core;
  }
  const advanced = all.filter(
    (p: any) => p.tier === 'advanced' && p.key !== 'ASTRA_MIN_LEVERAGE' && p.key !== 'ASTRA_MAX_LEVERAGE',
  );
  return [...core, ...advanced];
});

const hasDirtyAdvanced = computed(() => {
  return dirtyKeys.value.some((key: string) => {
    const p = schema.value?.params.find((x: any) => x.key === key);
    return p && p.tier === 'advanced';
  });
});

const availEquity = computed(() => {
  const eq = Number((store as any)?.data?.account?.avail_eq);
  return Number.isFinite(eq) && eq > 0 ? eq : 0;
});

function calcMarginPreview(p: any): string | null {
  if (!availEquity.value) return null;
  const v = draft[p.key] ?? p.default;
  if (p.key === 'ASTRA_MAX_MARGIN_EQUITY_RATIO') {
    const amt = availEquity.value * Number(v);
    return `≈ ${amt.toFixed(2)} USDT`;
  }
  if (p.key === 'ASTRA_DAILY_LOSS_EQUITY_RATIO') {
    const amt = availEquity.value * Number(v);
    return `≈ -${amt.toFixed(2)} USDT`;
  }
  return null;
}

function setLeverageCorridor(minLev: number, maxLev: number) {
  if (levMinP.value && levMaxP.value) {
    draft[levMinP.value.key] = minLev;
    disp[levMinP.value.key] = String(minLev);
    draft[levMaxP.value.key] = maxLev;
    disp[levMaxP.value.key] = String(maxLev);
  }
}

/** 引擎口径 6 项（数据驱动的单一模板，取代 6 段复制粘贴） */
const engineFacts = computed(() => {
  const e = engineValues.value
  if (!e) return []
  const U = ' U'
  return [
    { label: t('admin.risk.engineDailyLoss'), value: e.daily_loss_limit_usdt == null ? '--' : `${e.daily_loss_limit_usdt}${U}` },
    { label: t('admin.risk.engineSingleAsset'), value: e.single_asset_margin_usdt == null ? '--' : `${e.single_asset_margin_usdt}${U}` },
    { label: t('admin.risk.engineMaxPositions'), value: e.max_positions == null ? '--' : `${e.max_positions} / ${e.max_same_direction}` },
    { label: t('admin.risk.engineTargetRR'), value: e.max_risk_reward ? `${e.target_rr} ~ ${e.max_risk_reward}` : `≥ ${e.target_rr}` },
    {
      label: '止盈止损宽度',
      value: `止盈 ≤ ${e.max_take_profit_atr || 3.5}x ATR · 止损 ${e.stop_loss_atr_mult || 2.0}x ATR`,
    },
    { label: t('admin.risk.engineConfBand'), value: `${(e.confidence_band || []).join('% ~ ')}%` },
    {
      label: '分批止盈口径',
      value: e.scale_out_enabled
        ? `${Math.round((e.scale_out_ratio || 0.5) * 100)}% · ${e.scale_out_trigger_atr || 1.2}x ATR`
        : '已禁用',
    },
    { label: t('admin.risk.engineEquityUsed'), value: e.usdt_available_used == null ? t('admin.risk.engineEquityUnknown') : `${e.usdt_available_used}${U}` },
  ]
})

const driftLabels = computed(() =>
  driftCount.value.map((k) => schema.value?.params.find((x: any) => x.key === k)?.label || k),
)

async function saveChanges() {
  if (!dirtyKeys.value.length) return
  const bad = schema.value!.params.filter((p: any) => {
    const v = draft[p.key]
    return dirtyKeys.value.includes(p.key) && (v < p.min || v > p.max)
  })
  if (bad.length) {
    const labels = bad.map((p: any) => p.label).join(t('admin.risk.itemSep'))
    toast.err(t('admin.risk.outOfRange', undefined, { labels }))
    return
  }
  if (levInverted.value) {
    toast.err(t('admin.risk.levInvertedFix'))
    return
  }
  if (levInverted.value) {
    toast.err(t('admin.risk.levInvertedSave'))
    return
  }
  if ((draft.ASTRA_MIN_RISK_REWARD ?? 0) > (draft.ASTRA_MAX_RISK_REWARD ?? 0)) {
    toast.err(t('admin.risk.rrInvertedSave'))
    return
  }
  // 审计 P2-9：极端值（单标的占比≥50% / 日亏≥25% 权益 / 杠杆≥10x 等）此前一次点击即落盘，
  // 误触就能把硬风控放松到接近失效。后端要求逐字短语 HIGH RISK，这里补上确认框。
  const values: Record<string, number> = {}
  for (const k of dirtyKeys.value) values[k] = draft[k]
  const limitOf = (key: string): number | null => {
    const row = schema.value?.params.find((x: any) => x.key === key)
    return row && (row as any).high_risk_at != null ? Number((row as any).high_risk_at) : null
  }
  const extreme = dirtyKeys.value.filter((k) => {
    const lim = limitOf(k)
    return lim != null && Number(values[k]) >= lim
  })
  let confirmation = ''
  if (extreme.length) {
    const detail = extreme
      .map((k) => `${schema.value?.params.find((x: any) => x.key === k)?.label || k} = ${values[k]}`)
      .join(t('admin.risk.detailSep'))
    const _ok = await ask({
      title: t('admin.risk.extremeTitle'),
      desc: t('admin.risk.extremeDesc', undefined, { detail }),
      danger: true,
      confirmPhrase: 'HIGH RISK',
      okText: t('common.confirmWrite'),
    })
    if (!_ok) return
    confirmation = 'HIGH RISK'
  }
  busy.value = 'save'
  try {
    const res = await api('/api/v1/admin/risk', { method: 'POST', body: JSON.stringify({ values, confirmation }) })
    syncFromServer(res.values)
    toast.ok(t('admin.risk.saveOk', undefined, { n: res.updated.length, effect: res.effect }))
  } catch (e: any) {
    toast.err(t('admin.risk.saveFailed', undefined, { msg: e.message }))
  } finally {
    busy.value = ''
  }
}

async function resetAll() {
  // 批C(2026-09-13)·补门禁：本操作把全部风控参数恢复代码默认基线（含仓位/日亏上限），
  // 此前**零确认**一次点击即执行，而后端本就要求逐字短语 `RESET RISK`（前端把短语写死
  // 在请求体里，等于保险被旁路）。移动端误触即放松风控，风险极高——现要求逐字确认。
  const _ok = await ask({
    title: t('admin.risk.resetAllTitle'),
    desc: t('admin.risk.resetAllDesc'),
    danger: true,
    confirmPhrase: 'RESET RISK',
    okText: t('common.resetBaseline'),
  })
  if (!_ok) return
  busy.value = 'reset'
  try {
    const res = await api('/api/v1/admin/risk/reset', { method: 'POST', body: JSON.stringify({ confirmation: 'RESET RISK' }) })
    syncFromServer(res.values)
    toast.ok(t('admin.risk.resetOk', undefined, { effect: res.effect }))
  } catch (e: any) {
    toast.err(t('admin.risk.resetFailed', undefined, { msg: e.message }))
  } finally {
    busy.value = ''
  }
}

onMounted(loadData)
</script>

<template>
  <div class="rk">
    <PageHeader :title="t('nav.admin.risk')">
      <template #actions>
        <span class="badge" :class="dirtyKeys.length ? 'badge-warn' : 'badge-up'">
          {{ dirtyKeys.length ? t('admin.risk.pendingSave', undefined, { n: dirtyKeys.length }) : t('admin.risk.inSync') }}
        </span>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="loading || busy !== ''" @click="loadData">
          <RefreshCw :size="14" :class="loading && 'animate-spin shrink-0'" />
          <span>{{ t('common.refresh') }}</span>
        </button>
        <button type="button" class="btn btn-primary btn-sm" :disabled="busy !== '' || !dirtyKeys.length" @click="saveChanges">
          <Loader2 v-if="busy === 'save'" :size="14" class="animate-spin shrink-0" />
          <Save v-else :size="14" />
          <span>{{ busy === 'save' ? t('admin.risk.saving') : t('admin.risk.saveApply') }}</span>
        </button>
      </template>
    </PageHeader>

    <!-- 生效说明条 -->
    <div class="rk-note" :class="{ 'is-warn': driftCount.length || processFresh?.stale }">
      <AlertTriangle v-if="driftCount.length || processFresh?.stale" :size="13" />
      <Info v-else :size="13" />
      <div class="rk-note-body">
        <p>{{ effectText || t('admin.risk.effectHint') }}</p>
        <p v-if="processFresh?.stale" class="rk-note-warn">
          {{ t('admin.risk.processStale') }}{{ t('common.punct.parenOpen') }}{{ t('admin.risk.processDiffCount', undefined, { n: driftCount.length }) }}{{ t('common.punct.parenClose') }}
        </p>
        <p v-else-if="driftCount.length" class="rk-note-warn">
          {{ t('admin.risk.processDiffCount', undefined, { n: driftCount.length }) }}
        </p>
      </div>
    </div>

    <!-- 引擎此刻的口径 -->
    <section v-if="engineValues" class="card">
      <header class="card-head">
        <div>
          <h2 class="card-title"><Target :size="14" />{{ t('admin.risk.engineNow') }}</h2>
          <p class="card-sub">{{ t('admin.risk.engineNowHint') }}</p>
        </div>
      </header>

      <div class="rk-band">
        <div v-for="f in engineFacts" :key="f.label" class="rk-fact">
          <span class="label-caps">{{ f.label }}</span>
          <span class="rk-fact-v num">{{ f.value }}</span>
        </div>
      </div>

      <p v-if="driftCount.length" class="rk-drift">
        <AlertTriangle :size="12" class="shrink-0" />
        <span>{{ t('admin.risk.engineDrift') }}{{ t('common.punct.colon') }}{{ driftLabels.join(t('admin.risk.itemSep')) }}</span>
      </p>
    </section>

    <!-- 首屏加载 -->
    <div v-if="loading" class="rk-skel">
      <BaseLoadingAnnounce />
      <div v-for="i in 6" :key="i" class="skeleton skeleton-row" />
    </div>

    <template v-else-if="schema">
      <!-- 预设套件 -->
      <section v-if="suites.length" class="card">
        <header class="card-head">
          <div>
            <h2 class="card-title">{{ t('admin.risk.suitesTitle') }}</h2>
            <p class="card-sub">{{ t('admin.risk.suitesDesc') }}</p>
          </div>
        </header>

        <div class="rk-suites">
          <div
            v-for="s in suites"
            :key="s.id"
            class="rk-suite transition-all duration-200"
            :class="{ 'is-on !border-l-4 !border-[var(--brand)]': activeSuiteId === s.id }"
          >
            <div class="rk-suite-top">
              <div class="flex items-center gap-2">
                <component
                  :is="s.id === 'conservative' ? Shield : (s.id === 'aggressive' ? Zap : Target)"
                  :size="15"
                  :class="activeSuiteId === s.id ? 'text-[var(--brand)]' : 'text-[var(--ink-3)]'"
                />
                <span class="rk-suite-name">{{ s.name }}</span>
              </div>
              <span v-if="activeSuiteId === s.id" class="badge badge-up">{{ t('admin.risk.activeNow') }}</span>
              <span v-else class="rk-suite-tag">{{ s.tagline }}</span>
            </div>
            <p class="rk-suite-desc">{{ s.desc }}</p>
            <div class="flex flex-wrap gap-x-2.5 gap-y-1 pt-1.5 pb-0.5 border-t border-[var(--line-subtle)] font-mono text-4xs">
              <span class="text-[var(--ink-3)]">{{ t('admin.risk.suiteMetricLev') }}: <b class="text-[var(--ink-1)] font-medium">{{ s.values?.ASTRA_MIN_LEVERAGE }}~{{ s.values?.ASTRA_MAX_LEVERAGE }}x</b></span>
              <span class="text-[var(--ink-3)]">{{ t('admin.risk.suiteMetricMargin') }}: <b class="text-[var(--ink-1)] font-medium">{{ Math.round((s.values?.ASTRA_MAX_MARGIN_EQUITY_RATIO || 0) * 100) }}%</b></span>
              <span class="text-[var(--ink-3)]">{{ t('admin.risk.suiteMetricRisk1R') }}: <b class="text-[var(--accent)] font-medium">{{ Number(((s.values?.ASTRA_RISK_PER_TRADE_RATIO || 0) * 100).toFixed(1)) }}%</b></span>
              <span class="text-[var(--ink-3)]">{{ t('admin.risk.suiteMetricAssetCap') }}: <b class="text-[var(--ink-1)] font-medium">{{ Math.round((s.values?.ASTRA_SINGLE_ASSET_EQUITY_RATIO || 0) * 100) }}%</b></span>
              <span class="text-[var(--ink-3)]">{{ t('admin.risk.suiteMetricRR') }}: <b class="text-[var(--brand)] font-medium">{{ s.values?.ASTRA_MIN_RISK_REWARD }}~{{ s.values?.ASTRA_MAX_RISK_REWARD }}</b></span>
              <span class="text-[var(--ink-3)]">{{ t('admin.risk.suiteMetricCooldown') }}: <b class="text-[var(--ink-1)] font-medium">{{ s.values?.ASTRA_STOP_COOLDOWN_MINUTES }}m</b></span>
              <span class="text-[var(--ink-3)]">{{ t('admin.risk.suiteMetricDailyLoss') }}: <b class="text-[var(--down)] font-medium">{{ Math.round((s.values?.ASTRA_DAILY_LOSS_EQUITY_RATIO || 0) * 100) }}%</b></span>
            </div>
            <button type="button"
              class="btn btn-sm"
              :class="activeSuiteId === s.id ? 'btn-primary' : 'btn-ghost'"
              :disabled="busy !== '' || activeSuiteId === s.id"
              @click="applySuite(s)"
            >
              {{ activeSuiteId === s.id ? t('admin.risk.applied') : t('admin.risk.applySuite') }}
            </button>
          </div>
        </div>
      </section>

      <!-- 风控参数 -->
      <section class="card">
        <header class="card-head flex items-center justify-between">
          <div class="flex items-center gap-2">
            <h2 class="card-title"><ShieldAlert :size="14" />{{ t('admin.risk.paramsTitle') }}</h2>
            <span class="badge mono">{{ showAdvanced ? (coreParamsCount + advancedParamsCount) : coreParamsCount }}</span>
          </div>
          <button
            type="button"
            class="btn btn-ghost btn-sm font-mono text-3xs flex items-center gap-1.5"
            :class="{ 'bg-[var(--surface-3)] text-[var(--ink-1)] font-medium': showAdvanced }"
            :aria-expanded="showAdvanced"
            :aria-controls="showAdvanced ? 'rk-advanced-list' : undefined"
            @click="showAdvanced = !showAdvanced"
          >
            <Layers :size="12" />
            <span>{{ showAdvanced ? t('admin.risk.hideAdvanced') : t('admin.risk.showAdvanced', undefined, { n: advancedParamsCount }) }}</span>
            <span v-if="hasDirtyAdvanced" class="badge badge-warn text-3xs">{{ t('admin.risk.customized') }}</span>
          </button>
        </header>

        <!-- 杠杆区间合并行 -->
        <div v-if="levMinP && levMaxP" class="rk-row">
          <div class="rk-row-info">
            <div class="rk-row-title">
              <span>{{ t('admin.risk.levRangeTitle') }}</span>
              <span class="badge badge-up text-3xs">{{ t('admin.risk.coreBadge') }}</span>
              <span v-if="isCustomized(levMinP) || isCustomized(levMaxP)" class="badge badge-warn">
                {{ t('admin.risk.customized') }}
              </span>
              <span v-if="levInverted" class="badge badge-down">{{ t('admin.risk.levInverted') }}</span>
            </div>
            <p class="panel-desc">{{ t('admin.risk.levRangeDesc') }}</p>
            <p class="rk-row-meta mono">
              {{ t('admin.risk.defaultWord') }} {{ toDisplay(levMinP, levMinP.default) }} ~ {{ toDisplay(levMaxP, levMaxP.default) }} x
              · {{ t('admin.risk.configurableWord') }} {{ toDisplay(levMinP, levMinP.min) }} ~ {{ toDisplay(levMaxP, levMaxP.max) }} x
              · {{ levMinP.key }} / {{ levMaxP.key }}
            </p>
            <div class="flex items-center gap-1.5 mt-2 flex-wrap">
              <span class="text-3xs text-[var(--ink-3)] font-mono">{{ t('admin.risk.quickPresets') }}:</span>
              <button
                type="button"
                class="btn btn-ghost btn-sm !h-5 !px-2 !py-0 text-3xs font-mono rounded"
                :class="{ '!bg-[var(--brand)] !text-white font-medium': draft[levMinP.key] === 2 && draft[levMaxP.key] === 3 }"
                @click="setLeverageCorridor(2, 3)"
              >
                2x ~ 3x
              </button>
              <button
                type="button"
                class="btn btn-ghost btn-sm !h-5 !px-2 !py-0 text-3xs font-mono rounded"
                :class="{ '!bg-[var(--brand)] !text-white font-medium': draft[levMinP.key] === 2 && draft[levMaxP.key] === 5 }"
                @click="setLeverageCorridor(2, 5)"
              >
                2x ~ 5x
              </button>
              <button
                type="button"
                class="btn btn-ghost btn-sm !h-5 !px-2 !py-0 text-3xs font-mono rounded"
                :class="{ '!bg-[var(--brand)] !text-white font-medium': draft[levMinP.key] === 6 && draft[levMaxP.key] === 10 }"
                @click="setLeverageCorridor(6, 10)"
              >
                6x ~ 10x
              </button>
            </div>
          </div>

          <div class="rk-input-group focus-ring">
            <input
              v-model="disp[levMinP.key]"
              type="number"
              inputmode="decimal"
              class="rk-input"
              :aria-label="t('admin.risk.levLowerAria')"
              :aria-invalid="outOfRange(levMinP) || levInverted ? 'true' : undefined"
              :class="{ 'is-bad': outOfRange(levMinP) || levInverted }"
              :min="toDisplay(levMinP, levMinP.min)"
              :max="toDisplay(levMinP, levMaxP.max)"
              :step="levMinP.step"
              @input="onFieldInput(levMinP)"
            />
            <span class="rk-unit">x</span>
            <span class="rk-sep">~</span>
            <input
              v-model="disp[levMaxP.key]"
              type="number"
              inputmode="decimal"
              class="rk-input"
              :aria-label="t('admin.risk.levUpperAria')"
              :aria-invalid="outOfRange(levMaxP) || levInverted ? 'true' : undefined"
              :class="{ 'is-bad': outOfRange(levMaxP) || levInverted }"
              :min="toDisplay(levMaxP, levMaxP.min)"
              :max="toDisplay(levMaxP, levMaxP.max)"
              :step="levMaxP.step"
              @input="onFieldInput(levMaxP)"
            />
            <span class="rk-unit">x</span>
          </div>
        </div>

        <!-- 参数条目平铺（无嵌套折叠卡片，核心参数首屏直见） -->
        <template v-for="(p, idx) in visibleParams" :key="p.key">
          <!-- 高级参数分隔条（仅当展开高级参数且到达第一项高级参数时显示） -->
          <div
            v-if="showAdvanced && p.tier === 'advanced' && (idx === 0 || visibleParams[idx - 1]?.tier === 'core')"
            id="rk-advanced-list"
            class="rk-advanced-divider"
          >
            <div class="flex items-center gap-2">
              <Layers :size="13" class="text-[var(--ink-3)]" />
              <span class="text-3xs font-mono font-medium text-[var(--ink-2)]">
                {{ t('admin.risk.advancedHeading', undefined, { n: advancedParamsCount }) }}
              </span>
            </div>
            <span class="text-4xs text-[var(--ink-3)]">{{ t('admin.risk.advancedParamsDesc') }}</span>
          </div>

          <div class="rk-row">
            <div class="rk-row-info">
              <div class="rk-row-title">
                <span>{{ p.label }}</span>
                <span v-if="p.tier === 'advanced'" class="badge text-3xs">{{ t('admin.risk.advancedBadge') }}</span>
                <span v-else class="badge badge-up text-3xs">{{ t('admin.risk.coreBadge') }}</span>
                <span v-if="calcMarginPreview(p)" class="badge badge-accent text-3xs font-mono" :title="t('admin.risk.liveEquityHint')">
                  {{ calcMarginPreview(p) }}
                </span>
                <span v-if="isCustomized(p)" class="badge badge-warn">{{ t('admin.risk.customized') }}</span>
              </div>
              <p class="panel-desc">{{ p.desc }}</p>
              <p class="rk-row-meta mono">
                {{ t('admin.risk.defaultWord') }} {{ toDisplay(p, p.default) }} {{ p.unit }}
                · {{ t('admin.risk.rangeWord') }} {{ toDisplay(p, p.min) }} ~ {{ toDisplay(p, p.max) }} {{ p.unit }}
                · {{ p.key }}
              </p>
            </div>

            <div class="rk-row-ctl">
              <div v-if="p.key === 'ASTRA_SCALE_OUT_ENABLED'" class="flex items-center gap-3">
                <span class="text-xs font-mono font-medium" :style="{ color: draft[p.key] ? 'var(--up)' : 'var(--ink-3)' }">
                  {{ draft[p.key] ? '已开启' : '已关闭' }}
                </span>
                <BaseSwitch
                  :model-value="Boolean(draft[p.key])"
                  :aria-label="p.label"
                  @update:model-value="(val: boolean) => {
                    draft[p.key] = val ? 1 : 0;
                    disp[p.key] = val ? '1' : '0';
                  }"
                />
              </div>
              <div v-else class="rk-input-group focus-ring">
                <input
                  v-model="disp[p.key]"
                  type="number"
                  inputmode="decimal"
                  class="rk-input"
                  :aria-label="p.label"
                  :aria-invalid="outOfRange(p) ? 'true' : undefined"
                  :class="{ 'is-bad': outOfRange(p) }"
                  :min="toDisplay(p, p.min)"
                  :max="toDisplay(p, p.max)"
                  :step="p.step * (p.display_scale || 1)"
                  @input="onFieldInput(p)"
                />
                <span class="rk-unit">{{ p.unit }}</span>
              </div>
              <button type="button"
                v-if="Math.abs((draft[p.key] ?? 0) - p.default) > 1e-9"
                class="btn btn-quiet btn-icon btn-sm"
                :title="t('admin.risk.revertItem')"
                @click="revertOne(p)"
              >
                <RotateCcw :size="13" />
              </button>
            </div>
          </div>
        </template>
      </section>

      <!-- 危险区 -->
      <DangerZone
        :title="t('admin.risk.resetTitle')"
        :description="t('admin.risk.resetDesc')"
        confirm-phrase="RESET RISK"
        :action-label="busy === 'reset' ? t('admin.risk.resetting') : t('admin.risk.resetAllBtn')"
        @confirm="resetAll"
      />
    </template>

    <BaseEmpty v-else :text="t('common.loadFailed')" :desc="loadError || t('common.networkError')">
      <template #action>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="loading" @click="loadData">
          <Loader2 v-if="loading" :size="14" class="animate-spin shrink-0" />
          <RefreshCw v-else :size="14" />
          <span>{{ t('common.retry') }}</span>
        </button>
      </template>
    </BaseEmpty>

    <!-- 悬浮保存条 -->
    <div v-if="schema && dirtyKeys.length" class="rk-savebar">
      <span class="rk-savebar-text">{{ t('admin.risk.unsavedCount', undefined, { n: dirtyKeys.length }) }}</span>
      <button type="button" class="btn btn-primary btn-sm" :disabled="busy !== ''" @click="saveChanges">
        <Loader2 v-if="busy === 'save'" :size="14" class="animate-spin shrink-0" />
        <Save v-else :size="14" />
        <span>{{ busy === 'save' ? t('admin.risk.saving') : t('admin.risk.saveApply') }}</span>
      </button>
    </div>
  </div>
</template>

<style scoped>
/* 批 97：72px = 悬浮保存条 `.rk-savebar`（position:fixed，bottom 16 + 自身高约 46）
   + 间隙 —— 为固定条预留的可视余量，属推导几何，刻意离格。 */
.rk {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
  padding-bottom: 72px;
}

/* 生效说明条 */
.rk-note {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  padding: 10px var(--ds-space-4);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
  font-size: var(--text-3xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-description);
}
.rk-note.is-warn {
  background-color: var(--warn-bg);
  color: var(--warn);
}
.rk-note > svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.rk-note-body {
  min-width: 0;
}
.rk-note-warn {
  margin-top: 2px;
  color: var(--warn);
}

/* 引擎口径状态带 */
.rk-band {
  display: grid;
  grid-template-columns: 1fr;
}
@media (min-width: 640px) {
  .rk-band {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (min-width: 1024px) {
  .rk-band {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
@media (min-width: 1600px) {
  .rk-band {
    grid-template-columns: repeat(6, minmax(0, 1fr));
  }
}
.rk-fact {
  display: flex;
  flex-direction: column;
  gap:4px;
  min-width: 0;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  border-left: 1px solid var(--ds-color-border-default);
}
.rk-fact-v {
  font-size: var(--text-md);
  font-weight: 500;
  color: var(--ds-color-text-primary);
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rk-drift {
  display: flex;
  align-items: center;
  gap: 6px;
  /* 批 36：实测图标被压成 7.02×12（父级 flex + 长文案把它挤扁）。 */
  > svg {
    flex-shrink: 0;
  }
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  background-color: var(--warn-bg);
  color: var(--warn);
  font-size: var(--text-3xs);
}

.rk-skel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

/* ══ 预设套件 ══ */
.rk-suites {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1px;
  background-color: var(--ds-color-border-default);
}
@media (min-width: 900px) {
  .rk-suites {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
.rk-suite {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--ds-space-4);
  background-color: var(--ds-color-bg-surface-card);
  border-left: 2px solid transparent;
}
.rk-suite.is-on {
  background-color: var(--ds-color-bg-surface-inset);
  border-left-color: var(--ds-color-brand);
}
.rk-suite-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
}
.rk-suite-name {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.rk-suite-tag {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.rk-suite-desc {
  flex: 1;
  font-size: var(--text-3xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-description);
}
.rk-suite .btn {
  align-self: flex-start;
}

/* ══ 高级参数分隔条 ══ */
.rk-advanced-divider {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3) var(--ds-space-4);
  background-color: var(--ds-color-bg-surface-inset);
  border-top: 1px solid var(--ds-color-border-default);
  flex-wrap: wrap;
}

.rk-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--ds-space-4);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
}
.rk-row:hover {
  background-color: var(--ds-color-bg-hover);
}
.rk-row-info {
  min-width: 0;
}
.rk-row-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.rk-row-meta {
  margin-top: 2px;
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.rk-row-ctl {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-shrink: 0;
}

.rk-input-group {
  display: flex;
  align-items: center;
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-input);
  overflow: hidden;
}
.rk-input {
  width: 92px;
  /* 批 34：全站输入控件走 --h-md（30px）；本页自写成 8px 上下内边距 → 实测 35px，
     既不在高度梯队（24/30/36）上，也比同页其它输入高 5px。 */
  height: var(--h-md);
  padding: 0 10px;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--ds-color-text-primary);
  font-size: var(--text-xs);
  font-variant-numeric: tabular-nums;
  text-align: right;
}
.rk-input.is-bad {
  color: var(--down);
  background-color: var(--down-bg);
}
.rk-unit {
  padding: 0 8px 0 2px;
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
  white-space: nowrap;
}
.rk-sep {
  padding: 0 2px;
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}

/* 悬浮保存条 */
.rk-savebar {
  position: fixed;
  left: 50%;
  bottom: var(--ds-space-4);
  transform: translateX(-50%);
  z-index: var(--z-float);
  display: flex;
  align-items: center;
  gap: var(--ds-space-3);
  padding: 10px var(--ds-space-4);
  border-radius: var(--r-float);
  background-color: var(--ds-color-bg-overlay);
  border: 1px solid var(--ds-color-border-default);
  box-shadow: var(--shadow-float);
}
.rk-savebar-text {
  font-size: var(--text-xs);
  color: var(--ds-color-text-secondary);
  white-space: nowrap;
}

@media (max-width: 720px) {
  .rk-row {
    grid-template-columns: minmax(0, 1fr);
  }
  .rk-row-ctl {
    justify-content: flex-end;
  }
}
</style>
