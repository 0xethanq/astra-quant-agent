<script setup lang="ts">
/**
 * SecurityPage.vue · OKX 专向账户与标的配置工位
 * ---------------------------------------------------------------------------
 * 架构：
 *   PageHeader（环境标识与当前委托执行模式）
 *   → 顶部指标概览带（OKX V5 接入 / 活跃标的池 / 订单模式 / 初始本金基线）
 *   → 纯净三页签导航：
 *     1. venues：OKX 账户与配置（统一资金环境 + API 凭证管理 + 委托订单模式 + 行情健康 + 策略广场）
 *     2. pool：交易标的池（初始本金基线 + 在管 USDT 永续合约池与安全移出）
 *     3. emergency：应急风控与持仓（手动平仓总闸 + 实时持仓挂单快照 + 安全平仓双确认弹窗）
 *
 * 后端契约：
 *   GET  /api/v1/admin/config · /api/v1/admin/okx/runtime?refresh=1 · /api/v1/admin/instruments
 *   GET  /api/v1/admin/multi-exchange · /api/v1/admin/okx/account-snapshot · /api/v1/referral-channels
 *   PUT  /api/v1/admin/config · /api/v1/admin/account-baseline · /api/v1/admin/multi-exchange
 *   POST /api/v1/admin/instruments · /api/v1/admin/multi-exchange/test-connection
 *        /api/v1/admin/positions/close
 *   DELETE /api/v1/admin/instruments/{instId}
 *
 * ⚠️ 高风险门禁严格保留：
 *    - 切 LIVE 需逐字确认 `LIVE`；
 *    - 改本金需超级管理员 + 逐字短语 `UPDATE CAPITAL`；
 *    - 删标的需逐字短语 `REMOVE <instId>`；
 *    - 应急平仓需管理员密码 + 90秒动态令牌确认短语 + 防重入闭锁。
 */
import { useToast } from '../../composables/useToast'
import { useConfirm } from '../../composables/useConfirm'
import { ref, computed, onMounted } from 'vue'
import PageHeader from '../../components/admin/PageHeader.vue'
import SettingsSection from '../../components/admin/page-parts/SettingsSection.vue'
import { useI18n } from '../../composables/useI18n'
import { useRovingTabs } from '../../composables/useRovingTabs'
import { useApi } from '../../composables/useApi'
import { useAuthStore } from '../../stores/auth'
import { fmtDateTime } from '../../utils/format'
import {
  deriveOkxLinked, deriveMxHealthChips, okxEnvText as okxEnvTextOf, envBadge,
} from './securityLogic'
import BaseSwitch from '../../components/base/BaseSwitch.vue'
import BaseDialog from '../../components/base/BaseDialog.vue'
import BaseEmpty from '../../components/base/BaseEmpty.vue'
import {
  Save, RefreshCw, Layers, Trash2, Zap, ShieldCheck, KeyRound,
  Wallet, Activity, AlertTriangle, Loader2, Radar, Share2, Copy, Eye,
} from 'lucide-vue-next'
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue'

const toast = useToast()
const { ask } = useConfirm()
const { api } = useApi()
const auth = useAuthStore()
const { t } = useI18n()

const config = ref<any>(null)
const runtime = ref<any>(null)
const channels = ref<any[]>([])
const channelOf = (key: string) => channels.value.find((c) => c.key === key) || null

async function loadChannels() {
  try {
    const res = await api<any>('/api/v1/referral-channels')
    channels.value = Array.isArray(res?.channels) ? res.channels : []
  } catch {
    channels.value = []
  }
}

const loading = ref(true)
const loadError = ref('')

type TabKey = 'venues' | 'pool' | 'emergency'
const activeTab = ref<TabKey>('venues')
const positionsLoadedOnce = ref(false)

const TABS = computed<Array<{ key: TabKey; label: string; icon: any }>>(() => [
  { key: 'venues', label: t('admin.security.tabVenues'), icon: KeyRound },
  { key: 'pool', label: t('admin.security.tabPool'), icon: Layers },
  { key: 'emergency', label: t('admin.security.tabEmergency'), icon: Zap },
])

const { setRef: setSecTabRef, onKeydown: onSecTabKey, roving: secTabRoving } = useRovingTabs(
  () => TABS.value.length,
  (i) => { switchTab(TABS.value[i].key) },
)

function switchTab(tab: TabKey) {
  activeTab.value = tab
  if (tab === 'emergency' && !positionsLoadedOnce.value) {
    positionsLoadedOnce.value = true
    loadPositions()
  }
}

function openExternal(url: string) {
  window.open(url, '_blank', 'noopener,noreferrer')
}

// ---- LIVE / DEMO API keys (OKX) ----
const keys = ref({ live_key: '', live_secret: '', live_pass: '', demo_key: '', demo_secret: '', demo_pass: '' })

// ---- capital ----
const newCapital = ref<string>('')
const capitalConfirm = ref<string>('')
const savingCapital = ref(false)
const capitalAmountOk = computed(() => {
  const n = Number(newCapital.value)
  return !Number.isNaN(n) && n > 0
})
const capitalConfirmOk = computed(() => capitalConfirm.value.trim().toUpperCase() === 'UPDATE CAPITAL')

// ---- instruments ----
const instruments = ref<any[]>([])
const instLimits = ref<any>({ minimum: 1, maximum: 20 })
const newInstId = ref('')

// ---- positions & close ----
const snapshot = ref<any>(null)
const snapshotState = ref('')
const snapshotError = ref(false)
const manualClose = ref(false)
const closePassword = ref('')
const closeModal = ref<{ show: boolean; pos: any } | null>(null)
const closePhraseInput = ref('')
const closing = ref(false)
const closePhraseOk = computed(() => {
  const pos = closeModal.value?.pos
  if (!pos?.close_confirmation) return false
  return closePhraseInput.value.trim().toUpperCase() === pos.close_confirmation
})
const closeReady = computed(() => {
  return !!closePassword.value && closePhraseOk.value
})

// ---- 交易环境与健康状态 ----
const mx = ref<any>(null)
const okxCredViewLive = ref(false)
const orderMode = ref<'limit' | 'market'>('market')
const savingOrderMode = ref(false)
const venueLatencies = ref<Record<string, number>>({})
const savingOkx = ref(false)
const probingVenue = ref<'' | 'okx'>('')
const savingUnifiedEnv = ref(false)
const isUnifiedLive = computed(() => config.value?.editable?.okx_environment === 'live')

async function requestUnifiedEnvSwitch(targetEnv: 'demo' | 'live') {
  if (savingUnifiedEnv.value) return
  if (targetEnv === (isUnifiedLive.value ? 'live' : 'demo')) return

  if (targetEnv === 'live') {
    const _ok = await ask({
      title: t('admin.security.confirmUnifiedLiveTitle'),
      desc: t('admin.security.confirmUnifiedLiveDesc'),
      detail: t('admin.security.confirmUnifiedLiveDetail'),
      danger: true,
      confirmPhrase: 'LIVE',
      okText: t('common.switchLive'),
    })
    if (!_ok) {
      toast.warn(t('admin.security.warnNotConfirmed'))
      return
    }
  }

  savingUnifiedEnv.value = true
  try {
    await api('/api/v1/admin/multi-exchange', {
      method: 'PUT',
      body: JSON.stringify({
        okx_environment: targetEnv,
      }),
    })
    await api('/api/v1/admin/config', {
      method: 'PUT',
      body: JSON.stringify({
        okx_environment: targetEnv,
      }),
    })
    if (config.value?.editable) {
      config.value.editable.okx_environment = targetEnv
    }
    okxCredViewLive.value = (targetEnv === 'live')
    toast.ok(t('admin.security.toastUnifiedEnvSaved', undefined, { env: targetEnv.toUpperCase() }))
    await Promise.all([loadAll(), loadMx()])
  } catch (e: any) {
    toast.err(t('admin.security.errSaveFailed', undefined, { msg: e.message }))
  } finally {
    savingUnifiedEnv.value = false
  }
}

