<script setup lang="ts">
/**
 * NotifyPage.vue · 通知通道与事件流工位
 * ---------------------------------------------------------------------------
 * 骨架（推倒重来）：
 *   旧 = 4 张通道卡（**开关块逐字复制了 4 遍，每遍 10 行**）
 *        + 6 张类别卡（Tailwind 色相类 emerald/blue/indigo/purple/red/amber）
 *        + 2 个手写 fixed 遮罩弹窗（含 📱💬🤖 emoji）
 *   新 = 共享 PageHeader
 *        → **通道状态带**（已开启 / QQ / Telegram / 简报时间）
 *        → **通道清单：4 张卡由一份 `channelCards` computed 驱动**，模板只剩一份
 *        → **通知类别：单一面板内的行式清单**（中性图标 + 等宽事件键）
 *        → **每日简报** 独立面板
 *        → 2 个弹窗改用 BaseDialog
 *
 * 后端契约（逐字未改）：
 *   GET  /api/v1/admin/notifications
 *   GET  /api/v1/admin/notifications/schedule
 *   PUT  /api/v1/admin/notifications            ← saveAll 请求体字段逐字保留
 *   PUT  /api/v1/admin/notifications/schedule   { briefing_times }
 *   PUT  /api/v1/admin/channels/{channel}/toggle{ enabled, ...per-channel }
 *   POST /api/v1/admin/notifications/diagnose   { channel }
 *   POST /api/v1/admin/notifications/test       { channel, confirmation }
 *   POST /api/v1/admin/notifications/qq/capture-openid/start  { timeout: 60 }
 *   GET  /api/v1/admin/notifications/qq/capture-openid/{id}
 *   POST /api/v1/admin/notifications/qq/bind/start            {}
 *   GET  /api/v1/admin/notifications/qq/bind/{taskId}
 *
 * ⚠️ 轮询纪律逐字保留：捕获 1.5s / 绑定 2s，终态即停，`onBeforeUnmount` 停全部定时器。
 */
import { useToast } from '../../composables/useToast';
const toast = useToast();
import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import PageHeader from '../../components/admin/PageHeader.vue';
import BaseDialog from '../../components/base/BaseDialog.vue';
import BaseSwitch from '../../components/base/BaseSwitch.vue';
import { useI18n } from '../../composables/useI18n';
const { t } = useI18n();
import { useApi } from '../../composables/useApi';
import { Zap, RefreshCw, Loader2, ScanLine, QrCode, AlertTriangle, Send, Save,
  ArrowUpRight, CheckCircle2, ShieldCheck, Brain, OctagonAlert, Clock, Radio, CalendarClock } from 'lucide-vue-next';
import BaseLoadingAnnounce from '../../components/base/BaseLoadingAnnounce.vue';

const { api } = useApi();
const config = ref<any>(null);
const loading = ref(true);
const loadError = ref('');
const testResults = ref<Record<string, any>>({});
const captureModal = ref(false);
const captureStatus = ref<any>(null);
let captureTimer: any = null;

const enabledChannelsCount = computed(() => {
  if (!config.value) return 0
  return ['qq', 'telegram', 'wechat', 'feishu', 'dingtalk', 'webhook'].filter(k => config.value[k]?.enabled).length
})

async function loadConfig(silent = false) {
  if (!silent) loading.value = true
  loadError.value = ''
  try {
    const res = await api('/api/v1/admin/notifications')
    // Preserve local un-submitted secret inputs if any
    if (config.value) {
      if (config.value.qq?._secret) res.qq._secret = config.value.qq._secret
      if (config.value.telegram?._token) res.telegram._token = config.value.telegram._token
      if (config.value.feishu?._secret) res.feishu._secret = config.value.feishu._secret
      if (config.value.dingtalk?._secret) res.dingtalk._secret = config.value.dingtalk._secret
    }
    const schedule = await api('/api/v1/admin/notifications/schedule')
    res._briefingTimes = schedule.briefing_times?.join(', ') || ''
    config.value = res
  } catch (e: any) {
    console.error(e)
    loadError.value = e.message || String(e)
    if (!silent) toast.err(t('admin.notify.loadFailed', undefined, { msg: e.message || String(e) }))
  } finally {
    if (!silent) loading.value = false
  }
}

