<script setup lang="ts">
/**
 * LedgerDrawer.vue · AstraQuant 单笔订单全生命周期穿透抽屉
 * 穿透展示：开平仓生命周期轨迹、费用精细构成、多维度盈亏归因、AI 委员会席位采纳溯源
 */
import { computed } from 'vue';
import { fmtDateTime, fmtNum, fmtSigned, fmtPct, fmtPrice, fmtUsdt, dirClass, cleanReason } from '../../utils/format';
import { pairLabel } from '../../utils/instId';
import { useI18n } from '../../composables/useI18n';
import {
  Coins,
  Landmark,
  Activity,
} from 'lucide-vue-next';
import BaseDrawer from '../base/BaseDrawer.vue';
import DirTag from '../base/DirTag.vue';
import CryptoLogo from './CryptoLogo.vue';

const props = defineProps<{ trade: any | null }>();
const emit = defineEmits<{ (e: 'close'): void }>();
const { t } = useI18n();

const x = computed(() => props.trade || {});
const holding = computed(() => x.value.status === 'holding');

/** 投委会溯源 */
/**
 * 席位展示名（批 41）。**完整键路径**查表，与雷达抽屉共用 `dash.radar.seat.*`
 * —— 同一个席位在两处必须同名，此前这里写死中文、雷达抽屉走 locale，
 * 英文界面下台账抽屉显示「A·顺势交易员」。未登记 id 原样透出。
 */
const SEAT_TEXT_KEY: Record<string, string> = {
  trader_trend: 'dash.radar.seat.traderTrend',
  trader_momentum: 'dash.radar.seat.traderMomentum',
  trader_quant: 'dash.radar.seat.traderQuant',
  cio: 'dash.radar.seat.cio',
  REJECT_ALL: 'dash.radar.seat.rejectAll',
};
function seatLabel(id: unknown): string {
  const raw = String(id ?? '');
  const key = SEAT_TEXT_KEY[raw];
  return key ? t(key, raw) : raw;
}

const councilNote = computed(() => {
  const cc = x.value.council;
  if (!cc || !holding.value) return '';
  if (!cc.ran) return t('dash.ledger.council.degraded');
  const seat = seatLabel(cc.adopted_role);
  return seat ? t('dash.ledger.council.adopted', undefined, { seat }) : t('dash.ledger.council.ran');
});

function feeAbs(v: unknown): string {
  if (v === null || v === undefined || v === '') return '--';
  const n = Number(v);
  return Number.isNaN(n) ? '--' : fmtNum(Math.abs(n), 4);
}

function feeSigned(v: unknown): string {
  const a = feeAbs(v);
  if (a === '--') return '--';
  // 批 24：0 不加负号 —— 否则「手续费 0」会渲染成 `-0.0000`（负零）
  return Number(a.replace(/,/g, '')) === 0 ? a : `-${a}`;
}

/* —— 数理快照可观测性（证据纪律）——
 * 与台账表格同源：后端逐单判定的 snapshot_observability。
 * PRICE_ONLY / NONE = 数理快照不可观测 —— 抽屉必须把「本笔未记录哪些量」和
 * 「禁止倒推编造」讲清楚，而不是留白（留白会被误读成「没有异常」）。 */
const obsTag = computed<string>(() => {
  const v = String(x.value?.snapshot_observability || 'NONE').toUpperCase();
  return ['DYNAMICS_OBSERVED', 'PARTIAL', 'PRICE_ONLY', 'NONE'].includes(v) ? v : 'NONE';
});
const obsUnobservable = computed(() => obsTag.value === 'NONE' || obsTag.value === 'PRICE_ONLY');

const isScaleOut = computed(() => {
  const row = x.value;
  return Number(row?.scale_out_phase || 0) >= 1
    || String(row?.action_type || '').includes('分批')
    || String(row?.side || '').includes('分批')
    || String(row?.exit_reason || '').includes('分批');
});
const obsLabel = computed(() => {
  if (obsTag.value === 'DYNAMICS_OBSERVED') return t('dash.ledger.observability.observed');
  if (obsTag.value === 'PARTIAL') return t('dash.ledger.observability.partial');
  if (obsTag.value === 'PRICE_ONLY') return t('dash.ledger.observability.priceOnly');
  return t('dash.ledger.observability.none');
});

