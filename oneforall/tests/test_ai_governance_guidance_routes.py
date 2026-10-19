"""
AI governance G3 through HTTP: the checklist and a reviewer's "not applicable", the quality checks and their dismissals,
the AI controls with their proof, control mappings, and what an assessment form can start from.

Written by hand: someone not signed in is sent to log in, a person without the capability gets 403, a use the caller may
not open answers exactly like one that does not exist, and a body that is not a JSON object is refused before anything runs.
"""
import pytest

from tests.test_ai_governance_routes import _accepted, http  # noqa: F401
from tests.test_platform_ownership import _insert  # noqa: F401
from tests.test_ai_governance_service import platform_world, world  # noqa: F401

API = "/ai-governance/api"


# ── Who may call what ───────────────────────────────────────────────────────

def _system_reads(app):
    return [("get", f"{API}/systems/{app}/{tail}") for tail in ("checklist", "quality", "controls", "aiia-prefill")]


def _reviewer_calls(app):
    return [("put", f"{API}/systems/{app}/checklist/vendor", {"reason": "Built by us."}),
            ("delete", f"{API}/systems/{app}/checklist/vendor", None),
            ("post", f"{API}/systems/{app}/quality/dismiss", {"key": "x:y:1", "reason": "because"}),
            ("delete", f"{API}/systems/{app}/quality/dismiss?key=x", None),
            ("get", f"{API}/controls/1/suggestions", None),
            ("get", f"{API}/canonical-controls?q=ab", None),
            ("put", f"{API}/control-mappings", {"ai_control_id": 1, "canonical_control_id": 1}),
            ("delete", f"{API}/control-mappings?ai_control_id=1&canonical_control_id=1", None)]


def _call(http, method, path, name, body):
    return http(method, path, name=name, **({"json": body} if body is not None else {}))


def test_nobody_signed_out_reaches_any_of_them(http):
    for method, path in _system_reads(1):
        assert http(method, path, name=None).status_code == 303, path
    for method, path, body in _reviewer_calls(1):
        assert _call(http, method, path, None, body).status_code == 303, path


def test_an_outside_auditor_is_refused_everywhere(http):
    for method, path in _system_reads(1):
        assert http(method, path, name="auditor").status_code == 403, path
    for method, path, body in _reviewer_calls(1):
        assert _call(http, method, path, "auditor", body).status_code == 403, path


def test_ordinary_staff_can_read_a_use_they_can_open_and_change_nothing(http):
    app = _accepted(http)
    for method, path in _system_reads(app):
        assert http(method, path, name="employee_a").status_code == 200, path
    for method, path, body in _reviewer_calls(app):
        assert _call(http, method, path, "employee_a", body).status_code == 403, path


def test_a_use_in_another_unit_answers_exactly_like_one_that_is_not_there(http):
    app = _accepted(http)
    for (method, path), (_, missing) in zip(_system_reads(app), _system_reads(987654)):
        hidden = http(method, path, name="dpo_b")
        gone = http(method, missing, name="dpo_b")
        assert (hidden.status_code, hidden.json()) == (gone.status_code, gone.json()) == (404, {"ok": False, "error": "Not found."}), path
    for method, path, body in _reviewer_calls(app)[:4]:
        assert _call(http, method, path, "dpo_b", body).status_code == 404, path


@pytest.mark.parametrize("method, tail", [("put", "checklist/vendor"), ("post", "quality/dismiss")])
def test_a_body_that_is_not_a_json_object_is_refused(http, method, tail):
    app = _accepted(http)
    path = f"{API}/systems/{app}/{tail}"
    assert http(method, path, name="dpo_a", content=b"{nope", headers={"content-type": "application/json"}).status_code == 400
    assert http(method, path, name="dpo_a", json=["a", "list"]).status_code == 400


# ── The checklist and a reviewer's judgement ────────────────────────────────

