<script setup lang="ts">
/**
 * GatewayPage.vue · 事件网关与调度器工位
 * ---------------------------------------------------------------------------
 * 骨架（推倒重来）：
 *   旧 = 手写页头 + 4 张独立指标卡 + 调度作业表 + 投递表
 *   新 = 共享 PageHeader → 运行状态带（4 项事实 · 发丝分隔单卡）
 *        → 调度作业清单（点/任务/触发/最近调度/状态，任务状态一眼可判）
 *        → 投递流水（保留 DataTable 外壳，状态改为徽章语义）
 *        → 重放确认为**对话框**，取代浏览器原生 prompt()
 *
 * 三态：首屏骨架 · 空态 · 拉取失败（含「已有旧数据时的刷新失败」细条提示）
 *
 * 后端契约（逐字未改）：
 *   GET  /api/v1/admin/gateway?limit=50
 *        → running / pid / version / stats{} / event_health{} / scheduler.jobs[] / deliveries[]
 *   POST /api/v1/admin/gateway/deliveries/{id}/replay
 *        body { confirmation: <输入去空格转大写> }
 *   ⚠️ 语义与旧版一致：仍由后端校验确认短语，前端只负责收集；输入非空即允许提交。
 */
import { computed, onMounted, ref, watch } from 'vue';
import { useI18n } from '../../composables/useI18n';
import { useRoute, useRouter } from 'vue-router';
import { useApi } from '../../composables/useApi';
import { useToast } from '../../composables/useToast';
import { useConfirm } from '../../composables/useConfirm';
import { useResource } from '../../composables/useResource';
import DataTable from '../../components/admin/DataTable.vue';
import BaseDialog from '../../components/base/BaseDialog.vue';
import PageHeader from '../../components/admin/PageHeader.vue';
import BaseTabs from '../../components/base/BaseTabs.vue';
import AgentsPage from './AgentsPage.vue';

import { Zap, RefreshCw, RotateCcw, Server, Clock, CalendarClock, AlertTriangle, Save } from 'lucide-vue-next';
import { fmtDateTime } from '../../utils/format';
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue';

const { t } = useI18n();

/**
 * 运行单元页签：本页是宿主页 ——
 *   dispatch 调度与投递（本页原有内容）
 *   workers  Worker 与遥测（AgentsPage）
 */
type GwTab = 'dispatch' | 'workers';
function resolveGwTab(raw: unknown): GwTab {
  const v = Array.isArray(raw) ? raw[0] : raw;
  return String(v) === 'workers' ? 'workers' : 'dispatch';
}
const route = useRoute();
const router = useRouter();
if (route.query.tab === 'logs') {
  router.replace('/admin/decisions');
}
const activeTab = ref<GwTab>(resolveGwTab(route.query.tab));
watch(() => route.query.tab, (v) => {
  if (v === 'logs') {
    router.replace('/admin/decisions');
    return;
  }
  activeTab.value = resolveGwTab(v);
});
const tabs = computed(() => [
  { key: 'dispatch', label: t('admin.gateway.tabDispatch') },
  { key: 'workers', label: t('admin.agents.title') },
]);
const { api } = useApi();
const toast = useToast();
const { ask } = useConfirm();

function fmtJobTime(iso: string): string {
  return fmtDateTime(iso).slice(5);
}

/** ⚠️ 显式 immediate: true —— useResource 的文档声明默认立即取数，
 *  但实现只在传入真值时 reload，故此处显式声明，避免页面永不自动加载。 */
const { data: gw, loading, error, loaded, reload: load } = useResource<any>(
  '/api/v1/admin/gateway?limit=50',
  {
    immediate: true,
    onError: (e) => toast.err(t('admin.gateway.msgs.loadFailed', undefined, { msg: e.message })),
  },
);

const showSkeleton = computed(() => loading.value && !loaded.value);
const jobs = computed<any[]>(() => gw.value?.scheduler?.jobs || []);
const deliveries = computed<any[]>(() => gw.value?.deliveries || []);

const deliveredCount = computed(() => (gw.value?.stats?.delivered ?? 0) + (gw.value?.stats?.accepted ?? 0));
const deliveryTotal = computed(() => Object.values(gw.value?.stats || {}).reduce((a: number, b: any) => a + Number(b || 0), 0));
const overdueCount = computed(() => jobs.value.filter((j: any) => j.overdue).length);

