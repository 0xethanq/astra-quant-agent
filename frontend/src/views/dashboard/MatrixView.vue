<script setup lang="ts">
/**
 * MatrixView.vue · AstraQuant 实盘矩阵核心交易工位
 * 从零重新设计信息层级与工位排布：
 * 1. 顶部紧凑状态与工位模式换挡（标准工作台 / 沉浸工位模式）
 * 2. 核心指标 HUD 区域（低饱和黑白分层卡片）
 * 3. 首屏直达核心工位：左侧主图表 + 右侧持仓挂单与 OKX 账户
 * 4. 底部 7 梯队微观结构因子矩阵
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
import CouncilVerdictRail from '../../components/dashboard/CouncilVerdictRail.vue';
import FactorMatrix from '../../components/dashboard/FactorMatrix.vue';
import RadarDrawer from '../../components/dashboard/RadarDrawer.vue';

const store = useDashboardStore();
const { t } = useI18n();

// 工位全屏/聚焦模式持久化
const isFocusMode = useLocalStorage('astra_matrix_focus_mode', false);

const chart = ref<InstanceType<typeof ChartWorkstation> | null>(null);
const selectedCycle = ref<any>(null);

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
  <div class="w-full">
    <!-- 轻量无边框顶部标题行（去掉全宽横条线，保留 Focus Mode 入口） -->
    <div class="flex items-center justify-between gap-2 mb-3">
      <div class="flex items-center gap-2.5">
        <span class="dsh-status-dot active" aria-hidden="true" />
        <h1 class="text-xs font-mono font-semibold uppercase tracking-wider text-[var(--ink-strong)]">
          {{ t('dash.matrix.title') }}
        </h1>
        <span class="text-4xs font-mono text-[var(--ink-3)] uppercase">
          · {{ t('dash.matrix.hudProdDynamics') }}
        </span>
      </div>

      <button type="button"
        class="btn btn-sm h-7 px-2.5 text-3xs font-mono cursor-pointer inline-flex items-center gap-1.5 rounded-md transition-colors"
        :class="isFocusMode ? 'btn-primary' : 'btn-quiet'"
        :title="isFocusMode ? t('dash.matrix.focusRestoreTip') : t('dash.matrix.focusTip')"
        @click="isFocusMode = !isFocusMode"
      >
        <Minimize2 v-if="isFocusMode" class="h-3 w-3" />
        <Maximize2 v-else class="h-3 w-3" />
        <span>{{ isFocusMode ? t('dash.matrix.focusExit') : t('dash.matrix.focusEnter') }}</span>
      </button>
    </div>

    <DataGate>
      <!-- 无边框开放式 Portfolio Hero Strip -->
      <KpiRibbon v-if="!isFocusMode" />

      <!-- 工位沉浸模式布局（xl 限定 12 栏铺满大屏，保持 viewportMathConstants 契约） -->
      <div v-if="isFocusMode" class="grid grid-cols-1 gap-3 xl:grid-cols-12 xl:h-[calc(100vh-140px)]">
        <div class="xl:col-span-8 h-full min-h-0">
          <ChartWorkstation
            ref="chart"
            :initial-symbol="initialSymbol"
            :fill="true"
            :wheel-zoom="true"
            chart-height="100%"
          />
        </div>
        <div class="xl:col-span-4 h-full min-h-0 overflow-hidden">
          <PositionsOrdersPanel :scroll-inside="true" @pick-symbol="pick" />
        </div>
      </div>

      <!-- 舒展留白双区工作台：色调分层区块 + 大间距留白取代硬切线 -->
      <div v-else class="space-y-6 mt-5">
        <div class="grid grid-cols-1 gap-5 xl:grid-cols-12 items-stretch">
          <div class="xl:col-span-8 flex flex-col min-h-[440px] xl:min-h-[640px]">
            <ChartWorkstation
              ref="chart"
              :initial-symbol="initialSymbol"
              :fill="true"
              chart-height="100%"
            />
          </div>
          <div class="xl:col-span-4 flex flex-col gap-5">
            <PositionsOrdersPanel class="flex-1" @pick-symbol="pick" />
            <CouncilVerdictRail class="shrink-0" @open-cycle="selectedCycle = $event" />
          </div>
        </div>

        <!-- 7 梯队微观结构因子矩阵（独立色调面板） -->
        <FactorMatrix @pick-symbol="pick" />
      </div>
    </DataGate>

    <!-- 决策白盒审计抽屉（支持从主屏 AI 裁决直达完整多席位辩论） -->
    <RadarDrawer :cycle="selectedCycle" @close="selectedCycle = null" />
  </div>
</template>
