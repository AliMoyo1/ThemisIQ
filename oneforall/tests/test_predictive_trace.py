"""
A predictive risk number can be traced to the records it was made from
(plans/2026-10-governance-rework/04 section 9, acceptance scenario 5).

Expectations are written by hand from the formula in core/predictive_risk.py and from the registry rules in
modules/governance/entity_scope.py. Every "is not shown" has a positive twin: the same situation for a person who
may open the record. A dispute is a note beside the number and changes nothing.
"""
import asyncio
import json
import math
import types
from datetime import timedelta

import pytest

import core.middleware as middleware
from core import predictive_risk as pr
from core import rbac
from core.timeutils import utcnow
from modules.launcher import predictive_trace as trace

# Bind the router's names to the real functions at collection time (the fixture below replaces get_current_user).
from modules.launcher import routes_dashboard as _dash  # noqa: E402,F401

ORG = 1


def _insert(db, table, **cols):
    cur = db.execute(f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
                     tuple(cols.values()))
    db.commit()
    return cur.lastrowid


def _day(days_ago: int) -> str:
    return (utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%d")


def _stamp(days_ago: int) -> str:
    return (utcnow() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    async def current_user(request):
        return request.state.user

    monkeypatch.setattr(middleware, "get_current_user", current_user)


@pytest.fixture
def world(test_db):
    """Units A and B; two open breaches (one per unit), findings, exercises, events, controls and appetite."""
    db = test_db
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (1, 'org', 'org')")
    db.commit()
    unit_a = _insert(db, "business_units", name="Unit A", is_active=1)
    unit_b = _insert(db, "business_units", name="Unit B", is_active=1)

    people = {}
    for i, (name, role, unit, platform) in enumerate((
            ("platform", rbac.SUPER_ADMIN, None, 1), ("org_admin", rbac.ORG_ADMIN, None, 0),
            ("dpo_a", rbac.DPO, unit_a, 0), ("employee_a", rbac.EMPLOYEE, unit_a, 0)), start=1):
        _insert(db, "users", id=i, username=name, email=f"{name}@example.test", full_name=name.replace("_", " ").title(),
                password_hash="x", org_id=ORG, business_unit_id=unit, is_super_admin=platform)
        people[name] = {"id": i, "username": name, "full_name": name.replace("_", " ").title(), "org_id": ORG,
                        "business_unit_id": unit, "is_super_admin": platform, "roles": [role]}

    rec = {}
    rec["breach_a"] = _insert(db, "sentinel_breaches", ref_number="BR-A", title="Breach in A", severity="critical",
                              status="open", discovery_date=_day(1), business_unit_id=unit_a)
    rec["breach_b"] = _insert(db, "sentinel_breaches", ref_number="BR-B", title="Breach in B", severity="medium",
                              status="investigating", discovery_date=_day(20), business_unit_id=unit_b)
    rec["breach_closed"] = _insert(db, "sentinel_breaches", ref_number="BR-C", title="Closed breach",
                                   severity="critical", status="closed", discovery_date=_day(3),
                                   business_unit_id=unit_a)
    audit_a = _insert(db, "grid_audits", name="Audit A", business_unit_id=unit_a)
    audit_b = _insert(db, "grid_audits", name="Audit B", business_unit_id=unit_b)
    rec["nc_a"] = _insert(db, "grid_non_conformances", audit_id=audit_a, title="Critical finding A",
                          severity="critical", status="open")
    rec["nc_b"] = _insert(db, "grid_non_conformances", audit_id=audit_b, title="Major finding B",
                          severity="major", status="open")
    rec["nc_minor"] = _insert(db, "grid_non_conformances", audit_id=audit_a, title="Minor finding",
                              severity="minor", status="open")
    rec["nc_closed"] = _insert(db, "grid_non_conformances", audit_id=audit_a, title="Closed finding",
                               severity="critical", status="closed")
    rec["ex_old"] = _insert(db, "bcm_exercises", title="Old exercise", status="completed",
                            scheduled_date=_day(200), business_unit_id=unit_a)
    rec["ex_new"] = _insert(db, "bcm_exercises", title="Latest exercise", status="completed",
                            scheduled_date=_day(30), business_unit_id=unit_a)
    rec["ex_planned"] = _insert(db, "bcm_exercises", title="Planned exercise", status="planned",
                                scheduled_date=_day(-20), business_unit_id=unit_a)
    rec["ev_a"] = _insert(db, "orm_events", title="Recurring in A", is_recurring=1, created_at=_stamp(2),
                          business_unit_id=unit_a)
    rec["ev_b"] = _insert(db, "orm_events", title="Recurring in B", is_recurring=1, created_at=_stamp(5),
                          business_unit_id=unit_b)
    rec["ev_old"] = _insert(db, "orm_events", title="Recurring long ago", is_recurring=1, created_at=_stamp(90),
                            business_unit_id=unit_a)
    rec["ev_once"] = _insert(db, "orm_events", title="Happened once", is_recurring=0, created_at=_stamp(1),
                             business_unit_id=unit_a)
    fw = _insert(db, "frameworks", name="Trace framework")
    rec["ctl_done"] = _insert(db, "controls", framework_id=fw, ref="T-1", name="Implemented control",
                              status="Implemented")
    rec["ctl_1"] = _insert(db, "controls", framework_id=fw, ref="T-2", name="Control in progress",
                           status="In Progress")
    rec["ctl_2"] = _insert(db, "controls", framework_id=fw, ref="T-3", name="Control not started",
                           status="Not Started")
    rec["ctl_3"] = _insert(db, "controls", framework_id=fw, ref="T-4", name="Control with documents only",
                           status="Partially Implemented")
    _insert(db, "erm_risk_appetite", category="cyber", max_score=6)
    _insert(db, "erm_risk_appetite", category="strategic", max_score=20)
    _insert(db, "erm_enterprise_risks", title="Cyber risk", category="cyber", likelihood=4, impact=4, status="open")
    _insert(db, "erm_enterprise_risks", title="Closed cyber risk", category="cyber", likelihood=5, impact=5,
            status="closed")
    _insert(db, "erm_enterprise_risks", title="Strategic risk", category="strategic", likelihood=2, impact=2,
            status="open")
    return types.SimpleNamespace(db=db, rec=rec, people=people, unit_a=unit_a, unit_b=unit_b)


def _store(db, metrics: dict) -> "tuple[int, dict]":
    """Store a prediction the way the route does."""
    result = pr.compute_delta_p(metrics)
    cur = db.execute(
        "INSERT INTO ai_risk_predictions (delta_p, delta_cyber, delta_operational, delta_compliance, confidence, "
        "risk_level, telemetry_json, contributions_json) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
        (result["delta_p"], result["delta_cyber"], result["delta_operational"], result["delta_compliance"],
         result["confidence"], result["risk_level"], json.dumps(metrics), json.dumps(result["signal_contributions"])))
    db.commit()
    return cur.lastrowid, result


def _ids(part) -> list:
    return [r["id"] for r in part["records"]]


# ── What is kept with a prediction ──────────────────────────────────────────

def test_each_signal_keeps_exactly_the_records_it_was_made_from(world):
    t = pr.collect_telemetry(world.db)["trace"]
    r = world.rec

    assert t["breaches"]["count"] == 2, "open and investigating count; the closed one does not"
    assert _ids(t["breaches"]) == [r["breach_a"], r["breach_b"]], "heaviest first: critical and fresh, then medium"
    weights = [x["weight"] for x in t["breaches"]["records"]]
    assert weights[0] > weights[1] > 0

    assert t["non_conformances"]["count"] == 2
    assert _ids(t["non_conformances"]) == [r["nc_a"], r["nc_b"]], "critical weighs 4, major 3; minor and closed are out"

    assert t["bcm_staleness"]["count"] == 1 and _ids(t["bcm_staleness"]) == [r["ex_new"]]
    assert t["bcm_staleness"]["none_found"] is False

    assert t["orm_recurring"]["count"] == 2, "the recurring event from 90 days ago and the one-off are out"
    assert sorted(_ids(t["orm_recurring"])) == sorted([r["ev_a"], r["ev_b"]])

    assert t["compliance_gap"]["count"] == 3 and t["compliance_gap"]["of"] == 4
    assert _ids(t["compliance_gap"]) == [r["ctl_1"], r["ctl_2"], r["ctl_3"]]

    assert t["appetite_breaches"]["count"] == 1
    assert t["appetite_breaches"]["categories"] == ["cyber"], "the strategic risk is inside its appetite"


def test_the_weights_kept_add_up_to_the_figure_the_formula_used(world):
    metrics = pr.collect_telemetry(world.db)
    listed = sum(r["weight"] for r in metrics["trace"]["breaches"]["records"])
    assert listed == pytest.approx(metrics["B"], abs=0.01)
    assert sum(r["weight"] for r in metrics["trace"]["non_conformances"]["records"]) == pytest.approx(metrics["F"])
    assert metrics["F"] == pytest.approx(7.0), "4 for the critical finding and 3 for the major one"


def test_a_signal_with_more_records_than_the_limit_keeps_the_limit_and_the_count(world):
    for i in range(30):
        _insert(world.db, "orm_events", title=f"Again {i}", is_recurring=1, created_at=_stamp(1))
    t = pr.collect_telemetry(world.db)["trace"]["orm_recurring"]
    assert t["count"] == 32 and len(t["records"]) == pr.TRACE_LIMIT == 25

    stored, _ = _store(world.db, pr.collect_telemetry(world.db))
    out = trace.build(world.db, world.people["platform"], stored)
    part = next(s for s in out["signals"] if s["key"] == "orm_recurring")
    assert part["count"] == 32 and part["truncated"] is True and len(part["records"]) == 25
    other = next(s for s in out["signals"] if s["key"] == "breaches")
    assert other["truncated"] is False, "the two breaches are all listed"


def test_no_completed_exercise_is_said_in_words_and_reads_as_a_year(world):
    world.db.execute("DELETE FROM bcm_exercises")
    world.db.commit()
    metrics = pr.collect_telemetry(world.db)
    assert metrics["days_since_exercise"] == 365.0
    stored, _ = _store(world.db, metrics)
    part = next(s for s in trace.build(world.db, world.people["platform"], stored)["signals"]
                if s["key"] == "bcm_staleness")
    assert part["none_found"] is True and part["records"] == []
    assert part["figure"] == pytest.approx((365.0 - 180.0) / 180.0, abs=1e-4)
    assert part["direction"] == "raises"


# ── The trace reproduces the number ─────────────────────────────────────────

def test_the_terms_in_the_trace_reproduce_the_stored_number(world):
    metrics = pr.collect_telemetry(world.db)
    stored, result = _store(world.db, metrics)
    out = trace.build(world.db, world.people["platform"], stored)

    assert out["prediction_id"] == stored and out["traceable"] is True and out["note"] is None
    assert [s["key"] for s in out["signals"]] == ["breaches", "non_conformances", "bcm_staleness", "orm_recurring",
                                                   "compliance_gap", "appetite_breaches"]
    by = {s["key"]: s for s in out["signals"]}
    expected_weights = {"breaches": 0.45, "non_conformances": 0.25, "bcm_staleness": 0.30, "orm_recurring": 0.20,
                        "compliance_gap": 0.15, "appetite_breaches": 0.35}
    for key, weight in expected_weights.items():
        assert by[key]["weight"] == weight, key
        assert by[key]["term"] == pytest.approx(weight * by[key]["figure"], abs=1e-4), key
    # 30 days and part of a day since the last exercise: (30.x - 180) / 180 is below zero, so that term lowers the score
    assert by["bcm_staleness"]["figure"] == pytest.approx(-0.83, abs=0.01)
    assert by["bcm_staleness"]["direction"] == "lowers" and by["breaches"]["direction"] == "raises"

    total = sum(s["term"] for s in out["signals"])
    assert 100.0 * math.tanh(max(0.0, total)) == pytest.approx(out["delta_p"], abs=0.2)
    assert out["delta_p"] == result["delta_p"]
    assert [s["share_pct"] for s in out["signals"]] == [result["signal_contributions"][k] for k in by]


def test_a_prediction_made_before_records_were_kept_says_so_and_still_shows_its_figures(world):
    metrics = pr.collect_telemetry(world.db)
    del metrics["trace"]
    stored, _ = _store(world.db, metrics)
    out = trace.build(world.db, world.people["platform"], stored)
    assert out["traceable"] is False and "before its source records were kept" in out["note"]
    for s in out["signals"]:
        assert s["records"] == [] and s["count"] is None, s["key"]
    assert next(s for s in out["signals"] if s["key"] == "breaches")["figure"] == metrics["B"]


def test_the_latest_active_prediction_is_the_default_and_an_unknown_one_is_none(world):
    assert trace.build(world.db, world.people["platform"]) is None
    first, _ = _store(world.db, pr.collect_telemetry(world.db))
    second, _ = _store(world.db, pr.collect_telemetry(world.db))
    assert trace.build(world.db, world.people["platform"])["prediction_id"] == second
    assert trace.build(world.db, world.people["platform"], first)["prediction_id"] == first
    assert trace.build(world.db, world.people["platform"], 9999) is None


# ── Who sees which record ───────────────────────────────────────────────────

def _signal(out, key):
    return next(s for s in out["signals"] if s["key"] == key)


def test_a_platform_administrator_may_open_every_record_and_gets_a_link_to_each(world):
    stored, _ = _store(world.db, pr.collect_telemetry(world.db))
    out = trace.build(world.db, world.people["platform"], stored)
    breaches = _signal(out, "breaches")
    assert [(r["title"], r["url"]) for r in breaches["records"]] == [
        ("Breach in A", f"/sentinel/?open=breach:{world.rec['breach_a']}"),
        ("Breach in B", f"/sentinel/?open=breach:{world.rec['breach_b']}")]
    assert breaches["not_shown"] == 0
    assert [r["title"] for r in _signal(out, "non_conformances")["records"]] == [
        "Critical finding A", "Major finding B"]
    assert [r["title"] for r in _signal(out, "bcm_staleness")["records"]] == ["Latest exercise"]
    assert len(_signal(out, "compliance_gap")["records"]) == 3
    assert _signal(out, "appetite_breaches")["categories"] == ["cyber"]


def test_a_unit_reviewer_is_not_shown_a_record_from_another_unit_or_one_their_role_cannot_open(world):
    stored, _ = _store(world.db, pr.collect_telemetry(world.db))
    out = trace.build(world.db, world.people["dpo_a"], stored)

    breaches = _signal(out, "breaches")
    assert [r["title"] for r in breaches["records"]] == ["Breach in A"], "the unit B breach is not theirs to open"
    assert breaches["not_shown"] == 1 and breaches["count"] == 2, "it is counted, never named"

    findings = _signal(out, "non_conformances")
    assert findings["records"] == [] and findings["not_shown"] == 2, "a DPO holds no finding capability"
    assert "Critical finding A" not in json.dumps(out) and "Breach in B" not in json.dumps(out)

    # the same person for whom nothing is hidden sees the record
    admin = trace.build(world.db, world.people["platform"], stored)
    assert "Breach in B" in json.dumps(admin)


def test_an_employee_sees_the_controls_and_exercises_of_their_own_unit_only(world):
    stored, _ = _store(world.db, pr.collect_telemetry(world.db))
    out = trace.build(world.db, world.people["employee_a"], stored)
    assert _signal(out, "breaches")["records"] == [] and _signal(out, "breaches")["not_shown"] == 2
    assert [r["title"] for r in _signal(out, "compliance_gap")["records"]] == [
        "Control in progress", "Control not started", "Control with documents only"]
    assert [r["title"] for r in _signal(out, "bcm_staleness")["records"]] == ["Latest exercise"]


def test_a_record_that_was_deleted_since_is_counted_not_named(world):
    stored, _ = _store(world.db, pr.collect_telemetry(world.db))
    world.db.execute("DELETE FROM sentinel_breaches WHERE id = %s", (world.rec["breach_b"],))
    world.db.commit()
    breaches = _signal(trace.build(world.db, world.people["platform"], stored), "breaches")
    assert [r["title"] for r in breaches["records"]] == ["Breach in A"]
    assert breaches["not_shown"] == 1 and breaches["count"] == 2, "as it was when the number was made"


# ── Disputes ────────────────────────────────────────────────────────────────

def test_a_dispute_sits_beside_the_number_and_changes_nothing(world):
    stored, result = _store(world.db, pr.collect_telemetry(world.db))
    before = dict(world.db.execute("SELECT * FROM ai_risk_predictions WHERE id = %s", (stored,)).fetchone())
    records_before = world.db.execute("SELECT COUNT(*) FROM sentinel_breaches").fetchone()[0]

    made = trace.add_dispute(world.db, world.people["platform"], stored, "breaches",
                             "The breach in unit B was a test and is still open by mistake.")
    world.db.commit()
    assert made["signal"] == "breaches" and made["id"] > 0

    out = trace.build(world.db, world.people["platform"], stored)
    notes = _signal(out, "breaches")["disputes"]
    assert [(n["author"], n["body"]) for n in notes] == [
        ("Platform", "The breach in unit B was a test and is still open by mistake.")]
    assert all(s["disputes"] == [] for s in out["signals"] if s["key"] != "breaches")
    assert out["delta_p"] == result["delta_p"]

    after = dict(world.db.execute("SELECT * FROM ai_risk_predictions WHERE id = %s", (stored,)).fetchone())
    assert after == before, "the prediction row is not touched"
    assert world.db.execute("SELECT COUNT(*) FROM sentinel_breaches").fetchone()[0] == records_before


def test_a_dispute_must_name_a_signal_say_something_and_stay_short(world):
    stored, _ = _store(world.db, pr.collect_telemetry(world.db))
    for signal, body, expect in (
            ("weather", "This is wrong.", "one of the signals"),
            ("breaches", "", "what you dispute"),
            ("breaches", " ab ", "what you dispute"),
            ("breaches", "x" * 1001, "1000 characters")):
        with pytest.raises(ValueError) as refused:
            trace.add_dispute(world.db, world.people["platform"], stored, signal, body)
        assert expect in str(refused.value), (signal, body[:10])
    with pytest.raises(LookupError):
        trace.add_dispute(world.db, world.people["platform"], 9999, "breaches", "No such prediction.")
    assert world.db.execute("SELECT COUNT(*) FROM ai_risk_prediction_notes").fetchone()[0] == 0
    ok = trace.add_dispute(world.db, world.people["platform"], stored, "breaches", "x" * 1000)
    assert ok["id"] > 0, "exactly the limit is allowed"


def test_markup_in_a_dispute_is_not_kept(world):
    stored, _ = _store(world.db, pr.collect_telemetry(world.db))
    trace.add_dispute(world.db, world.people["platform"], stored, "orm_recurring",
                      "<img src=x onerror=alert(1)>The  events\nwere   one incident.")
    world.db.commit()
    body = world.db.execute("SELECT body FROM ai_risk_prediction_notes").fetchone()["body"]
    assert body == "The events were one incident.", "the tag is gone and the spacing is one space"


def test_disputes_go_with_their_prediction(world):
    stored, _ = _store(world.db, pr.collect_telemetry(world.db))
    trace.add_dispute(world.db, world.people["platform"], stored, "breaches", "Wrong window.")
    world.db.commit()
    world.db.execute("DELETE FROM ai_risk_predictions WHERE id = %s", (stored,))
    world.db.commit()
    assert world.db.execute("SELECT COUNT(*) FROM ai_risk_prediction_notes").fetchone()[0] == 0


# ── The routes ──────────────────────────────────────────────────────────────

def _request(user, query=None, payload=None):
    request = types.SimpleNamespace(state=types.SimpleNamespace(user=user), url=types.SimpleNamespace(path="/api/x"),
                                    query_params=query or {}, client=None, headers={})
    if payload is not None:
        async def _json():
            return payload

        request.json = _json
    return request


def _call(coro):
    response = asyncio.run(coro)
    return response.status_code, json.loads(response.body)


def test_the_trace_is_for_a_platform_administrator_like_the_panel_itself(world):
    from modules.launcher import routes_dashboard as dash
    _store(world.db, pr.collect_telemetry(world.db))
    for name in ("org_admin", "dpo_a", "employee_a"):
        status, body = _call(dash.api_predictive_risk_trace(_request(world.people[name])))
        assert status == 403 and body == {"error": "Forbidden"}, name
    status, body = _call(dash.api_predictive_risk_trace(_request(world.people["platform"])))
    assert status == 200 and body["traceable"] is True and len(body["signals"]) == 6
    assert "Breach in A" in json.dumps(body)


def test_the_trace_route_refuses_a_bad_id_and_says_when_there_is_nothing_yet(world):
    from modules.launcher import routes_dashboard as dash
    platform = world.people["platform"]
    status, body = _call(dash.api_predictive_risk_trace(_request(platform)))
    assert status == 404 and "no prediction" in body["error"]
    status, body = _call(dash.api_predictive_risk_trace(_request(platform, {"prediction_id": "latest"})))
    assert status == 400
    stored, _ = _store(world.db, pr.collect_telemetry(world.db))
    status, body = _call(dash.api_predictive_risk_trace(_request(platform, {"prediction_id": str(stored)})))
    assert status == 200 and body["prediction_id"] == stored
    status, _ = _call(dash.api_predictive_risk_trace(_request(platform, {"prediction_id": "9999"})))
    assert status == 404


def test_a_dispute_is_recorded_audited_and_returned_with_the_trace(world):
    from modules.launcher import routes_dashboard as dash
    platform = world.people["platform"]
    stored, _ = _store(world.db, pr.collect_telemetry(world.db))

    status, body = _call(dash.api_predictive_risk_dispute(
        _request(platform, payload={"signal": "compliance_gap", "body": "Control T-4 is implemented elsewhere."}),
        stored))
    assert status == 201 and body["ok"] is True and body["signal"] == "compliance_gap"

    status, out = _call(dash.api_predictive_risk_trace(_request(platform, {"prediction_id": str(stored)})))
    assert [n["body"] for n in _signal(out, "compliance_gap")["disputes"]] == [
        "Control T-4 is implemented elsewhere."]
    audit = world.db.execute(
        "SELECT user_id, action, entity_type, entity_id FROM audit_log WHERE action = 'predictive_risk_dispute'"
    ).fetchall()
    assert [(a["user_id"], a["action"], a["entity_type"], a["entity_id"]) for a in audit] == [
        (world.people["platform"]["id"], "predictive_risk_dispute", "ai_risk_prediction", stored)]


def test_a_dispute_is_refused_for_anyone_but_a_platform_administrator_and_for_bad_input(world):
    from modules.launcher import routes_dashboard as dash
    stored, _ = _store(world.db, pr.collect_telemetry(world.db))
    good = {"signal": "breaches", "body": "This is wrong because of the date."}
    for name in ("org_admin", "dpo_a"):
        status, _ = _call(dash.api_predictive_risk_dispute(_request(world.people[name], payload=good), stored))
        assert status == 403, name
    platform = world.people["platform"]
    status, body = _call(dash.api_predictive_risk_dispute(
        _request(platform, payload={"signal": "weather", "body": "It rained."}), stored))
    assert status == 422 and "signals" in body["error"]
    status, body = _call(dash.api_predictive_risk_dispute(_request(platform, payload={"signal": "breaches"}), stored))
    assert status == 422
    status, body = _call(dash.api_predictive_risk_dispute(_request(platform, payload=good), 9999))
    assert status == 404
    assert world.db.execute("SELECT COUNT(*) FROM ai_risk_prediction_notes").fetchone()[0] == 0
    assert world.db.execute(
        "SELECT COUNT(*) FROM audit_log WHERE action = 'predictive_risk_dispute'").fetchone()[0] == 0
