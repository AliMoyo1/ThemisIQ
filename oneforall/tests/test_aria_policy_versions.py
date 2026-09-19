"""
PLAN-35 T06: confirmation and immutable version tests.

Covers: new-policy confirm creates document+version 1.0, retry returns the
same IDs (no duplicate), revision confirm preserves the current Approved
projection, hash/tamper detection, missing-artifact refusal, stale-base
refusal, and that version reads never leak a filesystem path.
"""
import io

import pytest
from docx import Document as DocxDocument

from modules.aria import policy_workflow_service as svc
from modules.aria import policy_storage as storage
from modules.aria import policy_preview as preview


def _org(db, org_id=1):
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
               (org_id, f"org{org_id}", f"org{org_id}"))


def _user(db, uid=1, org_id=1):
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, org_id) "
        "VALUES (%s,%s,%s,%s,'x',%s)", (uid, f"user{uid}", f"user{uid}@x.com", f"user{uid}", org_id),
    )


def _actor(db, uid=1):
    row = db.execute(
        "SELECT id, username, full_name, org_id, business_unit_id, "
        "COALESCE(is_super_admin,0) AS is_super_admin "
        "FROM users WHERE id=%s", (uid,),
    ).fetchone()
    d = dict(row)
    d["roles"] = ["policy_author"]
    return d


def _real_template_bytes() -> bytes:
    doc = DocxDocument()
    doc.add_paragraph("TEMPLATE COVER PAGE")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
def actor(test_db):
    _org(test_db)
    _user(test_db)
    test_db.commit()
    return _actor(test_db)


@pytest.fixture
def template(test_db, tmp_path, monkeypatch, actor):
    template_dir = tmp_path / "aria_templates"
    template_dir.mkdir()
    (template_dir / "t1.docx").write_bytes(_real_template_bytes())
    monkeypatch.setattr("modules.aria.routes.ARIA_TEMPLATE_DIR", template_dir)
    test_db.execute(
        "INSERT INTO aria_doc_templates (name, file_path, file_name, org_id, is_active) "
        "VALUES ('T1', 't1.docx', 't1.docx', %s, 1)", (actor["org_id"],),
    )
    test_db.commit()
    return test_db.execute("SELECT id FROM aria_doc_templates WHERE file_path='t1.docx'").fetchone()["id"]


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    root = tmp_path / "aria_uploads"
    monkeypatch.setattr(storage, "ARIA_UPLOAD_DIR", root)
    monkeypatch.setattr(storage, "WORKFLOW_ROOT", root / "policy_workflow")
    yield


@pytest.fixture(autouse=True)
def mock_conversion(monkeypatch):
    def fake_submit(branded_bytes, timeout_seconds=None):
        return "fake-job-id"

    def fake_poll(job_id, timeout_seconds=None, poll_interval=0.5):
        return b"%PDF-FAKE-PREVIEW"

    monkeypatch.setattr(preview, "submit_conversion_job", fake_submit)
    monkeypatch.setattr(preview, "poll_conversion_result", fake_poll)
    monkeypatch.setattr(preview, "cleanup_job", lambda job_id: None)


