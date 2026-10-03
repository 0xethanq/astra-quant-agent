/** 关于与社区弹窗 */
export const zhAbout = {
  title: '关于 AstraQuant',
  desc: '加密货币自主量化交易系统 · 多模型协同分析 · 衍生品盘口微结构因子 · 确定性代码风控',
  pitch: '“模型提供分析假说，量化因子交叉验证，底层代码执行强制风控与止损约束。”',
  arch: {
    title: '系统核心架构支柱',
    stack: 'FastAPI + Vue 3 实盘工作台 · OKX V5 原生直签',
    points: [
      '【模型协同】多模型分工分析（宏观/趋势/盘口微结构），降低单一模型认知偏差',
      '【数据验证】结合 CVD 订单流、深度失衡 OBI、期权隐含波动率与 VWAP 等微观因子综合研判',
      '【确定性风控】Python 物理风控闸门与 100% 交易所云端 OCO 止损，对违规意图行使一票否决',
      '【提示词缓存】Prompt Caching 共享上下文广播与分级更新，降低调用延迟与推理开销',
    ],
  },
  repo: { title: '开源代码仓库', visit: '访问 GitHub 仓库', starHint: '欢迎 Star 与 Issue' },
  community: {
    title: '生态与交流',
    qqGroup: '官方技术交流群',
    qqPersonal: '技术架构师联络',
    linuxdo: 'LINUX DO 开源社区',
    channel: '{channel} 专属通道',
    open: '打开注册页',
    copyHint: '点击复制',
  },
  version: '系统版本 {v} · 构建代号 {r}',
  license: 'GNU AGPL-3.0 + Commons Clause v1.0 + Anti-Scam Rider · 严禁商业转售与收费带单',
  risk: '免责声明：加密货币高波动衍生品具有高杠杆资本风险，本系统为自主量化科研与自营交易框架，历史收益不预示未来表现。',
};
