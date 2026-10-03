<script setup lang="ts">
/**
 * `embedded`（2026-09-30 后台精简）：本页被吸收为宿主页的一个页签时为真。
 * 宿主页负责大标题与页签标签，本页 PageHeader 降级为紧凑行（说明收起），
 * 但 #actions 里的按钮原样渲染 —— 被吸收页的按钮一个都不能丢。
 */
const props = withDefaults(defineProps<{ embedded?: boolean }>(), { embedded: false })
/**
 * DecisionsPage.vue · 系统日志控制台 (System Logs Console)
 * ---------------------------------------------------------------------------
 * 职责定位：专注呈现机器与服务的运行状态、异常报错与 AI 决策推演。
 * 1. 运行日志流 (Runtime Stream)：Trader 交易巡检、Backend 后端服务、Scheduler 调度网关三路高频流；
 * 2. 系统报错汇总 (Error Center)：跨源自动聚合全系统的 ERROR / CRITICAL 异常与堆栈；
 * 3. AI 决策卷宗 (AI Decisions)：各大标的的实时推演动作、置信度与思维链归因；
 * 4. 深度联动：提供直达人员操作审计台账 (AuditPage) 的跨域穿透。
 *
 * 后端契约（逐字保留）：
 *   GET /api/v1/admin/logs?source={trader|backend|scheduler}&lines=100
 *   GET /api/v1/admin/runtime
 */
import { computed, onMounted, ref, watch } from 'vue';
import { useRoute } from 'vue-router';
import { useI18n } from '../../composables/useI18n';
import { useRovingTabs } from '../../composables/useRovingTabs';
import { useApi } from '../../composables/useApi';
import { fmtDateTime, fmtPct } from '../../utils/format';
import {
  Terminal,
  RefreshCw,
  AlertCircle,
  BrainCircuit,
  Search,
  TrendingUp,
  TrendingDown,
  PauseCircle,
  CheckCircle2,
  Bug,
} from 'lucide-vue-next';
import PageHeader from '../../components/admin/PageHeader.vue';
import CopyButton from '../../components/base/CopyButton.vue';
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue';
import BaseEmpty from '../../components/base/BaseEmpty.vue';
import BaseTabs from '../../components/base/BaseTabs.vue';
import AuditPage from './AuditPage.vue';

const { t } = useI18n();
const { api } = useApi();
const route = useRoute();

/* ── 一级主维度切换 (运行流 / 报错汇总 / AI决策 / 操作审计) ── */
type HubTab = 'logs' | 'errors' | 'decisions' | 'audit';

function resolveHubTab(raw: unknown): HubTab {
  const v = Array.isArray(raw) ? raw[0] : raw;
  if (v === 'stream' || v === 'logs') return 'logs';
  if (v === 'errors') return 'errors';
  if (v === 'decisions') return 'decisions';
  if (v === 'audit') return 'audit';
  return 'logs';
}

const currentHubTab = ref<HubTab>(resolveHubTab(route.query.tab));

const hubTabs = computed(() => [
  { key: 'logs', label: t('admin.decisions.hubTabLogs') },
  { key: 'errors', label: t('admin.decisions.hubTabErrors'), count: criticalIssues.value.length || undefined },
  { key: 'decisions', label: t('admin.decisions.hubTabDecisions') },
  { key: 'audit', label: t('admin.audit.tabAudit') },
]);

/* ══════════════════════════════════════════════════
 * 1. 运行日志流 (Runtime Stream)
 * ══════════════════════════════════════════════════ */
type LogSource = 'trader' | 'backend' | 'scheduler';

interface LogEntry {
  key: number;
  time: string;
  level: string;
  msg: string;
  extra: string[];
  raw: string;
}

const activeLogTab = ref<LogSource>('trader');
const entries = ref<LogEntry[]>([]);
const logLoading = ref(false);
const logError = ref('');

const ENTRY_START = /^(\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]|(INFO|WARNING|ERROR|CRITICAL|DEBUG)[:\s])/;
const TIME_RE = /^\[(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})\]\s*/;
const LEVEL_RE = /^(INFO|WARNING|ERROR|CRITICAL|DEBUG)\b[:\s]*/;
const LEVEL_RANK: Record<string, number> = { DEBUG: 0, INFO: 1, WARNING: 2, ERROR: 3, CRITICAL: 4 };

