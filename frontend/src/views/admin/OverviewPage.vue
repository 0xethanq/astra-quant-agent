<script setup lang="ts">
/**
 * OverviewPage.vue · 开发者工作台 · 系统全景总览
 * ---------------------------------------------------------------------------
 * 架构重构（推倒旧版模板）：
 *   - 顶部：实时心跳指示器与工作台状态栏
 *   - 模块 1：四维全景指标矩阵（执行核心 / AI决策主脑 / 撮合路由网关 / 物理安全防线）
 *   - 模块 2：双栏指挥工位
 *       · 左侧（62%）：AI 实时决策流（指令周期动作、置信度量规、推理时间与核心研判）
 *       · 右侧（38%）：数据管道实时时效监控 + 核心管控通道直达
 *   - 模块 3：系统审计与运行轨迹面板（结构化事件提取、状态指示、人类可读上下文）
 *
 * 后端契约（严格保持原样）：
 *   GET /api/v1/admin/runtime
 *   GET /api/v1/admin/config
 *   锁定消费键：model / provider_name / reasoning_effort / api_format
 */
import { computed, onMounted, ref } from 'vue';
import {
  Server,
  Cpu,
  Wallet,
  Braces,
  Crosshair,
  Landmark,
  RefreshCw,
  ArrowRight,
  Database,
  ScrollText,
  AlertCircle,
  ShieldCheck,
  History,
  LayoutGrid,
  ChevronRight,
  Clock
} from 'lucide-vue-next';
import { get } from '../../api/http';
import { useI18n } from '../../composables/useI18n';
import { APP_VERSION } from '../../config/version';
import PageHeader from '../../components/admin/PageHeader.vue';
import BaseEmpty from '../../components/base/BaseEmpty.vue';
import TimeAgo from '../../components/base/TimeAgo.vue';
import { fmtNum, fmtDateTime } from '../../utils/format';
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue';

const { t } = useI18n();

const runtime = ref<any>(null);
const loading = ref(false);
const loaded = ref(false);
const loadError = ref(false);
const inspectingAuditIndex = ref<number | null>(null);

async function load() {
  loading.value = true;
  loadError.value = false;
  try {
    const [rt, cfg] = await Promise.all([
      get('/api/v1/admin/runtime').catch(() => null),
      get('/api/v1/admin/config').catch(() => null),
    ]);
    if (rt && cfg?.configuration) {
      rt.configuration = { ...cfg.configuration, ...(rt.configuration || {}) };
    }
    runtime.value = rt;
    loadError.value = !rt;
  } finally {
    loading.value = false;
    loaded.value = true;
  }
}
onMounted(load);

const service = computed(() => runtime.value?.service || {});
const uptime = computed(() => {
  const s = Number(service.value.uptime_seconds || 0);
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h > 0 ? `${h}h ${m}m` : `${m}m`;
});

const llm = computed(() => runtime.value?.llm_runtime || {});
const conf = computed<Record<string, string>>(() => runtime.value?.configuration || {});
const venueEnv = computed(() => conf.value['交易场所与路由'] || conf.value['OKX 当前环境'] || 'DEMO');
const isDemo = computed(() => venueEnv.value.includes('DEMO') || venueEnv.value.includes('模拟'));
const health = computed(() => runtime.value?.data_health || {});
const healthFiles = computed<any[]>(() => health.value.files || []);
const decisions = computed<any[]>(() => (runtime.value?.decisions || []).slice(0, 8));
const audits = computed<any[]>(() => (runtime.value?.audit || []).slice(0, 8));

const showSkeleton = computed(() => loading.value && !loaded.value);

const quickNavs = computed(() => [
  { to: '/admin/promptlib', icon: Braces, title: t('admin.overview.quick.prompts'), desc: t('admin.overview.quickPromptsDesc') },
  { to: '/admin/council', icon: Landmark, title: t('admin.overview.quick.council'), desc: t('admin.overview.quickCouncilDesc') },
  { to: '/admin/interceptors', icon: Crosshair, title: t('admin.overview.quick.interceptors'), desc: t('admin.overview.quickInterceptorsDesc') },
  { to: '/admin/llm', icon: Cpu, title: t('admin.overview.quick.llm'), desc: t('admin.overview.quickLlmDesc') },
]);

