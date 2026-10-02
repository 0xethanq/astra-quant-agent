/**
 * 投委会页面的无状态逻辑（结构优化阶段 4·B3 第六十刀）。
 *
 * ## 抽了什么、为什么
 *
 * `views/admin/CouncilPage.vue`（873 行，script 302 行）此前**没有任何行为测试**
 * —— 唯一的既有测试 `tests/test_audit_config_p1b_guards.py::test_ui_slots_are_real_variables`
 * 是对 `{ k: '…' }` 字面量做正则扫描。也就是说这个页面里
 * "哪些槽位是合法变量"有护栏，而**其余纯逻辑一条断言都没有**。
 *
 * 故本刀把**真正无状态**的部分搬出来，使其可被 node 直接执行测试。
 * 本模块**不 import 任何东西**（连 vue 都不 import）—— 输入进、值出。
 *
 * ⚠️ 与 `views/admin/llm/` 的拆分同理：**不**把有状态的动作搬出来。
 * `addNewCustomTrader` / `removeRole` / `saveConfig` 等读写的是同一批 `ref`，
 * 拆成独立模块会各建一份新状态（见 `injection.ts` 里记录的陷阱）。
 */

// ---------------------------------------------------------------- 共识模式

export interface ConsensusMode {
  id: string
  name: string
  tag: string
  desc: string
}

/** 三种议事模式。`id` 必须与后端 `consensus_mode` 取值一致。 */
export const CONSENSUS_MODES: ConsensusMode[] = [
  {
    id: 'standard',
    name: '标准提案模式',
    tag: 'Standard',
    desc: '交易员独立提案 → CIO 汇总终审。效率最高，适合常规行情。',
  },
  {
    id: 'cross_examination',
    name: '交叉质询模式',
    tag: 'Cross-Exam',
    desc: '交易员先互评质疑再定稿，CIO 终审。更稳但更慢，适合分歧行情。',
  },
  {
    id: 'debate',
    name: '对抗辩论模式',
    tag: 'Debate',
    desc: '多空双方逐轮辩论，CIO 裁决。最慢，适合极端不确定行情。',
  },
]

// ---------------------------------------------------------------- 席位识别

/** 内置交易员席位 id（与后端 `ALL_AVAILABLE_PRESETS` 对齐）。 */
export const BUILTIN_TRADER_IDS = ['trader_trend', 'trader_momentum', 'trader_quant']

/** 首席投资官席位 id —— 终审收口与发单，**不可删除**。 */
export const CIO_ROLE_ID = 'cio'

/**
 * 是否为 CIO 席位。
 *
 * ⚠️ 该判断原本在模板与脚本里**重复了 7 处**
 * （`role.is_arbitrator || roleId === 'cio'` 及其取反），
 * 收成单一来源后改判据只需改这一处。
 */
export function isCioSeat(role: any, roleId: string): boolean {
  return Boolean(role?.is_arbitrator) || roleId === CIO_ROLE_ID
}

/** 是否为内置交易员席位（自定义席位 id 形如 `trader_<base36>`，不在其列）。 */
export function isBuiltinTrader(roleId: string): boolean {
  return BUILTIN_TRADER_IDS.includes(String(roleId))
}

/**
 * 生成新自定义席位的 id。
 *
 * ⚠️ 用 base36 毫秒时间戳：同一毫秒内连点两次会**撞 id 并静默覆盖前一个席位**。
 * 原实现即如此，本刀保持等价（见 `tests/councilLogic.test.mjs` 的钉住用例）。
 */
export function roleIdOf(now: number = Date.now()): string {
  return `trader_${now.toString(36)}`
}

// ---------------------------------------------------------------- 席位外观

/**
 * 内置席位 → 配色 class。**不含 `custom`**：那一档由 `roleColorOf` 兜底，
 * 避免"表里有一项永远不会被命中"。
 */
export const ROLE_COLORS: Record<string, string> = {
  trader_trend: 'text-emerald-400 border-emerald-500/30 bg-emerald-500/10',
  trader_momentum: 'text-amber-400 border-amber-500/30 bg-amber-500/10',
  trader_quant: 'text-cyan-400 border-cyan-500/30 bg-cyan-500/10',
  cio: 'text-purple-400 border-purple-500/30 bg-purple-500/10',
}

/** 兜底配色（未知席位 / 自定义席位）。 */
export const CUSTOM_ROLE_COLOR = 'text-blue-400 border-blue-500/30 bg-blue-500/10'

