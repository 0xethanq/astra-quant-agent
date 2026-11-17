"""OKX 入场闸门：跨所同向敞口 / 持仓模式体检。

## 为什么单独成件（2026-09-28 审计）

闸门此前被**实现了两遍**，而只有一遍接了 OKX：

- 多所执行入口（`open_protected_position`，已随多所执行面整体移除）里有一套；
- OKX 直签路径（`okx_rest.place_order`，不经该入口）**一个都没有**。

于是出现最坏的一种不对称：`check_total_exposure` 的统计口径**明确把 OKX 持仓算进去**
—— 也就是说

    **OKX 的仓占着上限，而 OKX 的下单不查上限。**

（本仓已收口为 OKX 专用；统计集合随之退化为单所，逻辑不变。）

## 本件的定位：策略单源，IO 全注入

判据收在这里，IO（持仓、模式探测结果）全部由调用方备好 ——
与 `risk_gates.py` 同一风格（纯函数、零 import 期绑定）。

| 阶段 | 判据 |
|---|---|
| `exposure` | 同向名义额合计（含本单）> 上限 → 拒（**拒**不是夹） |
| `position_mode` | 持仓模式测不出、或不在**已核验**子集 → 拒（本系统永不自动切换账户模式） |

## 阶段顺序

`exposure → position_mode`。
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence

__all__ = ["venue_entry_gate"]


def _resolve(value: Any) -> Any:
    """惰性探针契约：值或零参可调用。

    惰性是有意的：本仓明确要求「闸门拒单时**不产生额外网络调用**」——
    若在进闸门前就把模式探针跑掉，静态拒单也会去触网。
    """
    return value() if callable(value) else value


def venue_entry_gate(
    *,
    venue: str,
    asset: str,
    exposure_fail: Optional[Dict[str, Any]] = None,
    position_mode: Any = None,
    declared_modes: Sequence[str] = (),
    entry_ready_modes: Sequence[str] = (),
    mode_checked: bool = False,
    mode_hazard: str = "",
    mode_hazards: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """共用的入场闸门。`None` = 全部通过；否则返回拒单载荷。

    ### 入参（全部由调用方备好 —— 本函数零 IO、零 import 期绑定）

    - `exposure_fail`：调用方用 `risk_gates.check_total_exposure(...)` **算好的结果**
      （已含 `positions_reader` 与 fail-closed 语义）。传 `None` 表示无敞口问题。
      之所以把 IO 留在调用方：持仓读取是**多条网络路径 + fail-closed 抛错**，
      塞进纯函数会让"读不到"与"没有敞口"两种情形难以分辨。
    - `position_mode`：**可以是值，也可以是零参可调用**（惰性探针）。
    - `mode_checked`：调用方是否**真的实现了**只读模式探测。`False` ⇒ 跳过体检。
      这是刻意的不对称：适配器没实现 `detect_position_mode` 时，
      「声明了就体检、探测不到就拒」会**直接把该所新开仓全部停掉**。
    """
    # ① 同向敞口（**拒**不是夹；超限说明不该再开）
    if exposure_fail is not None:
        return exposure_fail

    # ② 持仓模式只读体检（本系统**永不自动切换**用户账户的持仓模式）
    if mode_checked:
        mode = str(_resolve(position_mode) or "unknown").strip().lower()
        declared = tuple(str(m) for m in (declared_modes or ()))
        ready = tuple(str(m) for m in (entry_ready_modes or ()))
        if mode not in declared:
            return {"stage": "position_mode",
                    "detail": (f"{asset} 无法只读确认持仓模式（探测={mode}，该所声明支持="
                               f"{'/'.join(declared)}）——禁新开仓；"
                               f"本系统不自动切换账户模式"),
                    "venue": venue, "position_mode": mode}
        if ready and mode not in ready:
            hazard = ((mode_hazards or {}).get(mode) or mode_hazard
                      or "该模式下单/保护腿载荷未核验")
            return {"stage": "position_mode",
                    "detail": (f"{asset} 账户持仓模式={mode}（{hazard}）——本系统仅在 "
                               f"{'/'.join(ready)} 下核验过下单与保护腿载荷，禁新开仓；"
                               "请在交易所侧改回受支持模式或人工处理"),
                    "venue": venue, "position_mode": mode}
    return None
