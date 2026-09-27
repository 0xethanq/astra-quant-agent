<script setup lang="ts">
/**
 * AuditPage.vue · 操作审计工位
 * ---------------------------------------------------------------------------
 * 骨架（推倒重来）：
 *   旧 = 一行简介 + 蓝色徽章 + 工具栏 + 一张 DataTable 卡（含紫色图标）
 *        + **手写 fixed 遮罩详情弹窗**（裸 JSON.stringify dump）
 *        + 色相类（emerald-400 / rose-400 / amber-400 / purple-400）
 *        + 无骨架、无错误态、无空态（仅 DataTable 的 empty-text）
 *   新 = 共享 PageHeader（治理徽章 + 刷新）
 *        → **审计统计带**（记录总数 / 成功 / 异常 / 最近留痕）
 *        → **审计流水日志面板**（时间 · 动作 · 状态徽章 · 操作者 + 详情），行点击穿透
 *        → **BaseDialog 详情**（结构化头部 + 原始 JSON），搜索 + 状态筛选
 *
 * 后端契约（逐字未改）：GET /api/v1/admin/audit?limit=200 → { records:[{timestamp,action,status,detail}] }
 *
 * ⚠️ 判定语义逐字保留：success/completed/accepted → 成功；failed/denied → 异常；其余 → 待定。
 * ⚠️ 检索口径逐字保留：对 `action` / `status` / `JSON.stringify(detail)` 三者合并后做大小写无关包含匹配。
 */
import { fmtDateTime } from '../../utils/format';
import { ref, computed, onMounted } from 'vue'
import { useI18n } from '../../composables/useI18n'
import { useRovingTabs } from '../../composables/useRovingTabs';
const { t } = useI18n()
import { useApi } from '../../composables/useApi'
import PageHeader from '../../components/admin/PageHeader.vue'
import BaseDialog from '../../components/base/BaseDialog.vue'
import BaseEmpty from '../../components/base/BaseEmpty.vue'
import { ScrollText, RefreshCw, Search, AlertTriangle, Loader2, CheckCircle2,
  Ban, HelpCircle, Activity, ShieldCheck, User, FileJson, Terminal } from 'lucide-vue-next'
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue';

const { api } = useApi()
const records = ref<any[]>([])
const loading = ref(true)
const loadError = ref('')
const search = ref('')
const statusFilter = ref<'all' | 'ok' | 'bad'>('all')
const detailRec = ref<any | null>(null)

const OK_STATUSES = ['success', 'completed', 'accepted']
const BAD_STATUSES = ['failed', 'denied']

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const res = await api('/api/v1/admin/audit?limit=200')
    records.value = res.records || []
  } catch (e: any) {
    loadError.value = e.message
  } finally {
    loading.value = false
  }
}

/** 检索口径与旧版逐字一致：action / status / JSON(detail) 三合一包含匹配 */
function matchesQuery(r: any): boolean {
  const q = search.value.trim().toLowerCase()
  if (!q) return true
  return [r.action, r.status, JSON.stringify(r.detail || '')].join(' ').toLowerCase().includes(q)
}

const filtered = computed(() =>
  records.value.filter((r) => {
    if (!matchesQuery(r)) return false
    if (statusFilter.value === 'ok') return OK_STATUSES.includes(r.status)
    if (statusFilter.value === 'bad') return BAD_STATUSES.includes(r.status)
    return true
  }),
)

/** 状态 → 徽章色调（判定集合与原 statusColor 完全一致） */
function statusTone(s: string): string {
  if (OK_STATUSES.includes(s)) return 'badge-up'
  if (BAD_STATUSES.includes(s)) return 'badge-down'
  return 'badge-warn'
}
function statusIcon(s: string) {
  if (OK_STATUSES.includes(s)) return CheckCircle2
  if (BAD_STATUSES.includes(s)) return Ban
  return HelpCircle
}
/** 状态文案：查表本地化，未登记的枚举**原样回退**（不吞数据）。
 *  批 27：此前直接把 `r.status` 印在徽章上，于是同一页 KPI 带写「成功 / 异常」、
 *  表格里却是 `success / failed`，中英混排。 */
