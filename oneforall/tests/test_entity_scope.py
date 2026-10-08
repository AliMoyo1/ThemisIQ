"""Topbar search and Related Items show a record only to a user who could open it in its own module.

PLAN-37 Appendix A findings 1 and 2: both used to ignore the business unit and the module
capability, so a unit A user saw unit B titles (and could create a link to a record they cannot
open and read its title back). The rule under test: the same capability and the same business
unit rule as the owning module's own list and detail routes (a NULL unit is organization wide;
anything else must sit inside the caller's own subtree, so a parent unit sees its children and
a child does not see its parent).

The expectations below are written out by hand from core/rbac.py, deliberately not computed by
the code under test. Every "sees nothing" assertion has a positive twin (the same persona does
see its own rows), so an empty answer can never pass for isolation.
"""
import asyncio
import json
import types

import pytest

import core.middleware as middleware
import modules.launcher.routes_platform as plat
from core import rbac
from modules.governance.entity_scope import entity_scope_sql, may_view_kind

ORG = 1
UNIT_TAGS = ("org", "A", "A1", "B")  # "org" = organization wide (NULL unit)

# What each kind of unit sees: organization wide rows, plus its own subtree.
UNIT_VISIBLE = {
    None: {"org"},
    "A": {"org", "A", "A1"},
    "A1": {"org", "A1"},
    "B": {"org", "B"},
}

# persona -> (role, business unit)
PERSONAS = {
    "super": (rbac.SUPER_ADMIN, None),
    "dpo_a": (rbac.DPO, "A"),
    "dpo_a1": (rbac.DPO, "A1"),
    "dpo_b": (rbac.DPO, "B"),
    "dpo_no_unit": (rbac.DPO, None),
    "compliance_a": (rbac.COMPLIANCE_MGR, "A"),
    "employee_a": (rbac.EMPLOYEE, "A"),
}

SENTINEL = {("sentinel", "ropa"), ("sentinel", "breach"), ("sentinel", "dpia"),
            ("sentinel", "dsr"), ("sentinel", "vendor")}
FLAT = {("aria", "control"), ("sentinel", "vendor"), ("erm", "obligation"),
        ("orm", "kri"), ("platform", "risk")}  # no business unit column: gated by capability only
ALL_KINDS = SENTINEL | FLAT | {
    ("aria", "document"), ("evidence", "item"), ("grid", "audit"), ("grid", "nc"),
    ("bcm", "plan"), ("bcm", "incident"), ("erm", "risk"), ("orm", "event"),
}
# Written from core/rbac.py: the capability each owning module's list/detail route requires.
ALLOWED = {
    rbac.SUPER_ADMIN: ALL_KINDS,
    rbac.DPO: SENTINEL | {("grid", "audit"), ("erm", "risk"), ("erm", "obligation"), ("platform", "risk"),
                          ("aria", "control"), ("aria", "document"), ("evidence", "item")},
    rbac.COMPLIANCE_MGR: {("sentinel", "ropa"), ("grid", "audit"), ("bcm", "plan"), ("bcm", "incident"),
                          ("erm", "risk"), ("erm", "obligation"), ("platform", "risk"), ("orm", "event"),
                          ("orm", "kri"), ("aria", "control"), ("aria", "document"), ("evidence", "item")},
    rbac.EMPLOYEE: {("bcm", "plan"), ("bcm", "incident"), ("aria", "control"), ("aria", "document"),
                    ("evidence", "item")},
}

# kind -> (table, title column, builder(tag, unit_id) -> extra columns)
UNIT_KINDS = {
    ("aria", "document"): ("aria_documents", "title", lambda t, b: {
        "doc_id": f"DOC-{t}", "framework": "ISO 27001", "org_id": ORG, "business_unit_id": b,
        "policy_workflow_managed": 0}),
    ("evidence", "item"): ("evidence_items", "title", lambda t, b: {
        "org_id": ORG, "business_unit_id": b, "status": "current"}),
    ("sentinel", "ropa"): ("sentinel_ropa", "processing_name", lambda t, b: {
        "ref_number": f"RP-{t}", "business_unit_id": b}),
    ("sentinel", "breach"): ("sentinel_breaches", "title", lambda t, b: {
        "ref_number": f"BR-{t}", "business_unit_id": b}),
    ("sentinel", "dpia"): ("sentinel_dpias", "title", lambda t, b: {
        "ref_number": f"DP-{t}", "business_unit_id": b}),
    ("sentinel", "dsr"): ("sentinel_dsr", "requester_name", lambda t, b: {
        "ref_number": f"DS-{t}", "business_unit_id": b}),
    ("grid", "audit"): ("grid_audits", "name", lambda t, b: {"business_unit_id": b}),
    ("bcm", "plan"): ("bcm_plans", "title", lambda t, b: {"business_unit_id": b}),
    ("bcm", "incident"): ("bcm_incidents", "title", lambda t, b: {"business_unit_id": b}),
    ("erm", "risk"): ("erm_enterprise_risks", "title", lambda t, b: {"business_unit_id": b}),
    ("orm", "event"): ("orm_events", "title", lambda t, b: {"business_unit_id": b}),
}
FLAT_KINDS = {
    ("platform", "risk"): ("risk_register", "title", {}),
    ("sentinel", "vendor"): ("sentinel_vendors", "name", {}),
    ("erm", "obligation"): ("erm_regulatory_obligations", "regulation_name",
                            {"regulator": "Regulator", "obligation": "Obligation"}),
    ("orm", "kri"): ("orm_kris", "name", {}),
}