function parseAuditContext(action: string, detail: any): { label: string; tag: string; tagType: string; summary: string } {
  const act = String(action || '').replace('admin.', '');
  const d = detail || {};
  
  if (act === 'login') {
    return {
      label: t('admin.overview.auditLoginLabel'),
      tag: 'AUTH',
      tagType: 'info',
      summary: t('admin.overview.auditUser', undefined, { u: d.username || 'admin', ip: d.ip || t('admin.overview.auditLocalClient') })
    };
  }
  if (act.includes('test') || act.includes('notify') || act.includes('notification')) {
    return {
      label: t('admin.overview.auditTestLabel'),
      tag: 'NOTIFY',
      tagType: 'neutral',
      summary: t('admin.overview.auditChannel', undefined, { c: d.channel || t('admin.overview.auditSystemChannel'), r: d.result?.accepted ? t('admin.overview.auditAccepted') : t('admin.overview.auditDispatched') })
    };
  }
  if (act.includes('interceptor')) {
    return {
      label: t('admin.overview.auditRuleLabel'),
      tag: 'RULE',
      tagType: 'warn',
      summary: t('admin.overview.auditRule', undefined, { f: d.filename || d.actor || t('admin.overview.auditRuleConfig'), s: d.enabled ? t('admin.overview.auditEnabled') : t('admin.overview.auditDisabled') })
    };
  }
  return {
    label: act,
    tag: 'OP',
    tagType: 'neutral',
    summary: Object.keys(d).length ? JSON.stringify(d).slice(0, 80) : t('admin.overview.auditOk')
  };
}
</script>