async function loadAll() {
  loading.value = true
  loadError.value = ''
  try {
    const [cfg, rt] = await Promise.all([
      api('/api/v1/admin/config'),
      api('/api/v1/admin/okx/runtime?refresh=1').catch(() => null),
    ])
    config.value = cfg
    applyRuntime(rt)
    if (cfg?.editable?.okx_environment) {
      okxCredViewLive.value = (cfg.editable.okx_environment === 'live')
    }
    if (cfg?.editable?.order_mode) {
      orderMode.value = (cfg.editable.order_mode === 'limit' ? 'limit' : 'market')
    } else {
      orderMode.value = 'market'
    }
    newCapital.value = String(cfg.editable?.initial_capital ?? '')
    manualClose.value = !!cfg.editable?.manual_close_enabled
    const inst = await api('/api/v1/admin/instruments')
    instruments.value = inst.instruments || []
    instLimits.value = inst.limits || instLimits.value
  } catch (e: any) {
    loadError.value = String(e?.message || e)
    toast.err(t('admin.security.errLoadFailed', undefined, { msg: e.message }))
  } finally {
    loading.value = false
  }
}

function applyRuntime(rt: any) {
  runtime.value = rt
}

async function saveEnvironment() {
  const environment = config.value.editable.okx_environment
  savingOkx.value = true
  try {
    const body: any = { okx_environment: environment }
    if (keys.value.live_key) body.okx_live_api_key = keys.value.live_key
    if (keys.value.live_secret) body.okx_live_secret_key = keys.value.live_secret
    if (keys.value.live_pass) body.okx_live_passphrase = keys.value.live_pass
    if (keys.value.demo_key) body.okx_demo_api_key = keys.value.demo_key
    if (keys.value.demo_secret) body.okx_demo_secret_key = keys.value.demo_secret
    if (keys.value.demo_pass) body.okx_demo_passphrase = keys.value.demo_pass
    await api('/api/v1/admin/config', { method: 'PUT', body: JSON.stringify(body) })
    keys.value = { live_key: '', live_secret: '', live_pass: '', demo_key: '', demo_secret: '', demo_pass: '' }
    toast.ok(t('admin.security.toastOkxCredsSaved'))
    await loadAll()
  } catch (e: any) {
    toast.err(t('admin.security.errSaveFailed', undefined, { msg: e.message }))
  } finally {
    savingOkx.value = false
  }
}

async function saveManualClose() {
  try {
    const d = await api('/api/v1/admin/config', { method: 'PUT', body: JSON.stringify({ manual_close_enabled: manualClose.value }) })
    manualClose.value = !!(d?.editable?.manual_close_enabled ?? d?.manual_close_enabled)
    if (manualClose.value) toast.warn(t('admin.security.toastManualCloseOn')); else toast.ok(t('admin.security.toastManualCloseOff'))
  } catch (e: any) {
    toast.err(e.message)
  }
}

async function saveOrderMode() {
  savingOrderMode.value = true
  try {
    await api('/api/v1/admin/config', {
      method: 'PUT',
      body: JSON.stringify({ order_mode: orderMode.value })
    })
    toast.ok(t('admin.security.toastOrderModeSaved'))
    await loadAll()
  } catch (e: any) {
    toast.err(t('admin.security.errSaveFailed', undefined, { msg: e.message }))
  } finally {
    savingOrderMode.value = false
  }
}

async function saveCapital() {
  if (!auth.isSuperadmin) { toast.err(t('admin.security.errSuperadminOnly')); return }
  if (capitalConfirm.value.trim().toUpperCase() !== 'UPDATE CAPITAL') { toast.err(t('admin.security.errPhraseCapital')); return }
  savingCapital.value = true
  try {
    const res = await api('/api/v1/admin/account-baseline', { method: 'PUT', body: JSON.stringify({ initial_capital: parseFloat(newCapital.value), confirmation: capitalConfirm.value }) })
    toast.ok(res.effect || t('admin.security.toastCapitalSet', undefined, { n: res.initial_capital }))
    capitalConfirm.value = ''
    await loadAll()
  } catch (e: any) {
    toast.err(t('admin.security.errUpdateFailed', undefined, { msg: e.message }))
  } finally {
    savingCapital.value = false
  }
}

async function addInstrument() {
  let instId = newInstId.value.trim().toUpperCase()
  if (/^[A-Z0-9]{2,15}$/.test(instId)) {
    instId = `${instId}-USDT-SWAP`
  }
  if (!/^[A-Z0-9]{2,15}-USDT-SWAP$/.test(instId)) { toast.err(t('admin.security.errInstFormat')); return }
  try {
    const res = await api('/api/v1/admin/instruments', { method: 'POST', body: JSON.stringify({ inst_id: instId }) })
    toast.ok(res.message || t('admin.security.toastInstAdded', undefined, { inst: instId }))
    newInstId.value = ''
    await loadAll()
  } catch (e: any) {
    toast.err(t('admin.security.errAddFailed', undefined, { msg: e.message }))
  }
}

async function removeInstrument(item: any) {
  if (item.protected) { toast.warn(t('admin.security.warnProtectedInst')); return }
  if (item.held_live || item.has_tracker) {
    toast.warn(t('admin.security.warnHeldInst', undefined, { venues: (item.held_venues || []).join('/') || t('admin.security.trackedRecord') }))
    return
  }
  if (item.holdings_unknown) { toast.warn(t('admin.security.warnHoldingsUnknown')); return }
  const _ok = await ask({
    title: t('admin.security.confirmRemoveInstTitle'),
    desc: t('admin.security.confirmRemoveInstDesc', undefined, { inst: item.instId }),
    danger: true,
    confirmPhrase: `REMOVE ${item.instId}`,
    okText: t('common.remove'),
  })
  if (!_ok) return
  try {
    const res = await api(`/api/v1/admin/instruments/${encodeURIComponent(item.instId)}`, {
      method: 'DELETE',
      body: JSON.stringify({ confirmation: `REMOVE ${item.instId}` })
    })
    toast.ok(res.message || t('admin.security.toastInstRemoved', undefined, { inst: item.instId }))
    await loadAll()
  } catch (e: any) {
    toast.err(t('admin.security.errDeleteFailed', undefined, { msg: e.message }))
  }
}

async function loadPositions() {
  snapshotState.value = t('admin.security.loadingPositions')
  snapshotError.value = false
  try {
    const d = await api('/api/v1/admin/okx/account-snapshot')
    snapshot.value = d
    snapshotState.value = ''
  } catch (e: any) {
    snapshotState.value = e.message
    snapshotError.value = true
    snapshot.value = null
  }
}

function openClose(pos: any) {
  if (!manualClose.value) { toast.err(t('admin.security.errEnableManualFirst')); return }
  closePhraseInput.value = ''
  closeModal.value = { show: true, pos }
}

async function confirmClose() {
  if (closing.value) return
  const pos = closeModal.value?.pos
  if (!pos) return
  if (!closePassword.value) { toast.err(t('admin.security.errNeedPassword')); return }
  if (!pos.close_token || !pos.close_confirmation) { toast.err(t('admin.security.errCloseTokenMissing')); return }
  if (closePhraseInput.value.trim().toUpperCase() !== pos.close_confirmation) {
    toast.err(t('admin.security.errPhraseClose', undefined, { phrase: pos.close_confirmation }))
    return
  }
  closing.value = true
  try {
    const d = await api('/api/v1/admin/positions/close', {
      method: 'POST',
      body: JSON.stringify({ close_token: pos.close_token, admin_password: closePassword.value, confirmation: closePhraseInput.value.trim().toUpperCase(), venue: pos.venue || 'okx' }),
    })
    toast.ok(t('admin.security.toastCloseConfirmed', undefined, { inst: d.instId, size: d.closed_size }))
    closeModal.value = null
    closePassword.value = ''
    await loadPositions()
  } catch (e: any) {
    toast.err(t('admin.security.errCloseFailed', undefined, { msg: e.message }))
    await loadPositions()
    const fresh = (snapshot.value?.positions || []).find((x: any) => x.instId === pos.instId && (x.posSide || 'net') === (pos.posSide || 'net') && (x.venue || 'okx') === (pos.venue || 'okx'))
    if (fresh) closeModal.value = { show: true, pos: fresh }
    else { closeModal.value = null; closePassword.value = '' }
  } finally {
    closing.value = false
  }
}

