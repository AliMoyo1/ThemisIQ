"""
PLAN-35 T04: draft lifecycle tests.

Covers generate-to-draft persistence, IMS metadata, idempotency, size
limits enforced before any truncation, the stale-edit conflict (the
module's actual pass condition: two editors get an explicit conflict
instead of lost edits), discard/recover, list scoping, the one-open-
revision guard, and the core "generating never touches an approved
record" invariant.
"""
import json

import pytest

from modules.aria import policy_workflow_service as svc


def _control(ref="A.5.15", name="Access Control", framework_id=7, fw_name="ISO 27001"):
    return {"id": 1, "ref": ref, "name": name, "framework_id": framework_id, "fw_name": fw_name}


def _user(db, uid, org_id, bu_id=None, username=None):
    username = username or f"user{uid}"
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, org_id, business_unit_id) "
        "VALUES (%s,%s,%s,%s,'x',%s,%s)",
        (uid, username, f"{username}@example.com", username, org_id, bu_id),
    )


def _org(db, org_id):
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
               (org_id, f"org{org_id}", f"org{org_id}"))


def _actor(db, uid):
    row = db.execute(
        "SELECT id, org_id, business_unit_id, COALESCE(is_super_admin,0) AS is_super_admin "
        "FROM users WHERE id=%s", (uid,),
    ).fetchone()
    d = dict(row)
    d["roles"] = []
    return d


@pytest.fixture
def actor(test_db):
    _org(test_db, 1)
    _user(test_db, 1, 1)
    test_db.commit()
    return _actor(test_db, 1)


# ─────────────────────────────────────────────────────────────────────────
# New policy vs. revision detection
# ─────────────────────────────────────────────────────────────────────────

def test_generation_creates_a_new_policy_draft_when_no_document_exists(test_db, actor):
    draft = svc.create_draft_from_generation(
        test_db, actor, control=_control(), generated_content="# Policy\n\nBody.",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    assert draft["source_document_id"] is None
    assert draft["reserved_doc_id"] == "DOC-0001"
    assert draft["version_major"] == 1 and draft["version_minor"] == 0
    assert draft["state"] == "editing"
    assert draft["lock_version"] == 1
    assert draft["owner_user_id"] == actor["id"]


def test_generation_targets_existing_document_as_a_revision(test_db, actor):
    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, control_ref, title, version, "
        "status, org_id, policy_workflow_managed) "
        "VALUES ('DOC-0099', 'ISO 27001', 'A.5.15', 't', '1.0', 'Approved', 1, 1)"
    )
    test_db.commit()
    doc_id_row = test_db.execute(
        "SELECT id FROM aria_documents WHERE doc_id='DOC-0099'"
    ).fetchone()

    draft = svc.create_draft_from_generation(
        test_db, actor, control=_control(), generated_content="# Revised Policy",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    assert draft["source_document_id"] == doc_id_row["id"]
    assert draft["reserved_doc_id"] is None
    assert draft["version_major"] == 1 and draft["version_minor"] == 1  # preview: 1.0 -> 1.1


def test_generating_never_changes_the_existing_approved_document(test_db, actor):
    """The module's actual pass condition."""
    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, control_ref, title, version, "
        "status, body, org_id, policy_workflow_managed) "
        "VALUES ('DOC-0099', 'ISO 27001', 'A.5.15', 'Original Title', '1.0', "
        "'Approved', 'Original approved body', 1, 1)"
    )
    test_db.commit()

    svc.create_draft_from_generation(
        test_db, actor, control=_control(), generated_content="# Completely Different Content",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )

    doc = dict(test_db.execute(
        "SELECT title, version, status, body FROM aria_documents WHERE doc_id='DOC-0099'"
    ).fetchone())
    assert doc == {
        "title": "Original Title", "version": "1.0",
        "status": "Approved", "body": "Original approved body",
    }


def test_regenerating_also_never_changes_the_approved_document(test_db, actor):
    """"Re-generating" (calling generation again for the same control) must
    be exactly as inert against the approved record as the first call."""
    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, control_ref, title, version, "
        "status, body, org_id, policy_workflow_managed) "
        "VALUES ('DOC-0099', 'ISO 27001', 'A.5.15', 'Original Title', '1.0', "
        "'Approved', 'Original approved body', 1, 1)"
    )
    test_db.commit()

    for _ in range(3):
        try:
            svc.create_draft_from_generation(
                test_db, actor, control=_control(), generated_content=f"# Attempt content",
                org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
                integrated_controls=None, request_id=None, target_business_unit_id=None,
            )
        except svc.OpenRevisionExistsError:
            pass  # expected from the 2nd/3rd call onward; see one-open-revision test below

    doc = dict(test_db.execute(
        "SELECT title, version, status, body FROM aria_documents WHERE doc_id='DOC-0099'"
    ).fetchone())
    assert doc == {
        "title": "Original Title", "version": "1.0",
        "status": "Approved", "body": "Original approved body",
    }