# What topbar search calls a kind: (module, type) in its results.
SEARCH_NAME = {key: key for key in ALL_KINDS}
SEARCH_NAME[("evidence", "item")] = ("platform", "evidence")
NOT_IN_SEARCH = {("grid", "nc"), ("bcm", "incident")}

LINKABLE = [
    ("erm", "risk"), ("orm", "event"), ("grid", "audit"), ("grid", "nc"), ("sentinel", "breach"),
    ("sentinel", "ropa"), ("sentinel", "dpia"), ("bcm", "plan"), ("bcm", "incident"),
    ("aria", "document"), ("evidence", "item"),
]


@pytest.fixture(autouse=True)
def signed_in(monkeypatch):
    async def current_user(request):
        return request.state.user

    monkeypatch.setattr(middleware, "get_current_user", current_user)


def _insert(db, table, **cols):
    cur = db.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        tuple(cols.values()),
    )
    db.commit()
    return cur.lastrowid


@pytest.fixture
def world(test_db):
    """One organization, units A, A1 (child of A) and B, and every kind seeded once per unit."""
    test_db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,'org','org')", (ORG,))
    test_db.commit()
    unit = {"org": None}
    unit["A"] = _insert(test_db, "business_units", name="Unit A", is_active=1)
    unit["A1"] = _insert(test_db, "business_units", name="Unit A1", is_active=1, parent_id=unit["A"])
    unit["B"] = _insert(test_db, "business_units", name="Unit B", is_active=1)

    rows = {}  # kind -> {tag: id}
    for key, (table, title_col, extra) in UNIT_KINDS.items():
        rows[key] = {
            tag: _insert(test_db, table, **{title_col: f"needle {key[1]} {tag}"}, **extra(tag, unit[tag]))
            for tag in UNIT_TAGS
        }
    rows[("grid", "nc")] = {
        tag: _insert(test_db, "grid_non_conformances", audit_id=rows[("grid", "audit")][tag],
                     title=f"needle nc {tag}")
        for tag in UNIT_TAGS
    }
    for key, (table, title_col, extra) in FLAT_KINDS.items():
        rows[key] = {"all": _insert(test_db, table, **{title_col: f"needle {key[1]}"}, **extra)}
    fw = _insert(test_db, "frameworks", name="Scope framework")
    rows[("aria", "control")] = {"all": _insert(test_db, "controls", framework_id=fw, ref="NEEDLE-1",
                                                name="needle control")}

    users = {}
    for i, (name, (role, tag)) in enumerate(PERSONAS.items(), start=1):
        users[name] = {
            "id": i, "username": name, "org_id": ORG, "business_unit_id": unit.get(tag) if tag else None,
            "is_super_admin": 1 if role == rbac.SUPER_ADMIN else 0, "roles": [role],
        }
        _insert(test_db, "users", id=i, username=name, email=f"{name}@example.test", full_name=name,
                password_hash="x", org_id=ORG, business_unit_id=users[name]["business_unit_id"])
    return types.SimpleNamespace(db=test_db, unit=unit, rows=rows, users=users)


def _tags_seen(name, key):
    """The tags of the rows of `key` this persona may see."""
    role, tag = PERSONAS[name]
    if key not in ALLOWED[role]:
        return set()
    if key in FLAT:
        return {"all"}
    if role == rbac.SUPER_ADMIN:
        return set(UNIT_TAGS)
    return UNIT_VISIBLE[tag]


def _visible_ids(world, name, key):
    return {world.rows[key][t] for t in _tags_seen(name, key)}


def _request(user, query=None, payload=None):
    request = types.SimpleNamespace(
        state=types.SimpleNamespace(user=user),
        url=types.SimpleNamespace(path="/api/search"),
        query_params=query or {},
    )
    if payload is not None:
        async def _json():
            return payload

        request.json = _json
    return request


def _call(coro):
    response = asyncio.run(coro)
    return response.status_code, json.loads(response.body)


# ── Topbar search ───────────────────────────────────────────────────────────