function statusLabel(s: string): string {
  return t(`admin.audit.status.${s}`, s)
}
/** 操作者：原实现取 detail.actor || detail.username || 'system' */
function actorOf(r: any): string {
  return r?.detail?.actor || r?.detail?.username || 'system'
}

const okCount = computed(() => records.value.filter((r) => OK_STATUSES.includes(r.status)).length)
const badCount = computed(() => records.value.filter((r) => BAD_STATUSES.includes(r.status)).length)

const FILTERS = computed(() => [
  { key: 'all' as const, label: t('admin.audit.filterAll') },
  { key: 'ok' as const, label: t('admin.audit.filterSuccess') },
  { key: 'bad' as const, label: t('admin.audit.filterFailed') },
])

/* 批 66：状态筛选分段的漫游 tabindex 与方向键导航。 */
const { setRef: setFilterRef, onKeydown: onFilterKey, roving: filterRoving } = useRovingTabs(
  () => FILTERS.value.length,
  (i) => { statusFilter.value = FILTERS.value[i].key },
)

/** 审计统计带（4 项事实） */
const bandFacts = computed(() => [
  {
    icon: Activity,
    label: t('admin.audit.bandTotal'),
    value: String(records.value.length),
    foot: `${filtered.value.length} / 200`,
    tone: '',
  },
  {
    icon: ShieldCheck,
    label: t('admin.audit.bandSuccess'),
    value: String(okCount.value),
    foot: records.value.length ? `${Math.round((100 * okCount.value) / records.value.length)}%` : '--',
    tone: okCount.value ? 'is-up' : 'is-off',
  },
  {
    icon: AlertTriangle,
    label: t('admin.audit.bandFailed'),
    value: String(badCount.value),
    foot: '',
    tone: badCount.value ? 'is-warn' : 'is-off',
  },
  {
    icon: ScrollText,
    label: t('admin.audit.bandLatest'),
    value: records.value.length ? fmtDateTime(records.value[0]?.timestamp) : '--',
    foot: records.value[0]?.action || '',
    tone: '',
  },
])

onMounted(load)
</script>

