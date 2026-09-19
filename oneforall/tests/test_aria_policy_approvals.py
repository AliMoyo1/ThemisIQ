"""
PLAN-35 T07: submission, decision, withdrawal tests.

Covers eligible-approver resolution, named submission with hash/round-
number binding, separation of duties (owner/creator/contributor/requester
all excluded), approve/reject/withdraw transitions and their effect on the
document projection, decision refusing a since-ineligible approver
(deactivated, moved BU, removed role), stale-token refusal, the atomic
current-version-promotion + publication-job insert on approval, and real
concurrent deciders racing for the same approval.
"""
import concurrent.futures
import io

import pytest
from docx import Document as DocxDocument

import database
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
    """Also creates org 1: this fixture must run (and create the org)
    before any org_id=1 foreign key, including its own template insert,
    can succeed -- callers that need both an org and a template depend on
    this fixture rather than calling _org() themselves afterward."""
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
    """One BU, an author (uid 1) and an eligible approver (uid 2, holds
    compliance_manager), a confirmed version ready to submit. Org 1 is
    already created by the template fixture above."""
    _bu(test_db, 100, "Finance")
    _user(test_db, 1, bu_id=100, username="author")
    _user(test_db, 2, bu_id=100, username="approver")
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
    return {"author": author, "approver_id": 2, "confirmed": confirmed}


# ─────────────────────────────────────────────────────────────────────────
# Eligible approver resolution and separation of duties
# ─────────────────────────────────────────────────────────────────────────

def test_owner_is_excluded_from_their_own_eligible_approver_list(test_db, scenario):
    _role(test_db, scenario["author"]["id"], "compliance_manager")  # author would otherwise qualify
    test_db.commit()
    approvers = svc.list_eligible_approvers_for_version(test_db, scenario["author"], scenario["confirmed"]["version_id"])
    ids = {a["id"] for a in approvers}
    assert scenario["author"]["id"] not in ids
    assert scenario["approver_id"] in ids


def test_submit_rejects_an_ineligible_approver(test_db, scenario):
    _user(test_db, 3, bu_id=100, username="no_role")
    test_db.commit()
    with pytest.raises(svc.ApproverIneligibleError):
        svc.submit_for_approval(
            test_db, scenario["author"], scenario["confirmed"]["version_id"], 3,
            "please review", "req-1", 1,
        )


def test_submit_rejects_the_owner_as_their_own_approver(test_db, scenario):
    _role(test_db, scenario["author"]["id"], "compliance_manager")
    test_db.commit()
    with pytest.raises(svc.ApproverIneligibleError):
        svc.submit_for_approval(
            test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["author"]["id"],
            "self review", "req-2", 1,
        )


# ─────────────────────────────────────────────────────────────────────────
# Submission: hash/round-number binding, idempotency
# ─────────────────────────────────────────────────────────────────────────

def test_submit_binds_hashes_and_round_number(test_db, scenario):
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "review please", "req-1", 1,
    )
    row = dict(test_db.execute("SELECT * FROM aria_document_approvals WHERE id=%s", (approval["id"],)).fetchone())
    version = dict(test_db.execute(
        "SELECT * FROM aria_policy_versions WHERE id=%s", (scenario["confirmed"]["version_id"],)
    ).fetchone())
    assert row["round_number"] == 1
    assert row["submitted_branded_sha256"] == version["branded_sha256"]
    assert row["submitted_preview_sha256"] == version["preview_sha256"]
    assert version["state"] == "pending"

    doc = dict(test_db.execute("SELECT status FROM aria_documents WHERE id=%s", (scenario["confirmed"]["document_id"],)).fetchone())
    assert doc["status"] == "Under Review"


def test_resubmitting_same_request_id_is_idempotent(test_db, scenario):
    first = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    second = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    assert first == second
    count = test_db.execute(
        "SELECT COUNT(*) FROM aria_document_approvals WHERE request_id='req-1'"
    ).fetchone()[0]
    assert count == 1


def test_cannot_submit_twice_while_one_is_already_pending(test_db, scenario):
    svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    with pytest.raises(svc.OpenRevisionExistsError):
        svc.submit_for_approval(
            test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
            "note again", "req-2", 2,
        )


# ─────────────────────────────────────────────────────────────────────────
# Decide: approve
# ─────────────────────────────────────────────────────────────────────────

