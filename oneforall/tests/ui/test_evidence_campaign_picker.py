"""The campaigns "Submit evidence" picker reads the paginated Vault list (PHASE-1A.md, T6)."""
import time

import database


def test_submit_picker_lists_matching_evidence_from_the_paginated_response(login_as, live_app, synthetic_tenant):
    org = synthetic_tenant["org_id"]
    employee = synthetic_tenant["users"]["employee"]["user_id"]
    manager = synthetic_tenant["users"]["compliance_manager"]["user_id"]
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO evidence_items (title, org_id, uploaded_by, status) VALUES ('Picker probe evidence', %s, %s, 'current')",
            (org, employee),
        )
        db.execute(
            "INSERT INTO evidence_requests (org_id, module, entity_type, entity_id, title, assignee_id, reviewer_id, "
            "due_date, status, created_by, created_at, updated_at) "
            "VALUES (%s,'grid','control','1','Picker probe request',%s,%s,'2099-01-01','requested',%s,"
            "'2026-01-01 00:00:00','2026-01-01 00:00:00')",
            (org, employee, manager, manager),
        )
        db.commit()
        evidence_id = db.execute("SELECT id FROM evidence_items WHERE title='Picker probe evidence'").fetchone()["id"]
    finally:
        db.close()
    try:
        page = login_as("employee")
        prompts = []

        def on_dialog(dialog):
            prompts.append(dialog.message)
            if len(prompts) == 1:
                dialog.accept("Picker probe")
            else:
                dialog.dismiss()

        page.on("dialog", on_dialog)
        page.goto(f"{live_app}/evidence-campaigns")
        page.click(".ec-tab[data-tab='mine']")
        page.click("[data-submit]")
        deadline = time.time() + 10
        while len(prompts) < 2 and time.time() < deadline:
            page.wait_for_timeout(100)
        assert len(prompts) == 2, prompts
        assert f"Picker probe evidence (id {evidence_id})" in prompts[1]
    finally:
        db = database.get_db()
        try:
            db.execute("DELETE FROM evidence_requests WHERE title='Picker probe request'")
            db.execute("DELETE FROM evidence_items WHERE title='Picker probe evidence'")
            db.commit()
        finally:
            db.close()
