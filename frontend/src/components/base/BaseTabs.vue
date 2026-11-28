<script setup lang="ts">
/**
 * 下划线选项卡：抽屉/详情页内分区切换
 * ---------------------------------------------------------------------------
 * 批 66：补齐 WAI-ARIA APG Tabs 模式的键盘交互契约。
 *   旧状 = 只有一个 `role="tablist"` 外壳，每个 tab 都落在 Tab 键顺序里，且方向键完全无响应；
 *          键盘用户必须逐个按 Tab 穿过整条选项卡栏才能到达内容区（WCAG 2.1.1 不达标）。
 *   新状 = 漫游 tabindex（仅选中项 tabindex="0"）+ ←/→/Home/End 移动焦点并同步激活，
 *          传入 baseId 时同时产出 aria-controls，与消费端 role="tabpanel" 严格配对。
 */
import { useRovingTabs } from '../../composables/useRovingTabs';

const props = defineProps<{
  modelValue: string;
  items: { key: string; label: string; count?: number }[];
  /** 组名（批 110 由可选改**必填**，理由同 BaseSegmented：无名 tablist 读屏只会念"标签列表"）。 */
  label: string;
  /**
   * 分区 id 前缀（批 66）。传入后每个 tab 会生成 `aria-controls="${baseId}-panel-${key}"`，
   * 消费端对应面板需声明 `:id="`${baseId}-panel-${key}`"`、`role="tabpanel"`、
   * `:aria-labelledby="`${baseId}-tab-${key}`"`。不传则不产出 aria-controls（避免指向不存在的 id）。
   */
  baseId?: string;
}>();

const emit = defineEmits<{ (e: 'update:modelValue', v: string): void }>();

function select(key: string) {
  emit('update:modelValue', key);
}

// ←/→ 环绕移动，Home/End 跳首尾；移动焦点的同时激活（APG 自动激活策略）。
const { setRef, onKeydown, roving } = useRovingTabs(
  () => props.items.length,
  (i) => select(props.items[i].key),
);
</script>

<template>
  <div
    class="flex items-center gap-1 overflow-x-auto overflow-y-hidden"
    style="border-bottom: 1px solid var(--line-1)"
    role="tablist"
    :aria-label="label"
  >
    <button
      v-for="(it, idx) in items"
      :key="it.key"
      :ref="setRef(idx)"
      type="button"
      role="tab"
      class="relative shrink-0 px-3 py-2 text-sm font-medium transition-colors cursor-pointer"
      :class="
        modelValue === it.key
          ? 'text-[var(--ink-strong)]'
          : 'text-[var(--ink-2)] hover:text-[var(--ink-1)]'
      "
      :id="baseId ? `${baseId}-tab-${it.key}` : undefined"
      :aria-selected="modelValue === it.key"
      :tabindex="roving(modelValue === it.key)"
      :aria-controls="baseId ? `${baseId}-panel-${it.key}` : undefined"
      @click="select(it.key)"
      @keydown="onKeydown($event, idx)"
    >
      {{ it.label }}
      <span v-if="it.count !== undefined" class="num ml-1 text-xs" style="color: var(--ink-3)">{{ it.count }}</span>
      <span
        v-if="modelValue === it.key"
        class="absolute inset-x-2 bottom-0 h-0.5 rounded-full"
        style="background-color: var(--accent)"
      />
    </button>
  </div>
</template>