async function toggleChannel(channel: string, enabled: boolean) {
  try {
    const payload: any = { enabled }
    if (config.value) {
      if (channel === 'wechat' && config.value.wechat?.webhook) payload.wechat_webhook = config.value.wechat.webhook
      if (channel === 'feishu') {
        if (config.value.feishu?.webhook) payload.feishu_webhook = config.value.feishu.webhook
        if (config.value.feishu?._secret) payload.feishu_secret = config.value.feishu._secret
      }
      if (channel === 'dingtalk') {
        if (config.value.dingtalk?.webhook) payload.dingtalk_webhook = config.value.dingtalk.webhook
        if (config.value.dingtalk?._secret) payload.dingtalk_secret = config.value.dingtalk._secret
      }
      if (channel === 'webhook' && config.value.webhook?.url) payload.webhook_url = config.value.webhook.url
      if (channel === 'telegram') {
        if (config.value.telegram?._token) payload.telegram_bot_token = config.value.telegram._token
        if (config.value.telegram?.chat_id) payload.telegram_chat_id = config.value.telegram.chat_id
        if (config.value.telegram?.api_base) payload.telegram_api_base = config.value.telegram.api_base
      }
      if (channel === 'qq') {
        if (config.value.qq?.app_id) payload.qq_app_id = config.value.qq.app_id
        if (config.value.qq?._secret) payload.qq_client_secret = config.value.qq._secret
        if (config.value.qq?.openid) payload.qq_openid = config.value.qq.openid
      }
      // Optimistically flip visual state immediately
      if (config.value[channel]) {
        config.value[channel].enabled = enabled
      }
    }
    const res = await api(`/api/v1/admin/channels/${channel}/toggle`, { method: 'PUT', body: JSON.stringify(payload) })
    toast.ok(
      res.message ||
        t('admin.notify.toggleOk', undefined, {
          channel,
          state: t(enabled ? 'admin.notify.stateOn' : 'admin.notify.stateOff'),
        }),
    )
    await loadConfig(true)
  } catch (e: any) {
    toast.err(e.message || t('admin.notify.toggleFailed'))
    await loadConfig(true)
  }
}

async function saveAll() {
  try {
    const body: any = {
      webhook_enabled: config.value.webhook?.enabled ?? false,
      webhook_url: config.value.webhook?.url ?? '',
      wechat_enabled: config.value.wechat?.enabled ?? false,
      wechat_webhook: config.value.wechat?.webhook ?? '',
      feishu_enabled: config.value.feishu?.enabled ?? false,
      feishu_webhook: config.value.feishu?.webhook ?? '',
      feishu_secret: config.value.feishu?._secret || undefined,
      dingtalk_enabled: config.value.dingtalk?.enabled ?? false,
      dingtalk_webhook: config.value.dingtalk?.webhook ?? '',
      dingtalk_secret: config.value.dingtalk?._secret || undefined,
      telegram_enabled: config.value.telegram?.enabled ?? false,
      telegram_bot_token: config.value.telegram?._token || undefined,
      telegram_chat_id: config.value.telegram?.chat_id ?? '',
      telegram_api_base: config.value.telegram?.api_base || undefined,
      qq_enabled: config.value.qq?.enabled ?? false,
      qq_app_id: config.value.qq?.app_id ?? '',
      qq_client_secret: config.value.qq?._secret || undefined,
      qq_openid: config.value.qq?.openid ?? '',
    }
    const res = await api('/api/v1/admin/notifications', { method: 'PUT', body: JSON.stringify(body) })
    toast.ok(res.message || t('admin.notify.savedAll'))
    await loadConfig(true)
  } catch (e: any) {
    toast.err(e.message || t('admin.notify.saveFailed'))
  }
}

async function diagnose(channel: string) {
  try {
    const res = await api('/api/v1/admin/notifications/diagnose', { method: 'POST', body: JSON.stringify({ channel }) })
    testResults.value[channel] = res.result
  } catch (e: any) {
    testResults.value[channel] = { status: 'failed', detail: e.message }
  }
}

async function startCapture() {
  try {
    const res = await api('/api/v1/admin/notifications/qq/capture-openid/start', { method: 'POST', body: JSON.stringify({ timeout: 60 }) })
    captureModal.value = true
    captureStatus.value = res
    pollCapture(res.capture_id)
  } catch (e: any) {
    toast.err(e.message)
  }
}

