<script setup lang="ts">
/**
 * NewsView.vue · DeepSeek Harness 风格舆情快讯与重大黑天鹅情报看板
 * 包含：重大黑天鹅熔断预警带、币种情绪极性矩阵（支持移动端折叠与防挤压排版）、多源情报流（OKX/金十/全球宏观）与关键词检索
 */
import { computed, ref } from 'vue';
import {
  ExternalLink,
  ShieldAlert,
  Radio,
  X,
  Flame,
  ChevronDown,
  ChevronUp,
  Search,
} from 'lucide-vue-next';
import { useDashboardStore } from '../../stores/dashboard';
import DataGate from '../../components/dashboard/DataGate.vue';
import { useI18n } from '../../composables/useI18n';
import { useRovingTabs } from '../../composables/useRovingTabs';
import { fmtHM } from '../../utils/format';
import BaseEmpty from '../../components/base/BaseEmpty.vue';
import TimeAgo from '../../components/base/TimeAgo.vue';
import CryptoLogo from '../../components/dashboard/CryptoLogo.vue';

const store = useDashboardStore();
const { t } = useI18n();

const selectedCoin = ref<string | null>(null);
const selectedSource = ref<string>('all');
const searchQuery = ref<string>('');
const isBandCollapsed = ref<boolean>(false);

const cryptoNewsCount = computed(() => rawNews.value.filter((item) =>
  (item.platforms || []).some((p: string) => ['Cointelegraph', 'CoinDesk', 'TheBlock', 'Binance'].some((k) => p.includes(k))) || (item.coins && item.coins.length > 0)
).length);

const jin10NewsCount = computed(() => rawNews.value.filter((item) =>
  (item.platforms || []).some((p: string) => p.includes('金十'))
).length);

const macroNewsCount = computed(() => rawNews.value.filter((item) =>
  (item.platforms || []).some((p: string) => p.includes('宏观') || p.includes('华尔街') || p.includes('新浪'))
).length);

const sourceFilters = computed(() => [
  { key: 'all', label: `${t('dash.news.filters.all')} (${rawNews.value.length})` },
  { key: 'crypto', label: `${t('dash.news.filters.crypto')} (${cryptoNewsCount.value})` },
  { key: 'jin10', label: `${t('dash.news.filters.jin10')} (${jin10NewsCount.value})` },
  { key: 'macro', label: `${t('dash.news.filters.macro')} (${macroNewsCount.value})` },
]);

/** 来源筛选分段的漫游 tabindex 与方向键导航。 */
const { setRef: setSourceRef, onKeydown: onSourceKey, roving: sourceRoving } = useRovingTabs(
  () => sourceFilters.value.length,
  (i) => { selectedSource.value = sourceFilters.value[i].key; },
);

const ni = computed<any>(() => (store.data as any)?.news_intelligence || {});
const macro = computed(() => ni.value.macro_sentiment || t('dash.news.macroDefault'));
const rawNews = computed<any[]>(() => ni.value.latest_news || []);
const freshAt = computed(() => ni.value.news_fresh_at || ni.value.timestamp || '');
const sourceReason = computed(() => ni.value.source_reason || t('dash.news.sourceReasonDefault'));
const isSourceActive = computed(() => ni.value.source_available === true);

// 黑天鹅熔断状态
const circuitBreaker = computed<any>(() => {
  const cb = ni.value.circuit_breaker;
  if (cb && typeof cb === 'object') return cb;
  return { active: false };
});
const isCbActive = computed(() => Boolean(circuitBreaker.value?.active));

// 币种情绪极性矩阵数据
const coins = computed(() => {
  const cs = ni.value.coins_sentiment || {};
  return Object.entries(cs)
    .map(([sym, v]: [string, any]) => {
      const bull = Math.max(0, Math.min(100, parseFloat(v.bullish_ratio) || 0));
      const bear = Math.max(0, Math.min(100, parseFloat(v.bearish_ratio) || 0));
      const score = typeof v.sentiment_factor_score === 'number' ? v.sentiment_factor_score : 0;
      return {
        sym,
        label: v.label || 'neutral',
        bull,
        bear,
        score,
        ls: v.long_short_ratio,
        mentions: Number(v.mentions) || 0,
      };
    })
    .sort((a, b) => (b.mentions || 0) - (a.mentions || 0));
});