async function loadMx(preserveVenue?: string) {
  try {
    mx.value = await api('/api/v1/admin/multi-exchange')
    if (mx.value?.health?.venues) {
      for (const [k, v] of Object.entries(mx.value.health.venues as Record<string, any>)) {
        if (v?.avg_ms && (!preserveVenue || k !== preserveVenue || !venueLatencies.value[k])) {
          venueLatencies.value[k] = v.avg_ms
        }
      }
    }
  } catch {
    mx.value = null
  }
}

async function probeVenue(venue: 'okx') {
  probingVenue.value = venue
  try {
    const isDemo = config.value?.editable?.okx_environment === 'demo'
    const env = isDemo ? 'demo' : 'live'

    const payload: Record<string, any> = {
      venue,
      environment: env,
    }

    if (isDemo) {
      if (keys.value.demo_key.trim()) payload.api_key = keys.value.demo_key.trim()
      if (keys.value.demo_secret.trim()) payload.secret_key = keys.value.demo_secret.trim()
      if (keys.value.demo_pass.trim()) payload.passphrase = keys.value.demo_pass.trim()
    } else {
      if (keys.value.live_key.trim()) payload.api_key = keys.value.live_key.trim()
      if (keys.value.live_secret.trim()) payload.secret_key = keys.value.live_secret.trim()
      if (keys.value.live_pass.trim()) payload.passphrase = keys.value.live_pass.trim()
    }

    const res: any = await api('/api/v1/admin/multi-exchange/test-connection', {
      method: 'POST',
      body: JSON.stringify(payload),
    })

    if (res?.latency_ms) {
      venueLatencies.value[venue] = res.latency_ms
    }

    if (res?.ok) {
      toast.ok(res.message || t('admin.security.toastProbeOk', undefined, { venue: venue.toUpperCase() }))
    } else {
      toast.err(res?.message || t('admin.security.toastProbeFail', undefined, { venue: venue.toUpperCase() }))
    }
    await loadMx(venue)
  } catch (e: any) {
    toast.err(t('admin.security.errProbeFailed', undefined, { msg: e.message }))
  } finally {
    probingVenue.value = ''
  }
}

// ---- 总览派生（单测契约：必须调用并依赖 securityLogic.ts） ----
const okxLinked = computed(() => deriveOkxLinked(runtime.value))
const mxHealthChips = computed(() => deriveMxHealthChips(mx.value))
const okxEnvText = computed(() => okxEnvTextOf(config.value?.editable?.okx_environment, t))

const healthAllOk = computed(() => {
  const chips = mxHealthChips.value || []
  return chips.length > 0 && chips.every((h: any) => h.ok === h.total)
})

// ---- 顶部概览四元指标带 ----
const bandFacts = computed(() => {
  return [
    {
      icon: ShieldCheck,
      label: t('admin.security.okxApi'),
      value: okxLinked.value ? t('admin.security.okxReady') : t('admin.security.okxNotReady'),
      foot: envBadge(runtime.value?.environment),
      tone: okxLinked.value ? 'is-up' : 'is-down',
    },
    {
      icon: Layers,
      label: t('admin.security.activePool'),
      value: t('admin.security.poolCount', undefined, { count: instruments.value.length, max: instLimits.value.maximum }),
      foot: t('admin.security.usdtPerp'),
      tone: '',
    },
    {
      icon: Zap,
      label: t('admin.security.orderModeTitle'),
      value: orderMode.value === 'market' ? t('admin.security.optMarket') : t('admin.security.optLimit'),
      foot: orderMode.value === 'market' ? 'Taker · 即时吃单' : 'Maker · 挂单等待',
      tone: '',
    },
    {
      icon: Wallet,
      label: t('admin.security.capitalTitle'),
      value: `${config.value?.editable?.initial_capital ?? '--'} USDT`,
      foot: '绩效统计基准',
      tone: '',
    },
  ]
})

// ---- Strategy Plaza Sharing ----
const plazaSettings = ref({
  enabled: false,
  nickname: '0xEthan',
  show_performance: true,
  show_balance: false,
  show_model: true,
  show_strategy_params: true,
  plaza_hub_url: 'https://hub.astraquant.tech',
})
const plazaIsLive = ref(false)
const loadingPlaza = ref(false)
const savingPlaza = ref(false)
const showPlazaPreview = ref(false)
const plazaPreviewData = ref<any>(null)
const loadingPlazaPreview = ref(false)

const plazaPublicUrl = computed(() => {
  if (typeof window !== 'undefined' && window.location) {
    return `${window.location.origin}/api/v1/public/plaza/profile`
  }
  return '/api/v1/public/plaza/profile'
})

async function loadPlazaSettings() {
  loadingPlaza.value = true
  try {
    const res = await api<any>('/api/v1/admin/plaza/settings')
    if (res?.settings) {
      plazaSettings.value = { ...plazaSettings.value, ...res.settings }
    }
    plazaIsLive.value = Boolean(res?.is_live)
  } catch {
    // Keep defaults
  } finally {
    loadingPlaza.value = false
  }
}

async function savePlazaSettings() {
  if (!isUnifiedLive.value) {
    toast.warn(t('admin.security.plazaLiveOnlyAlert'))
    return
  }
  savingPlaza.value = true
  try {
    await api('/api/v1/admin/plaza/settings', {
      method: 'PUT',
      body: JSON.stringify(plazaSettings.value),
    })
    toast.ok(t('admin.security.toastPlazaSaved'))
    await loadPlazaSettings()
  } catch (err: any) {
    toast.err(t('admin.security.errSaveFailed', undefined, { msg: err.message || 'Error' }))
  } finally {
    savingPlaza.value = false
  }
}

function copyPlazaUrl() {
  navigator.clipboard.writeText(plazaPublicUrl.value)
  toast.ok(t('admin.security.toastPlazaCopied'))
}

async function openPlazaPreview() {
  showPlazaPreview.value = true
  loadingPlazaPreview.value = true
  try {
    const res = await api<any>('/api/v1/public/plaza/profile')
    plazaPreviewData.value = res
  } catch (err: any) {
    plazaPreviewData.value = null
  } finally {
    loadingPlazaPreview.value = false
  }
}

function copyStrategyCloneData() {
  if (!plazaPreviewData.value?.strategy_clone_payload) return
  navigator.clipboard.writeText(JSON.stringify(plazaPreviewData.value.strategy_clone_payload, null, 2))
  toast.ok(t('admin.security.plazaCloneSuccess'))
}

onMounted(() => {
  loadAll()
  loadMx()
  loadChannels()
  loadPlazaSettings()
})
</script>

