"""Evidence Vault read paths share one scope rule (design/evidence-vault/PHASE-1A.md, T2 to T5)."""
import asyncio
import json
import types
from datetime import date, timedelta

import pytest

import core.middleware as middleware
import modules.bcm.data_service as bcm_ds
import modules.evidence.routes as ev
import modules.grid.data_service as grid_ds
import modules.launcher.routes_platform as plat


@pytest.fixture
def auth(monkeypatch):
    state = {"user": None}

    async def fake_current_user(request):
        return state["user"]

    monkeypatch.setattr(middleware, "get_current_user", fake_current_user)
    return state


def _req(auth, user, **query):
    auth["user"] = user
    return types.SimpleNamespace(
        state=types.SimpleNamespace(user=user),
        url=types.SimpleNamespace(path="/x"),
        query_params=query,
    )


def _json_req(auth, user, payload):
    request = _req(auth, user)

    async def _json():
        return payload

    request.json = _json
    return request


def _get(coro):
    return json.loads(asyncio.run(coro).body)


def _org(db, slug):
    db.execute(
        "INSERT INTO organizations (name, slug, plan, status) VALUES (%s,%s,'enterprise','active')",
        (slug, slug),
    )
    db.commit()
    return db.execute("SELECT id FROM organizations WHERE slug=%s", (slug,)).fetchone()["id"]


def _bu(db, code):
    db.execute("INSERT INTO business_units (name, code, is_active) VALUES (%s,%s,1)", (code, code))
    db.commit()
    return db.execute("SELECT id FROM business_units WHERE code=%s", (code,)).fetchone()["id"]


def _item(db, title, org_id, bu_id=None, status="current", **cols):
    fields = {"title": title, "org_id": org_id, "business_unit_id": bu_id, "status": status, **cols}
    cur = db.execute(
        f"INSERT INTO evidence_items ({', '.join(fields)}) VALUES ({', '.join(['%s'] * len(fields))})",
        tuple(fields.values()),
    )
    db.commit()
    return cur.lastrowid


def _link(db, evidence_id, entity_id, deleted=False):
    db.execute(
        "INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, deleted_at) "
        "VALUES (%s,'aria','control',%s,%s)",
        (evidence_id, entity_id, "2026-01-01 00:00:00" if deleted else None),
    )
    db.commit()


def _titles(items):
    return {i["title"] for i in items}


def _all_pages(auth, user, **query):
    seen, page = [], 1
    while True:
        body = _get(ev.api_evidence_list(_req(auth, user, page=str(page), **query)))
        seen.extend(i["id"] for i in body["items"])
        if page >= body["pages"]:
            return seen, body
        page += 1


@pytest.fixture
def world(test_db):
    org1, org2 = _org(test_db, "o1"), _org(test_db, "o2")
    bu_a, bu_b = _bu(test_db, "A"), _bu(test_db, "B")
    ids = {
        "wide": _item(test_db, "Access Review wide", org1),
        "a": _item(test_db, "Access Review unit A", org1, bu_a),
        "b": _item(test_db, "Access Review unit B", org1, bu_b),
        "other_org": _item(test_db, "Access Review other org", org2),
    }
    test_db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, org_id) "
        "VALUES (5,'org1admin','org1admin@example.com','Org1 Admin','x',%s)",
        (org1,),
    )
    test_db.commit()
    def user(uid, org_id, bu_id, roles, super_admin=0):
        return {"id": uid, "username": f"user{uid}", "org_id": org_id, "business_unit_id": bu_id,
                "is_super_admin": super_admin, "roles": roles}

    users = types.SimpleNamespace(
        admin=user(1, None, None, ["super_admin"], super_admin=1),
        unit_a=user(2, org1, bu_a, ["compliance_mgr"]),
        no_unit=user(3, org1, None, ["compliance_mgr"]),
        no_org=user(4, None, None, ["compliance_mgr"]),
        org1_admin=user(5, org1, None, ["super_admin"]),
    )
    return types.SimpleNamespace(org1=org1, org2=org2, bu_a=bu_a, bu_b=bu_b, ids=ids, users=users)


WIDE_AND_A = {"Access Review wide", "Access Review unit A"}


