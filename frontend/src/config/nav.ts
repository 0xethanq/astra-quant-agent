/**
 * 导航元数据单一来源：前台 tab / 后台侧栏分组 / 命令面板共用。
 * path 与后端钉扎路由严格一致（/ /trading /factors /news /lab /history /docs /admin/*）。
 */
import type { Component } from 'vue';
import {
  LayoutDashboard,
  BrainCircuit,
  Newspaper,
  Dna,
  ReceiptText,
  Gauge,
  Workflow,
  Terminal,
  Landmark,
  Braces,
  ShieldCheck,
  KeyRound,
  Cpu,
  BellRing,
  UserCog,
  DatabaseBackup,
} from 'lucide-vue-next';

export interface NavItem {
  /** 内部 tab/路由标识（不随文案变化） */
  key: string;
  labelKey: string;
  path: string;
  icon: Component;
  /** 命令面板搜索别名（品牌词/旧称/英文） */
  alias?: string;
  /**
   * 该导航项对应的页面组件文件名（不含 `.vue`）。
   *
   * 为什么把组件名放在这里（2026-09-30）：`AdminLayout` 原先自己维护一份
   * 手写的 `key → 组件名` 映射用于空闲预取，与本文件**重复且会漂移**。
   * nav.ts 的自我定位就是"导航元数据单一来源"，故把组件名收进来；
   * `frontend/tests/absorbedPageTabs.test.mjs` 会逐项断言文件真实存在。
   * 公开 tab（`publicTabs`）走 `DashboardLayout`，不需要该字段。
   */
  component?: string;
}

export const publicTabs: NavItem[] = [
  { key: 'trading', labelKey: 'nav.tabs.matrix', path: '/trading', icon: LayoutDashboard, alias: 'matrix trading 实盘' },
  { key: 'factors', labelKey: 'nav.tabs.radar', path: '/factors', icon: BrainCircuit, alias: 'radar factors ai 推演' },
  { key: 'news', labelKey: 'nav.tabs.news', path: '/news', icon: Newspaper, alias: 'news sentiment 舆情' },
  { key: 'lab', labelKey: 'nav.tabs.evolution', path: '/lab', icon: Dna, alias: 'lab evolution 进化' },
  { key: 'history', labelKey: 'nav.tabs.ledger', path: '/history', icon: ReceiptText, alias: 'ledger history 台账' },
];

/**
 * 后台侧栏：**11 项 / 5 组**（2026-09-30 由 18 项精简）。
 *
 * 精简原则（证据见各 `alias` 与提交说明）：
 *   - 只做**页面级**重组：被吸收的页面保留为组件，作为宿主页的页签渲染，
 *     路径保留重定向 ⇒ 功能零删除、书签不 404；
 *   - 宿主页沿用原有 key 与 path（`admin-gateway` / `admin-risk` / `admin-audit`
 *     / `admin-backup`），只改显示名，避免无意义的迁移成本；
 *   - 被吸收能力的搜索词并入宿主页 `alias`，命令面板"插件/日志/账号/版本"仍搜得到。
 */
export const adminGroups: { key: string; labelKey: string; items: NavItem[] }[] = [
  {
    key: 'observe',
    labelKey: 'nav.groups.observe',
    items: [
      { key: 'admin-overview', labelKey: 'nav.admin.overview', path: '/admin/overview', icon: Gauge, alias: 'overview 总览', component: 'OverviewPage' },
      {
        key: 'admin-gateway', labelKey: 'nav.admin.gateway', path: '/admin/gateway', icon: Workflow,
        alias: 'gateway scheduler 调度 runtime units worker agents 运行单元 名册 遥测',
        component: 'GatewayPage',
      },
      {
        key: 'admin-decisions', labelKey: 'nav.admin.decisions', path: '/admin/decisions', icon: Terminal,
        alias: 'decisions logs errors audit 系统日志 运行日志 报错 异常 决策 审计 流水',
        component: 'DecisionsPage',
      },
    ],
  },
  {
    key: 'strategy',
    labelKey: 'nav.groups.strategy',
    items: [
      { key: 'admin-council', labelKey: 'nav.admin.council', path: '/admin/council', icon: Landmark, alias: 'council 委员会 投委会', component: 'CouncilPage' },
      { key: 'admin-promptlib', labelKey: 'nav.admin.prompts', path: '/admin/promptlib', icon: Braces, alias: 'prompt studio 提示词', component: 'PromptStudioPage' },
      { key: 'admin-evolution', labelKey: 'nav.admin.evolution', path: '/admin/evolution', icon: Dna, alias: 'evolution memory 心法', component: 'EvolutionPage' },
    ],
  },
  {
    key: 'riskExec',
    labelKey: 'nav.groups.riskExec',
    items: [
      {
        key: 'admin-risk', labelKey: 'nav.admin.risk', path: '/admin/risk', icon: ShieldCheck,
        alias: 'risk 风控 interceptor pipeline fail-closed 拦截 规则 事前风控',
        component: 'RiskPage',
      },
      { key: 'admin-security', labelKey: 'nav.admin.security', path: '/admin/security', icon: KeyRound, alias: 'account symbols 标的池 账户 接入', component: 'SecurityPage' },
    ],
  },
  {
    key: 'platform',
    labelKey: 'nav.groups.platform',
    items: [
      { key: 'admin-llm', labelKey: 'nav.admin.llm', path: '/admin/llm', icon: Cpu, alias: 'llm provider model 模型 供应商', component: 'LlmPage' },
      { key: 'admin-notify', labelKey: 'nav.admin.notify', path: '/admin/notify', icon: BellRing, alias: 'notify qq telegram 通知 channel plugin 渠道', component: 'NotifyPage' },
    ],
  },
  {
    key: 'system',
    labelKey: 'nav.groups.system',
    items: [
      {
        key: 'admin-adminsys', labelKey: 'nav.admin.adminsys', path: '/admin/adminsys', icon: UserCog,
        alias: 'adminsys users password 账号 管理员 改密 建号 权限 会话',
        component: 'AdminSysPage',
      },
      {
        key: 'admin-backup', labelKey: 'nav.admin.backup', path: '/admin/backup', icon: DatabaseBackup,
        alias: 'backup restore 备份 policy snapshot hash rollback 策略快照 指纹 回滚 version update 版本 更新 关于',
        component: 'BackupPage',
      },
    ],
  },
];

export const allAdminItems = adminGroups.flatMap((g) => g.items);