function formatExitReason(row: any): string {
  if (!row) return '--';
  const cause = String(row.exit_cause || '');
  if (cause === 'time_stop' || cause.includes('时间止损')) return t('dash.ledger.exitReasons.timeout');
  if (cause === 'ratchet_lock' || cause.includes('阶梯锁利')) return t('dash.ledger.exitReasons.ratchetLock');
  if (cause === 'momentum_tp' || cause.includes('移动止盈')) return t('dash.ledger.exitReasons.momentumTp');
  if (cause === 'scale_out' || cause.includes('分批止盈')) return t('dash.ledger.exitReasons.scaleOut');
  if (cause === 'hard_stop' || cause.includes('硬止损')) return t('dash.ledger.exitReasons.sl');
  if (cause === 'breakeven' || cause.includes('保本平仓')) return t('dash.ledger.exitReasons.be');
  if (cause === 'ai_close' || cause.includes('AI 主动')) return t('dash.ledger.exitReasons.aiClose');
  if (cause === 'protection_fail' || cause.includes('保护失效')) return t('dash.ledger.exitReasons.protectionFail');
  if (cause === 'exchange_closed') return Number(row.net_pnl || 0) > 0 ? t('dash.ledger.exitReasons.tp') : t('dash.ledger.exitReasons.sl');
  const raw = cleanReason(row.exit_reason);
  if (raw === '止盈推定' || raw.includes('止盈推定')) return t('dash.ledger.exitReasons.inferredTp');
  if (raw === '止损推定' || raw.includes('止损推定')) return t('dash.ledger.exitReasons.inferredSl');
  return raw;
}

const snap = computed<Record<string, any> | null>(() => {
  const s = x.value?.entry_snapshot || x.value?.signal_snapshot || x.value?.snapshot;
  return s && typeof s === 'object' ? s : null;
});

const cells = computed(() => [
  { label: t('dash.ledger.col.entry'), value: fmtPrice(x.value.open_px), cls: 'text-[var(--ink-strong)]' },
  { label: t('dash.ledger.col.exit'), value: holding.value ? t('status.running') : fmtPrice(x.value.close_px), cls: holding.value ? 'text-[var(--ink-3)]' : 'text-[var(--ink-strong)]' },
  { label: t('dash.matrix.positions.col.margin'), value: fmtNum(x.value.margin, 2) + ' U', cls: 'text-[var(--ink-strong)]' },
  {
    // ⚠️ 2026-09-28 用户拍板：台账也**不再显示原生数量**（`x.sz`）。
    // 各币种的合约面值算法各不相同（BTC 一张 0.01 币、XRP 一张 100 币），
    // 用户看到的数字既不能跨币种比，量纲也不统一。
    // 改为**名义价值**（= 保证金 × 杠杆，纯钱、跨币种可比），
    // 台账行里 `margin`/`lever` 两个字段本来就有，无需改数据结构。
    label: t('dash.ledger.col.qty'),
    value: (() => {
      const m = Number(x.value.margin);
      const lv = Number(String(x.value.lever ?? '').replace('x', ''));
      if (!Number.isFinite(m) || m <= 0) return '--';
      if (!Number.isFinite(lv) || lv <= 0) return '--';
      return fmtNum(m * lv, 2) + ' U';
    })(),
    cls: 'text-[var(--ink-strong)]',
  },
  { label: t('dash.ledger.lifecycle.grossPnl'), value: fmtSigned(x.value.gross_pnl), cls: dirClass(x.value.gross_pnl) },
  { label: t('dash.ledger.lifecycle.netPnl'), value: fmtSigned(x.value.net_pnl), cls: dirClass(x.value.net_pnl) },
  { label: t('dash.ledger.col.roi'), value: fmtPct(x.value.roi_pct), cls: dirClass(x.value.roi_pct) },
  { label: t('dash.ledger.col.fees'), value: feeSigned(x.value.fee), cls: feeSigned(x.value.fee) === '--' ? 'text-[var(--ink-3)]' : 'text-[var(--down)]' },
]);
</script>

