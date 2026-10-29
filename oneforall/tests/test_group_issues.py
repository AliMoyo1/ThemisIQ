"""
The level-2 issue register (plan 21, slice 5) and its leak tests.

A record's free text must not cross however it is typed, a value that does not fit a field's pattern is sent as
nothing, and only the types a relationship approved, to a person holding an issue grant in an allowed role, are read.
Row level security of the new tables is tested on real PostgreSQL in tests/test_postgres_init.py.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from modules.governance import group_issues as gi

CANARY = "ZQXCANARYQXZ"


def _id(db, table, **fields):
    keys = list(fields)
    db.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})",
               [fields[k] for k in keys])
    db.commit()
    return db.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]


def _future(days=30):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(tzinfo=None).isoformat()


def _user(db, org, key, role):
    uid = _id(db, "users", username=key, email=key + "@example.invalid", full_name=key, password_hash="t",
              org_id=org, is_active=1)
    db.execute("INSERT INTO user_roles (user_id,role_key) VALUES (%s,%s)", (uid, role))
    db.commit()
    return {"id": uid, "org_id": org, "business_unit_id": None, "roles": [role], "is_super_admin": False}


def _terms(types):
    return json.dumps({"issue_types": list(types)})


@pytest.fixture
def world(test_db):
    db = test_db
    parent = _id(db, "organizations", name="Issue Parent", slug="iss_parent", status="active")
    child = _id(db, "organizations", name="Issue Child", slug="iss_child", status="active")
    other = _id(db, "organizations", name="Issue Other", slug="iss_other", status="active")
    relation = _id(db, "org_relationships", parent_org_id=parent, child_org_id=child, status="active", purpose="Group",
                   child_ack_by=1, privacy_review_by=2, legal_review_by=3, terms_json=_terms(gi.ISSUE_TYPES),
                   review_due_at=_future(90))
    _id(db, "org_relationships", parent_org_id=parent, child_org_id=other, status="active", purpose="Group",
        child_ack_by=1, privacy_review_by=2, legal_review_by=3, terms_json=_terms(gi.ISSUE_TYPES),
        review_due_at=_future(90))
    users = {"dpo": _user(db, parent, "iss_dpo", "dpo"), "grc": _user(db, parent, "iss_grc", "grc_officer"),
             "audit": _user(db, parent, "iss_audit", "audit_lead"), "emp": _user(db, parent, "iss_emp", "employee"),
             "child_dpo": _user(db, child, "iss_child_dpo", "dpo")}
    return db, parent, child, other, relation, users


def _grant(db, relation, parent, child, user, capability="issue.view", days=30):
    return _id(db, "group_view_grants", relationship_id=relation, source_org_id=child, viewer_org_id=parent,
               user_id=user["id"], capability=capability, expires_at=_future(days), review_due_at=_future(7),
               granted_by=999)


def _seed(db):
    """One record of each kind, with the canary in every free-text column."""
    _id(db, "sentinel_breaches", ref_number="BR-2026-001", title=CANARY + " title", description=CANARY, severity="high",
        status="investigating", affected_count=120, cause=CANARY, impact=CANARY, containment=CANARY, root_cause=CANARY,
        corrective_actions=CANARY, lessons_learned=CANARY, notes=CANARY, remediation=CANARY, authority_ref=CANARY,
        data_types=CANARY, ai_analysis=CANARY, ai_assessment=CANARY, regulation="GDPR", discovery_date="2026-10-01",
        breach_type="Ransomware", notification_required=1, authority_notified=0)
    _id(db, "sentinel_dsr", ref_number="DSR-2026-001", requester_name=CANARY + " Jane", requester_email=CANARY + "@x.com",
        request_type="Erasure Request", regulation="GDPR", description=CANARY, received_date="2026-10-02",
        deadline_date="2026-11-01", status="open", response_notes=CANARY, ai_draft=CANARY)
    _id(db, "sentinel_dpias", ref_number="DPIA-2026-001", title=CANARY, description=CANARY, department=CANARY,
        owner=CANARY, risks=CANARY, mitigations=CANARY, dpo_opinion=CANARY, notes=CANARY, ai_assessment=CANARY,
        status="draft", risk_level="high", regulation="GDPR")
    _id(db, "sentinel_ropa", ref_number="ROPA-2026-001", processing_name=CANARY, department=CANARY, owner=CANARY,
        purpose=CANARY, recipients=CANARY, notes=CANARY, status="active", risk_level="low", regulation="GDPR",
        dpia_required=1)
    for status in ("active", "active", "withdrawn"):
        _id(db, "sentinel_consent", purpose=CANARY, data_subjects=CANARY, notes=CANARY, status=status)


def _stored(db, org):
    rows = db.execute("SELECT * FROM group_issue_rows WHERE source_org_id=%s", (org,)).fetchall()
    runs = db.execute("SELECT * FROM group_issue_runs WHERE source_org_id=%s", (org,)).fetchall()
    return json.dumps([dict(r) for r in rows] + [dict(r) for r in runs], default=str)


# ── what may leave a tenant ─────────────────────────────────────────────────

def test_a_value_that_does_not_fit_its_field_is_sent_as_nothing_never_as_the_text():
    row = gi.sanitize("breach", {
        "id": 7, "ref_number": "Jane Moyo jane@x.com", "breach_type": "Jane's laptop", "severity": "SEVERE",
        "status": "gone wrong", "discovery_date": "2026-13-45", "reported_date": "yesterday", "affected_count": -5,
        "notification_required": "yes", "authority_notified": 2, "authority_notify_date": "<script>",
        "regulation": "Secret regime"})
    assert row["ref"] == "breach-7", "a reference that is not a reference says nothing about the record"
    assert row["fields"] == {"breach_type": "other", "severity": None, "status": None, "discovery_date": None,
                             "reported_date": None, "affected_count": None, "notification_required": None,
                             "authority_notified": None, "authority_notify_date": None, "regulation": None}
    assert "Jane" not in json.dumps(row)


def test_good_values_pass_through_normalised():
    row = gi.sanitize("dsr", {"id": 1, "ref_number": "DSR-2026-001", "request_type": " erasure request ",
                              "regulation": "GDPR", "received_date": "2026-10-02T10:00:00", "deadline_date": "2026-11-01",
                              "status": "OPEN"})
    assert row == {"ref": "DSR-2026-001", "fields": {"request_type": "Erasure Request", "regulation": "GDPR",
                                                     "received_date": "2026-10-02", "deadline_date": "2026-11-01",
                                                     "status": "open"}}


def test_terms_only_approve_known_issue_types():
    assert gi.validate_types(None) == [] and gi.validate_types(["dsr", "breach"]) == ["breach", "dsr"]
    for bad in ("breach", ["breach", "breach"], ["payroll"], [1], ["breach"] * 9):
        with pytest.raises(HTTPException) as refused:
            gi.validate_types(bad)
        assert refused.value.status_code == 422


def test_free_text_in_every_column_of_every_register_never_reaches_the_shared_table(world):
    db, parent, child, *_ = world
    _seed(db)
    written = gi.publish_tenant(child, "iss_child")
    assert written == 1 + 1 + 1 + 1 + 1, "one row per record, and one summary row for consent"
    stored = _stored(db, child)
    assert CANARY not in stored and "Jane" not in stored and "@x.com" not in stored
    breach = json.loads(db.execute("SELECT fields_json FROM group_issue_rows WHERE issue_type='breach'").fetchone()[0])
    assert breach["severity"] == "high" and breach["affected_count"] == 120 and breach["breach_type"] == "ransomware"
    consent = db.execute("SELECT ref_number, fields_json FROM group_issue_rows WHERE issue_type='consent'").fetchone()
    assert consent["ref_number"] == "consent-summary" and json.loads(consent["fields_json"]) == {"active": 2, "withdrawn": 1}


def test_only_the_approved_types_are_published(world):
    db, parent, child, other, relation, users = world
    _seed(db)
    db.execute("UPDATE org_relationships SET terms_json=%s WHERE id=%s", (_terms(["dsr"]), relation))
    db.commit()
    gi.publish_tenant(child, "iss_child")
    kinds = {r[0] for r in db.execute("SELECT DISTINCT issue_type FROM group_issue_rows WHERE source_org_id=%s", (child,))}
    assert kinds == {"dsr"}


def test_an_organization_that_is_nobodys_child_or_has_no_approved_types_publishes_nothing(world):
    db, parent, child, other, relation, users = world
    _seed(db)
    assert gi.publish_tenant(parent, "iss_parent") == 0
    db.execute("UPDATE org_relationships SET terms_json='{}' WHERE id=%s", (relation,))
    db.commit()
    assert gi.publish_tenant(child, "iss_child") == 0
    assert db.execute("SELECT COUNT(*) FROM group_issue_runs").fetchone()[0] == 0


def test_a_subsidiary_not_licensed_for_sentinel_publishes_nothing(world):
    db, parent, child, *_ = world
    _seed(db)
    db.execute("INSERT INTO licenses (org_id, module_keys, seats) VALUES (%s,'aria',10)", (child,))
    db.commit()
    assert gi.publish_tenant(child, "iss_child") == 0


def test_a_long_register_is_cut_and_says_so(world, monkeypatch):
    db, parent, child, *_ = world
    monkeypatch.setattr(gi, "MAX_ROWS", 2)
    for n in range(5):
        _id(db, "sentinel_dsr", ref_number=f"DSR-X-{n}", request_type="Access Request", status="open")
    db.execute("UPDATE org_relationships SET terms_json=%s", (_terms(["dsr"]),))
    db.commit()
    gi.publish_tenant(child, "iss_child")
    run = db.execute("SELECT row_count, truncated FROM group_issue_runs WHERE issue_type='dsr'").fetchone()
    assert (run["row_count"], run["truncated"]) == (2, 1)


def test_old_runs_are_pruned_with_their_rows(world, monkeypatch):
    db, parent, child, *_ = world
    monkeypatch.setattr(gi, "KEEP_RUNS", 2)
    _id(db, "sentinel_dsr", ref_number="DSR-P-1", request_type="Access Request", status="open")
    db.execute("UPDATE org_relationships SET terms_json=%s", (_terms(["dsr"]),))
    db.commit()
    for _ in range(4):
        gi.publish_tenant(child, "iss_child")
    runs = [r["id"] for r in db.execute("SELECT id FROM group_issue_runs ORDER BY id").fetchall()]
    assert len(runs) == 2
    assert {r["run_id"] for r in db.execute("SELECT DISTINCT run_id FROM group_issue_rows").fetchall()} == set(runs)


# ── who may read ────────────────────────────────────────────────────────────

def test_the_register_needs_the_capability_a_grant_and_an_approved_type(world):
    db, parent, child, other, relation, users = world
    _seed(db)
    gi.publish_tenant(child, "iss_child")
    for role in ("emp", "audit"):
        with pytest.raises(HTTPException) as denied:
            gi.view(db, users[role], child, "breach")
        assert denied.value.status_code == 403
    for who in ("dpo", "grc"):
        with pytest.raises(HTTPException) as masked:
            gi.view(db, users[who], child, "breach")
        assert masked.value.status_code == 404, "no grant: the subsidiary looks unknown"
        assert gi.views(db, users[who])["subsidiaries"] == []
    _grant(db, relation, parent, child, users["dpo"])
    seen = gi.view(db, users["dpo"], child, "breach")
    assert seen["state"] == "reporting" and seen["total"] == 1 and seen["rows"][0]["ref"] == "BR-2026-001"
    assert [s["name"] for s in gi.views(db, users["dpo"])["subsidiaries"]] == ["Issue Child"]
    with pytest.raises(HTTPException) as other_grant:
        gi.view(db, users["dpo"], other, "breach")
    assert other_grant.value.status_code == 404, "a grant for one subsidiary opens no other"
    with pytest.raises(HTTPException) as bad_type:
        gi.view(db, users["dpo"], child, "payroll")
    assert bad_type.value.status_code == 404


def test_a_figure_grant_does_not_open_issues_and_an_issue_grant_does_not_open_figures(world):
    from modules.governance import group_figures as gf
    db, parent, child, other, relation, users = world
    _seed(db)
    gi.publish_tenant(child, "iss_child")
    _grant(db, relation, parent, child, users["dpo"], capability="figure.view")
    with pytest.raises(HTTPException):
        gi.view(db, users["dpo"], child, "breach")
    _grant(db, relation, parent, child, users["grc"], capability="issue.view")
    assert gf.views(db, users["grc"])["subsidiaries"] == []


def test_an_unapproved_type_looks_like_an_unknown_one_and_the_terms_are_rechecked_at_read(world):
    db, parent, child, other, relation, users = world
    _seed(db)
    gi.publish_tenant(child, "iss_child")
    _grant(db, relation, parent, child, users["dpo"])
    assert gi.view(db, users["dpo"], child, "dsr")["state"] == "reporting"
    db.execute("UPDATE org_relationships SET terms_json=%s WHERE id=%s", (_terms(["breach"]), relation))
    db.commit()
    with pytest.raises(HTTPException) as narrowed:
        gi.view(db, users["dpo"], child, "dsr")
    assert narrowed.value.status_code == 404, "narrowing the terms stops reading what was already published"


def test_expired_revoked_or_unreviewed_access_reads_nothing(world):
    db, parent, child, other, relation, users = world
    _seed(db)
    gi.publish_tenant(child, "iss_child")
    grant = _grant(db, relation, parent, child, users["dpo"])
    for sql in ("UPDATE group_view_grants SET revoked_at='2020-01-01T00:00:00' WHERE id=%s",
                "UPDATE group_view_grants SET revoked_at=NULL, expires_at='2020-01-01T00:00:00' WHERE id=%s",
                "UPDATE group_view_grants SET expires_at='2099-01-01T00:00:00', review_due_at='2020-01-01T00:00:00' WHERE id=%s"):
        db.execute(sql, (grant,))
        db.commit()
        with pytest.raises(HTTPException) as refused:
            gi.view(db, users["dpo"], child, "breach")
        assert refused.value.status_code == 404
    db.execute("UPDATE group_view_grants SET review_due_at='2099-01-01T00:00:00' WHERE id=%s", (grant,))
    db.execute("UPDATE org_relationships SET status='ended' WHERE id=%s", (relation,))
    db.commit()
    with pytest.raises(HTTPException):
        gi.view(db, users["dpo"], child, "breach")


def test_a_register_not_refreshed_for_two_days_is_not_reporting_and_shows_no_rows(world):
    db, parent, child, other, relation, users = world
    _seed(db)
    gi.publish_tenant(child, "iss_child")
    _grant(db, relation, parent, child, users["dpo"])
    db.execute("UPDATE group_issue_runs SET published_at='2020-01-01T00:00:00'")
    db.commit()
    stale = gi.view(db, users["dpo"], child, "breach")
    assert stale["state"] == "not_reporting" and stale["rows"] == [] and stale["total"] == 0


def test_a_subsidiary_that_never_published_is_not_reporting(world):
    db, parent, child, other, relation, users = world
    _grant(db, relation, parent, child, users["dpo"])
    seen = gi.view(db, users["dpo"], child, "breach")
    assert seen["state"] == "not_reporting" and seen["as_of"] is None


def test_the_reader_gets_the_latest_run_in_pages_and_each_view_is_logged(world, monkeypatch):
    db, parent, child, other, relation, users = world
    monkeypatch.setattr(gi, "PAGE", 3)
    for n in range(7):
        _id(db, "sentinel_dsr", ref_number=f"DSR-L-{n}", request_type="Access Request", status="open")
    db.execute("UPDATE org_relationships SET terms_json=%s", (_terms(["dsr"]),))
    db.commit()
    gi.publish_tenant(child, "iss_child")
    gi.publish_tenant(child, "iss_child")
    _grant(db, relation, parent, child, users["dpo"])
    first = gi.view(db, users["dpo"], child, "dsr", 1)
    last = gi.view(db, users["dpo"], child, "dsr", 3)
    assert first["total"] == 7 and len(first["rows"]) == 3 and len(last["rows"]) == 1
    assert len(gi.view(db, users["dpo"], child, "dsr", 99)["rows"]) == 0
    assert gi.view(db, users["dpo"], child, "dsr", -4)["page"] == 1
    logged = db.execute("SELECT COUNT(*) FROM group_access_events WHERE action='issues_view' AND source_org_id=%s",
                        (child,)).fetchone()[0]
    assert logged == 4
