"""
PLAN-36 P03: real-browser coverage for the ARIA policy workbench page.

Seeds a pending approval directly via SQL (document -> version -> approval
rows) rather than running the full draft/build/convert pipeline through a
real LibreOffice-conversion mock a second time -- that heavier fixture
already exists (tests/test_aria_policy_approvals.py's `scenario`) and its
business logic (submission, hashing, round numbers) is already covered
there and in tests/test_aria_policy_workbench.py's service-level tests with
a red/green proof. What only a real browser test can catch is whether the
rendered page actually wires renderApprovalDecision/initSubmitForApprovalForm
correctly -- a script tag typo, a DOM id mismatch between the template and
aria_policy_workflow.js, a JS exception -- so that is what this file checks:
the one primary transition task_plan.md's P03 acceptance line singles out
by name ("author cannot approve own content"), visible in a real render.
"""
import database
import pytest

from core.auth import hash_password
from tests.ui.conftest import PERSONA_PASSWORD

_PASSWORD = "Synthetic-Test-Pass-2!"


@pytest.fixture(scope="module")
def pending_approval_doc(live_app, synthetic_tenant):
    """A managed document, org-wide (business_unit_id NULL so it's readable
    regardless of BU scope), with a version pending approval by the
    synthetic tenant's compliance_manager, requested by a separately
    seeded author who is not the approver. Module-scoped (like
    test_org_isolation.py's second_org_risk_owner) so both tests in this
    file share the one seeded document rather than colliding on a second
    insert of the same username/doc_id."""
    org_id = synthetic_tenant["users"]["compliance_manager"]["org_id"]
    approver_id = synthetic_tenant["users"]["compliance_manager"]["user_id"]

    db = database.get_db()
    try:
        username = "uiharness_wb_author"
        db.execute(
            "INSERT INTO users (username, email, full_name, password_hash, org_id, "
            "is_super_admin, must_change_password) VALUES (%s,%s,%s,%s,%s,0,0)",
            (username, f"{username}@example.test", "Workbench Author",
             hash_password(_PASSWORD), org_id),
        )
        db.commit()
        author_id = db.execute("SELECT id FROM users WHERE username=%s", (username,)).fetchone()["id"]
        # module.aria.access (require_module("aria")) requires a role that
        # grants it -- a bare user row has none (core/rbac.py's CAPABILITIES).
        db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s,'policy_author')", (author_id,))
        db.commit()

        doc_id = "WB-TEST-001"
        db.execute(
            "INSERT INTO aria_documents (doc_id, framework, control_ref, title, doc_type, "
            "version, status, org_id, business_unit_id, owner_user_id, policy_workflow_managed) "
            "VALUES (%s,'ISO 27001','A.1','Workbench Test Policy','Policy','1.0','Draft',%s,NULL,%s,1)",
            (doc_id, org_id, author_id),
        )
        db.commit()
        document_id = db.execute("SELECT id FROM aria_documents WHERE doc_id=%s", (doc_id,)).fetchone()["id"]

        db.execute(
            "INSERT INTO aria_policy_versions (org_id, document_id, version_major, version_minor, "
            "version, state, origin, body, author_user_ids_json, created_by) "
            "VALUES (%s,%s,1,0,'1.0','pending','authored','Body text.',%s,%s)",
            (org_id, document_id, f"[{author_id}]", author_id),
        )
        db.commit()
        version_id = db.execute(
            "SELECT id FROM aria_policy_versions WHERE document_id=%s", (document_id,)
        ).fetchone()["id"]
        db.execute(
            "UPDATE aria_documents SET current_policy_version_id=%s WHERE id=%s",
            (version_id, document_id),
        )
        db.execute(
            "INSERT INTO aria_document_approvals (org_id, document_id, policy_version_id, "
            "round_number, approver_id, requested_by, status, request_id) "
            "VALUES (%s,%s,%s,1,%s,%s,'pending','seed-1')",
            (org_id, document_id, version_id, approver_id, author_id),
        )
        db.commit()
    finally:
        db.close()

    return {"doc_id": doc_id, "author_username": username}


def test_assigned_approver_sees_decision_controls(live_app, page, synthetic_tenant, pending_approval_doc):
    creds = synthetic_tenant["users"]["compliance_manager"]
    page.goto(f"{live_app}/login")
    page.fill("#username", creds["username"])
    page.fill("#password", creds["password"])
    page.click("#submitBtn")
    page.wait_for_load_state("networkidle")

    page.goto(f"{live_app}/aria/documents/{pending_approval_doc['doc_id']}/workbench")
    page.wait_for_selector("#wbApprovalBody button:has-text('Approve')", timeout=5000)
    assert page.locator("#wbApprovalBody button:has-text('Approve')").count() == 1
    assert page.locator("#wbApprovalBody button:has-text('Reject')").count() == 1


def test_requester_does_not_see_decision_controls(live_app, page, pending_approval_doc):
    page.goto(f"{live_app}/login")
    page.fill("#username", pending_approval_doc["author_username"])
    page.fill("#password", _PASSWORD)
    page.click("#submitBtn")
    page.wait_for_load_state("networkidle")
    assert "/login" not in page.url, f"login failed for {pending_approval_doc['author_username']!r}, still on {page.url}"

    page.goto(f"{live_app}/aria/documents/{pending_approval_doc['doc_id']}/workbench")
    # Wait for a positive, reliable "the page finished loading real data"
    # signal (the seeded pending version always appears in History
    # regardless of who's viewing) rather than waiting on the absence of
    # something, which wait_for_selector can't express directly.
    page.wait_for_selector("#wbHistoryCard .aria-version-row", timeout=5000)
    assert page.locator("#wbApprovalBody button:has-text('Approve')").count() == 0
    assert page.locator("#wbApprovalBody button:has-text('Reject')").count() == 0
