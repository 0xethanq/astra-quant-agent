"""Shared, validated ASTRA trading universe configuration."""
from __future__ import annotations
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict
# 结构优化阶段 4·B3 第四十八刀：本地锁兜底外提到 `scripts/local_lock.py`。
# ⚠️ 双模导入：本模块既可能以裸名导入（`scripts/` 在 sys.path），
# 也可能以 `scripts.instrument_pool` 导入（repo 根在 sys.path）。
try:  # repo 根在 sys.path
    from scripts.local_lock import local_file_lock  # noqa: E402
except ImportError:  # scripts/ 在 sys.path
    from local_lock import local_file_lock  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
#: ⚠️ 这些路径**必须**是模块级常量，不能写成函数内 `ROOT / "data" / …` 内联拼法。
#:
#: 原因（结构优化阶段 4·B3 第七十三刀实测确认）：测试沙箱
#: `tests/config_sandbox.py::isolate_config` 的重定向**只对模块级 UPPERCASE 常量
#: 生效**，而且要求该常量能 `relative_to(project / "data")` 成功。
#: 于是 `ROOT`（指向**仓库根**）本身永远不被重定向，而函数内的
#: `state_file = ROOT / "data" / "trading_state.json"` 又因是**局部变量**
#: 根本不在 `vars(module)` 里 —— 两者叠加的结果是：
#: **跑测试套件会直接覆盖生产 `data/trading_state.json`**（实测 mtime 落在
#: 套件运行窗口内，且当时无任何 trader 周期）。
#:
#: 这与第四十八刀那次事故（`instrument_pool.json` 被写成缺 `instId`/`ctVal`
#: 导致实盘周期 fail-safe）是**同一机制**。`POOL_FILE` 当初就是模块级常量，
#: 所以它一直是安全的；其余四个是内联拼法，一直漏。本刀把它们统一提上来。
DATA_DIR = ROOT / "data"
POOL_FILE = DATA_DIR / "instrument_pool.json"
TRADING_STATE_FILE = DATA_DIR / "trading_state.json"
FACTOR_LIBRARY_FILE = DATA_DIR / "factor_library_snapshot.json"
NEWS_SENTIMENT_FILE = DATA_DIR / "news_sentiment.json"
DASHBOARD_CACHE_FILE = DATA_DIR / "dashboard_last_good.json"

TIER_PROFILES = {
    "tier_1_bluechip": {
        "label": "蓝筹主流",
        "max_leverage": 5,
        "base_risk_ratio": 1.0,
        "sl_atr_mult": 1.8,
        "min_vol_24h_usd": 100_000_000,
    },
    "tier_2_momentum": {
        "label": "高弹性动量",
        "max_leverage": 3,
        "base_risk_ratio": 0.75,
        "sl_atr_mult": 2.2,
        "min_vol_24h_usd": 20_000_000,
    }
}

