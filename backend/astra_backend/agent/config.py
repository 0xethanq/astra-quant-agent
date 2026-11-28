"""Agent 专属模型与推理配置读写（调用期解析路径，不绑定生产文件）。"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from astra_backend.file_locks import file_lock

ROOT = Path(__file__).resolve().parents[2]
BJ_TZ = timezone(timedelta(hours=8))
VALID_EFFORTS = {"none", "minimal", "low", "medium", "high"}
DEFAULT_EFFORT = "medium"
DEFAULT_MAX_ROUNDS = 10
MIN_ROUNDS = 1
MAX_ROUNDS = 15


def _config_file() -> Path:
    override = os.environ.get("ASTRA_AGENT_CONFIG_FILE", "").strip()
    if override:
        return Path(override)
    data_dir = os.environ.get("ASTRA_DATA_DIR", "").strip()
    if data_dir:
        return Path(data_dir) / "agent_config.json"
    return ROOT / "data" / "agent_config.json"


def _now_text() -> str:
    return datetime.now(BJ_TZ).strftime("%Y-%m-%d %H:%M:%S")


def _safe_available_models() -> List[Dict[str, Any]]:
    """返回脱敏后的可用模型摘要（绝不返回 api_key 或敏感凭证）。"""
    try:
        from astra_backend.llm_manager import load_llm_config
        cfg = load_llm_config(mask_keys=True)
    except Exception:
        return []
    health_models: Dict[str, Any] = {}
    try:
        from astra_backend.llm.model_health import audit_llm_config
        from astra_backend.llm.policy import SUPPORTED_API_FORMATS
        formats = tuple(f["id"] for f in SUPPORTED_API_FORMATS)
        health_models = (audit_llm_config(cfg, formats).get("models") or {})
    except Exception:
        health_models = {}

    out: List[Dict[str, Any]] = []
    for item in cfg.get("models") or []:
        if not isinstance(item, dict):
            continue
        mid = str(item.get("id") or "").strip()
        if not mid:
            continue
        m_health = health_models.get(mid) if isinstance(health_models.get(mid), dict) else {}
        out.append({
            "id": mid,
            "name": str(item.get("name") or mid),
            "provider_id": str(item.get("provider_id") or ""),
            "provider_name": str(item.get("provider_name") or ""),
            "api_format": str(item.get("api_format") or "openai_chat"),
            "reasoning_effort": str(item.get("reasoning_effort") or "high"),
            "capabilities": list(item.get("capabilities") or []),
            "status": str(m_health.get("status") or "ready"),
        })
    return out


def load_agent_config() -> Dict[str, Any]:
    """读取 Agent 配置；文件缺失或损坏时回落安全默认值。"""
    cfg_path = _config_file()
    data: Dict[str, Any] = {}
    if cfg_path.is_file():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}

    model_id = str(data.get("model_id") or "auto").strip() or "auto"
    effort = str(data.get("reasoning_effort") or DEFAULT_EFFORT).strip().lower()
    if effort not in VALID_EFFORTS:
        effort = DEFAULT_EFFORT

    try:
        max_rounds = int(data.get("max_tool_rounds", DEFAULT_MAX_ROUNDS))
    except (TypeError, ValueError):
        max_rounds = DEFAULT_MAX_ROUNDS
    max_rounds = max(MIN_ROUNDS, min(MAX_ROUNDS, max_rounds))

    effective_model_id = model_id
    if model_id == "auto":
        try:
            from astra_backend.llm_manager import get_active_llm_runtime
            active = get_active_llm_runtime()
            effective_model_id = str(active.get("model") or "auto")
        except Exception:
            effective_model_id = "auto"

    return {
        "model_id": model_id,
        "effective_model_id": effective_model_id,
        "reasoning_effort": effort,
        "max_tool_rounds": max_rounds,
        "updated_at": str(data.get("updated_at") or ""),
        "available_models": _safe_available_models(),
    }


def save_agent_config(payload: Dict[str, Any]) -> Dict[str, Any]:
    """更新 Agent 配置（原子写入 + 文件锁）。"""
    cfg_path = _config_file()
    prev = load_agent_config()

    model_id = prev["model_id"]
    if "model_id" in payload:
        raw_mid = str(payload.get("model_id") or "").strip()
        model_id = raw_mid if raw_mid else "auto"
        if model_id != "auto":
            known_ids = {m["id"] for m in _safe_available_models()}
            if known_ids and model_id not in known_ids:
                raise ValueError(f"模型 {model_id} 未在「模型连接」中登记")

    effort = prev["reasoning_effort"]
    if "reasoning_effort" in payload and payload.get("reasoning_effort") is not None:
        raw_eff = str(payload.get("reasoning_effort") or "").strip().lower()
        if raw_eff not in VALID_EFFORTS:
            raise ValueError(f"不支持的思考强度：{raw_eff}")
        effort = raw_eff

    max_rounds = prev["max_tool_rounds"]
    if "max_tool_rounds" in payload and payload.get("max_tool_rounds") is not None:
        try:
            rounds = int(payload.get("max_tool_rounds"))
        except (TypeError, ValueError) as exc:
            raise ValueError("max_tool_rounds 必须为整数") from exc
        if not (MIN_ROUNDS <= rounds <= MAX_ROUNDS):
            raise ValueError(f"最大工具轮次须在 {MIN_ROUNDS}~{MAX_ROUNDS} 之间")
        max_rounds = rounds

    doc = {
        "model_id": model_id,
        "reasoning_effort": effort,
        "max_tool_rounds": max_rounds,
        "updated_at": _now_text(),
    }

    with file_lock(cfg_path):
        cfg_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_path = tempfile.mkstemp(prefix=".agent-config-", suffix=".tmp", dir=str(cfg_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(doc, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                os.chmod(temp_path, 0o600)
            except OSError:
                pass
            os.replace(temp_path, cfg_path)
            try:
                os.chmod(cfg_path, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    return load_agent_config()


def resolve_agent_llm_runtime(
    agent_cfg: Optional[Dict[str, Any]] = None,
    model_override: Optional[str] = None,
) -> Dict[str, Any]:
    """解析 Agent 当前使用的完整 LLM 运行时配置（含回退到交易主脑）。"""
    from astra_backend.llm_manager import get_active_llm_runtime, resolve_model_runtime

    cfg = agent_cfg if agent_cfg is not None else load_agent_config()
    target_mid = str(model_override or cfg.get("model_id") or "auto").strip() or "auto"
    effort = str(cfg.get("reasoning_effort") or DEFAULT_EFFORT).strip().lower()
    if effort not in VALID_EFFORTS:
        effort = DEFAULT_EFFORT

    runtime: Dict[str, Any] = {}
    if target_mid != "auto":
        resolved = resolve_model_runtime(target_mid)
        if resolved and resolved.get("model"):
            runtime = dict(resolved)

    if not runtime:
        active = get_active_llm_runtime()
        runtime = dict(active) if active else {}

    if not runtime or not runtime.get("model"):
        raise RuntimeError("尚未配置可用的 LLM 模型，请先前往「模型连接」配置供应商与主脑模型。")

    runtime["reasoning_effort"] = effort
    runtime["agent_dedicated"] = target_mid != "auto"
    return runtime
