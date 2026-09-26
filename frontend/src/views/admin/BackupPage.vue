<script setup lang="ts">
/**
 * BackupPage.vue · 数据灾备工位
 * ---------------------------------------------------------------------------
 * 骨架（推倒重来）：
 *   旧 = 一行简介 + 蓝色徽章 + 一张大配置卡（4 字段网格 + 内联凭据块）
 *        + 两张卡（最近一次 / 归档表）+ 4 个内联样式按钮
 *        + 色相类（blue-400 / cyan-400 / amber-500 / emerald-500 / zinc-500）
 *   新 = 共享 PageHeader（测试 / 保存 / 立即备份 / 上传 / 刷新）
 *        → **灾备状态带**（自动灾备 / 保存位置 / 执行时间 / 最近一次）
 *        → **灾备配置面板**（4 字段 + 远端凭据分区 + 动作页脚）
 *        → **最近一次灾备** 面板 + **备份归档清单**行式清单
 *
 * 后端契约（逐字未改）：
 *   GET  /api/v1/admin/backups/simple · /api/v1/admin/backup-target-types · /api/v1/admin/backups
 *   PUT  /api/v1/admin/backups/simple                 ← payload() 七字段逐字保留
 *   POST /api/v1/admin/backups/simple/test · /api/v1/admin/backups/run
 *   POST /api/v1/admin/backups/restore · /api/v1/admin/backups/upload
 *   GET  /api/v1/admin/backups/download/{name}?token=  ← **原生 fetch 双通道下载**，逐字保留
 *
 * ⚠️ 高危门禁逐字保留：立即备份需逐字 `BACKUP ASTRA`；恢复需逐字 `RESTORE ASTRA`（覆盖式不可撤销）。
 * ⚠️ 下载/上传走原生 `fetch`（带 `X-Astra-Session` 头、Blob 与降级直链双通道、
 *    FormData 上传）——这些都不经 `api()` 封装，本批**一字未动**。
 */
import { fmtDateTime } from '../../utils/format';
import { useToast } from '../../composables/useToast'
import { useConfirm } from '../../composables/useConfirm'
const toast = useToast()
const { ask } = useConfirm()
import { ref, computed, onMounted } from 'vue'
import PageHeader from '../../components/admin/PageHeader.vue'
import BaseSwitch from '../../components/base/BaseSwitch.vue'
import BaseEmpty from '../../components/base/BaseEmpty.vue'
import { useI18n } from '../../composables/useI18n'
const { t } = useI18n()
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'
import { HardDrive, RefreshCw, PlugZap, Save, PlayCircle, Archive, Download,
  Upload, RotateCcw, AlertTriangle, Loader2, MapPin, Clock, CalendarClock, History } from 'lucide-vue-next'
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue';

const { api } = useApi()
const auth = useAuthStore()

const loading = ref(true)
const loadError = ref('')
const busy = ref<'test' | 'save' | 'run' | 'restore' | 'upload' | ''>('')
const downloadingArchive = ref<string>('')

const simple = ref<any>(null)

/** 灾备执行时间：按 started_at/finished_at/created_at 顺序取，格式统一 */
function fmtBackupTime(latest: any): string {
  const raw = latest?.finished_at || latest?.started_at || latest?.created_at || latest?.time
  if (!raw) return '--'
  return fmtDateTime(raw)
}
/** 最近一次备份的状态文案（批 27）：查表本地化，未登记枚举原样回退。
 *  此前徽章直接印后端枚举 `success`，同卡片其它字段却都是中文。 */
function statusLabelOf(s?: string): string {
  if (!s) return t('admin.backup.statusSuccess')
  const key = `admin.backup.status${s.charAt(0).toUpperCase()}${s.slice(1)}`
  return t(key, s)
}
const targetTypes = ref<any[]>([])
const status = ref<any>(null)
const uploadFileInput = ref<HTMLInputElement | null>(null)