<template>
  <div class="au">
    <PageHeader :title="t('nav.admin.audit')" :description="t('admin.audit.intro')">
      <template #actions>
        <RouterLink to="/admin/decisions?tab=logs" class="btn btn-ghost btn-sm text-xs inline-flex items-center gap-1.5">
          <Terminal :size="13" />
          <span>{{ t('admin.decisions.hubTabLogs') }}</span>
        </RouterLink>
        <span class="badge badge-accent mono">{{ t('admin.audit.badge') }}</span>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="loading" @click="load">
          <Loader2 v-if="loading && records.length" :size="14" class="animate-spin shrink-0" />
          <RefreshCw v-else :size="14" />
          <span>{{ t('admin.audit.refresh') }}</span>
        </button>
      </template>
    </PageHeader>

    <!-- 拉取失败（旧版无错误位：请求抛错时页面停在空白） -->
    <div v-if="loadError && !records.length" role="alert" class="state-block is-error">
      <span class="state-icon"><AlertTriangle :size="17" /></span>
      <p class="state-title">{{ t('common.loadFailed') }}</p>
      <p class="state-desc">{{ loadError }}</p>
      <button type="button" class="btn btn-ghost btn-sm mt-1" :disabled="loading" @click="load">
        <RefreshCw :size="14" />
        <span>{{ t('common.retry') }}</span>
      </button>
    </div>

    <template v-else>
      <!-- ══ 审计统计带 ══ -->
      <section class="card band">
        <template v-if="loading && !records.length">
          <BaseLoadingAnnounce />
          <div v-for="i in 4" :key="i" class="fact">
            <div class="skeleton skeleton-text" style="width: 48%" />
            <div class="skeleton skeleton-text skeleton-value" style="width: 60%" />
            <div class="skeleton skeleton-text" style="width: 34%" />
          </div>
        </template>
        <template v-else>
          <div v-for="f in bandFacts" :key="f.label" class="fact">
            <span class="fact-label"><component :is="f.icon" :size="12" />{{ f.label }}</span>
            <span class="fact-value" :class="f.tone">{{ f.value }}</span>
            <span class="fact-foot truncate" :title="f.foot">{{ f.foot }}</span>
          </div>
        </template>
      </section>

      <!-- ══ 审计流水 ══ -->
      <section class="card">
        <header class="card-head">
          <h2 class="card-title"><ScrollText :size="14" />{{ t('admin.audit.recordsTitle') }}</h2>

          <div class="au-tools">
            <div class="au-search focus-ring">
              <Search :size="13" />
              <input v-model="search" type="search" autocomplete="off" spellcheck="false" :aria-label="t('admin.audit.searchPlaceholder')" :placeholder="t('admin.audit.searchPlaceholder')" class="au-search-input" />
            </div>
            <div class="seg" role="tablist" :aria-label="t('admin.audit.filtersLabel')">
              <button
                v-for="(f, fi) in FILTERS"
                :key="f.key"
                :ref="setFilterRef(fi)"
                type="button"
                role="tab"
                :aria-selected="statusFilter === f.key"
                :tabindex="filterRoving(statusFilter === f.key)"
                :class="{ 'seg-on': statusFilter === f.key }"
                @click="statusFilter = f.key"
                @keydown="onFilterKey($event, fi)"
              >{{ f.label }}</button>
            </div>
            <span class="badge mono">{{ filtered.length }}</span>
          </div>
        </header>

        <div v-if="loading && !records.length" class="au-skel">
          <BaseLoadingAnnounce />
          <div v-for="i in 8" :key="i" class="skeleton skeleton-row" />
        </div>

        <BaseEmpty
          v-else-if="!filtered.length"
          :text="records.length ? t('admin.audit.noMatch') : t('admin.audit.empty')"
        />

        <div v-else class="log-panel is-flush au-rows">
          <button
            v-for="(r, i) in filtered"
            :key="i"
            type="button"
            class="au-row"
            @click="detailRec = r"
          >
            <span class="au-time mono num">{{ fmtDateTime(r.timestamp) }}</span>

            <span class="badge" :class="statusTone(r.status)" :title="r.status">
              <component :is="statusIcon(r.status)" :size="11" />
              {{ statusLabel(r.status) }}
            </span>

            <span class="au-action mono truncate" :title="r.action">{{ r.action }}</span>

            <span class="au-actor truncate" :title="actorOf(r)">
              <User :size="11" />
              <span>{{ actorOf(r) }}</span>
            </span>

            <span class="au-detail truncate" :title="JSON.stringify(r.detail || {})">
              {{ JSON.stringify(r.detail || {}) }}
            </span>
          </button>
        </div>

        <p class="au-hint">{{ t('admin.audit.rowHint') }}</p>
      </section>
    </template>

    <!-- ══ 详情穿透 ══ -->
    <BaseDialog
      :open="!!detailRec"
      :title="t('admin.audit.detailTitle')"
      size="lg"
      @close="detailRec = null"
    >
      <template #title>
        <span class="au-dlg-title">
          <span>{{ t('admin.audit.detailTitle') }}</span>
          <span class="au-dlg-action mono">{{ detailRec?.action }}</span>
        </span>
      </template>

      <template v-if="detailRec">
        <div class="au-dlg-meta">
          <div class="au-dlg-cell">
            <span class="label-caps">{{ t('admin.audit.colTimestamp') }}</span>
            <span class="mono num">{{ fmtDateTime(detailRec.timestamp) }}</span>
          </div>
          <div class="au-dlg-cell">
            <span class="label-caps">{{ t('admin.audit.colStatus') }}</span>
            <span class="badge" :class="statusTone(detailRec.status)" :title="detailRec.status">{{ statusLabel(detailRec.status) }}</span>
          </div>
          <div class="au-dlg-cell">
            <span class="label-caps">{{ t('admin.audit.actorLabel') }}</span>
            <span class="mono">{{ actorOf(detailRec) }}</span>
          </div>
        </div>

        <div class="au-dlg-json-head">
          <FileJson :size="12" />
          <span>{{ t('admin.audit.rawJson') }}</span>
        </div>
        <pre class="code-block au-json" tabindex="0">{{ JSON.stringify(detailRec, null, 2) }}</pre>
      </template>

      <template #footer>
        <button type="button" class="btn btn-primary btn-sm" @click="detailRec = null">
          {{ t('admin.audit.close') }}
        </button>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.au {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}

