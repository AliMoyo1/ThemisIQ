"""Needs attention (plan 24, CISO 01): fixed checks over what the viewer may open, reviews that reopen on new facts."""
from datetime import timedelta

import pytest
from fastapi import HTTPException

from modules.erm import acceptance
from modules.governance import attention
from modules.launcher.routes_dashboard import _attention_summary
from core.timeutils import utcnow


def _id(db, table, **fields):
    keys = list(fields)
    db.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})",
               [fields[k] for k in keys])
    db.commit()
    return db.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]


def _person(db, org, name, role, unit):
    uid = _id(db, "users", username=name, email=name + "@example.invalid", full_name=name, password_hash="x",
              org_id=org, business_unit_id=unit, is_active=1)
    db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s,%s)", (uid, role))
    db.commit()
    return {"id": uid, "org_id": org, "business_unit_id": unit, "roles": [role], "is_super_admin": False}


def _day(offset):
    return (utcnow().date() + timedelta(days=offset)).isoformat()


@pytest.fixture
def world(test_db):
    db = test_db
    org = _id(db, "organizations", name="Attention Co", slug="attention_co", status="active")
    unit = _id(db, "business_units", name="Operations", is_active=1)
    other = _id(db, "business_units", name="Retail", is_active=1)
    people = {"cm": _person(db, org, "na_cm", "compliance_manager", unit),
              "far_lead": _person(db, org, "na_far_lead", "audit_lead", other),
              "employee": _person(db, org, "na_employee", "employee", unit),
              "uploader": _person(db, org, "na_uploader", "grc_officer", unit)}
    audit = _id(db, "grid_audits", name="ISO audit", business_unit_id=unit, lead_id=people["cm"]["id"])
    far_audit = _id(db, "grid_audits", name="Retail audit", business_unit_id=other, lead_id=people["far_lead"]["id"])
    _id(db, "grid_audits", name="Lapsed audit", business_unit_id=unit, end_date=_day(-5), status="In Progress")
    c = {name: _id(db, "grid_controls", audit_id=audit, control_id=ref, name=name, status=status)
         for ref, name, status in (("G1", "No proof", "Complete"), ("G2", "Old proof", "Complete"),
                                   ("G3", "Good file", "Complete"), ("G4", "Waiting link", "Complete"),
                                   ("G5", "Accepted link", "Complete"), ("G6", "Not done", "Not Started"))}
    c["Far"] = _id(db, "grid_controls", audit_id=far_audit, control_id="R1", name="Far control", status="Complete")
    _id(db, "grid_evidence_files", control_id=c["Old proof"], filename="a", original_name="a.pdf", file_path="x",
        status="Approved", expires_at=_day(-1))
    _id(db, "grid_evidence_files", control_id=c["Good file"], filename="b", original_name="b.pdf", file_path="y",
        status="Approved", expires_at=_day(30))
    item = _id(db, "evidence_items", title="Review record", status="current", version=1, file_hash="h1", org_id=org,
               business_unit_id=unit, uploaded_by=people["uploader"]["id"])
    _id(db, "evidence_links", evidence_id=item, module="grid", entity_type="control", entity_id=c["Waiting link"])
    _id(db, "evidence_links", evidence_id=item, module="grid", entity_type="control", entity_id=c["Accepted link"],
        review_status="accepted")
    framework = db.execute("SELECT id FROM frameworks ORDER BY id LIMIT 1").fetchone()[0]
    _id(db, "controls", framework_id=framework, ref="NA-1", name="Implemented but unproved", status="Implemented")
    risks = {}
    for name, extra in (("Worse after treatment", dict(residual_likelihood=4, residual_impact=5)),
                        ("Unexplained drop", dict(residual_likelihood=2, residual_impact=2)),
                        ("Explained drop", dict(residual_likelihood=2, residual_impact=2, treatment_plan="New MFA")),
                        ("Unowned review", dict(review_date=_day(-3))),
                        ("Lapsed acceptance", {}), ("Changed after acceptance", {})):
        risks[name] = _id(db, "erm_enterprise_risks", title=name, likelihood=4, impact=4, business_unit_id=unit,
                          owner_id=None if name == "Unowned review" else people["cm"]["id"], status="open", **extra)
    for name, expires in (("Lapsed acceptance", _day(-1)), ("Changed after acceptance", _day(60))):
        risk = dict(db.execute("SELECT * FROM erm_enterprise_risks WHERE id=%s", (risks[name],)).fetchone())
        snapshot, fingerprint = acceptance._snapshot(db, risk)
        _id(db, "erm_risk_acceptances", org_id=org, risk_id=risks[name], proposed_by=people["cm"]["id"],
            reason="Within appetite", alternatives="None", scope_note="All", review_on=_day(-30), expires_on=expires,
            source_snapshot=snapshot, source_hash=fingerprint, status="approved")
    db.execute("UPDATE erm_enterprise_risks SET impact=5 WHERE id=%s", (risks["Changed after acceptance"],))
    _id(db, "bcm_exercises", title="Failover test", scheduled_date=_day(-10), status="planned", business_unit_id=unit)
    _id(db, "bcm_plans", title="Data centre plan", next_review=_day(-2), owner="", status="active",
        business_unit_id=unit)
    db.commit()
    return db, people, c


