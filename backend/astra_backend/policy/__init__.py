"""策略快照子系统。

结构优化阶段 2（B6）：把 astra_backend/policy_snapshot.py 的指纹计算、归档读写、
恢复流程拆开。**关键约束**：tests/core/test_beijing_time_producers.py 的 isolated()
按 AST 从 policy_snapshot.py 取 `_rebuild_index_from_archives` 与
`archive_current_policy`，且 PRODUCER_PATHS 要求该文件仍含 ≥1 个 datetime
isoformat/strftime 表达式 —— 这两个函数**必须留在门面**。
与本目录其余文件不同，门面同时是 config_sandbox 的重定向目标（它遍历 sys.modules
里所有 astra_backend.* 模块，重定向指向 data/ 的大写 str/Path 属性，故子模块只要被
门面导入即自动纳入沙箱）。
"""
