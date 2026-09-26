<script setup lang="ts">
/**
 * PageHeader.vue · 页面头部基准件
 * ---------------------------------------------------------------------------
 * DSH 语汇：标题用负字距大字，说明文字降一档并限宽 80ch，
 * 动作区右对齐且可横向滚动（窄屏不换行挤压）。无底部分隔线 —— 层级交给留白。
 * 契约：props（title / description / stacked）与 actions 插槽保持向后兼容。
 */
defineProps<{
  title: string
  description?: string
  stacked?: boolean
}>()
</script>

<template>
  <header class="ph" :class="{ 'is-stacked': stacked }">
    <div class="ph-main">
      <h1 class="ph-title">{{ title }}</h1>
      <p v-if="description" class="ph-desc">{{ description }}</p>
    </div>
    <div v-if="$slots.actions" class="ph-actions">
      <slot name="actions" />
    </div>
  </header>
</template>

<style scoped>
.ph {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-3);
  animation: astra-enter var(--dur-slow) var(--ease-out) backwards;
}
@media (min-width: 640px) {
  .ph:not(.is-stacked) {
    flex-direction: row;
    align-items: flex-start;
    justify-content: space-between;
  }
}
.ph.is-stacked {
  flex-direction: column;
}

.ph-main {
  min-width: 0;
}
.ph-title {
  font-size: var(--text-xl);
  font-weight: 600;
  letter-spacing: var(--track-display);
  color: var(--ds-color-text-primary);
}
.ph-desc {
  margin-top:6px;
  max-width: 80ch;
  font-size: var(--text-xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-description);
}

.ph-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-shrink: 0;
  max-width: 100%;
  overflow-x: auto;
  padding-bottom: 1px;
}
</style>
