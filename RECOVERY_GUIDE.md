# AstraQuant — 生产部署与灾备恢复手册 (v8.6.1)

> 本文档用于在全新服务器或灾难恢复场景下，快速恢复与拉起基于多模型对抗、7 层量化因子微积分验证与纯 Python 物理风控一票否决的 AstraQuant 自主量化交易系统。

---

## 1. 核心架构与关键资产

### 1.1 系统运行组件
- **交易决策主脑**：`scripts/ai_brain_trader.py` + `scripts/ai_factor_trader.py`（每 15 分钟主脑周期，多模型投委会质询，Maker/BBO 挂单，OKX 云端 OCO 止盈止损保护）；
- **微观因子与行情服务**：`scripts/factors/okx_quant_factors.py`（高频计算衍生品基差、订单流 CVD、深度盘口 OBI、波动率及量能筹码分布）；
- **自进化复盘引擎**：`scripts/self_improvement_engine.py`（基于真实平仓流水与因子证据，归因复盘并沉淀长期交易心法）；
- **统一网关与调度守护**：`astra_gateway/scheduler.py`（单进程驱动交易 15m、资讯 10m、因子 60s、进化 6h 与日终巡检 12h）；
- **Web 控制面与终端**：FastAPI 后端（`astra_backend/`）+ Vue 3 交易工作站与管理控制台（`frontend/`，静态构建后由 8080 端口统一反代）；
- **多端备份引擎**：`scripts/backup_runtime.py` + 后台「灾备中心」（`/admin/backup`，支持本地归档、S3/R2、阿里云 OSS、百度网盘、WebDAV、阿里云盘与夸克网盘）。

### 1.2 核心数据资产清单
| 资产路径 | 类型 | 说明与安全级别 |
|---|---|---|
| `data/astra_secrets.enc` & `.astra_secret_key` | 核心凭据 | Fernet 本地强加密存储的 OKX 交易 API 凭证，成对匹配 |
| `data/astra_admin.db` | 数据库 | 管理员账号鉴权与权限数据库（默认超级管理员 `admin`） |
| `data/astra_quant.db` | 数据库 | 本地量化交易流水、委托快照与审计台账 |
| `data/trading_ledger.json` | 交易台账 | 全量平仓历史账本与盈亏证据 |
| `data/structured_trading_memory.json` | 策略心法 | 自进化认知中枢的结构化长期记忆事实源 |
| `data/AI_TRADING_MEMORY.md` | 记忆镜像 | 供可视化与模型注入的 Markdown 格式心法镜像 |
| `data/instrument_pool.json` | 标的配置 | 活跃交易标的池、合约面值、精度与杠杆限制 |
| `data/prompt_library.json` | 提示词库 | 策略提示词方案与决策契约 |
| `data/council_config.json` | 投委会 | 多模型投委会席位名单与提示词设置 |
| `data/llm_models.json` | 模型网关 | 上游大模型接入凭证、端点与健康探测配置 |
| `data/backup_methods.json` | 备份配置 | 各灾备云存储渠道的加密接入凭据 |

---

## 2. 灾后冷恢复全流程

### 步骤 1：解压最新灾备归档包
从后台灾备中心备份的目标渠道（S3/OSS/网盘/本地）下载最新备份包 `data_backup_*.tar.gz`，解压至目标目录：
```bash
git clone https://github.com/0xethanq/astra-quant-agent.git astra-quant
cd astra-quant
tar -zxvf /path/to/data_backup_*.tar.gz
```

### 步骤 2：环境初始化与配置核对
运行交互式向导或初始化虚拟环境：
```bash
./setup.sh                  # 交互式向导，快速核对配置与初始凭证
# 或手动安装依赖：
sh deploy/install.sh        # 创建 .venv 并安装核心依赖
```

**凭证核对关键项**：
- 检查 `.env` 文件中的环境档位：`ASTRA_OKX_ENV=demo`（模拟盘）或 `live`（实盘）；
- 确认 `data/astra_secrets.enc` 与 `data/.astra_secret_key` 存在且成对匹配；
- 检查管理员访问口令：系统默认账号 `admin`，初始安全口令详见 `.env` 中的 `ASTRA_ADMIN_TOKEN`；
- 生产部署前，系统处于 `NOT READY` 状态，不会发生未经人工确认的真实交易所交互。

### 步骤 3：启动服务

**方案 A：Docker 容器启动（推荐）**
```bash
./deploy/docker-start.sh    # 构建并拉起控制面与守护容器
docker compose ps           # 检查服务健康状态
```

**方案 B：Linux 裸机 / systemd 服务启动**
```bash
# 1. 构建前端生产资源（如从源码全新构建）
cd frontend && npm install && npm run build && cd ..

# 2. 启动服务与调度守护
./start.sh
```
> 如需以 systemd 常驻运行，参考 `deploy/astra-quant.service` 与 `deploy/astra-gateway.service` 模板。

### 步骤 4：恢复验证与检查
1. 访问交易工作站：`http://<服务器IP>:8080/trading` 确认实时行情与微观结构正常渲染；
2. 登录管理控制台：`http://<服务器IP>:8080/admin/login`；
3. 进入「账户中心」：检查 OKX 运行状态，确认 API 响应正常且延迟健康；
4. 进入「风控中心」：确认各项风控参数符合当前资金规模预算。

---

## 3. 应急控制与制动操作 (Kill Switch)

### 3.1 紧急停机与停止调度（急停自动报单）
若发现外部行情极端异常或需紧急维护，立即中止自动化调度：
```bash
# 停止调度进程
pkill -f astra_gateway
# 检查是否已完全终止
pgrep -fl astra_gateway
```

### 3.2 紧急全平持仓与撤销挂单
- **方式 A（Web 控制台）**：
  登录管理后台，进入「持仓面板」或「账户安全」，点击对应标的的【紧急平仓】或全局【一键全平】按钮；
- **方式 B（交易所原生条件单托底）**：
  AstraQuant 采用交易所原生云端 OCO 委托机制。即使服务器断网或完全关机，挂在 OKX 撮合引擎上的止损单依然物理生效，本金处于云端强制保护状态。

### 3.3 数据清理与全新初始化重跑
若需彻底清空历史实战数据，从零启动新一轮测试：
```bash
# 1. 归档现有数据
mkdir -p .archive && tar -czf .archive/data_backup_$(date +%Y%m%d_%H%M%S).tar.gz data/ logs/

# 2. 清空交易台账与追踪状态（保留密钥与配置）
.venv/bin/python -c '
import json
for p in ["data/trading_ledger.json", "data/closed_trades.json", "data/closed_trade_evidence.json", "data/snapshots.json", "data/open_order_intents.json"]:
    with open(p, "w") as f: json.dump([], f)
for p in ["data/position_trackers.json", "data/trading_state.json", "data/stop_cooldown.json"]:
    with open(p, "w") as f: json.dump({}, f)
'
```

---

## 4. 常用运维与验证命令

- **查看后端服务运行状态**：`curl -s http://127.0.0.1:8080/api/all | head -c 120`
- **手工触发一次全量多通道云备份**：`.venv/bin/python scripts/nightly_backup_and_clean.py --all-enabled`
- **手工单次执行 AI 大脑推演周期**：`.venv/bin/python scripts/ai_brain_trader.py`
- **手工触发一次策略自进化复盘**：`.venv/bin/python scripts/self_improvement_engine.py`
- **手工执行 OKX 账本对账同步**：`.venv/bin/python scripts/sync_full_ledger.py`
- **磁盘存储与日志安全轮转检查**：`.venv/bin/python scripts/cleanup_disk.py`
