<script setup lang="ts">
/**
 * EvolutionView.vue · DeepSeek Harness 风格自进化与认知中枢
 * 包含：自进化复盘 HUD 状态带、诊断归因与行动决策树、确定性数理快照可观测性审计、核心黄金心法库与长期认知记忆流
 */
import { computed } from 'vue';
import {
  Dna,
  Sparkles,
  ShieldCheck,
  Brain,
  ListChecks,
  FileText,
} from 'lucide-vue-next';
import { useDashboardStore } from '../../stores/dashboard';
import DataGate from '../../components/dashboard/DataGate.vue';
import { useI18n } from '../../composables/useI18n';
import { fmtNum, fmtDateTime } from '../../utils/format';
import BaseStat from '../../components/base/BaseStat.vue';
import BaseEmpty from '../../components/base/BaseEmpty.vue';
import BaseCollapse from '../../components/base/BaseCollapse.vue';
import { resolveEvolutionStatus } from '../../utils/evolutionStatus';

const store = useDashboardStore();
const { t } = useI18n();

const review = computed<any>(() => (store.data as any)?.review || {});

const statusResolved = computed(() =>
  resolveEvolutionStatus(review.value.change_status, review.value.llm_error)
);

const statusKey = computed(() => statusResolved.value.key);
const statusMeta = computed(() => {
  const r = statusResolved.value;
  let label = '--';
  if (r.category === 'EVOLVED') label = t('dash.evolution.hud.statuses.CHANGED');
  else if (r.category === 'NO_CHANGE') label = t('dash.evolution.hud.statuses.NO_CHANGE');
  else if (r.category === 'RUNNING') label = t('dash.evolution.hud.statuses.RUNNING');
  else if (r.category === 'FAILED') label = t('dash.evolution.hud.statuses.FAILED');
  else if (r.category === 'UNKNOWN') label = r.key;

  return {
    cls: r.hudClass,
    textCls: r.hudTextClass,
    label,
  };
});

const insights = computed<any[]>(() => review.value.diagnosis_insights || review.value.insights || []);

function insTitle(it: any): string {
  if (typeof it === 'string') {
    const i = it.indexOf('：');
    if (i > 0 && i <= 24) return it.slice(0, i);
    return '';
  }
  return it?.dimension || it?.title || '';
}

function insBody(it: any): string {
  if (typeof it === 'string') {
    const i = it.indexOf('：');
    return i > 0 && i <= 24 ? it.slice(i + 1) : it;
  }
  const direct = it?.observation || it?.detail || it?.text || it?.action || it?.analysis
    || it?.content || it?.finding || it?.summary || it?.description || it?.reason;
  if (direct) return String(direct);
  if (it && typeof it === 'object') {
    return Object.entries(it)
      .filter(([, v]) => v !== null && v !== undefined && typeof v !== 'object')
      .map(([k, v]) => `${k}: ${v}`)
      .join(t('dash.evolution.itemSep'));
  }
  return String(it ?? '');
}

const actions = computed<any[]>(() => review.value.actions_taken || []);
const snapAudit = computed<any>(() => review.value.snapshot_audit || null);

function actText(a: any): string {
  if (typeof a === 'string') return a;
  if (a && typeof a === 'object') {
    // 批 41：局部变量改名（原为 `t`，把 i18n 的 t 遮蔽了），
    // 动作前缀的方括号交由语言决定（中文【】/ 英文 []）。
    const body = a.action || a.text || a.content || a.summary || a.description;
    if (body)
      return a.action_type
        ? t('dash.evolution.actText', undefined, { type: a.action_type, text: body })
        : String(body);
    return Object.entries(a)
      .filter(([, v]) => v !== null && v !== undefined && typeof v !== 'object')
      .map(([k, v]) => `${k}: ${v}`)
      .join(t('dash.evolution.itemSep'));
  }
  return String(a ?? '');
}

const rules = computed(() => {
  const list: string[] = review.value.core_lessons || [];
  return list.map((raw) => {
    const m = String(raw).match(/^【(.+?)】([\s\S]*)$/);
    return m ? { title: m[1], body: m[2].trim() } : { title: '', body: String(raw).trim() };
  });
});

