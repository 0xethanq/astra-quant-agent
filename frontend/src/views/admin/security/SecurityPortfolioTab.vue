<script setup lang="ts">
import { RouterLink } from 'vue-router';
import { Bot, Layers, Loader2, Save, Wallet } from 'lucide-vue-next';
import SettingsSection from '../../../components/admin/page-parts/SettingsSection.vue';
import BaseEmpty from '../../../components/base/BaseEmpty.vue';
import { useI18n } from '../../../composables/useI18n';
import { useSecurityCtx } from './useSecurityAdmin';

const { t } = useI18n();
const {
  auth,
  capitalAmountOk,
  capitalConfirm,
  capitalConfirmOk,
  instLimits,
  instruments,
  newCapital,
  saveCapital,
  savingCapital,
} = useSecurityCtx();
</script>

<template>
  <div class="sp-stack">
    <SettingsSection :title="t('admin.security.capitalTitle')" :icon="Wallet">
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

    <SettingsSection :title="t('admin.security.poolTitle')" :icon="Layers">
      <template #actions>
        <RouterLink to="/admin/agent" class="btn btn-ghost btn-sm">
          <Bot :size="14" />
          <span>{{ t('admin.security.goToAgent') }}</span>
        </RouterLink>
      </template>

      <p class="sc-hint">{{ t('admin.security.poolReadonlyHint') }}</p>

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
          <span />
        </article>
      </div>

      <p class="sc-hint pad">{{ t('admin.security.poolFooter', undefined, { max: instLimits.maximum }) }}</p>
    </SettingsSection>
  </div>
</template>

<style scoped>
.sp-stack {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}
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
.sc-hint {
  margin: 0 0 var(--ds-space-3);
  font-size: var(--text-xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-description);
}
.sc-hint.pad {
  margin: var(--ds-space-3) 0 0;
  padding-top: var(--ds-space-3);
  border-top: 1px solid var(--ds-color-border-subtle);
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
  grid-template-columns: 1.5fr 1.5fr 1fr 1.5fr auto;
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
.sc-inst {
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.sc-name {
  color: var(--ds-color-text-secondary);
}
.sc-type {
  color: var(--ds-color-text-description);
}
.sc-badges {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
@media (max-width: 900px) {
  .sc-row {
    grid-template-columns: minmax(0, 1fr) auto;
  }
  .sc-row-head {
    display: none;
  }
  .sc-badges {
    grid-column: 2;
    justify-content: flex-end;
  }
}
</style>
