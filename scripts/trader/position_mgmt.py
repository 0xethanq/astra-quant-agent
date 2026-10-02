"""AI 持仓指令的执行器（B3 抽取第十二块）。

从 `scripts/ai_factor_trader.py` 搬出 `execute_ai_position_management`（95 行）：
读取主脑写下的 `ai_position_management.json`，把其中的持仓指令落到交易所。

## 为什么单独成为一块

它是**执行层**里少见的"策略判定 + 云端改单"复合体，且带两条硬安全语义：

1. **CLOSE_MARKET 需置信度 ≥ 85** 才执行（`AI_CLOSE_CONFIDENCE_MIN`）；
   低于阈值直接拒绝并在 `executed_actions` 里留痕 —— 宁可少平，不可误平。
2. **UPDATE_SL 必须先过 `ai_tightens_stop`**：只有"确实在收紧"的改单才放行。
   放松止损 = 账户裸奔，一律拒绝（判定数学见 `scripts/trader/protection.py`）。

另有两条 fail-closed 边界：文件不存在直接返回；指令 **超过 300 秒**视为过期不执行
（防止用上一轮的陈旧指令操作当前盘面）。

## 注入面（全部调用期）

| 依赖 | 说明 |
|---|---|
| `ai_position_management_file` | 门面 `AI_POSITION_MANAGEMENT_FILE`；测试会 patch 门面属性 |
| `ai_tightens_stop` | 来自 `scripts/trader/protection.py`，同一份判定 |
| `close_position_confirmed` / `okx_rest` | OKX 直下路径 |
| `venue_registry` / `current_environment` | 场所上下文（保留在签名中；OKX 单所路径不再走多所适配器） |

全部**调用期注入**：门面会被 `pin_baseline_risk_env()` 原地重载，
import 期绑定会变成过期快照（`astra_backend/README.md` §5）。

> 平仓置信度阈值 **85 是原实现里的字面量**（不是 `risk_constants` 常量，全仓查无
> `AI_CLOSE_CONFIDENCE_MIN`）。本次搬运**刻意保持字面量不变** —— 重构不得改业务阈值。
> 若将来要把它配置化，那是独立的行为变更，需单独评审。
"""
import json
import os
import time


