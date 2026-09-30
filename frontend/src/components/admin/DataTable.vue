<script setup lang="ts" generic="T extends Record<string, any>">
/** 共享表格原语（结构优化阶段 3·F1 升级版）。
 *
 * ## 背景：F1 的原状是"最坏的状态"
 *
 * 本组件原先只有 `AuditPage` 一个消费者，而另外 8 个管理页各写各的
 * `<table>/<thead>/<tbody>`（共 12 张表）。于是"表格已统一"是个假象：
 * 排序/空态/加载态/行高/分隔线在 9 个页面里被实现 9 次。
 *
 * ## 为什么升级成"外壳 + row 槽"，而不是"columns + cell-* 槽"
 *
 * 逐页实测后判断：各页表格**同构**（5~7 列、遍历列表），但**每格渲染高度定制**
 * （名称下方子行、色标、条件按钮、i18n 拼接）。若用 columns + `cell-*` 槽，
 * 早期 PluginsPage 一张 6 列表就要写 4 个槽 —— 抽象立刻变成负担，迁移成本高还容易漏。
 * （该页已于 2026-09-30 后台精简中删除；此处保留当初的判断依据。）
 *
 * 所以本组件统一的是**外壳与行为**（容器、thead 结构、行高、分隔线、hover、
 * 空态、加载态、排序、点击行），把**每格长什么样**留给 `#row` 槽原样书写：
 * ```vue
 * <DataTable :rows="data.plugins" :row-key="p => p.plugin_id" :empty-text="t('…')" flat>
 *   <template #head><th>…</th></template>
 *   <template #row="{ row: p }"><td>…</td></template>
 * </DataTable>
 * ```
 * 迁移因此近乎机械：换外壳、搬 `<td>` 原文，不重写渲染逻辑。
 *
 * ## 兼容
 *
 * 原 `columns` 用法**完全保留**（AuditPage 不用改）：给了 `columns` 但没给 `#row`
 * 时，按列定义渲染，并继续支持 `cell-<key>` 与 `actions` 槽。
 *
 * ## 行为约定（从 AuditPage 的既有观感继承）
 *  - sticky 表头、紧凑行高、发丝分隔线（无斑马纹）
 *  - 数值列右对齐 + 等宽数字（`column.align === 'right'` 或 `mono`）
 *  - `sortable` 打开后，列头可点：升序 → 降序 → 还原；**不改动传入的 rows**
 *    （内部对副本排序），避免"组件悄悄改父级状态"。
 *  - `loading` 为真时渲染加载行（优先 `#loading` 槽），而不是"空表 + 空态文案"，
 *    否则加载中与"确实没有数据"在界面上无法区分。
 *
 * ## `#head` 槽包住**整个 `<tr>`**
 *
 * 这是为迁移刻意选的形状：各页原有 `<thead><tr class="…">` 上的样式
 * （`border-b` / `text-4xs uppercase tracking-wider font-bold` / 背景色）挂在 **tr** 上，
 * 若槽只包 `<th>`，迁移时就得把这些类拆到每个 th 上 —— 既繁琐又容易改出视觉差异。
 * 让槽包整个 tr，页面即可**原样搬入自己的表头行**，做到外观零变化。
 */
import { computed, ref, useSlots } from 'vue'
import { ChevronDown, ChevronUp, ChevronsUpDown, Loader2 } from 'lucide-vue-next'

export interface DataTableColumn {
  key: string
  label: string
  align?: 'left' | 'right' | 'center'
  width?: string
  mono?: boolean
  /** 该列是否可点表头排序（需组件级 `sortable` 打开） */
  sortable?: boolean
  /** 排序取值函数；缺省取 row[key] */
  sortValue?: (row: any) => any
}