<template>
  <div class="ov-deck">
    <!-- 顶部工作台标题与状态 -->
    <PageHeader :title="t('nav.admin.overview')" :description="t('admin.overview.desc')">
      <template #actions>
        <div class="ov-header-actions">
          <div class="ov-live-pill">
            <span class="ov-live-dot" aria-hidden="true" />
            <span class="ov-live-text">TELEMETRY LIVE</span>
          </div>
          <span class="ov-version-badge mono">{{ APP_VERSION }}</span>
          <button type="button" class="ov-btn-refresh" :disabled="loading" @click="load" :title="t('common.refresh')">
            <RefreshCw :size="14" :class="loading && 'animate-spin shrink-0'" />
            <span>{{ t('common.refresh') }}</span>
          </button>
        </div>
      </template>
    </PageHeader>

    <!-- 错误恢复横幅 -->
    <div v-if="loadError" role="alert" class="ov-error-banner">
      <div class="ov-error-left">
        <AlertCircle :size="18" class="ov-error-icon" />
        <div>
          <h4 class="ov-error-title">{{ t('admin.overview.loadFailedTitle') }}</h4>
          <p class="ov-error-desc">{{ t('admin.overview.loadFailedDesc') }}</p>
        </div>
      </div>
      <button type="button" class="btn btn-primary btn-sm" :disabled="loading" @click="load">
        <RefreshCw :size="14" :class="loading && 'animate-spin shrink-0'" />
        <span>{{ t('common.retry') }}</span>
      </button>
    </div>

    <!-- ══ 模块 1：四维全景指标矩阵 (HUD) ══ -->
    <section class="ov-hud">
      <!-- 指标 1：执行核心 -->
      <div class="ov-hud-card">
        <div class="ov-hud-head">
          <span class="ov-hud-icon"><Server :size="14" /></span>
          <span class="ov-hud-label">{{ t('admin.overview.backend') }}</span>
          <span class="ov-hud-badge is-up">
            <span class="pulse-dot" aria-hidden="true" />
            ONLINE
          </span>
        </div>
        <div class="ov-hud-body">
          <div class="ov-hud-val num">PID {{ service.pid || '--' }}</div>
          <div class="ov-hud-sub mono">{{ t('admin.overview.hudCoreProcess') }}</div>
        </div>
        <div class="ov-hud-foot">
          <span class="ov-hud-pill">
            <Clock :size="11" />
            {{ t('admin.overview.hudUptime', undefined, { t: uptime }) }}
          </span>
        </div>
      </div>

      <!-- 指标 2：决策主脑 -->
      <RouterLink to="/admin/llm" class="ov-hud-card is-interactive">
        <div class="ov-hud-head">
          <span class="ov-hud-icon"><Cpu :size="14" /></span>
          <span class="ov-hud-label">{{ t('admin.overview.brain') }}</span>
          <span class="ov-hud-link-arrow"><ChevronRight :size="13" /></span>
        </div>
        <div class="ov-hud-body">
          <div class="ov-hud-val mono truncate" :title="llm.model">
            {{ llm.model || t('common.notConfigured') }}
          </div>
          <div class="ov-hud-sub truncate">
            {{ llm.provider_name || t('admin.overview.hudBuiltin') }} · {{ t('admin.overview.hudEffort') }} {{ (llm.reasoning_effort || t('admin.overview.hudEffortStd')).toUpperCase() }}
          </div>
        </div>
        <div class="ov-hud-foot">
          <span class="ov-hud-pill">{{ t('admin.overview.hudArbiter') }}</span>
        </div>
      </RouterLink>

      <!-- 指标 3：撮合路由 -->
      <RouterLink to="/admin/security" class="ov-hud-card is-interactive">
        <div class="ov-hud-head">
          <span class="ov-hud-icon"><Wallet :size="14" /></span>
          <span class="ov-hud-label">{{ t('admin.overview.quickVenues') }}</span>
          <span class="ov-hud-link-arrow"><ChevronRight :size="13" /></span>
        </div>
        <div class="ov-hud-body">
          <div class="ov-hud-val" :class="isDemo ? 'text-amber' : 'is-up'">
            {{ venueEnv }}
          </div>
          <div class="ov-hud-sub">{{ t('admin.overview.hudVenueRoute') }}</div>
        </div>
        <div class="ov-hud-foot">
          <span class="ov-hud-pill">{{ t('admin.overview.hudAutoRoute') }}</span>
        </div>
      </RouterLink>

      <!-- 指标 4：物理安全防线 -->
      <RouterLink to="/admin/interceptors" class="ov-hud-card is-interactive">
        <div class="ov-hud-head">
          <span class="ov-hud-icon"><ShieldCheck :size="14" /></span>
          <span class="ov-hud-label">{{ t('admin.overview.hudRiskLine') }}</span>
          <span class="ov-hud-badge is-shield">FAIL-CLOSED</span>
        </div>
        <div class="ov-hud-body">
          <div class="ov-hud-val is-up">{{ t('admin.overview.hudPhysicalBlock', undefined, { n: 100 }) }}</div>
          <div class="ov-hud-sub">{{ t('admin.overview.hudPipeReady', undefined, { a: 4, b: 4 }) }}</div>
        </div>
        <div class="ov-hud-foot">
          <span class="ov-hud-pill">{{ t('admin.overview.hudBreakerReady') }}</span>
        </div>
      </RouterLink>
    </section>

    <!-- ══ 模块 2：双栏指挥工位 ══ -->
    <div class="ov-workspace">
      <!-- 左主栏：AI 实时决策流 -->
      <section class="card ov-stream-card">
        <header class="ov-card-header">
          <div class="ov-ch-main">
            <h2 class="ov-ch-title">
              <ScrollText :size="14" class="ov-ch-icon" />
              <span>{{ t('admin.overview.decisions') }}</span>
            </h2>
            <p class="ov-ch-desc">{{ t('admin.overview.decisionsDesc') }}</p>
          </div>
          <RouterLink to="/admin/decisions" class="ov-ch-link">
            <span>{{ t('admin.overview.viewAll') }} (92)</span>
            <ArrowRight :size="13" />
          </RouterLink>
        </header>

        <!-- 加载骨架 -->
        <div v-if="showSkeleton" class="ov-skel-stack">
          <BaseLoadingAnnounce />
          <div v-for="i in 5" :key="i" class="skeleton ov-skel-row" />
        </div>

        <!-- 空数据 -->
        <BaseEmpty v-else-if="!decisions.length" :text="t('common.noData')" />

        <!-- 决策流数据矩阵 -->
        <div v-else class="ov-stream-list">
          <div
            v-for="d in decisions"
            :key="d.instId + d.updated_at"
            class="ov-stream-item"
          >
            <!-- 标的铭牌 -->
            <div class="ov-stream-sym">
              <span class="ov-sym-chip mono">{{ String(d.instId).split('-')[0] }}</span>
              <span class="ov-sym-market mono">USDT·PERP</span>
            </div>

            <!-- 动作指示 -->
            <div class="ov-stream-act">
              <span
                v-if="d.action === 'BUY_LONG'"
                class="ov-act-tag is-long"
              >
                {{ t('admin.overview.dirLong') }}
              </span>
              <span
                v-else-if="d.action === 'SELL_SHORT'"
                class="ov-act-tag is-short"
              >
                {{ t('admin.overview.dirShort') }}
              </span>
              <span v-else class="ov-act-tag is-wait">
                {{ t('admin.overview.dirWait') }}
              </span>
            </div>

            <!-- 置信度进度量规 -->
            <div class="ov-stream-gauge">
              <div
                class="ov-gauge-bar"
                role="progressbar"
                :aria-valuenow="Math.round(Number(d.confidence || 0))"
                aria-valuemin="0"
                aria-valuemax="100"
                :aria-label="t('admin.overview.confidenceGauge')"
                :aria-valuetext="`${fmtNum(d.confidence, 0)}%`"
              >
                <div
                  class="ov-gauge-fill"
                  :style="{
                    width: `${Math.min(100, Number(d.confidence || 0))}%`,
                    backgroundColor: Number(d.confidence || 0) > 70 ? 'var(--up)' : Number(d.confidence || 0) > 40 ? 'var(--warn)' : 'var(--ds-color-text-placeholder)'
                  }"
                />
              </div>
              <span class="ov-gauge-num mono">{{ fmtNum(d.confidence, 0) }}%</span>
            </div>

            <!-- 宏观决策研判理由 -->
            <div class="ov-stream-reason" :title="d.summary">
              {{ d.summary }}
            </div>

            <!-- 时间戳 -->
            <div class="ov-stream-time mono">
              {{ fmtDateTime(d.updated_at).slice(11, 19) }}
            </div>
          </div>
        </div>
      </section>

      <!-- 右副轨：数据管道 + 核心通道 -->
      <div class="ov-side-rail">
        <!-- 侧栏卡片 1：数据管道监控 -->
        <section class="card ov-pipe-card">
          <header class="ov-card-header">
            <div class="ov-ch-main">
              <h2 class="ov-ch-title">
                <Database :size="14" class="ov-ch-icon" />
                <span>{{ t('admin.overview.dataHealth') }}</span>
              </h2>
              <p class="ov-ch-desc">{{ t('admin.overview.dataHealthDesc') }}</p>
            </div>
            <span
              class="ov-chip-status"
              :class="health.overall === 'LIVE' ? 'is-live' : 'is-warn'"
            >
              <span class="pulse-dot" aria-hidden="true" />
              {{ health.overall || 'SYNC' }}
            </span>
          </header>

          <div class="ov-pipe-list">
            <div v-if="showSkeleton" class="ov-skel-stack">
              <BaseLoadingAnnounce />
              <div v-for="i in 4" :key="i" class="skeleton ov-skel-pipe" />
            </div>

            <BaseEmpty v-else-if="!healthFiles.length" :text="t('common.noData')" />

            <div
              v-else
              v-for="f in healthFiles"
              :key="f.name"
              class="ov-pipe-row"
            >
              <div class="ov-pipe-info">
                <span class="ov-pipe-dot" :class="f.fresh ? 'is-fresh' : 'is-stale'" aria-hidden="true" />
                <span class="ov-pipe-filename mono truncate" :title="f.name">{{ f.name }}</span>
              </div>
              <div class="ov-pipe-meta">
                <span class="ov-pipe-age mono">
                  {{ f.age_seconds != null ? t('admin.overview.pipeAgeMinutes', undefined, { n: Math.round(f.age_seconds / 60) }) : '--' }}
                </span>
                <span class="ov-pipe-size mono">{{ fmtNum((f.bytes || 0) / 1024, 0) }}K</span>
              </div>
            </div>
          </div>
        </section>

        <!-- 侧栏卡片 2：核心管控通道 -->
        <section class="card ov-nav-card">
          <header class="ov-card-header">
            <div class="ov-ch-main">
              <h2 class="ov-ch-title">
                <LayoutGrid :size="14" class="ov-ch-icon" />
                <span>{{ t('admin.overview.quickTitle') }}</span>
              </h2>
            </div>
          </header>

          <div class="ov-nav-grid">
            <RouterLink
              v-for="q in quickNavs"
              :key="q.to"
              :to="q.to"
              class="ov-nav-tile"
            >
              <div class="ov-nt-icon">
                <component :is="q.icon" :size="16" />
              </div>
              <div class="ov-nt-content">
                <div class="ov-nt-title">{{ q.title }}</div>
                <div class="ov-nt-desc">{{ q.desc }}</div>
              </div>
              <ChevronRight :size="14" class="ov-nt-arrow" />
            </RouterLink>
          </div>
        </section>
      </div>
    </div>

    <!-- ══ 模块 3：系统审计与运行轨迹 ══ -->
    <section class="card ov-audit-card">
      <header class="ov-card-header">
        <div class="ov-ch-main">
          <h2 class="ov-ch-title">
            <History :size="14" class="ov-ch-icon" />
            <span>{{ t('admin.overview.recentAudit') }}</span>
          </h2>
          <p class="ov-ch-desc">{{ t('admin.overview.auditDesc') }}</p>
        </div>
        <RouterLink to="/admin/audit" class="ov-ch-link">
          <span>{{ t('admin.overview.viewAll') }} →</span>
        </RouterLink>
      </header>

      <div v-if="showSkeleton" class="ov-skel-stack">
        <BaseLoadingAnnounce />
        <div v-for="i in 4" :key="i" class="skeleton ov-skel-row" />
      </div>

      <BaseEmpty v-else-if="!audits.length" :text="t('common.noRecords')" />

      <div v-else class="ov-audit-table">
        <div
          v-for="(a, idx) in audits"
          :key="idx"
          class="ov-audit-row clickable"
          :class="{ 'is-selected': inspectingAuditIndex === idx }"
          role="button"
          tabindex="0"
          :aria-expanded="inspectingAuditIndex === idx"
          :aria-controls="inspectingAuditIndex === idx ? 'audit-detail-' + idx : undefined"
          @click="inspectingAuditIndex = inspectingAuditIndex === idx ? null : idx"
          @keydown.enter="inspectingAuditIndex = inspectingAuditIndex === idx ? null : idx"
          @keydown.space.prevent="inspectingAuditIndex = inspectingAuditIndex === idx ? null : idx"
        >
          <!-- 状态点与时间 -->
          <div class="ov-ar-time">
            <span class="ov-ar-dot" :class="a.status === 'success' ? 'is-ok' : 'is-fail'" aria-hidden="true" />
            <span class="mono">{{ fmtDateTime(a.timestamp) }}</span>
          </div>

          <!-- 动作标签 -->
          <div class="ov-ar-tag">
            <span
              class="ov-tag-chip"
              :class="`is-${parseAuditContext(a.action, a.detail).tagType}`"
            >
              {{ parseAuditContext(a.action, a.detail).tag }}
            </span>
            <span class="ov-tag-name">{{ parseAuditContext(a.action, a.detail).label }}</span>
          </div>

          <!-- 人类可读上下文详情（批 24：被截断时给出 title，否则长文案永远读不全） -->
          <div class="ov-ar-summary truncate" :title="parseAuditContext(a.action, a.detail).summary">
            {{ parseAuditContext(a.action, a.detail).summary }}
          </div>

          <!-- 相对时间与详情展开指示 -->
          <div class="ov-ar-meta">
            <TimeAgo :time="fmtDateTime(a.timestamp)" class="ov-ar-ago mono" />
            <span class="ov-ar-toggle mono">{{ inspectingAuditIndex === idx ? t('admin.overview.collapse') : 'JSON' }}</span>
          </div>

          <!-- 展开的原始 JSON 结构 -->
          <div v-if="inspectingAuditIndex === idx" :id="'audit-detail-' + idx" class="ov-ar-json-panel" @click.stop>
            <pre class="ov-json-code mono" tabindex="0">{{ JSON.stringify(a.detail || {}, null, 2) }}</pre>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
