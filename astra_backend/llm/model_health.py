"""模型条目**结构自检**（离线判定，绝不发网络请求）。

## 为什么需要它

2026-09-29 实测后台配置：三条模型里两条是死的 ——
`glm-5.3-flash` 真机回 `HTTP 402 余额不足`，`gemini-3.1-flash-image`
**既没有密钥、`provider_id=custom` 在 `providers[]` 里也根本不存在**。
界面把三条并列显示、没有任何标记，`fallback_model_ids` 又是空的
（等于没有任何回退）—— 出故障时人无法从后台看出"这条到底能不能用"。

## 判据边界（刻意保守）

本模块只看**结构可得性**：密钥、供应商、格式、路径。它**不判运行态**：

- 「余额不足」「限流」「模型名在对方账上不存在」这类只有真机能回答的问题，
  交给 `POST /api/v1/admin/llm/test-all`（真机探针），本模块**绝不**据此判死。
  理由：把一次 402 永久写成"死条目"会让配置页撒谎 —— 充值后它仍然是死的。

三态：`dead`（结构上不可能发出请求）/ `warn`（能跑但可疑）/ `ok`。
`role` 是纯信息位（active / fallback / dormant），不参与三态。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

#: 由**协议格式**决定的端点路径。这些值写在条目上不影响行为（transport 会主动清空），
#: 只有"非标准自定义路径"才真的覆盖端点 —— 故后者才值得提示。
STANDARD_API_PATHS = (
    "/chat/completions", "/messages", "/responses",
    "/v1/chat/completions", "/v1/messages", "/v1/responses",
)

#: 结构性致命码：命中即 `dead`（不可能发出请求），也是"一键清理"的删除依据。
DEAD_CODES = frozenset({"no_api_key"})

#: 只提示、不判死。
WARN_CODES = frozenset({
    "provider_missing", "provider_disabled", "unsupported_format",
    "invalid_base_url", "custom_api_path", "no_fallback_chain",
})


def _provider_of(providers: Sequence[Dict[str, Any]], provider_id: str) -> Optional[Dict[str, Any]]:
    if not provider_id or provider_id == "custom":
        return None
    return next((p for p in providers if str(p.get("id") or "") == provider_id), None)


def _entry_has_key(entry: Optional[Dict[str, Any]]) -> bool:
    """条目是否**真有**密钥 —— 兼容脱敏后的载荷。

    `load_llm_config(mask_keys=True)` 会**摘掉** `api_key` 字段，改用 `has_key`
    布尔 + `api_key_masked`（`store_normalize.py`）。自检如果只读 `api_key`，
    那么"给后台看的这份配置"里每条模型都会显得没有密钥 ⇒ 全盘误判为死。
    故：有 `has_key` 就以它为准（那正是界面展示的口径），否则看原始字段。
    """
    if entry is None:
        return False
    if "has_key" in entry:
        return bool(entry.get("has_key"))
    return bool(entry.get("api_key"))


def audit_model_entry(
    model: Dict[str, Any],
    providers: Sequence[Dict[str, Any]],
    supported_formats: Sequence[str] = (),
    *,
    active_model_id: str = "",
    fallback_model_ids: Sequence[str] = (),
) -> Dict[str, Any]:
    """对单条模型条目做结构自检，返回 `{status, role, issues:[...]}`。"""
    issues: List[Dict[str, str]] = []
    provider_id = str(model.get("provider_id") or "")
    prov = _provider_of(providers, provider_id)
    model_id = str(model.get("id") or "")

    # 1) 供应商存在性。`custom` 是合法的"条目自带端点"形态，不算缺失；
    #    但一个**具名**供应商在 providers[] 里找不到，说明配置被删/改名了。
    if provider_id and provider_id != "custom" and prov is None:
        issues.append({
            "code": "provider_missing", "level": "warn",
            "detail": f"供应商 {provider_id} 不在供应商列表里（可能已被删除）；"
                      f"若本条目自带 base_url 与密钥，仍可直连",
        })

    # 2) 密钥可得性 —— 模型自带优先，回落供应商（与运行期 get_active_llm_runtime 同序）。
    #    脱敏载荷里 `api_key` 被摘掉、只剩 `has_key`，故统一走 _entry_has_key。
    if not (_entry_has_key(model) or _entry_has_key(prov)):
        issues.append({
            "code": "no_api_key", "level": "dead",
            "detail": "模型条目与供应商都没有 API Key，本条目不可能发出请求",
        })

    # 3) 端点可用性。
    base_url = str(model.get("base_url") or (prov or {}).get("base_url") or "")
    if not base_url:
        issues.append({
            "code": "invalid_base_url", "level": "warn",
            "detail": "没有 base_url；运行期会回落到当前活跃模型的出口",
        })

    # 4) 协议格式。
    api_format = str(model.get("api_format") or "openai_chat")
    if supported_formats and api_format not in tuple(supported_formats):
        issues.append({
            "code": "unsupported_format", "level": "warn",
            "detail": f"格式 {api_format} 不在支持列表里；运行期会按 base_url/模型名自动探测",
        })

    # 5) 自定义路径（标准路径会被 transport 主动清空 ⇒ 写了也无害，不提示）。
    api_path = str(model.get("api_path") or "")
    if api_path and api_path not in STANDARD_API_PATHS:
        issues.append({
            "code": "custom_api_path", "level": "info",
            "detail": f"非标准路径 {api_path} 会覆盖协议默认端点（标准路径不会）",
        })

    # 6) 供应商被停用：条目还在，但整家不可用。
    if prov is not None and not bool(prov.get("enabled", False)):
        issues.append({
            "code": "provider_disabled", "level": "warn",
            "detail": f"供应商 {prov.get('name') or provider_id} 处于停用状态，本条目不会被使用",
        })

    if active_model_id and model_id == active_model_id:
        role = "active"
    elif model_id in tuple(fallback_model_ids or ()):
        role = "fallback"
    else:
        role = "dormant"

    status = "dead" if any(i["level"] == "dead" for i in issues) else (
        "warn" if any(i["level"] == "warn" for i in issues) else "ok")
    return {"status": status, "role": role, "issues": issues}


def audit_llm_config(
    config: Dict[str, Any],
    supported_formats: Sequence[str] = (),
) -> Dict[str, Any]:
    """整份 LLM 配置的结构自检报告。

    返回 `{"models": {model_id: {...}}, "warnings": [...], "counts": {...}}`。
    同一 id 出现在多条（多供应商同名）时，报告保留**最先一条**的判定 ——
    运行期同样按"列表首个命中"解析（`next(m for m in models if m['id']==...)`），
    两者同序，界面与真相同源。
    """
    providers = list(config.get("providers") or [])
    models = list(config.get("models") or [])
    active_model_id = str(config.get("active_model_id") or "")
    fallback_ids = list(config.get("fallback_model_ids") or ())

    report: Dict[str, Dict[str, Any]] = {}
    for model in models:
        model_id = str(model.get("id") or "")
        if not model_id or model_id in report:
            continue
        report[model_id] = audit_model_entry(
            model, providers, supported_formats,
            active_model_id=active_model_id, fallback_model_ids=fallback_ids,
        )

    warnings: List[Dict[str, str]] = []
    try:
        attempts = int(config.get("request_attempts") or 1)
    except (TypeError, ValueError):
        attempts = 1
    usable_fallbacks = [fid for fid in fallback_ids
                        if report.get(str(fid), {}).get("status") != "dead"]
    if attempts > 1 and not usable_fallbacks:
        warnings.append({
            "code": "no_fallback_chain", "level": "warn",
            "detail": f"每模型请求 {attempts} 次但没有可用回退模型 —— 主模型不可用时无兜底（单点故障）",
        })

    counts = {"ok": 0, "warn": 0, "dead": 0}
    for item in report.values():
        counts[item["status"]] = counts.get(item["status"], 0) + 1
    return {"models": report, "warnings": warnings, "counts": counts}


def dead_model_ids(report: Dict[str, Any]) -> List[str]:
    """结构上**不可能发出请求**的条目 id（一键清理只删这些）。

    刻意不含 `warn`/`provider_disabled`：模型条目本身可能是好的，
    供应商停用是另一回事，删掉用户配置属于越权。
    """
    models = (report or {}).get("models") or {}
    out: List[str] = []
    for model_id, item in models.items():
        codes = {i.get("code") for i in (item or {}).get("issues") or []}
        if codes & DEAD_CODES or (item or {}).get("status") == "dead":
            out.append(str(model_id))
    return out
