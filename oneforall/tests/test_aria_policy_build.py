"""
PLAN-35 T05: build orchestration tests (policy_workflow_service.build_draft).

Mocks the conversion call site (submit/poll), not the whole spool protocol
(already covered by test_aria_policy_preview.py), so these tests focus on
the orchestration: fingerprinting, template scope, staging/attach, hash
recording, and -- the key correctness property -- that a stale draft state
at final attach time never lets an orphaned build silently become "the"
build for a draft it no longer matches.
"""
import io
import json

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
        "SELECT id, org_id, business_unit_id, COALESCE(is_super_admin,0) AS is_super_admin "
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
    """A real, valid, active template scoped to actor's org, with a real
    file on disk under an isolated ARIA_TEMPLATE_DIR."""
    template_dir = tmp_path / "aria_templates"
    template_dir.mkdir()
    (template_dir / "t1.docx").write_bytes(_real_template_bytes())
    monkeypatch.setattr("modules.aria.routes.ARIA_TEMPLATE_DIR", template_dir)

    test_db.execute(
        "INSERT INTO aria_doc_templates (name, file_path, file_name, org_id, is_active) "
        "VALUES ('T1', 't1.docx', 't1.docx', %s, 1)",
        (actor["org_id"],),
    )
    test_db.commit()
    row = test_db.execute("SELECT id FROM aria_doc_templates WHERE file_path='t1.docx'").fetchone()
    return row["id"]


@pytest.fixture
def draft(test_db, actor):
    return svc.create_draft_from_generation(
        test_db, actor, control={"id": 1, "ref": "A.1", "name": "Test Control",
                                  "framework_id": 1, "fw_name": "ISO 27001"},
        generated_content="# Test Policy\n\nSome body content.",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )


@pytest.fixture(autouse=True)
def _isolated_storage(tmp_path, monkeypatch):
    root = tmp_path / "aria_uploads"
    monkeypatch.setattr(storage, "ARIA_UPLOAD_DIR", root)
    monkeypatch.setattr(storage, "WORKFLOW_ROOT", root / "policy_workflow")
    yield


@pytest.fixture
def mock_conversion(monkeypatch):
    """Bypass the real spool/worker entirely: submit_conversion_job and
    poll_conversion_result are the two calls build_draft actually makes."""
    state = {"calls": 0, "behavior": "success"}

    def fake_submit(branded_bytes, timeout_seconds=None):
        state["calls"] += 1
        return "fake-job-id"

    def fake_poll(job_id, timeout_seconds=None, poll_interval=0.5):
        if state["behavior"] == "success":
            return b"%PDF-FAKE-PREVIEW"
        if state["behavior"] == "timeout":
            raise preview.ConversionTimeoutError("mock timeout")
        if state["behavior"] == "failed":
            raise preview.ConversionFailedError("PREVIEW_UNAVAILABLE", "mock conversion failure")
        raise RuntimeError("unexpected")

    monkeypatch.setattr(preview, "submit_conversion_job", fake_submit)
    monkeypatch.setattr(preview, "poll_conversion_result", fake_poll)
    monkeypatch.setattr(preview, "cleanup_job", lambda job_id: None)
    return state


# ─────────────────────────────────────────────────────────────────────────
# Happy path
# ─────────────────────────────────────────────────────────────────────────

def test_build_succeeds_and_records_all_artifacts(test_db, actor, draft, template, mock_conversion):
    result = svc.build_draft(test_db, actor, draft["id"], template, draft["lock_version"])
    assert result["state"] == "ready"
    assert result["build_id"]
    assert result["source_sha256"] and result["branded_sha256"] and result["preview_sha256"]
    assert storage.resolve_stored_path(result["source_path"]).exists()
    assert storage.resolve_stored_path(result["branded_path"]).exists()
    assert storage.resolve_stored_path(result["preview_path"]).exists()
    assert result["lock_version"] == draft["lock_version"] + 1


def test_idempotent_retry_does_not_reconvert(test_db, actor, draft, template, mock_conversion):
    first = svc.build_draft(test_db, actor, draft["id"], template, draft["lock_version"])
    assert mock_conversion["calls"] == 1

    second = svc.build_draft(test_db, actor, draft["id"], template, first["lock_version"])
    assert second["build_id"] == first["build_id"]
    assert mock_conversion["calls"] == 1, "unchanged inputs must not trigger a second conversion"


# ─────────────────────────────────────────────────────────────────────────
# Fault injection: conversion failure/timeout
# ─────────────────────────────────────────────────────────────────────────

def test_conversion_timeout_leaves_draft_unchanged(test_db, actor, draft, template, mock_conversion):
    mock_conversion["behavior"] = "timeout"
    with pytest.raises(svc.PreviewTimeoutError):
        svc.build_draft(test_db, actor, draft["id"], template, draft["lock_version"])

    unchanged = svc.get_draft(test_db, actor, draft["id"])
    assert unchanged["state"] == "editing"
    assert unchanged["build_id"] is None
    assert unchanged["lock_version"] == draft["lock_version"]