/* ══ 统计带 ══ */










/* ══ 工具条 ══ */
.au-tools {
  display: flex;
  align-items: center;
  gap: var(--ds-space-3);
  margin-left: auto;
  flex-wrap: wrap;
}
.au-search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-input);
  color: var(--ds-color-text-placeholder);
}
.au-search-input {
  width: 220px;
  padding: 6px 0;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--ds-color-text-primary);
  font-size: var(--text-3xs);
}
@media (max-width: 900px) {
  .au-search-input {
    width: 120px;
  }
}

/* ══ 流水 ══ */
.au-skel {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--ds-space-4);
}
.au-rows {
  max-height: 580px;
}
.au-row {
  display: grid;
  grid-template-columns: 140px auto minmax(0, 1.1fr) minmax(0, 0.8fr) minmax(0, 1.5fr);
  align-items: center;
  gap: var(--ds-space-3);
  width: 100%;
  padding:8px var(--ds-space-4);
  border: 0;
  border-bottom: 1px solid var(--ds-color-border-default);
  background: transparent;
  text-align: left;
  cursor: pointer;
  transition: background-color var(--dur-fast);
}
.au-row:hover {
  background-color: var(--ds-color-bg-hover);
}
.au-time {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
  white-space: nowrap;
}
.au-action {
  font-size: var(--text-3xs);
  font-weight: 600;
  color: var(--ds-color-brand);
  min-width: 0;
}
.au-actor {
  display: flex;
  align-items: center;
  gap:6px;
  font-size: var(--text-4xs);
  color: var(--ds-color-text-secondary);
  min-width: 0;
}
.au-actor > svg {
  flex-shrink: 0;
}
.au-detail {
  font-family: var(--ds-font-mono);
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
  min-width: 0;
}
.au-hint {
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}

@media (max-width: 1100px) {
  .au-row {
    grid-template-columns: 130px auto minmax(0, 1fr);
  }
  .au-actor,
  .au-detail {
    grid-column: 3;
  }
}

/* ══ 详情弹窗 ══ */
.au-dlg-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.au-dlg-action {
  font-size: var(--text-4xs);
  font-weight: 400;
  color: var(--ds-color-brand);
}
.au-dlg-meta {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  overflow: hidden;
  margin-bottom: var(--ds-space-4);
}
@media (max-width: 640px) {
  .au-dlg-meta {
    grid-template-columns: 1fr;
  }
}
.au-dlg-cell {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
  padding: 10px var(--ds-space-3);
  border-left: 1px solid var(--ds-color-border-default);
}
.au-dlg-cell:first-child {
  border-left: 0;
}
@media (max-width: 640px) {
  .au-dlg-cell {
    border-left: 0;
    border-top: 1px solid var(--ds-color-border-default);
  }
  .au-dlg-cell:first-child {
    border-top: 0;
  }
}
.au-dlg-cell .mono {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-primary);
  overflow-wrap: anywhere;
}
.au-dlg-json-head {
  display: flex;
  align-items: center;
  gap:6px;
  margin-bottom: 6px;
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.au-json {
  max-height: 380px;
  margin: 0;
  overflow: auto;
  font-size: var(--text-4xs);
  line-height: var(--leading-body);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  user-select: text;
}
</style>
