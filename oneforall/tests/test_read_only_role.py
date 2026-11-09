"""An external auditor reads and comments but files and changes nothing (owner, 2026-11-09).

Written out by hand, not computed by the code under test:

* every write an External Auditor sends is refused, whatever the route's own checks say, except their own sign-in and
  settings, reading through a form (the guide, Ask ARIA, the Vault's question search) and comments;
* they may comment on an audit control in their scope, and ask questions in an auditor room;
* someone who holds another role besides is not limited by this rule;
* every write route in the code passes through the decorators that apply it.
"""
import glob
import re

import pytest

import core.middleware as middleware
from core import rbac
from tests.test_platform_ownership import _insert, world  # noqa: F401

AUDITOR = {"id": 50, "roles": [rbac.EXTERNAL_AUDITOR], "is_super_admin": 0}


# ── The rule ────────────────────────────────────────────────────────────────

def test_only_a_person_whose_every_role_is_read_only_is_read_only():
    assert rbac.is_read_only(AUDITOR)
    assert not rbac.is_read_only({"roles": [rbac.EXTERNAL_AUDITOR, rbac.EMPLOYEE]})
    assert not rbac.is_read_only({"roles": [rbac.EMPLOYEE]})
    assert not rbac.is_read_only({"roles": []})
    assert not rbac.is_read_only(None)


@pytest.mark.parametrize("method, path", [
    ("GET", "/evidence/api/items/7"), ("HEAD", "/evidence/"),
    ("POST", "/logout"), ("POST", "/change-password"), ("POST", "/mfa/enable"),
    ("PUT", "/api/my-email-preferences"), ("POST", "/api/notifications/12/read"), ("POST", "/api/notifications/read-all"),
    ("POST", "/api/trainer/ask"), ("POST", "/aria/api/ask"), ("POST", "/evidence/api/find"),
    ("POST", "/governance/api/group/rooms/3/messages"), ("POST", "/grid/api/controls/9/comments"),
])
def test_what_a_read_only_person_may_send(method, path):
    assert rbac.read_only_may_send(method, path)


@pytest.mark.parametrize("method, path", [
    ("POST", "/evidence/api/items"), ("PUT", "/evidence/api/items/7"), ("POST", "/evidence/api/items/7/confidence-verify"),
    ("POST", "/evidence/api/items/7/links"), ("POST", "/evidence/api/batch/staged"),
    ("POST", "/aria/documents/add"), ("POST", "/aria/api/export-word"), ("POST", "/api/tasks"), ("POST", "/api/links"),
    ("POST", "/api/risks"), ("POST", "/grid/api/assignments/1/items/2/proof"),
    ("POST", "/governance/api/group/rooms"), ("POST", "/governance/api/group/rooms/3/close"),
    ("POST", "/grid/api/controls/9/comments/extra"), ("POST", "/grid/api/controls/x/comments"),
    ("DELETE", "/grid/api/controls/9/comments"), ("PATCH", "/api/my-email-preferences"),
])
def test_what_a_read_only_person_may_not_send(method, path):
    assert not rbac.read_only_may_send(method, path)


# ── Through the application ─────────────────────────────────────────────────

@pytest.fixture
def app_as(world, monkeypatch):
    from fastapi import FastAPI
    from starlette.testclient import TestClient
    from modules.aria.routes import router as aria_router
    from modules.evidence.routes import router as evidence_router
    from modules.grid.routes import router as grid_router

    unit_a = world.unit["A"]
    for uid, name, roles in ((50, "auditor_a", [rbac.EXTERNAL_AUDITOR]),
                             (51, "auditor_staff_a", [rbac.EXTERNAL_AUDITOR, rbac.EMPLOYEE])):
        world.users[name] = {"id": uid, "username": name, "org_id": 1, "business_unit_id": unit_a,
                             "is_super_admin": 0, "roles": roles}
        _insert(world.db, "users", id=uid, username=name, email=f"{name}@example.test", full_name=name,
                password_hash="x", org_id=1, business_unit_id=unit_a)
    world.item = _insert(world.db, "evidence_items", title="needle proof", status="current", org_id=1,
                         business_unit_id=unit_a)
    world.control = _insert(world.db, "grid_controls", audit_id=world.rec[("audit", "A")], name="Access review")
    who = {"name": "super"}

    async def current_user(request):
        return world.users[who["name"]]

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    for router in (aria_router, evidence_router, grid_router):
        app.include_router(router)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False)

    def call(method, path, name, **kwargs):
        who["name"] = name
        return getattr(client, method)(path, **kwargs)

    world.call = call
    return world


