# 文档索引

> 本目录是**参考资料**，不是入门读物。第一次接触请先读仓库根的 [`README.md`](../README.md)；
> 要动手改代码再看 [`STRUCTURE_OVERVIEW.md`](STRUCTURE_OVERVIEW.md)。

---

## 该读哪一份？

| 你的问题 | 读这份 | 性质 |
|---|---|---|
| 「这系统怎么跑起来？」 | [仓库根 README](../README.md) | 入门 |
| 「代码怎么分层、东西都放哪？」 | [**STRUCTURE_OVERVIEW.md**](STRUCTURE_OVERVIEW.md) | **结构地图（先看这个）** |
| 「提示词怎么写？插槽有哪些？」 | [**PROMPT_GUIDE.md**](PROMPT_GUIDE.md) | 编写指南 |
| 「某处读数据失败时该往哪边倒？」 | [FAILURE_SEMANTICS.md](FAILURE_SEMANTICS.md) | 行为契约（参考表） |
| 「时间戳到底按哪个时区、什么格式？」 | [BEIJING_TIME_CONTRACT.md](BEIJING_TIME_CONTRACT.md) | 契约 |
| 「支持哪些交易所、能力边界在哪？」 | [exchange_support_matrix.md](exchange_support_matrix.md) | 契约 |
| 「怎么部署 / 应急怎么恢复？」 | [`../STANDALONE.md`](../STANDALONE.md)、[`../RECOVERY_GUIDE.md`](../RECOVERY_GUIDE.md) | 运维 |
| 「后端 / 脚本 / 前端各自怎么组织？」 | [`../astra_backend/README.md`](../astra_backend/README.md)、[`../scripts/README.md`](../scripts/README.md)、[`../frontend/src/components/admin/README.md`](../frontend/src/components/admin/README.md) | 分层详解 |
| 「监控指标怎么接？」 | [`../deploy/observability/README.md`](../deploy/observability/README.md) | 运维 |

---

## 本目录各文档的定位

### [STRUCTURE_OVERVIEW.md](STRUCTURE_OVERVIEW.md) — 结构地图
分层架构图、各域目录职责与模块数、提示词与配置的数据流、以及**改动前必读的六条硬约束**。
接手开发从这里开始。

### [PROMPT_GUIDE.md](PROMPT_GUIDE.md) — 提示词编写指南
提示词体系的事实源（正文只存 `data/prompt_library.json`，代码只留只读 JSON Schema）、
四条管线与模块来源、实时语义插槽字典、出厂策略口径。

### [FAILURE_SEMANTICS.md](FAILURE_SEMANTICS.md) — 失败语义手册
本仓最核心的一条纪律：**分清「没有」与「读不到」**。逐条列出"输入读不到时该往哪边倒"，
每行都绑定代码锚点与门禁用例 —— 由 `tests/audit/test_failure_semantics_doc.py` 校验，
悄悄改成"静默忽略"会当场翻红。**这是参考表，不必通读**；改到相关代码时按需查。

### [BEIJING_TIME_CONTRACT.md](BEIJING_TIME_CONTRACT.md) — 时间契约
全链路时间口径与格式化约定，避免"本地时区 vs 交易所时区"这类静默错位。

### [exchange_support_matrix.md](exchange_support_matrix.md) — 交易所接入
本系统是 **OKX 专用**：单一场所、单一凭证、单一签名路径。文中列明能力边界，
并与 `astra_backend/exchanges/okx.py` 的 `ExchangeCapabilities` 保持同步。

---

## 一个提醒

本仓的文档受门禁保护：被引用的源码路径必须真实存在且已提交
（`tests/audit/test_doc_paths_are_committed.py`），模块必须登记进对应 README
（`tests/audit/test_directory_docs_current.py`），数字必须与实测同量级
（`tests/core/test_readme_baseline_numbers.py`）。

**因此：不要凭记忆往文档里写路径或数字，先确认它们在仓库里存在。**