const props = withDefaults(defineProps<{
  /** 列定义；使用 `#row` 整行槽时可不传 */
  columns?: DataTableColumn[]
  rows: T[]
  rowKey?: (row: T, i: number) => string | number
  emptyText?: string
  /** flat: 不套自己的卡片外壳 —— 嵌在已有面板里时用 */
  flat?: boolean
  /** 可点击行（视觉提示；行为走 @row-click） */
  clickable?: boolean
  /** 加载中：渲染加载行而非空态 */
  loading?: boolean
  loadingText?: string
  /** 是否允许按列排序（列上还需 sortable: true） */
  sortable?: boolean
  /** 追加到 <tr> 上的类（批 34：消费方需要自定义行样式时用它，
   *  不要在 #row 槽里再套一层 <tr> —— 那是无效嵌套，会让行高一分为二） */
  rowClass?: string
  /** 表格的可访问名（批 44）。读屏器进入表格时应先播报"这是什么表"，
   *  只靠周围的标题不可靠（标题在表格外，不构成关联）。 */
  label?: string
}>(), {
  columns: () => [],
  loading: false,
  sortable: false,
  flat: false,
  clickable: false,
  rowClass: '',
})

const emit = defineEmits<{
  (e: 'row-click', row: T): void
  (e: 'sort', payload: { key: string; dir: 'asc' | 'desc' | null }): void
}>()

defineSlots<{
  head?: () => any
  row?: (props: { row: T; index: number }) => any
  loading?: () => any
  [name: `cell-${string}`]: (props: { row: any; value: any }) => any
  actions?: (props: { row: any }) => any
}>()

const slots = useSlots()
const has = (name: string) => !!slots[name]

// ── 排序状态 ──────────────────────────────────────────────
const sortKey = ref<string | null>(null)
const sortDir = ref<'asc' | 'desc' | null>(null)

/** `aria-sort` 取值：只有当前排序列才报方向，其余为 none（屏幕阅读器据此播报）。 */
function ariaSortOf(col: DataTableColumn): 'ascending' | 'descending' | 'none' {
  if (sortKey.value !== col.key || !sortDir.value) return 'none'
  return sortDir.value === 'asc' ? 'ascending' : 'descending'
}

function toggleSort(col: DataTableColumn) {
  if (!props.sortable || !col.sortable) return
  if (sortKey.value !== col.key) {
    sortKey.value = col.key
    sortDir.value = 'asc'
  } else if (sortDir.value === 'asc') {
    sortDir.value = 'desc'
  } else {
    // 第三次点击还原 —— 用户要能回到后端给的原始顺序
    sortKey.value = null
    sortDir.value = null
  }
  emit('sort', { key: sortKey.value ?? col.key, dir: sortDir.value })
}

function valueOf(col: DataTableColumn, row: T) {
  return col.sortValue ? col.sortValue(row) : (row as any)[col.key]
}

/** 排序在副本上做，绝不改动传入的 rows */
const displayRows = computed<T[]>(() => {
  const key = sortKey.value
  const dir = sortDir.value
  if (!key || !dir) return props.rows
  const col = props.columns.find((c) => c.key === key)
  if (!col) return props.rows
  const factor = dir === 'asc' ? 1 : -1
  return [...props.rows].sort((a, b) => {
    const va = valueOf(col, a)
    const vb = valueOf(col, b)
    if (va == null && vb == null) return 0
    // 空值恒排末尾（升降序都一样），避免"空值占头"
    if (va == null) return 1
    if (vb == null) return -1
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * factor
    return String(va).localeCompare(String(vb), 'zh-Hans-CN') * factor
  })
})

const colCount = computed(() => props.columns.length + (has('actions') ? 1 : 0))
</script>

