"""Circuit breaker engine: Black swan sentinel, daily loss limits, and stop cooldowns."""
from __future__ import annotations
import datetime
import json
import os
import time
from pathlib import Path
from typing import Dict, Any, Tuple, Optional

from scripts.risk_constants import STOP_COOLDOWN_MINUTES
from astra_backend.time_utils import beijing_day
from astra_backend.execution.sizing import effective_daily_loss_limit
from astra_backend.execution.cooldowns import (
    add_stop_cooldown as _cooldowns_add,
    is_in_stop_cooldown as _cooldowns_is_in,
    load_stop_cooldowns as _cooldowns_load,
    read_stop_cooldowns_state as _cooldowns_read_state,
)

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT / "data"
NEWS_SENTIMENT_FILE = DATA_DIR / "news_sentiment.json"
CIRCUIT_BREAKER_FILE = DATA_DIR / "circuit_breaker.json"
LEDGER_JSON_FILE = DATA_DIR / "trading_ledger.json"
# 2026-11-17（用户拍板）：系统已收口为 OKX 单所，原“跨所台账同步完整性”闸门
# 已无对象。`ledger_sync_status.json` 仍由 sync_full_ledger 写入、仍供 data_health
# 显示 PARTIAL，但**不再参与开仓熔断**：单次同步失败不应停掉整个系统。
# 审计③(2026-09-13)：文件名分裂修复——旧值（复数 .json）与 trader 活文件
# stop_cooldown.json（单数）互不可见；若后端接平仓写复数而 trader 消费单数，冷却
# 静默失效。归一到既成事实文件名（两边 key/schema 本就同构）。
STOP_COOLDOWN_FILE = DATA_DIR / "stop_cooldown.json"


def ledger_daily_closed_pnl(ledger, environment_mode: str, today_str: str) -> float:
    """审计④1(2026-09-13) 单一事实源：当日已平仓盈亏求和必须带环境轴。
    台账行自带 environment 标签（sync_full_ledger 写入），demo↔live 切换当天若不
    过滤，两环境盈亏互相抵消/虚增可让熔断假阴性。规则：
    - 行环境与当前环境明确不同 → 剔除；
    - 行缺环境标签（历史旧行）或当前环境拿不到 → 保守计入（宁停不漏，与
      本模块「不可判定=不放松」纪律一致，绝不静默放宽）。"""
    want = str(environment_mode or "").strip().lower()
    total = 0.0
    for t in ledger:
        try:
            if t.get("status") != "closed":
                continue
            if beijing_day(t.get("close_time")) != today_str:
                continue
            row_env = str(t.get("environment") or "").strip().lower()
            if row_env and want and row_env != want:
                continue
            total += float(t.get("pnl", 0) or 0)
        except (TypeError, ValueError):
            continue
    return total