function pollCapture(captureId: string) {
  if (captureTimer) clearInterval(captureTimer)
  captureTimer = setInterval(async () => {
    try {
      const res = await api(`/api/v1/admin/notifications/qq/capture-openid/${captureId}`)
      captureStatus.value = res
      if (res.status === 'captured' || res.status === 'expired' || res.status === 'failed') {
        clearInterval(captureTimer)
        captureTimer = null
        if (res.status === 'captured') {
          await loadConfig()
          setTimeout(() => { captureModal.value = false }, 1800)
        }
      }
    } catch (e: any) {
      clearInterval(captureTimer)
      captureTimer = null
    }
  }, 1500)
}

// ---- QQ scan bind ----
const bindModal = ref(false)
const bindStatus = ref<any>(null)
let bindTimer: any = null
let bindTaskId = ''

function stopBindPolling() {
  if (bindTimer) { clearInterval(bindTimer); bindTimer = null }
}

async function startQqBind() {
  try {
    const d = await api('/api/v1/admin/notifications/qq/bind/start', { method: 'POST', body: '{}' })
    bindTaskId = d.task_id
    bindStatus.value = { qr: d.qr_data_uri || '', link: d.qr_data_uri ? '' : (d.connect_url || ''), text: t('admin.notify.waitScan', undefined, { n: d.expires_in }), tone: 'blue' }
    bindModal.value = true
    stopBindPolling()
    bindTimer = setInterval(async () => {
      if (!bindTaskId) return
      try {
        const r = await api(`/api/v1/admin/notifications/qq/bind/${bindTaskId}`)
        if (r.status === 'bound') {
          bindStatus.value = { ...bindStatus.value, text: t('admin.notify.bindSuccess'), tone: 'green' }
          stopBindPolling()
          await loadConfig()
          setTimeout(() => { bindModal.value = false }, 1800)
        } else if (r.status === 'awaiting_message') {
          stopBindPolling()
          bindModal.value = false
          toast.ok(t('admin.notify.qqBound'))
          startCapture()
        } else if (r.status === 'expired') {
          bindStatus.value = { ...bindStatus.value, text: t('admin.notify.qrExpired'), tone: 'amber' }
          stopBindPolling()
        } else if (r.status === 'failed') {
          bindStatus.value = { ...bindStatus.value, text: t('admin.notify.bindFailed', undefined, { error: r.error || t('admin.notify.unknownError') }), tone: 'red' }
          stopBindPolling()
        } else {
          bindStatus.value = { ...bindStatus.value, text: t('admin.notify.waitScan', undefined, { n: r.expires_in ?? '--' }), tone: 'blue' }
        }
      } catch (e: any) {
        bindStatus.value = { ...bindStatus.value, text: e.message, tone: 'red' }
        stopBindPolling()
      }
    }, 2000)
  } catch (e: any) {
    toast.err(e.message)
  }
}

function closeBindModal() {
  stopBindPolling()
  bindModal.value = false
}

// ---- protected test send ----
async function sendTest(channel: string) {
  try {
    testResults.value[channel] = { status: 'testing', detail: t('admin.notify.requestingTest') }
    const res = await api('/api/v1/admin/notifications/test', {
      method: 'POST',
      body: JSON.stringify({ channel, confirmation: `SEND TEST ${channel.toUpperCase()}` }),
    })
    testResults.value[channel] = { status: res.result?.[channel]?.startsWith('accepted:') ? 'ready' : (res.result?.status || 'sent'), detail: `${res.result?.[channel] || res.result?.detail || t('admin.notify.sent')} · ${res.meaning || ''}` }
  } catch (e: any) {
    testResults.value[channel] = { status: 'failed', detail: e.message }
  }
}

async function saveSchedule() {
  const times = String(config.value._briefingTimes || '').split(/[,，\s]+/).filter(Boolean)
  if (!times.length) { toast.warn(t('admin.notify.scheduleRequired')); return }
  try {
    await api('/api/v1/admin/notifications/schedule', { method: 'PUT', body: JSON.stringify({ briefing_times: times }) })
    toast.ok(t('admin.notify.scheduleSaved'))
  } catch (e: any) {
    toast.err(e.message)
  }
}

