import asyncio
import ipaddress
import socket
from urllib.parse import urlparse


class UnsafeUrlError(ValueError):
    pass


def canonical_domain(value: str) -> str:
    value = value.strip().lower().rstrip(".")
    if value.startswith("www."):
        value = value[4:]
    return value.encode("idna").decode("ascii")


def domain_endpoint(value: str, scheme: str) -> tuple[str, int]:
    parsed = urlparse(f"//{value}")
    if not parsed.hostname:
        raise UnsafeUrlError("网站域名配置无效")
    port = parsed.port or (443 if scheme == "https" else 80)
    return canonical_domain(parsed.hostname), port


def hostname_allowed(
    hostname: str,
    port: int,
    scheme: str,
    allowed_domains: set[str],
) -> bool:
    host = canonical_domain(hostname)
    for domain in allowed_domains:
        candidate, candidate_port = domain_endpoint(domain, scheme)
        if port != candidate_port:
            continue
        if host == candidate or host.endswith(f".{candidate}"):
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
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    if not hostname_allowed(parsed.hostname, port, parsed.scheme, allowed_domains):
        raise UnsafeUrlError("采集器只能访问已配置的域名和端口")
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