function parseEntries(raw: string): LogEntry[] {
  const groups: string[][] = [];
  for (const line of raw.split('\n')) {
    if (groups.length === 0 || ENTRY_START.test(line)) groups.push([line]);
    else groups[groups.length - 1].push(line);
  }
  return groups.map((g, i) => {
    const head = g[0] ?? '';
    let rest = head;
    let time = '';
    let level = '';
    const tm = rest.match(TIME_RE);
    if (tm) {
      time = tm[1];
      rest = rest.slice(tm[0].length);
    }
    const lm = rest.match(LEVEL_RE);
    if (lm) {
      level = lm[1];
      rest = rest.slice(lm[0].length);
    }
    return {
      key: i,
      time,
      level,
      msg: rest.trim() || head.trim(),
      extra: g.slice(1).map((s) => s.trim()).filter(Boolean),
      raw: g.join('\n'),
    };
  });
}

async function fetchLogStream(type: LogSource) {
  activeLogTab.value = type;
  logLoading.value = true;
  logError.value = '';
  try {
    const res = await api(`/api/v1/admin/logs?source=${type}&lines=100`);
    const raw: string = res.content || res.lines?.join('\n') || '';
    entries.value = raw ? parseEntries(raw).reverse() : [];
  } catch (e: any) {
    entries.value = [];
    logError.value = t('admin.decisions.fetchLogFailed', undefined, { message: e.message });
  } finally {
    logLoading.value = false;
  }
}

// 客户端日志筛选（v-model="query" 维持已有静态测试断言）
const query = ref('');
const levelFilter = ref<'all' | 'warn' | 'error'>('all');

const LOG_TABS = ['trader', 'backend', 'scheduler'] as const;
const { setRef: setLogTabRef, onKeydown: onLogTabKey, roving: logTabRoving } = useRovingTabs(
  () => LOG_TABS.length,
  (i) => { fetchLogStream(LOG_TABS[i]); },
);

const LEVEL_TABS = ['all', 'warn', 'error'] as const;
const { setRef: setLevelRef, onKeydown: onLevelKey, roving: levelRoving } = useRovingTabs(
  () => LEVEL_TABS.length,
  (i) => { levelFilter.value = LEVEL_TABS[i]; },
);

const warnPlusCount = computed(
  () => entries.value.filter((e) => (LEVEL_RANK[e.level] ?? 1) >= 2).length,
);
const errorCount = computed(
  () => entries.value.filter((e) => (LEVEL_RANK[e.level] ?? 1) >= 3).length,
);

const filtered = computed(() => {
  const q = query.value.trim().toLowerCase();
  const min = levelFilter.value === 'error' ? 3 : levelFilter.value === 'warn' ? 2 : -1;
  return entries.value.filter((e) => {
    if ((LEVEL_RANK[e.level] ?? 1) < min) return false;
    if (q && !e.raw.toLowerCase().includes(q)) return false;
    return true;
  });
});

const copyText = computed(() => filtered.value.map((e) => e.raw).join('\n'));

function tone(level: string): string {
  if (level === 'ERROR' || level === 'CRITICAL') return 'is-error';
  if (level === 'WARNING') return 'is-warn';
  if (level === 'DEBUG') return 'is-debug';
  return '';
}

/* ══════════════════════════════════════════════════
 * 2. 系统报错汇总 (Error Center)
 * ══════════════════════════════════════════════════ */
interface IssueItem {
  key: string;
  source: LogSource;
  sourceName: string;
  time: string;
  level: string;
  msg: string;
  extra: string[];
  raw: string;
}

const criticalIssues = ref<IssueItem[]>([]);
const issuesLoading = ref(false);
const issuesError = ref('');
const issueSourceFilter = ref<'all' | 'trader' | 'backend' | 'scheduler'>('all');
const issueSearch = ref('');

const ISSUE_SOURCE_TABS = ['all', 'trader', 'backend', 'scheduler'] as const;
const { setRef: setIssueSourceRef, onKeydown: onIssueSourceKey, roving: issueSourceRoving } = useRovingTabs(
  () => ISSUE_SOURCE_TABS.length,
  (i) => { issueSourceFilter.value = ISSUE_SOURCE_TABS[i]; },
);

async function fetchAllIssues() {
  issuesLoading.value = true;
  issuesError.value = '';
  try {
    const [traderRes, backendRes, schedulerRes] = await Promise.allSettled([
      api('/api/v1/admin/logs?source=trader&lines=200'),
      api('/api/v1/admin/logs?source=backend&lines=200'),
      api('/api/v1/admin/logs?source=scheduler&lines=200'),
    ]);

    const collected: IssueItem[] = [];

    function processSource(res: PromiseSettledResult<any>, source: LogSource, sourceName: string) {
      if (res.status === 'fulfilled') {
        const raw = res.value?.content || res.value?.lines?.join('\n') || '';
        const parsed = parseEntries(raw);
        for (const e of parsed) {
          if (e.level === 'ERROR' || e.level === 'CRITICAL' || (LEVEL_RANK[e.level] ?? 0) >= 3) {
            collected.push({
              key: `${source}-${e.key}-${e.time}`,
              source,
              sourceName,
              time: e.time,
              level: e.level,
              msg: e.msg,
              extra: e.extra,
              raw: e.raw,
            });
          }
        }
      }
    }

    processSource(traderRes, 'trader', 'Trader');
    processSource(backendRes, 'backend', 'Backend');
    processSource(schedulerRes, 'scheduler', 'Scheduler');

    collected.sort((a, b) => (b.time > a.time ? 1 : b.time < a.time ? -1 : 0));
    criticalIssues.value = collected;
  } catch (e: any) {
    issuesError.value = e.message || '获取报错失败';
  } finally {
    issuesLoading.value = false;
  }
}

