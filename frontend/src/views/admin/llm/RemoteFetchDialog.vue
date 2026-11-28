<script setup lang="ts">
/**
 * RemoteFetchDialog · 远端模型探测与批量导入
 * ---------------------------------------------------------------------------
 * 骨架（推倒重来）：
 *   旧 = 手写 `fixed inset-0 bg-black/60 backdrop-blur-md` 遮罩 + 自绘面板
 *        + 探测条 + 状态条 + 搜索 + 列表（硬编码 indigo rgba 按钮）
 *   新 = **BaseDialog xl**（自带焦点陷阱 / ESC / 滚动锁）
 *        + 探测条 → 紧凑信息行；列表 → 行式清单；导入按钮走品牌与常规按钮
 *
 * ⚠️ 逻辑模块 `useLlmConfig.ts` / `llmLogic.ts` 未触碰。
 */
import { useI18n } from '../../../composables/useI18n'
import { useLlmCtx } from './injection'
import BaseDialog from '../../../components/base/BaseDialog.vue'
import BaseEmpty from '../../../components/base/BaseEmpty.vue'
import { DownloadCloud, RefreshCw, Search, CheckCircle2, AlertCircle } from 'lucide-vue-next'

const { t } = useI18n()
const {
  customFetchUrl,
  executeRemoteFetch,
  fetchModalVisible,
  fetchingRemote,
  filteredRemoteModels,
  importAllFilteredRemoteModels,
  importRemoteModel,
  remoteFetchResult,
  remoteSearch,
  selectedProvider,
} = useLlmCtx()
</script>

<template>
  <BaseDialog
    :open="fetchModalVisible"
    :title="t('admin.llm.fetchTitle', undefined, { name: selectedProvider?.name })"
    :desc="t('admin.llm.probeHint')"
    size="xl"
    @close="fetchModalVisible = false"
  >
    <template #title>
      <span class="rf-title">
        <DownloadCloud :size="15" />
        <span>{{ t('admin.llm.fetchTitle', undefined, { name: selectedProvider?.name }) }}</span>
      </span>
    </template>

    <div class="rf">
      <!-- 探测端点 -->
      <div class="rf-probe">
        <div class="rf-probe-text">
          <span class="label-caps">{{ t('admin.llm.probeEndpoint') }}</span>
          <span class="rf-endpoint mono truncate">{{ customFetchUrl || selectedProvider?.base_url || '--' }}</span>
        </div>
        <span v-if="selectedProvider?.has_key" class="badge badge-up">{{ t('admin.llm.useStoredKey') }}</span>
        <button type="button" class="btn btn-primary btn-sm" :disabled="fetchingRemote" @click="executeRemoteFetch">
          <RefreshCw :size="14" :class="fetchingRemote ? 'animate-spin shrink-0' : ''" />
          <span>{{ fetchingRemote ? t('admin.llm.probing') : t('admin.llm.reprobe') }}</span>
        </button>
      </div>

      <!-- 状态 -->
      <div v-if="remoteFetchResult" class="rf-status" :role="remoteFetchResult.ok ? 'status' : 'alert'" :class="remoteFetchResult.ok ? 'is-ok' : 'is-error'">
        <CheckCircle2 v-if="remoteFetchResult.ok" :size="14" />
        <AlertCircle v-else :size="14" />
        <span class="rf-status-text">
          {{ remoteFetchResult.ok
            ? t('admin.llm.probeSuccess', undefined, { n: remoteFetchResult.total })
            : remoteFetchResult.error }}
        </span>
        <span v-if="remoteFetchResult.ok" class="rf-status-endpoint mono truncate">
          {{ remoteFetchResult.endpoint_used }}
        </span>
      </div>

      <!-- 过滤 + 列表 -->
      <template v-if="remoteFetchResult?.ok">
        <div class="rf-search focus-ring">
          <Search :size="13" />
          <input v-model="remoteSearch" type="search" autocomplete="off" spellcheck="false" :aria-label="t('admin.llm.filterPlaceholder')" :placeholder="t('admin.llm.filterPlaceholder')" class="rf-search-input" />
        </div>

        <BaseEmpty v-if="!filteredRemoteModels.length" :text="t('common.noRecords')" />

        <div v-else class="log-panel rf-list">
          <div v-for="rm in filteredRemoteModels" :key="rm.id" class="rf-row">
            <div class="rf-row-main">
              <span class="rf-row-name">{{ rm.name }}</span>
              <span class="rf-row-id mono truncate">{{ rm.id }}</span>
            </div>
            <div class="rf-row-actions">
              <button type="button" class="btn btn-ghost btn-sm" @click="importRemoteModel(rm, false)">
                {{ t('admin.llm.addBtn') }}
              </button>
              <button type="button" class="btn btn-primary btn-sm" @click="importRemoteModel(rm, true)">
                {{ t('admin.llm.addAndEnable') }}
              </button>
            </div>
          </div>
        </div>
      </template>
    </div>

    <template #footer>
      <span class="rf-count">
        <template v-if="filteredRemoteModels.length">
          {{ t('admin.llm.showingCount', undefined, { n: filteredRemoteModels.length }) }}
        </template>
      </span>
      <button
        v-if="filteredRemoteModels.length"
        type="button"
        class="btn btn-ghost btn-sm"
        @click="importAllFilteredRemoteModels"
      >
        {{ t('admin.llm.addAll', undefined, { n: filteredRemoteModels.length }) }}
      </button>
      <button type="button" class="btn btn-primary btn-sm" @click="fetchModalVisible = false">
        {{ t('admin.llm.done') }}
      </button>
    </template>
  </BaseDialog>
