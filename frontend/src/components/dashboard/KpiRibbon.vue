<script setup lang="ts">
/**
 * KpiRibbon.vue · DeepSeek Harness 风格核心指标仪表盘
 * 纯净低饱和黑白/深灰主题，分层卡片结构，呈现 OKX 账户总权益、走势、浮亏与防线
 */
import { computed, onMounted, ref } from 'vue';
import { ShieldCheck } from 'lucide-vue-next';
import { useDashboardStore } from '../../stores/dashboard';
import { useI18n } from '../../composables/useI18n';
import { fmtNum, fmtSigned, fmtPct, arrow } from '../../utils/format';
import BaseStat from '../base/BaseStat.vue';
import BaseSparkline from '../base/BaseSparkline.vue';

const store = useDashboardStore();
const { t } = useI18n();

const account = computed(() => store.data?.account || ({} as any));
const today = computed(() => (store.data as any)?.today_stats || {});

/* ── 账户总权益：OKX 单所快照 ────────────────────────────────────────────────
 * 系统已收口为 OKX 专用，`/api/all` 的 `account` 段就是 OKX 当前档（模拟盘 /
 * 实盘）的读数，不再有第二家交易所可以混进来。缺值一律按「未知」处理：
 * 显示 `--`，**绝不以 0 冒充未知**。
 * ────────────────────────────────────────────────────────────────────────── */
const totalEquityNum = computed<number | null>(() => {
  const one = Number(account.value.total_eq || 0);
  return one > 0 ? one : null;
});

/** 单位以文本后缀形式给出（读作 "1234.00 U"）—— 绝不用 "$" 前缀冒充币种。 */
const totalEquity = computed(() =>
  totalEquityNum.value === null ? '--' : `${fmtNum(totalEquityNum.value, 2)} U`,
);

const todayNet = computed(() => Number(today.value.net_realized ?? today.value.total_pnl ?? 0));
const todayTrades = computed(() => Number(today.value.win_trades ?? 0) + Number(today.value.loss_trades ?? 0));
const todayWinRate = computed(() => {
  const w = Number(today.value.win_trades ?? 0);
  const n = todayTrades.value;
  return n > 0 ? Math.round((w / n) * 100) : null;
});

const floatPnl = computed(() => Number(account.value.pos_upl_total ?? account.value.upl ?? 0));
const posMargin = computed(() =>
  store.positions.reduce((s, p: any) => s + (Number(p.margin_usdt ?? p.margin ?? 0) || 0), 0),
);
const floatRoi = computed(() =>
  posMargin.value > 0 ? (floatPnl.value / posMargin.value) * 100 : 0,
);

const longCount = computed(() => store.positions.filter((p) => p.side === 'long').length);
const shortCount = computed(() => store.positions.filter((p) => p.side === 'short').length);

const actualMarginUsed = computed(() => {
  if (posMargin.value > 0) return posMargin.value;
  return Number(account.value.total_pos_margin || 0);
});

const marginUsage = computed(() => {
  const eq = totalEquityNum.value;
  if (eq !== null && eq > 0) {
    return Math.round((actualMarginUsed.value / eq) * 1000) / 10;
  }
  return 0;
});

const ocoCoverage = computed(() => {
  const total = store.positions.length;
  if (!total) return { pct: 100, missing: 0 };
  const ok = store.positions.filter((p: any) => p.cloud_oco_verified !== false && p.protectionStatus !== 'unprotected').length;
  return { pct: Math.round((ok / total) * 100), missing: total - ok };
});

/* 14 日净值走势 */
const eqSeries = ref<number[]>([]);
onMounted(async () => {
  try {
    const r = await fetch('/api/v1/equity_history?days=14');
    const d = await r.json();
    eqSeries.value = (d.days || []).map((x: any) => Number(x.equity)).filter((n: number) => Number.isFinite(n));
  } catch {
    /* sparkline optional */
  }
});
</script>

<template>
  <div class="dsh-card">
    <!-- 6 个核心指标单元格 -->
    <div class="grid grid-cols-2 gap-2 p-2 sm:grid-cols-3 xl:grid-cols-6 bg-[var(--surface-1)]">
      <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors flex flex-col justify-between">
        <BaseStat
          :label="t('dash.matrix.kpi.equity')"
          :value="totalEquity"
          :hint="totalEquityNum === null ? t('dash.matrix.kpi.equityEmpty') : t('dash.matrix.kpi.equityTip')"
        >
          <!-- 今日盈亏与净值走势取自**后端交易轴**（OKX 台账）。总权益未知时这一行
               整块不渲染；今日盈亏本身在下方的「今日已实现」有专格。 -->
          <template v-if="totalEquityNum !== null" #extra>
            <div class="flex items-center gap-2 mt-1">
              <span class="num text-xs font-semibold" :class="todayNet >= 0 ? 'up' : 'down'">
                {{ arrow(todayNet) }} {{ fmtSigned(todayNet) }}
              </span>
              <BaseSparkline :values="eqSeries" :width="48" :height="18" />
            </div>
          </template>
        </BaseStat>
      </div>

      <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors flex flex-col justify-between">
        <BaseStat
          :label="t('dash.matrix.kpi.todayPnl')"
          :value="fmtSigned(todayNet)"
          :delta="todayTrades ? `${todayTrades} ${t('common.unitCount')} · ${todayWinRate}%` : undefined"
          :delta-tone="todayWinRate === null ? 'muted' : todayWinRate >= 50 ? 'up' : 'down'"
          :hint="t('dash.matrix.kpi.todayTip')"
        />
      </div>

      <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors flex flex-col justify-between">
        <BaseStat
          :label="t('dash.matrix.kpi.floatPnl')"
          :value="fmtSigned(floatPnl)"
          :delta="store.positions.length ? `(${fmtPct(floatRoi)})` : '--'"
          :delta-tone="floatPnl >= 0 ? 'up' : 'down'"
          :hint="t('dash.matrix.kpi.floatTip')"
        />
      </div>

      <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors flex flex-col justify-between">
        <BaseStat
          :label="t('dash.matrix.kpi.ls')"
          :value="`${longCount} / ${shortCount}`"
          hint="L / S"
        />
      </div>

      <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors flex flex-col justify-between">
        <BaseStat
          :label="t('dash.matrix.kpi.margin')"
          :value="`${fmtNum(marginUsage, 1)}%`"
          :delta="actualMarginUsed > 0 ? `${fmtNum(actualMarginUsed, 2)} U` : '0.00 U'"
          :delta-tone="marginUsage > 70 ? 'down' : marginUsage > 30 ? 'warn' : 'muted'"
          :hint="t('dash.matrix.kpi.marginTip')"
        />
      </div>

      <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors flex flex-col justify-between">
        <BaseStat
          :label="t('dash.matrix.kpi.oco')"
          :value="`${ocoCoverage.pct}%`"
          :delta="ocoCoverage.missing ? t('dash.matrix.kpi.missN', undefined, { n: ocoCoverage.missing }) : t('dash.matrix.kpi.allCovered')"
          :delta-tone="ocoCoverage.pct === 100 ? 'up' : 'warn'"
          :hint="t('dash.matrix.kpi.ocoTip')"
        >
          <template #extra>
            <ShieldCheck class="h-4 w-4 shrink-0 mt-1" :style="{ color: ocoCoverage.pct === 100 ? 'var(--up)' : 'var(--warn)' }" />
          </template>
        </BaseStat>
      </div>
    </div>
  </div>
</template>