def _count(db, table, where="1 = 1"):
    return db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where}").fetchone()[0]


def test_an_external_auditor_files_and_changes_nothing_in_the_vault(app_as):
    w = app_as
    upload = w.call("post", "/evidence/api/items", "auditor_a", data={"title": "auditor file", "filing_scope": "org"},
                    files={"file": ("note.txt", b"proof", "text/plain")})
    assert upload.status_code == 403 and "read-only" in upload.json()["detail"], upload.text
    assert _count(w.db, "evidence_items", "title = 'auditor file'") == 0

    edit = w.call("put", f"/evidence/api/items/{w.item}", "auditor_a", json={"title": "changed"})
    assert edit.status_code == 403 and "read-only" in edit.json()["detail"]
    verify = w.call("post", f"/evidence/api/items/{w.item}/confidence-verify", "auditor_a",
                    json={"verification_method": "auditor_signed"})
    assert verify.status_code == 403 and "read-only" in verify.json()["detail"]
    row = w.db.execute("SELECT title, verification_method FROM evidence_items WHERE id = %s", (w.item,)).fetchone()
    assert tuple(row) == ("needle proof", None)

    shown = w.call("get", f"/evidence/api/items/{w.item}", "auditor_a")
    assert shown.status_code == 200 and shown.json()["can_change"] is False, "they still read it"
    assert w.call("get", f"/evidence/api/items/{w.item}", "employee_a").json()["can_change"] is True
    page = w.call("get", "/evidence/", "auditor_a")
    assert page.status_code == 200 and "+ Upload" not in page.text and "Batch upload" not in page.text


@pytest.mark.parametrize("path, form", [
    ("/aria/documents/add", {"title": "auditor policy", "framework": "ISO 27001"}),
    ("/aria/risks/add", {"framework": "ISO 27001", "description": "auditor risk"}),
])
def test_an_external_auditor_is_refused_by_the_rule_before_any_aria_write_runs(app_as, path, form):
    w = app_as
    before = (_count(w.db, "aria_documents"), _count(w.db, "aria_risks"))
    refused = w.call("post", path, "auditor_a", data=form)
    assert refused.status_code == 403 and "read-only" in refused.json()["detail"], refused.text
    assert (_count(w.db, "aria_documents"), _count(w.db, "aria_risks")) == before


def test_an_external_auditor_comments_on_an_audit_control_in_their_scope(app_as):
    w = app_as
    made = w.call("post", f"/grid/api/controls/{w.control}/comments", "auditor_a", json={"content": "Sample of 5 seen."})
    assert made.status_code == 201, made.text
    assert _count(w.db, "grid_control_comments", "content = 'Sample of 5 seen.'") == 1
    other = w.call("post", f"/grid/api/controls/{w.control}/comments", "owner_b", json={"content": "x"})
    assert other.status_code == 403, "a role without the comment capability is refused as before"


def test_a_person_with_another_role_besides_writes_as_that_role_allows(app_as):
    w = app_as
    edit = w.call("put", f"/evidence/api/items/{w.item}", "auditor_staff_a", json={"title": "renamed by staff"})
    assert edit.status_code == 200, edit.text


# ── Every write route passes through the rule ───────────────────────────────

# Writes that do not sign in through require_auth or require_capability, and why that is safe.
_OUTSIDE_THE_DECORATORS = {
    ("routes_auth.py", "/login"), ("routes_auth.py", "/mfa/verify"),  # signing in
    ("routes_api_v1.py", "/risks"), ("routes_api_v1.py", "/risks/{rid}"),  # API keys an administrator issues
}
_GUARDS = re.compile(r"@(require_auth|require_capability|_require_cap|require_module|require_super_admin)\b")


def test_every_write_route_signs_in_through_the_decorators_that_apply_the_rule():
    unguarded = []
    for path in glob.glob("modules/**/*.py", recursive=True) + glob.glob("core/*.py"):
        lines = open(path, encoding="utf-8").read().split("\n")
        for i, line in enumerate(lines):
            route = re.match(r'\s*@\w+\.(post|put|patch|delete)\("([^"]+)"', line)
            if not route:
                continue
            decorators = []
            for following in lines[i + 1:]:
                if not following.strip().startswith("@"):
                    break
                decorators.append(following.strip())
            name = path.replace("\\", "/").rsplit("/", 1)[-1]
            if not any(_GUARDS.match(d) for d in decorators) and (name, route.group(2)) not in _OUTSIDE_THE_DECORATORS:
                unguarded.append(f"{path}:{i + 1} {route.group(2)}")
    assert unguarded == []