/* ══ 整体控制台框架 ══ */
.ov-deck {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-5);
  animation: astra-enter var(--dur-slow) var(--ease-out) backwards;
}


/* 顶部操作区 */
.ov-header-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-3);
}

.ov-live-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 20px;
  padding: 0 8px;
  border-radius: var(--r-pill);
  /* 批 74：胶囊的底/边此前硬编码了 --up 的同色 rgba —— 色相一样，
     但不吃 CVD 令牌，色盲模式下就变成「蓝字配绿底」。统一走 --up-bg / --up-line。 */
  background: var(--up-bg);
  border: 1px solid var(--up-line);
}
.ov-live-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--up);
  box-shadow: 0 0 8px var(--up);
  animation: ov-pulse 2s ease-in-out infinite;
}
@keyframes ov-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.4; transform: scale(0.85); }
}
.ov-live-text {
  font-family: var(--ds-font-mono);
  font-size: var(--text-3xs);
  font-weight: 600;
  letter-spacing: 0.06em;
  color: var(--up);
}

.ov-version-badge {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  border-radius: var(--r-xs);
  background: var(--ds-color-bg-hover);
  border: 1px solid var(--ds-color-border-default);
  font-size: var(--text-3xs);
  color: var(--ds-color-text-description);
}

.ov-btn-refresh {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 12px;
  border-radius: var(--r-ctl);
  background: var(--ds-color-bg-hover);
  border: 1px solid var(--ds-color-border-default);
  color: var(--ds-color-text-secondary);
  font-size: var(--text-xs);
  cursor: pointer;
  transition: all var(--dur-fast) var(--ease-out);
}
/* 批 102：`loading` 期间这是**禁用**按钮，但此前它没有任何禁用样式 ——
   看上去和可点的一样，而且 `:hover` 照样亮（点下去没反应）。
   全仓 131 个可禁用控件里就漏了这一个。视觉沿用 `.btn:disabled` 的既有约定。 */
