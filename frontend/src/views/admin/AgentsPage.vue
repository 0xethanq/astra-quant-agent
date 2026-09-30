<script setup lang="ts">
/**
 * `embedded`（2026-09-30 后台精简）：本页被吸收为宿主页的一个页签时为真。
 * 宿主页负责大标题与页签标签，本页 PageHeader 降级为紧凑行（说明收起），
 * 但 #actions 里的按钮原样渲染 —— 被吸收页的按钮一个都不能丢。
 */
const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
/**
 * AgentsPage.vue · 运行单元与遥测工位
 * ---------------------------------------------------------------------------
 * 骨架（推倒重来）：
 *   旧 = 一行说明 + 3 张卡（名册表 / 遥测表 / 密钥库），字色靠蓝紫琥珀色相区分
 *   新 = 共享 PageHeader（策略徽章 + 刷新）
 *        → **名册状态带**（在册 / 健康 / 异常 / 平均时延）
 *        → **Worker 名册行式清单**（图标 + 名称·职责 / 健康徽章 / 最近执行 / 产物时效）
 *        → 双栏：**模型遥测**（策略说明 + 3 项统计 + 调用流水日志面板）
 *               / **本机密文库**（kv 行）
 *
 * ⚠️ 修复：`useResource` 的文档声明 `immediate` 默认 true，但实现只在传入真值时取数，
 *    本页此前**从不自动加载**。现显式传 `immediate: true`。
 *
 * 后端契约（逐字未改）：GET /api/v1/admin/agents
 *   → { agents:[{id,name,role,health,last_run_at,last_run_status,output_age_seconds,output}],
 *       prompt_policy,
 *       model_stats:{total_calls,successful_calls,avg_duration_ms,cached_tokens_total,
 *                    cache_hit_calls,cache_reporting_calls,cache_hit_rate},
 *       model_calls:[{id,caller,model,status,total_tokens,cached_tokens,cache_status,duration_ms}],
 *       secret_store:{initialized,count,store_mode,source_priority,keys[]} }
 *
 * 缓存三态（2026-09-29）：`cache_status` ∈ hit / miss / unreported —— `unreported` 表示
 * 上游**根本没上报缓存字段**（旧实现把它印成"缓存: 0"，于是"还是 0 缓存"永远说不清）。
 * `cache_hit_rate` 为 `null` 一律显示 `--`（不可判定 ≠ 0%）。
 */
import { computed } from 'vue';
import { fmtDateTime } from '../../utils/format';
import { useI18n } from '../../composables/useI18n';
const { t } = useI18n();
import PageHeader from '../../components/admin/PageHeader.vue';
import BaseEmpty from '../../components/base/BaseEmpty.vue';
import { useResource } from '../../composables/useResource';
import { Package, Cpu, KeyRound, RefreshCw, Loader2, AlertTriangle,
  Activity, ShieldCheck, Radio } from 'lucide-vue-next';
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue';

const { data, loading, error, loaded, reload: load } = useResource<any>('/api/v1/admin/agents', {
  immediate: true,
});

const agents = computed<any[]>(() => data.value?.agents || []);
const calls = computed<any[]>(() => (data.value?.model_calls || []).slice(0, 30));
const showSkeleton = computed(() => loading.value && !loaded.value);

/** 状态语义 → 徽章色调（判定集合与旧版 statusColor 完全一致） */
function statusTone(s: string): string {
  if (['success', 'running', 'online', 'idle'].includes(s)) return 'badge-up';
  if (['failed', 'error', 'offline'].includes(s)) return 'badge-down';
  return 'badge-warn';
}

/** 状态文案：查表本地化，未登记枚举原样回退（批 27）。 */
function statusLabel(s: string): string {
  return t(`admin.agents.status.${s}`, s);
}

const healthyCount = computed(
  () => agents.value.filter((a) => ['success', 'running', 'online', 'idle'].includes(a.health)).length,
);
const issueCount = computed(() => agents.value.length - healthyCount.value);

const avgLatency = computed(() =>
  data.value?.model_stats?.avg_duration_ms
    ? `${Math.round(data.value.model_stats.avg_duration_ms)}ms`
    : '--',
);
const successRate = computed(() => {
  const s = data.value?.model_stats;
  if (!s || !(s.total_calls > 0)) return '--';
  return `${Math.round((100 * (s.successful_calls ?? 0)) / s.total_calls)}%`;
});
const successRateTone = computed(() => {
  const s = data.value?.model_stats;
  if (!s || !(s.total_calls > 0)) return '';
  return (s.successful_calls ?? 0) < s.total_calls ? 'is-warn' : 'is-up';
});
const callsDegraded = computed(() => {
  const s = data.value?.model_stats;
  return !!s && s.total_calls > 0 && (s.successful_calls ?? 0) < s.total_calls;
});

