"""The ERM risk CSV export applies the business unit rule that the ERM risk list applies.

GET /erm/api/export/csv used to select every row of erm_enterprise_risks and risk_register, so a risk owner or
DPO in unit A could download unit B's risks, which the list, detail and delete routes hide from them. The rule
under test is the registry's (modules/governance/entity_scope.py): a NULL unit is organization wide, anything
else must sit inside the caller's own subtree (a parent unit sees its children, a child does not see its
parent), and the caller needs erm.risk.view.

Expectations are written out by hand from the seed rows below, never computed by the code under test, and every
"sees nothing" assertion has a positive twin. The export is called through the real router, so the capability
gate is part of what is tested.
"""
import csv
import io

import pytest
from fastapi import FastAPI
from starlette.testclient import TestClient

import core.middleware as middleware
from modules.erm.routes import router as erm_router
from tests.test_platform_ownership import _insert, world  # noqa: F401  (world is a fixture)

# Unit tags each persona may export: organization wide rows plus their own subtree (A has the child A1).
# employee_a is not here: it lacks erm.risk.view and is refused, see the last test.
SEES = {
    "super": {"org", "A", "A1", "B"},
    "dpo_a": {"org", "A", "A1"},        # a parent unit sees its children
    "owner_a": {"org", "A", "A1"},
    "dpo_a1": {"org", "A1"},            # a child does not see its parent
    "dpo_b": {"org", "B"},
    "owner_b": {"org", "B"},
    "dpo_no_unit": {"org"},
}


@pytest.fixture
def export(world, monkeypatch):
    """Seeds one enterprise risk and one platform risk per unit tag, and returns a function that downloads the
    CSV as a persona, through the real router."""
    for tag, unit_id in world.unit.items():
        _insert(world.db, "erm_enterprise_risks", title=f"export erm {tag}", business_unit_id=unit_id)
        _insert(world.db, "risk_register", title=f"export platform {tag}", business_unit_id=unit_id)

    caller = {}

    async def current_user(request):
        return world.users[caller["name"]]

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    app = FastAPI()
    app.include_router(erm_router)
    client = TestClient(app, base_url="http://testserver", raise_server_exceptions=False)

    def download(name):
        caller["name"] = name
        return client.get("/erm/api/export/csv")

    return download


@pytest.mark.parametrize("name", list(SEES))
def test_the_export_holds_the_rows_the_viewer_may_see_and_no_others(export, name):
    response = export(name)
    assert response.status_code == 200
    names = {row["name"] for row in csv.DictReader(io.StringIO(response.text))}
    # the world fixture adds one ERM risk of its own; only the rows seeded above are judged here
    exported = {n for n in names if n.startswith("export ")}
    assert exported == {f"export {kind} {tag}" for tag in SEES[name] for kind in ("erm", "platform")}


def test_a_user_without_erm_risk_view_is_refused(export):
    assert export("employee_a").status_code == 403
