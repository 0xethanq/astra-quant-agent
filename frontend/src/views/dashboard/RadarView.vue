<script setup lang="ts">
/**
 * RadarView.vue · DeepSeek Harness 风格 AI 委员会决策推演与审计大盘
 * 呈现：决策周期时序流、AI 决策健康中枢、宏观研判流、多模型多空博弈与白盒穿透抽屉
 */
import { computed, ref } from 'vue';
import {
  Brain,
  ChevronRight,
} from 'lucide-vue-next';
import { useDashboardStore } from '../../stores/dashboard';
import DataGate from '../../components/dashboard/DataGate.vue';
import { symOf } from '../../utils/instId';
import { useI18n } from '../../composables/useI18n';
import { fmtHM, fmtDate, parseTime } from '../../utils/format';
import BaseEmpty from '../../components/base/BaseEmpty.vue';
import DirTag from '../../components/base/DirTag.vue';
import ConfBadge from '../../components/base/ConfBadge.vue';
import RadarDrawer from '../../components/dashboard/RadarDrawer.vue';
import CryptoLogo from '../../components/dashboard/CryptoLogo.vue';

const store = useDashboardStore();
const { t } = useI18n();

const history = computed<any[]>(() => {
  const h = (store.data as any)?.ai_brain_history;
  return Array.isArray(h) ? [...h] : [];
});

/** AI 决策健康度 */
const aiHealth = computed<any>(() => (store.data as any)?.ai_health || null);
const decisionAgeText = computed(() => {
  const s = aiHealth.value?.decision_age_seconds;
  if (s == null) return '--';
  return s < 90 ? `${s}s` : s < 5400 ? `${Math.round(s / 60)}min` : `${Math.round(s / 3600 * 10) / 10}h`;
});
const decisionAgeWarn = computed(() => (aiHealth.value?.decision_age_seconds ?? 0) > 900);

const selected = ref<any>(null);

function timeOf(c: any): Date {
  return parseTime(c.time);
}
function hm(c: any) {
  const d = timeOf(c);
  return Number.isNaN(d.getTime()) ? String(c.time || '').slice(11, 16) : fmtHM(d);
}
function dayOf(c: any): string {
  const d = timeOf(c);
  const today = new Date();
  const sameDay = fmtDate(d) === fmtDate(today);
  return sameDay ? t('dash.news.feed.grouped.today') : fmtDate(d);
}

/** 按日期分组 */
const grouped = computed(() => {
  const out: { day: string; items: any[] }[] = [];
  for (const c of history.value) {
    const day = dayOf(c);
    if (!out.length || out[out.length - 1].day !== day) out.push({ day, items: [] });
    out[out.length - 1].items.push(c);
  }
  return out;
});

function actionsOf(c: any): { inst: string; dir: string; conf: number; label?: string }[] {
  const list: { inst: string; dir: string; conf: number; label?: string }[] = [];
  for (const m of c.position_management || []) {
    const a = String(m.action || '').toUpperCase();
    if (a && a !== 'WAIT' && a !== 'HOLD') {
      const label = a === 'UPDATE_SL' ? '移损' : a === 'CLOSE_MARKET' ? '平仓' : a;
      list.push({
        inst: symOf(String(m.instId || '')),
        dir: a.includes('LONG') ? 'long' : a.includes('SHORT') ? 'short' : 'flat',
        conf: Number(m.confidence || 0),
        label,
      });
    }
  }
  for (const o of c.top_opportunities || []) {
    const a = String(o.action || '').toUpperCase();
    if (a === 'BUY_LONG' || a === 'SELL_SHORT') {
      list.push({
        inst: String(o.inst || '').split('-')[0],
        dir: a === 'BUY_LONG' ? 'long' : 'short',
        conf: Number(o.confidence || 0),
      });
    }
  }
  return list.slice(0, 4);
}
</script>

