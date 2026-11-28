<script setup lang="ts">
/**
 * PageHeader.vue · 控制台页面头部基准件 (v9.2.0)
 * ---------------------------------------------------------------------------
 * · 标准态：24px 负字距大标题 + 14px 清晰说明 + 右对齐动作槽
 * · `compact`：用于 AI 指挥台单行沉浸顶栏（保留 h1 语义与动作区，无多余边距底线）
 * · `embedded`：被吸收为宿主页页签时自动降级为紧凑分节头（保留 actions 插槽）
 */
defineProps<{
  title: string
  description?: string
  badge?: string
  stacked?: boolean
  embedded?: boolean
  compact?: boolean
}>()
</script>

<template>
  <header
    class="ph"
    :class="{ 'is-stacked': stacked, 'is-embedded': embedded, 'is-compact': compact }"
  >
    <div class="ph-main">
      <div class="ph-title-row">
        <component :is="embedded ? 'h2' : 'h1'" class="ph-title">{{ title }}</component>
        <span v-if="badge" class="badge badge-accent mono ph-badge">{{ badge }}</span>
      </div>
      <p v-if="description && !embedded && !compact" class="ph-desc">{{ description }}</p>
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
  padding-bottom: var(--ds-space-4);
  border-bottom: 1px solid var(--ds-color-border-subtle);
  animation: astra-enter var(--dur-slow) var(--ease-out) backwards;
}
.ph-title-row {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-wrap: wrap;
}
.ph-badge {
  font-size: var(--text-xs);
}
@media (min-width: 640px) {
  .ph:not(.is-stacked) {
    flex-direction: row;
    align-items: center;
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
  margin-top: var(--sp-2);
  max-width: 80ch;
  font-size: var(--text-xs);
  line-height: var(--leading-body);
  color: var(--ds-color-text-description);
}

.ph.is-embedded {
  gap: var(--ds-space-2);
  padding-bottom: var(--ds-space-2);
  border-bottom: 0;
}
.ph.is-embedded .ph-title {
  font-size: var(--text-base);
  color: var(--ds-color-text-primary);
}

.ph.is-compact {
  flex-direction: row;
  align-items: center;
  gap: var(--ds-space-2);
  padding-bottom: 0;
  border-bottom: 0;
  animation: none;
}
.ph.is-compact .ph-title {
  font-size: var(--text-base);
  letter-spacing: var(--track-title);
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