/**
 * 前缀缓存命中率（2026-09-29 新增）：
 * 后端只在**上游确实上报过缓存字段**的调用上算这个数；一次上报都没有时它是 `null`
 * ⇒ 显示 `--`（不可判定），绝不显示 0% 冒充"一次都没命中"。
 */
const cacheHitRate = computed(() => {
  const rate = data.value?.model_stats?.cache_hit_rate;
  return typeof rate === 'number' ? `${rate}%` : '--';
});

/** 单次调用的缓存三态：命中 / 上游上报未命中 / 上游未上报（不可判定）。 */
function cacheTone(c: any): string {
  if (c?.cache_status === 'hit') return 'is-up';
  if (c?.cache_status === 'miss') return 'is-warn';
  return '';
}
function cacheText(c: any): string {
  if (c?.cache_status === 'hit') return t('admin.agents.cacheHit');
  if (c?.cache_status === 'miss') return t('admin.agents.cacheMiss');
  if (c?.cache_status === 'unreported') return t('admin.agents.cacheUnreported');
  return '--';
}
function cacheTitle(c: any): string {
  if (c?.cache_status === 'hit') return t('admin.agents.cacheHitTitle', undefined, { n: c.cached_tokens ?? 0 });
  if (c?.cache_status === 'miss') return t('admin.agents.cacheMissTitle');
  if (c?.cache_status === 'unreported') return t('admin.agents.cacheUnreportedTitle');
  return '';
}

function ageText(a: any): string {
  if (a.output_age_seconds != null) {
    return t('admin.agents.minutesAgo', undefined, { n: Math.round(a.output_age_seconds / 60) });
  }
  return a.output ? t('admin.agents.coldStart') : t('admin.agents.noOutput');
}
</script>

