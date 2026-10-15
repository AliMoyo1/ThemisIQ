"""
Platform functions (plan 04 section 8): the fixes found while taking their inventory
(plans/2026-10-governance-rework/08-platform-functions-inventory.md).
"""
import json
import pathlib

import modules.launcher.routes_dashboard as dash
import modules.launcher.routes_platform as plat
import modules.launcher.routes_reports as reports
from core import rbac
from tests.test_platform_ownership import _call, _insert, _request, signed_in, world  # noqa: F401

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_an_imported_risk_belongs_to_the_importers_unit_and_is_not_organization_wide(world):
    importer = {**world.users["super"], "business_unit_id": world.unit["A"], "roles": [rbac.SUPER_ADMIN]}
    status, body = _call(plat.api_bulk_import(
        _request(importer, payload={"records": [{"title": "Imported supplier risk", "likelihood": 4, "impact": 4}]}),
        "risks"))
    assert status == 200 and body["imported"] == 1
    row = world.db.execute("SELECT business_unit_id FROM risk_register WHERE title = 'Imported supplier risk'").fetchone()
    assert row["business_unit_id"] == world.unit["A"]

    def titles(user):
        return {r["title"] for r in reports.builders.build(world.db, user, "risk_report").result["top_risks"]}
    assert "Imported supplier risk" in titles(world.users["dpo_a"]), "the unit that imported it sees it"
    assert "Imported supplier risk" not in titles(world.users["dpo_b"]), "another unit does not"


def test_a_percentage_with_nothing_behind_it_is_null_not_zero_and_not_a_hundred(world):
    world.db.execute("DELETE FROM controls")
    world.db.execute("DELETE FROM sla_instances")
    world.db.commit()
    status, stats = _call(dash.api_command_centre_stats(_request(world.users["dpo_a"])))
    assert status == 200
    assert stats["compliance_pct"] is None
    assert stats["sla"]["pct"] is None
    assert all(h["pct"] is None or isinstance(h["pct"], int) for h in stats["module_health"])
    assert any(h["key"] == "aria" and h["pct"] is None for h in stats["module_health"]), "no control: not measured"


def test_the_inventory_sees_a_capability_behind_require_auth():
    inventory = json.loads((ROOT / "docs/generated/capability_inventory.json").read_text(encoding="utf-8"))
    by_path = {(e["path"], tuple(e["methods"])): e for e in inventory["entries"]}
    activate = by_path[("/api/frameworks/{fid}/activate", ("POST",))]
    assert activate["gate"] == "capability" and activate["capabilities"] == ["manage_frameworks"]
