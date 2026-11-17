"""AI 批次决策的「持仓全景」装配（结构优化阶段 4·B3 第三十一刀）。

原样搬自 `scripts/ai_factor_trader.py::execute_portfolio` 里构造
`active_pos_list` 的一段（45 行）：

`collect_okx_position_payloads` —— 从因子快照里摘出 OKX 在仓，补上追踪器
（trailingStopPx / highWaterMark / lowWaterMark / takeProfitPx / stage_desc）与 ATR。

⚠️ **OKX 专用化**：跨所持仓汇入（`merge_cross_venue_positions`）已随多所执行面
（外所适配器 / 场所路由 / 跨所接管）的拆除一并删除 —— 本系统只在 OKX 上持仓，
"持仓全景"不再需要合成外所记录。历史台账/追踪器里的外所行只做只读容错，不接管。

## 为什么这一段值得单独抽

它决定**送给 AI 的持仓全景是什么样**。AI 看到的"持仓"与真实持仓不一致，
就会基于不存在的仓位做决策 —— 这类错误不会报错，只会让模型持续误判。

## 易错点（均原样保留）

1. **OKX 侧的 `venue` 用 `setdefault` 补默认值**，不是无条件覆盖 ——
   因子快照里若已带 `venue`，必须尊重原值。
2. **追踪器键是 `f"{instId}_{side}"`**，而 `side` 取自 `position.get('side','')`
   （**不是**规范化后的值）。键拼错就静默拿不到追踪器 → 止损/水位全变 `None`
   → 提示词里显示"无止损线"。

## 边界与失败语义

`collect_okx_position_payloads` **不吞异常** —— 原实现也没有吞（它在更外层的
`try` 里）。

## 与门面的分工

纯数据装配：只吃 `all_factors` / `trackers`，无 I/O、无全局状态。
"""
from __future__ import annotations

from typing import Any, Dict, List

__all__ = ["collect_okx_position_payloads"]


def collect_okx_position_payloads(all_factors: List[Dict[str, Any]],
                                  trackers: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从因子快照摘出在仓，补上追踪器字段与 ATR。

    - 无 `position` 的因子项跳过；
    - `venue` 用 `setdefault`（**尊重**因子快照里已有的值）；
    - 追踪器键为 `f"{instId}_{position.get('side','')}"`；
    - 追踪器缺失时字段为 `None`（`stage_desc` 例外，给 `""`）。
    """
    active_pos_list: List[Dict[str, Any]] = []
    for f in all_factors:
        position = f.get("position")
        if not position:
            continue
        position_payload = dict(position)
        position_payload.setdefault("venue", "okx")
        tracker = trackers.get(f"{f['instId']}_{position.get('side', '')}", {})
        position_payload["trailingStopPx"] = tracker.get("trailingStopPx")
        position_payload["highWaterMark"] = tracker.get("highWaterMark")
        position_payload["lowWaterMark"] = tracker.get("lowWaterMark")
        position_payload["takeProfitPx"] = tracker.get("takeProfitPx")
        position_payload["stage_desc"] = tracker.get("stage_desc", "")
        position_payload["atr"] = f.get("atr", 0.0)
        active_pos_list.append(position_payload)
    return active_pos_list