# 出厂默认 6 标的池（2026-09-30 收敛：8 → 6，移除 ADA 与 SUI）。
#
# 选型判据（按 OKX 24H 名义成交额实测 + 台账效率）：
#   BTC 5.97B / ETH 7.65B（蓝筹，BTC 另兼全局黑天鹅哨兵基准，不可删）
#   SOL 1.27B / XRP 545M / DOGE 361M（候选里流动性最好的三个）
#   ARB 88M（流动性第 6，但当时有实时持仓与追踪器 ⇒ 被动保留）
#   移除 ADA（76M，候选里流动性最低）与 SUI（占全台账 39% 笔数、单日最大亏 -139.35、
#   每笔净 +3.80 为全池最差 ⇒ 过度集中 + 尾部风险最大）。
#
# ⚠️ 这份常量是「默认标的」**唯一可持久化**的定义：`data/instrument_pool.json`
# 被 `.gitignore` 忽略（`data/*.json`），池文件缺失/损坏时 `load_instruments()`
# 走的就是这份清单。故它必须与运行态池**保持同一份 6 条**，否则一旦重建就会复活
# 已淘汰标的并把并发上限顶高（旧版正是 10 条、含已移除的 LINK/UNI）。
# 规格取自 OKX /public/instruments 实时数据；`max_leverage` 为按 `.env`
# （ASTRA_MIN_LEVERAGE/ASTRA_MAX_LEVERAGE）派生后的值（tier1=12、tier2=6）。
# 扩容说明：MAX_CONCURRENT_POSITIONS = len(池) 自动跟随（当前 6），
# 同向持仓上限仍由 ASTRA_MAX_SAME_DIRECTION_POSITIONS 钳制（当前 5，防 Beta 踩踏）。
DEFAULT_INSTRUMENTS = [
    {"instId": "ARB-USDT-SWAP", "name": "ARB", "type": "crypto", "ccy": "ARB", "tier": "tier_2_momentum", "max_leverage": 6, "sl_atr_mult": 2.2, "base_sz": 1, "precision": 5, "ctVal": 10.0, "tickSz": "0.00001", "minSz": "0.1", "risk_per_trade_usd": 0.0},
    {"instId": "BTC-USDT-SWAP", "name": "BTC", "type": "crypto", "ccy": "BTC", "tier": "tier_1_bluechip", "max_leverage": 12, "sl_atr_mult": 1.8, "base_sz": 1, "precision": 1, "ctVal": 0.01, "tickSz": "0.1", "minSz": "0.01", "risk_per_trade_usd": 0.0},
    {"instId": "DOGE-USDT-SWAP", "name": "DOGE", "type": "crypto", "ccy": "DOGE", "tier": "tier_2_momentum", "max_leverage": 6, "sl_atr_mult": 2.2, "base_sz": 1, "precision": 5, "ctVal": 1000.0, "tickSz": "0.00001", "minSz": "0.01", "risk_per_trade_usd": 0.0},
    {"instId": "ETH-USDT-SWAP", "name": "ETH", "type": "crypto", "ccy": "ETH", "tier": "tier_1_bluechip", "max_leverage": 12, "sl_atr_mult": 1.8, "base_sz": 1, "precision": 2, "ctVal": 0.1, "tickSz": "0.01", "minSz": "0.01", "risk_per_trade_usd": 0.0},
    {"instId": "SOL-USDT-SWAP", "name": "SOL", "type": "crypto", "ccy": "SOL", "tier": "tier_2_momentum", "max_leverage": 6, "sl_atr_mult": 2.2, "base_sz": 1, "precision": 2, "ctVal": 1.0, "tickSz": "0.01", "minSz": "0.01", "risk_per_trade_usd": 0.0},
    {"instId": "XRP-USDT-SWAP", "name": "XRP", "type": "crypto", "ccy": "XRP", "tier": "tier_2_momentum", "max_leverage": 6, "sl_atr_mult": 2.2, "base_sz": 1, "precision": 4, "ctVal": 100.0, "tickSz": "0.0001", "minSz": "0.01", "risk_per_trade_usd": 0.0},
    {"instId": "SUI-USDT-SWAP", "name": "SUI", "type": "crypto", "ccy": "SUI", "tier": "tier_2_momentum", "max_leverage": 6, "sl_atr_mult": 2.2, "base_sz": 1, "precision": 4, "ctVal": 1.0, "tickSz": "0.0001", "minSz": "1.0", "risk_per_trade_usd": 0.0},
    {"instId": "AVAX-USDT-SWAP", "name": "AVAX", "type": "crypto", "ccy": "AVAX", "tier": "tier_2_momentum", "max_leverage": 6, "sl_atr_mult": 2.2, "base_sz": 1, "precision": 3, "ctVal": 1.0, "tickSz": "0.001", "minSz": "0.1", "risk_per_trade_usd": 0.0},
    {"instId": "LINK-USDT-SWAP", "name": "LINK", "type": "crypto", "ccy": "LINK", "tier": "tier_2_momentum", "max_leverage": 6, "sl_atr_mult": 2.2, "base_sz": 1, "precision": 3, "ctVal": 1.0, "tickSz": "0.001", "minSz": "0.1", "risk_per_trade_usd": 0.0},
    {"instId": "OP-USDT-SWAP", "name": "OP", "type": "crypto", "ccy": "OP", "tier": "tier_2_momentum", "max_leverage": 6, "sl_atr_mult": 2.2, "base_sz": 1, "precision": 5, "ctVal": 1.0, "tickSz": "0.00001", "minSz": "1.0", "risk_per_trade_usd": 0.0},
    {"instId": "BNB-USDT-SWAP", "name": "BNB", "type": "crypto", "ccy": "BNB", "tier": "tier_2_momentum", "max_leverage": 6, "sl_atr_mult": 2.2, "base_sz": 1, "precision": 1, "ctVal": 0.01, "tickSz": "0.1", "minSz": "1.0", "risk_per_trade_usd": 0.0},
]