// 按选中币种、来源与关键词过滤后的快讯流
const filteredNews = computed(() => {
  let list = rawNews.value;
  if (selectedSource.value === 'crypto') {
    list = list.filter((item) =>
      (item.platforms || []).some((p: string) => ['Cointelegraph', 'CoinDesk', 'TheBlock', 'Binance'].some((k) => p.includes(k))) || (item.coins && item.coins.length > 0)
    );
  } else if (selectedSource.value === 'jin10') {
    list = list.filter((item) => (item.platforms || []).some((p: string) => p.includes('金十')));
  } else if (selectedSource.value === 'macro') {
    list = list.filter((item) => (item.platforms || []).some((p: string) => p.includes('宏观') || p.includes('华尔街') || p.includes('新浪')));
  } else if (selectedSource.value !== 'all') {
    list = list.filter((item) => (item.platforms || []).some((p: string) => p.includes(selectedSource.value)));
  }

  if (selectedCoin.value) {
    const target = selectedCoin.value.toUpperCase();
    list = list.filter((item) => {
      const coinList = (item.coins || []).map((c: string) => String(c).toUpperCase());
      if (coinList.includes(target)) return true;
      const title = String(item.title || '').toUpperCase();
      const summary = String(item.summary || '').toUpperCase();
      return title.includes(target) || summary.includes(target);
    });
  }

  const query = searchQuery.value.trim().toUpperCase();
  if (query) {
    list = list.filter((item) => {
      const title = String(item.title || '').toUpperCase();
      const summary = String(item.summary || '').toUpperCase();
      const platforms = (item.platforms || []).join(' ').toUpperCase();
      const coinList = (item.coins || []).join(' ').toUpperCase();
      return title.includes(query) || summary.includes(query) || platforms.includes(query) || coinList.includes(query);
    });
  }

  return list;
});

function toggleCoinFilter(sym: string) {
  if (selectedCoin.value === sym) {
    selectedCoin.value = null;
  } else {
    selectedCoin.value = sym;
  }
}
</script>