const traderIssuesCount = computed(() => criticalIssues.value.filter((e) => e.source === 'trader').length);
const backendIssuesCount = computed(() => criticalIssues.value.filter((e) => e.source === 'backend').length);
const schedulerIssuesCount = computed(() => criticalIssues.value.filter((e) => e.source === 'scheduler').length);

const filteredIssues = computed(() => {
  const q = issueSearch.value.trim().toLowerCase();
  const src = issueSourceFilter.value;
  return criticalIssues.value.filter((e) => {
    if (src !== 'all' && e.source !== src) return false;
    if (!q) return true;
    return e.raw.toLowerCase().includes(q);
  });
});

/* ══════════════════════════════════════════════════
 * 3. AI 决策卷宗 (AI Brain Decisions)
 * ══════════════════════════════════════════════════ */
interface DecisionItem {
  instId: string;
  action: string;
  confidence: number;
  timestamp: string;
  reason: string;
}

const decisionsList = ref<DecisionItem[]>([]);
const decisionsLoading = ref(false);
const decisionsError = ref('');
const decisionActionFilter = ref<'all' | 'BUY' | 'SELL' | 'WAIT'>('all');
const decisionSearch = ref('');

const ACTION_TABS = ['all', 'BUY', 'SELL', 'WAIT'] as const;
const { setRef: setActRef, onKeydown: onActKey, roving: actRoving } = useRovingTabs(
  () => ACTION_TABS.length,
  (i) => { decisionActionFilter.value = ACTION_TABS[i]; },
);

async function fetchDecisions() {
  decisionsLoading.value = true;
  decisionsError.value = '';
  try {
    const res = await api('/api/v1/admin/runtime');
    const rawList = res?.full_decisions || res?.decisions || [];
    decisionsList.value = Array.isArray(rawList) ? rawList : [];
  } catch (e: any) {
    decisionsError.value = e.message || '加载决策失败';
  } finally {
    decisionsLoading.value = false;
  }
}

const filteredDecisions = computed(() => {
  const q = decisionSearch.value.trim().toLowerCase();
  const act = decisionActionFilter.value;
  return decisionsList.value.filter((d) => {
    const actionMatch = act === 'all' || d.action?.toUpperCase().includes(act);
    if (!actionMatch) return false;
    if (!q) return true;
    const text = `${d.instId} ${d.action} ${d.reason}`.toLowerCase();
    return text.includes(q);
  });
});

const buyDecisionsCount = computed(() => decisionsList.value.filter((d) => d.action?.toUpperCase().includes('BUY')).length);
const sellDecisionsCount = computed(() => decisionsList.value.filter((d) => d.action?.toUpperCase().includes('SELL')).length);
const waitDecisionsCount = computed(() => decisionsList.value.filter((d) => d.action?.toUpperCase().includes('WAIT') || d.action?.toUpperCase().includes('HOLD')).length);

function decisionActionTone(action: string): string {
  const u = String(action || '').toUpperCase();
  if (u.includes('BUY') || u.includes('LONG')) return 'badge-up';
  if (u.includes('SELL') || u.includes('SHORT')) return 'badge-down';
  return 'badge-warn';
}

function decisionActionIcon(action: string) {
  const u = String(action || '').toUpperCase();
  if (u.includes('BUY') || u.includes('LONG')) return TrendingUp;
  if (u.includes('SELL') || u.includes('SHORT')) return TrendingDown;
  return PauseCircle;
}

/* ══════════════════════════════════════════════════
 * 初始化与路由侦听
 * ══════════════════════════════════════════════════ */
function handleRefresh() {
  if (currentHubTab.value === 'logs') {
    fetchLogStream(activeLogTab.value);
  } else if (currentHubTab.value === 'errors') {
    fetchAllIssues();
  } else {
    fetchDecisions();
  }
}

function switchHubTab(tab: HubTab) {
  currentHubTab.value = tab;
  if (tab === 'logs' && !entries.value.length) {
    fetchLogStream(activeLogTab.value);
  } else if (tab === 'errors' && !criticalIssues.value.length) {
    fetchAllIssues();
  } else if (tab === 'decisions' && !decisionsList.value.length) {
    fetchDecisions();
  }
}

