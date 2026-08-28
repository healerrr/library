import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    pass


def canonical_domain(value: str) -> str:
    """标准化域名，保留端口号"""
    value = value.strip().lower().rstrip(".")
    if value.startswith("www."):
        value = value[4:]
    return value.encode("idna").decode("ascii")


def hostname_allowed(hostname: str, allowed_domains: set[str]) -> bool:
    """检查 hostname 是否在允许的域名列表中（支持带端口）"""
    host = canonical_domain(hostname)
    for domain in allowed_domains:
        candidate = canonical_domain(domain)
        # 精确匹配（包括端口）
        if host == candidate:
            return True
        # 子域名匹配（不带端口的情况）
        if ":" not in candidate and host.endswith(f".{candidate.split(':')[0]}"):
            return True
        # 父域名匹配（检查去掉端口后的域名）
        candidate_host = candidate.split(':')[0]
        if host == candidate_host or host.endswith(f".{candidate_host}"):
            return True
    return False


def ip_is_public(value: str) -> bool:
    ip = ipaddress.ip_address(value)
    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def validate_url_format(url: str, allowed_domains: set[str]) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UnsafeUrlError("只允许 HTTP 或 HTTPS 地址")
    if not parsed.hostname or parsed.username or parsed.password:
        raise UnsafeUrlError("URL 格式无效或包含认证信息")
    if not hostname_allowed(parsed.hostname, allowed_domains):
        raise UnsafeUrlError("采集器只能访问已添加网站的域名")
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    # 允许非标准端口（已在域名中配置）
    return parsed.hostname, port


async def validate_target_url(url: str, allowed_domains: set[str]) -> None:
    hostname, port = validate_url_format(url, allowed_domains)
    try:
        addresses = await asyncio.to_thread(
            socket.getaddrinfo,
            hostname,
            port,
            family=socket.AF_UNSPEC,
            type=socket.SOCK_STREAM,
        )
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"域名无法解析: {hostname}") from exc

    resolved = {address[4][0] for address in addresses}
    if not resolved or any(not ip_is_public(address) for address in resolved):
        raise UnsafeUrlError("禁止访问 localhost、内网或保留 IP 地址")

