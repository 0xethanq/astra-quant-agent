"""选所证据：候选装配与决策回写（B3 抽取·trader 瘦身第三刀，第八十二刀）。

从 `scripts/ai_factor_trader.py` **纯搬家**两函数（51 + 33 行）：

| 函数 | 职责 |
|---|---|
| `build_venue_candidates` | 路由候选集 = registry 全场所 + 健康观测/费率/稳定性打分输入 |
| `persist_venue_decision` | 选所证据并进 `ai_brain_decisions.json`（flock 包 RMW + 原子替换） |

## 同名注入（刻意为之）

注入 kw 参数与门面全局**同名**（`MAKER_FEE_RATE`/`AI_DECISION_CACHE_FILE`…）：
函数体因此**逐字零改动** —— `tests/audit/test_audit_batch3_persistence_atomic.py::
TestDecisionsFlock` 的 tripwire 断言文本 `file_lock(AI_DECISION_CACHE_FILE)`
原样可查（getsource 指向本模块实现即可）；`test_venue_wiring` 的
`patch.object(trader, "…")` 面经"壳调用期解析门面全局传参"保真。

⚠️ `_venue_health_stamp`（读 `VENUE_HEALTH_FILE` 的小工具）**留在门面**
（还有一处调用者 `route_and_reserve_signal`）——本模块经 `venue_health_stamp`
参数收它，门面壳传 `venue_health_stamp=_venue_health_stamp`。
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from typing import Any, Dict, List


def build_venue_candidates(inst_id: str, environment: str, *,
                           venue_health_stamp, venue_registry, load_preferred_venue,
                           venue_execution_ready, MAKER_FEE_RATE: float,
                           VENUE_HEALTH_MAX_AGE_S) -> List[Dict[str, Any]]:
    """路由候选集 = registry 全部已登记场所（okx 真候选 + binance/gate 占位）。

    场所清单与 executable 全部来自能力表，不硬编码；价差/深度/资金费的成本观测
    输入在跨所证据二期（US-004+）接入前先给 0（评分中性），不猜数。
    """
    observed_stamp, venues = venue_health_stamp()
    live_stamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    cands: List[Dict[str, Any]] = []
    try:
        names = list(venue_registry.registered_venues())
    except Exception as exc:
        print(f"[选所路由] warn registry 场所清单不可用，回退 OKX 单候选: {exc}")
        names = ["okx"]
    for name in names:
        observed = venues.get(name) if isinstance(venues.get(name), dict) else {}
        latency = [float(v) for v in (observed.get("latency_ms") or {}).values()
                   if isinstance(v, (int, float))]
        avg_latency = sum(latency) / len(latency) if latency else 0.0
        pref = load_preferred_venue()
        if name == "okx" or (pref != "auto" and name == pref and venue_execution_ready(name, environment)):
            # OKX 由巡检周期直连取数；手选锁定所（如锁定币安且就绪）享有同等现时新鲜度，
            # 不受跨所观测文件暂态老化影响（三所对等平权）。
            stamp = live_stamp
        elif observed:
            stamp = observed_stamp
        else:
            stamp = None  # 该所无跨所观测记录：诚实交新鲜度闸门判定
        # 费率平权与返佣优势：Gate 80% 返佣 Maker 净成本约 0.0001 (2.0bps 双腿)；OKX/Binance 约 0.0002 (4.0bps 双腿)
        eff_fee = (MAKER_FEE_RATE * 0.5) if name == "gate" else MAKER_FEE_RATE
        # 延迟稳定性惩罚：300ms 以内正常网络零惩罚，超出部分温和计入（上限 5bps）
        eff_stab = max(0.0, min(5.0, (avg_latency - 300.0) / 100.0)) if avg_latency > 0 else 0.0

        cands.append({
            "venue": name,
            "environment": environment,
            "executable": venue_execution_ready(name, environment),
            "fee_rate": eff_fee,
            "spread_bps": 0.0,
            "depth_usd": 0.0,
            "funding_rate": 0.0,
            "stability_penalty": eff_stab,
            "min_notional": 0.0,
            "min_qty": 0.0,
            "precision": 0.0,
            "health_updated_utc": stamp,
            "health_max_age_s": VENUE_HEALTH_MAX_AGE_S,
            "price": 0.0,
            # OKX 是本链路现任所（存量持仓与历史成交都在 OKX）
            "current_venue": name == "okx",
        })
    return cands



def persist_venue_decision(inst_id: str, venue_decision: Dict[str, Any], *,
                           AI_DECISION_CACHE_FILE: str) -> bool:
    """把选所证据并进决策缓存（data/ai_brain_decisions.json）对应标的条目。

    只追加 `venue_decision` 键，既有字段逐键保留（老 reader 无感）；主脑缓存是
    证据的落盘位置，写回沿用原子替换语义。缓存里没有该标的条目时**不伪造**决策
    ——直接跳过并 warn（没有主脑决策就没有可附着的决策 JSON）。
    """
    try:
        # 审计③(2026-09-13)：本函数与主脑（ai_brain_trader 整档覆盖写）是同一文件的
        # 两路常驻写者——每次写虽原子，但 读→merge→写 之间可被对方插队（lost update，
        # 证据回退/整轮决策被旧副本覆盖）。RMW 外包 flock 互斥（同 evolution_shield 路数）。
        from astra_backend.file_locks import file_lock
        with file_lock(AI_DECISION_CACHE_FILE):
            with open(AI_DECISION_CACHE_FILE, "r", encoding="utf-8") as handle:
                cache = json.load(handle)
            if not isinstance(cache, dict) or not isinstance(cache.get(inst_id), dict):
                print(f"[选所证据] warn {inst_id} 不在决策缓存中，本轮证据不落盘")
                return False
            cache[inst_id]["venue_decision"] = venue_decision
            fd, tmp_path = tempfile.mkstemp(prefix=".venue-decision-", suffix=".tmp",
                                            dir=os.path.dirname(AI_DECISION_CACHE_FILE))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(cache, handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(tmp_path, AI_DECISION_CACHE_FILE)
            finally:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
        return True
    except Exception as exc:
        print(f"[选所证据] warn 落盘失败（不影响本轮交易）: {exc}")
        return False

