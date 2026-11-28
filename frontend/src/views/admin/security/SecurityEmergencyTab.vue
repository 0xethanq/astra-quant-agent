<script setup lang="ts">
import { AlertTriangle, Loader2, Radar, Save, Zap } from 'lucide-vue-next';
import SettingsSection from '../../../components/admin/page-parts/SettingsSection.vue';
import BaseDialog from '../../../components/base/BaseDialog.vue';
import BaseEmpty from '../../../components/base/BaseEmpty.vue';
import BaseSwitch from '../../../components/base/BaseSwitch.vue';
import { useI18n } from '../../../composables/useI18n';
import { fmtDateTime } from '../../../utils/format';
import { envBadge } from '../securityLogic';
import { useSecurityCtx } from './useSecurityAdmin';

const { t } = useI18n();
const {
  closeModal,
  closePassword,
  closePhraseInput,
  closePhraseOk,
  closeReady,
  closing,
  confirmClose,
  loadPositions,
  manualClose,
  openClose,
  saveManualClose,
  snapshot,
  snapshotError,
  snapshotState,
} = useSecurityCtx();
</script>

<template>
  <div class="se-stack">
    <SettingsSection :title="t('admin.security.manualTitle')" :icon="Zap">
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

    <SettingsSection :title="t('admin.security.snapshotTitle')" :icon="Radar">
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

        <article v-for="p in snapshot.positions" :key="p.instId + p.posSide" class="sc-row sc-pos-row">
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
            <button type="button" class="btn btn-quiet btn-sm is-danger" @click="openClose(p)">
              {{ t('admin.security.quickClose') }}
            </button>
          </span>
        </article>
      </div>
    </SettingsSection>

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
  </div>
</template>

<style scoped>
.se-stack {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}
.sc-check {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  font-size: var(--text-base);
  color: var(--ds-color-text-description);
  cursor: pointer;
  border-radius: var(--r-ctl);
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
  gap: var(--sp-5);
  padding: var(--ds-space-3) var(--ds-space-4);
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
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ds-color-text-secondary);
}
.sc-switch-row.is-danger .sc-switch-text {
  color: var(--warn);
}
.sc-loading {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  font-size: var(--text-base);
  color: var(--ds-color-text-description);
}
.sc-loading.is-error {
  color: var(--down);
  padding-left: var(--ds-space-2);
  border-left: 2px solid var(--down);
}
.sc-snap-meta {
  display: flex;
  align-items: baseline;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
  margin-bottom: var(--ds-space-3);
  font-size: var(--text-xs);
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
.sc-rows {
  display: flex;
  flex-direction: column;
  border: 1px solid var(--ds-color-border-subtle);
  border-radius: var(--r-ctl);
  overflow: hidden;
}
.sc-row {
  display: grid;
  grid-template-columns: 2fr 1.2fr 1fr 1.2fr auto;
  align-items: center;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3) var(--ds-space-4);
  background-color: var(--ds-color-bg-surface-inset);
  border-top: 1px solid var(--ds-color-border-subtle);
  font-size: var(--text-base);
}
.sc-row:first-child {
  border-top: 0;
}
.sc-row:hover:not(.sc-row-head) {
  background-color: var(--ds-color-bg-hover);
}
.sc-row-head {
  background-color: var(--ds-color-bg-surface-1);
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-description);
}
.sc-pos-id {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  min-width: 0;
}
.sc-pos-id b {
  color: var(--ds-color-text-primary);
}
.sc-contracts,
.sc-mode {
  color: var(--ds-color-text-secondary);
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
.sc-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
@media (max-width: 900px) {
  .sc-pos-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .sc-row-head {
    display: none;
  }
  .sc-actions {
    grid-column: 2;
    justify-content: flex-end;
  }
}
.sc-close-desc {
  font-size: var(--text-base);
  line-height: var(--leading-body);
  color: var(--ds-color-text-secondary);
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
  padding: 1px var(--sp-3);
  border-radius: var(--r-ctl);
  background-color: var(--down-bg);
  color: var(--down);
  font-family: var(--ds-font-mono);
  font-weight: 600;
}
</style>