/* ── 重放确认对话框（取代 prompt()） ── */
const replayId = ref<number | null>(null);
const replayPhrase = ref('');
const replaying = ref(false);

const replayExpected = computed(() => (replayId.value != null ? `REPLAY ${replayId.value}` : ''));
const replayMatched = computed(
  () => replayPhrase.value.trim().toUpperCase() === replayExpected.value,
);

function openReplay(id: number) {
  replayId.value = id;
  replayPhrase.value = '';
}
function closeReplay() {
  replayId.value = null;
  replayPhrase.value = '';
}

async function confirmReplay() {
  const id = replayId.value;
  const phrase = replayPhrase.value;
  // 与旧版等价：空输入视为取消；其余一律提交，由后端裁定
  if (id == null || !phrase.trim()) return;
  replaying.value = true;
  try {
    await api(`/api/v1/admin/gateway/deliveries/${id}/replay`, {
      method: 'POST',
      body: JSON.stringify({ confirmation: phrase.trim().toUpperCase() }),
    });
    toast.ok(t('admin.gateway.msgs.replayed', undefined, { id }));
    closeReplay();
    await load();
  } catch (e: any) {
    toast.err(t('admin.gateway.msgs.replayFailed', undefined, { msg: e.message }));
  } finally {
    replaying.value = false;
  }
}

/** 投递状态语义 → 徽章色调（映射规则与旧版 statusColor 完全一致） */
function statusTone(s: string): string {
  if (s === 'success' || s === 'delivered' || s === 'ok') return 'badge-up';
  if (s === 'dead' || s === 'failed' || s === 'error') return 'badge-down';
  if (s === 'pending' || s === 'retrying') return 'badge-warn';
  return '';
}

/** 投递状态文案：查表本地化，未登记枚举原样回退（批 27）。 */
function statusLabel(s: string): string {
  return t(`admin.gateway.status.${s}`, s);
}

/* ══════════════════════════════════════════════════════════════════════════
 * 交易时段（2026-09-30）
 * ---------------------------------------------------------------------------
 * 后端契约（逐字）：
 *   GET  /api/v1/admin/gateway/trading-session
 *        → { enabled, mode_outside, timezone, windows[{days,start,end}],
 *            state{mode,restricted,reason,next_change_bj,errors[]}, coverage{}, … }
 *   PUT  同路径 body { enabled, mode_outside, windows[] }
 *
 * ⚠️ 为什么 `state` 由后端算：判定口径只有一份实现（scripts/trader/session.py）。
 *    前端自己比时间就会出现"页面说在窗口内、引擎按窗口外跑"的分叉，
 *    而那个分叉的代价是 43k token/次。
 * ⚠️ 时段一律北京时间（与提示词时间戳同源），页面只展示、不做时区换算。
 * ═════════════════════════════════════════════════════════════════════════ */

interface SessionWindow { days: number[]; start: string; end: string }

const session = ref<any>(null);
const sessionLoading = ref(false);
const sessionSaving = ref(false);
const sessionError = ref('');
const sessionLoaded = ref(false);
const draftEnabled = ref(false);
const draftMode = ref<'manage_only' | 'off'>('manage_only');
const draftWindows = ref<SessionWindow[]>([]);

/** 星期取值与后端同一口径：0=周一 … 6=周日。 */
const WEEKDAYS = [0, 1, 2, 3, 4, 5, 6];

function weekdayLabel(day: number): string {
  return t(`admin.gateway.session.weekdays.${day}`);
}

async function loadSession() {
  sessionLoading.value = true;
  sessionError.value = '';
  try {
    const res = await api('/api/v1/admin/gateway/trading-session');
    session.value = res;
    draftEnabled.value = !!res.enabled;
    draftMode.value = res.mode_outside === 'off' ? 'off' : 'manage_only';
    draftWindows.value = (res.windows || []).map((w: any) => ({
      days: [...(w.days || [])],
      start: String(w.start || ''),
      end: String(w.end || ''),
    }));
    sessionLoaded.value = true;
  } catch (e: any) {
    sessionError.value = e.message;
  } finally {
    sessionLoading.value = false;
  }
}

