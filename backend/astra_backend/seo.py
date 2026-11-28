"""Server-side per-route SEO metadata injection and crawler policy headers."""
from __future__ import annotations

from dataclasses import dataclass
from html import escape
import json
import re
from fastapi.responses import HTMLResponse, Response

from astra_backend.version import APP_NAME, APP_SITE

PUBLIC_ROBOTS = "index, follow, max-image-preview:large, max-snippet:-1, max-video-preview:-1"
NOINDEX_ROBOTS = "noindex, nofollow, noarchive"

_TITLE_RE = re.compile(r"<title>.*?</title>", re.I | re.S)
_DESC_RE = re.compile(r'(<meta\s+name=["\']description["\']\s+content=["\'])[^"\']*(["\']\s*/?>)', re.I)
_ROBOTS_RE = re.compile(r'(<meta\s+name=["\']robots["\']\s+content=["\'])[^"\']*(["\']\s*/?>)', re.I)
_CANON_RE = re.compile(r'(<link\s+rel=["\']canonical["\']\s+href=["\'])[^"\']*(["\']\s*/?>)', re.I)
_OG_TITLE_RE = re.compile(r'(<meta\s+property=["\']og:title["\']\s+content=["\'])[^"\']*(["\']\s*/?>)', re.I)
_OG_DESC_RE = re.compile(r'(<meta\s+property=["\']og:description["\']\s+content=["\'])[^"\']*(["\']\s*/?>)', re.I)
_OG_URL_RE = re.compile(r'(<meta\s+property=["\']og:url["\']\s+content=["\'])[^"\']*(["\']\s*/?>)', re.I)
_OG_IMG_RE = re.compile(r'(<meta\s+property=["\']og:image["\']\s+content=["\'])[^"\']*(["\']\s*/?>)', re.I)
_TW_TITLE_RE = re.compile(r'(<meta\s+name=["\']twitter:title["\']\s+content=["\'])[^"\']*(["\']\s*/?>)', re.I)
_TW_DESC_RE = re.compile(r'(<meta\s+name=["\']twitter:description["\']\s+content=["\'])[^"\']*(["\']\s*/?>)', re.I)
_TW_URL_RE = re.compile(r'(<meta\s+name=["\']twitter:url["\']\s+content=["\'])[^"\']*(["\']\s*/?>)', re.I)
_TW_IMG_RE = re.compile(r'(<meta\s+name=["\']twitter:image["\']\s+content=["\'])[^"\']*(["\']\s*/?>)', re.I)
_JSONLD_RE = re.compile(r'(<script\s+type=["\']application/ld\+json["\']>\s*)(.*?)(\s*</script>)', re.I | re.S)


@dataclass(frozen=True)
class RouteSeoSpec:
    path: str
    name: str
    title: str
    description: str
    image_path: str


ROUTE_SPECS: dict[str, RouteSeoSpec] = {
    "/trading": RouteSeoSpec(
        path="/trading",
        name="实盘看板",
        title="实盘看板 | AstraQuant",
        description="AstraQuant OKX USDT 永续合约实盘看板：多周期交互 K 线、实时持仓浮盈、盘口深度与自动风控状态实时监控。",
        image_path="/images/v920_dashboard.png",
    ),
    "/factors": RouteSeoSpec(
        path="/factors",
        name="AI 决策",
        title="AI 决策 | AstraQuant",
        description="AstraQuant 多智能体 AI 投委会决策面板：alpha-hunter、quant-analyst 与 risk-officer 协同裁决与 28+ 量化因子雷达。",
        image_path="/images/v920_decisions.png",
    ),
    "/news": RouteSeoSpec(
        path="/news",
        name="市场快讯",
        title="市场快讯 | AstraQuant",
        description="AstraQuant 7x24 加密市场快讯与宏观日历：BTC/ETH 突发催化、ETF 资金流与 AI 情绪影响评级实时聚合。",
        image_path="/images/v920_news.png",
    ),
    "/lab": RouteSeoSpec(
        path="/lab",
        name="策略复盘",
        title="策略复盘 | AstraQuant",
        description="AstraQuant 量化策略复盘实验室：多周期回放、滑点与手续费归因分析、胜率统计与 AI 参数自演化提案。",
        image_path="/images/v920_review.png",
    ),
    "/history": RouteSeoSpec(
        path="/history",
        name="交易台账",
        title="交易台账 | AstraQuant",
        description="AstraQuant 历史交易台账：逐笔成交明细、资金费率与手续费拆解、日度净值曲线与分币种绩效归因。",
        image_path="/images/v920_ledger.png",
    ),
    "/docs": RouteSeoSpec(
        path="/docs",
        name="系统文档",
        title="系统文档 | AstraQuant",
        description="AstraQuant v9.2 系统文档：多智能体量化架构、一键部署指南、AI 助手控制面操作说明与安全风控体系。",
        image_path="/images/v920_cot_drawer.png",
    ),
}