def test_a_reviewer_reads_the_checklist_rules_a_step_out_and_puts_it_back(http):
    app = _accepted(http)
    plan = http("get", f"{API}/systems/{app}/checklist", name="dpo_a").json()
    assert plan["rule_version"] == "v1" and [s["key"] for s in plan["steps"]] == ["aiia", "dpia", "ropa", "vendor", "aims", "policy"]
    assert plan["unresolved"] == ["vendor"]
    vendor = next(s for s in plan["steps"] if s["key"] == "vendor")
    assert vendor["applicability"] == "required" and vendor["reasons"] and vendor["action"]["url"].startswith("/vendors")

    path = f"{API}/systems/{app}/checklist/vendor"
    assert http("put", path, name="dpo_a", json={"reason": " "}).status_code == 422
    assert http("put", f"{API}/systems/{app}/checklist/nonsense", name="dpo_a", json={"reason": "because"}).status_code == 404
    assert http("put", path, name="dpo_a", json={"reason": "x" * 501}).status_code == 422
    done = http("put", path, name="dpo_a", json={"reason": "Built by us under licence."})
    assert done.status_code == 200 and done.json() == {"ok": True, "key": "vendor"}

    after = http("get", f"{API}/systems/{app}/checklist", name="dpo_a").json()
    vendor = next(s for s in after["steps"] if s["key"] == "vendor")
    assert vendor["applicability"] == "required" and vendor["effective"] == "not_applicable"
    assert vendor["override"]["reason"] == "Built by us under licence." and vendor["override"]["out_of_date"] is False
    assert after["unresolved"] == []

    assert http("delete", path, name="dpo_a").status_code == 200
    assert http("delete", path, name="dpo_a").status_code == 404
    assert http("get", f"{API}/systems/{app}/checklist", name="dpo_a").json()["unresolved"] == ["vendor"]


def test_a_use_without_a_profile_has_an_empty_checklist_not_an_error(http):
    world = http.world
    plain = _insert(world.db, "applications", name="Plain", business_unit_id=world.unit["A"], is_active=1)
    world.db.commit()
    got = http("get", f"{API}/systems/{plain}/checklist", name="dpo_a").json()
    assert got["profile"] is False and got["steps"] == []
    assert http("put", f"{API}/systems/{plain}/checklist/vendor", name="dpo_a", json={"reason": "because"}).status_code == 409
    assert http("get", f"{API}/systems/{plain}/aiia-prefill", name="dpo_a").status_code == 404


def test_an_assessment_form_starts_from_the_profile_and_says_where_it_came_from(http):
    app = _accepted(http)
    got = http("get", f"{API}/systems/{app}/aiia-prefill", name="dpo_a").json()
    assert got["fields"]["application_id"] == app and got["fields"]["ai_system_name"] == "Ticket summarizer"
    assert got["source"]["kind"] == "AI profile" and got["source"]["updated_at"]


# ── Quality checks and their dismissals ─────────────────────────────────────

def test_a_check_can_be_set_aside_with_a_reason_and_reopened(http):
    app = _accepted(http)
    found = http("get", f"{API}/systems/{app}/quality", name="dpo_a").json()
    assert found["rule_version"] == "v1" and found["unchecked"] == []
    key = "step_not_started:step:vendor"
    finding = next(f for f in found["findings"] if f["key"] == key)
    assert finding["fix"]["url"] and finding["why"] and finding["dismissed"] is None

    path = f"{API}/systems/{app}/quality/dismiss"
    assert http("post", path, name="dpo_a", json={"key": key, "reason": ""}).status_code == 422
    assert http("post", path, name="dpo_a", json={"key": "made_up:x:1", "reason": "because"}).status_code == 404
    assert http("post", path, name="dpo_a", json={"key": key, "reason": "Compensating review.", "expires_at": "2000-01-01"}).status_code == 422
    assert http("post", path, name="dpo_a", json={"key": key, "reason": "Compensating review.", "expires_at": "not a date"}).status_code == 422
    assert http("post", path, name="dpo_a", json={"key": key, "reason": "Compensating review."}).status_code == 200

    again = http("get", f"{API}/systems/{app}/quality", name="dpo_a").json()
    shown = next(f for f in again["findings"] if f["key"] == key)
    assert shown["dismissed"]["reason"] == "Compensating review." and again["open"] == found["open"] - 1

    assert http("delete", f"{path}?key={key}", name="dpo_a").status_code == 200
    assert http("delete", f"{path}?key={key}", name="dpo_a").status_code == 404
    assert http("delete", path, name="dpo_a").status_code == 404, "no key at all is just a finding that was not dismissed"
    assert http("get", f"{API}/systems/{app}/quality", name="dpo_a").json()["open"] == found["open"]


# ── AI controls and mappings ────────────────────────────────────────────────

@pytest.fixture
def controls(http):
    world = http.world
    app = _accepted(http)
    aims = _insert(world.db, "aims_assessments", ref="AIMS-1", title="AI management", business_unit_id=world.unit["A"],
                   application_id=app, status="draft")
    ai = _insert(world.db, "ai_control_catalogue", ref="AC-1", title="Human oversight of model output", business_unit_id=world.unit["A"])
    _insert(world.db, "aims_risks", assessment_id=aims, risk_description="r", catalogue_control_id=ai, in_scope=1, implemented=1)
    canonical = _insert(world.db, "canonical_controls", ref="CC-1", title="Human oversight of automated output", is_active=1)
    inactive = _insert(world.db, "canonical_controls", ref="CC-2", title="Human oversight retired", is_active=0)
    world.db.commit()
    return type("Controls", (), {"app": app, "ai": ai, "canonical": canonical, "inactive": inactive})