function addWindow() {
  draftWindows.value.push({ days: [], start: '09:00', end: '11:00' });
}

function removeWindow(index: number) {
  draftWindows.value.splice(index, 1);
}

function toggleDay(win: SessionWindow, day: number) {
  const at = win.days.indexOf(day);
  if (at >= 0) win.days.splice(at, 1);
  else win.days.push(day);
}

async function saveSession() {
  sessionSaving.value = true;
  sessionError.value = '';
  try {
    const res = await api('/api/v1/admin/gateway/trading-session', {
      method: 'PUT',
      body: JSON.stringify({
        enabled: draftEnabled.value,
        mode_outside: draftMode.value,
        windows: draftWindows.value,
      }),
    });
    session.value = res;
    toast.ok(t('admin.gateway.session.saved'));
    await loadSession();
  } catch (e: any) {
    sessionError.value = e.message;
    toast.err(t('admin.gateway.session.saveFailed', undefined, { msg: e.message }));
  } finally {
    sessionSaving.value = false;
  }
}

/** 恢复全天候运行 = **放松**方向（重新开始烧 token、重新开新仓）⇒ 需要一次确认。 */
async function resumeFullTime() {
  const ok = await ask({
    title: t('admin.gateway.session.resumeTitle'),
    desc: t('admin.gateway.session.resumeDesc'),
    okText: t('admin.gateway.session.resumeOk'),
    danger: true,
  });
  if (!ok) return;
  draftEnabled.value = false;
  draftWindows.value = [];
  draftMode.value = 'manage_only';
  await saveSession();
}

const sessionMode = computed<string>(() => session.value?.state?.mode || 'full');
const sessionNextChange = computed<string>(() => session.value?.state?.next_change_bj || '');
const sessionErrors = computed<string[]>(() => session.value?.state?.errors || []);
const sessionCoverage = computed<any>(() => session.value?.coverage || {});

onMounted(() => {
  loadSession();
});
</script>

