<script setup lang="ts">
/**
 * LedgerView.vue · DeepSeek Harness 风格交易台账与订单生命周期中枢
 * 包含：汇总指标 HUD、多维实时筛选工具栏、高密度等宽订单流表格、生命周期穿透抽屉与底层巡检日志
 */
import { computed, ref, watch, onMounted } from 'vue';
import { Download, ScrollText, History, Landmark, Zap, Database } from 'lucide-vue-next';
import { useDashboardStore } from '../../stores/dashboard';
import DataGate from '../../components/dashboard/DataGate.vue';
import { useI18n } from '../../composables/useI18n';
import { fmtNum, fmtSigned, fmtPct, fmtPrice, arrow, dirClass, cleanReason, fmtDate, fmtDateTime } from '../../utils/format';
import { venueToneCls } from '../../utils/venueMeta';
import BaseStat from '../../components/base/BaseStat.vue';
import BaseEmpty from '../../components/base/BaseEmpty.vue';
import BaseSegmented from '../../components/base/BaseSegmented.vue';
import BaseCollapse from '../../components/base/BaseCollapse.vue';
import BasePager from '../../components/base/BasePager.vue';
import DirTag from '../../components/base/DirTag.vue';
import CryptoLogo from '../../components/dashboard/CryptoLogo.vue';
import LedgerDrawer from '../../components/dashboard/LedgerDrawer.vue';
import { useToast } from '../../composables/useToast';

const store = useDashboardStore();
const { t } = useI18n();
const toast = useToast();

const fullTrades = ref<any[]>([]);
const loadingFull = ref<boolean>(false);
const allTimeScope = ref<boolean>(false);
const isUserToggle = ref<boolean>(false);

async function loadFullLedger() {
  loadingFull.value = true;
  try {
    const res = await fetch(`/api/v1/public/ledger?all_time=${allTimeScope.value ? 1 : 0}`);
    if (res.ok) {
      const json = await res.json();
      if (Array.isArray(json?.trades) && json.trades.length > 0) {
        fullTrades.value = json.trades;
        if (isUserToggle.value) {
          const count = json.closed_count || fullTrades.value.length;
          toast.ok(allTimeScope.value
            ? t('dash.ledger.loadedAll', undefined, { n: count })
            : t('dash.ledger.loadedCycle', undefined, { n: count }));
          isUserToggle.value = false;
        }
      }
    } else if (isUserToggle.value) {
      toast.err(t('dash.ledger.loadFailed'));
      isUserToggle.value = false;
    }
  } catch {
    if (isUserToggle.value) {
      toast.err(t('dash.ledger.loadNetworkError'));
      isUserToggle.value = false;
    }
  } finally {
    loadingFull.value = false;
  }
}

function toggleScope() {
  isUserToggle.value = true;
  allTimeScope.value = !allTimeScope.value;
}

onMounted(() => {
  loadFullLedger();
});

watch(allTimeScope, () => {
  loadFullLedger();
});

const all = computed<any[]>(() => (fullTrades.value.length ? fullTrades.value : ((store.data as any)?.trades || [])));
const perf = computed<any>(() => (store.data as any)?.performance || {});

/* —— 筛选状态 —— */
const fVenue = ref<string>('all');
const fMode = ref<'all' | 'live' | 'demo'>('all');
const fStatus = ref<'all' | 'closed' | 'holding'>('closed');
const fSide = ref<'all' | 'long' | 'short'>('all');
const fResult = ref<'all' | 'win' | 'loss'>('all');
const fInst = ref('all');

const venueOptions = [
  { value: 'all', label: t('dash.ledger.venueAll') },
  { value: 'okx', label: t('dash.ledger.venueOkx') },
  { value: 'binance', label: t('dash.ledger.venueBinance') },
  { value: 'gate', label: 'Gate.io' },
];

