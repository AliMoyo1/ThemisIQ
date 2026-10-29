"""Filing-scope facets must count only rows the viewer can actually open."""

import pytest
from fastapi import HTTPException

from modules.evidence.company_views import can_file_org_wide, facets, selected_unit
from modules.evidence.routes import _library_page


def _id(db, table, **fields):
    keys = list(fields)
    db.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})",
               [fields[k] for k in keys])
    db.commit()
    return db.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]


def test_filing_facets_and_list_use_same_unit_boundary(test_db):
    db = test_db
    org = _id(db, "organizations", name="Alpha", slug="alpha-company-views", status="active")
    other = _id(db, "organizations", name="Hidden", slug="hidden-company-views", status="active")
    parent = _id(db, "business_units", name="Parent", is_active=1)
    child = _id(db, "business_units", name="Child", parent_id=parent, is_active=1)
    sibling = _id(db, "business_units", name="Sibling", is_active=1)
    for title, oid, unit in (("wide", org, None), ("parent", org, parent),
                             ("child", org, child), ("hidden sibling", org, sibling),
                             ("hidden tenant", other, parent)):
        _id(db, "evidence_items", title=title, org_id=oid, business_unit_id=unit, status="current")
    user = {"id": 80, "org_id": org, "business_unit_id": parent, "roles": ["compliance_manager"]}
    got = facets(db, user)
    assert got["organization"] == {"id": org, "name": "Alpha", "count": 3, "organization_wide": 1}
    assert {(r["name"], r["count"]) for r in got["units"]} == {("Parent", 1), ("Child", 1)}
    assert got["can_file_org_wide"] is False
    assert _library_page(user, {"filing_scope": f"unit:{child}"})["total"] == 1
    assert _library_page(user, {"filing_scope": "organization"})["total"] == 1
    for hidden in (f"unit:{sibling}", "unit:99999", "unit:1 OR 1=1"):
        with pytest.raises(HTTPException) as exc:
            _library_page(user, {"filing_scope": hidden})
        assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        selected_unit(db, user, "organization", for_filing=True)
    assert exc.value.status_code == 404


def test_unscoped_specialist_must_explicitly_choose_broad_filing(test_db):
    db = test_db
    org = _id(db, "organizations", name="Alpha", slug="alpha-broad-file", status="active")
    specialist = {"id": 81, "org_id": org, "business_unit_id": None,
                  "roles": ["grc_officer"]}
    employee = {**specialist, "roles": ["employee"]}
    assert can_file_org_wide(specialist)
    assert selected_unit(db, specialist, "organization", for_filing=True) is None
    assert not can_file_org_wide(employee)
    with pytest.raises(HTTPException):
        selected_unit(db, employee, "organization", for_filing=True)
    assert facets(db, employee)["units"] == []