def _found(data):
    return sorted((i["rule"], i["source_type"], i["title"]) for i in data["issues"])


def test_every_check_fires_on_its_own_case_and_nothing_else(world):
    db, people, c = world
    data = attention.needs_attention(db, people["cm"], state="all")
    assert _found(data) == sorted([
        ("proof_missing", "grid.control", "G1 No proof"),
        ("proof_stale", "grid.control", "G2 Old proof"),
        ("proof_missing", "grid.control", "G4 Waiting link"),
        ("proof_missing", "aria.control", "NA-1 Implemented but unproved"),
        ("owner_or_review_missing", "grid.audit", "Lapsed audit"),
        ("risk_residual_above_current", "erm.risk", "Worse after treatment"),
        ("risk_basis_unexplained", "erm.risk", "Unexplained drop"),
        ("owner_or_review_missing", "erm.risk", "Unowned review"),
        ("risk_acceptance_expired", "erm.risk", "Lapsed acceptance"),
        ("risk_acceptance_basis_changed", "erm.risk", "Changed after acceptance"),
        ("owner_or_review_missing", "bcm.exercise", "Failover test"),
        ("owner_or_review_missing", "bcm.plan", "Data centre plan"),
    ])
    waiting = next(i for i in data["issues"] if i["title"] == "G4 Waiting link")
    assert "1 linked piece(s) wait for a reviewer" in waiting["why"]
    assert data["counts"]["open"] == {"error": 3, "warning": 9}
    assert all(s["state"] == "checked" for s in data["sources"])
    assert all(i["link"].startswith("/") for i in data["issues"])


def test_a_record_the_viewer_cannot_open_is_never_counted_or_named(world):
    db, people, c = world
    assert "R1 Far control" not in [t for _, _, t in _found(attention.needs_attention(db, people["cm"], state="all"))]
    far = attention.needs_attention(db, people["far_lead"], state="all")
    titles = [t for _, _, t in _found(far)]
    assert "R1 Far control" in titles
    assert not {"G1 No proof", "Lapsed audit", "Worse after treatment"} & set(titles), "another unit stays hidden"
    assert "bcm" not in [s["source"] for s in far["sources"]], "a module the viewer lacks is not mentioned at all"
    with pytest.raises(HTTPException) as refused:
        attention.needs_attention(db, people["employee"])
    assert refused.value.status_code == 403


def test_command_centre_count_is_scoped_and_marks_incomplete_reads(world, monkeypatch):
    db, people, _ = world
    summary = _attention_summary(db, people["cm"])
    assert summary["state"] == "measured"
    assert summary["open"] == 12
    assert summary["path"] == "/governance/attention/"
    other = _attention_summary(db, people["far_lead"])
    assert other["open"] != summary["open"]

    original = attention.evaluate

    def partial(db, user):
        issues, sources = original(db, user)
        return issues, [*sources, {"source": "temporarily_unavailable", "state": "unavailable"}]

    monkeypatch.setattr(attention, "evaluate", partial)
    assert _attention_summary(db, people["cm"])["state"] == "partial"