def ledger_today_stats(ledger, environment_mode: str, today_str: str) -> Dict[str, Any]:
    """审计批7(2026-09-13)·前台「今日已实现」台账口径：前台 KPI 曾从 OKX bills 单所
    聚合，而台账/熔断早已是各所合并——用户实锤「今日已实现和台账对不上」（当时某外所
    当日的已实现盈亏前台不可见，且彼时台账又吞过一条腿）。单一事实源：KPI 与熔断共用
    本函数——net_realized=Σ行pnl 与 ledger_daily_closed_pnl **逐字同式**（fees 已含
    于行内，funding 单列展示不混入净值，两数从此不可能打架）。行筛选规则与熔断逐字
    同款（环境轴保守计入、status=closed、北京日）；win/loss 计数沿仪表盘旧口径
    剔除 |net|<0.01 且 |gross|<0.01 的摩擦尘单。environment_mode 传 "" = 保守全计
    （与熔断不可判定时纪律一致）。"""
    want = str(environment_mode or "").strip().lower()
    out = {"realized_gross": 0.0, "fees_paid": 0.0, "funding_paid": 0.0,
           "net_realized": 0.0, "win_trades": 0, "loss_trades": 0, "win_rate": 0.0,
           "source": "ledger"}
    for t in ledger:
        try:
            if t.get("status") != "closed":
                continue
            if beijing_day(t.get("close_time")) != today_str:
                continue
            row_env = str(t.get("environment") or "").strip().lower()
            if row_env and want and row_env != want:
                continue
            net = float(t.get("pnl", 0) or 0)
            gross = float(t.get("gross_pnl", 0) or 0)
            out["realized_gross"] += gross
            out["fees_paid"] += float(t.get("fee", 0) or 0)
            out["funding_paid"] += float(t.get("funding_fee", 0) or 0)
            out["net_realized"] += net
            if abs(net) < 0.01 and abs(gross) < 0.01:
                continue
            if net > 0:
                out["win_trades"] += 1
            elif net < 0:
                out["loss_trades"] += 1
        except (TypeError, ValueError):
            continue
    closed_n = out["win_trades"] + out["loss_trades"]
    out["win_rate"] = round(out["win_trades"] / closed_n * 100, 1) if closed_n else 0.0
    for k in ("realized_gross", "fees_paid", "funding_paid", "net_realized"):
        out[k] = round(out[k], 2)
    return out


def _read_stop_cooldowns_state() -> Tuple[Dict[str, Any], bool]:
    """薄壳：转调单一事实源，并在调用时解析本模块的 `STOP_COOLDOWN_FILE`。

    结构优化阶段 4·B3 第五十刀：与 `scripts/ai_factor_trader.py` 的同名函数
    原为等价重复，已收敛到 `astra_backend.execution.cooldowns`。

    (data, corrupt)。损坏≠缺失：corrupt 时 is_in_stop_cooldown fail-closed。
    """
    return _cooldowns_read_state(STOP_COOLDOWN_FILE)


def load_stop_cooldowns() -> Dict[str, Any]:
    return _cooldowns_load(STOP_COOLDOWN_FILE)


def _atomic_write_json(path, payload) -> None:
    """审计③：与 trader._atomic_write_json / secrets 同路数（mkstemp+fsync+replace）。"""
    import tempfile
    d = str(Path(path).parent)
    fd, tmp = tempfile.mkstemp(prefix="." + Path(path).name + "-", dir=d)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def add_stop_cooldown(inst_id: str, side: str, reason: str = "止损冷却") -> None:
    """薄壳：转调单一事实源（`cooldowns.add_stop_cooldown`，第一百四十八刀）。

    ⚠️ 文件路径与原子写函数都**在调用时**从本模块全局解析（测试会 patch
    `cb.STOP_COOLDOWN_FILE`；import 期烘焙会让补丁静默失效）。
    """
    return _cooldowns_add(inst_id, side, STOP_COOLDOWN_FILE, reason=reason,
                          atomic_write_json=_atomic_write_json)


def is_in_stop_cooldown(inst_id: str, side: str) -> bool:
    """薄壳：转调单一事实源（结构优化阶段 4·B3 第五十刀）。

    ⚠️ 冷却时长按全局名在调用时读取（本模块**不在**
    `pin_baseline_risk_env()` 的重载名单里，故与改动前读 `STOP_COOLDOWN_MINUTES`
    静态导入名的行为**完全等价**）。
    """
    return _cooldowns_is_in(inst_id, side, STOP_COOLDOWN_FILE,
                            STOP_COOLDOWN_MINUTES * 60)


