<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { ExternalLink, Gift, Globe, ShieldCheck } from 'lucide-vue-next';
import BaseDialog from '../base/BaseDialog.vue';
import CopyButton from '../base/CopyButton.vue';
import { useUi } from '../../composables/useUi';
import { useI18n } from '../../composables/useI18n';
import {
  resolveChannelUrl,
  useReferralChannels,
  type MirrorRegion,
} from '../../composables/useReferralChannels';
import { SKILLHUB_REBATES_URL } from '../../config/version';
import { trackEvent } from '../../utils/analytics';

const { rebateOpen } = useUi();
const { t, currentLocale } = useI18n();
const { channels, partnerChannels, load: loadChannels } = useReferralChannels();

const mirror = ref<MirrorRegion>(currentLocale.value === 'zh-CN' ? 'cn' : 'global');

onMounted(loadChannels);

const allChannels = computed(() => {
  const combined = [...channels.value, ...partnerChannels.value];
  return combined.map((ch) => ({
    ...ch,
    isApiSupported: ch.key === 'okx',
    href: resolveChannelUrl(ch, mirror.value),
  }));
});
</script>

<template>
  <BaseDialog
    :open="rebateOpen"
    :title="t('dash.about.rebateModal.title')"
    :desc="t('dash.about.rebateModal.desc')"
    size="md"
    @close="rebateOpen = false"
  >
    <template #title>
      <div class="flex items-center gap-2.5">
        <div
          class="flex h-8 w-8 items-center justify-center rounded-lg border border-emerald-500/30 bg-emerald-500/10 text-emerald-400"
        >
          <Gift class="h-4 w-4" aria-hidden="true" />
        </div>
        <div>
          <h2 class="text-sm font-semibold" style="color: var(--ink-1)">{{ t('dash.about.rebateModal.title') }}</h2>
          <p class="text-xs text-[var(--ink-3)] mt-0.5">{{ t('dash.about.rebateModal.desc') }}</p>
        </div>
      </div>
    </template>

    <div class="flex items-center justify-between gap-2 pb-3 border-b" style="border-color: var(--line-1)">
      <div class="flex items-center gap-1.5 text-xs" style="color: var(--ink-2)">
        <Globe class="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
        <span>{{ t('landing.referral.mirrorLabel') }}</span>
      </div>
      <div class="inline-flex rounded-lg border p-0.5" style="border-color: var(--line-2); background: var(--surface-2)">
        <button
          type="button"
          class="h-7 px-2.5 rounded-md text-xs font-medium cursor-pointer transition-colors"
          :class="mirror === 'cn' ? 'bg-[var(--surface-1)] text-emerald-400 font-semibold' : 'text-[var(--ink-2)] hover:text-[var(--ink-1)]'"
          @click="mirror = 'cn'"
        >
          {{ t('dash.about.rebateModal.mirrorCn') }}
        </button>
        <button
          type="button"
          class="h-7 px-2.5 rounded-md text-xs font-medium cursor-pointer transition-colors"
          :class="mirror === 'global' ? 'bg-[var(--surface-1)] text-emerald-400 font-semibold' : 'text-[var(--ink-2)] hover:text-[var(--ink-1)]'"
          @click="mirror = 'global'"
        >
          {{ t('dash.about.rebateModal.mirrorGlobal') }}
        </button>
      </div>
    </div>

    <div class="mt-3 space-y-2.5">
      <div
        v-for="ch in allChannels"
        :key="ch.key"
        class="card-flat p-3 flex flex-col gap-2.5 border"
        :class="ch.isApiSupported ? 'border-emerald-500/35' : 'border-[var(--line-1)]'"
      >
        <div class="flex items-center justify-between gap-2">
          <div class="flex items-center gap-2 flex-wrap">
            <span class="text-sm font-bold font-mono" style="color: var(--ink-1)">{{ ch.name }}</span>
            <span
              class="rounded px-2 py-0.5 text-3xs font-mono border"
              :class="ch.isApiSupported
                ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-400'
                : 'bg-[var(--surface-2)] border-[var(--line-2)] text-[var(--ink-3)]'"
            >
              {{ ch.isApiSupported ? t('landing.referral.okxBadge') : t('landing.referral.partnerBadge') }}
            </span>
          </div>
          <span
            v-if="ch.rebate"
            class="rounded-md px-2 py-0.5 text-xs font-mono font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20"
          >
            {{ ch.rebate }} {{ t('landing.referral.rebateRateSuffix') }}
          </span>
        </div>

        <p class="text-xs leading-relaxed" style="color: var(--ink-3)">
          {{ ch.isApiSupported ? t('landing.referral.okxOldUserNote') : t('landing.referral.partnerNote') }}
        </p>

        <div class="flex items-center justify-between gap-2 pt-1">
          <div
            v-if="ch.code"
            class="flex items-center gap-2 rounded-lg border px-2.5 py-1.5 bg-[var(--surface-1)]"
            style="border-color: var(--line-2)"
          >
            <span class="text-3xs" style="color: var(--ink-3)">{{ t('landing.referral.codeLabel') }}</span>
            <span class="num text-xs font-bold font-mono" style="color: var(--ink-1)">{{ ch.code }}</span>
            <CopyButton :text="ch.code" />
          </div>
          <div class="flex items-center gap-1.5 ml-auto">
            <CopyButton :text="ch.href" />
            <a
              :href="ch.href"
              target="_blank"
              rel="noopener noreferrer"
              class="btn btn-sm inline-flex items-center gap-1.5"
              :class="ch.isApiSupported ? 'btn-primary' : 'btn-quiet'"
              @click="trackEvent('rebate_click', { exchange: ch.key, placement: 'rebate_modal', mirror })"
            >
              <span>{{ t('landing.referral.openAccount') }}</span>
              <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
              <ExternalLink class="h-3.5 w-3.5" aria-hidden="true" />
            </a>
          </div>
        </div>
      </div>
    </div>

    <div class="mt-3 rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2 flex items-start gap-2 text-xs text-amber-400 leading-relaxed">
      <ShieldCheck class="h-4 w-4 shrink-0 mt-0.5" aria-hidden="true" />
      <span>{{ t('landing.referral.compatibilityNotice') }}</span>
    </div>

    <div class="mt-3 pt-2.5 border-t flex items-center justify-between" style="border-color: var(--line-1)">
      <a
        :href="SKILLHUB_REBATES_URL"
        target="_blank"
        rel="noopener noreferrer"
        class="link text-xs inline-flex items-center gap-1.5"
        @click="trackEvent('crosslink_click', { target: 'skillhub_rebates', placement: 'rebate_modal' })"
      >
        <span>{{ t('dash.about.rebateModal.footerLink') }}</span>
        <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
        <ExternalLink class="h-3.5 w-3.5" aria-hidden="true" />
      </a>
    </div>
  </BaseDialog>
</template>