const enabled = ref(false)
const scheduleTime = ref('02:00')
const destination = ref('local')
const retention = ref(3)
const endpoint = ref('')
const bucket = ref('')
const credentials = ref<Record<string, string>>({})

const remoteDest = computed(() => ['s3', 'oss', 'webdav', 'baidu_oauth'].includes(destination.value))
const needsBucket = computed(() => destination.value === 's3' || destination.value === 'oss')
const credentialFields = computed(() => {
  if (['s3', 'oss'].includes(destination.value)) return ['access_key_id', 'secret_access_key']
  if (['webdav', 'aliyundrive', 'quark'].includes(destination.value)) return ['username', 'password']
  if (destination.value === 'baidu_oauth') return ['app_key', 'app_secret', 'refresh_token']
  return []
})

async function load() {
  loading.value = true
  loadError.value = ''
  try {
    const [s, t, st] = await Promise.all([
      api('/api/v1/admin/backups/simple'),
      api('/api/v1/admin/backup-target-types'),
      api('/api/v1/admin/backups'),
    ])
    simple.value = s
    targetTypes.value = t.target_types || []
    status.value = st
    enabled.value = s.enabled
    destination.value = s.destination
    scheduleTime.value = s.schedule_time || '02:00'
    retention.value = s.retention || 3
    endpoint.value = s.target?.endpoint || ''
    bucket.value = s.target?.bucket || ''
  } catch (e: any) {
    loadError.value = e.message
    toast.err(t('admin.backup.loadFailed', undefined, { msg: e.message }))
  } finally {
    loading.value = false
  }
}

function payload() {
  return {
    enabled: enabled.value,
    schedule_time: scheduleTime.value,
    destination: destination.value,
    retention: Number(retention.value) || 3,
    endpoint: endpoint.value.trim(),
    bucket: bucket.value.trim(),
    credentials: credentials.value,
  }
}

async function testConnection() {
  busy.value = 'test'
  try {
    const res = await api('/api/v1/admin/backups/simple/test', { method: 'POST', body: JSON.stringify(payload()) })
    toast.ok(`${res.detail}`)
  } catch (e: any) {
    toast.err(t('admin.backup.testFailed', undefined, { msg: e.message }))
  } finally {
    busy.value = ''
  }
}

async function save() {
  busy.value = 'save'
  try {
    await api('/api/v1/admin/backups/simple', { method: 'PUT', body: JSON.stringify(payload()) })
    toast.ok(t('admin.backup.configSaved', undefined, { time: scheduleTime.value }))
    await load()
  } catch (e: any) {
    toast.err(t('admin.backup.saveFailed', undefined, { msg: e.message }))
  } finally {
    busy.value = ''
  }
}

async function runNow() {
  // 批C(2026-09-13)：prompt() → 项目确认服务（移动端 prompt 常被浏览器弱化/难用），
  // 短语仍由用户逐字输入，与后端 `BACKUP ASTRA` 契约一致。
  const _ok = await ask({
    title: t('admin.backup.runNowTitle'),
    desc: t('admin.backup.runNowDesc'),
    danger: true,
    confirmPhrase: 'BACKUP ASTRA',
    okText: t('common.execute'),
  })
  if (!_ok) return
  busy.value = 'run'
  try {
    const res = await api('/api/v1/admin/backups/run', { method: 'POST', body: JSON.stringify({ confirmation: 'BACKUP ASTRA' }) })
    toast.ok(t('admin.backup.runOk', undefined, { n: (res.output || '').length }))
    await load()
  } catch (e: any) {
    toast.err(t('admin.backup.runFailed', undefined, { msg: e.message }))
  } finally {
    busy.value = ''
  }
}

