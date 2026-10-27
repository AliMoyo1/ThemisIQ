"""The shared source spine fails closed on transport and unsupported claims."""
import hashlib

import httpx
import pytest

from core import source_fetch, source_interpret, source_registry


def test_registry_preserves_sentinel_keys_and_limits_reproduction():
    from modules.sentinel import living_law
    assert living_law.SOURCES == {key: (source.jurisdiction, source.title, source.url)
                                  for key, source in source_registry.SOURCES.items()
                                  if key in source_registry.SENTINEL_KEYS}
    assert all(source_registry.SOURCES[key].rights == "link_and_short_excerpt"
               for key in source_registry.SENTINEL_KEYS)
    assert source_registry.SOURCES["iso_42001_edition"].rights == "metadata_only"
    with pytest.raises(ValueError, match="pending"):
        source_fetch.fetch_source(source_registry.SOURCES["iso_42001_edition"])
    assert "ico.org.uk" in source_registry.citation_domains()
    assert "www.iso.org" not in source_registry.citation_domains()
    with pytest.raises(ValueError):
        source_registry.by_url("https://127.0.0.1/private")


@pytest.mark.parametrize("status,mime,size", [
    (302, "text/html", 10), (503, "text/html", 10),
    (200, "text/plain", 10), (200, "text/html", source_fetch.MAX_BYTES + 1),
])
def test_fetch_rejects_redirect_failure_mime_and_oversize(monkeypatch, status, mime, size):
    source = source_registry.SOURCES["uk_ico_breach"]
    client = httpx.Client
    monkeypatch.setattr(source_fetch, "validate_outbound_url", lambda url: url)
    monkeypatch.setattr(source_fetch.httpx, "Client", lambda **kwargs: client(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            status, headers={"content-type": mime}, content=b"x" * size))))
    with pytest.raises(ValueError):
        source_fetch.fetch_source(source)


def test_fetch_pins_bytes_and_parser(monkeypatch):
    source = source_registry.SOURCES["uk_ico_breach"]
    client = httpx.Client
    monkeypatch.setattr(source_fetch, "validate_outbound_url", lambda url: url)
    monkeypatch.setattr(source_fetch.httpx, "Client", lambda **kwargs: client(
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, headers={"content-type": "text/html; charset=utf-8"}, content=b"<p>Official text</p>"))))
    capture = source_fetch.fetch_source(source)
    assert capture.sha256 == hashlib.sha256(capture.raw).hexdigest()
    assert capture.parser_version == "visible-text-v1"
    assert capture.source_key == source.key


def test_exact_quote_must_be_in_hash_verified_pinned_capture(monkeypatch):
    source = source_registry.SOURCES["uk_ico_breach"]
    body = "A regulator passage of exact source text."
    capture = {"id": 7, "source_key": source.key, "source_url": source.url,
               "raw_sha256": "a" * 64, "text_sha256": hashlib.sha256(body.encode()).hexdigest(),
               "captured_text": body, "captured_at": "2026-10-27T00:00:00Z", "hash_verified": True}
    claim = source_interpret.verified_quote(capture, "regulator passage")
    assert claim["capture_id"] == 7 and claim["legal_effect"] == "not_determined"
    with pytest.raises(ValueError):
        source_interpret.verified_quote(capture, "Invented rule")
    with pytest.raises(ValueError):
        source_interpret.verified_quote({**capture, "hash_verified": False}, "regulator passage")
    assert source_interpret.draft_change(capture)["verified"] is False  # baseline is not a change


def test_navigation_only_edit_does_not_change_comparable_text():
    from modules.sentinel.living_law import _extract
    article = b"<article><h1>Notice</h1><p>The applicable reporting guidance is available from this authority for specialist review and source comparison.</p></article>"
    a = b"<nav>Old service menu with many links</nav>" + article
    b = b"<nav>New service menu with many links</nav>" + article
    assert _extract(a) == _extract(b)
