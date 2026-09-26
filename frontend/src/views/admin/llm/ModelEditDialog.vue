<script setup lang="ts">
/**
 * ModelEditDialog · 模型参数编辑
 * ---------------------------------------------------------------------------
 * 骨架（推倒重来）：
 *   旧 = 手写 `fixed inset-0 bg-black/60 backdrop-blur-md` 遮罩 + 自绘面板
 *        + 4 个能力开关（**每个 3 行内联 rgba 三元表达式**）
 *   新 = **BaseDialog**（自带焦点陷阱 / ESC 关闭 / 滚动锁）
 *        + 能力开关由一份 `CAPABILITIES` 数组驱动，色调只走品牌与中性
 *
 * ⚠️ 逻辑模块 `useLlmConfig.ts` / `llmLogic.ts` 未触碰。
 */
import { computed } from 'vue'
import { useI18n } from '../../../composables/useI18n'
import { useLlmCtx } from './injection'
import BaseDialog from '../../../components/base/BaseDialog.vue'

const { t } = useI18n()
const {
  availableEffortOptions,
  editingModel,
  modelForm,
  modelModalVisible,
  saveModelForm,
  selectedProvider,
  toggleCapability,
} = useLlmCtx()

/** 能力标签（旧版把同一段三元样式写了 4 遍，只有 key 与文案不同）
 *  存**完整键路径**并直接 `t(c.labelKey)`，避免拼接键逃过 i18n 静态校验。 */
const CAPABILITIES = [
  { key: 'chat', labelKey: 'admin.llm.capChatFull' },
  { key: 'vision', labelKey: 'admin.llm.capVisionFull' },
  { key: 'tools', labelKey: 'admin.llm.capToolsFull' },
  { key: 'reasoning', labelKey: 'admin.llm.capCotFull' },
]

const title = computed(() =>
  editingModel.value ? t('admin.llm.editModel') : t('admin.llm.addNewModel'),
)
</script>

<template>
  <BaseDialog :open="modelModalVisible" :title="title" size="lg" @close="modelModalVisible = false">
    <template #title>
      <span class="me-title">
        <span>{{ title }}</span>
        <span class="me-owner">{{ t('admin.llm.belongsTo') }} {{ selectedProvider?.name }}</span>
      </span>
    </template>

    <form id="model-edit-form" class="me-form" @submit.prevent="saveModelForm">
      <label class="field-stack me-field">
        <span class="form-label">{{ t('admin.llm.modelIdLabel') }}</span>
        <input
          v-model="modelForm.id"
          :readonly="!!editingModel"
          :placeholder="t('admin.llm.modelIdPlaceholder')"
          class="field mono"
          :class="{ 'is-readonly': !!editingModel }"
        />
      </label>

      <label class="field-stack me-field">
        <span class="form-label">{{ t('admin.llm.displayName') }}</span>
        <input
          v-model="modelForm.name"
          :placeholder="t('admin.llm.displayNamePlaceholder')"
          class="field"
        />
      </label>

      <div class="field-stack me-field">
        <span class="form-label">{{ t('admin.llm.capBadges') }}</span>
        <div class="me-caps">
          <button
            v-for="c in CAPABILITIES"
            :key="c.key"
            type="button"
            class="me-cap"
            :class="{ 'is-on': modelForm.capabilities.includes(c.key) }"
            @click="toggleCapability(c.key)"
          >
            {{ t(c.labelKey) }}
          </button>
        </div>
      </div>

      <label class="field-stack me-field">
        <span class="form-label">{{ t('admin.llm.effortLabel') }}</span>
        <select v-model="modelForm.reasoning_effort" class="field me-select" :aria-label="t('admin.llm.effortLabel')">
          <option v-for="opt in availableEffortOptions" :key="opt.value" :value="opt.value">
            {{ opt.label }}
          </option>
        </select>
      </label>

      <label class="field-stack me-field">
        <span class="form-label">{{ t('admin.llm.contextLen') }}</span>
        <input
          v-model.number="modelForm.context_length"
          type="number"
          inputmode="numeric"
          placeholder="1048576"
          class="field num"
        />
      </label>
    </form>

    <template #footer>
      <button type="button" class="btn btn-ghost btn-sm" @click="modelModalVisible = false">
        {{ t('admin.llm.cancel') }}
      </button>
      <!-- 批 115：表单已挂 @submit.prevent="saveModelForm"，type="submit" 按钮无需再挂 @click，避免单次点击触发两次保存 -->
      <button class="btn btn-primary btn-sm" type="submit" form="model-edit-form" :disabled="!modelForm.id.trim()">
        {{ t('admin.llm.saveModel') }}
      </button>
    </template>
  </BaseDialog>
</template>

<style scoped>
.me-title {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
}
.me-owner {
  font-size: var(--text-4xs);
  font-weight: 400;
  color: var(--ds-color-text-placeholder);
}
.me-form {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
}

.me-field .field.is-readonly {
  background-color: var(--ds-color-bg-surface-inset);
  color: var(--ds-color-text-placeholder);
  cursor: not-allowed;
}
.me-caps {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.me-cap {
  padding:6px 10px;
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: transparent;
  font-size: var(--text-3xs);
  color: var(--ds-color-text-description);
  cursor: pointer;
  transition: all var(--dur-fast);
}
.me-cap:hover {
  background-color: var(--ds-color-bg-hover);
  color: var(--ds-color-text-primary);
}
.me-cap.is-on {
  background-color: var(--astra-brand-bg);
  border-color: var(--astra-brand-line);
  color: var(--ds-color-brand);
  font-weight: 600;
}
.me-select {
  cursor: pointer;
}
</style>