async function downloadArchive(archiveName: string) {
  const clean = archiveName.split('/').pop() || archiveName
  downloadingArchive.value = clean
  toast.ok(t('admin.backup.connecting', undefined, { file: clean }))

  const token = auth.token || localStorage.getItem('astra.admin.session.id') || ''
  const directUrl = `/api/v1/admin/backups/download/${encodeURIComponent(clean)}${token ? `?token=${encodeURIComponent(token)}` : ''}`

  try {
    // 双通道策略 1：通过 Fetch Blob 在内存中获取并检查状态
    const resp = await fetch(directUrl, {
      headers: {
        ...(token ? { 'X-Astra-Session': token } : {})
      }
    })

    if (!resp.ok) {
      let errMsg = `HTTP ${resp.status}`
      try {
        const errJson = await resp.json()
        errMsg = errJson.detail || errMsg
      } catch {}
      throw new Error(errMsg)
    }

    const blob = await resp.blob()
    const blobUrl = window.URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = blobUrl
    a.download = clean
    document.body.appendChild(a)
    a.click()
    setTimeout(() => {
      a.remove()
      window.URL.revokeObjectURL(blobUrl)
    }, 2000)

    toast.ok(t('admin.backup.downloadTriggered', undefined, { file: clean }))
  } catch (e: any) {
    // 双通道策略 2：若 Blob 或 Fetch 产生跨域或浏览器安全拦截，降级采用原生链接直连触发
    try {
      const fallbackA = document.createElement('a')
      fallbackA.href = directUrl
      fallbackA.download = clean
      fallbackA.target = '_blank'
      document.body.appendChild(fallbackA)
      fallbackA.click()
      setTimeout(() => fallbackA.remove(), 1000)
      toast.ok(t('admin.backup.directChannel', undefined, { file: clean }))
    } catch (fallbackErr: any) {
      toast.err(t('admin.backup.downloadFailed', undefined, { msg: e.message }))
    }
  } finally {
    downloadingArchive.value = ''
  }
}

function triggerUpload() {
  if (uploadFileInput.value) {
    uploadFileInput.value.click()
  }
}

async function onFileSelected(e: Event) {
  const target = e.target as HTMLInputElement
  const file = target.files?.[0]
  if (!file) return
  busy.value = 'upload'
  try {
    const formData = new FormData()
    formData.append('file', file)
    const resp = await fetch('/api/v1/admin/backups/upload', {
      method: 'POST',
      headers: {
        ...(auth.token ? { 'X-Astra-Session': auth.token } : {})
      },
      body: formData
    })
    const res = await resp.json()
    if (!resp.ok) {
      throw new Error(res.detail || t('admin.backup.uploadHttp', undefined, { status: resp.status }))
    }
    toast.ok(t('admin.backup.uploadOk', undefined, { file: file.name }))
    await load()
  } catch (err: any) {
    toast.err(t('admin.backup.uploadFailed', undefined, { msg: err.message }))
  } finally {
    busy.value = ''
    if (target) target.value = ''
  }
}

async function restoreArchive(archiveName: string) {
  const clean = archiveName.split('/').pop() || archiveName
  // 批C(2026-09-13)：prompt+alert → 项目确认服务。恢复备份是覆盖式破坏操作
  // （解压覆盖当前配置/历史数据/策略），短语逐字输入，与后端 `RESTORE ASTRA` 契约一致。
  const _ok = await ask({
    title: t('admin.backup.restoreConfirmTitle'),
    desc: t('admin.backup.restoreConfirmDesc', undefined, { file: clean }),
    danger: true,
    confirmPhrase: 'RESTORE ASTRA',
    okText: t('common.overwriteRestore'),
  })
  if (!_ok) return
  busy.value = 'restore'
  try {
    const res = await api('/api/v1/admin/backups/restore', {
      method: 'POST',
      body: JSON.stringify({
        archive_name: clean,
        confirmation: 'RESTORE ASTRA'
      })
    })
    toast.ok(t('admin.backup.restoreOk', undefined, { file: clean, n: res.restored_count }))
    await load()
  } catch (e: any) {
    toast.err(t('admin.backup.restoreFailed', undefined, { msg: e.message }))
  } finally {
    busy.value = ''
  }
}