def test_list_is_an_envelope_and_obeys_scope(world, auth):
    body = _get(ev.api_evidence_list(_req(auth, world.users.unit_a)))
    assert set(body) == {"items", "total", "page", "page_size", "pages"}
    assert _titles(body["items"]) == WIDE_AND_A
    assert (body["total"], body["page"], body["page_size"], body["pages"]) == (2, 1, 25, 1)


def test_super_admin_sees_every_organization(world, auth):
    body = _get(ev.api_evidence_list(_req(auth, world.users.admin)))
    assert body["total"] == 4


def test_pages_cover_every_item_exactly_once_when_timestamps_tie(test_db, world, auth):
    for i in range(60):
        _item(test_db, f"bulk {i:03d}", world.org1, updated_at="2026-01-01 00:00:00")
    ids, body = _all_pages(auth, world.users.no_unit)
    assert body["total"] == len(ids) == 61
    assert len(set(ids)) == 61
    tied = [i for i in ids if i not in world.ids.values()]
    assert tied == sorted(tied, reverse=True)


def test_every_item_is_reachable_beyond_row_200(test_db, world, auth):
    for i in range(230):
        _item(test_db, f"bulk {i:03d}", world.org1)
    ids, body = _all_pages(auth, world.users.no_unit)
    assert body["pages"] == 10
    assert len(ids) == len(set(ids)) == body["total"] == 231
    last = _get(ev.api_evidence_list(_req(auth, world.users.no_unit, page="10")))
    assert len(last["items"]) == 6


def test_page_size_is_limited_to_the_allowed_sizes(test_db, world, auth):
    for i in range(60):
        _item(test_db, f"bulk {i:03d}", world.org1)
    sizes = {}
    for raw in ("50", "25", "1000", "abc", "0", "-5", ""):
        body = _get(ev.api_evidence_list(_req(auth, world.users.no_unit, page_size=raw)))
        sizes[raw] = (body["page_size"], len(body["items"]))
    assert sizes == {"50": (50, 50), "25": (25, 25), "1000": (25, 25), "abc": (25, 25),
                     "0": (25, 25), "-5": (25, 25), "": (25, 25)}


def test_page_numbers_are_clamped(test_db, world, auth):
    for i in range(60):
        _item(test_db, f"bulk {i:03d}", world.org1)
    pages = {}
    for raw in ("99", "3", "0", "-3", "abc"):
        body = _get(ev.api_evidence_list(_req(auth, world.users.no_unit, page=raw)))
        pages[raw] = (body["page"], len(body["items"]))
    assert pages == {"99": (3, 11), "3": (3, 11), "0": (1, 25), "-3": (1, 25), "abc": (1, 25)}


def test_single_item_lookup_agrees_with_the_list(test_db, world, auth):
    for user in vars(world.users).values():
        listed, _ = _all_pages(auth, user)
        for name, eid in world.ids.items():
            allowed = ev._scoped_evidence_item(test_db, eid, user) is not None
            assert allowed == (eid in listed), (name, user["id"])


def test_stats_total_matches_the_default_list_total(test_db, world, auth):
    _item(test_db, "Old archived", world.org1, status="archived")
    _item(test_db, "Old superseded", world.org1, status="superseded")
    for user in (world.users.admin, world.users.unit_a, world.users.no_unit, world.users.no_org):
        stats = _get(ev.api_evidence_stats(_req(auth, user)))
        listing = _get(ev.api_evidence_list(_req(auth, user)))
        assert stats["total"] == listing["total"], user["id"]


def test_stats_recently_added_never_leaves_the_users_scope(world, auth):
    stats = _get(ev.api_evidence_stats(_req(auth, world.users.unit_a)))
    assert _titles(stats["recently_added"]) == WIDE_AND_A
    empty = _get(ev.api_evidence_stats(_req(auth, world.users.no_org)))
    assert empty["total"] == 0 and empty["recently_added"] == []


