/** 自进化：复盘 HUD + 心法库 + 归因切片 */
export const zhEvolution = {
  title: '策略进化',
  desc: '每 6 小时复盘全量台账，提炼经验法则',
  hud: {
    at: '最近复盘',
    sample: '复盘样本',
    winRate: '综合胜率',
    pf: '利润因子',
    status: '演进状态',
    sampleN: '{n} 笔平仓',
    statuses: {
      CHANGED: '已进化',
      NO_CHANGE: '维持现状',
      RUNNING: '复盘中',
      FAILED: '复盘失败',
    },
    empty: '尚未产生复盘记录',
  },
  rationale: {
    title: '复盘裁决',
    desc: '本轮"改或不改"的完整推演',
  },
  insights: {
    title: '交易复盘归因',
    desc: '对代表性平仓的痛点切片',
    empty: '暂无归因切片',
  },
  actions: {
    title: '行动清单',
    empty: '本轮无新增行动',
  },
  memory: {
    title: '核心策略纪律',
    desc: 'AI 自维护的实战纪律，旧经验按半衰期淘汰',
    empty: '心法库为空，等待首次复盘',
    halfLife: '半衰期 {n} 天',
    remaining: '余量 {n}%',
    weight: '权重',
    bornAt: '沉淀于 {t}',
    rules: '{n} 条生效',
    dev: '策略原始记录 (Markdown)',
    devDesc: '直接查看心法库原始 Markdown',
    dimension: '维度',
    lesson: '心法',
    evidence: '证据',
  },
  guard: {
    title: '防污染护栏',
    on: '生效中',
    off: '未生效',
    desc: '样本不足、情绪化措辞与过拟合经验会被拒绝入库',
    snapshot: '数理快照可观测性',
    snapshotCounts: '动力学 {observed}/{total} · 仅价格 {priceOnly} · 无快照 {none}',
    baselineProtected: '基准心法补回 {n} 条',
  },
  // 批 38：展示用列表分隔符（全角分号 vs 半角分号+空格）
  itemSep: '；',
  // ── 批 41：本地化写死文案（EvolutionView 模板与动作文本前缀）──
  autoIterateBadge: '6小时迭代周期',
  snapshotAuditTitle: '数据快照完整度',
  actText: '【{type}】{text}',
  // ── 2026-10（方向 1：证据链可观测性）──
  // 让"台账缺什么"在看板上直接可读，而不是要人去翻 80 行台账散文。
  evidenceChainTitle: '证据链健康度',
  // ⚠️ 口径必须是"梯队因子可观测率"，不是"快照非空率"：实测快照非空率 100%
  // 而梯队因子可观测率 0%（旧格式快照只有价格类观测）。标错口径会让看板
  // 显示"开仓现场覆盖 100%"，恰好掩盖它本该暴露的缺口。
  evidenceEntryCoverage: '开仓梯队因子可观测率',
  evidenceExitCoverage: '离场原因机制确认率',
  evidenceGapsTitle: '证据缺口（如实披露）',
  evidenceNoGaps: '证据链完整：开仓现场与离场原因均无缺口',
};
