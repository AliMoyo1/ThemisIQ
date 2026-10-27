"""Bounded retrieval of reviewed authority URLs for capture and comparison.

The egress firewall must also deny private/metadata ranges at connect time:
DNS validation and the HTTP connection are separate lookups. A fetch error is
never an unchanged result. Content extraction is owned by the caller.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass

import httpx

from core.outbound_http import validate_outbound_url
from core.source_registry import AuthoritySource, by_url

MAX_BYTES = 5_000_000


@dataclass(frozen=True)
class CaptureBytes:
    source_key: str
    raw: bytes
    sha256: str
    content_type: str
    parser_version: str


def fetch_source(source: AuthoritySource) -> CaptureBytes:
    # Identity is checked against the registry immediately before transport.
    if by_url(source.url) != source:
        raise ValueError("Source metadata does not match the reviewed catalogue")
    if not source.monitored:
        raise ValueError("This source is a publication pointer pending monitoring and rights review")
    validate_outbound_url(source.url)
    timeout = httpx.Timeout(connect=5, read=15, write=5, pool=5)
    with httpx.Client(timeout=timeout, trust_env=False, follow_redirects=False,
                      headers={"User-Agent": "ThemisIQ-LawMonitor/1.0"}) as client:
        with client.stream("GET", source.url) as response:
            if response.status_code != 200:
                raise ValueError(f"Authority returned HTTP {response.status_code}; review source URL")
            mime = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            expected = "application/pdf" if source.content_type == "pdf" else "text/html"
            if mime != expected:
                raise ValueError("Authority returned an unexpected content type")
            body = bytearray()
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > MAX_BYTES:
                    raise ValueError("Authority page exceeds capture limit")
                body.extend(chunk)
    raw = bytes(body)
    if not raw:
        raise ValueError("Authority returned an empty response")
    return CaptureBytes(source.key, raw, hashlib.sha256(raw).hexdigest(),
                        mime, source.parser_version)