def test_a_removed_link_is_not_counted_anywhere(test_db, world, auth):
    unit_a = world.users.unit_a
    _link(test_db, world.ids["wide"], 11)
    _link(test_db, world.ids["a"], 11, deleted=True)
    auto = _item(test_db, "Auto evidence live", world.org1, tags="auto")
    gone = _item(test_db, "Auto evidence removed", world.org1, tags="auto")
    _link(test_db, auto, 12)
    _link(test_db, gone, 12, deleted=True)

    by_title = {i["title"]: i for i in _get(ev.api_evidence_list(_req(auth, unit_a)))["items"]}
    assert by_title["Access Review wide"]["link_count"] == 1
    assert by_title["Access Review unit A"]["link_count"] == 0

    unlinked = _get(ev.api_evidence_list(_req(auth, unit_a, view="unlinked")))["items"]
    assert "Access Review unit A" in _titles(unlinked) and "Access Review wide" not in _titles(unlinked)
    assert "Auto evidence removed" in _titles(unlinked) and "Auto evidence live" not in _titles(unlinked)

    in_module = _get(ev.api_evidence_list(_req(auth, unit_a, module="aria")))["items"]
    assert _titles(in_module) == {"Access Review wide", "Auto evidence live"}

    stats = _get(ev.api_evidence_stats(_req(auth, unit_a)))
    assert stats["total_links"] == 2 and stats["by_module"] == {"aria": 2}
    assert stats["unlinked"] == 2

    panel = _get(ev.api_evidence_for_entity(_req(auth, unit_a, module="aria", entity_type="control", entity_id="11")))
    assert _titles(panel) == {"Access Review wide"}
    auto_panel = _get(ev.api_auto_evidence(_req(auth, unit_a), "aria", "control", 12))
    assert _titles(auto_panel["items"]) == {"Auto evidence live"}


def test_entity_panels_respect_business_unit_scope(test_db, world, auth):
    for key in ("wide", "a", "b", "other_org"):
        _link(test_db, world.ids[key], 21)
    query = dict(module="aria", entity_type="control", entity_id="21")
    panel = _get(ev.api_evidence_for_entity(_req(auth, world.users.unit_a, **query)))
    assert _titles(panel) == WIDE_AND_A
    nobody = _get(ev.api_evidence_for_entity(_req(auth, world.users.no_org, **query)))
    assert nobody == []


def test_linked_endpoint_rejects_a_non_integer_entity_id(world, auth):
    response = asyncio.run(ev.api_evidence_for_entity(
        _req(auth, world.users.unit_a, module="aria", entity_type="control", entity_id="abc")))
    assert response.status_code == 400


def test_default_views_hide_superseded_and_explicit_views_show_it(test_db, world, auth):
    _item(test_db, "Policy v1", world.org1, status="superseded")
    _item(test_db, "Policy v2", world.org1)
    _item(test_db, "Retired policy", world.org1, status="archived")
    user = world.users.no_unit

    default = _titles(_get(ev.api_evidence_list(_req(auth, user)))["items"])
    assert "Policy v2" in default and "Policy v1" not in default and "Retired policy" not in default
    assert _titles(_get(ev.api_evidence_list(_req(auth, user, view="superseded")))["items"]) == {"Policy v1"}
    assert _titles(_get(ev.api_evidence_list(_req(auth, user, status="superseded")))["items"]) == {"Policy v1"}
    assert _titles(_get(ev.api_evidence_list(_req(auth, user, view="archived")))["items"]) == {"Retired policy"}
    assert "Policy v1" not in _titles(_get(ev.api_evidence_list(_req(auth, user, view="unlinked")))["items"])


def test_expiring_view_lists_only_current_items_inside_the_window(test_db, world, auth):
    soon = (date.today() + timedelta(days=10)).isoformat()
    later = (date.today() + timedelta(days=90)).isoformat()
    _item(test_db, "Expires soon", world.org1, expiry_date=soon)
    _item(test_db, "Expires soon but superseded", world.org1, status="superseded", expiry_date=soon)
    _item(test_db, "Expires later", world.org1, expiry_date=later)
    body = _get(ev.api_evidence_list(_req(auth, world.users.no_unit, view="expiring")))
    assert _titles(body["items"]) == {"Expires soon"}


def test_list_search_ignores_case_and_treats_wildcards_literally(test_db, world, auth):
    _item(test_db, "100% complete", world.org1)
    _item(test_db, "a_b", world.org1)
    _item(test_db, "axb", world.org1)
    user = world.users.no_unit

    def found(term):
        return _titles(_get(ev.api_evidence_list(_req(auth, user, q=term)))["items"])

    assert found("ACCESS review WIDE") == {"Access Review wide"}
    assert found("%") == {"100% complete"}
    assert found("a_b") == {"a_b"}