function fmtBytes(n: number) {
  if (!n) return '--'
  return n > 1048576 ? (n / 1048576).toFixed(1) + ' MB' : Math.round(n / 1024) + ' KB'
}
function fmtTime(ts: number) {
  return fmtDateTime(ts * 1000)
}

const archives = computed<any[]>(() => (status.value?.local_archives || []).slice(0, 10))

/** 保存位置的展示名（旧版 select 里的 option 文案）
 *  存**完整键路径**并直接 `t(k)`，不使用拼接式键名（拼接键无法被 i18n 静态校验识别）。 */
const DEST_LABEL_KEY: Record<string, string> = {
  local: 'admin.backup.destLocal',
  s3: 'admin.backup.destS3',
  oss: 'admin.backup.destOss',
  webdav: 'admin.backup.destWebdav',
  baidu_oauth: 'admin.backup.destBaidu',
}
function destLabel(d: string): string {
  const k = DEST_LABEL_KEY[d]
  return k ? t(k) : d
}

/** 灾备状态带（4 项事实） */
const bandFacts = computed(() => {
  const s = simple.value
  if (!s) return []
  return [
    {
      icon: HardDrive,
      label: t('admin.backup.bandEnabled'),
      value: enabled.value ? t('admin.backup.enabledOn') : t('admin.backup.enabledOff'),
      foot: s.legacy_bypy ? t('admin.backup.legacyTag') : '',
      tone: enabled.value ? 'is-up' : 'is-off',
    },
    {
      icon: MapPin,
      label: t('admin.backup.bandLocation'),
      value: destLabel(destination.value),
      foot: s.configured ? t('admin.backup.targetConfigured') : t('admin.backup.targetNotConfigured'),
      tone: s.configured ? 'is-up' : 'is-warn',
    },
    {
      icon: CalendarClock,
      label: t('admin.backup.bandSchedule'),
      value: scheduleTime.value || '--',
      foot: `${t('admin.backup.secRetention')} ${retention.value}${destination.value === 'local' ? t('admin.backup.retentionLocal') : ''}`,
      tone: '',
    },
    {
      icon: History,
      label: t('admin.backup.bandLatest'),
      value: s.latest ? fmtBackupTime(s.latest) : t('admin.backup.noLatest'),
      foot: s.latest?.status || '',
      tone: s.latest?.status === 'failed' ? 'is-down' : (s.latest ? 'is-up' : 'is-off'),
    },
  ]
})

onMounted(load)
</script>

