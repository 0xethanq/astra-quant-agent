"""LLM 客户端凭据解析 —— **单一事实源**（结构优化阶段 4·B3 第四十六刀）。

## ⚠️ 为什么放在 `scripts/` 而不是 `astra_backend/llm/`

我第一版把它放进了 `astra_backend/llm/credentials.py`，被
`tests/test_llm_seam_discipline.py::test_core_modules_do_not_import_facade`
**当场拒绝**：

    credentials.py:67 from astra_backend.llm_manager import ...

该闸的铁律是「`astra_backend/llm/` 下的核心模块**不得**反向 import 门面
`llm_manager`（会成环；应为薄壳注入）」。而本函数的**业务本身**就是
"先问 `llm_manager.get_active_llm_runtime()`"，天然违反该铁律。

既然两个调用方都是 `scripts/` 下的脚本，正确位置就是 **`scripts/` 同层**，
而不是 `astra_backend/llm/` 包内。**闸抓对了，是我的落点错了。**

## 为什么新增这个模块

跨文件重复扫描发现 `get_cpa_client_config()` 在**两个独立脚本**里
**逐字相同**地存在（各 15 行）：

| 文件 | 行 |
|---|---|
| `scripts/ai_brain_trader.py` | 239 |
| `scripts/self_improvement_engine.py` | 125 |

两份**完全相同**（逐字对拍，`== True`），所以此刻不是 bug；
但它是一条**必然漂移**的复制：两处都从 `astra_backend.llm_manager` 取
"当前激活模型"再回落到环境变量，任何一处改了回落顺序、或加了新环境变量，
另一处不会跟着改 —— 两个进程就会用**不同的凭据**说话。

本仓已有同类教训与修法：`scripts/ai_factor_trader.py:714` 的注释写着

    审计回马枪④2(2026-09-13)：上轮 A2 的「同步失败所→禁开仓」加固只进了
    astra_backend.execution.circuit_breaker 模块版，而活路径走本函数（孪生漂移），
    等于闸装了死副本。现从模块导入同一实现，双进程单一事实源。

本模块按同一思路消除**这一处**孪生漂移。

## ⚠️ 为什么需要 `standalone_settings` 形参（调用时注入）

原实现读的是**各自模块的全局** `standalone_settings`
（两个文件都在 `try: from astra_backend.config import settings as
standalone_settings` / `except: = None`）。

按本仓铁律（见 `scripts/trader/signals.py` 的模块文档），**子模块不得在
import 期绑定门面全局**：门面的全局会被测试 patch / 原地 reload，
import 期烘焙的副本**不会**跟着刷新。故这里把它做成**显式形参**，
由两个调用方在**调用时**传入各自的全局。

## ⚠️ 顺序是业务语义，不是实现细节

1. **先问运行时激活模型**（`get_active_llm_runtime()`），它来自 LLM 配置库，
   是运维在后台改的；
2. 只有在**取不到或抛异常**时，才回落到 `standalone_settings`；
3. 最后才回落到环境变量，并按 `LLM_BASE_URL` → `OPENAI_BASE_URL`、
   `LLM_API_KEY` → `OPENAI_API_KEY`、默认 `https://api.openai.com/v1` 的顺序。

**异常被静默吞掉（`except Exception: pass`）是有意的**：后台配置库不可用时
不应让交易进程起不来，回落链会把这条兜住。**勿"顺手"加日志或改成抛出。**
"""

from __future__ import annotations

import os
from typing import Any, Optional, Tuple

__all__ = ["get_cpa_client_config"]


def get_cpa_client_config(standalone_settings: Optional[Any] = None) -> Tuple[str, str]:
    """解析 LLM base_url 与 api_key。

    回落顺序（**业务语义，勿改**）：
    运行时激活模型 → `standalone_settings` → 环境变量 → OpenAI 默认。

    `standalone_settings` 由调用方在**调用时**传入自己模块的全局
    （勿在本模块 import 期绑定任何门面全局）。
    """
    try:
        from astra_backend.llm_manager import get_active_llm_runtime
        active_llm = get_active_llm_runtime()
        if active_llm.get("base_url"):
            return active_llm["base_url"], active_llm.get("api_key", "")
    except Exception:
        pass
    if standalone_settings:
        return standalone_settings.llm_base_url, standalone_settings.llm_api_key
    return (
        os.getenv("LLM_BASE_URL") or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1",
        os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "",
    )
