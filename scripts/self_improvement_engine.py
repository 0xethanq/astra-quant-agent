#!/usr/bin/env python3
"""
ASTRA AI LLM-Native Self-Improvement & Strategy Evolution Engine v6.8.1 (self_improvement_engine.py)
Focuses purely on Crypto Alpha generation & dynamic quantitative risk adaptation.
Eliminates rigid cooldown bans in favor of dynamic volatility-adjusted thresholds,
asymmetric Kelly bet-sizing, and LLM cognitive post-mortem lessons.
"""

import os
import sys
import json
import time
import datetime
import urllib.request
import tempfile
import fcntl
import hashlib
from typing import Dict, Any, List, Optional, Tuple

from pathlib import Path

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROOT = Path(PROJECT_ROOT)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

try:
    from astra_backend.config import settings as standalone_settings
except ImportError:
    standalone_settings = None

WORKSPACE_DIR = PROJECT_ROOT
DATA_DIR = os.path.join(WORKSPACE_DIR, "data")
LOGS_DIR = os.path.join(WORKSPACE_DIR, "logs")

LEDGER_JSON_FILE = os.path.join(DATA_DIR, "trading_ledger.json")
REPORT_JSON_FILE = os.path.join(DATA_DIR, "self_improvement_report.json")
AI_DECISIONS_FILE = os.path.join(DATA_DIR, "ai_brain_decisions.json")
AI_MEMORY_FILE = os.path.join(DATA_DIR, "ai_trading_memory.json")
AI_MEMORY_MD_FILE = os.path.join(DATA_DIR, "AI_TRADING_MEMORY.md")
EVOLUTION_LAST_PROMPT_FILE = os.path.join(DATA_DIR, "self_improvement_last_prompt.txt")
LOG_FILE = os.path.join(LOGS_DIR, "self_improvement.log")
EVOLUTION_LOCK_FILE = os.path.join(DATA_DIR, ".self_improvement.lock")

from astra_backend.time_utils import parse_beijing
from astra_backend.version import __version__
from instrument_pool import load_instruments
from prompt_library import active_profile, apply_module_layout
from astra_gateway.telemetry import ModelCallTelemetry

# 结构优化阶段 4·B3 第四十二刀：数理快照可观测性聚簇外提到 scripts/evolution/observability.py。
# 这里**再导出**（不是搬空）——外部 `from scripts.self_improvement_engine import
# EVOLUTION_SYSTEM_PROMPT` 式的引用与既有测试都按门面名解析，故门面必须继续提供。
# ⚠️ 注意：`SNAPSHOT_MAX_STALE_SECONDS` / `SIDE_ALIASES` **留在本文件** ——
# 它们属于 join 侧（`_match_snapshot`），不属于可观测性判定。
from scripts.evolution.memory_review import apply_memory_review
from scripts.evolution.review_context import (
    build_host_constitution,
    normalize_asset_multipliers,
    parse_review_json,
    summarize_closed_trades,
)
from scripts.evolution.report import build_evolution_report
from scripts.evolution.observability import (  # noqa: E402,F401
    DYNAMICS_FIELDS,
    DYNAMICS_OBSERVED_MIN,
    RETIRED_DYNAMICS_FIELDS,
    _parse_bj,
    audit_snapshot_observability,
    classify_snapshot_observability,
    prune_snapshot,
    render_observability_brief,
)
from llm_credentials import get_cpa_client_config as _get_cpa_client_config  # noqa: E402
from astra_backend.math_utils import clamp as _clamp
TARGET_INSTRUMENTS = [item["name"] for item in load_instruments()]

