"""Proof filed on a GRID audit control counts for the canonical control it is mapped to.

GRID uploads, respondent assignments and cross-framework reuse all link a Vault file to the GRID control
(grid/control). Nothing in the product links a file to the canonical control itself, so the two evidence
factors of a control's effectiveness score (35 of 100 points) could never be earned, and the ERM risk-control
view never counted any proof. Written out by hand: a current, unexpired file on a mapped GRID control earns
both factors; a turned-down link, an expired file or an unmapped control earns nothing; a change through the
Vault rescores the mapped canonical control at once.
"""
import modules.evidence.routes as vault
import modules.governance.effectiveness as eff
from tests.test_vault_rescores_controls import BASE, EARNED, _call, _insert, as_admin  # noqa: F401


def _world(db):
    _insert(db, "users", id=1, username="admin", email="admin@example.test", full_name="Admin", password_hash="x")
    control = _insert(db, "canonical_controls", title="Access review")
    audit = _insert(db, "grid_audits", name="ISO audit")
    mapped = _insert(db, "grid_controls", audit_id=audit, name="A.5.15 access", canonical_control_id=control)
    unmapped = _insert(db, "grid_controls", audit_id=audit, name="A.5.16 identity")
    return control, mapped, unmapped


def _file(db, grid_control, **item):
    evidence = _insert(db, "evidence_items", title="Access review sample", status="current", **item)
    link = _insert(db, "evidence_links", evidence_id=evidence, module="grid", entity_type="control",
                   entity_id=grid_control)
    return evidence, link


def _score(db, control):
    eff.recompute_controls_by_ids(db, [control])
    db.commit()
    return eff.get_control_score(db, control)


def test_a_file_on_a_mapped_grid_control_earns_both_evidence_factors(test_db):
    control, mapped, _ = _world(test_db)
    assert _score(test_db, control)["score"] == BASE
    _file(test_db, mapped)
    scored = _score(test_db, control)
    assert (scored["evidence_uploaded"], scored["evidence_valid"], scored["score"]) == (1, 1, BASE + EARNED)


def test_a_file_on_an_unmapped_grid_control_earns_nothing(test_db):
    control, _, unmapped = _world(test_db)
    _file(test_db, unmapped)
    assert _score(test_db, control)["score"] == BASE


def test_a_turned_down_link_or_an_expired_file_earns_nothing(test_db):
    control, mapped, _ = _world(test_db)
    _, link = _file(test_db, mapped, expiry_date="2000-01-01")
    assert _score(test_db, control)["score"] == BASE
    _, link = _file(test_db, mapped)
    test_db.execute("UPDATE evidence_links SET review_status='rejected' WHERE id=%s", (link,))
    test_db.commit()
    assert _score(test_db, control)["score"] == BASE


def test_the_erm_risk_control_view_counts_the_same_proof(test_db):
    from modules.erm import data_service as erm
    control, mapped, _ = _world(test_db)
    risk = _insert(test_db, "erm_enterprise_risks", title="Access risk")
    _insert(test_db, "risk_controls", risk_id=risk, control_id=control)
    _file(test_db, mapped)
    rows = erm.list_risk_controls(risk)
    assert [(r["control_title"], r["evidence_count"]) for r in rows] == [("Access review", 1)]


def test_linking_and_unlinking_through_the_vault_rescores_the_mapped_control(test_db):
    control, mapped, _ = _world(test_db)
    evidence = _insert(test_db, "evidence_items", title="Fresh sample", status="current")
    assert _score(test_db, control)["score"] == BASE

    status, body = _call(vault.api_evidence_link_create, evidence,
                         payload={"module": "grid", "entity_type": "control", "entity_id": mapped})
    assert status == 201, body
    assert eff.get_control_score(test_db, control)["score"] == BASE + EARNED, "rescored at once, not at 03:00"

    status, _ = _call(vault.api_evidence_link_delete, body["id"])
    assert status == 200
    assert eff.get_control_score(test_db, control)["score"] == BASE
