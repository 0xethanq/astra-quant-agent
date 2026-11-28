<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue';
import { Check, CheckCircle2, FileDiff, Loader2, RotateCcw, ShieldAlert, XCircle } from 'lucide-vue-next';
import CopyButton from '../../../components/base/CopyButton.vue';
import { useI18n } from '../../../composables/useI18n';
import { useAuthStore } from '../../../stores/auth';
import {
  type AgentProposal,
  DIFF_LINE_CLASS,
  collectRequiredPhrases,
  formatDiffValue,
  itemIdOf,
  missingConfirmations,
  parseUnifiedDiff,
} from './agentLogic';

const props = defineProps<{
  proposal: AgentProposal;
  busy?: boolean;
}>();

const emit = defineEmits<{
  (e: 'apply', payload: {
    proposalId: string;
    selectedItemIds: string[];
    confirmations: Record<string, string>;
  }): void;
  (e: 'reject', payload: { proposalId: string }): void;
  (e: 'rollback', payload: { proposalId: string }): void;
}>();

const { t } = useI18n();
const auth = useAuthStore();

const selectedIds = ref<string[]>([]);
const phraseInputs = reactive<Record<string, string>>({});

watch(
  () => props.proposal.items,
  (items) => {
    selectedIds.value = (items || []).map(itemIdOf).filter(Boolean);
  },
  { immediate: true },
);

const isPending = computed(() => props.proposal.status === 'pending');
const isRolledBack = computed(() => !!(props.proposal.rolled_back || props.proposal.applied_result?.rolled_back));
const canRollback = computed(() =>
  auth.isSuperadmin
  && !props.busy
  && !isRolledBack.value
  && (props.proposal.status === 'applied' || props.proposal.status === 'partially_applied'),
);

const statusLabel = computed(() => {
  if (isRolledBack.value) return t('admin.agent.proposalRolledBackBadge');
  const s = props.proposal.status;
  if (s === 'applied') return t('admin.agent.proposalStatusApplied');
  if (s === 'partially_applied') return t('admin.agent.proposalStatusPartial');
  if (s === 'rejected') return t('admin.agent.proposalStatusRejected');
  return t('admin.agent.proposalStatusPending');
});

const statusBadgeClass = computed(() => {
  if (isRolledBack.value) return 'badge-warn';
  const s = props.proposal.status;
  if (s === 'applied') return 'badge-up';
  if (s === 'partially_applied') return 'badge-warn';
  if (s === 'rejected' || s === 'failed') return 'badge-down';
  return 'badge-accent';
});

const requiredPhrases = computed(() =>
  collectRequiredPhrases(props.proposal.items || [], selectedIds.value),
);

const missingPhrases = computed(() =>
  missingConfirmations(props.proposal.items || [], selectedIds.value, phraseInputs),
);

const canApply = computed(() =>
  auth.isSuperadmin
  && isPending.value
  && !props.busy
  && selectedIds.value.length > 0
  && missingPhrases.value.length === 0,
);

function toggleItem(id: string) {
  if (!isPending.value) return;
  const idx = selectedIds.value.indexOf(id);
  if (idx >= 0) {
    selectedIds.value = selectedIds.value.filter((x) => x !== id);
  } else {
    selectedIds.value = [...selectedIds.value, id];
  }
}

function selectAll() {
  if (!isPending.value) return;
  selectedIds.value = (props.proposal.items || []).map(itemIdOf).filter(Boolean);
}

function clearSelection() {
  if (!isPending.value) return;
  selectedIds.value = [];
}

function submitApply() {
  if (!canApply.value) return;
  const confirmations: Record<string, string> = {};
  for (const phrase of requiredPhrases.value) {
    confirmations[phrase] = String(phraseInputs[phrase] || '').trim();
  }
  emit('apply', {
    proposalId: props.proposal.id,
    selectedItemIds: [...selectedIds.value],
    confirmations,
  });
}

function submitReject() {
  if (!auth.isSuperadmin || !isPending.value || props.busy) return;
  emit('reject', { proposalId: props.proposal.id });
}

function submitRollback() {
  if (!canRollback.value) return;
  emit('rollback', { proposalId: props.proposal.id });
}

function resultForItem(itemId: string) {
  const rows = props.proposal.applied_result?.results || [];
  return rows.find((r) => r.item_id === itemId) || null;
}

function isPhraseInvalid(phrase: string): boolean {
  const val = String(phraseInputs[phrase] || '').trim();
  if (!val) return false;
  return val.toUpperCase() !== phrase.toUpperCase();
}
</script>

