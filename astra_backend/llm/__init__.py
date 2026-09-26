"""LLM 子系统。

结构优化阶段 2（B4）：把 astra_backend/llm_manager.py 按职责拆开。
**关键约束**：llm_manager 是测试注入接缝（测试 patch 其模块常量、
isolated() 按文件取同名函数），因此只有"不引用模块常量、且不调用读常量的
兄弟函数"的部分才整块迁出；其余留在 llm_manager 或改用薄壳+核心手法。
"""
