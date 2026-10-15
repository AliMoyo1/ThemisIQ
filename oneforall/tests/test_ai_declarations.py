"""
The platform's AI use cases declare what they do, and a feature that needs the assistant does not make an answer up
(plans/2026-10-governance-rework/04 section 6, acceptance scenario 6).

Before this a plan review, a risk score, a list of risks identified from an assessment and an operational event analysis
returned canned content when the assistant was off or failed, and the first of them was saved as a review nobody made and
the second written over the owner's score. The declarations tell a reader what each place does; these tests keep the
register complete and keep two of its claims true.
"""
import asyncio
import ast
import json
import pathlib
import types

import pytest

import core.middleware as middleware
from core import ai_client, ai_declarations as decl, rbac
from core.ai_client import AIUnavailable
from core.ai_policy import FEATURES

ROOT = pathlib.Path(__file__).resolve().parents[1]
ORG = 1


# ── The register ────────────────────────────────────────────────────────────

def test_every_feature_the_platform_calls_a_model_for_is_declared_and_nothing_else():
    assert set(decl.DECLARATIONS) == set(FEATURES)


def test_each_declaration_is_complete_and_uses_the_closed_vocabulary():
    for key, d in decl.DECLARATIONS.items():
        for field in ("task", "reads", "leaves_out", "trigger", "output"):
            assert isinstance(getattr(d, field), str) and getattr(d, field).strip(), (key, field)
        assert d.approval in decl.APPROVAL, key
        assert d.fallback in decl.FALLBACK, key
    shown = decl.declaration("erm.score_risk")
    assert shown["label"] == FEATURES["erm.score_risk"][0] and shown["categories"] == ["business"]
    assert shown["approval_words"] == decl.APPROVAL["person"]


def test_only_these_features_write_without_a_review_step():
    """A change to this set is a decision about the data, not a refactor."""
    assert decl.WRITES_WITHOUT_REVIEW == {"core.auto_map_controls", "governance.run_drift_check", "grid.batch_risk_score"}


def _sites():
    """feature id -> list of (path, enclosing function source)."""
    found = {}
    for path in sorted(ROOT.rglob("*.py")):
        parts = path.relative_to(ROOT).parts
        if parts[0] in ("tests", ".venv", "scripts", "seeds", "node_modules") or "__pycache__" in parts:
            continue
        try:
            text = path.read_text(encoding="utf-8-sig")
            tree = ast.parse(text)
        except Exception:
            continue
        funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        lines = text.split("\n")
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "feature" and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str):
                line = node.value.lineno
                enclosing = None
                for f in funcs:
                    if f.lineno <= line <= (f.end_lineno or f.lineno) and (enclosing is None or f.lineno >= enclosing.lineno):
                        enclosing = f
                if enclosing is not None:
                    found.setdefault(node.value.value, []).append(
                        "\n".join(lines[enclosing.lineno - 1: enclosing.end_lineno]))
    return found


def test_a_feature_that_says_unavailable_has_no_canned_answer_in_its_code():
    sites = _sites()
    for key, d in decl.DECLARATIONS.items():
        if d.fallback == "unavailable":
            assert key in sites, f"{key}: no call site found"
            for source in sites[key]:
                assert "_stub" not in source, f"{key} declares 'unavailable' but its code returns a stub"


def test_a_feature_that_says_labelled_or_template_still_has_the_placeholder_it_declares():
    sites = _sites()
    for key, d in decl.DECLARATIONS.items():
        if d.fallback in ("labelled", "template"):
            # a feature served by the same function as another (the three assistants share a chat route) is checked
            # through the function that holds the placeholder
            assert any("_stub" in source or "stub]" in source for source in sites[key]),                 f"{key}: the declaration is out of date"


# ── What the services do now ────────────────────────────────────────────────

@pytest.fixture
def ai_off(monkeypatch):
    monkeypatch.setattr(ai_client, "is_configured", lambda: False)