def execute_ai_position_management(real_pos_dict, trackers, timestamp_full, executed_actions, *,
                                 ai_position_management_file, ai_tightens_stop,
                                 close_position_confirmed, okx_rest, venue_registry,
                                 current_environment):
    """Execute only fresh, high-confidence and risk-reducing AI position instructions."""
    if not os.path.exists(ai_position_management_file):
        return
    try:
        with open(ai_position_management_file, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if int(time.time()) - int(payload.get("timestamp", 0) or 0) > 300:
            executed_actions.append("AI持仓指令已过期，未执行")
            return
    except Exception as e:
        executed_actions.append(f"AI持仓指令读取失败: {e}")
        return

    for instruction in payload.get("instructions", []):
        inst_id = str(instruction.get("instId", ""))
        action = str(instruction.get("action", "HOLD")).upper()
        confidence = float(instruction.get("confidence", 0) or 0)
        reason = str(instruction.get("reason", "AI持仓管理"))[:120]
        position = real_pos_dict.get(inst_id)
        if not position:
            # ⚠️ 第一百一十七刀：旧实现在这里**静默** `continue` —— AI 明明对一笔
            # **不在本字典**的持仓写了 CLOSE_MARKET / UPDATE_SL，面板与日志里毫无痕迹，
            # 看起来像"本轮无事可做"（假阴性）。
            #
            # 实测（2026-09-20）：AI 指令文件里唯一一条就是 `UNI-USDT-SWAP`（HOLD），
            # 而它当时并不在本路径持仓字典里；`real_pos_dict` 由
            # `cycle_stages.fetch_positions_and_reconcile` 用 **OKX 直签链**的
            # `query_positions()` 构建 ⇒ 不在字典里的持仓**永远**不会被执行，
            # 这条缺口**实际可达**（只要 AI 把 HOLD 换成 CLOSE_MARKET/UPDATE_SL）。
            #
            # 本刀只**如实留痕**、不改任何交易行为；已移除场所的历史持仓同样只留痕跳过。
            if action != "HOLD":
                _nm = inst_id.replace("-USDT-SWAP", "") or inst_id
                executed_actions.append(
                    f"[{_nm}] AI{action}指令未执行：{inst_id} 不在本路径持仓字典"
                    f"（该字典为 OKX 直签链的真实持仓）")
            continue
        if action == "HOLD":
            continue

        pos_side = str(position.get("posSide", "net")).lower()
        pos_venue = str(position.get("venue") or position.get("exchange") or "okx").lower()
        name = inst_id.replace("-USDT-SWAP", "")
        if pos_venue != "okx":
            executed_actions.append(
                f"[{name}] 非 OKX 场所({pos_venue})历史持仓，只读跳过AI持仓管理（不下发任何交易所指令）")
            continue
        current_px = float(position.get("markPx", position.get("last", 0)) or 0)

        if action == "CLOSE_MARKET":
            if confidence < 85:
                executed_actions.append(f"[{name}] AI平仓置信度{confidence:.0f}<85，拒绝执行")
                continue
            closed, close_detail = close_position_confirmed(inst_id, pos_side, float(position.get("pos", 0) or 0), venue=pos_venue)
            if closed:
                executed_actions.append(f"[{name}] AI高置信度整仓退出 ({pos_venue.upper()}): {reason}")
                tr = trackers.get(f"{inst_id}_{pos_side}")
                if tr and isinstance(tr, dict):
                    try:
                        from scripts.trader.close_evidence import build_close_evidence, append_close_evidence
                        from astra_backend.dashboard_payload.readers import DATA_DIR
                        append_close_evidence(
                            os.path.join(DATA_DIR, "closed_trade_evidence.json"),
                            build_close_evidence(
                                tracker=tr,
                                position_key=f"{inst_id}_{pos_side}",
                                exit_cause="ai_close",
                                closed_at=timestamp_full,
                            )
                        )
                    except Exception:
                        pass
                trackers.pop(f"{inst_id}_{pos_side}", None)
            else:
                executed_actions.append(f"[{name}] AI平仓请求未获交易所确认，仓位保持不变: {close_detail}")

        elif action == "UPDATE_SL":
            new_sl = float(instruction.get("suggested_sl_price", 0) or 0)
            # 反过早收紧判定见 scripts/trader/protection.py::ai_tightens_stop
            # （判定收紧方向；放松即账户裸奔）。三个阈值常量随函数搬去，值未改。
            tightens_risk = ai_tightens_stop(instruction, position)

            if not tightens_risk:
                executed_actions.append(f"[{name}] 浮盈空间不足或与现价缓冲过近({current_px} vs 拟调SL {new_sl})，拒绝过早收紧止损")
                continue

            amend_ok = False
            old_sl = 0.0
            try:
                algo_orders = okx_rest.pending_algo_orders(inst_id)
            except Exception as exc:
                executed_actions.append(f"[{name}] 云端止损收紧失败，原保护单保持不变（查询异常：{exc}）")
                continue
            # 第一百八十六刀：同 cloud_protection —— 净持仓账户的云端单 `posSide` 是
            # `"net"`，精确相等会永远找不到 ⇒ 只会打印"未找到真实云端止损单"，
            # 云端止损上移静默不生效。统一为 net 容错。
            # ⚠️ 2026-09-29：双腿方案下一个持仓挂着 [TP1 腿, 余仓腿] 两条保护单，
            # 旧实现用 `next(...)` **只挑一条** amend ⇒ 另一条腿保留旧止损
            # （覆盖率统计照样说 100%，人从面板上看不出来）。此处改为**逐条** amend。
            live_algos = [o for o in algo_orders
                          if str(o.get("state", "")).lower() == "live"
                          and str(o.get("posSide", "net")).lower() in {pos_side, "net"}
                          and o.get("slTriggerPx")]
            if not live_algos:
                executed_actions.append(f"[{name}] 未找到真实云端止损单，无法更新")
                continue
            old_sl = float(live_algos[0].get("slTriggerPx", 0) or 0)
            failed_legs = []
            for _leg in live_algos:
                try:
                    okx_rest.amend_algo_sl(_leg["algoId"], new_sl, inst_id=inst_id, new_sl_ord_px="-1")
                except Exception:
                    failed_legs.append(str(_leg.get("algoId") or ""))
            amend_ok = not failed_legs

            if amend_ok:
                executed_actions.append(f"[{name}] 云端止损收紧至 {new_sl} ({pos_venue.upper()}): {reason}")
                tracker = trackers.get(f"{inst_id}_{pos_side}")
                if tracker:
                    tracker["trailingStopPx"] = new_sl
                try:
                    from qq_notifier import notify_sl_updated
                    notify_sl_updated(name, pos_side, old_sl, new_sl, reason, venue=pos_venue)
                except Exception:
                    pass
            else:
                executed_actions.append(f"[{name}] 云端止损更新失败，原保护单保持不变")

        elif action == "UPDATE_TP":
            # 持仓中调整止盈（2026-09-29）。三条纪律缺一不可：
            #   ① 认腿靠建仓登记的 leg_algo_ids（不靠比价猜，改错腿 = 半仓错价成交）；
            #   ② 分批已发生 ⇒ 只允许改 tp2（tp1 那一半已经落袋）；
            #   ③ 失败**不回写真源**（tracker 只记录真的改成功的价格）。
            tracker = trackers.get(f"{inst_id}_{pos_side}")
            if tracker is None:
                executed_actions.append(f"[{name}] UPDATE_TP 未执行：无持仓跟踪器（无法确定 TP1 与阶段）")
                continue
            _is_long = "long" in str(pos_side).lower()
            _phase = int(tracker.get("scale_out_phase", 0) or 0)
            new_tp1 = float(instruction.get("suggested_tp1_price", 0) or 0)
            new_tp2 = float(instruction.get("suggested_tp2_price", 0) or 0)
            if new_tp1 <= 0 and new_tp2 <= 0:
                executed_actions.append(f"[{name}] UPDATE_TP 未执行：未提供任何有效止盈价")
                continue
            if _phase >= 1 and new_tp1 > 0:
                executed_actions.append(f"[{name}] UPDATE_TP：分批已完成，忽略 tp1（只允许调整 tp2）")
                new_tp1 = 0.0
            # 几何硬闸（拒绝而非夹取）：止盈必须仍在"尚未到达"的一侧。
            _tp2_effective = new_tp2 or float(tracker.get("takeProfitPx") or 0.0)
            _geom_msg = ""
            if new_tp2 > 0:
                if (_is_long and new_tp2 <= current_px) or (not _is_long and new_tp2 >= current_px):
                    _geom_msg = f"tp2 {new_tp2:g} 已在现价 {current_px:g} 的到达侧（应改用 CLOSE_MARKET）"
            if not _geom_msg and new_tp1 > 0:
                from scripts.trader.tp1 import tp1_geometry_ok
                if not tp1_geometry_ok(new_tp1, _tp2_effective, current_px, _is_long):
                    _geom_msg = (f"tp1 {new_tp1:g} 与 现价 {current_px:g}/tp2 {_tp2_effective:g} "
                                 f"几何不合法（须 现价{'<' if _is_long else '>'}tp1"
                                 f"{'<' if _is_long else '>'}tp2）")
            if _geom_msg:
                executed_actions.append(f"[{name}] UPDATE_TP 被拒：{_geom_msg}")
                continue
            try:
                from scripts.trader.tp_sync import sync_cloud_algo_tp
                _ok, _detail, _applied = sync_cloud_algo_tp(
                    inst_id, pos_side, is_long=_is_long,
                    tp1_px=new_tp1 or None, tp2_px=new_tp2 or None,
                    sl_px=float(tracker.get("trailingStopPx") or 0.0) or None,
                    phase=_phase, leg_algo_ids=tracker.get("leg_algo_ids"),
                    tracker=tracker, okx_rest=okx_rest,
                    atr=float(position.get("atr") or 0.0) if isinstance(position, dict) else 0.0,
                    # ⚠️ 必须传**价格**精度：张数精度（ARB=0、BTC=1）会把 0.2236 取整成 0.22。
                    cur_px=current_px, px_prec=int(tracker.get("px_prec", 2) or 2),
                )
            except Exception as exc:
                _ok, _detail, _applied = False, f"异常: {type(exc).__name__}: {exc}", {}
            if _ok:
                _dirs = (tracker.get("last_tp_amend") or {}).get("directions") or {}
                _adverse = any(v == "下调" for v in _dirs.values())
                _flag = "⚠️ 止盈下调" if _adverse else "止盈上移"
                executed_actions.append(
                    f"[{name}] {_flag} ({pos_venue.upper()}): {_detail}｜理由: {reason}")
                try:
                    from qq_notifier import _publish
                    _publish("trade.tp_updated", f"{'⚠️' if _adverse else '🎯'} 【止盈调整】{name}",
                             f"标的: {name}｜方向: {pos_side}\n"
                             f"调整: {_detail}\n"
                             f"当前止盈: TP1={tracker.get('scale_out_tp')} / TP2={tracker.get('takeProfitPx')}\n"
                             f"理由: {reason}",
                             {"instrument": inst_id, "venue": pos_venue, "applied": _applied},
                             priority=80)
                except Exception:
                    pass
            else:
                executed_actions.append(f"[{name}] 止盈调整未生效（原挂单与真源保持不变）: {_detail}")
