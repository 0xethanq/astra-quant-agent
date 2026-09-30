<script setup lang="ts">
/**
 * FactorMatrix.vue · DeepSeek Harness 风格因子动能矩阵
 * 融合 1H 微积分动力学一阶/二阶导、聪明钱仓位与 AI 委员会决策终审
 * 支持客户端高密度排序、多空过滤、行内快速切图与证据链白盒透视抽屉
 */
import { computed, ref } from 'vue';
import { useDashboardStore } from '../../stores/dashboard';
import { useI18n } from '../../composables/useI18n';
import { useHotkeys } from '../../composables/useHotkeys';
import { fmtNum, fmtPct, fmtPrice, arrow, dirClass } from '../../utils/format';
import {
  Activity,
  Crosshair,
  Search,
  ArrowUpDown,
  ArrowUp,
  ArrowDown,
} from 'lucide-vue-next';
import BaseEmpty from '../base/BaseEmpty.vue';
import ConfBadge from '../base/ConfBadge.vue';
import FactorDrawer from './FactorDrawer.vue';
import CryptoLogo from './CryptoLogo.vue';

const emit = defineEmits<{ (e: 'pick-symbol', instId: string): void }>();

const store = useDashboardStore();
const { t } = useI18n();

const rows = computed(() => store.factors || []);
const detail = ref<any>(null);

// 搜索与过滤
const searchQuery = ref('');
const searchInput = ref<HTMLInputElement | null>(null);

useHotkeys({
  '/': {
    handler: () => {
      searchInput.value?.focus();
      searchInput.value?.select();
    },
    preventDefault: true,
  },
});
const filterMode = ref<'all' | 'long' | 'short' | 'wait'>('all');

// 客户端排序状态
type SortKey = 'name' | 'price' | 'chg24h' | 'velocity' | 'accel' | 'adx' | 'ls' | 'conf';
const sortKey = ref<SortKey | null>(null);
const sortOrder = ref<'asc' | 'desc'>('desc');

/** `aria-sort`：只有当前排序列报方向（批 43，键盘/读屏可感知排序状态）。 */
function ariaSortOf(key: string): 'ascending' | 'descending' | 'none' {
  if (sortKey.value !== key) return 'none'
  if (sortOrder.value === 'asc') return 'ascending'
  if (sortOrder.value === 'desc') return 'descending'
  return 'none'
}

function toggleSort(key: SortKey) {
  if (sortKey.value === key) {
    if (sortOrder.value === 'desc') {
      sortOrder.value = 'asc';
    } else {
      sortKey.value = null;
      sortOrder.value = 'desc';
    }
  } else {
    sortKey.value = key;
    sortOrder.value = 'desc';
  }
}

function actionOf(f: any): string {
  return String(f.decision?.action || f.action || 'WAIT').toUpperCase();
}

function actionMeta(a: string): { cls: string; label: string } {
  if (a === 'BUY_LONG' || a === 'BUY' || a === 'LONG') {
    return { cls: 'text-[var(--up)] bg-[var(--up-bg)] border-[var(--up-line)]', label: t('common.dir.long') };
  }
  if (a === 'SELL_SHORT' || a === 'SELL' || a === 'SHORT') {
    return { cls: 'text-[var(--down)] bg-[var(--down-bg)] border-[var(--down-line)]', label: t('common.dir.short') };
  }
  return { cls: 'text-[var(--ink-2)] bg-[var(--surface-2)] border-[var(--line-1)]', label: t('common.dir.flat') };
}

function regimeOf(f: any): string {
  const r = String(f.market_regime || f.calculus?.state_1h || '').toLowerCase();
  if (r.includes('up') || r.includes('bull')) return t('dash.matrix.matrix.regime.trendUp');
  if (r.includes('down') || r.includes('bear')) return t('dash.matrix.matrix.regime.trendDown');
  if (r.includes('range')) return t('dash.matrix.matrix.regime.range');
  return '';
}

function lsOf(f: any): string {
  const v = Number(f.lsRatio);
  return Number.isFinite(v) && v > 0 ? v.toFixed(2) : '--';
}