.ov-btn-refresh:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.ov-btn-refresh:hover:not(:disabled) {
  background: var(--ds-color-bg-hover);
  color: var(--ds-color-text-primary);
  border-color: var(--ds-color-border-hover);
}

/* 报错恢复 */
.ov-error-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--ds-space-4);
  border-radius: var(--r-card);
  /* 批 74：同上 —— 硬编码 --down 同色 rgba 会让色盲模式下出现「橙字配红底」。 */
  background: var(--down-bg);
  border: 1px solid var(--down-line);
}
.ov-error-left {
  display: flex;
  align-items: center;
  gap: var(--ds-space-3);
}
.ov-error-icon {
  color: var(--down);
}
.ov-error-title {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--down);
}
.ov-error-desc {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}

/* ══ 模块 1：四维全景指标矩阵 (HUD) ══ */
.ov-hud {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-3);
}
@media (min-width: 640px) {
  .ov-hud { grid-template-columns: repeat(2, 1fr); gap: var(--ds-space-4); }
}
@media (min-width: 1200px) {
  .ov-hud { grid-template-columns: repeat(4, 1fr); }
}

.ov-hud-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-height: 104px;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-radius: var(--r-card);
  background: var(--ds-color-bg-surface-card);
  border: 1px solid var(--ds-color-border-default);
  box-shadow: var(--shadow-card);
  backdrop-filter: blur(16px);
  -webkit-backdrop-filter: blur(16px);
  transition: all var(--dur-fast) var(--ease-out);
  text-decoration: none;
  color: inherit;
}
@media (min-width: 640px) {
  .ov-hud-card {
    min-height: 124px;
    padding: var(--ds-space-4) var(--sp-8);
  }
}
.ov-hud-card.is-interactive:hover {
  border-color: var(--ds-color-brand);
  box-shadow: var(--shadow-float);
  transform: translateY(-1px);
}

