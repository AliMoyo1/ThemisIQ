"""Company navigation is reviewed metadata over the existing Vault boundary."""

import pytest
from fastapi import HTTPException

from modules.evidence import ownership
from modules.evidence.routes import _library_page


def row(db, table, **fields):
    names = list(fields)
    db.execute(f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join(['%s'] * len(names))})",
               [fields[name] for name in names])
    db.commit()
    return db.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]


def actor(org, unit, uid, role="compliance_manager"):
    return {"id": uid, "org_id": org, "business_unit_id": unit, "roles": [role]}


def test_reviewed_company_facets_obey_unit_and_org_scope(test_db):
    db = test_db
    org = row(db, "organizations", name="Parent", slug="company-label-parent", status="active")
    other = row(db, "organizations", name="Other", slug="company-label-other", status="active")
    unit = row(db, "business_units", name="Visible", is_active=1)
    hidden = row(db, "business_units", name="Hidden", is_active=1)
    visible = row(db, "evidence_items", org_id=org, business_unit_id=unit, title="A", status="current")
    invisible = row(db, "evidence_items", org_id=org, business_unit_id=hidden, title="B", status="current")
    foreign = row(db, "evidence_items", org_id=other, business_unit_id=unit, title="C", status="current")
    proposer, reviewer = actor(org, unit, 101), actor(org, unit, 102)
    company = ownership.create_company(db, proposer, "OmniContact")
    db.commit()
    ownership.propose(db, proposer, visible, company, "Confirmed by company register")
    db.commit()
    assert ownership.facets(db, proposer) == {"companies": [], "unconfirmed": 1}
    with pytest.raises(HTTPException) as same:
        ownership.review(db, proposer, visible, "confirm", "Independently confirmed")
    assert same.value.status_code == 409
    assert ownership.review(db, reviewer, visible, "confirm", "Confirmed against register") == "confirmed"
    db.commit()
    events = db.execute("SELECT action,actor_id FROM evidence_company_events WHERE evidence_id=%s ORDER BY id",
                        (visible,)).fetchall()
    assert [(event["action"], event["actor_id"]) for event in events] == [
        ("proposed", proposer["id"]), ("confirmed", reviewer["id"])]
    assert ownership.facets(db, proposer)["companies"] == [{"id": company, "name": "OmniContact", "count": 1}]
    assert _library_page(proposer, {"company": str(company)})["total"] == 1
    assert _library_page(proposer, {"company": "unconfirmed"})["total"] == 0
    for inaccessible in (invisible, foreign):
        with pytest.raises(HTTPException) as missing:
            ownership.propose(db, proposer, inaccessible, company, "This should not be visible")
        assert missing.value.status_code == 404
    with pytest.raises(HTTPException) as missing:
        _library_page(actor(other, unit, 103), {"company": str(company)})
    assert missing.value.status_code == 404


def test_assignment_requires_local_company_and_review_rejects_without_filing(test_db):
    db = test_db
    org = row(db, "organizations", name="Source", slug="company-label-source", status="active")
    other = row(db, "organizations", name="Unrelated", slug="company-label-unrelated", status="active")
    item = row(db, "evidence_items", org_id=org, title="Unconfirmed", status="current")
    proposer, reviewer = actor(org, None, 201), actor(org, None, 202)
    foreign_company = ownership.create_company(db, actor(other, None, 203), "SecretCo")
    db.commit()
    with pytest.raises(HTTPException) as missing:
        ownership.propose(db, proposer, item, foreign_company, "Foreign company label")
    assert missing.value.status_code == 404
    local = ownership.create_company(db, proposer, "Econet Group")
    db.commit()
    ownership.propose(db, proposer, item, local, "Signed entity register")
    db.commit()
    assert ownership.review(db, reviewer, item, "reject", "Source does not identify owner") == "rejected"
    db.commit()
    assert db.execute("SELECT COUNT(*) FROM evidence_company_events WHERE evidence_id=%s",
                      (item,)).fetchone()[0] == 2
    assert ownership.facets(db, proposer) == {"companies": [], "unconfirmed": 1}
    assert _library_page(proposer, {"company": "unconfirmed"})["total"] == 1
    with pytest.raises(HTTPException) as malformed:
        _library_page(proposer, {"company": "1 OR 1=1"})
    assert malformed.value.status_code == 404
