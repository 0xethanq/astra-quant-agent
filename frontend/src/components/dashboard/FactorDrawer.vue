<script setup lang="ts">
import { pairLabel } from '../../utils/instId';
/** 因子详情抽屉：行情快照 / 动力学 / 聪明钱 / AI 裁决与理由 */
import { computed } from 'vue';
import { LineChart } from 'lucide-vue-next';
import BaseDrawer from '../base/BaseDrawer.vue';
import BaseCollapse from '../base/BaseCollapse.vue';
import BaseCodeBlock from '../base/BaseCodeBlock.vue';
import ConfBadge from '../base/ConfBadge.vue';
import DirTag from '../base/DirTag.vue';
import { useI18n } from '../../composables/useI18n';
import { fmtNum, fmtPct, fmtPrice, arrow, dirClass } from '../../utils/format';

const props = defineProps<{ factor: any | null }>();
const emit = defineEmits<{ (e: 'close'): void; (e: 'pick-symbol', instId: string): void }>();

const { t } = useI18n();
const f = computed(() => props.factor || {});
// 后端 /api/all 的因子对象里决策字段是平铺的（action/confidence/entry_price...），
// 没有嵌套 decision；保留 decision 优先以兼容未来结构变化。
const d = computed(() => f.value.decision || f.value);
const tp = computed(() => f.value.thought_process || {});

/** 后端行情字段可能是已格式化的字符串（"0.0054%"、"21.76亿 U"）或 N/A，直接透传展示 */
function asIs(v: unknown): string {
  if (v === null || v === undefined) return '--';
  const s = String(v).trim();
  if (!s || s === 'N/A' || s === '--') return '--';
  return s;
}

const action = computed(() => String(d.value.action || f.value.action || 'WAIT').toUpperCase());
const dir = computed<'long' | 'short' | 'flat'>(() =>
  action.value === 'BUY_LONG' ? 'long' : action.value === 'SELL_SHORT' ? 'short' : 'flat',
);

function row(label: string, value: string, cls = '', hint = '') {
  return { label, value, cls, hint };
}