const modeOptions = [
  { value: 'all', label: t('dash.ledger.modeAll') },
  { value: 'live', label: t('dash.ledger.modeLive') },
  { value: 'demo', label: t('dash.ledger.modeDemo') },
];

const instOptions = computed(() => {
  const set = new Set<string>(all.value.map((x) => x.inst));
  return [{ value: 'all', label: t('common.all') }, ...Array.from(set).sort().map((s) => ({ value: s, label: s }))];
});

function sideNorm(s: unknown): 'long' | 'short' | 'flat' {
  const d = String(s || '').toUpperCase();
  if (d === '多' || d.includes('LONG') || d === 'BUY' || d === 'B') return 'long';
  if (d === '空' || d.includes('SHORT') || d === 'SELL' || d === 'S') return 'short';
  return 'flat';
}

const filtered = computed(() =>
  all.value.filter((x) => {
    if (fVenue.value !== 'all') {
      const v = String(x.venue || 'okx').toLowerCase();
      if (v !== fVenue.value) return false;
    }
    if (fMode.value !== 'all') {
      const m = String(x.account_mode || x.environment || 'live').toLowerCase();
      if (fMode.value === 'live' && !m.includes('live')) return false;
      if (fMode.value === 'demo' && !m.includes('demo')) return false;
    }
    if (fStatus.value === 'closed' && x.status === 'holding') return false;
    if (fStatus.value === 'holding' && x.status !== 'holding') return false;
    if (fSide.value !== 'all' && sideNorm(x.side) !== fSide.value) return false;
    if (fResult.value === 'win' && !(Number(x.net_pnl) > 0)) return false;
    if (fResult.value === 'loss' && !(Number(x.net_pnl) <= 0)) return false;
    if (fInst.value !== 'all' && x.inst !== fInst.value) return false;
    return true;
  }),
);

/* —— 分页与重置 —— */
const page = ref(1);
const PAGE = 20;
const pageCount = computed(() => Math.max(1, Math.ceil(filtered.value.length / PAGE)));

watch([fVenue, fMode, fStatus, fSide, fResult, fInst], () => { page.value = 1; });
watch(filtered, () => { if (page.value > pageCount.value) page.value = pageCount.value; });
const rows = computed(() => filtered.value.slice((page.value - 1) * PAGE, page.value * PAGE));

/* —— 统计指标 —— */
const netSum = computed(() => filtered.value.reduce((s, x) => s + (Number(x.net_pnl) || 0), 0));
const feeSum = computed(() => filtered.value.reduce((s, x) => s + Math.abs(Number(x.fee) || 0), 0));
const fundingSum = computed(() => filtered.value.reduce((s, x) => s + (Number(x.funding_fee) || 0), 0));
const fundingIncome = computed(() => filtered.value.reduce((s, x) => s + Math.max(0, Number(x.funding_fee) || 0), 0));
const fundingExpense = computed(() => filtered.value.reduce((s, x) => s + Math.abs(Math.min(0, Number(x.funding_fee) || 0)), 0));
const wins = computed(() => filtered.value.filter((x) => Number(x.net_pnl) > 0).length);
const winRate = computed(() => (filtered.value.length ? Math.round((wins.value / filtered.value.length) * 1000) / 10 : null));

const detail = ref<any>(null);

