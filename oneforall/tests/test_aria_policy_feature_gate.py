"""
PLAN-35 T11: ARIA_POLICY_AUTHORING_ENABLED / ARIA_POLICY_AUTHORING_ORG_IDS
actually gate something.

The setting existed since T00's config work (with its own startup
validator) but nothing ever read it anywhere in the codebase -- confirmed
directly by grepping the whole tree during T11's release-verification
pass. That meant every one of section 15's rollout steps ("deploy with
the feature disabled... enable for a test tenant") was inert: the workflow
was always fully available to every organization regardless of the flag.

Gated at the two entry points that create new authoring work
(api_generate_policy in routes.py, api_start_revision_draft in
routes_policy_workflow.py) rather than inside the service functions they
call: this is a tenant-level feature-availability check, the same kind
require_capability's own licence check already makes at the route layer,
not an object-level authorization rule policy_access.py/policy_workflow_service.py
own. Confirmed directly that gating inside create_draft_from_generation
instead breaks nearly the entire existing test suite for this workflow
(all ~350 tests call it directly with no reason to know about a rollout
flag) before settling on the route-layer placement used here.
"""
import asyncio
import types

import pytest

import core.middleware as middleware
import modules.aria.routes as routes
import modules.aria.routes_policy_workflow as routes_wf
from modules.aria.policy_access import policy_authoring_enabled_for


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


def _org(db, org_id=1):
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
               (org_id, f"org{org_id}", f"org{org_id}"))


def _user(db, uid, org_id=1, username=None):
    username = username or f"user{uid}"
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, org_id) "
        "VALUES (%s,%s,%s,%s,'x',%s)",
        (uid, username, f"{username}@x.com", username, org_id),
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


# ─────────────────────────────────────────────────────────────────────────
# policy_authoring_enabled_for: the pure predicate
# ─────────────────────────────────────────────────────────────────────────