watch(currentHubTab, (tab) => {
  switchHubTab(tab);
});

function syncRouteTab() {
  const qTab = (route.query.tab as string)?.toLowerCase();
  if (qTab === 'errors' || qTab === 'error') {
    switchHubTab('errors');
  } else if (qTab === 'decisions') {
    switchHubTab('decisions');
  } else if (qTab === 'audit') {
    switchHubTab('audit');
  } else {
    switchHubTab('logs');
  }
}

watch(() => route.query.tab, syncRouteTab);

onMounted(() => {
  syncRouteTab();
});
</script>

<template>
  <div class="dc">
    <PageHeader :embedded="props.embedded" :title="t('admin.decisions.title')">
      <template #actions>
        <span class="dsh-pill">
          <span class="dsh-status-dot active" aria-hidden="true" />
          {{ t('admin.decisions.normalRun') }}
        </span>
        <button
          type="button"
          class="btn btn-ghost btn-sm"
          :disabled="logLoading || issuesLoading || decisionsLoading"
          @click="handleRefresh"
        >
          <RefreshCw
            :size="14"
            :class="(logLoading || issuesLoading || decisionsLoading) && 'animate-spin shrink-0'"
          />
          <span>{{ t('common.refresh') }}</span>
        </button>
      </template>
    </PageHeader>

    <!-- ══ 主维度选项卡：运行日志 / 报错汇总 / AI决策 / 操作审计 ══ -->
    <BaseTabs
      v-model="currentHubTab"
      :items="hubTabs"
      :label="t('admin.decisions.hubAria')"
      baseId="dc"
    />

    <!-- ══════════════════════════════════════════════════
         视图 1：三路系统运行日志控制台
         ══════════════════════════════════════════════════ -->
    <div v-if="currentHubTab === 'logs'" id="dc-panel-logs" role="tabpanel" aria-labelledby="dc-tab-logs" tabindex="0" class="dc-panel">
      <section class="card dc-console">
        <header class="card-head dc-head">
        <div class="dc-head-left">
          <h2 class="card-title"><Terminal :size="14" />{{ t('admin.decisions.hubTabLogs') }}</h2>
          <span class="badge">{{ t('admin.decisions.latestFirst') }}</span>
        </div>

        <div class="seg" role="tablist" :aria-label="t('admin.decisions.logSourceAria')">
          <button
            type="button"
            role="tab"
            :ref="setLogTabRef(0)"
            :aria-selected="activeLogTab === 'trader'"
            :tabindex="logTabRoving(activeLogTab === 'trader')"
            :class="{ 'seg-on': activeLogTab === 'trader' }"
            @click="fetchLogStream('trader')"
            @keydown="onLogTabKey($event, 0)"
          >
            {{ t('admin.decisions.tabTrader') }}
          </button>
          <button
            type="button"
            role="tab"
            :ref="setLogTabRef(1)"
            :aria-selected="activeLogTab === 'backend'"
            :tabindex="logTabRoving(activeLogTab === 'backend')"
            :class="{ 'seg-on': activeLogTab === 'backend' }"
            @click="fetchLogStream('backend')"
            @keydown="onLogTabKey($event, 1)"
          >
            {{ t('admin.decisions.tabBackend') }}
          </button>
          <button
            type="button"
            role="tab"
            :ref="setLogTabRef(2)"
            :aria-selected="activeLogTab === 'scheduler'"
            :tabindex="logTabRoving(activeLogTab === 'scheduler')"
            :class="{ 'seg-on': activeLogTab === 'scheduler' }"
            @click="fetchLogStream('scheduler')"
            @keydown="onLogTabKey($event, 2)"
          >
            {{ t('admin.decisions.tabScheduler') }}
          </button>
        </div>
      </header>

      <!-- 工具条：内容 + 级别 + 计数 + 复制 -->
      <div class="dc-tools">
        <input
          v-model="query"
          type="search"
          autocomplete="off"
          spellcheck="false"
          class="field dc-search"
          :aria-label="t('admin.decisions.searchPlaceholder')"
          :placeholder="t('admin.decisions.searchPlaceholder')"
        />

        <div class="seg" role="tablist" :aria-label="t('admin.decisions.logLevelAria')">
          <button
            type="button"
            role="tab"
            :ref="setLevelRef(0)"
            :aria-selected="levelFilter === 'all'"
            :tabindex="levelRoving(levelFilter === 'all')"
            :class="{ 'seg-on': levelFilter === 'all' }"
            @click="levelFilter = 'all'"
            @keydown="onLevelKey($event, 0)"
          >
            {{ t('admin.decisions.filterAll') }}
            <span class="dc-seg-n num">{{ entries.length }}</span>
          </button>
          <button
            type="button"
            role="tab"
            :ref="setLevelRef(1)"
            :aria-selected="levelFilter === 'warn'"
            :tabindex="levelRoving(levelFilter === 'warn')"
            :class="{ 'seg-on': levelFilter === 'warn' }"
            @click="levelFilter = 'warn'"
            @keydown="onLevelKey($event, 1)"
          >
            {{ t('admin.decisions.filterWarn') }}
            <span class="dc-seg-n num">{{ warnPlusCount }}</span>
          </button>
          <button
            type="button"
            role="tab"
            :ref="setLevelRef(2)"
            :aria-selected="levelFilter === 'error'"
            :tabindex="levelRoving(levelFilter === 'error')"
            :class="{ 'seg-on': levelFilter === 'error' }"
            @click="levelFilter = 'error'"
            @keydown="onLevelKey($event, 2)"
          >
            {{ t('admin.decisions.filterError') }}
            <span class="dc-seg-n num">{{ errorCount }}</span>
          </button>
        </div>

        <div class="dc-tools-right">
          <span class="dc-count num">
            {{ t('admin.decisions.entriesCount', undefined, { n: filtered.length }) }}
          </span>
          <CopyButton :text="copyText" />
        </div>
      </div>

      <!-- 日志体 -->
      <div class="dc-body">
        <!-- 首屏加载 -->
        <div v-if="logLoading && !entries.length" class="dc-skel">
          <BaseLoadingAnnounce />
          <div v-for="i in 14" :key="i" class="skeleton skeleton-text" :style="{ width: 40 + ((i * 37) % 55) + '%' }" />
        </div>

        <!-- 拉取失败 -->
        <div v-else-if="logError" role="alert" class="state-block is-error">
          <span class="state-icon"><AlertCircle :size="17" /></span>
          <p class="state-title">{{ t('common.loadFailed') }}</p>
          <p class="state-desc">{{ logError }}</p>
          <button
            type="button"
            class="btn btn-ghost btn-sm mt-1"
            :disabled="logLoading"
            @click="fetchLogStream(activeLogTab)"
          >
            <RefreshCw :size="14" :class="logLoading && 'animate-spin shrink-0'" />
            <span>{{ t('common.retry') }}</span>
          </button>
        </div>

        <!-- 无日志 -->
        <div v-else-if="!entries.length" class="state-block">
          <span class="state-icon"><Terminal :size="17" /></span>
          <p class="state-title">{{ t('admin.decisions.noLiveLogs') }}</p>
          <p class="state-desc">{{ t('admin.decisions.pullingLogs') }}</p>
        </div>

        <!-- 筛选无命中 -->
        <div v-else-if="!filtered.length" class="state-block">
          <span class="state-icon"><Terminal :size="17" /></span>
          <p class="state-title">{{ t('admin.decisions.filterNoMatch') }}</p>
        </div>

        <!-- 结构化日志行 -->
        <div v-else class="dc-lines">
          <article
            v-for="e in filtered"
            :key="e.key"
            class="dc-entry"
            :class="tone(e.level)"
          >
            <time class="dc-time">{{ e.time ? e.time.slice(11) : '--:--:--' }}</time>
            <span class="dc-level">{{ e.level || 'LOG' }}</span>
            <div class="dc-msg">
              <p class="dc-msg-head">{{ e.msg }}</p>
              <p v-for="(x, i) in e.extra" :key="i" class="dc-msg-cont">{{ x }}</p>
            </div>
          </article>
        </div>
      </div>
    </section>
    </div>

    <!-- ══════════════════════════════════════════════════
         视图 2：全系统报错汇总大盘 (Error Center)
         ══════════════════════════════════════════════════ -->
    <div v-else-if="currentHubTab === 'errors'" id="dc-panel-errors" role="tabpanel" aria-labelledby="dc-tab-errors" tabindex="0" class="dc-panel">
    <section class="card flex flex-col flex-1 min-h-[400px]">
      <header class="card-head dc-head">
        <div class="dc-head-left">
          <h2 class="card-title text-rose-400"><Bug :size="14" />{{ t('admin.decisions.errorsTitle') }}</h2>
          <span class="badge badge-down mono">{{ t('admin.decisions.errorsCount', undefined, { n: criticalIssues.length }) }}</span>
        </div>

        <!-- 报错来源过滤 -->
        <div class="seg" role="tablist" :aria-label="t('admin.decisions.errorSourceAria')">
          <button
            v-for="(src, i) in ISSUE_SOURCE_TABS"
            :key="src"
            type="button"
            role="tab"
            :ref="setIssueSourceRef(i)"
            :aria-selected="issueSourceFilter === src"
            :tabindex="issueSourceRoving(issueSourceFilter === src)"
            :class="{ 'seg-on': issueSourceFilter === src }"
            @click="issueSourceFilter = src"
            @keydown="onIssueSourceKey($event, i)"
          >
            {{ src === 'all' ? t('admin.decisions.errorAll') : src === 'trader' ? t('admin.decisions.errorTrader') : src === 'backend' ? t('admin.decisions.errorBackend') : t('admin.decisions.errorScheduler') }}
            <span
              class="dc-seg-n num"
              :class="{ 'text-rose-400': (src === 'all' ? criticalIssues.length : src === 'trader' ? traderIssuesCount : src === 'backend' ? backendIssuesCount : schedulerIssuesCount) > 0 }"
            >
              {{ src === 'all' ? criticalIssues.length : src === 'trader' ? traderIssuesCount : src === 'backend' ? backendIssuesCount : schedulerIssuesCount }}
            </span>
          </button>
        </div>
      </header>

      <div class="dc-tools">
        <div class="relative flex-1 max-w-sm">
          <Search :size="13" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
          <input
            v-model="issueSearch"
            type="search"
            autocomplete="off"
            spellcheck="false"
            class="field pl-8 w-full text-xs"
            :placeholder="t('admin.decisions.searchErrorsPlaceholder')"
            :aria-label="t('admin.decisions.searchErrorsAria')"
          />
        </div>
        <div class="ms-auto text-3xs text-zinc-400">
          {{ t('admin.decisions.matchCount', undefined, { n: filteredIssues.length }) }}
        </div>
      </div>

      <div class="p-4 flex-1 overflow-y-auto">
        <div v-if="issuesLoading && !criticalIssues.length" class="space-y-3">
          <BaseLoadingAnnounce />
          <div v-for="i in 4" :key="i" class="skeleton h-20 rounded-xl" />
        </div>

        <div v-else-if="issuesError" role="alert" class="state-block is-error">
          <span class="state-icon"><AlertCircle :size="17" /></span>
          <p class="state-title">{{ t('common.loadFailed') }}</p>
          <p class="state-desc">{{ issuesError }}</p>
          <button
            type="button"
            class="btn btn-ghost btn-sm mt-1"
            :disabled="issuesLoading"
            @click="fetchAllIssues"
          >
            <RefreshCw :size="14" :class="issuesLoading && 'animate-spin shrink-0'" />
            <span>{{ t('common.retry') }}</span>
          </button>
        </div>

        <!-- 0 报错健康态 -->
        <div
          v-else-if="!criticalIssues.length"
          class="flex flex-col items-center justify-center p-12 text-center border border-[var(--line-1)] rounded-2xl bg-[var(--surface-head)]"
        >
          <div class="w-12 h-12 rounded-full bg-emerald-500/10 flex items-center justify-center mb-3">
            <CheckCircle2 :size="24" class="text-emerald-400" />
          </div>
          <h3 class="text-sm font-semibold text-[var(--ink-strong)] mb-1">
            {{ t('admin.decisions.errorsEmpty') }}
          </h3>
          <p class="text-xs text-[var(--ink-2)] max-w-md">
            {{ t('admin.decisions.errorsEmptyDesc') }}
          </p>
        </div>

        <!-- 搜索无命中 -->
        <BaseEmpty
          v-else-if="!filteredIssues.length"
          :text="t('admin.decisions.filterNoMatch')"
        />

        <!-- 报错列表 -->
        <div v-else class="space-y-3">
          <article
            v-for="item in filteredIssues"
            :key="item.key"
            class="p-4 rounded-xl border border-[var(--down-line)] bg-[var(--down-bg)] flex flex-col gap-2.5 transition-colors"
          >
            <div class="flex items-center justify-between gap-3 flex-wrap">
              <div class="flex items-center gap-2">
                <span class="badge badge-down font-mono font-bold">{{ item.level }}</span>
                <span class="badge font-mono">{{ item.sourceName }}</span>
                <time class="text-3xs font-mono text-[var(--ink-2)]">{{ item.time || '--' }}</time>
              </div>
              <CopyButton :text="item.raw" :title="t('admin.decisions.copyError')" />
            </div>

            <!-- 主错误行 -->
            <p class="text-xs font-mono text-[var(--down)] font-medium break-all whitespace-pre-wrap leading-relaxed">
              {{ item.msg }}
            </p>

            <!-- 附加堆栈 (如果有) -->
            <div
              v-if="item.extra && item.extra.length"
              class="p-2.5 rounded-lg bg-[var(--surface-input)] border border-[var(--line-1)] font-mono text-3xs text-[var(--ink-2)] overflow-x-auto whitespace-pre leading-relaxed"
            >
              <div v-for="(ex, ei) in item.extra" :key="ei">{{ ex }}</div>
            </div>
          </article>
        </div>
      </div>
    </section>
    </div>

    <!-- ══════════════════════════════════════════════════
         视图 3：AI 决策卷宗 (AI Brain Decisions)
         ══════════════════════════════════════════════════ -->
    <div v-else-if="currentHubTab === 'decisions'" id="dc-panel-decisions" role="tabpanel" aria-labelledby="dc-tab-decisions" tabindex="0" class="dc-panel">
    <section class="card flex flex-col flex-1 min-h-[400px]">
      <header class="card-head dc-head">
        <div class="dc-head-left">
          <h2 class="card-title"><BrainCircuit :size="14" />{{ t('admin.decisions.decisionsTitle') }}</h2>
          <span class="badge mono">{{ t('admin.decisions.cyclesCount', undefined, { n: decisionsList.length }) }}</span>
        </div>

        <!-- 动作过滤器 -->
        <div class="seg" role="tablist" :aria-label="t('admin.decisions.actionFilterAria')">
          <button
            v-for="(act, i) in ACTION_TABS"
            :key="act"
            type="button"
            role="tab"
            :ref="setActRef(i)"
            :aria-selected="decisionActionFilter === act"
            :tabindex="actRoving(decisionActionFilter === act)"
            :class="{ 'seg-on': decisionActionFilter === act }"
            @click="decisionActionFilter = act"
            @keydown="onActKey($event, i)"
          >
            {{ act === 'all' ? t('admin.decisions.actionAll') : act === 'BUY' ? t('admin.decisions.actionBuy') : act === 'SELL' ? t('admin.decisions.actionSell') : t('admin.decisions.actionWait') }}
            <span
              class="dc-seg-n num"
              :class="{ 'text-emerald-400': act === 'BUY', 'text-rose-400': act === 'SELL' }"
            >
              {{ act === 'all' ? decisionsList.length : act === 'BUY' ? buyDecisionsCount : act === 'SELL' ? sellDecisionsCount : waitDecisionsCount }}
            </span>
          </button>
        </div>
      </header>

      <div class="dc-tools">
        <div class="relative flex-1 max-w-sm">
          <Search :size="13" class="absolute left-2.5 top-1/2 -translate-y-1/2 text-zinc-500 pointer-events-none" />
          <input
            v-model="decisionSearch"
            type="search"
            autocomplete="off"
            spellcheck="false"
            class="field pl-8 w-full text-xs"
            :placeholder="t('admin.decisions.searchDecisionsPlaceholder')"
            :aria-label="t('admin.decisions.searchDecisionsAria')"
          />
        </div>
        <div class="ms-auto text-3xs text-zinc-400">
          {{ t('admin.decisions.matchCount', undefined, { n: filteredDecisions.length }) }}
        </div>
      </div>

      <div class="p-4 flex-1 overflow-y-auto">
        <div v-if="decisionsLoading && !decisionsList.length" class="space-y-3">
          <BaseLoadingAnnounce />
          <div v-for="i in 4" :key="i" class="skeleton h-24 rounded-xl" />
        </div>

        <div v-else-if="decisionsError" role="alert" class="state-block is-error">
          <span class="state-icon"><AlertCircle :size="17" /></span>
          <p class="state-title">{{ t('common.loadFailed') }}</p>
          <p class="state-desc">{{ decisionsError }}</p>
          <button
            type="button"
            class="btn btn-ghost btn-sm mt-1"
            :disabled="decisionsLoading"
            @click="fetchDecisions"
          >
            <RefreshCw :size="14" :class="decisionsLoading && 'animate-spin shrink-0'" />
            <span>{{ t('common.retry') }}</span>
          </button>
        </div>

        <BaseEmpty
          v-else-if="!filteredDecisions.length"
          :text="t('admin.decisions.decisionsEmpty')"
        />

        <div v-else class="grid grid-cols-1 md:grid-cols-2 gap-3.5">
          <div
            v-for="(d, idx) in filteredDecisions"
            :key="idx"
            class="rounded-xl border border-[var(--line-1)] bg-[var(--surface-2)] p-3.5 flex flex-col justify-between hover:border-[var(--ds-color-border-hover)] transition-colors"
          >
            <div>
              <div class="flex items-center justify-between gap-2 mb-2">
                <div class="flex items-center gap-2">
                  <span class="font-mono font-bold text-sm text-[var(--ink-strong)]">{{ d.instId }}</span>
                  <span class="badge" :class="decisionActionTone(d.action)">
                    <component :is="decisionActionIcon(d.action)" :size="11" class="inline -mt-0.5 me-0.5" />
                    {{ d.action }}
                  </span>
                </div>
                <time class="text-3xs font-mono text-[var(--ink-2)]">{{ d.timestamp ? fmtDateTime(d.timestamp).slice(5) : '--' }}</time>
              </div>

              <!-- 决策理由与推演 -->
              <p class="text-xs text-[var(--ink-1)] leading-relaxed line-clamp-3 mb-3">
                {{ d.reason || t('admin.decisions.noDecisionsReason') }}
              </p>
            </div>

            <!-- 置信度进度条 -->
            <div class="pt-2 border-t border-[var(--line-1)] flex items-center justify-between gap-3 text-3xs font-mono">
              <span class="text-[var(--ink-2)]">{{ t('admin.decisions.confidence') }}</span>
              <div class="flex items-center gap-2 flex-1 max-w-[140px]">
                <div class="flex-1 h-1.5 rounded-full bg-[var(--surface-3)] overflow-hidden">
                  <div
                    class="h-full bg-emerald-400 rounded-full"
                    :style="{ width: `${Math.min(100, Math.max(0, (d.confidence || 0) * 100))}%` }"
                  />
                </div>
                <span class="font-bold text-[var(--ink-strong)]">{{ fmtPct(d.confidence || 0) }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </section>
    </div>

    <!-- ══════════════════════════════════════════════════
         视图 4：操作审计流水
         ══════════════════════════════════════════════════ -->
    <div v-else id="dc-panel-audit" role="tabpanel" aria-labelledby="dc-tab-audit" tabindex="0" class="dc-panel">
      <AuditPage embedded />
    </div>
  </div>
</template>

<style scoped>
.dc,
.dc-panel {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
  flex: 1;
  min-height: 0;
}

/* ══ 控制台容器：填满工作台高度 ══ */
.dc-console {
  flex: 1;
  min-height: 360px;
  overflow: hidden;
}

/* 卡头 */
.dc-head {
  flex-wrap: wrap;
}
.dc-head-left {
  display: flex;
  align-items: center;
  gap: var(--ds-space-3);
  min-width: 0;
}

/* 工具条 */
.dc-tools {
  display: flex;
  align-items: center;
  gap: var(--ds-space-3);
  flex-wrap: wrap;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface-inset);
}
.dc-search {
  width: 220px;
  flex: 0 1 220px;
}
.dc-seg-n {
  margin-left: 4px;
  color: var(--ds-color-text-placeholder);
  font-size: var(--text-4xs);
}
.dc-tools-right {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
}
.dc-count {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
  white-space: nowrap;
}