const md = computed(() => (store.data as any)?.ai_trading_memory_md || '');
</script>

<template>
  <div class="space-y-3">
    <!-- 页头 -->
    <div class="flex items-center justify-between gap-2 pt-0.5">
      <div class="flex items-center gap-2">
        <h1 class="text-sm font-semibold tracking-tight text-[var(--ink-strong)] flex items-center gap-2">
          <Dna class="h-4 w-4 text-[var(--accent)]" />
          {{ t('dash.evolution.title') }}
        </h1>
        <span
          class="rounded-full px-2 py-0.5 border text-3xs font-mono font-medium"
          style="background-color: var(--surface-2); border-color: var(--line-1); color: var(--ink-2)"
        >
          {{ t('dash.evolution.autoIterateBadge') }}
        </span>
      </div>

      <div class="flex items-center gap-2">
        <span
          v-if="statusKey"
          class="rounded-full px-2.5 py-0.5 border text-3xs font-mono font-bold uppercase"
          :class="statusMeta.cls"
        >
          {{ statusMeta.label }}
        </span>
      </div>
    </div>

    <DataGate>
      <!-- 复盘 HUD 5 指标卡片 -->
      <div class="dsh-card">
        <div class="grid grid-cols-2 gap-2 p-2 sm:grid-cols-3 xl:grid-cols-5 bg-[var(--surface-1)]">
          <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors">
            <BaseStat
              :label="t('dash.evolution.hud.at')"
              :value="review.timestamp ? fmtDateTime(review.timestamp).slice(5, 16) : '--'"
            />
          </div>
          <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors">
            <BaseStat
              :label="t('dash.evolution.hud.sample')"
              :value="review.total_trades != null ? `${fmtNum(review.total_trades, 0)} ${t('common.unitCount')}` : '--'"
            />
          </div>
          <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors">
            <BaseStat
              :label="t('dash.evolution.hud.winRate')"
              :value="review.win_rate != null ? fmtNum(review.win_rate, 1) + '%' : '--'"
            />
          </div>
          <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors">
            <BaseStat
              :label="t('dash.evolution.hud.pf')"
              :value="review.profit_factor != null ? fmtNum(review.profit_factor, 2) : '--'"
              :delta="(review.profit_factor ?? 0) >= 1 ? t('common.ge') + ' 1' : undefined"
              :delta-tone="(review.profit_factor ?? 0) >= 1 ? 'up' : 'down'"
              :hint="t('dash.ledger.summary.tipPf')"
            />
          </div>
          <div class="rounded-lg bg-[var(--surface-2)]/30 hover:bg-[var(--surface-2)]/70 transition-colors px-3.5 py-2.5 flex flex-col justify-center">
            <span class="text-3xs text-[var(--ink-3)] font-semibold uppercase tracking-wider">{{ t('dash.evolution.hud.status') }}</span>
            <span class="text-xs font-bold mt-1" :class="statusMeta.textCls">
              {{ statusMeta.label }}
            </span>
          </div>
        </div>
      </div>

      <!-- 双列工位排布：左侧诊断与行动决策 / 右侧黄金心法与长期记忆 -->
      <div class="grid grid-cols-1 gap-3 xl:grid-cols-12 items-start">
        <!-- 左列：诊断归因、行动项与物理快照 (7) -->
        <div class="xl:col-span-7 space-y-3">
          <!-- 诊断归因切片 -->
          <div class="dsh-card p-4 space-y-3">
            <h2 class="text-xs font-bold uppercase tracking-wider text-[var(--ink-strong)] flex items-center gap-1.5">
              <Brain class="h-4 w-4 text-[var(--accent)]" />
              {{ t('dash.evolution.insights.title') }}
            </h2>

            <BaseEmpty v-if="!insights.length" :text="t('dash.evolution.insights.empty')" />

            <div v-else class="space-y-2.5">
              <div
                v-for="(it, idx) in insights"
                :key="idx"
                class="dsh-card-sub p-3 space-y-1"
              >
                <span v-if="insTitle(it)" class="text-3xs font-bold font-mono text-[var(--accent)] block uppercase">
                  {{ insTitle(it) }}
                </span>
                <p class="text-xs text-[var(--ink-1)] leading-body font-sans">{{ insBody(it) }}</p>
              </div>
            </div>
          </div>

          <!-- 自进化行动项 -->
          <div v-if="actions.length" class="dsh-card p-4 space-y-3">
            <h2 class="text-xs font-bold uppercase tracking-wider text-[var(--ink-strong)] flex items-center gap-1.5">
              <ListChecks class="h-4 w-4 text-[var(--accent)]" />
              {{ t('dash.evolution.actions.title') }}
            </h2>

            <div class="space-y-2">
              <div
                v-for="(a, idx) in actions"
                :key="idx"
                class="dsh-card-sub p-3 flex items-start gap-2.5"
              >
                <span class="num font-mono font-bold text-3xs text-[var(--accent)] shrink-0 mt-0.5">0{{ idx + 1 }}</span>
                <p class="text-xs text-[var(--ink-1)] leading-body flex-1">{{ actText(a) }}</p>
              </div>
            </div>
          </div>

          <!-- 确定性数理快照审计 -->
          <div v-if="snapAudit" class="dsh-card p-4 space-y-2">
            <h2 class="text-xs font-bold uppercase tracking-wider text-[var(--ink-strong)] flex items-center gap-1.5">
              <ShieldCheck class="h-4 w-4 text-[var(--accent)]" />
              {{ t('dash.evolution.snapshotAuditTitle') }}
            </h2>
            <div class="dsh-card-sub p-3 text-3xs font-mono text-[var(--ink-2)] space-y-1">
              <div v-for="(v, k) in snapAudit" :key="k" class="flex justify-between">
                <span class="text-[var(--ink-3)]">{{ k }}:</span>
                <span class="font-bold text-[var(--ink-1)]">{{ v }}</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 右列：核心黄金心法库 & 长期记忆 Markdown (5) -->
        <div class="xl:col-span-5 space-y-3">
          <!-- 黄金心法库 -->
          <div class="dsh-card p-4 space-y-3">
            <h2 class="text-xs font-bold uppercase tracking-wider text-[var(--ink-strong)] flex items-center gap-1.5">
              <Sparkles class="h-4 w-4 text-[var(--accent)]" />
              {{ t('dash.evolution.memory.title') }}
            </h2>

            <BaseEmpty v-if="!rules.length" :text="t('dash.evolution.memory.empty')" />

            <div v-else class="space-y-2.5">
              <div
                v-for="(r, idx) in rules"
                :key="idx"
                class="dsh-card-sub p-3 space-y-1"
              >
                <h3 v-if="r.title" class="text-xs font-bold text-[var(--ink-strong)] flex items-center gap-1.5">
                  <span class="h-1.5 w-1.5 rounded-full bg-[var(--accent)]" />
                  {{ r.title }}
                </h3>
                <p class="text-xs text-[var(--ink-2)] leading-body font-sans">{{ r.body }}</p>
              </div>
            </div>
          </div>

          <!-- 全量自进化认知记忆 Markdown -->
          <BaseCollapse v-if="md">
            <template #head>
              <span class="flex items-center gap-2 text-xs font-bold text-[var(--ink-strong)]">
                <FileText class="h-3.5 w-3.5 text-[var(--accent)]" />
                {{ t('dash.evolution.memory.dev') }}
              </span>
            </template>
            <div class="p-3">
              <pre
                class="rounded p-3 font-mono text-3xs leading-body whitespace-pre-wrap select-text max-h-96 overflow-y-auto"
                tabindex="0"
                style="background-color: var(--surface-input); border: 1px solid var(--line-1); color: var(--ink-2)"
              >{{ md }}</pre>
            </div>
          </BaseCollapse>
        </div>
      </div>
    </DataGate>
  </div>
</template>
