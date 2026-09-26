"""跨所采集与提示词组装（B3 抽取第二块）。

从 `scripts/ai_brain_trader.py` 原 L446-L676（231 行）整段搬出：跨所矩阵采集、
场所级健康度落盘、跨所分歧标注与证据行生成。

## 这块包含什么

| 函数 | 作用 |
|---|---|
| `_xvenue_enabled` | 总开关（`ASTRA_XVENUE_PROMPT`） |
| `_xv_record` | 场所级取数健康度累计（内存） |
| `_xv_flush_health` | 健康度 + 逐币跨所快照落盘 `venue_health.json` |
| `_get_xvenue_adapter` | 适配器获取（**测试的既定 mock 缝**） |
| `_xv_binance_snapshot` / `_xv_gate_snapshot` | 两所现价/大户比/费率单点取数 |
| `fetch_cross_venue_matrix` | 并发装配 `pkg["xvenue"]`（fail-soft） |
| `_xv_divergence_notes` / `_xvenue_prompt_line` | 分歧标注与提示词证据行 |

## 为什么这些依赖是注入而不是 import

这块的注入面比 `packages.py` 宽，原因是它踩了三处**既有测试缝**，搬走时
必须原样保留可替换性：

| 依赖 | 为什么必须调用期注入 |
|---|---|
| `get_adapter` | `tests/venues/test_xvenue_prompt.py` 4 处 `patch.object(abt, "_get_xvenue_adapter", …)` —— 板块内取数要用到补丁后的那个函数 |
| `safe_float` | 定义在门面本身（`ai_brain_trader.py:192`），不是共享叶子函数；且门面会被 `pin_baseline_risk_env()` 原地重载 |
| `atomic_write_json` | 仓内 22 处测试引用该名字（`test_audit_batch3_persistence_atomic` 等） |
| `venue_health_file` | `tests/venues/test_xvenue_prompt.py` 3 处 `patch.object(abt, "VENUE_HEALTH_FILE", …)` |
| `health`（`_XV_HEALTH` 字典） | `tests/venues/test_xvenue_prompt.py:120` **直接断言** `abt._XV_HEALTH` —— 状态必须留在门面，由门面传入 |

**通例**（同 `astra_backend/README.md` §5）：`pin_baseline_risk_env()` 的重载名单
只有 `risk_constants` / `ai_factor_trader` / `ai_brain_trader`，**不含子模块** ——
凡是在 import 期绑定的门面名，门面重载后就不再是同一个对象。

## 刻意不注入的

`XV_FUNDING_DIVERGE_MULT` / `XV_LS_DIVERGE_RATIO` 是**不可变的领域阈值**
（3.0 / 0.50，注释里有实测依据），无测试 patch、无运行期改参路径，
因此随领域一起搬来，不占用调用签名。
"""
import datetime
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional


def _xvenue_enabled() -> bool:
    return str(os.environ.get("ASTRA_XVENUE_PROMPT", "1")).strip().lower() not in ("0", "off", "false")


# 跨所分歧自动标注阈值（US-003，依据 2026-09-09 价值研究实测：
# 方向二 同刻同币三所费率分化 2.3 倍属常态噪声 → 标注阈值取 3.0 倍且同号；
# 方向三 大户比博弈样本 币安2.12 vs Gate1.10 ≈ 93% 差 → 阈值取 50%。
# 注意：两所大户比口径不同（账户/持仓维度差异），标注定位为「博弈提示」而非绝对事实。）
XV_FUNDING_DIVERGE_MULT = 3.0
XV_LS_DIVERGE_RATIO = 0.50


import threading

# 状态**不在这里**：`_XV_HEALTH` 留在门面（`tests/venues/test_xvenue_prompt.py:120`
# 直接断言 `abt._XV_HEALTH`，且它必须与门面重载后的那个对象是同一个），
# 由门面在每次调用时作为 `health` 传入。本模块只保留保护它的锁 ——
# 锁是纯粹的序列化原语、无状态，多个副本不会丢失更新。
_HEALTH_LOCK = threading.Lock()


def _xv_record(health, venue: str, name: str, ok: bool, latency_ms: float, err: str = "") -> None:
    """记录场所级取数健康度（每 15 分钟周期覆盖式累计），落盘 venue_health.json。"""
    with _HEALTH_LOCK:
        v = health.setdefault(venue, {"latency": {}, "failed": {}})
        if ok:
            v["latency"][name] = int(round(latency_ms))
            v["failed"].pop(name, None)
        else:
            v["failed"][name] = (err or "unknown")[:160]