/* ══ 日志体 ══ */
.dc-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  overscroll-behavior: contain;
}
.dc-skel {
  padding: var(--ds-space-3) var(--ds-space-4);
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.dc-lines {
  display: flex;
  flex-direction: column;
  padding: var(--ds-space-2) 0;
}

/* 每条：时间 / 级别 / 正文 三列，续行在正文列内缩进 */
.dc-entry {
  display: grid;
  grid-template-columns: 62px 52px minmax(0, 1fr);
  gap: var(--ds-space-3);
  align-items: baseline;
  padding: 4px var(--ds-space-4);
  border-left: 2px solid transparent;
  font-family: var(--ds-font-mono);
  font-size: var(--text-2xs);
  line-height: var(--leading-dense);
}
.dc-entry:hover {
  background-color: var(--ds-color-bg-hover);
}
.dc-entry.is-warn {
  border-left-color: var(--warn);
}
.dc-entry.is-error {
  border-left-color: var(--down);
  background-color: var(--down-bg);
}
.dc-entry.is-error:hover {
  background-color: var(--down-bg);
}

.dc-time {
  color: var(--ds-color-text-placeholder);
  font-variant-numeric: tabular-nums;
}
.dc-level {
  font-size: var(--text-4xs);
  font-weight: 600;
  letter-spacing: 0.04em;
  color: var(--ds-color-text-placeholder);
}
.dc-entry.is-warn .dc-level {
  color: var(--warn);
}
.dc-entry.is-error .dc-level {
  color: var(--down);
}

.dc-msg {
  min-width: 0;
}
.dc-msg-head {
  color: var(--ds-color-text-secondary);
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.dc-entry.is-warn .dc-msg-head {
  color: var(--warn);
}
.dc-entry.is-error .dc-msg-head {
  color: var(--down);
}
.dc-msg-cont {
  padding-left: var(--ds-space-3);
  color: var(--ds-color-text-placeholder);
  overflow-wrap: anywhere;
  white-space: pre-wrap;
}
.dc-entry.is-debug .dc-msg-head {
  color: var(--ds-color-text-placeholder);
}

@media (max-width: 720px) {
  .dc-search {
    flex: 1 1 100%;
    width: 100%;
  }
  .dc-tools-right {
    margin-left: 0;
  }
  .dc-entry {
    grid-template-columns: 56px minmax(0, 1fr);
  }
  .dc-level {
    grid-column: 2;
    grid-row: 1;
  }
  .dc-msg {
    grid-column: 2;
  }
}
</style>