// ★ 2026-10：MACD 是**价格单位**的量，两位小数会把低价币抹成 -0.00/0.00
// （实盘：ARB 柱 −1.8e−05、DOGE +9.3e−05，看着像"没有动能"）。
// ⇒ 主显示改用后端归一化口径「占现价 %」，绝对值放悬停提示里备查。
// 自适应精度：量级 < 0.01% 时多给一位，避免"零轴穿越附近"又显示成 0.0000%。
function macdPct(v: number | null | undefined): string {
  if (v === null || v === undefined) return '--';
  const n = Number(v);
  if (!Number.isFinite(n)) return '--';
  return `${fmtNum(n, Math.abs(n) < 0.01 ? 5 : 4)}%`;
}
const snapshot = computed(() => [
  row(t('dash.matrix.matrix.col.price'), fmtPrice(f.value.price)),
  row(t('dash.matrix.matrix.col.chg'), `${arrow(f.value.chg24h)} ${fmtPct(f.value.chg24h, 2, false)}`, dirClass(f.value.chg24h)),
  row('24h ' + t('dash.matrix.chart.vol'), f.value.vol24h != null ? fmtNum(f.value.vol24h, 0) : '--'),
  row('Funding', asIs(f.value.fundingRate)),
  row('OI', asIs(f.value.oiUsd)),
  row('L/S', asIs(f.value.lsRatio)),
]);
// ★ 2026-10：原 calculus 卡（v/a/jerk/impulse）随数理系统退场，
// 换成 7 梯队里真正会看的三张卡：MACD 动能 / 订单流 / 盘口深度。
const momentum = computed(() => [
  row(t('dash.matrix.matrix.col.vel') + ' (1H)', macdPct(f.value.momentum?.macd_hist_pct_1h),
      dirClass(f.value.momentum?.macd_hist_pct_1h),
      `${t('dash.matrix.matrix.macdNormalized')} · ${asIs(f.value.momentum?.macd_hist_1h)}`),
  row(t('dash.matrix.matrix.col.acc') + ' (1H)', macdPct(f.value.momentum?.macd_accel_pct_1h),
      dirClass(f.value.momentum?.macd_accel_pct_1h),
      `${t('dash.matrix.matrix.macdNormalized')} · ${asIs(f.value.momentum?.macd_accel_1h)}`),
  row(t('dash.matrix.matrix.momentumState'), asIs(f.value.momentum?.macd_momentum_state)),
  row(t('dash.matrix.matrix.divergence'), asIs(f.value.momentum?.macd_divergence)),
  row('RSI (1H)', fmtNum(f.value.momentum?.rsi_1h, 1), ''),
  row(t('dash.matrix.matrix.rsiZone'), asIs(f.value.momentum?.rsi_zone)),
  row('ADX', fmtNum(f.value.adx_1h, 1), ''),
  row('ATR%', fmtPct(f.value.atr_pct, 2, false), ''),
]);
const orderflow = computed(() => [
  row('5M CVD', fmtNum(f.value.orderflow?.cvd_5m_usd, 0), dirClass(f.value.orderflow?.cvd_5m_usd)),
  row('1H CVD', fmtNum(f.value.orderflow?.cvd_1h_usd, 0), dirClass(f.value.orderflow?.cvd_1h_usd)),
  row(t('dash.matrix.matrix.takerRatio'), fmtNum(f.value.orderflow?.taker_buy_sell_ratio, 3), ''),
  row(t('dash.matrix.matrix.cvdDivergence'), asIs(f.value.orderflow?.cvd_divergence)),
]);
const bookdepth = computed(() => [
  row('OBI', fmtPct(f.value.microstructure?.obi_pct, 1, false), dirClass(f.value.microstructure?.obi_pct)),
  row(t('dash.matrix.matrix.depthBias'), asIs(f.value.microstructure?.depth_bias)),
  row(t('dash.matrix.matrix.depthTop5'), fmtNum(f.value.microstructure?.bid_ask_depth_ratio, 2), ''),
  row(t('dash.matrix.matrix.spreadBps'), fmtNum(f.value.microstructure?.spread_bps, 2), ''),
  row('24H VWAP', fmtNum(f.value.value_area?.vwap_24h, 2), ''),
  row(t('dash.matrix.matrix.vwapBias'), fmtPct(f.value.value_area?.vwap_bias_pct, 2, false), dirClass(f.value.value_area?.vwap_bias_pct)),
  row(t('dash.matrix.matrix.poc'), fmtNum(f.value.value_area?.vpvr_poc, 2), ''),
  row(t('dash.matrix.matrix.valueArea'), asIs(f.value.value_area?.value_area_position)),
]);
const smart = computed(() => [
  row(t('dash.matrix.matrix.col.ls'), asIs(f.value.lsRatio)),
  row('Funding', asIs(f.value.fundingRate)),
  row('OI', asIs(f.value.oiUsd)),
]);


</script>

