<script setup lang="ts">
/**
 * CouncilVerdictRail.vue · 实盘工作台右侧 AI 投委会最新裁决轨
 * 与 ChartWorkstation / PositionsOrdersPanel 同屏组成 70/30 机构级发丝线主工位
 */
import { computed } from 'vue';
import { ChevronRight } from 'lucide-vue-next';
import { useDashboardStore } from '../../stores/dashboard';
import { useI18n } from '../../composables/useI18n';
import { fmtHM, parseTime } from '../../utils/format';
import { symOf } from '../../utils/instId';
import BaseEmpty from '../base/BaseEmpty.vue';
import DirTag from '../base/DirTag.vue';
import ConfBadge from '../base/ConfBadge.vue';
import CryptoLogo from './CryptoLogo.vue';

const emit = defineEmits<{ (e: 'open-cycle', cycle: any): void }>();

const store = useDashboardStore();
const { t } = useI18n();

const latestCycle = computed<any>(() => {
  const hist = (store.data as any)?.ai_brain_history;
  return Array.isArray(hist) && hist.length > 0 ? hist[0] : null;
});

const aiHealth = computed<any>(() => (store.data as any)?.ai_health || null);

const cycleHm = computed(() => {
  if (!latestCycle.value?.time) return '--';
  const d = parseTime(latestCycle.value.time);
  return Number.isNaN(d.getTime()) ? String(latestCycle.value.time).slice(11, 16) : fmtHM(d);
});

const signals = computed(() => {
  const c = latestCycle.value;
  if (!c) return [] as { inst: string; dir: 'long' | 'short' | 'flat'; conf: number }[];
  const out: { inst: string; dir: 'long' | 'short' | 'flat'; conf: number }[] = [];
  for (const m of c.position_management || []) {
    const a = String(m.action || '').toUpperCase();
    if (a && a !== 'WAIT' && a !== 'HOLD') {
      out.push({
        inst: symOf(String(m.instId || '')),
        dir: a.includes('LONG') ? 'long' : a.includes('SHORT') ? 'short' : 'flat',
        conf: Number(m.confidence || 0),
      });
    }
  }
  for (const o of c.top_opportunities || []) {
    const a = String(o.action || '').toUpperCase();
    if (a === 'BUY_LONG' || a === 'SELL_SHORT') {
      out.push({
        inst: String(o.inst || '').split('-')[0],
        dir: a === 'BUY_LONG' ? 'long' : 'short',
        conf: Number(o.confidence || 0),
      });
    }
  }
  return out.slice(0, 3);
});
</script>

<template>
  <section
    class="dsh-card flex flex-col min-h-0"
    :aria-label="t('dash.matrix.councilRail.title')"
  >
    <header class="dsh-card-header !flex-nowrap items-center justify-between gap-2">
      <div class="flex items-center gap-2 min-w-0">
        <h2 class="text-xs font-mono font-semibold uppercase tracking-wider text-[var(--ink-strong)] truncate">
          {{ t('dash.matrix.councilRail.title') }}
        </h2>
        <span v-if="latestCycle" class="text-4xs font-mono text-[var(--ink-3)] shrink-0 whitespace-nowrap">
          {{ cycleHm }}
        </span>
      </div>

      <div class="flex items-center gap-0.5 shrink-0">
        <button
          v-if="latestCycle"
          type="button"
          class="btn btn-quiet btn-sm !px-1.5 text-3xs font-mono"
          @click="emit('open-cycle', latestCycle)"
        >
          <span>{{ t('dash.matrix.councilRail.inspect') }}</span>
          <ChevronRight class="h-3 w-3" />
        </button>
        <RouterLink
          to="/factors"
          class="btn btn-quiet btn-sm !px-1.5 text-3xs font-mono text-[var(--ink-3)] hover:text-[var(--ink-strong)] no-underline"
        >
          {{ t('dash.matrix.councilRail.allCycles') }}
        </RouterLink>
      </div>
    </header>

    <div class="flex-1 min-h-0 flex flex-col">
      <div v-if="!latestCycle" class="px-5 py-4">
        <BaseEmpty :text="t('dash.matrix.councilRail.empty')" />
      </div>

      <div
        v-else
        class="clickable flex-1 px-5 pb-4 pt-1 transition-colors hover:bg-[var(--surface-2)]/40"
        tabindex="0"
        @click="emit('open-cycle', latestCycle)"
        @keydown.enter="emit('open-cycle', latestCycle)"
        @keydown.space.prevent="emit('open-cycle', latestCycle)"
      >
        <div class="flex items-center justify-between gap-2 mb-2 text-4xs font-mono text-[var(--ink-3)]">
          <span class="uppercase">
            {{ aiHealth?.council_enabled ? t('dash.matrix.councilRail.councilOn') : t('dash.matrix.councilRail.councilOff') }}
          </span>
          <span v-if="aiHealth?.last_council_status?.ran">
            {{ ((aiHealth.last_council_status.duration_ms || 0) / 1000).toFixed(0) }}s
          </span>
        </div>

        <p class="text-xs leading-body text-[var(--ink-1)] line-clamp-3 font-sans">
          {{ latestCycle.macro_assessment || t('dash.matrix.councilRail.empty') }}
        </p>

        <div class="mt-3 flex flex-wrap items-center gap-1.5">
          <template v-if="signals.length">
            <span
              v-for="s in signals"
              :key="s.inst + s.dir"
              class="inline-flex items-center gap-1.5 rounded border border-[var(--line-3)] bg-[var(--surface-2)] px-2 py-0.5 text-3xs font-mono"
            >
              <CryptoLogo :symbol="s.inst" :size="13" />
              <span class="font-bold text-[var(--ink-strong)]">{{ s.inst }}</span>
              <DirTag :dir="s.dir" />
              <ConfBadge v-if="s.conf > 0" :value="s.conf" />
            </span>
          </template>
          <span v-else class="text-4xs font-mono text-[var(--ink-3)]">
            {{ t('dash.matrix.councilRail.waitMode') }}
          </span>
        </div>
      </div>
    </div>
  </section>
</template>