// ── 展示层：把 4 段复制粘贴的通道卡收成一份数据 ──
interface FieldSpec {
  key: string
  label: string
  type?: string
  placeholder?: string
  span?: boolean
}
interface ChannelCard {
  key: string
  title: string
  offTitle: string
  onTitle: string
  qqActions: boolean
  fields: FieldSpec[]
}

const channelCards = computed<ChannelCard[]>(() => [
  {
    key: 'feishu',
    title: t('admin.notify.feishuTitle'),
    offTitle: t('admin.notify.feishuOff'),
    onTitle: t('admin.notify.feishuOn'),
    qqActions: false,
    fields: [
      { key: 'webhook', label: 'Webhook URL', placeholder: 'https://open.feishu.cn/open-apis/bot/v2/hook/...', span: true },
      { key: '_secret', label: t('admin.notify.signatureSecret'), type: 'password', placeholder: t('admin.notify.optionalSecret'), span: true },
    ],
  },
  {
    key: 'dingtalk',
    title: t('admin.notify.dingtalkTitle'),
    offTitle: t('admin.notify.dingtalkOff'),
    onTitle: t('admin.notify.dingtalkOn'),
    qqActions: false,
    fields: [
      { key: 'webhook', label: 'Webhook URL', placeholder: 'https://oapi.dingtalk.com/robot/send?access_token=...', span: true },
      { key: '_secret', label: t('admin.notify.signatureSecret'), type: 'password', placeholder: t('admin.notify.optionalSecret'), span: true },
    ],
  },
  {
    key: 'wechat',
    title: t('admin.notify.wechatTitle'),
    offTitle: t('admin.notify.wechatOff'),
    onTitle: t('admin.notify.wechatOn'),
    qqActions: false,
    fields: [{ key: 'webhook', label: 'Webhook URL', placeholder: 'https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=...', span: true }],
  },
  {
    key: 'telegram',
    title: 'Telegram Bot',
    offTitle: t('admin.notify.telegramOff'),
    onTitle: t('admin.notify.telegramOn'),
    qqActions: false,
    fields: [
      { key: '_token', label: 'Bot Token', type: 'password', placeholder: t('admin.notify.keepExisting') },
      { key: 'chat_id', label: 'Chat ID' },
      { key: 'api_base', label: t('admin.notify.apiBaseLabel'), placeholder: 'https://api.telegram.org', span: true },
    ],
  },
  {
    key: 'qq',
    title: t('admin.notify.qqTitle'),
    offTitle: t('admin.notify.qqOff'),
    onTitle: t('admin.notify.qqOn'),
    qqActions: true,
    fields: [
      { key: 'app_id', label: 'App ID' },
      { key: '_secret', label: 'Client Secret', type: 'password', placeholder: t('admin.notify.keepExisting') },
      { key: 'openid', label: t('admin.notify.targetOpenId'), span: true },
    ],
  },
  {
    key: 'webhook',
    title: t('admin.notify.webhookTitle'),
    offTitle: t('admin.notify.webhookOff'),
    onTitle: t('admin.notify.webhookOn'),
    qqActions: false,
    fields: [{ key: 'url', label: t('admin.notify.webhookUrlLabel'), placeholder: 'https://api.example.com/webhook', span: true }],
  },
])

const categories = computed(() => [
  { key: 'trade.opened', label: t('admin.notify.catOpen'), desc: t('admin.notify.catOpenDesc'), icon: ArrowUpRight },
  { key: 'trade.closed', label: t('admin.notify.catClosed'), desc: t('admin.notify.catClosedDesc'), icon: CheckCircle2 },
  { key: 'trade.sl_updated', label: t('admin.notify.catBreakEven'), desc: t('admin.notify.catBreakEvenDesc'), icon: ShieldCheck },
  { key: 'evolution.completed', label: t('admin.notify.catEvolution'), desc: t('admin.notify.catEvolutionDesc'), icon: Brain },
  { key: 'risk.triggered', label: t('admin.notify.catRisk'), desc: t('admin.notify.catRiskDesc'), icon: OctagonAlert },
  { key: 'briefing.ready', label: t('admin.notify.catBriefing'), desc: t('admin.notify.catBriefingDesc'), icon: Clock },
])