# ─────────────────────────────────────────────────────────────────────────
# IMS metadata
# ─────────────────────────────────────────────────────────────────────────

def test_ims_integrated_controls_stored_in_metadata(test_db, actor):
    integrated = [{"framework": "SOC 2", "ref": "CC6.1", "name": "Logical Access", "description": ""}]
    draft = svc.create_draft_from_generation(
        test_db, actor, control=_control(), generated_content="# IMS Policy",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001, SOC 2",
        integrated_controls=integrated, request_id=None, target_business_unit_id=None,
    )
    metadata = json.loads(draft["metadata_json"])
    assert metadata["framework_label"] == "ISO 27001, SOC 2"
    assert metadata["integrated_controls"] == integrated


# ─────────────────────────────────────────────────────────────────────────
# Idempotency
# ─────────────────────────────────────────────────────────────────────────

def test_repeated_request_id_returns_the_same_draft_not_a_duplicate(test_db, actor):
    first = svc.create_draft_from_generation(
        test_db, actor, control=_control(), generated_content="# Policy",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id="req-abc", target_business_unit_id=None,
    )
    second = svc.create_draft_from_generation(
        test_db, actor, control=_control(), generated_content="# Different content this time",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id="req-abc", target_business_unit_id=None,
    )
    assert first["id"] == second["id"]
    count = test_db.execute(
        "SELECT COUNT(*) FROM aria_policy_drafts WHERE generation_request_id='req-abc'"
    ).fetchone()[0]
    assert count == 1


# ─────────────────────────────────────────────────────────────────────────
# Size limits, rejected before truncation
# ─────────────────────────────────────────────────────────────────────────

def test_over_limit_generated_content_is_rejected_not_truncated(test_db, actor):
    huge = "x" * (svc.MAX_BODY_CHARS + 1)
    with pytest.raises(svc.ContentTooLargeError):
        svc.create_draft_from_generation(
            test_db, actor, control=_control(), generated_content=huge,
            org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
            integrated_controls=None, request_id=None, target_business_unit_id=None,
        )
    count = test_db.execute("SELECT COUNT(*) FROM aria_policy_drafts").fetchone()[0]
    assert count == 0, "an oversized draft must never be partially saved"


