<script setup lang="ts">
import { RouterLink } from 'vue-router';
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Copy,
  Eye,
  KeyRound,
  Loader2,
  Radar,
  RefreshCw,
  Save,
  Share2,
  ShieldCheck,
  TrendingUp,
  Zap,
} from 'lucide-vue-next';
import SettingsSection from '../../../components/admin/page-parts/SettingsSection.vue';
import BaseDialog from '../../../components/base/BaseDialog.vue';
import BaseEmpty from '../../../components/base/BaseEmpty.vue';
import BaseSwitch from '../../../components/base/BaseSwitch.vue';
import { useI18n } from '../../../composables/useI18n';
import { useSecurityCtx } from './useSecurityAdmin';

const { t } = useI18n();
const {
  channelOf,
  config,
  copyPlazaUrl,
  copyStrategyCloneData,
  healthAllOk,
  healthUnknownTotal,
  isUnifiedLive,
  keys,
  loadMx,
  loadingPlazaPreview,
  mxHealthChips,
  okxCredViewLive,
  okxEnvText,
  okxLinked,
  openExternal,
  openPlazaPreview,
  orderMode,
  plazaPreviewData,
  plazaPublicUrl,
  plazaSettings,
  probeVenue,
  probingVenue,
  requestUnifiedEnvSwitch,
  saveEnvironment,
  saveOrderMode,
  savePlazaSettings,
  savingOkx,
  savingOrderMode,
  savingPlaza,
  savingScaleOut,
  savingUnifiedEnv,
  scaleOutEnabled,
  showPlazaPreview,
  toggleScaleOut,
  venueLatencies,
} = useSecurityCtx();
</script>

