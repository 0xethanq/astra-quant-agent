"""三所共用的**入场闸门**：跨所敞口 / 池门禁 / 持仓模式体检。

## 为什么单独成件（2026-09-28 审计）

闸门此前被**实现了两遍**，而只有一遍接了 OKX：

- `execution_router.open_protected_position`（binance/Gate 的执行入口）里有
  池门禁（`dry_run` / `assets` / `max_open` / `min_confidence`）、跨所同向敞口、
  持仓模式体检；
- OKX 直签路径（`okx_rest.place_order`，不经 router）**一个都没有**。

于是出现最坏的一种不对称：`check_total_exposure` 的统计口径**明确把 OKX 持仓算进去**
（`execution_router._exposure_venues` 为此专门写过一段：`execution_open("okx")` 恒 False，
按开闸判会把持仓最多的 OKX 整个漏掉）—— 也就是说

    **OKX 的仓占着上限，而 OKX 的下单不查上限。**

加重情节：提示词对主脑写「跨所同向敞口上限 … 超出执行层拒开」
（`ai_brain_trader.py` 的 `build_risk_budget_lines`）—— 走到 OKX 时这句话是**空头支票**。
历史上该闸门真的拦过单（2026-09-25 日志：GATE「将达 13630990U，超上限 3000U」），
那时同标的同方向的 OKX 单会**静默通过**。

## 本件的定位：策略单源，IO 全注入

判据收在这里，IO（池配置、持仓、模式探测结果）全部由调用方备好 ——
与 `risk_gates.py` 同一风格（纯函数、零 import 期绑定），便于对**三所逐一套用同一组断言**。

| 阶段 | 判据 |
|---|---|
| `exposure` | 跨所**同向**名义额合计（含本单）> 上限 → 拒（**拒**不是夹） |
| `venue_dry_run` | 该所池 `dry_run=true` → 拒（本地演算不发单） |
| `venue_pool` | 准入币种清单 / `min_confidence` / `max_open` 三道 → 拒 |
| `position_mode` | 持仓模式测不出、或不在**已核验**子集 → 拒（本系统永不自动切换账户模式） |

两条执行路径共用同一个函数，故将来任何新增闸门**自动覆盖三所**；
`tests/audit/test_three_venue_gate_parity.py` 钉住「策略只实现一次、两个调用点都在」。

## 阶段顺序

`exposure → dry_run → assets → min_confidence → max_open → position_mode`。

这是 binance/Gate 既有路径的相对次序（敞口在 router 里本就在池门禁之前）。
抽取时 `max_open` 与 `position_mode` 从更靠后的位置**前移**到本序列 —— 这是有意的：
判据**只拒不放**，故对「该拒的单」结果不变，只有**同时多处不满足时的报错优先级**会变
（例如「已达 max_open 且合约规格取不到」以前报 `specs`、现在报 `venue_pool`，
两者都是拒单）。
"""

from __future__ import annotations

import math
from typing import Any, Callable, Dict, Optional, Sequence

__all__ = ["venue_entry_gate"]


def _num(value: Any, default: float = 0.0) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return default
    return out if math.isfinite(out) else default