@pytest.fixture
def built_draft(test_db, actor, template):
    """A fresh draft, already built (state='ready'), ready to confirm."""
    draft = svc.create_draft_from_generation(
        test_db, actor, control={"id": 1, "ref": "A.1", "name": "Test Control",
                                  "framework_id": 1, "fw_name": "ISO 27001"},
        generated_content="# Test Policy\n\nSome body content.",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    return svc.build_draft(test_db, actor, draft["id"], template, draft["lock_version"])


# ─────────────────────────────────────────────────────────────────────────
# New policy: confirm creates document + version 1.0
# ─────────────────────────────────────────────────────────────────────────

def test_confirm_new_policy_creates_document_and_version_1_0(test_db, actor, built_draft):
    result = svc.confirm_draft(test_db, actor, built_draft["id"], built_draft["build_id"], built_draft["lock_version"])
    assert result["version"] == "1.0"

    doc = dict(test_db.execute(
        "SELECT doc_id, version, status, body, current_policy_version_id, "
        "policy_workflow_managed, owner_user_id FROM aria_documents WHERE id=%s",
        (result["document_id"],),
    ).fetchone())
    assert doc["doc_id"] == result["doc_id"]
    assert doc["version"] == "1.0"
    assert doc["status"] == "Draft"
    assert doc["current_policy_version_id"] == result["version_id"]
    assert doc["policy_workflow_managed"] == 1
    assert doc["owner_user_id"] == actor["id"]

    version = dict(test_db.execute(
        "SELECT state, origin, version FROM aria_policy_versions WHERE id=%s", (result["version_id"],)
    ).fetchone())
    assert version == {"state": "draft", "origin": "authored", "version": "1.0"}


def test_confirm_retry_returns_the_same_ids_no_duplicate(test_db, actor, built_draft):
    first = svc.confirm_draft(test_db, actor, built_draft["id"], built_draft["build_id"], built_draft["lock_version"])
    # Retry: even with a now-stale lock_version, the retry path must not
    # demand it (section 9.1 item 8) -- pass the ORIGINAL pre-confirm token.
    second = svc.confirm_draft(test_db, actor, built_draft["id"], built_draft["build_id"], built_draft["lock_version"])

    assert first == second
    count = test_db.execute(
        "SELECT COUNT(*) FROM aria_policy_versions WHERE document_id=%s", (first["document_id"],)
    ).fetchone()[0]
    assert count == 1


def test_confirmed_hashes_match_the_previewed_build(test_db, actor, built_draft):
    result = svc.confirm_draft(test_db, actor, built_draft["id"], built_draft["build_id"], built_draft["lock_version"])
    version = dict(test_db.execute(
        "SELECT source_sha256, branded_sha256, preview_sha256 FROM aria_policy_versions WHERE id=%s",
        (result["version_id"],),
    ).fetchone())
    assert version["source_sha256"] == built_draft["source_sha256"]
    assert version["branded_sha256"] == built_draft["branded_sha256"]
    assert version["preview_sha256"] == built_draft["preview_sha256"]


# ─────────────────────────────────────────────────────────────────────────
# Revision confirm preserves the current Approved projection
# ─────────────────────────────────────────────────────────────────────────

def _make_approved_document(db, actor, doc_id="DOC-0099"):
    db.execute(
        "INSERT INTO aria_documents (doc_id, framework, control_ref, title, version, "
        "status, body, org_id, owner_user_id, policy_workflow_managed) "
        "VALUES (%s, 'ISO 27001', 'A.1', 'Original Title', '1.0', 'Approved', "
        "'Original approved body', %s, %s, 1)",
        (doc_id, actor["org_id"], actor["id"]),
    )
    doc_pk = db.execute("SELECT id FROM aria_documents WHERE doc_id=%s", (doc_id,)).fetchone()["id"]
    db.execute(
        "INSERT INTO aria_policy_versions (org_id, document_id, version_major, version_minor, "
        "version, state, origin, body, created_by) "
        "VALUES (%s,%s,1,0,'1.0','approved','legacy','Original approved body',%s)",
        (actor["org_id"], doc_pk, actor["id"]),
    )
    version_id = db.execute("SELECT id FROM aria_policy_versions WHERE document_id=%s", (doc_pk,)).fetchone()["id"]
    db.execute("UPDATE aria_documents SET current_policy_version_id=%s WHERE id=%s", (version_id, doc_pk))
    db.commit()
    return doc_pk, version_id


def test_revision_confirm_preserves_the_approved_projection(test_db, actor, template):
    doc_pk, approved_version_id = _make_approved_document(test_db, actor)

    revision_draft = svc.start_revision_draft(test_db, actor, "DOC-0099")
    revision_draft = svc.save_draft_body(test_db, actor, revision_draft["id"], body="# Revised content",
                                          expected_lock_version=revision_draft["lock_version"])
    built = svc.build_draft(test_db, actor, revision_draft["id"], template, revision_draft["lock_version"])

    result = svc.confirm_draft(test_db, actor, built["id"], built["build_id"], built["lock_version"])
    assert result["version"] == "1.1"
    assert result["document_id"] == doc_pk

    doc = dict(test_db.execute(
        "SELECT version, status, body, current_policy_version_id FROM aria_documents WHERE id=%s", (doc_pk,)
    ).fetchone())
    assert doc["version"] == "1.0", "the document projection must stay on the approved version"
    assert doc["status"] == "Approved"
    assert doc["body"] == "Original approved body"
    assert doc["current_policy_version_id"] == approved_version_id, \
        "current pointer must not move to the unapproved candidate"

    candidate = dict(test_db.execute(
        "SELECT state, version, body FROM aria_policy_versions WHERE id=%s", (result["version_id"],)
    ).fetchone())
    assert candidate == {"state": "draft", "version": "1.1", "body": "# Revised content"}


def test_stale_base_refused_when_document_advanced_since_draft_started(test_db, actor, template):
    doc_pk, approved_version_id = _make_approved_document(test_db, actor)
    revision_draft = svc.start_revision_draft(test_db, actor, "DOC-0099")
    built = svc.build_draft(test_db, actor, revision_draft["id"], template, revision_draft["lock_version"])

    # Simulate someone else's revision having already been approved and
    # promoted to current while this draft was in progress.
    test_db.execute(
        "INSERT INTO aria_policy_versions (org_id, document_id, version_major, version_minor, "
        "version, state, origin, body, created_by) "
        "VALUES (%s,%s,1,2,'1.2','approved','authored','someone else won the race',%s)",
        (actor["org_id"], doc_pk, actor["id"]),
    )
    other_version_id = test_db.execute(
        "SELECT id FROM aria_policy_versions WHERE version='1.2' AND document_id=%s", (doc_pk,)
    ).fetchone()["id"]
    test_db.execute("UPDATE aria_documents SET current_policy_version_id=%s WHERE id=%s",
                     (other_version_id, doc_pk))
    test_db.commit()

    with pytest.raises(svc.StaleBaseError):
        svc.confirm_draft(test_db, actor, built["id"], built["build_id"], built["lock_version"])


# ─────────────────────────────────────────────────────────────────────────
# Guard conditions
# ─────────────────────────────────────────────────────────────────────────

def test_confirm_without_a_build_is_refused(test_db, actor):
    draft = svc.create_draft_from_generation(
        test_db, actor, control={"id": 1, "ref": "A.1", "name": "Test", "framework_id": 1, "fw_name": "ISO 27001"},
        generated_content="# Policy", org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    with pytest.raises(svc.BuildRequiredError):
        svc.confirm_draft(test_db, actor, draft["id"], "any-build-id", draft["lock_version"])


def test_confirm_with_mismatched_build_id_refused(test_db, actor, built_draft):
    with pytest.raises(svc.PolicyWorkflowError) as exc_info:
        svc.confirm_draft(test_db, actor, built_draft["id"], "wrong-build-id", built_draft["lock_version"])
    assert exc_info.value.code == "STALE_DRAFT"


def test_confirm_with_stale_lock_version_refused(test_db, actor, built_draft):
    with pytest.raises(svc.StaleDraftError):
        svc.confirm_draft(test_db, actor, built_draft["id"], built_draft["build_id"], built_draft["lock_version"] + 5)


def test_confirm_refuses_a_tampered_source_file(test_db, actor, built_draft):
    path = storage.resolve_stored_path(built_draft["source_path"])
    path.write_bytes(b"TAMPERED CONTENT")
    with pytest.raises(svc.PolicyWorkflowError) as exc_info:
        svc.confirm_draft(test_db, actor, built_draft["id"], built_draft["build_id"], built_draft["lock_version"])
    assert exc_info.value.code == "INVALID_INPUT"
    # Must not have created anything.
    count = test_db.execute("SELECT COUNT(*) FROM aria_documents").fetchone()[0]
    assert count == 0


def test_confirm_refuses_a_missing_branded_file(test_db, actor, built_draft):
    path = storage.resolve_stored_path(built_draft["branded_path"])
    path.unlink()
    with pytest.raises(svc.PolicyWorkflowError) as exc_info:
        svc.confirm_draft(test_db, actor, built_draft["id"], built_draft["build_id"], built_draft["lock_version"])
    assert exc_info.value.code == "INVALID_INPUT"


# ─────────────────────────────────────────────────────────────────────────
# No filesystem paths leak through the read API
# ─────────────────────────────────────────────────────────────────────────

def test_version_public_dict_has_no_filesystem_paths(test_db, actor, built_draft):
    result = svc.confirm_draft(test_db, actor, built_draft["id"], built_draft["build_id"], built_draft["lock_version"])
    version = svc.get_version(test_db, actor, result["version_id"])
    public = svc._version_to_public_dict(version)
    for forbidden in ("source_path", "branded_path", "preview_path", "template_snapshot_path", "body"):
        assert forbidden not in public, f"{forbidden} must not appear in the public version dict"


def test_list_document_versions_has_no_filesystem_paths(test_db, actor, built_draft):
    result = svc.confirm_draft(test_db, actor, built_draft["id"], built_draft["build_id"], built_draft["lock_version"])
    versions = svc.list_document_versions(test_db, actor, result["doc_id"])
    assert len(versions) == 1
    for forbidden in ("source_path", "branded_path", "preview_path", "body"):
        assert forbidden not in versions[0]
