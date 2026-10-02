"""交易所侧云端保护单（OCO / 动态止损棘轮）（B3 抽取·trader 瘦身第六刀，第八十五刀）。

从 `scripts/ai_factor_trader.py` **纯搬家**三函数：

| 函数 | 职责 |
|---|---|
| `_live_oco_coverage` | 统计 reduce-only OCO 单覆盖的合约张数 |
| `ensure_cloud_position_protection` | 校验 100% 云端 OCO 覆盖，补缺口并复验 |
| `sync_cloud_algo_stop` | 把棘轮动态止损同步到 OKX 云端条件单 |

本模块是 **OKX 直签链专属**：三者都直接吃门面注入的 `okx_rest`
（`pending_algo_orders` / `place_algo_oco` / `amend_algo_sl`）。

## 同名注入（沿第八十二～八十四刀）

`okx_rest` / `_live_oco_coverage` / `_float_or_zero` 同名注入 ⇒ 函数体
（含嵌套 def）AST **零例外全等**。`patch.object(aft, "okx_rest", …)` 的既有
patch 面（batch5_d_tails / batch6 / three_tier_ratchet_and_cloud_sync）
经门面壳调用期传参保真。

⚠️ `close_position_confirmed`（平仓确认，73 行）**不在本域** —— 它依赖
`query_positions`，属后续"平仓确认/场所查询"域。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

try:
    from scripts.tag_markers import normalize_legacy_markers
except ImportError:      # scripts/ 在 sys.path 上（双拼写铁律）
    from tag_markers import normalize_legacy_markers


def _live_oco_coverage(orders: List[Dict[str, Any]], pos_side: str,
                              *,
                              _float_or_zero) -> float:
    """Return contract size covered by live, reduce-only OCO TP/SL orders."""
    coverage = 0.0
    close_side = "sell" if pos_side == "long" else "buy"
    for order in orders:
        if str(order.get("state", "live")).lower() not in {"live", "effective"}:
            continue
        if str(order.get("posSide", "net")).lower() not in {pos_side, "net"}:
            continue
        if str(order.get("side", close_side)).lower() != close_side:
            continue
        if not order.get("tpTriggerPx") or not order.get("slTriggerPx"):
            continue
        reduce_only = str(order.get("reduceOnly", "true")).lower() in {"true", "1", "yes"}
        if not reduce_only:
            continue
        coverage += _float_or_zero(order.get("sz") or order.get("actualSz"))
    return coverage



def _lookup_inst_min_sz(inst_id: str) -> float:
    try:
        from scripts.instrument_pool import load_instruments
        for inst in load_instruments():
            if inst.get("instId") == inst_id:
                return float(inst.get("minSz", 1.0) or 1.0)
    except Exception:
        pass
    return 1.0


def ensure_cloud_position_protection(inst_id: str, pos_side: str, size: float, tp_px: float, sl_px: float,
                              *,
                              okx_rest,
                              _live_oco_coverage,
                              tp1_px: Any = None,
                              scale_out_ratio: float = 0.5,
                              leg_min_sz: float = 0.0,
                              prec: int = 2,
                              px_prec: Optional[int] = None,
                              legs_state: Optional[Dict[str, Any]] = None,
                              simulated: bool = False,
                              split_enabled: bool = True) -> Tuple[bool, str]:
    """Verify 100% live cloud OCO coverage, repair any gap, and verify again.

    2026-09-29 增补：覆盖率达标后，若给了 `tp1_px` 且尚未分批
    （`split_enabled`），把"一条全量腿"升级成 **[TP1 腿, 余仓腿]** 两条 sized 腿，
    让首批止盈由交易所瞬时执行而不是等 15 分钟巡检。所有成败都**不改变**
    "覆盖率必须 100%"这一先决条件 —— 拆腿失败时旧保护单原样保留。
    """
    try:
        algo_rows = okx_rest.pending_algo_orders(inst_id)
    except Exception as exc:
        return False, f"unable to verify cloud OCO: {exc}"
    coverage = _live_oco_coverage(algo_rows, pos_side)
    missing = max(0.0, float(size) - coverage)
    verified_detail = ""
    if missing <= max(1e-12, float(size) * 0.001):
        verified_detail = f"cloud OCO coverage verified ({coverage:g}/{size:g})"
    else:
        # 量化 missing 补单张数至最小步长，防止 OKX 51121 lot size 报错误杀盈利余仓
        min_sz = _lookup_inst_min_sz(inst_id)
        try:
            from astra_backend.execution.sizing import quantize_size
            missing_to_place = quantize_size(missing, min_sz)
        except Exception:
            import math
            missing_to_place = math.floor(missing / min_sz + 1e-9) * min_sz if min_sz > 0 else missing

        if missing_to_place <= 0:
            verified_detail = f"cloud OCO coverage verified ({coverage:g}/{size:g})"
        else:
            close_side = "sell" if pos_side == "long" else "buy"
            try:
                okx_rest.place_algo_oco(
                    inst_id, close_side, missing_to_place, pos_side=pos_side, td_mode="cross",
                    tp_trigger_px=tp_px, tp_ord_px="-1", sl_trigger_px=sl_px, sl_ord_px="-1",
                    reduce_only=True, cxl_on_close_pos=True,
                )
            except Exception as exc:
                return False, f"cloud OCO repair failed: {exc}"

            for _ in range(4):
                time.sleep(0.5)
                try:
                    verify_rows = okx_rest.pending_algo_orders(inst_id)
                except Exception:
                    continue
                verified_coverage = _live_oco_coverage(verify_rows, pos_side)
                if verified_coverage + max(1e-12, float(size) * 0.001, min_sz * 0.5) >= float(size):
                    verified_detail = f"cloud OCO repaired and verified ({verified_coverage:g}/{size:g})"
                    break
            else:
                return False, "cloud OCO repair was submitted but full coverage could not be verified"

    # ── 覆盖率已 100%：把"一条全量腿"升级成 [TP1 腿, 余仓腿] ──────────────
    # 先决条件已满足才拆腿；拆腿失败**不改变**上面的成功结论（旧腿仍在保护），
    # 但会把失败如实写在返回说明里，交给下一轮幂等重试。
    if split_enabled and tp1_px and float(tp1_px or 0.0) > 0:
        try:
            from scripts.trader.legs import sync_position_legs
            ok_legs, leg_detail = sync_position_legs(
                inst_id, pos_side, size,
                tp1_px=tp1_px, tp2_px=tp_px, sl_px=sl_px,
                ratio=scale_out_ratio, min_sz=leg_min_sz or _lookup_inst_min_sz(inst_id),
                prec=prec, px_prec=px_prec,
                okx_rest=okx_rest, simulated=simulated, state=legs_state,
            )
            if ok_legs:
                return True, f"{verified_detail}；{leg_detail}"
            return True, f"{verified_detail}；双腿未就位: {leg_detail}"
        except Exception as exc:
            return True, f"{verified_detail}；双腿编排异常: {type(exc).__name__}: {exc}"
    return True, verified_detail



def sync_cloud_algo_stop(inst_id: str, pos_side: str, new_sl: float, reason: str = "",
                              *,
                              okx_rest) -> bool:
    """Sync ratchet dynamic stop to OKX cloud conditional OCO order.
    
    Ensures that once a position reaches Breakeven (Tier 1) or Profit-Lock (Tier 2),
    the cloud trigger order is immediately amended without waiting for the 15-minute LLM cycle.
    """
    # 修复(2026-09-08)：v7.6 环境重构删除了旧全局 SIMULATED_TRADING，此处残留引用导致
    # NameError，连续 4 个交易周期崩溃(09-08 18:30~19:15 BJ)。DEMO/LIVE 统一尝试云端
    # amend：价格一致时幂等跳过；失败仅返回 False，调用方忽略返回值、由本地棘轮兜底，
    # 与 execute_ai_position_management 内联云端止损上移行为保持一致(演示盘与实盘同构)。
    try:
        algo_orders = okx_rest.pending_algo_orders(inst_id)
        # 统一为 net 容错，并支持双腿方案（[TP1 腿, 余仓腿]）逐条同步止损
        live_algos = [o for o in (algo_orders or [])
                      if str(o.get("state", "")).lower() == "live"
                      and str(o.get("posSide", "net")).lower() in {pos_side, "net"}
                      and o.get("slTriggerPx")]
        if not live_algos:
            return False
        failed_count = 0
        for leg in live_algos:
            current_cloud_sl = float(leg.get("slTriggerPx") or 0.0)
            if abs(current_cloud_sl - new_sl) < 1e-6:
                continue
            try:
                okx_rest.amend_algo_sl(leg["algoId"], new_sl, inst_id=inst_id, new_sl_ord_px="-1")
            except Exception as amend_err:
                print(f"[Cloud OCO Amend Error] {inst_id} {pos_side} algo {leg.get('algoId')}: {amend_err}")
                failed_count += 1
        return failed_count == 0
    except Exception as e:
        print(f"[Cloud OCO Sync Error] {inst_id} {pos_side}: {e}")
        return False

