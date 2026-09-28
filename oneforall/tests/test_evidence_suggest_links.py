"""
PLAN-36 T04 (findings.md F05): the evidence-suggestion risk lookup used to
query enterprise risks by their old, pre-rename table name, which has never
existed -- every call silently reached the `except Exception: suggestions =
[]` fallback with no SQL error surfaced anywhere. Covers the corrected query
(modules/evidence/routes.py api_evidence_suggest_links) reaching the AI
layer cleanly, and that a risk from a business unit the actor isn't scoped
to never appears in the prompt.

Uses the same _mock_auth/_request_as pattern as test_aria_policy_legacy.py
(async route function, real @require_auth needs a real get_current_user).
"""
import asyncio
import types

import pytest

import core.middleware as middleware
import modules.evidence.routes as routes


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _mock_auth(monkeypatch):
    state = {"actor": None}

    async def fake_get_current_user(request):
        return state["actor"]

    monkeypatch.setattr(middleware, "get_current_user", fake_get_current_user)
    return state


def _request_as(auth_state, actor):
    auth_state["actor"] = actor
    return types.SimpleNamespace(state=types.SimpleNamespace(user=actor),
                                  url=types.SimpleNamespace(path="/evidence/test"))


def _bu(db, name):
    db.execute("INSERT INTO business_units (name, is_active) VALUES (%s,1)", (name,))
    db.commit()
    return db.execute("SELECT id FROM business_units WHERE name=%s", (name,)).fetchone()["id"]


def _actor(db, uid, bu_id):
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, business_unit_id) "
        "VALUES (%s,%s,%s,%s,'x',%s)",
        (uid, f"user{uid}", f"user{uid}@example.com", f"User {uid}", bu_id),
    )
    db.commit()
    return {"id": uid, "username": f"user{uid}", "business_unit_id": bu_id, "is_super_admin": 0}


def _evidence_item(db, title="Evidence A"):
    db.execute(
        "INSERT INTO evidence_items (title, category, description, tags) "
        "VALUES (%s,'general','desc','tags')", (title,),
    )
    db.commit()
    return db.execute("SELECT id FROM evidence_items WHERE title=%s", (title,)).fetchone()["id"]


def _risk(db, title, bu_id):
    db.execute(
        "INSERT INTO erm_enterprise_risks (title, category, business_unit_id) VALUES (%s,'operational',%s)",
        (title, bu_id),
    )
    db.commit()


def _audit(db, name, bu_id, framework_id=None):
    db.execute(
        "INSERT INTO grid_audits (name, business_unit_id, framework_id, status) "
        "VALUES (%s,%s,%s,'Planning')",
        (name, bu_id, framework_id),
    )
    db.commit()


def _grid_framework(db, name):
    db.execute("INSERT INTO grid_frameworks (name) VALUES (%s)", (name,))
    db.commit()
    return db.execute("SELECT id FROM grid_frameworks WHERE name=%s", (name,)).fetchone()["id"]


def test_suggest_links_reaches_ai_without_sql_error(test_db, _mock_auth, monkeypatch):
    finance = _bu(test_db, "Finance")
    actor = _actor(test_db, 10, bu_id=finance)
    eid = _evidence_item(test_db)
    _risk(test_db, "In-Scope Risk", bu_id=finance)

    captured = {}

    def fake_create_message(messages, **kwargs):
        captured["prompt"] = messages[0]["content"]
        return "[]"

    monkeypatch.setattr("core.ai_client.is_configured", lambda: True)
    monkeypatch.setattr("core.ai_client.create_message", fake_create_message)
    monkeypatch.setattr("core.ai_client.safe_json_parse", lambda raw: [])

    request = _request_as(_mock_auth, actor)
    result = _run(routes.api_evidence_suggest_links(request, eid))

    assert result.status_code == 200
    assert "prompt" in captured, "create_message (the AI layer) must have been reached"
    assert "In-Scope Risk" in captured["prompt"]


def test_suggest_links_excludes_another_business_units_risk(test_db, _mock_auth, monkeypatch):
    finance = _bu(test_db, "Finance")
    legal = _bu(test_db, "Legal")
    actor = _actor(test_db, 10, bu_id=finance)
    eid = _evidence_item(test_db)
    _risk(test_db, "In-Scope Risk", bu_id=finance)
    _risk(test_db, "Other BU Secret Risk", bu_id=legal)

    captured = {}

    def fake_create_message(messages, **kwargs):
        captured["prompt"] = messages[0]["content"]
        return "[]"

    monkeypatch.setattr("core.ai_client.is_configured", lambda: True)
    monkeypatch.setattr("core.ai_client.create_message", fake_create_message)
    monkeypatch.setattr("core.ai_client.safe_json_parse", lambda raw: [])

    request = _request_as(_mock_auth, actor)
    _run(routes.api_evidence_suggest_links(request, eid))

    assert "In-Scope Risk" in captured["prompt"]
    assert "Other BU Secret Risk" not in captured["prompt"], \
        "another business unit's risk title must never reach the AI prompt"


