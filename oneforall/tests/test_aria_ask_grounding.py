"""The model cannot turn an arbitrary URL or title into an Ask ARIA citation."""

import asyncio

from modules.aria import ask_service
from modules.aria.ask_grounding import verified_citations


SOURCE = {"content_type": "document", "title": "Policy A", "section": "Access",
          "url_path": "/aria/documents/DOC-A", "body": "Access requires approval.",
          "framework": "ISO 27001", "owner": "Policy owner"}
CITE = {key: SOURCE[key] for key in ("content_type", "title", "section", "url_path")}


def test_exact_retrieved_citation_only():
    assert verified_citations([CITE], [SOURCE]) == [CITE]
    for false_citation in (
        {**CITE, "title": "Policy B"}, {**CITE, "url_path": "https://outside.example/a"},
        {**CITE, "url_path": "//outside.example/a"}, {**CITE, "section": "Other"},
        {**CITE, "content_type": "risk"},
        {**CITE, "title": ["Policy A"]}, {**CITE, "section": {"name": "Access"}},
    ):
        assert verified_citations([false_citation], [SOURCE]) is None
        assert verified_citations([CITE, false_citation], [SOURCE]) is None
    assert verified_citations([], [SOURCE]) is None
    assert verified_citations([CITE, CITE], [SOURCE]) is None
    assert verified_citations([CITE], [{**SOURCE, "url_path": "javascript:alert(1)"}]) is None


def test_answer_abstains_if_model_invents_a_citation(monkeypatch):
    monkeypatch.setattr(ask_service, "init_index", lambda: None)
    monkeypatch.setattr(ask_service, "search", lambda *args, **kwargs: [SOURCE])
    monkeypatch.setattr(ask_service, "_filter_chunks_by_scope", lambda chunks, user: chunks)
    monkeypatch.setattr(ask_service, "_log_qa", lambda *args: None)

    async def fake_model(*args, **kwargs):
        return 'A fabricated answer.\n```json\n[{"content_type":"document","title":"Policy B","section":"Access","url_path":"/aria/documents/DOC-A"}]\n```', {}

    monkeypatch.setattr(ask_service, "_call_ai", fake_model)
    result = asyncio.run(ask_service.ask("Who approves access?", user={"id": 1, "org_id": 1}))
    assert result["covered"] is False and result["citations"] == []
    assert "fabricated" not in result["answer"]