<template>
  <div class="sc">
    <PageHeader :title="t('nav.admin.security')" :description="t('admin.security.desc')">
      <template #actions>
        <span class="badge mono" :class="isUnifiedLive ? 'badge-warn' : 'badge-accent'">
          {{ isUnifiedLive ? t('admin.security.envLive') : t('admin.security.optDemo') }}
        </span>
        <span class="badge badge-accent mono">
          {{ orderMode === 'market' ? t('admin.security.optMarket') : t('admin.security.optLimit') }}
        </span>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="loading" @click="loadAll">
          <Loader2 v-if="loading && config" :size="14" class="animate-spin shrink-0" />
          <RefreshCw v-else :size="14" />
          <span>{{ t('common.refresh') }}</span>
        </button>
      </template>
    </PageHeader>

    <!-- 首屏骨架 -->
    <div v-if="loading && !config" class="sc-skel">
      <BaseLoadingAnnounce />
      <div v-for="i in 6" :key="i" class="skeleton skeleton-row" />
    </div>

    <!-- 加载失败 -->
    <div v-else-if="loadError && !config" role="alert" class="state-block is-error">
      <span class="state-icon"><AlertTriangle :size="17" /></span>
      <p class="state-title">{{ t('common.loadFailed') }}</p>
      <p class="state-desc">{{ loadError }}</p>
      <button type="button" class="btn btn-ghost btn-sm mt-1" :disabled="loading" @click="loadAll">
        <RefreshCw :size="14" />
        <span>{{ t('common.retry') }}</span>
      </button>
    </div>

    <template v-else-if="config">
      <!-- ══ 顶部概览指标带 ══ -->
      <section class="card band">
        <div v-for="f in bandFacts" :key="f.label" class="fact">
          <span class="fact-label"><component :is="f.icon" :size="12" />{{ f.label }}</span>
          <span class="fact-value" :class="f.tone">{{ f.value }}</span>
          <span class="fact-foot mono">{{ f.foot }}</span>
        </div>
      </section>

      <!-- ══ 页签导航 ══ -->
      <div class="seg seg-lg sc-tabs" role="tablist" :aria-label="t('admin.security.tabsLabel')">
        <button
          v-for="(tab, ti) in TABS"
          :key="tab.key"
          :ref="setSecTabRef(ti)"
          type="button"
          role="tab"
          :aria-selected="activeTab === tab.key"
          :tabindex="secTabRoving(activeTab === tab.key)"
          :class="{ 'seg-on': activeTab === tab.key }"
          @click="switchTab(tab.key)"
          @keydown="onSecTabKey($event, ti)"
        >
          <component :is="tab.icon" :size="13" aria-hidden="true" />
          <span>{{ tab.label }}</span>
        </button>
      </div>

      <!-- ══════════ 页签 1：交易所账户 ══════════ -->
      <template v-if="activeTab === 'venues'">
        <!-- 全局统一交易环境一键切换 -->
        <SettingsSection :title="t('admin.security.unifiedEnvTitle')" :description="t('admin.security.unifiedEnvDesc')" :icon="ShieldCheck">
          <template #actions>
            <span class="badge mono" :class="isUnifiedLive ? 'badge-warn' : 'badge-accent'">
              {{ isUnifiedLive ? t('admin.security.envLive') : t('admin.security.optDemo') }}
            </span>
          </template>

          <div class="sc-group">
            <span class="form-label">{{ t('admin.security.unifiedEnvLabel') }}</span>
            <div class="seg seg-compact" role="group" :aria-label="t('admin.security.unifiedEnvLabel')">
              <button
                type="button"
                class="disabled:opacity-40 disabled:cursor-not-allowed"
                :aria-pressed="!isUnifiedLive"
                :class="{ 'seg-on': !isUnifiedLive }"
                :disabled="savingUnifiedEnv"
                @click="requestUnifiedEnvSwitch('demo')"
              >
                <Loader2 v-if="savingUnifiedEnv && !isUnifiedLive" :size="12" class="animate-spin shrink-0" />
                <span>{{ t('admin.security.optDemo') }} · {{ t('admin.security.envDemoOkx') }}</span>
              </button>
              <button
                type="button"
                class="disabled:opacity-40 disabled:cursor-not-allowed"
                :aria-pressed="isUnifiedLive"
                :class="{ 'seg-on': isUnifiedLive }"
                :disabled="savingUnifiedEnv"
                @click="requestUnifiedEnvSwitch('live')"
              >
                <Loader2 v-if="savingUnifiedEnv && isUnifiedLive" :size="12" class="animate-spin shrink-0" />
                <span>{{ t('admin.security.optLive') }} · {{ t('admin.security.envLive') }}</span>
              </button>
            </div>
            <p class="sc-hint">
              {{ isUnifiedLive ? t('admin.security.unifiedLiveHint') : t('admin.security.unifiedDemoHint') }}
            </p>
          </div>
        </SettingsSection>

        <!-- 委托订单模式 -->
        <SettingsSection :title="t('admin.security.orderModeTitle')" :description="t('admin.security.orderModeDesc')" :icon="Zap">
          <template #actions>
            <button type="button" class="btn btn-primary btn-sm" :disabled="savingOrderMode" @click="saveOrderMode">
              <Loader2 v-if="savingOrderMode" :size="13" class="animate-spin shrink-0" />
              <Save v-else :size="13" />
              <span>{{ savingOrderMode ? t('admin.security.saving') : t('admin.security.saveOrderMode') }}</span>
            </button>
          </template>

          <div class="sc-group">
            <span class="form-label">{{ t('admin.security.orderModeTitle') }}</span>
            <div class="seg seg-compact" role="group" :aria-label="t('admin.security.orderModeTitle')">
              <button
                type="button"
                :aria-pressed="orderMode === 'limit'"
                :class="{ 'seg-on': orderMode === 'limit' }"
                @click="orderMode = 'limit'"
              >
                <span>{{ t('admin.security.optLimit') }}</span>
              </button>
              <button
                type="button"
                :aria-pressed="orderMode === 'market'"
                :class="{ 'seg-on': orderMode === 'market' }"
                @click="orderMode = 'market'"
              >
                <span>{{ t('admin.security.optMarket') }}</span>
              </button>
            </div>
            <p class="sc-hint">
              {{ orderMode === 'market' ? t('admin.security.orderModeMarketHint') : t('admin.security.orderModeLimitHint') }}
            </p>
          </div>
        </SettingsSection>

        <!-- OKX 接入凭证 -->
        <SettingsSection :title="t('admin.security.credsTitle')" :description="t('admin.security.credsDesc')" :icon="KeyRound">
          <div class="sc-venues">
            <article class="sc-venue-card">
              <header class="sc-venue-head">
                <div class="sc-venue-id">
                  <h3 class="sc-venue-name">{{ t('admin.security.okxName') }}</h3>
                  <span class="sc-venue-api">{{ t('admin.security.okxApiLabel') }}</span>
                </div>
                <span class="badge" :class="okxLinked ? 'badge-up' : 'badge-down'">
                  {{ okxLinked ? t('admin.security.okxReady') : t('admin.security.okxNotReady') }}
                </span>
              </header>

              <div class="kv-row">
                <span class="sc-venue-env-label">{{ t('admin.security.fundEnv') }}</span>
                <span class="sc-venue-env-value mono">{{ okxEnvText }}</span>
              </div>

              <div class="sc-venue-body">
                <div class="field-stack">
                  <span class="form-label">{{ t('admin.security.endpointTier') }}</span>
                  <div class="sc-env-indicator">
                    <span class="badge mono" :class="isUnifiedLive ? 'badge-warn' : 'badge-accent'">
                      {{ isUnifiedLive ? t('admin.security.envLive') : t('admin.security.envDemoOkx') }}
                    </span>
                    <span class="sc-env-hint">{{ t('admin.security.envFollowsUnified') }}</span>
                  </div>
                </div>

                <div class="sc-creds">
                  <div class="sc-creds-header">
                    <span class="form-label">
                      {{ (okxCredViewLive ? t('admin.security.liveTrio') : t('admin.security.demoTrio')) }}
                    </span>
                    <div class="seg seg-compact" role="group" :aria-label="t('admin.security.okxCredViewLabel')">
                      <button
                        type="button"
                        :aria-pressed="!okxCredViewLive"
                        :class="{ 'seg-on': !okxCredViewLive }"
                        @click="okxCredViewLive = false"
                      >
                        <span>{{ t('admin.security.viewDemoCred') }}</span>
                      </button>
                      <button
                        type="button"
                        :aria-pressed="okxCredViewLive"
                        :class="{ 'seg-on': okxCredViewLive }"
                        @click="okxCredViewLive = true"
                      >
                        <span>{{ t('admin.security.viewLiveCred') }}</span>
                      </button>
                    </div>
                  </div>

                  <div v-show="!okxCredViewLive" class="sc-creds-group">
                    <input v-model="keys.demo_key" type="password" :placeholder="t('admin.security.apiKeyKeep')" class="field" :aria-label="t('admin.security.demoKeyAria')" />
                    <input v-model="keys.demo_secret" type="password" :placeholder="t('admin.security.phSecretKey')" class="field" :aria-label="t('admin.security.demoSecretAria')" />
                    <input v-model="keys.demo_pass" type="password" :placeholder="t('admin.security.phPassphrase')" class="field" :aria-label="t('admin.security.demoPassAria')" />
                  </div>
                  <div v-show="okxCredViewLive" class="sc-creds-group">
                    <input v-model="keys.live_key" type="password" :placeholder="t('admin.security.apiKeyKeep')" class="field" :aria-label="t('admin.security.liveKeyAria')" />
                    <input v-model="keys.live_secret" type="password" :placeholder="t('admin.security.phSecretKey')" class="field" :aria-label="t('admin.security.liveSecretAria')" />
                    <input v-model="keys.live_pass" type="password" :placeholder="t('admin.security.phPassphrase')" class="field" :aria-label="t('admin.security.livePassAria')" />
                  </div>
                </div>

                <div v-if="channelOf('okx')" class="sc-channel-box">
                  <button
                    v-if="channelOf('okx')?.invite_url"
                    type="button"
                    class="sc-channel-btn"
                    @click="openExternal(channelOf('okx')!.invite_url)"
                  >
                    <span>{{ t('admin.security.okxRegisterDiscount') }}</span>
                  </button>
                </div>
                <p class="sc-hint"><AlertTriangle :size="11" />{{ t('admin.security.liveConfirmNote') }}</p>
              </div>

              <footer class="sc-venue-foot">
                <span v-if="venueLatencies.okx" class="sc-latency mono num">
                  <Radar :size="12" />
                  <span>{{ venueLatencies.okx }}ms</span>
                </span>
                <div class="sc-venue-actions">
                  <button type="button" class="btn btn-quiet btn-sm" :disabled="probingVenue === 'okx'" @click="probeVenue('okx')">
                    <RefreshCw :size="14" :class="probingVenue === 'okx' ? 'animate-spin shrink-0' : ''" />
                    <span>{{ probingVenue === 'okx' ? t('admin.security.probing') : t('admin.security.detect') }}</span>
                  </button>
                  <button type="button" class="btn btn-primary btn-sm" :disabled="savingOkx" @click="saveEnvironment">
                    <Loader2 v-if="savingOkx" :size="12" class="animate-spin shrink-0" />
                    <Save v-else :size="12" />
                    <span>{{ savingOkx ? t('admin.security.saving') : t('admin.security.saveOkx') }}</span>
                  </button>
                </div>
              </footer>
            </article>
          </div>
        </SettingsSection>

        <!-- OKX 行情健康 -->
        <SettingsSection :title="t('admin.security.healthTitle')" :description="t('admin.security.healthDesc')" :icon="Activity">
          <template #actions>
            <span class="badge" :class="healthAllOk ? 'badge-up' : 'badge-warn'">
              {{ healthAllOk ? t('admin.security.healthOk') : t('admin.security.healthDegraded') }}
            </span>
            <button type="button" class="btn btn-quiet btn-sm" @click="loadMx">
              <RefreshCw :size="14" />
              <span>{{ t('admin.security.recheck') }}</span>
            </button>
          </template>

          <BaseEmpty v-if="!mxHealthChips" :text="t('admin.security.noHealthData')" />

          <div v-else class="sc-health">
            <div
              v-for="h in mxHealthChips"
              :key="h.name"
              class="sc-health-row"
              :class="{ 'is-ok': h.ok === h.total }"
            >
              <span class="sc-health-name">{{ h.name }}</span>
              <span class="sc-health-stat mono num">{{ h.ok }}/{{ h.total }} {{ t('admin.security.coinsUnit') }}</span>
              <span v-if="h.avg_ms" class="sc-health-ms mono num">{{ h.avg_ms }}ms</span>
              <span v-if="h.testnet" class="badge">{{ t('admin.security.sandboxTag') }}</span>
            </div>
          </div>
        </SettingsSection>

        <!-- 策略广场实盘共享 -->
        <SettingsSection :title="t('admin.security.plazaShareTitle')" :description="t('admin.security.plazaShareDesc')" :icon="Share2">
          <template #actions>
            <span class="badge mono" :class="!isUnifiedLive ? 'badge-warn' : plazaSettings.enabled ? 'badge-accent' : ''">
              {{ !isUnifiedLive ? t('admin.security.plazaDemoLocked') : plazaSettings.enabled ? t('admin.security.plazaActive') : t('admin.security.plazaOff') }}
            </span>
          </template>

          <div class="sc-group">
            <p v-if="!isUnifiedLive" class="sc-hint flex items-center gap-1.5 text-amber-400">
              <AlertTriangle :size="13" class="shrink-0" />
              <span>{{ t('admin.security.plazaLiveOnlyAlert') }}</span>
            </p>

            <div class="flex items-center justify-between py-2 border-b border-[var(--border-subtle)]">
              <div>
                <span class="font-medium text-sm text-[var(--text-primary)]">{{ t('admin.security.plazaEnableLabel') }}</span>
                <p class="text-xs text-[var(--text-muted)] mt-0.5">{{ t('admin.security.plazaShareDesc') }}</p>
              </div>
              <BaseSwitch
                v-model="plazaSettings.enabled"
                :disabled="!isUnifiedLive || savingPlaza"
                :label="t('admin.security.plazaEnableLabel')"
              />
            </div>

            <div class="grid grid-cols-1 md:grid-cols-2 gap-4 pt-2">
              <div class="space-y-1">
                <label for="plaza-nickname-input" class="form-label text-xs">{{ t('admin.security.plazaNicknameLabel') }}</label>
                <input
                  id="plaza-nickname-input"
                  v-model="plazaSettings.nickname"
                  type="text"
                  class="field text-xs disabled:opacity-40 disabled:cursor-not-allowed"
                  maxlength="40"
                  :disabled="!isUnifiedLive || savingPlaza"
                  :placeholder="t('admin.security.plazaNicknamePlaceholder')"
                />
              </div>

              <div class="space-y-1">
                <label for="plaza-api-url-input" class="form-label text-xs">{{ t('admin.security.plazaApiUrlLabel') }}</label>
                <div class="flex items-center gap-2">
                  <input
                    id="plaza-api-url-input"
                    type="text"
                    readonly
                    class="field text-xs mono text-[var(--text-muted)] select-all disabled:opacity-40 disabled:cursor-not-allowed"
                    :value="plazaPublicUrl"
                  />
                  <button
                    type="button"
                    class="btn btn-quiet btn-sm shrink-0"
                    :disabled="!plazaSettings.enabled || !isUnifiedLive"
                    @click="copyPlazaUrl"
                  >
                    <Copy :size="12" />
                    <span>{{ t('admin.security.plazaCopyUrl') }}</span>
                  </button>
                </div>
              </div>
            </div>

            <div class="space-y-2 pt-2 border-t border-[var(--border-subtle)]">
              <span class="form-label text-xs">{{ t('admin.security.plazaPrivacyCustom') }}</span>
              <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 text-xs">
                <label class="flex items-center gap-2 cursor-pointer text-[var(--text-secondary)]">
                  <input
                    type="checkbox"
                    v-model="plazaSettings.show_performance"
                    :disabled="!isUnifiedLive || savingPlaza"
                    class="rounded border-[var(--border-base)] text-[var(--color-primary)] disabled:opacity-40 disabled:cursor-not-allowed"
                  />
                  <span>{{ t('admin.security.plazaShowPerf') }}</span>
                </label>

                <label class="flex items-center gap-2 cursor-pointer text-[var(--text-secondary)]">
                  <input
                    type="checkbox"
                    v-model="plazaSettings.show_balance"
                    :disabled="!isUnifiedLive || savingPlaza"
                    class="rounded border-[var(--border-base)] text-[var(--color-primary)] disabled:opacity-40 disabled:cursor-not-allowed"
                  />
                  <span>{{ t('admin.security.plazaShowBalance') }}</span>
                </label>

                <label class="flex items-center gap-2 cursor-pointer text-[var(--text-secondary)]">
                  <input
                    type="checkbox"
                    v-model="plazaSettings.show_model"
                    :disabled="!isUnifiedLive || savingPlaza"
                    class="rounded border-[var(--border-base)] text-[var(--color-primary)] disabled:opacity-40 disabled:cursor-not-allowed"
                  />
                  <span>{{ t('admin.security.plazaShowModel') }}</span>
                </label>

                <label class="flex items-center gap-2 cursor-pointer text-[var(--text-secondary)]">
                  <input
                    type="checkbox"
                    v-model="plazaSettings.show_strategy_params"
                    :disabled="!isUnifiedLive || savingPlaza"
                    class="rounded border-[var(--border-base)] text-[var(--color-primary)] disabled:opacity-40 disabled:cursor-not-allowed"
                  />
                  <span>{{ t('admin.security.plazaShowParams') }}</span>
                </label>
              </div>
            </div>

            <div class="flex items-center justify-between pt-3 border-t border-[var(--border-subtle)]">
              <button
                type="button"
                class="btn btn-ghost btn-sm"
                :disabled="!isUnifiedLive || !plazaSettings.enabled"
                @click="openPlazaPreview"
              >
                <Eye :size="13" />
                <span>{{ t('admin.security.plazaPreviewCard') }}</span>
              </button>

              <button
                type="button"
                class="btn btn-primary btn-sm"
                :disabled="!isUnifiedLive || savingPlaza"
                @click="savePlazaSettings"
              >
                <Loader2 v-if="savingPlaza" :size="13" class="animate-spin shrink-0" />
                <Save v-else :size="13" />
                <span>{{ savingPlaza ? t('admin.security.saving') : t('admin.security.plazaSaveSettings') }}</span>
              </button>
            </div>
          </div>
        </SettingsSection>
      </template>

      <!-- ══════════ 页签 2：标的池与初始本金 ══════════ -->
      <template v-if="activeTab === 'pool'">
        <SettingsSection :title="t('admin.security.capitalTitle')" :description="t('admin.security.capitalDesc')" :icon="Wallet">
          <template #actions>
            <button
              type="button"
              class="btn btn-primary btn-sm"
              :disabled="savingCapital || !auth.isSuperadmin || !capitalAmountOk || !capitalConfirmOk"
              @click="saveCapital"
            >
              <Loader2 v-if="savingCapital" :size="13" class="animate-spin shrink-0" />
              <Save v-else :size="13" />
              <span>{{ savingCapital ? t('admin.security.capitalSaving') : t('admin.security.capitalSave') }}</span>
            </button>
          </template>

          <div class="sc-form-2">
            <label class="field-stack">
              <span class="form-label">{{ t('admin.security.capitalAmount') }}</span>
              <input
                v-model="newCapital"
                type="text"
                class="field num"
                :class="{ 'is-bad': !!newCapital && !capitalAmountOk }"
                :aria-invalid="!!newCapital && !capitalAmountOk ? 'true' : undefined"
                inputmode="decimal"
              />
            </label>
            <label class="field-stack">
              <span class="form-label">{{ t('admin.security.capitalConfirmLabel') }}</span>
              <input
                v-model="capitalConfirm"
                type="text"
                autocomplete="off"
                spellcheck="false"
                class="field mono"
                :class="{ 'is-bad': !!capitalConfirm && !capitalConfirmOk }"
                :aria-invalid="!!capitalConfirm && !capitalConfirmOk ? 'true' : undefined"
                placeholder="UPDATE CAPITAL"
              />
            </label>
          </div>

          <p class="sc-hint pad">{{ t('admin.security.capitalFooter') }}</p>
        </SettingsSection>

        <SettingsSection :title="t('admin.security.poolTitle')" :description="t('admin.security.poolDesc')" :icon="Layers">
          <template #actions>
            <input
              v-model="newInstId"
              :aria-label="t('admin.security.instAria')"
              :placeholder="t('admin.security.instPlaceholder')"
              class="field mono sc-inst-input"
              @keyup.enter="addInstrument"
            />
            <button type="button" class="btn btn-primary btn-sm" @click="addInstrument">
              <Layers :size="13" />
              <span>{{ t('admin.security.addInstrument') }}</span>
            </button>
          </template>

          <BaseEmpty v-if="!instruments.length" :text="t('admin.security.poolEmpty')" />

          <div v-else class="sc-rows">
            <div class="sc-row sc-row-head">
              <span>{{ t('admin.security.colInstId') }}</span>
              <span>{{ t('admin.security.colName') }}</span>
              <span>{{ t('admin.security.colType') }}</span>
              <span>{{ t('admin.security.colRisk') }}</span>
              <span />
            </div>

            <article v-for="item in instruments" :key="item.instId" class="sc-row">
              <span class="sc-inst mono num">{{ item.instId }}</span>
              <span class="sc-name truncate">{{ item.name }}</span>
              <span class="sc-type mono">{{ item.ctType || 'SWAP' }}</span>
              <span class="sc-badges">
                <span v-if="item.protected" class="badge badge-warn">{{ t('admin.security.protectedBadge') }}</span>
                <span v-else-if="item.held_live" class="badge badge-accent">
                  {{ t('admin.security.holdingLiveBadge', undefined, { venues: (item.held_venues || []).join('/') || '—' }) }}
                </span>
                <span v-else-if="item.has_tracker" class="badge badge-accent">{{ t('admin.security.holdingBadge') }}</span>
                <span
                  v-else-if="item.holdings_unknown"
                  class="badge badge-warn"
                  :title="String(item.holdings_unknown)"
                >{{ t('admin.security.holdingUnknownBadge') }}</span>
                <span v-else class="badge">{{ t('admin.security.removableBadge') }}</span>
              </span>
              <span class="sc-actions">
                <button
                  type="button"
                  :disabled="item.protected || item.has_tracker || item.held_live || item.holdings_unknown"
                  class="btn btn-quiet btn-icon btn-sm is-danger"
                  :title="item.held_live
                    ? t('admin.security.removeBlockedHoldings', undefined, { venues: (item.held_venues || []).join('/') || '—' })
                    : item.holdings_unknown
                      ? t('admin.security.removeBlockedUnknown')
                      : t('admin.security.removeTitle')"
                  @click="removeInstrument(item)"
                >
                  <Trash2 :size="13" />
                </button>
              </span>
            </article>
          </div>

          <p class="sc-hint pad">{{ t('admin.security.poolFooter', undefined, { max: instLimits.maximum }) }}</p>
        </SettingsSection>
      </template>

      <!-- ══════════ 页签 3：应急风控与持仓 ══════════ -->
      <template v-if="activeTab === 'emergency'">
        <SettingsSection :title="t('admin.security.manualTitle')" :description="t('admin.security.manualDesc')" :icon="Zap">
          <template #actions>
            <button type="button" class="btn btn-quiet btn-sm" @click="saveManualClose">
              <Save :size="13" />
              <span>{{ t('admin.security.saveSwitch') }}</span>
            </button>
          </template>

          <div class="sc-check sc-switch-row" :class="{ 'is-danger': manualClose }">
            <BaseSwitch v-model="manualClose" :label="t('admin.security.manualTitle')" />
            <span class="sc-switch-text">
              {{ manualClose ? t('admin.security.manualOn') : t('admin.security.manualOff') }}
            </span>
          </div>
        </SettingsSection>

        <SettingsSection :title="t('admin.security.snapshotTitle')" :description="t('admin.security.snapshotDesc')" :icon="Radar">
          <template #actions>
            <button type="button" class="btn btn-quiet btn-sm" @click="loadPositions">
              <Zap :size="13" />
              <span>{{ t('admin.security.refreshPositions') }}</span>
            </button>
          </template>

          <p
            v-if="snapshotState"
            class="sc-loading"
            :class="{ 'is-error': snapshotError }"
            :role="snapshotError ? 'alert' : 'status'"
            aria-live="polite"
          >
            <Loader2 v-if="!snapshotError" :size="12" class="animate-spin shrink-0" aria-hidden="true" />
            <AlertTriangle v-else :size="12" aria-hidden="true" />
            {{ snapshotState }}
          </p>

          <p v-else-if="snapshot" class="sc-snap-meta">
            <span class="label-caps">{{ t('admin.security.envWord') }}</span>
            <b :class="snapshot.environment === 'live' ? 'is-down' : 'is-up'">{{ envBadge(snapshot.environment) }}</b>
            <span class="sc-sep">·</span>
            <span>{{ t('admin.security.positionsWord') }} <b class="num">{{ snapshot.positions?.length ?? 0 }}</b></span>
            <span class="sc-sep">·</span>
            <span>{{ t('admin.security.ordersWord') }} <b class="num">{{ snapshot.orders?.length ?? 0 }}</b></span>
            <span class="sc-sep">·</span>
            <span class="mono">{{ fmtDateTime(snapshot.captured_at_ms) }}</span>
          </p>

          <BaseEmpty
            v-if="!snapshot?.positions?.length"
            :text="snapshot ? t('admin.security.noPositions') : t('admin.security.clickRefreshHint')"
          />

          <div v-else class="sc-rows">
            <div class="sc-row sc-pos-row sc-row-head">
              <span>{{ t('admin.security.colPosition') }}</span>
              <span>{{ t('admin.security.colContracts') }}</span>
              <span>{{ t('admin.security.colMode') }}</span>
              <span>{{ t('admin.security.colUpl') }}</span>
              <span />
            </div>

            <article
              v-for="p in snapshot.positions"
              :key="p.instId + p.posSide"
              class="sc-row sc-pos-row"
            >
              <span class="sc-pos-id">
                <b class="mono">{{ p.instId }}</b>
                <span v-if="p.venue" class="badge mono">{{ p.venue }}</span>
                <span class="badge" :class="p.posSide === 'long' ? 'badge-up' : 'badge-down'">
                  {{ (p.posSide || 'net').toUpperCase() }}
                </span>
              </span>
              <span class="sc-contracts num" :title="p.pos ? `${p.pos}` : undefined">
                {{ p.margin ? `${Number(p.margin).toFixed(2)} U` : (p.pos || '0') }}
              </span>
              <span class="sc-mode mono">{{ p.mgnMode || '--' }}</span>
              <span class="sc-upl num" :class="Number(p.upl || 0) >= 0 ? 'is-up' : 'is-down'">
                {{ Number(p.upl || 0).toFixed(4) }}
              </span>
              <span class="sc-actions">
                <button
                  type="button"
                  class="btn btn-quiet btn-sm is-danger"
                  @click="openClose(p)"
                >
                  {{ t('admin.security.quickClose') }}
                </button>
              </span>
            </article>
          </div>
        </SettingsSection>
      </template>
    </template>

    <!-- ══ 平仓二次确认弹窗 ══ -->
    <BaseDialog
      :open="!!closeModal?.show"
      :title="t('admin.security.closeModalTitle')"
      tone="danger"
      size="md"
      initial-focus="input"
      @close="closeModal = null"
    >
      <template v-if="closeModal?.pos">
        <p class="sc-close-desc">
          {{ t('admin.security.closePrefix') }}
          <b :class="snapshot?.environment === 'live' ? 'is-down' : 'is-up'">{{ envBadge(snapshot?.environment) }}</b>
          {{ t('admin.security.closeMiddle') }}
          <b class="sc-close-target mono">
            {{ closeModal.pos.instId }} {{ (closeModal.pos.posSide || 'net').toUpperCase() }}
            {{ Math.abs(Number(closeModal.pos.pos || 0)) }}
          </b>{{ t('admin.security.period') }}
          {{ t('admin.security.closeSuffix') }}
        </p>

        <form id="sc-close-form" class="sc-close-fields" @submit.prevent="confirmClose">
          <label class="field-stack">
            <span class="form-label">{{ t('admin.security.adminPasswordLabel') }}</span>
            <input v-model="closePassword" type="password" autocomplete="current-password" class="field" />
          </label>

          <label class="field-stack">
            <span class="form-label">
              {{ t('admin.security.confirmPhraseLabel') }}
              <code class="sc-close-phrase">{{ closeModal.pos.close_confirmation }}</code>
            </span>
            <input
              v-model="closePhraseInput"
              type="text"
              autocomplete="off"
              spellcheck="false"
              :class="{ 'is-bad': !!closePhraseInput && !closePhraseOk }"
              :aria-invalid="!!closePhraseInput && !closePhraseOk ? 'true' : undefined"
              :placeholder="closeModal.pos.close_confirmation"
              class="field mono"
            />
          </label>
        </form>
      </template>

      <template #footer>
        <button type="button" class="btn btn-ghost btn-sm" @click="closeModal = null">
          {{ t('admin.security.cancel') }}
        </button>
        <button class="btn btn-danger btn-sm" type="submit" form="sc-close-form" :disabled="closing || !closeReady">
          <Loader2 v-if="closing" :size="13" class="animate-spin shrink-0" />
          <span>{{ closing ? t('admin.security.closing') : t('admin.security.confirmClose') }}</span>
        </button>
      </template>
    </BaseDialog>

    <!-- ══ 策略广场名片预览弹窗 ══ -->
    <BaseDialog
      :open="showPlazaPreview"
      :title="t('admin.security.plazaPreviewTitle')"
      size="md"
      @close="showPlazaPreview = false"
    >
      <div v-if="loadingPlazaPreview" class="py-8 flex justify-center items-center">
        <Loader2 :size="24" class="animate-spin shrink-0 text-[var(--color-primary)]" />
      </div>
      <div v-else-if="plazaPreviewData" class="space-y-4">
        <div class="card p-4 border border-[var(--border-base)] bg-[var(--bg-elevated)] space-y-3">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <span class="font-bold text-sm text-[var(--text-primary)]">{{ plazaPreviewData.node_info?.nickname || plazaSettings.nickname }}</span>
              <span class="badge badge-accent label-caps">{{ t('admin.security.plazaVerifiedBadge') }}</span>
            </div>
            <span class="text-xs text-[var(--text-muted)] mono">{{ plazaPreviewData.node_info?.system_version }}</span>
          </div>

          <div v-if="plazaPreviewData.performance?.visible" class="grid grid-cols-3 gap-2 py-2 border-y border-[var(--border-subtle)] text-center">
            <div>
              <span class="text-xs text-[var(--text-muted)]">{{ t('admin.security.plazaRoi') }}</span>
              <p class="text-base font-bold text-emerald-400 font-mono">{{ plazaPreviewData.performance?.total_roi_pct >= 0 ? '+' : '' }}{{ plazaPreviewData.performance?.total_roi_pct }}%</p>
            </div>
            <div>
              <span class="text-xs text-[var(--text-muted)]">{{ t('admin.security.plazaWinRate') }}</span>
              <p class="text-base font-bold text-[var(--text-primary)] font-mono">{{ plazaPreviewData.performance?.win_rate_pct }}%</p>
            </div>
            <div>
              <span class="text-xs text-[var(--text-muted)]">{{ t('admin.security.plazaTotalTrades') }}</span>
              <p class="text-base font-bold text-[var(--text-primary)] font-mono">{{ plazaPreviewData.performance?.all_trades }} {{ t('admin.security.plazaTradeUnit') }}</p>
            </div>
          </div>

          <div v-if="plazaPreviewData.model_specs?.visible" class="text-xs space-y-1">
            <span class="text-[var(--text-muted)]">{{ t('admin.security.plazaDriverModel') }}:</span>
            <span class="ml-2 font-mono font-medium text-[var(--color-primary)]">{{ plazaPreviewData.model_specs?.primary_model }}</span>
            <span class="text-[var(--text-muted)] ml-2">({{ plazaPreviewData.model_specs?.reasoning_effort }} effort)</span>
          </div>

          <div v-if="plazaPreviewData.risk_settings?.visible" class="text-xs space-y-1">
            <span class="text-[var(--text-muted)]">{{ t('admin.security.plazaRiskConfig') }}:</span>
            <span class="ml-2 font-mono">{{ t('admin.security.plazaRiskSummary', undefined, { min: plazaPreviewData.risk_settings?.min_leverage, max: plazaPreviewData.risk_settings?.max_leverage, pct: (Number(plazaPreviewData.risk_settings?.max_margin_equity_ratio || 0.35) * 100).toFixed(0) }) }}</span>
          </div>
        </div>

        <div class="flex items-center justify-between pt-2">
          <button
            type="button"
            class="btn btn-quiet btn-sm"
            @click="copyStrategyCloneData"
          >
            <Copy :size="12" />
            <span>{{ t('admin.security.plazaTestCopy') }}</span>
          </button>
          <button
            type="button"
            class="btn btn-primary btn-sm"
            @click="showPlazaPreview = false"
          >
            {{ t('admin.security.plazaPreviewClose') }}
          </button>
        </div>
      </div>
    </BaseDialog>
  </div>