<template>
  <div class="sv-stack">
    <!-- Unified Environment Switch -->
    <SettingsSection :title="t('admin.security.unifiedEnvTitle')" :icon="ShieldCheck">
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

    <!-- Order Execution Mode -->
    <SettingsSection :title="t('admin.security.orderModeTitle')" :icon="Zap">
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
            :aria-pressed="orderMode === 'smart'"
            :class="{ 'seg-on': orderMode === 'smart' }"
            @click="orderMode = 'smart'"
          >
            <span>{{ t('admin.security.optSmart') }}</span>
          </button>
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
          {{ orderMode === 'smart' ? t('admin.security.orderModeSmartHint') : orderMode === 'market' ? t('admin.security.orderModeMarketHint') : t('admin.security.orderModeLimitHint') }}
        </p>
      </div>
    </SettingsSection>

    <!-- Scale-Out -->
    <SettingsSection :title="t('admin.security.scaleOutTitle')" :icon="TrendingUp">
      <template #actions>
        <span class="badge" :class="scaleOutEnabled ? 'badge-up' : 'badge-neutral'">
          {{ scaleOutEnabled ? t('admin.security.scaleOutEnabledTag') : t('admin.security.scaleOutDisabledTag') }}
        </span>
      </template>

      <div class="sc-group">
        <div class="wb-toggle-row">
          <div class="wb-setting-meta">
            <span class="wb-setting-title">{{ t('admin.security.scaleOutSwitchLabel') }}</span>
            <p class="wb-setting-desc">{{ t('admin.security.scaleOutHint') }}</p>
          </div>
          <div class="sv-switch-pack">
            <Loader2 v-if="savingScaleOut" :size="14" class="animate-spin shrink-0" />
            <BaseSwitch
              :model-value="scaleOutEnabled"
              :aria-label="t('admin.security.scaleOutSwitchLabel')"
              :disabled="savingScaleOut"
              @update:model-value="toggleScaleOut"
            />
          </div>
        </div>
        <div class="sv-link-bar">
          <span>
            {{ t('admin.security.scaleOutCurrentPreset') }}:
            {{ Math.round((config?.editable?.scale_out_ratio || 0.5) * 100) }}% ·
            {{ config?.editable?.scale_out_trigger_atr || 1.2 }}x ATR
          </span>
          <RouterLink to="/admin/strategy?tab=risk" class="sv-link-accent">
            <span>{{ t('admin.security.scaleOutCustomizeInRisk') }}</span>
            <ArrowRight :size="13" />
          </RouterLink>
        </div>
      </div>
    </SettingsSection>

    <!-- OKX Credentials -->
    <SettingsSection :title="t('admin.security.credsTitle')" :icon="KeyRound">
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
                {{ okxCredViewLive ? t('admin.security.liveTrio') : t('admin.security.demoTrio') }}
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
          <p class="sc-hint"><AlertTriangle :size="12" />{{ t('admin.security.liveConfirmNote') }}</p>
        </div>

        <footer class="sc-venue-foot">
          <span v-if="venueLatencies.okx" class="sc-latency mono num">
            <Radar :size="13" />
            <span>{{ venueLatencies.okx }}ms</span>
          </span>
          <div class="sc-venue-actions">
            <button type="button" class="btn btn-quiet btn-sm" :disabled="probingVenue === 'okx'" @click="probeVenue('okx')">
              <RefreshCw :size="14" :class="probingVenue === 'okx' ? 'animate-spin shrink-0' : ''" />
              <span>{{ probingVenue === 'okx' ? t('admin.security.probing') : t('admin.security.detect') }}</span>
            </button>
            <button type="button" class="btn btn-primary btn-sm" :disabled="savingOkx" @click="saveEnvironment">
              <Loader2 v-if="savingOkx" :size="13" class="animate-spin shrink-0" />
              <Save v-else :size="13" />
              <span>{{ savingOkx ? t('admin.security.saving') : t('admin.security.saveOkx') }}</span>
            </button>
          </div>
        </footer>
      </article>
    </SettingsSection>

    <!-- OKX Market Health -->
    <SettingsSection :title="t('admin.security.healthTitle')" :icon="Activity">
      <template #actions>
        <span class="badge" :class="healthAllOk ? 'badge-up' : 'badge-warn'">
          {{ healthAllOk ? t('admin.security.healthOk') : t('admin.security.healthDegraded') }}
        </span>
        <button type="button" class="btn btn-quiet btn-sm" @click="loadMx()">
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
          :class="{ 'is-ok': h.allOk, 'is-unknown': h.unknown > 0 }"
        >
          <span class="sc-health-name">{{ h.name }}</span>
          <span class="sc-health-stat mono num">{{ h.ok }}/{{ h.total }} {{ t('admin.security.coinsUnit') }}</span>
          <span v-if="h.unknown" class="badge badge-warn">
            {{ t('admin.security.healthUnknownBadge', undefined, { count: h.unknown }) }}
          </span>
          <span v-if="h.avg_ms" class="sc-health-ms mono num">{{ h.avg_ms }}ms</span>
          <span v-if="h.testnet" class="badge">{{ t('admin.security.sandboxTag') }}</span>
        </div>
        <p v-if="healthUnknownTotal" class="sc-hint pad">{{ t('admin.security.healthUnknownNote') }}</p>
      </div>
    </SettingsSection>

    <!-- Strategy Plaza Sharing -->
    <SettingsSection :title="t('admin.security.plazaShareTitle')" :icon="Share2">
      <template #actions>
        <span class="badge mono" :class="!isUnifiedLive ? 'badge-warn' : plazaSettings.enabled ? 'badge-accent' : ''">
          {{ !isUnifiedLive ? t('admin.security.plazaDemoLocked') : plazaSettings.enabled ? t('admin.security.plazaActive') : t('admin.security.plazaOff') }}
        </span>
      </template>

      <div class="sc-group">
        <p v-if="!isUnifiedLive" class="sv-warn-line">
          <AlertTriangle :size="14" class="shrink-0" />
          <span>{{ t('admin.security.plazaLiveOnlyAlert') }}</span>
        </p>

        <div class="wb-toggle-row">
          <div class="wb-setting-meta">
            <span class="wb-setting-title">{{ t('admin.security.plazaEnableLabel') }}</span>
            <p class="wb-setting-desc">{{ t('admin.security.plazaShareDesc') }}</p>
          </div>
          <BaseSwitch
            v-model="plazaSettings.enabled"
            :disabled="!isUnifiedLive || savingPlaza"
            :label="t('admin.security.plazaEnableLabel')"
          />
        </div>

        <div class="wb-grid-2">
          <label class="sv-col">
            <span class="form-label">{{ t('admin.security.plazaNicknameLabel') }}</span>
            <input
              v-model="plazaSettings.nickname"
              type="text"
              class="field"
              maxlength="40"
              :disabled="!isUnifiedLive || savingPlaza"
              :placeholder="t('admin.security.plazaNicknamePlaceholder')"
            />
          </label>

          <div class="sv-col">
            <span class="form-label">{{ t('admin.security.plazaApiUrlLabel') }}</span>
            <div class="sv-url-row">
              <input
                type="text"
                readonly
                class="field mono"
                :aria-label="t('admin.security.plazaApiUrlLabel')"
                :value="plazaPublicUrl"
              />
              <button
                type="button"
                class="btn btn-quiet btn-sm shrink-0"
                :disabled="!plazaSettings.enabled || !isUnifiedLive"
                @click="copyPlazaUrl"
              >
                <Copy :size="13" />
                <span>{{ t('admin.security.plazaCopyUrl') }}</span>
              </button>
            </div>
          </div>
        </div>

        <div class="sv-privacy">
          <span class="form-label">{{ t('admin.security.plazaPrivacyCustom') }}</span>
          <div class="wb-grid-2">
            <label class="sv-chk-item">
              <input type="checkbox" class="sv-chk-box" v-model="plazaSettings.show_performance" :disabled="!isUnifiedLive || savingPlaza" />
              <span>{{ t('admin.security.plazaShowPerf') }}</span>
            </label>
            <label class="sv-chk-item">
              <input type="checkbox" class="sv-chk-box" v-model="plazaSettings.show_balance" :disabled="!isUnifiedLive || savingPlaza" />
              <span>{{ t('admin.security.plazaShowBalance') }}</span>
            </label>
            <label class="sv-chk-item">
              <input type="checkbox" class="sv-chk-box" v-model="plazaSettings.show_model" :disabled="!isUnifiedLive || savingPlaza" />
              <span>{{ t('admin.security.plazaShowModel') }}</span>
            </label>
            <label class="sv-chk-item">
              <input type="checkbox" class="sv-chk-box" v-model="plazaSettings.show_strategy_params" :disabled="!isUnifiedLive || savingPlaza" />
              <span>{{ t('admin.security.plazaShowParams') }}</span>
            </label>
          </div>
        </div>

        <div class="wb-toolbar">
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

    <!-- Plaza Card Preview Dialog -->
    <BaseDialog
      :open="showPlazaPreview"
      :title="t('admin.security.plazaPreviewTitle')"
      size="md"
      @close="showPlazaPreview = false"
    >
      <div v-if="loadingPlazaPreview" class="sv-preview-load">
        <Loader2 :size="24" class="animate-spin shrink-0" />
      </div>
      <div v-else-if="plazaPreviewData" class="sv-preview-box">
        <div class="wb-toolbar">
          <div class="sv-title-pack">
            <strong>{{ plazaPreviewData.node_info?.nickname || plazaSettings.nickname }}</strong>
            <span class="badge badge-accent">{{ t('admin.security.plazaVerifiedBadge') }}</span>
          </div>
          <span class="sv-dim mono">{{ plazaPreviewData.node_info?.system_version }}</span>
        </div>

        <div v-if="plazaPreviewData.performance?.visible" class="sv-perf-grid">
          <div class="sv-perf-cell">
            <span class="form-label">{{ t('admin.security.plazaRoi') }}</span>
            <strong class="sv-perf-val is-up mono">
              {{ plazaPreviewData.performance?.total_roi_pct >= 0 ? '+' : '' }}{{ plazaPreviewData.performance?.total_roi_pct }}%
            </strong>
          </div>
          <div class="sv-perf-cell">
            <span class="form-label">{{ t('admin.security.plazaWinRate') }}</span>
            <strong class="sv-perf-val mono">{{ plazaPreviewData.performance?.win_rate_pct }}%</strong>
          </div>
          <div class="sv-perf-cell">
            <span class="form-label">{{ t('admin.security.plazaTotalTrades') }}</span>
            <strong class="sv-perf-val mono">
              {{ plazaPreviewData.performance?.all_trades }} {{ t('admin.security.plazaTradeUnit') }}
            </strong>
          </div>
        </div>

        <div v-if="plazaPreviewData.model_specs?.visible" class="sv-dim">
          <span>{{ t('admin.security.plazaDriverModel') }}: </span>
          <strong class="mono">{{ plazaPreviewData.model_specs?.primary_model }}</strong>
          <span> ({{ plazaPreviewData.model_specs?.reasoning_effort }})</span>
        </div>

        <div v-if="plazaPreviewData.risk_settings?.visible" class="sv-dim">
          <span>{{ t('admin.security.plazaRiskConfig') }}: </span>
          <span class="mono">
            {{ t('admin.security.plazaRiskSummary', undefined, {
              min: plazaPreviewData.risk_settings?.min_leverage,
              max: plazaPreviewData.risk_settings?.max_leverage,
              pct: (Number(plazaPreviewData.risk_settings?.max_margin_equity_ratio || 0.35) * 100).toFixed(0),
            }) }}
          </span>
        </div>

        <div class="wb-toolbar">
          <button type="button" class="btn btn-quiet btn-sm" @click="copyStrategyCloneData">
            <Copy :size="13" />
            <span>{{ t('admin.security.plazaTestCopy') }}</span>
          </button>
          <button type="button" class="btn btn-primary btn-sm" @click="showPlazaPreview = false">
            {{ t('admin.security.plazaPreviewClose') }}
          </button>
        </div>
      </div>
    </BaseDialog>
  </div>
