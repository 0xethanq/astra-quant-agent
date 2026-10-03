<script setup lang="ts">
/**
 * LLM 配置页 —— 只负责「取状态 + provide + 编排视图」（结构优化阶段 3·F3）。
 *
 * 拆分前 1762 行（script 636 + template 1124）。现在：
 *   状态与全部服务端动作 → `composables/useLlmConfig.ts`
 *   列表视图             → `views/admin/llm/ProviderListView.vue`
 *   详情视图             → `views/admin/llm/ProviderDetailView.vue`
 *   远端获取弹窗         → `views/admin/llm/RemoteFetchDialog.vue`
 *   模型编辑弹窗         → `views/admin/llm/ModelEditDialog.vue`
 *
 * 两个视图块是 `<template v-if>` 的分支，拆成组件后以 `v-if` / `v-else-if`
 * 挂在同一父 div 上 —— DOM 子节点与原结构一致，父级 `space-y-4` 的间距行为不变。
 * 弹窗的 `v-if` 随组件一起搬走（原 `v-if` 在弹窗根 div 上）。
 */
import { provide } from 'vue'
import { useLlmConfig } from '../../composables/useLlmConfig'
import { LLM_KEY } from './llm/injection'
import ProviderListView from './llm/ProviderListView.vue'
import ProviderDetailView from './llm/ProviderDetailView.vue'
import RemoteFetchDialog from './llm/RemoteFetchDialog.vue'
import ModelEditDialog from './llm/ModelEditDialog.vue'

const llm = useLlmConfig()
provide(LLM_KEY, llm)

// 仅这两项用于父级的分支编排；其余绑定由各子组件自行 inject
const { currentView, selectedProvider } = llm
</script>

<template>
  <div class="space-y-4 max-w-4xl 2xl:max-w-6xl mx-auto font-sans text-xs w-full min-w-0 overflow-x-hidden">
    <ProviderListView v-if="currentView === 'list'" />
    <ProviderDetailView v-else-if="currentView === 'detail' && selectedProvider" />

    <RemoteFetchDialog />
    <ModelEditDialog />
  </div>
</template>
