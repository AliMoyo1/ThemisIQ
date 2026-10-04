"""Evidence links must reach supported module views without revealing unrelated records."""
import json
from urllib.parse import quote

import database


def test_evidence_links_open_real_module_targets_and_are_item_scoped(login_as, live_app, synthetic_tenant):
    db = database.get_db()
    try:
        uid = synthetic_tenant["users"]["compliance_manager"]["user_id"]
        org = synthetic_tenant["org_id"]
        db.execute("INSERT INTO evidence_items (title, org_id, uploaded_by) VALUES ('Linked handoff evidence', %s, %s)", (org, uid))
        evidence_id = db.execute("SELECT id FROM evidence_items WHERE title='Linked handoff evidence'").fetchone()["id"]
        db.execute("INSERT INTO evidence_items (title, org_id, uploaded_by) VALUES ('Other evidence', %s, %s)", (org, uid))
        other_evidence_id = db.execute("SELECT id FROM evidence_items WHERE title='Other evidence'").fetchone()["id"]
        db.execute("INSERT INTO organizations (name, slug) VALUES ('Handoff Other Org', 'handoff-other-org')")
        other_org = db.execute("SELECT id FROM organizations WHERE slug='handoff-other-org'").fetchone()["id"]
        db.execute("INSERT INTO evidence_items (title, org_id) VALUES ('Private other-org evidence', %s)", (other_org,))
        private_evidence_id = db.execute("SELECT id FROM evidence_items WHERE title='Private other-org evidence'").fetchone()["id"]
        db.execute("INSERT INTO bcm_incidents (title, status) VALUES ('Handoff incident', 'open')")
        incident_id = db.execute("SELECT id FROM bcm_incidents WHERE title='Handoff incident'").fetchone()["id"]
        db.execute("INSERT INTO aria_documents (doc_id, framework, title, org_id) VALUES ('DOC-HANDOFF-1', 'ISO 27001', 'Handoff policy', %s)", (org,))
        document_id = db.execute("SELECT id FROM aria_documents WHERE doc_id='DOC-HANDOFF-1'").fetchone()["id"]
        db.execute("INSERT INTO aria_documents (doc_id, framework, title, org_id) VALUES ('DOC-HANDOFF-PRIVATE', 'ISO 27001', 'Other-org policy', %s)", (other_org,))
        private_document_id = db.execute("SELECT id FROM aria_documents WHERE doc_id='DOC-HANDOFF-PRIVATE'").fetchone()["id"]
        db.execute("INSERT INTO aria_risks (risk_id, framework, description) VALUES ('RISK-HANDOFF-1', 'ISO 27001', 'Handoff risk')")
        db.execute("INSERT INTO bcm_plans (title) VALUES ('Handoff continuity plan')")
        db.execute("INSERT INTO sentinel_ropa (ref_number, processing_name) VALUES ('ROPA-HANDOFF-1', 'Handoff processing')")
        db.execute("INSERT INTO sentinel_dsr (ref_number, requester_name) VALUES ('DSR-HANDOFF-1', 'Handoff requester')")
        dsr_id = db.execute("SELECT id FROM sentinel_dsr WHERE ref_number='DSR-HANDOFF-1'").fetchone()["id"]
        db.execute("INSERT INTO erm_enterprise_risks (title, category, business_unit_id) VALUES ('Handoff enterprise risk', 'operational', %s)", (synthetic_tenant["business_unit_id"],))
        erm_risk_id = db.execute("SELECT id FROM erm_enterprise_risks WHERE title='Handoff enterprise risk'").fetchone()["id"]
        db.execute("INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) VALUES (%s, 'erm', 'risk', %s, %s)", (evidence_id, erm_risk_id, uid))
        db.execute("INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) VALUES (%s, 'sentinel', 'dsr', %s, %s)", (evidence_id, dsr_id, uid))
        db.execute("INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) VALUES (%s, 'aria', 'document', %s, %s)", (evidence_id, private_document_id, uid))
        db.execute("INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) VALUES (%s, 'bcm', 'incident', %s, %s)", (evidence_id, incident_id, uid))
        db.execute("INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) VALUES (%s, 'aria', 'document', %s, %s)", (evidence_id, document_id, uid))
        db.execute("INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id, linked_by) VALUES (%s, 'aria', 'document', %s, %s)", (private_evidence_id, document_id, uid))
        expected_doc_total = db.execute("SELECT COUNT(*) FROM aria_documents WHERE org_id = %s", (org,)).fetchone()[0]
        db.commit()
    finally:
        db.close()

    page = login_as("compliance_manager")
    specs = json.dumps([
        {"module": "bcm", "entity_type": "incident", "entity_id": incident_id},
        {"module": "aria", "entity_type": "document", "entity_id": document_id},
        {"module": "sentinel", "entity_type": "dsr", "entity_id": dsr_id},
        {"module": "erm", "entity_type": "risk", "entity_id": erm_risk_id},
    ])
    url = f"{live_app}/evidence/api/resolve-links?evidence_id={evidence_id}&links={quote(specs)}"
    response = page.request.get(url)
    assert response.status == 200
    results = response.json()
    assert results[0]["url"] == f"/bcm/?open=incident:{incident_id}"
    assert results[1]["url"] == "/aria/documents?open=DOC-HANDOFF-1"
    assert results[2]["name"] == "Handoff requester"
    assert results[2]["url"] == f"/sentinel/?open=dsr:{dsr_id}"
    assert results[3]["url"] == f"/erm/register?open=risk:{erm_risk_id}"
    coverage_response = page.request.get(f"{live_app}/evidence/api/coverage")
    assert coverage_response.status == 200
    document_coverage = next(
        item for item in coverage_response.json()["aria"]["entities"] if item["type"] == "document"
    )
    assert document_coverage["total"] == expected_doc_total
    assert document_coverage["with_evidence"] == 1
    for module, entity_type, term in (
        ("aria", "risk", "Handoff risk"),
        ("bcm", "plan", "Handoff continuity plan"),
        ("sentinel", "ropa", "Handoff processing"),
    ):
        found = page.request.get(
            f"{live_app}/evidence/api/search-entities?module={module}&entity_type={entity_type}&q={quote(term)}"
        )
        assert found.status == 200
        assert any(item["name"] == term for item in found.json()), (module, entity_type)

    private_spec = json.dumps([{"module": "aria", "entity_type": "document", "entity_id": private_document_id}])
    hidden_target = page.request.get(f"{live_app}/evidence/api/resolve-links?evidence_id={evidence_id}&links={quote(private_spec)}")
    assert hidden_target.status == 200
    assert hidden_target.json()[0]["name"] is None
    assert hidden_target.json()[0]["url"] is None
    search = page.request.get(f"{live_app}/evidence/api/search-entities?module=aria&entity_type=document&q=Other-org")
    assert search.status == 200
    assert search.json() == []
    forged = page.request.post(
        f"{live_app}/evidence/api/items/{evidence_id}/links",
        data=json.dumps({"module": "aria", "entity_type": "document", "entity_id": private_document_id}),
        headers={"Origin": live_app, "Content-Type": "application/json"},
    )
    assert forged.status == 404

    unrelated = page.request.get(f"{live_app}/evidence/api/resolve-links?evidence_id={other_evidence_id}&links={quote(specs)}")
    assert unrelated.status == 200
    assert all(not item["name"] and not item["url"] for item in unrelated.json())
    private = page.request.get(f"{live_app}/evidence/api/resolve-links?evidence_id={private_evidence_id}&links={quote(specs)}")
    assert private.status == 404
    missing = page.request.get(f"{live_app}/evidence/api/resolve-links?links={quote(specs)}")
    assert missing.status == 404

    page.goto(f"{live_app}{results[0]['url']}")
    page.locator("#bcmConsoleRoot .bcm-console-panel").wait_for(state="visible", timeout=10000)
    page.goto(f"{live_app}{results[3]['url']}")
    page.locator("#ermRiskDrawer .erm-drawer-panel").wait_for(state="visible", timeout=10000)

