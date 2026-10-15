"""
Search says what each result is, finds AI uses and the Governance structure, and can search one case
(plans/2026-10-governance-rework/04 section 4, acceptance scenario 4).

Every fact a result carries is read through the same unit scope as the result itself, and the narrative of a privacy
record is never a snippet. Expectations are written by hand from the rows inserted; every "cannot find" has a positive
twin so an empty answer cannot pass for isolation.
"""
import json

import modules.launcher.routes_platform as plat
from modules.governance import entity360, relationships
from modules.launcher import search_service
from tests.test_platform_ownership import _call, _insert, _request, signed_in, world  # noqa: F401


def _search(user, q, **extra):
    return _call(plat.api_global_search(_request(user, {"q": q, **extra})))


def _link(db, source, target, status="confirmed", relationship="supports"):
    (sm, st, sid), (tm, tt, tid) = source, target
    return _insert(db, "cross_module_links", source_module=sm, source_type=st, source_id=sid, target_module=tm,
                   target_type=tt, target_id=tid, relationship=relationship, provenance="manual", status=status)


def test_a_result_carries_its_status_date_unit_and_a_permitted_snippet(world):
    db = world.db
    db.execute("UPDATE sentinel_breaches SET description = 'Secret narrative of the incident' WHERE id = %s",
               (world.rec[("breach", "A")],))
    db.commit()
    risk = _insert(db, "risk_register", title="needle supplier risk", description="Supplier continuity is not assured",
                   likelihood=3, impact=3, risk_level="medium", business_unit_id=world.unit["A"], source_module="sentinel")

    status, body = _search(world.users["dpo_a"], "needle breach")
    assert status == 200
    by_title = {r["title"]: r for r in body["results"] if r["type"] == "breach"}
    assert set(by_title) == {"needle breach A", "needle breach A1", "needle breach org"}
    assert by_title["needle breach A"]["status"] == "open"
    assert by_title["needle breach A"]["business_unit"] == "Unit A"
    assert by_title["needle breach A1"]["business_unit"] == "Unit A1"
    assert by_title["needle breach org"]["business_unit"] == "Whole organization"
    assert len(by_title["needle breach A"]["date"]) == 10
    assert all(r["snippet"] is None for r in by_title.values()), "a privacy narrative is never a snippet"
    assert "Secret narrative" not in json.dumps(body)

    _, found = _search(world.users["dpo_a"], "needle supplier")
    row = next(r for r in found["results"] if r["id"] == risk and r["type"] == "risk")
    assert row["snippet"] == "Supplier continuity is not assured" and row["status"] == "open"


def test_ai_uses_and_the_governance_structure_are_found_only_through_the_viewers_units(world):
    db, unit = world.db, world.unit
    use_a = _insert(db, "applications", name="needle copilot A", business_unit_id=unit["A"], is_active=1)
    use_b = _insert(db, "applications", name="needle copilot B", business_unit_id=unit["B"], is_active=1)
    _insert(db, "ai_use_profiles", application_id=use_a)
    plain_a = _insert(db, "applications", name="needle ledger system", business_unit_id=unit["A"], is_active=1,
                      application_type="finance")
    proc_a = _insert(db, "business_processes", name="needle onboarding A", business_unit_id=unit["A"], is_active=1)
    asset_b = _insert(db, "data_assets", name="needle register B", business_unit_id=unit["B"], is_active=1)

    _, a = _search(world.users["dpo_a"], "needle")
    found_a = {(r["type"], r["id"]): r for r in a["results"] if r["module"] == "governance"}
    assert ("application", use_a) in found_a and ("process", proc_a) in found_a
    assert found_a[("application", use_a)]["subtitle"] == "AI use"
    assert found_a[("application", plain_a)]["subtitle"] == "finance", "an application with no AI profile is not called an AI use"
    assert found_a[("application", use_a)]["status"] == "Active"
    assert found_a[("application", use_a)]["business_unit"] == "Unit A"
    assert ("application", use_b) not in found_a and ("data_asset", asset_b) not in found_a

    _, b = _search(world.users["dpo_b"], "needle")
    found_b = {(r["type"], r["id"]) for r in b["results"] if r["module"] == "governance"}
    assert ("application", use_b) in found_b and ("data_asset", asset_b) in found_b, "its positive twin"
    assert ("application", use_a) not in found_b


def test_a_finding_and_an_incident_are_found_with_their_own_scope(world):
    lead_a = {**world.users["dpo_a"], "roles": ["audit_lead"]}
    lead_b = {**world.users["dpo_b"], "roles": ["audit_lead"]}
    _, a = _search(lead_a, "NC in unit A")
    assert [(r["module"], r["type"]) for r in a["results"]] == [("grid", "nc")]
    assert _search(lead_b, "NC in unit A")[1]["results"] == [], "unit B cannot open unit A's audit"
    assert _search(world.users["dpo_a"], "NC in unit A")[1]["results"] == [], "a DPO may not manage findings"
    incident = world.rec[("incident", "B")]
    manager = {**world.users["dpo_b"], "roles": ["bcm_manager"]}
    _, b = _search(manager, "Incident B")
    assert any(r["type"] == "incident" and r["id"] == incident for r in b["results"])
    assert not any(r["type"] == "incident" for r in _search({**manager, "business_unit_id": world.unit["A"]},
                                                              "Incident B")[1]["results"])


