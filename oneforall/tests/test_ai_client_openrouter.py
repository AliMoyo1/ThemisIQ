"""OpenRouter provider, privacy, provenance, and anti-drift regression tests."""

import pytest


class _FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        return None

    def json(self):
        return self._data


def _configure(monkeypatch, ai_client):
    monkeypatch.setattr(ai_client, "_provider", lambda: "openrouter")
    monkeypatch.setattr(
        ai_client,
        "_key",
        lambda name: "test-openrouter-key" if name == "OPENROUTER_API_KEY" else "",
    )
    values = {
        "OPENROUTER_MODEL": "z-ai/glm-5.3-flash-20260826",
        "OPENROUTER_SITE_URL": "https://app.themisiq.net",
        "OPENROUTER_APP_NAME": "ThemisIQ",
        "OPENROUTER_REQUIRE_EXACT_MODEL": True,
        "OPENROUTER_ZDR": True,
        "OPENROUTER_DATA_COLLECTION": "deny",
        "OPENROUTER_MAX_INPUT_PRICE_PER_M": 0.25,
        "OPENROUTER_MAX_OUTPUT_PRICE_PER_M": 0.75,
        "OPENROUTER_WEB_SEARCH_ENGINE": "exa",
        "OPENROUTER_WEB_SEARCH_MAX_RESULTS": 5,
        "OPENROUTER_WEB_SEARCH_MAX_TOTAL_RESULTS": 15,
    }
    for name, value in values.items():
        monkeypatch.setattr(ai_client.settings, name, value, raising=False)


def test_openrouter_dispatch_applies_privacy_headers_guardrail_and_model_pin(monkeypatch):
    import httpx
    from core import ai_client

    _configure(monkeypatch, ai_client)
    captured = {}

    def fake_post(self, url, headers=None, json=None):
        captured.update(url=url, headers=headers, body=json)
        return _FakeResponse({
            "model": "z-ai/glm-5.3-flash-20260826",
            "choices": [{"message": {"content": "Verified-looking but advisory answer"}}],
            "usage": {"prompt_tokens": 17, "completion_tokens": 9},
        })

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = ai_client.create_message_full(
        [{"role": "user", "content": "Assess this control"}],
        system="Use the supplied control evidence.",
        max_tokens=250,
    )

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer test-openrouter-key"
    assert captured["headers"]["HTTP-Referer"] == "https://app.themisiq.net"
    assert captured["headers"]["X-OpenRouter-Title"] == "ThemisIQ"
    assert captured["body"]["model"] == "z-ai/glm-5.3-flash-20260826"
    assert captured["body"]["provider"] == {
        "zdr": True,
        "data_collection": "deny",
        "max_price": {"prompt": 0.25, "completion": 0.75},
    }
    assert "Never claim that information is current" in captured["body"]["messages"][0]["content"]
    assert result["model"] == "z-ai/glm-5.3-flash-20260826"
    assert result["input_tokens"] == 17
    assert result["output_tokens"] == 9


def test_openrouter_rejects_routing_alias_when_exact_model_is_required(monkeypatch):
    from core import ai_client

    _configure(monkeypatch, ai_client)
    monkeypatch.setattr(
        ai_client.settings, "OPENROUTER_MODEL", "~google/gemini-flash-latest", raising=False
    )

    with pytest.raises(RuntimeError, match="exact paid model slug"):
        ai_client.create_message([{"role": "user", "content": "hello"}])


def test_openrouter_detects_response_model_drift(monkeypatch):
    import httpx
    from core import ai_client

    _configure(monkeypatch, ai_client)

    def fake_post(self, url, headers=None, json=None):
        return _FakeResponse({
            "model": "different/provider-model",
            "choices": [{"message": {"content": "answer"}}],
            "usage": {},
        })

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(RuntimeError, match="model drift detected"):
        ai_client.create_message([{"role": "user", "content": "hello"}])


def test_openrouter_rejects_response_without_model_identity(monkeypatch):
    import httpx
    from core import ai_client

    _configure(monkeypatch, ai_client)

    def fake_post(self, url, headers=None, json=None):
        return _FakeResponse({
            "choices": [{"message": {"content": "answer"}}],
            "usage": {},
        })

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(RuntimeError, match="omitted model identity"):
        ai_client.create_message([{"role": "user", "content": "hello"}])


def test_openrouter_web_search_normalises_only_response_citations(monkeypatch):
    import httpx
    from core import ai_client

    _configure(monkeypatch, ai_client)
    captured = {}

    def fake_post(self, url, headers=None, json=None):
        captured.update(url=url, headers=headers, body=json)
        return _FakeResponse({
            "model": "z-ai/glm-5.3-flash-20260826",
            "choices": [{"message": {
                "content": '[{"title":"Risk","source_url":"https://cisa.gov/risk"}]',
                "annotations": [
                    {"type": "url_citation", "url_citation": {
                        "url": "https://cisa.gov/risk", "title": "CISA risk bulletin"
                    }},
                    {"type": "url_citation", "url_citation": {
                        "url": "https://cisa.gov/risk", "title": "duplicate"
                    }},
                    {"type": "url_citation", "url_citation": {
                        "url": "https://cisa.gov.evil.example/fake", "title": "lookalike"
                    }},
                    {"type": "other", "url": "https://untrusted.example/"},
                ],
            }}],
            "usage": {
                "prompt_tokens": 101,
                "completion_tokens": 44,
                "server_tool_use": {"web_search_requests": 2},
            },
        })

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    result = ai_client.create_message_web_search(
        [{"role": "user", "content": "Search current risks"}],
        max_searches=3,
        allowed_domains=["cisa.gov", "nist.gov"],
    )

    tool = captured["body"]["tools"][0]
    assert tool["type"] == "openrouter:web_search"
    assert tool["parameters"]["engine"] == "exa"
    assert tool["parameters"]["max_uses"] == 3
    assert tool["parameters"]["allowed_domains"] == ["cisa.gov", "nist.gov"]
    assert captured["body"]["max_tool_calls"] == 3
    assert result["citations"] == [
        {"url": "https://cisa.gov/risk", "title": "CISA risk bulletin"}
    ]
    assert result["searches_used"] == 2
    assert result["model"] == "z-ai/glm-5.3-flash-20260826"


def test_openrouter_web_search_fails_closed_without_citations(monkeypatch):
    import httpx
    from core import ai_client

    _configure(monkeypatch, ai_client)

    def fake_post(self, url, headers=None, json=None):
        return _FakeResponse({
            "model": "z-ai/glm-5.3-flash-20260826",
            "choices": [{"message": {
                "content": '[{"title":"Risk","source_url":"https://invented.example/"}]',
                "annotations": [],
            }}],
            "usage": {"server_tool_use": {"web_search_requests": 0}},
        })

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    with pytest.raises(RuntimeError, match="no verifiable URL citations"):
        ai_client.create_message_web_search(
            [{"role": "user", "content": "Search current risks"}]
        )


def test_openrouter_active_provider_configuration(monkeypatch):
    from core import ai_client

    _configure(monkeypatch, ai_client)
    assert ai_client.is_configured() is True
    assert ai_client.provider_name() == "OpenRouter"
    assert ai_client._model_for_provider() == "z-ai/glm-5.3-flash-20260826"