def _xv_flush_health(packages: List[Dict[str, Any]], *, health, safe_float,
                     atomic_write_json, venue_health_file) -> None:
    try:
        with _HEALTH_LOCK:
            snapshot = {k: {"latency": dict(v.get("latency", {})),
                            "failed": dict(v.get("failed", {}))}
                        for k, v in health.items()}
        okx_ok = [p["name"] for p in packages if safe_float(p.get("price", 0)) > 0]
        okx_latencies = {p["name"]: int(p["okx_latency_ms"]) for p in packages if p.get("okx_latency_ms")}
        okx_avg = round(sum(okx_latencies.values()) / len(okx_latencies)) if okx_latencies else 0
        try:
            from scripts.okx_runtime import current_environment
            okx_testnet = bool(current_environment().simulated)
        except Exception:
            okx_testnet = str(os.environ.get("ASTRA_OKX_ENV", "demo")).lower() == "demo"
        venues = {
            "okx": {
                "ok": okx_ok,
                "failed": {p["name"]: "ticker/price unavailable" for p in packages
                           if safe_float(p.get("price", 0)) <= 0},
                "latency_ms": okx_latencies,
                "avg_ms": okx_avg,
                "testnet": okx_testnet,
            },
        }
        for venue, v in snapshot.items():
            failed = v["failed"]
            venues[venue] = {
                "ok": sorted(n for n in v["latency"] if n not in failed),
                "failed": failed,
                "latency_ms": v["latency"],
                "avg_ms": round(sum(v["latency"].values()) / len(v["latency"])) if v["latency"] else 0,
                "testnet": str(os.environ.get(f"ASTRA_{venue.upper()}_TESTNET", "0")) == "1",
            }
        symbols: Dict[str, Any] = {}
        try:  # 逐币跨所快照（US-007 前端消费源）——纯附加，异常不影响健康度落盘
            for p in packages:
                xv = p.get("xvenue") or {}
                okx_px = safe_float(p.get("price", 0))
                name = str(p.get("name") or "")
                if okx_px <= 0 or not xv or not name:
                    continue

                def _basis(v, _ref=okx_px):
                    try:
                        v = float(v)
                        return round((v - _ref) / _ref * 100, 3) if v > 0 else None
                    except (TypeError, ValueError):
                        return None
                symbols[name] = {
                    "okx": okx_px,
                    "bin_last": xv.get("bin_last"), "bin_basis_pct": _basis(xv.get("bin_last")),
                    "gate_last": xv.get("gate_last"), "gate_basis_pct": _basis(xv.get("gate_last")),
                    "bin_ls": xv.get("bin_ls"), "gate_ls": xv.get("gate_ls"),
                    "bin_funding_pct": xv.get("bin_funding_pct"),
                    "gate_funding_pct": xv.get("gate_funding_pct"),
                }
        except Exception:
            pass
        out = {
            "v": 1,  # G12 schema 版本：结构演进时消费端可按版本分派（当前消费端已 || {} 防御）
            "updated_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
            "writer_pid": os.getpid(),
            "package_count": len(packages),
            "venues": venues,
            "symbols": symbols,
        }
        # 审计③(2026-09-13)：同文件 :130 就有 fsync 版 atomic_write_json，这里却是
        # 裸 open("w")——读者全在开仓执行链（reservation/选所/面板），撕裂窗=选所失真。
        atomic_write_json(venue_health_file, out)
    except Exception:
        pass


def _get_xvenue_adapter(venue: str):
    # 测试与故障注入缝：mock 此函数即可完全离线
    from astra_backend.exchanges import get_adapter
    return get_adapter(venue)


def _xv_binance_snapshot(base: str, *, get_adapter, record):
    t0 = time.time()
    try:
        ad = get_adapter("binance")
        t = ad.fetch_ticker(base) or {}
        ls = ad.fetch_top_trader_ratio(base)
        # 费率经适配器实装取 premiumIndex（小数口径，挂载点统一 ×100）
        try:
            fund = ad.fetch_funding_rate(base)
        except Exception:
            fund = None
        if not t.get("last"):
            record("binance", base, False, (time.time() - t0) * 1000, "empty ticker (unreachable/blocked?)")
            return None
        record("binance", base, True, (time.time() - t0) * 1000)
        return {"venue": "binance", "name": base, "last": t.get("last"), "ls": ls,
                "funding_rate": fund}
    except Exception as exc:
        record("binance", base, False, (time.time() - t0) * 1000, str(exc))
        return None


def _xv_gate_snapshot(base: str, *, get_adapter, record):
    t0 = time.time()
    try:
        ad = get_adapter("gate")
        t = ad.fetch_ticker(base) or {}
        # Gate 大户比走 contract_stats top_lsr_size（适配器实装自带容错）
        try:
            ls = ad.fetch_top_trader_ratio(base)
        except Exception:
            ls = None
        if not t.get("last"):
            record("gate", base, False, (time.time() - t0) * 1000, "empty ticker (unreachable/blocked?)")
            return None
        record("gate", base, True, (time.time() - t0) * 1000)
        return {"venue": "gate", "name": base, "last": t.get("last"),
                "funding_rate": t.get("funding_rate"), "ls": ls}
    except Exception as exc:
        record("gate", base, False, (time.time() - t0) * 1000, str(exc))
        return None