<template>
  <div class="ag">
    <PageHeader :embedded="props.embedded" :title="t('admin.agents.title')">
      <template #actions>
        <span class="badge badge-accent mono">{{ t('admin.agents.policyChip') }}</span>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="loading" @click="load">
          <Loader2 v-if="loading && loaded" :size="14" class="animate-spin shrink-0" />
          <RefreshCw v-else :size="14" />
          <span>{{ t('admin.agents.refresh') }}</span>
        </button>
      </template>
    </PageHeader>

    <!-- 拉取失败 -->
    <div v-if="error && !data" role="alert" class="state-block is-error">
      <span class="state-icon"><AlertTriangle :size="17" /></span>
      <p class="state-title">{{ t('common.loadFailed') }}</p>
      <p class="state-desc">{{ error }}</p>
      <button type="button" class="btn btn-ghost btn-sm mt-1" :disabled="loading" @click="load">
        <RefreshCw :size="14" />
        <span>{{ t('common.retry') }}</span>
      </button>
    </div>

    <template v-else>
      <!-- ══ 名册状态带 ══ -->
      <section class="card band">
        <template v-if="showSkeleton">
          <BaseLoadingAnnounce />
          <div v-for="i in 4" :key="i" class="fact">
            <div class="skeleton skeleton-text" style="width: 48%" />
            <div class="skeleton skeleton-text skeleton-value" style="width: 64%" />
            <div class="skeleton skeleton-text" style="width: 36%" />
          </div>
        </template>

        <template v-else>
          <div class="fact">
            <span class="fact-label"><Radio :size="12" />{{ t('admin.agents.bandUnits') }}</span>
            <span class="fact-value num">{{ agents.length }}</span>
            <span class="fact-foot">{{ t('admin.agents.roster') }}</span>
          </div>

          <div class="fact">
            <span class="fact-label"><ShieldCheck :size="12" />{{ t('admin.agents.bandHealthy') }}</span>
            <span class="fact-value num" :class="healthyCount === agents.length && agents.length ? 'is-up' : ''">
              {{ healthyCount }}
            </span>
            <span class="fact-foot">{{ t('admin.agents.colHealth') }}</span>
          </div>

          <div class="fact">
            <span class="fact-label"><AlertTriangle :size="12" />{{ t('admin.agents.bandIssues') }}</span>
            <span class="fact-value num" :class="issueCount ? 'is-warn' : 'is-up'">{{ issueCount }}</span>
            <span class="fact-foot">{{ t('admin.agents.colResult') }}</span>
          </div>

          <div class="fact">
            <span class="fact-label"><Activity :size="12" />{{ t('admin.agents.bandLatency') }}</span>
            <span class="fact-value num">{{ avgLatency }}</span>
            <span class="fact-foot mono">
              {{ t('admin.agents.successRate') }} {{ successRate }}
            </span>
          </div>
        </template>
      </section>

      <!-- ══ Worker 名册 ══ -->
      <section class="card">
        <header class="card-head">
          <div>
            <h2 class="card-title"><Package :size="14" />{{ t('admin.agents.title') }}</h2>
            <p class="card-sub">{{ t('admin.agents.roster') }}</p>
          </div>
          <span v-if="!showSkeleton" class="badge mono">{{ agents.length }}</span>
        </header>

        <div v-if="showSkeleton" class="ag-skel">
          <BaseLoadingAnnounce />
          <div v-for="i in 4" :key="i" class="skeleton skeleton-row" />
        </div>

        <BaseEmpty v-else-if="!agents.length" :text="t('common.noRecords')" />

        <div v-else class="ag-rows">
          <div class="ag-row ag-row-head">
            <span />
            <span>{{ t('admin.agents.colUnit') }}</span>
            <span>{{ t('admin.agents.colHealth') }}</span>
            <span>{{ t('admin.agents.colLastRun') }}</span>
            <span>{{ t('admin.agents.colOutputAge') }}</span>
          </div>

          <article v-for="a in agents" :key="a.id" class="ag-row">
            <span class="icon-box"><Cpu :size="14" /></span>

            <div class="ag-main">
              <span class="ag-name">{{ a.name }}</span>
              <span class="ag-role">{{ a.role }}</span>
            </div>

            <span class="badge" :class="statusTone(a.health)" :title="a.health">{{ statusLabel(a.health) }}</span>

            <div class="ag-run">
              <span class="ag-run-time mono">
                {{ a.last_run_at ? fmtDateTime(a.last_run_at) : t('admin.agents.notScheduled') }}
              </span>
              <span class="badge" :class="statusTone(a.last_run_status)" :title="a.last_run_status">{{ statusLabel(a.last_run_status) }}</span>
            </div>

            <span class="ag-age num">{{ ageText(a) }}</span>
          </article>
        </div>
      </section>

      <!-- ══ 遥测 / 密文库 ══ -->
      <div class="ag-grid">
        <!-- 模型调用遥测 -->
        <section class="card">
          <header class="card-head">
            <h2 class="card-title"><Cpu :size="14" />{{ t('admin.agents.modelTelemetry') }}</h2>
            <span v-if="callsDegraded" class="badge badge-warn">{{ t('admin.agents.colStatus') }}</span>
          </header>

          <p class="ag-policy">
            <span class="label-caps">{{ t('admin.agents.promptPolicy') }}</span>
            <span>{{ data?.prompt_policy }}</span>
          </p>

          <div class="ag-stats">
            <div class="ag-stat">
              <span class="label-caps">{{ t('admin.agents.totalCalls') }}</span>
              <span class="ag-stat-v num">{{ data?.model_stats?.total_calls ?? '--' }}</span>
            </div>
            <div class="ag-stat">
              <span class="label-caps">{{ t('admin.agents.successRate') }}</span>
              <span class="ag-stat-v num" :class="successRateTone">{{ successRate }}</span>
            </div>
            <div class="ag-stat">
              <span class="label-caps">{{ t('admin.agents.avgLatency') }}</span>
              <span class="ag-stat-v num">{{ avgLatency }}</span>
            </div>
            <div class="ag-stat">
              <span class="label-caps">{{ t('admin.agents.cacheHitRate') }}</span>
              <span
                class="ag-stat-v num"
                :class="data?.model_stats?.cache_hit_rate ? 'is-up' : ''"
                :title="cacheHitRate === '--' ? t('admin.agents.cacheUnreportedTitle') : ''"
              >{{ cacheHitRate }}</span>
            </div>
          </div>

          <div class="ag-calls-head">
            <span class="label-caps">{{ t('admin.agents.callsTitle') }}</span>
            <span class="badge mono">{{ calls.length }}</span>
          </div>

          <BaseEmpty v-if="!calls.length" :text="t('admin.agents.emptyCalls')" />

          <div v-else class="log-panel is-flush ag-calls">
            <div v-for="c in calls" :key="c.id" class="ag-call">
              <span class="ag-call-caller truncate" :title="c.caller">{{ c.caller || '--' }}</span>
              <span class="ag-call-model mono truncate" :title="c.model">{{ c.model || '--' }}</span>
              <span class="badge" :class="statusTone(c.status)" :title="c.status">{{ statusLabel(c.status) }}</span>
              <span class="ag-call-cache" :class="cacheTone(c)" :title="cacheTitle(c)">{{ cacheText(c) }}</span>
              <span class="ag-call-n num">{{ c.total_tokens ?? '--' }}</span>
              <span class="ag-call-n num">{{ c.duration_ms ? Math.round(c.duration_ms) + 'ms' : '--' }}</span>
            </div>
          </div>
        </section>

        <!-- 本机加密密文库 -->
        <section class="card">
          <header class="card-head">
            <h2 class="card-title"><KeyRound :size="14" />{{ t('admin.agents.secretStore') }}</h2>
            <span
              class="badge"
              :class="data?.secret_store?.initialized ? 'badge-up' : 'badge-down'"
            >
              {{ data?.secret_store?.initialized ? t('admin.agents.initialized') : t('admin.agents.notInitialized') }}
            </span>
          </header>

          <div class="ag-kv">
            <div class="kv-row">
              <span class="ag-kv-k">{{ t('admin.agents.storeStatus') }}</span>
              <span class="ag-kv-v mono">
                {{ t('admin.agents.cipherCount', undefined, { count: data?.secret_store?.count ?? 0 }) }}
                · {{ t('admin.agents.filePerm') }} {{ data?.secret_store?.store_mode || '--' }}
              </span>
            </div>

            <div class="kv-row">
              <span class="ag-kv-k">{{ t('admin.agents.readPriority') }}</span>
              <span class="ag-kv-v mono">{{ data?.secret_store?.source_priority || 'encrypted-store-over-env' }}</span>
            </div>

            <div
              v-for="k in (data?.secret_store?.keys || [])"
              :key="k"
              class="kv-row"
            >
              <span class="ag-kv-k mono truncate" :title="k">{{ k }}</span>
              <span class="badge badge-up">{{ t('admin.agents.configured') }}</span>
            </div>
          </div>
        </section>
      </div>
    </template>
  </div>
