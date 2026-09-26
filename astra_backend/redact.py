"""凭证脱敏的**单一事实源**（结构优化阶段 4·B3 第四十九刀）。

## 为什么新增这个模块

跨文件重复扫描发现两个**逐字相同**的凭证脱敏函数：

| 位置 | 名字 |
|---|---|
| `astra_backend/settings_store.py` L65 | `mask(value, visible=4)` |
| `astra_backend/llm/util.py` L32 | `mask_secret(value, visible=4)` |

函数体各 6 行、**逐字节相同**，且**签名一致**。行为对拍 50 组用例（10 种输入
× 5 种 `visible`）**零差异**。

**此刻不是 bug**，但它是**安全敏感**的漂移风险：两处都决定"一个密钥有多少字符
可以露出"。任何一处被改动（比如把 `'*' * 8` 改成 `'*' * 4` 以免遮住尾部，
或把 `visible * 2` 的边界改掉），另一处不会跟着改 —— 于是
**后台设置页**与**LLM 配置页**会对密钥做**不同强度**的脱敏，
弱的那一侧成为泄露面。

本仓对这类问题已有命名（「孪生漂移」）与既有修法：见
`scripts/ai_factor_trader.py:714` 的审计注释
（「…只进了模块版，而活路径走本函数（孪生漂移），等于闸装了死副本。
现从模块导入同一实现，双进程单一事实源」）。

## ⚠️ 本模块只依赖标准库

刻意**不** import `settings_store`（它带 `config` / `file_locks`），
也**不** import `llm`。这样两个消费方都能安全依赖它，
不会引入新的模块耦合、也不改变任何导入图方向。

## ⚠️ 脱敏语义（勿"顺手"改）

- 空值 → `""`（**不是** `"*" * 0` 之外的任何东西，调用方据此判"没有密钥"）；
- `len(value) <= visible * 2` → **全星**（短密钥整体遮住，不泄露长度以外信息）；
- 否则 → 前 `visible` 位 + **固定 8 个星** + 后 `visible` 位。

中间恒为 **8 个星**（不随密钥长度变化）是有意的：给出"被截断"的视觉信号，
同时不泄露密钥长度。`is_masked()` 正是靠"含连续 8 个星"来识别脱敏产物，
故**这个 8 与 `is_masked` 是一对契约**，改一处必须改另一处。
"""

from __future__ import annotations

__all__ = ["mask", "MASK_STARS"]

#: 脱敏串中段的固定星号数 —— 与 `settings_store.is_masked()` 的识别规则**成对**
MASK_STARS = 8


def mask(value: str, visible: int = 4) -> str:
    """凭证脱敏：保留首尾各 `visible` 位，中段固定 `MASK_STARS` 个星。

    ⚠️ 语义与边界见模块文档；`astra_backend.settings_store.mask` 与
    `astra_backend.llm.util.mask_secret` 都指到本函数（同一个对象）。
    """
    if not value:
        return ""
    if len(value) <= visible * 2:
        return "*" * len(value)
    return f"{value[:visible]}{'*' * MASK_STARS}{value[-visible:]}"
