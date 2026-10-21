"""
Centralized outbound HTTP policy for webhooks and connectors (PLAN-36 T05,
findings.md F07).

Single place that decides whether a destination URL is safe to contact and
a single, bounded, non-redirecting way to actually contact it. Every
webhook/connector save, test-send, and real delivery path must go through
`validate_outbound_url()` immediately before connecting (DNS answers change;
a URL validated at save time can resolve somewhere else by send time --
DNS rebinding) and `send_outbound()` to make the connection itself.

This module cannot eliminate DNS-rebinding risk on its own: the resolution
in `validate_outbound_url()` and the connection `send_outbound()` opens a
moment later are still two separate DNS lookups (httpx/the OS resolver do
their own connect-time lookup; there is no portable way in Python to force
a low-level socket connect to the exact IP this module already resolved
without reimplementing HTTP/TLS). A production deployment must pair this
with an egress rule/proxy that blocks outbound traffic to private,
link-local, metadata, and management address ranges at the network layer --
see the deployment note this task also adds.
"""
from __future__ import annotations

import dataclasses
import ipaddress
import socket
import time
from urllib.parse import urlparse

import httpx

CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0
WRITE_TIMEOUT = 5.0
POOL_TIMEOUT = 5.0
MAX_RESPONSE_BYTES = 64 * 1024  # a delivery ack body has no business being larger


class OutboundURLError(ValueError):
    """A destination URL failed outbound policy validation."""


@dataclasses.dataclass
class OutboundResult:
    status_code: int
    text: str  # bounded to MAX_RESPONSE_BYTES, decoded best-effort
    elapsed_ms: float


def _is_blocked(ip: "ipaddress.IPv4Address | ipaddress.IPv6Address") -> bool:
    """True if this address must never be contacted from the app server.

    `not ip.is_global` is the actual policy (validate_outbound_url's own
    docstring says "every A/AAAA record... is a global (publicly
    routable) address"). An earlier version of this function instead
    OR'd together is_private/is_loopback/is_link_local/is_reserved/
    is_multicast/is_unspecified, which misses IPv4 Shared Address Space
    (100.64.0.0/10, RFC 6598, used for carrier-grade NAT): that range is
    not globally routable but is also not classified as private,
    loopback, link-local, reserved, multicast, or unspecified by
    Python's ipaddress module, so it passed every one of those checks
    while still being internal infrastructure an attacker should not be
    able to reach (confirmed directly: ipaddress.ip_address('100.64.0.1')
    has is_private=False, is_reserved=False, but is_global=False)."""
    return not ip.is_global


def validate_outbound_url(url: str) -> str:
    """Raise OutboundURLError if `url` fails policy. Returns the
    stripped url on success.

    Checks: HTTPS scheme, a real hostname, no embedded credentials, and
    that *every* A/AAAA record the hostname resolves to is a global
    (publicly routable) address -- a hostname that resolves to even one
    non-global address is rejected outright, since an attacker only needs
    one usable answer.
    """
    url = (url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https":
        raise OutboundURLError("URL must use HTTPS")
    if parsed.username or parsed.password:
        raise OutboundURLError("URL must not contain embedded credentials")
    host = parsed.hostname or ""
    if not host:
        raise OutboundURLError("URL has no hostname")

    try:
        addrinfo = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise OutboundURLError(f"Could not resolve host: {exc.strerror or exc}") from None
    if not addrinfo:
        raise OutboundURLError("Host did not resolve to any address")

    for family, _type, _proto, _canon, sockaddr in addrinfo:
        ip = ipaddress.ip_address(sockaddr[0])
        if _is_blocked(ip):
            raise OutboundURLError("URL resolves to a blocked (non-public) address")

    return url


def send_outbound(url: str, *, method: str = "POST", json=None, content=None,
                   headers: "dict | None" = None) -> OutboundResult:
    """Revalidate `url` immediately, then send with strict per-phase
    timeouts, no redirect following, and a bounded response read.

    Raises OutboundURLError (policy) or an httpx exception (network/DNS/
    TLS/timeout) -- callers decide how to translate that into a truthful
    UI message and a sanitized audit-log entry; this function does not log
    or swallow anything itself.
    """
    url = validate_outbound_url(url)
    timeout = httpx.Timeout(
        connect=CONNECT_TIMEOUT, read=READ_TIMEOUT, write=WRITE_TIMEOUT, pool=POOL_TIMEOUT,
    )
    start = time.monotonic()
    with httpx.Client(timeout=timeout, follow_redirects=False) as client:
        with client.stream(method, url, json=json, content=content, headers=headers) as resp:
            body = bytearray()
            for chunk in resp.iter_bytes():
                remaining = MAX_RESPONSE_BYTES - len(body)
                if remaining <= 0:
                    break
                body.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    break  # this chunk alone reached the cap; don't read further
            elapsed_ms = (time.monotonic() - start) * 1000
            return OutboundResult(
                status_code=resp.status_code,
                text=bytes(body).decode("utf-8", errors="replace"),
                elapsed_ms=elapsed_ms,
            )