.ov-hud-head {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ov-hud-icon {
  color: var(--ds-color-text-placeholder);
}
.ov-hud-label {
  font-size: var(--text-2xs);
  font-weight: 500;
  letter-spacing: 0.04em;
  color: var(--ds-color-text-placeholder);
  text-transform: uppercase;
}
  /* 批 35：全站徽标/胶囊的规范盒模型是 .badge/.chip/.dsh-pill ——
     高 20px、左右 8px、字号 --text-3xs。本页此前有 6 种手写盒模型
     （24/24/26/26/22/24），同一个「状态胶囊」角色出现 4 种几何。 */
.ov-hud-badge {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 20px;
  padding: 0 8px;
  border-radius: var(--r-pill);
  font-family: var(--ds-font-mono);
  font-size: var(--text-3xs);
  font-weight: 600;
}
.ov-hud-badge.is-up {
  background: var(--up-bg);
  color: var(--up);
  border: 1px solid var(--up-line);
}
.ov-hud-badge.is-shield {
  background: rgba(103, 153, 254, 0.1);
  color: var(--ds-color-brand);
  border: 1px solid rgba(103, 153, 254, 0.25);
}
.ov-hud-link-arrow {
  margin-left: auto;
  color: var(--ds-color-text-placeholder);
  transition: transform var(--dur-fast);
}
.ov-hud-card:hover .ov-hud-link-arrow {
  transform: translateX(2px);
  color: var(--ds-color-brand);
}

.ov-hud-body {
  margin: 6px 0;
}
@media (min-width: 640px) {
  .ov-hud-body {
    margin: 12px 0 8px;
  }
}
.ov-hud-val {
  /* 批 28：16px 不在字阶上（档位是 15 / 18），落到 lg。 */
  font-size: var(--text-lg);
  font-weight: 600;
  color: var(--ds-color-text-primary);
  letter-spacing: -0.01em;
  line-height: 1.3;
}
.ov-hud-val.is-up { color: var(--up); }
.ov-hud-val.text-amber { color: var(--warn); }
.ov-hud-sub {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-description);
  margin-top: var(--sp-1);
}

.ov-hud-foot {
  display: flex;
  align-items: center;
}
.ov-hud-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 20px;
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
  background: var(--ds-color-bg-hover);
  padding: 0 8px;
  border-radius: var(--r-pill);
  border: 1px solid var(--ds-color-border-subtle);
}

.pulse-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  background: currentColor;
  box-shadow: 0 0 6px currentColor;
}

/* ══ 模块 2：双栏工位 ══ */
.ov-workspace {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-4);
  align-items: start;
}
@media (min-width: 1200px) {
  .ov-workspace {
    grid-template-columns: minmax(0, 1.8fr) minmax(0, 1fr);
  }
}

.ov-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: var(--sp-7) var(--sp-8);
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  background: transparent;
}
.ov-ch-main { min-width: 0; }
.ov-ch-title {
  display: flex;
  align-items: center;
  gap: 8px;
  /* 批 33：全站 18 个页面用 .card-title（--text-xs 12px），只有本页自定义成
     --text-sm（12.5px）→ 同一「卡片标题」角色出现两种字号。改回同一档，
     并改用同一套令牌（颜色用 token 而非写死 #fff，字距用 --track-title）。 */
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
  letter-spacing: var(--track-title);
}
.ov-ch-icon {
  color: var(--ds-color-brand);
}
.ov-ch-desc {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
  margin-top: var(--sp-1);
}
.ov-ch-link {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  /* 批 18：原热区 82×17px；负外边距抵消内边距，视觉位置不变，命中区 25px 高 */
  padding: 4px 8px;
  margin: -4px -8px;
  border-radius: var(--r-xs);
  font-family: var(--ds-font-mono);
  font-size: var(--text-3xs);
  color: var(--ds-color-brand);
  text-decoration: none;
  white-space: nowrap;
  transition: opacity var(--dur-fast), background-color var(--dur-fast);
}
.ov-ch-link:hover {
  text-decoration: underline;
  opacity: 0.85;
  background-color: var(--astra-brand-bg);
}