<template>
  <BaseDrawer
    :open="!!factor"
    width="620px"
    :title="t('dash.matrix.matrix.detailTitle', undefined, { sym: pairLabel(factor?.name || '') })"
    :subtitle="factor?.desc || ''"
    @close="emit('close')"
  >
    <template #actions>
      <button type="button" class="btn btn-ghost btn-sm" @click="factor && emit('pick-symbol', factor.instId)">
        <LineChart />{{ t('dash.matrix.chart.title') }}
      </button>
    </template>

    <div class="space-y-4">
      <!-- AI 裁决 -->
      <div class="card-flat p-3.5">
        <div class="flex flex-wrap items-center gap-2">
          <DirTag :dir="dir" />
          <ConfBadge :value="d.confidence" />
          <span v-if="d.risk_reward_ratio" class="badge num">R:R {{ d.risk_reward_ratio }}</span>
          <span v-if="d.leverage" class="badge num">{{ d.leverage }}x · {{ fmtNum(d.margin_usdt, 0) }} U</span>
        </div>
        <div v-if="dir !== 'flat'" class="mt-2.5 grid grid-cols-3 gap-2 text-center">
          <div>
            <p class="t-label">{{ t('dash.matrix.matrix.entry') }}</p>
            <p class="num text-sm font-semibold">{{ fmtPrice(d.entry_price) }}</p>
          </div>
          <div>
            <p class="t-label" style="color: var(--down)">{{ t('dash.matrix.matrix.sl') }}</p>
            <p class="num down text-sm font-semibold">{{ fmtPrice(d.stop_loss_price) }}</p>
          </div>
          <div>
            <p class="t-label" style="color: var(--up)">{{ t('dash.matrix.matrix.tp') }}</p>
            <p class="num up text-sm font-semibold">{{ fmtPrice(d.take_profit_price) }}</p>
          </div>
        </div>
        <p v-else class="t-muted mt-2 text-xs">{{ t('dash.matrix.matrix.noDecision') }}</p>
        <p v-if="d.summary_reason || f.reason" class="mt-2.5 border-t pt-2.5 text-xs leading-body" style="color: var(--ink-2); border-color: var(--line-1)">
          <!-- 2026-10 三态徽章：同样的「观望」文案背后可能是三种完全不同的原因，
               不标出来就没法判断"系统在等"还是"系统在拦"还是"模型没答"。 -->
          <span
            v-if="d.decision_source === 'omitted'"
            class="badge badge-warn mr-1.5 align-middle"
            :title="t('dash.matrix.matrix.sourceOmitted')"
          >{{ t('dash.matrix.matrix.sourceOmitted') }}</span>
          <span
            v-else-if="d.gate_blocked"
            class="badge badge-down mr-1.5 align-middle"
          >{{ t('dash.matrix.matrix.sourceGateBlocked') }}</span>
          <span
            v-else-if="(d.action || f.action) === 'WAIT'"
            class="badge mr-1.5 align-middle"
            :title="t('dash.matrix.matrix.sourceModelWait')"
          >{{ t('dash.matrix.matrix.sourceModelWait') }}</span>
          {{ d.summary_reason || f.reason }}
        </p>
      </div>

      <!-- 数据组 -->
      <div class="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div v-for="grp in [
          { title: t('dash.matrix.matrix.market'), items: snapshot },
          { title: t('dash.matrix.matrix.momentum'), items: momentum },
          { title: t('dash.matrix.matrix.orderflow'), items: orderflow },
          { title: t('dash.matrix.matrix.microstructure'), items: bookdepth },
        ]" :key="grp.title" class="card-flat p-3">
          <p class="t-label mb-2">{{ grp.title }}</p>
          <dl class="space-y-1.5">
            <div v-for="r in grp.items" :key="r.label" class="flex items-baseline justify-between gap-3 text-xs">
              <dt style="color: var(--ink-3)" :title="r.hint || undefined">{{ r.label }}</dt>
              <dd class="num font-semibold" :class="r.cls" style="color: var(--ink-1)"
                  :title="r.hint || undefined">{{ r.value }}</dd>
            </div>
          </dl>
        </div>
      </div>

      

      <div class="card-flat p-3">
        <p class="t-label mb-2">{{ t('dash.news.smart.title') }} · OKX</p>
        <dl class="grid grid-cols-3 gap-2 text-center">
          <div v-for="r in smart" :key="r.label">
            <dt class="t-label truncate">{{ r.label }}</dt>
            <dd class="num text-sm font-semibold" :class="r.cls">{{ r.value }}</dd>
          </div>
        </dl>
      </div>

      <!-- 推演过程 -->
      <BaseCollapse v-if="Object.keys(tp).length">
        <template #head><span class="text-sm font-medium">{{ t('dash.radar.detail.verdict') }} · thought_process</span></template>
        <div class="space-y-2.5 p-3.5">
          <div v-for="(v, k) in tp" :key="k">
            <p class="t-label">{{ k }}</p>
            <p class="text-xs leading-body" style="color: var(--ink-2)">{{ v }}</p>
          </div>
        </div>
      </BaseCollapse>

      <BaseCollapse>
        <template #head><span class="text-sm font-medium" style="color: var(--ink-2)">{{ t('dash.radar.detail.raw') }}</span></template>
        <div class="p-2"><BaseCodeBlock :code="JSON.stringify(factor, null, 2)" max-height="300px" /></div>
      </BaseCollapse>
    </div>
  </BaseDrawer>
</template>
