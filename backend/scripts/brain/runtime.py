"""主脑周期的**前置解析**（B3 抽取，`ai_brain_trader.py` 第四块）。

| 函数 | 内容 |
|---|---|
| `capture_policy_snapshot` | 决策周期开始处**冻结**策略快照（两级 import 兜底 → 再退化为 `unknown` 常量快照），并派生 `policy_version/hash/summary` |
| `resolve_llm_runtime` | LLM 运行时解析：环境变量默认 → `get_active_llm_runtime()` 覆盖（含 `api_format`/`base_url`/`api_key`/超时），失败时把 `execute_llm_request` 置 `None` |

## 两处 in-out 语义（"传进去再传出来"）

- `policy_snapshot`：调用方可能**已经**给了快照（参数），此时本块原样不动 ——
  只按"段内是否赋值"判"必然绑定"会误判，故按 **in-out**；
- `api_key` / `base_url`：段内 `active_llm.get("base_url") or base_url` 会**读取旧值**，
  必须把调用方当前值传进来，再随输出返回。

**判据（第九十二刀规则）**：凡"非必然绑定"的输出，**必须**出现在入参里，
否则未命中分支时 `UnboundLocalError`。段体 **AST 逐字**（对门 `tests/extraction/test_brain_runtime_extraction.py`）。
"""
from __future__ import annotations

from typing import Any, Dict, Optional


def capture_policy_snapshot(*,
        _get_system_version_tag,
        policy_snapshot):
    if policy_snapshot is None:
        try:
            from policy_snapshot import generate_policy_snapshot
            policy_snapshot = generate_policy_snapshot()
        except Exception:
            try:
                from astra_backend.policy_snapshot import generate_policy_snapshot
                policy_snapshot = generate_policy_snapshot()
            except Exception as exc:
                print(f"[AI Brain Batch] Policy snapshot warning: {exc}")
                policy_snapshot = {
                    "policy_version": f"{_get_system_version_tag()}@unknown",
                    "policy_hash": "unknown",
                    "summary": "policy_snapshot_fallback",
                    "units": {},
                }
    policy_version = policy_snapshot.get("policy_version", f"{_get_system_version_tag()}@unknown")
    policy_hash = policy_snapshot.get("policy_hash", "unknown")
    policy_summary = policy_snapshot.get("summary", "")
    return (policy_hash, policy_snapshot, policy_summary, policy_version)


def resolve_llm_runtime(*,
        api_key,
        base_url,
        os):
    model_name = os.environ.get("LLM_MODEL") or ""
    effort = os.environ.get("LLM_REASONING_EFFORT") or "high"
    api_format = "openai_chat"
    thinking_timeout = float(os.environ.get("LLM_THINKING_TIMEOUT", os.environ.get("LLM_TIMEOUT_SECONDS", 120.0)))
    try:
        from astra_backend.llm_manager import get_active_llm_runtime, execute_llm_request
        active_llm = get_active_llm_runtime()
        model_name = os.environ.get("LLM_MODEL") or active_llm.get("model") or model_name
        effort = os.environ.get("LLM_REASONING_EFFORT") or active_llm.get("reasoning_effort") or effort
        api_format = active_llm.get("api_format", "openai_chat")
        base_url = active_llm.get("base_url") or base_url
        api_key = active_llm.get("api_key") or api_key
        thinking_timeout = float(active_llm.get("thinking_timeout") or thinking_timeout)
    except Exception:
        execute_llm_request = None
    return (api_format, api_key, base_url, effort, execute_llm_request, model_name, thinking_timeout)