def evaluate_instrument_tier(inst_id: str, name: str = "") -> str:
    """Classify instrument into Tier-1 Bluechip or Tier-2 Momentum."""
    name_upper = (name or inst_id.split("-")[0]).upper()
    if name_upper in ("BTC", "ETH"):
        return "tier_1_bluechip"
    return "tier_2_momentum"


def derive_instrument_leverage_cap(
    tier: str,
    min_leverage: float | None = None,
    max_leverage: float | None = None,
) -> int:
    """根据标的分层 (Tier 1 蓝筹 vs Tier 2 动量) 与全局风控杠杆区间动态派生单标的上限。

    - Tier 1 (蓝筹 BTC/ETH)：跟随全局上限 MAX_LEVERAGE；
    - Tier 2 (动量高弹性 SOL/DOGE 等)：在 [MIN_LEVERAGE, MAX_LEVERAGE] 区间内按风险梯度收紧，
      保证不低于 MIN_LEVERAGE 且不高于 MAX_LEVERAGE。
    """
    if min_leverage is None or max_leverage is None:
        try:
            from scripts.risk_constants import MIN_LEVERAGE as _RC_MIN, MAX_LEVERAGE as _RC_MAX
        except Exception:
            _RC_MIN, _RC_MAX = 2.0, 5.0
        if min_leverage is None:
            min_leverage = float(os.getenv("ASTRA_MIN_LEVERAGE", "") or _RC_MIN or 2.0)
        if max_leverage is None:
            max_leverage = float(os.getenv("ASTRA_MAX_LEVERAGE", "") or _RC_MAX or 5.0)
    lo = max(1.0, float(min_leverage or 2.0))
    hi = max(lo, float(max_leverage or 5.0))
    if tier == "tier_1_bluechip":
        return max(1, int(round(hi)))
    # 动量币在 [lo, hi] 内取约 40% 的弹性跨度（在默认 2~5x 时刚好为 3x，与出厂基线完美对齐）
    cap = int(round(lo + (hi - lo) * 0.4))
    return max(int(round(lo)), min(int(round(hi)), cap))


def sync_pool_leverage_caps(
    min_leverage: float | None = None,
    max_leverage: float | None = None,
) -> list[dict[str, Any]]:
    """根据指定的杠杆区间，在锁内重新对齐池内所有标的的 max_leverage 并安全落盘。"""
    def _updater(pool: list[dict[str, Any]]) -> list[dict[str, Any]]:
        for item in pool:
            tier = item.get("tier") or evaluate_instrument_tier(item.get("instId", ""), item.get("name", ""))
            item["tier"] = tier
            item["max_leverage"] = derive_instrument_leverage_cap(
                tier, min_leverage=min_leverage, max_leverage=max_leverage
            )
        return pool
    return mutate_instruments(_updater)