def test_suggest_links_org_wide_risk_is_visible_to_every_bu(test_db, _mock_auth, monkeypatch):
    """A risk with no business_unit_id (org-wide) must still be suggested,
    matching the same NULL-is-always-visible convention used everywhere
    else bu_scope_ids() is consumed (modules/erm/data_service.py etc.)."""
    finance = _bu(test_db, "Finance")
    actor = _actor(test_db, 10, bu_id=finance)
    eid = _evidence_item(test_db)
    _risk(test_db, "Org Wide Risk", bu_id=None)

    captured = {}

    def fake_create_message(messages, **kwargs):
        captured["prompt"] = messages[0]["content"]
        return "[]"

    monkeypatch.setattr("core.ai_client.is_configured", lambda: True)
    monkeypatch.setattr("core.ai_client.create_message", fake_create_message)
    monkeypatch.setattr("core.ai_client.safe_json_parse", lambda raw: [])

    request = _request_as(_mock_auth, actor)
    _run(routes.api_evidence_suggest_links(request, eid))

    assert "Org Wide Risk" in captured["prompt"]


def test_suggest_links_excludes_another_business_units_audit(test_db, _mock_auth, monkeypatch):
    """Companion to the risk-scoping test above: audits were the one
    unscoped query in this function (findings.md review item) -- a scoped
    user's suggest-links call must not expose another business unit's
    audit names to the AI prompt either."""
    finance = _bu(test_db, "Finance")
    legal = _bu(test_db, "Legal")
    actor = _actor(test_db, 10, bu_id=finance)
    eid = _evidence_item(test_db)
    _audit(test_db, "In-Scope Audit", bu_id=finance)
    _audit(test_db, "Other BU Secret Audit", bu_id=legal)

    captured = {}

    def fake_create_message(messages, **kwargs):
        captured["prompt"] = messages[0]["content"]
        return "[]"

    monkeypatch.setattr("core.ai_client.is_configured", lambda: True)
    monkeypatch.setattr("core.ai_client.create_message", fake_create_message)
    monkeypatch.setattr("core.ai_client.safe_json_parse", lambda raw: [])

    request = _request_as(_mock_auth, actor)
    _run(routes.api_evidence_suggest_links(request, eid))

    assert "In-Scope Audit" in captured["prompt"]
    assert "Other BU Secret Audit" not in captured["prompt"], \
        "another business unit's audit name must never reach the AI prompt"


def test_suggest_links_org_wide_audit_is_visible_to_every_bu(test_db, _mock_auth, monkeypatch):
    finance = _bu(test_db, "Finance")
    actor = _actor(test_db, 10, bu_id=finance)
    eid = _evidence_item(test_db)
    _audit(test_db, "Org Wide Audit", bu_id=None)

    captured = {}

    def fake_create_message(messages, **kwargs):
        captured["prompt"] = messages[0]["content"]
        return "[]"

    monkeypatch.setattr("core.ai_client.is_configured", lambda: True)
    monkeypatch.setattr("core.ai_client.create_message", fake_create_message)
    monkeypatch.setattr("core.ai_client.safe_json_parse", lambda raw: [])

    request = _request_as(_mock_auth, actor)
    _run(routes.api_evidence_suggest_links(request, eid))

    assert "Org Wide Audit" in captured["prompt"]


def test_suggest_links_uses_grid_frameworks_not_shared_frameworks_table(test_db, _mock_auth, monkeypatch):
    """The audit query previously joined the shared `frameworks` table
    (ARIA's), not `grid_frameworks` (GRID's own) -- framework_id values
    from grid_audits don't correspond to rows in the wrong table, so the
    join silently produced NULL/incorrect framework names. Confirms the
    real GRID framework name reaches the prompt."""
    finance = _bu(test_db, "Finance")
    actor = _actor(test_db, 10, bu_id=finance)
    eid = _evidence_item(test_db)
    fw_id = _grid_framework(test_db, "ISO 27001 GRID Copy")
    _audit(test_db, "Framework-Linked Audit", bu_id=finance, framework_id=fw_id)

    captured = {}

    def fake_create_message(messages, **kwargs):
        captured["prompt"] = messages[0]["content"]
        return "[]"

    monkeypatch.setattr("core.ai_client.is_configured", lambda: True)
    monkeypatch.setattr("core.ai_client.create_message", fake_create_message)
    monkeypatch.setattr("core.ai_client.safe_json_parse", lambda raw: [])

    request = _request_as(_mock_auth, actor)
    _run(routes.api_evidence_suggest_links(request, eid))

    # audits[:20] is interpolated into the prompt via str(list-of-dicts),
    # so the framework_name value itself appears in the text only if the
    # join actually matched a real grid_frameworks row.
    assert "ISO 27001 GRID Copy" in captured["prompt"]