def fetch_cross_venue_matrix(packages: List[Dict[str, Any]], *, enabled, snapshot_binance,
                             snapshot_gate, flush_health) -> None:
    """给每个 pkg 就地挂 xvenue：双所 现价/大户多空比/资金费率（US-003 对称化）。fail-soft。"""
    if not enabled:
        return
    try:
        by_name = {p["name"]: p for p in packages if p.get("name")}
        with ThreadPoolExecutor(max_workers=6) as ex:
            futures = []
            for name in by_name:
                futures.append(ex.submit(snapshot_binance, name))
                futures.append(ex.submit(snapshot_gate, name))
            for fut in futures:
                try:
                    val = fut.result(timeout=6)
                except Exception:
                    val = None
                if not isinstance(val, dict):
                    continue
                pkg = by_name.get(val.get("name"))
                if pkg is None:
                    continue
                xv = pkg.setdefault("xvenue", {})
                prefix = "bin" if val.get("venue") == "binance" else "gate"
                if val.get("last") is not None:
                    xv[f"{prefix}_last"] = val["last"]
                if val.get("ls") is not None:
                    xv[f"{prefix}_ls"] = val["ls"]
                if val.get("funding_rate") is not None:
                    try:
                        xv[f"{prefix}_funding_pct"] = round(float(val["funding_rate"]) * 100, 4)
                    except (TypeError, ValueError):
                        pass
        flush_health(packages)
    except Exception:
        pass


def _xv_divergence_notes(xv: Dict[str, Any]) -> str:
    """US-003 跨所分歧自动标注：博弈提示语（可多条，拼接于证据行尾）。"""
    notes: List[str] = []
    def _f(v: Any) -> Optional[float]:
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    b_ls, g_ls = _f(xv.get("bin_ls")), _f(xv.get("gate_ls"))
    if b_ls and g_ls and b_ls > 0 and g_ls > 0:
        conflict = (b_ls - 1.0) * (g_ls - 1.0) < 0     # 一所以为主导、另一所以空为主导
        diff_ratio = abs(b_ls - g_ls) / min(b_ls, g_ls)
        if conflict or diff_ratio >= XV_LS_DIVERGE_RATIO:
            optimistic = "币安" if b_ls > g_ls else "Gate"
            notes.append(f"大户比分歧{b_ls:g}vs{g_ls:g}→{optimistic}大户更乐观"
                         f"(两所口径有异,作博弈提示非绝对)")
    b_f, g_f = _f(xv.get("bin_funding_pct")), _f(xv.get("gate_funding_pct"))
    if b_f is not None and g_f is not None and b_f * g_f > 0 \
            and min(abs(b_f), abs(g_f)) > 0:
        mult = max(abs(b_f), abs(g_f)) / min(abs(b_f), abs(g_f))
        if mult >= XV_FUNDING_DIVERGE_MULT:
            gate_hi = abs(g_f) > abs(b_f)
            hi = "Gate" if gate_hi else "币安"
            hi_val = g_f if gate_hi else b_f
            side = "空" if hi_val > 0 else "多"       # 正费率=多头付费给空头
            notes.append(f"费率背离{mult:.1f}x→{hi}费率更高({hi_val:g}%),"
                         f"{side}向持仓为收费方向")
    return (" | " + " | ".join(notes)) if notes else ""


def _xvenue_prompt_line(p: Dict[str, Any], *, safe_float) -> str:
    """归一跨所证据行（双所现价基差/大户比/费率+分歧标注）；数据不足返回空串。"""
    xv = p.get("xvenue") or {}
    okx_px = safe_float(p.get("price", 0))
    bin_px = safe_float(xv.get("bin_last", 0))
    gate_px = safe_float(xv.get("gate_last", 0))
    if okx_px <= 0 or (bin_px <= 0 and gate_px <= 0):
        return ""
    seg = [f"OKX:{okx_px:g}"]
    for label, px in (("币安", bin_px), ("Gate", gate_px)):
        if px > 0:
            basis = (px - okx_px) / okx_px * 100
            seg.append(f"{label}:{px:g}(基差{basis:+.3f}%)")
    if xv.get("bin_ls") is not None:
        seg.append(f"币安大户比:{xv['bin_ls']}")
    if xv.get("gate_ls") is not None:
        seg.append(f"Gate大户比:{xv['gate_ls']}")
    if xv.get("bin_funding_pct") is not None:
        seg.append(f"币安费率:{xv['bin_funding_pct']}%")
    if xv.get("gate_funding_pct") is not None:
        seg.append(f"Gate费率:{xv['gate_funding_pct']}%")
    return ("- 🌐 跨所比对 (基差=对OKX偏离，>0.05% 警惕插针/流动性分层): "
            + " | ".join(seg) + _xv_divergence_notes(xv))
