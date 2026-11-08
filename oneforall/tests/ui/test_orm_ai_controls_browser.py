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


def test_orm_static_event_controls_load_from_external_script(live_app, page, login_as):
    login_as("super_admin")
    page.goto(f"{live_app}/orm/events")
    policy = page.request.get(f"{live_app}/orm/events").headers["content-security-policy"]
    assert "script-src-attr 'none'" in policy
    assert "script-src 'unsafe-inline'" not in policy
    page.locator("#ormEvtBody tr").first.wait_for()
    assert page.locator("script[src='/static/js/orm_index.js']").count() == 1
    assert page.locator("[onclick],[onchange],[oninput],[onblur],[onkeydown]").count() == 0

    page.locator("#evtStatusBar button[data-val='open']").click()
    assert "active" in page.locator("#evtStatusBar button[data-val='open']").get_attribute("class")
    page.locator("#evtSearch").fill("unmatched fixture query")
    assert page.locator("#evtSearch").input_value() == "unmatched fixture query"

    page.locator("#view-events .header-actions").get_by_role("button", name="Log Event").click()
    page.locator("#ormEvtModal").wait_for()
    assert page.locator("[onclick],[onchange],[oninput],[onblur],[onkeydown]").count() == 0
    page.locator("#ormEvtModal").get_by_role("button", name="Cancel").click()
    page.locator("#ormEvtModal").wait_for(state="detached")


def test_orm_nested_forms_open_without_inline_handlers(live_app, page, login_as):
    login_as("super_admin")
    for route, button, modal in (
        ("indicators", "Add KRI", "#kriModal"),
        ("assessment", "New (Blank)", "#rcsaModal"),
        ("aims", "New Assessment", "#aimsModal"),
    ):
        page.goto(f"{live_app}/orm/{route}")
        page.get_by_role("button", name=button).click()
        page.locator(modal).wait_for()
        assert page.locator("[onclick],[onchange],[oninput],[onblur],[onkeydown]").count() == 0
        page.locator(modal).get_by_role("button", name="Cancel").click()
        page.locator(modal).wait_for(state="detached")


def test_orm_rcsa_nested_control_actions_under_strict_csp(live_app, page, login_as):
    login_as("super_admin")
    page.goto(f"{live_app}/orm/assessment")
    page.get_by_role("button", name="New (Blank)").click()
    page.locator("#rc_title").fill("CSP browser assessment")
    page.locator("#rcsaModal").get_by_role("button", name="Save", exact=True).click()
    row = page.locator("#rcsaBody tr").filter(has_text="CSP browser assessment")
    row.wait_for()
    row.locator("button[title='Open']").click()
    page.locator("#ormDrawerRoot").get_by_role("button", name="Add Risk").click()
    page.locator("#rr_title").fill("CSP browser risk")
    page.locator("#rcsaRiskModal").get_by_role("button", name="Add Risk").click()
    page.locator("#ormDrawerRoot [data-orm-complex='rcsa-control-add']").click()
    page.locator("#rc_name").fill("CSP browser control")
    page.locator("#rcsaControlModal").get_by_role("button", name="Save Control").click()
    edit = page.locator("#ormDrawerRoot [data-orm-complex='rcsa-control-edit']")
    edit.wait_for()
    edit.click()
    assert page.locator("#rc_name").input_value() == "CSP browser control"
    assert page.locator("[onclick],[onchange],[oninput],[onblur],[onkeydown]").count() == 0


def test_orm_aims_drawer_edit_under_strict_csp(live_app, page, login_as):
    login_as("super_admin")
    page.goto(f"{live_app}/orm/aims")
    page.get_by_role("button", name="New Assessment").click()
    page.locator("#am_title").fill("CSP browser AI risk assessment")
    page.locator("#aimsModal").get_by_role("button", name="Save", exact=True).click()
    row = page.locator("#aimsBody tr").filter(has_text="CSP browser AI risk assessment")
    row.wait_for()
    row.locator("button[title='Open']").click()
    page.locator("#ormDrawerRoot [data-orm-complex='aims-edit-close']").click()
    page.locator("#aimsModal").wait_for()
    assert page.locator("#am_title").input_value() == "CSP browser AI risk assessment"
    assert page.locator("[onclick],[onchange],[oninput],[onblur],[onkeydown]").count() == 0


def test_orm_kri_update_controls_under_strict_csp(live_app, page, login_as):
    login_as("super_admin")
    page.goto(f"{live_app}/orm/indicators")
    page.get_by_role("button", name="Add KRI").click()
    page.locator("#kr_name").fill("CSP browser KRI")
    page.locator("#kriModal").get_by_role("button", name="Save KRI").click()
    card = page.locator(".kri-card").filter(has_text="CSP browser KRI")
    card.wait_for()
    card.get_by_role("button", name="Update Value").click()
    page.locator("#kriUpdateModal").get_by_role("button", name="+5").click()
    assert page.locator("#kum_val").input_value() == "5"
    assert page.locator("[onclick],[onchange],[oninput],[onblur],[onkeydown]").count() == 0
    page.locator("#kriUpdateModal").get_by_role("button", name="Cancel").click()