def test_a_reviewer_maps_an_ai_control_and_sees_it_with_its_proof_state(http, controls):
    shown = http("get", f"{API}/systems/{controls.app}/controls", name="owner_a").json()
    assert shown["access"] is True
    before = shown["items"]
    assert len(before) == 1 and before[0]["mapped"] is False and before[0]["proof"]["current"] == 0
    denied = http("get", f"{API}/systems/{controls.app}/controls", name="dpo_a").json()
    assert (denied["items"], denied["access"]) == ([], False), "no right to Operations risk is not the same as none recorded"
    assert (before[0]["applicable"], before[0]["implemented"]) == (True, True)

    found = http("get", f"{API}/controls/{controls.ai}/suggestions", name="owner_a").json()["items"]
    assert [f["id"] for f in found] == [controls.canonical] and "Shares:" in found[0]["reason"]
    assert http("get", f"{API}/controls/987654/suggestions", name="owner_a").status_code == 404

    body = {"ai_control_id": controls.ai, "canonical_control_id": controls.canonical}
    made = http("put", f"{API}/control-mappings", name="owner_a", json={**body, "note": "Same intent."})
    assert made.status_code == 200 and made.json() == {"ok": True, "created": True}
    assert http("put", f"{API}/control-mappings", name="owner_a", json=body).json()["created"] is False

    after = http("get", f"{API}/systems/{controls.app}/controls", name="owner_a").json()["items"]
    assert after[0]["mapped"] is True and [m["id"] for m in after[0]["mapped_to"]] == [controls.canonical]

    unmap = f"{API}/control-mappings?ai_control_id={controls.ai}&canonical_control_id={controls.canonical}"
    assert http("delete", unmap, name="owner_a").status_code == 200
    assert http("delete", unmap, name="owner_a").status_code == 404
    assert http("delete", f"{API}/control-mappings?ai_control_id=x", name="owner_a").status_code == 400


def test_a_mapping_needs_real_controls_and_a_reviewer_who_may_see_them(http, controls):
    ok = {"ai_control_id": controls.ai, "canonical_control_id": controls.canonical}
    assert http("put", f"{API}/control-mappings", name="owner_a", json={**ok, "ai_control_id": "x"}).status_code == 400
    assert http("put", f"{API}/control-mappings", name="owner_a", json={**ok, "ai_control_id": True}).status_code == 400
    assert http("put", f"{API}/control-mappings", name="owner_a", json={**ok, "ai_control_id": 987654}).status_code == 404
    assert http("put", f"{API}/control-mappings", name="owner_a", json={**ok, "canonical_control_id": controls.inactive}).status_code == 404
    assert http("put", f"{API}/control-mappings", name="dpo_a", json=ok).status_code == 403, "no right to Operations risk"
    assert http("put", f"{API}/control-mappings", name="owner_b", json=ok).status_code == 404, "the control sits in unit A"


def test_the_canonical_control_picker_finds_by_typing_and_a_wildcard_is_just_a_character(http, controls):
    found = http("get", f"{API}/canonical-controls?q=oversight", name="owner_a").json()["items"]
    assert [c["id"] for c in found] == [controls.canonical], "an inactive control is not offered"
    assert http("get", f"{API}/canonical-controls?q=o", name="owner_a").json()["items"] == []
    assert http("get", f"{API}/canonical-controls?q=%25%25", name="owner_a").json()["items"] == []
    assert http("get", f"{API}/canonical-controls?q=CC-1", name="owner_a").json()["items"][0]["id"] == controls.canonical
    assert http("get", f"{API}/canonical-controls", name="owner_a").json()["items"] == []


# ── The way back from a form opened from a system ───────────────────────────

def test_a_page_opened_from_a_system_offers_the_way_back_and_only_for_a_plain_number(http):
    page = http("get", "/ai-governance/?aig_return=7", name="employee_a")
    assert page.status_code == 200 and 'href="/ai-governance/systems/7#assessments"' in page.text
    for bad in ("7x", "-1", "1234567890", "%3Cscript%3E", ""):
        text = http("get", f"/ai-governance/?aig_return={bad}", name="employee_a").text
        assert "Back to the AI system" not in text, bad
