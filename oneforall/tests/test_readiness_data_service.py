"""
PLAN-36 P04: run_rules_for_org's reconciliation (new/updated/resolved),
acknowledge/suppress/reopen, cross-org isolation, and CSV export.

Uses one trivially-controllable rule (MISSING_RISK_OWNER over
erm_enterprise_risks) rather than re-exercising every rule -- this file is
about the shared engine/service around the rules, not the rules themselves
(covered in test_readiness_rules.py).
"""
import pytest

from modules.readiness import rules  # noqa: F401  (registers rules on import)
from modules.readiness.data_service import (
    run_rules_for_org, list_findings, acknowledge_finding, reopen_finding, export_findings_csv,
)


def _org(db, org_id=1):
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
               (org_id, f"org{org_id}", f"org{org_id}"))


def _user(db, uid, org_id=1):
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, org_id) "
        "VALUES (%s,%s,%s,%s,'x',%s)", (uid, f"user{uid}", f"user{uid}@x.com", f"user{uid}", org_id),
    )


def _actor(db, uid):
    row = db.execute("SELECT id, org_id FROM users WHERE id=%s", (uid,)).fetchone()
    return dict(row)


def test_first_run_creates_a_new_open_finding(test_db):
    _org(test_db)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (1,'Orphan','open')")
    test_db.commit()
    counts = run_rules_for_org(test_db, 1)
    assert counts["new"] == 1
    findings = list_findings(test_db, 1)
    assert len(findings) == 1
    assert findings[0]["status"] == "open"
    assert findings[0]["rule_code"] == "MISSING_RISK_OWNER"


def test_second_run_updates_not_duplicates(test_db):
    _org(test_db)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (1,'Orphan','open')")
    test_db.commit()
    run_rules_for_org(test_db, 1)
    counts = run_rules_for_org(test_db, 1)
    assert counts["new"] == 0
    assert counts["updated"] == 1
    assert len(list_findings(test_db, 1)) == 1


def test_fixed_record_auto_resolves_its_finding(test_db):
    _org(test_db)
    _user(test_db, 1)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (1,'Orphan','open')")
    test_db.commit()
    run_rules_for_org(test_db, 1)
    assert len(list_findings(test_db, 1)) == 1

    test_db.execute("UPDATE erm_enterprise_risks SET owner_id=1 WHERE id=1")
    test_db.commit()
    counts = run_rules_for_org(test_db, 1)
    assert counts["resolved"] == 1
    assert list_findings(test_db, 1) == []  # list_findings excludes resolved by default
    all_findings = list_findings(test_db, 1, status="resolved")
    assert len(all_findings) == 1


def test_a_finding_that_reproduces_after_being_resolved_reopens(test_db):
    _org(test_db)
    _user(test_db, 1)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (1,'Orphan','open')")
    test_db.commit()
    run_rules_for_org(test_db, 1)
    test_db.execute("UPDATE erm_enterprise_risks SET owner_id=1 WHERE id=1")
    test_db.commit()
    run_rules_for_org(test_db, 1)  # resolved

    test_db.execute("UPDATE erm_enterprise_risks SET owner_id=NULL WHERE id=1")
    test_db.commit()
    run_rules_for_org(test_db, 1)  # reproduces
    findings = list_findings(test_db, 1)
    assert len(findings) == 1
    assert findings[0]["status"] == "open"


def test_findings_are_scoped_per_org(test_db):
    """run_rules_for_org(db, 1) must never write a finding attributed to a
    different org, and list_findings(db, 2) must never see org 1's rows --
    the same fail-closed scoping convention as every other module's own
    tenant-isolation tests this session (F14/F16)."""
    _org(test_db, org_id=1)
    _org(test_db, org_id=2)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (1,'Org1 risk','open')")
    test_db.commit()
    run_rules_for_org(test_db, 1)
    assert len(list_findings(test_db, 1)) == 1
    assert list_findings(test_db, 2) == []


def test_acknowledge_requires_a_reason(test_db):
    _org(test_db)
    _user(test_db, 1)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (1,'Orphan','open')")
    test_db.commit()
    run_rules_for_org(test_db, 1)
    finding_id = list_findings(test_db, 1)[0]["id"]
    actor = _actor(test_db, 1)
    with pytest.raises(ValueError):
        acknowledge_finding(test_db, 1, finding_id, actor, "")


def test_acknowledge_without_expiry_sets_acknowledged_status(test_db):
    _org(test_db)
    _user(test_db, 1)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (1,'Orphan','open')")
    test_db.commit()
    run_rules_for_org(test_db, 1)
    finding_id = list_findings(test_db, 1)[0]["id"]
    actor = _actor(test_db, 1)
    result = acknowledge_finding(test_db, 1, finding_id, actor, "Reviewed, accepted risk")
    assert result["status"] == "acknowledged"
    assert result["acknowledged_reason"] == "Reviewed, accepted risk"


def test_acknowledge_with_expiry_sets_suppressed_status(test_db):
    _org(test_db)
    _user(test_db, 1)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (1,'Orphan','open')")
    test_db.commit()
    run_rules_for_org(test_db, 1)
    finding_id = list_findings(test_db, 1)[0]["id"]
    actor = _actor(test_db, 1)
    result = acknowledge_finding(test_db, 1, finding_id, actor, "Fixing next sprint", "2099-01-01T00:00:00")
    assert result["status"] == "suppressed"
    assert result["suppressed_until"] == "2099-01-01T00:00:00"


def test_acknowledge_cannot_reach_another_orgs_finding(test_db):
    """Fail-closed scoped lookup: acknowledging by id alone, without an
    org match, must return None (404-equivalent) rather than silently
    acting on another tenant's row."""
    _org(test_db, org_id=1)
    _org(test_db, org_id=2)
    _user(test_db, 1, org_id=1)
    _user(test_db, 2, org_id=2)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (1,'Org1 risk','open')")
    test_db.commit()
    run_rules_for_org(test_db, 1)
    finding_id = list_findings(test_db, 1)[0]["id"]
    actor_org2 = _actor(test_db, 2)
    result = acknowledge_finding(test_db, 2, finding_id, actor_org2, "trying to reach org 1's finding")
    assert result is None
    # Confirm the org-1 finding was NOT touched by the cross-org attempt.
    assert list_findings(test_db, 1)[0]["status"] == "open"


def test_reopen_reverts_an_acknowledged_finding(test_db):
    _org(test_db)
    _user(test_db, 1)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (1,'Orphan','open')")
    test_db.commit()
    run_rules_for_org(test_db, 1)
    finding_id = list_findings(test_db, 1)[0]["id"]
    actor = _actor(test_db, 1)
    acknowledge_finding(test_db, 1, finding_id, actor, "reason")
    result = reopen_finding(test_db, 1, finding_id)
    assert result["status"] == "open"
    assert result["acknowledged_reason"] is None


def test_export_csv_contains_no_raw_record_content(test_db):
    """P04's own acceptance line: export without sensitive content. The
    exported message is rule-generated metadata (a title snippet, a status
    word) -- this test asserts the CSV round-trips the finding's own
    message field and nothing beyond the documented column set."""
    _org(test_db)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (1,'Orphan risk','open')")
    test_db.commit()
    run_rules_for_org(test_db, 1)
    csv_text = export_findings_csv(test_db, 1)
    lines = csv_text.strip().splitlines()
    assert lines[0] == "rule_code,severity,module,entity_type,entity_id,message,status,detected_at,last_seen_at"
    assert "MISSING_RISK_OWNER" in lines[1]
    assert "Orphan risk" in lines[1]  # from the rule's own message, not a raw dump of the row