<template>
  <div class="bk">
    <PageHeader :title="t('nav.admin.backup')" :description="t('admin.backup.intro')">
      <template #actions>
        <span class="badge" :class="simple?.configured ? 'badge-up' : 'badge-warn'">
          {{ simple?.configured ? t('admin.backup.targetConfigured') : t('admin.backup.targetNotConfigured') }}
        </span>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="loading" @click="load">
          <Loader2 v-if="loading && simple" :size="14" class="animate-spin shrink-0" />
          <RefreshCw v-else :size="14" />
          <span>{{ t('common.refresh') }}</span>
        </button>
      </template>
    </PageHeader>

    <div v-if="loadError && !simple" role="alert" class="state-block is-error">
      <span class="state-icon"><AlertTriangle :size="17" /></span>
      <p class="state-title">{{ t('common.loadFailed') }}</p>
      <p class="state-desc">{{ loadError }}</p>
      <button type="button" class="btn btn-ghost btn-sm mt-1" :disabled="loading" @click="load">
        <RefreshCw :size="14" />
        <span>{{ t('common.retry') }}</span>
      </button>
    </div>

    <template v-else>
      <!-- ══ 灾备状态带 ══ -->
      <section class="card band">
        <template v-if="loading && !simple">
          <BaseLoadingAnnounce />
          <div v-for="i in 4" :key="i" class="fact">
            <div class="skeleton skeleton-text" style="width: 48%" />
            <div class="skeleton skeleton-text skeleton-value" style="width: 62%" />
            <div class="skeleton skeleton-text" style="width: 36%" />
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

      <template v-if="simple">
        <!-- ══ 灾备配置 ══ -->
        <section class="card">
          <header class="card-head">
            <div>
              <h2 class="card-title"><HardDrive :size="14" />{{ t('admin.backup.configTitle') }}</h2>
              <p class="card-sub">{{ t('admin.backup.autoBackup') }}</p>
            </div>
            <div class="bk-switch">
              <span class="bk-switch-text" :class="enabled ? 'is-on' : ''">
                {{ enabled ? t('admin.backup.enabledOn') : t('admin.backup.enabledOff') }}
              </span>
              <BaseSwitch v-model="enabled" :disabled="!auth.isSuperadmin" :label="t('admin.backup.configTitle')" />
            </div>
          </header>

          <div v-if="simple.legacy_bypy" class="bk-legacy">
            <AlertTriangle :size="13" />
            <span>{{ simple.migration_note }}</span>
          </div>

          <div class="bk-fields">
            <label class="field-stack">
              <span class="form-label">{{ t('admin.backup.secContent') }}</span>
              <select disabled class="field bk-readonly" :aria-label="t('admin.backup.secContent')">
                <option>{{ t('admin.backup.scopeValue') }}</option>
              </select>
            </label>

            <label class="field-stack">
              <span class="form-label">{{ t('admin.backup.secLocation') }}</span>
              <select v-model="destination" :disabled="!auth.isSuperadmin" class="field" :aria-label="t('admin.backup.secLocation')">
                <option value="local">{{ t('admin.backup.destLocal') }}</option>
                <option value="s3">{{ t('admin.backup.destS3') }}</option>
                <option value="oss">{{ t('admin.backup.destOss') }}</option>
                <option value="webdav">{{ t('admin.backup.destWebdav') }}</option>
                <option value="baidu_oauth">{{ t('admin.backup.destBaidu') }}</option>
              </select>
            </label>

            <label class="field-stack">
              <span class="form-label">{{ t('admin.backup.secSchedule') }}</span>
              <input v-model="scheduleTime" type="time" :disabled="!auth.isSuperadmin" class="field num" />
            </label>

            <label class="field-stack">
              <span class="form-label">
                {{ t('admin.backup.secRetention') }}{{ destination === 'local' ? t('admin.backup.retentionLocal') : '' }}
              </span>
              <input v-model="retention" type="number" inputmode="numeric" min="1" max="365" :disabled="!auth.isSuperadmin" class="field num" />
            </label>
          </div>

          <!-- 远端凭据 -->
          <div v-if="remoteDest" class="bk-creds">
            <div class="bk-creds-head">
              <span class="label-caps">{{ t('admin.backup.connInfo') }}</span>
            </div>
            <div class="bk-creds-grid">
              <label v-if="destination !== 'baidu_oauth'" class="field-stack">
                <span class="form-label">Endpoint</span>
                <input
                  v-model="endpoint"
                  :disabled="!auth.isSuperadmin"
                  placeholder="https://s3.us-west-004.backblazeb2.com"
                  class="field mono"
                />
              </label>
              <label v-if="needsBucket" class="field-stack">
                <span class="form-label">Bucket</span>
                <input v-model="bucket" :disabled="!auth.isSuperadmin" class="field mono" />
              </label>
              <label v-for="f in credentialFields" :key="f" class="field-stack">
                <span class="form-label mono">{{ f }}</span>
                <input
                  v-model="credentials[f]"
                  type="password"
                  :disabled="!auth.isSuperadmin"
                  :placeholder="simple.configured ? t('admin.backup.keepExisting') : ''"
                  class="field"
                />
              </label>
            </div>
          </div>

          <footer class="bk-foot">
            <template v-if="auth.isSuperadmin">
              <button type="button" class="btn btn-ghost btn-sm" :disabled="busy !== ''" @click="testConnection">
                <Loader2 v-if="busy === 'test'" :size="13" class="animate-spin shrink-0" />
                <PlugZap v-else :size="13" />
                <span>{{ busy === 'test' ? t('admin.backup.testing') : t('admin.backup.testConnection') }}</span>
              </button>
              <button type="button" class="btn btn-primary btn-sm" :disabled="busy !== ''" @click="save">
                <Loader2 v-if="busy === 'save'" :size="13" class="animate-spin shrink-0" />
                <Save v-else :size="13" />
                <span>{{ busy === 'save' ? t('admin.backup.saving') : t('admin.backup.saveBackup') }}</span>
              </button>
              <button type="button" class="btn btn-danger btn-sm" :disabled="busy !== ''" @click="runNow">
                <Loader2 v-if="busy === 'run'" :size="13" class="animate-spin shrink-0" />
                <PlayCircle v-else :size="13" />
                <span>{{ busy === 'run' ? t('admin.backup.running') : t('admin.backup.backupNow') }}</span>
              </button>

              <!-- Hidden file input for upload -->
              <input ref="uploadFileInput" type="file" accept=".tar.gz,.tgz" class="hidden" @change="onFileSelected" />
              <button type="button" class="btn btn-ghost btn-sm" :disabled="busy !== ''" @click="triggerUpload">
                <Loader2 v-if="busy === 'upload'" :size="13" class="animate-spin shrink-0" />
                <Upload v-else :size="13" />
                <span>{{ busy === 'upload' ? t('admin.backup.uploading') : t('admin.backup.uploadPackage') }}</span>
              </button>
            </template>
            <span v-else class="bk-readonly-note">{{ t('admin.backup.readonly') }}</span>
          </footer>
        </section>

        <div class="bk-grid">
          <!-- ══ 最近一次 ══ -->
          <section class="card">
            <header class="card-head">
              <h2 class="card-title"><Clock :size="14" />{{ t('admin.backup.latestRun') }}</h2>
            </header>

            <BaseEmpty v-if="!simple.latest" :text="t('admin.backup.noLatest')" />

            <div v-else class="bk-kv">
              <div class="kv-row">
                <span class="bk-kv-k">{{ t('admin.backup.time') }}</span>
                <span class="bk-kv-v mono num">{{ fmtBackupTime(simple.latest) }}</span>
              </div>
              <div class="kv-row">
                <span class="bk-kv-k">{{ t('admin.backup.status') }}</span>
                <span class="badge" :class="simple.latest.status === 'failed' ? 'badge-down' : 'badge-up'" :title="simple.latest.status">
                  {{ statusLabelOf(simple.latest.status) }}
                </span>
              </div>
            </div>

            <p v-if="status?.schedule" class="bk-schedule">
              <CalendarClock :size="12" />
              <span>{{ status.schedule }}</span>
            </p>
          </section>

          <!-- ══ 归档清单 ══ -->
          <section class="card">
            <header class="card-head">
              <h2 class="card-title"><Archive :size="14" />{{ t('admin.backup.archiveList') }}</h2>
              <span class="badge mono">{{ archives.length }}</span>
            </header>

            <BaseEmpty v-if="!archives.length" :text="t('admin.backup.emptyArchives')" />

            <div v-else class="bk-rows">
              <article v-for="a in archives" :key="a.name" class="bk-row">
                <span class="icon-box"><Archive :size="14" /></span>

                <div class="bk-archive-main">
                  <span class="bk-archive-name mono truncate" :title="a.name">{{ a.name.split('/').pop() || a.name }}</span>
                  <span class="bk-archive-meta mono num">{{ fmtBytes(a.bytes) }} · {{ fmtTime(a.mtime) }}</span>
                </div>

                <div class="bk-archive-actions">
                  <button type="button"
                    class="btn btn-ghost btn-sm"
                    :disabled="downloadingArchive === (a.name.split('/').pop() || a.name)"
                    :title="t('admin.backup.downloadTitle')"
                    @click="downloadArchive(a.name)"
                  >
                    <Loader2 v-if="downloadingArchive === (a.name.split('/').pop() || a.name)" :size="13" class="animate-spin shrink-0" />
                    <Download v-else :size="13" />
                    <span>{{ t('admin.backup.downloadTitle') }}</span>
                  </button>
                  <button type="button"
                    v-if="auth.isSuperadmin"
                    class="btn btn-quiet btn-sm is-danger"
                    :disabled="busy === 'restore'"
                    :title="t('admin.backup.restoreTitle')"
                    @click="restoreArchive(a.name)"
                  >
                    <RotateCcw :size="13" />
                  </button>
                </div>
              </article>
            </div>

            <p class="bk-hint">{{ t('admin.backup.archiveHint') }}</p>
          </section>
        </div>
      </template>
    </template>
  </div>
