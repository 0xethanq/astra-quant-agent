<script setup lang="ts">
/**
 * PageHeader.vue · 页面头部基准件
 * ---------------------------------------------------------------------------
 * DSH 语汇：标题用负字距大字，说明文字降一档并限宽 80ch，
 * 动作区右对齐且可横向滚动（窄屏不换行挤压）。无底部分隔线 —— 层级交给留白。
 * 契约：props（title / description / stacked / embedded）与 actions 插槽保持向后兼容。
 *
 * `embedded`（2026-09-30 后台精简）：页面被吸收为**宿主页的一个页签**时置真。
 * 此时宿主页负责大标题与页签标签，本组件降级为紧凑行 —— 标题降一档、说明收起，
 * 但 **actions 插槽原样渲染**。这条是硬要求：被吸收页的按钮（刷新 / 沙箱 / 新建 /
 * 归档 / 检查更新 …）必须一个不丢，所以"隐藏整个页头"的写法是错的。
 */
defineProps<{
  title: string
  description?: string
  stacked?: boolean
  embedded?: boolean
}>()
</script>

<template>
  <header class="ph" :class="{ 'is-stacked': stacked, 'is-embedded': embedded }">
    <div class="ph-main">
      <component :is="embedded ? 'h2' : 'h1'" class="ph-title">{{ title }}</component>
      <p v-if="description && !embedded" class="ph-desc">{{ description }}</p>
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

.ph.is-embedded {
  gap: var(--ds-space-2);
}
.ph.is-embedded .ph-title {
  font-size: var(--text-sm);
  color: var(--ds-color-text-secondary);
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