</template>

<style scoped>
.sc {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}
.sc-skel {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sc-tabs {
  align-self: flex-start;
}

.sc-hint {
  display: flex;
  align-items: flex-start;
  gap: 6px;
  font-size: var(--text-4xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-placeholder);
}
.sc-hint > svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.sc-hint.pad {
  margin-top: var(--ds-space-3);
  padding-top: var(--ds-space-3);
  border-top: 1px solid var(--ds-color-border-default);
}

.sc-group + .sc-group {
  margin-top: var(--ds-space-4);
}

/* ══ OKX 凭证卡 ══ */
.sc-venues {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--ds-space-3);
}

.sc-venue-card {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
  overflow: hidden;
}
.sc-venue-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--ds-space-3);
  padding: 10px var(--ds-space-3);
  border-bottom: 1px solid var(--ds-color-border-default);
}
.sc-venue-id {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.sc-venue-name {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sc-venue-api {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.sc-venue-head .badge {
  flex-shrink: 0;
}
.sc-venue-env-label {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.sc-venue-env-value {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-secondary);
}

.sc-venue-body {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3);
}

.sc-env-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
}
.sc-env-hint {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}

.sc-creds {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.sc-creds-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  flex-wrap: wrap;
}
.sc-creds-group {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-2);
}
@media (min-width: 768px) {
  .sc-creds-group {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

.sc-venue-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-3);
  padding: 8px var(--ds-space-3);
  border-top: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface);
}
.sc-latency {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.sc-venue-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  margin-left: auto;
}

