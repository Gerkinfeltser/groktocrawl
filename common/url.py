"""Shared URL utility functions for GroktoCrawl.

Consolidates urlparse-based URL handling across all services into a single,
testable module. Uses only stdlib plus socket I/O for DNS resolution.
"""

import logging
import socket
from ipaddress import (
    IPv4Address,
    IPv4Network,
    IPv6Address,
    IPv6Network,
    ip_address,
    ip_network,
)
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ── Private/hostile network definitions (SSRF guard) ────────────────

_PRIVATE_NETWORKS: list[IPv4Network | IPv6Network] = [
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("127.0.0.0/8"),  # loopback
    ip_network("169.254.0.0/16"),  # link-local
    ip_network("0.0.0.0/8"),  # "this" network (RFC 1122)
    ip_network("100.64.0.0/10"),  # Carrier-grade NAT (RFC 6598)
    ip_network("198.18.0.0/15"),  # Benchmarking (RFC 2544)
    ip_network("240.0.0.0/4"),  # Reserved / future use
    ip_network("224.0.0.0/4"),  # Multicast (RFC 5771)
    ip_network("::1/128"),  # IPv6 loopback
    ip_network("fc00::/7"),  # IPv6 unique-local (ULA)
    ip_network("fe80::/10"),  # IPv6 link-local
    ip_network("ff00::/8"),  # IPv6 multicast
]

_METADATA_IPS: list[IPv4Address | IPv6Address] = [
    ip_address("169.254.169.254"),  # AWS/GCP/Azure metadata
    ip_address("100.100.100.200"),  # Alibaba Cloud metadata
    ip_address("fd00:ec2::254"),  # AWS IMDSv2 IPv6
]

_PRIVATE_HOSTNAME_SUFFIXES: list[str] = [
    ".docker.internal",
]


# ── Public API ─────────────────────────────────────────────────────


def normalize_url(url: str) -> str:
    """Normalize a URL for consistent cache keying.

    Lowercases scheme and hostname, strips trailing slash from path
    (preserving root '/'), and sorts query parameters alphabetically.
    """
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = parsed.path.lower().rstrip("/") if parsed.path.lower() != "/" else "/"
    query = parsed.query
    fragment = parsed.fragment
    # Sort query parameters for consistency
    if query:
        params = sorted(query.lower().split("&"))
        query = "&".join(params)
    normalized = f"{scheme}://{netloc}{path}"
    if query:
        normalized += f"?{query}"
    if fragment:
        normalized += f"#{fragment}"
    return normalized


def extract_domain(url: str, include_scheme: bool = False) -> str:
    """Extract the hostname/netloc from a URL.

    Args:
        url: The URL to parse.
        include_scheme: When True, returns ``scheme://hostname``
            instead of just ``hostname``.

    Returns:
        The hostname (with port if non-default) or ``""`` for empty/invalid URLs.
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if not hostname:
        return ""
    if include_scheme:
        port = f":{parsed.port}" if parsed.port is not None else ""
        host = f"[{hostname}]" if ":" in hostname else hostname
        return f"{parsed.scheme}://{host}{port}"
    return hostname


def is_same_origin(url1: str, url2: str) -> bool:
    """Check whether two URLs share the same scheme and host.

    Comparison is case-insensitive. Port is included when explicitly present.
    """
    p1 = urlparse(url1)
    p2 = urlparse(url2)
    return (
        p1.scheme.lower() == p2.scheme.lower()
        and p1.netloc.lower() == p2.netloc.lower()
    )


def _unmap_ipv4_mapped(
    addr: IPv4Address | IPv6Address,
) -> IPv4Address | IPv6Address:
    """Unwrap IPv4-mapped IPv6 addresses to their embedded IPv4 form.

    ``::ffff:a.b.c.d`` addresses (RFC 4291 section 2.2) represent IPv4
    destinations, so they must be checked against IPv4 private ranges —
    e.g. ``::ffff:127.0.0.1`` is loopback. Without unmapping, the
    address matches no IPv6 private network and the SSRF guard is
    bypassed.
    """
    if isinstance(addr, IPv6Address) and addr.ipv4_mapped is not None:
        return addr.ipv4_mapped
    return addr


def _resolve_to_ips(hostname: str) -> list[IPv4Address | IPv6Address]:
    """Resolve a hostname to all IP addresses (IPv4 and IPv6).

    IPv4-mapped IPv6 results are unwrapped so downstream checks evaluate
    the embedded IPv4 address against IPv4 private ranges.
    """
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
        ips: set[IPv4Address | IPv6Address] = set()
        for _family, _stype, _proto, _canonname, sockaddr in addrinfo:
            try:
                ips.add(_unmap_ipv4_mapped(ip_address(sockaddr[0])))
            except ValueError:
                continue
        return list(ips)
    except socket.gaierror:
        logger.warning("DNS resolution failed for %s — treating as private", hostname)
        return []


def is_private_host(url: str) -> bool:
    """Check if a URL's hostname resolves to a private or internal IP.

    Covers RFC 1918 private ranges, RFC 4193 unique-local IPv6,
    link-local addresses, loopback, cloud metadata endpoints, and
    Docker internal hostnames.

    Returns ``True`` when the host is private, internal, or
    otherwise unsafe to navigate to (SSRF guard).
    """
    parsed = urlparse(url)
    hostname = parsed.hostname or ""

    # Reject empty/relative URLs
    if not hostname:
        return True

    # Check hostname suffixes for internal Docker resolution
    hostname_lower = hostname.lower()
    for suffix in _PRIVATE_HOSTNAME_SUFFIXES:
        if hostname_lower.endswith(suffix):
            return True

    # Check if hostname is itself a private IP literal
    try:
        addr = _unmap_ipv4_mapped(ip_address(hostname))
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                return True
        # It's a valid, non-private IP literal — safe to navigate
        return addr in _METADATA_IPS
    except ValueError:
        pass  # Not an IP literal, treat as hostname

    # Resolve hostname to IPs and check each
    ips = _resolve_to_ips(hostname)
    if not ips:
        # Can't resolve — _resolve_to_ips already logged at WARNING
        return True

    for addr in ips:
        addr = _unmap_ipv4_mapped(addr)
        for net in _PRIVATE_NETWORKS:
            if addr in net:
                return True
        if addr in _METADATA_IPS:
            return True

    return False


def validate_outbound_webhook_url(url: str) -> None:
    """Validate a user-supplied webhook destination before delivery.

    Enforces the shared SSRF policy for outbound webhook POSTs: only
    explicit ``http``/``https`` schemes are allowed, and the host must
    resolve to a public, non-restricted address. Raises ``ValueError``
    with a human-readable reason when the URL is not deliverable, so
    callers can reject it without attempting a request.

    DNS resolution and host checks use the same private/hostile network
    definitions as :func:`is_private_host` (RFC 1918, loopback,
    link-local, multicast, metadata endpoints, Docker internal
    hostnames), and unresolvable hostnames fail closed.

    Raises:
        ValueError: If the URL is missing, uses a non-HTTP(S) scheme,
            has no hostname, or its host is private/restricted.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("webhook URL is missing")

    parsed = urlparse(url)
    if parsed.scheme.lower() not in ("http", "https"):
        raise ValueError(f"webhook URL must use http or https, got {parsed.scheme!r}")

    if not parsed.hostname:
        raise ValueError("webhook URL has no hostname")

    if is_private_host(url):
        raise ValueError("webhook URL resolves to a private or restricted destination")
