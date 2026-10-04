"""Browser contract for the AI Controls Catalogue actions."""


def test_ai_control_edit_opens_prefilled_dialog(live_app, page, login_as):
    login_as("super_admin")
    page.goto(f"{live_app}/orm/ai-controls")
    page.locator("#aicBody tr").first.wait_for()
    page.locator("#aicBody button[title='Edit']").first.click()
    page.locator("#aicModal").wait_for()
    original = page.locator("#aic_title").input_value()
    assert original
    updated = original + ' "reviewed"'
    page.locator("#aic_title").fill(updated)
    page.locator("#aicModal").get_by_role("button", name="Save").click()
    page.locator("#aicModal").wait_for(state="detached")
    page.locator("#aicBody").get_by_text(updated).wait_for()
    page.locator("#aicBody tr").filter(has_text=updated).get_by_role("button", name="Edit").click()
    assert page.locator("#aic_title").input_value() == updated



def test_ai_control_viewer_has_no_mutation_buttons(live_app, page, login_as):
    login_as("audit_lead")
    page.goto(f"{live_app}/orm/ai-controls")
    page.locator("#aicBody tr").first.wait_for()
    assert page.get_by_role("button", name="Add Control").count() == 0
    assert page.locator("#aicBody button[title='Edit']").count() == 0
    assert page.locator("#aicBody button[title='Deactivate']").count() == 0
