"""
PLAN-35 T08: legacy bypass closure tests.

Covers: add_document can no longer create an already-Approved document,
_can_approve_policy no longer has a platform.manage_users self-approval
override, update_document refuses content-field changes on a managed
document (but still works normally on a legacy/unmanaged one, and still
allows cosmetic fields when nothing is pending), upload_document_revision
and apply_template_to_document refuse outright on a managed document,
download_document enforces org/BU scope where it previously had none, and
Ask ARIA's scope filter keeps an out-of-scope document's content out of
what gets sent to the AI.

Route functions under test are `async def`, and this project has no
pytest-asyncio (or similar) installed or configured -- confirmed directly
by running with @pytest.mark.asyncio first, which failed with "async def
functions are not natively supported". Rather than add a new test
dependency for this one file, each async call is driven through
asyncio.run() from an ordinary sync test, which needs nothing beyond the
standard library.

Every route under test is wrapped by require_module/require_capability
(core/middleware.py), which does its own cookie-based re-authentication
via get_current_user(request) -- confirmed directly by a first run that
failed with "'_FakeRequest' object has no attribute 'cookies'", since a
plain object with just .state.user set (which is all the route bodies
themselves read) isn't enough to satisfy the decorator wrapping them.
Rather than construct real session cookies, get_current_user is
monkeypatched to return the test's chosen actor directly.
"""
import asyncio
import io
import json
import types

import pytest
from fastapi import UploadFile

import core.middleware as middleware
import modules.aria.routes as routes
from database import insert_returning_id
from modules.aria import ask_service


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _mock_auth(monkeypatch):
    """Patches the one function every @require_module/@require_capability
    route calls to authenticate, so a bare request object (no real cookies
    or session) can drive these routes directly. _request_as(actor) sets
    which user the next call resolves to."""
    state = {"actor": None}

    async def fake_get_current_user(request):
        return state["actor"]

    monkeypatch.setattr(middleware, "get_current_user", fake_get_current_user)
    return state


def _request_as(auth_state, actor):
    auth_state["actor"] = actor
    return types.SimpleNamespace(state=types.SimpleNamespace(user=actor),
                                  url=types.SimpleNamespace(path="/aria/test"))


def _org(db, org_id=1):
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
               (org_id, f"org{org_id}", f"org{org_id}"))


def _bu(db, bu_id, name, parent_id=None):
    db.execute("INSERT INTO business_units (id, name, parent_id, is_active) VALUES (%s,%s,%s,1)",
               (bu_id, name, parent_id))


def _user(db, uid, org_id=1, bu_id=None, username=None):
    username = username or f"user{uid}"
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, org_id, business_unit_id) "
        "VALUES (%s,%s,%s,%s,'x',%s,%s)",
        (uid, username, f"{username}@x.com", username, org_id, bu_id),
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


def _fake_upload(filename: str, content: bytes) -> UploadFile:
    return UploadFile(filename=filename, file=io.BytesIO(content))


@pytest.fixture
def two_orgs(test_db):
    _org(test_db, 1)
    _org(test_db, 2)
    _bu(test_db, 100, "Finance")
    _bu(test_db, 200, "OtherOrgBU")
    _user(test_db, 1, org_id=1, bu_id=100, username="author")
    _user(test_db, 2, org_id=2, bu_id=200, username="outsider")
    _role(test_db, 1, "policy_author")
    _role(test_db, 1, "compliance_manager")
    _role(test_db, 2, "compliance_manager")
    test_db.commit()
    return {"author": _actor(test_db, 1), "outsider": _actor(test_db, 2)}


def _make_document(db, doc_id="DOC-0099", org_id=1, bu_id=100, managed=1,
                    owner_user_id=None, status="Approved"):
    db.execute(
        "INSERT INTO aria_documents (doc_id, framework, control_ref, title, version, "
        "status, body, org_id, business_unit_id, owner_user_id, policy_workflow_managed, owner) "
        "VALUES (%s,'ISO 27001','A.1','Title','1.0',%s,'body',%s,%s,%s,%s,'author')",
        (doc_id, status, org_id, bu_id, owner_user_id, managed),
    )
    db.commit()
    return db.execute("SELECT id FROM aria_documents WHERE doc_id=%s", (doc_id,)).fetchone()["id"]