<template>
  <div class="gw">
    <PageHeader :title="t('nav.admin.gateway')">
      <template #actions>
        <span class="badge">{{ t('admin.gateway.opsBadge') }}</span>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="loading" @click="load">
          <RefreshCw :size="14" :class="loading && 'animate-spin shrink-0'" />
          <span>{{ t('common.refresh') }}</span>
        </button>
      </template>
    </PageHeader>

    <!-- 页签：运行单元三块（被吸收页各自保留页头动作行，按钮一个不少） -->
    <BaseTabs v-model="activeTab" :items="tabs" :label="t('admin.gateway.tabsLabel')" baseId="gw" />

    <div v-if="activeTab === 'dispatch'" id="gw-panel-dispatch" role="tabpanel" aria-labelledby="gw-tab-dispatch" tabindex="0" class="gw-panel">

    <!-- 拉取失败（无任何数据） -->
    <div v-if="error && !gw" role="alert" class="state-block is-error">
      <span class="state-icon"><AlertTriangle :size="17" /></span>
      <p class="state-title">{{ t('common.loadFailed') }}</p>
      <!-- 批 24：原来这里复用 `msgs.loadFailed`（值 = 「加载失败：{msg}」），
           于是标题与说明连读成「加载失败 / 加载失败：stub failure」——同一句话说了两遍。
           toast 仍用带前缀的那条（toast 没有标题），这里只留原因。 -->
      <p class="state-desc">{{ error }}</p>
      <button type="button" class="btn btn-ghost btn-sm mt-1" :disabled="loading" @click="load">
        <RefreshCw :size="14" :class="loading && 'animate-spin shrink-0'" />
        <span>{{ t('common.retry') }}</span>
      </button>
    </div>

    <template v-else>
      <!-- 刷新失败但仍有旧数据：细条提示，不清空界面 -->
      <div v-if="error" role="status" aria-live="polite" class="gw-stale">
        <AlertTriangle :size="13" />
        <span>{{ t('admin.gateway.msgs.loadFailed', undefined, { msg: error }) }}</span>
        <button type="button" class="btn btn-quiet btn-sm" :disabled="loading" @click="load">
          <RefreshCw :size="14" :class="loading && 'animate-spin shrink-0'" aria-hidden="true" />
          {{ t('common.retry') }}
        </button>
      </div>

      <!-- ══ 运行状态带 ══ -->
      <section class="card band">
        <template v-if="showSkeleton">
          <BaseLoadingAnnounce />
          <div v-for="i in 4" :key="i" class="fact">
            <div class="skeleton skeleton-text" style="width: 50%" />
            <div class="skeleton skeleton-text skeleton-value" style="width: 70%" />
            <div class="skeleton skeleton-text" style="width: 38%" />
          </div>
        </template>

        <template v-else>
          <div class="fact">
            <span class="fact-label"><Server :size="12" />{{ t('admin.gateway.cards.process') }}</span>
            <span class="fact-value" :class="gw?.running ? 'is-up' : 'is-down'">
              {{ gw?.running ? 'ONLINE' : 'OFFLINE' }}
            </span>
            <span class="fact-foot mono">PID {{ gw?.pid || '--' }} · v{{ gw?.version }}</span>
          </div>

          <div class="fact">
            <span class="fact-label"><Zap :size="12" />{{ t('admin.gateway.cards.deliveryQueue') }}</span>
            <span class="fact-value num">
              {{ deliveredCount }}<span class="fact-sub"> / {{ deliveryTotal }}</span>
            </span>
            <span class="fact-foot mono">
              {{ t('admin.gateway.cards.queueStats', undefined, { n: gw?.stats?.pending ?? 0, m: gw?.stats?.retry ?? 0 }) }}
            </span>
          </div>

          <div class="fact">
            <span class="fact-label"><AlertTriangle :size="12" />{{ t('admin.gateway.cards.deadLetter') }}</span>
            <span class="fact-value num" :class="(gw?.stats?.dead ?? 0) > 0 ? 'is-down' : 'is-up'">
              {{ gw?.stats?.dead ?? 0 }}<span class="fact-sub"> / {{ gw?.event_health?.critical_total ?? 0 }}</span>
            </span>
            <span class="fact-foot mono">
              {{ t('admin.gateway.cards.criticalStats', undefined, { n: gw?.event_health?.critical_unmet ?? 0, m: gw?.event_health?.critical_failed ?? 0 }) }}
            </span>
          </div>

          <div class="fact">
            <span class="fact-label"><Clock :size="12" />{{ t('admin.gateway.cards.scheduler') }}</span>
            <span class="fact-value num">{{ jobs.length }}</span>
            <span class="fact-foot mono" :class="overdueCount > 0 ? 'is-down' : 'is-up'">
              {{ overdueCount > 0
                ? t('admin.gateway.cards.overdueJobs', undefined, { n: overdueCount })
                : t('admin.gateway.cards.noOverdue') }}
            </span>
          </div>
        </template>
      </section>

      <!-- ══ 调度作业 ══ -->
      <section v-if="showSkeleton || jobs.length" class="card">
        <header class="card-head">
          <div>
            <h2 class="card-title"><Clock :size="14" />{{ t('nav.admin.gateway') }}</h2>
            <p class="card-sub">{{ t('admin.gateway.scheduler.subtitle') }}</p>
          </div>
          <span class="badge">{{ t('admin.gateway.scheduler.managedJobs', undefined, { n: jobs.length }) }}</span>
        </header>

        <div v-if="showSkeleton" class="gw-jobs">
          <BaseLoadingAnnounce />
          <div v-for="i in 5" :key="i" class="gw-job">
            <span class="skeleton skeleton-dot" />
            <span class="skeleton skeleton-text" style="width: 40%" />
          </div>
        </div>

        <div v-else class="gw-jobs">
          <div class="gw-job gw-job-head">
            <span />
            <span>{{ t('admin.gateway.scheduler.colJob') }}</span>
            <span class="gw-job-cell">{{ t('admin.gateway.scheduler.colTrigger') }}</span>
            <span class="gw-job-cell">{{ t('admin.gateway.scheduler.colLastRun') }}</span>
            <span class="text-right sm:text-left">{{ t('admin.gateway.scheduler.colStatus') }}</span>
          </div>
          <div v-for="j in jobs" :key="j.name" class="gw-job" :class="{ 'is-overdue': j.overdue }">
            <span class="dsh-status-dot" :class="j.overdue ? 'error' : 'active'" aria-hidden="true" />
            <span class="gw-job-name mono truncate" :title="j.name">{{ j.name }}</span>
            <span class="gw-job-cell mono">{{ j.interval_seconds }}s</span>
            <span class="gw-job-cell mono">
              {{ j.last_run ? fmtJobTime(j.last_run) : t('admin.gateway.scheduler.notScheduled') }}
            </span>
            <span>
              <span class="badge" :class="j.overdue ? 'badge-down' : 'badge-up'">
                {{ j.overdue ? t('admin.gateway.scheduler.overdue') : t('admin.gateway.scheduler.normal') }}
              </span>
            </span>
          </div>
        </div>
      </section>

      <!-- ══ 交易时段 ══ -->
      <section class="card">
        <header class="card-head">
          <div>
            <h2 class="card-title"><CalendarClock :size="14" />{{ t('admin.gateway.session.title') }}</h2>
            <p class="card-sub">{{ t('admin.gateway.session.subtitle') }}</p>
          </div>
          <span class="badge" :class="sessionMode === 'full' ? 'badge-up' : 'badge-warn'">
            {{ t(`admin.gateway.session.mode.${sessionMode}`) }}
          </span>
        </header>

        <div v-if="sessionLoading && !sessionLoaded" class="gw-sess-pad">
          <BaseLoadingAnnounce />
        </div>

        <div v-else class="gw-sess-pad">
          <!-- 实时状态：判定由后端给出，页面只渲染 -->
          <p class="gw-sess-state">
            <span class="gw-dim">{{ t('admin.gateway.session.currentLabel') }}</span>
            <span class="gw-sess-strong">{{ session?.state?.reason || '--' }}</span>
            <span v-if="sessionNextChange" class="gw-dim mono">
              · {{ t('admin.gateway.session.nextChange', undefined, { time: sessionNextChange }) }}
            </span>
          </p>

          <p v-if="sessionErrors.length" role="status" aria-live="polite" class="gw-sess-warn">
            {{ t('admin.gateway.session.configWarning', undefined, { n: sessionErrors.length }) }}
            {{ sessionErrors.join('；') }}
          </p>
          <p v-if="sessionError" role="alert" class="gw-sess-bad">{{ sessionError }}</p>

          <!-- 开关 + 窗口外行为 -->
          <div class="gw-sess-row">
            <label class="gw-sess-check">
              <input
                v-model="draftEnabled"
                type="checkbox"
                :aria-label="t('admin.gateway.session.enableLabel')"
              />
              <span>{{ t('admin.gateway.session.enableLabel') }}</span>
            </label>

            <label class="gw-sess-mode">
              <span class="form-label">{{ t('admin.gateway.session.modeLabel') }}</span>
              <select
                v-model="draftMode"
                class="field"
                :aria-label="t('admin.gateway.session.modeLabel')"
                :disabled="!draftEnabled"
              >
                <option value="manage_only">{{ t('admin.gateway.session.modeOptions.manageOnly') }}</option>
                <option value="off">{{ t('admin.gateway.session.modeOptions.off') }}</option>
              </select>
            </label>
          </div>

          <!-- 时段列表 -->
          <div class="gw-sess-windows">
            <p v-if="!draftWindows.length" class="gw-dim">
              {{ draftEnabled ? t('admin.gateway.session.emptyEnabled') : t('admin.gateway.session.emptyDisabled') }}
            </p>

            <div v-for="(win, index) in draftWindows" :key="index" class="gw-sess-window">
              <div class="gw-sess-days" role="group" :aria-label="t('admin.gateway.session.daysLabel', undefined, { n: index + 1 })">
                <button
                  v-for="day in WEEKDAYS"
                  :key="day"
                  type="button"
                  class="gw-sess-day"
                  :class="{ 'is-on': win.days.includes(day) }"
                  :aria-pressed="win.days.includes(day) ? 'true' : 'false'"
                  @click="toggleDay(win, day)"
                >
                  {{ weekdayLabel(day) }}
                </button>
              </div>

              <label class="gw-sess-time">
                <span class="form-label">{{ t('admin.gateway.session.startLabel') }}</span>
                <input
                  v-model="win.start"
                  class="field num"
                  type="time"
                  autocomplete="off"
                  spellcheck="false"
                  :aria-label="t('admin.gateway.session.startLabel')"
                />
              </label>
              <label class="gw-sess-time">
                <span class="form-label">{{ t('admin.gateway.session.endLabel') }}</span>
                <input
                  v-model="win.end"
                  class="field num"
                  type="time"
                  autocomplete="off"
                  spellcheck="false"
                  :aria-label="t('admin.gateway.session.endLabel')"
                />
              </label>

              <button
                type="button"
                class="btn btn-quiet btn-sm"
                @click="removeWindow(index)"
              >
                <span>{{ t('admin.gateway.session.remove') }}</span>
              </button>
            </div>
          </div>

          <p class="gw-dim gw-sess-hint">{{ t('admin.gateway.session.crossMidnightHint') }}</p>

          <p class="gw-dim gw-sess-hint">
            {{ t('admin.gateway.session.coverage', undefined, {
              hours: sessionCoverage.hours_per_week ?? 0,
              saved: sessionCoverage.saved_brain_calls_per_day ?? 0,
            }) }}
          </p>

          <footer class="gw-sess-actions">
            <button type="button" class="btn btn-ghost btn-sm" @click="addWindow">
              <span>{{ t('admin.gateway.session.addWindow') }}</span>
            </button>
            <button
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="sessionSaving"
              @click="saveSession"
            >
              <Save :size="14" />
              <span>{{ sessionSaving ? t('admin.gateway.session.saving') : t('admin.gateway.session.save') }}</span>
            </button>
            <button
              type="button"
              class="btn btn-ghost btn-sm"
              :disabled="sessionSaving || (!draftEnabled && !draftWindows.length)"
              @click="resumeFullTime"
            >
              <span>{{ t('admin.gateway.session.resumeFullTime') }}</span>
            </button>
          </footer>

          <p class="gw-dim gw-sess-hint">{{ t('admin.gateway.session.restartNote') }}</p>
        </div>
      </section>

      <!-- ══ 投递流水 ══ -->
      <section class="card">
        <header class="card-head">
          <div>
            <h2 class="card-title"><Zap :size="14" />{{ t('admin.gateway.deliveries.title') }}</h2>
            <p class="card-sub">{{ t('admin.gateway.deliveries.records', undefined, { n: deliveries.length }) }}</p>
          </div>
          <button type="button" class="btn btn-ghost btn-sm" :disabled="loading" @click="load">
            <RefreshCw :size="14" :class="loading && 'animate-spin shrink-0'" />
            <span>{{ t('admin.gateway.deliveries.refresh') }}</span>
          </button>
        </header>

        <!-- 骨架屏：不经 DataTable 的 loading（其 colspan 依赖 columns，本表只用槽） -->
        <div v-if="showSkeleton" class="gw-skel">
          <BaseLoadingAnnounce />
          <div v-for="i in 7" :key="i" class="gw-skel-row">
            <span class="skeleton skeleton-text" :style="{ width: 24 + ((i * 29) % 46) + '%' }" />
          </div>
        </div>

        <DataTable
          v-else
          flat
          :rows="deliveries"
          :row-key="(d: any) => d.id"
          :empty-text="t('admin.gateway.deliveries.empty')"
          :label="t('admin.gateway.deliveries.title')"
          row-class="gw-tr"
        >
          <template #head>
            <tr class="gw-th">
              <th scope="col">{{ t('admin.gateway.deliveries.colId') }}</th>
              <th scope="col">{{ t('admin.gateway.deliveries.colEventType') }}</th>
              <th scope="col">{{ t('admin.gateway.deliveries.colChannel') }}</th>
              <th scope="col">{{ t('admin.gateway.deliveries.colStatus') }}</th>
              <th scope="col" class="gw-r">{{ t('admin.gateway.deliveries.colAttempts') }}</th>
              <th scope="col">{{ t('admin.gateway.deliveries.colTime') }}</th>
              <th scope="col">{{ t('admin.gateway.deliveries.colActions') }}</th>
            </tr>
          </template>

          <template #row="{ row: d }">
                <td class="mono gw-dim">#{{ d.id }}</td>
                <td class="gw-topic">{{ d.topic }}</td>
                <td class="mono gw-target truncate" :title="d.target">{{ d.target }}</td>
                <td>
                  <span class="badge" :class="statusTone(d.status)" :title="d.status">{{ statusLabel(d.status) }}</span>
                </td>
                <td class="gw-r mono gw-dim">{{ d.attempts ?? 0 }}</td>
                <td class="mono gw-dim">{{ d.updated_at ? fmtJobTime(d.updated_at) : '--' }}</td>
                <td>
                  <button type="button"
                    v-if="d.status === 'dead' || d.status === 'failed'"
                    class="btn btn-quiet btn-sm gw-replay"
                    @click="openReplay(d.id)"
                  >
                    <RotateCcw :size="13" />
                    <span>{{ t('admin.gateway.deliveries.replay') }}</span>
                  </button>
                  <span v-else class="gw-dim">--</span>
                </td>
          
          </template>
        </DataTable>
      </section>
    </template>

    <!-- ══ 重放确认对话框 ══ -->
    <BaseDialog
      :open="replayId !== null"
      :title="t('admin.gateway.deliveries.replayTitle', undefined, { id: replayId ?? '' })"
      :desc="t('admin.gateway.deliveries.replayDesc')"
      size="sm"
      initial-focus="input"
      @close="closeReplay"
    >
      <label class="field-stack">
        <span class="form-label">{{ t('admin.gateway.deliveries.replayExpected') }}</span>
        <code class="gw-phrase">{{ replayExpected }}</code>
        <input
          v-model="replayPhrase"
          class="field"
          type="text"
          autocomplete="off"
          spellcheck="false"
          :class="{ 'is-bad': !!replayPhrase && !replayMatched }"
          :aria-invalid="!!replayPhrase && !replayMatched ? 'true' : undefined"
          :placeholder="replayExpected"
          @keyup.enter="confirmReplay"
        />
      </label>
      <p v-if="replayPhrase && !replayMatched" class="gw-warn">
        {{ t('admin.gateway.msgs.replayPrompt', undefined, { id: replayId ?? '' }) }}
      </p>

      <template #footer>
        <button type="button" class="btn btn-ghost btn-sm" @click="closeReplay">{{ t('common.cancel') }}</button>
        <button type="button"
          class="btn btn-primary btn-sm"
          :disabled="!replayMatched || replaying"
          @click="confirmReplay"
        >
          <span>{{ t('admin.gateway.deliveries.replaySubmit') }}</span>
        </button>
      </template>
    </BaseDialog>
    </div>

    <div v-else id="gw-panel-workers" role="tabpanel" aria-labelledby="gw-tab-workers" tabindex="0" class="gw-panel">
      <AgentsPage embedded />
    </div>
  </div>