/* ══ 表单布局 ══ */
.sc-form-2 {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-3);
}
@media (min-width: 640px) {
  .sc-form-2 {
    grid-template-columns: 1fr 1fr;
  }
}

.sc-inst-input {
  max-width: 220px;
}

/* ══ 行式标的与持仓列表 ══ */
.sc-rows {
  display: flex;
  flex-direction: column;
  gap: 1px;
  background-color: var(--ds-color-border-default);
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  overflow: hidden;
}
.sc-row {
  display: grid;
  grid-template-columns: 1.5fr 1.5fr 1fr 1.5fr auto;
  align-items: center;
  gap: var(--ds-space-3);
  padding: 8px var(--ds-space-3);
  background-color: var(--ds-color-bg-surface-inset);
  font-size: var(--text-3xs);
}
.sc-row:hover:not(.sc-row-head) {
  background-color: var(--ds-color-bg-hover);
}
.sc-row-head {
  background-color: var(--ds-color-bg-surface);
  font-size: var(--text-4xs);
  font-weight: 600;
  color: var(--ds-color-text-placeholder);
}
.sc-inst {
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.sc-name {
  color: var(--ds-color-text-description);
}
.sc-type {
  color: var(--ds-color-text-placeholder);
}
.sc-badges {
  display: flex;
  align-items: center;
  gap: 4px;
}
.sc-actions {
  display: flex;
  align-items: center;
  gap: 4px;
}

.sc-pos-row {
  grid-template-columns: 2fr 1.2fr 1fr 1.2fr auto;
}
.sc-pos-id {
  display: flex;
  align-items: center;
  gap: 6px;
  min-width: 0;
}
.sc-pos-id b {
  color: var(--ds-color-text-primary);
}
.sc-contracts,
.sc-mode {
  color: var(--ds-color-text-description);
}
.sc-upl {
  font-weight: 600;
  text-align: right;
}
.sc-upl.is-up {
  color: var(--up);
}
.sc-upl.is-down {
  color: var(--down);
}

@media (max-width: 900px) {
  .sc-row,
  .sc-pos-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .sc-row-head {
    display: none;
  }
  .sc-badges,
  .sc-actions {
    grid-column: 2;
    justify-content: flex-end;
  }
}

/* ══ 应急总闸与勾选行 ══ */
.sc-check {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--text-3xs);
  color: var(--ds-color-text-description);
  cursor: pointer;
  border-radius: var(--r-xs);
  transition: background-color var(--dur-fast) var(--ease-out), color var(--dur-fast) var(--ease-out);
}
.sc-check:hover {
  background-color: var(--ds-color-bg-hover);
}
.sc-check:hover:not(.is-danger) {
  color: var(--ds-color-text-primary);
}
.sc-check.is-danger span {
  color: var(--down);
}