def _make_template(db, name="Tpl", org_id=1, is_active=1):
    tid = insert_returning_id(db,
        "INSERT INTO aria_doc_templates (name, file_path, file_name, org_id, is_active) "
        "VALUES (%s,%s,%s,%s,%s)",
        (name, f"{name}.docx", f"{name}.docx", org_id, is_active),
    )
    db.commit()
    return tid


def test_documents_page_binds_ai_generated_pattern_for_empty_library(
        test_db, two_orgs, _mock_auth, monkeypatch):
    """The PostgreSQL driver treats literal percent signs as placeholders
    whenever parameters are supplied. Keep the Library's AI-generated count
    pattern bound as data so an empty production library renders instead of
    raising ``IndexError: list index out of range`` in psycopg2.
    """
    test_db.execute("DELETE FROM aria_documents")
    test_db.commit()

    class RecordingDb:
        def __init__(self, delegate):
            self.delegate = delegate
            self.ai_query = None

        def execute(self, sql, params=None):
            if "comments LIKE" in sql:
                self.ai_query = (sql, list(params or []))
            return self.delegate.execute(sql, params)

        def close(self):
            pass

    recording_db = RecordingDb(test_db)
    monkeypatch.setattr(routes, "get_db", lambda: recording_db)
    monkeypatch.setattr(
        routes,
        "_aria_render",
        lambda request, template, context, active_section=None: context,
    )

    request = _request_as(_mock_auth, two_orgs["author"])
    result = _run(routes.documents_page(request))

    assert recording_db.ai_query is not None
    query, params = recording_db.ai_query
    assert query.endswith("AND comments LIKE %s")
    assert params[-1] == "%AI Generated%"
    assert result["stats"]["ai_gen"] == 0


# ─────────────────────────────────────────────────────────────────────────
# add_document: no more direct-to-Approved creation
# ─────────────────────────────────────────────────────────────────────────

def test_add_document_always_creates_draft_even_when_approved_requested(test_db, two_orgs, _mock_auth):
    request = _request_as(_mock_auth, two_orgs["author"])
    result = _run(routes.add_document(
        request, framework="ISO 27001", control_ref="A.1", title="New Policy",
        doc_type="Policy", version="1.0", status="Approved",  # attempted bypass
        owner="", approver="", effective_date="", review_date="", location="", comments="",
    ))
    doc_id = json.loads(result.body.decode())["doc_id"]
    doc = test_db.execute("SELECT status FROM aria_documents WHERE doc_id=%s", (doc_id,)).fetchone()
    assert doc["status"] == "Draft"


def test_upload_new_document_always_creates_draft_and_scopes_to_creator(test_db, two_orgs, _mock_auth):
    # This call alone proves the SUBSTRING(doc_id FROM 5) fix: that syntax
    # is PostgreSQL-only and raised sqlite3.OperationalError on every call
    # against the real SQLite test database before reserve_document_number
    # replaced it.
    request = _request_as(_mock_auth, two_orgs["author"])
    result = _run(routes.upload_new_document(
        request, file=None, framework="ISO 27001", control_ref="A.1",
        title="Uploaded Policy", doc_type="Policy", version="1.0",
        status="Approved",  # attempted bypass, like add_document's equivalent test
        owner="", approver="", effective_date="", review_date="",
        location="", comments="",
    ))
    doc_id = json.loads(result.body.decode())["doc_id"]
    doc = test_db.execute(
        "SELECT status, org_id, business_unit_id, owner_user_id "
        "FROM aria_documents WHERE doc_id=%s", (doc_id,)
    ).fetchone()
    assert doc["status"] == "Draft"
    assert doc["org_id"] == two_orgs["author"]["org_id"]
    assert doc["business_unit_id"] == two_orgs["author"]["business_unit_id"]
    assert doc["owner_user_id"] == two_orgs["author"]["id"]


# ─────────────────────────────────────────────────────────────────────────
# delete_document: scope enforcement and managed-document guard
# ─────────────────────────────────────────────────────────────────────────

