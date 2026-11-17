"""路由配置读取（单一事实文件 ``data/venue_routing.json``）。

OKX 专用化后，本模块只剩**配置文件读取/回写**能力：
- 多所「池」（每所独立预算 / 准入币种 / dry_run）概念随多所执行面一并移除，
  相关的 ``load_venue_pool`` / ``DEFAULT_GATE_POOL`` 等已删除；
- 保留 ``preferred_venue`` / ``routing_mode`` 两个顶层键的读改写：运行时配置面
  仍然由后台维护，本模块只读配置与状态，永不写交易所。

fail-safe 铁律：配置写错/缺字段 → 回退默认 + warn，绝不阻断交易链，也绝不猜所。
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

from .registry import registered_venues

ROOT = Path(__file__).resolve().parents[2]
ROUTING_FILE = ROOT / "data" / "venue_routing.json"


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

#: 选所路由模式（架构 A/B/C 三档）
VALID_ROUTING_MODES = ("auto", "balanced", "split")


def load_preferred_venue(raw: Dict[str, Any] = None) -> str:
    """手动选所优先项：顶层 preferred_venue ∈ 注册场所 ∪ {auto}。

    向后兼容铁律：老配置文件没有该键 → 返回 'auto'（评分路由，行为与旧版
    逐位一致）；非法值 → warn + 回退 'auto'（fail-safe：宁可回到评分路由，
    绝不因为一个写错的配置字符串把交易链断掉，也绝不猜某个所）。
    """
    data = _read_raw_routing() if raw is None else raw
    if "preferred_venue" not in data:
        print("[routing] warn: 配置缺 preferred_venue 字段，回退 auto（评分路由）")
        return "auto"
    value = data.get("preferred_venue")
    key = str(value or "").strip().lower()
    if key in VALID_PREFERRED_VENUES:
        return key
    print(f"[routing] warn: preferred_venue 非法值 {value!r}"
          f"（允许 {list(VALID_PREFERRED_VENUES)}），回退 auto")
    return "auto"


def load_routing_mode(raw: Dict[str, Any] = None) -> str:
    """选所路由模式：'auto'(最优执行B) | 'balanced'(均衡轮换A) | 'split'(资金拆分C)。

    非法值/缺失回退 'balanced' 并 warn——与 preferred_venue 同族 fail-safe：
    配置写错绝不阻断交易链，也绝不猜。
    """
    data = _read_raw_routing() if raw is None else raw
    key = str(data.get("routing_mode") or "").strip().lower()
    if key in VALID_ROUTING_MODES:
        return key
    if key:
        print(f"[routing] warn: routing_mode 非法值 {data.get('routing_mode')!r}"
              f"（允许 {list(VALID_ROUTING_MODES)}），回退 balanced")
    else:
        print("[routing] warn: 配置缺 routing_mode 字段，回退 balanced（均衡轮动基线）")
    return "balanced"


def _atomic_write(data: Dict[str, Any]) -> bool:
    try:
        ROUTING_FILE.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=ROUTING_FILE.parent, delete=False, encoding="utf-8") as tf:
            json.dump(data, tf, ensure_ascii=False, indent=1)
            tf.write("\n")
            tf.flush()
            os.fsync(tf.fileno())
            temp_name = tf.name
        os.replace(temp_name, ROUTING_FILE)
        return True
    except Exception as exc:
        print(f"[routing] 写盘失败（不改动原配置）: {exc}")
        return False


def save_routing_mode(mode: str) -> bool:
    """写顶层 routing_mode（读-改-写原子替换，其余键原样保留）。"""
    key = str(mode or "").strip().lower()
    if key not in VALID_ROUTING_MODES:
        print(f"[routing] 拒绝写入非法 routing_mode: {mode!r}")
        return False
    data = _read_raw_routing()
    data["routing_mode"] = key
    return _atomic_write(data)


def save_preferred_venue(venue: str) -> bool:
    """写顶层 preferred_venue（读-改-写原子替换，其余键原样保留）。

    老 writer 兼容性：本函数只新增/覆盖一个顶层键，不改其余子树形状，
    旧读者逐键取默认表内的字段，多余键忽略——双向都不崩。
    """
    key = str(venue or "").strip().lower()
    if key not in VALID_PREFERRED_VENUES:
        print(f"[routing] 拒绝写入非法 preferred_venue: {venue!r}")
        return False
    data = _read_raw_routing()
    data["preferred_venue"] = key
    return _atomic_write(data)
