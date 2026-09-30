"""Prompt Cache Warmer（**默认关闭**）：把与生产**逐字节一致**的前缀保持温热。

## 为什么重写（2026-09-29 实测复盘）

旧实现发送的是 `scripts.ai_brain_trader.SYSTEM_PROMPT`（base 版，8165 字符），
而生产真正发送的是 `get_effective_system_prompt()`（profile 模块布局之后）。
两者在**第 4460 个字符**处就分歧（模块文本替换）。前缀缓存要求逐字节相同的
前缀，而上游按 ~4092 token（≈6500 字符）**分块**上报，第一块整块落在分歧点
之后 ⇒ 探针的前缀**永远匹配不上生产的第一块**，supervisor 日志里 4 条全是
`缓存: 0/4940`，每 4.5 分钟白烧一次请求。

同一批实测还给出了成本口径：

- 同一份 28.4k 生产形态提示词连发：第 2 次起命中 `24544` tokens（86%）；
- 缓存寿命只有分钟级（间隔 2 分钟命中、5 分钟已出现过期），而 trader 周期是 15 分钟；
- 稳定头 7.7k tokens 只拿回 1 块 ≈4076 tokens（占输入 14%、整单约 3%），
  而任何 ≥ 阈值（介于 5.4k~7.7k token）的预热请求都要为不可缓存的尾巴付全价
  ⇒ **预热本身比省下的还贵**。

故：默认 `off`（一个请求都不发）。`jit` 只作为**被遥测盯着的实验模式**保留 ——
它在 trader 槽位前预热一次**真前缀**，并把自身 token 成本记进 `model_calls`
（`caller=cache_warmer`），让"值不值得"由数据回答，而不是靠猜。

## 环境变量（**每次调用读取**，便于测试与运行期调整）

| 变量 | 默认 | 说明 |
|---|---|---|
| `ASTRA_CACHE_WARMUP_MODE` | `off` | `off`（默认，不发请求）/ `jit`（槽位前预热） |
| `ASTRA_CACHE_WARMUP_LEAD_SECONDS` | `90` | jit 模式在槽位开始前多少秒预热 |
| `ASTRA_CACHE_WARMUP_REPEATS` | `2` | 每次预热发几个请求（实测上游存在双副本） |
| `ASTRA_CACHE_WARMUP_MAX_MISSES` | `3` | 连续非命中达到该次数即熔断停用 |
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]

#: 生产提示词快照（每轮 trader 周期在调用大模型**之前**写好）。接缝：测试可 patch。
SNAPSHOT_FILE: Path = ROOT / "data" / "ai_brain_last_prompt.txt"

SYSTEM_MARKER = "【SYSTEM PROMPT】："
USER_MARKER = "【USER PROMPT"

#: 快照里被 `build_effective_prompt_text` 插在 SYSTEM 与 USER 之间的分隔线
#: （70 个 `=`，请求体里**没有**它，回放时必须剥掉，否则前缀整体错位）。
_DIVIDER_RE = re.compile(r"^=+$")

#: 用户消息里第一批**逐轮必变**的小节标题：真前缀在这一刀之前截断。
DYNAMIC_MARKERS: Tuple[str, ...] = (
    "【全网实时重大快讯",
    "【账户当前持仓",
    "【在途未成交限价挂单",
    "【全标的池原生行情",
    "【当前决策时间戳",
    "【全市场宏观体制自适应识别",
)

#: trader 周期（与 `astra_gateway/scheduler.py::JOBS` 的 `JobSpec("trader", ..., 15*60)` 同源）。
TRADER_INTERVAL_SECONDS = 15 * 60
#: 快照超过两个周期未更新即视为陈旧：**宁可不预热，也不拿过期前缀去烧钱**（fail-closed）。
SNAPSHOT_MAX_AGE_SECONDS = 2 * TRADER_INTERVAL_SECONDS
#: 实测 5.4k token（≈8100 字符）的前缀完全不触发缓存；低于该长度的前缀直接不发。
MIN_PAYLOAD_CHARS = 9000

_last_warmup_time: float = 0.0
_last_warmed_slot: int = -1
_consecutive_misses: int = 0
_breaker_tripped: bool = False
_breaker_logged: bool = False
_drift_logged: bool = False


def warmup_mode() -> str:
    """当前保活模式：`off`（默认）/ `jit`；未知取值一律回落 `off`（fail-closed）。"""
    mode = str(os.getenv("ASTRA_CACHE_WARMUP_MODE", "off") or "off").strip().lower()
    return mode if mode in ("off", "jit") else "off"


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(str(os.getenv(name, default)).strip()))
    except (TypeError, ValueError):
        return default


def _strip_snapshot_divider(system_text: str) -> str:
    """剥掉快照在 SYSTEM 段尾部插入的 `====` 分隔线，得到**请求体里那串**原文。"""
    lines = [line for line in system_text.rstrip("\n").split("\n") if not _DIVIDER_RE.fullmatch(line.strip())]
    return "\n".join(lines).strip()


def load_snapshot_prefix(path: Optional[Path] = None, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """从最近一轮生产快照里取出**真前缀**（system + 稳定用户头）。

    返回 `{"system", "user", "payload_chars", "snapshot_age_seconds"}`；
    快照缺失、格式不认识、陈旧（> 2 个周期）或前缀太短时**一律返回 None**，
    调用方据此不发任何请求（fail-closed）。
    """
    target = Path(path) if path is not None else SNAPSHOT_FILE
    now_ts = time.time() if now is None else float(now)
    try:
        age = now_ts - target.stat().st_mtime
    except OSError:
        return None
    if age > SNAPSHOT_MAX_AGE_SECONDS:
        return None
    try:
        text = target.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if SYSTEM_MARKER not in text or USER_MARKER not in text:
        return None
    system_raw = text.split(SYSTEM_MARKER, 1)[1]
    user_idx = system_raw.find(USER_MARKER)
    if user_idx < 0:
        return None
    system_text = _strip_snapshot_divider(system_raw[:user_idx])
    user_all = system_raw[user_idx:].split("\n", 1)[1] if "\n" in system_raw[user_idx:] else ""
    cuts = [user_all.find(marker) for marker in DYNAMIC_MARKERS]
    cuts = [cut for cut in cuts if cut >= 0]
    # 尾部换行一并去掉：动态小节前通常留了一个空行，留着只是白白多发一两个 token
    # （前缀仍是字面前缀，只是更短），缓存块边界远在其后，命中不受影响。
    user_head = user_all[:min(cuts)].rstrip("\n") if cuts else ""
    payload_chars = len(system_text) + len(user_head)
    if not system_text.strip() or not user_head.strip() or payload_chars < MIN_PAYLOAD_CHARS:
        return None
    return {
        "system": system_text,
        "user": user_head,
        "payload_chars": payload_chars,
        "snapshot_age_seconds": round(age, 1),
    }


def _log(message: str) -> None:
    print(f"[Cache Warmer] {message}", flush=True)


def _check_prefix_drift(system_text: str) -> None:
    """快照 SYSTEM 段 vs 现网 `get_effective_system_prompt()`：不一致只告警一次。

    这正是本次事故的形状探测器 —— 旧实现预热的前缀与生产前缀分歧却无人知晓。
    """
    global _drift_logged
    if _drift_logged:
        return
    try:
        from scripts.ai_brain_trader import get_effective_system_prompt
        live = get_effective_system_prompt()
    except Exception:
        return
    if live and live.strip() != system_text.strip():
        _drift_logged = True
        _log("⚠️ 快照 SYSTEM 段与现网 effective system prompt 不一致（前缀漂移），"
             "本次预热可能无法命中生产的第一块缓存")


def _persist_status(status: Dict[str, Any]) -> None:
    """把保活结论写进 gateway `runtime_state`（后台可见）；失败绝不影响主流程。"""
    try:
        from astra_gateway.publisher import DB_PATH
        from astra_gateway.store import GatewayStore
        GatewayStore(DB_PATH).set_state("cache.warmer_status", json.dumps(status, ensure_ascii=False))
    except Exception:
        pass


def _record_warmup_telemetry(model: str, effort: str, system_text: str, user_text: str,
                             ok: bool, usage: Dict[str, Any], output_chars: int,
                             error: Optional[Exception] = None) -> None:
    """把预热自身也记进 `model_calls`（caller=cache_warmer）——它的成本必须可见。"""
    try:
        from astra_gateway.telemetry import ModelCallTelemetry
        call = ModelCallTelemetry("cache_warmer", model, effort, system_text, user_text)
        call.finish("success" if ok else "failed", {"usage": usage}, output_chars=output_chars, error=error)
    except Exception:
        pass


def send_cache_warmup_ping(timeout: float = 30.0, prefix: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """发送**真前缀**微请求（max_tokens=1），返回缓存命中情况与诊断字段。"""
    global _last_warmup_time
    prefix = prefix if prefix is not None else load_snapshot_prefix()
    if not prefix:
        return {"ok": False, "reason": "no fresh production snapshot prefix"}
    try:
        from astra_backend.llm_manager import get_active_llm_runtime
        rt = get_active_llm_runtime()
        if not rt or not rt.get("model") or not rt.get("base_url") or not rt.get("api_key"):
            return {"ok": False, "reason": "No active LLM runtime or key configured"}

        from astra_backend.llm.transport import build_request_spec, _parse_llm_response

        _check_prefix_drift(prefix["system"])
        messages = [
            {"role": "system", "content": prefix["system"]},
            {"role": "user", "content": prefix["user"]},
        ]
        endpoint, headers, payload = build_request_spec(
            model=rt["model"],
            messages=messages,
            base_url=rt["base_url"],
            api_key=rt.get("api_key", ""),
            api_format=rt.get("api_format", "openai_chat"),
            reasoning_effort="none",
            max_tokens=1,
            api_path=rt.get("api_path", ""),
        )
        payload["max_tokens"] = 1
        if rt.get("api_format") == "openai_responses":
            payload["max_output_tokens"] = 1

        import urllib.request
        req = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers=headers)
        t0 = time.time()
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            res_json = json.loads(resp.read().decode("utf-8"))
        latency_ms = int((time.time() - t0) * 1000)
        content, _reasoning, usage = _parse_llm_response(rt.get("api_format", "openai_chat"), res_json)
        _last_warmup_time = time.time()
        cached = int(usage.get("cached_tokens") or 0)
        prompt_t = usage.get("prompt_tokens") or usage.get("input_tokens") or 0
        reported = bool(usage.get("cache_reported"))
        usage_keys = ",".join(sorted(str(k) for k in usage.keys()))[:200]
        rate = round(cached / prompt_t * 100, 1) if prompt_t and cached else 0.0
        if cached:
            _log(f"⚡ 缓存保活命中 ({latency_ms}ms | {cached}/{prompt_t} tokens, {rate}%)")
        elif reported:
            _log(f"⏱️ 缓存保活未命中（上游上报 0）({latency_ms}ms | 0/{prompt_t} tokens)")
        else:
            _log(f"ℹ️ 缓存保活：上游未上报缓存字段 ({latency_ms}ms | 输入 {prompt_t} tokens | usage_keys={usage_keys})")
        _record_warmup_telemetry(
            str(rt.get("model") or ""), str(rt.get("reasoning_effort") or "none"),
            prefix["system"], prefix["user"], True, usage, output_chars=len(str(content or "")),
        )
        return {
            "ok": True,
            "latency_ms": latency_ms,
            "cached_tokens": cached,
            "cache_reported": reported,
            "usage_keys": usage_keys,
            "payload_chars": prefix["payload_chars"],
            "usage": usage,
        }
    except Exception as exc:
        _record_warmup_telemetry("", "none", prefix.get("system", ""), prefix.get("user", ""),
                                 False, {}, output_chars=0, error=exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def _mark_result(res: Dict[str, Any]) -> Dict[str, Any]:
    """累计命中/未命中，触发熔断（连续非命中即停用，只记一次日志）。"""
    global _consecutive_misses, _breaker_tripped, _breaker_logged
    hit = bool(res.get("ok")) and int(res.get("cached_tokens") or 0) > 0
    if hit:
        _consecutive_misses = 0
    elif res.get("ok"):
        _consecutive_misses += 1
    max_misses = _env_int("ASTRA_CACHE_WARMUP_MAX_MISSES", 3)
    if _consecutive_misses >= max_misses and not _breaker_tripped:
        _breaker_tripped = True
        if not _breaker_logged:
            _breaker_logged = True
            _log(f"🛑 连续 {_consecutive_misses} 次非同命中，预热已自行停用"
                 "（实测该组合下预热净亏；如需重试请改 ASTRA_CACHE_WARMUP_MODE 后重启 worker）")
    res["cache_hit"] = hit
    _persist_status({
        "mode": warmup_mode(),
        "last_ok": bool(res.get("ok")),
        "cached_tokens": int(res.get("cached_tokens") or 0),
        "cache_reported": bool(res.get("cache_reported")),
        "consecutive_misses": _consecutive_misses,
        "breaker_tripped": _breaker_tripped,
        "at": int(time.time()),
    })
    return res


def check_and_warmup_cache(now: Optional[float] = None, idle_threshold_seconds: float = 270.0) -> bool:
    """按模式决定是否预热；返回**是否真的发出了预热请求**。

    - `off`（默认）：立刻返回 False，**一个网络请求都不发**；
    - `jit`：每个 trader 槽位前 `LEAD_SECONDS` 秒触发一次（每槽位至多一次），
      并受熔断开关约束。`idle_threshold_seconds` 仅为兼容旧签名保留，不再使用。
    """
    global _last_warmed_slot
    if _breaker_tripped:
        return False
    if warmup_mode() != "jit":
        return False
    ts = time.time() if now is None else float(now)
    slot = int(ts // TRADER_INTERVAL_SECONDS)
    sec_in_slot = ts % TRADER_INTERVAL_SECONDS
    lead = _env_int("ASTRA_CACHE_WARMUP_LEAD_SECONDS", 90)
    if sec_in_slot < max(0, TRADER_INTERVAL_SECONDS - lead):
        return False
    if slot == _last_warmed_slot:
        return False
    _last_warmed_slot = slot
    prefix = load_snapshot_prefix(now=ts)
    if not prefix:
        _log("跳过预热：没有可用的新鲜生产快照前缀（fail-closed）")
        return False
    repeats = _env_int("ASTRA_CACHE_WARMUP_REPEATS", 2)
    results = [_mark_result(send_cache_warmup_ping(prefix=prefix)) for _ in range(repeats)]
    return any(bool(res.get("ok")) for res in results)