<template>
  <article class="card ap-card">
    <header class="card-head ap-head">
      <div class="ap-title-wrap">
        <span class="ap-eyebrow">
          <FileDiff :size="13" />
          <span>{{ t('admin.agent.proposalCardTitle') }}</span>
        </span>
        <h3 class="ap-title">{{ props.proposal.title || props.proposal.id }}</h3>
      </div>
      <div class="ap-head-meta">
        <span class="badge mono" :class="statusBadgeClass">{{ statusLabel }}</span>
      </div>
    </header>

    <div class="ap-body">
      <div v-if="isPending && (props.proposal.items || []).length > 1" class="ap-toolbar">
        <span class="ap-count mono num">
          {{ t('admin.agent.proposalAppliedItemsCount', undefined, { selected: selectedIds.length, total: props.proposal.items.length }) }}
        </span>
        <div class="ap-toolbar-actions">
          <button type="button" class="btn btn-quiet btn-sm" @click="selectAll">
            {{ t('admin.agent.proposalSelectAll') }}
          </button>
          <button type="button" class="btn btn-quiet btn-sm" @click="clearSelection">
            {{ t('admin.agent.proposalClearSelection') }}
          </button>
        </div>
      </div>

      <div v-for="item in props.proposal.items" :key="itemIdOf(item)" class="ap-item">
        <div class="ap-item-head">
          <label class="ap-check-label">
            <input
              v-if="isPending"
              type="checkbox"
              :checked="selectedIds.includes(itemIdOf(item))"
              :aria-label="t('admin.agent.proposalSelectItemAria', undefined, { title: item.title })"
              @change="toggleItem(itemIdOf(item))"
            />
            <span class="badge mono">{{ item.domain }}</span>
            <span class="ap-item-title">{{ item.title }}</span>
            <span v-if="item.high_risk" class="badge badge-warn">
              <ShieldAlert :size="11" />
              <span>{{ item.required_phrase }}</span>
            </span>
          </label>
          <span
            v-if="resultForItem(itemIdOf(item))"
            class="badge mono"
            :class="resultForItem(itemIdOf(item))?.ok ? 'badge-up' : 'badge-down'"
          >
            <CheckCircle2 v-if="resultForItem(itemIdOf(item))?.ok" :size="11" />
            <XCircle v-else :size="11" />
            <span>{{ resultForItem(itemIdOf(item))?.ok ? t('common.ok') : (resultForItem(itemIdOf(item))?.detail || resultForItem(itemIdOf(item))?.error) }}</span>
          </span>
        </div>

        <p v-if="item.reason" class="ap-item-reason">{{ item.reason }}</p>

        <ul v-if="(item.warnings || []).length" class="ap-warnings">
          <li v-for="(w, wi) in item.warnings" :key="wi">{{ w }}</li>
        </ul>

        <div
          v-if="item.diff_type === 'text' && typeof item.diff === 'string'"
          class="diff-view"
          tabindex="0"
        >
          <span
            v-for="(dline, dIdx) in parseUnifiedDiff(item.diff)"
            :key="dIdx"
            class="diff-line"
            :class="DIFF_LINE_CLASS[dline.kind]"
          >{{ dline.text || ' ' }}</span>
        </div>

        <div
          v-else-if="Array.isArray(item.diff) && item.diff.length"
          class="ap-kv-table"
        >
          <div v-for="(row, ri) in item.diff" :key="ri" class="ap-kv-row">
            <span class="ap-kv-key">{{ row.label || row.field }}</span>
            <span class="ap-kv-before mono num">{{ formatDiffValue(row.before) }}</span>
            <span class="ap-kv-arrow mono">-&gt;</span>
            <span class="ap-kv-after mono num">{{ formatDiffValue(row.after) }}</span>
          </div>
        </div>

        <p v-else class="ap-empty-diff">{{ t('admin.agent.proposalNoDiff') }}</p>
      </div>

      <div v-if="isPending && requiredPhrases.length" class="ap-phrases">
        <label v-for="phrase in requiredPhrases" :key="phrase" class="field-stack">
          <span class="form-label">
            {{ t('admin.agent.proposalConfirmLabel') }}: <code class="mono">{{ phrase }}</code>
          </span>
          <input
            v-model="phraseInputs[phrase]"
            type="text"
            autocomplete="off"
            spellcheck="false"
            class="field mono"
            :class="{ 'is-bad': isPhraseInvalid(phrase) }"
            :aria-invalid="isPhraseInvalid(phrase) ? 'true' : undefined"
            :aria-label="t('admin.agent.proposalConfirmAria', undefined, { phrase })"
            :placeholder="t('admin.agent.proposalConfirmPlaceholder', undefined, { phrase })"
          />
        </label>
      </div>

      <div v-if="props.proposal.snapshot_hash" class="ap-snap-bar">
        <span class="ap-snap-label">{{ t('admin.agent.proposalSnapshotHash') }}</span>
        <code class="mono">{{ props.proposal.snapshot_hash }}</code>
        <CopyButton :text="props.proposal.snapshot_hash" />
      </div>
    </div>

    <footer v-if="isPending" class="ap-foot">
      <template v-if="auth.isSuperadmin">
        <button
          type="button"
          class="btn btn-primary btn-sm"
          :disabled="!canApply"
          @click="submitApply"
        >
          <Loader2 v-if="props.busy" :size="13" class="animate-spin shrink-0" />
          <Check v-else :size="13" />
          <span>{{ props.busy ? t('admin.agent.proposalApplying') : t('admin.agent.proposalApply') }}</span>
        </button>
        <button
          type="button"
          class="btn btn-ghost btn-sm is-danger"
          :disabled="props.busy"
          @click="submitReject"
        >
          <XCircle :size="13" />
          <span>{{ t('admin.agent.proposalReject') }}</span>
        </button>
      </template>
      <p v-else class="ap-readonly">{{ t('admin.agent.proposalReadonlyHint') }}</p>
    </footer>
    <footer v-else-if="canRollback" class="ap-foot">
      <button
        type="button"
        class="btn btn-ghost btn-sm"
        :disabled="props.busy"
        @click="submitRollback"
      >
        <Loader2 v-if="props.busy" :size="13" class="animate-spin shrink-0" />
        <RotateCcw v-else :size="13" />
        <span>{{ props.busy ? t('admin.agent.proposalRollingBack') : t('admin.agent.proposalRollback') }}</span>
      </button>
    </footer>
  </article>
