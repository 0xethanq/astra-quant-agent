<script setup lang="ts">
/**
 * PolicySnapshotPage.vue · 策略版本快照工位
 * ---------------------------------------------------------------------------
 * 骨架（推倒重来）：
 *   旧 = 自带图标的巨型头部卡 + 三格身份条 + **四张各自带彩色图标方块的单元卡**
 *        + 归档版本库 + 手写遮罩归档弹窗
 *   新 = 共享 PageHeader（动作集中）→ 策略身份带（4 项事实，含整包哈希）
 *        → **四大策略单元收进单一面板的 4 行矩阵**（图标中性化、明细横向排布）
 *        → 归档版本库（行式清单 + 空态/骨架）→ BaseDialog 归档对话框
 *
 * 关键结构变化：四张重复了四遍「彩色图标块 + 边框 + 页脚说明框」的单元卡，
 * 改为**一个面板里的四行**，每行按 `单元 | 关键明细(4 项) | 进入` 三段排布。
 * 四个单元的结构因此变成**一份数据驱动的模板**（`units` computed），
 * 而不是四段复制粘贴的模板代码。
 *
 * 后端契约（逐字未改）：
 *   GET    /api/v1/admin/policy/current-snapshot
 *   GET    /api/v1/admin/policy/archives
 *   POST   /api/v1/admin/policy/archive    { name, description }
 *   POST   /api/v1/admin/policy/restore    { policy_hash }
 *   DELETE /api/v1/admin/policy/archive/{hash}
 *
 * ⚠️ 归档标识口径未动：一律优先 `package_hash`，历史归档（无该字段）退回 `policy_hash`。
 */
import { fmtDateTime, utcStrToBj } from '../../utils/format';
import { useToast } from '../../composables/useToast';
import { useConfirm } from '../../composables/useConfirm';
const toast = useToast();
const { ask } = useConfirm();
import { ref, computed, onMounted } from 'vue';
import { useI18n } from '../../composables/useI18n';
const { t } = useI18n();
import { useApi } from '../../composables/useApi';
import { useAuthStore } from '../../stores/auth';
import PageHeader from '../../components/admin/PageHeader.vue';
import BaseDialog from '../../components/base/BaseDialog.vue';
import BaseEmpty from '../../components/base/BaseEmpty.vue';
import { Layers, FileText, Sparkles, ShieldCheck, Users, RefreshCw,
  Hash, Activity, Clock, ArrowUpRight, BookmarkPlus, RotateCcw,
  Archive, Trash2, Loader2, AlertTriangle, Package } from 'lucide-vue-next';
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue';

const { api } = useApi();
const auth = useAuthStore();

const loading = ref(true);
const refreshing = ref(false);
const archiving = ref(false);
const restoring = ref(false);
const deleting = ref<string | null>(null);

const snapshotData = ref<any>(null);
const archives = ref<any[]>([]);

/**
 * 归档标识（批1 P0-3）：归档文件按「整包标识」命名，四单元 policy_hash 看不到
 * 风控/路由 —— 只差风控的两个版本会同 policy_hash。展示/回滚/删除/「当前正在运行」
 * 判定一律优先用 package_hash，历史归档（无该字段）退回 policy_hash。
 */
function arcKey(arc: any): string {
  return String(arc?.package_hash || arc?.policy_hash || '');
}
function isCurrentArc(arc: any): boolean {
  const pkg = String(snapshotData.value?.package_hash || '');
  if (arc?.package_hash) return !!pkg && String(arc.package_hash) === pkg;
  return !!arc?.policy_hash && arc.policy_hash === snapshotData.value?.snapshot?.policy_hash;
}
const errorMsg = ref<string | null>(null);

// Archive Dialog State
const showArchiveModal = ref(false);
const archiveName = ref('');
const archiveDesc = ref('');

async function fetchSnapshot() {
  refreshing.value = true;
  errorMsg.value = null;
  try {
    const [snapRes, arcRes] = await Promise.all([
      api('/api/v1/admin/policy/current-snapshot'),
      api('/api/v1/admin/policy/archives'),
    ]);
    if (snapRes && snapRes.ok) {
      snapshotData.value = snapRes;
    }
    if (arcRes && arcRes.ok) {
      archives.value = arcRes.archives || [];
    }
  } catch (err: any) {
    errorMsg.value = err.message || t('admin.policySnapshot.err.fetchFailed');
  } finally {
    loading.value = false;
    refreshing.value = false;
  }
}