</template>

<style scoped>
.bk {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}

/* ══ 状态带 ══ */











/* ══ 配置 ══ */
.bk-switch {
  display: flex;
  align-items: center;
  gap: 8px;
}
.bk-switch-text {
  font-size: var(--text-3xs);
  font-weight: 600;
  color: var(--ds-color-text-placeholder);
}
.bk-switch-text.is-on {
  color: var(--up);
}
.bk-legacy {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding:10px var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
  background-color: var(--warn-bg);
  color: var(--warn);
  font-size: var(--text-3xs);
  line-height: var(--leading-body);
}
.bk-legacy > svg {
  flex-shrink: 0;
  margin-top: 2px;
}

.bk-fields {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-4);
  padding: var(--ds-space-4);
}
@media (min-width: 700px) {
  .bk-fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (min-width: 1200px) {
  .bk-fields {
    grid-template-columns: repeat(4, minmax(0, 1fr));
  }
}

.bk-readonly {
  opacity: 0.7;
  cursor: not-allowed;
}

.bk-creds {
  padding: 0 var(--ds-space-4) var(--ds-space-4);
}
.bk-creds-head {
  padding-bottom: var(--ds-space-3);
}
.bk-creds-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3);
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
}
@media (min-width: 700px) {
  .bk-creds-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.bk-foot {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface-inset);
}
.bk-readonly-note {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
}