def test_search_inside_a_case_returns_only_connected_records_the_viewer_may_open(world):
    db, unit = world.db, world.unit
    proc = _insert(db, "business_processes", name="Customer onboarding", business_unit_id=unit["A"], is_active=1)
    ropa_a = _insert(db, "sentinel_ropa", ref_number="RP-CA", processing_name="Onboarding records A", business_unit_id=unit["A"])
    ropa_b = _insert(db, "sentinel_ropa", ref_number="RP-CB", processing_name="Onboarding records B", business_unit_id=unit["B"])
    maybe = _insert(db, "sentinel_ropa", ref_number="RP-CC", processing_name="Onboarding records proposed",
                    business_unit_id=unit["A"])
    process = ("governance", "process", proc)
    _link(db, ("sentinel", "ropa", ropa_a), process, relationship="supports")
    _link(db, ("sentinel", "ropa", ropa_b), process, relationship="supports")
    _link(db, ("sentinel", "ropa", maybe), process, status="candidate")

    status, body = _search(world.users["dpo_a"], "onboarding", case=f"governance:process:{proc}")
    assert status == 200 and body["case"] == f"governance:process:{proc}"
    titles = sorted(r["title"] for r in body["results"])
    assert titles == ["Customer onboarding", "Onboarding records A"], "the subject, and the one connected record it may open"
    assert body["total"] == 2, "the count follows the rows: the unit B record is not counted"
    assert all(r["in_case"] for r in body["results"])
    assert "Onboarding records B" not in json.dumps(body) and "proposed" not in json.dumps(body)

    narrow = _search(world.users["dpo_a"], "records A", case=f"governance:process:{proc}")[1]
    assert [r["title"] for r in narrow["results"]] == ["Onboarding records A"], "the query still filters inside the case"
    facts = narrow["results"][0]
    assert facts["status"] and facts["business_unit"] == "Unit A"

    status, hidden = _search(world.users["dpo_b"], "onboarding", case=f"governance:process:{proc}")
    assert status == 404 and hidden["results"] == [], "a case the viewer cannot open answers like a missing one"
    assert _search(world.users["dpo_a"], "onboarding", case="nonsense")[0] == 404
    assert _search(world.users["dpo_a"], "onboarding", case="governance:process:99999")[0] == 404


def test_a_connection_is_recorded_suggested_or_disputed(world):
    db, unit = world.db, world.unit
    proc = _insert(db, "business_processes", name="Payroll run", business_unit_id=unit["A"], is_active=1)
    recorded = _insert(db, "sentinel_ropa", ref_number="RP-R", processing_name="Recorded link", business_unit_id=unit["A"])
    suggested = _insert(db, "sentinel_ropa", ref_number="RP-S", processing_name="Suggested link", business_unit_id=unit["A"])
    disputed = _insert(db, "sentinel_ropa", ref_number="RP-D", processing_name="Disputed link", business_unit_id=unit["A"])
    process = ("governance", "process", proc)
    _link(db, ("sentinel", "ropa", recorded), process)
    _link(db, ("sentinel", "ropa", suggested), process, status="candidate")
    _link(db, ("sentinel", "ropa", disputed), process, status="rejected")
    dpo = world.users["dpo_a"]

    plain = relationships.list_links(db, dpo, ("governance", "process"), proc)
    assert [(l["title"], l["state"]) for l in plain] == [("Recorded link", "recorded")], "default listing is unchanged"

    view = entity360.get_connected(db, dpo, "governance", "process", proc)
    items = {i["title"]: i for section in view["connections"] for i in section["items"]}
    assert {t: i["state"] for t, i in items.items()} == {
        "Recorded link": "recorded", "Suggested link": "suggested", "Disputed link": "disputed"}
    assert items["Recorded link"]["confirmed"] is True and items["Disputed link"]["confirmed"] is False
    section = view["connections"][0]
    assert (section["proposed"], section["disputed"]) == (1, 1)
    assert "disputed" in view["note"]


def test_every_column_search_reads_exists(test_db):
    """The facts are looked up by name, so a renamed column would silently drop a status or a date."""
    from modules.governance.entity_scope import _KINDS
    for key, columns in search_service.FACETS.items():
        table = _KINDS[key].table
        have = {row[1] for row in test_db.execute(f"PRAGMA table_info({table})").fetchall()}
        for column in (*columns, _KINDS[key].bu):
            if column:
                assert column in have, (key, table, column)


def test_a_snippet_is_one_short_line_around_the_match():
    text = "word " * 100 + "needle in the middle " + "tail " * 100
    shown = search_service._snippet(text, "needle")
    assert shown.startswith("…") and "needle" in shown and len(shown) <= search_service.SNIPPET_LENGTH + 2
    assert search_service._snippet("a  b\n c", "z") == "a b c"
    assert search_service._snippet("", "x") is None