def test_link_picker_all_offered_targets_resolve_in_search(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/evidence")
    targets = {
        "aria": ("control", "document", "risk", "framework"),
        "grid": ("audit", "control", "non_conformance"),
        "bcm": ("plan", "incident", "risk", "bia", "compliance_control"),
        "sentinel": ("ropa", "dpia", "breach", "dsr", "vendor"),
        "erm": ("risk",),
    }
    for entity_type in ("control", "framework"):
        seeded = page.request.get(
            f"{live_app}/evidence/api/search-entities?module=aria&entity_type={entity_type}"
        )
        assert seeded.status == 200
        assert seeded.json(), entity_type
    for module, types in targets.items():
        assert page.locator(f"#linkModule option[value='{module}']").count() == 1
        for entity_type in types:
            response = page.request.get(
                f"{live_app}/evidence/api/search-entities?module={module}&entity_type={entity_type}"
            )
            assert response.status == 200, (module, entity_type, response.status)
            assert isinstance(response.json(), list)


def test_link_picker_hides_unavailable_modules(login_as, live_app):
    page = login_as("employee")
    page.goto(f"{live_app}/evidence")
    assert page.locator("#linkModule option[value='grid']").count() == 0
    assert page.locator("#linkModule option[value='sentinel']").count() == 0
    response = page.request.get(f"{live_app}/evidence/api/search-entities?module=sentinel&entity_type=dsr")
    assert response.status == 200
    assert response.json() == []
    coverage = page.request.get(f"{live_app}/evidence/api/coverage")
    assert coverage.status == 200
    assert "sentinel" not in coverage.json()