def test_a_reviewed_issue_stays_listed_and_opens_again_when_its_facts_change_or_the_review_expires(world):
    db, people, c = world
    issue = next(i for i in attention.needs_attention(db, people["cm"])["issues"] if i["title"] == "G1 No proof")
    with pytest.raises(HTTPException) as stale:
        attention.review(db, people["cm"], issue["rule"], issue["source_type"], issue["source_id"], "old",
                         "false_positive", "Proof is kept on paper in the safe")
    assert stale.value.status_code == 409
    with pytest.raises(HTTPException) as short:
        attention.review(db, people["cm"], issue["rule"], issue["source_type"], issue["source_id"],
                         issue["fingerprint"], "false_positive", "too short")
    assert short.value.status_code == 422
    attention.review(db, people["cm"], issue["rule"], issue["source_type"], issue["source_id"], issue["fingerprint"],
                     "accepted_exception", "Proof is kept on paper in the safe until the scan", _day(30))
    db.commit()
    assert "G1 No proof" not in [i["title"] for i in attention.needs_attention(db, people["cm"])["issues"]]
    reviewed = attention.needs_attention(db, people["cm"], state="reviewed")
    assert [(i["title"], i["review"]["label"]) for i in reviewed["issues"]] == [("G1 No proof", "Accepted exception")]
    assert reviewed["counts"]["reviewed"] == 1
    _id(db, "grid_evidence_files", control_id=c["No proof"], filename="z", original_name="z.pdf", file_path="z",
        status="Uploaded")
    again = next(i for i in attention.needs_attention(db, people["cm"])["issues"] if i["title"] == "G1 No proof")
    assert again["state"] == "open" and again["reopened"] == "The facts changed after it was reviewed."
    db.execute("UPDATE assurance_issue_reviews SET fingerprint=%s, expires_on=%s", (again["fingerprint"], _day(-1)))
    db.commit()
    lapsed = next(i for i in attention.needs_attention(db, people["cm"])["issues"] if i["title"] == "G1 No proof")
    assert lapsed["reopened"].startswith("The review expired")
    with pytest.raises(HTTPException) as viewer:
        attention.review(db, {**people["far_lead"], "roles": ["risk_owner"]}, issue["rule"], issue["source_type"],
                         issue["source_id"], issue["fingerprint"], "false_positive", "Not my unit but trying")
    assert viewer.value.status_code == 403


def test_a_source_that_cannot_be_read_is_said_to_be_unchecked_never_clean(world, monkeypatch):
    db, people, c = world

    def broken(db, user):
        raise RuntimeError("the BCM tables are being rebuilt")

    monkeypatch.setattr(attention, "SOURCES", tuple(
        (name, kinds, broken if name == "bcm" else check) for name, kinds, check in attention.SOURCES))
    data = attention.needs_attention(db, people["cm"], state="all")
    assert {"source": "bcm", "state": "unavailable"} in data["sources"]
    assert "Failover test" not in [i["title"] for i in data["issues"]]
    assert "G1 No proof" in [i["title"] for i in data["issues"]], "the other checks still run"


def test_issues_page_and_one_record_can_be_asked_about(world, monkeypatch):
    db, people, c = world
    monkeypatch.setattr(attention, "PAGE", 5)
    first = attention.needs_attention(db, people["cm"], state="all")
    assert first["pages"] == 3 and len(first["issues"]) == 5
    assert [i["severity"] for i in first["issues"]] == ["error"] * 3 + ["warning"] * 2, "errors first"
    last = attention.needs_attention(db, people["cm"], state="all", page=9)
    assert last["page"] == 3 and len(last["issues"]) == 2
    one = attention.needs_attention(db, people["cm"], state="all", source_type="grid.control",
                                    source_id=c["Old proof"])
    assert [i["rule"] for i in one["issues"]] == ["proof_stale"]
