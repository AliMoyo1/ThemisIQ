"""
Tests for PLAN-28: ERM External Context (emerging risk inbox + AI horizon scan).

Covers the manual CRUD/status flow, add-to-register (with idempotency and
delete-cleanup), the knowledge-only scan's JSON parse hardening, the
grounded scan's citation cross-check (the trust boundary for source_url),
its RuntimeError fallback path, and create_message_web_search's mixed
block / pause_turn continuation parsing.

Uses the standard conftest test_db fixture (fresh SQLite per test) for
everything that touches the database; the pure HTTP-parsing test (8) needs
no database and omits the fixture.
"""
import json
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _create_user(db, username="tester"):
    """erm_enterprise_risks.created_by has an FK to users(id); the fresh
    test_db has no seeded users, so any test that passes a real
    created_by/user_id needs one to actually exist."""
    db.execute(
        "INSERT INTO users (username, email, full_name, password_hash) VALUES (%s,%s,%s,%s)",
        (username, f"{username}@example.com", username.title(), "x"),
    )
    db.commit()
    row = db.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()
    return row["id"]


def test_create_manual_item_and_list_filters_by_status(test_db):
    from modules.erm.data_service import create_emerging, list_emerging

    eid = create_emerging({"title": "Ransomware surge", "summary": "Rising ransomware activity"}, origin="manual")
    assert eid > 0

    all_items = list_emerging()
    assert any(i["id"] == eid for i in all_items)

    new_items = list_emerging(status="new")
    assert any(i["id"] == eid for i in new_items)
    dismissed_items = list_emerging(status="dismissed")
    assert not any(i["id"] == eid for i in dismissed_items)


def test_dismiss_then_reopen(test_db):
    """Reopen only makes sense from dismissed -- reopening a 'new' item
    raises ValueError."""
    from modules.erm.data_service import create_emerging, dismiss_emerging, reopen_emerging

    eid = create_emerging({"title": "Supply chain risk"}, origin="manual")

    with pytest.raises(ValueError):
        reopen_emerging(eid)

    dismiss_emerging(eid)
    reopen_emerging(eid)


def test_add_to_register_creates_risk_and_blocks_double_add(test_db):
    from modules.erm.data_service import (
        create_emerging, add_emerging_to_register, get_enterprise_risk, list_emerging,
    )

    uid = _create_user(test_db)
    eid = create_emerging({
        "title": "Third-party API outage risk",
        "summary": "Vendor dependency risk.",
        "pillar": "Technology & Innovation",
        "source_note": "Industry report XYZ",
    }, origin="manual")

    risk_id = add_emerging_to_register(eid, user_id=uid)
    risk = get_enterprise_risk(risk_id)
    assert risk["title"] == "Third-party API outage risk"
    assert risk["impacted_pillar"] == "Technology & Innovation"
    assert "Source: external context inbox. Industry report XYZ" in risk["description"]

    added_items = list_emerging(status="added")
    match = next(i for i in added_items if i["id"] == eid)
    assert match["added_risk_id"] == risk_id

    with pytest.raises(ValueError):
        add_emerging_to_register(eid, user_id=uid)


def test_scan_emerging_risks_parse_hardening(test_db, monkeypatch):
    """(a) valid JSON with more than 5 items is capped at 5; (b) a fenced
    code block still parses; (c) garbage text yields 0 items, no
    exception. Monkeypatched at the ai_service module boundary -- never
    calls the real API."""
    import modules.erm.ai_service as ai_mod

    six_items = [{"title": f"Risk {i}", "summary": "s", "rationale": "r"} for i in range(6)]
    monkeypatch.setattr(ai_mod, "is_configured", lambda: True)
    monkeypatch.setattr(ai_mod, "create_message", lambda *a, **k: json.dumps(six_items))
    created = ai_mod.scan_emerging_risks({"pillars": [], "frameworks": [], "top_categories": []})
    assert len(created) == 5

    fenced = "```json\n" + json.dumps([{"title": "Fenced Risk", "summary": "s", "rationale": "r"}]) + "\n```"
    monkeypatch.setattr(ai_mod, "create_message", lambda *a, **k: fenced)
    created2 = ai_mod.scan_emerging_risks({"pillars": [], "frameworks": [], "top_categories": []})
    assert len(created2) == 1

    monkeypatch.setattr(ai_mod, "create_message", lambda *a, **k: "not json at all !!!")
    created3 = ai_mod.scan_emerging_risks({"pillars": [], "frameworks": [], "top_categories": []})
    assert created3 == []


def test_delete_risk_nulls_added_risk_id(test_db):
    """delete_enterprise_risk must NULL added_risk_id rather than leaving
    a dangling reference or being blocked by the FK -- the inbox row
    itself survives the risk's deletion."""
    from modules.erm.data_service import (
        create_emerging, add_emerging_to_register, delete_enterprise_risk, list_emerging,
    )

    uid = _create_user(test_db)
    eid = create_emerging({"title": "Delete Cascade Test"}, origin="manual")
    risk_id = add_emerging_to_register(eid, user_id=uid)

    delete_enterprise_risk(risk_id)

    items = list_emerging(status="added")
    match = next(i for i in items if i["id"] == eid)
    assert match["added_risk_id"] is None


