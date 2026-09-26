"""委员会子系统。

结构优化阶段 2（B5）：把 astra_backend/council_manager.py 的花名册/辩论引擎拆开。
**关键约束**：council_manager 是测试注入接缝 —— 测试直接赋值
cm.COUNCIL_CONFIG_FILE / cm.DATA_DIR / cm._LEGACY_PRESET_PROMPT_HASHES，且
tests/core/test_beijing_time_producers.py 的 isolated() 按 AST 从该文件取
save_council_config / export_council_config / _backup_council_config。
因此配置侧留在门面，只有辩论引擎（不读那些常量）迁出。

## 模块清单

| 模块 | 内容 |
|---|---|
| `debate.py` | 辩论引擎：单席位调用、互评、提示词渲染、整场辩论编排 |
| `policy.py` | 常量与预设模板（共识模式、超时下限、`DEFAULT_PRESET_TEMPLATES`） |
| `presets.py` / `roster.py` | 预设与花名册的纯数据/纯计算部件 |
| `role_normalizer.py` | CIO 终审输出的 `adopted_role` 归一化（纯函数，无 I/O） |

## 抽取约定

- 子模块**不得** import `council_manager`（它是测试注入接缝）；
- 需要 `roles` / `trader_keys` / `datetime` 等一律**调用方传入**；
- 只搬纯计算，不搬副作用（I/O、`print`、全局状态留在门面）。

> ⚠️ 委员会路径当前在生产中**未启用**（`data/council_config.json` 的
> `enabled=false`），故本子包的改动**没有实盘流量覆盖** ——
> 验证只能靠与搬走前实现的差分和等价测试，不能声称"已被实盘验证"。
"""