def test_approve_promotes_current_version_and_inserts_publication_job(test_db, scenario):
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    approver_actor = _actor(test_db, scenario["approver_id"])
    result = svc.decide_approval(test_db, approver_actor, approval["id"], "approve", "looks good", approval["lock_version"])
    assert result["status"] == "approved"

    doc = dict(test_db.execute(
        "SELECT status, current_policy_version_id, version FROM aria_documents WHERE id=%s",
        (scenario["confirmed"]["document_id"],),
    ).fetchone())
    assert doc["status"] == "Approved"
    assert doc["current_policy_version_id"] == scenario["confirmed"]["version_id"]
    assert doc["version"] == "1.0"

    version = dict(test_db.execute(
        "SELECT state, approved_by FROM aria_policy_versions WHERE id=%s", (scenario["confirmed"]["version_id"],)
    ).fetchone())
    assert version["state"] == "approved"
    assert version["approved_by"] == scenario["approver_id"]

    job = test_db.execute(
        "SELECT state FROM aria_policy_publication_jobs WHERE policy_version_id=%s",
        (scenario["confirmed"]["version_id"],),
    ).fetchone()
    assert job is not None and job["state"] == "pending"


def test_approving_twice_is_refused_second_time(test_db, scenario):
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    approver_actor = _actor(test_db, scenario["approver_id"])
    result = svc.decide_approval(test_db, approver_actor, approval["id"], "approve", "ok", approval["lock_version"])
    with pytest.raises(svc.AlreadyDecidedError):
        svc.decide_approval(test_db, approver_actor, approval["id"], "approve", "ok again", result["lock_version"] - 1)


def test_decide_requires_a_comment_to_reject(test_db, scenario):
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    approver_actor = _actor(test_db, scenario["approver_id"])
    with pytest.raises(svc.InvalidDecisionError):
        svc.decide_approval(test_db, approver_actor, approval["id"], "reject", "", approval["lock_version"])


# ─────────────────────────────────────────────────────────────────────────
# Decide: reject, and the document-projection rule
# ─────────────────────────────────────────────────────────────────────────

def test_reject_before_first_approval_sets_document_to_draft(test_db, scenario):
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    approver_actor = _actor(test_db, scenario["approver_id"])
    svc.decide_approval(test_db, approver_actor, approval["id"], "reject", "needs work", approval["lock_version"])

    doc = dict(test_db.execute("SELECT status, current_policy_version_id FROM aria_documents WHERE id=%s",
                                (scenario["confirmed"]["document_id"],)).fetchone())
    assert doc["status"] == "Draft"
    # Section 6.3: "show the decision beside the retained snapshot" -- the
    # pointer stays on the rejected version (it's the only content that
    # ever existed for this document), only the document status reverts.
    assert doc["current_policy_version_id"] == scenario["confirmed"]["version_id"]

    version = dict(test_db.execute("SELECT state FROM aria_policy_versions WHERE id=%s",
                                    (scenario["confirmed"]["version_id"],)).fetchone())
    assert version["state"] == "rejected"


def test_reject_of_a_revision_leaves_the_approved_current_version_untouched(test_db, scenario, template):
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    approver_actor = _actor(test_db, scenario["approver_id"])
    svc.decide_approval(test_db, approver_actor, approval["id"], "approve", "ok", approval["lock_version"])

    doc_row = test_db.execute("SELECT doc_id FROM aria_documents WHERE id=%s", (scenario["confirmed"]["document_id"],)).fetchone()
    revision = svc.start_revision_draft(test_db, scenario["author"], doc_row["doc_id"])
    revision = svc.save_draft_body(test_db, scenario["author"], revision["id"], body="# Revised",
                                    expected_lock_version=revision["lock_version"])
    built2 = svc.build_draft(test_db, scenario["author"], revision["id"], template, revision["lock_version"])
    confirmed2 = svc.confirm_draft(test_db, scenario["author"], built2["id"], built2["build_id"], built2["lock_version"])

    approval2 = svc.submit_for_approval(
        test_db, scenario["author"], confirmed2["version_id"], scenario["approver_id"], "note2", "req-2", 1,
    )
    svc.decide_approval(test_db, approver_actor, approval2["id"], "reject", "not this time", approval2["lock_version"])

    doc = dict(test_db.execute("SELECT status, version, current_policy_version_id FROM aria_documents WHERE id=%s",
                                (scenario["confirmed"]["document_id"],)).fetchone())
    assert doc["status"] == "Approved"
    assert doc["version"] == "1.0"
    assert doc["current_policy_version_id"] == scenario["confirmed"]["version_id"], \
        "current pointer must stay on the previously approved version, not the rejected candidate"