def normalize_public_path(route_path: str) -> str:
    """Normalize public SPA paths so aliases resolve to canonical routes."""
    cleaned = "/" + (route_path or "").strip().split("?", 1)[0].split("#", 1)[0].strip("/")
    if cleaned == "/":
        return "/"
    if cleaned == "/doc" or cleaned.startswith("/doc/") or cleaned.startswith("/docs/"):
        return "/docs"
    for candidate in ROUTE_SPECS:
        if cleaned == candidate or cleaned.startswith(f"{candidate}/"):
            return candidate
    return cleaned


def _replace_meta(html: str, pattern: re.Pattern[str], value: str) -> str:
    escaped = escape(value, quote=True)
    return pattern.sub(lambda m: f"{m.group(1)}{escaped}{m.group(2)}", html, count=1)


def _rewrite_jsonld_for_subroute(html: str, spec: RouteSeoSpec, origin: str, canonical: str, og_image: str) -> str:
    match = _JSONLD_RE.search(html)
    if not match:
        return html
    try:
        payload = json.loads(match.group(2))
    except Exception:
        return html
    if not isinstance(payload, dict) or not isinstance(payload.get("@graph"), list):
        return html
    graph = [
        node for node in payload["@graph"]
        if not (isinstance(node, dict) and node.get("@type") in ("WebPage", "BreadcrumbList"))
    ]
    graph.extend([
        {
            "@type": "WebPage",
            "@id": f"{canonical}#webpage",
            "url": canonical,
            "name": spec.title,
            "description": spec.description,
            "inLanguage": "zh-CN",
            "isPartOf": {"@id": f"{origin}/#website"},
            "primaryImageOfPage": {"@type": "ImageObject", "url": og_image},
        },
        {
            "@type": "BreadcrumbList",
            "@id": f"{canonical}#breadcrumb",
            "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": APP_NAME, "item": f"{origin}/"},
                {"@type": "ListItem", "position": 2, "name": spec.name, "item": canonical},
            ],
        },
    ])
    payload["@graph"] = graph
    rendered = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace("</", r"<\/")
    return f"{html[:match.start()]}{match.group(1)}{rendered}{match.group(3)}{html[match.end():]}"


def inject_route_seo(
    response: Response,
    route_path: str,
    *,
    is_public: bool = True,
    site_url: str = "",
) -> Response:
    """Inject route-specific HTML metadata and crawler directives cleanly."""
    if not is_public:
        response.headers["X-Robots-Tag"] = NOINDEX_ROBOTS

    if not isinstance(response, HTMLResponse):
        return response

    body_bytes = getattr(response, "body", b"")
    if not body_bytes:
        return response
    html = body_bytes.decode("utf-8", errors="ignore")
    if "<head" not in html.lower() or "<title" not in html.lower():
        return response

    origin = (site_url or APP_SITE).rstrip("/")
    if not is_public:
        updated = _TITLE_RE.sub(f"<title>控制台 | {escape(APP_NAME)}</title>", html, count=1)
        updated = _replace_meta(updated, _ROBOTS_RE, NOINDEX_ROBOTS)
        return _clone_html_response(response, updated)

    norm_path = normalize_public_path(route_path)
    updated = _replace_meta(html, _ROBOTS_RE, PUBLIC_ROBOTS)
    spec = ROUTE_SPECS.get(norm_path)
    if spec is None:
        canonical = f"{origin}/"
        updated = _replace_meta(updated, _CANON_RE, canonical)
        updated = _replace_meta(updated, _OG_URL_RE, canonical)
        updated = _replace_meta(updated, _TW_URL_RE, canonical)
        return _clone_html_response(response, updated)

    canonical = f"{origin}{spec.path}"
    og_image = f"{origin}{spec.image_path}"
    updated = _TITLE_RE.sub(f"<title>{escape(spec.title)}</title>", updated, count=1)
    updated = _replace_meta(updated, _DESC_RE, spec.description)
    updated = _replace_meta(updated, _CANON_RE, canonical)
    updated = _replace_meta(updated, _OG_TITLE_RE, spec.title)
    updated = _replace_meta(updated, _OG_DESC_RE, spec.description)
    updated = _replace_meta(updated, _OG_URL_RE, canonical)
    updated = _replace_meta(updated, _OG_IMG_RE, og_image)
    updated = _replace_meta(updated, _TW_TITLE_RE, spec.title)
    updated = _replace_meta(updated, _TW_DESC_RE, spec.description)
    updated = _replace_meta(updated, _TW_URL_RE, canonical)
    updated = _replace_meta(updated, _TW_IMG_RE, og_image)
    updated = _rewrite_jsonld_for_subroute(updated, spec, origin, canonical, og_image)
    return _clone_html_response(response, updated)


def _clone_html_response(source: HTMLResponse, html: str) -> HTMLResponse:
    headers = {
        k: v for k, v in source.headers.items()
        if k.lower() not in ("content-length", "content-type")
    }
    return HTMLResponse(content=html, status_code=source.status_code, headers=headers)