<template>
  <div
    class="overflow-x-auto"
    :class="flat ? '' : 'rounded-xl border'"
    :style="flat ? {} : { borderColor: 'var(--line-1)', backgroundColor: 'var(--surface-2)' }"
  >
    <table class="w-full text-xs border-collapse" :aria-label="label" :aria-busy="loading ? 'true' : undefined">
      <thead>
        <slot name="head">
          <tr class="sticky top-0 z-10" style="background-color: var(--surface-2);">
            <!-- 批 43：可排序表头改成**真按钮**。
                 此前 `@click` 挂在 `<th>` 上 —— 鼠标能排序，键盘用户完全够不着
                 （`<th>` 不可聚焦、不响应 Enter），屏幕阅读器也不知道它能点。
                 现在：`<th>` 带 `aria-sort`（语义），里面是裸按钮（可聚焦 + Enter/Space）。
                 外观由 `.sort-btn` 保证与原来的纯文本一致。 -->
            <th scope="col"
              v-for="col in columns"
              :key="col.key"
              class="px-3 py-2 text-4xs font-bold uppercase tracking-wider border-b whitespace-nowrap"
              :aria-sort="sortable && col.sortable ? ariaSortOf(col) : undefined"
              :style="{ color: 'var(--ink-3)', borderColor: 'var(--line-1)', textAlign: col.align || 'left', width: col.width || 'auto' }"
            >
              <button
                v-if="sortable && col.sortable"
                type="button"
                class="sort-btn"
                :style="{ width: '100%', justifyContent: col.align === 'right' ? 'flex-end' : 'flex-start' }"
                :title="col.label"
                @click="toggleSort(col)"
              >
                {{ col.label }}
                <ChevronUp v-if="sortKey === col.key && sortDir === 'asc'" class="w-3 h-3" />
                <ChevronDown v-else-if="sortKey === col.key && sortDir === 'desc'" class="w-3 h-3" />
                <ChevronsUpDown v-else class="w-3 h-3 opacity-40" />
              </button>
              <span v-else class="inline-flex items-center gap-1">{{ col.label }}</span>
            </th>
            <th scope="col" v-if="has('actions')" class="px-3 py-2 text-4xs font-bold uppercase tracking-wider border-b text-right" style="color: var(--ink-3); border-color: var(--line-1);">
              ·
            </th>
          </tr>
        </slot>
      </thead>
      <tbody>
        <tr v-if="loading">
          <td :colspan="Math.max(colCount, 1)" role="status" class="px-3 py-10 text-center" style="color: var(--ink-3);">
            <slot name="loading">
              <Loader2 class="w-5 h-5 animate-spin shrink-0 inline mr-1.5" style="color: var(--accent);" />
              {{ loadingText || '…' }}
            </slot>
          </td>
        </tr>
        <template v-else>
          <!-- 批 43：`clickable` 的行补键盘可达（此前只有鼠标能点行）。 -->
          <tr
            v-for="(row, i) in displayRows"
            :key="rowKey ? rowKey(row, i) : i"
            class="border-b last:border-b-0 transition-colors hover:bg-[var(--surface-3)]"
            :class="[clickable ? 'clickable' : '', rowClass]"
            :tabindex="clickable ? 0 : undefined"
            style="border-color: var(--line-1);"
            @click="emit('row-click', row)"
            @keydown.enter="clickable && emit('row-click', row)"
            @keydown.space.prevent="clickable && emit('row-click', row)"
          >
            <slot name="row" :row="row" :index="i">
              <td
                v-for="col in columns"
                :key="col.key"
                class="px-3 py-[7px] whitespace-nowrap"
                :class="col.align === 'right' || col.mono ? 'num' : ''"
                :style="{ textAlign: col.align || 'left', color: 'var(--ink-1)' }"
              >
                <slot :name="`cell-${col.key}`" :row="row" :value="(row as any)[col.key]">
                  {{ (row as any)[col.key] ?? '--' }}
                </slot>
              </td>
              <td v-if="has('actions')" class="px-3 py-[7px] text-right whitespace-nowrap">
                <div class="inline-flex items-center gap-2">
                  <slot name="actions" :row="row" />
                </div>
              </td>
            </slot>
          </tr>
          <tr v-if="!displayRows.length">
            <td :colspan="Math.max(colCount, 1)" role="status" class="px-3 py-10 text-center" style="color: var(--ink-3);">
              {{ emptyText || '—' }}
            </td>
          </tr>
        </template>
      </tbody>
    </table>
  </div>
</template>
