"""LLM 子系统。

结构优化阶段 2（B4）：把 astra_backend/llm_manager.py 按职责拆开。
**关键约束**：llm_manager 是测试注入接缝（测试 patch 其模块常量、
isolated() 按文件取同名函数），因此只有"不引用模块常量、且不调用读常量的
兄弟函数"的部分才整块迁出；其余留在 llm_manager 或改用薄壳+核心手法。

模块清单
--------
| 模块 | 职责 |
|---|---|
| `policy.py` | 不可变策略常量（重试/回退预算、支持的 API 格式、默认供应商） |
| `capabilities.py` | 模型能力/思考类型/API 格式探测 |
| `providers.py` | 端点拼装与供应商辅助 |
| `transport.py` | 三协议请求构造与响应解析（含缓存/截断指标） |
| `call.py` | 统一执行器（重试、回退、连接自检） |
| `failover.py` | 回退事件记录 |
| `store.py` | 配置读写、激活、模型统计 |
| `store_normalize.py` | 配置规范化与脱敏 |
| `store_upsert.py` | 供应商/模型写入辅助 |
| `env_sync.py` | 与 `.env` 的双向同步 |
| `util.py` | 通用小工具 |
| `model_health.py` | 模型条目**结构自检**（密钥/供应商/格式/路径；只判结构，不据运行态判死） |
"""