function openDetail(f: any) {
  detail.value = f;
}

function onQuickChart(e: MouseEvent, instId: string) {
  e.stopPropagation();
  emit('pick-symbol', instId);
}

// 过滤与排序后的数据
const processedRows = computed(() => {
  let list = [...rows.value];

  // 1. 文本搜索
  const q = searchQuery.value.trim().toLowerCase();
  if (q) {
    list = list.filter((f) => (f.name || f.instId || '').toLowerCase().includes(q));
  }

  // 2. 状态过滤
  if (filterMode.value !== 'all') {
    list = list.filter((f) => {
      const act = actionOf(f);
      if (filterMode.value === 'long') return act.includes('BUY') || act.includes('LONG');
      if (filterMode.value === 'short') return act.includes('SELL') || act.includes('SHORT');
      if (filterMode.value === 'wait') return !act.includes('BUY') && !act.includes('SELL');
      return true;
    });
  }

  // 3. 排序
  if (sortKey.value) {
    const k = sortKey.value;
    const factor = sortOrder.value === 'asc' ? 1 : -1;
    list.sort((a: any, b: any) => {
      let valA: number = 0;
      let valB: number = 0;
      switch (k) {
        case 'name': return factor * String(a.name || '').localeCompare(String(b.name || ''));
        case 'price': valA = Number(a.price || 0); valB = Number(b.price || 0); break;
        case 'chg24h': valA = Number(a.chg24h || 0); valB = Number(b.chg24h || 0); break;
        case 'velocity': valA = Number(a.calculus?.velocity_1h ?? 0); valB = Number(b.calculus?.velocity_1h ?? 0); break;
        case 'accel': valA = Number(a.calculus?.accel_1h ?? 0); valB = Number(b.calculus?.accel_1h ?? 0); break;
        case 'adx': valA = Number(a.adx_1h ?? 0); valB = Number(b.adx_1h ?? 0); break;
        case 'ls': valA = Number(a.lsRatio || 0); valB = Number(b.lsRatio || 0); break;
        case 'conf': valA = Number(a.decision?.confidence ?? a.confidence ?? 0); valB = Number(b.decision?.confidence ?? b.confidence ?? 0); break;
      }
      return (valA - valB) * factor;
    });
  }

  return list;
});
</script>

