"""DNS/IP safety checks for SSRF protection.

Checks whether a URL resolves to a private/internal IP address before
attempting to scrape it. The actual check delegates to the shared
``common.url.is_private_host`` function.
"""

import logging
import socket
from ipaddress import ip_address, ip_network

logger = logging.getLogger(__name__)

# ── Private IP / SSRF protection ─────────────────────────────────

_PRIVATE_NETWORKS = [
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("127.0.0.0/8"),
    ip_network("::1/128"),
    ip_network("169.254.0.0/16"),
    ip_network("0.0.0.0/8"),
    ip_network("100.64.0.0/10"),
    ip_network("198.18.0.0/15"),
    ip_network("240.0.0.0/4"),
]

_METADATA_IPS = {
    ip_address("169.254.169.254"),
    ip_address("fd00:ec2::254"),
}

_PRIVATE_HOSTNAME_SUFFIXES = [
    ".docker.internal",
]


def _resolve_to_ips(hostname: str) -> list:
    try:
        addrinfo = socket.getaddrinfo(hostname, None)
        ips = set()
        for _family, _, _, _, sockaddr in addrinfo:
            try:
                ips.add(ip_address(sockaddr[0]))
            except ValueError:
                continue
        return list(ips)
    except socket.gaierror:
        return []


def _is_private_url(url: str) -> tuple[bool, str]:
    """Check if a URL targets a private/internal IP or hostname.

    Returns (is_private, reason) tuple. Shared logic with browser-svc.

    Delegates to the shared ``common.url.is_private_host``
    for the actual check, then maps the boolean result back to the
    ``(bool, str)`` tuple format.
    """
    from common.url import is_private_host as _shared_is_private

    return (True, "Private or internal URL") if _shared_is_private(url) else (False, "")