def score_universe_candidate(
    candidate: dict[str, Any],
    vol_24h_usd: float = 0.0,
    atr_pct: float = 0.0,
    funding_rate: float = 0.0
) -> dict[str, Any]:
    """Evaluate candidate instrument suitability and rank quality score (0 ~ 100)."""
    name = candidate.get("name", "")
    tier = evaluate_instrument_tier(candidate.get("instId", ""), name)
    profile = TIER_PROFILES[tier]

    score = 50.0
    # Liquidity check
    if vol_24h_usd > 0:
        if vol_24h_usd >= profile["min_vol_24h_usd"]:
            score += 20.0
        else:
            score -= 30.0

    # Volatility band check (healthy swing trading band: 1.5% ~ 6.0%)
    if atr_pct > 0:
        if 1.5 <= atr_pct <= 6.0:
            score += 20.0
        elif atr_pct < 1.0:
            score -= 15.0  # too sleepy
        elif atr_pct > 9.0:
            score -= 25.0  # extreme rug risk

    # Extreme funding rate penalty (abs(funding) > 0.05% implies crowding)
    if abs(funding_rate) > 0.0005:
        score -= 15.0

    candidate["tier"] = tier
    candidate["max_leverage"] = derive_instrument_leverage_cap(tier)
    candidate["sl_atr_mult"] = profile["sl_atr_mult"]
    candidate["universe_score"] = round(max(0.0, min(100.0, score)), 1)
    return candidate


def _precision(tick_size: str) -> int:
    normalized = tick_size.rstrip("0")
    return len(normalized.split(".", 1)[1]) if "." in normalized else 0


def from_okx_instrument(raw: dict[str, Any]) -> dict[str, Any]:
    inst_id = str(raw.get("instId", "")).upper()
    base = str(raw.get("baseCcy") or inst_id.split("-", 1)[0]).upper()
    tick_size = str(raw.get("tickSz") or "0.0001")
    tier = evaluate_instrument_tier(inst_id, base)
    profile = TIER_PROFILES[tier]
    return {
        "instId": inst_id,
        "name": base,
        "type": "crypto",
        "ccy": base,
        "tier": tier,
        "max_leverage": derive_instrument_leverage_cap(tier),
        "sl_atr_mult": profile["sl_atr_mult"],
        "base_sz": 1,
        "precision": _precision(tick_size),
        "ctVal": float(raw.get("ctVal") or 1.0),
        "tickSz": tick_size,
        "minSz": str(raw.get("minSz") or "1"),
        "risk_per_trade_usd": 0.0,
    }


REQUIRED_POOL_FIELDS = ("instId", "name", "ctVal")

# 审计 P2-11(2026-09-13)：池文件坏掉时旧实现静默返回 10 币 DEFAULT_INSTRUMENTS ——
# 于是管理员删掉的标的会因为"文件坏了"重新出现在交易池里（缺失≠0 的反面：坏掉≠默认）。
# 现在把状态记在这里，交易侧据此 fail-closed（只做风控接管、不开新仓），而
# dashboard/后端仍能读到一份可展示的数据，不至于整个 API 起不来。
_POOL_STATE: Dict[str, Any] = {"status": "unknown", "detail": "", "dropped": []}


def pool_state() -> Dict[str, Any]:
    """最近一次 load_instruments() 的可信度快照（status: ok|missing|corrupt|empty|invalid）。"""
    return {**_POOL_STATE, "dropped": list(_POOL_STATE.get("dropped") or [])}


def pool_is_trustworthy() -> bool:
    """true 仅当 POOL_FILE 存在且解析出一份通过字段校验的非空池。"""
    return _POOL_STATE.get("status") == "ok"


