"""Evidence Vault module rule (plans/2026-11-vault-current-proof-policy-layout.md, 1a).

A file linked to a Privacy record or AI impact assessment the viewer may not open is hidden from them, unless they may
open another kind of record it is linked to or uploaded it. Links to other modules never hide a file.
"""
import asyncio
import json
import types

import pytest
from fastapi import HTTPException

import core.middleware as middleware
import modules.evidence.routes as ev
from modules.evidence.scope import evidence_scope_sql


@pytest.fixture
def auth(monkeypatch):
    state = {"user": None}

    async def fake_current_user(request):
        return state["user"]

    monkeypatch.setattr(middleware, "get_current_user", fake_current_user)
    return state


def _req(auth, user, **query):
    auth["user"] = user
    return types.SimpleNamespace(state=types.SimpleNamespace(user=user), url=types.SimpleNamespace(path="/x"),
                                 query_params=query)


def _get(coro):
    return json.loads(asyncio.run(coro).body)


def _item(db, title, org_id, uploaded_by=None):
    cur = db.execute("INSERT INTO evidence_items (title, org_id, status, uploaded_by) VALUES (%s,%s,'current',%s)",
                     (title, org_id, uploaded_by))
    db.commit()
    return cur.lastrowid


def _link(db, evidence_id, module, entity_type, entity_id=1, deleted=False):
    db.execute("INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, deleted_at) "
               "VALUES (%s,%s,%s,%s,%s)",
               (evidence_id, module, entity_type, entity_id, "2026-01-01 00:00:00" if deleted else None))
    db.commit()


@pytest.fixture
def world(test_db):
    db = test_db
    db.execute("INSERT INTO organizations (name, slug, plan, status) VALUES ('o','o','enterprise','active')")
    db.commit()
    org = db.execute("SELECT id FROM organizations WHERE slug='o'").fetchone()["id"]
    db.execute("INSERT INTO users (id, username, email, full_name, password_hash, org_id) "
               "VALUES (21,'u21','u21@example.com','Employee','x',%s)", (org,))
    db.commit()

    def user(uid, role):
        return {"id": uid, "username": f"u{uid}", "org_id": org, "business_unit_id": None, "is_super_admin": 0,
                "roles": [role]}

    people = types.SimpleNamespace(employee=user(21, "employee"), dpo=user(22, "dpo"),
                                   analyst=user(23, "privacy_analyst"), auditor=user(24, "auditor"))
    ids = {
        "plain": _item(db, "Unlinked policy scan", org),
        "control": _item(db, "Access review", org),
        "breach": _item(db, "Breach forensic export", org),
        "breach_and_control": _item(db, "Breach lessons learned", org),
        "removed_breach": _item(db, "Formerly breach evidence", org),
        "own_breach": _item(db, "My breach note", org, uploaded_by=21),
        "dpia": _item(db, "DPIA interview notes", org),
        "aiia": _item(db, "AI impact interview", org),
        "grid": _item(db, "Audit answer proof", org),
        "unknown": _item(db, "Odd legacy link", org),
    }
    _link(db, ids["control"], "aria", "control")
    _link(db, ids["breach"], "sentinel", "breach")
    _link(db, ids["breach_and_control"], "sentinel", "breach")
    _link(db, ids["breach_and_control"], "aria", "control")
    _link(db, ids["removed_breach"], "sentinel", "breach", deleted=True)
    _link(db, ids["own_breach"], "sentinel", "breach")
    _link(db, ids["dpia"], "sentinel", "dpia")
    _link(db, ids["aiia"], "sentinel", "aiia")
    _link(db, ids["grid"], "grid", "control")
    _link(db, ids["unknown"], "legacy", "thing")
    return types.SimpleNamespace(org=org, people=people, ids=ids)


def _visible(db, user):
    scope, params = evidence_scope_sql(user)
    return {r["title"] for r in db.execute(f"SELECT e.title FROM evidence_items e WHERE {scope}", params).fetchall()}


def test_an_employee_never_sees_files_linked_only_to_privacy_records(test_db, world):
    seen = _visible(test_db, world.people.employee)
    assert {"Breach forensic export", "DPIA interview notes", "AI impact interview"}.isdisjoint(seen)
    # Not restricted: no link, a removed link, a link they can open, their own upload, other modules, unknown kinds.
    assert {"Unlinked policy scan", "Access review", "Formerly breach evidence", "My breach note",
            "Breach lessons learned", "Audit answer proof", "Odd legacy link"} <= seen


def test_the_dpo_sees_privacy_files(test_db, world):
    seen = _visible(test_db, world.people.dpo)
    assert {"Breach forensic export", "DPIA interview notes"} <= seen


def test_privacy_access_alone_does_not_open_breach_files(test_db, world):
    """A privacy analyst holds Privacy access but not breach management, so breach-only files stay hidden."""
    both = _item(test_db, "Breach and processing record", world.org)
    _link(test_db, both, "sentinel", "breach")
    _link(test_db, both, "sentinel", "ropa")
    seen = _visible(test_db, world.people.analyst)
    assert "Breach forensic export" not in seen
    assert "Breach lessons learned" not in seen, "an analyst cannot open ARIA controls either"
    assert "Breach and processing record" in seen, "the processing record is one they may open"


def test_audit_answers_from_my_work_stay_visible_without_a_grid_licence(test_db, world):
    assert "Audit answer proof" in _visible(test_db, world.people.employee)


def test_list_item_and_download_follow_the_rule(test_db, world, auth):
    employee, dpo = world.people.employee, world.people.dpo
    titles = {i["title"] for i in _get(ev.api_evidence_list(_req(auth, employee)))["items"]}
    assert "Breach forensic export" not in titles and "Access review" in titles
    with pytest.raises(HTTPException) as refused:
        asyncio.run(ev.api_evidence_get(_req(auth, employee), world.ids["breach"]))
    assert refused.value.status_code == 404
    assert _get(ev.api_evidence_get(_req(auth, dpo), world.ids["breach"]))["title"] == "Breach forensic export"
    with pytest.raises(HTTPException) as no_file:
        asyncio.run(ev.api_evidence_download(_req(auth, employee), world.ids["breach"]))
    assert no_file.value.status_code == 404


def test_stats_match_the_list_under_the_rule(test_db, world, auth):
    for user in (world.people.employee, world.people.dpo, world.people.auditor):
        stats = _get(ev.api_evidence_stats(_req(auth, user)))
        listing = _get(ev.api_evidence_list(_req(auth, user)))
        assert stats["total"] == listing["total"], user["roles"]
