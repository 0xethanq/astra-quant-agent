"""Outbound endpoint validation for credential-bearing backup and notification calls."""
from __future__ import annotations
import ipaddress
import socket
import urllib.error
import urllib.parse
import urllib.request


def validate_outbound_url(url: str, *, allow_private: bool = False, allowed_hosts: set[str] | None = None) -> str:
    parsed = urllib.parse.urlparse(str(url).strip())
    if parsed.scheme not in ({"https", "http"} if allow_private else {"https"}):
        raise ValueError("Endpoint 必须使用 HTTPS；仅显式启用私有存储时允许 HTTP")
    host = (parsed.hostname or "").lower().rstrip(".")
    if not host or parsed.username or parsed.password:
        raise ValueError("Endpoint 主机无效，URL 中不得嵌入账号密码")
    if allowed_hosts and host not in allowed_hosts:
        raise ValueError("Endpoint 不在官方域名白名单")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)}
    except socket.gaierror as exc:
        raise ValueError(f"Endpoint 域名无法解析：{host}") from exc
    for raw in addresses:
        ip = ipaddress.ip_address(raw)
        if ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise ValueError("Endpoint 指向受保护的本机、链路本地或保留地址")
        if ip.is_private and not allow_private:
            raise ValueError("Endpoint 指向私有网络；如为自建 MinIO/NAS，请显式启用私有存储")
    return str(url).rstrip("/")


def validate_wechat_base_url(url: str) -> str:
    return validate_outbound_url(url, allowed_hosts={"ilinkai.weixin.qq.com"})


class _RedirectDenied(urllib.error.HTTPError):
    """端点回 3xx——本工具链一律视为拒发，绝不自动跟随。"""


class _NoRedirectHandler(urllib.request.HTTPRedirectHandler):
    """审计D(2026-09-13)·重定向 SSFR 兜闸。

    validate_outbound_url 只核**首跳** URL 的主机/IP；而 urllib 默认**自动跟随**
    3xx——一个首跳合法、却回 302→http://169.254.169.254/（云元数据）或
    http://127.0.0.1/ 的端点，凭 validate 后即借道打内网（校验时序与真实去向
    脱节的 TOCTOU）。凭证类出站（备份投递/通知）没有任何场景需要跟随重定向，
    故对这些链路统一禁跳：遇 3xx 直接抛，交由上层按失败重试/上报。

    残余风险如实记：DNS 重绑定（getaddrinfo 校验与 connect 各自解析）在纯标准库
    下无法根除，需要自定义 connect/sock 层钉 IP——留待网络层专项，勿以本闸宣称
    已彻底闭环。
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401
        raise _RedirectDenied(newurl, code, f"重定向被安全策略拒绝：{newurl}", headers, fp)
        return None


_SAFE_OPENER = urllib.request.build_opener(_NoRedirectHandler)


def safe_urlopen(request, *, timeout: int):
    """凭证类出站统一入口：禁跟随重定向的 urlopen。"""
    return _SAFE_OPENER.open(request, timeout=timeout)
