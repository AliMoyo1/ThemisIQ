"""
PLAN-36 P03: policy_workflow_service.get_document_workbench_state -- the
federated read view backing the ARIA policy lifecycle workbench.

Every can_* field here is a UI hint only, computed with the exact same
helper the real mutating endpoint uses; the assertions below verify the
hint matches the endpoint's real gate, not an invented parallel rule.
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


def _bu(db, bu_id, name, parent_id=None):
    db.execute("INSERT INTO business_units (id, name, parent_id, is_active) VALUES (%s,%s,%s,1)",
               (bu_id, name, parent_id))


def _user(db, uid, org_id=1, bu_id=None, username=None, is_active=1):
    username = username or f"user{uid}"
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, org_id, "
        "business_unit_id, is_active) VALUES (%s,%s,%s,%s,'x',%s,%s,%s)",
        (uid, username, f"{username}@x.com", username, org_id, bu_id, is_active),
    )


def _role(db, uid, role_key):
    db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s,%s)", (uid, role_key))


def _actor(db, uid):
    row = db.execute(
        "SELECT id, username, full_name, org_id, business_unit_id, "
        "COALESCE(is_super_admin,0) AS is_super_admin FROM users WHERE id=%s", (uid,),
    ).fetchone()
    d = dict(row)
    d["roles"] = [r[0] for r in db.execute(
        "SELECT role_key FROM user_roles WHERE user_id=%s", (uid,)
    ).fetchall()]
    return d


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
def template(test_db, tmp_path, monkeypatch):
    _org(test_db)
    test_db.commit()
    template_dir = tmp_path / "aria_templates"
    template_dir.mkdir()
    (template_dir / "t1.docx").write_bytes(_real_template_bytes())
    monkeypatch.setattr("modules.aria.routes.ARIA_TEMPLATE_DIR", template_dir)
    test_db.execute(
        "INSERT INTO aria_doc_templates (name, file_path, file_name, org_id, is_active) "
        "VALUES ('T1', 't1.docx', 't1.docx', 1, 1)"
    )
    test_db.commit()
    return test_db.execute("SELECT id FROM aria_doc_templates WHERE file_path='t1.docx'").fetchone()["id"]


@pytest.fixture
def scenario(test_db, template):
    """One BU, an author (uid 1), an eligible approver (uid 2), a plain
    read-only employee with no ARIA capability (uid 3), and a confirmed
    first version -- state 'draft', promoted straight to current_policy_version_id
    since this is a brand-new document (confirm_draft's promote_to_current)."""
    _bu(test_db, 100, "Finance")
    _user(test_db, 1, bu_id=100, username="author")
    _user(test_db, 2, bu_id=100, username="approver")
    _user(test_db, 3, bu_id=100, username="bystander")
    _role(test_db, 1, "policy_author")
    _role(test_db, 2, "compliance_manager")
    test_db.commit()

    author = _actor(test_db, 1)
    draft = svc.create_draft_from_generation(
        test_db, author, control={"id": 1, "ref": "A.1", "name": "Test", "framework_id": 1, "fw_name": "ISO 27001"},
        generated_content="# Policy\n\nBody.", org_name="Econet", doc_type="Policy",
        framework_label="ISO 27001", integrated_controls=None, request_id=None, target_business_unit_id=100,
    )
    built = svc.build_draft(test_db, author, draft["id"], template, draft["lock_version"])
    confirmed = svc.confirm_draft(test_db, author, built["id"], built["build_id"], built["lock_version"])
    return {"author": author, "approver": _actor(test_db, 2), "bystander": _actor(test_db, 3),
            "confirmed": confirmed}


# ─────────────────────────────────────────────────────────────────────────
# Brand-new document, pre-submission: the first version is simultaneously
# "current" and the thing awaiting submission -- there is no separate
# candidate row yet.
# ─────────────────────────────────────────────────────────────────────────

def test_new_document_shows_current_version_as_submittable(test_db, scenario):
    doc_id = test_db.execute(
        "SELECT doc_id FROM aria_documents WHERE id=%s", (scenario["confirmed"]["document_id"],)
    ).fetchone()["doc_id"]
    state = svc.get_document_workbench_state(test_db, scenario["author"], doc_id)

    assert state["current_version"]["id"] == scenario["confirmed"]["version_id"]
    assert state["current_version"]["state"] == "draft"
    assert state["candidate"] is None
    assert state["submittable_version"]["id"] == scenario["confirmed"]["version_id"]
    assert state["submittable_version"]["can_submit"] is True
    assert state["active_approval"] is None


def test_can_submit_is_false_for_a_user_with_no_edit_permission(test_db, scenario):
    """Red/green-relevant: a bystander with plain document read access (same
    org/BU, no aria.policy.edit_own/edit_any) must not be told they can
    submit -- _draft_can_edit_document is the same gate submit_for_approval
    itself enforces."""
    doc_id = test_db.execute(
        "SELECT doc_id FROM aria_documents WHERE id=%s", (scenario["confirmed"]["document_id"],)
    ).fetchone()["doc_id"]
    state = svc.get_document_workbench_state(test_db, scenario["bystander"], doc_id)
    assert state["submittable_version"]["can_submit"] is False


def test_unknown_document_raises_not_found(test_db, scenario):
    with pytest.raises(svc.NotFoundError):
        svc.get_document_workbench_state(test_db, scenario["author"], "NO-SUCH-DOC")


def test_cross_org_document_raises_not_found_not_forbidden(test_db, scenario):
    """Fail-closed: a 404, not a 403, so a cross-org id is never confirmed
    to exist (same convention as document_read_ok's other callers)."""
    _org(test_db, org_id=2)
    _user(test_db, 99, org_id=2, username="otherorg")
    test_db.commit()
    other_org_actor = _actor(test_db, 99)
    doc_id = test_db.execute(
        "SELECT doc_id FROM aria_documents WHERE id=%s", (scenario["confirmed"]["document_id"],)
    ).fetchone()["doc_id"]
    with pytest.raises(svc.NotFoundError):
        svc.get_document_workbench_state(test_db, other_org_actor, doc_id)


# ─────────────────────────────────────────────────────────────────────────
# Submitted, pending decision: still on current_version's own slot (no
# separate candidate exists for a first-ever version) -- active_approval
# must be found and gated correctly regardless.
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def pending_scenario(test_db, scenario):
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver"]["id"],
        "please review", "req-1", 1,
    )
    scenario["approval"] = approval
    scenario["doc_id"] = test_db.execute(
        "SELECT doc_id FROM aria_documents WHERE id=%s", (scenario["confirmed"]["document_id"],)
    ).fetchone()["doc_id"]
    return scenario


