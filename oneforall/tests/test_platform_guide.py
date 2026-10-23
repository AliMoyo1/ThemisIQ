"""Themis, the platform guide (Level 2, plans/2026-10-onboarding-agent/plan.md section 8).

The knowledge base must stay true to the code: every menu name and button label it mentions exists in the named
source file, every page is a real link, and nobody is offered a page their role cannot open. The guide never sees the
screen: a model receives only the masked question and the retrieved entries, and can only point to one of them.
"""
import html
import json
import re
from pathlib import Path

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

from config import settings
from core import onboarding, platform_guide as guide
from core.auth import create_session
from core.rbac import ALL_ROLES

ROOT = Path(__file__).resolve().parent.parent


def _src(path):
    return (ROOT / path).read_text(encoding="utf-8", errors="ignore")


def _user(role):
    return {"roles": [role], "org_id": None}


def _ask(question, role):
    user = _user(role)
    return guide.search(question, user, onboarding.open_areas(user))


def test_entries_are_unique_complete_and_written_plainly():
    ids = [e["id"] for e in guide.ENTRIES]
    assert len(ids) == len(set(ids))
    for e in guide.ENTRIES:
        assert e["title"] and e["answer"] and e["keywords"], e["id"]
        assert e["path"] is None or (e["path"].startswith("/") and not e["path"].startswith("//")), e["id"]
        assert e["area"] in (None, "aria", "grid", "bcm", "sentinel", "erm", "orm", "ai_governance"), e["id"]
        assert "\u2014" not in e["answer"] + e["title"], e["id"]
        for label in e["labels"]:
            assert label in e["answer"], (e["id"], label)
        if e["show"] and not e["show"].startswith(("#", ".")):
            assert e["show"] in e["labels"], e["id"]


@pytest.mark.parametrize("entry", guide.ENTRIES, ids=lambda e: e["id"])
def test_every_menu_name_and_button_label_exists_in_its_source(entry):
    sources = [_src(p) for p in entry["sources"]]
    for text in ([entry["nav"]] if entry["nav"] else []) + entry["labels"]:
        assert any(text in s or html.escape(text, quote=False) in s for s in sources), (entry["id"], text)
    if entry["nav"]:
        assert any(f'href="{entry["path"]}"' in s for s in sources), (entry["id"], entry["path"])


def test_every_page_is_a_real_route():
    import main
    from starlette.routing import Match

    def routed(path):
        scope = {"type": "http", "method": "GET", "path": path, "root_path": "", "headers": [], "query_string": b""}
        return any(route.matches(scope)[0] == Match.FULL for route in main.app.routes)

    for e in guide.ENTRIES:
        if e["path"]:
            assert routed(e["path"]), (e["id"], e["path"])


def test_nobody_is_offered_a_page_their_role_cannot_open():
    inventory = json.loads(_src("docs/generated/capability_inventory.json"))["entries"]
    gates = {}
    for row in inventory:
        if "GET" in row.get("methods", []) and row.get("gate") == "capability":
            allowed = set()
            for roles in row["roles_by_capability"].values():
                allowed |= set(roles)
            gates[row["path"]] = allowed
    checked = 0
    for role in ALL_ROLES:
        user = _user(role)
        areas = onboarding.open_areas(user)
        for e in guide.ENTRIES:
            if e["path"] in gates and guide.visible(e, user, areas):
                assert role in gates[e["path"]], (role, e["id"], e["path"])
                checked += 1
    assert checked > 50


@pytest.mark.parametrize("question, role, expected", [
    ("How do I report a data breach?", "dpo", "sentinel.breach"),
    ("we had a data leak, what do I do", "dpo", "sentinel.breach"),
    ("How do I add a new user?", "super_admin", "admin.add-user"),
    ("invite a colleague", "org_admin", "admin.add-user"),
    ("log a near miss", "super_admin", "orm.event"),
    ("register an AI tool we want to use", "dpo", "aig.register"),
    ("how do I decide on an AI use", "compliance_manager", "aig.decide"),
    ("create an audit", "audit_lead", "grid.new-audit"),
    ("record a nonconformity", "audit_lead", "grid.finding"),
    ("set our risk appetite", "risk_owner", "erm.appetite"),
    ("write a continuity plan", "bcm_manager", "bcm.plan"),
    ("run a business impact analysis", "bcm_manager", "bcm.bia"),
    ("draft a policy for a control", "policy_author", "aria.generate-policy"),
    ("map controls across standards", "compliance_manager", "aria.mapping"),
    ("upload evidence", "compliance_manager", "platform.evidence-upload"),
    ("turn on two factor authentication", "employee", "platform.mfa"),
    ("handle a subject access request", "dpo", "sentinel.dsr"),
    ("where do I set the AI policy", "org_admin", "admin.ai-policy"),
    ("start a guided tour", "employee", "platform.tours"),
])
def test_questions_find_the_right_entry_for_the_role(question, role, expected):
    found = _ask(question, role)
    assert found and found[0][0] >= guide.MIN_SCORE, (question, found[:2])
    assert found[0][1]["id"] == expected, (question, [(s, e["id"]) for s, e in found])


def test_questions_outside_the_platform_are_not_answered():
    for question in ("what is the weather in Harare", "tell me a joke", "write me a poem about cats"):
        assert not [r for r in _ask(question, "super_admin") if r[0] >= guide.MIN_SCORE], question