</template>

<style scoped>
.gw,
.gw-panel {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}


/* 刷新失败细条 */
.gw-stale {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  padding: 8px var(--ds-space-4);
  border-radius: var(--r-ctl);
  background-color: var(--warn-bg);
  color: var(--warn);
  font-size: var(--text-xs);
}
.gw-stale > span {
  min-width: 0;
  flex: 1;
}
.gw-stale .btn {
  color: var(--warn);
}

/* ══ 运行状态带 ══ */












/* ══ 调度作业清单 ══ */
.gw-jobs {
  display: flex;
  flex-direction: column;
}
.gw-job {
  display: grid;
  grid-template-columns: 6px minmax(0, 1fr) 64px 108px 84px;
  align-items: center;
  gap: var(--ds-space-3);
  min-height: var(--row-h);
  padding: 0 var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
}
@media (max-width: 640px) {
  .gw-job {
    grid-template-columns: 6px minmax(0, 1fr) auto;
    gap: var(--ds-space-2);
    padding: 0 var(--ds-space-3);
  }
  .gw-job-cell {
    display: none;
  }
}
.gw-job:last-child {
  border-bottom: 0;
}
.gw-job:not(.gw-job-head):hover {
  background-color: var(--ds-color-bg-hover);
}
.gw-job.is-overdue {
  background-color: var(--down-bg);
}
.gw-job.is-overdue:hover {
  background-color: var(--down-bg);
}
.gw-job-head {
  min-height: 30px;
  background-color: var(--ds-color-bg-surface-inset);
  font-size: var(--text-3xs);
  font-weight: 500;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ds-color-text-placeholder);
}
.gw-job-name {
  font-size: var(--text-xs);
  color: var(--ds-color-text-primary);
  font-weight: 500;
}
.gw-job-cell {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
  white-space: nowrap;
}