def test_assigned_approver_can_decide_but_bystander_cannot(test_db, pending_scenario):
    approver_state = svc.get_document_workbench_state(test_db, pending_scenario["approver"], pending_scenario["doc_id"])
    assert approver_state["active_approval"]["can_decide"] is True
    assert approver_state["active_approval"]["policy_version_id"] == pending_scenario["confirmed"]["version_id"]

    bystander_state = svc.get_document_workbench_state(test_db, pending_scenario["bystander"], pending_scenario["doc_id"])
    # A bystander with no edit_any/approver/requester relationship to this
    # approval must not even see it (matches get_approval's own visibility rule).
    assert bystander_state["active_approval"] is None


def test_requester_can_withdraw_but_approver_cannot(test_db, pending_scenario):
    author_state = svc.get_document_workbench_state(test_db, pending_scenario["author"], pending_scenario["doc_id"])
    assert author_state["active_approval"]["can_withdraw"] is True
    assert author_state["active_approval"]["can_decide"] is False  # author is not the approver

    approver_state = svc.get_document_workbench_state(test_db, pending_scenario["approver"], pending_scenario["doc_id"])
    assert approver_state["active_approval"]["can_withdraw"] is False


def test_submittable_version_is_none_once_pending(test_db, pending_scenario):
    state = svc.get_document_workbench_state(test_db, pending_scenario["author"], pending_scenario["doc_id"])
    assert state["current_version"]["state"] == "pending"
    assert state["submittable_version"] is None


# ─────────────────────────────────────────────────────────────────────────
# Draft visibility: at most one open draft per document (I09), but only
# actually visible/editable to its owner or an edit_any holder.
# ─────────────────────────────────────────────────────────────────────────

def test_draft_editable_by_owner_hidden_from_bystander(test_db, scenario):
    doc = test_db.execute("SELECT doc_id FROM aria_documents WHERE id=%s", (scenario["confirmed"]["document_id"],)).fetchone()
    # Approve the first version so a revision draft is legal to start.
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver"]["id"],
        "please review", "req-1", 1,
    )
    svc.decide_approval(test_db, scenario["approver"], approval["id"], "approve", "", approval["lock_version"])

    new_draft = svc.start_revision_draft(test_db, scenario["author"], doc["doc_id"])

    owner_state = svc.get_document_workbench_state(test_db, scenario["author"], doc["doc_id"])
    assert owner_state["draft"]["id"] == new_draft["id"]
    assert owner_state["draft"]["can_edit"] is True

    bystander_state = svc.get_document_workbench_state(test_db, scenario["bystander"], doc["doc_id"])
    assert bystander_state["draft"] is None  # exists, but not theirs to see
    assert bystander_state["can_start_revision"] is False  # no edit_own/edit_any permission