async function saveArchive() {
  if (!auth.isSuperadmin) {
    toast.err(t('admin.policySnapshot.err.notSuperadmin'));
    return;
  }
  if (!archiveName.value.trim()) {
    toast.warn(t('admin.policySnapshot.err.nameRequired'));
    return;
  }
  archiving.value = true;
  try {
    const res = await api('/api/v1/admin/policy/archive', {
      method: 'POST',
      body: JSON.stringify({
        name: archiveName.value.trim(),
        description: archiveDesc.value.trim(),
      }),
    });
    if (res && res.ok) {
      toast.ok(t('admin.policySnapshot.toast.archivedOk', undefined, { name: res.entry?.name, hash: res.entry?.package_hash || res.entry?.policy_hash }));
      showArchiveModal.value = false;
      archiveName.value = '';
      archiveDesc.value = '';
      await fetchSnapshot();
    }
  } catch (err: any) {
    toast.err(t('admin.policySnapshot.err.archiveFailed', undefined, { msg: err.message }));
  } finally {
    archiving.value = false;
  }
}

async function restorePolicy(hash: string, name: string) {
  if (!auth.isSuperadmin) return;
  const _ok = await ask({ title: t('admin.policySnapshot.confirm.restore', undefined, { name, hash }), danger: true, okText: t('common.restore') });
  if (!_ok) return;
  restoring.value = true;
  try {
    const res = await api('/api/v1/admin/policy/restore', {
      method: 'POST',
      body: JSON.stringify({ policy_hash: hash }),
    });
    if (res && res.ok) {
      toast.ok(t('admin.policySnapshot.toast.restoredOk', undefined, { name, hash }));
      await fetchSnapshot();
    }
  } catch (err: any) {
    toast.err(t('admin.policySnapshot.err.restoreFailed', undefined, { msg: err.message }));
  } finally {
    restoring.value = false;
  }
}

async function deleteArchive(hash: string, name: string) {
  if (!auth.isSuperadmin) return;
  const _ok = await ask({ title: t('admin.policySnapshot.confirm.delete', undefined, { name, hash }), danger: true, okText: t('common.del') });
  if (!_ok) return;
  deleting.value = hash;
  try {
    const res = await api(`/api/v1/admin/policy/archive/${hash}`, {
      method: 'DELETE',
    });
    if (res && res.ok) {
      toast.ok(t('admin.policySnapshot.toast.deletedOk', undefined, { name }));
      await fetchSnapshot();
    }
  } catch (err: any) {
    toast.err(t('admin.policySnapshot.err.deleteFailed', undefined, { msg: err.message }));
  } finally {
    deleting.value = null;
  }
}

function formatTimestamp(ts: number) {
  if (!ts) return t('admin.policySnapshot.notRecorded');
  return fmtDateTime(ts * 1000);
}

/** 未知值统一回落 '--'（避免界面上出现 undefined / 空白） */
function v(x: any): string {
  return x === null || x === undefined || x === '' ? '--' : String(x);
}

/**
 * 四大策略单元：**一份数据驱动的模板**。
 * tone: 'up' 表示该值属于"守卫已生效"的肯定态，走语义绿。
 */