</template>

<style scoped>
.ag {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}

/* ══ 状态带 ══ */









/* ══ 名册 ══ */
.ag-skel {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: var(--ds-space-4);
}
.ag-rows {
  display: flex;
  flex-direction: column;
}
.ag-row {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr) 84px minmax(0, 1fr) 92px;
  align-items: center;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
  transition: background-color var(--dur-fast);
}
.ag-row:last-child {
  border-bottom: 0;
}
.ag-row:not(.ag-row-head):hover {
  background-color: var(--ds-color-bg-hover);
}
.ag-row-head {
  min-height: 30px;
  padding-top: 0;
  padding-bottom: 0;
  background-color: var(--ds-color-bg-surface-inset);
  font-size: var(--text-3xs);
  font-weight: 500;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ds-color-text-placeholder);
}
.ag-main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.ag-name {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ag-role {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.ag-run {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  min-width: 0;
  flex-wrap: wrap;
}
.ag-run-time {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
  white-space: nowrap;
}
.ag-age {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-secondary);
  text-align: right;
}

@media (max-width: 1000px) {
  .ag-row {
    grid-template-columns: 26px minmax(0, 1fr) auto;
  }
  .ag-run,
  .ag-age {
    grid-column: 2 / -1;
  }
  .ag-age {
    text-align: left;
  }
  .ag-row-head {
    display: none;
  }
}

/* ══ 遥测 / 密文库 ══ */
.ag-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-4);
  align-items: start;
}
@media (min-width: 1100px) {
  .ag-grid {
    grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr);
  }
}
.ag-policy {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
  font-size: var(--text-3xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-description);
}
.ag-stats {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  border-bottom: 1px solid var(--ds-color-border-default);
}
.ag-stat {
  display: flex;
  flex-direction: column;
  gap:4px;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-left: 1px solid var(--ds-color-border-default);
}
.ag-stat:first-child {
  border-left: 0;
}
.ag-stat-v {
  font-size: var(--text-md);
  font-weight: 500;
  color: var(--ds-color-text-primary);
  font-variant-numeric: tabular-nums;
}
.ag-stat-v.is-up {
  color: var(--up);
}
.ag-stat-v.is-warn {
  color: var(--warn);
}
.ag-calls-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3) var(--ds-space-4) 6px;
}
.ag-calls {
  padding: 0 0 var(--ds-space-3);
  max-height: 300px;
}
.ag-call {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto 58px 60px 56px;
  align-items: center;
  gap: var(--ds-space-3);
  padding: 4px var(--ds-space-4);
  font-size: var(--text-4xs);
}
.ag-call:hover {
  background-color: var(--ds-color-bg-hover);
}
.ag-call-caller {
  color: var(--ds-color-text-secondary);
  min-width: 0;
}
.ag-call-model {
  color: var(--ds-color-text-placeholder);
  min-width: 0;
}
.ag-call-n {
  color: var(--ds-color-text-placeholder);
  text-align: right;
}
/* 缓存三态：命中(绿) / 上游上报未命中(琥珀) / 上游未上报(灰，不可判定) */
.ag-call-cache {
  color: var(--ds-color-text-placeholder);
  text-align: right;
  white-space: nowrap;
}
.ag-call-cache.is-up {
  color: var(--up);
}
.ag-call-cache.is-warn {
  color: var(--warn);
}

/* 密文库 */
.ag-kv {
  display: flex;
  flex-direction: column;
}
.ag-kv-k {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
  min-width: 0;
}
.ag-kv-v {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-primary);
  text-align: right;
}
</style>
