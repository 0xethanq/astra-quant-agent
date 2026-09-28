# OKX 接入说明（Exchange Support）

> **单一事实文档**：本系统是 **OKX 专用**系统，只对接 **OKX V5 永续**
> （适配器 `astra_backend/exchanges/okx.py`；直签链路 `scripts/okx_rest.py`）。
>
> 代码级能力表见 `astra_backend/exchanges/okx.py` 的 `ExchangeCapabilities`，
> 本文档与其保持同步；口径差异以代码为准。

## 1. 当前支持状态

| 场所 | 只读行情 | 决策证据 | 凭证配置 | 实盘执行 |
|---|---|---|---|---|
| **OKX V5 永续**（唯一场所） | ✅ 公共 REST（无需凭证） | ✅ 全因子（资金费率 / 持仓 OI / 多空比 / Taker） | ✅ 三件套（API Key + Secret Key + Passphrase） | ✅ 生产链路（`scripts/ai_factor_trader.py` 直签） |

能力要点（与 `ExchangeCapabilities` 对齐）：

| 维度 | OKX V5 |
|---|---|
| 标的命名 | `{base}-USDT-SWAP`（如 `BTC-USDT-SWAP`） |
| 下单数量单位 | **张**（`contracts`），按合约面值 `ctVal` 折算名义额 |
| 订单号类型 | 字符串 |
| 附带止盈止损 | ✅ `attachAlgoOrds`（同一订单原子附带 TP/SL） |
| 触发价默认 | 最新价；保护腿**显式**发 `mark`（标记价） |
| 持仓模式 | `net` / `long_short`；**入场准入只认 `long_short`**（`entry_ready_position_modes`，净持仓载荷未核验） |
| K 线上限 | 300 根 |
| 限频 | 公共行情约 20 req/2s，429 常见需退避 |
| 公开数据 | 有 Top Trader 多空比、Taker 主动比 |
| 大陆网络 | ✅ 可用 |

## 2. 凭证与档位（demo / live）

- **档位开关**：`ASTRA_OKX_ENV=demo|live`（缺省按兼容键 `OKX_IS_SIMULATED` 推导，
  未配置时兜底 `demo`）。档位决定读哪一组档位键。
- **档位键是原子三元组**：`OKX_DEMO_API_KEY` / `OKX_DEMO_SECRET_KEY` /
  `OKX_DEMO_PASSPHRASE` 与对应的 `OKX_LIVE_*`。**部分填入不得借用另一档的单个字段**
  —— 未配齐即视为该档未配置。
- **兼容旧写法**：`OKX_API_KEY` / `OKX_SECRET_KEY` / `OKX_PASSPHRASE` + `OKX_IS_SIMULATED`。
- **后台录入（推荐）**：`/admin` →「账户接入」按 DEMO / LIVE 分别录入三件套，
  本地 **Fernet 加密**存储（`data/astra_secrets.enc` + 匹配的 `data/.astra_secret_key`），
  **留空不改**已有值；只授予必要读取/交易权限，禁用提款权限。
- **就绪探针**：`GET /api/v1/admin/okx/runtime` 报告 `environment` / `mode_configured` /
  `live_configured` / `demo_configured` / `fingerprint` / `base_url` / `status`。
  ⚠️ `READY` **只表示本地配置齐全**，不代表交易所鉴权已通过 —— 恢复交易前先用只读账户快照核对。
- 单一事实源：`scripts/okx_runtime.py`（`selected_environment()`）。

## 3. 开闸（下单开关）

OKX 下单**不走**「适配器执行开关」那一族环境旗标：

1. 主链下单在 `scripts/ai_factor_trader.py` 的 **OKX 直签链路**（`scripts/okx_rest.py` +
   `scripts/okx_runtime.py`）上完成；
2. 该链路的档位与凭证由 `ASTRA_OKX_ENV` + 上节的凭证三元组共同把关，**未配齐即 NOT READY**，
   私有调用与交易 **fail-closed**；公共行情不受影响，仍可免凭证读取；
3. `astra_backend/exchanges/registry.py` 的 `execution_open("okx")` **结构性恒为 False**
   （OKX 未声明 `adapter_execution_flag`）——也就是说**不存在** `ASTRA_OKX_EXECUTION`
   这类开关，经适配器下单的路径不开闸；不要把「没有开关」误读成「默认放行」。

## 4. 沙盒 / 实盘档案

- **demo 档不是独立域名**：仍是 `https://www.okx.com`，靠请求头
  `x-simulated-trading: 1` 表示模拟盘（`astra_backend/exchanges/env_profiles.py` 的
  `simulated_trading` 位）。因此**不要**用「换域名」的思路理解 OKX 沙盒。
- **demo 与 live 必须各自创建 API Key**（两个独立三元组），不能共用一个 Key 切档位。
- 初始验证固定用 `ASTRA_OKX_ENV=demo`，确认只读快照与小额链路正常后再切 `live`。
- 公共行情的主备域名在适配器内部（`www.okx.com` → `aws.okx.com`），属只读面。

## 5. 最小下单单位与取整方向

- 数量以**张**为单位；名义额 = 张数 × `ctVal` × 价格。
- 价格与数量按交易所规格 `tickSz` / `lotSz` **向下取整**，换算名义额**永不超出**目标；
  取整的代价是可能更常低于最小张数而被拒 —— **少下单，不超买**。
- 推不出合法张数（含低于 `minSz`）⇒ **拒单/跳过并说明原因**，绝不静默改成 1 张放大仓位。
- 语义与门禁锚点见 `docs/FAILURE_SEMANTICS.md` 的「下单量换算的方向」「杠杆夹取与张数推导的顺序契约」两条。

## 6. 保护腿（止盈 / 止损）

- 入场腿用 `attachAlgoOrds` **原子附带** TP/SL；云端棘轮改单走 OKX 算法单接口。
- ⚠️ **HTTP 200 ≠ 受保护**：附带算法单在普通订单完全成交后才提交，回执里的
  `failCode` / `failReason` 必须回读核验（账户 / 合约 / 方向 / 数量 / 触发值），
  核验 helper 为 `astra_backend/okx_trade_service.py` 的 `verify_attached_protection`。
- 触发价类型**显式发送 `mark`**（标记价触发），不依赖交易所默认值；`last` / `index`
  可显式覆盖。展示口径分四态：`mark` / `last` / `index` / `unknown`，**读不到就报「未上报」**。
- 门禁：`tests/venues/test_okx_trigger_price_type_semantics.py`。

## 7. 数据健康度

每 15 分钟决策周期自动落盘取数健康（成功币数 / 失败原因 / 延迟），
后台同一卡片实时展示，原始数据在 `data/venue_health.json`。
健康文件缺失或损坏时回退静态顺序，**不把「读不到」当成「很健康」**。

## 8. 历史台账数据兼容

`data/trading_ledger.json` 里的历史成交行属于历史事实：

- **只读保留、不重写、不删除、不伪造**；
- 统计与展示必须按历史行如实计入；
- 历史行的必要字段缺失时按「不可判定」处理，而不是当 0 —— 读不到 ≠ 没有。

## 9. 失败语义

所有「读不到 / 不可判定 / 部分失败」时的倒向（保留 / 不做 / 披露 / 吼 / 防）见
`docs/FAILURE_SEMANTICS.md`：本页只讲**接什么、怎么接**，那页讲**接不上时往哪边倒**。
