"""多所分流策略（单一事实文件 data/venue_routing.json）。

安全设计：
- 默认空池 + dry_run=true——不开配置什么都不会发生；
- gate 池的币即使配了，也必须同时满足**执行许可开关**（live 档
  ASTRA_GATE_EXECUTION / 沙盒档 ASTRA_GATE_DEMO_EXECUTION，US-002 双轴）
  与凭证就绪才会真实下单，否则自动降级为 dry_run（fail-safe 向安全侧收敛）；
- 本模块只读配置与状态，永不写交易所。

两条独立轴（US-002 命名拆分，纠正旧「dry_run=false 名称变 live」混淆）：
- **本地执行模式**（pool.dry_run）：演算不发单 vs 真实发送；
- **交易所资金环境**（ASTRA_GATE_TESTNET 档位轴）：live 实盘 vs demo 模拟盘。
effective_mode 输出 {off | dry_run | demo | live}：gate 沙盒档 + 执行开闸 =
真实发送**模拟盘订单**，标注 demo——依时效审计字面「Gate demo + enabled 是
真实发送模拟盘订单，绝不能标成 LIVE 实盘」。旧配置无字段、无新开关时
输出与现状逐位一致（无 TESTNET 布尔 → live 轴）。

配置形状：
{
  "preferred_venue": "auto",            # US-003 手动选所优先：okx|binance|gate|auto
                                        # （缺字段/非法值 → 回退 auto + warn）
  "gate": {
    "assets": ["BTC"],                 # 准入币种（canonical 裸币名）
    "margin_per_trade_usdt": 50.0,     # 每笔保证金上限（该所独立预算）
    "max_open": 2,                     # 同时最大持仓笔数
    "min_confidence": 80.0,            # 决策置信度门禁（与主链同尺）
    "dry_run": true                    # true=全链路演算不发单（本地轴）
  }
}
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from .registry import (execution_open, gate_environment_axis,
                       registered_venues)

ROOT = Path(__file__).resolve().parents[2]
ROUTING_FILE = ROOT / "data" / "venue_routing.json"

# 审计②1(2026-09-13)：默认池数值不得再硬编码——与 global_risk_defaults 派生同源
# （旧值 50/72 是 ImportError 静默 fallback 的化石，风控收紧对它无效）。
# DEFAULT_GATE_POOL 在 global_risk_defaults() 定义后计算（见下方）。


def global_risk_defaults() -> Dict[str, Any]:
    """单一事实源风控基线（来自 scripts/risk_constants.py 与 .env）。"""
    try:
        # 审计②1(2026-09-13)：原名 MAX_CONCURRENT_POSITIONS 不存在（真名 *_CAP），
        # ImportError 100% 发生却被宽 except 静默吞成硬编码值——「单一事实源」从未生效。
        from scripts.risk_constants import (
            MAX_CONCURRENT_POSITIONS_CAP,
            MAX_SINGLE_ASSET_MARGIN,
            MIN_ENTRY_CONFIDENCE,
        )
        return {
            # ⚠️ **不得**写成 `MAX_SINGLE_ASSET_MARGIN or 50.0`：`.env` 里
            # `ASTRA_MAX_SINGLE_ASSET_MARGIN_USDT=0.0` 的语义是"不限单标的封顶"，
            # 而 `0.0` 是 falsy ⇒ 会被这里悄悄兜底成 **50**，再经
            # `load_venue_pool` 变成每所池预算，最后被 `clamp_margin` 当上限执行
            # （50 > 0 参与求最小）——「不限」被反转成「每笔硬夹 50U」。
            # 实测 2026-09-28：币安账户 4739U、Gate 1302U，每单却只占 ~50U 保证金。
            # 0 一路保持 0（`clamp_margin` 的既定语义：0 = 该上限不可用）。
            "margin_per_trade_usdt": float(MAX_SINGLE_ASSET_MARGIN),
            "max_open": int(MAX_CONCURRENT_POSITIONS_CAP or 5),
            "min_confidence": float(MIN_ENTRY_CONFIDENCE or 72.0),
        }
    except Exception as exc:
        # 兜底不再静默：外所池会退到保守硬编码（50U/5笔/72），必须吼出来。
        print(f"[routing_policy] warn 风控单一事实源导入失败，外所池回退保守硬编码值: {exc!r}")
        return {
            "margin_per_trade_usdt": 50.0,
            "max_open": 5,
            "min_confidence": 72.0,
        }


DEFAULT_GATE_POOL: Dict[str, Any] = {
    "assets": [],
    **{k: global_risk_defaults()[k]
       for k in ("margin_per_trade_usdt", "max_open", "min_confidence")},
    "dry_run": True,
}


_ASSET_TOKEN_RE = re.compile(r"^[A-Z0-9]{2,15}$")


def _normalize_assets(raw_assets: Any, venue: str) -> List[str]:
    """准入币种规范化：单字符串视作一个币种；非法项丢弃并吼出来（绝不静默拆字符）。"""
    if raw_assets in (None, ""):
        return []
    items = [raw_assets] if isinstance(raw_assets, str) else list(raw_assets) if isinstance(raw_assets, (list, tuple, set)) else None
    if items is None:
        print(f"[routing_policy] warn {venue} 的 assets 既不是字符串也不是列表（{type(raw_assets).__name__}），已按空池处理")
        return []
    out: List[str] = []
    for item in items:
        if not isinstance(item, str):
            print(f"[routing_policy] warn {venue} 的 assets 含非字符串项 {item!r}，已丢弃")
            continue
        token = item.strip().upper()
        if not _ASSET_TOKEN_RE.match(token):
            print(f"[routing_policy] warn {venue} 的 assets 项 {item!r} 不是合法币种名，已丢弃")
            continue
        if token not in out:
            out.append(token)
    return out


def load_venue_pool(venue: str) -> Dict[str, Any]:
    """统一多所池配置加载：优先读取各所覆盖项，缺省自动继承全局风控单一事实源。"""
    vkey = str(venue or "").strip().lower()
    defaults = global_risk_defaults()
    base_pool: Dict[str, Any] = {
        "assets": [],
        "margin_per_trade_usdt": defaults["margin_per_trade_usdt"],
        "max_open": defaults["max_open"],
        "min_confidence": defaults["min_confidence"],
        "dry_run": False if vkey != "gate" else True,
    }
    try:
        if ROUTING_FILE.exists():
            raw = json.loads(ROUTING_FILE.read_text(encoding="utf-8"))
            v_cfg = raw.get(vkey) or {}
            if isinstance(v_cfg, dict):
                for k in ("assets", "dry_run"):
                    if k in v_cfg:
                        base_pool[k] = v_cfg[k]
                # 审计 P2-10：assets 旧实现直接拿配置值去迭代 → 写成字符串 "BTC" 时
                # 会变成 ['B','C','T']，于是"准入币种"静默变成三个单字母垃圾。
                base_pool["assets"] = _normalize_assets(base_pool.get("assets"), vkey)
                # 数值风控参数：若配置且 > 0 则覆盖，未配置或 0/负数则继承全局风控默认值
                for k in ("margin_per_trade_usdt", "max_open", "min_confidence"):
                    if k in v_cfg and v_cfg[k] not in (None, 0, ""):
                        base_pool[k] = v_cfg[k]
    except Exception:
        pass
    assets = [str(a).upper() for a in (base_pool.get("assets") or []) if str(a).strip()]
    base_pool["assets"] = sorted(set(assets))
    try:
        base_pool["margin_per_trade_usdt"] = max(0.0, float(base_pool.get("margin_per_trade_usdt") or defaults["margin_per_trade_usdt"]))
        base_pool["max_open"] = max(1, int(base_pool.get("max_open") or defaults["max_open"]))
        base_pool["min_confidence"] = min(100.0, max(0.0, float(base_pool.get("min_confidence") or defaults["min_confidence"])))
    except (TypeError, ValueError):
        pass
    if vkey == "gate" and not _gate_execution_ready():
        base_pool["dry_run"] = True
    return base_pool


def load_gate_pool() -> Dict[str, Any]:
    return load_venue_pool("gate")


def load_binance_pool() -> Dict[str, Any]:
    return load_venue_pool("binance")


def _gate_execution_ready() -> bool:
    """真实发送前置条件：当前资金环境轴的执行许可开闸 + 凭证就绪。

    轴取法（US-002 双轴）：live 轴查 ASTRA_GATE_EXECUTION（语义与旧逐字节一致）；
    demo 轴（ASTRA_GATE_TESTNET=1 沙盒档）查独立开关 ASTRA_GATE_DEMO_EXECUTION——
    两把闸互不越权，任一缺失 fail-closed 向 dry_run 收敛。
    """
    axis = gate_environment_axis()
    if not execution_open("gate", axis):
        return False
    try:
        from astra_gateway.secrets import load_secrets
        vals = load_secrets()
        return bool(vals.get("GATE_API_KEY") and vals.get("GATE_SECRET_KEY"))
    except Exception:
        return False


def _read_raw_routing() -> Dict[str, Any]:
    """原始配置 dict（读不到/损坏 → 空 dict；永不抛穿）。"""
    try:
        if ROUTING_FILE.exists():
            raw = json.loads(ROUTING_FILE.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                return raw
    except Exception:
        pass
    return {}


#: 手动选所合法值 = 注册表已登记场所 + auto（不硬编码场所名单，新所登记即生效）
VALID_PREFERRED_VENUES = tuple(sorted(set(registered_venues()) | {"auto"}))

#: 选所路由模式（架构 A/B/C 三档；split 执行面接线前仅在证据中给出拆单方案）
VALID_ROUTING_MODES = ("auto", "balanced", "split")


def load_preferred_venue(raw: Dict[str, Any] = None) -> str:
    """US-003 手动选所优先项：顶层 preferred_venue ∈ {okx,binance,gate,auto}。

    向后兼容铁律：老配置文件没有该键 → 返回 'auto'（评分路由，行为与 US-003 前
    逐位一致）；非法值 → warn + 回退 'auto'（fail-safe：宁可回到评分路由，
    绝不因为一个写错的配置字符串把交易链断掉，也绝不猜某个所）。
    """
    data = _read_raw_routing() if raw is None else raw
    if "preferred_venue" not in data:
        print("[venue_routing] warn: 配置缺 preferred_venue 字段，回退 auto（评分路由）")
        return "auto"
    value = data.get("preferred_venue")
    key = str(value or "").strip().lower()
    if key in VALID_PREFERRED_VENUES:
        return key
    print(f"[venue_routing] warn: preferred_venue 非法值 {value!r}"
          f"（允许 {list(VALID_PREFERRED_VENUES)}），回退 auto")
    return "auto"


def load_routing_mode(raw: Dict[str, Any] = None) -> str:
    """选所路由模式：'auto'(最优执行B) | 'balanced'(均衡轮换A) | 'split'(资金拆分C)。

    非法值/缺失回退 'balanced'（三所平权改造后的系统基线）并 warn——
    与 preferred_venue 同族 fail-safe：配置写错绝不阻断交易链，也绝不猜。
    """
    data = _read_raw_routing() if raw is None else raw
    key = str(data.get("routing_mode") or "").strip().lower()
    if key in VALID_ROUTING_MODES:
        return key
    if key:
        print(f"[venue_routing] warn: routing_mode 非法值 {data.get('routing_mode')!r}"
              f"（允许 {list(VALID_ROUTING_MODES)}），回退 balanced")
    else:
        print("[venue_routing] warn: 配置缺 routing_mode 字段，回退 balanced（均衡轮动基线）")
    return "balanced"


def save_routing_mode(mode: str) -> bool:
    """写顶层 routing_mode（读-改-写原子替换，其余键原样保留）。"""
    key = str(mode or "").strip().lower()
    if key not in VALID_ROUTING_MODES:
        print(f"[venue_routing] 拒绝写入非法 routing_mode: {mode!r}")
        return False
    data = _read_raw_routing()
    data["routing_mode"] = key
    tmp = ROUTING_FILE.with_suffix(".json.tmp")
    try:
        ROUTING_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        os.replace(tmp, ROUTING_FILE)
        return True
    except Exception as exc:
        print(f"[venue_routing] 写盘失败（不改动原配置）: {exc}")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False


def save_preferred_venue(venue: str) -> bool:
    """写顶层 preferred_venue（读-改-写原子替换，gate 等其余键原样保留）。

    老 writer 兼容性：本函数只新增/覆盖一个顶层键，不改 'gate' 子树形状，
    load_gate_pool 逐键取默认表内的字段，多余键忽略——双向都不崩。
    """
    key = str(venue or "").strip().lower()
    if key not in VALID_PREFERRED_VENUES:
        print(f"[venue_routing] 拒绝写入非法 preferred_venue: {venue!r}")
        return False
    data = _read_raw_routing()
    data["preferred_venue"] = key
    tmp = ROUTING_FILE.with_suffix(".json.tmp")
    try:
        ROUTING_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n",
                       encoding="utf-8")
        os.replace(tmp, ROUTING_FILE)
        return True
    except Exception as exc:
        print(f"[venue_routing] 写盘失败（不改动原配置）: {exc}")
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return False


def gate_execution_axis() -> str:
    """对外披露当前资金环境轴（live|demo），供面板/审计显示，纯读。"""
    return gate_environment_axis()


def gate_pool_assets() -> List[str]:
    return list(load_gate_pool()["assets"])


def effective_mode() -> str:
    """'off'（无池）| 'dry_run'（本地演算，不涉所环境）| 'demo'（模拟盘真实发送）
    | 'live'（实盘验田真实发送）。

    dry_run 是**本地行为轴**；demo/live 是**交易所资金环境轴**——Gate 沙盒档 +
    执行开闸 = 真实发送模拟盘订单，标 demo 绝不标 LIVE（时效审计字面）。
    兼容钉：无 ASTRA_GATE_TESTNET 布尔时轴恒为 live，旧配置输出与现状逐位一致。
    """
    pool = load_gate_pool()
    if not pool["assets"]:
        return "off"
    if pool["dry_run"]:
        return "dry_run"
    return "demo" if gate_environment_axis() == "demo" else "live"