const units = computed(() => {
  const u = snapshotData.value?.snapshot?.units || {};
  const P = 'admin.policySnapshot.unit.';
  return [
    {
      key: 'prompt',
      title: t(`${P}prompt.title`),
      icon: FileText,
      to: '/admin/promptlib',
      fields: [
        { label: t(`${P}prompt.profile`), value: v(u.prompt_profile?.active_profile_name || u.prompt_profile?.active_profile_id) },
        { label: t(`${P}prompt.layoutHash`), value: '#' + v(u.prompt_profile?.layout_hash), mono: true },
        { label: t(`${P}prompt.mode`), value: v(u.prompt_profile?.editor_mode) },
        { label: t(`${P}prompt.slotGuard`), value: t(`${P}prompt.slotGuardValue`), tone: 'up' },
      ],
      note: t(`${P}prompt.note`),
    },
    {
      key: 'evolution',
      title: t(`${P}evolution.title`),
      icon: Sparkles,
      to: '/admin/evolution',
      fields: [
        { label: t(`${P}evolution.version`), value: v(u.evolution_mind?.version), mono: true },
        { label: t(`${P}evolution.counts`), value: `${v(u.evolution_mind?.enabled_count)} / ${v(u.evolution_mind?.total_count)}` },
        { label: t(`${P}evolution.review`), value: t(`${P}evolution.reviewValue`), tone: 'up' },
        { label: t(`${P}evolution.concurrency`), value: t(`${P}evolution.concurrencyValue`), tone: 'up' },
      ],
      note: t(`${P}evolution.note`),
    },
    {
      key: 'interceptor',
      title: t(`${P}interceptor.title`),
      icon: ShieldCheck,
      to: '/admin/interceptors',
      fields: [
        { label: t(`${P}interceptor.core`), value: t(`${P}interceptor.coreValue`), tone: 'up' },
        { label: t(`${P}interceptor.pluginsHash`), value: '#' + v(u.physical_interceptors?.plugins_hash), mono: true },
        {
          label: t(`${P}interceptor.enabled`),
          value: t(`${P}interceptor.enabledValue`, undefined, {
            n: v(u.physical_interceptors?.enabled_count),
            t: v(u.physical_interceptors?.total_count),
          }),
        },
        { label: t(`${P}interceptor.recheck`), value: t(`${P}interceptor.recheckValue`), tone: 'up' },
      ],
      note: t(`${P}interceptor.note`),
    },
    {
      key: 'council',
      title: t(`${P}council.title`),
      icon: Users,
      to: '/admin/council',
      fields: [
        {
          label: t(`${P}council.status`),
          value: u.model_council?.enabled ? t(`${P}council.statusEnabled`) : t(`${P}council.statusDisabled`),
          tone: u.model_council?.enabled ? 'up' : 'muted',
        },
        {
          label: t(`${P}council.consensus`),
          value: u.model_council?.consensus_mode === 'cross_examination'
            ? t(`${P}council.consensusCross`)
            : t(`${P}council.consensusStandard`),
        },
        { label: t(`${P}council.seats`), value: t(`${P}council.seatsValue`, undefined, { n: u.model_council?.active_roles?.length || 0 }) },
        { label: t(`${P}council.adopted`), value: t(`${P}council.adoptedValue`), tone: 'up' },
      ],
      note: t(`${P}council.note`),
    },
  ];
});

function closeArchiveModal() {
  showArchiveModal.value = false;
  archiveName.value = '';
  archiveDesc.value = '';
}

onMounted(() => {
  fetchSnapshot();
});
</script>