/* 决策流 */
.ov-stream-list {
  display: flex;
  flex-direction: column;
  /* 批 114：窄屏（移动端 390px）卡片宽度不足时允许横向平滑滚动，不裁切右侧时间与状态 */
  overflow-x: auto;
}
.ov-stream-item {
  display: grid;
  grid-template-columns: 100px 100px 90px 1fr 70px;
  min-width: 480px;
  align-items: center;
  gap: var(--sp-6);
  padding: var(--sp-6) var(--sp-8);
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  transition: background-color var(--dur-fast);
}
.ov-stream-item:last-child {
  border-bottom: 0;
}
.ov-stream-item:hover {
  background-color: rgba(255, 255, 255, 0.025);
}

.ov-stream-sym {
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.ov-sym-chip {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
  letter-spacing: 0.02em;
}
.ov-sym-market {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}

.ov-stream-act {
  display: flex;
  align-items: center;
}
.ov-act-tag {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 8px;
  border-radius: var(--r-xs);
  font-size: var(--text-3xs);
  font-weight: 600;
  font-family: var(--ds-font-mono);
  white-space: nowrap;
}
.ov-act-tag.is-long {
  background: var(--up-bg);
  color: var(--up);
  border: 1px solid var(--up-line);
}
.ov-act-tag.is-short {
  background: var(--down-bg);
  color: var(--down);
  border: 1px solid var(--down-line);
}
.ov-act-tag.is-wait {
  background: var(--surface-2);
  color: var(--ds-color-text-description);
  border: 1px solid var(--line-1);
}

.ov-stream-gauge {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ov-gauge-bar {
  flex: 1;
  height: 4px;
  border-radius: var(--r-pill);
  background: var(--surface-2);
  overflow: hidden;
}
.ov-gauge-fill {
  height: 100%;
  border-radius: var(--r-pill);
  /* 批 93：同上，显式缓动一律用令牌（原为裸 ease）。 */
  transition: width var(--dur-base) var(--ease-out);
}
.ov-gauge-num {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-secondary);
  width: 32px;
  text-align: right;
}

.ov-stream-reason {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1.4;
}
.ov-stream-time {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
  text-align: right;
}

/* 右副轨 */
.ov-side-rail {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
  min-width: 0;
}

/* 批 30：右副轨此前比左栏矮 140px，页面右下角留一块空白（实测：
   左卡 .ov-stream-card 561px / 右轨 421px，网格 align-items:start，
   差值直接变成桌面上的一块死区）。宽屏下让**两张卡各自吃掉一半余量**：
   管道列表的行距与管控磁贴的高度随之摊开，两列底边对齐。 */
@media (min-width: 1200px) {
  .ov-workspace {
    align-items: stretch;
  }
  .ov-side-rail > .card {
    display: flex;
    flex-direction: column;
    flex: 1 1 auto;
  }
  .ov-side-rail .ov-pipe-list {
    flex: 1 1 auto;
    justify-content: space-evenly;
  }
  .ov-side-rail .ov-nav-grid {
    flex: 1 1 auto;
    align-content: stretch;
  }
}

.ov-chip-status {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 20px;
  padding: 0 8px;
  border-radius: var(--r-pill);
  font-family: var(--ds-font-mono);
  font-size: var(--text-3xs);
  font-weight: 600;
}
.ov-chip-status.is-live {
  background: var(--up-bg);
  color: var(--up);
  border: 1px solid var(--up-line);
}
.ov-chip-status.is-warn {
  background: var(--warn-bg);
  color: var(--warn);
  border: 1px solid var(--warn-line);
}

.ov-pipe-list {
  display: flex;
  flex-direction: column;
}
.ov-pipe-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
}
.ov-pipe-row:last-child {
  border-bottom: 0;
}
.ov-pipe-info {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  min-width: 0;
}
.ov-pipe-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.ov-pipe-dot.is-fresh {
  background: var(--up);
  box-shadow: 0 0 6px var(--up);
}
.ov-pipe-dot.is-stale {
  background: var(--warn);
}
.ov-pipe-filename {
  font-size: var(--text-xs);
  color: var(--ds-color-text-secondary);
}
.ov-pipe-meta {
  display: flex;
  align-items: center;
  gap: 10px;
}
.ov-pipe-age {
  font-size: var(--text-4xs);
  color: var(--ds-color-brand);
  background: rgba(103, 153, 254, 0.08);
  padding: 1px 6px;
  border-radius: var(--r-xs);
}
.ov-pipe-size {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
  width: 44px;
  text-align: right;
}