/** 后端返回的 status 是自由字符串 → 徽章色调（ready/sent 绿 · failed/error 红 · 其余琥珀） */
function testTone(status: string): string {
  if (['ready', 'sent', 'ok', 'success'].includes(status)) return 'badge-up'
  if (['failed', 'error'].includes(status)) return 'badge-down'
  return 'badge-warn'
}
function channelOn(k: string): boolean {
  return config.value?.[k]?.enabled === true
}
const bindTone = computed(() => {
  const tone = bindStatus.value?.tone
  if (tone === 'green') return 'badge-up'
  if (tone === 'red') return 'badge-down'
  if (tone === 'amber') return 'badge-warn'
  return 'badge-accent'
})

onMounted(() => {
  loadConfig()
})

// 批B(2026-09-13)·离场清理：旧实现仅在「终态/异常」清定时器，离开本页后 QQ
// OpenID 捕获/扫码绑定仍每 1.5s 打一次管理接口（最长持续到服务端过期，失败还被
// 静默吞）。组件卸载即停全部轮询。
onBeforeUnmount(() => {
  if (captureTimer) { clearInterval(captureTimer); captureTimer = null }
  stopBindPolling()
})
</script>

<template>
  <div class="nf">
    <PageHeader :title="t('nav.admin.notify')">
      <template #actions>
        <span class="badge badge-accent mono">
          {{ t('admin.notify.channelsChip') }} {{ enabledChannelsCount }}/6
        </span>
        <button type="button" class="btn btn-ghost btn-sm" :disabled="loading" @click="loadConfig()">
          <Loader2 v-if="loading && config" :size="14" class="animate-spin shrink-0" />
          <RefreshCw v-else :size="14" />
          <span>{{ t('common.refresh') }}</span>
        </button>
      </template>
    </PageHeader>

    <!-- 拉取失败 -->
    <div v-if="loadError && !config" role="alert" class="state-block is-error">
      <span class="state-icon"><AlertTriangle :size="17" /></span>
      <p class="state-title">{{ t('common.loadFailed') }}</p>
      <p class="state-desc">{{ loadError }}</p>
      <button type="button" class="btn btn-ghost btn-sm mt-1" :disabled="loading" @click="loadConfig()">
        <RefreshCw :size="14" />
        <span>{{ t('common.retry') }}</span>
      </button>
    </div>

    <template v-else>
      <!-- ══ 通道状态带 ══ -->
      <section class="card band">
        <template v-if="loading && !config">
          <BaseLoadingAnnounce />
          <div v-for="i in 4" :key="i" class="fact">
            <div class="skeleton skeleton-text" style="width: 48%" />
            <div class="skeleton skeleton-text skeleton-value" style="width: 62%" />
            <div class="skeleton skeleton-text" style="width: 36%" />
          </div>
        </template>

        <template v-else-if="config">
          <div class="fact">
            <span class="fact-label"><Radio :size="12" />{{ t('admin.notify.bandEnabled') }}</span>
            <span class="fact-value num" :class="enabledChannelsCount ? 'is-up' : ''">
              {{ enabledChannelsCount }} / 6
            </span>
            <span class="fact-foot">{{ t('admin.notify.channelsTitle') }}</span>
          </div>

          <div class="fact">
            <span class="fact-label"><Zap :size="12" />{{ t('admin.notify.bandQQ') }}</span>
            <span class="fact-value" :class="channelOn('qq') ? 'is-up' : 'is-off'">
              {{ channelOn('qq') ? t('admin.notify.enabled') : t('admin.notify.disabled') }}
            </span>
            <span class="fact-foot mono truncate" :title="config.qq?.openid || t('admin.notify.notSet')">{{ config.qq?.openid || t('admin.notify.notSet') }}</span>
          </div>

          <div class="fact">
            <span class="fact-label"><Send :size="12" />{{ t('admin.notify.bandTelegram') }}</span>
            <span class="fact-value" :class="channelOn('telegram') ? 'is-up' : 'is-off'">
              {{ channelOn('telegram') ? t('admin.notify.enabled') : t('admin.notify.disabled') }}
            </span>
            <span class="fact-foot mono truncate">{{ config.telegram?.chat_id || t('admin.notify.notSet') }}</span>
          </div>

          <div class="fact">
            <span class="fact-label"><CalendarClock :size="12" />{{ t('admin.notify.bandBriefing') }}</span>
            <span class="fact-value num truncate" :title="config._briefingTimes || t('admin.notify.notSet')">{{ config._briefingTimes || t('admin.notify.notSet') }}</span>
            <span class="fact-foot">{{ t('admin.notify.scheduleTitle') }}</span>
          </div>
        </template>
      </section>

      <template v-if="config">
        <!-- ══ 通知通道 ══ -->
        <section class="nf-block">
          <header class="nf-block-head">
            <div>
              <h2 class="card-title">{{ t('admin.notify.channelsTitle') }}</h2>
              <p class="card-sub">{{ t('admin.notify.channelsDesc') }}</p>
            </div>
          </header>

          <div class="nf-channels">
            <article
              v-for="c in channelCards"
              :key="c.key"
              class="card nf-card"
              :class="{ 'is-on': channelOn(c.key) }"
            >
              <header class="nf-card-head">
                <span class="nf-card-dot" :class="{ 'is-on': channelOn(c.key) }" aria-hidden="true" />
                <h3 class="nf-card-title">{{ c.title }}</h3>

                <div class="nf-card-actions">
                  <template v-if="c.qqActions">
                    <button type="button" class="btn btn-primary btn-sm" @click="startQqBind">
                      <QrCode :size="13" />
                      <span>{{ t('admin.notify.scanBind') }}</span>
                    </button>
                    <button type="button" class="btn btn-ghost btn-sm" @click="startCapture">
                      <Zap :size="13" />
                      <span>{{ t('admin.notify.autoOpenId') }}</span>
                    </button>
                  </template>

                  <span class="nf-state" :class="channelOn(c.key) ? 'is-on' : ''">
                    {{ channelOn(c.key) ? t('admin.notify.enabled') : t('admin.notify.disabled') }}
                  </span>
                  <BaseSwitch
                    :model-value="channelOn(c.key)"
                    :label="channelOn(c.key) ? c.offTitle : c.onTitle"
                    @update:model-value="() => toggleChannel(c.key, !channelOn(c.key))"
                  />
                </div>
              </header>

              <div class="nf-fields">
                <label
                  v-for="f in c.fields"
                  :key="f.key"
                  class="field-stack nf-field"
                  :class="{ 'is-span': f.span }"
                >
                  <span class="form-label">{{ f.label }}</span>
                  <input
                    v-model="config[c.key][f.key]"
                    :type="f.type || 'text'"
                    :placeholder="f.placeholder"
                    class="field"
                  />
                </label>
              </div>

              <footer class="nf-card-foot">
                <!-- 批 71：测试进行中按钮必须禁用 —— 此前连点会并发发起多次测试请求，
                     而右上角结果区只会显示最后一次，用户看到的"重试"其实是请求风暴。 -->
                <button type="button"
                  class="btn btn-ghost btn-sm"
                  :disabled="testResults[c.key]?.status === 'testing'"
                  @click="diagnose(c.key)"
                >
                  <ScanLine :size="13" aria-hidden="true" />
                  <span>{{ t('admin.notify.diagnose') }}</span>
                </button>
                <button type="button"
                  class="btn btn-ghost btn-sm"
                  :disabled="testResults[c.key]?.status === 'testing'"
                  @click="sendTest(c.key)"
                >
                  <Send :size="13" aria-hidden="true" />
                  <span>{{ t('admin.notify.sendTest') }}</span>
                </button>

                <!-- 批 70：测试发送/诊断的结果只写进 testResults，本页不弹 toast，
                     故这里必须自报 —— 失败用 alert，其余（含 testing）用 status。 -->
                <span
                  v-if="testResults[c.key]"
                  class="nf-result"
                  :class="testTone(testResults[c.key].status)"
                  :role="testTone(testResults[c.key].status) === 'badge-down' ? 'alert' : 'status'"
                  aria-live="polite"
                >
                  <b>{{ testResults[c.key].status }}</b>
                  <span class="nf-result-detail">{{ testResults[c.key].detail }}</span>
                </span>
                <span v-else class="nf-result is-idle">{{ t('admin.notify.testIdle') }}</span>
              </footer>
            </article>
          </div>
        </section>

        <!-- ══ 通知类别 ══ -->
        <section class="card">
          <header class="card-head">
            <div>
              <h2 class="card-title">{{ t('admin.notify.categoriesTitle') }}</h2>
              <p class="card-sub">{{ t('admin.notify.categoriesDesc') }}</p>
            </div>
            <span class="badge mono">{{ categories.length }}</span>
          </header>

          <div class="nf-cats">
            <article v-for="cat in categories" :key="cat.key" class="nf-cat">
              <span class="icon-box"><component :is="cat.icon" :size="14" /></span>
              <div class="nf-cat-main">
                <div class="nf-cat-title">
                  <span class="nf-cat-name">{{ cat.label }}</span>
                  <code class="nf-cat-key">{{ cat.key }}</code>
                </div>
                <p class="panel-desc">{{ cat.desc }}</p>
              </div>
            </article>
          </div>
        </section>

        <!-- ══ 每日简报 ══ -->
        <section class="card">
          <header class="card-head">
            <h2 class="card-title"><CalendarClock :size="14" />{{ t('admin.notify.scheduleTitle') }}</h2>
          </header>

          <div class="nf-schedule">
            <label class="field-stack nf-field is-span">
              <span class="form-label">{{ t('admin.notify.scheduleLabel') }}</span>
              <input
                v-model="config._briefingTimes"
                placeholder="08:00, 20:00"
                class="field num"
              />
            </label>
          </div>

          <footer class="nf-save">
            <button type="button" class="btn btn-primary btn-sm" @click="saveAll">
              <Save :size="14" />
              <span>{{ t('admin.notify.saveAll') }}</span>
            </button>
            <button type="button" class="btn btn-ghost btn-sm" @click="saveSchedule">
              <CalendarClock :size="14" />
              <span>{{ t('admin.notify.saveSchedule') }}</span>
            </button>
          </footer>
        </section>
      </template>
    </template>

    <!-- ══ OpenID 捕获 ══ -->
    <BaseDialog
      :open="captureModal"
      :title="t('admin.notify.captureTitle')"
      size="md"
      @close="captureModal = false"
    >
      <div class="nf-capture">
        <span
          class="badge"
          :class="captureStatus?.status === 'captured' ? 'badge-up' : 'badge-accent'"
        >
          {{ captureStatus?.status === 'captured' ? t('admin.notify.captured') : t('admin.notify.listening') }}
        </span>

        <p class="nf-capture-bot">{{ captureStatus?.bot_name || t('admin.notify.connecting') }}</p>
        <p class="nf-capture-guide">{{ t('admin.notify.captureGuide') }}</p>

        <div class="nf-capture-box">
          <p v-if="captureStatus?.expires_in" class="nf-capture-meta mono">
            {{ t('admin.notify.remainingSeconds', undefined, { n: captureStatus.expires_in }) }}
          </p>
          <p v-if="captureStatus?.openid" class="nf-capture-openid mono">
            OpenID: {{ captureStatus.openid }}
          </p>
        </div>
      </div>

      <template #footer>
        <button type="button" class="btn btn-ghost btn-sm" @click="captureModal = false">
          {{ t('admin.notify.close') }}
        </button>
      </template>
    </BaseDialog>

    <!-- ══ QQ 扫码绑定 ══ -->
    <BaseDialog
      :open="bindModal"
      :title="t('admin.notify.bindTitle')"
      :desc="t('admin.notify.bindGuide')"
      size="sm"
      @close="closeBindModal"
    >
      <div class="nf-bind">
        <img
          v-if="bindStatus?.qr"
          :src="bindStatus.qr"
          :alt="t('admin.notify.qrAlt')"
          class="nf-qr"
        />
        <p v-if="bindStatus?.link" class="nf-bind-link mono">{{ bindStatus.link }}</p>
        <span class="badge" :class="bindTone">{{ bindStatus?.text }}</span>
      </div>

      <template #footer>
        <button type="button" class="btn btn-ghost btn-sm" @click="startQqBind">
          <RefreshCw :size="14" />
          <span>{{ t('admin.notify.refreshQr') }}</span>
        </button>
        <button type="button" class="btn btn-primary btn-sm" @click="closeBindModal">
          {{ t('admin.notify.close') }}
        </button>
      </template>
    </BaseDialog>
  </div>
