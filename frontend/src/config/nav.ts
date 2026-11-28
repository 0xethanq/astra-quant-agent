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
  Bot,
  Terminal,
  KeyRound,
  Cpu,
  BellRing,
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
 * 后台侧栏：**6 项 / 2 组**（Agent-First 精简架构）。
 *
 * ⚠️ 项数必须与命名路由数**双向相等** —— `frontend/tests/routeDocumentTitles.test.mjs`
 * 两个方向都断言（防"导航项指向空气"与"命名路由没有入口"）。
 *
 * 精简原则：
 *   - 高频运维页保留为独立路由，策略/提示词/风控/投委会/自进化统一收口至「AI 指挥台」；
 *   - `AdminSysPage` 并入 `BackupPage` 第四个页签（`?tab=adminsys`），所有历史路由平滑重定向不 404。
 */
export const adminGroups: { key: string; labelKey: string; items: NavItem[] }[] = [
  {
    key: 'command',
    labelKey: 'nav.groups.command',
    items: [
      {
        key: 'admin-agent',
        labelKey: 'nav.admin.agent',
        path: '/admin/agent',
        icon: Bot,
        alias: 'agent copilot overview risk prompt council evolution gateway 指挥台 总览 风控 提示词 委员会 自进化 网关',
        component: 'AgentConsolePage',
      },
      {
        key: 'admin-decisions',
        labelKey: 'nav.admin.decisions',
        path: '/admin/decisions',
        icon: Terminal,
        alias: 'decisions logs errors audit 系统日志 运行日志 报错 异常 决策 审计 流水',
        component: 'DecisionsPage',
      },
    ],
  },
  {
    key: 'platform',
    labelKey: 'nav.groups.platform',
    items: [
      {
        key: 'admin-security',
        labelKey: 'nav.admin.security',
        path: '/admin/security',
        icon: KeyRound,
        alias: 'account okx symbols capital emergency 账户 应急 平仓 标的池 接入 本金',
        component: 'SecurityPage',
      },
      {
        key: 'admin-llm',
        labelKey: 'nav.admin.llm',
        path: '/admin/llm',
        icon: Cpu,
        alias: 'llm provider model 模型 供应商',
        component: 'LlmPage',
      },
      {
        key: 'admin-notify',
        labelKey: 'nav.admin.notify',
        path: '/admin/notify',
        icon: BellRing,
        alias: 'notify qq telegram 通知 channel plugin 渠道',
        component: 'NotifyPage',
      },
      {
        key: 'admin-backup',
        labelKey: 'nav.admin.backup',
        path: '/admin/backup',
        icon: DatabaseBackup,
        alias: 'backup restore 备份 adminsys accounts 账号 改密 policy snapshot 回滚 version update 版本 更新 关于',
        component: 'BackupPage',
      },
    ],
  },
];

export const allAdminItems = adminGroups.flatMap((g) => g.items);