function exportCsv() {
  const head = ['inst', 'venue', 'account_mode', 'side', 'lever', 'open_time', 'open_px', 'close_time', 'close_px', 'margin', 'fee', 'funding_fee', 'net_pnl', 'roi_pct', 'duration', 'exit_reason', 'strategy'];
  const lines = [head.join(',')];
  for (const x of filtered.value) {
    lines.push(head.map((k) => `"${String((k === 'open_time' || k === 'close_time') ? (x[k] ? fmtDateTime(x[k]) + ' +08:00' : '') : (x[k] ?? '')).replaceAll('"', '""')}"`).join(','));
  }
  const blob = new Blob(['\ufeff' + lines.join('\n')], { type: 'text/csv;charset=utf-8' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `astra-ledger-${fmtDate(new Date())}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
  toast.ok(t('dash.ledger.exported'));
}

const VENUE_LABELS: Record<string, string> = { okx: 'OKX', gate: 'Gate', binance: 'Binance' };
function venueLabel(v: unknown): string {
  return VENUE_LABELS[String(v || '').toLowerCase()] ?? String(v || '');
}

/* —— 数理快照可观测性（证据纪律） ——
 * 标签由后端逐单给出（只认该笔自带的快照证据，绝不回填/推算）。
 * DYNAMICS_OBSERVED = 动力学链完整，可作数理因果归因；
 * PARTIAL          = 只可引用 entry_snapshot 中实际非空的字段；
 * PRICE_ONLY/NONE  = 数理快照不可观测 —— 前台必须明确标注，严禁对
 *                    v/a/j/I、能量积分、偏离面积积分、延续/击穿概率、
 *                    VaR/CVaR 作任何因果陈述（字段缺失本身也不是证据）。 */
const OBS_TAGS = ['DYNAMICS_OBSERVED', 'PARTIAL', 'PRICE_ONLY', 'NONE'] as const;
type ObsTag = (typeof OBS_TAGS)[number];

function obsTag(x: any): ObsTag {
  const v = String(x?.snapshot_observability || 'NONE').toUpperCase();
  return ((OBS_TAGS as readonly string[]).includes(v) ? v : 'NONE') as ObsTag;
}
function obsLabel(x: any): string {
  const tag = obsTag(x);
  if (tag === 'DYNAMICS_OBSERVED') return t('dash.ledger.observability.observed');
  if (tag === 'PARTIAL') return t('dash.ledger.observability.partial');
  if (tag === 'PRICE_ONLY') return t('dash.ledger.observability.priceOnly');
  return t('dash.ledger.observability.none');
}
function obsBadge(x: any): string {
  const tag = obsTag(x);
  if (tag === 'DYNAMICS_OBSERVED') return t('dash.ledger.observability.badgeObserved');
  if (tag === 'PARTIAL') return t('dash.ledger.observability.badgePartial');
  if (tag === 'PRICE_ONLY') return t('dash.ledger.observability.badgePriceOnly');
  return t('dash.ledger.observability.badgeNone');
}
function obsToneCls(x: any): string {
  const tag = obsTag(x);
  if (tag === 'DYNAMICS_OBSERVED') return 'text-[var(--up)] border-[var(--up-line)] bg-[var(--up-bg)]';
  if (tag === 'PARTIAL') return 'text-[var(--warn)] border-[var(--warn-line)] bg-[var(--warn-bg)]';
  return 'text-[var(--ink-3)] border-[var(--line-1)] bg-[var(--surface-2)]';
}

function isScaleOutRow(row: any): boolean {
  return Number(row?.scale_out_phase || 0) >= 1
    || String(row?.exit_reason || '').includes('分批')
    || String(row?.side || '').includes('分批')
    || String(row?.action_type || '').includes('分批');
}

/** 当前筛选集的确定性可观测性审计（宿主统计，非模型推断）。 */
const snapshotAudit = computed(() => {
  const counts: Record<ObsTag, number> = { DYNAMICS_OBSERVED: 0, PARTIAL: 0, PRICE_ONLY: 0, NONE: 0 };
  for (const x of filtered.value) counts[obsTag(x)] += 1;
  return { ...counts, total: filtered.value.length, unobservable: counts.PRICE_ONLY + counts.NONE };
});

/**
 * 载荷截断披露（UI 不说谎）：`/api/all` 瘦身会在 `_meta.omitted.trades` 留痕
 * （`kept` / `total`）。此前前端从不读 `_meta`，34 笔台账被砍到 20 笔时页面
 * 一声不吭 —— 既是少数据，也是把切片当全集渲染。
 * 上限已与台账视图同源（见 `LEDGER_TRADES_MAX`），此处是**最后一道**保证：
 * 台账真超过上限时也必须显式说明，绝不静默少行。
 */
const truncation = computed<{ kept: number; total: number } | null>(() => {
  const o = (store.data as any)?._meta?.omitted?.trades;
  const kept = Number(o?.kept);
  const total = Number(o?.total);
  if (!Number.isFinite(kept) || !Number.isFinite(total) || kept >= total) return null;
  return { kept, total };
});
</script>

<template>
  <div class="space-y-3">
    <!-- 页头：标题与工位状态 -->
    <div class="flex items-center justify-between gap-2 pt-0.5">
      <div class="flex items-center gap-2">
        <h1 class="text-sm font-semibold tracking-tight text-[var(--ink-strong)] flex items-center gap-2">
          <History class="h-4 w-4 text-[var(--accent)]" />
          {{ t('dash.ledger.title') }}
        </h1>
        <span
          class="rounded-full px-2 py-0.5 border text-3xs font-mono font-medium"
          style="background-color: var(--surface-2); border-color: var(--line-1); color: var(--ink-2)"
        >
          {{ t('dash.ledger.countRecords', undefined, { a: filtered.length, b: all.length }) }}
        </span>
      </div>

      <!-- 范围切换与快速导出 CSV -->
      <div class="flex items-center gap-1.5">
        <button
          type="button"
          class="btn btn-quiet h-7 px-2.5 text-xs font-medium cursor-pointer inline-flex items-center gap-1 rounded-full transition-all"
          :title="allTimeScope ? t('dash.ledger.loadCycleHistory') : t('dash.ledger.loadAllHistory')"
          @click="toggleScope"
        >
          <Database class="h-3 w-3 text-[var(--accent)]" :class="{ 'animate-spin': loadingFull }" />
          <span>{{ allTimeScope ? t('dash.ledger.loadCycleHistory') : t('dash.ledger.loadAllHistory') }}</span>
        </button>

        <button type="button"
          class="btn btn-ghost h-7 px-3 text-xs font-medium cursor-pointer inline-flex items-center gap-1.5 rounded-full transition-all"
          :disabled="!filtered.length"
          @click="exportCsv"
        >
          <Download class="h-3.5 w-3.5 text-[var(--accent)]" />
          <span>{{ t('dash.ledger.exportCsv') }}</span>
        </button>
      </div>
    </div>

    <DataGate>
      <!-- 汇总指标 HUD -->
      <div class="dsh-card">
        <div class="grid grid-cols-2 gap-2 p-2 sm:grid-cols-3 xl:grid-cols-6 bg-[var(--surface-1)]">
          <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors">
            <BaseStat :label="t('dash.ledger.summary.total')" :value="fmtNum(filtered.length, 0)" />
          </div>
          <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors">
            <BaseStat
              :label="t('dash.ledger.summary.winRate')"
              :value="winRate != null ? fmtNum(winRate, 1) + '%' : '--'"
              :delta="`${wins} / ${filtered.length}`"
              delta-tone="muted"
            />
          </div>
          <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors">
            <BaseStat :label="t('dash.ledger.summary.net')" :value="fmtSigned(netSum)" />
          </div>
          <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors">
            <BaseStat :label="t('dash.ledger.summary.fees')" :value="feeSum ? `-${fmtNum(feeSum, 2)}` : fmtNum(0, 2)" />
          </div>
          <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors">
            <BaseStat
              :label="t('dash.ledger.summary.fundingNet')"
              :value="fmtSigned(fundingSum)"
              :delta="`${fundingIncome ? '+' + fmtNum(fundingIncome, 2) : fmtNum(0, 2)} / ${fundingExpense ? '-' + fmtNum(fundingExpense, 2) : fmtNum(0, 2)}`"
              :delta-tone="fundingSum >= 0 ? 'up' : 'down'"
              :hint="t('dash.ledger.summary.fundingNetHint')"
            />
          </div>
          <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors">
            <BaseStat
              :label="t('dash.ledger.summary.pf')"
              :value="perf.profit_factor != null ? fmtNum(perf.profit_factor, 2) : '--'"
              :delta="perf.all_trades != null ? t('dash.ledger.summary.pfSource', undefined, { n: perf.all_trades }) : undefined"
              delta-tone="muted"
              :hint="t('dash.ledger.summary.tipPf')"
            />
          </div>
        </div>
      </div>

      <!-- 数理快照异常或截断提示：仅在有截断或不可观测时展示，正常时不干扰视线 -->
      <div
        v-if="truncation || snapshotAudit.unobservable > 0"
        class="dsh-card-sub flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-1.5 text-3xs"
      >
        <span
          v-if="truncation"
          class="rounded border px-1.5 py-0.5 font-medium"
          style="color: var(--warn, var(--ink-2)); border-color: var(--line-1); background-color: var(--surface-2)"
          :title="t('dash.ledger.truncatedHint')"
        >
          {{ t('dash.ledger.truncated', undefined, { kept: truncation.kept, total: truncation.total }) }}
        </span>
        <span
          v-if="snapshotAudit.unobservable"
          class="rounded border px-1.5 py-0.5 font-medium"
          style="color: var(--ink-2); border-color: var(--line-1); background-color: var(--surface-2)"
        >
          {{ t('dash.ledger.observability.unobservable', undefined, { n: snapshotAudit.unobservable, total: snapshotAudit.total }) }}
        </span>
      </div>

      <!-- 筛选工具栏与台账表格 -->
      <div class="dsh-card overflow-hidden">
        <!-- 筛选栏 -->
        <header class="dsh-card-header flex flex-wrap items-center justify-between gap-2">
          <div class="flex flex-wrap items-center gap-2">
            <BaseSegmented
              v-model="fStatus"
              :label="t('dash.ledger.col.status')"
              :options="[
                { value: 'all', label: t('common.all') },
                { value: 'closed', label: t('dash.ledger.status.closed') },
                { value: 'holding', label: t('status.running') },
              ]"
            />
            <BaseSegmented
              v-model="fSide"
              :label="t('dash.ledger.filters.dir')"
              :options="[
                { value: 'all', label: t('common.all') },
                { value: 'long', label: t('common.dir.long') },
                { value: 'short', label: t('common.dir.short') },
              ]"
            />
            <BaseSegmented
              v-model="fResult"
              :label="t('dash.ledger.filters.result')"
              :options="[
                { value: 'all', label: t('common.all') },
                { value: 'win', label: t('dash.ledger.filters.results.win') },
                { value: 'loss', label: t('dash.ledger.filters.results.loss') },
              ]"
            />
          </div>

          <div class="flex flex-wrap items-center gap-2 ms-auto">
            <select
              v-model="fVenue"
              :aria-label="t('dash.ledger.filters.venue')" 
              class="h-7 rounded border border-[var(--line-1)] px-2 text-3xs transition-colors focus:outline-none focus:border-[var(--ds-color-border-input-focus)] focus:ring-1 focus:ring-[var(--ds-color-border-input-focus)]"
              style="background-color: var(--surface-2); color: var(--ink-1)"
              @change="page = 1"
            >
              <option v-for="vo in venueOptions" :key="vo.value" :value="vo.value">{{ vo.label }}</option>
            </select>

            <select
              v-model="fMode"
              :aria-label="t('dash.ledger.filters.mode')" 
              class="h-7 rounded border border-[var(--line-1)] px-2 text-3xs transition-colors focus:outline-none focus:border-[var(--ds-color-border-input-focus)] focus:ring-1 focus:ring-[var(--ds-color-border-input-focus)]"
              style="background-color: var(--surface-2); color: var(--ink-1)"
              @change="page = 1"
            >
              <option v-for="mo in modeOptions" :key="mo.value" :value="mo.value">{{ mo.label }}</option>
            </select>

            <select
              v-model="fInst"
              :aria-label="t('dash.ledger.filters.symbol')" 
              class="h-7 rounded border border-[var(--line-1)] px-2 text-3xs transition-colors focus:outline-none focus:border-[var(--ds-color-border-input-focus)] focus:ring-1 focus:ring-[var(--ds-color-border-input-focus)]"
              style="background-color: var(--surface-2); color: var(--ink-1)"
              @change="page = 1"
            >
              <option v-for="o in instOptions" :key="o.value" :value="o.value">{{ o.label }}</option>
            </select>
          </div>
        </header>

        <!-- 数据为空 -->
        <BaseEmpty v-if="!filtered.length" :text="t('dash.ledger.empty')" />

        <!-- 数据表 -->
        <template v-else>
          <div class="overflow-x-auto">
            <table class="table w-full max-w-[1360px]" :aria-label="t('dash.ledger.title')">
              <thead>
                <tr>
                  <th scope="col" class="min-w-[180px]">{{ t('dash.ledger.col.symbol') }}</th>
                  <th scope="col" class="col-num min-w-[100px]">{{ t('dash.ledger.col.entry') }} / {{ t('dash.ledger.col.exit') }}</th>
                  <th scope="col" class="col-num min-w-[90px]">{{ t('dash.ledger.col.pnl') }}</th>
                  <th scope="col" class="col-num min-w-[85px]">{{ t('dash.ledger.col.fees') }}</th>
                  <th scope="col" class="min-w-[65px]">{{ t('dash.ledger.col.hold') }}</th>
                  <th scope="col" class="max-w-[180px]">{{ t('dash.ledger.col.exitReason') }}</th>
                  <th scope="col" class="text-right min-w-[95px]">{{ t('dash.ledger.col.time') }}</th>
                </tr>
              </thead>
              <tbody>
                <tr
                  v-for="x in rows"
                  :key="x.id"
                  class="clickable transition-colors hover:bg-[var(--surface-2)]"
                  tabindex="0"
                  @click="detail = x"
                  @keydown.enter="detail = x"
                  @keydown.space.prevent="detail = x"
                >
                  <td>
                    <div class="flex items-center gap-1 flex-wrap">
                      <CryptoLogo :symbol="x.inst" :size="16" />
                      <span class="num font-mono font-semibold text-xs text-[var(--ink-strong)]">{{ x.inst }}</span>
                      <DirTag :dir="x.side" />
                      <span
                        class="rounded px-1 py-0.5 text-3xs font-mono border"
                        style="background-color: var(--surface-2); border-color: var(--line-1); color: var(--ink-2)"
                      >
                        {{ x.lever }}
                      </span>
                      <span
                        v-if="x.venue"
                        class="rounded px-1 py-0.5 text-3xs font-mono font-semibold uppercase border"
                        :class="venueToneCls(x.venue)"
                      >
                        {{ venueLabel(x.venue) }}
                      </span>
                      <span
                        v-if="x.council?.ran"
                        class="dsh-pill !h-5 !px-1 text-3xs"
                        :title="x.council.adopted_role ? t('dash.ledger.council.adopted', undefined, { seat: x.council.adopted_role }) : t('dash.ledger.council.ran')"
                      >
                        <Landmark class="w-3 h-3" />
                      </span>
                      <span
                        v-else-if="x.council"
                        class="dsh-pill !h-5 !px-1 text-3xs"
                        :title="t('dash.ledger.council.degraded')"
                      >
                        <Zap class="w-3 h-3" />
                      </span>
                      <!-- 数理快照异常标记：仅在快照不完整时提示，全部观测到时保持行面干净 -->
                      <span
                        v-if="obsTag(x) !== 'DYNAMICS_OBSERVED'"
                        class="rounded px-1.5 py-0.5 text-3xs font-medium border"
                        :class="obsToneCls(x)"
                        :title="`${obsLabel(x)} · ${t('dash.ledger.observability.missingFields')} ${t('dash.ledger.observability.noBackfill')}`"
                      >
                        {{ obsBadge(x) }}
                      </span>
                      <!-- 分批止盈状态徽章 -->
                      <span
                        v-if="isScaleOutRow(x)"
                        class="rounded px-1.5 py-0.5 text-3xs font-mono font-medium border text-[var(--accent)] border-[var(--accent-line)] bg-[var(--accent-bg)]"
                        :title="t('dash.ledger.scaleOutTitle')"
                      >
                        {{ t('dash.ledger.scaleOutShort') }}
                      </span>
                    </div>
                  </td>
                  <td class="col-num font-mono">
                    <span class="block text-xs font-medium text-[var(--ink-strong)]">{{ fmtPrice(x.open_px) }}</span>
                    <span class="block text-3xs" :class="x.status === 'holding' ? 'text-[var(--accent)] font-medium' : 'text-[var(--ink-3)]'">
                      {{ x.status === 'holding' ? t('status.running') : fmtPrice(x.close_px) }}
                    </span>
                  </td>
                  <td class="col-num font-mono" :class="dirClass(x.net_pnl)">
                    <span class="block font-medium">{{ arrow(x.net_pnl) }} {{ fmtSigned(x.net_pnl) }}</span>
                    <span class="block text-3xs text-[var(--ink-3)]">{{ fmtPct(x.roi_pct) }}</span>
                  </td>
                  <td class="col-num font-mono text-[var(--ink-2)]">
                    <span class="whitespace-nowrap">{{ fmtNum(Math.abs(Number(x.fee) || 0), 2) }}</span>
                    <span
                      v-if="Number(x.funding_fee || 0) !== 0"
                      class="block text-3xs whitespace-nowrap"
                      :class="Number(x.funding_fee) >= 0 ? 'text-[var(--up)]' : 'text-[var(--down)]'"
                    >
                      {{ t('dash.ledger.fundingTag') }} {{ Number(x.funding_fee) >= 0 ? '+' : '' }}{{ fmtNum(x.funding_fee, 2) }}
                    </span>
                  </td>
                  <td class="num font-mono text-3xs text-[var(--ink-2)]">{{ x.duration || '--' }}</td>
                  <td class="text-3xs text-[var(--ink-2)] max-w-48 truncate" :title="cleanReason(x.exit_reason)">
                    {{ cleanReason(x.exit_reason) }}
                  </td>
                  <td class="num font-mono text-3xs text-right text-[var(--ink-3)]">
                    {{ fmtDateTime(x.close_time).slice(5, 16) }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="border-t p-2" style="border-color: var(--line-1)">
            <BasePager v-model:page="page" :page-count="pageCount" :total="filtered.length" />
          </div>
        </template>
      </div>

      <!-- 巡检日志 -->
      <BaseCollapse>
        <template #head>
          <span class="flex items-center gap-2 text-xs font-semibold text-[var(--ink-strong)]">
            <ScrollText class="h-3.5 w-3.5 text-[var(--accent)]" />
            {{ t('dash.ledger.logs.title') }}
            <span class="text-3xs text-[var(--ink-3)] font-normal">{{ t('dash.ledger.logs.desc') }}</span>
          </span>
        </template>
        <div class="scroll-y max-h-80 p-2">
          <BaseEmpty v-if="!store.logs.length" :text="t('dash.ledger.logs.empty')" />
          <pre
            v-else
            class="rounded p-2.5 font-mono text-3xs leading-body whitespace-pre-wrap select-text"
            tabindex="0"
            style="background-color: var(--surface-input); border: 1px solid var(--line-1); color: var(--ink-2)"
          >{{ store.logs.join('\n') }}</pre>
        </div>
      </BaseCollapse>

      <!-- 订单生命周期穿透抽屉 -->
      <LedgerDrawer :trade="detail" @close="detail = null" />
    </DataGate>
  </div>
</template>
