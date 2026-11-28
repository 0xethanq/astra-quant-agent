"""AstraQuant 策略运维 Copilot Agent（L4 子包）。

## 模块清单

| 模块 | 职责 |
|---|---|
| `config.py` | Agent 专属模型与推理配置读写（默认 `auto` 跟随交易主脑） |
| `store.py` | SQLite WAL 多会话、消息轨迹与变更提案持久化 |
| `llm_stream.py` | 三协议（OpenAI Chat / Responses / Claude Messages）SSE 流式与 Tool Calling / ReAct 降级 |
| `tools_read.py` | 全只读诊断与策略透视工具 + 指挥台实时状态摘要聚合 |
| `tools_verify.py` | 改动前验证演练工具（实景快照决策预演 + 历史 K 线风控回测对比） |
| `tools_write.py` | 写操作提案构造与强校验（不直接落盘，统一产出结构化 Diff 提案条目） |
| `proposals.py` | 提案审批落地引擎（前置自动拍策略快照、逐项/整包原子写入、二次确认短语校验、审计记账） |
| `engine.py` | Agent 对话编排主循环（SSE 事件流产出、多轮工具调用、提案收集落库） |
"""
from __future__ import annotations
