"""`scripts/factors/` 抽取子包（结构优化阶段 4·B3）。

`scripts/factor_library.py` 的 `compute_instrument_factors` 是 438 行的单函数，
`scripts/factors/` 用**门面保留式抽取**把其中不依赖模块状态的纯结构搬出来：
门面保留同名壳与全部被测试钉住的字面量，只搬"可独立成立"的部分。

## 与 `scripts/trader/` / `scripts/brain/` 的约定一致

- 子模块**不得** import 门面（避免循环导入）；
- 门面里的名字会被测试 `patch.object`，故子模块不得在 import 期绑定门面名字 ——
  需要的一律**调用期注入**（见 `scripts/factor_library.py` 里
  `compute_instrument_factors` 调用 `build_default_factors` 的方式）；
- 导入用**绝对路径** `scripts.factors.*`（与仓里 `scripts.` 顶层包一致）。

## 模块清单

| 模块 | 内容 | 注入面 |
|---|---|---|
| `defaults.py` | `build_default_factors(inst_id, name)` —— 7 梯队的完整默认结构（原 3 个退役数理 Pillar 已整体剥离） | 无（除 `time.time()`） |
| `scoring.py` | `score_composite_alpha(factors)` —— **六项 7 梯队加权打分**（-100~+100）与信号建议 | **无**（只读入参 `factors`；不 import 任何取数模块） |
| `candles_15m.py` | `derive_candle_series` / `compute_15m_indicators` / `mark_15m_missing` —— 15M 的 ATR/RSI/VWAP 乖离/量比/OBV（**Pillar 6 微积分段已退场**） | 仅 `safe_float`（2026-10 起注入面收缩为零） |
| `okx_quant_factors.py` | **7 梯队量化因子引擎**：T0 衍生品／T0.5 订单流／T1 盘口／T1.5 期权／T2 期限／T3 筹码／T4 动量 —— 纯计算 + 带 TTL 缓存的公开 REST 取数 + `apply_*_tier` 装配 | 无（自持 `_public_get` 与 `safe_float`；取数与装配都可单测） |
| `smart_money.py` | `fetch_smart_money_for_symbol` / `fetch_smart_money_pool` —— 大户多空比与聪明钱资金流（OKX Rubik 单源） | 无 |

### ⚠️ 数理系统退场与剥离（2026-10）

`calculus_dynamics` / `definite_integrals` / `probability_theory` 三个 Pillar
已于 2026-10 **彻底从代码层剥离**（连占位键位也不再产出）：
不再计算、不进提示词、不参与打分与信号。`candles_15m.py` 的 Pillar 6
整段摘除，`scoring.py` 的第五项由「微积分 ±1.5」换成「7 梯队因子共振 ±1.5」。

### ⚠️ `candles_15m.py` 的取数**故意留在门面**

`fetch_candles(...)` 留在 `scripts/factor_library.py`，`candles_15m` 只吃
**已经取回的** `raw_candles`。这样：

- 门面对 `fetch_candles` 的 `patch.object` 缝继续生效（零新增注入面）；
- 子模块可以用构造 K 线纯函数式测试，不需要 mock。

**新加数值段时请沿用这条**：取数留在门面，计算搬进来。

## 三条铁律（与 `scripts/trader/__init__.py` 同）

1. **原样搬运**：搬进来的逻辑不得"顺手优化"；改动一律发生在门面那一侧，且要写清原因。
2. **不绑门面名字**：`patch.object(门面, "..."）` 必须继续生效 —— 意味着子模块
   不能 `from factor_library import fetch_candles` 这类 import 期绑定。
3. **形状即接口**：默认结构里的字段名、初值、占位符都是前端与主脑的取值契约，
   "看起来不统一"的值（比率 1.0 / 百分位 50.0 / 幅度 0.0）各有含义，不得归一。
"""
