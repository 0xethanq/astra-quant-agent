<div align="center">

[**简体中文**](README.zh-CN.md) · [English](README.md)

# AstraQuant

### OKX 原生自主量化交易终端 · 多智能体操作系统

[![Release](https://img.shields.io/badge/Release-v8.5.0--preview-00E599.svg?style=flat-square)](https://github.com/0xethanq/astra-quant-agent/releases)
[![Website](https://img.shields.io/badge/Site-www.astraquant.tech-6E56CF.svg?style=flat-square)](https://www.astraquant.tech)
[![License](https://img.shields.io/badge/License-MIT-green.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg?style=flat-square&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Vue 3](https://img.shields.io/badge/Vue-3.5%2B-4FC08D.svg?style=flat-square&logo=vuedotjs&logoColor=white)](https://vuejs.org/)
[![Tests](https://img.shields.io/badge/Tests-9.5k%2B%20Passing-brightgreen.svg?style=flat-square)](tests/)
[![Community](https://img.shields.io/badge/Community-LINUX%20DO-F97316.svg?style=flat-square&logo=linux&logoColor=white)](https://linux.do/)

**多模型席位辩论 → CIO 仲裁定调 → 物理 Python 风控管线一票否决 → OKX 收到带原子条件单的 Maker 限价委托。**

*认知交给模型，物理风控交给底座。没有黑箱魔法。*

[快速开始](#-快速开始) · [系统架构](#-系统架构) · [设计原则](#-设计原则) · [调度节奏](#-调度节奏) · [提示词体系](#-提示词体系) · [风控模型](#-风控模型) · [界面一览](#-界面一览) · [部署](#-部署) · [代码结构入口](#-代码结构入口)

</div>

> 🌟 **本项目已与开源技术社区 [LINUX DO（linux.do）](https://linux.do/) 达成官方合作并真诚致谢。**

---

## 🚀 快速开始

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git && cd astra-quant-agent
./deploy/docker-start.sh     # 推荐 Docker。裸机：./deploy/install.sh && ./start.sh
```

| 界面 | 地址 | 访问 |
|---|---|---|
| **交易工作站** | `http://localhost:8080/trading` | 公开 |
| **管理控制台** | `http://localhost:8080/admin/login` | 用户 `admin` |
| **系统文档与 OpenAPI** | `http://localhost:8080/docs` | 公开 |

> 🛡️ **安全优先。** 系统默认以**模拟盘 / 纸面模式**启动，在你同时配置好 **LLM 供应商密钥**与 **OKX API 密钥**、并在 `/admin/security` 打开实盘开关之前，绝不会触碰真实资金。所选环境缺少完整密钥三件套时，系统会显示 `NOT READY` 并拒绝一切交易。

---

## 🏛 系统架构

一个 15 分钟周期，四道硬边界。界线以下的每一层都是你可以阅读、测试、修改的普通 Python：

```text
                    ┌───────────────────────────────────────────────┐
                    │        调度器 · 15 分钟主脑周期                │
                    │  交易 15m · 资讯 10m · 因子 60s · 进化 6h      │
                    └───────────────────────┬───────────────────────┘
                                            ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ 1 · 市场体制识别与数理基石                                            │
   │   速度 v · 加速度 a · 冲击 I · 能量 ∫E · 偏离面积 ∫A                   │
   │   概率（偏度 / 峰度 / VaR / CVaR）· ADX · 盘口深度 · OI · 宏观资讯      │
   │   → 体制标签（单边趋势 / 宽幅震荡 / 低速区间 / …）                     │
   └───────────────────────────────┬────────────────────────────────────────┘
                                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ 2 · 多模型投委会                     （席位与供应商由你自定义）        │
   │   趋势席 · 动能席 · 数理量化席 · 宏观资讯席                            │
   │   交叉质询轮次  →  CIO 首席投资官仲裁出唯一下单意向                    │
   └───────────────────────────────┬────────────────────────────────────────┘
                                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ 3 · 失效关闭（Fail-Closed）物理风控管线        （不可绕过的 Python）   │
   │   数据有效性 · 价格几何 · 盈亏比硬底线 · 4H 方向否决                   │
   │   杠杆与保证金上限 · 同向敞口配额 · 拦截插件                           │
   │   ⚠️ 任何异常或超时  =  硬拒绝（绝不「照常开仓」）                     │
   └───────────────────────────────┬────────────────────────────────────────┘
                                   ▼
   ┌────────────────────────────────────────────────────────────────────────┐
   │ 4 · OKX 原生执行                                                      │
   │   Maker / BBO 限价 · 附带 TP1 · TP2 · 云端止损条件单                   │
   │   分批止盈（2.0×ATR 平 35%）· 利润棘轮 · 时间止损（8h）                │
   └────────────────────────────────────────────────────────────────────────┘
```

每一根箭头都可观测：完整思维链、每个席位的质询记录、数理快照、拦截器裁决与最终 `policy_hash` 都会逐笔落盘。

---

## 🎯 设计原则

1. **认知归模型，物理风控归底座。**
   LLM 与投委会只拥有**提议权**。任何委托在抵达交易所 socket 之前，必须通过 100% 的 Python 风控闸门。任一拦截器抛异常或超时，一律 **fail-closed 阻断开仓**。模型幻觉在物理上无法变成真实亏损。

2. **市场体制自适应，而不是曲线拟合。**
   趋势策略在震荡里流血，均值回归网格在单边突破里爆仓。体制状态由数理与波动结构持续推导，随动调整提示词策略与杠杆带宽。

3. **OKX 原生设计。**
   一个交易所、一套凭证、一条签名路径、一份订单契约。旧的交易所抽象层已移除：不存在分叉的交易所代码路径、不存在「多所对等」承诺、不存在跨所套利矩阵。每一笔进场都从同一条路径携带原生条件保护。

4. **全白盒可解释 + 闭环自进化。**
   每一次决策都记录推理链、辩论记录、数理特征与执行证据。每天 4 次，自进化引擎挖掘**真实已平仓台账**，在严格的反编造规则下把经验蒸馏进长期记忆（见[提示词体系](#-提示词体系)）。

---

## ⏱ 调度节奏

所有节奏只在**一处**声明（`astra_gateway/scheduler.py`），下表即为契约：

| 任务 | 节奏 | 超时 | 职责 |
|---|---|---|---|
| `trader` | **每 15 分钟** | 1260 s | 完整主脑周期：行情 → 投委会 → 风控闸门 → OKX 执行 |
| `news` | 每 10 分钟 | 300 s | 采集并加权宏观 / 币圈要闻，供资讯席位使用 |
| `factor_library` | 每 60 秒 | 55 s | 刷新技术因子库 |
| `self_improvement` | **02:00 / 08:00 / 14:00 / 20:00** | 1200 s | 平仓归因 → 长期记忆更新 |
| `daily_briefing` | 08:00 / 20:00 | 600 s | 每日总结与备份 |

---

## 🎨 提示词体系

> **这是外界最容易误解的部分，所以直说。**

**全部提示词正文只存在一个文件里** —— `data/prompt_library.json`（出厂基线，随 git 跟踪；你的改动落在 `data/prompt_library.local.json`）。**Python 里没有任何提示词正文。**

| 组成 | 归属 | 可否编辑 |
|---|---|---|
| **输出 JSON Schema** —— 模型回复的机器契约 | **代码**（`scripts/ai_brain_trader.py`） | ❌ **只读**：工坊禁用、接口拒绝改动、被删除时渲染层会回插 |
| 角色、军规、入场规则、兑现节奏、任务清单、复盘规则 | `data/prompt_library.json` | ✅ 在可视化提示词工坊里自由编辑 |
| 实时数据（行情矩阵、持仓、预算、记忆、资讯） | 代码逐周期生成 | 通过 `{{插槽}}` 变量注入 |

**为什么 Schema 只读。** 它不是文档，而是解析器依赖的契约 —— 改一个字段名就可能让**整轮决策解析失败**。因此它随代码发版，绝不通过工坊改动。

**为什么正文搬出了 Python。** 过去同一段文案存在**三份**副本（Python 常量、JSON 基线、你的本地改动）。改一处另几处不同步，表现就是**「我在工坊里改了，实发提示词却一直没变」**。收敛为单一事实源后，这整类故障消失。

**实时语义插槽** —— 8 个语义插槽承载运行态：`{{decision_timestamp}}` `{{account_balance}}` `{{risk_budget}}` `{{account_positions}}` `{{pending_orders}}` `{{market_matrix}}` `{{news_intelligence}}` `{{trading_memory}}`（四条管线合计 24 个可用变量，含进化管线的台账插槽）。

📖 完整编写指南、插槽字典与出厂策略口径：**[`docs/PROMPT_GUIDE.md`](docs/PROMPT_GUIDE.md)**

---

## 🧩 策略配置中心

> *策略的定义权永远属于交易者，而不属于硬编码逻辑。*

| # | 模块 | 管什么 |
|---|---|---|
| 1 | 🎨 **提示词工坊** | 以有序模块编辑四条提示词管线；注入实时插槽；复制 / 导入导出方案；防提示词投毒护栏；输出 Schema 保持锁定 |
| 2 | 👥 **多模型投委会** | 自定义席位，绑定任意 OpenAI / Anthropic 兼容供应商；投票权重、交叉质询、CIO 仲裁 |
| 3 | 🛡️ **失效关闭拦截器** | 不可绕过的 Python 插件闸门（4H 宏观方向、入场置信度、ADX 震荡过滤、盈亏比底线）。插件故障即停止开仓 |
| 4 | 🧬 **自进化引擎** | 每 6 小时对已平仓台账归因；在离群剔除与反编造规则下把经验蒸馏进提示词记忆 |
| 5 | 📦 **策略快照** | 把提示词 + 拦截器 + 投委会席位 + 标的参数哈希成指纹；亚秒级原子回滚；逐笔审计 `policy_hash` |
| 6 | 🎛️ **风控中心** | 全部 **27** 个物理执行旋钮均可在界面配置，含保守 / 均衡 / 激进预设与破坏性操作二次确认 |
| 7 | 🤖 **LLM 网关** | 多供应商直连；推理模型思考预算最高 1800 s；限流（HTTP 429）或故障时自动切换 |
| 8 | 🌐 **OKX 连通性** | OKX V5 原生接入，模拟盘 / 实盘凭证档案分离；资金费率、未平仓量、动能分析 |
| 9 | 🧪 **回测与沙箱** | 多标的组合回测与沙箱重放，执行与实盘**完全相同**的 Python 风控与仓位推导代码路径 |

---

## 💰 风控模型

所有参数随**账户权益**伸缩 —— 20 USDT 模拟盘与 10,000 USDT 实盘跑同一套逻辑。下表为出厂的*均衡*基线，与执行层强制使用的常量同源（`scripts/risk_constants.py`）：

| 规则 | 公式 / 取值 | 20 USDT 模拟盘 | 4,000 USDT 实盘 |
| :--- | :--- | ---: | ---: |
| 单笔风险（1R） | `min(单标的封顶, 权益 × 4.5%)` | 0.90 USDT | 180 USDT |
| 单笔最大保证金 | `权益 × 40%` | 8.00 USDT | 1,600 USDT |
| 单标的累计保证金 | `权益 × 48%` | 9.60 USDT | 1,920 USDT |
| 当日亏损熔断 | `min(500 USDT, 权益 × 10%)` | 2.00 USDT | 400 USDT |
| 杠杆带宽 | `6x – 12x`，按标的收紧 | 已夹取 | 已夹取 |
| 盈亏比下限 / 上限 | `≥ 2.0`，`≤ 5.0` | — | — |
| 止损距离 | `2.0 × ATR(1H)` | — | — |
| 止盈距离上限 | `≤ 4.5 × ATR` | — | — |
| 分批止盈 | 底仓浮盈 `2.0 × ATR` 时平 `35%` | — | — |
| 时间止损 | `8 小时` | — | — |
| 止损后冷静期（单标的） | `15 分钟` | — | — |
| 同向持仓上限 | `5` 笔 | — | — |
| 金字塔加仓 | `≤ 2` 次，每次需 `≥ 68%` 置信度且浮盈 `≥ 0.6%` | — | — |
| 最低开仓置信度 | `68%` | — | — |

> ⚙️ 这些是默认值而非教条：每一项都能在风控中心修改，并在下一个周期生效。

---

## 📸 界面一览

| | |
|---|---|
| **实盘交易工作站**<br>![实盘工作站](docs/images/v840_live_dashboard.png) | **思维链（CoT）推理抽屉**<br>![思维链](docs/images/v840_trajectory_cot.png) |
| **因果微积分动力学矩阵**<br>![数理因子](docs/images/v840_calculus_factors.png) | **多模型投委会看板**<br>![投委会](docs/images/v840_council_board.png) |
| **可视化提示词工坊**<br>![提示词工坊](docs/images/v840_prompt_studio.png) | **自进化引擎**<br>![自进化](docs/images/v840_self_evolution.png) |
| **失效关闭拦截器**<br>![拦截器](docs/images/v840_interceptors_failclosed.png) | **策略快照与回滚**<br>![策略快照](docs/images/v840_policy_snapshot.png) |
| **执行风控中心**<br>![风控中心](docs/images/v840_risk_control.png) | **LLM 网关与推理配置**<br>![LLM 网关](docs/images/v840_llm_hub.png) |
| **管理控制台总览**<br>![管理总览](docs/images/v840_admin_overview.png) | **安全与策略广场**<br>![安全中心](docs/images/v840_security_plaza.png) |

---

## 📊 可观测性

| 日志器 | 路径 | 产生进程 | 覆盖范围 |
| :--- | :--- | :--- | :--- |
| `trader` | `logs/ai_factor_trader.log` | 主脑周期守护 | 行情、辩论、置信度标定、下单、条件单、移动棘轮 |
| `backend` | `logs/uvicorn.log` | FastAPI / Uvicorn | 请求生命周期、鉴权、CORS、异常栈、遥测 |
| `scheduler` | `logs/astra_gateway.log` | 调度守护 | 分布式锁租约、定时派发、心跳、日志清理 |
| `audit` | `logs/astra_admin_audit.jsonl` | 安全审计子系统 | 追加式 JSONL：时间、IP、操作者、动作 |

两个 Docker 容器都带容器内看门狗与健康探测 —— 因为 `restart:` 策略只覆盖**进程退出**，「进程还活着但已卡死」这种死法否则永远不会被发现。

> 📈 **Prometheus & Grafana**：预置看板见 [`deploy/observability/README.md`](deploy/observability/README.md)，可视化 `/api/v1/admin/metrics`。

---

## 🧪 测试

本仓文档里的每一处声明都有自动门禁兜底；跑绿门禁本身就是交付物的一部分。

```bash
# 1) 后端 —— 全量离线回归（结构门、LLM 契约、交易所契约、UI）
.venv/bin/pytest tests/ -q

# 2) 前端 —— 类型检查、生产构建、组件测试
cd frontend
npx vue-tsc --noEmit -p tsconfig.app.json
npm run build
node --test tests/*.test.mjs
```

> ⚠️ 始终使用 `.venv/bin/python` 与 `.venv/bin/pytest` —— 本仓**刻意不依赖全局 Python**。

---

## 🚀 部署

### 方案 A 🐳 Docker（推荐，宿主机零依赖）

打包 Python 3.11、编译 Vue 3 产物，并同时拉起 Web 应用与调度器：

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git
cd astra-quant-agent
cp env.example .env && vim .env      # 配置 LLM 与 OKX 凭证
./deploy/docker-start.sh             # 等价于 docker compose up -d --build

docker compose ps                    # 查看状态
docker compose logs -f               # 跟踪聚合日志
```

> 💡 一键脚本会预先检查 Docker 的经典陷阱：宿主机上缺失的 `./.env` 会被**静默创建成同名目录**，导致配置永远保存不上。真发生时，容器入口会拒绝启动并打印可直接复制的修复命令。

### 方案 B 裸机安装

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git
cd astra-quant-agent
sh deploy/install.sh                 # 创建 .venv 并安装依赖
vim .env

cd frontend && npm install && npm run build && cd ..
./start.sh                           # 在 0.0.0.0:8080 启动 Uvicorn
```

Windows 用户运行 `start.ps1`。systemd 单元模板：`deploy/astra-quant.service`、`deploy/astra-gateway.service`、`deploy/astra-scheduler.service`。

---

## 🗂 代码结构入口（开发者与接手必读）

> ⚠️ **防坑声明**：本仓库历史上**从未存在过 `OPENCODE.md`** —— 外部部分旧文档提示寻找该文件纯属误导。请直接阅读下方真实存在的结构入口：

| 学习与开发目标 | 查阅入口 | 核心说明 |
|---|---|---|
| **总体架构与模块布局** | [`docs/STRUCTURE_OVERVIEW.md`](docs/STRUCTURE_OVERVIEW.md) | 分层架构、目录约定与各域模块清单 |
| **后端分层** | [`astra_backend/README.md`](astra_backend/README.md) | L0 门面 / L1 装配 / L2 路由 / L3 领域 / L4 子包 |
| **运行时脚本与守护进程：哪个是入口/守护** | [`scripts/README.md`](scripts/README.md) | 根层脚本用途、调度入口、守护进程与双拼写 import 铁律 |
| **提示词工程** | [`docs/PROMPT_GUIDE.md`](docs/PROMPT_GUIDE.md) | 插槽字典、编写军规与出厂策略口径 |
| **失败语义（每道闸为何存在）** | [`docs/FAILURE_SEMANTICS.md`](docs/FAILURE_SEMANTICS.md) | 逐条事故与对应的防御设计 |
| **北京时间契约** | [`docs/BEIJING_TIME_CONTRACT.md`](docs/BEIJING_TIME_CONTRACT.md) | 全链路时间口径与格式化约定 |
| **前端组件** | [`frontend/src/components/admin/README.md`](frontend/src/components/admin/README.md) | Vue 3 组件、composable 与状态划分 |
| **独立运行部署** | [`STANDALONE.md`](STANDALONE.md) | 本地裸机部署与环境变量配置 |
| **应急与故障恢复** | [`RECOVERY_GUIDE.md`](RECOVERY_GUIDE.md) | 应急止损、进程重置与数据冷恢复 |
| **可观测性** | [`deploy/observability/README.md`](deploy/observability/README.md) | Prometheus 抓取目标与 Grafana 看板 |

**盯着本仓的门禁：**

| 门禁 | 它防的是什么 |
|---|---|
| `tests/audit/test_directory_docs_current.py` | 新增模块却没登记进 `__init__.py` **和** 对应 `README.md` |
| `tests/core/test_readme_baseline_numbers.py` | 文档里的测试基线数字悄悄腐烂失真 |
| `tests/audit/test_doc_paths_are_committed.py` | 文档指向不存在、或未提交的路径 |
| `tests/audit/test_brand_strings_are_consistent.py` | 品牌 / 命名空间漂移（会破坏线上生产数据） |
| `tests/audit/test_deployment_scripts_are_sound.py` | 启动脚本或 Docker 交付物实际上起不来 |

---

## 🏷 品牌与内部代号（改名时必读）

- **对外品牌**：**AstraQuant** —— <https://www.astraquant.tech>
- **内部命名空间**：**`astra`**（包名 `astra_backend`、`astra_gateway`；配置前缀 `ASTRA_*`）

### 有意保留的历史标记 —— 请勿改名

为保护线上生产数据与在途持仓，以下三处历史标记被刻意保留（由 `tests/audit/test_brand_strings_are_consistent.py` 守护）：

1. **交易所条件单标签 `t-r20sl*` / `t-r20tp*`** —— 命名空间升级之前挂出的条件单仍在撮合引擎上存活。`scripts/tag_markers.py` 保留它们，使云端棘轮能继续管理；新订单使用 `astrasl` / `astratp`。
2. **加密备份魔数 `R20GCM2` + NUL** —— 用户既有的加密归档必须仍可解密。新归档使用 `ASTRAGCM`。
3. **测试夹具里的 `cpa.r20.cn`** —— 维护者专用的 LLM 上游 DNS 网关，不是仓库命名空间。

---

## 🤝 社区与致谢

AstraQuant 已与开源技术社区 **[LINUX DO（linux.do）](https://linux.do/)** 达成官方合作并真诚致谢。

- 🐧 **技术土壤** —— 感谢 LINUX DO 的技术讨论、策略灵感与社区反馈。
- 💬 **一起聊** —— 多智能体提示词工程、风控参数、加密量化实盘执行。

---

## ⚠️ 免责声明

1. 本项目是**开源算法交易软件与量化研究框架**，仅用于研究、教育与模拟测试。
2. 加密货币衍生品交易存在重大本金损失风险与极端波动。历史表现与回测结果不保证未来收益。
3. 使用者必须具备足够的风险管理知识，并应在部署真实资金前于 **DEMO / 纸面交易**环境充分验证策略。
4. 作者与开源贡献者对使用本软件造成的任何财务损失不承担责任。

---

## 📄 开源许可证

基于 [MIT License](LICENSE) 分发。