def test_scan_emerging_risks_grounded_citation_cross_check(test_db, monkeypatch):
    """Only items whose source_url exactly matches a returned citation are
    stored as ai_scan_web with that URL; everything else (including all
    items when citations come back empty) falls back to ai_scan with
    source_url NULL -- a model can write a plausible URL into its JSON,
    but only the citations array proves a page was actually retrieved."""
    import modules.erm.ai_service as ai_mod
    from modules.erm.data_service import list_emerging

    items = [
        {"title": "Cited Risk A", "summary": "s", "source_url": "https://nist.gov/a", "rationale": "r"},
        {"title": "Cited Risk B", "summary": "s", "source_url": "https://cisa.gov/b", "rationale": "r"},
        {"title": "Uncited Risk C", "summary": "s", "source_url": "https://fake-not-cited.example/c", "rationale": "r"},
    ]
    citations = [
        {"url": "https://nist.gov/a", "title": "NIST Page A"},
        {"url": "https://cisa.gov/b", "title": "CISA Page B"},
    ]
    monkeypatch.setattr(ai_mod, "create_message_web_search", lambda *a, **k: {
        "text": json.dumps(items), "citations": citations, "searches_used": 2,
    })
    created = ai_mod.scan_emerging_risks_grounded({"pillars": [], "frameworks": [], "top_categories": []})
    assert len(created) == 3

    rows = {r["title"]: r for r in list_emerging()}
    assert rows["Cited Risk A"]["origin"] == "ai_scan_web"
    assert rows["Cited Risk A"]["source_url"] == "https://nist.gov/a"
    assert rows["Cited Risk B"]["origin"] == "ai_scan_web"
    assert rows["Cited Risk B"]["source_url"] == "https://cisa.gov/b"
    assert rows["Uncited Risk C"]["origin"] == "ai_scan"
    assert rows["Uncited Risk C"]["source_url"] is None

    # (b) empty citations list -> even a previously-cited-looking URL is untrusted.
    monkeypatch.setattr(ai_mod, "create_message_web_search", lambda *a, **k: {
        "text": json.dumps([items[0]]), "citations": [], "searches_used": 1,
    })
    created2 = ai_mod.scan_emerging_risks_grounded({"pillars": [], "frameworks": [], "top_categories": []})
    rows2 = {r["id"]: r for r in list_emerging()}
    new_row = rows2[created2[0]]
    assert new_row["origin"] == "ai_scan"
    assert new_row["source_url"] is None


def test_grounded_scan_falls_back_to_knowledge_only(test_db, monkeypatch):
    """When create_message_web_search raises (e.g. web search disabled for
    the org), the caller must fall through to the knowledge-only generator
    and still report created items, with grounded=False. Mirrors the exact
    try/except structure api_emerging_scan uses (no HTTP test client
    exists in this suite, so the route's fallback logic is exercised
    directly at the same call sites the route itself uses)."""
    import modules.erm.ai_service as ai_mod
    from modules.erm.data_service import list_emerging

    def raise_runtime(*a, **k):
        raise RuntimeError("Web search not enabled: org admin disabled the feature")
    monkeypatch.setattr(ai_mod, "create_message_web_search", raise_runtime)
    monkeypatch.setattr(ai_mod, "is_configured", lambda: True)
    monkeypatch.setattr(ai_mod, "create_message", lambda *a, **k: json.dumps(
        [{"title": "Fallback Risk", "summary": "s", "rationale": "r"}]
    ))

    grounded = False
    created_ids = []
    try:
        created_ids = ai_mod.scan_emerging_risks_grounded({"pillars": [], "frameworks": [], "top_categories": []})
        grounded = bool(created_ids)
    except Exception:
        pass
    if not created_ids:
        created_ids = ai_mod.scan_emerging_risks({"pillars": [], "frameworks": [], "top_categories": []})
        grounded = False

    assert grounded is False
    assert len(created_ids) == 1
    rows = {r["id"]: r for r in list_emerging()}
    assert rows[created_ids[0]]["title"] == "Fallback Risk"
    assert rows[created_ids[0]]["origin"] == "ai_scan"


def test_create_message_web_search_pause_turn_continuation(monkeypatch):
    """A pause_turn response's assistant content is resent UNCHANGED on the
    continuation call (encrypted_content blocks fail validation if
    modified); both legs' text is joined and searches_used sums across
    both calls. No database needed -- this is pure HTTP-response parsing."""
    import httpx
    from core import ai_client

    monkeypatch.setattr(ai_client, "_provider", lambda: "anthropic")
    monkeypatch.setattr(ai_client, "_key", lambda name: "test-key")

    responses = [
        {
            "stop_reason": "pause_turn",
            "content": [{"type": "text", "text": "Part 1. "}],
            "usage": {"input_tokens": 10, "output_tokens": 20, "server_tool_use": {"web_search_requests": 1}},
        },
        {
            "stop_reason": "end_turn",
            "content": [{"type": "text", "text": "Part 2."}],
            "usage": {"input_tokens": 5, "output_tokens": 8, "server_tool_use": {"web_search_requests": 0}},
        },
    ]
    call_bodies = []

    class _FakeResponse:
        def __init__(self, data):
            self._data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self._data

    def fake_post(self, url, headers=None, json=None):
        call_bodies.append(json)
        return _FakeResponse(responses[len(call_bodies) - 1])

    monkeypatch.setattr(httpx.Client, "post", fake_post)

    result = ai_client.create_message_web_search(
        [{"role": "user", "content": "search for something"}],
        max_searches=3,
        allowed_domains=["nist.gov"],
    )

    assert result["text"] == "Part 1. Part 2."
    assert result["searches_used"] == 1
    assert len(call_bodies) == 2
    second_messages = call_bodies[1]["messages"]
    assert second_messages[-1] == {"role": "assistant", "content": responses[0]["content"]}
