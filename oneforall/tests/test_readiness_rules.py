"""
PLAN-36 P04: one positive + one negative case per concrete rule in
modules/readiness/rules.py. Each rule is read-only; these tests assert
that too (the row a rule flags is byte-identical before and after the
rule runs).
"""
import io

import pytest
from docx import Document as DocxDocument

from core.timeutils import utcnow
from modules.readiness import rules  # noqa: F401  (registers rules on import)
from modules.readiness.data_service import _RULES
from modules.aria import policy_workflow_service as svc
from modules.aria import policy_storage as storage
from modules.aria import policy_preview as preview


def _org(db, org_id=1):
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
               (org_id, f"org{org_id}", f"org{org_id}"))


def _user(db, uid, org_id=1, is_active=1, username=None):
    username = username or f"user{uid}"
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, org_id, is_active) "
        "VALUES (%s,%s,%s,%s,'x',%s,%s)",
        (uid, username, f"{username}@x.com", username, org_id, is_active),
    )


def _run(rule_code, db, org_id):
    return _RULES[rule_code](db, org_id)


# ─────────────────────────────────────────────────────────────────────────
# 1. MISSING_RISK_OWNER
# ─────────────────────────────────────────────────────────────────────────

def test_missing_risk_owner_flags_ownerless_open_risk(test_db):
    _org(test_db)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (1,'Orphan risk','open')")
    test_db.commit()
    findings = _run("MISSING_RISK_OWNER", test_db, 1)
    assert len(findings) == 1
    assert findings[0].entity_id == "1"


def test_missing_risk_owner_ignores_owned_or_closed_risks(test_db):
    _org(test_db)
    _user(test_db, 1)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status, owner_id) VALUES (1,'Owned','open',1)")
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (2,'Closed orphan','closed')")
    test_db.commit()
    assert _run("MISSING_RISK_OWNER", test_db, 1) == []


# ─────────────────────────────────────────────────────────────────────────
# 2. INACTIVE_CONTROL_ASSIGNEE
# ─────────────────────────────────────────────────────────────────────────

def test_inactive_control_assignee_flags_deactivated_user(test_db):
    _org(test_db)
    _user(test_db, 1, is_active=0)
    test_db.execute("INSERT INTO grid_audits (id, name) VALUES (1,'Audit')")
    test_db.execute(
        "INSERT INTO grid_controls (id, audit_id, name, status, assignee_id) "
        "VALUES (1,1,'Control A','In Progress',1)"
    )
    test_db.commit()
    findings = _run("INACTIVE_CONTROL_ASSIGNEE", test_db, 1)
    assert len(findings) == 1
    assert findings[0].entity_id == "1"


def test_inactive_control_assignee_ignores_active_or_closed(test_db):
    _org(test_db)
    _user(test_db, 1, is_active=1)
    _user(test_db, 2, is_active=0)
    test_db.execute("INSERT INTO grid_audits (id, name) VALUES (1,'Audit')")
    test_db.execute("INSERT INTO grid_controls (id, audit_id, name, status, assignee_id) VALUES (1,1,'Active-assignee','Open',1)")
    test_db.execute("INSERT INTO grid_controls (id, audit_id, name, status, assignee_id) VALUES (2,1,'Closed','Complete',2)")
    test_db.commit()
    assert _run("INACTIVE_CONTROL_ASSIGNEE", test_db, 1) == []


# ─────────────────────────────────────────────────────────────────────────
# 3. BROKEN_FRAMEWORK_REFERENCE
# ─────────────────────────────────────────────────────────────────────────

def test_broken_framework_reference_flags_nonexistent_framework(test_db):
    _org(test_db)
    test_db.execute("INSERT INTO grid_audits (id, name) VALUES (1,'Audit')")
    test_db.execute("INSERT INTO grid_controls (id, audit_id, name, framework_id) VALUES (1,1,'Ctrl',99999)")
    test_db.commit()
    findings = _run("BROKEN_FRAMEWORK_REFERENCE", test_db, 1)
    assert len(findings) == 1
    assert "99999" in findings[0].message


def test_broken_framework_reference_ignores_valid_or_null(test_db):
    """frameworks is pre-seeded by init_db() itself -- reference an existing
    row's real id rather than guessing one, since a fixed literal id could
    collide with (or miss) whatever the seed data actually contains."""
    _org(test_db)
    real_framework_id = test_db.execute("SELECT id FROM frameworks LIMIT 1").fetchone()["id"]
    test_db.execute("INSERT INTO grid_audits (id, name) VALUES (1,'Audit')")
    test_db.execute(
        "INSERT INTO grid_controls (id, audit_id, name, framework_id) VALUES (1,1,'Valid',%s)",
        (real_framework_id,),
    )
    test_db.execute("INSERT INTO grid_controls (id, audit_id, name, framework_id) VALUES (2,1,'NoFw',NULL)")
    test_db.commit()
    assert _run("BROKEN_FRAMEWORK_REFERENCE", test_db, 1) == []