<template>
  <div class="dsh-card overflow-hidden">
    <!-- 面板头部 -->
    <header class="dsh-card-header flex flex-col sm:flex-row sm:items-center justify-between gap-2.5">
      <div>
        <div class="flex items-center gap-2">
          <h2 class="text-xs font-bold uppercase tracking-wider text-[var(--ink-strong)] flex items-center gap-1.5">
            <Activity class="h-3.5 w-3.5 text-[var(--accent)]" />
            {{ t('dash.matrix.matrix.title') }}
          </h2>
          <span
            class="rounded-full px-2 py-0.5 border text-3xs font-mono font-medium"
            style="background-color: var(--surface-2); border-color: var(--line-1); color: var(--ink-2)"
          >
            {{ processedRows.length }} / {{ rows.length }} {{ t('common.unitCoin') }}
          </span>
        </div>
      </div>

      <!-- 搜索与筛选工具栏 -->
      <div class="flex items-center gap-2">
        <!-- 搜索输入框 -->
        <div class="relative">
          <Search class="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-[var(--ink-3)]" />
          <input
            ref="searchInput"
            v-model="searchQuery"
            type="search"
            autocomplete="off"
            spellcheck="false"
            :aria-label="t('dash.matrix.searchPlaceholder')"
            :placeholder="t('dash.matrix.searchPlaceholder')"
            class="h-6 w-36 rounded-full border border-[var(--line-1)] pl-6 pr-6 text-3xs transition-all focus:outline-none focus:border-[var(--ds-color-border-input-focus)] focus:ring-1 focus:ring-[var(--ds-color-border-input-focus)]"
            style="background-color: var(--surface-2); color: var(--ink-1)"
          />
          <kbd
            v-if="!searchQuery"
            class="hidden sm:inline-flex absolute right-1.5 top-1/2 -translate-y-1/2 pointer-events-none opacity-60"
          >
            /
          </kbd>
        </div>

        <!-- 多空过滤小标签 -->
        <div
          class="flex items-center gap-0.5 rounded-full p-0.5"
          style="background-color: var(--surface-2); border: 1px solid var(--line-1)"
        >
          <button type="button"
            v-for="m in [
              { key: 'all', label: t('dash.matrix.filterAll') },
              { key: 'long', label: t('dash.matrix.filterLong') },
              { key: 'short', label: t('dash.matrix.filterShort') },
              { key: 'wait', label: t('dash.matrix.filterWait') },
            ] as const"
            :key="m.key"
            class="px-2 py-0.5 rounded-full text-3xs font-medium cursor-pointer transition-all"
            :class="
              filterMode === m.key
                ? 'bg-[var(--surface-3)] text-[var(--ink-strong)] font-semibold border border-[var(--line-2)] shadow-xs'
                : 'text-[var(--ink-3)] hover:bg-[var(--ds-color-bg-hover)] hover:text-[var(--ink-1)]'
            "
            @click="filterMode = m.key"
          >
            {{ m.label }}
          </button>
        </div>
      </div>
    </header>

    <BaseEmpty v-if="!processedRows.length" :text="t('dash.matrix.matrix.empty')" />

    <template v-else>
      <!-- 桌面表格 -->
      <div class="hidden overflow-x-auto lg:block">
        <table class="table w-full" :aria-label="t('dash.matrix.matrix.title')">
          <thead>
            <tr>
              <th scope="col" :aria-sort="ariaSortOf('name')">
                <button type="button" class="sort-btn w-full" @click="toggleSort('name')">
                  <span class="inline-flex w-full items-center gap-1">
                    <span>{{ t('dash.matrix.matrix.col.symbol') }}</span>
                    <ArrowUp v-if="sortKey === 'name' && sortOrder === 'asc'" class="h-3 w-3" />
                    <ArrowDown v-else-if="sortKey === 'name' && sortOrder === 'desc'" class="h-3 w-3" />
                    <ArrowUpDown v-else class="h-3 w-3 opacity-40" />
                  </span>
                </button>
              </th>
              <th scope="col" class="col-num" :aria-sort="ariaSortOf('price')">
                <button type="button" class="sort-btn w-full" @click="toggleSort('price')">
                  <span class="inline-flex w-full items-center justify-end gap-1">
                    <span>{{ t('dash.matrix.matrix.col.price') }}</span>
                    <ArrowUp v-if="sortKey === 'price' && sortOrder === 'asc'" class="h-3 w-3" />
                    <ArrowDown v-else-if="sortKey === 'price' && sortOrder === 'desc'" class="h-3 w-3" />
                    <ArrowUpDown v-else class="h-3 w-3 opacity-40" />
                  </span>
                </button>
              </th>
              <th scope="col" class="col-num" :aria-sort="ariaSortOf('chg24h')">
                <button type="button" class="sort-btn w-full" @click="toggleSort('chg24h')">
                  <span class="inline-flex w-full items-center justify-end gap-1">
                    <span>{{ t('dash.matrix.matrix.col.chg') }}</span>
                    <ArrowUp v-if="sortKey === 'chg24h' && sortOrder === 'asc'" class="h-3 w-3" />
                    <ArrowDown v-else-if="sortKey === 'chg24h' && sortOrder === 'desc'" class="h-3 w-3" />
                    <ArrowUpDown v-else class="h-3 w-3 opacity-40" />
                  </span>
                </button>
              </th>
              <th scope="col" class="col-num" :title="t('dash.matrix.matrix.col.vel') + ' · ' + t('dash.matrix.matrix.velTip')" :aria-sort="ariaSortOf('velocity')">
                <button type="button" class="sort-btn w-full" @click="toggleSort('velocity')">
                  <span class="inline-flex w-full items-center justify-end gap-1">
                    <span>v (1H)</span>
                    <ArrowUp v-if="sortKey === 'velocity' && sortOrder === 'asc'" class="h-3 w-3" />
                    <ArrowDown v-else-if="sortKey === 'velocity' && sortOrder === 'desc'" class="h-3 w-3" />
                    <ArrowUpDown v-else class="h-3 w-3 opacity-40" />
                  </span>
                </button>
              </th>
              <th scope="col" class="col-num" :title="t('dash.matrix.matrix.col.acc') + ' · ' + t('dash.matrix.matrix.accTip')" :aria-sort="ariaSortOf('accel')">
                <button type="button" class="sort-btn w-full" @click="toggleSort('accel')">
                  <span class="inline-flex w-full items-center justify-end gap-1">
                    <span>a (1H)</span>
                    <ArrowUp v-if="sortKey === 'accel' && sortOrder === 'asc'" class="h-3 w-3" />
                    <ArrowDown v-else-if="sortKey === 'accel' && sortOrder === 'desc'" class="h-3 w-3" />
                    <ArrowUpDown v-else class="h-3 w-3 opacity-40" />
                  </span>
                </button>
              </th>
              <th scope="col" class="col-num" :title="t('dash.matrix.matrix.adxTip')" :aria-sort="ariaSortOf('adx')">
                <button type="button" class="sort-btn w-full" @click="toggleSort('adx')">
                  <span class="inline-flex w-full items-center justify-end gap-1">
                    <span>ADX</span>
                    <ArrowUp v-if="sortKey === 'adx' && sortOrder === 'asc'" class="h-3 w-3" />
                    <ArrowDown v-else-if="sortKey === 'adx' && sortOrder === 'desc'" class="h-3 w-3" />
                    <ArrowUpDown v-else class="h-3 w-3 opacity-40" />
                  </span>
                </button>
              </th>
              <th scope="col" class="col-num" :title="t('dash.matrix.matrix.lsTip')" :aria-sort="ariaSortOf('ls')">
                <button type="button" class="sort-btn w-full" @click="toggleSort('ls')">
                  <span class="inline-flex w-full items-center justify-end gap-1">
                    <span>{{ t('dash.matrix.matrix.col.ls') }}</span>
                    <ArrowUp v-if="sortKey === 'ls' && sortOrder === 'asc'" class="h-3 w-3" />
                    <ArrowDown v-else-if="sortKey === 'ls' && sortOrder === 'desc'" class="h-3 w-3" />
                    <ArrowUpDown v-else class="h-3 w-3 opacity-40" />
                  </span>
                </button>
              </th>
              <th scope="col" :aria-sort="ariaSortOf('conf')">
                <button type="button" class="sort-btn w-full" @click="toggleSort('conf')">
                  <span class="inline-flex w-full items-center gap-1">
                    <span>{{ t('dash.matrix.matrix.col.decision') }}</span>
                    <ArrowUp v-if="sortKey === 'conf' && sortOrder === 'asc'" class="h-3 w-3" />
                    <ArrowDown v-else-if="sortKey === 'conf' && sortOrder === 'desc'" class="h-3 w-3" />
                    <ArrowUpDown v-else class="h-3 w-3 opacity-40" />
                  </span>
                </button>
              </th>
              <th scope="col" class="text-right">{{ t('dash.matrix.colActions') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr
              v-for="f in processedRows"
              :key="f.instId"
              class="clickable transition-colors hover:bg-[var(--surface-2)]"
              tabindex="0"
              @click="openDetail(f)"
              @keydown.enter="openDetail(f)"
              @keydown.space.prevent="openDetail(f)"
            >
              <td>
                <div class="flex items-center gap-2">
                  <CryptoLogo :symbol="f.name" :size="18" />
                  <span class="num font-mono font-semibold text-xs text-[var(--ink-strong)]">{{ f.name }}</span>
                  <span v-if="regimeOf(f)" class="text-3xs font-mono text-[var(--ink-3)] hidden 2xl:inline">
                    {{ regimeOf(f) }}
                  </span>
                </div>
              </td>
              <td class="col-num font-mono">{{ fmtPrice(f.price) }}</td>
              <td class="col-num font-mono" :class="dirClass(f.chg24h)">
                {{ arrow(f.chg24h) }} {{ fmtPct(f.chg24h, 2, false) }}
              </td>
              <td class="col-num font-mono" :class="dirClass(f.calculus?.velocity_1h)">
                {{ fmtNum(f.calculus?.velocity_1h, 3) }}
              </td>
              <td class="col-num font-mono" :class="dirClass(f.calculus?.accel_1h)">
                {{ fmtNum(f.calculus?.accel_1h, 4) }}
              </td>
              <td class="col-num font-mono" :style="{ color: (f.adx_1h ?? 0) < 18 ? 'var(--ink-3)' : 'var(--ink-1)' }">
                {{ fmtNum(f.adx_1h, 1) }}
              </td>
              <td class="col-num font-mono">{{ lsOf(f) }}</td>
              <td>
                <div class="flex items-center gap-1.5">
                  <span
                    class="rounded border px-1.5 py-0.5 text-3xs font-semibold uppercase"
                    :class="actionMeta(actionOf(f)).cls"
                  >
                    {{ actionMeta(actionOf(f)).label }}
                  </span>
                  <ConfBadge v-if="actionOf(f) !== 'WAIT'" :value="f.decision?.confidence ?? f.confidence" />
                </div>
              </td>
              <td class="text-right" @click.stop>
                <button type="button"
                  class="btn btn-quiet h-6 px-2 text-3xs font-medium cursor-pointer inline-flex items-center gap-1"
                  :title="t('dash.matrix.chartTip')"
                  @click="onQuickChart($event, f.instId)"
                >
                  <Crosshair class="h-3 w-3 text-[var(--accent)]" />
                  <span>{{ t('dash.matrix.chartBtn') }}</span>
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>

      <!-- 移动端卡片视图 -->
      <div class="grid grid-cols-1 gap-2 p-2.5 sm:grid-cols-2 lg:hidden">
        <div
          v-for="f in processedRows"
          :key="f.instId"
          class="clickable dsh-card-sub flex flex-col gap-1.5 p-3 text-left transition-colors hover:border-[var(--line-2)]"
          role="button"
          tabindex="0"
          @click="openDetail(f)"
          @keydown.enter="openDetail(f)"
          @keydown.space.prevent="openDetail(f)"
        >
          <div class="flex items-center justify-between gap-2">
            <span class="flex items-center gap-2 text-xs font-bold text-[var(--ink-strong)]">
              <CryptoLogo :symbol="f.name" :size="16" />{{ f.name }}
            </span>
            <div class="flex items-center gap-1">
              <span
                class="rounded border px-1.5 py-0.5 text-3xs font-semibold uppercase"
                :class="actionMeta(actionOf(f)).cls"
              >
                {{ actionMeta(actionOf(f)).label }}
              </span>
              <button type="button"
                class="btn btn-quiet btn-icon h-6 w-6 cursor-pointer"
                :title="t('dash.matrix.chartBtn')"
                @click="onQuickChart($event, f.instId)"
              >
                <Crosshair class="h-3 w-3 text-[var(--accent)]" />
              </button>
            </div>
          </div>
          <div class="flex items-baseline justify-between text-xs">
            <span class="num font-mono font-semibold">{{ fmtPrice(f.price) }}</span>
            <span class="num font-mono" :class="dirClass(f.chg24h)">{{ arrow(f.chg24h) }} {{ fmtPct(f.chg24h, 2, false) }}</span>
          </div>
          <div class="flex justify-between text-3xs text-[var(--ink-3)] font-mono">
            <span>v {{ fmtNum(f.calculus?.velocity_1h, 3) }} · a {{ fmtNum(f.calculus?.accel_1h, 4) }}</span>
            <span>ADX {{ fmtNum(f.adx_1h, 1) }}</span>
          </div>
        </div>
      </div>
    </template>

    <FactorDrawer
      :factor="detail"
      @close="detail = null"
      @pick-symbol="(id: string) => { detail = null; emit('pick-symbol', id) }"
    />
  </div>
</template>