.sc-switch-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px var(--ds-space-3);
  border: 1px solid var(--ds-color-border-default);
  border-left: 2px solid var(--ds-color-border-strong);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
}
.sc-switch-row.is-danger {
  border-left-color: var(--warn);
  background-color: var(--warn-bg);
}
.sc-switch-text {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-secondary);
}
.sc-switch-row.is-danger .sc-switch-text {
  color: var(--warn);
}

.sc-loading {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
}
.sc-loading.is-error {
  color: var(--down);
  padding-left: var(--ds-space-2);
  border-left: 2px solid var(--down);
}
.sc-snap-meta {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: var(--ds-space-3);
  font-size: var(--text-3xs);
  color: var(--ds-color-text-description);
}
.sc-snap-meta b.is-up {
  color: var(--up);
}
.sc-snap-meta b.is-down {
  color: var(--down);
}
.sc-sep {
  color: var(--ds-color-text-placeholder);
}

/* ══ 健康 ══ */
.sc-health {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
}
.sc-health-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 8px var(--ds-space-3);
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
  font-size: var(--text-3xs);
}
.sc-health-name {
  font-weight: 600;
  color: var(--ds-color-text-primary);
  text-transform: uppercase;
}
.sc-health-stat {
  color: var(--ds-color-text-description);
}
.sc-health-ms {
  color: var(--ds-color-text-placeholder);
}