# ─────────────────────────────────────────────────────────────────────────
# Decision refuses a since-ineligible approver
# ─────────────────────────────────────────────────────────────────────────

def test_decide_refuses_a_deactivated_approver(test_db, scenario):
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    test_db.execute("UPDATE users SET is_active=0 WHERE id=%s", (scenario["approver_id"],))
    test_db.commit()
    approver_actor = _actor(test_db, scenario["approver_id"])
    with pytest.raises(svc.ApproverIneligibleError):
        svc.decide_approval(test_db, approver_actor, approval["id"], "approve", "ok", approval["lock_version"])


def test_decide_refuses_an_approver_whose_role_was_removed(test_db, scenario):
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    test_db.execute("DELETE FROM user_roles WHERE user_id=%s", (scenario["approver_id"],))
    test_db.commit()
    approver_actor = _actor(test_db, scenario["approver_id"])
    # Losing aria.policy.approve entirely is caught by can_decide's own
    # capability check (-> ForbiddenError) before the later, more specific
    # still-eligible re-check (-> ApproverIneligibleError) is even reached.
    # Either is a correct refusal; the requirement under test is that a
    # role removal is caught at all, not which of the two catches it.
    with pytest.raises(svc.PolicyWorkflowError) as exc_info:
        svc.decide_approval(test_db, approver_actor, approval["id"], "approve", "ok", approval["lock_version"])
    assert exc_info.value.code in ("ACTION_FORBIDDEN", "APPROVER_INELIGIBLE")


def test_decide_refuses_an_approver_moved_to_a_sibling_bu(test_db, scenario):
    _bu(test_db, 101, "Marketing")
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    test_db.execute("UPDATE users SET business_unit_id=101 WHERE id=%s", (scenario["approver_id"],))
    test_db.commit()
    approver_actor = _actor(test_db, scenario["approver_id"])
    # Moving out of scope entirely is caught by document_read_ok's own
    # scope check (-> NotFoundError, matching this plan's established
    # "inaccessible object IDs return 404" pattern) before the later
    # still-eligible re-check is reached. Either is a correct refusal.
    with pytest.raises(svc.PolicyWorkflowError) as exc_info:
        svc.decide_approval(test_db, approver_actor, approval["id"], "approve", "ok", approval["lock_version"])
    assert exc_info.value.code in ("NOT_FOUND", "APPROVER_INELIGIBLE")


def test_decide_refuses_a_stale_lock_token(test_db, scenario):
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    approver_actor = _actor(test_db, scenario["approver_id"])
    with pytest.raises(svc.StaleDraftError):
        svc.decide_approval(test_db, approver_actor, approval["id"], "approve", "ok", approval["lock_version"] + 5)


def test_decide_refuses_someone_who_is_not_the_assigned_approver(test_db, scenario):
    _user(test_db, 4, bu_id=100, username="bystander")
    _role(test_db, 4, "compliance_manager")
    test_db.commit()
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    bystander = _actor(test_db, 4)
    with pytest.raises(svc.ForbiddenError):
        svc.decide_approval(test_db, bystander, approval["id"], "approve", "ok", approval["lock_version"])


# ─────────────────────────────────────────────────────────────────────────
# Withdraw
# ─────────────────────────────────────────────────────────────────────────

def test_withdraw_then_resubmit(test_db, scenario):
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    withdrawn = svc.withdraw_approval(test_db, scenario["author"], approval["id"],
                                       "wrong approver assigned", approval["lock_version"])
    assert withdrawn["status"] == "withdrawn"

    doc = dict(test_db.execute("SELECT status FROM aria_documents WHERE id=%s",
                                (scenario["confirmed"]["document_id"],)).fetchone())
    assert doc["status"] == "Draft"

    # The first submission already bumped the version's lock_version once
    # (1 -> 2); withdrawal doesn't touch it further, so the resubmit must
    # present the current token, not the original pre-submission one.
    current_version = dict(test_db.execute(
        "SELECT lock_version FROM aria_policy_versions WHERE id=%s", (scenario["confirmed"]["version_id"],)
    ).fetchone())
    resubmitted = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "resubmitting", "req-2", current_version["lock_version"],
    )
    assert resubmitted["round_number"] == 2