def test_over_limit_save_is_rejected(test_db, actor):
    draft = svc.create_draft_from_generation(
        test_db, actor, control=_control(), generated_content="# Policy",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    huge = "x" * (svc.MAX_BODY_CHARS + 1)
    with pytest.raises(svc.ContentTooLargeError):
        svc.save_draft_body(test_db, actor, draft["id"], body=huge,
                             expected_lock_version=draft["lock_version"])


# ─────────────────────────────────────────────────────────────────────────
# The stale-edit conflict: two editors, explicit conflict, no lost edits
# ─────────────────────────────────────────────────────────────────────────

def test_two_editors_get_an_explicit_conflict_not_a_lost_edit(test_db, actor):
    draft = svc.create_draft_from_generation(
        test_db, actor, control=_control(), generated_content="# Original",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    # Both "editor A" and "editor B" load the same draft at lock_version 1.
    editor_a_view = svc.get_draft(test_db, actor, draft["id"])
    editor_b_view = svc.get_draft(test_db, actor, draft["id"])
    assert editor_a_view["lock_version"] == editor_b_view["lock_version"] == 1

    # Editor A saves first and succeeds.
    saved = svc.save_draft_body(
        test_db, actor, draft["id"], body="Editor A's version",
        expected_lock_version=editor_a_view["lock_version"],
    )
    assert saved["lock_version"] == 2
    assert saved["body"] == "Editor A's version"

    # Editor B, still holding the stale token, must get an explicit
    # conflict rather than silently overwriting A's save.
    with pytest.raises(svc.StaleDraftError):
        svc.save_draft_body(
            test_db, actor, draft["id"], body="Editor B's version (should not win)",
            expected_lock_version=editor_b_view["lock_version"],
        )

    final = svc.get_draft(test_db, actor, draft["id"])
    assert final["body"] == "Editor A's version", "editor B's stale write must not have applied"


def test_save_invalidates_a_prior_build(test_db, actor):
    draft = svc.create_draft_from_generation(
        test_db, actor, control=_control(), generated_content="# Policy",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    test_db.execute(
        "UPDATE aria_policy_drafts SET state='ready', build_id='fake-build', "
        "source_path='x.docx', branded_path='y.docx', preview_path='z.pdf' "
        "WHERE id=%s", (draft["id"],),
    )
    test_db.commit()

    updated = svc.save_draft_body(
        test_db, actor, draft["id"], body="edited",
        expected_lock_version=1,
    )
    assert updated["state"] == "editing"
    assert updated["build_id"] is None
    assert updated["source_path"] is None
    assert updated["branded_path"] is None
    assert updated["preview_path"] is None


# ─────────────────────────────────────────────────────────────────────────
# Discard / recover
# ─────────────────────────────────────────────────────────────────────────

def test_discard_then_recover_creates_a_new_draft_preserving_history(test_db, actor):
    draft = svc.create_draft_from_generation(
        test_db, actor, control=_control(), generated_content="# Policy body to keep",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    svc.discard_draft(test_db, actor, draft["id"], expected_lock_version=1)

    original = svc.get_draft(test_db, actor, draft["id"])
    assert original["state"] == "discarded"

    recovered = svc.recover_draft(test_db, actor, draft["id"])
    assert recovered["id"] != draft["id"]
    assert recovered["state"] == "editing"
    assert recovered["lock_version"] == 1
    assert recovered["body"] == "# Policy body to keep"

    # The original stays discarded, not un-discarded in place.
    original_again = svc.get_draft(test_db, actor, draft["id"])
    assert original_again["state"] == "discarded"


def test_cannot_recover_an_editing_draft(test_db, actor):
    draft = svc.create_draft_from_generation(
        test_db, actor, control=_control(), generated_content="# Policy",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    with pytest.raises(svc.PolicyWorkflowError):
        svc.recover_draft(test_db, actor, draft["id"])


# ─────────────────────────────────────────────────────────────────────────
# List scoping
# ─────────────────────────────────────────────────────────────────────────

def test_list_my_drafts_excludes_other_owners_and_discarded(test_db, actor):
    _user(test_db, 2, 1, username="other")
    test_db.commit()
    other_actor = _actor(test_db, 2)

    mine = svc.create_draft_from_generation(
        test_db, actor, control=_control(ref="A.1"), generated_content="# Mine",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    svc.create_draft_from_generation(
        test_db, other_actor, control=_control(ref="A.2"), generated_content="# Not mine",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    discarded = svc.create_draft_from_generation(
        test_db, actor, control=_control(ref="A.3"), generated_content="# Discarded",
        org_name="Econet", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=None,
    )
    svc.discard_draft(test_db, actor, discarded["id"], expected_lock_version=1)

    my_drafts = svc.list_my_drafts(test_db, actor)
    ids = {d["id"] for d in my_drafts}
    assert ids == {mine["id"]}


# ─────────────────────────────────────────────────────────────────────────
# One-open-revision guard (start_revision_draft)
# ─────────────────────────────────────────────────────────────────────────

def test_one_open_revision_guard_blocks_a_second_revision_draft(test_db, actor):
    test_db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s, 'policy_author')",
                     (actor["id"],))
    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, control_ref, title, version, "
        "status, org_id, owner_user_id, policy_workflow_managed) "
        "VALUES ('DOC-0050', 'ISO 27001', 'A.9.1', 't', '1.0', 'Approved', 1, %s, 1)",
        (actor["id"],),
    )
    test_db.commit()
    actor_with_role = _actor(test_db, actor["id"])
    actor_with_role["roles"] = ["policy_author"]

    first = svc.start_revision_draft(test_db, actor_with_role, "DOC-0050")
    assert first["state"] == "editing"

    with pytest.raises(svc.OpenRevisionExistsError):
        svc.start_revision_draft(test_db, actor_with_role, "DOC-0050")


def test_revision_draft_requires_edit_permission(test_db, actor):
    _user(test_db, 3, 1, username="stranger")
    test_db.commit()
    stranger = _actor(test_db, 3)  # no roles: no edit_own/edit_any

    test_db.execute(
        "INSERT INTO aria_documents (doc_id, framework, control_ref, title, version, "
        "status, org_id, owner_user_id, policy_workflow_managed) "
        "VALUES ('DOC-0051', 'ISO 27001', 'A.9.2', 't', '1.0', 'Approved', 1, %s, 1)",
        (actor["id"],),
    )
    test_db.commit()

    with pytest.raises(svc.ForbiddenError):
        svc.start_revision_draft(test_db, stranger, "DOC-0051")
