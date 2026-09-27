<script setup lang="ts">
/**
 * MatrixView.vue · DeepSeek Harness 风格实盘矩阵主工位
 * 从零重新设计信息层级与工位排布：
 * 1. 顶部紧凑状态与工位模式换挡（标准工作台 / 沉浸工位模式）
 * 2. 核心指标 HUD 区域（低饱和黑白分层卡片）
 * 3. 首屏直达核心工位：左侧主图表 + 右侧持仓挂单与多所账户
 * 4. 底部多因子微积分动力学矩阵
 */
import { computed, ref } from 'vue';
import { useDashboardStore } from '../../stores/dashboard';
import DataGate from '../../components/dashboard/DataGate.vue';
import { symOf } from '../../utils/instId';
import { useI18n } from '../../composables/useI18n';
import { useLocalStorage } from '../../composables/useLocalStorage';
import {
  Maximize2,
  Minimize2,
} from 'lucide-vue-next';

import KpiRibbon from '../../components/dashboard/KpiRibbon.vue';
import ChartWorkstation from '../../components/dashboard/ChartWorkstation.vue';
import PositionsOrdersPanel from '../../components/dashboard/PositionsOrdersPanel.vue';
import FactorMatrix from '../../components/dashboard/FactorMatrix.vue';

const store = useDashboardStore();
const { t } = useI18n();

// 工位全屏/聚焦模式持久化
const isFocusMode = useLocalStorage('astra_matrix_focus_mode', false);

const chart = ref<InstanceType<typeof ChartWorkstation> | null>(null);

/** 初始选中：优先当前持仓，其次 BTC */
const initialSymbol = computed(() => {
  const p = store.positions[0];
  return p ? symOf(String(p.instId)) : 'BTC';
});

function pick(instId: string) {
  const sym = String(instId || '').split('-')[0].toUpperCase();
  if (sym) chart.value?.selectSymbol(sym);
}
</script>

<template>
  <div class="space-y-3">
    <!-- 工位导航与控制顶栏 -->
    <div class="flex items-center justify-between gap-2 pt-0.5">
      <div class="flex items-center gap-2">
        <h1 class="text-sm font-semibold tracking-tight text-[var(--ink-strong)] flex items-center gap-2">
          <span class="dsh-status-dot active" aria-hidden="true" />
          {{ t('dash.matrix.title') }}
        </h1>
        <span
          class="rounded-full px-2 py-0.5 border text-3xs font-mono font-medium"
          style="background-color: var(--surface-2); border-color: var(--line-1); color: var(--ink-2)"
        >
          {{ t('dash.matrix.hudProdDynamics') }}
        </span>
      </div>

      <!-- 模式切换控制器 -->
      <button type="button"
        class="btn btn-ghost h-7 px-3 text-xs font-medium cursor-pointer inline-flex items-center gap-1.5 rounded-full transition-all"
        :class="isFocusMode ? 'btn-primary' : ''"
        :title="isFocusMode ? t('dash.matrix.focusRestoreTip') : t('dash.matrix.focusTip')"
        @click="isFocusMode = !isFocusMode"
      >
        <Minimize2 v-if="isFocusMode" class="h-3.5 w-3.5" />
        <Maximize2 v-else class="h-3.5 w-3.5" />
        <span>{{ isFocusMode ? t('dash.matrix.focusExit') : t('dash.matrix.focusEnter') }}</span>
      </button>
    </div>

    <DataGate>
      <!-- 常规模式下展示核心指标 HUD -->
      <KpiRibbon v-if="!isFocusMode" />

      <!-- 工位沉浸模式布局：铺满大屏。
           批 84：固定高度**只在 xl 生效**。原先无条件 `h-[calc(100vh-140px)]`，
           是按 xl 的 12 栏并排布局算的；在 <1280px（单栏堆叠）下容器高被钉死，
           两个 `h-full` 子项一个溢出 140px、另一个塌成 **0 高度并被推到 y=900**
           —— 即「持仓面板整个消失」。改为 xl 限定后，窄屏回归自然文档流。 -->
      <div v-if="isFocusMode" class="grid grid-cols-1 gap-3 xl:grid-cols-12 xl:h-[calc(100vh-140px)]">
        <div class="xl:col-span-8 h-full min-h-0">
          <ChartWorkstation
            ref="chart"
            :initial-symbol="initialSymbol"
            :fill="true"
            chart-height="100%"
          />
        </div>
        <div class="xl:col-span-4 h-full min-h-0 overflow-hidden">
          <PositionsOrdersPanel @pick-symbol="pick" />
        </div>
      </div>

      <!-- 标准工作台布局：首屏直达主图与持仓，分层卡片排布 -->
      <template v-else>
        <!-- 主工位区：图表(8) + 持仓挂单(4) -->
        <div class="grid grid-cols-1 gap-3 xl:grid-cols-12 xl:h-[600px] items-stretch">
          <div class="xl:col-span-8 flex flex-col h-full min-h-0">
            <ChartWorkstation
              ref="chart"
              :initial-symbol="initialSymbol"
              :fill="true"
              chart-height="100%"
            />
          </div>
          <div class="xl:col-span-4 flex flex-col gap-3 h-full min-h-0">
            <PositionsOrdersPanel class="flex-1 min-h-0" @pick-symbol="pick" />
          </div>
        </div>

        <!-- 因子动能微积分动力学矩阵 -->
        <FactorMatrix @pick-symbol="pick" />
      </template>
    </DataGate>
  </div>
</template>