</template>

<style scoped>
.sv-stack,
.sc-group {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}
.sc-hint {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  margin: 0;
  font-size: var(--text-xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-description);
}
.sc-hint > svg {
  flex-shrink: 0;
  margin-top: 2px;
}
.sc-hint.pad {
  margin-top: var(--ds-space-2);
  padding-top: var(--ds-space-3);
  border-top: 1px solid var(--ds-color-border-subtle);
}
.sv-switch-pack {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-shrink: 0;
}
.sv-link-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: var(--ds-space-2);
  padding-top: var(--ds-space-3);
  border-top: 1px solid var(--ds-color-border-subtle);
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.sv-link-accent {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  font-weight: 600;
  color: var(--ds-color-brand);
  text-decoration: none;
}
.sv-link-accent:hover {
  text-decoration: underline;
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
  padding: var(--sp-5) var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-subtle);
}
.sc-venue-id {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  min-width: 0;
}
.sc-venue-name {
  margin: 0;
  font-size: var(--text-md);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.sc-venue-api {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.sc-venue-env-label {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.sc-venue-env-value {
  font-size: var(--text-base);
  color: var(--ds-color-text-primary);
}
.sc-venue-body {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
  padding: var(--ds-space-4);
}
.sc-env-indicator {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.sc-env-hint {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.sc-creds {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
}
.sc-creds-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
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
.sc-channel-box {
  padding: var(--sp-3) var(--ds-space-3);
  border: 1px dashed var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-1);
}
.sc-channel-btn {
  background: none;
  border: none;
  padding: 0;
  cursor: pointer;
  font-size: var(--text-base);
  color: var(--ds-color-brand);
  text-align: left;
}
.sc-channel-btn:hover {
  text-decoration: underline;
}
.sc-venue-foot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-subtle);
  background-color: var(--ds-color-bg-surface-1);
}
.sc-latency {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
}
.sc-venue-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  margin-left: auto;
}
.sc-health {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
}
.sc-health-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
  padding: var(--ds-space-2) var(--ds-space-3);
  border: 1px solid var(--ds-color-border-subtle);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
  font-size: var(--text-base);
}
.sc-health-name {
  font-weight: 600;
  color: var(--ds-color-text-primary);
  text-transform: uppercase;
}
.sc-health-row.is-ok {
  border-color: var(--up-line);
  background-color: var(--up-bg);
}
.sc-health-row.is-unknown {
  border-color: var(--warn-line);
  background-color: var(--warn-bg);
}
.sc-health-stat {
  color: var(--ds-color-text-secondary);
}
.sc-health-ms {
  color: var(--ds-color-text-description);
}
.sv-warn-line {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  margin: 0;
  padding: var(--ds-space-3);
  border-radius: var(--r-ctl);
  background-color: var(--warn-bg);
  color: var(--warn);
  font-size: var(--text-base);
}
.sv-col {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.sv-url-row {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
}
.sv-privacy {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding-top: var(--ds-space-3);
  border-top: 1px solid var(--ds-color-border-subtle);
}
.sv-chk-item {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  cursor: pointer;
  font-size: var(--text-base);
  color: var(--ds-color-text-secondary);
}
.sv-chk-box:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.sv-preview-load {
  padding: var(--ds-space-8);
  display: flex;
  justify-content: center;
}
.sv-preview-box {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}
.sv-title-pack {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
}
.sv-perf-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: var(--ds-space-3);
  padding: var(--ds-space-3) 0;
  border-top: 1px solid var(--ds-color-border-subtle);
  border-bottom: 1px solid var(--ds-color-border-subtle);
  text-align: center;
}
.sv-perf-cell {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.sv-perf-val {
  font-size: var(--text-lg);
  color: var(--ds-color-text-primary);
}
.sv-perf-val.is-up {
  color: var(--up);
}
.sv-dim {
  font-size: var(--text-xs);
  color: var(--ds-color-text-description);
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
