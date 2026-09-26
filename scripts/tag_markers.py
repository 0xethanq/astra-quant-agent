"""交易所挂单的**归属标记**：本系统写的新标记，以及改名前落在交易所上的旧标记。

## 为什么旧标记必须继续被认（这**不是**"旧配置兼容"）

2026-09-27 把内部代号 `r20` 全量改名为 `astra`。归属标记的物理位置是：

- **OKX / Gate**：原生条件单的 `initial.text`（形如 `t-<marker>sl…` / `t-<marker>tp…`）；
- **Binance**：`type` / `raw.orderType` 里的类型名。

改名那一刻，交易所上可能仍挂着**改名前创建**的保护腿，它们的 text 是 `t-r20sl…`。
若只认新标记，这些腿会被判成"不是我们的"，后果是**静默削弱已有仓位的保护**：

- 云端棘轮不再给它们续期 / 收紧止损；
- 孤儿清理不再撤它们 ⇒ 残留脏单会干扰后续整仓平仓。

两者都**不会立刻下错单**，所以不会有告警 —— 正因为失败是静默的，才必须显式处理。

## 与「硬切」的关系

`r20 → astra` 对**配置契约**是硬切：`R20_*` 环境变量不再被读取，用户必须改自己的 `.env`。
本模块处理的是**已经落在别人服务器上的历史数据**，两者是两件事 ——
配置可以要求用户改，交易所上的单子改不了。

## 何时可以删

当所有"改名前开的仓位"都已平掉之后（覆盖最长持仓时效 + 保护单续期窗口即可）。
判据：交易所上再查不到带 `t-r20sl*` / `t-r20tp*` 标记的腿。
"""
from __future__ import annotations

#: 旧标记 → 新标记（**只做记号级替换**，不做任何语义改写）
LEGACY_MARKER_MAP = (
    ("r20sl", "astrasl"),
    ("r20tp", "astratp"),
    ("r20close", "astraclose"),
)


def normalize_legacy_markers(text: str) -> str:
    """把文本里的**旧归属标记**归一成新标记，让下游的标记判定只需认一套。

    ⚠️ 大小写都替换：`_row_text()` 这类调用方会先 `.lower()`，但
    `cloud_protection` 在同一表达式里既用 `text.lower()` 又用 `text.upper()`
    （`"STOP" in text.upper()`），两种形态都得覆盖。

    未命中时**原样返回**（包括非 str 会被 `str()` 兜住），保证这是纯函数、无副作用。
    """
    out = "" if text is None else str(text)
    for old, new in LEGACY_MARKER_MAP:
        if old in out:
            out = out.replace(old, new)
        upper_old, upper_new = old.upper(), new.upper()
        if upper_old in out:
            out = out.replace(upper_old, upper_new)
    return out
