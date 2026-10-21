"""Specialist screens expose reviewable evidence and rule card actions."""

import database


def test_sentinel_rule_card_draft_is_visible_to_dpo(login_as, live_app):
    page = login_as("dpo")
    page.goto(f"{live_app}/sentinel/jurisdictions")
    page.locator("#snCreateRuleCard").click()
    assert page.locator("#snRuleForm").is_visible()
    assert page.locator("#snRuleForm").get_by_text("DPO approval").is_visible()


def test_bcm_legacy_proof_offers_reviewed_vault_match(login_as, live_app):
    page = login_as("super_admin")
    db = database.get_db()
    try:
        control = database.insert_returning_id(
            db, "INSERT INTO bcm_compliance_controls (framework,clause,title) "
            "VALUES ('ISO 22301','probe','Browser legacy proof')", ())
        evidence = database.insert_returning_id(
            db, "INSERT INTO bcm_compliance_evidence (control_id,title,file_path) "
            "VALUES (%s,'Browser legacy reference','/client/not/trusted')", (control,))
        db.commit()
        page.goto(f"{live_app}/bcm/compliance")
        page.wait_for_function("typeof bcmShowControlProof === 'function'")
        page.evaluate("id => bcmShowControlProof(id)", control)
        button = page.get_by_role("button", name="Match Vault artifact")
        button.wait_for()
        button.click()
        assert page.locator("#bcmProofMatches").get_by_text(
            f"legacy reference #{evidence}").is_visible()
    finally:
        db.execute("DELETE FROM bcm_compliance_evidence WHERE id=%s", (evidence,))
        db.execute("DELETE FROM bcm_compliance_controls WHERE id=%s", (control,))
        db.commit()
        db.close()