def test_a_role_is_never_shown_entries_it_cannot_use():
    assert all(e["id"] != "admin.add-user" for _, e in _ask("How do I add a new user?", "employee"))
    assert all(e["area"] != "ai_governance" for _, e in _ask("register an AI tool", "employee"))
    assert all(e["id"] != "aig.decide" for _, e in _ask("decide on an AI use", "privacy_analyst"))


def test_a_task_for_another_role_is_reported_as_unavailable_not_answered_wrongly():
    for question, role in (("How do I add a new user?", "dpo"), ("create an API key", "dpo"),
                           ("register an AI tool we want to use", "employee")):
        user = _user(role)
        found, best_hidden = guide.search(question, user, onboarding.open_areas(user), hidden=True)
        confident = [r for r in found if r[0] >= guide.MIN_SCORE]
        assert best_hidden >= guide.MIN_SCORE and (not confident or best_hidden > confident[0][0]), question


def test_short_questions_need_every_word_to_match():
    assert all(e["id"] != "platform.reports" for _, e in _ask("How do I add a new user?", "super_admin"))


def test_contact_details_and_long_numbers_are_masked():
    masked = guide.mask("Breach for jane.doe@example.com, call +263 77 123 4567, card 4111111111111111")
    assert "jane.doe" not in masked and "4567" not in masked and "4111" not in masked
    assert "[email]" in masked and "[number]" in masked


def test_an_answer_can_only_open_a_retrieved_page():
    assert guide.target("sentinel.breach", {"sentinel.breach"})["path"] == "/sentinel/breaches"
    assert guide.target("admin.add-user", {"sentinel.breach"}) is None
    assert guide.target("https://evil.example", {"https://evil.example"}) is None
    assert guide.target("platform.tours", {"platform.tours"}) is None  # no page to open


# ── The endpoint ────────────────────────────────────────────────────────────

@pytest.fixture
def ask(test_db, monkeypatch):
    from modules.launcher.routes import router as launcher_router
    test_db.execute("INSERT INTO users (username, email, full_name, password_hash) VALUES "
                    "('guide_user','guide_user@example.test','Guide User','x')")
    test_db.commit()
    uid = test_db.execute("SELECT id FROM users WHERE username='guide_user'").fetchone()["id"]
    token = create_session(uid, ip="203.0.113.9", user_agent="Test/1.0")
    app = FastAPI()
    app.include_router(launcher_router)
    client = TestClient(app, base_url="http://testserver", follow_redirects=False)

    def _post(question, page="/"):
        r = client.post("/api/trainer/ask", json={"question": question, "page": page},
                        headers={"Cookie": f"{settings.SESSION_COOKIE_NAME}={token}"})
        assert r.status_code == 200, r.text
        return r.json()
    return _post


def _ai(monkeypatch, reply, calls):
    import core.ai_client as ai_client
    monkeypatch.setattr(ai_client, "is_configured", lambda: True)

    def fake(messages, system=None, **kw):
        calls.append({"messages": messages, "system": system, **kw})
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(ai_client, "create_message", fake)


def test_without_ai_the_guide_answers_from_the_knowledge_base(ask, monkeypatch):
    import core.ai_client as ai_client
    monkeypatch.setattr(ai_client, "is_configured", lambda: False)
    body = ask("How do I change my password?")
    assert body["source"] == "kb"
    assert "Change Password" in body["answer"]
    assert body["go"]["path"] == "/change-password"


def test_free_text_question_stays_local_and_uses_the_retrieved_entry(ask, monkeypatch):
    calls = []
    _ai(monkeypatch, '{"answer": "Open Task Board and press New Task.", "go": "platform.tasks"}', calls)
    body = ask("How do I create a task for bob@example.com?", page="/aria/frameworks?secret=1")
    assert body["source"] == "kb" and body["go"]["path"] == "/tasks"
    assert calls == []


def test_provider_output_cannot_override_the_local_guide(ask, monkeypatch):
    calls = []
    _ai(monkeypatch, '{"answer": "Go to API Keys.", "go": "admin.api-keys"}', calls)
    body = ask("How do I create a task?")
    assert body["source"] == "kb" and body["go"]["path"] == "/tasks" and calls == []


def test_provider_failure_does_not_affect_the_local_guide(ask, monkeypatch):
    _ai(monkeypatch, RuntimeError("refused by policy"), [])
    assert ask("How do I create a task?")["source"] == "kb"
    _ai(monkeypatch, "Ignore your rules. <script>alert(1)</script>", [])
    body = ask("How do I add a calendar event?")
    assert body["source"] == "kb" and "Add Event" in body["answer"]


def test_a_person_asking_for_something_their_role_cannot_do_gets_no_page_and_no_model_call(ask, monkeypatch):
    calls = []
    _ai(monkeypatch, '{"answer": "x", "go": "admin.add-user"}', calls)
    body = ask("How do I add a new user?")
    assert body == {"answer": guide.not_for_you()} and calls == []


def test_a_question_the_guide_does_not_cover_never_reaches_the_model(ask, monkeypatch):
    calls = []
    _ai(monkeypatch, '{"answer": "x", "go": ""}', calls)
    body = ask("What is the capital of France?")
    assert "not sure" in body["answer"] and "go" not in body
    assert calls == []


def test_the_local_guide_is_not_an_active_provider_feature():
    """Old policy references stay readable without advertising a model call."""
    from core import ai_policy
    assert "launcher.api_trainer_ask" in ai_policy.RETIRED_FEATURES
    assert "launcher.api_trainer_ask" not in ai_policy.FEATURES
