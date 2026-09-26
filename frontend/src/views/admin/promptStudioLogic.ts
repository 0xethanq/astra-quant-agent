/**
 * 提示词工作室（`PromptStudioPage.vue`）的纯逻辑（结构优化阶段 4·B3 第三十五刀）。
 *
 * 原样搬自 `frontend/src/views/admin/PromptStudioPage.vue` 的 script setup：
 * 六段**纯函数**（给定入参就有确定输出），与 Vue 响应式、网络、组件状态无关。
 *
 * | 函数 | 决定什么 |
 * |---|---|
 * | `renderSourceBadge` | 模块来源徽标（base/legacy/custom，**其它一律 `null`**） |
 * | `cloneModulesForEditing` | 载入编辑区：深拷贝 + **全量解锁** |
 * | `compileWorkingModules` | 编译「渲染后 Prompt」：过滤 → trim → `\n\n` 连接 |
 * | `buildTemplatePreview` | 编译「模板视图」：带回卷标头的另一种排版 |
 * | `computeInsertTarget` | 一键插变量时**钳到合法下标** |
 * | `deriveImportName` | 从文件名推默认方案名（剥 `.json` 与 `astra-strategy-`） |
 *
 * ## 五处易错点（均原样保留）
 *
 * 1. **`sourceBadge` 对未知来源返回 `null`**（不是空对象、不是默认徽标）——
 *    模板里靠 `v-if` 判断，返回 `{}` 会渲染出一个空徽标。
 * 2. **两种预览的排版不同**，不能合并：
 *    - 渲染视图：各模块 `content` 直接 trim 后 `\n\n` 连接（**无模块标题**）；
 *    - 模板视图：每块包 `======================= 【标题】 =======================`。
 *    把两者当成"同一种编译"是这类代码最常见的改错。
 * 3. **两者都先过滤掉 `!enabled` 或内容为空白串的模块**（用 `.trim()` 判空），
 *    且**先判 `enabled` 再取 `content`** —— 顺序不影响结果，但短路顺序别乱改。
 * 4. **`cloneModulesForEditing` 无条件把 `locked` 置 false**（"全量解锁，支持自由修改"），
 *    同时**深拷贝**（`JSON.parse(JSON.stringify(...))`）—— 浅拷贝会让编辑区
 *    直接改到 `lib` 里的原对象，未保存的改动就悄悄生效了。
 * 5. **`computeInsertTarget` 下标钳制是双向的**：先 `max(0, ·)` 再
 *    `min(·, len-1)`；只看一边会漏掉负数或越界的另一侧。
 *
 * ## 本模块**不**做名称规范化
 *
 * `deriveImportName` 只剥扩展名与固定前缀，不做 slug 化、不去空格 ——
 * 方案名允许中文与空格，前端只负责给个默认值。
 */

export type TFn = (path: string, fallback?: string, params?: Record<string, string | number>) => string

export interface PromptModule {
  id?: string
  title?: string
  content?: string
  enabled?: boolean
  locked?: boolean
  source?: string
}

/** 模块来源徽标；来源不在 base/legacy/custom 三者之内时返回 **`null`**。 */
export function renderSourceBadge(
  m: PromptModule | null | undefined,
  t: TFn,
): { text: string; tone: 'base' | 'legacy' | 'custom' } | null {
  const source = String(m?.source || '')
  if (source === 'base') return { text: t('admin.promptStudio.source.base'), tone: 'base' }
  if (source === 'legacy') return { text: t('admin.promptStudio.source.legacy'), tone: 'legacy' }
  if (source === 'custom') return { text: t('admin.promptStudio.source.custom'), tone: 'custom' }
  return null
}

/**
 * 载入编辑区用的模块副本：**深拷贝 + 全量解锁**。
 *
 * 深拷贝是必须的：浅拷贝会让编辑区直接改到 `lib` 里的原对象。
 */
export function cloneModulesForEditing(views: unknown): PromptModule[] {
  const list = Array.isArray(views) ? views : []
  return JSON.parse(JSON.stringify(list)).map((m: PromptModule) => ({
    ...m,
    locked: false, // 全量解锁，支持自由修改
  }))
}

/** 当前生效的模块（`enabled` 且内容非空白）。 */
function _activeModules(modules: PromptModule[] | null | undefined): PromptModule[] {
  return (Array.isArray(modules) ? modules : []).filter(
    (m) => m.enabled && String(m.content || '').trim(),
  )
}

/** 编译「渲染后 Prompt」：各模块内容 trim 后以空行连接（**无模块标题**）。 */
export function compileWorkingModules(modules: PromptModule[] | null | undefined): string {
  return _activeModules(modules)
    .map((m) => String(m.content).trim())
    .join('\n\n')
}

/** 编译「模板视图」：每块带 `======================= 【标题】 =======================` 标头。 */
export function buildTemplatePreview(modules: PromptModule[] | null | undefined): string {
  return _activeModules(modules)
    .map((m) => `======================= 【${m.title}】 =======================\n${String(m.content).trim()}`)
    .join('\n\n')
}

/**
 * 一键插变量时要写进哪个模块。
 *
 * 返回 `null` 表示**没有可写目标**（模块列表为空）。
 * 否则返回**钳制后**的下标：先 `max(0, idx)` 再 `min(·, len-1)`。
 */
export function computeInsertTarget(modules: PromptModule[] | null | undefined, activeIdx: number): number | null {
  const list = Array.isArray(modules) ? modules : []
  if (list.length === 0) return null
  return Math.min(Math.max(0, activeIdx), list.length - 1)
}

/**
 * 把变量插槽追加到模块内容末尾。
 *
 * 返回 `{ content, duplicate }`：
 * - `duplicate: true` 表示该模块**已包含**此插槽 → 内容**原样返回**，调用方应提示而非插入；
 * - 否则返回追加后的新内容（原内容为空时**不加前导换行**）。
 */
export function appendVariableSlot(content: unknown, key: string): { content: string; duplicate: boolean; tag: string } {
  const tag = `{{${key}}}`
  const cur = String(content ?? '')
  if (cur.includes(tag)) return { content: cur, duplicate: true, tag }
  return { content: cur ? `${cur.trim()}\n\n${tag}` : tag, duplicate: false, tag }
}

/** 从导入文件名推默认方案名：剥 `.json`（大小写不敏感）与 `astra-strategy-` 前缀。 */
export function deriveImportName(fileName: unknown): string {
  return String(fileName || '').replace(/\.json$/i, '').replace(/^astra-strategy-/, '')
}