<template>
  <BaseDrawer
    :open="!!trade"
    width="580px"
    :title="t('dash.ledger.lifecycle.title', undefined, { sym: pairLabel(x.inst || ''), dir: x.side || '' })"
    :subtitle="`${x.strategy || 'Momentum'} · ${x.lever || '10x'}${councilNote ? ' · ' + councilNote : ''}`"
    @close="emit('close')"
  >
    <div class="space-y-3.5">
      <!-- 订单状态与生命周期总览 -->
      <div class="dsh-card-sub p-3.5">
        <div class="flex items-center justify-between gap-2 border-b pb-2.5" style="border-color: var(--line-1)">
          <div class="flex items-center gap-2">
            <CryptoLogo :symbol="x.inst" :size="20" />
            <span class="text-sm font-bold font-mono text-[var(--ink-strong)]">{{ x.inst }}</span>
            <DirTag :dir="x.side" />
            <span
              class="rounded px-1.5 py-0.5 border text-3xs font-mono font-semibold"
              style="background-color: var(--surface-2); border-color: var(--line-1); color: var(--ink-2)"
            >
              {{ x.lever || '10x' }}
            </span>
          </div>
          <div class="flex items-center gap-1.5">
            <span
              v-if="isScaleOut"
              class="rounded px-1.5 py-0.5 text-3xs font-semibold border text-[var(--accent)] border-[var(--accent-line)] bg-[var(--accent-bg)]"
            >
              🎯 {{ t('dash.ledger.scaleOutBadge') }}
            </span>
            <span
              class="rounded px-1.5 py-0.5 text-3xs font-semibold uppercase border"
              :class="holding ? 'text-[var(--warn)] border-[var(--warn-line)] bg-[var(--warn-bg)]' : 'text-[var(--ink-2)] border-[var(--line-1)] bg-[var(--surface-2)]'"
            >
              {{ holding ? t('status.running') : t('dash.ledger.status.closed') }}
            </span>
          </div>
        </div>

        <!-- 生命周期时间线 -->
        <div class="mt-3 grid grid-cols-2 gap-3 text-xs">
          <div>
            <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.lifecycle.open') }}</span>
            <span class="num font-mono font-medium text-[var(--ink-1)] mt-0.5 block">{{ fmtDateTime(x.open_time) }}</span>
          </div>
          <div>
            <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.lifecycle.close') }}</span>
            <span class="num font-mono font-medium text-[var(--ink-1)] mt-0.5 block">{{ holding ? '--' : fmtDateTime(x.close_time) }}</span>
          </div>
          <div>
            <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.col.hold') }}</span>
            <span class="num font-mono font-medium text-[var(--ink-1)] mt-0.5 block">{{ x.duration || '--' }}</span>
          </div>
          <div>
            <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.col.exitReason') }}</span>
            <span class="text-[var(--ink-1)] mt-0.5 block leading-snug font-medium">{{ formatExitReason(x) }}</span>
          </div>
        </div>
      </div>

      <!-- 数理快照可观测性（证据纪律：明确标注「不可观测」，严禁倒推编造） -->
      <div class="dsh-card-sub p-3.5 space-y-2.5">
        <div class="flex items-center justify-between gap-2">
          <h4 class="text-3xs font-bold uppercase tracking-wider text-[var(--ink-3)] flex items-center gap-1.5">
            <Activity class="h-3 w-3 text-[var(--accent)]" />
            {{ t('dash.ledger.observability.title') }}
          </h4>
          <span
            class="rounded px-1.5 py-0.5 text-3xs font-semibold border"
            :class="obsUnobservable
              ? 'text-[var(--ink-2)] border-[var(--line-1)] bg-[var(--surface-2)]'
              : 'text-[var(--up)] border-[var(--up-line)] bg-[var(--up-bg)]'"
          >
            {{ obsLabel }}
          </span>
        </div>

        <template v-if="obsUnobservable">
          <p class="text-3xs leading-body text-[var(--ink-2)]">
            {{ t('dash.ledger.observability.missingFields') }}
          </p>
          <p class="text-3xs leading-body text-[var(--ink-3)]">
            {{ t('dash.ledger.observability.noBackfill') }}
          </p>
        </template>

        <template v-else-if="snap">
          <p class="text-3xs text-[var(--ink-3)] leading-body">
            {{ t('dash.ledger.observability.observedDesc') }}
          </p>

          <!-- 因子状态徽章带（★ 2026-10：原 regime/power_regime/dynamics_quality/fat_tail
               均属已退役的数理链，改为现行 7 梯队因子的状态枚举） -->
          <div
            v-if="snap.macd_momentum_state || snap.rsi_zone || snap.oi_price_quadrant || snap.funding_crowding"
            class="flex flex-wrap items-center gap-1.5 pt-0.5"
          >
            <span
              v-if="snap.macd_momentum_state"
              class="rounded px-1.5 py-0.5 border text-3xs font-mono font-medium text-[var(--up)] border-[var(--up-line)] bg-[var(--up-bg)]"
            >
              MACD: {{ snap.macd_momentum_state }}
            </span>
            <span
              v-if="snap.rsi_zone"
              class="rounded px-1.5 py-0.5 border text-3xs font-mono font-medium text-[var(--accent)] border-[var(--line-1)] bg-[var(--surface-2)]"
            >
              RSI: {{ snap.rsi_zone }}
            </span>
            <span
              v-if="snap.macd_divergence && snap.macd_divergence !== 'NONE'"
              class="rounded px-1.5 py-0.5 border text-3xs font-mono text-[var(--ink-2)] border-[var(--line-1)] bg-[var(--surface-2)]"
            >
              {{ t('dash.ledger.observability.macdDivergence') }}: {{ snap.macd_divergence }}
            </span>
            <span
              v-if="snap.oi_price_quadrant"
              class="rounded px-1.5 py-0.5 border text-3xs font-mono text-[var(--ink-2)] border-[var(--line-1)] bg-[var(--surface-2)]"
            >
              {{ t('dash.ledger.observability.oiQuadrant') }}: {{ snap.oi_price_quadrant }}
            </span>
            <span
              v-if="snap.funding_crowding"
              class="rounded px-1.5 py-0.5 border text-3xs font-mono text-[var(--ink-2)] border-[var(--line-1)] bg-[var(--surface-2)]"
            >
              {{ t('dash.ledger.observability.fundingCrowding') }}: {{ snap.funding_crowding }}
            </span>
            <span
              v-if="snap.value_area_position"
              class="rounded px-1.5 py-0.5 border text-3xs font-mono text-[var(--ink-2)] border-[var(--line-1)] bg-[var(--surface-2)]"
            >
              {{ snap.value_area_position }}
            </span>
          </div>

          <!-- 7 梯队因子网格（★ 2026-10 替换原「微积分 + 定积分 + 概率极值」网格） -->
          <div class="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-1">
            <div class="rounded border p-2 bg-[var(--surface-1)] border-[var(--line-1)]">
              <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.observability.macdHist') }}</span>
              <span class="num font-mono font-bold text-xs mt-0.5 block" :class="dirClass(snap.macd_hist)">
                {{ snap.macd_hist != null ? fmtNum(snap.macd_hist, 4) : '--' }}
              </span>
            </div>
            <div class="rounded border p-2 bg-[var(--surface-1)] border-[var(--line-1)]">
              <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.observability.macdAccel') }}</span>
              <span class="num font-mono font-bold text-xs mt-0.5 block" :class="dirClass(snap.macd_accel)">
                {{ snap.macd_accel != null ? fmtNum(snap.macd_accel, 4) : '--' }}
              </span>
            </div>
            <div class="rounded border p-2 bg-[var(--surface-1)] border-[var(--line-1)]">
              <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.observability.rsi1h') }}</span>
              <span class="num font-mono font-bold text-xs mt-0.5 block text-[var(--ink-strong)]">
                {{ snap.rsi_1h != null ? fmtNum(snap.rsi_1h, 1) : '--' }}
              </span>
            </div>
            <div class="rounded border p-2 bg-[var(--surface-1)] border-[var(--line-1)]">
              <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.observability.cvd1h') }}</span>
              <span class="num font-mono font-bold text-xs mt-0.5 block" :class="dirClass(snap.cvd_1h_usd)">
                {{ snap.cvd_1h_usd != null ? fmtUsdt(snap.cvd_1h_usd, 0) : '--' }}
              </span>
            </div>
            <div class="rounded border p-2 bg-[var(--surface-1)] border-[var(--line-1)]">
              <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.observability.takerRatio') }}</span>
              <span class="num font-mono font-bold text-xs mt-0.5 block text-[var(--ink-strong)]">
                {{ snap.taker_buy_sell_ratio != null ? fmtNum(snap.taker_buy_sell_ratio, 3) : '--' }}
              </span>
            </div>
            <div class="rounded border p-2 bg-[var(--surface-1)] border-[var(--line-1)]">
              <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.observability.obi') }}</span>
              <span class="num font-mono font-bold text-xs mt-0.5 block" :class="dirClass(snap.obi_pct)">
                {{ snap.obi_pct != null ? fmtNum(snap.obi_pct, 1) + '%' : '--' }}
              </span>
            </div>
            <div class="rounded border p-2 bg-[var(--surface-1)] border-[var(--line-1)]">
              <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.observability.vwapBias') }}</span>
              <span class="num font-mono font-bold text-xs mt-0.5 block" :class="dirClass(snap.vwap_bias_pct)">
                {{ snap.vwap_bias_pct != null ? fmtNum(snap.vwap_bias_pct, 2) + '%' : '--' }}
              </span>
            </div>
            <div class="rounded border p-2 bg-[var(--surface-1)] border-[var(--line-1)]">
              <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.observability.vpvrPoc') }}</span>
              <span class="num font-mono font-bold text-xs mt-0.5 block text-[var(--ink-strong)]">
                {{ snap.vpvr_poc != null ? fmtPrice(snap.vpvr_poc) : '--' }}
              </span>
            </div>
            <div class="rounded border p-2 bg-[var(--surface-1)] border-[var(--line-1)]">
              <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.observability.fundingRate') }}</span>
              <span class="num font-mono font-bold text-xs mt-0.5 block text-[var(--ink-strong)]">
                {{ snap.funding_rate_pct != null ? fmtNum(snap.funding_rate_pct, 4) + '%' : '--' }}
              </span>
            </div>
            <div class="rounded border p-2 bg-[var(--surface-1)] border-[var(--line-1)]">
              <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.observability.oiChange') }}</span>
              <span class="num font-mono font-bold text-xs mt-0.5 block" :class="dirClass(snap.oi_chg_1h_pct)">
                {{ snap.oi_chg_1h_pct != null ? fmtNum(snap.oi_chg_1h_pct, 3) + '%' : '--' }}
              </span>
            </div>
            <div class="rounded border p-2 bg-[var(--surface-1)] border-[var(--line-1)]">
              <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.observability.eliteDivergence') }}</span>
              <span class="num font-mono font-bold text-2xs mt-0.5 block text-[var(--ink-strong)]">
                {{ snap.elite_divergence || '--' }}
              </span>
            </div>
            <div class="rounded border p-2 bg-[var(--surface-1)] border-[var(--line-1)]">
              <span class="text-3xs text-[var(--ink-3)] block">{{ t('dash.ledger.observability.basisAnnualized') }}</span>
              <span class="num font-mono font-bold text-xs mt-0.5 block text-[var(--ink-strong)]">
                {{ snap.basis_annualized_pct != null ? fmtNum(snap.basis_annualized_pct, 3) + '%' : '--' }}
              </span>
            </div>
          </div>
        </template>
      </div>

      <!-- 8 核心财务指标矩阵 -->
      <div>
        <h4 class="text-3xs font-bold uppercase tracking-wider text-[var(--ink-3)] mb-1.5">
          {{ t('dash.ledger.lifecycle.metricsTitle') }}
        </h4>
        <div class="grid grid-cols-2 gap-2 sm:grid-cols-4">
          <div
            v-for="c in cells"
            :key="c.label"
            class="dsh-card-sub px-3 py-2"
          >
            <p class="text-3xs text-[var(--ink-3)] truncate">{{ c.label }}</p>
            <p class="num font-mono mt-0.5 text-xs font-bold" :class="c.cls">{{ c.value }}</p>
          </div>
        </div>
      </div>

      <!-- 费用构成明细 -->
      <div class="dsh-card-sub p-3.5">
        <h4 class="text-3xs font-bold uppercase tracking-wider text-[var(--ink-3)] mb-2 flex items-center gap-1.5">
          <Coins class="h-3 w-3 text-[var(--accent)]" />
          {{ t('dash.ledger.lifecycle.feesBreak') }}
        </h4>
        <dl class="space-y-1.5 text-xs">
          <div class="flex justify-between items-center">
            <dt class="text-[var(--ink-3)]">{{ t('dash.ledger.lifecycle.makerFee') }} (Open)</dt>
            <dd class="num font-mono" :class="feeAbs(x.open_fee) === '--' ? 'text-[var(--ink-3)]' : 'text-[var(--down)]'">
              {{ feeAbs(x.open_fee) }}
            </dd>
          </div>
          <div class="flex justify-between items-center">
            <dt class="text-[var(--ink-3)]">{{ t('dash.ledger.lifecycle.takerFee') }} (Close)</dt>
            <dd class="num font-mono" :class="feeAbs(x.close_fee) === '--' ? 'text-[var(--ink-3)]' : 'text-[var(--down)]'">
              {{ feeAbs(x.close_fee) }}
            </dd>
          </div>
          <div v-if="x.funding_fee !== undefined" class="flex justify-between items-center">
            <dt class="text-[var(--ink-3)]">{{ t('dash.ledger.fundingTag') }} (Funding Fee)</dt>
            <dd
              class="num font-mono"
              :class="Number(x.funding_fee || 0) >= 0 ? 'text-[var(--up)]' : 'text-[var(--down)]'"
            >
              {{ Number(x.funding_fee || 0) >= 0 ? '+' : '' }}{{ fmtNum(x.funding_fee, 4) }}
            </dd>
          </div>
          <div class="flex justify-between items-center border-t pt-2" style="border-color: var(--line-1)">
            <dt class="font-bold text-[var(--ink-1)]">{{ t('dash.ledger.lifecycle.totalFees') }}</dt>
            <dd class="num font-mono font-bold" :class="feeAbs(x.fee) === '--' ? 'text-[var(--ink-3)]' : 'text-[var(--down)]'">
              {{ feeAbs(x.fee) }}
            </dd>
          </div>
        </dl>
      </div>

      <!-- 投委会溯源与策略信息 -->
      <div v-if="x.council || x.strategy" class="dsh-card-sub p-3.5">
        <h4 class="text-3xs font-bold uppercase tracking-wider text-[var(--ink-3)] mb-2 flex items-center gap-1.5">
          <Landmark class="h-3 w-3 text-[var(--accent)]" />
          {{ t('dash.ledger.councilSource') }}
        </h4>
        <div class="space-y-2 text-xs">
          <div class="flex items-center justify-between">
            <span class="text-[var(--ink-3)]">{{ t('dash.ledger.execStrategy') }}</span>
            <span class="font-mono font-semibold text-[var(--ink-1)]">{{ x.strategy || 'Momentum Alpha' }}</span>
          </div>
          <div v-if="x.council?.adopted_role" class="flex items-center justify-between">
            <span class="text-[var(--ink-3)]">{{ t('dash.ledger.adoptedSeat') }}</span>
            <span class="font-mono font-semibold text-[var(--up)]">
              {{ seatLabel(x.council.adopted_role) }}
            </span>
          </div>
          <div v-if="councilNote" class="text-3xs text-[var(--ink-2)] rounded p-2" style="background-color: var(--surface-2)">
            {{ councilNote }}
          </div>
        </div>
      </div>
    </div>
  </BaseDrawer>
</template>