def _search(user, term):
    status, body = _call(plat.api_global_search(_request(user, {"q": term})))
    assert status == 200
    return body["results"]


@pytest.mark.parametrize("name", list(PERSONAS))
def test_search_returns_exactly_the_records_the_persona_may_open(world, name):
    """One query per kind: search stops at 30 results overall, which a super admin would exceed."""
    seen_any = False
    for key in sorted(ALL_KINDS - NOT_IN_SEARCH):
        module, kind = SEARCH_NAME[key]
        found = {r["id"] for r in _search(world.users[name], f"needle {key[1]}")
                 if (r["module"], r["type"]) == (module, kind)}
        assert found == _visible_ids(world, name, key), (name, key)
        seen_any = seen_any or bool(found)
    assert seen_any, "every persona can search at least the policy library"


def test_a_unit_b_breach_is_not_found_by_a_unit_a_dpo_but_is_found_by_unit_b(world):
    """The reproduced PLAN-37 case, spelled out."""
    breach_b = world.rows[("sentinel", "breach")]["B"]
    for name, expect in (("dpo_a", False), ("dpo_a1", False), ("dpo_no_unit", False), ("dpo_b", True)):
        _, body = _call(plat.api_global_search(_request(world.users[name], {"q": "needle breach"})))
        ids = {r["id"] for r in body["results"] if r["type"] == "breach"}
        assert (breach_b in ids) is expect, name
        assert ids, f"{name} must still find the breaches they may open"


# ── Related Items: reading ──────────────────────────────────────────────────

def _link(world, a, b):
    """Link row `a` to row `b`; each is (kind, tag)."""
    (ak, at), (bk, bt) = a, b
    _insert(world.db, "cross_module_links", source_module=ak[0], source_type=ak[1],
            source_id=world.rows[ak][at], target_module=bk[0], target_type=bk[1],
            target_id=world.rows[bk][bt], relationship="related")


@pytest.fixture
def linked(world):
    """Every organization wide row of a linkable kind is linked to every other linkable row."""
    for ak in LINKABLE:
        for bk in LINKABLE:
            for bt in UNIT_TAGS:
                if (ak, "org") != (bk, bt):
                    _link(world, (ak, "org"), (bk, bt))
    return world


@pytest.mark.parametrize("name", list(PERSONAS))
def test_related_items_list_only_records_the_viewer_may_open(linked, name):
    world, user = linked, linked.users[name]
    for ak in LINKABLE:
        anchor = world.rows[ak]["org"]
        status, body = _call(plat.api_links_get(_request(user), ak[0], ak[1], anchor))
        assert status == 200
        got = {(r["module"], r["entity_type"], r["entity_id"]) for r in body}

        if "org" not in _tags_seen(name, ak):
            assert got == set(), f"{name} cannot open the {ak} record, so nothing may be said about it"
            continue
        expected = {(bk[0], bk[1], i) for bk in LINKABLE for i in _visible_ids(world, name, bk)
                    if (bk, i) != (ak, anchor)}
        assert got == expected, (name, ak)
        assert all("needle" in r["title"] for r in body), "titles of visible records are still shown"


def test_related_items_do_not_even_mention_a_record_outside_the_viewers_unit(linked):
    user = linked.users["dpo_a"]
    anchor = linked.rows[("erm", "risk")]["org"]
    _, body = _call(plat.api_links_get(_request(user), "erm", "risk", anchor))
    raw = json.dumps(body)
    hidden = linked.rows[("sentinel", "breach")]["B"]
    assert not any(r["module"] == "sentinel" and r["entity_type"] == "breach" and r["entity_id"] == hidden
                   for r in body)
    assert "needle breach B" not in raw
    assert any(r["entity_type"] == "breach" for r in body), "unit A and organization wide breaches remain"


def test_links_to_kinds_the_registry_cannot_check_are_not_listed(world):
    anchor = world.rows[("erm", "risk")]["org"]
    _insert(world.db, "cross_module_links", source_module="erm", source_type="risk", source_id=anchor,
            target_module="grid", target_type="control", target_id=1, relationship="related")
    _, body = _call(plat.api_links_get(_request(world.users["super"]), "erm", "risk", anchor))
    assert body == []


# ── Related Items: creating and removing ────────────────────────────────────

def _create(user, source, target):
    (sk, sid), (tk, tid) = source, target
    return _call(plat.api_links_create(_request(user, payload={
        "source_module": sk[0], "source_type": sk[1], "source_id": sid,
        "target_module": tk[0], "target_type": tk[1], "target_id": tid, "relationship": "related",
    })))


def _count_links(world):
    return world.db.execute("SELECT COUNT(*) FROM cross_module_links").fetchone()[0]


