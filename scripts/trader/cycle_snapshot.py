"""周期快照的两段纯装配（B3 抽取第十七块）。

从 `scripts/ai_factor_trader.py::execute_portfolio` 搬出"只做数据装配"的长块。

## 1. `build_state_payload` —— 面板/巡检状态快照

原实现 25 行的手工字典拼装（含 17 个字段的逐项拷贝与四舍五入）。
搬出后字段清单集中一处，新增面板字段不必在 652 行里翻找。

## 2. `venue_position_span` —— 「持仓构成」一行（2026-09 新增纯函数）

不是搬家，是**缺陷修复**抽出的纯函数：巡检通知与 AI 提示词此前把场所写死成
`持仓 OKX {n}/{max}`，而系统实际在三个所上跑 ⇒ 通知读起来像"只有 OKX 有仓"。
现在系统是 **OKX 专用**（外所执行面整体移除），口径回归"只报 OKX" —— 但这是
**真实的全量**，不再是"漏报另两所"，故函数保留、跨所参数移除。

两处调用点（`cycle_stages.py` 的巡检通知与 `pos_desc`）都必须共用它 —— 各自
再写一份口径就是本缺陷的成因。

## 已随多所执行面拆除的段落

- `collect_pending_inst_ids`（外所挂单枚举）—— 外所挂单不存在了，枚举归零；
- `broken_execution_venues`（执行闸开着却不可就绪的外所）—— 同一原因。

## 边界说明（有意保守）

本模块**只搬装配**。同一函数里另有三处"从订单对象推基础币种"的表达式，
看似可合并，但**三者语义并不相同**，合并即行为变更 —— 故不动。

"""
from __future__ import annotations


def build_state_payload(*, timestamp_full, active_pos_count, max_positions, long_count,
                        short_count, cb_active, cb_reason, executed_actions,
                        all_factors, evaluate_asset_signal):
    """装配写入 `trading_state.json` 的字典（面板与巡检的读取源）。

    逐字保留原实现的字段顺序与四舍五入（`round(..., 1)` / `round(..., 2)`）——
    面板按这些键取值，缺一个或改一次精度都会显示错。

    `evaluate_asset_signal` 注入：每个标的的 `(score, action, strat_tag, strat_desc)`
    由它现算，保证快照与执行用的是**同一次**信号求值口径。
    """
    payload = {
        "timestamp": timestamp_full,
        "active_positions_count": active_pos_count,
        "max_positions": max_positions,
        "long_count": long_count,
        "short_count": short_count,
        "circuit_breaker": {"active": cb_active, "reason": cb_reason},
        "executed_actions": executed_actions,
        "instruments": []
    }

    for f in all_factors:
        score, action, reasons, strat_tag, strat_desc = evaluate_asset_signal(f)
        payload["instruments"].append({
            "name": f["name"],
            "instId": f["instId"],
            "type": f["type"],
            "price": f["price"],
            "rsi": round(f["rsi"], 1),
            "rsi_7": round(f.get("rsi_7", 50.0), 1),
            "vwap_bias": round(f.get("vwap_bias", 0.0), 2),
            "macd_hist": f.get("macd_hist", 0.0),
            "macd_accel": f.get("macd_accel", 0.0),
            "obv_flow": f.get("obv_flow", "NEUTRAL"),
            "bb_bandwidth": f.get("bb_bandwidth", 0.0),
            "vol_ratio": f.get("vol_ratio", 1.0),
            "market_regime": f.get("market_regime", "CHOP"),
            "structure_1h": f.get("structure_1h", "CHOP"),
            "trend_1h": "多头" if f.get("trend_1h_bullish") else "空头",
            "trend_4h": "多头" if f.get("trend_4h_bullish") else "空头",
            "score": score,
            "action": action,
            "strategy": strat_tag,
            "desc": strat_desc,
            "position": f["position"]
        })

    return payload


def venue_position_span(*, okx_count, okx_long, okx_short, max_positions):
    """巡检通知与 AI 提示词共用的「持仓构成」一行（2026-09 用户报缺陷后新增）。

    OKX 专用化后系统只有一个场所，故只报 OKX —— 与旧实现"跨所拉不到"时的
    退化输出**逐字相同**（`持仓 N/max (多L/空S)｜okx N`），区别在于那曾是
    "未知/漏报"，现在是**真实全量**。

    返回形如：

        持仓 7/9 (多4/空3)｜okx 7

    纯函数：不碰网络、不读全局，便于逐条钉住口径。
    """
    return (f"持仓 {int(okx_count)}/{max_positions} "
            f"(多{int(okx_long)}/空{int(okx_short)})｜okx {int(okx_count)}")
