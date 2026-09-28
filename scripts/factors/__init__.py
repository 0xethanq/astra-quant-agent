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
| `defaults.py` | `build_default_factors(inst_id, name)` —— 六 Pillar 的完整默认结构（95 行字面量） | 无（除 `time.time()`） |
| `scoring.py` | `score_composite_alpha(factors)` —— 八项加权打分（-100~+100）与信号建议 | **无**（只读入参 `factors`；不 import 任何取数模块） |
| `candles_15m.py` | `derive_candle_series` / `compute_15m_indicators` —— 15M 的 ATR/RSI/VWAP 乖离/量比/OBV + Pillar 6 | `safe_float`、`calculate_calculus`（微积分引擎）由调用方传入 |
| `smart_money.py` | `fetch_smart_money_for_symbol` / `fetch_smart_money_pool` —— 大户多空比与聪明钱资金流（OKX Rubik 单源） | 无 |

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
