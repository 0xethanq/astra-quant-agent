/** 操作审计页文案 */
export const zhAdminAudit = {
  tabsLabel: '账号与审计分区',
  tabAudit: '操作审计',
  intro: "只追加的操作审计流水；登录、配置变更、交易动作全部留痕。",
  badge: "治理 · 1/3",
  searchPlaceholder: "搜索动作 / 状态 / 账号 / 详情...",
  refresh: "刷新",
  entries: "条",
  rowHint: "点击任意行穿透查看原始参数 JSON",
  colTimestamp: "时间戳",
  colAction: "动作类型",
  colStatus: "执行结果",
  colDetail: "操作者与审计详情",
  empty: "暂无符合条件的审计记录",
  detailTitle: "审计详情",
  close: "关闭",

  // ── 推倒重来新增（批 11）──
  bandTotal: '审计记录',
  bandSuccess: '成功',
  bandFailed: '异常',
  bandLatest: '最近留痕',
  filterAll: '全部',
  filterSuccess: '成功',
  filterFailed: '异常',
  recordsTitle: '审计流水',
  actorLabel: '操作者',
  rawJson: '原始记录 JSON',
  noMatch: '没有匹配的记录',

  // ── 批 27：行内状态徽章此前直接印后端枚举（success / failed / …），
  // 与同页 KPI 带的中文「成功 / 异常」自相矛盾。改为查表，未登记的值原样回退。
  status: {
    success: '成功',
    completed: '已完成',
    accepted: '已受理',
    failed: '失败',
    denied: '已拒绝',
    error: '异常',
    confirmed_closed: '已确认平仓',
  },
  // ── 批 44：筛选分段组名（role=tablist 的可访问名）──
  filtersLabel: '按状态筛选审计记录',
};