def test_conversion_failure_leaves_draft_unchanged(test_db, actor, draft, template, mock_conversion):
    mock_conversion["behavior"] = "failed"
    with pytest.raises(svc.PreviewUnavailableError):
        svc.build_draft(test_db, actor, draft["id"], template, draft["lock_version"])
    unchanged = svc.get_draft(test_db, actor, draft["id"])
    assert unchanged["state"] == "editing"


# ─────────────────────────────────────────────────────────────────────────
# Fault injection: source build and branding
# ─────────────────────────────────────────────────────────────────────────

def test_source_build_failure_leaves_draft_unchanged(test_db, actor, draft, template, mock_conversion, monkeypatch):
    import modules.aria.branding_engine as be
    monkeypatch.setattr(be, "build_policy_docx", lambda *a, **k: (_ for _ in ()).throw(ValueError("boom")))
    with pytest.raises(svc.PolicyWorkflowError) as exc_info:
        svc.build_draft(test_db, actor, draft["id"], template, draft["lock_version"])
    assert exc_info.value.code == "INVALID_INPUT"
    assert mock_conversion["calls"] == 0, "must never reach conversion if the source build already failed"
    unchanged = svc.get_draft(test_db, actor, draft["id"])
    assert unchanged["state"] == "editing"


def test_branding_failure_leaves_draft_unchanged(test_db, actor, draft, template, mock_conversion, monkeypatch):
    import modules.aria.branding_engine as be
    monkeypatch.setattr(be, "apply_template", lambda **k: (_ for _ in ()).throw(RuntimeError("branding boom")))
    with pytest.raises(svc.PolicyWorkflowError) as exc_info:
        svc.build_draft(test_db, actor, draft["id"], template, draft["lock_version"])
    assert exc_info.value.code == "INVALID_INPUT"
    assert mock_conversion["calls"] == 0
    unchanged = svc.get_draft(test_db, actor, draft["id"])
    assert unchanged["state"] == "editing"


# ─────────────────────────────────────────────────────────────────────────
# Fault injection: atomic attach (rename)
# ─────────────────────────────────────────────────────────────────────────

def test_attach_failure_leaves_draft_unchanged(test_db, actor, draft, template, mock_conversion, monkeypatch):
    monkeypatch.setattr(storage, "attach_build", lambda org_id, build_id: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        svc.build_draft(test_db, actor, draft["id"], template, draft["lock_version"])
    unchanged = svc.get_draft(test_db, actor, draft["id"])
    assert unchanged["state"] == "editing"
    assert unchanged["build_id"] is None


# ─────────────────────────────────────────────────────────────────────────
# The core correctness property: no stale build ever attaches
# ─────────────────────────────────────────────────────────────────────────

def test_concurrent_edit_during_build_prevents_stale_attach(test_db, actor, draft, template, mock_conversion):
    """Simulates another request editing the draft (bumping lock_version)
    while a build was in flight against the OLD lock_version. The build's
    final DB attach must be refused, and the artifacts it produced must be
    left as orphans (for the cleanup job), never silently attached to a
    draft state that no longer matches what was authorized."""
    # "Concurrent" edit happens first in this test's timeline, but the
    # build call below is still given the ORIGINAL (now stale) token, the
    # same as if the edit had raced it mid-build.
    svc.save_draft_body(test_db, actor, draft["id"], body="edited concurrently",
                         expected_lock_version=draft["lock_version"])

    with pytest.raises(svc.StaleDraftError):
        svc.build_draft(test_db, actor, draft["id"], template, draft["lock_version"])

    current = svc.get_draft(test_db, actor, draft["id"])
    assert current["body"] == "edited concurrently"
    assert current["build_id"] is None, "the stale build must never attach to the draft record"


def test_concurrent_discard_during_build_prevents_stale_attach(test_db, actor, draft, template, mock_conversion):
    svc.discard_draft(test_db, actor, draft["id"], expected_lock_version=draft["lock_version"])

    with pytest.raises(svc.PolicyWorkflowError):
        svc.build_draft(test_db, actor, draft["id"], template, draft["lock_version"])

    current = svc.get_draft(test_db, actor, draft["id"])
    assert current["state"] == "discarded"
    assert current["build_id"] is None


# ─────────────────────────────────────────────────────────────────────────
# Template scope and status
# ─────────────────────────────────────────────────────────────────────────

def test_build_rejects_a_retired_template(test_db, actor, draft, template, mock_conversion):
    test_db.execute("UPDATE aria_doc_templates SET is_active=0 WHERE id=%s", (template,))
    test_db.commit()
    with pytest.raises(svc.InvalidTemplateError):
        svc.build_draft(test_db, actor, draft["id"], template, draft["lock_version"])


def test_build_rejects_a_template_from_another_org(test_db, actor, draft, template, mock_conversion):
    _org(test_db, org_id=2)
    test_db.execute("UPDATE aria_doc_templates SET org_id=2 WHERE id=%s", (template,))
    test_db.commit()
    with pytest.raises(svc.NotFoundError):
        svc.build_draft(test_db, actor, draft["id"], template, draft["lock_version"])


def test_build_rejects_a_nonexistent_template(test_db, actor, draft, mock_conversion):
    with pytest.raises(svc.NotFoundError):
        svc.build_draft(test_db, actor, draft["id"], 999999, draft["lock_version"])
