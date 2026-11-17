"""投委会席位历史战绩与胜率归因统计（无副作用纯数据处理）。

本模块职责：
1. 聚合交易台账 (trading_ledger.json) 与决策历史 (ai_brain_history.json)；
2. 依据 adopted_role / council_adopted 溯源各席位被采纳方案的带单战绩；
3. 输出各席位的采纳频次、平仓胜率、累计 PnL 与盈利因子，为动态调权与管理后台提供客观支撑。
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

__all__ = ["compute_council_seat_performance"]

#: 内置席位默认列表
BUILTIN_SEATS = ["trader_trend", "trader_momentum", "trader_quant", "cio"]


def _default_seat_stat(role_id: str) -> Dict[str, Any]:
    return {
        "role_id": role_id,
        "adopted_count": 0,
        "total_trades": 0,
        "win_trades": 0,
        "loss_trades": 0,
        "win_rate": 0.0,
        "total_pnl_usdt": 0.0,
        "gross_profit": 0.0,
        "gross_loss": 0.0,
        "profit_factor": 0.0,
    }


def compute_council_seat_performance(data_dir: Optional[Path | str] = None) -> Dict[str, Any]:
    """计算各投委会席位的实盘战绩与带单盈亏统计。

    零抛异常设计：任何文件损坏或缺失均自动兜底返回初始统计。
    """
    if data_dir is None:
        base_dir = Path("data")
    else:
        base_dir = Path(data_dir)

    seat_stats: Dict[str, Dict[str, Any]] = {
        sid: _default_seat_stat(sid) for sid in BUILTIN_SEATS
    }

    # 1. 从决策历史中统计 adopted_count 采纳频次
    history_file = base_dir / "ai_brain_history.json"
    if history_file.is_file():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                history_data = json.load(f)
            if isinstance(history_data, list):
                for cycle in history_data:
                    if not isinstance(cycle, dict):
                        continue
                    # 统计 top_opportunities 中的 council_adopted
                    top_ops = cycle.get("top_opportunities") or []
                    for op in top_ops:
                        if isinstance(op, dict):
                            adopted = str(op.get("council_adopted") or "").strip()
                            if adopted and adopted not in {"REJECT_ALL", "None", "none"}:
                                if adopted not in seat_stats:
                                    seat_stats[adopted] = _default_seat_stat(adopted)
                                seat_stats[adopted]["adopted_count"] += 1
        except Exception:
            pass

    # 2. 从实盘交易台账中统计平仓订单的盈亏与胜率
    ledger_candidates = [
        base_dir / "trading_ledger.json",
        base_dir / "full_ledger.json",
    ]
    ledger_entries: List[Dict[str, Any]] = []
    for cand in ledger_candidates:
        if cand.is_file():
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    content = json.load(f)
                if isinstance(content, list):
                    ledger_entries = content
                    break
                elif isinstance(content, dict) and "trades" in content and isinstance(content["trades"], list):
                    ledger_entries = content["trades"]
                    break
            except Exception:
                continue

    total_council_trades = 0
    total_council_pnl = 0.0

    for trade in ledger_entries:
        if not isinstance(trade, dict):
            continue

        # 检查是否有关联的投委会采纳席位
        c_meta = trade.get("council")
        adopted_role: Optional[str] = None
        if isinstance(c_meta, dict):
            adopted_role = c_meta.get("adopted_role")
        if not adopted_role:
            adopted_role = trade.get("adopted_role")

        if not adopted_role or str(adopted_role).strip() in {"", "None", "REJECT_ALL", "none"}:
            continue

        adopted_role = str(adopted_role).strip()
        if adopted_role not in seat_stats:
            seat_stats[adopted_role] = _default_seat_stat(adopted_role)

        # 提取净盈亏 (net_pnl 或 pnl)
        pnl = trade.get("net_pnl")
        if pnl is None:
            pnl = trade.get("pnl")
        if pnl is None:
            continue

        try:
            pnl_val = float(pnl)
        except (ValueError, TypeError):
            continue

        stat = seat_stats[adopted_role]
        stat["total_trades"] += 1
        stat["total_pnl_usdt"] = round(stat["total_pnl_usdt"] + pnl_val, 2)
        total_council_trades += 1
        total_council_pnl = round(total_council_pnl + pnl_val, 2)

        if pnl_val > 0.0001:
            stat["win_trades"] += 1
            stat["gross_profit"] = round(stat["gross_profit"] + pnl_val, 2)
        else:
            stat["loss_trades"] += 1
            stat["gross_loss"] = round(stat["gross_loss"] + abs(pnl_val), 2)

    # 3. 计算胜率与 Profit Factor
    for sid, stat in seat_stats.items():
        tt = stat["total_trades"]
        if tt > 0:
            stat["win_rate"] = round((stat["win_trades"] / tt) * 100.0, 1)
            gl = stat["gross_loss"]
            if gl > 0:
                stat["profit_factor"] = round(stat["gross_profit"] / gl, 2)
            else:
                stat["profit_factor"] = round(stat["gross_profit"], 2) if stat["gross_profit"] > 0 else 0.0

    return {
        "roles": seat_stats,
        "total_council_trades": total_council_trades,
        "total_council_pnl_usdt": round(total_council_pnl, 2),
    }