</template>

<style scoped>
.rf {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-3);
  min-height: 200px;
}
.rf-title {
  display: flex;
  align-items: center;
  gap: 8px;
}

.rf-probe {
  display: flex;
  align-items: center;
  gap: var(--ds-space-3);
  flex-wrap: wrap;
  padding: 10px var(--ds-space-3);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-surface-inset);
}
.rf-probe-text {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
  flex: 1;
}
.rf-endpoint {
  font-size: var(--text-xs);
  color: var(--ds-color-text-secondary);
  min-width: 0;
}

.rf-status {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 10px;
  border-radius: var(--r-ctl);
  font-size: var(--text-base);
}
.rf-status.is-ok {
  background-color: var(--up-bg);
  color: var(--up);
}
.rf-status.is-error {
  background-color: var(--down-bg);
  color: var(--down);
}
.rf-status-text {
  font-weight: 600;
}
.rf-status-endpoint {
  margin-left: auto;
  font-weight: 400;
  opacity: 0.85;
  min-width: 0;
}

.rf-search {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 0 10px;
  border: 1px solid var(--ds-color-border-default);
  border-radius: var(--r-ctl);
  background-color: var(--ds-color-bg-input);
  color: var(--ds-color-text-placeholder);
}
.rf-search-input {
  width: 100%;
  padding:8px 0;
  border: 0;
  outline: none;
  background: transparent;
  color: var(--ds-color-text-primary);
  font-size: var(--text-base);
}

.rf-list {
  max-height: 380px;
  min-height: 180px;
}
.rf-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: var(--ds-space-3);
  padding:8px var(--ds-space-3);
}
.rf-row:hover {
  background-color: var(--ds-color-bg-hover);
}
.rf-row-main {
  display: flex;
  flex-direction: column;
  gap: 1px;
  min-width: 0;
}
.rf-row-name {
  font-size: var(--text-base);
  font-weight: 600;
  color: var(--ds-color-text-primary);
}
.rf-row-id {
  font-size: var(--text-xs);
  color: var(--ds-color-text-placeholder);
  min-width: 0;
}
.rf-row-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.rf-count {
  margin-right: auto;
  font-size: var(--text-4xs);
  color: var(--ds-color-text-placeholder);
}
</style>
