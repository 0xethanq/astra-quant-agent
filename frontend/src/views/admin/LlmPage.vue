<script setup lang="ts">
import { provide } from 'vue';
import { useLlmConfig } from '../../composables/useLlmConfig';
import { LLM_KEY } from './llm/injection';
import ProviderListView from './llm/ProviderListView.vue';
import ProviderDetailView from './llm/ProviderDetailView.vue';
import RemoteFetchDialog from './llm/RemoteFetchDialog.vue';
import ModelEditDialog from './llm/ModelEditDialog.vue';

const llm = useLlmConfig();
provide(LLM_KEY, llm);

const { currentView, selectedProvider } = llm;
</script>

<template>
  <div class="llm-stage">
    <ProviderListView v-if="currentView === 'list'" />
    <ProviderDetailView v-else-if="currentView === 'detail' && selectedProvider" />

    <RemoteFetchDialog />
    <ModelEditDialog />
  </div>
</template>

<style scoped>
.llm-stage {
  display: flex;
  flex-direction: column;
  gap: var(--ds-space-4);
  width: 100%;
  min-width: 0;
  overflow-x: hidden;
  font-size: var(--text-base);
}
</style>