/* ══ 平仓弹窗 ══ */
.sc-close-desc {
  font-size: var(--text-3xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-description);
}
.sc-close-desc b.is-up {
  color: var(--up);
}
.sc-close-desc b.is-down {
  color: var(--down);
}
.sc-close-target {
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.sc-close-fields {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-3);
  margin-top: var(--ds-space-4);
}
.sc-close-phrase {
  padding: 1px 6px;
  border-radius: var(--r-xs);
  background-color: var(--down-bg);
  color: var(--down);
  font-family: var(--ds-font-mono);
  font-weight: 600;
}
.sc-channel-box {
  margin-top: 4px;
  padding: 6px var(--ds-space-2);
  border: 1px dashed var(--ds-color-border-subtle, rgba(255, 255, 255, 0.1));
  border-radius: var(--r-xs);
  background-color: var(--ds-color-bg-surface-inset);
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.sc-channel-btn {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-size: var(--text-3xs);
  color: var(--brand, #3b82f6);
  text-align: left;
  display: inline-flex;
  align-items: center;
}
.sc-channel-btn:hover {
  text-decoration: underline;
}
.seg-compact {
  width: fit-content;
  max-width: 100%;
}
.seg-compact button {
  padding-left: var(--sp-4);
  padding-right: var(--sp-4);
}
</style>