<template>
  <div class="pol">
    <PageHeader :title="t('nav.admin.policy')" :description="t('admin.policySnapshot.desc')">
      <template #actions>
        <span v-if="snapshotData?.policy_version" class="badge badge-accent mono">
          {{ snapshotData.policy_version }}
        </span>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="refreshing" @click="fetchSnapshot">
          <RefreshCw :size="14" :class="refreshing && 'animate-spin shrink-0'" />
          <span>{{ refreshing ? t('admin.policySnapshot.btn.refreshing') : t('admin.policySnapshot.btn.refresh') }}</span>
        </button>
        <button type="button" class="btn btn-primary btn-sm" :disabled="!auth.isSuperadmin" @click="showArchiveModal = true">
          <BookmarkPlus :size="14" />
          <span>{{ t('admin.policySnapshot.btn.archive') }}</span>
        </button>
      </template>
    </PageHeader>

    <!-- 拉取失败 -->
    <div v-if="errorMsg" role="alert" class="state-block is-error">
      <span class="state-icon"><AlertTriangle :size="17" /></span>
      <p class="state-title">{{ t('admin.policySnapshot.err.fetchFailed') }}</p>
      <p class="state-desc">{{ errorMsg }}</p>
      <button type="button" class="btn btn-ghost btn-sm mt-1" :disabled="refreshing" @click="fetchSnapshot">
        <RefreshCw :size="14" :class="refreshing && 'animate-spin shrink-0'" />
        <span>{{ t('common.retry') }}</span>
      </button>
    </div>

    <!-- 首屏骨架 -->
    <template v-if="loading">
      <BaseLoadingAnnounce />
      <section class="card band">
        <div v-for="i in 4" :key="i" class="fact">
          <div class="skeleton skeleton-text" style="width: 46%" />
          <div class="skeleton skeleton-text skeleton-value" style="width: 72%" />
          <div class="skeleton skeleton-text" style="width: 34%" />
        </div>
      </section>
      <section class="card p-4">
        <div v-for="i in 4" :key="i" class="skeleton skeleton-row mt-2.5" />
      </section>
    </template>

    <template v-else-if="snapshotData?.snapshot">
      <!-- ══ 策略身份带 ══ -->
      <section class="card band">
        <div class="fact">
          <span class="fact-label"><Layers :size="12" />{{ t('admin.policySnapshot.identity.activeVersion') }}</span>
          <span class="fact-value truncate" :title="v(snapshotData.snapshot.policy_version)">{{ v(snapshotData.snapshot.policy_version) }}</span>
          <span class="fact-foot mono">{{ snapshotData.policy_version || '--' }}</span>
        </div>

        <div class="fact">
          <span class="fact-label"><Hash :size="12" />{{ t('admin.policySnapshot.identity.hash') }}</span>
          <span class="fact-value truncate" :title="'#' + v(snapshotData.snapshot.policy_hash)">#{{ v(snapshotData.snapshot.policy_hash) }}</span>
          <span class="fact-foot mono">{{ t('admin.policySnapshot.unitsTitle') }}</span>
        </div>

        <div class="fact">
          <span class="fact-label"><Package :size="12" />{{ t('admin.policySnapshot.bandPackageHash') }}</span>
          <span class="fact-value truncate" :title="'#' + v(snapshotData.package_hash)">#{{ v(snapshotData.package_hash) }}</span>
          <span class="fact-foot">{{ t('admin.policySnapshot.bandPackageHashFoot') }}</span>
        </div>

        <div class="fact">
          <span class="fact-label"><Clock :size="12" />{{ t('admin.policySnapshot.identity.generatedAt') }}</span>
          <span class="fact-value num truncate" :title="formatTimestamp(snapshotData.snapshot.timestamp)">{{ formatTimestamp(snapshotData.snapshot.timestamp) }}</span>
          <span class="fact-foot mono">
            <Activity :size="12" /> {{ snapshotData.policy_version ? 'OK' : '--' }}
          </span>
        </div>
      </section>

      <!-- ══ 四大策略单元矩阵 ══ -->
      <section class="card">
        <header class="card-head">
          <div>
            <h2 class="card-title">{{ t('admin.policySnapshot.unitsTitle') }}</h2>
            <p class="card-sub">{{ t('admin.policySnapshot.unitsDesc') }}</p>
          </div>
        </header>

        <div class="pol-units">
          <div class="pol-unit pol-unit-head">
            <span>{{ t('admin.policySnapshot.colUnit') }}</span>
            <span>{{ t('admin.policySnapshot.colDetail') }}</span>
            <span>{{ t('admin.policySnapshot.colEnter') }}</span>
          </div>

          <div v-for="u in units" :key="u.key" class="pol-unit">
            <div class="pol-unit-id">
              <span class="icon-box"><component :is="u.icon" :size="14" /></span>
              <span class="pol-unit-name">{{ u.title }}</span>
            </div>

            <dl class="pol-unit-fields">
              <div v-for="f in u.fields" :key="f.label" class="pol-kv">
                <dt>{{ f.label }}</dt>
                <dd
                  :class="[f.mono ? 'mono' : '', f.tone === 'up' ? 'is-up' : f.tone === 'muted' ? 'is-muted' : '']"
                  :title="f.value"
                >{{ f.value }}</dd>
              </div>
            </dl>

            <RouterLink :to="u.to" class="pol-unit-enter">
              <span>{{ t('admin.policySnapshot.unit.enter') }}</span>
              <ArrowUpRight :size="13" />
            </RouterLink>

            <p class="pol-unit-note">{{ u.note }}</p>
          </div>
        </div>
      </section>

      <!-- ══ 归档版本库 ══ -->
      <section class="card">
        <header class="card-head">
          <div>
            <h2 class="card-title"><Archive :size="14" />{{ t('admin.policySnapshot.archive.title') }}</h2>
            <p class="card-sub">{{ t('admin.policySnapshot.archive.hint') }}</p>
          </div>
          <span class="badge">{{ t('admin.policySnapshot.archive.count', undefined, { n: archives.length }) }}</span>
        </header>

        <BaseEmpty v-if="!archives.length" :text="t('admin.policySnapshot.archive.empty')" />

        <div v-else class="pol-archives">
          <article v-for="arc in archives" :key="arcKey(arc)" class="pol-arc">
            <div class="pol-arc-main">
              <div class="pol-arc-top">
                <span class="pol-arc-name">{{ arc.name }}</span>
                <span class="badge mono">#{{ arcKey(arc) }}</span>
                <span v-if="isCurrentArc(arc)" class="badge badge-up">
                  {{ t('admin.policySnapshot.archive.running') }}
                </span>
              </div>
              <p v-if="arc.description" class="pol-arc-desc">{{ arc.description }}</p>
              <div class="pol-arc-meta mono">
                <span>{{ t('admin.policySnapshot.archive.archivedAt') }}: {{ utcStrToBj(arc.archived_at, true) }}</span>
                <span>{{ t('admin.policySnapshot.archive.author') }}: {{ arc.author }}</span>
                <span class="pol-arc-summary truncate" :title="arc.summary">{{ arc.summary }}</span>
              </div>
            </div>

            <div class="pol-arc-actions">
              <button type="button"
                class="btn btn-sm"
                :class="isCurrentArc(arc) ? 'btn-ghost' : 'btn-ghost pol-restore'"
                :disabled="restoring || !auth.isSuperadmin || isCurrentArc(arc)"
                @click="restorePolicy(arcKey(arc), arc.name)"
              >
                <RotateCcw :size="13" :class="restoring && 'animate-spin shrink-0'" />
                <span>{{ isCurrentArc(arc) ? t('admin.policySnapshot.archive.isCurrent') : t('admin.policySnapshot.archive.restore') }}</span>
              </button>

              <button type="button"
                class="btn btn-danger btn-sm"
                :disabled="deleting === arcKey(arc) || !auth.isSuperadmin"
                :title="t('admin.policySnapshot.archive.deleteTitle')"
                @click="deleteArchive(arcKey(arc), arc.name)"
              >
                <Loader2 v-if="deleting === arcKey(arc)" :size="13" class="animate-spin shrink-0" />
                <Trash2 v-else :size="13" />
                <span>{{ t('admin.policySnapshot.archive.delete') }}</span>
              </button>
            </div>
          </article>
        </div>
      </section>
    </template>

    <!-- 拉取失败：透出真实原因（此前这里显示一句通用的「网络异常」，
         401/500 之类的真实原因只存在于 toast 里，toast 一消失就无从查起）。 -->
    <BaseEmpty
      v-else-if="errorMsg"
      :text="t('admin.policySnapshot.err.fetchFailed')"
      :desc="errorMsg"
    >
      <template #action>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="refreshing" @click="fetchSnapshot">
          <RefreshCw :size="14" :class="refreshing && 'animate-spin shrink-0'" />
          <span>{{ t('common.retry') }}</span>
        </button>
      </template>
    </BaseEmpty>

    <!-- 批 72：拉取**成功**但后台尚无快照 —— 这是「没有数据」，不是「拉取失败」。
         此前它落进上面的失败分支，页面会声称「获取策略版本快照失败 + 网络异常」，
         把一次正常响应谎报成故障，运维会去排查根本不存在的网络问题。 -->
    <BaseEmpty
      v-else
      :text="t('admin.policySnapshot.emptySnapshot')"
      :desc="t('admin.policySnapshot.emptySnapshotDesc')"
    >
      <template #action>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="refreshing" @click="fetchSnapshot">
          <RefreshCw :size="14" :class="refreshing && 'animate-spin shrink-0'" />
          <span>{{ t('admin.policySnapshot.btn.refresh') }}</span>
        </button>
      </template>
    </BaseEmpty>

    <!-- ══ 归档对话框 ══ -->
    <BaseDialog
      :open="showArchiveModal"
      :title="t('admin.policySnapshot.modal.title')"
      :desc="t('admin.policySnapshot.modal.desc')"
      size="md"
      @close="closeArchiveModal"
    >
      <div class="pol-form">
        <label class="field-stack">
          <span class="form-label">{{ t('admin.policySnapshot.modal.nameLabel') }}</span>
          <input
            v-model="archiveName"
            type="text"
            class="field"
            :placeholder="t('admin.policySnapshot.modal.namePlaceholder')"
            @keyup.enter="saveArchive"
          />
        </label>

        <label class="field-stack">
          <span class="form-label">{{ t('admin.policySnapshot.modal.descLabel') }}</span>
          <textarea
            v-model="archiveDesc"
            rows="3"
            class="field pol-textarea"
            :placeholder="t('admin.policySnapshot.modal.descPlaceholder')"
          />
        </label>
      </div>

      <template #footer>
        <button type="button" class="btn btn-ghost btn-sm" @click="closeArchiveModal">
          {{ t('admin.policySnapshot.modal.cancel') }}
        </button>
        <button type="button"
          class="btn btn-primary btn-sm"
          :disabled="archiving || !archiveName.trim()"
          @click="saveArchive"
        >
          <Loader2 v-if="archiving" :size="14" class="animate-spin shrink-0" />
          <BookmarkPlus v-else :size="14" />
          <span>{{ archiving ? t('admin.policySnapshot.modal.archiving') : t('admin.policySnapshot.modal.confirm') }}</span>
        </button>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.pol {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}