def check_black_swan_sentinel(fetch_candles_fn=None) -> Tuple[bool, str]:
    """Minute-level Black Swan Sentinel: fail-closed against extreme plunges and severe news."""
    if fetch_candles_fn is None:
        from scripts.market_data_service import fetch_candles
        fetch_candles_fn = fetch_candles

    try:
        candles = fetch_candles_fn("BTC-USDT-SWAP", bar="15m", limit=3)
    except Exception as exc:
        return True, f"🚨 黑天鹅熔断：统一行情通道异常 ({type(exc).__name__})，不可判定=不放松，保守暂停新开仓"
    if not candles or len(candles) < 2:
        return True, "🚨 黑天鹅熔断：统一行情通道无有效数据（双域+备源皆断），不可判定=不放松，保守暂停新开仓"
    try:
        latest_c = candles[0]
        c_open = float(latest_c[1])
        c_close = float(latest_c[4])
        c_low = float(latest_c[3])
        drop_pct = (c_close - c_open) / c_open * 100.0
        if drop_pct <= -3.0 or ((c_low - c_open) / c_open * 100.0 <= -4.0):
            return True, f"🚨 监测到 BTC 15M 级别发生断崖式暴跌插针 ({drop_pct:.2f}%)，触发全网黑天鹅紧急熔断！"
    except (ValueError, TypeError, IndexError):
        return True, "🚨 黑天鹅熔断：行情数据格式异常不可判定，不可判定=不放松，保守暂停新开仓"

    if NEWS_SENTIMENT_FILE.exists():
        try:
            with open(NEWS_SENTIMENT_FILE, "r", encoding="utf-8") as f:
                n_data = json.load(f)
            raw_score = n_data.get("overall_score")
            if raw_score is not None:
                score = float(raw_score)
                if score <= 20.0:
                    return True, f"🚨 监测到突发黑天鹅极度恶性利空舆情 (情绪指数: {score:.1f})，触发全网黑天鹅紧急熔断！"
        except Exception:
            return True, "🚨 黑天鹅熔断：新闻情绪缓存损坏不可判定，不可判定=不放松，保守暂停新开仓"

    return False, ""


def is_circuit_breaker_active(usdt_available: Optional[float] = None, fetch_candles_fn=None) -> Tuple[bool, str]:
    """Unified circuit breaker check combining black swan sentinel, state file, and daily loss."""
    bs_active, bs_reason = check_black_swan_sentinel(fetch_candles_fn=fetch_candles_fn)
    if bs_active:
        return True, bs_reason

    if CIRCUIT_BREAKER_FILE.exists():
        try:
            with open(CIRCUIT_BREAKER_FILE, "r", encoding="utf-8") as f:
                cb = json.load(f)
            expires_at = float(cb.get("expires_at_ts", 0) or 0)
            active = bool(cb.get("active")) or cb.get("status") == "triggered"
            if active and (expires_at <= 0 or time.time() < expires_at):
                return True, cb.get("reason") or cb.get("headline") or "黑天鹅极端行情熔断中"
        except Exception as e:
            return True, f"熔断状态文件损坏，安全暂停开仓: {e}"

    if LEDGER_JSON_FILE.exists():
        # 2026-11-17：台账同步旁车不再参与熔断（单所口径，失败只在 data_health 报
        # PARTIAL）。这里只保留当日亏损限额这条独立风险闸门。
        try:
            with open(LEDGER_JSON_FILE, "r", encoding="utf-8") as f:
                ledger = json.load(f)
            tz_bj = datetime.timezone(datetime.timedelta(hours=8))
            today_str = datetime.datetime.now(tz_bj).strftime("%Y-%m-%d")
            try:
                from scripts.okx_runtime import current_environment
                _mode = str(current_environment().mode or "")
            except Exception:
                _mode = ""  # 环境不可判 → ledger_daily_closed_pnl 保守全计
            today_pnl = ledger_daily_closed_pnl(ledger, _mode, today_str)
            _loss_cap = effective_daily_loss_limit(usdt_available)
            if today_pnl < -_loss_cap:
                return True, f"今日累计回撤 ({today_pnl:.2f}U) 触及单日最大风控熔断限额 ({_loss_cap}U｜按可用余额自适应)"
        except Exception as e:
            return True, f"日亏损风控数据读取失败，安全暂停开仓: {e}"

    return False, ""