</template>

<style scoped>
.ap-card {
  border-color: var(--accent-line);
}
.ap-head {
  gap: var(--ds-space-3);
}
.ap-title-wrap {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-1);
  min-width: 0;
}
.ap-eyebrow {
  display: inline-flex;
  align-items: center;
  gap: var(--ds-space-1);
  font-size: var(--text-4xs);
  color: var(--accent);
  font-weight: 600;
}
.ap-title {
  margin: 0;
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ap-head-meta {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-shrink: 0;
}
.ap-body {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-3);
  padding: var(--ds-space-3) var(--ds-space-4);
}
.ap-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
  padding-bottom: var(--ds-space-2);
  border-bottom: 1px solid var(--ds-color-border-subtle);
}
.ap-count {
  font-size: var(--text-4xs);
  color: var(--ds-color-text-description);
}
.ap-toolbar-actions {
  display: flex;
  gap: var(--ds-space-2);
}
.ap-item {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.ap-item + .ap-item {
  padding-top: var(--ds-space-3);
  border-top: 1px solid var(--ds-color-border-subtle);
}
.ap-item-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.ap-check-label {
  display: inline-flex;
  align-items: center;
  gap: var(--ds-space-2);
  cursor: pointer;
}
.ap-item-title {
  font-size: var(--text-xs);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ap-item-reason {
  margin: 0;
  font-size: var(--text-xs);
  color: var(--ds-color-text-secondary);
  line-height: var(--leading-body);
}
.ap-warnings {
  margin: 0;
  padding: var(--sp-3) var(--ds-space-3);
  border: 1px solid var(--warn-line);
  border-radius: var(--r-ctl);
  background-color: var(--warn-bg);
  color: var(--warn);
  font-size: var(--text-xs);
  list-style: none;
}
.ap-kv-table {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.ap-kv-row {
  display: grid;
  grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr) auto minmax(0, 1fr);
  align-items: center;
  gap: var(--ds-space-2);
  padding: var(--sp-3) var(--ds-space-3);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
  font-size: var(--text-xs);
}
.ap-kv-key {
  color: var(--ds-color-text-primary);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ap-kv-before {
  color: var(--down);
  word-break: break-all;
}
.ap-kv-arrow {
  color: var(--ds-color-text-placeholder);
}
.ap-kv-after {
  color: var(--up);
  font-weight: 600;
  word-break: break-all;
}
.ap-empty-diff {
  margin: 0;
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
.ap-phrases {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3);
  border: 1px solid var(--warn-line);
  border-radius: var(--r-ctl);
  background-color: var(--warn-bg);
}
.ap-snap-bar {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
  padding-top: var(--ds-space-2);
  border-top: 1px solid var(--ds-color-border-subtle);
  font-size: var(--text-4xs);
  color: var(--ds-color-text-description);
}
.ap-snap-label {
  font-weight: 500;
  color: var(--ds-color-text-secondary);
}
.ap-foot {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
  padding: var(--sp-4) var(--ds-space-4);
  border-top: 1px solid var(--ds-color-border-subtle);
  background-color: var(--ds-color-bg-surface-inset);
}
.ap-readonly {
  margin: 0;
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
@media (max-width: 720px) {
  .ap-kv-row {
    grid-template-columns: 1fr;
  }
  .ap-kv-arrow {
    display: none;
  }
}
</style>
