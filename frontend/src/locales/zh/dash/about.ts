/** 关于与社区弹窗 */
export const zhAbout = {
  title: '关于 AstraQuant',
  desc: '多模型对抗质询 · 7层量化因子微积分 · 确定性物理风控的 OKX 永续自主交易系统',
  pitch: '“认知在上，数据为基，纪律在底 —— 大模型负责提出假说，7层高频量化因子负责物理验真，纯 Python 底座行使一票否决权。”',
  arch: {
    title: '系统核心支柱',
    stack: 'FastAPI + Vue 3 纯静态 SPA · OKX 原生直签',
    points: [
      '【认知在上】多模型投委会对抗质询与交叉辩论，彻底消灭单一模型幻觉与认知盲区',
      '【事实为基】基差/订单流CVD/盘口深度OBI/期权IV曲面等 7 层衍生品微积分物理验真',
      '【纪律在底】纯 Python 确定性物理风控门禁 + 100% 交易所云端 OCO 止损，一票否决任何违规意向',
    ],
  },
  repo: { title: '开源仓库', visit: '访问仓库', starHint: '欢迎 Star 与 Issue' },
  community: {
    title: '社区交流',
    qqGroup: '量化交流群',
    qqPersonal: '作者 QQ',
    linuxdo: 'LINUX DO 社区',
    // 2026-09：通道列表改为**后端出值**（`/api/v1/referral-channels`，公开只读），
    // 前端不再写死链接 ⇒ 每个渠道的展示文案：这里只留"每种所叫什么"的展示文案。
    channel: '{channel} 专属通道',
    open: '打开注册页',
    copyHint: '点击复制',
  },
  version: '版本 {v} · 构建 {r}',
  license: 'AGPL-3.0 + Commons Clause · 开源仅供研究，严禁商业转售与收费带单',
  risk: '风险提示：加密货币永续合约具有极高杠杆风险，历史收益不代表未来表现。',
};
