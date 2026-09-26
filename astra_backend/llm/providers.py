"""网关基址与 API 路径拼装、活跃模型持有者探测。

纯函数，不读任何模块级常量。结构优化阶段 2（B4）。
"""
from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import urlparse


# ── Base URL 拼接：以用户显式输入的路径为准，不再强插 /v1 ──
# 历史缺陷：所有请求端点构造都在 base_url 不以 /v1 结尾时硬拼 "/v1/..."，
# 导致智谱（https://open.bigmodel.cn/api/paas/v4）、Gemini（.../v1beta）这类
# 带版本路径的供应商被拼成 /v4/v1/chat/completions 而 404/401。
# 规则：base 含任何显式路径 → 直接拼接协议后缀；裸域名（无路径）→ 兼容补 /v1。
def _url_path_of(base: str) -> str:
    try:
        return urlparse(base).path or ""
    except Exception:
        return "/unparseable"  # 解析失败按“有路径”处理，不做任何自动填充


def _join_api_path(base: str, suffix: str) -> str:
    """把协议后缀（/chat/completions、/messages、/responses、/models）拼到 Base URL 上。"""
    cleaned = str(base or "").strip().rstrip("/")
    if cleaned.endswith(suffix):
        return cleaned
    if _url_path_of(cleaned) in ("", "/"):
        return f"{cleaned}/v1{suffix}"
    return f"{cleaned}{suffix}"


def _model_holder_pids(providers: List[Dict[str, Any]], model_id: str) -> List[str]:
    """列出嵌套模型清单里持有该模型 id 的所有供应商 id。"""
    return [
        str(p.get("id", ""))
        for p in providers
        if any(m.get("id") == model_id for m in p.get("models", []))
    ]


def _resolve_active_provider_id(config: Dict[str, Any]) -> str:
    """判定主脑模型归属的供应商。

    优先级：显式 active_provider_id > 唯一持有者 > 顶层扁平缓存归属。
    多个供应商挂同名模型且无法判定时返回空串——调用方据此保守处理（宁可拦，不可放错）。
    """
    mid = config.get("active_model_id", "")
    if not mid:
        return ""
    providers = config.get("providers", [])
    holders = _model_holder_pids(providers, mid)
    if not holders:
        # 模型不嵌套在任何供应商名下（仅顶层注册）→ 没有归属可言，
        # 绝不能沿用陈旧的 active_provider_id，否则会被误重挂到该供应商凭据上
        return ""
    pid = str(config.get("active_provider_id") or "").strip()
    if pid and pid in holders:
        return pid
    if len(set(holders)) == 1:
        return holders[0]
    flat_pid = next(
        (str(m.get("provider_id") or "") for m in config.get("models", []) if m.get("id") == mid),
        "",
    )
    if flat_pid and flat_pid in holders:
        return flat_pid
    return ""


def _provider_holds_active_model(config: Dict[str, Any], provider_id: str) -> bool:
    """该供应商是否持有当前主脑模型。

    多供应商挂同名模型时按归属精确判定，不再让未启用的那份副本被误伤；
    归属无法判定（多持有者且无记录）时保守视为持有，防止主脑悬空。
    """
    mid = config.get("active_model_id", "")
    if not mid:
        return False
    prov = next((p for p in config.get("providers", []) if p.get("id") == provider_id), None)
    if not prov or not any(m.get("id") == mid for m in prov.get("models", [])):
        return False
    active_pid = _resolve_active_provider_id(config)
    return (not active_pid) or active_pid == provider_id
