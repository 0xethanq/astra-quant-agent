"""投委会报价单结构化解析与数理共识度算法（纯函数，无 I/O）。

本模块职责：
1. 解析各交易员提案文本中的标准化报价单（标的|倾向|限价|止损|止盈|保证金|置信度|依据）；
2. 逐标的计算方向共识度（Agreement Index，0.0~1.0）、加权综合置信度与席位分布；
3. 生成格式化【量化共识度矩阵卷宗 (Consensus Docket)】供 CIO 终审横向参考；
4. 识别多空严重对立的争议标的，为 Debate 对抗辩论模式提供精准靶向。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

__all__ = [
    "parse_trader_quote_table",
    "calculate_symbol_consensus",
    "calculate_council_consensus",
    "format_consensus_docket",
    "extract_disputed_symbols",
]


def _clean_token(text: str) -> str:
    """清理 markdown 加粗、反引号与首尾空格。"""
    return re.sub(r"[\*`]", "", text).strip()


def _parse_float(val: str) -> Optional[float]:
    cleaned = re.sub(r"[\*`$,]", "", val).strip()
    if not cleaned or cleaned in {"-", "—", "--", "N/A", "NA", "null", "none"}:
        return None
    try:
        return float(cleaned)
    except (ValueError, TypeError):
        return None


def _parse_int(val: str, default: int = 50) -> int:
    cleaned = re.sub(r"[\*`%,]", "", val).strip()
    if not cleaned or cleaned in {"-", "—", "--", "N/A", "null"}:
        return default
    try:
        num = int(float(cleaned))
        return max(0, min(100, num))
    except (ValueError, TypeError):
        return default


def parse_trader_quote_table(proposal_text: str) -> List[Dict[str, Any]]:
    """从交易员提案文本中提取标准化报价单列表。

    优先通过管道符表格解析；若未包含表格，尝试通过标准正则行解析。
    """
    if not proposal_text or not isinstance(proposal_text, str):
        return []

    quotes: List[Dict[str, Any]] = []
    seen_symbols = set()

    lines = proposal_text.strip().splitlines()
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        # 尝试管道表格解析
        if "|" in line:
            # 去除首尾的管道符
            stripped = line
            if stripped.startswith("|"):
                stripped = stripped[1:]
            if stripped.endswith("|"):
                stripped = stripped[:-1]

            parts = [p.strip() for p in stripped.split("|")]
            # 至少包含 标的 | 倾向 | 限价 | 止损 | 止盈 | 保证金 | 置信度
            if len(parts) >= 6:
                first_col = _clean_token(parts[0])
                # 排除表头行或分割线行
                if first_col.lower() in {"标的", "symbol", "instrument", "instid", "---", "--"}:
                    continue
                if all(c in "-: " for c in first_col):
                    continue

                # 识别标的 ID (例如 BTC-USDT-SWAP 或 BTC-USDT 或 BTC)
                if ("USDT" in first_col or "SWAP" in first_col or first_col.endswith("-USDT")):
                    sym = first_col
                    act_raw = _clean_token(parts[1]).upper()
                    if any(w in act_raw for w in ("BUY", "LONG", "多", "做多")):
                        action = "BUY_LONG"
                    elif any(w in act_raw for w in ("SELL", "SHORT", "空", "做空")):
                        action = "SELL_SHORT"
                    else:
                        action = "WAIT"

                    lp = _parse_float(parts[2]) if len(parts) > 2 else None
                    sl = _parse_float(parts[3]) if len(parts) > 3 else None
                    tp = _parse_float(parts[4]) if len(parts) > 4 else None
                    margin = _parse_float(parts[5]) if len(parts) > 5 else None
                    conf = _parse_int(parts[6]) if len(parts) > 6 else 50
                    reason = parts[7].strip() if len(parts) > 7 else ""

                    if sym not in seen_symbols:
                        seen_symbols.add(sym)
                        quotes.append({
                            "symbol": sym,
                            "action": action,
                            "limit_price": lp,
                            "stop_loss": sl,
                            "take_profit": tp,
                            "margin": margin,
                            "confidence": conf,
                            "reason": reason,
                        })

    # 若表格未解析出任何标的，尝试备用正则扫描（容错部分模型自由文本表述）
    if not quotes:
        pattern = re.compile(
            r"([A-Z0-9]{2,10}-USDT(?:-SWAP)?)\s*[:：|]\s*(BUY_LONG|SELL_SHORT|WAIT|做多|做空|观望)",
            re.IGNORECASE,
        )
        for m in pattern.finditer(proposal_text):
            sym = m.group(1).upper()
            act_text = m.group(2).upper()
            if any(w in act_text for w in ("BUY", "LONG", "多")):
                act = "BUY_LONG"
            elif any(w in act_text for w in ("SELL", "SHORT", "空")):
                act = "SELL_SHORT"
            else:
                act = "WAIT"

            if sym not in seen_symbols:
                seen_symbols.add(sym)
                quotes.append({
                    "symbol": sym,
                    "action": act,
                    "limit_price": None,
                    "stop_loss": None,
                    "take_profit": None,
                    "margin": None,
                    "confidence": 50,
                    "reason": "",
                })

    return quotes


def calculate_symbol_consensus(
    symbol: str,
    quotes_by_role: Dict[str, Dict[str, Any]],
    roles: Dict[str, Any],
) -> Dict[str, Any]:
    """计算单个标的在多个席位提案中的方向共识度与置信度。

    参数:
    - symbol: 标的 ID (例如 BTC-USDT-SWAP)
    - quotes_by_role: { role_id: quote_dict }
    - roles: { role_id: role_spec } (含 weight 与 name)
    """
    actions_count: Dict[str, int] = {"BUY_LONG": 0, "SELL_SHORT": 0, "WAIT": 0}
    weighted_votes: Dict[str, float] = {"BUY_LONG": 0.0, "SELL_SHORT": 0.0, "WAIT": 0.0}
    seat_details: List[Dict[str, Any]] = []

    total_weight = 0.0
    for r_k, q in quotes_by_role.items():
        act = q.get("action", "WAIT")
        if act not in actions_count:
            act = "WAIT"
        actions_count[act] += 1

        r_spec = roles.get(r_k, {})
        w = float(r_spec.get("weight", 0.3) or 0.3)
        total_weight += w
        weighted_votes[act] += w

        conf = int(q.get("confidence", 50))
        r_name = r_spec.get("name", r_k)
        seat_details.append({
            "role_id": r_k,
            "role_name": r_name,
            "action": act,
            "confidence": conf,
            "weight": w,
            "limit_price": q.get("limit_price"),
            "stop_loss": q.get("stop_loss"),
            "take_profit": q.get("take_profit"),
            "reason": q.get("reason", ""),
        })

    if total_weight <= 0:
        total_weight = 1.0

    # 确定主流倾向 (Dominant Action)
    sorted_actions = sorted(weighted_votes.items(), key=lambda x: x[1], reverse=True)
    dominant_action, dominant_weight = sorted_actions[0]

    total_traders = len(quotes_by_role)
    agreement_score: float = 0.0
    status: str = "MODERATE_LEANING"

    # 计算方向共识度
    if total_traders > 0:
        dom_ratio = dominant_weight / total_weight
        dom_count = actions_count[dominant_action]

        # 检查是否存在明确多空对立 (同时有多和空)
        has_opposite_conflict = (actions_count["BUY_LONG"] > 0 and actions_count["SELL_SHORT"] > 0)

        if dom_count == total_traders:
            agreement_score = 1.0
            status = "STRONG_CONSENSUS"
        elif has_opposite_conflict:
            agreement_score = max(0.2, min(0.5, round(dom_ratio * 0.5, 2)))
            status = "CONFLICT_SPLIT"
        elif dom_ratio >= 0.65:
            agreement_score = round(dom_ratio, 2)
            status = "MODERATE_LEANING"
        else:
            agreement_score = round(dom_ratio, 2)
            status = "CONFLICT_SPLIT"

    # 加权平均置信度
    weighted_conf_sum = sum(
        detail["confidence"] * detail["weight"] for detail in seat_details
    )
    weighted_confidence = int(round(weighted_conf_sum / total_weight)) if total_weight > 0 else 50

    # 生成文字摘要 (如: 稳健:多(82) / 动能:多(78) / 量化:多(75))
    dist_parts = []
    for d in seat_details:
        short_name = d["role_name"].split("(")[0].strip().replace("资深交易员 ", "")
        act_label = "多" if d["action"] == "BUY_LONG" else ("空" if d["action"] == "SELL_SHORT" else "观望")
        dist_parts.append(f"{short_name}:{act_label}({d['confidence']})")
    distribution_str = " / ".join(dist_parts)

    return {
        "symbol": symbol,
        "dominant_action": dominant_action,
        "agreement_score": round(agreement_score, 2),
        "weighted_confidence": weighted_confidence,
        "status": status,
        "actions_count": actions_count,
        "distribution_summary": distribution_str,
        "seat_details": seat_details,
    }


def calculate_council_consensus(
    trader_proposals: Dict[str, Dict[str, Any]],
    roles: Dict[str, Any],
) -> Dict[str, Any]:
    """汇总全部交易员提案，生成整套标的共识度矩阵。"""
    quotes_by_symbol: Dict[str, Dict[str, Dict[str, Any]]] = {}

    for r_k, prop in trader_proposals.items():
        if not isinstance(prop, dict) or prop.get("status") == "error":
            continue
        content = prop.get("content", "")
        parsed_quotes = parse_trader_quote_table(content)
        for q in parsed_quotes:
            sym = q["symbol"]
            if sym not in quotes_by_symbol:
                quotes_by_symbol[sym] = {}
            quotes_by_symbol[sym][r_k] = q

    consensus_by_symbol: Dict[str, Dict[str, Any]] = {}
    disputed_symbols: List[str] = []
    strong_consensus_symbols: List[str] = []

    for sym, role_quotes in sorted(quotes_by_symbol.items()):
        metrics = calculate_symbol_consensus(sym, role_quotes, roles)
        consensus_by_symbol[sym] = metrics

        if metrics["status"] == "CONFLICT_SPLIT":
            disputed_symbols.append(sym)
        elif metrics["status"] == "STRONG_CONSENSUS" and metrics["dominant_action"] != "WAIT":
            strong_consensus_symbols.append(sym)

    return {
        "by_symbol": consensus_by_symbol,
        "disputed_symbols": disputed_symbols,
        "strong_consensus_symbols": strong_consensus_symbols,
        "total_symbols_evaluated": len(consensus_by_symbol),
    }


def extract_disputed_symbols(consensus_data: Dict[str, Any]) -> List[str]:
    """提取需要进入 Debate 模式对抗辩论的争议标的清单。"""
    disputed = consensus_data.get("disputed_symbols", [])
    if isinstance(disputed, list):
        return [str(s) for s in disputed]
    return []


def format_consensus_docket(consensus_data: Dict[str, Any]) -> str:
    """生成嵌入 CIO 卷宗的【量化共识度与报价对比矩阵】。"""
    by_sym = consensus_data.get("by_symbol", {})
    if not by_sym:
        return "【量化共识度矩阵】暂无有效标的报价提案数据"

    lines = [
        "====================================================",
        "【量化共识度矩阵 (Algorithmic Consensus Docket)】",
        "标的 | 综合倾向 | 共识度 | 加权置信度 | 席位分布 | 仲裁决策指引",
    ]

    for sym, data in sorted(by_sym.items()):
        act = data["dominant_action"]
        score = data["agreement_score"]
        conf = data["weighted_confidence"]
        status = data["status"]
        dist = data["distribution_summary"]

        pct_str = f"{int(score * 100)}%"
        if status == "STRONG_CONSENSUS":
            guidance = "全员强共识；若开仓应优先采纳，严格核准点位与止损止盈"
            tag = f"{pct_str} (强共识)"
        elif status == "CONFLICT_SPLIT":
            guidance = "多空撕裂分歧；审阅攻防论据，无压倒性胜率时建议审慎观望 WAIT"
            tag = f"{pct_str} (严重分歧)"
        else:
            guidance = "偏向共识；参考主流倾向并核验反向交易员指出之风险"
            tag = f"{pct_str} (相对多数)"

        lines.append(f"{sym} | {act} | {tag} | {conf} | {dist} | {guidance}")

    return "\n".join(lines)