def test_a_record_the_caller_cannot_open_is_indistinguishable_from_one_that_does_not_exist(world):
    user = world.users["dpo_a"]
    source = (("erm", "risk"), world.rows[("erm", "risk")]["A"])
    hidden = (("sentinel", "breach"), world.rows[("sentinel", "breach")]["B"])
    missing = (("sentinel", "breach"), 987654)

    assert _create(user, source, hidden) == _create(user, source, missing)
    status, _ = _create(user, source, hidden)
    assert status == 404
    hidden_source = (("sentinel", "breach"), world.rows[("sentinel", "breach")]["B"])
    assert _create(user, hidden_source, source)[0] == 404
    assert _count_links(world) == 0


def test_a_caller_without_the_module_capability_cannot_link_its_records(world):
    employee = world.users["employee_a"]  # no ERM or Sentinel access
    risk = (("erm", "risk"), world.rows[("erm", "risk")]["org"])
    plan = (("bcm", "plan"), world.rows[("bcm", "plan")]["org"])
    assert _create(employee, risk, plan)[0] == 404
    assert _create(employee, plan, risk)[0] == 404
    assert _count_links(world) == 0


def test_visible_records_link_and_read_back_and_the_link_is_audited(world):
    user = world.users["dpo_a"]
    source = (("erm", "risk"), world.rows[("erm", "risk")]["A"])
    target = (("sentinel", "breach"), world.rows[("sentinel", "breach")]["A1"])

    status, body = _create(user, source, target)
    assert status == 201 and body["ok"]
    assert _create(user, source, target) == (200, {"ok": True, "link_id": body["link_id"]}), "duplicate"

    _, listed = _call(plat.api_links_get(_request(user), "erm", "risk", source[1]))
    assert [(r["entity_id"], r["title"]) for r in listed] == [(target[1], "needle breach A1")]

    audit = world.db.execute(
        "SELECT user_id, module, action, entity_type, entity_id, details FROM audit_log "
        "WHERE action = 'link_create'").fetchall()
    assert len(audit) == 1, "only the real creation is audited, not the duplicate"
    row = audit[0]
    assert (row["user_id"], row["module"], row["entity_type"], row["entity_id"]) == (
        user["id"], "platform", "cross_module_link", body["link_id"])
    assert f"erm/risk/{source[1]}" in row["details"] and f"sentinel/breach/{target[1]}" in row["details"]
    assert "needle" not in row["details"], "the audit trail records ids, never titles"


def test_unlinking_is_audited_and_still_limited_to_the_creator_or_an_admin(world):
    creator, other, admin = world.users["dpo_a"], world.users["compliance_a"], world.users["super"]
    source = (("erm", "risk"), world.rows[("erm", "risk")]["A"])
    target = (("sentinel", "ropa"), world.rows[("sentinel", "ropa")]["A"])
    _, made = _create(creator, source, target)

    status, _ = _call(plat.api_links_delete(_request(other), made["link_id"]))
    assert status == 403 and _count_links(world) == 1

    status, body = _call(plat.api_links_delete(_request(creator), made["link_id"]))
    assert (status, body) == (200, {"success": True}) and _count_links(world) == 0
    audit = world.db.execute(
        "SELECT user_id, module, entity_type, entity_id, details FROM audit_log WHERE action = 'link_delete'"
    ).fetchall()
    assert len(audit) == 1 and audit[0]["user_id"] == creator["id"]
    assert f"erm/risk/{source[1]}" in audit[0]["details"]

    _, made_again = _create(creator, source, target)
    assert _call(plat.api_links_delete(_request(admin), made_again["link_id"]))[0] == 200
    assert _call(plat.api_links_delete(_request(admin), 424242))[0] == 404


# ── The shared rule itself ──────────────────────────────────────────────────

def test_unknown_kinds_match_nothing_and_a_bad_alias_is_refused(world):
    admin = world.users["super"]
    assert entity_scope_sql(("platform", "evidence"), admin) == ("(1 = 0)", [])
    assert not may_view_kind(admin, ("grid", "control"))
    with pytest.raises(ValueError):
        entity_scope_sql(("sentinel", "ropa"), admin, "t; DROP TABLE users")


def test_a_user_with_no_roles_sees_nothing_anywhere(world):
    nobody = {**world.users["dpo_a"], "roles": []}
    for key in ALL_KINDS - {("evidence", "item")}:
        assert entity_scope_sql(key, nobody) == ("(1 = 0)", []), key


def test_a_module_the_organization_is_not_licensed_for_is_closed_even_to_its_roles(world):
    dpo = {**world.users["dpo_a"], "licensed_modules": ["aria"]}
    assert may_view_kind(dpo, ("aria", "document"))
    assert not may_view_kind(dpo, ("sentinel", "breach"))
    assert not may_view_kind(dpo, ("erm", "risk"))