def test_delete_document_enforces_org_scope(test_db, two_orgs, _mock_auth):
    _make_document(test_db, owner_user_id=two_orgs["author"]["id"], managed=0, org_id=1, bu_id=100)
    request = _request_as(_mock_auth, two_orgs["outsider"])
    result = _run(routes.delete_document(request, "DOC-0099"))
    assert result.status_code == 404
    still_there = test_db.execute("SELECT id FROM aria_documents WHERE doc_id='DOC-0099'").fetchone()
    assert still_there is not None


def test_delete_document_refuses_a_managed_document(test_db, two_orgs, _mock_auth):
    _make_document(test_db, owner_user_id=two_orgs["author"]["id"], managed=1)
    request = _request_as(_mock_auth, two_orgs["author"])
    result = _run(routes.delete_document(request, "DOC-0099"))
    assert result.status_code == 409
    still_there = test_db.execute("SELECT id FROM aria_documents WHERE doc_id='DOC-0099'").fetchone()
    assert still_there is not None


def test_delete_document_still_works_on_a_legacy_document_in_scope(test_db, two_orgs, _mock_auth):
    _make_document(test_db, owner_user_id=two_orgs["author"]["id"], managed=0, org_id=1, bu_id=100)
    request = _request_as(_mock_auth, two_orgs["author"])
    result = _run(routes.delete_document(request, "DOC-0099"))
    assert result.status_code == 200
    gone = test_db.execute("SELECT id FROM aria_documents WHERE doc_id='DOC-0099'").fetchone()
    assert gone is None


# ─────────────────────────────────────────────────────────────────────────
# _can_approve_policy: no admin self-approval override
# ─────────────────────────────────────────────────────────────────────────

def test_can_approve_policy_has_no_admin_override_for_self_approval(test_db):
    from core.rbac import has_capability
    admin = {"id": 1, "username": "admin1", "full_name": "Admin One", "roles": ["super_admin"]}
    # Precondition for this test to mean anything: super_admin must actually
    # hold aria.policy.approve, otherwise the self-approval check below
    # would trivially return False for the wrong reason.
    assert has_capability(admin, "aria.policy.approve") is True
    doc_owned_by_admin = {"owner": "Admin One"}
    assert routes._can_approve_policy(admin, doc_owned_by_admin) is False, \
        "no override, not even for a role that also holds platform.manage_users, per section 5.1"


# ─────────────────────────────────────────────────────────────────────────
# update_document: managed vs legacy behavior
# ─────────────────────────────────────────────────────────────────────────

def test_update_document_refuses_content_fields_on_a_managed_document(test_db, two_orgs, _mock_auth):
    doc_id_pk = _make_document(test_db, owner_user_id=two_orgs["author"]["id"], managed=1)
    request = _request_as(_mock_auth, two_orgs["author"])
    result = _run(routes.update_document(
        request, "DOC-0099", status="Draft", version=None, owner=None, approver=None,
        title=None, effective_date=None, review_date=None, location=None, comments=None, control_ref=None,
    ))
    assert result.status_code == 409
    doc = test_db.execute("SELECT status FROM aria_documents WHERE id=%s", (doc_id_pk,)).fetchone()
    assert doc["status"] == "Approved", "the attempted status change must not have applied"


def test_update_document_allows_cosmetic_fields_on_a_managed_document_when_nothing_pending(test_db, two_orgs, _mock_auth):
    _make_document(test_db, owner_user_id=two_orgs["author"]["id"], managed=1)
    request = _request_as(_mock_auth, two_orgs["author"])
    result = _run(routes.update_document(
        request, "DOC-0099", title="Renamed Title", status=None, version=None, owner=None,
        approver=None, effective_date=None, review_date=None, location=None, comments=None, control_ref=None,
    ))
    assert result.status_code == 200
    doc = test_db.execute("SELECT title FROM aria_documents WHERE doc_id='DOC-0099'").fetchone()
    assert doc["title"] == "Renamed Title"