/* ══ 交易时段 ══ */
.gw-sess-pad {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-3);
  padding: var(--ds-space-4);
}
.gw-sess-state {
  display: flex;
  align-items: baseline;
  flex-wrap: wrap;
  gap: var(--ds-space-2);
  margin: 0;
  font-size: var(--text-xs);
}
.gw-sess-strong {
  color: var(--ds-color-text-primary);
  font-weight: 500;
}
.gw-sess-warn,
.gw-sess-bad {
  margin: 0;
  padding: 6px 10px;
  border-radius: var(--r-ctl);
  font-size: var(--text-xs);
}
.gw-sess-warn {
  background-color: var(--warn-bg);
  color: var(--warn);
}
.gw-sess-bad {
  background-color: var(--down-bg);
  color: var(--down);
}
.gw-sess-row {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: var(--ds-space-4);
}
.gw-sess-check {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-xs);
  color: var(--ds-color-text-secondary);
}
.gw-sess-check input {
  accent-color: var(--ds-color-accent);
}
.gw-sess-mode {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 220px;
}
.gw-sess-windows {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
}
.gw-sess-window {
  display: flex;
  align-items: flex-end;
  flex-wrap: wrap;
  gap: var(--ds-space-3);
  padding: var(--ds-space-2) 0;
  border-bottom: 1px solid var(--ds-color-border-default);
}
.gw-sess-days {
  display: flex;
  gap: 4px;
}
.gw-sess-day {
  min-width: 44px;
  padding: 4px 8px;
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface);
  color: var(--ds-color-text-placeholder);
  font-size: var(--text-3xs);
  cursor: pointer;
}
.gw-sess-day.is-on {
  border-color: var(--ds-color-accent);
  background-color: var(--accent-bg);
  color: var(--ds-color-accent);
}
.gw-sess-time {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 108px;
}
.gw-sess-hint {
  margin: 0;
  font-size: var(--text-3xs);
  line-height: 1.5;
}
.gw-sess-actions {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--ds-space-2);
}

