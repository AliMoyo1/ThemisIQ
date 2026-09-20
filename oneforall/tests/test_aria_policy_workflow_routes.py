"""
PLAN-35 T10: route-layer tests for routes_policy_workflow.py.

Every prior test for this workflow (T04-T09) calls policy_workflow_service
functions directly on one thread, never through the actual HTTP route
layer. That gap let a real, serious bug reach a live browser test
unnoticed: api_build_policy_draft opened its DB connection on the
request's event-loop thread, then handed that same connection into
asyncio.to_thread(...) -- which runs the call on a *different* thread.
SQLite connections are bound to the thread that created them, so this
raised `sqlite3.ProgrammingError: SQLite objects created in a thread can
only be used in that same thread` on every single build attempt. This
file exists specifically to drive that route through asyncio.to_thread
for real, the same way a live server does, using a real file-based
database (not the shared in-memory-style test_db connection) so a
regression here is caught by pytest again, not just by hand.
"""
import asyncio
import io
import types

import pytest
from docx import Document as DocxDocument

import database
import modules.aria.routes_policy_workflow as routes_wf
import core.middleware as middleware
from modules.aria import policy_workflow_service as svc
from modules.aria import policy_storage as storage
from modules.aria import policy_preview as preview


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _mock_auth(monkeypatch):
    state = {"actor": None}

    async def fake_get_current_user(request):
        return state["actor"]

    monkeypatch.setattr(middleware, "get_current_user", fake_get_current_user)
    return state


def _request_as(auth_state, actor):
    auth_state["actor"] = actor
    return types.SimpleNamespace(state=types.SimpleNamespace(user=actor),
                                  url=types.SimpleNamespace(path="/aria/test"))


def _fake_json(payload):
    """request.json() is awaited by _json_body -- this returns a plain
    function (not a coroutine itself) so calling request.json() produces a
    fresh coroutine each time, matching how a real Request behaves."""
    async def _inner():
        return payload
    return _inner


def _org(db, org_id=1):
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
               (org_id, f"org{org_id}", f"org{org_id}"))


def _bu(db, bu_id, name):
    db.execute("INSERT INTO business_units (id, name, is_active) VALUES (%s,%s,1)", (bu_id, name))


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


def _real_template_bytes() -> bytes:
    doc = DocxDocument()
    doc.add_paragraph("TEMPLATE COVER")
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


@pytest.fixture
def real_file_db(tmp_path, monkeypatch):
    """A genuine file-based database (not the standard test_db fixture's
    single shared connection) -- the whole point of this test is that a
    background thread opens its OWN connection to the SAME file, which
    only means something when there really is a file for it to open."""
    monkeypatch.setattr(database, "_DB_PATH", str(tmp_path / "route_thread_test.db"))
    database.init_db()

    root = tmp_path / "aria_uploads"
    monkeypatch.setattr(storage, "ARIA_UPLOAD_DIR", root)
    monkeypatch.setattr(storage, "WORKFLOW_ROOT", root / "policy_workflow")
    monkeypatch.setattr(preview, "submit_conversion_job", lambda b, timeout_seconds=None: "job")
    monkeypatch.setattr(preview, "poll_conversion_result",
                         lambda j, timeout_seconds=None, poll_interval=0.5: b"%PDF-X")
    monkeypatch.setattr(preview, "cleanup_job", lambda j: None)

    template_dir = root.parent / "aria_templates"
    template_dir.mkdir(parents=True, exist_ok=True)
    (template_dir / "t1.docx").write_bytes(_real_template_bytes())
    monkeypatch.setattr("modules.aria.routes.ARIA_TEMPLATE_DIR", template_dir)

    conn = database.get_db()
    try:
        yield conn
    finally:
        conn.close()


def test_build_route_does_not_raise_a_cross_thread_sqlite_error(real_file_db, _mock_auth):
    """Drives api_build_policy_draft exactly as a live server does --
    through asyncio.to_thread -- proving the connection is opened and used
    entirely within that worker thread, not handed in from the event-loop
    thread. Before the fix, this raised sqlite3.ProgrammingError on every
    call; it never surfaced in any prior test because every other test
    calls svc.build_draft(db, ...) directly, on a single thread."""
    db = real_file_db
    _org(db)
    _bu(db, 100, "Finance")
    _user(db, 1, bu_id=100, username="author")
    _role(db, 1, "policy_author")
    db.execute(
        "INSERT INTO aria_doc_templates (name, file_path, file_name, org_id, is_active) "
        "VALUES ('T1', 't1.docx', 't1.docx', 1, 1)"
    )
    db.commit()
    template_id = db.execute("SELECT id FROM aria_doc_templates WHERE file_path='t1.docx'").fetchone()["id"]

    author = _actor(db, 1)
    draft = svc.create_draft_from_generation(
        db, author, control={"id": 1, "ref": "A.1", "name": "Test", "framework_id": 1, "fw_name": "ISO 27001"},
        generated_content="# Policy", org_name="Test Org", doc_type="Policy", framework_label="ISO 27001",
        integrated_controls=None, request_id=None, target_business_unit_id=100,
    )
    db.commit()

    request = _request_as(_mock_auth, author)

    async def do_build():
        # api_build_policy_draft reads its JSON body via await request.json()
        request.json = _fake_json({"template_id": template_id, "expected_lock_version": draft["lock_version"]})
        return await routes_wf.api_build_policy_draft(request, draft["id"])

    response = _run(do_build())
    import json as _json
    body = _json.loads(response.body.decode())
    assert body.get("ok") is True, body
    assert body["draft"]["state"] == "ready"
    assert "preview_url" in body