/** 席位配色：未知席位一律回落到兜底档（原实现为 `roleColors[roleId] || roleColors['custom']`）。 */
export function roleColorOf(roleId: string): string {
  return ROLE_COLORS[String(roleId)] || CUSTOM_ROLE_COLOR
}

/**
 * 席位图标**键**：已知席位返回自身 id，未知返回 `'custom'`，
 * 由页面据此在本地图标表里取（本模块刻意不 import lucide 图标，保持零依赖）。
 */
export function roleIconKeyOf(roleId: string): string {
  const k = String(roleId)
  return k in ROLE_COLORS || k === CIO_ROLE_ID ? k : 'custom'
}

// ---------------------------------------------------------------- 插入槽位

/**
 * 提示词编辑器可插入的数据槽位。
 *
 * ⚠️ 审计 P1-4d：这些 `k` **必须**是 `scripts/prompt_library.py::ALLOWED_VARIABLES`
 * 里的真变量。旧列表 6 个里 5 个（macro_4h / calculus_1h / smart_money /
 * orderbook_depth / sentiment）不是合法变量 → 插进去只会渲染成
 * `[UNKNOWN_VARIABLE:x]`，模型永远拿不到值。
 * 该约束由 `tests/test_audit_config_p1b_guards.py::test_ui_slots_are_real_variables` 钉住。
 */
export const DATA_SLOTS: Array<{ k: string; label: string }> = [
  { k: 'market_matrix', label: '行情矩阵' },
  { k: 'account_balance', label: '账户余额' },
  { k: 'account_positions', label: '当前持仓' },
  { k: 'pending_orders', label: '挂单列表' },
  { k: 'risk_budget', label: '风控预算' },
  { k: 'active_instruments', label: '活跃标的' },
  { k: 'news_intelligence', label: '情报简报' },
  { k: 'trading_memory', label: '交易记忆' },
]

// ---------------------------------------------------------------- 校验与展示

/**
 * 席位绑定的 `model_id` 是否**不在**模型库里（在库返回 false）。
 *
 * ⚠️ 审计 P1-4b：绑了未登记模型时后端会**静默回落主脑**，UI 必须说出来。
 * 空/缺失的 `model_id` 不算缺失（返回 false）—— 那表示"跟随主脑"，是合法状态。
 */
export function isModelMissing(role: any, models: any[] | null | undefined): boolean {
  const id = String(role?.model_id || '').trim()
  if (!id) return false
  return !(models || []).some((m: any) => String(m?.id) === id)
}

/** 议事模式的展示名（找不到时回落 `fallback`）。 */
export function consensusModeName(modeId: string, fallback: string): string {
  const found = CONSENSUS_MODES.find((m) => m.id === modeId)
  return found ? found.name : fallback
}

/** 席位名（缺失时回落 id），用于确认弹窗文案。 */
export function roleDisplayName(role: any, roleId: string): string {
  return String(role?.name || roleId)
}

/** 席位号位文案（缺失时回落 `fallback`，即 CIO 标题或默认交易员标题）。 */
export function roleTitleOf(role: any, fallback: string): string {
  return String(role?.role_title || fallback)
}

// ---------------------------------------------------------------- 保存载荷

/** `saveConfig` 的请求体（字段与回落链逐字对齐原实现）。 */
export function buildCouncilSavePayload(cfg: any): Record<string, any> {
  return {
    enabled: cfg?.enabled,
    consensus_mode: cfg?.consensus_mode || 'standard',
    timeout_seconds: Number(cfg?.timeout_seconds) || 240.0,
    roles: cfg?.roles,
  }
}

/** 导入请求体：把用户粘贴的 JSON 包成 `{ payload }`。 */
export function buildCouncilImportPayload(payload: any): Record<string, any> {
  return { payload }
}

/**
 * `loadData` 的席位展开回落：当前展开项不在席位列里时改展开第一个。
 *
 * ⚠️ `roleKeys` 缺省按空数组处理。原实现直接读 `.length`，
 * 对 `undefined` 会抛 —— 但原文的调用点是
 * `Object.keys(cRes.roles || {})`，**永远给数组**，故该差异在真实路径上不可达。
 * 写成缺省值是"抽出来当独立函数后"的合理防御，**不是行为变更**。
 */
export function nextExpandedRole(roleKeys: string[] | undefined | null, current: string): string {
  const keys = roleKeys || []
  if (keys.length > 0 && !keys.includes(current)) return keys[0]
  return current
}