@pytest.fixture
def ai_on(monkeypatch):
    monkeypatch.setattr(ai_client, "is_configured", lambda: True)

    def reply(text):
        monkeypatch.setattr("modules.erm.ai_service.create_message", lambda *a, **k: text)
        monkeypatch.setattr("modules.bcm.ai_service.create_message", lambda *a, **k: text)
        monkeypatch.setattr("modules.orm.ai_service.create_message", lambda *a, **k: text)
    return reply


def test_when_the_assistant_is_off_these_features_raise_instead_of_returning_content(ai_off):
    from modules.bcm import ai_service as bcm
    from modules.erm import ai_service as erm
    from modules.orm import ai_service as orm
    calls = [
        lambda: erm.score_risk("Supplier failure", "A key supplier stops", "operational"),
        lambda: erm.suggest_scores("t", "d", "c", {"dimensions": [], "likelihood": []}),
        lambda: erm.suggest_treatment("t", "d", "c", 3, 3),
        lambda: erm.generate_risk_statement("operational", "d"),
        lambda: erm.suggest_assessment_questions("self", ["r"], []),
        lambda: erm.identify_risks_from_responses("Q: a A: b", "Assessment"),
        lambda: erm.smart_remediation_plan("t", "d", "c", 9),
        lambda: bcm.review_plan({"title": "Plan", "content": "text"}),
        lambda: bcm.suggest_incident_actions({"title": "Fire"}),
        lambda: bcm.rag_ask("What is our RTO?"),
        lambda: orm.analyze_event({"title": "Outage"}),
    ]
    for call in calls:
        with pytest.raises(AIUnavailable) as caught:
            call()
        assert caught.value.reason == "not_configured"
        assert "not configured" in str(caught.value)


def test_an_unreadable_answer_is_unavailable_not_a_default(ai_on):
    from modules.bcm import ai_service as bcm
    from modules.erm import ai_service as erm
    from modules.orm import ai_service as orm
    ai_on("I could not do that as JSON.")
    for call in (lambda: erm.score_risk("t", "d"), lambda: bcm.review_plan({"title": "p", "content": "c"}),
                 lambda: orm.analyze_event({"title": "e"}), lambda: erm.identify_risks_from_responses("x", "y")):
        with pytest.raises(AIUnavailable) as caught:
            call()
        assert caught.value.reason == "unreadable"
    ai_on(json.dumps({"likelihood": 9, "impact": 2}))
    with pytest.raises(AIUnavailable):
        erm.score_risk("t", "d")  # outside the 1 to 5 scale
    ai_on(json.dumps({"score": 150, "strengths": [], "weaknesses": [], "recommendations": []}))
    with pytest.raises(AIUnavailable):
        bcm.review_plan({"title": "p", "content": "c"})


def test_a_readable_answer_is_returned_as_it_was_given(ai_on):
    from modules.bcm import ai_service as bcm
    from modules.erm import ai_service as erm
    ai_on(json.dumps({"likelihood": 4, "impact": 5, "rationale": "Single supplier"}))
    assert erm.score_risk("t", "d") == {"likelihood": 4, "impact": 5, "rationale": "Single supplier"}
    ai_on(json.dumps({"score": 64, "strengths": ["Clear roles"], "weaknesses": ["No RTOs"], "recommendations": ["Test"]}))
    review = bcm.review_plan({"title": "p", "content": "c"})
    assert review["score"] == 64 and review["weaknesses"] == ["No RTOs"]


def test_a_policy_refusal_keeps_its_own_sentence(monkeypatch):
    from core.ai_policy import AIPolicyError
    from modules.erm import ai_service as erm
    monkeypatch.setattr(ai_client, "is_configured", lambda: True)

    def refuse(*a, **k):
        raise AIPolicyError("blocked", "This organization has turned off risk scoring.")

    monkeypatch.setattr("modules.erm.ai_service.create_message", refuse)
    with pytest.raises(AIPolicyError) as caught:
        erm.score_risk("t", "d")
    assert "turned off risk scoring" in str(caught.value)


