"""G7 oversight in the browser: draft, review, history and accessible controls."""

from tests.ui.test_ai_governance_pages import _accepted_system, unique  # noqa: F401


def test_oversight_draft_and_independent_review(login_as, live_app, page, run_axe, unique):
    _accepted_system(login_as, live_app, page, unique)
    url = page.url
    page.click("#aigtab_oversight")
    design = page.locator("[data-track='design']")
    design.locator("button:has-text('Create draft')").wait_for()
    assert run_axe() == []
    design.locator("button:has-text('Create draft')").click()
    page.fill("#aigOversightPerson", "Compliance")  # the oversight person must be able to open the use
    page.locator(".aig-dialog .aig-queue-item:has-text('Compliance')").first.click()
    page.fill("#aigOversight_monitoring_method", "A team lead reviews outputs each day.")
    page.fill("#aigOversight_intervention_method", "A reviewer can reject an output.")
    page.fill("#aigOversight_stop_procedure", "Disable the AI use and switch to manual review.")
    page.fill("#aigOversight_escalation_path", "Escalate concerns to the incident lead.")
    assert run_axe() == []
    page.locator(".aig-dialog button:has-text('Save draft')").click()
    design.locator("text=Draft, awaiting review").wait_for()
    assert "Ask another authorized reviewer" in design.inner_text()
    page.click("#aigtab_decisions")
    decision_context = page.locator("section:has(#aigDecOversight)")
    decision_context.locator("text=Design: Draft").wait_for()
    assert "does not change the signed decision" in decision_context.inner_text()
    page.reload()
    page.click("#aigtab_oversight")
    design.locator("text=Draft, awaiting review").wait_for()

    page.context.clear_cookies()
    login_as("risk_owner")
    page.goto(url)
    page.click("#aigtab_oversight")
    design.locator("button:has-text('Review this version')").click()
    page.locator(".aig-dialog button:has-text('Mark reviewed')").click()
    design.locator(".aig-chip-good", has_text="Reviewed").wait_for()
    assert "A team lead reviews outputs each day" in design.inner_text()
    page.click("#aigtab_decisions")
    page.locator("section:has(#aigDecOversight) >> text=Design: Reviewed").wait_for()
    assert run_axe() == []
