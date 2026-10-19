"""Material ARIA form edits reach confirmed linked records."""
import asyncio
import json
from types import SimpleNamespace

from modules.aria import routes as aria_routes
from tests.test_platform_ownership import _insert, signed_in, world  # noqa: F401


def _request(user):
    return SimpleNamespace(state=SimpleNamespace(user=user))


def _linked_application(world, source_type, source_id):
    app_id = _insert(world.db, "applications", name=f"Linked to {source_type}",
                     business_unit_id=world.unit["A"], is_active=1)
    _insert(world.db, "cross_module_links", source_module="aria", source_type=source_type,
            source_id=source_id, target_module="governance", target_type="application",
            target_id=app_id, relationship="affects", status="confirmed")
    return app_id


def test_risk_form_publishes_only_material_change_to_linked_application(world):
    risk_id = _insert(world.db, "aria_risks", risk_id="RISK-ARIA-1", framework="ISO 27001",
                      description="Access risk", likelihood=2, impact=2, status="Open")
    app_id = _linked_application(world, "risk", risk_id)
    response = asyncio.run(aria_routes.update_risk.__wrapped__(
        _request(world.users["super"]), risk_id, status="Mitigating", owner="Private Owner",
        mitigation="Private mitigation detail", likelihood=4, impact=None))
    assert response.status_code == 200
    [signal] = world.db.execute("SELECT * FROM change_signals").fetchall()
    assert (signal["source_module"], signal["source_type"], signal["source_id"]) == (
        "aria", "risk", risk_id)
    changes = json.loads(signal["changes"])
    assert {change["field"] for change in changes} == {"status", "likelihood"}
    assert "Private" not in signal["changes"]
    [target] = world.db.execute("SELECT target_module,target_type,target_id FROM change_signal_targets").fetchall()
    assert (target["target_module"], target["target_type"], target["target_id"]) == (
        "governance", "application", app_id)


def test_document_form_publishes_version_change_but_not_comments(world):
    document_id = world.rec[("document", "A")]
    _linked_application(world, "document", document_id)
    response = asyncio.run(aria_routes.update_document.__wrapped__(
        _request(world.users["super"]), "DOC-A", title=None, status=None,
        version="2", owner=None, approver=None, effective_date=None, review_date=None,
        location=None, comments="Private editing note", control_ref=None))
    assert response.status_code == 200
    [signal] = world.db.execute("SELECT * FROM change_signals").fetchall()
    assert (signal["source_module"], signal["source_type"], signal["source_id"]) == (
        "aria", "document", document_id)
    assert [change["field"] for change in json.loads(signal["changes"])] == ["version"]
    assert "Private" not in signal["changes"]