def atomic_write_json(path: str, payload: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".evolution-", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def clamp(value, lower, upper, default):
    """把 value 夹到 [lower, upper]；不可比较时返回 default。

    结构优化阶段 4·B3 第五十一刀：本函数与 ``scripts/trader/signals.py`` 的同名函数原为逐字重复，
    已收敛到 `astra_backend.math_utils.clamp`。

    ⚠️ 名字保留在本模块：调用点按全局名查找，且 `patch.object(模块, "clamp")`
    是既有接缝（别名赋值会让它失效）。
    """
    return _clamp(value, lower, upper, default)


def single_evolution_cycle(func):
    def wrapped(*args, **kwargs):
        lock_handle = open(EVOLUTION_LOCK_FILE, "a+", encoding="utf-8")
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            lock_handle.close()
            log_msg("Self-evolution skipped: another cycle is still running")
            return None
        try:
            return func(*args, **kwargs)
        finally:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            lock_handle.close()
    return wrapped


def _log_file() -> str:
    """调用时解析（审计卫生）：测试未 patch LOG_FILE 时（如 evolution_fallback_model
    的异常路径）不再污染生产 logs/self_improvement.log。ASTRA_SELF_IMPROVEMENT_LOG
    覆盖 + tests/__init__.py 统一隔离；生产默认不变。"""
    return os.environ.get("ASTRA_SELF_IMPROVEMENT_LOG") or LOG_FILE


def log_msg(msg: str):
    tz_bj = datetime.timezone(datetime.timedelta(hours=8))
    timestamp = datetime.datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    try:
        target = _log_file()
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass

def get_cpa_client_config() -> Tuple[str, str]:
    """薄壳：调用时解析门面全局，使测试的 patch / 直接赋值生效。

    实现已迁往 astra_backend.llm.credentials（结构优化阶段 4·B3 第四十六刀）。
    ⚠️ `standalone_settings` 必须**在这里**读取后传入 —— 门面全局会被测试
    patch / 原地 reload，子模块 import 期绑定会读到陈旧副本。
    """
    return _get_cpa_client_config(standalone_settings)

# =============================================================================
# 数理快照可观测性（宿主确定性审计，2026-09-10）
# 事故链：build_signal_snapshot 旧版 schema 错配（09-09 已修复写入侧）导致历史
# journal 全部为「对象存在但 22/17 动力学字段 null」的空壳；宿主把空壳原样喂给
# 模型，模型只能自数 null，既易漂移，也给「倒推伪造」留了口子。从此由宿主逐单
# 判定可观测性并把统计结论前置注入 Prompt；join 侧同时禁止用未来或过期快照
# 回填因果证据。
# =============================================================================
SNAPSHOT_MAX_STALE_SECONDS = 6 * 3600
#: 限价单撮合成交后、在下一个 15 分钟巡检周期首次被 trackers 建档捕获的最大时差（20分钟）
SNAPSHOT_MAX_POST_FILL_LAG_SECONDS = 1200
SIDE_ALIASES = {"多": "long", "空": "short", "long": "long", "short": "short"}


#: 复盘调用失败的**分类标记**（决定重试策略，2026-09-30）。
#: 背景：一次只错在"字符串里裸换行"的回复，因为唯一回退模型欠费而整轮零产出。
_PARSE_ERROR_MARKERS = (
    "JSONDecodeError", "Expecting value", "Expecting ',' delimiter",
    "Expecting property name", "Expecting ':' delimiter", "Invalid control character",
    "Unterminated string", "Extra data", "Invalid \\escape",
)
_BILLING_AUTH_ERROR_MARKERS = (
    "402", "401", "403", "INSUFFICIENT_BALANCE", "insufficient_balance", "insufficient balance",
    "余额不足", "Unauthorized", "unauthorized", "invalid_api_key", "Invalid API key",
    "account_deactivated", "quota",
)

#: 同模型修复重试时追加到 **user** 消息的格式指令。
EVOLUTION_JSON_REPAIR_HINT = (
    "【格式修复要求】你上一次的回复不是合法 JSON（解析在字符层面失败）。"
    "现在请**只输出一个 JSON 对象**，并严格遵守："
    "① 字符串内部严禁出现裸换行或制表符 —— 需要换行时写成 \\n 转义；"
    "② 严禁尾逗号（数组/对象最后一项后面不要逗号）；"
    "③ 不要输出任何解释性文字、前后缀或 Markdown 代码围栏。"
)


def classify_evolution_llm_error(message: str) -> str:
    """把复盘调用失败分成 `parse` / `billing` / `transport` 三类。

    - `parse`：模型回复**语法**不合法（可零成本同模型修一次）；
    - `billing`：计费/鉴权不可用（换再多模型也没用，须跳过该候选）；
    - `transport`：网关/超时等其余情况（沿用既有"换一个模型试一次"策略）。
    """
    text = str(message or "")
    if any(marker in text for marker in _PARSE_ERROR_MARKERS):
        return "parse"
    if any(marker in text for marker in _BILLING_AUTH_ERROR_MARKERS):
        return "billing"
    return "transport"


#: 回退候选"计费/鉴权不可用"的**运行态冷却**（2026-09-30）。
#:
#: ⚠️ 边界（与 `astra_backend/llm/model_health.py` 的分工，务必别混）：
#: `model_health` 判的是**结构可得性**（密钥/供应商/格式），并明确拒绝把一次 402
#: 写成永久"死条目"——"充值后它仍然是死的"会让配置页撒谎。
#: 这里判的是**运行态**，故必须是**带时限**的冷却：窗口过期自动恢复，任何一次成功也立即解除。
#: 它只作用于**自进化复盘的回退选择**，绝不写回用户配置、绝不出现在结构自检报告里。
EVOLUTION_MODEL_COOLDOWN_FILE = os.path.join(DATA_DIR, "evolution_model_cooldown.json")


def _cooldown_file() -> str:
    """**调用时**解析冷却文件路径（与 `_log_file` 同纪律）。

    ⚠️ 必须可重定向：测试会话碰巧触发一次 402，就会把冷却状态写进**生产** `data/`
    （本刀实测：`data/evolution_model_cooldown.json` 被测试写过一次）。
    生产从不设置 `ASTRA_EVOLUTION_MODEL_COOLDOWN_FILE` ⇒ 生产路径逐字不变。
    """
    return os.environ.get("ASTRA_EVOLUTION_MODEL_COOLDOWN_FILE") or EVOLUTION_MODEL_COOLDOWN_FILE
#: 默认冷却 60 分钟：足够覆盖同一轮调度与相邻周期，又短于下一次 6 小时复盘。
EVOLUTION_MODEL_COOLDOWN_SECONDS = 3600.0


def _cooldown_window_seconds() -> float:
    """冷却窗口（秒）。`ASTRA_EVOLUTION_MODEL_COOLDOWN_SECONDS` 可覆盖（测试与运维用）。"""
    raw = os.environ.get("ASTRA_EVOLUTION_MODEL_COOLDOWN_SECONDS")
    if raw is None or str(raw).strip() == "":
        return EVOLUTION_MODEL_COOLDOWN_SECONDS
    try:
        return max(0.0, float(raw))
    except (TypeError, ValueError):
        return EVOLUTION_MODEL_COOLDOWN_SECONDS


def load_model_cooldowns(now: Optional[float] = None) -> Dict[str, float]:
    """读取冷却表 `{model_id: 到期时间戳}`，**顺带剔除已过期项**。

    读不到/损坏一律当"无冷却"（绝不因为一个状态文件坏掉就停掉整条回退链）。
    """
    current = time.time() if now is None else float(now)
    try:
        with open(_cooldown_file(), "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError):
        return {}
    entries = raw.get("cooldowns") if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        return {}
    out: Dict[str, float] = {}
    for model_id, until in entries.items():
        try:
            until_f = float(until)
        except (TypeError, ValueError):
            continue
        if str(model_id).strip() and until_f > current:
            out[str(model_id)] = until_f
    return out


def model_in_cooldown(model_id: str, now: Optional[float] = None) -> bool:
    """该模型是否仍在"计费/鉴权不可用"冷却窗口内。"""
    return str(model_id or "").strip() in load_model_cooldowns(now)


def note_model_billing_failure(model_id: str, reason: str = "", now: Optional[float] = None) -> float:
    """记一次"计费/鉴权不可用"，返回冷却到期时间戳；返回 0 表示没记成。

    只在**真的**判定为 `billing` 类失败时调用（由 `classify_evolution_llm_error` 决定）。
    """
    model_id = str(model_id or "").strip()
    if not model_id:
        return 0.0
    current = time.time() if now is None else float(now)
    window = _cooldown_window_seconds()
    if window <= 0:
        return 0.0
    until = current + window
    cooldowns = load_model_cooldowns(current)
    cooldowns[model_id] = until
    try:
        atomic_write_json(_cooldown_file(), {
            "cooldowns": cooldowns,
            "updated_at": current,
            "last_reason": f"{model_id}: {str(reason or '')[:200]}",
        })
    except OSError:
        return 0.0
    return until


def clear_model_cooldown(model_id: str) -> bool:
    """解除某模型的冷却（某次调用成功、或真机探针通过时调用）。返回是否真的清掉了。"""
    model_id = str(model_id or "").strip()
    if not model_id:
        return False
    cooldowns = load_model_cooldowns()
    if model_id not in cooldowns:
        return False
    cooldowns.pop(model_id, None)
    try:
        atomic_write_json(_cooldown_file(), {
            "cooldowns": cooldowns, "updated_at": time.time(),
            "last_reason": f"{model_id}: cleared",
        })
    except OSError:
        return False
    return True


def _evolution_fallback_candidates() -> List[str]:
    """池内候选回退模型（同网关优先），按序、去重。**已冷却的候选被剔除。**

    同网关优先（2026-09-10）：模型池可能横跨多域名（tokenrhythm/cpa 混布），
    死域上的席位（如 cpa 的 gemini）回退过去也是 400/504，故先选与激活模型
    同 base_url 的健康池成员，其次才考虑异域名候选。

    刻意只作用于自进化复盘调用——交易主脑的选模与回退链是风险行为，
    调整需用户批准（`fallback_model_ids` 属全局配置，本函数绝不改写）。
    """
    try:
        from astra_backend.llm_manager import init_llm_config
        cfg = init_llm_config() or {}
        active = str(cfg.get("active_model_id") or "").strip()
        models = [m for m in (cfg.get("models") or []) if isinstance(m, dict)]
        active_base = ""
        for m in models:
            if str(m.get("id") or "").strip() == active:
                active_base = str(m.get("base_url") or "").strip()
                break
        same_gw, other_gw = [], []
        for m in models:
            mid = str(m.get("id") or "").strip()
            if not mid or mid == active:
                continue
            (same_gw if str(m.get("base_url") or "").strip() == active_base else other_gw).append(mid)
        seen: List[str] = []
        for mid in same_gw + other_gw:
            if mid not in seen:
                seen.append(mid)
        # 剔除"计费/鉴权不可用"冷却中的候选（2026-09-30）。
        # 实测：`glm-5.3-flash` 自 2026-09-13 起每轮都回 402，却仍被当作唯一回退位
        # 反复尝试 —— 每次都白花一次调用与数秒延迟，还把"回退尝试记录"污染成噪音。
        # 冷却到期的候选**会**自动回到列表（这不是永久判死，见模块级注释的边界说明）。
        cooled = load_model_cooldowns()
        if cooled:
            kept: List[str] = []
            for mid in seen:
                if mid in cooled:
                    remain = int(max(0.0, cooled[mid] - time.time()))
                    log_msg(f"⏭️ 回退候选 {mid} 处于计费/鉴权冷却中（剩余约 {remain}s），本轮不尝试")
                    continue
                kept.append(mid)
            return kept
        return seen
    except Exception as exc:
        log_msg(f"复盘回退模型解析失败: {exc}")
    return []


def evolution_fallback_model() -> Optional[str]:
    """复盘专属回退模型：主模型网关故障时，按后台模型池顺序选**下一个**候选。

    壳：真正的候选枚举在 `_evolution_fallback_candidates`（2026-09-30 拆出，
    便于回退链按序跳过"计费/鉴权不可用"的候选）。本函数保持"只返回首个候选"
    的既有契约 —— 编排层与既有专测面都按它打桩。
    """
    candidates = _evolution_fallback_candidates()
    return candidates[0] if candidates else None


def evolution_fallback_models(limit: int = 2) -> List[str]:
    """回退候选列表（同网关优先，去重），最多 `limit` 个。

    `limit` 默认 2：一个欠费/无鉴权的候选不该吃掉全部回退机会。
    """
    return _evolution_fallback_candidates()[:max(1, int(limit))]


def load_signal_journal():
    """读取开仓时刻的数理快照日志，按标的分组，供平仓台账 join 真实因果证据。"""
    journal_file = os.path.join(DATA_DIR, "signal_journal.json")
    by_inst = {}
    if not os.path.exists(journal_file):
        return by_inst
    try:
        with open(journal_file, "r", encoding="utf-8") as f:
            for rec in json.load(f):
                inst = str(rec.get("name") or rec.get("inst") or "")
                if inst:
                    by_inst.setdefault(inst, []).append(rec)
    except Exception as e:
        log_msg(f"读取 signal_journal 异常: {e}")
    return by_inst


def _match_snapshot(journal_by_inst, inst, open_time, side=None):
    """按方向与开仓时间就近匹配开仓时刻快照。

    因果铁律与巡检容差（2026-09-18）：
    1. 方向必须一致——台账方向可解析且 journal 记录带方向时，不一致者跳过，
       防止把空头开仓快照当多头成因；
    2. 允许 15 分钟巡检时差——限价单挂单撮合成交后，持仓在下一个 15 分钟巡检周期
       首次被 trackers 建档并写入快照（entryTime 略晚于 open_time 几分钟至 15 分钟），
       允许 [open_dt - 6h, open_dt + 20min] 的合理首巡检窗口，杜绝误杀真实开仓快照；
    3. 禁止远期未来快照——开仓 20 分钟之后的快照绝非开仓因果现场，一律返回 None；
    4. 禁止过期证据——快照早于开仓超过 SNAPSHOT_MAX_STALE_SECONDS 即非本次开仓
       的因果现场，弃用。
    """
    candidates = journal_by_inst.get(inst) or []
    open_dt = _parse_bj(open_time)
    if not candidates or open_dt is None:
        return None
    wanted_side = SIDE_ALIASES.get(str(side or "").strip())
    best_diff, best_rec = None, None
    for rec in candidates:
        rec_side = SIDE_ALIASES.get(str(rec.get("side") or "").strip())
        if wanted_side and rec_side and rec_side != wanted_side:
            continue
        rec_dt = _parse_bj(rec.get("entryTime"))
        if rec_dt is None:
            continue
        delta_sec = (rec_dt - open_dt).total_seconds()
        if delta_sec < -SNAPSHOT_MAX_STALE_SECONDS or delta_sec > SNAPSHOT_MAX_POST_FILL_LAG_SECONDS:
            continue
        abs_diff = abs(delta_sec)
        if best_diff is None or abs_diff < best_diff:
            best_diff, best_rec = abs_diff, rec
    return (best_rec or {}).get("snapshot")


def load_closed_trades(start_time_override: str | None = None):
    account_init_file = os.path.join(DATA_DIR, "account_initial_state.json")
    reset_time_str = "1970-01-01 00:00:00"
    evo_start_str = os.getenv("ASTRA_EVOLUTION_START_TIME", "").strip()
    if os.path.exists(account_init_file):
        try:
            with open(account_init_file, "r", encoding="utf-8") as f:
                acc_init = json.load(f)
                reset_time_str = str(acc_init.get("reset_time") or "1970-01-01 00:00:00")
                if not evo_start_str:
                    evo_start_str = str(acc_init.get("evolution_start_time") or "").strip()
        except Exception:
            pass

    # 确定自进化复盘起始时间（过滤更早的人工历史交易，杜绝远古历史单污染自进化）：
    # 显式入参 > 环境变量 ASTRA_EVOLUTION_START_TIME > account_initial_state.json evolution_start_time > reset_time > 默认 2026-09-01 00:00:00
    effective_start = (
        start_time_override
        or evo_start_str
        or (reset_time_str if reset_time_str > "2026-01-01 00:00:00" else "2026-09-01 00:00:00")
    ).strip()
    if len(effective_start) == 10:
        effective_start = f"{effective_start} 00:00:00"

    journal_by_inst = load_signal_journal()
    closed_trades = []
    if os.path.exists(LEDGER_JSON_FILE):
        try:
            with open(LEDGER_JSON_FILE, "r", encoding="utf-8") as f:
                t_list = json.load(f)
                for t in t_list:
                    if t.get("status") == "holding":
                        continue

                    # OKX专用化：严格过滤非OKX（如历史残留的 Binance / Gate）订单
                    venue = str(t.get("venue") or t.get("exchange") or "okx").lower()
                    if venue != "okx":
                        continue
                    
                    c_time = str(t.get("close_time") or t.get("time") or "")
                    o_time = str(t.get("open_time") or "")
                    # 时间过滤器：若平仓或开仓早于自进化起始时间，则不纳入复盘
                    check_time = c_time or o_time
                    if check_time and check_time < effective_start:
                        continue

                    inst = str(t.get("inst") or t.get("name") or "OTHER")
                    if inst not in TARGET_INSTRUMENTS:
                        continue
                    pnl = float(t.get("pnl", 0.0) or 0.0)
                    gross = float(t.get("gross_pnl", pnl) or pnl)
                    fee = abs(float(t.get("fee", 0.0) or 0.0))
                    strat = str(t.get("strategy") or "⚡ 趋势")
                    reason = str(t.get("exit_reason") or t.get("remark") or "")

                    # join 铁律：方向一致、非未来、非过期；宿主逐单标注可观测性
                    #
                    # 证据优先级（2026-10）：**台账内嵌的 `entry_snapshot` 最权威**
                    # （由 `close_evidence` 在平仓前钉死、`sync_full_ledger` join 进来），
                    # 其次才是 journal 时间窗匹配（旧口径，容差宽、易错配）。
                    # 原 `calculus_snapshot.json` 兜底已随数理退役链整体剥离（无证据即标 NONE，绝不伪造）。
                    raw_side = str(t.get("side") or t.get("direction") or "")
                    snap = (t.get("entry_snapshot")
                            or t.get("signal_snapshot")
                            or _match_snapshot(journal_by_inst, inst, t.get("open_time"), raw_side))
                    observability = classify_snapshot_observability(snap)
                    closed_trades.append({
                        "inst": inst,
                        "side": raw_side,
                        "time": c_time,
                        "open_time": t.get("open_time", ""),
                        "strategy": strat,
                        "margin": t.get("margin", "--"),
                        "gross_pnl": round(gross, 2),
                        "fee": round(fee, 2),
                        "net_pnl": round(pnl, 2),
                        "exit_reason": reason,
                        "snapshot_observability": observability,
                        "entry_snapshot": prune_snapshot(snap),
                        # ── 2026-10：离场证据与决策来源（台账 join 进来的新字段）──
                        # `exit_cause` 是**机制确认**的机器标签；`exit_reason_source`
                        # 说明这条标签是事实还是交易所侧推断（`inferred`）。
                        # `mfe_r`/`mae_r` 需要初始止损距离当 1R 分母，取不到时为 None。
                        "exit_cause": str(t.get("exit_cause") or ""),
                        "exit_reason_source": str(t.get("exit_reason_source") or ""),
                        "mfe_pct": t.get("mfe_pct"),
                        "mae_pct": t.get("mae_pct"),
                        "mfe_r": t.get("mfe_r"),
                        "mae_r": t.get("mae_r"),
                        "decision_source": str(t.get("decision_source") or ""),
                        "adopted_role": t.get("adopted_role"),
                    })
        except Exception as e:
            log_msg(f"读取交易台账异常: {e}")

    return closed_trades

# ── 自进化系统提示词：正文已迁出代码（2026-09-30 重构，用户批准）──────────────
# 空串意味着"这条管线没有代码基座"：`apply_module_layout` 直接按
# `data/prompt_library.json` 里 `evolution_system` 的方案模块编排。
# 唯一留在代码里的是**宿主宪章**（`scripts/evolution/review_context.py::
# build_host_constitution`）—— 那是 Code is Law 的硬约束，在 layout **之后**强制
# 追加，方案只能调措辞风格，无法删改证据纪律（与只读 JSON Schema 同一族）。
EVOLUTION_SYSTEM_PROMPT = ""

def resolve_memory_update(change_status: str, proposed_memory: Any, existing_memory: List[str]) -> Tuple[str, List[str], bool]:
    """Normalize LLM memory change and preserve existing lessons when evidence is insufficient."""
    status = str(change_status or "NO_CHANGE").upper()
    if status not in {"NO_CHANGE", "ADD", "REVISE", "INVALIDATE"}:
        status = "NO_CHANGE"
    proposed = proposed_memory if isinstance(proposed_memory, list) else []
    # 心法条目同受模型 schema 漂移影响，入库前统一压平为字符串
    proposed = [s for s in (_coerce_display_str(x) for x in proposed) if s]
    preserve = status == "NO_CHANGE" or not proposed
    return status, list(existing_memory if preserve else proposed), preserve


def merge_lesson_texts(change_status: str, proposed_texts: List[str],
                       existing_lessons: List[Dict[str, Any]]) -> List[str]:
    """心法合并（2026-10 起**只做去重与追加**，不再有宪法级保护）。

    历史：本函数原名 `merge_memory_with_constitution`，会把模型省略的"基准心法"
    （`is_baseline`）原样补回，因为它们是宪法级、大模型无权删除。用户已要求系统
    不再预设任何心法，且基准机制整体拆除，故"补回"这一半逻辑没有对象了 ——
    函数只保留仍然需要的部分：

    - **ADD 为纯追加**：现有全部条目保留 + 新增条目去重后置；
    - 其余状态（REVISE/INVALIDATE/NO_CHANGE）：采用模型给出的清单（已去重）；
      被省略的启用条目由 `_review_candidates` 落成**停用存档**，不会蒸发。

    ⚠️ 这里**不再有任何**"宿主强制补回"的行为 —— 那是基准机制的遗迹。
    """
    def _text(lesson):
        return _coerce_display_str(lesson.get("rule_text") or "")

    enabled = [l for l in (existing_lessons or []) if isinstance(l, dict) and l.get("enabled")]
    existing_texts = [t for t in (_text(l) for l in enabled) if t]

    final: List[str] = []
    for p in proposed_texts or []:
        t = _coerce_display_str(p)
        if t and t not in final:
            final.append(t)
    if change_status == "ADD":
        final = existing_texts + [t for t in final if t not in existing_texts]
    return final


def _compute_multi_dimensional_breakdown(closed_trades: List[Dict[str, Any]]) -> str:
    """计算多维战绩归因矩阵（标的、多空方向、出场形态、持仓时长与手续费磨损）。"""
    if not closed_trades:
        return "暂无平仓样本"

    sym_stats: Dict[str, Dict[str, Any]] = {}
    dir_stats = {"long": {"count": 0, "wins": 0, "pnl": 0.0}, "short": {"count": 0, "wins": 0, "pnl": 0.0}}
    exit_reasons: Dict[str, int] = {}
    gross_win = 0.0
    total_fee = 0.0

    for t in closed_trades:
        # ⚠️ 2026-10 修复：键名必须 `inst` 优先。
        # `load_closed_trades` 产出的条目用的是 `inst`（台账字段），而旧实现先取
        # `symbol`/`instId` —— 两者在台账行里**都不存在**，于是**全部交易塌成一个
        # `UNKNOWN` 桶**。实测发给模型的提示词里就一行：
        #     `• UNKNOWN: 37笔 (胜16/负21 | 胜率 43.2% | 净利 -349.97 USDT)`
        # —— 逐标的归因（复盘最有行动价值的一维）被整块抹平，而 `asset_multipliers`
        # 又完全由模型据此定夺、直接乘在真实保证金上。
        sym = str(t.get("inst") or t.get("symbol") or t.get("instId") or "UNKNOWN")
        side = str(t.get("side") or "").lower()
        d_key = "short" if ("short" in side or "空" in side) else "long"
        pnl = float(t.get("net_pnl") or 0.0)
        fee = float(t.get("fee") or 0.0)
        total_fee += fee
        if pnl > 0:
            gross_win += pnl

        if sym not in sym_stats:
            sym_stats[sym] = {"count": 0, "wins": 0, "pnl": 0.0}
        sym_stats[sym]["count"] += 1
        sym_stats[sym]["pnl"] += pnl
        if pnl > 0:
            sym_stats[sym]["wins"] += 1

        dir_stats[d_key]["count"] += 1
        dir_stats[d_key]["pnl"] += pnl
        if pnl > 0:
            dir_stats[d_key]["wins"] += 1

        reason = str(t.get("exit_reason") or t.get("reason") or "常规平仓")
        r_type = "止盈达成" if any(k in reason for k in ("止盈", "TP", "tp", "take_profit")) else (
            "止损触发" if any(k in reason for k in ("止损", "SL", "sl", "stop_loss")) else (
                "移动棘轮锁利" if any(k in reason for k in ("棘轮", "保本", "ratchet")) else "其他/主动结清"
            )
        )
        exit_reasons[r_type] = exit_reasons.get(r_type, 0) + 1

    lines = ["【多维量化战绩透视矩阵】:"]
    lines.append("- 标的胜负与净盈亏分布:")
    for sym, st in sorted(sym_stats.items(), key=lambda x: x[1]["pnl"], reverse=True):
        cnt = st["count"]
        w = st["wins"]
        wr = round(w / cnt * 100, 1) if cnt > 0 else 0.0
        lines.append(f"  • {sym}: {cnt}笔 (胜{w}/负{cnt-w} | 胜率 {wr}% | 净利 {st['pnl']:+.2f} USDT)")

    l_cnt, s_cnt = dir_stats["long"]["count"], dir_stats["short"]["count"]
    l_wr = round(dir_stats["long"]["wins"] / l_cnt * 100, 1) if l_cnt > 0 else 0.0
    s_wr = round(dir_stats["short"]["wins"] / s_cnt * 100, 1) if s_cnt > 0 else 0.0
    lines.append(f"- 多空方向偏向: 多头 {l_cnt}笔 (胜率 {l_wr}% | 净利 {dir_stats['long']['pnl']:+.2f} U) | 空头 {s_cnt}笔 (胜率 {s_wr}% | 净利 {dir_stats['short']['pnl']:+.2f} U)")

    r_parts = [f"{k}: {v}笔" for k, v in sorted(exit_reasons.items(), key=lambda x: x[1], reverse=True)]
    lines.append(f"- 出场形态分布: {', '.join(r_parts)}")

    fee_pct = round(total_fee / gross_win * 100, 1) if gross_win > 0 else 0.0
    lines.append(f"- 交易摩擦成本: 累计手续费 {total_fee:.2f} U (占毛利 {fee_pct}%)")

    try:
        mults_path = os.path.join(DATA_DIR, "asset_multipliers.json")
        if os.path.exists(mults_path):
            with open(mults_path, "r", encoding="utf-8") as f:
                cur_m = json.load(f).get("multipliers", {})
                if cur_m:
                    m_str = ", ".join(f"{k}: {v:.2f}x" for k, v in cur_m.items())
                    lines.append(f"- 当前标的自适应权重: {m_str}")
    except Exception:
        pass

    return "\n".join(lines)


def compose_evolution_prompts(closed_trades: List[Dict[str, Any]], existing_memory_md: str = "", timestamp_str: str = "") -> Tuple[str, str, str, Dict[str, int]]:
    """组装自进化 System/User 提示词，并前置注入宿主确定性数理快照可观测性审计与多维战绩矩阵。

    返回 (system, user, now_bj_str, snapshot_audit)。审计由宿主统计而非模型自数
    null，从结构上杜绝「表面有快照、实际全空值」诱发的倒推伪造。
    """
    tz_bj = datetime.timezone(datetime.timedelta(hours=8))
    now_bj_str = timestamp_str or datetime.datetime.now(tz_bj).strftime("%Y-%m-%d %H:%M:%S (北京时间)")

    (total, wins, losses, win_rate, total_net, total_fees, snapshot_audit, observability_brief) = summarize_closed_trades(
        audit_snapshot_observability=audit_snapshot_observability,
        closed_trades=closed_trades,
        render_observability_brief=render_observability_brief    )

    v_counts: Dict[str, int] = {}
    for t in closed_trades:
        v = str(t.get("venue") or "okx").upper()
        v_counts[v] = v_counts.get(v, 0) + 1
    v_summary = ", ".join(f"{v}: {c}笔" for v, c in sorted(v_counts.items())) if v_counts else "无"

    memory_context = f"""======================= 【当前系统已有的历史长期记忆库】 =======================
{existing_memory_md.strip()}
""" if existing_memory_md.strip() else "当前长期记忆库为空 (系统初始冷启动状态)"

    breakdown_text = _compute_multi_dimensional_breakdown(closed_trades)

    prompt = f"""======================= 【当前认知复盘基准时间】 =======================
【复盘基准时间】: {now_bj_str}

{memory_context}

======================= 【AstraQuant 加密量化实盘战绩与历史交易台账】 =======================
【统计汇总】:
- 总平仓笔数: {total} 笔 (胜 {len(wins)} / 负 {len(losses)} | 胜率: {win_rate}%)
- 跨交易所分布: {v_summary}
- 累计净盈亏: {total_net:+.2f} USDT | 累计手续费消耗: {total_fees:.2f} USDT
- 当前聚焦标的池: {TARGET_INSTRUMENTS}

{breakdown_text}

【逐笔历史交易明细 (按时间排序)】:
{json.dumps(closed_trades, indent=2, ensure_ascii=False)}

【复盘与长期记忆进化任务】:
请严格基于可观测台账证据与透视矩阵复盘。以宿主注入的「数理快照可观测性审计」为准：对 PRICE_ONLY / NONE 的交易不得输出任何数理因果，只能标注“数理快照不可观测”。证据不足时使用 NO_CHANGE，不得强行生成新规律。输出标准 JSON：
{{
  "change_status": "NO_CHANGE" | "ADD" | "REVISE" | "INVALIDATE",
  "diagnosis_insights": [
    "0~4 条有台账字段支持的诊断；每条以【战绩归因】/【风控审查】/【时段特征】等标签开头；区分已验证事实与待验证假设"
  ],
  "evolution_actions": [
    "0~4 条可执行改进；每条以【参数校准】/【执行优化】开头；证据不足时只提出数据采集或观察建议"
  ],
  "asset_multipliers": {{
    "BTC": 1.0,
    "ETH": 1.0
  }},
  "ai_long_term_memory": [
    "生效后的完整心法清单：必须原样包含现有全部基准心法（宿主会把省略的基准补回并留痕）；新增条目须有多个独立样本支持；严禁生成与现有心法同名或矛盾的冲突规则；严禁硬编码具体绝对金额（必须以 R、ATR 或风险预算比例表达）；不得覆盖任何硬风控"
  ],
  "memory_overwrites_reason": "说明证据支持何种变更；NO_CHANGE 时明确为何不覆盖旧记忆"
}}
"""

    profile = active_profile()
    runtime_context = {
        "decision_timestamp": now_bj_str, "timestamp": now_bj_str,
        "timestamp_beijing": now_bj_str,
        "trading_memory": existing_memory_md.strip(),
        "existing_memory_markdown": existing_memory_md.strip() or "当前长期记忆库为空 (系统初始冷启动状态)",
        "total": total, "wins": len(wins), "losses": len(losses), "win_rate": win_rate,
        "total_net": f"{total_net:+.2f}", "total_fees": f"{total_fees:.2f}",
        "target_instruments": ", ".join(TARGET_INSTRUMENTS),
        "closed_trades_json": json.dumps(closed_trades, indent=2, ensure_ascii=False),
        "active_instruments": ",".join(TARGET_INSTRUMENTS),
        "snapshot_observability_summary": observability_brief,
        "dynamics_observable_trades": snapshot_audit["math_observable"],
        "unobservable_trades": snapshot_audit["PRICE_ONLY"] + snapshot_audit["NONE"],
        "profile_name": profile.get("name", ""), "timezone": "Asia/Shanghai",
        "strategy_version": os.getenv("ASTRA_VERSION", f"v{__version__}"),
    }
    effective_evolution_system = apply_module_layout(EVOLUTION_SYSTEM_PROMPT, profile, "evolution_system", f"{profile.get('name', '稳健')}自进化系统提示词模板", context=runtime_context)
    effective_evolution_user = apply_module_layout(prompt, profile, "evolution_user", f"{profile.get('name', '稳健')}自进化用户提示词模板", context=runtime_context)
    # 宿主宪章：代码层硬约束，在风格档案 layout 之后强制追加——profile 只能调整
    # 措辞风格，永远无法删改证据纪律与基准心法保护（Code is Law，2026-09-10）。
    host_constitution = build_host_constitution(
        observability_brief=observability_brief    )
    effective_evolution_system = effective_evolution_system.rstrip() + host_constitution
    effective_evolution_user = effective_evolution_user.rstrip() + host_constitution
    return effective_evolution_system, effective_evolution_user, now_bj_str, snapshot_audit


def call_llm_evolution_review(closed_trades: List[Dict[str, Any]], existing_memory_md: str = "", timestamp_str: str = "",
                              model_override: Optional[str] = None,
                              repair_hint: str = "") -> Dict[str, Any]:
    """跑一次复盘 LLM 调用。

    `repair_hint`（2026-09-30）：**同模型修复重试**用的追加指令。上一次回复只错在
    格式（字符串内裸换行、尾逗号、前后散文）时，最省的做法是拿同一模型再问一次并
    明确点出格式要求 —— 而不是把唯一一次回退机会花在换模型上（实测换到的那个还欠费）。
    只有非空时才会被拼进 user 消息；默认 `""` ⇒ 行为与改造前逐字相同。
    """
    base_url, api_key = get_cpa_client_config()
    if not api_key:
        log_msg("[AI Evolution] Error: CPA API Key not found, using fallback heuristics.")
        return {}

    effective_evolution_system, effective_evolution_user, now_bj_str, _audit = compose_evolution_prompts(
        closed_trades, existing_memory_md=existing_memory_md, timestamp_str=timestamp_str)
    # 实发内容 = 基础 user 消息（+ 修复指令）。提示词快照与遥测都按**实发**记录，
    # 否则白盒快照会与真发出去的东西不一致。
    request_user_prompt = str(effective_evolution_user)
    if repair_hint:
        request_user_prompt = f"{request_user_prompt}\n\n{repair_hint}"
    try:
        snapshot = f"【SYSTEM PROMPT】:\n{effective_evolution_system.strip()}\n\n{'='*70}\n【USER PROMPT ({now_bj_str})】：\n{request_user_prompt.strip()}"
        fd, temp_path = tempfile.mkstemp(prefix=".evolution-prompt-", suffix=".tmp", dir=DATA_DIR)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(snapshot)
        os.replace(temp_path, EVOLUTION_LAST_PROMPT_FILE)
    except OSError:
        pass

    model_name = os.environ.get("LLM_MODEL") or ""
    effort = os.environ.get("LLM_REASONING_EFFORT") or "high"
    api_format = "openai_chat"
    thinking_timeout = max(90.0, float(os.environ.get("LLM_THINKING_TIMEOUT", os.environ.get("LLM_TIMEOUT_SECONDS", 120.0))))
    execute_llm_request = None

    try:
        from astra_backend.evolution_config import load_evolution_config, resolve_evolution_llm_runtime
        from astra_backend.llm_manager import execute_llm_request as _exec
        evo_cfg = load_evolution_config()
        evo_runtime = resolve_evolution_llm_runtime(evo_cfg)
        if evo_runtime:
            model_name = evo_runtime.get("model") or model_name
            base_url = evo_runtime.get("base_url") or base_url
            api_key = evo_runtime.get("api_key") or api_key
            api_format = evo_runtime.get("api_format") or "openai_chat"
            effort = os.environ.get("LLM_REASONING_EFFORT") or evo_runtime.get("reasoning_effort") or effort
            thinking_timeout = float(evo_runtime.get("thinking_timeout") or thinking_timeout)
        execute_llm_request = _exec
    except Exception:
        execute_llm_request = None

    if model_override:
        # 复盘专属回退/指定模型
        model_name = str(model_override)
        if execute_llm_request is not None:
            try:
                from astra_backend.llm_manager import resolve_model_runtime
                resolved_override = resolve_model_runtime(model_name)
                if resolved_override and resolved_override.get("model"):
                    base_url = resolved_override.get("base_url") or base_url
                    api_key = resolved_override.get("api_key") or api_key
                    api_format = resolved_override.get("api_format") or api_format
            except Exception:
                pass

    telemetry = ModelCallTelemetry(
        "self_improvement", model_name, str(effort), effective_evolution_system, request_user_prompt
    )
    try:
        t0 = time.time()
        log_msg(f"🚀 正在调用自进化专属引擎 {model_name} ({api_format} / 思考上限 {thinking_timeout:.0f}s / 推理强度 {effort}) 进行多维实战复盘与策略进化...")
        raw_res = None
        content = ""
        if execute_llm_request:
            content, _, usage_dict, _ = execute_llm_request(
                messages=[
                    {"role": "system", "content": effective_evolution_system},
                    {"role": "user", "content": request_user_prompt}
                ],
                model=model_name,
                base_url=base_url,
                api_key=api_key,
                api_format=api_format,
                reasoning_effort=effort,
                temperature=0.2,
                response_format={"type": "json_object"},
                timeout=thinking_timeout,
            )
            raw_res = {"usage": usage_dict} if isinstance(usage_dict, dict) else {}
        else:
            payload = {
                "model": model_name,
                "messages": [
                    {"role": "system", "content": effective_evolution_system},
                    {"role": "user", "content": request_user_prompt}
                ],
                "temperature": 0.2,
                "response_format": {"type": "json_object"}
            }
            if effort not in ("none", "auto"):
                payload["reasoning_effort"] = effort
            req = urllib.request.Request(
                f"{base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "Mozilla/5.0"}
            )
            with urllib.request.urlopen(req, timeout=thinking_timeout) as resp:
                res = json.loads(resp.read().decode("utf-8"))
                content = res["choices"][0]["message"]["content"].strip()
                raw_res = res

        content = (content or "").strip()
        content, review_json = parse_review_json(content=content)
        telemetry.finish("success", raw_res, output_chars=len(content))
        log_msg(f"✅ AI 大脑认知复盘完成 (耗时 {round(time.time() - t0, 2)}s)")
        return review_json
    except Exception as e:
        telemetry.finish("failed", error=e)
        log_msg(f"Error in LLM evolution review: {e}")
        # Surface the upstream failure in the dashboard report instead of silently
        # degrading to an unexplained NO_CHANGE (which looks like a stale cache).
        return {"__llm_error__": f"{type(e).__name__}: {e}"}


_TEXTISH_KEYS = (
    "observation", "detail", "text", "action", "content", "analysis",
    "finding", "summary", "description", "reason", "evidence",
)


def _coerce_display_str(item) -> str:
    """把复盘数组项归一为展示字符串。

    - 字符串原样；若内容是自序列化的 JSON（模型常见漂移）则解包递归处理；
    - 对象：优先【dimension/title/category】+ 已知正文字段；action_type 类对象
      用其作标题；无已知键时按 key:value 拼接，绝不落回 str(dict)。
    """
    if isinstance(item, str):
        s = item.strip()
        if s.startswith("{") or s.startswith("["):
            try:
                parsed = json.loads(s)
            except Exception:
                return s
            if isinstance(parsed, (dict, list)):
                return _coerce_display_str(parsed)
        return s
    if isinstance(item, dict):
        title = str(item.get("dimension") or item.get("title") or item.get("category")
                    or item.get("action_type") or "").strip()
        body = ""
        for k in _TEXTISH_KEYS:
            v = item.get(k)
            if isinstance(v, (str, int, float)) and str(v).strip():
                body = str(v).strip()
                break
        if not body:
            parts = [f"{k}:{v}" for k, v in item.items()
                     if not isinstance(v, (dict, list)) and str(v).strip() and k != "dimension"]
            body = "；".join(parts)
        if title and body and not body.startswith(f"【{title}】"):
            return f"【{title}】{body}"
        return body or title
    if isinstance(item, list):
        return "；".join(filter(None, (_coerce_display_str(x) for x in item)))
    return str(item).strip() if item is not None else ""


def _time_stop_hours_default() -> float:
    """时间止损阈值（小时）：与执行层同源，取不到时回落 8.0（`risk_constants` 现状）。"""
    try:
        from risk_constants import TIME_STOP_HOURS
        return float(TIME_STOP_HOURS)
    except Exception:
        try:
            from scripts.risk_constants import TIME_STOP_HOURS
            return float(TIME_STOP_HOURS)
        except Exception:
            return 8.0


#: 低于这个样本量时，只报"样本不足"，不产出结构性结论（防小样本幻觉）。
DETERMINISTIC_MIN_SAMPLE = 10
#: 兜底认知每条前缀：一眼可辨"这条不是模型说的"。
_DETERMINISTIC_PREFIX = "[本地台账推导]"


def derive_deterministic_insights(closed_trades: List[Dict[str, Any]],
                                  snapshot_audit: Dict[str, Any] = None,
                                  *, time_stop_hours: float = None) -> List[str]:
    """**LLM 全链失败时**的兜底认知：只用台账可观测事实，零编造、绝不改记忆。

    起因（2026-09-30）：主模型输出一个裸换行 + 唯一回退模型欠费 402 ⇒ 整轮复盘落成
    `insights: []`，用户看到的是"本轮没有产出任何新认知"——**看起来像系统没干活**。
    但即使模型不可用，台账里的事实（胜率、均亏/均盈比、离场原因分布、持仓时长、
    单标的期望）本来就足以产出有价值的认知，不该因为"模型挂了"而全部丢弃。

    边界（Code is Law）：
    - 只统计**可观测字段**，不做因果断言、不给策略建议式结论；
    - 每条都带 `[本地台账推导]` 前缀，与模型结论在界面上可区分；
    - 调用方据此**恒置 `change_status = NO_CHANGE`** —— 兜底认知绝不写入长期记忆；
    - 样本 < `DETERMINISTIC_MIN_SAMPLE` 时只报样本不足，不产出结构结论。
    """
    trades = [t for t in (closed_trades or []) if isinstance(t, dict)]
    if not trades:
        return [f"{_DETERMINISTIC_PREFIX} 账本内没有可观测的已平仓交易，无法形成认知。"]

    threshold = float(time_stop_hours if time_stop_hours is not None else _time_stop_hours_default())
    net_pnls = [_clamp(t.get("net_pnl"), -1e12, 1e12, 0.0) for t in trades]
    fees = [_clamp(t.get("fee"), -1e12, 1e12, 0.0) for t in trades]
    wins = [p for p in net_pnls if p > 0]
    losses = [p for p in net_pnls if p <= 0]
    total = len(trades)
    win_rate = round(len(wins) / total * 100, 1)
    net_total = sum(net_pnls)
    fee_total = sum(fees)
    insights: List[str] = []

    if total < DETERMINISTIC_MIN_SAMPLE:
        insights.append(
            f"{_DETERMINISTIC_PREFIX} 样本仅 {total} 笔（< {DETERMINISTIC_MIN_SAMPLE} 笔），"
            f"证据不足，本轮不形成结构性结论；胜率 {win_rate}%、净利 {net_total:+.2f} USDT。")
        return insights

    insights.append(
        f"{_DETERMINISTIC_PREFIX} 样本 {total} 笔：胜率 {win_rate}%、净利 {net_total:+.2f} USDT、"
        f"手续费 {fee_total:.2f} USDT。")

    if wins and losses:
        avg_win = sum(wins) / len(wins)
        avg_loss = abs(sum(losses) / len(losses))
        if avg_win > 0 and avg_loss > avg_win:
            insights.append(
                f"{_DETERMINISTIC_PREFIX} **赢小输大**：均盈 {avg_win:.2f} vs 均亏 -{avg_loss:.2f}"
                f"（单笔亏损是单笔盈利的 {avg_loss / avg_win:.2f} 倍）——"
                f"胜率再高也撑不住这个结构。")
        else:
            insights.append(
                f"{_DETERMINISTIC_PREFIX} 均盈 {avg_win:.2f} / 均亏 -{avg_loss:.2f}"
                f"（盈亏幅度比 {avg_win / avg_loss:.2f}）。")

    # 离场原因分布：只做归类计数，不推断原因。
    stop_like = sum(1 for t in trades
                    if any(k in str(t.get("exit_reason") or "") for k in ("止损", "保本")))
    tp_like = sum(1 for t in trades if "止盈" in str(t.get("exit_reason") or ""))
    if stop_like or tp_like:
        insights.append(
            f"{_DETERMINISTIC_PREFIX} 离场结构：止损/保本类 {stop_like} 笔（{stop_like / total * 100:.0f}%）、"
            f"止盈类 {tp_like} 笔（{tp_like / total * 100:.0f}%）。")

    # 快节奏履约：持仓时长 vs 时间止损阈值。
    durations: List[float] = []
    for t in trades:
        try:
            opened = datetime.datetime.strptime(str(t.get("open_time")), "%Y-%m-%d %H:%M:%S")
            closed = datetime.datetime.strptime(str(t.get("time")), "%Y-%m-%d %H:%M:%S")
            hours = (closed - opened).total_seconds() / 3600.0
            if hours >= 0:
                durations.append(hours)
        except (TypeError, ValueError):
            continue
    if durations:
        durations.sort()
        median = durations[len(durations) // 2]
        over = sum(1 for h in durations if h > threshold)
        insights.append(
            f"{_DETERMINISTIC_PREFIX} 持仓时长：中位 {median:.1f}h、最长 {durations[-1]:.1f}h；"
            f"超过 {threshold:.0f}h 时间止损阈值的 {over} 笔（{over / len(durations) * 100:.0f}%）。")

    # 单标的期望：只报最差与最好各一个。
    by_inst: Dict[str, List[float]] = {}
    for t, pnl in zip(trades, net_pnls):
        inst = str(t.get("inst") or "?").strip() or "?"
        by_inst.setdefault(inst, []).append(pnl)
    ranked = sorted(by_inst.items(), key=lambda kv: sum(kv[1]))
    if len(ranked) >= 2:
        worst_inst, worst_pnls = ranked[0]
        best_inst, best_pnls = ranked[-1]
        insights.append(
            f"{_DETERMINISTIC_PREFIX} 单标的期望：最差 {worst_inst} {len(worst_pnls)} 笔 "
            f"{sum(worst_pnls):+.2f} USDT；最好 {best_inst} {len(best_pnls)} 笔 "
            f"{sum(best_pnls):+.2f} USDT。")

    if isinstance(snapshot_audit, dict) and snapshot_audit.get("total"):
        observable = int(snapshot_audit.get("DYNAMICS_OBSERVED") or 0)
        insights.append(
            f"{_DETERMINISTIC_PREFIX} 数理快照可观测性：{observable}/{snapshot_audit.get('total')} "
            f"笔含完整动力学字段（不可观测的样本不得用于因果归因）。")

    # 离场质量（2026-10 方向 3）：回答"这笔本来能赚多少、吐回去多少"。
    # 这是确定性事实（全部由台账＋平仓证据算出），故放进兜底认知 —— 即便大模型
    # 全链失败，用户仍能看到回吐/兑现率，而不是"本轮没有产出任何新认知"。
    try:
        from scripts.evolution.exit_quality import (analyze_exit_quality,
                                                    render_exit_quality_brief)
        _exit_quality = analyze_exit_quality(closed_trades=trades)
        insights.append(f"{_DETERMINISTIC_PREFIX} " +
                        render_exit_quality_brief(_exit_quality).replace("\n", " "))
    except Exception as _eq_exc:
        log_msg(f"离场质量分析跳过（不影响复盘）: {_eq_exc}")

    return insights


@single_evolution_cycle
def run_self_evolution(force: bool = False):
    tz_bj = datetime.timezone(datetime.timedelta(hours=8))
    now_bj = datetime.datetime.now(tz_bj)
    timestamp_str = now_bj.strftime("%Y-%m-%d %H:%M:%S")
    log_msg(f"🧬 启动 AstraQuant AI 大脑自进化认知复盘与实战心法提炼 (v{__version__} Crypto Focus)...")

    closed_trades = load_closed_trades()
    total_trades = len(closed_trades)
    ledger_revision = hashlib.sha256(
        json.dumps(closed_trades, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    if not force and os.path.exists(REPORT_JSON_FILE):
        try:
            with open(REPORT_JSON_FILE, "r", encoding="utf-8") as f:
                previous_report = json.load(f)
            if previous_report.get("ledger_revision") == ledger_revision:
                log_msg("No new closed-trade evidence; keeping the current adaptive configuration")
                return previous_report
        except Exception:
            pass

    # 1. Base Stats
    win_trades = [t for t in closed_trades if t["net_pnl"] > 0]
    loss_trades = [t for t in closed_trades if t["net_pnl"] <= 0]
    win_count = len(win_trades)
    win_rate = round(win_count / total_trades * 100, 1) if total_trades > 0 else 0.0
    total_win_amt = sum(t["net_pnl"] for t in win_trades)
    total_loss_amt = abs(sum(t["net_pnl"] for t in loss_trades))
    total_fees_amt = sum(t["fee"] for t in closed_trades)
    profit_factor = round(total_win_amt / total_loss_amt, 2) if total_loss_amt > 0 else (99.0 if total_win_amt > 0 else 0.0)

    from scripts import evolution_shield as memory_service
    memory_snapshot, existing_memory_md, existing_core_lessons = memory_service.read_trading_context(
        AI_MEMORY_MD_FILE, AI_MEMORY_FILE)

    # 宿主确定性数理快照可观测性审计（写进报告，结论不依赖模型自数 null）
    snapshot_audit = audit_snapshot_observability(closed_trades)
    log_msg("🔬 数理快照可观测性审计: " + render_observability_brief(snapshot_audit))

    # 2. Call LLM for Cognitive Review & Memory Overwriting
    # 复盘预算守卫：调度器对子进程有 600s 硬超时，504 内部重试可达 ~560s。
    # 主调用超过 EVOLUTION_FALLBACK_BUDGET_SECONDS 后不再回退（回退大概率被腰斩，
    # 徒耗一池模型调用；本周期照常落 NO_CHANGE + 错误透传）。
    EVOLUTION_FALLBACK_BUDGET_SECONDS = 400.0
    cycle_t0 = time.time()
    llm_review = call_llm_evolution_review(closed_trades, existing_memory_md=existing_memory_md, timestamp_str=timestamp_str)
    if not isinstance(llm_review, dict):
        llm_review = {}
    # 复盘恢复链（2026-09-30 重排，起因：一次"字符串裸换行"的格式错误 + 唯一回退模型欠费
    # ⇒ 整轮复盘落成无解释的 NO_CHANGE + insights: []）。
    #   ① **格式类**失败 ⇒ 同模型带格式修复指令重试一次（零额外模型开销，不花回退位）；
    #   ② 仍失败 ⇒ 按序走回退候选，**跳过**计费/鉴权不可用的候选（402/401/403/欠费）；
    #   ③ 全部失败 ⇒ 把回退链诊断拼进 `__llm_error__`，让管理页显示可操作原因。
    # 复盘专属回退（2026-09-10 起）：交易主脑的选模与回退链不受影响。
    if llm_review.get("__llm_error__"):
        failure_kind = classify_evolution_llm_error(str(llm_review.get("__llm_error__")))
        if failure_kind == "parse" and (time.time() - cycle_t0) <= EVOLUTION_FALLBACK_BUDGET_SECONDS:
            log_msg("⚠️ 复盘主模型输出不是合法 JSON（格式类失败），同模型带格式修复指令重试一次")
            repaired = call_llm_evolution_review(
                closed_trades, existing_memory_md=existing_memory_md,
                timestamp_str=timestamp_str, repair_hint=EVOLUTION_JSON_REPAIR_HINT)
            if isinstance(repaired, dict) and repaired and not repaired.get("__llm_error__"):
                llm_review = repaired
                log_msg("✅ 同模型格式修复重试成功（未消耗回退位）")
    if llm_review.get("__llm_error__"):
        fallback_model = evolution_fallback_model()
        elapsed = time.time() - cycle_t0
        if fallback_model and elapsed > EVOLUTION_FALLBACK_BUDGET_SECONDS:
            log_msg(f"⏳ 复盘主模型已耗时 {elapsed:.0f}s 超预算 {EVOLUTION_FALLBACK_BUDGET_SECONDS:.0f}s，"
                    f"放弃回退避免调度器 600s 腰斩（NO_CHANGE + 错误透传）")
        elif fallback_model:
            # 首个候选取 `evolution_fallback_model()`（保持既有打桩面），其后候选按需补足。
            chain = [fallback_model]
            for candidate in evolution_fallback_models(limit=2):
                if candidate != fallback_model:
                    chain.append(candidate)
            attempts: List[str] = []
            for candidate in chain:
                log_msg(f"⚠️ 复盘主模型失败（{str(llm_review['__llm_error__'])[:120]}），回退 {candidate} 重试一次")
                fb_review = call_llm_evolution_review(
                    closed_trades, existing_memory_md=existing_memory_md,
                    timestamp_str=timestamp_str, model_override=candidate)
                if isinstance(fb_review, dict) and fb_review and not fb_review.get("__llm_error__"):
                    llm_review = fb_review
                    log_msg(f"✅ 回退模型 {candidate} 复盘完成（仅本周期；不改全局激活位）")
                    clear_model_cooldown(candidate)
                    break
                fb_error = str((fb_review or {}).get("__llm_error__") or "空回复")
                attempts.append(f"{candidate}: {fb_error[:160]}")
                if classify_evolution_llm_error(fb_error) == "billing":
                    # 冷却该候选：下一轮不再白试（窗口到期自动恢复，充了值就重新可用）。
                    until = note_model_billing_failure(candidate, fb_error)
                    if until:
                        log_msg(f"⏭️ 回退候选 {candidate} 计费/鉴权不可用，跳过并进入冷却至 "
                                f"{time.strftime('%H:%M:%S', time.localtime(until))}（窗口到期自动恢复）")
                    else:
                        log_msg(f"⏭️ 回退候选 {candidate} 计费/鉴权不可用，跳过并尝试下一个候选")
                    continue
                break
            if llm_review.get("__llm_error__") and attempts:
                # 回退链诊断并入既有 `llm_error`（**不新增报告键**：报告键集被
                # tests/extraction/test_evolution_report_extraction.py 精确钉住；
                # `llm_error` 本来就是"上游失败透出"的既有通道，前端已渲染它）。
                llm_review["__llm_error__"] = (
                    f"{llm_review['__llm_error__']}｜回退尝试: " + " ; ".join(attempts))

    change_status, _, _ = resolve_memory_update(llm_review.get("change_status", "NO_CHANGE"), [], [])
    insights = llm_review.get("diagnosis_insights", [])
    actions_taken = llm_review.get("evolution_actions", [])
    if not isinstance(insights, list):
        insights = []
    if not isinstance(actions_taken, list):
        actions_taken = []
    # 模型 schema 漂移归一：部分模型把数组项输出为对象（{dimension, analysis} /
    # {action_type, action}）或自序列化 JSON 字符串；不归一则前端渲染成
    # [object Object] / 原始 JSON（2026-09-09 用户截图）。统一压平成展示字符串。
    insights = [s for s in (_coerce_display_str(x) for x in insights) if s]
    actions_taken = [s for s in (_coerce_display_str(x) for x in actions_taken) if s]

    # 兜底认知（2026-09-30）：LLM 全链失败且一条洞察都没拿到时，用**台账可观测事实**
    # 产出认知，而不是让用户看到一片空白。Code is Law：这条路径**恒不改记忆**
    # （change_status 强制 NO_CHANGE，下面的 resolve_memory_update 因此不会写心法）。
    if llm_review.get("__llm_error__") and not insights:
        insights = derive_deterministic_insights(closed_trades, snapshot_audit)
        change_status = "NO_CHANGE"
        log_msg(f"🧾 LLM 复盘失败，已用台账确定性认知兜底 {len(insights)} 条"
                f"（只报事实、不改记忆；原始原因见 llm_error）")
    
    asset_mults = normalize_asset_multipliers(
        TARGET_INSTRUMENTS=TARGET_INSTRUMENTS,
        clamp=clamp,
        llm_review=llm_review    )
    change_status, long_term_memory, preserve_existing_memory = resolve_memory_update(
        change_status, llm_review.get("ai_long_term_memory", []), existing_core_lessons
    )

    retired_lessons: List[str] = []
    (preserve_existing_memory, retired_lessons) = apply_memory_review(
        change_status=change_status,
        log_msg=log_msg,
        long_term_memory=long_term_memory,
        memory_service=memory_service,
        memory_snapshot=memory_snapshot,
        merge_lesson_texts=merge_lesson_texts,
        preserve_existing_memory=preserve_existing_memory,
        retired_lessons=retired_lessons,
        total_trades=total_trades    )

    # 心法健康度重算（2026-10 方向 4）：把 `health_score` 从"建档时写死 90.0、
    # 此后再没人读"变成**承重件** —— 用本轮平仓证据给每条心法按"适用人群"打分，
    # 并按需归档（停用留痕、绝不删除、绝不触碰基准心法）。走 CAS，失败只记日志。
    #
    # 为什么放在 `apply_memory_review` **之后**：本轮新学的心法要先落库，才能在
    # 同一轮里被评估到；而重算只改分数/状态，不会让新心法绕过宪法门禁。
    try:
        _health_result = memory_service.refresh_health_from_evidence(
            closed_trades=closed_trades, log_msg=log_msg)
        if _health_result.get("status") == "error":
            log_msg(f"⚠️ 心法健康度未更新：{_health_result.get('reason')}")
    except Exception as _health_exc:
        log_msg(f"心法健康度重算跳过（不影响复盘）: {_health_exc}")

    # Keep the legacy markdown mirror in lock-step with the authority so the
    # public dashboard can never freeze on a hand-edited snapshot.
    try:
        if memory_service.sync_markdown_mirror():
            log_msg("🪞 AI_TRADING_MEMORY.md 已同步至结构化心法权威库")
    except Exception as exc:
        log_msg(f"Markdown mirror sync skipped: {exc}")

    # Persist asset multipliers to data/asset_multipliers.json so brain trader can consume
    try:
        mults_payload = {
            "timestamp": timestamp_str,
            "multipliers": asset_mults,
            "updated_by": "self_improvement_engine",
        }
        atomic_write_json(os.path.join(DATA_DIR, "asset_multipliers.json"), mults_payload)
    except Exception as exc:
        log_msg(f"Failed to persist asset multipliers: {exc}")

    # Reflect concurrent toggle/rollback even when the model returns NO_CHANGE.
    _, _, long_term_memory = memory_service.read_trading_context(AI_MEMORY_MD_FILE, AI_MEMORY_FILE)

    # 4. Save Dashboard Report
    report_payload = build_evolution_report(
        actions_taken=actions_taken,
        change_status=change_status,
        insights=insights,
        ledger_revision=ledger_revision,
        llm_review=llm_review,
        long_term_memory=long_term_memory,
        preserve_existing_memory=preserve_existing_memory,
        profit_factor=profit_factor,
        retired_lessons=retired_lessons,
        snapshot_audit=snapshot_audit,
        timestamp_str=timestamp_str,
        total_trades=total_trades,
        win_rate=win_rate    )

    atomic_write_json(REPORT_JSON_FILE, report_payload)

    log_msg(f"🧬 自进化认知复盘完成 | 状态={change_status} | 当前保留 {len(long_term_memory)} 条启发式长期记忆")
    try:
        from qq_notifier import notify_evolution_report
        top_lesson = long_term_memory[0] if long_term_memory else "保持风控原则"
        notify_evolution_report(win_rate, total_trades, change_status, top_lesson)
    except Exception as e:
        log_msg(f"自进化通知发送失败: {e}")
    return report_payload

if __name__ == "__main__":
    force_run = "--force" in sys.argv or "-f" in sys.argv
    res = run_self_evolution(force=force_run)
    print(json.dumps(res, indent=2, ensure_ascii=False))