def test_cannot_withdraw_an_already_decided_submission(test_db, scenario):
    approval = svc.submit_for_approval(
        test_db, scenario["author"], scenario["confirmed"]["version_id"], scenario["approver_id"],
        "note", "req-1", 1,
    )
    approver_actor = _actor(test_db, scenario["approver_id"])
    decided = svc.decide_approval(test_db, approver_actor, approval["id"], "approve", "ok", approval["lock_version"])
    with pytest.raises(svc.AlreadyDecidedError):
        svc.withdraw_approval(test_db, scenario["author"], approval["id"], "changed my mind", decided["lock_version"])


# ─────────────────────────────────────────────────────────────────────────
# Real concurrency: two deciders racing for the same approval
# ─────────────────────────────────────────────────────────────────────────

def test_two_concurrent_deciders_exactly_one_wins(tmp_path, monkeypatch):
    """Uses a real file-based DB and real separate connections/threads,
    not the shared in-memory test_db fixture, so this is a genuine race,
    not a simulated one."""
    monkeypatch.setattr(database, "_DB_PATH", str(tmp_path / "concurrency.db"))
    database.init_db()
    monkeypatch.setattr(storage, "ARIA_UPLOAD_DIR", tmp_path / "aria_uploads")
    monkeypatch.setattr(storage, "WORKFLOW_ROOT", tmp_path / "aria_uploads" / "policy_workflow")
    monkeypatch.setattr(preview, "submit_conversion_job", lambda b, timeout_seconds=None: "job")
    monkeypatch.setattr(preview, "poll_conversion_result", lambda j, timeout_seconds=None, poll_interval=0.5: b"%PDF-X")
    monkeypatch.setattr(preview, "cleanup_job", lambda j: None)
    template_dir = tmp_path / "aria_templates"
    template_dir.mkdir()
    (template_dir / "t1.docx").write_bytes(_real_template_bytes())
    monkeypatch.setattr("modules.aria.routes.ARIA_TEMPLATE_DIR", template_dir)

    setup_db = database.get_db()
    _org(setup_db)
    _bu(setup_db, 100, "Finance")
    _user(setup_db, 1, bu_id=100, username="author")
    _user(setup_db, 2, bu_id=100, username="approver")
    _role(setup_db, 1, "policy_author")
    _role(setup_db, 2, "compliance_manager")
    setup_db.execute(
        "INSERT INTO aria_doc_templates (name, file_path, file_name, org_id, is_active) "
        "VALUES ('T1', 't1.docx', 't1.docx', 1, 1)"
    )
    setup_db.commit()
    template_id = setup_db.execute("SELECT id FROM aria_doc_templates WHERE file_path='t1.docx'").fetchone()["id"]
    author = _actor(setup_db, 1)
    draft = svc.create_draft_from_generation(
        setup_db, author, control={"id": 1, "ref": "A.1", "name": "Test", "framework_id": 1, "fw_name": "ISO 27001"},
        generated_content="# Policy", org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=100,
    )
    built = svc.build_draft(setup_db, author, draft["id"], template_id, draft["lock_version"])
    confirmed = svc.confirm_draft(setup_db, author, built["id"], built["build_id"], built["lock_version"])
    approval = svc.submit_for_approval(setup_db, author, confirmed["version_id"], 2, "note", "req-1", 1)
    setup_db.close()

    results = []
    errors = []

    def decide_worker():
        db = database.get_db()
        try:
            approver_actor = _actor(db, 2)
            result = svc.decide_approval(db, approver_actor, approval["id"], "approve", "ok", approval["lock_version"])
            results.append(result)
        except svc.PolicyWorkflowError as exc:
            errors.append(exc)
        finally:
            db.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(decide_worker) for _ in range(2)]
        for f in futures:
            f.result()

    assert len(results) == 1, f"expected exactly one winner, got {len(results)}"
    assert len(errors) == 1
    assert isinstance(errors[0], svc.AlreadyDecidedError)

    verify_db = database.get_db()
    jobs = verify_db.execute(
        "SELECT COUNT(*) FROM aria_policy_publication_jobs WHERE policy_version_id=%s",
        (confirmed["version_id"],),
    ).fetchone()[0]
    assert jobs == 1, "exactly one publication job must exist even though two decisions were attempted"
    verify_db.close()
