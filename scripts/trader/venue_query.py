"""场所视角的查询与状态判定（B3 抽取·trader 瘦身第七刀，第八十六刀）。

从 `scripts/ai_factor_trader.py` **纯搬家**五函数（163 行）：

| 函数 | 行数 | 职责 |
|---|---|---|
| `query_positions` | 7 | OKX 直签查持仓（三态返回：ok/rows/error） |
| `venue_execution_ready` | 26 | 该所当前是否可执行（登记 + 闸开 + 未在坏所名单） |
| `fetch_other_venue_positions` | 38 | 非 OKX 且已开闸场所的持仓全景（今天恒为空快照） |
| `_venue_health_stamp` | 19 | 场所健康观测文件的时间戳/内容读取 |
| `close_position_confirmed` | 73 | 平仓后**在交易所侧确认**再改本地状态（OKX 专用） |

## 同名注入（沿第八十二～八十五刀）

`okx_rest` / `venue_registry` / `current_environment` / `_BROKEN_VENUES` /
`VENUE_HEALTH_FILE` / `query_positions` / `fetch_other_venue_positions` /
`venue_execution_ready` 同名注入 ⇒ 函数体 AST **零例外全等**。

⚠️ 两个**跨模块注入项**（本刀最容易静默失效处）：
- `position_mgmt.execute_ai_position_management` 收 `close_position_confirmed`；
- `reservation_reconcile.reconcile_reservation_ledger` 收 `fetch_other_venue_positions`。
两处均由门面**调用期**解析门面全局 ⇒ 搬为壳后自动拿到壳，`patch.object(trader, …)`
的既有 patch 面（test_venue_wiring / test_reservation_reconcile）不断。

⚠️ `_BROKEN_VENUES` 按**引用**注入（§99.2 引用语义）：`venue_execution_ready`
读它、`clean_stale_open_orders` 写它，必须同一个集合对象。

⚠️ **OKX 专用化**：`close_position_confirmed` 的外所平仓分支（原挂在统一执行路由上）
已随多所执行面删除；非 OKX 场所一律**只读容错**拒绝（绝不拿 OKX 接口去平外所仓）。
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple


def query_positions(
                              *,
                              okx_rest) -> Tuple[bool, List[Dict[str, Any]], str]:
    """Distinguish an exchange-confirmed empty account from a failed query."""
    try:
        rows = okx_rest.positions()
    except Exception as exc:
        return False, [], f"invalid positions response: {exc}"
    return True, rows, ""



def venue_execution_ready(venue: str, environment: str,
                              *,
                              venue_registry,
                              current_environment,
                              _BROKEN_VENUES) -> bool:
    """该所在该资金环境下能否真实下单——一律读 registry/能力表，不写死场所名单。

    - OKX：实盘/模拟盘执行走本 trader 的 V5 直签链路（不经适配器），就绪条件 =
      当前冻结环境凭证齐备且档位一致；
    - 其余场所：登记表里已经没有它们（本系统为 OKX 专用），`is_registered` 直接
      否决；这段按 registry 判定的通用逻辑保留给将来重新登记的新所
      （`registry.execution_open` 单源判定——开闸即自动成为真候选，无需改这里）。
    """
    key = str(venue or "").strip().lower()
    try:
        if not venue_registry.is_registered(key):
            return False
        if key == "okx":
            env = current_environment()
            return bool(env.configured) and str(env.mode) == str(environment)
        # 审计(2026-09-13)·坏键所自动摘除：execution_open 只看旗标——旗开着
        # 但密钥已死时仍会以最低费率赢下评分，信号派过去死在下单阶段白白烧掉。
        # 回收枚举在周期开头已实测凭证生死，认证类失败当场记入 _BROKEN_VENUES
        # （进程级=每轮重探，密钥修好自动恢复），此处一并否决，让路由把单留给
        # 真实可执行的场。
        if key in _BROKEN_VENUES:
            return False
        return bool(venue_registry.execution_open(key, environment))
    except Exception as exc:
        print(f"[选所路由] warn 场所 {key} 能力表读取失败，按不可执行处理: {exc}")
        return False



def fetch_other_venue_positions(environment: str,
                              *,
                              venue_registry,
                              venue_execution_ready) -> Tuple[bool, Dict[str, List[Dict[str, Any]]], str]:
    """跨所持仓快照（多所封顶用）：非 OKX 且已开闸场所的活跃持仓。

    登记场所集今天已经收敛为 `{"okx"}` ⇒ 本函数结构性返回 `(True, {}, "")`：
    OKX 自身的仓位走直签链路单独计数，不重复计入这里。保留本函数是为了守住
    "多所"这一层的接口形状（将来重新登记新所即自动生效）。

    语义（fail-closed）：
    - 返回 (ok, {venue: [normalized_pos...]}, error)。任一开闸所读取失败 →
      ok=False，调用方本周期禁止新增开仓（宁可不计数错杀，不可漏计超卖）；
    - 未开闸所不参与读取也不构成失败（结构性无仓位来源）；
    - 孤儿持仓纪律：本函数**只计数不处置**——外所来源不明的仓可能是用户
      手动仓位，绝不清算，仅 warn 提示并占用额度；
    - 每所单次读取，异常捕获后连同场所名返回，不静默吞。
    """
    snapshot: Dict[str, List[Dict[str, Any]]] = {}
    try:
        names = list(venue_registry.registered_venues())
    except Exception as exc:
        return False, {}, f"registry 场所清单不可用: {exc}"
    for name in names:
        if name == "okx":
            continue
        if not venue_execution_ready(name, environment):
            continue
        try:
            # 审计 C3：档位轴必须经 ADAPTER_ENV 唯一映射（与手工 close 同源）——
            # 无档 get_adapter 走 legacy 布尔→未钉死域，generic LIVE 键被打进
            # 错误沙盒域正是「跨所封顶每周期 INVALID_KEY 禁开仓」的根因。
            from astra_backend.close_intent import adapter_environment as _adapter_env
            ad = venue_registry.get_adapter(name, environment=_adapter_env(name, environment or ""))
            rows = ad.positions() or []
            live = [p for p in rows if abs(float(p.get("size_signed") or 0)) > 1e-12]
            snapshot[name] = live
            # 审计(2026-09-13)：快照函数被主周期/关闭回读/对账 fallback 多点复用，
            # 逐仓打印移交给唯一语义拥有者——主周期 1a 封顶块（此处静默=日志不再成倍）。
        except Exception as exc:
            return False, {}, f"{name} 持仓读取失败: {exc}"
    return True, snapshot, ""



def _venue_health_stamp(
                              *,
                              VENUE_HEALTH_FILE) -> Tuple[Optional[str], Dict[str, Any]]:
    """venue_health.json → (UTC ISO 观测时刻 | None, venues 观测表)。

    缺文件/坏文件 → (None, {})：跨所观测不存在，绝不编造新鲜度。
    """
    try:
        with open(VENUE_HEALTH_FILE, "r", encoding="utf-8") as handle:
            raw = json.load(handle) or {}
        venues = raw.get("venues") if isinstance(raw.get("venues"), dict) else {}
        stamp = str(raw.get("updated_utc") or "").strip()
        if stamp:
            # 文件里是 "YYYY-MM-DD HH:MM:SS" 的 UTC 时刻，补 T/Z 供路由按 UTC 解析
            stamp = stamp.replace(" ", "T")
            if not stamp.endswith("Z"):
                stamp += "Z"
            return stamp, venues
    except Exception:
        pass
    return None, {}



def close_position_confirmed(inst_id: str, pos_side: str, before_size: float, venue: str = "okx",
                              *,
                              okx_rest,
                              current_environment,
                              query_positions,
                              fetch_other_venue_positions) -> Tuple[bool, str]:
    """Close a position and verify at the exchange before changing local state."""
    target_venue = str(venue or "okx").lower()
    if target_venue != "okx":
        # 已移除场所（历史追踪器/台账里的外所行）：本系统不再持有其执行链路。
        # 只读容错——显式拒绝并留痕，绝不拿 OKX 的接口去平一个外所的仓
        # （同一 instId 在 OKX 上也存在，误平就是"平了别人的仓"）。
        return False, (f"{target_venue.upper()} 场所已移除，跳过平仓确认"
                       f"（只读容错：本系统为 OKX 专用）")

    # Pre-cancel any conflicting pending/reduce-only orders for this instrument to release available size
    try:
        for o in okx_rest.pending_orders(inst_id):
            o_side = str(o.get("posSide", "net")).lower()
            if o_side in (pos_side.lower(), "net"):
                o_id = str(o.get("ordId") or "")
                if o_id:
                    okx_rest.cancel_order(inst_id, o_id)
    except Exception as e:
        print(f"[Close Pre-Clean] Warning cancelling pending orders for {inst_id}: {e}")

    try:
        okx_rest.close_position(inst_id, pos_side, td_mode="cross", auto_cxl=True)
    except Exception as exc:
        return False, f"close command failed: {exc}"

    saw_successful_query = False
    for _ in range(6):
        time.sleep(0.6)
        query_ok, positions, query_error = query_positions()
        if not query_ok:
            continue
        saw_successful_query = True
        remaining = 0.0
        for position in positions:
            # 第一百八十六刀：净持仓账户的仓位 `posSide` 是 `"net"`，精确相等匹配不上
            # ⇒ `remaining` 保持 0.0 ⇒ **在仓位仍然开着的时候宣称"已平仓"**（假成功；
            # 这是"读不到当成没有"里最危险的一档：调用方会以为已经空仓）。
            # 与 `scale_out`/`cloud_protection` 同一 convention：`in {pos_side, "net"}`。
            if (position.get("instId") == inst_id
                    and str(position.get("posSide", "net")).lower() in {pos_side, "net"}):
                remaining = abs(float(position.get("pos", 0) or 0))
                break
        if remaining < max(1e-12, abs(before_size) * 0.001):
            return True, "exchange position closed"
    if not saw_successful_query:
        return False, "position verification failed: no successful exchange response"
    return False, f"exchange still reports an open position after close request (before={before_size})"