# ── The routes ──────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    async def current_user(request):
        return request.state.user

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    monkeypatch.setattr(middleware, "check_ai_rate_limit", lambda uid: True)
    monkeypatch.setattr(middleware, "record_ai_call", lambda uid: None)


def _request(user, payload=None):
    request = types.SimpleNamespace(state=types.SimpleNamespace(user=user), url=types.SimpleNamespace(path="/api"),
                                    query_params={}, client=None)
    if payload is not None:
        async def _json():
            return payload
        request.json = _json
    return request


def _insert(db, table, **cols):
    cur = db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                     tuple(cols.values()))
    db.commit()
    return cur.lastrowid


@pytest.fixture
def estate(test_db):
    db = test_db
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,'org','org')", (ORG,))
    db.commit()
    a = _insert(db, "business_units", name="Unit A", is_active=1)
    b = _insert(db, "business_units", name="Unit B", is_active=1)
    users = {}
    for i, (name, role, unit) in enumerate((("owner_a", rbac.RISK_OWNER, a), ("compliance_a", rbac.COMPLIANCE_MGR, a),
                                            ("bcm_a", rbac.BCM_MANAGER, a)), start=1):
        _insert(db, "users", id=i, username=name, email=f"{name}@example.test", full_name=name, password_hash="x",
                org_id=ORG, business_unit_id=unit)
        users[name] = {"id": i, "username": name, "full_name": name, "org_id": ORG, "business_unit_id": unit,
                       "is_super_admin": 0, "roles": [role]}
    return types.SimpleNamespace(db=db, a=a, b=b, users=users)


def _run(coro):
    return asyncio.run(coro)


def test_an_ai_risk_score_is_a_suggestion_the_owners_score_stays(estate, monkeypatch):
    import modules.erm.routes as routes
    risk = _insert(estate.db, "erm_enterprise_risks", title="Supplier failure", likelihood=2, impact=2,
                   business_unit_id=estate.a)
    monkeypatch.setattr(routes.ai, "score_risk", lambda *a, **k: {"likelihood": 5, "impact": 5, "rationale": "r"})
    response = _run(routes.api_ai_score_risk(_request(estate.users["compliance_a"]), risk))
    body = json.loads(response.body)
    assert response.status_code == 200 and body["applied"] is False
    assert (body["likelihood"], body["impact"]) == (5, 5) and body["current"] == {"likelihood": 2, "impact": 2}
    stored = estate.db.execute("SELECT likelihood, impact FROM erm_enterprise_risks WHERE id = %s", (risk,)).fetchone()
    assert (stored["likelihood"], stored["impact"]) == (2, 2), "a compliance manager has erm.ai.use, not erm.risk.manage"


def test_an_ai_risk_score_cannot_reach_a_risk_in_another_business_unit(estate, monkeypatch):
    import modules.erm.routes as routes
    from fastapi import HTTPException
    other = _insert(estate.db, "erm_enterprise_risks", title="Unit B risk", likelihood=3, impact=3,
                    business_unit_id=estate.b)
    seen = []
    monkeypatch.setattr(routes.ai, "score_risk", lambda *a, **k: seen.append(a) or {"likelihood": 1, "impact": 1})
    with pytest.raises(HTTPException) as caught:
        _run(routes.api_ai_score_risk(_request(estate.users["owner_a"]), other))
    assert caught.value.status_code == 404 and seen == [], "the other unit's title never reached the model"
    with pytest.raises(HTTPException):
        _run(routes.api_remediation_plan(_request(estate.users["owner_a"]), other))


def test_with_the_assistant_off_a_plan_review_is_not_recorded(estate, monkeypatch, ai_off):
    import modules.bcm.routes as routes
    from fastapi import HTTPException
    plan = _insert(estate.db, "bcm_plans", title="Plan A", business_unit_id=estate.a, content="text")
    with pytest.raises(HTTPException) as caught:
        _run(routes.api_plan_review_create(_request(estate.users["bcm_a"]), plan))
    assert caught.value.status_code == 502 and "not configured" in str(caught.value.detail)
    reviews = estate.db.execute("SELECT COUNT(*) FROM bcm_plan_reviews").fetchone()[0]
    assert reviews == 0, "no review was made, so none is on the plan"