def test_update_document_refuses_even_cosmetic_fields_while_a_decision_is_pending(test_db, two_orgs, _mock_auth):
    doc_pk = _make_document(test_db, owner_user_id=two_orgs["author"]["id"], managed=1, status="Under Review")
    test_db.execute(
        "INSERT INTO aria_policy_versions (org_id, document_id, version_major, version_minor, "
        "version, state, origin, body, created_by) "
        "VALUES (1,%s,1,0,'1.0','pending','authored','body',%s)",
        (doc_pk, two_orgs["author"]["id"]),
    )
    version_id = test_db.execute("SELECT id FROM aria_policy_versions WHERE document_id=%s", (doc_pk,)).fetchone()["id"]
    test_db.execute(
        "INSERT INTO aria_document_approvals (org_id, document_id, policy_version_id, round_number, "
        "approver_id, requested_by, status, request_id) VALUES (1,%s,%s,1,%s,%s,'pending','req-1')",
        (doc_pk, version_id, two_orgs["author"]["id"], two_orgs["author"]["id"]),
    )
    test_db.commit()

    request = _request_as(_mock_auth, two_orgs["author"])
    result = _run(routes.update_document(
        request, "DOC-0099", title="Renamed While Pending", status=None, version=None, owner=None,
        approver=None, effective_date=None, review_date=None, location=None, comments=None, control_ref=None,
    ))
    assert result.status_code == 409


def test_update_document_still_works_normally_on_a_legacy_unmanaged_document(test_db, two_orgs, _mock_auth):
    # Deliberately not testing a transition to "Approved" here: the owner
    # and actor are the same user ("author" == doc's free-text owner), so
    # that would instead exercise the separate, correct self-approval
    # guard (elif status == "Approved" in update_document) rather than the
    # managed-document guard this test isolates.
    _make_document(test_db, owner_user_id=two_orgs["author"]["id"], managed=0, status="Draft")
    request = _request_as(_mock_auth, two_orgs["author"])
    result = _run(routes.update_document(
        request, "DOC-0099", status="Archived", version=None, owner=None, approver=None,
        title=None, effective_date=None, review_date=None, location=None, comments=None, control_ref=None,
    ))
    assert result.status_code == 200
    doc = test_db.execute("SELECT status FROM aria_documents WHERE doc_id='DOC-0099'").fetchone()
    assert doc["status"] == "Archived", "legacy documents are unaffected by the managed-document guard"


def test_update_document_enforces_org_scope(test_db, two_orgs, _mock_auth):
    _make_document(test_db, owner_user_id=two_orgs["author"]["id"], managed=0, org_id=1, bu_id=100)
    request = _request_as(_mock_auth, two_orgs["outsider"])  # org 2, unrelated to org 1's document
    result = _run(routes.update_document(
        request, "DOC-0099", title="Hijacked", status=None, version=None, owner=None, approver=None,
        effective_date=None, review_date=None, location=None, comments=None, control_ref=None,
    ))
    assert result.status_code == 404


# ─────────────────────────────────────────────────────────────────────────
# upload_document_revision / apply_template_to_document: managed refusal
# ─────────────────────────────────────────────────────────────────────────

def test_upload_document_revision_refuses_on_a_managed_document(test_db, two_orgs, _mock_auth):
    _make_document(test_db, owner_user_id=two_orgs["author"]["id"], managed=1)
    request = _request_as(_mock_auth, two_orgs["author"])
    upload = _fake_upload("revised.docx", b"fake docx bytes")
    result = _run(routes.upload_document_revision(request, "DOC-0099", file=upload, notes=""))
    assert result.status_code == 409


def test_apply_template_to_document_refuses_on_a_managed_document(test_db, two_orgs, _mock_auth):
    _make_document(test_db, owner_user_id=two_orgs["author"]["id"], managed=1)
    request = _request_as(_mock_auth, two_orgs["author"])
    result = _run(routes.apply_template_to_document(request, "DOC-0099", template_id=1))
    assert result.status_code == 409


def test_apply_template_to_document_refuses_an_out_of_scope_template(test_db, two_orgs, _mock_auth):
    _make_document(test_db, owner_user_id=two_orgs["author"]["id"], managed=0)
    test_db.execute("UPDATE aria_documents SET file_path='doc.docx' WHERE doc_id='DOC-0099'")
    test_db.commit()
    other_org_tpl = _make_template(test_db, name="OtherOrgTpl", org_id=2)
    request = _request_as(_mock_auth, two_orgs["author"])
    result = _run(routes.apply_template_to_document(request, "DOC-0099", template_id=other_org_tpl))
    assert result.status_code == 404


# ─────────────────────────────────────────────────────────────────────────
# Template management: scope enforcement and soft retirement
# ─────────────────────────────────────────────────────────────────────────

