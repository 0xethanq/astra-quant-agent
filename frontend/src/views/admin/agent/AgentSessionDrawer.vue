<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue';
import { MessageSquare, Plus, Trash2, X } from 'lucide-vue-next';
import { useI18n } from '../../../composables/useI18n';

const props = defineProps<{
  sessions: any[];
  activeSessionId: string;
}>();

const emit = defineEmits<{
  (e: 'close'): void;
  (e: 'select', sessionId: string): void;
  (e: 'create'): void;
  (e: 'delete', sessionId: string): void;
}>();

const { t } = useI18n();

function onKeydown(ev: KeyboardEvent) {
  if (ev.key === 'Escape') {
    emit('close');
  }
}

onMounted(() => {
  window.addEventListener('keydown', onKeydown);
});

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown);
});
</script>

<template>
  <div class="ag-drawer-backdrop">
    <div class="ag-drawer-scrim" @click="emit('close')" />
    <aside class="ag-drawer" :aria-label="t('admin.agent.historyDrawerAria')">
      <header class="ag-drawer-head">
        <span class="ag-drawer-title">{{ t('admin.agent.sessionsTitle') }}</span>
        <div class="ag-drawer-actions">
          <button type="button" class="btn btn-primary btn-sm" @click="emit('create')">
            <Plus :size="14" />
            <span>{{ t('admin.agent.newSession') }}</span>
          </button>
          <button
            type="button"
            class="btn btn-quiet btn-icon btn-sm"
            :aria-label="t('admin.agent.closeHistoryDrawer')"
            :title="t('admin.agent.closeHistoryDrawer')"
            @click="emit('close')"
          >
            <X :size="15" />
          </button>
        </div>
      </header>

      <div class="ag-drawer-list scroll-area">
        <p v-if="!props.sessions.length" class="ag-drawer-empty">
          {{ t('admin.agent.sessionsEmpty') }}
        </p>
        <div
          v-for="sess in props.sessions"
          :key="sess.id"
          class="ag-drawer-row"
          :class="{ 'is-active': sess.id === props.activeSessionId }"
        >
          <button
            type="button"
            class="ag-drawer-select"
            @click="emit('select', sess.id)"
          >
            <MessageSquare :size="14" class="shrink-0" />
            <span class="truncate">{{ sess.title || t('admin.agent.sessionDefaultTitle') }}</span>
          </button>
          <button
            type="button"
            class="btn btn-quiet btn-icon btn-sm is-danger"
            :aria-label="t('admin.agent.deleteSessionAria')"
            :title="t('admin.agent.deleteSessionTitle')"
            @click="emit('delete', sess.id)"
          >
            <Trash2 :size="13" />
          </button>
        </div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.ag-drawer-backdrop {
  position: fixed;
  inset: 0;
  z-index: 45;
  display: flex;
}
.ag-drawer-scrim {
  position: absolute;
  inset: 0;
  background-color: var(--scrim-strong, rgba(0, 0, 0, 0.45));
}
.ag-drawer {
  position: relative;
  z-index: 1;
  width: 320px;
  max-width: 88vw;
  height: 100%;
  display: flex;
  flex-direction: column;
  background-color: var(--ds-color-bg-surface-1);
  border-right: 1px solid var(--ds-color-border-strong);
}
.ag-drawer-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--ds-space-2);
  padding: var(--ds-space-3) var(--ds-space-4);
  min-height: 52px;
  border-bottom: 1px solid var(--ds-color-border-subtle);
}
.ag-drawer-title {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.ag-drawer-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-1);
}
.ag-drawer-list {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--ds-space-2);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.ag-drawer-empty {
  padding: var(--ds-space-4);
  margin: 0;
  font-size: var(--text-base);
  line-height: 1.55;
  color: var(--ds-color-text-muted);
}
.ag-drawer-row {
  display: flex;
  align-items: center;
  gap: var(--ds-space-1);
  padding: var(--sp-1);
  border-radius: var(--r-ctl);
  border: 1px solid transparent;
  transition: background-color var(--dur-fast) var(--ease-out), border-color var(--dur-fast) var(--ease-out);
}
.ag-drawer-row:hover {
  background-color: var(--ds-color-bg-surface-inset);
}
.ag-drawer-row.is-active {
  background-color: var(--ds-color-brand-subtle);
  border-color: var(--accent-line);
}
.ag-drawer-select {
  flex: 1;
  min-width: 0;
  min-height: 36px;
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  padding: var(--sp-2) var(--sp-4);
  font-size: var(--text-base);
  color: var(--ds-color-text-primary);
  text-align: left;
}
</style>