/* ══ 双栏 ══ */
.bk-grid {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-4);
  align-items: start;
}
@media (min-width: 1000px) {
  .bk-grid {
    grid-template-columns: minmax(0, 0.85fr) minmax(0, 1.15fr);
  }
}

.bk-kv {
  display: flex;
  flex-direction: column;
}
.bk-kv-k {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.bk-kv-v {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-primary);
}
.bk-schedule {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  font-size: var(--text-4xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-placeholder);
}
.bk-schedule > svg {
  flex-shrink: 0;
  margin-top: 2px;
}

/* ══ 归档清单 ══ */
.bk-rows {
  display: flex;
  flex-direction: column;
}
.bk-row {
  display: grid;
  grid-template-columns: 26px minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--ds-space-3);
  padding: 10px var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
  transition: background-color var(--dur-fast);
}
.bk-row:last-child {
  border-bottom: 0;
}
.bk-row:hover {
  background-color: var(--ds-color-bg-hover);
}
.bk-archive-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.bk-archive-name {
  font-size: var(--text-3xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
  min-width: 0;
}
.bk-archive-meta {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.bk-archive-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-shrink: 0;
}
.bk-hint {
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}

@media (max-width: 760px) {
  .bk-row {
    grid-template-columns: 26px minmax(0, 1fr);
  }
  .bk-archive-actions {
    grid-column: 2;
    justify-content: flex-end;
  }
}
</style>