<template>
  <div class="space-y-3">
    <!-- 页头 -->
    <div class="flex items-center justify-between gap-2 pt-0.5">
      <div class="flex items-center gap-2">
        <h1 class="text-sm font-semibold tracking-tight text-[var(--ink-strong)] flex items-center gap-2">
          <Brain class="h-4 w-4 text-[var(--accent)]" />
          {{ t('dash.radar.title') }}
        </h1>
        <span
          class="rounded-full px-2 py-0.5 border text-3xs font-mono font-medium"
          style="background-color: var(--surface-2); border-color: var(--line-1); color: var(--ink-2)"
        >
          {{ t('dash.radar.cycles', undefined, { n: history.length }) }}
        </span>
      </div>

      <!-- AI 决策健康指示状态 -->
      <div v-if="aiHealth" class="flex flex-wrap items-center gap-1.5">
        <span class="dsh-pill">
          <span class="text-[var(--ink-3)]">{{ t('dash.radar.health.decisionAge') }}:</span>
          <b class="num font-mono" :class="decisionAgeWarn ? 'text-[var(--down)]' : 'text-[var(--up)]'">{{ decisionAgeText }}</b>
        </span>
        <span class="dsh-pill">
          <span class="text-[var(--ink-3)]">{{ t('dash.radar.council.title') }}:</span>
          <b :class="aiHealth.council_enabled ? 'text-[var(--up)]' : 'text-[var(--warn)]'">
            {{ aiHealth.council_enabled ? t('dash.radar.council.on') : t('dash.radar.council.off') }}
          </b>
        </span>
        <span
          v-if="aiHealth.council_enabled && aiHealth.last_council_status?.ran"
          class="dsh-pill text-[var(--up)]"
        >
          {{ t('dash.radar.council.done') }} {{ (((aiHealth.last_council_status.duration_ms || 0) / 1000)).toFixed(0) }}s
        </span>
      </div>
    </div>

    <DataGate>
      <!-- 决策周期时序卡片流 -->
      <div class="dsh-card overflow-clip">
        <BaseEmpty v-if="!history.length" :text="t('dash.radar.empty')" />
        <div v-else>
          <template v-for="grp in grouped" :key="grp.day">
            <div
              class="border-b px-4 py-1.5 text-3xs font-bold uppercase tracking-wider text-[var(--ink-3)]"
              style="background-color: var(--surface-header); border-color: var(--line-1)"
            >
              {{ grp.day }}
            </div>
            <button type="button"
              v-for="c in grp.items"
              :key="c.time"
              class="group flex w-full cursor-pointer items-start gap-4 border-b px-4 py-3.5 text-left transition-colors last:border-b-0 hover:bg-[var(--surface-2)]"
              style="border-color: var(--line-1)"
              @click="selected = c"
            >
              <!-- 决策时钟 -->
              <div class="shrink-0 w-16 pt-0.5">
                <span class="num font-mono text-xs font-bold text-[var(--ink-strong)] block">{{ hm(c) }}</span>
                <span class="text-4xs text-[var(--ink-3)] block font-mono">BJT</span>
              </div>

              <!-- 研判正文与指令 -->
              <div class="min-w-0 flex-1">
                <p class="text-xs text-[var(--ink-1)] leading-relaxed font-medium line-clamp-2">
                  {{ c.macro_assessment || t('dash.radar.empty') }}
                </p>

                <!-- 指令与机会 -->
                <div class="mt-2.5 flex flex-wrap items-center gap-2">
                  <span
                    v-for="a in actionsOf(c)"
                    :key="a.inst + a.dir + (a.label || '')"
                    class="dsh-pill !py-0.5"
                  >
                    <CryptoLogo :symbol="a.inst" :size="15" />
                    <span class="num font-mono text-3xs font-bold text-[var(--ink-strong)]">{{ a.inst }}</span>
                    <span v-if="a.label" class="rounded px-1.5 py-0.5 border text-4xs font-mono font-medium text-[var(--accent)] border-[var(--accent-line)] bg-[var(--accent-bg)]">{{ a.label }}</span>
                    <DirTag v-else :dir="a.dir" />
                    <ConfBadge :value="a.conf" />
                  </span>

                  <span v-if="!actionsOf(c).length" class="inline-flex items-center rounded-full px-2.5 py-0.5 text-3xs text-[var(--ink-3)] font-mono border border-[var(--line-1)] bg-[var(--surface-2)]">
                    {{ t('dash.radar.detail.waitNote') }}
                  </span>
                </div>
              </div>

              <!-- 右侧箭头 -->
              <div class="shrink-0 self-center text-[var(--ink-3)] transition-transform group-hover:translate-x-0.5">
                <ChevronRight class="h-4 w-4" />
              </div>
            </button>
          </template>
        </div>
      </div>

      <!-- 决策审计抽屉 -->
      <RadarDrawer :cycle="selected" @close="selected = null" />
    </DataGate>
  </div>
</template>
