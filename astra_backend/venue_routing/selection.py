"""多所选所的**硬筛与成本评分**（结构优化阶段 4·B3 第四十三刀）。

原样搬自 `astra_backend/venue_router.py`：

| 成员 | 原位置 | 行数 | 作用 |
|---|---|---|---|
| `_hard_filters` | L96–167 | 72 行 | 第一层：逐候选所硬性淘汰 |
| `_balanced_pick` | L172–178 | 7 行 | 跨进程确定的均衡选所 |
| `_score` | L181–226 | 46 行 | 第二层：成本评分（bps，越低越好） |

## 为什么这三块自成一域

`venue_router.py` 里其实有**两件不同的事**：

1. **选所质量**——哪些所能用（硬筛）、哪个所更便宜（评分）、同价时怎么均衡
   （跨进程确定哈希）；
2. **分配**——把一笔资金拆到多个所（`split_allocation`）、滞回防抖
   （`_apply_hysteresis`）、编排入口（`route_signal`）。

本模块只承接第 1 件。第 2 件仍在门面。

## 铁律：本模块**零真实网络**

`_hard_filters` 里的合约代码对齐必须走**纯元数据翻译**
（`native_symbol_pure`），**绝不**实例化适配器 —— 实例化会触发沙盒档域名探测
出网，破坏本模块「零真实网络」的封闭铁律。原注释保留在调用处。

## `_balanced_pick` 的跨进程确定性（审计 D7）

旧式 `abs(hash(x)) % n` 受 `PYTHONHASHSEED` 每进程随机化影响 ——
同一标的在后端 / trader / 重启后的不同进程会轮入不同所，「均衡轮换」不可复现。
`sha256` 摘要取模：任何进程任何时刻同输入恒定结果。

⚠️ 本函数被 `tests/audit/test_cross_process_hash_determinism.py` 在**子进程**里
`from astra_backend.venue_router import _balanced_pick` 直接调用，故门面必须
**再导出**该名字。
"""

from __future__ import annotations

import hashlib
import warnings
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..exchanges import listing
from ..exchanges.base import canonical_base as _canonical_base

__all__ = ["_hard_filters", "_balanced_pick", "_score"]

#: listing 对账 fail-open 时的标记串（命中则不淘汰，仅注明）
_LISTING_FAILOPEN_MARK = "跳过对账"


def _venue_pool_assets(venue: str) -> Optional[List[str]]:
    """该所配置的**准入币种清单**；未配置/为空/不可读 → `None`（=不淘汰）。

    与执行层 `execution_router.open_protected_position` 的池门禁**同源同规则**
    （同一份 `data/venue_routing.json`）：清单非空且标的不在其中 → 该所注定被
    执行层拒单，路由阶段就必须淘汰它。

    ⚠️ 2026-09-16 P0 事故**第二层**：listing gate 修好之后，ARB 这类**不在
    binance/gate 准入清单**（两份清单都只有 8 个币）的标的仍会被 `_balanced_pick`
    按 sha256 分到 binance/gate，然后在执行层被「不在 BINANCE 准入币种清单」拒掉；
    而 `route_signal` 一旦选中**不会回退**到其它所 ⇒ 主脑发单继续全灭
    （实盘日志 11:45「[ARB] … 不在 BINANCE 准入币种清单（…）」）。

    ⚠️ 刻意**不**把「清单为空」当淘汰：空清单在执行层是「该所停发」的开关，而
    OKX 直下路径（`okx_rest.place_order`，不经 execution_router）根本没有池概念，
    两者共用「空」这一表示。故空清单返回 `None`（不设限），与「未配置」同路 ——
    不替管理员发明新的拒绝理由。
    """
    try:
        from ..exchanges.routing_policy import load_venue_pool
        pool = load_venue_pool(venue)
    except Exception as exc:
        warnings.warn(
            f"[venue-router] {venue} 准入币种池不可读，跳过池门禁（不淘汰）: {exc!r}",
            RuntimeWarning,
        )
        return None
    assets = pool.get("assets") if isinstance(pool, dict) else None
    if not assets:
        return None
    return [str(a).strip().upper() for a in assets if str(a).strip()]


