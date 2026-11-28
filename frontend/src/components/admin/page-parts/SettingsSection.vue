<script setup lang="ts">
/**
 * SettingsSection · Admin v2 设置区块外壳
 */
import type { Component } from 'vue';

defineProps<{
  title: string;
  description?: string;
  tone?: 'default' | 'subtle';
  icon?: Component;
}>();
</script>

<template>
  <section class="card ss" :class="{ 'is-subtle': tone === 'subtle' }">
    <header class="card-head">
      <div class="ss-head-text">
        <h2 class="card-title">
          <component :is="icon" v-if="icon" :size="15" />
          {{ title }}
        </h2>
        <p v-if="description" class="card-sub">{{ description }}</p>
      </div>
      <div class="ss-actions">
        <slot name="actions" />
      </div>
    </header>

    <div class="ss-body">
      <slot />
    </div>
  </section>
</template>

<style scoped>
.ss {
  overflow: hidden;
}
.ss.is-subtle {
  background-color: var(--ds-color-bg-surface-inset);
}
.ss-head-text {
  min-width: 0;
}
.ss-actions {
  display: flex;
  align-items: center;
  gap: var(--ds-space-2);
  flex-shrink: 0;
  flex-wrap: wrap;
  justify-content: flex-end;
}
.ss-body {
  padding: var(--ds-space-5);
}
</style>
