<script setup lang="ts">
/**
 * EvolutionView.vue · AstraQuant 模型自进化与复盘认知中枢
 * 包含：自进化复盘 HUD 状态带、诊断归因与行动决策树、确定性数理快照可观测性审计、核心黄金心法库与长期认知记忆流
 */
import { computed } from 'vue';
import {
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
// ── 2026-10（方向 1：证据链可观测性）──
// 报告载荷里的两个覆盖率与缺口清单。它们**由后端从 snapshot_audit 内部派生**
// （14 入参契约未变），故前端只需读；缺失时整块不渲染（老报告仍能打开）。
const evidenceEntryCoverage = computed<number | null>(() => {
  const v = review.value.evidence_coverage_pct;
  return typeof v === 'number' ? v : null;
});
const evidenceExitCoverage = computed<number | null>(() => {
  const v = review.value.exit_cause_coverage_pct;
  return typeof v === 'number' ? v : null;
});
const evidenceGaps = computed<string[]>(() => {
  const list = review.value.evidence_gap_reasons;
  return Array.isArray(list) ? list.filter((g: any) => typeof g === 'string' && g) : [];
});
const hasEvidenceChain = computed(
  () => evidenceEntryCoverage.value !== null || evidenceExitCoverage.value !== null,
);

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
  <div class="w-full">
    <!-- 无边框舒展页头 -->
    <div class="mb-6 flex items-center justify-between gap-3">
      <div class="flex items-baseline gap-3 flex-wrap">
        <h1 class="text-2xl font-semibold tracking-tight text-[var(--ink-strong)]">
          {{ t('dash.evolution.title') }}
        </h1>
      </div>

      <div class="flex items-center gap-2">
        <span
          v-if="statusKey"
          class="rounded-xs px-2.5 py-0.5 border text-3xs font-mono font-bold uppercase"
          :class="statusMeta.cls"
        >
          {{ statusMeta.label }}
        </span>
      </div>
    </div>

    <DataGate>
      <!-- 开放式无边框 6 指标 HUD（保留 BaseStat delta-tone 契约） -->
      <div class="mb-8 grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-x-8 gap-y-4">
        <BaseStat
          :bare="true"
          :label="t('dash.evolution.hud.at')"
          :value="review.timestamp ? fmtDateTime(review.timestamp).slice(5, 16) : '--'"
        />
        <BaseStat
          :bare="true"
          :label="t('dash.evolution.hud.sample')"
          :value="review.total_trades != null ? `${fmtNum(review.total_trades, 0)} ${t('common.unitCount')}` : '--'"
        />
        <BaseStat
          :bare="true"
          :label="t('dash.evolution.hud.winRate')"
          :value="review.win_rate != null ? fmtNum(review.win_rate, 1) + '%' : '--'"
        />
        <BaseStat
          :bare="true"
          :label="t('dash.evolution.hud.pf')"
          :value="review.profit_factor != null ? fmtNum(review.profit_factor, 2) : '--'"
          :delta="(review.profit_factor ?? 0) >= 1 ? t('common.ge') + ' 1' : undefined"
          :delta-tone="(review.profit_factor ?? 0) >= 1 ? 'up' : 'down'"
          :hint="t('dash.ledger.summary.tipPf')"
        />
        <div class="py-1 flex flex-col justify-center">
          <span class="text-4xs font-mono text-[var(--ink-3)] font-semibold uppercase tracking-wider">{{ t('dash.evolution.hud.status') }}</span>
          <span class="text-lg font-mono font-semibold mt-1" :class="statusMeta.textCls">
            {{ statusMeta.label }}
          </span>
        </div>
      </div>

      <!-- 双列色调卡片排布：左 7 诊断与证据 / 右 5 黄金心法与记忆 -->
      <div class="grid grid-cols-1 xl:grid-cols-12 gap-6 items-start">
        <!-- 左列 (7) -->
        <div class="xl:col-span-7 space-y-6">
          <!-- 诊断归因流 -->
          <section class="dsh-card p-6 space-y-3">
            <h2 class="text-xs font-mono font-semibold uppercase tracking-wider text-[var(--ink-strong)]">
              {{ t('dash.evolution.insights.title') }}
            </h2>

            <BaseEmpty v-if="!insights.length" :text="t('dash.evolution.insights.empty')" />

            <div v-else class="divide-y divide-[var(--line-3)]">
              <div
                v-for="(it, idx) in insights"
                :key="idx"
                class="py-3.5 first:pt-1 last:pb-0 space-y-1 max-w-3xl"
              >
                <span v-if="insTitle(it)" class="text-3xs font-bold font-mono text-[var(--accent)] block uppercase">
                  {{ insTitle(it) }}
                </span>
                <p class="text-xs sm:text-sm text-[var(--ink-1)] leading-body font-sans">{{ insBody(it) }}</p>
              </div>
            </div>
          </section>

          <!-- 自进化行动项 -->
          <section v-if="actions.length" class="dsh-card p-6 space-y-3">
            <h2 class="text-xs font-mono font-semibold uppercase tracking-wider text-[var(--ink-strong)]">
              {{ t('dash.evolution.actions.title') }}
            </h2>

            <div class="divide-y divide-[var(--line-3)]">
              <div
                v-for="(a, idx) in actions"
                :key="idx"
                class="py-3.5 first:pt-1 last:pb-0 flex items-start gap-3 max-w-3xl"
              >
                <span class="num font-mono font-bold text-xs text-[var(--accent)] shrink-0 mt-0.5">0{{ idx + 1 }}</span>
                <p class="text-xs sm:text-sm text-[var(--ink-1)] leading-body flex-1">{{ actText(a) }}</p>
              </div>
            </div>
          </section>

          <!-- 证据链健康度 -->
          <section v-if="hasEvidenceChain" class="dsh-card p-6 space-y-4">
            <h2 class="text-xs font-mono font-semibold uppercase tracking-wider text-[var(--ink-strong)]">
              {{ t('dash.evolution.evidenceChainTitle') }}
            </h2>
            <div class="grid grid-cols-2 gap-4">
              <div v-if="evidenceEntryCoverage !== null" class="rounded-md p-3.5 bg-[var(--surface-2)]/50">
                <div class="text-3xs font-mono text-[var(--ink-3)]">{{ t('dash.evolution.evidenceEntryCoverage') }}</div>
                <div class="text-xl font-bold font-mono text-[var(--ink-strong)] mt-1">{{ evidenceEntryCoverage }}%</div>
              </div>
              <div v-if="evidenceExitCoverage !== null" class="rounded-md p-3.5 bg-[var(--surface-2)]/50">
                <div class="text-3xs font-mono text-[var(--ink-3)]">{{ t('dash.evolution.evidenceExitCoverage') }}</div>
                <div class="text-xl font-bold font-mono text-[var(--ink-strong)] mt-1">{{ evidenceExitCoverage }}%</div>
              </div>
            </div>
            <div class="text-xs text-[var(--ink-2)] space-y-1 max-w-3xl">
              <div class="font-mono text-3xs font-semibold text-[var(--ink-3)] uppercase">{{ t('dash.evolution.evidenceGapsTitle') }}</div>
              <div v-if="!evidenceGaps.length" class="text-[var(--ink-2)]">
                {{ t('dash.evolution.evidenceNoGaps') }}
              </div>
              <div v-for="(gap, i) in evidenceGaps" :key="i" class="flex gap-2">
                <span class="text-[var(--accent)]">-</span>
                <span>{{ gap }}</span>
              </div>
            </div>
          </section>

          <!-- 确定性数理快照审计 -->
          <section v-if="snapAudit" class="dsh-card p-6 space-y-3">
            <h2 class="text-xs font-mono font-semibold uppercase tracking-wider text-[var(--ink-strong)]">
              {{ t('dash.evolution.snapshotAuditTitle') }}
            </h2>
            <div class="divide-y divide-[var(--line-3)] text-3xs font-mono text-[var(--ink-2)] max-w-2xl">
              <div v-for="(v, k) in snapAudit" :key="k" class="flex justify-between py-2.5 first:pt-1 last:pb-0">
                <span class="text-[var(--ink-3)]">{{ k }}</span>
                <span class="font-semibold text-[var(--ink-1)]">{{ v }}</span>
              </div>
            </div>
          </section>
        </div>

        <!-- 右列 (5) -->
        <div class="xl:col-span-5 space-y-6">
          <!-- 黄金心法库 -->
          <section class="dsh-card p-6 space-y-3">
            <h2 class="text-xs font-mono font-semibold uppercase tracking-wider text-[var(--ink-strong)]">
              {{ t('dash.evolution.memory.title') }}
            </h2>

            <BaseEmpty v-if="!rules.length" :text="t('dash.evolution.memory.empty')" :desc="t('dash.evolution.memory.desc')" />

            <div v-else class="divide-y divide-[var(--line-3)]">
              <div
                v-for="(r, idx) in rules"
                :key="idx"
                class="py-3.5 first:pt-1 last:pb-0 space-y-1 max-w-2xl"
              >
                <h3 v-if="r.title" class="text-xs font-mono font-bold text-[var(--ink-strong)] flex items-center gap-2">
                  <span class="h-1.5 w-1.5 rounded-full bg-[var(--accent)] shrink-0" />
                  <span>{{ r.title }}</span>
                </h3>
                <p class="text-xs text-[var(--ink-2)] leading-body font-sans">{{ r.body }}</p>
              </div>
            </div>
          </section>

          <!-- 全量自进化认知记忆 Markdown -->
          <div class="dsh-card p-4" v-if="md">
            <BaseCollapse>
              <template #head>
                <span class="flex items-center gap-2 text-xs font-mono font-semibold text-[var(--ink-strong)]">
                  <FileText class="h-3.5 w-3.5 text-[var(--accent)]" />
                  {{ t('dash.evolution.memory.dev') }}
                </span>
              </template>
              <div class="p-3">
                <pre
                  class="rounded-md p-3 font-mono text-3xs leading-body whitespace-pre-wrap select-text max-h-96 overflow-y-auto"
                  tabindex="0"
                  style="background-color: var(--surface-input); color: var(--ink-2)"
                >{{ md }}</pre>
              </div>
            </BaseCollapse>
          </div>
        </div>
      </div>
    </DataGate>
  </div>
</template>
