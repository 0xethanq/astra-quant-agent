"""多所选所的**选所质量**域（结构优化阶段 4·B3 第四十三刀起）。

门面仍是单文件 `astra_backend/venue_router.py`（`RouteDecision` / `RouterConfig` /
`route_signal` / `split_allocation` / `_apply_hysteresis` / `_coerce_config` /
`_now_epoch` / `_stage_of`）。

## 模块清单

| 模块 | 职责 | 注入面 |
|---|---|---|
| `selection.py` | **选所质量**：硬筛淘汰（`_hard_filters`）/ 成本评分（`_score`）/ 跨进程确定的均衡选所（`_balanced_pick`）/ ISO 时间解析（`_parse_iso_utc`） | 无（纯计算；`budget_view` 由调用方传入，无网络） |

## `venue_router.py` 里的两件事

它此前把**两件不同的事**放在一起：

1. **选所质量** —— 哪些所能用、哪个更便宜、同价怎么均衡 → 本子包；
2. **分配** —— 拆单（`split_allocation`）、滞回防抖（`_apply_hysteresis`）、
   编排入口（`route_signal`）→ 仍留门面。

## 约定

1. **门面必须再导出**被搬走的名字（`_hard_filters` / `_score` / `_balanced_pick`
   / `_parse_iso_utc` / `_LISTING_FAILOPEN_MARK`）——
   `tests/audit/test_cross_process_hash_determinism.py` 在**子进程**里
   `from astra_backend.venue_router import _balanced_pick`。
2. **`_parse_iso_utc` 必须住在 `selection.py`**：若留在门面由本子包反向导入，
   会形成「门面 → selection → 门面」的**循环导入**（实测 ImportError）。
   这是**模块图**约束，锚点体检查不出来。
3. **本子包零真实网络**：合约代码对齐只走纯元数据翻译
   （`native_symbol_pure`），**绝不**实例化适配器 ——
   实例化会触发沙盒档域名探测出网。
"""
