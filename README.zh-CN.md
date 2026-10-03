<div align="center">

[**简体中文**](README.zh-CN.md) · [English](README.md)

# AstraQuant

### 基于多大模型分析与确定性代码风控的加密货币自主量化交易系统

[![Release](https://img.shields.io/badge/Release-v8.6.1-00E599.svg?style=flat-square)](https://github.com/0xethanq/astra-quant-agent/releases)
[![License](https://img.shields.io/badge/License-AGPLv3%20%2B%20Commons%20Clause-blue.svg?style=flat-square)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB.svg?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![Vue 3](https://img.shields.io/badge/Vue-3.5%2B-4FC08D.svg?style=flat-square&logo=vuedotjs&logoColor=white)](https://vuejs.org/)

AstraQuant 将大语言模型多维度研判（宏观趋势、技术形态、盘口微结构）与 Python 确定性物理风控相结合，并通过 OKX 原生 API 实现限价入场与双腿云端止损止盈。

[界面预览](#界面预览) · [快速开始](#快速开始) · [开户返佣](#交易所开户与手续费返现) · [系统架构](#系统架构) · [量化因子](#行情与微观结构因子) · [风控模型](#资金管理与风控参数) · [部署指南](#部署指南) · [代码地图](#代码结构入口)

</div>

---

## 界面预览

| | |
|---|---|
| **机构量化交易大屏**<br>![交易工作台](docs/images/v850_live_dashboard.png) | **决策思维链 (CoT) 抽屉**<br>![思维链详情](docs/images/v850_trajectory_cot.png) |
| **物理风控管理中心**<br>![风控管理](docs/images/v850_risk_control.png) | **多模型协同投委会看板**<br>![投委会看板](docs/images/v850_council_board.png) |

<details>
<summary><b>展开查看更多系统界面</b>（提示词工坊、自进化、系统治理、安全凭证等）</summary>

| | |
|---|---|
| **提示词工程工坊**<br>![提示词工坊](docs/images/v850_prompt_studio.png) | **闭环经验自进化中枢**<br>![经验自进化](docs/images/v850_self_evolution.png) |
| **大模型网关与思考配置**<br>![大模型中枢](docs/images/v850_llm_hub.png) | **系统治理与运维概览**<br>![系统治理](docs/images/v850_admin_overview.png) |
| **安全与密钥凭证管理**<br>![安全中心](docs/images/v850_security_plaza.png) | **多维因子遥测矩阵**<br>![量化因子矩阵](docs/images/v850_calculus_factors.png) |

</details>

---

## 快速开始

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git && cd astra-quant-agent
./setup.sh                  # 交互式向导（推荐，2分钟完成基础环境配置）
# 容器启动：./deploy/docker-start.sh | 裸机环境：./deploy/install.sh && ./start.sh
```

| 服务入口 | 本地访问链接 | 访问定位 |
|---|---|---|
| **量化交易大屏** | `http://localhost:8080/trading` | 实盘持仓 HUD 与因子遥测大屏 |
| **管理控制中心** | `http://localhost:8080/admin/login` | 风控参数、提示词配置与 API 密钥管理 |
| **API 技术文档** | `http://localhost:8080/docs` | OpenAPI 规范与接口定义手册 |

> **默认模拟盘**：AstraQuant 出厂默认以 **模拟盘 (`demo`)** 模式启动。在配置正式交易凭证并显式切换实盘开关前，系统物理阻断真实资产调用。

---

## 交易所开户与手续费返现

> **交易接口兼容性声明**：AstraQuant 量化执行引擎**目前仅支持直连 OKX 原生 API**。币安 (Binance) 与芝麻开门 (Gate.io) 仅作为社区合作推荐开户通道提供最高手续费返现优惠，本系统暂不支持非 OKX 平台的 API 直连下单。

| 交易所 | 平台角色与兼容性 | 专属开户通道 | 邀请码 | 特别说明 |
|---|---|---|---|---|
| **OKX 欧易** | **系统实盘直连** (核心执行支持) | [前往 OKX 注册开户](https://www.mitxcqvwnhj.com/join/48039151) | `48039151` | 支持新用户及 **180 天未登录老用户重新绑定** 享受费率返还 |
| **Binance 币安** | 仅生态合作推广 (不支持 API 交易) | [前往币安注册开户](https://www.bsmkweb.cc/activity/referral-entry/CPA?ref=CPA_00N8UVQ2OG) | `CPA_00N8UVQ2OG` | 专属手续费减免链接；量化系统暂不支持直连下单 |
| **Gate.io 芝麻开门** | 仅生态合作推广 (不支持 API 交易) | [前往 Gate 注册开户](https://www.gatesites.net/share/MCHDBKYF) | `MCHDBKYF` | 专属手续费减免链接；量化系统暂不支持直连下单 |

---

## 核心设计原则

1. **智能体提议，代码强制风控**：大模型仅拥有交易意图提议权；Python 确定性风控底座行使绝对一票否决权，严密管控杠杆、仓位与止损位置。
2. **多视角协同研判**：通过宏观、趋势动量、盘口微结构等多模型席位分工研判，降低单一智能体的认知偏差。
3. **交易所原生安全防护**：订单成交后立即在交易所侧原子下发双腿条件单（TP1 独立算法腿平仓保本 + TP2 趋势跟随腿 + 100% 交易所云端 OCO 止损），防范断网与单点故障。

---

## 系统架构

系统以 15 分钟为一个完整决策周期，链路清晰解耦：

```text
1. 市场因子采集与清洗    ──> 资金费率、CVD 订单流背离、L2 深度 OBI、期权波动率偏度、VWAP 筹码中枢
2. 多模型投委会综合分析  ──> 宏观、趋势动量、盘口微结构席位独立分析并输出标准机器契约
3. Python 物理风控闸门  ──> 几何报价校验、仓位硬顶钳制、期望盈亏比底线、日内熔断审查（一票否决）
4. OKX 执行与云端双腿防护 ──> 被动 BBO Maker 限价单、分批止盈腿 (TP1/TP2) 与 100% 云端 OCO 止损
```

---

## 行情与微观结构因子

AstraQuant 摒弃简单滞后指标，结合高频衍生品微观数据进行综合评估：

| 维度 | 关键测算指标 | 在策略中的作用 |
|---|---|---|
| **订单流与主动吃单** | 累计成交量差 (CVD Divergence) 背离、主力主动吃单净流入 | 识别大资金主动进攻意图与被动吸收盘 |
| **盘口微观失衡** | 盘口失衡度 (Order Book Imbalance, OBI)、前20档深度不对称性 | 量化买卖盘瞬时物理阻力，防范流动性真空 |
| **持仓筹码与费率** | 资金费率变化率、未平仓持仓量 (OI) 导数、多空账户比 | 侦测杠杆拥挤度与潜在单边踩踏挤压风险 |
| **波动率曲面** | 期权隐含波动率 (IV) 偏度、最大痛点引力位 | 评估市场尾部对冲预期与行权日筹码引力 |
| **结构锚点** | 成交量加权平均价 (VWAP ±1σ / ±2σ)、VPVR 筹码控制点 (POC) | 定位机构公允价值区间与均值回归边界 |
| **动量向量** | MACD 柱一阶速度与二阶加速度、ADX 趋势强度向量 | 区分单边加速行情与震荡衰竭伪突破 |

---

## 多模型分析与提示词缓存

- **专业席位分工**：支持 DeepSeek-V3/R1、Claude 3.5 Sonnet、GPT-4o、Qwen 等前沿模型分别担任宏观策略官、技术动量官、盘口量化官与逆向风控官。
- **博弈裁决机制**：支持*一票否决*（严重异常降级为 WAIT）、*加权多数决*与*动能突破优先*等仲裁模式。
- **提示词缓存 (Prompt Caching)**：
  - 提示词上下文 90% 以上由稳定规则、风控边界与全市场因子矩阵构成；
  - 投委会各席位基于共享前缀进行广播推理，实现亚秒级首字响应 (TTFT)，显著降低 API 推理成本。

---

## 资金管理与风控参数

风控规则由底层代码 (`scripts/risk_constants.py`) 严格执行。出厂基准参数：

| 参数项 | 基准值 | 业务逻辑与防守说明 |
|---|---|---|
| **全系统总持仓上限** | `6` 笔 | 全市场最多同时持有的活跃仓位数 |
| **同向持仓上限** | `4` 笔 | 纯多单或纯空单笔数上限，防范大盘同向 Beta 踩踏 |
| **单标的保证金硬顶** | `可用余额 × 30%` | 限制单一币种仓位集中度 |
| **日内亏损熔断线** | `min(150 USDT, 权益 × 5%)` | 触发后 24 小时内禁止新开仓 |
| **动态杠杆区间** | `2.0x – 5.0x` | 结合品种波动率 (ATR) 与流动性动态钳制 |
| **最低期望盈亏比 (R:R)**| `R:R ≥ 2.0` | 拦截盈亏比不达标交易，保障数学正期望 |
| **最长持仓时间止损** | `4.0 小时` | 超时且无动能突破的横盘仓位自动平价释放 |
| **云端止损覆盖率** | `100%` | 每一笔成交均挂载交易所原生条件止损单 |

---

## 部署指南

> 💡 **云服务器安全组与端口配置提示（避坑必读）**：
> 在公网云服务器（阿里云 / 腾讯云 / AWS / 各类海外 VPS）部署前，请在服务商控制台安全组入站规则中确认放行：
> - **8080 (TCP 入站)**：AstraQuant 操盘大屏与管理控制面（公网访问必须）；
> - **22 (TCP 入站)**：SSH 远程终端连接与运维管理；
> - **443 (TCP 出站)**：直连 OKX REST API 与 LLM 推理网关。
>
> ⚠️ **交易安全红线**：OKX API 密钥仅需勾选 **读取** 与 **交易** 权限，**严禁开启提现权限**；强烈建议在 OKX 控制台绑定服务器静态公网 IP。

| 部署方式 | 宿主机依赖 | 特点与适用场景 | 推荐度 |
|---|---|---|:---:|
| **Docker 容器（推荐）** | 仅需 `Docker` 与 `Docker Compose` | 零宿主机依赖、多阶段自动打包前端、进程自愈看门狗 | ⭐⭐⭐⭐⭐ |
| **Linux 裸机部署** | `Python 3.11+` (`python3-venv`), `Node.js 18+`, `Git` | 本地源码调试、二次开发与极低内存实例 | ⭐⭐⭐ |

### 选项 A：Docker 容器（推荐）

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git && cd astra-quant-agent
./setup.sh                  # 交互式初始化向导
./deploy/docker-start.sh    # 构建并拉起后台与网关容器
docker compose ps           # 检查容器运行状态
```

### 选项 B：Linux / macOS 裸机部署

```bash
git clone https://github.com/0xethanq/astra-quant-agent.git && cd astra-quant-agent
sh deploy/install.sh        # 安装 Python 虚拟环境与依赖
./setup.sh                  # 配置 .env 环境
cd frontend && npm install && npm run build && cd ..
./start.sh                  # 启动控制面服务 (http://0.0.0.0:8080)
```

---

## 自动化测试

```bash
# Tier 0: 核心量化业务门 (~20秒)
.venv/bin/pytest tests/trading tests/venues tests/risk tests/backtest -n auto -q

# Tier 1: 模型与前端集成门 (~60秒)
.venv/bin/pytest tests/llm tests/ui tests/core -n auto -q
cd frontend && npm run build && npx vue-tsc --noEmit && node --test tests/*.test.mjs && cd ..

# Tier 2: 全量架构审计门 (~90秒)
.venv/bin/pytest tests/audit tests/extraction tests/ops -n auto -q
```

---

<a id="代码结构入口"></a>
## 代码结构入口

> 本仓库历史上从未存在过 `OPENCODE.md`。权威工程架构与入口索引如下：

| 领域 | 规范文档 | 核心说明 |
|---|---|---|
| **架构全景** | [`docs/STRUCTURE_OVERVIEW.md`](docs/STRUCTURE_OVERVIEW.md) | 分层架构与各子目录核心职责划分 |
| **后端分层** | [`astra_backend/README.md`](astra_backend/README.md) | 后端分层 (L0 门面 / L1 装配 / L2 路由 / L3 领域 / L4 子包架构与新模块约定) |
| **哪个是入口/守护** | [`scripts/README.md`](scripts/README.md) | 哪个是入口/守护 (38 个根层脚本用途、调度入口、守护进程与双拼写 import 铁律) |
| **提示词工程** | [`docs/PROMPT_GUIDE.md`](docs/PROMPT_GUIDE.md) | 提示词正文 JSON 库、8 大语义插槽与席位模板 |
| **失败语义手册** | [`docs/FAILURE_SEMANTICS.md`](docs/FAILURE_SEMANTICS.md) | 真实事故复盘与防御性不变量清单 |
| **北京时间契约** | [`docs/BEIJING_TIME_CONTRACT.md`](docs/BEIJING_TIME_CONTRACT.md) | 统一 UTC+8 财务结算与时间戳基线 |
| **前端组件** | [`frontend/src/components/admin/README.md`](frontend/src/components/admin/README.md) | 前端组件与 Composables (Vue 3 管理后台与操盘看板组件、状态与业务逻辑划分) |
| **独立部署** | [`STANDALONE.md`](STANDALONE.md) | 本地独立部署与环境变量配置手册 |
| **应急止损** | [`RECOVERY_GUIDE.md`](RECOVERY_GUIDE.md) | 紧急平仓与状态冷恢复实操预案 |
| **可观测性** | [`deploy/observability/README.md`](deploy/observability/README.md) | Prometheus 指标采集与 Grafana 监控大屏 |

**持续治理与防腐烂门禁：**

| 门禁文件 | 监控范围与防护目标 |
|---|---|
| [`tests/audit/test_directory_docs_current.py`](tests/audit/test_directory_docs_current.py) | 确保新增模块均已登记进子包 `__init__.py` 与对应清单 |
| [`tests/core/test_readme_baseline_numbers.py`](tests/core/test_readme_baseline_numbers.py) | 保证文档中的基线数字与实际测试用例保持同步 |
| [`tests/audit/test_doc_paths_are_committed.py`](tests/audit/test_doc_paths_are_committed.py) | 确保文档引用的所有源码路径真实存在并已入库跟踪 |

---

## 品牌与内部代号

- **公开品牌**：**AstraQuant** — <https://www.astraquant.tech>
- **内部命名空间**：**`astra`**（包名 `astra_backend`, `astra_gateway`；配置前缀 `ASTRA_*`）

### 历史兼容标记（保留项）

为保护历史运行态与交易所订单追踪，以下标记有意保留（`tests/audit/test_brand_strings_are_consistent.py`）：
1. **交易所订单标记 `t-r20sl*` / `t-r20tp*`**：旧订单保持兼容跟踪；新订单使用 `astrasl` / `astratp`。
2. **加密备份标识 `R20GCM2` + NUL**：历史备份保持可解密；新备份使用 `ASTRAGCM`。
3. **测试夹具 `cpa.r20.cn`**：维护者内部 LLM 网关域名，非仓库命名空间。

---

## 生态与社区

AstraQuant 积极参与并支持 **[LINUX DO (linux.do)](https://linux.do/)** 开源技术社区。

---

## 免责声明

1. 本项目为开源量化科研与自营交易框架，仅供学术研究、技术验证与模拟测试使用。
2. 加密货币衍生品具有高杠杆与高波动风险，历史回测不保证未来实际收益。
3. 使用者须具备完备的风险管理意识，并在投入实盘前在模拟盘（`demo`）中完成全面验证。
4. 作者与贡献者对因使用本软件造成的任何资本损失概不承担责任。

---

## 开源协议

AstraQuant 采用 **[GNU Affero General Public License v3.0 (AGPL-3.0)](LICENSE)** 结合 **[Commons Clause Condition v1.0](LICENSE)** 及防欺诈附加条款分发。

- **科研与自营交易自由**：源码完全开放，支持学术研究、策略开发与个人自营部署。
- **网络使用传染 (AGPLv3)**：任何通过网络提供服务的修改版本必须公开对应的完整源代码。
- **禁止商业转售与收费带单 (Commons Clause)**：未经许可，严禁将本软件封装为闭源商业产品或运营收费带单跟单服务。
- **防欺诈条款**：严禁利用本项目进行任何非法集资、发币或未经授权的商业背书。