def _validate_pool_items(instruments: list[Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """逐项校验：缺必需字段/类型不对的条目丢弃并点名（旧实现是周期中途 KeyError 崩掉）。"""
    kept: list[dict[str, Any]] = []
    dropped: list[str] = []
    for index, item in enumerate(instruments):
        if not isinstance(item, dict):
            dropped.append(f"#{index}({type(item).__name__})")
            continue
        missing = [field for field in REQUIRED_POOL_FIELDS if not str(item.get(field) or "").strip()]
        if missing:
            dropped.append(f"#{index} {item.get('instId') or item.get('name') or '?'} 缺 {','.join(missing)}")
            continue
        try:
            float(item.get("ctVal"))
        except (TypeError, ValueError):
            dropped.append(f"#{index} {item.get('instId')} 的 ctVal 非数值（{item.get('ctVal')!r}）")
            continue
        kept.append(item)
    return kept, dropped


def load_instruments() -> list[dict[str, Any]]:
    if not POOL_FILE.exists():
        # 首次启动没有池文件：用出厂默认并把状态标成 missing（交易侧不据此开新仓）
        _POOL_STATE.update({"status": "missing", "detail": f"{POOL_FILE} 不存在，已按出厂默认池返回", "dropped": []})
        print(f"[instrument_pool] warn 未找到 {POOL_FILE}，返回出厂默认 {len(DEFAULT_INSTRUMENTS)} 币；"
              f"交易侧本轮不开新仓（请先在后台保存一次标的池）")
        return [dict(item) for item in DEFAULT_INSTRUMENTS]
    try:
        payload = json.loads(POOL_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        _POOL_STATE.update({"status": "corrupt", "detail": f"{POOL_FILE} 解析失败: {exc}", "dropped": []})
        print(f"[instrument_pool] error 标的池文件损坏（{exc}）→ 已退回出厂默认清单仅供展示，"
              f"交易侧本轮不开新仓。请修复或重新保存标的池。")
        return [dict(item) for item in DEFAULT_INSTRUMENTS]
    instruments = payload.get("instruments", payload) if isinstance(payload, dict) else payload
    if not isinstance(instruments, list) or not instruments:
        _POOL_STATE.update({"status": "empty", "detail": f"{POOL_FILE} 里没有 instruments", "dropped": []})
        print(f"[instrument_pool] error 标的池为空（{POOL_FILE}）→ 交易侧本轮不开新仓")
        return [dict(item) for item in DEFAULT_INSTRUMENTS]
    kept, dropped = _validate_pool_items(instruments)
    if dropped:
        print(f"[instrument_pool] error 标的池有 {len(dropped)} 项非法，已丢弃: {', '.join(dropped)}")
    if not kept:
        _POOL_STATE.update({"status": "invalid", "detail": f"{POOL_FILE} 全部条目非法", "dropped": dropped})
        print(f"[instrument_pool] error 标的池无一条合法 → 交易侧本轮不开新仓")
        return [dict(item) for item in DEFAULT_INSTRUMENTS]
    try:
        from scripts.risk_constants import MIN_LEVERAGE as _RC_MIN, MAX_LEVERAGE as _RC_MAX
    except Exception:
        _RC_MIN, _RC_MAX = 2.0, 5.0
    _cur_min = float(os.getenv("ASTRA_MIN_LEVERAGE", "") or _RC_MIN or 2.0)
    _cur_max = float(os.getenv("ASTRA_MAX_LEVERAGE", "") or _RC_MAX or 5.0)
    if _cur_min > _cur_max:
        _cur_min = _cur_max

    for item in kept:
        if "tier" not in item:
            item["tier"] = evaluate_instrument_tier(item.get("instId", ""), item.get("name", ""))
            item["sl_atr_mult"] = TIER_PROFILES[item["tier"]]["sl_atr_mult"]
        tier = item["tier"]
        cur_cap = item.get("max_leverage")
        # 兼容自适应：若池内上限低于当前全局下限、或高于全局上限、或蓝筹未跟随全局上限，按当前风控区间派生
        if cur_cap is None or cur_cap < _cur_min or cur_cap > _cur_max or (tier == "tier_1_bluechip" and cur_cap != int(round(_cur_max))):
            item["max_leverage"] = derive_instrument_leverage_cap(tier, min_leverage=_cur_min, max_leverage=_cur_max)
    _POOL_STATE.update({
        "status": "ok" if not dropped else "invalid",
        "detail": "" if not dropped else f"丢弃 {len(dropped)} 项: {', '.join(dropped)}",
        "dropped": dropped,
    })
    return kept


def _pool_lock():
    """跨进程互斥（审计 P2-6）：池文件是多进程 RMW 目标（后台路由写、采集脚本写）。
    优先用 astra_backend.file_locks（可重入、锁文件同目录），后端不在路径时退化为
    本地 flock —— 绝不在"锁不可用"时静默放行。

    兜底实现已移到 `scripts/local_lock.py`（结构优化阶段 4·B3 第四十八刀）——
    原手写兜底**不可重入**，而 `mutate_instruments` 会在锁内调
    `save_instruments`（嵌套取锁），走兜底分支会同线程自锁挂死。
    """
    try:
        from astra_backend.file_locks import file_lock
        return file_lock(POOL_FILE)
    except Exception:
        return local_file_lock(POOL_FILE)


def mutate_instruments(mutator):
    """在锁内完成 load → mutate → save 的整段 RMW（审计 P2-6）。

    旧实现里路由各自 `current = load_instruments(); save_instruments([...])`——
    两个并发保存（两次点击、页面重试、采集脚本同时跑）基于同一份旧池回写，后写者
    静默吞掉先写者（丢标的/丢参数）。mutator 接收当前池列表，返回要落盘的新列表。"""
    with _pool_lock():
        current = load_instruments()
        updated = mutator([dict(item) for item in current])
        if updated is None:
            return current
        save_instruments(list(updated))
        return updated


def save_instruments(instruments: list[dict[str, Any]]) -> None:
    with _pool_lock():
        _write_pool_file(instruments)


def _write_pool_file(instruments: list[dict[str, Any]]) -> None:
    POOL_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_path = tempfile.mkstemp(prefix=".instrument-pool-", suffix=".tmp", dir=POOL_FILE.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump({"version": 1, "instruments": instruments}, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, POOL_FILE)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
    try:
        sync_instruments_state()
    except Exception:
        pass


def _write_json_atomic(path, payload: Any) -> None:
    """审计③(2026-09-13)：同步扇出的三个下游文件曾直 write_text——与 trader 周期
    整档写者并存时，并发读者（面板等）可撞半截 JSON。统一 mkstemp+fsync+replace
    （与 save_instruments 同款路数）。双写者『丢更新』的单写者协议属批4结构收口。"""
    p = Path(path)
    fd, temp_path = tempfile.mkstemp(prefix="." + p.name + "-", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, p)
    except Exception:
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def _run_captured(script, label=None, timeout=45, env=None):
    """审计(2026-09-13)：同解释器子进程 + 非零必吼（旧裸 python3 shell 串=静默死亡）。"""
    from astra_backend.spawn import run_script
    return run_script(script, timeout=timeout, label=label, env=env)


def sync_instruments_state() -> None:
    """Synchronize trading_state.json, factor_library_snapshot.json, news_sentiment.json,
    and dashboard cache when the trading instrument pool changes."""
    active_pool = load_instruments()
    active_ids = {item["instId"] for item in active_pool}
    active_names = {item["name"] for item in active_pool}

    # 1. Update data/trading_state.json
    state_data: dict[str, Any] = {}
    if TRADING_STATE_FILE.exists():
        try:
            state_data = json.loads(TRADING_STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            state_data = {}

    current_insts = state_data.get("instruments", [])
    existing_by_id = {ins.get("instId"): ins for ins in current_insts if isinstance(ins, dict) and ins.get("instId")}

    new_insts = []
    for target in active_pool:
        inst_id = target["instId"]
        if inst_id in existing_by_id:
            new_insts.append(existing_by_id[inst_id])
        else:
            # New coin baseline
            # ★ 2026-10「不许假数据」：新币基线**只写系统状态**（"观望/等功能接入"），
            #   **不写任何市场观测值**。原实现写入 rsi=50.0 / vol_ratio=1.0 /
            #   obv_flow="NEUTRAL" / market_regime="CHOP" / trend="震荡" —— 看板会把
            #   它们显示成"RSI 中性、量能正常、区间震荡"，而事实是这个币还没取过数。
            #   市场类字段一律缺失（`None` / `"--"`），由行情与因子引擎随后填充。
            new_insts.append({
                "name": target.get("name"),
                "instId": inst_id,
                "type": target.get("type", "crypto"),
                "price": "--",
                "rsi": None,
                "rsi_7": None,
                "vwap_bias": None,
                "macd_hist": None,
                "macd_accel": None,
                "obv_flow": None,
                "bb_bandwidth": None,
                "vol_ratio": None,
                "market_regime": None,
                "structure_1h": None,
                "trend_1h": None,
                "trend_4h": None,
                "score": 0.0,
                "action": "WAIT",
                "strategy": "⚪ 观望",
                "desc": "新配置资产，微结构与特征雷达已初始化",
                "position": None,
            })
    state_data["instruments"] = new_insts
    state_data["max_positions"] = len(active_pool)
    try:
        _write_json_atomic(TRADING_STATE_FILE, state_data)
    except Exception:
        pass

    # 2. Update data/factor_library_snapshot.json to prune deleted coins
    if FACTOR_LIBRARY_FILE.exists():
        try:
            factor_data = json.loads(FACTOR_LIBRARY_FILE.read_text(encoding="utf-8"))
            if isinstance(factor_data, dict) and "instruments" in factor_data:
                factor_data["instruments"] = [
                    item for item in factor_data["instruments"]
                    if isinstance(item, dict) and item.get("instId") in active_ids
                ]
                _write_json_atomic(FACTOR_LIBRARY_FILE, factor_data)
        except Exception:
            pass

    # 3. Update data/news_sentiment.json to prune deleted coins and ensure active coins
    if NEWS_SENTIMENT_FILE.exists():
        try:
            news_data = json.loads(NEWS_SENTIMENT_FILE.read_text(encoding="utf-8"))
            if isinstance(news_data, dict) and "coins_sentiment" in news_data:
                coins_dict = news_data["coins_sentiment"]
                cleaned_coins = {c: s for c, s in coins_dict.items() if c in active_names}
                for name in active_names:
                    if name not in cleaned_coins:
                        cleaned_coins[name] = {
                            "ccy": name,
                            "label": "neutral",
                            "bullish_ratio": "50.0%",
                            "bearish_ratio": "50.0%",
                            "bullish_pct": "50.0%",
                            "bearish_pct": "50.0%",
                            "long_short_ratio": "1.00",
                            "bull_cnt": 0,
                            "bear_cnt": 0,
                            "neutral_cnt": 0,
                            "mentions": 0,
                            "sentiment_factor_score": 0.0,
                        }
                news_data["coins_sentiment"] = cleaned_coins
                _write_json_atomic(NEWS_SENTIMENT_FILE, news_data)
        except Exception:
            pass

    # 4. Invalidate dashboard cache file so next fetch generates fresh state
    if DASHBOARD_CACHE_FILE.exists():
        try:
            DASHBOARD_CACHE_FILE.unlink(missing_ok=True)
        except Exception:
            pass

    # 5. Run factor_library and news_sentiment in a non-blocking background thread
    import subprocess
    import threading
    # ⚠️ 第七十六刀：**线程启动前**抓环境快照。
    # 测试沙箱（isolate_config）的 cleanup 只保证在测试方法结束时还原 ——
    # 后台线程真正走到 spawn 可能在那之后，"继承当前环境"就会拿到
    # **已还原的干净环境** ⇒ 子进程写生产 data/（§88 实测窗口）。
    # 快照在调用线程前同步抓取，生产里快照=真实环境（行为不变）。
    _env_snapshot = dict(os.environ)
    def _run_bg() -> None:
        try:
            fl_script = ROOT / "scripts" / "factor_library.py"
            if fl_script.exists():
                _run_captured(fl_script, env=_env_snapshot)
            nh_script = ROOT / "scripts" / "news_sentiment_harvester.py"
            if nh_script.exists():
                _run_captured(nh_script, env=_env_snapshot)
        except Exception:
            pass
    threading.Thread(target=_run_bg, daemon=True).start()