def _parse_iso_utc(ts: str) -> Optional[float]:
    """ISO-8601 → epoch 秒；解析不了返回 `None`（调用方据此判"无法解析"）。

    ⚠️ **必须放在本模块**：门面 `route_signal` 与 `_hard_filters` 都要用它，
    若把它留在门面、再由本模块反向导入，就会形成
    「门面 → selection → 门面」的**循环导入**
    （实测报 `cannot import name '_parse_iso_utc' from partially initialized module`）。
    门面通过下面的再导出继续提供这个名字。
    """
    try:
        s = str(ts).strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s).timestamp()
    except Exception:
        return None


def _hard_filters(signal: Dict[str, Any], cand: Dict[str, Any],
                  cfg, budget_view,
                  now_epoch: float = 0.0) -> List[str]:
    """返回该候选所的硬筛淘汰原因列表；空列表 = 通过。"""
    venue = str(cand.get("venue", "?"))
    fails: List[str] = []

    if cand.get("executable") is not True:
        fails.append("执行开闸关：executable=False")

    # 原生合约代码对齐（防跨所 inst_id 格式错位导致误杀）
    # 纯元数据翻译（native_symbol_pure）：绝不实例化适配器——实例化会触发
    # 沙盒档域名探测出网，破坏本模块「零真实网络」的封闭铁律
    #
    # ⚠️ 2026-09-16 P0（下单全拒事故）：本模块从 `venue_router.py` 抽到
    # `venue_routing/` 子包后，此处的相对导入写成了**单点** `.exchanges`——
    # 它解析到不存在的 `astra_backend.venue_routing.exchanges`，ImportError 被下面
    # 的裸 `except Exception` 吞掉，`native_contract` 静默退化成 canonical base
    # （`BTC`）。listing gate 拿 `BTC` 去对 OKX 目录键 `BTC-USDT-SWAP` 必然查不到
    # → 每个候选所都被判「沙盒未上市：okx demo 目录中无 BTC」→ route_signal
    # 返回 ALL_REJECTED → **一单都开不出去**（ai_factor_trader 日志连续十数小时
    # 全是「路由拒绝: listing gate 拒」）。
    # 修复=两点：导入补一层点（`..exchanges`），且失败必须吼出来，禁止再静默降级。
    raw_sym = str(signal.get("symbol_canonical") or signal.get("inst_id") or "")
    native_contract = raw_sym
    try:
        from ..exchanges.registry import native_symbol_pure
        base_sym = _canonical_base(raw_sym)
        if base_sym:
            native_contract = native_symbol_pure(base_sym, venue)
    except Exception as _native_err:
        warnings.warn(
            f"[venue-router] {venue} 原生合约码对齐失败，已退化为 {native_contract!r}，"
            f"listing gate 将按此名对账（极可能误判未上市）：{_native_err!r}",
            RuntimeWarning,
        )

    check = listing.ensure_contract_listed(
        venue, str(cand.get("environment", "live")),
        native_contract)
    if not check.ok:
        fails.append(f"listing gate 拒：{check.reason}")
    elif check.reason and _LISTING_FAILOPEN_MARK in check.reason:
        # fail-open：不淘汰，但 reasons 注明（由调用方拼入 reasons）
        fails.append(f"__FAILOPEN__{check.reason}")

    # 每所准入币种池（与执行层同一份 data/venue_routing.json、同一条规则）：
    # 清单非空且标的不在其中的所，路由阶段就淘汰 —— 否则会选出一个**注定被
    # 执行层拒单**的所，而 route_signal 选中即不回退 ⇒ 主脑发单全灭。
    pool_assets = _venue_pool_assets(venue)
    if pool_assets:
        pool_asset = _canonical_base(raw_sym)
        if pool_asset and pool_asset not in pool_assets:
            fails.append(
                f"不在 {venue.upper()} 准入币种清单（{', '.join(pool_assets)}）")

    size_usdt = float(signal.get("size_usdt") or 0.0)
    min_notional = float(cand.get("min_notional") or 0.0)
    if min_notional > 0 and size_usdt < min_notional:
        fails.append(f"最小名义额不足：size {size_usdt} < min_notional {min_notional}")

    # 精度/最小量：需要价格折算 qty；无价格时跳过步进核对（注记）
    price = signal.get("price") or cand.get("price")
    min_qty = float(cand.get("min_qty") or 0.0)
    precision = float(cand.get("precision") or 0.0)
    if price:
        qty = size_usdt / float(price)
        if min_qty > 0 and qty < min_qty:
            fails.append(f"最小量不足：qty {qty} < min_qty {min_qty}")
        if precision > 0:
            steps = qty / precision
            if abs(steps - round(steps)) > 1e-6:
                fails.append(
                    f"数量步进不符：qty {qty} 与精度 {precision} 不对齐")
    elif min_qty > 0 or precision > 0:
        fails.append("__NOTE__无价格无法核对最小量/步进（未淘汰）")

    updated = cand.get("health_updated_utc")
    max_age = float(cand.get("health_max_age_s") or cfg.health_max_age_s_default)
    if not updated:
        fails.append(f"健康新鲜度失效：无 health_updated_utc（上限 {max_age}s）")
    else:
        ts = _parse_iso_utc(updated)
        if ts is None:
            fails.append(f"健康新鲜度失效：health_updated_utc 无法解析（上限 {max_age}s）")
        elif (now_epoch - ts) > max_age:
            fails.append(
                f"健康新鲜度失效：数据年龄 {now_epoch - ts:.0f}s > 上限 {max_age}s")

    if budget_view is not None:
        available = getattr(budget_view, "available", None)
        if available is not None and size_usdt > float(available):
            fails.append(
                f"预算不足：size {size_usdt} > 可用 {float(available)}")

    return fails