/* ══ 策略身份带 ══ */







/* ══ 四大策略单元矩阵 ══ */
.pol-units {
  display: flex;
  flex-direction: column;
}
.pol-unit {
  display: grid;
  grid-template-columns: 190px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--ds-space-4);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
}
.pol-unit:last-child {
  border-bottom: 0;
}
.pol-unit:not(.pol-unit-head):hover {
  background-color: var(--ds-color-bg-hover);
}
.pol-unit-head {
  min-height: 30px;
  background-color: var(--ds-color-bg-surface-inset);
  font-size: var(--text-3xs);
  font-weight: 500;
  letter-spacing: var(--track-label);
  text-transform: uppercase;
  color: var(--ds-color-text-placeholder);
}
.pol-unit-id {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  min-width: 0;
}
.pol-unit-name {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}

/* 4 项明细横向排布 */
.pol-unit-fields {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--ds-space-3);
  min-width: 0;
}
.pol-kv {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.pol-kv dt {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pol-kv dd {
  font-size: var(--text-xs);
  font-weight: 500;
  color: var(--ds-color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.pol-kv dd.is-up {
  color: var(--up);
}
.pol-kv dd.is-muted {
  color: var(--ds-color-text-placeholder);
}

.pol-unit-enter {
  display: inline-flex;
  align-items: center;
  gap:4px;
  /* 批 18：原热区 59×17px，低于可点下限；用负外边距抵消内边距，
     视觉位置不变，命中区变成 24px 高 */
  padding: 4px 8px;
  margin: -4px -8px;
  border-radius: var(--r-xs);
  font-size: var(--text-3xs);
  color: var(--ds-color-brand);
  white-space: nowrap;
}
.pol-unit-enter:hover {
  text-decoration: underline;
  background-color: var(--astra-brand-bg);
}
.pol-unit-note {
  grid-column: 2 / -1;
  font-size: var(--text-4xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-placeholder);
}

@media (max-width: 1100px) {
  .pol-unit {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .pol-unit-fields {
    grid-column: 1 / -1;
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .pol-unit-note {
    grid-column: 1 / -1;
  }
  .pol-unit-head {
    display: none;
  }
}

/* ══ 归档版本库 ══ */
.pol-archives {
  display: flex;
  flex-direction: column;
}
.pol-arc {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-4);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
  transition: background-color var(--dur-fast);
}
.pol-arc:last-child {
  border-bottom: 0;
}
.pol-arc:hover {
  background-color: var(--ds-color-bg-hover);
}
.pol-arc-main {
  display: flex;
  flex-direction: column;
  gap:4px;
  min-width: 0;
  flex: 1;
}
.pol-arc-top {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.pol-arc-name {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.pol-arc-desc {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-description);
}
.pol-arc-meta {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--ds-space-3);
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.pol-arc-summary {
  max-width: 420px;
}
.pol-arc-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-shrink: 0;
}
.pol-restore {
  color: var(--up);
}

@media (max-width: 860px) {
  .pol-arc {
    flex-direction: column;
    align-items: stretch;
  }
  .pol-arc-actions {
    justify-content: flex-end;
  }
}

/* 归档对话框 */
.pol-form {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}

.pol-textarea {
  width: 100%;
  resize: vertical;
  line-height: var(--leading-body);
  font-family: inherit;
}
</style>