<template>
  <div class="space-y-3">
    <!-- 页头：移动端分层自适应，彻底杜绝单字竖排挤压断行 -->
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2.5 pt-0.5">
      <div class="flex items-center gap-2 flex-wrap min-w-0">
        <h1 class="text-xs sm:text-sm font-bold tracking-tight text-[var(--ink-strong)] flex items-center gap-1.5 whitespace-nowrap shrink-0">
          <Radio class="h-3.5 w-3.5 text-[var(--accent)] shrink-0" />
          {{ t('dash.news.title') }}
        </h1>
        <span
          class="rounded-full px-2 py-0.5 border text-3xs font-mono font-medium whitespace-nowrap shrink-0"
          style="background-color: var(--surface-2); border-color: var(--line-1); color: var(--ink-2)"
        >
          {{ t('dash.news.count', undefined, { n: rawNews.length }) }}
        </span>
        <span
          class="rounded-full px-2 py-0.5 border text-3xs font-medium whitespace-nowrap shrink-0 inline-flex items-center gap-1"
          :class="macro.includes('多') ? 'text-[var(--up)] border-[var(--up-line)] bg-[var(--up-bg)]' : macro.includes('空') ? 'text-[var(--down)] border-[var(--down-line)] bg-[var(--down-bg)]' : 'text-[var(--ink-2)] border-[var(--line-1)] bg-[var(--surface-2)]'"
        >
          <span class="inline-block h-1.5 w-1.5 rounded-full shrink-0" :class="macro.includes('多') ? 'bg-[var(--up)] animate-pulse' : macro.includes('空') ? 'bg-[var(--down)] animate-pulse' : 'bg-[var(--ink-3)]'" />
          <span>{{ macro }}</span>
        </span>
      </div>

      <!-- 信源状态与新鲜度：防溢出保护 + 优雅换行 -->
      <div class="flex flex-wrap items-center gap-1.5 max-w-full min-w-0">
        <span class="dsh-pill max-w-full min-w-0 whitespace-nowrap" :title="sourceReason">
          <span class="dsh-status-dot shrink-0" :class="isSourceActive ? 'active' : 'warn'" aria-hidden="true" />
          <span class="text-[var(--ink-2)] truncate min-w-0">{{ isSourceActive ? sourceReason : t('status.attention') }}</span>
        </span>
        <span
          v-if="!isSourceActive && sourceReason"
          class="text-3xs whitespace-nowrap shrink-0"
          style="color: var(--warn)"
          data-test="news-source-reason"
        >
          {{ sourceReason }}
        </span>
        <span v-if="freshAt" class="dsh-pill text-3xs font-mono text-[var(--ink-3)] whitespace-nowrap shrink-0">
          <span>{{ t('dash.news.freshness') }}</span>
          <TimeAgo :time="freshAt" />
        </span>
      </div>
    </div>

    <DataGate>
      <!-- 黑天鹅重大熔断预警卡 -->
      <div
        v-if="isCbActive"
        class="dsh-card p-3.5 border-[var(--down-line)] bg-[var(--down-bg)]"
      >
        <div class="flex items-start gap-3">
          <ShieldAlert class="h-5 w-5 text-[var(--down)] shrink-0 mt-0.5" />
          <div class="flex-1 space-y-1">
            <div class="flex items-center justify-between">
              <h3 class="text-xs font-bold text-[var(--down)] uppercase tracking-wider">
                {{ circuitBreaker.headline || t('dash.news.cb.headlineFallback') }}
              </h3>
              <span class="dsh-pill border-[var(--down-line)] text-[var(--down)] font-mono text-3xs">
                {{ t('dash.news.cb.badge') }}
              </span>
            </div>
            <p class="text-xs text-[var(--ink-1)] leading-body">
              {{ circuitBreaker.reason || circuitBreaker.detail || t('dash.news.cb.actionFallback') }}
            </p>
          </div>
        </div>
      </div>

      <!-- 币种情绪极性矩阵 (Coin Sentiment Polarity Matrix) -->
      <div v-if="coins.length" class="dsh-card overflow-hidden">
        <header class="dsh-card-header flex items-center justify-between gap-2">
          <div class="flex items-center gap-2 min-w-0">
            <h2 class="text-xs font-bold uppercase tracking-wider text-[var(--ink-strong)] flex items-center gap-1.5 whitespace-nowrap shrink-0">
              <Flame class="h-3.5 w-3.5 text-[var(--accent)] shrink-0" />
              {{ t('dash.news.band.title') }}
            </h2>
            <p class="text-3xs text-[var(--ink-3)] truncate hidden sm:inline">{{ t('dash.news.band.desc') }}</p>
          </div>

          <div class="flex items-center gap-1.5 shrink-0">
            <button
              v-if="selectedCoin"
              type="button"
              class="btn btn-ghost h-6 px-2 text-3xs font-medium cursor-pointer inline-flex items-center gap-1 text-[var(--accent)] border border-[var(--accent)]/30 rounded"
              :aria-label="`${t('dash.news.clearFilter')} (${selectedCoin})`"
              @click="selectedCoin = null"
            >
              <X class="h-3 w-3 shrink-0" />
              <span class="whitespace-nowrap">{{ t('dash.news.clearFilter') }} (${{ selectedCoin }})</span>
            </button>

            <!-- 折叠/展开多空面板开关 -->
            <button
              type="button"
              class="btn btn-ghost h-6 px-2 text-3xs font-medium cursor-pointer inline-flex items-center gap-1 text-[var(--ink-2)] hover:text-[var(--ink-strong)] rounded"
              :aria-label="isBandCollapsed ? t('dash.news.expandBand') : t('dash.news.collapseBand')"
              :aria-expanded="!isBandCollapsed"
              :aria-controls="coins.length ? 'news-sentiment-band' : undefined"
              @click="isBandCollapsed = !isBandCollapsed"
            >
              <span class="whitespace-nowrap">{{ isBandCollapsed ? t('dash.news.expandBand') : t('dash.news.collapseBand') }}</span>
              <ChevronDown v-if="isBandCollapsed" class="h-3 w-3 shrink-0" />
              <ChevronUp v-else class="h-3 w-3 shrink-0" />
            </button>
          </div>
        </header>

        <!-- 极性卡片网格 -->
        <div id="news-sentiment-band" v-show="!isBandCollapsed" class="grid grid-cols-2 gap-2 p-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 border-b border-[var(--line-1)]/40">
          <button
            v-for="c in coins"
            :key="c.sym"
            type="button"
            class="dsh-card-sub p-2.5 text-left transition-all cursor-pointer relative flex flex-col justify-between"
            :class="selectedCoin === c.sym ? 'border-[var(--accent)] bg-[var(--surface-3)] shadow-sm shadow-[var(--accent)]/10 ring-1 ring-[var(--accent)]/30' : 'hover:border-[var(--line-2)]'"
            :aria-pressed="selectedCoin === c.sym"
            :aria-label="`${c.sym} ${t('dash.news.filterCoin', undefined, { sym: c.sym })}`"
            @click="toggleCoinFilter(c.sym)"
          >
            <!-- 头部：Logo + 币种 + 状态 -->
            <div class="flex items-center justify-between gap-1 mb-1.5">
              <div class="flex items-center gap-1.5 min-w-0">
                <CryptoLogo :symbol="c.sym" :size="16" class="shrink-0" />
                <span class="font-mono font-bold text-xs text-[var(--ink-strong)] truncate">{{ c.sym }}</span>
              </div>
              <span
                class="rounded px-1 py-0.5 text-4xs font-mono font-semibold uppercase border shrink-0 whitespace-nowrap"
                :class="c.label === 'bullish' ? 'text-[var(--up)] border-[var(--up-line)] bg-[var(--up-bg)]' : c.label === 'bearish' ? 'text-[var(--down)] border-[var(--down-line)] bg-[var(--down-bg)]' : 'text-[var(--ink-3)] border-[var(--line-1)] bg-[var(--surface-2)]'"
              >
                {{ c.label === 'bullish' ? t('common.dir.long') : c.label === 'bearish' ? t('common.dir.short') : t('common.dir.flat') }}
              </span>
            </div>

            <!-- 多空力量条 -->
            <div
              class="h-1.5 w-full overflow-hidden rounded bg-[var(--down)] flex mb-1.5"
              role="progressbar"
              :aria-valuenow="Math.round(c.bull)"
              aria-valuemin="0"
              aria-valuemax="100"
              :aria-label="`${c.sym} ${t('dash.news.ratioLabel')}`"
              :aria-valuetext="`${Math.round(c.bull)}% / ${Math.round(100 - c.bull)}%`"
            >
              <div
                class="h-full bg-[var(--up)] transition-all"
                :style="{ width: `${c.bull}%` }"
              />
            </div>

            <!-- 多空比例与指标（两行清晰排布，彻底根除挤压折断） -->
            <div class="space-y-1">
              <div class="flex items-center justify-between text-4xs font-mono whitespace-nowrap">
                <span class="text-[var(--up)] font-medium">{{ t('dash.news.pctBull', undefined, { n: c.bull.toFixed(0) }) }}</span>
                <span class="text-[var(--down)] font-medium">{{ t('dash.news.pctBear', undefined, { n: c.bear.toFixed(0) }) }}</span>
              </div>
              <div class="flex items-center justify-between text-4xs font-mono text-[var(--ink-3)] pt-1 border-t border-[var(--line-1)]/50 whitespace-nowrap">
                <span :title="t('dash.news.ratioHint')">
                  {{ t('dash.news.ratioLabel') }} <strong class="text-[var(--ink-2)] font-semibold">{{ c.ls || '--' }}</strong>
                </span>
                <span v-if="c.mentions > 0" class="text-3xs text-[var(--accent)] font-medium">
                  {{ t('dash.news.mentions', undefined, { n: c.mentions }) }}
                </span>
                <span v-else class="text-[var(--ink-4)]">--</span>
              </div>
            </div>
          </button>
        </div>

        <!-- 底部微提示栏 -->
        <div v-show="!isBandCollapsed" class="px-3 py-1.5 text-4xs text-[var(--ink-3)] flex items-center justify-between bg-[var(--surface-2)]/30">
          <span>{{ t('dash.news.matrixHint') }}</span>
          <span v-if="selectedCoin" class="text-[var(--accent)] font-medium">{{ t('dash.news.selectedFilter') }}: ${{ selectedCoin }}</span>
        </div>
      </div>

      <!-- 舆情快讯情报流 (News Stream) -->
      <div class="dsh-card overflow-hidden min-h-[480px] flex flex-col">
        <!-- 筛选与搜索栏 -->
        <header class="dsh-card-header flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2.5 min-w-0">
          <!-- 来源 Tab 组：移动端横向滑动，带防越界与平滑手势 -->
          <div class="w-full sm:w-auto min-w-0 max-w-full overflow-x-auto scrollbar-none -mx-1 px-1 py-0.5" style="-webkit-overflow-scrolling: touch;">
            <div class="seg inline-flex shrink-0 whitespace-nowrap" role="tablist" :aria-label="t('dash.news.feed.source')">
              <button
                v-for="(f, fi) in sourceFilters"
                :key="f.key"
                :ref="setSourceRef(fi)"
                type="button"
                role="tab"
                :aria-selected="selectedSource === f.key"
                :tabindex="sourceRoving(selectedSource === f.key)"
                :class="{ 'seg-on': selectedSource === f.key }"
                @click="selectedSource = f.key"
                @keydown="onSourceKey($event, fi)"
              >
                {{ f.label }}
              </button>
            </div>
          </div>

          <!-- 搜索与条数指示 -->
          <div class="flex items-center gap-2 justify-between sm:justify-end min-w-0 w-full sm:w-auto">
            <div class="relative flex items-center flex-1 sm:w-56">
              <Search class="absolute left-2 h-3.5 w-3.5 text-[var(--ink-3)] pointer-events-none shrink-0" aria-hidden="true" />
              <input
                v-model="searchQuery"
                type="search"
                autocomplete="off"
                spellcheck="false"
                :placeholder="t('dash.news.searchPlaceholder')"
                :aria-label="t('dash.news.searchPlaceholder')"
                class="pl-7 pr-6 h-7 text-xs w-full bg-[var(--surface-2)] rounded border border-[var(--line-1)] focus:border-[var(--accent)] text-[var(--ink-1)] outline-none"
              />
              <button
                v-if="searchQuery"
                type="button"
                class="absolute right-1.5 p-0.5 text-[var(--ink-3)] hover:text-[var(--ink-1)] cursor-pointer"
                :aria-label="t('dash.news.clearSearch')"
                @click="searchQuery = ''"
              >
                <X class="h-3 w-3" />
              </button>
            </div>

            <div class="hidden sm:inline-block text-3xs text-[var(--ink-3)] font-mono whitespace-nowrap shrink-0">
              {{ t('dash.news.countNews', undefined, { a: filteredNews.length, b: rawNews.length }) }}
            </div>
          </div>
        </header>

        <!-- 空态 -->
        <BaseEmpty v-if="!filteredNews.length" class="flex-1 flex items-center justify-center py-12" :text="t('dash.news.feed.empty')" />

        <!-- 快讯卡片列表 -->
        <div v-else class="divide-y flex-1" style="border-color: var(--line-1)">
          <article
            v-for="item in filteredNews"
            :key="item.id || item.title"
            class="p-3 sm:p-4 transition-colors hover:bg-[var(--surface-2)] flex flex-col gap-2 border-l-2"
            :class="item.importance === 'high' ? 'border-l-[var(--down)] bg-[var(--down-bg)]/10' : 'border-l-transparent hover:border-l-[var(--accent)]'"
          >
            <div class="flex flex-wrap items-center justify-between gap-2">
              <div class="flex items-center gap-2 flex-wrap">
                <!-- 时间 -->
                <span class="num font-mono text-xs font-semibold text-[var(--ink-strong)] whitespace-nowrap">
                  {{ fmtHM(item.timestamp || item.time) }}
                </span>

                <!-- 重要度 -->
                <span
                  v-if="item.importance === 'high'"
                  class="rounded px-1.5 py-0.5 text-4xs font-mono font-bold uppercase text-[var(--down)] border border-[var(--down-line)] bg-[var(--down-bg)] inline-flex items-center gap-1 shrink-0"
                >
                  <span class="h-1 w-1 rounded-full bg-[var(--down)] animate-ping" />
                  HIGH
                </span>

                <!-- 来源渠道 -->
                <span
                  v-for="p in (item.platforms || [])"
                  :key="p"
                  class="rounded px-1.5 py-0.5 text-4xs font-mono text-[var(--ink-2)] border border-[var(--line-1)] bg-[var(--surface-2)] shrink-0"
                >
                  {{ p }}
                </span>

                <!-- 关联币种 -->
                <button
                  v-for="coin in (item.coins || [])"
                  :key="coin"
                  type="button"
                  class="rounded px-1.5 py-0.5 text-4xs font-mono font-bold border cursor-pointer transition-colors shrink-0"
                  :class="selectedCoin === coin ? 'text-[var(--accent)] border-[var(--accent)] bg-[var(--surface-3)] ring-1 ring-[var(--accent)]' : 'text-[var(--accent)] border-[var(--line-2)] hover:bg-[var(--surface-3)]'"
                  :aria-pressed="selectedCoin === coin"
                  :aria-label="t('dash.news.filterCoin', undefined, { sym: coin })"
                  @click="toggleCoinFilter(coin)"
                >
                  ${{ coin }}
                </button>
              </div>

              <!-- 外链 -->
              <a
                v-if="item.url"
                :href="item.url"
                target="_blank"
                rel="noopener noreferrer"
                class="relative text-3xs text-[var(--ink-3)] hover:text-[var(--accent)] inline-flex items-center gap-1 transition-colors px-1 -mx-1 py-1 -my-1 shrink-0 whitespace-nowrap"
              >
                <span>{{ t('common.more') }}</span>
                <span class="sr-only">{{ t('common.opensInNewTab') }}</span>
                <ExternalLink class="h-3 w-3" aria-hidden="true" />
              </a>
            </div>

            <!-- 标题与正文 -->
            <h3 class="text-xs font-bold text-[var(--ink-strong)] leading-snug">
              {{ item.title }}
            </h3>
            <p v-if="item.summary && item.summary.trim() !== item.title.trim() && !item.summary.includes(item.title)" class="text-xs text-[var(--ink-2)] leading-relaxed font-sans">
              {{ item.summary }}
            </p>
          </article>
        </div>

        <!-- 底部结束提示，消除移动端大幅留白错觉 -->
        <footer
          v-if="filteredNews.length"
          class="mt-auto p-3.5 text-center text-3xs text-[var(--ink-3)] font-mono flex items-center justify-center gap-2 border-t border-[var(--line-1)] bg-[var(--surface-1)]/40"
        >
          <span class="h-px w-8 bg-[var(--line-1)]" aria-hidden="true" />
          <span>{{ t('dash.news.feedEnd') }}</span>
          <span class="h-px w-8 bg-[var(--line-1)]" aria-hidden="true" />
        </footer>
      </div>
    </DataGate>
  </div>
</template>