def test_templates_delete_enforces_org_scope(test_db, two_orgs, _mock_auth):
    tid = _make_template(test_db, org_id=1)
    request = _request_as(_mock_auth, two_orgs["outsider"])  # org 2
    result = _run(routes.api_templates_delete(request, tid))
    assert result.status_code == 404
    row = test_db.execute("SELECT is_active FROM aria_doc_templates WHERE id=%s", (tid,)).fetchone()
    assert row["is_active"] == 1, "an out-of-scope caller must not be able to retire this template"


def test_templates_delete_soft_retires_in_scope(test_db, two_orgs, _mock_auth):
    tid = _make_template(test_db, org_id=1)
    request = _request_as(_mock_auth, two_orgs["author"])
    result = _run(routes.api_templates_delete(request, tid))
    assert result.status_code == 200
    row = test_db.execute("SELECT is_active FROM aria_doc_templates WHERE id=%s", (tid,)).fetchone()
    assert row is not None, "soft retirement must keep the row (existing documents reference template_id)"
    assert row["is_active"] == 0


def test_templates_download_enforces_org_scope(test_db, two_orgs, _mock_auth):
    from fastapi import HTTPException
    tid = _make_template(test_db, org_id=1)
    request = _request_as(_mock_auth, two_orgs["outsider"])
    with pytest.raises(HTTPException) as exc_info:
        _run(routes.api_templates_download(request, tid))
    assert exc_info.value.status_code == 404


def test_templates_upload_scopes_to_creator(
    test_db, two_orgs, _mock_auth, tmp_path, monkeypatch
):
    monkeypatch.setattr(routes, "ARIA_TEMPLATE_DIR", tmp_path / "aria_templates")
    request = _request_as(_mock_auth, two_orgs["author"])
    upload = _fake_upload("brand.docx", b"fake docx bytes")
    result = _run(routes.api_templates_upload(
        request, file=upload, name="New Tpl", description="", doc_type="Policy", is_default="0",
    ))
    tid = json.loads(result.body.decode())["id"]
    row = test_db.execute(
        "SELECT org_id, business_unit_id FROM aria_doc_templates WHERE id=%s", (tid,)
    ).fetchone()
    assert row["org_id"] == two_orgs["author"]["org_id"]
    assert row["business_unit_id"] == two_orgs["author"]["business_unit_id"]


# ─────────────────────────────────────────────────────────────────────────
# download_document: scope enforcement where there was none
# ─────────────────────────────────────────────────────────────────────────

def test_download_document_enforces_scope(test_db, two_orgs, _mock_auth):
    from fastapi import HTTPException
    _make_document(test_db, owner_user_id=two_orgs["author"]["id"], managed=1, org_id=1, bu_id=100)
    request = _request_as(_mock_auth, two_orgs["outsider"])
    with pytest.raises(HTTPException) as exc_info:
        _run(routes.download_document(request, "DOC-0099"))
    assert exc_info.value.status_code == 404


# ─────────────────────────────────────────────────────────────────────────
# Ask ARIA: scope filtering on document chunks
# ─────────────────────────────────────────────────────────────────────────

def test_ask_scope_filter_excludes_out_of_scope_document_chunks(test_db, two_orgs):
    _make_document(test_db, doc_id="DOC-0001", org_id=1, bu_id=100, managed=1)
    _make_document(test_db, doc_id="DOC-0002", org_id=2, bu_id=200, managed=1)
    chunks = [
        {"content_type": "document", "content_id": "DOC-0001", "body": "in scope"},
        {"content_type": "document", "content_id": "DOC-0002", "body": "out of scope"},
        {"content_type": "control", "content_id": "5", "body": "control chunk, different model"},
    ]
    filtered = ask_service._filter_chunks_by_scope(chunks, two_orgs["author"])
    ids = {c["content_id"] for c in filtered}
    assert "DOC-0001" in ids
    assert "DOC-0002" not in ids
    assert "5" in ids, "non-document chunks pass through unfiltered (separate, pre-existing model)"


def test_ask_scope_filter_returns_nothing_for_no_actor():
    chunks = [{"content_type": "document", "content_id": "DOC-0001", "body": "x"}]
    assert ask_service._filter_chunks_by_scope(chunks, None) == []