# ─────────────────────────────────────────────────────────────────────────
# ARIA-backed rules (4, 5, 6, 8): built through the real service pipeline
# rather than hand-rolled INSERTs, so the "should never happen" fixtures
# genuinely require breaking an invariant on purpose, not just guessing at
# column values.
# ─────────────────────────────────────────────────────────────────────────

def _real_template_bytes() -> bytes:
    doc = DocxDocument()
    doc.add_paragraph("TEMPLATE COVER")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    root = tmp_path / "aria_uploads"
    monkeypatch.setattr(storage, "ARIA_UPLOAD_DIR", root)
    monkeypatch.setattr(storage, "WORKFLOW_ROOT", root / "policy_workflow")


@pytest.fixture(autouse=True)
def mock_conversion(monkeypatch):
    monkeypatch.setattr(preview, "submit_conversion_job", lambda b, timeout_seconds=None: "job")
    monkeypatch.setattr(preview, "poll_conversion_result", lambda j, timeout_seconds=None, poll_interval=0.5: b"%PDF-X")
    monkeypatch.setattr(preview, "cleanup_job", lambda j: None)


@pytest.fixture
def confirmed_version(test_db, tmp_path, monkeypatch):
    """A real, org-scoped, confirmed ARIA policy version (state='draft',
    pre-submission) plus its owning actor -- the common setup for rules 4-6/8."""
    _org(test_db)
    _user(test_db, 1)
    test_db.commit()
    actor = {"id": 1, "username": "user1", "full_name": "user1", "org_id": 1,
             "business_unit_id": None, "is_super_admin": 0, "roles": ["policy_author"]}

    template_dir = tmp_path / "aria_templates"
    template_dir.mkdir()
    (template_dir / "t1.docx").write_bytes(_real_template_bytes())
    monkeypatch.setattr("modules.aria.routes.ARIA_TEMPLATE_DIR", template_dir)
    test_db.execute(
        "INSERT INTO aria_doc_templates (name, file_path, file_name, org_id, is_active) "
        "VALUES ('T1', 't1.docx', 't1.docx', 1, 1)"
    )
    test_db.commit()
    template_id = test_db.execute("SELECT id FROM aria_doc_templates WHERE file_path='t1.docx'").fetchone()["id"]

    draft = svc.create_draft_from_generation(
        test_db, actor, control={"id": 1, "ref": "A.1", "name": "Test", "framework_id": 1, "fw_name": "ISO 27001"},
        generated_content="# Policy\n\nBody.", org_name="Econet", doc_type="Policy",
        framework_label="ISO 27001", integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    built = svc.build_draft(test_db, actor, draft["id"], template_id, draft["lock_version"])
    confirmed = svc.confirm_draft(test_db, actor, built["id"], built["build_id"], built["lock_version"])
    return {"actor": actor, "confirmed": confirmed}


def test_aria_draft_missing_build_flags_tampered_row(test_db, confirmed_version):
    """Red proof by construction: build_draft/confirm_draft never leave this
    combination behind through their own normal calls, so this test directly
    writes the violating state -- the rule exists for exactly this gap."""
    draft_id = test_db.execute(
        "SELECT id FROM aria_policy_drafts WHERE org_id=1"
    ).fetchone()["id"]
    test_db.execute("UPDATE aria_policy_drafts SET state='committed', build_id=NULL WHERE id=%s", (draft_id,))
    test_db.commit()
    findings = _run("ARIA_DRAFT_MISSING_BUILD", test_db, 1)
    assert len(findings) == 1
    assert findings[0].entity_id == draft_id


def test_aria_draft_missing_build_ignores_a_real_ready_draft(test_db):
    """A draft mid-editing (state='editing', no build yet) is normal, not a
    finding -- the rule only fires for 'ready'/'committed'."""
    _org(test_db)
    _user(test_db, 1)
    test_db.commit()
    actor = {"id": 1, "username": "user1", "full_name": "user1", "org_id": 1,
             "business_unit_id": None, "is_super_admin": 0, "roles": ["policy_author"]}
    svc.create_draft_from_generation(
        test_db, actor, control={"id": 1, "ref": "A.1", "name": "Test", "framework_id": 1, "fw_name": "ISO 27001"},
        generated_content="# Policy\n\nBody.", org_name="Econet", doc_type="Policy",
        framework_label="ISO 27001", integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    assert _run("ARIA_DRAFT_MISSING_BUILD", test_db, 1) == []


def test_aria_version_state_mismatch_flags_tampered_row(test_db, confirmed_version):
    version_id = confirmed_version["confirmed"]["version_id"]
    test_db.execute("UPDATE aria_policy_versions SET state='approved', approved_at=NULL WHERE id=%s", (version_id,))
    test_db.commit()
    findings = _run("ARIA_VERSION_STATE_MISMATCH", test_db, 1)
    assert len(findings) == 1
    assert findings[0].entity_id == str(version_id)


def test_aria_version_state_mismatch_ignores_a_real_draft_version(test_db, confirmed_version):
    assert _run("ARIA_VERSION_STATE_MISMATCH", test_db, 1) == []


def test_stale_publication_lease_flags_expired_lease(test_db, confirmed_version):
    version_id = confirmed_version["confirmed"]["version_id"]
    document_id = confirmed_version["confirmed"]["document_id"]
    past = (utcnow().replace(year=2000)).isoformat()
    test_db.execute(
        "INSERT INTO aria_policy_publication_jobs "
        "(org_id, policy_version_id, document_id, publication_key, state, lease_until, attempts) "
        "VALUES (1,%s,%s,'k1','running',%s,2)",
        (version_id, document_id, past),
    )
    test_db.commit()
    findings = _run("STALE_PUBLICATION_LEASE", test_db, 1)
    assert len(findings) == 1


def test_stale_publication_lease_ignores_a_fresh_lease(test_db, confirmed_version):
    version_id = confirmed_version["confirmed"]["version_id"]
    document_id = confirmed_version["confirmed"]["document_id"]
    future = (utcnow().replace(year=2099)).isoformat()
    test_db.execute(
        "INSERT INTO aria_policy_publication_jobs "
        "(org_id, policy_version_id, document_id, publication_key, state, lease_until, attempts) "
        "VALUES (1,%s,%s,'k1','running',%s,0)",
        (version_id, document_id, future),
    )
    test_db.commit()
    assert _run("STALE_PUBLICATION_LEASE", test_db, 1) == []


def test_aria_authoring_no_template_flags_org_with_zero_active_templates(test_db, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", True)
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ORG_IDS", [1])
    _org(test_db)
    test_db.commit()
    findings = _run("ARIA_AUTHORING_NO_TEMPLATE", test_db, 1)
    assert len(findings) == 1
    assert findings[0].entity_id == "1"


def test_aria_authoring_no_template_ignores_org_with_a_template_or_flag_off(test_db, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", True)
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ORG_IDS", [1, 2])
    _org(test_db, org_id=1)
    _org(test_db, org_id=2)
    test_db.execute(
        "INSERT INTO aria_doc_templates (name, file_path, file_name, org_id, is_active) "
        "VALUES ('T1','t1.docx','t1.docx',1,1)"
    )
    test_db.commit()
    assert _run("ARIA_AUTHORING_NO_TEMPLATE", test_db, 1) == []       # org 1 has a template
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ORG_IDS", [2])
    assert _run("ARIA_AUTHORING_NO_TEMPLATE", test_db, 2)              # org 2: enabled, no template -> flagged
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", False)
    assert _run("ARIA_AUTHORING_NO_TEMPLATE", test_db, 2) == []        # flag off entirely -> not our problem to flag


# ─────────────────────────────────────────────────────────────────────────
# 7. EVIDENCE_EXPIRED_UNFLAGGED
# ─────────────────────────────────────────────────────────────────────────

def test_evidence_expired_unflagged_flags_past_expiry_still_current(test_db):
    _org(test_db)
    test_db.execute(
        "INSERT INTO evidence_items (id, title, org_id, status, expiry_date) "
        "VALUES (1,'Old cert',1,'current','2000-01-01')"
    )
    test_db.commit()
    findings = _run("EVIDENCE_EXPIRED_UNFLAGGED", test_db, 1)
    assert len(findings) == 1


def test_evidence_expired_unflagged_ignores_future_or_already_flagged(test_db):
    _org(test_db)
    test_db.execute(
        "INSERT INTO evidence_items (id, title, org_id, status, expiry_date) "
        "VALUES (1,'Future',1,'current','2099-01-01')"
    )
    test_db.execute(
        "INSERT INTO evidence_items (id, title, org_id, status, expiry_date) "
        "VALUES (2,'AlreadyExpiredStatus',1,'expired','2000-01-01')"
    )
    test_db.commit()
    assert _run("EVIDENCE_EXPIRED_UNFLAGGED", test_db, 1) == []


# ─────────────────────────────────────────────────────────────────────────
# Rules never mutate the record they inspect (P04's own "read-only by
# default" design principle).
# ─────────────────────────────────────────────────────────────────────────

def test_rules_are_read_only(test_db):
    _org(test_db)
    test_db.execute("INSERT INTO erm_enterprise_risks (id, title, status) VALUES (1,'Orphan','open')")
    test_db.commit()
    before = dict(test_db.execute("SELECT * FROM erm_enterprise_risks WHERE id=1").fetchone())
    _run("MISSING_RISK_OWNER", test_db, 1)
    after = dict(test_db.execute("SELECT * FROM erm_enterprise_risks WHERE id=1").fetchone())
    assert before == after