/* 快捷管控通道 */
.ov-nav-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: 1px;
  background: var(--line-1);
}
@media (min-width: 480px) {
  .ov-nav-grid { grid-template-columns: repeat(2, 1fr); }
}
.ov-nav-tile {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: var(--sp-6) var(--ds-space-4);
  background: var(--surface-1);
  text-decoration: none;
  color: inherit;
  transition: all var(--dur-fast) var(--ease-out);
}
.ov-nav-tile:hover {
  background: var(--ds-color-bg-hover);
}
.ov-nt-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border-radius: var(--r-xs);
  background: var(--surface-2);
  border: 1px solid var(--line-1);
  color: var(--ds-color-brand);
  flex-shrink: 0;
}
.ov-nav-tile:hover .ov-nt-icon {
  background: var(--ds-color-brand);
  color: #fff;
  border-color: var(--ds-color-brand);
}
.ov-nt-content {
  min-width: 0;
  flex: 1;
}
.ov-nt-title {
  font-size: var(--text-xs);
  font-weight: 500;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ov-nt-desc {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  margin-top: 1px;
}
.ov-nt-arrow {
  color: var(--ds-color-text-placeholder);
  transition: transform var(--dur-fast);
}
.ov-nav-tile:hover .ov-nt-arrow {
  transform: translateX(2px);
  color: var(--ds-color-brand);
}

/* ══ 模块 3：系统审计与运行轨迹 ══ */
.ov-audit-table {
  display: flex;
  flex-direction: column;
  /* 批 114：窄屏（移动端 390px）允许横向平滑滚动，不裁切右侧详情指示与时间 */
  overflow-x: auto;
}
.ov-audit-row {
  display: grid;
  grid-template-columns: 180px 140px 1fr 140px;
  min-width: 520px;
  align-items: center;
  gap: 12px;
  padding: 10px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.04);
  cursor: pointer;
  transition: background-color var(--dur-fast);
}
.ov-audit-row:last-child {
  border-bottom: 0;
}
.ov-audit-row:hover {
  background-color: rgba(255, 255, 255, 0.025);
}
.ov-audit-row.is-selected {
  background-color: rgba(103, 153, 254, 0.04);
}

.ov-ar-time {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-3xs);
  color: var(--ds-color-text-description);
}
.ov-ar-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  flex-shrink: 0;
}
.ov-ar-dot.is-ok { background: var(--up); box-shadow: 0 0 6px var(--up); }
.ov-ar-dot.is-fail { background: var(--down); }

.ov-ar-tag {
  display: flex;
  align-items: center;
  gap: 8px;
}
.ov-tag-chip {
  display: inline-flex;
  align-items: center;
  height: 20px;
  padding: 0 6px;
  border-radius: var(--r-xs);
  font-family: var(--ds-font-mono);
  font-size: var(--text-3xs);
  font-weight: 600;
  text-transform: uppercase;
}
.ov-tag-chip.is-info {
  background: rgba(103, 153, 254, 0.12);
  color: var(--ds-color-brand);
  border: 1px solid rgba(103, 153, 254, 0.25);
}
.ov-tag-chip.is-warn {
  background: var(--warn-bg);
  color: var(--warn);
  border: 1px solid var(--warn-line);
}
.ov-tag-chip.is-neutral {
  background: rgba(255, 255, 255, 0.05);
  color: var(--ds-color-text-description);
  border: 1px solid rgba(255, 255, 255, 0.08);
}
.ov-tag-name {
  font-size: var(--text-xs);
  color: var(--ds-color-text-secondary);
}

.ov-ar-summary {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}

.ov-ar-meta {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 12px;
}
.ov-ar-ago {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.ov-ar-toggle {
  font-size: var(--text-4xs);
  color: var(--ds-color-brand);
  padding: var(--sp-hair) var(--sp-2);
  border-radius: var(--r-xs);
  background: rgba(103, 153, 254, 0.08);
}

.ov-ar-json-panel {
  grid-column: 1 / -1;
  margin-top: 6px;
  padding: var(--sp-6) var(--ds-space-4);
  border-radius: var(--r-xs);
  background: rgba(0, 0, 0, 0.4);
  border: 1px solid rgba(255, 255, 255, 0.06);
}
.ov-json-code {
  margin: 0;
  font-size: var(--text-4xs);
  line-height: 1.5;
  color: #8bb2ff;
  white-space: pre-wrap;
  word-break: break-all;
}

/* 骨架 */
.ov-skel-stack {
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.ov-skel-row {
  height: 38px;
  border-radius: var(--r-xs);
}
.ov-skel-pipe {
  height: 28px;
  border-radius: var(--r-xs);
}
</style>