def test_a_plan_review_is_stored_with_its_score_and_lists_and_names_the_provider(estate, monkeypatch):
    import modules.bcm.ai_service as ai_service
    import modules.bcm.routes as routes
    plan = _insert(estate.db, "bcm_plans", title="Plan A", business_unit_id=estate.a, content="text")
    monkeypatch.setattr(ai_client, "is_configured", lambda: True)
    monkeypatch.setattr(ai_client, "provider_name", lambda: "openrouter")
    monkeypatch.setattr(ai_service, "create_message", lambda *a, **k: json.dumps(
        {"score": 64, "strengths": ["Clear roles"], "weaknesses": ["No RTOs"], "recommendations": ["Test it"]}))
    response = _run(routes.api_plan_review_create(_request(estate.users["bcm_a"]), plan))
    body = json.loads(response.body)
    assert response.status_code == 201 and body["overall_score"] == 64 and body["gaps"] == ["No RTOs"]
    assert body["provider"] == "openrouter"
    stored = estate.db.execute("SELECT * FROM bcm_plan_reviews WHERE id = %s", (body["id"],)).fetchone()
    assert stored["overall_score"] == 64 and json.loads(stored["gaps"]) == ["No RTOs"]
    assert stored["provider"] == "openrouter" and stored["reviewer_name"] == "bcm_a"


def test_a_plan_review_cannot_reach_a_plan_in_another_business_unit(estate, monkeypatch):
    import modules.bcm.routes as routes
    from fastapi import HTTPException
    plan = _insert(estate.db, "bcm_plans", title="Plan B", business_unit_id=estate.b, content="secret text")
    seen = []
    monkeypatch.setattr("modules.bcm.ai_service.review_plan", lambda p: seen.append(p) or {})
    with pytest.raises(HTTPException) as caught:
        _run(routes.api_plan_review_create(_request(estate.users["bcm_a"]), plan))
    assert caught.value.status_code == 404 and seen == []


def test_an_operational_event_analysis_fills_only_what_is_empty_and_only_in_scope(estate, monkeypatch):
    import modules.orm.routes as routes
    from fastapi import HTTPException
    mine = _insert(estate.db, "orm_events", title="Outage", business_unit_id=estate.a,
                   root_cause_category="people", corrective_action="")
    theirs = _insert(estate.db, "orm_events", title="Other unit outage", business_unit_id=estate.b)
    monkeypatch.setattr(routes.ai, "analyze_event", lambda ev: {
        "root_cause_category": "system", "root_cause_analysis": "x", "corrective_action": "Restart it",
        "preventive_action": "Add monitoring"})
    _run(routes.api_ai_analyze(_request(estate.users["owner_a"]), mine))
    row = estate.db.execute("SELECT root_cause_category, corrective_action, preventive_action FROM orm_events WHERE id = %s",
                            (mine,)).fetchone()
    assert row["root_cause_category"] == "people", "a person's category is not replaced"
    assert row["corrective_action"] == "Restart it" and row["preventive_action"] == "Add monitoring"
    with pytest.raises(HTTPException) as caught:
        _run(routes.api_ai_analyze(_request(estate.users["owner_a"]), theirs))
    assert caught.value.status_code == 404


def test_the_unavailable_sentence_reaches_the_person_as_json(estate):
    """main.py turns AIUnavailable into a 503 with the sentence in `detail`, which the shared client shows."""
    import main
    handler = main.app.exception_handlers[AIUnavailable]
    response = _run(handler(None, AIUnavailable("The AI assistant is not configured.", "not_configured")))
    body = json.loads(response.body)
    assert response.status_code == 503 and body["detail"] == body["error"] == "The AI assistant is not configured."
    assert body["ai_unavailable"] is True and body["reason"] == "not_configured"