def test_disabled_flag_refuses_every_org(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", False)
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ORG_IDS", [1, 2, 3])
    assert policy_authoring_enabled_for(1) is False


def test_empty_allowlist_refuses_every_org_even_when_flag_is_on(monkeypatch):
    """config.py's own comment: an empty ARIA_POLICY_AUTHORING_ORG_IDS means
    no tenant is enabled, never a blanket default-on."""
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", True)
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ORG_IDS", [])
    assert policy_authoring_enabled_for(1) is False
    assert policy_authoring_enabled_for(999) is False


def test_org_on_the_allowlist_is_enabled(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", True)
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ORG_IDS", [1, 2])
    assert policy_authoring_enabled_for(1) is True
    assert policy_authoring_enabled_for(3) is False


def test_none_org_id_is_never_enabled(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", True)
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ORG_IDS", [1])
    assert policy_authoring_enabled_for(None) is False


# ─────────────────────────────────────────────────────────────────────────
# Route-level enforcement
# ─────────────────────────────────────────────────────────────────────────

def test_generate_policy_refuses_for_an_org_not_on_the_allowlist(test_db, monkeypatch, _mock_auth):
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", True)
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ORG_IDS", [999])  # not this actor's org

    _org(test_db, 1)
    _user(test_db, 1, org_id=1, username="author")
    _role(test_db, 1, "policy_author")
    test_db.commit()
    actor = _actor(test_db, 1)
    request = _request_as(_mock_auth, actor)

    result = _run(routes.api_generate_policy(
        request, control_id=1, org_name="Org", doc_type_override="",
        integrated_framework_id="", custom_instructions="", request_id="", target_business_unit_id="",
    ))
    assert result.status_code == 403
    import json
    body = json.loads(result.body.decode())
    assert "not yet enabled" in body["error"]


def test_generate_policy_refused_before_touching_ai_rate_limit(test_db, monkeypatch, _mock_auth):
    """The gate must fire before check_ai_rate_limit/record_ai_call --
    otherwise a disabled org's users could still burn through the shared
    AI rate-limit budget on a call that was always going to be refused."""
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", False)
    called = {"rate_limit_checked": False}
    monkeypatch.setattr(routes, "check_ai_rate_limit", lambda *a, **kw: called.__setitem__("rate_limit_checked", True) or True)

    _org(test_db, 1)
    _user(test_db, 1, org_id=1, username="author")
    _role(test_db, 1, "policy_author")
    test_db.commit()
    actor = _actor(test_db, 1)
    request = _request_as(_mock_auth, actor)

    result = _run(routes.api_generate_policy(
        request, control_id=1, org_name="Org", doc_type_override="",
        integrated_framework_id="", custom_instructions="", request_id="", target_business_unit_id="",
    ))
    assert result.status_code == 403
    assert called["rate_limit_checked"] is False


def test_start_revision_draft_refuses_for_an_org_not_on_the_allowlist(test_db, monkeypatch, _mock_auth):
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", True)
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ORG_IDS", [])  # empty: nobody enabled

    _org(test_db, 1)
    _user(test_db, 1, org_id=1, username="author")
    _role(test_db, 1, "policy_author")
    test_db.commit()
    actor = _actor(test_db, 1)
    request = _request_as(_mock_auth, actor)

    result = _run(routes_wf.api_start_revision_draft(request, "DOC-0001"))
    assert result.status_code == 403
    import json
    body = json.loads(result.body.decode())
    assert body["error"]["code"] == "ACTION_FORBIDDEN"


# ─────────────────────────────────────────────────────────────────────────
# T11 review finding: the gate only covered generate/start-revision, not
# build/confirm/submit/retry -- "existing drafts can still be built,
# confirmed, submitted for approval, and processed by the publication
# scheduler" despite the flag being off, contradicting section 15's
# rollback text ("disable new authoring/submission entry points... stop
# new conversion/publication claims"). All four route handlers place the
# gate before any database access at all, so a nonexistent id is enough to
# prove the refusal -- if the gate did not fire first, these would fail
# differently (e.g. a NOT_FOUND from the service layer), not with a 403.
# ─────────────────────────────────────────────────────────────────────────

def _disabled_actor(db, mock_auth):
    from config import settings
    _org(db, 1)
    _user(db, 1, org_id=1, username="author")
    _role(db, 1, "policy_author")
    db.commit()
    return _request_as(mock_auth, _actor(db, 1))


def test_build_policy_draft_refuses_when_disabled(test_db, monkeypatch, _mock_auth):
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", False)
    request = _disabled_actor(test_db, _mock_auth)
    result = _run(routes_wf.api_build_policy_draft(request, "nonexistent-draft-id"))
    assert result.status_code == 403


def test_confirm_policy_draft_refuses_when_disabled(test_db, monkeypatch, _mock_auth):
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", False)
    request = _disabled_actor(test_db, _mock_auth)
    result = _run(routes_wf.api_confirm_policy_draft(request, "nonexistent-draft-id"))
    assert result.status_code == 403


def test_submit_for_approval_refuses_when_disabled(test_db, monkeypatch, _mock_auth):
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", False)
    request = _disabled_actor(test_db, _mock_auth)
    result = _run(routes_wf.api_submit_for_approval(request, 999999))
    assert result.status_code == 403


def test_retry_publication_job_refuses_when_disabled(test_db, monkeypatch, _mock_auth):
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", False)
    request = _disabled_actor(test_db, _mock_auth)
    result = _run(routes_wf.api_retry_publication_job(request, 999999))
    assert result.status_code == 403


def test_build_policy_draft_passes_the_gate_when_enabled(test_db, monkeypatch, _mock_auth):
    """The gate must not fire for an enabled org -- proven by reaching some
    DIFFERENT, later failure (this fake request has no real JSON body or
    draft to act on, so the route fails downstream of the gate for
    unrelated reasons) instead of the gate's own ACTION_FORBIDDEN 403."""
    from config import settings
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ENABLED", True)
    monkeypatch.setattr(settings, "ARIA_POLICY_AUTHORING_ORG_IDS", [1])
    request = _disabled_actor(test_db, _mock_auth)
    result = _run(routes_wf.api_build_policy_draft(request, "nonexistent-draft-id"))
    assert result.status_code != 403
    import json
    body = json.loads(result.body.decode())
    assert body["error"]["code"] != "ACTION_FORBIDDEN"