def venue_entry_gate(
    *,
    venue: str,
    asset: str,
    confidence: Any = 0.0,
    pool: Optional[Dict[str, Any]] = None,
    exposure_cap: float = 0.0,
    exposure_fail: Optional[Dict[str, Any]] = None,
    open_count: Any = None,
    position_mode: Any = None,
    declared_modes: Sequence[str] = (),
    entry_ready_modes: Sequence[str] = (),
    mode_checked: bool = False,
    mode_hazard: str = "",
    mode_hazards: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """三所共用的入场闸门。`None` = 全部通过；否则返回拒单载荷。

    ### 入参（全部由调用方备好 —— 本函数零 IO、零 import 期绑定）

    - `exposure_fail`：调用方用 `risk_gates.check_total_exposure(...)` **算好的结果**
      （已含 `positions_reader` 与 fail-closed 语义）。传 `None` 表示无敞口问题。
      之所以把 IO 留在调用方：跨所持仓读取是**多条网络路径 + fail-closed 抛错**，
      塞进纯函数会让"读不到"与"没有敞口"两种情形难以分辨。
    - `open_count` / `position_mode`：**可以是值，也可以是零参可调用**（惰性探针）。
      惰性是有意的契约：本仓明确要求「闸门拒单时**不产生额外网络调用**」
      （见 execution_router 里"闸门停用时不产生任何额外网络调用"的注释）。
      若在进闸门前就把持仓/模式探针跑掉，`dry_run=true` 这种**纯静态**拒单
      也会去触网 —— `tests/core/test_execution_router.py::test_dry_run_blocks_the_send`
      正是钉这条（断言 `ad.calls == []`）。故静态阶段在前，探针只在走到该阶段时才调。
    - `open_count` 为 `None` ⇒ **未探针** ⇒ 跳过 `max_open`（不把"没探"渲染成"0 笔"）。
    - `mode_checked`：调用方是否**真的实现了**只读模式探测。`False` ⇒ 跳过体检。
      这是刻意的不对称：适配器没实现 `detect_position_mode` 时，
      「声明了就体检、探测不到就拒」会**直接把该所新开仓全部停掉**
      （币安 DEMO 实测踩过的自伤，见 execution_router 的长注释）。
    """
    venue_tag = str(venue or "").upper()
    _resolve = (lambda v: v() if callable(v) else v)

    # ① 跨所同向敞口（**拒**不是夹；超限说明不该再开）
    if exposure_fail is not None:
        return exposure_fail

    # ②③④⑤ 池门禁：dry_run / 准入币种 / 置信度 / 持仓笔数
    if pool:
        if pool.get("dry_run"):
            return {"stage": "venue_dry_run",
                    "detail": (f"{venue_tag} 池配置 dry_run=true（本地演算不发单）；"
                               f"如需真实发送请改 data/venue_routing.json 并确认执行开关"),
                    "venue": venue}
        pool_assets = pool.get("assets")
        if pool_assets is not None:
            # `None` = 该所**未配置**准入清单 ⇒ 不设限（如 OKX：它此前根本没有池段）。
            # `[]` = **显式**配成空 ⇒ 停发。两态必须区分，见 `_normalize_assets`。
            pool_assets = [str(a).upper() for a in pool_assets]
            if not pool_assets:
                return {"stage": "venue_pool",
                        "detail": f"{venue_tag} 准入币种清单为空（空池=不发单）",
                        "venue": venue}
            if str(asset or "").upper() not in pool_assets:
                return {"stage": "venue_pool",
                        "detail": (f"{asset} 不在 {venue_tag} 准入币种清单"
                                   f"（{', '.join(pool_assets)}）"),
                        "venue": venue}
        pool_conf = _num(pool.get("min_confidence"), 0.0)
        decision_conf = _num(confidence, 0.0)
        if pool_conf > 0 and 0 < decision_conf < pool_conf:
            return {"stage": "venue_pool",
                    "detail": (f"决策置信度 {decision_conf:g} 低于 {venue_tag} 门禁 "
                               f"{pool_conf:g}"),
                    "venue": venue}
        pool_max_open = int(_num(pool.get("max_open"), 0.0))
        if pool_max_open > 0 and open_count is not None:
            _cnt = int(_num(_resolve(open_count), -1.0))
            if _cnt >= 0 and _cnt >= pool_max_open:
                return {"stage": "venue_pool",
                        "detail": (f"{venue_tag} 当前持仓 {_cnt} 笔已达池上限 "
                                   f"max_open={pool_max_open}"),
                        "venue": venue}

    # ⑥ 持仓模式只读体检（本系统**永不自动切换**用户账户的持仓模式）
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