/* ══ 投递表 ══
   DataTable 的 <table> 不带 .table 类，故表头/单元格样式在本页收敛；
   槽内容在父作用域编译，scoped 样式可直接命中。 */
.gw-skel {
  display: flex;
  flex-direction: column;
}
.gw-skel-row {
  display: flex;
  align-items: center;
  height: var(--row-h);
  padding: 0 var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
}

.gw-th th {
  height: 30px;
  padding: 0 var(--ds-space-3);
  background-color: var(--ds-color-bg-surface-inset);
  border-bottom: 1px solid var(--ds-color-border-default);
  text-align: left;
  font-size: var(--text-3xs);
  font-weight: 500;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ds-color-text-placeholder);
  white-space: nowrap;
}
.gw-th th.gw-r {
  text-align: right;
}
.gw-tr td {
  height: var(--row-h);
  padding: 0 var(--ds-space-3);
  border-bottom: 1px solid var(--ds-color-border-default);
  font-size: var(--text-xs);
  color: var(--ds-color-text-secondary);
  vertical-align: middle;
}
.gw-tr:hover td {
  background-color: var(--ds-color-bg-hover);
}
.gw-r {
  text-align: right;
}

.gw-dim {
  color: var(--ds-color-text-placeholder);
}
.gw-topic {
  font-weight: 500;
  color: var(--ds-color-text-primary);
}
.gw-target {
  max-width: 240px;
}
.gw-replay {
  color: var(--ds-color-brand);
}

/* ══ 重放对话框 ══ */

.gw-phrase {
  align-self: flex-start;
  padding:2px 8px;
  border-radius: var(--r-xs);
  background-color: var(--ds-color-bg-surface-1);
  font-family: var(--ds-font-mono);
  font-size: var(--text-3xs);
  color: var(--ds-color-text-primary);
}
.gw-warn {
  margin-top: var(--ds-space-3);
  font-size: var(--text-3xs);
  line-height: var(--leading-body);
  color: var(--warn);
}
</style>