def _balanced_pick(canonical: str, sorted_venues: list) -> str:
    """审计 D7：跨进程确定的均衡选所。旧式 abs(hash(x))%n 受 PYTHONHASHSEED
    每进程随机化——同一标的在后端/trader/重启后的不同进程会轮入不同所，
    「均衡轮换」不可复现。sha256 摘要取模：任何进程任何时刻同输入恒定结果。"""
    if not sorted_venues:
        return ""
    return sorted_venues[int(hashlib.sha256(str(canonical).encode("utf-8")).hexdigest(), 16) % len(sorted_venues)]


def _score(cand: Dict[str, Any], signal: Dict[str, Any],
           cfg, reasons: List[str]) -> float:
    """成本评分（bps，越低越好）；每个因子分项写入 reasons。"""
    venue = str(cand.get("venue", "?"))
    size_usdt = float(signal.get("size_usdt") or 0.0)
    side = str(signal.get("side", "long")).lower()
    items: List[str] = []
    total = 0.0

    spread = float(cand.get("spread_bps") or 0.0)
    total += spread
    items.append(f"价差 {spread:.2f}bps")

    depth = float(cand.get("depth_usd") or 0.0)
    depth_need = size_usdt * 10.0
    if depth < depth_need:
        ratio = 0.0 if depth_need <= 0 else max(0.0, 1.0 - depth / depth_need)
        pen = ratio * cfg.depth_penalty_max_bps
        total += pen
        items.append(f"深度不足惩罚 {pen:.2f}bps（depth {depth:.0f} < 需求 {depth_need:.0f}）")
    else:
        items.append(f"深度充足（{depth:.0f} ≥ 需求 {depth_need:.0f}），无惩罚")

    fee_rate = float(cand.get("fee_rate") or 0.0)
    fee_bps = fee_rate * 2 * 10000.0  # open+close 两腿
    total += fee_bps
    items.append(f"手续费双腿 {fee_bps:.2f}bps（rate {fee_rate} ×2 腿）")

    funding = float(cand.get("funding_rate") or 0.0)
    periods = cfg.holding_hours / cfg.funding_interval_hours
    # 方向语义：多头在正资金费时付费；空头反向（可能收费）
    funding_bps = funding * periods * (1.0 if side == "long" else -1.0) * 10000.0
    total += funding_bps
    items.append(
        f"资金费估计 {funding_bps:.2f}bps（rate {funding} × {periods:.2f} 期，{side} 方向）")

    stability = float(cand.get("stability_penalty") or 0.0)
    total += stability
    items.append(f"稳定性惩罚 {stability:.2f}bps")

    if cand.get("current_venue"):
        total -= cfg.incumbent_bonus_bps
        items.append(f"现任所 bonus -{cfg.incumbent_bonus_bps:.2f}bps")

    reasons.append(f"[{venue}] 评分 {total:.2f}bps：" + "；".join(items))
    return total