</template>

<style scoped>
.nf {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}

/* ══ 状态带 ══ */









/* ══ 通道 ══ */
.nf-block {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-3);
}
.nf-block-head {
  padding: 0 2px;
}
.nf-channels {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-4);
}
@media (min-width: 1100px) {
  .nf-channels {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
.nf-card {
  display: flex;
  flex-direction: column;
  border-left: 2px solid transparent;
}
.nf-card.is-on {
  border-left-color: var(--up);
}
.nf-card-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-default);
}
.nf-card-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background-color: var(--ds-color-text-placeholder);
  flex-shrink: 0;
}
.nf-card-dot.is-on {
  background-color: var(--up);
}
.nf-card-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.nf-card-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  margin-left: auto;
  flex-wrap: wrap;
}
.nf-state {
  font-size: var(--text-3xs);
  font-weight: 600;
  color: var(--ds-color-text-placeholder);
}
.nf-state.is-on {
  color: var(--up);
}

.nf-fields {
  display: grid;
  grid-template-columns: 1fr;
  gap: var(--ds-space-3);
  padding: var(--ds-space-4);
}
@media (min-width: 520px) {
  .nf-fields {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

.nf-field.is-span {
  grid-column: 1 / -1;
}

.nf-card-foot {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
  margin-top: auto;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface-inset);
}
.nf-result {
  display: flex;
  align-items: baseline;
  gap: 6px;
  margin-left: auto;
  min-width: 0;
  font-size: var(--text-3xs);
}
.nf-result.is-idle {
  color: var(--ds-color-text-placeholder);
}
.nf-result b {
  font-weight: 600;
}
.nf-result-detail {
  color: var(--ds-color-text-description);
  overflow-wrap: anywhere;
}

/* ══ 类别 ══ */
.nf-cats {
  display: grid;
  grid-template-columns: 1fr;
}
@media (min-width: 900px) {
  .nf-cats {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
@media (min-width: 1500px) {
  .nf-cats {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
.nf-cat {
  display: flex;
  align-items: flex-start;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
}
@media (min-width: 900px) {
  .nf-cat:nth-child(-n + 2) {
    border-top: 0;
  }
  .nf-cat:nth-child(even) {
    border-left: 1px solid var(--ds-color-border-default);
  }
}
@media (min-width: 1500px) {
  .nf-cat:nth-child(3) {
    border-top: 0;
  }
  .nf-cat:nth-child(3n) {
    border-left: 0;
  }
  .nf-cat:not(:nth-child(3n + 1)) {
    border-left: 1px solid var(--ds-color-border-default);
  }
}
.nf-cat-main {
  min-width: 0;
}
.nf-cat-title {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.nf-cat-name {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.nf-cat-key {
  padding:1px 6px;
  border-radius: var(--r-xs);
  border: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface-1);
  font-family: var(--ds-font-mono);
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}

/* ══ 简报 ══ */
.nf-schedule {
  padding: var(--ds-space-4);
}
.nf-save {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-default);
  background-color: var(--ds-color-bg-surface-inset);
}

/* ══ 弹窗内 ══ */
.nf-capture {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--ds-space-2);
  text-align: center;
}
.nf-capture-bot {
  font-size: var(--text-sm);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.nf-capture-guide {
  font-size: var(--text-3xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-description);
}
.nf-capture-box {
  width: 100%;
  margin-top: var(--ds-space-2);
  padding: var(--ds-space-3);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
}
.nf-capture-meta {
  font-size: var(--text-3xs);
  color: var(--ds-color-text-placeholder);
}
.nf-capture-openid {
  margin-top: 6px;
  font-size: var(--text-3xs);
  color: var(--ds-color-brand);
  overflow-wrap: anywhere;
}
.nf-bind {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--ds-space-3);
  text-align: center;
}
.nf-qr {
  width: 220px;
  height: 220px;
  padding: 10px;
  border-radius: var(--r-ctl);
  border: 1px solid var(--ds-color-border-default);
  /* 唯一一处刻意的固定色：二维码必须落在纯白底上才能被手机相机/QQ 稳定识别，
     深色主题下的半透明表面色会让多数扫码器解读失败。这是功能性对比要求，非装饰用色。 */
  background-color: #fff;
}
.nf-bind-link {
  font-size: var(--text-3xs);
  color: var(--ds-color-brand);
  overflow-wrap: anywhere;
}
</style>
