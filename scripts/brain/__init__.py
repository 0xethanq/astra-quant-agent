"""主脑脚本的抽取子包（结构优化阶段 4·B3 起）。

`scripts/ai_brain_trader.py` 是主脑主脚本（worker 每 15 分钟 respawn），
沿用交易员侧（`scripts/trader/`）同一套**门面保留式抽取**手法：

- 门面保留同名薄壳与全部被测试钉住的字面量；
- 被测试 patch 的全局（路径、行情函数、可替换依赖）一律**调用期注入**，
  绝不在子模块 import 期烘焙 —— 原因见 `astra_backend/README.md` §5 与
  `tests/risk_test_env.py::pin_baseline_risk_env()` 的重载名单；
- 新增模块进本子包，不再往门面堆。

## 模块清单

| 模块 | 内容 | 来源 |
|---|---|---|
| `packages.py` | `fetch_single_instrument_package` 单标的数据包装配（254 行） | 门面 L303-556 |
| `xvenue.py` | 跨所矩阵采集 / 场所健康度落盘 / 分歧标注与提示词证据行（231 行） | 门面 L446-676 |
| `decisions.py` | `validate_and_filter_decision` + `assemble_decision_cache` 决策校验与缓存装配（148 行） | 门面 L915-1062 |
| `cycle_parts.py` | `normalize_position_management` / `build_effective_prompt_text` / `build_history_record`（周期内纯组装，108 行） | 门面 `execute_batch_ai_brain_cycle` 内联段 |
| `prompt.py` | `construct_full_market_prompt` 全市场提示词装配（269 行，**注入面最宽：15 项**） | 门面 L654-922 |
| `runtime.py` | `capture_policy_snapshot`（策略快照冻结 + 派生 version/hash/summary，两级 import 兜底）；`resolve_llm_runtime`（环境变量 → `get_active_llm_runtime()` 覆盖，失败置 `execute_llm_request=None`）—— 两处 **in-out**：`policy_snapshot`、`api_key`/`base_url`（段内 `... or base_url` 会读旧值）（B3 第一百刀） | 门面 `execute_batch_ai_brain_cycle` 前置段 |
| `snapshots.py` | `update_factor_library_snapshot`（因子库自更新）/ `write_calculus_snapshot`（演算快照原子落盘）/ `write_prompt_snapshot`（实时提示词快照，Web 透明检视用）—— **三段皆纯副作用**（0 输出、0 return，失败仅告警）（B3 第九十九刀） | 门面 `execute_batch_ai_brain_cycle` 内联段（3/5/6 项同名注入） |
| `dispatch.py` | `dispatch_llm_and_persist_decisions` —— `execute_batch_ai_brain_cycle` **末尾 173 行**：LLM 请求派发 → 决策解析/校验 → 决策缓存·历史·持仓指令三份落盘（flock 包裹）→ 周期健康记录；段内两处 `return` 即函数终返，调用点 `return helper(...)` **直接透传**（B3 第九十八刀） | 门面 `execute_batch_ai_brain_cycle` 尾块（36 项同名注入） |
| `account_text.py` | `build_position_lines` 在途持仓文本 + `build_pending_order_lines` 在途挂单文本（**三态语义**：`None`=缺上下文 / `[]`=确定空仓 / 非空=逐条） | `prompt.py` 内联段 |

## 注入面速查（改这些前先看）

| 模块 | 需要在调用期注入的门面名 | 原因 |
|---|---|---|
| `packages.py` | `fetch_candles` / `fetch_single_indicator` | 门面重载后 import 期绑定会失配；且测试可能 patch 门面名 |
| `xvenue.py` | `get_adapter`（门面 `_get_xvenue_adapter`）/ `safe_float` / `atomic_write_json` / `venue_health_file` / `health`（门面 `_XV_HEALTH`） | 前四个都是既有测试缝；`_XV_HEALTH` 被 `tests/venues/test_xvenue_prompt.py:120` 直接断言，状态必须留在门面 |
| `decisions.py` | `data_dir`（门面 `DATA_DIR`）/ `max_leverage` / `min_leverage` / `safe_float` / `get_system_version_tag` / `validate` |
| `cycle_parts.py` | `safe_float`（只此一个） | 门面私有函数，且门面会被原地重载 |
| `prompt.py` | `safe_float` / `sl_atr_mult_for` / `xvenue_prompt_line` / `build_risk_budget_text` / `active_profile` / `apply_module_layout` / `system_version` / 3 个文件路径 / 5 个风控常量 / `_build_position_lines` / `_build_pending_order_lines`（后两个见下） | **风控常量必须调用期取**：`risk_constants` 改参后由门面重载刷新，子模块 import 期绑定会变成过期快照，提示词口径就与执行层漂移 | 前三个都是既有测试缝（`test_ai_health_sidecar`、`test_leverage_range_and_council`）；`validate` 的契约是 **4 个位置参数**，由门面 curry 进 `safe_float` |

**`xvenue.py` 是注入面最宽、`decisions.py` 是契约最容易写错的一块。**
改动它们前请先看对应的 `tests/test_brain_*_extraction.py`：那里的 `InjectionContractTest`
就是为"搬走时把测试缝一起搬没了"这种情况写的。

> 实战教训（`decisions.py`）：`assemble_decision_cache` 调用注入的 `validate` 时
> 少传了 `safe_float`，**全量测试仍全绿** —— 因为门面壳把 `safe_float` 填好了，
> 只有"注入契约"测试（哨兵函数）才抓得到。跨文件互调的参数形状必须显式钉住。
"""
