<div align="center">

[**简体中文**](README.zh-CN.md) · [English](README.md)

# AstraQuant

### 机构级自主量化交易操作系统与多智能体博弈决策架构
#### 对冲基金多模型博弈投委会 · 7层衍生品微结构微积分 · 确定性物理风控硬防线

[![Release](https://img.shields.io/badge/Release-v8.5.1-00E599.svg?style=flat-square)](https://github.com/0xethanq/astra-quant-agent/releases)
[![Website](https://img.shields.io/badge/Site-www.astraquant.tech-6E56CF.svg?style=flat-square)](https://www.astraquant.tech)
[![License](https://img.shields.io/badge/License-AGPLv3%20%2B%20Commons%20Clause-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue-3.5%2B-4FC08D.svg?style=flat-square&logo=vuedotjs&logoColor=white)](https://vuejs.org/)
[![Tests](https://img.shields.io/badge/Tests-9.5k%2B%20Passing-brightgreen.svg?style=flat-square)](tests/)
[![Community](https://img.shields.io/badge/Community-LINUX%20DO-F97316.svg?style=flat-square&logo=linux&logoColor=white)](https://linux.do/)

**多前沿 AI 参谋对抗质询 → 首席投资官 (CIO) 仲裁定策 → 确定性 Python 物理风控一票否决 → OKX 原生 Maker 挂单与原子级云端 OCO 双腿防护。**

*认知归模型，微积分验真，底线归代码。彻底消除黑盒盲盒与单模型幻觉。*

[快速开始](#快速开始) · [系统核心定位](#系统核心工程定位为什么需要-astraquant) · [系统架构](#系统架构全景) · [7层量化微积分](#7-层衍生品微结构微积分矩阵) · [多模型投委会](#多模型对抗投委会-council-pro) · [Prompt 缓存](#-prompt-caching-提示词缓存与会话亲和架构) · [机构资金管理](#机构资金管理与动态风险平价矩阵) · [系统漫游](#系统界面漫游) · [部署指南](#部署指南) · [代码地图](#代码结构入口)

</div>

> 🌟 **本项目首发于 [LINUX DO (linux.do)](https://linux.do/) 开源技术社区并受其大力支持。**

---

## 💡 系统核心工程定位：为什么需要 AstraQuant？

市场上大多数开源交易脚本或简单的 LLM 炒币 Bot 在实盘中迅速失效穿仓，核心在于三大致命缺陷：
1. **单一模型的认知幻觉与过度自信**：单一 LLM 在面对极端行情异动时极易产生叙事偏见与幻觉。AstraQuant 引入对冲基金多席位架构，由宏观研究员、盘口微结构分析师、技术动量官与逆向对冲官展开**对抗性交叉质询**，基于博弈论共识（一票否决/加权多数/动能优先）由 CIO 裁决定策。
2. **散户级滞后指标 vs 衍生品物理微结构**：均线、RSI 等滞后指标在加密货币假突破和震荡绞肉中频繁磨损。AstraQuant 摒弃简单死叉金叉，实时计算**订单流 CVD 累计成交量差、L2 订单簿盘口失衡度 (OBI)、期权波动率曲面与最大痛点引力、VWAP 机构筹码分布**等高频衍生品微积分。
3. **软性提示词约束 vs 确定性资本风控**：提示词根本无法在极端插针或交易所超时中保全资金。AstraQuant 构建了**零信任 Fail-Closed 物理执行底座**：大模型仅拥有“假说提议权”，纯 Python 确定性风控底座行使“一票否决权”；每笔订单在交易所侧原子下发**双腿条件单（TP1 独立算法腿锁定利润 + TP2 终点趋势腿跟随 + 100% 交易所云端 OCO 止损）**，彻底免疫断网、宕机、API 限频风险。

---

## 🚀 快速开始

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git && cd astra-quant-agent
./setup.sh                  # 交互式部署向导（推荐，2分钟搞定全链路环境）
# 或容器一键启动：./deploy/docker-start.sh；裸机环境：./deploy/install.sh && ./start.sh
```

| 服务入口 | 本地访问链接 | 访问权限 / 定位 |
|---|---|---|
| **机构量化交易大屏** | `http://localhost:8080/trading` | 公开只读 · 实盘遥测工位 HUD |
| **管理控制中心** | `http://localhost:8080/admin/login` | 管理员凭证 (`admin`) · 策略与凭证中枢 |
| **系统技术文档与 OpenAPI** | `http://localhost:8080/docs` | 公开技术文档 · 12章完整工程手册 |

> 🛡️ **安全第一**：AstraQuant 出厂默认以 **模拟盘 (demo / paper mode)** 启动。在 `/admin/security` 完成大模型与 OKX 凭证配置并显式切换实盘之前，系统严禁触碰任何真金白银。在配置完整之前，系统始终处于 `NOT READY` 状态，物理阻断一切交易执行。

---

## 🏛 系统架构全景

以 15 分钟为一个完整大脑决策周期，确立四道不可逾越的物理硬防线：

```text
                    ┌─────────────────────────────────────────────────────────┐
                    │              AstraQuant 统一网关调度守护进程            │
                    │   trader (15m) · news (10m) · factors (60s) · evolve (6h│
                    └────────────────────────────┬────────────────────────────┘
                                                 ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │ 1 · 7 梯队衍生品高频微结构微积分因子矩阵                                 │
   │   • T0: 资金费率、持仓量 (OI) 变化率、大户持仓多空比                     │
   │   • T0.5: 累计成交量差 (CVD) 订单流背离、Whale Taker 主动吃单净量        │
   │   • T1: L2 深度倾角、买卖盘口失衡度 (OBI)、滑点价差动态                  │
   │   • T1.5: 期权 IV 波动率微笑曲面、Put/Call 偏度、最大痛点引力位          │
   │   • T2: 期限基差与远期展期年化收益率                                     │
   │   • T3: 机构 VWAP 筹码中枢 (±1σ / ±2σ)、VPVR 成交量控制点 (POC)          │
   │   • T4: MACD 柱一阶速度与二阶加速度导数、ADX 趋势向量                    │
   │   → 行情体制标签 (趋势单边扩张 / 宽幅震荡 / 流动性枯竭 / …)              │
   └─────────────────────────────────────┬────────────────────────────────────┘
                                         ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │ 2 · 对冲基金多模型博弈投委会质询 (COUNCIL PRO)                           │
   │   • 宏观策略官 · 技术动量官 · 盘口微结构量化官 · 逆向风控守门人          │
   │   • 多轮对抗辩论与交叉质询                                               │
   │   • 博弈论共识仲裁 (一票否决制 / 加权多数决 / 动能突破优先)              │
   │   • 首席投资官 (CIO) 收口输出唯一严格机器契约                            │
   │   • Prompt Caching：共享规则与矩阵前缀（命中率 >90%）                    │
   └─────────────────────────────────────┬────────────────────────────────────┘
                                         ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │ 3 · 零信任确定性物理风控门禁与熔断中枢                                   │
   │   • 关键行情与深度完整性校验 · 反向持仓冲突检查                          │
   │   • 报价几何合理性校验（多头必须满足 止损 < 入场 < 止盈）                │
   │   • 严格期望盈亏比底线 (R:R ≥ 2.0) · 动态杠杆上限强制收紧                │
   │   • 单标的敞口集中度配额 · 全账户日内累计亏损硬熔断                      │
   │   ⚠️ 任何一项校验失败或无法求值 = 物理硬拒绝（绝不开仓）                 │
   └─────────────────────────────────────┬────────────────────────────────────┘
                                         ▼
   ┌──────────────────────────────────────────────────────────────────────────┐
   │ 4 · OKX 原生撮合引擎执行与云端双腿防护                                   │
   │   • Maker / BBO 限价单入场（捕获被动挂单费率返还）                       │
   │   • 分批止盈双腿 (Scale-Out Legs)：TP1 (1.8× ATR) 挂独立 reduceOnly 腿  │
   │   • 利润奔跑趋势腿 (TP2)：达成 TP1 后自动抬升止损至开仓保本价            │
   │   • 止损覆盖率 100%：双腿各自绑定交易所云端 OCO 止损条件单               │
   │   • 结构失效时间止损 (8h 强制释放资金效率)                               │
   └──────────────────────────────────────────────────────────────────────────┘
```

全流程 100% 可观测：从每位席位的质询对话、因子微积分快照、Python 风控判决到生成的 `policy_hash` 均按周期结构化落盘。

---

## 🔬 7 层衍生品微结构微积分矩阵

AstraQuant 拒绝散户化滞后指标，专注于高频衍生品微结构物理验证：

| 梯队 | 维度 | 数学与微积分测算指标 | 量化 Alpha 意义 |
|---|---|---|---|
| **T0** | **结算与持仓筹码** | 资金费率加速度、未平仓持仓量 (OI) 导数、大户多空账户比 | 侦测散户过度杠杆拥挤度与潜在多空踩踏挤压清算点 |
| **T0.5** | **订单流与主动吃单** | 累计成交量差 (CVD Divergence) 背离、主力主动吃单净流入 | 捕捉大资金在盘口隐蔽吸筹或被动吸单的主动进攻意图 |
| **T1** | **盘口微观失衡** | 盘口失衡度 (Order Book Imbalance, OBI)、前20档深度不对称性 | 量化当前买卖盘瞬时物理阻力，识别流动性真空与假墙诱多诱空 |
| **T1.5** | **期权波动率曲面** | 隐含波动率 (IV) 偏度、25-Delta 波动率微笑、最大痛点引力磁石 | 穿透期权做市商尾部风险对冲头寸与行权日交割引力锚位 |
| **T2** | **期限基差结构** | 远期交割合约年化基差率、跨期日历展期价差 | 测算宏观资金借贷成本与对冲基金期现套利资金流向 |
| **T3** | **机构筹码足迹** | 成交量加权平均价 (VWAP) 波动带 (±1σ, ±2σ)、VPVR 筹码密集峰 | 锁定机构真实持仓成本中枢，识别极端乖离度均值回归极点 |
| **T4** | **动量与速度导数** | MACD 柱一阶导数（速度）与二阶导数（加速度）、ADX 趋势动能 | 区分高确信度真突破波段与无动能衰竭假突破诱多陷阱 |

---

## 👥 多模型对抗投委会 (Council Pro)

单一大模型难以在复杂市场中保持客观。AstraQuant 构建了机构级对冲基金交易台架构：

- **异构多席位分工**：支持自由配置不同大模型（DeepSeek-V3/R1、Claude 3.5 Sonnet、OpenAI GPT-4o、Qwen 2.5 等）担任独立参谋：
  - *宏观策略官 (Macro Specialist)*：研判全网快讯、央行利率决议与监管情绪。
  - *微结构分析师 (Quant Microstructure)*：精算订单流 CVD、盘口失衡度 OBI 与期权偏度。
  - *技术动量操盘手 (Momentum Trader)*：捕捉大级别突破形态与波动率扩张。
  - *逆向防守官 (Contrarian Risk Gatekeeper)*：挑战共识假说，排查流动性枯竭与多空陷阱。
- **博弈论仲裁共识机制**：
  1. **一票否决制 (Paranoid Veto)**：任何参谋提出重大宏观异动或流动性断崖预警，仲裁官强制降级为 `WAIT`。
  2. **加权多数决 (Weighted Majority)**：基于席位置信度与滚动历史胜率加权投票，仅在同向权重绝对占优时准许发单。
  3. **动能突破优先 (Alpha Momentum)**：因子多维强共振突破时，赋予技术突破分析师优先裁决权。
- **CIO 机器契约**：首席投资官收敛辩论观点，严格输出符合机器解析标准的结构化交易意图。

---

## ⚡ Prompt Caching 提示词缓存与会话亲和架构

为彻底解决多智能体量化系统中推理延迟与巨额 Token 成本，AstraQuant 打造了 **2026-10 架构级 Prompt Caching 引擎**：

```text
┌────────────────────────────────────────────────────────────────────────┐
│ Zone 0 · 不变宪法与只读输出 JSON Schema 契约                  [已缓存]│
├────────────────────────────────────────────────────────────────────────┤
│ Zone 1 · 慢变自进化实战心法（6 小时复盘更新）                 [已缓存]│
├────────────────────────────────────────────────────────────────────────┤
│ Zone 2 · 中变全网快讯舆情打分（10 分钟更新）                  [已缓存]│
├────────────────────────────────────────────────────────────────────────┤
│ Zone 3 · 周期 7 梯队量化微积分因子矩阵（15 分钟更新）         [已缓存]│
├────────────────────────────────────────────────────────────────────────┤
│ Zone 4 · 高频秒级动态状态（实时盘口、毫秒时间戳）             [动态变动]│
└────────────────────────────────────────────────────────────────────────┘
```

1. **单前缀广播 (Shared Prefix Broadcasting >90%)**：共享交易纪律、风控规则与全标的微积分矩阵作为静态前缀。投委会四席位并发质询时，通过代理会话亲和（Session Affinity）命中同一 KV 缓存块，首字延迟进入亚秒级，Token 成本降低 70%+。
2. **单调波动分级编排 (Monotonic Volatility Hierarchy)**：严格按数据更新频率排序，防止末尾高频变动打碎静态前缀缓存。
3. **Claude Ephemeral 显式断点与分块对齐**：针对 Anthropic 原生注入 `cache_control: {"type": "ephemeral"}` 标记；针对 DeepSeek 与 OpenAI 严格按 64/128 token 分块边界对齐。
4. **浮点防抖稳定机制 (Float Anti-Jitter)**：对价格和因子进行数学舍入防抖，消除毫厘级浮点扰动对缓存哈希的破坏。
5. **本地 L1 内存 + SQLite 双层缓存**：秒级阻断投委会辩论与网络重试期间的重复请求。

---

## 🛡️ 机构资金管理与动态风险平价矩阵

AstraQuant 遵循**严格与实时账户净资产挂钩的动态风险平价原则**，出厂均衡基线如下（源自 `scripts/risk_constants.py`）：

| 风控与资产维度 | 计算基准与阈值上限 | 战略风控目标与防御机理 |
|---|---|---|
| **单笔最大风险暴露 (1R)** | `min(单标的上限, 权益 × 4.5%)` | 严格仓位控制；将单笔极端损失限制在极小资产份额 |
| **单笔保证金占用上限** | `权益 × 40.0%` | 杜绝单次开仓过度占用可用流动性 |
| **单标的累计保证金上限** | `权益 × 48.0%` | 严格防止单边行情的单一资产黑天鹅集中度风险 |
| **全账户日内硬熔断** | `min(500 USDT, 权益 × 10.0%)` | 物理级止损底线；单日回撤达阈值强制终止一切新开仓 24 小时 |
| **动态杠杆约束区间** | `3.0x – 8.0x` (波动率自适应) | 随标的 ATR 与盘口流动性动态收缩杠杆，杜绝高倍赌徒行为 |
| **期望盈亏比门槛 (R:R)** | `R:R ≥ 2.0` (上限 5.0) | 确保长期正期望值，物理拦截低盈亏比追单 |
| **波动率自适应止损** | `1.8x – 2.2x × ATR(1H)` | 给予行情充足呼吸空间，彻底杜绝日内杂波洗盘 |
| **分批止盈腿 (TP1)** | `35% – 50%` 仓位于 `1.8 × ATR` | 交易所原生独立 `reduceOnly` 算法腿秒级撮合，锁定确定性利润 |
| **趋势利润奔跑腿 (TP2)** | 终点结构化目标位 | TP1 达成后系统自动将剩余仓位止损抬升至开仓均价（保本移损） |
| **止损覆盖率** | **100.0%** 全额双腿 OCO 覆盖 | 双腿各自绑定 OKX 云端条件单，即使拔线断网仍受撮合引擎物理保护 |
| **结构失效时间止损** | `8 小时` 极限持仓时长 | 若预期动能未能如期展开，主动释放保证金转战高确定性机会 |
| **多标的同向敞口配额** | `≤ 4` 笔同向在途持仓 | 阻断极端单边暴跌中强相关币种的 Beta 踩踏级连亏损 |
| **被扫损后冷静期** | `15 分钟` / 单标的 | 强制程序化冷却，杜绝人类或模型产生报复性逆势接刀心理 |

---

## 📸 系统界面漫游

| | |
|---|---|
| **机构量化交易大屏工位**<br>![Live Workstation](docs/images/v850_live_dashboard.png) | **思维链与量化轨迹深度抽屉**<br>![Chain of Thought](docs/images/v850_trajectory_cot.png) |
| **7 梯队微结构因子微积分矩阵**<br>![Factor Matrix](docs/images/v850_calculus_factors.png) | **对冲基金多模型博弈投委会**<br>![Council Board](docs/images/v850_council_board.png) |
| **可视化提示词策略工程工作室**<br>![Prompt Studio](docs/images/v850_prompt_studio.png) | **闭环实盘自进化认知中枢**<br>![Self Evolution](docs/images/v850_self_evolution.png) |
| **执行层物理风控管理中心**<br>![Risk Control](docs/images/v850_risk_control.png) | **策略快照与秒级原子回滚**<br>![Policy Snapshot](docs/images/v850_policy_snapshot.png) |
| **大模型路由与思考预算中枢**<br>![LLM Hub](docs/images/v850_llm_hub.png) | **系统治理与管理控制总览**<br>![Admin Overview](docs/images/v850_admin_overview.png) |
| **安全与 Fernet 凭证管理广场**<br>![Security Plaza](docs/images/v850_security_plaza.png) | **微结构全景实盘遥测**<br>![Live Workstation](docs/images/v850_live_dashboard.png) |

---

## 🎨 提示词工程与 8 大语义变量插槽

提示词策略统一收敛于 `data/prompt_library.json`，Python 代码中不包含任何硬编码提示词正文：

- **输出 JSON Schema 绝对锁定**：模型的回复契约定义在代码中（`scripts/ai_brain_trader.py`），后台工坊强制只读，杜绝格式错乱导致解析崩溃；
- **8 大运行时动态语义插槽**：
  - `{{decision_timestamp}}`：统一北京时间 (UTC+8) 财务与执行基准；
  - `{{account_balance}}`：实时 USDT 现金可用额度与账户总资产权益；
  - `{{risk_budget}}`：动态精算单笔保证金配额、1R 预算与杠杆上限；
  - `{{account_positions}}`：在途持仓方向、均价、浮盈 ROI、极值回撤百分比；
  - `{{pending_orders}}`：活跃 Maker 限价挂单列表，由模型执行保留或撤单；
  - `{{market_matrix}}`：全标的 7 梯队衍生品高频微结构微积分因子矩阵；
  - `{{news_intelligence}}`：全网最新宏观金融快讯与加权情绪打分；
  - `{{trading_memory}}`：基于真实已平仓账单数学归因蒸馏的长效实战心法。

📖 详细策略指南与席位提示词模板：**[`docs/PROMPT_GUIDE.md`](docs/PROMPT_GUIDE.md)**

---

## 📊 运行可观测性与遥测日志

| 守护服务 | 对应日志路径 | 职责范围与遥测内容 |
| :--- | :--- | :--- |
| `trader` | `logs/ai_factor_trader.log` | 主脑周期、投委会质询记录、因子快照、OCO 挂单与双腿推进 |
| `backend` | `logs/uvicorn.log` | FastAPI 控制面、REST 请求生命周期、鉴权与状态同步 |
| `scheduler` | `logs/astra_gateway.log` | 分布式文件锁租约、定时任务调度、健康心跳探测 |
| `audit` | `logs/astra_admin_audit.jsonl` | 只追加式不可逆安全审计链 (时间戳、操作者、来源 IP、动作) |

两个 Docker 容器均运行容器内看门狗，提供自愈能力；配套 Prometheus 与 Grafana 面板位于 [`deploy/observability/README.md`](deploy/observability/README.md)。

---

## 🧪 自动化测试与不变量门禁体系

仓库内所有工程声明均有对应的自动化测试保障，发版与迭代必须全绿通过：

```bash
# 1. Tier 0: 核心量化业务门 (量化交易链路、风控硬拦截、订单状态机, ~20s)
.venv/bin/pytest tests/trading tests/venues tests/risk tests/backtest -n auto -q

# 2. Tier 1: 模型与界面集成门 (多模型协议、前端类型与构建, ~60s)
.venv/bin/pytest tests/llm tests/ui tests/core -n auto -q
cd frontend && npm run build && npx vue-tsc --noEmit && node --test tests/*.test.mjs && cd ..

# 3. Tier 2: 全仓架构审计门 (静态规范、历史不变量、配置台账, ~90s)
.venv/bin/pytest tests/audit tests/extraction tests/ops -n auto -q
```

---

## 🚀 部署指南

### 方案 A：Docker 容器化部署（推荐 · 零宿主机依赖）

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git && cd astra-quant-agent
./setup.sh                  # 交互式向导配置环境（支持 --non-interactive）
./deploy/docker-start.sh    # 构建并启动控制面容器与调度容器

docker compose ps           # 查看运行状态
docker compose logs -f      # 跟踪聚合实时日志
```

### 方案 B：Linux 裸机部署

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git && cd astra-quant-agent
sh deploy/install.sh        # 初始化 Python 虚拟环境，自动升级 pip 并安装核心依赖
./setup.sh                  # 生成与加固 .env (chmod 600)
cd frontend && npm install && npm run build && cd ..
./start.sh                  # 在 0.0.0.0:8080 启动服务
```

Windows 环境提供 `start.ps1`；生产系统级常驻服务模板参考 `deploy/astra-quant.service` 与 `deploy/astra-gateway.service`。

---

## 代码结构入口

> **声明**：本仓库历史上**从未存在过 `OPENCODE.md`**，代码全景结构索引如下：

| 关注领域 | 入口文档 | 说明 |
|---|---|---|
| **总体架构与模块布局** | [`docs/STRUCTURE_OVERVIEW.md`](docs/STRUCTURE_OVERVIEW.md) | 分层架构规范与目录清单 |
| **后端分层** | [`astra_backend/README.md`](astra_backend/README.md) | L0 门面 / L1 装配 / L2 路由 / L3 领域 / L4 子包 |
| **运行时脚本与守护进程：哪个是入口/守护** | [`scripts/README.md`](scripts/README.md) | 根层脚本用途、调度入口与守护机制 |
| **提示词工程** | [`docs/PROMPT_GUIDE.md`](docs/PROMPT_GUIDE.md) | 提示词体系、插槽约定与决策军规 |
| **失败语义（为何需要各道闸）** | [`docs/FAILURE_SEMANTICS.md`](docs/FAILURE_SEMANTICS.md) | 历史事故沉淀与系统防御契约 |
| **北京时间契约** | [`docs/BEIJING_TIME_CONTRACT.md`](docs/BEIJING_TIME_CONTRACT.md) | 全局统一北京时间 (UTC+8) 财务结算底座 |
| **前端组件** | [`frontend/src/components/admin/README.md`](frontend/src/components/admin/README.md) | Vue 3 核心组件、状态与交互拆分 |
| **独立运行与配置** | [`STANDALONE.md`](STANDALONE.md) | 环境变量参考与单机运行说明 |
| **应急与故障恢复** | [`RECOVERY_GUIDE.md`](RECOVERY_GUIDE.md) | 紧急止损排障与灾备恢复方案 |
| **可观测性运维** | [`deploy/observability/README.md`](deploy/observability/README.md) | Prometheus 与 Grafana 监控配置 |

**盯着本仓的核心质量门禁：**

| 门禁 | 它防的是什么 |
|---|---|
| `tests/audit/test_directory_docs_current.py` | 新增模块未登记进 `__init__.py` 或对应 `README.md` |
| `tests/core/test_readme_baseline_numbers.py` | 文档里的测试基线数字失真腐烂 |
| `tests/audit/test_doc_paths_are_committed.py` | 文档指向未提交或不存在的路径 |
| `tests/audit/test_brand_strings_are_consistent.py` | 品牌与命名空间漂移 |
| `tests/audit/test_deployment_scripts_are_sound.py` | 交付物与启动脚本异常 |

---

## 品牌与内部代号（改名时必读）

- **对外品牌**：**AstraQuant** —— <https://www.astraquant.tech>
- **内部命名空间**：**`astra`**（包名 `astra_backend`、`astra_gateway`；配置前缀 `ASTRA_*`）

### 刻意保留的历史形态（勿动）

以下三类形态不是“漏改”，而是为保证生产连续性刻意保留的边界（`tests/audit/test_brand_strings_are_consistent.py` 会看护它们）：

1. **交易所持仓单标签 `t-r20sl*` / `t-r20tp*`**：撮合引擎上的活跃挂单可能由旧版本发起，改名会导致认不出自己曾经下的单，无法追踪撤销；新单已全部使用 `astrasl` / `astratp`；
2. **加密备份魔数 `R20GCM2` + NUL**：历史备份文件需要能够被新版解密恢复，新产生的备份文件使用 `ASTRAGCM`；
3. **测试夹具中的 `cpa.r20.cn`**：属于上游大模型中继网关的既有域名，不是本项目的命名空间。

---

## 风险与免责声明

1. 本软件为**开源量化交易系统与算法研究框架**，仅供技术研究、学习与模拟测试使用。
2. 加密货币衍生品合约交易具备极高的市场风险与价格波动，历史收益不预示未来表现。
3. 使用者应当具备完整的衍生品风险认知能力，在投入真实资金前务必通过模拟盘进行充分验证。
4. 作者与开源贡献者不承担任何因使用本软件产生的财务损失或交易纠纷。

---

## 开源许可证

本项目基于 **[GNU Affero General Public License v3.0 (AGPL-3.0)](LICENSE)** 结合 **[Commons Clause Condition v1.0](LICENSE)** 附则与反欺诈专项声明授权：

- 🔓 **个人学习与自营完全免费**：允许免费用于学术研究、策略开发、模拟盘验证以及个人自营账户实盘交易。
- 🛡️ **强传染性网络开源 (AGPLv3)**：任何基于本系统的修改或二次开发，若通过网络（包括但不限于 Web 界面、API、云端托管、Telegram/Discord 机器人等形式）向第三方提供交互服务，**必须 100% 免费开源其修改后的全部对应源代码**。
- 🚫 **严禁商业转售与收费带单 (Commons Clause)**：显式禁止任何未经授权将本软件闭源打包转售、收取月费订阅、出租交易信号或以本软件为核心开设付费托管服务的商业变现行为。
- ⚖️ **严正反割韭菜与防欺诈声明**：严禁任何人利用本项目从事非法集资、发行代币（发币/发NFT）、代客理财、承诺保本收益或冒充官方团队进行虚假宣传。