def test_coverage_runs_for_every_kind_of_user(world, auth):
    for user in vars(world.users).values():
        assert isinstance(_get(ev.api_evidence_coverage(_req(auth, user))), dict)


def test_topbar_search_uses_the_vault_scope_and_hides_archived_and_superseded(test_db, world, auth):
    _item(test_db, "Access Review archived", world.org1, status="archived")
    _item(test_db, "Access Review superseded", world.org1, status="superseded")

    def evidence_hits(user, term):
        results = _get(plat.api_global_search(_req(auth, user, q=term)))["results"]
        return {r["title"] for r in results if r["type"] == "evidence"}

    assert evidence_hits(world.users.unit_a, "ACCESS review") == WIDE_AND_A
    assert evidence_hits(world.users.no_org, "access review") == set()
    assert len(evidence_hits(world.users.admin, "access review")) == 4


def test_grid_picker_and_matcher_use_the_vault_scope(test_db, world):
    unit_a = world.users.unit_a
    _link(test_db, world.ids["wide"], 31)
    _link(test_db, world.ids["a"], 31, deleted=True)

    listed = grid_ds.list_vault_evidence(unit_a)
    assert _titles(listed) == WIDE_AND_A
    assert {r["title"]: r["link_count"] for r in listed} == {"Access Review wide": 1, "Access Review unit A": 0}
    assert _titles(grid_ds.list_vault_evidence(unit_a, search="ACCESS REVIEW")) == WIDE_AND_A
    assert grid_ds.list_vault_evidence(world.users.no_org) == []

    matches = grid_ds.search_vault_for_evidence(unit_a, ["access review", "   ", "no such thing"])
    assert _titles(matches["access review"]) == WIDE_AND_A
    assert matches["   "] == [] and matches["no such thing"] == []


def test_bcm_picker_uses_the_vault_scope(test_db, world):
    assert _titles(bcm_ds.search_vault_items(world.users.unit_a, "ACCESS")) == WIDE_AND_A
    assert bcm_ds.search_vault_items(world.users.no_org, "access") == []
    assert len(bcm_ds.search_vault_items(world.users.admin, "")) == 4


def test_bulk_import_creates_evidence_owned_by_the_importers_org(test_db, world, auth):
    records = [{"title": "Imported policy", "category": "policy"}, {"title": "Imported report"}]
    result = _get(plat.api_bulk_import(_json_req(auth, world.users.org1_admin, {"records": records}), "evidence"))
    assert result["imported"] == 2
    rows = test_db.execute(
        "SELECT title, org_id, uploaded_by FROM evidence_items WHERE title LIKE 'Imported%'"
    ).fetchall()
    assert {(r["org_id"], r["uploaded_by"]) for r in rows} == {(world.org1, 5)}
    seen = _get(ev.api_evidence_list(_req(auth, world.users.no_unit, q="imported")))
    assert seen["total"] == 2
    assert _get(ev.api_evidence_list(_req(auth, {**world.users.no_unit, "org_id": world.org2}, q="imported")))["total"] == 0


def test_bulk_import_failure_returns_a_clean_error_and_inserts_nothing(test_db, world, auth):
    # An importer id with no users row violates the uploaded_by foreign key.
    user = {**world.users.org1_admin, "id": 999}
    records = [{"title": "Imported one"}, {"title": "Imported two"}]
    response = asyncio.run(plat.api_bulk_import(_json_req(auth, user, {"records": records}), "evidence"))
    assert response.status_code == 500
    assert json.loads(response.body) == {"error": "Import failed", "imported": 0}
    assert test_db.execute("SELECT COUNT(*) FROM evidence_items WHERE title LIKE 'Imported%'").fetchone()[0] == 0


def test_bulk_import_refuses_a_user_without_an_organization(test_db, world, auth):
    user = {**world.users.no_org, "roles": ["super_admin"]}
    response = asyncio.run(plat.api_bulk_import(_json_req(auth, user, {"records": [{"title": "x"}]}), "evidence"))
    assert response.status_code == 403
    assert test_db.execute("SELECT COUNT(*) FROM evidence_items WHERE title = 'x'").fetchone()[0] == 0
