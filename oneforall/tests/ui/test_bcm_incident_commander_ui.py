"""
The incident form names its commander as a person, so the person can be told by email
(plans/2026-10-governance-rework/11 step 3). The list is the organization's active people who can open Business Continuity.
"""


def test_the_incident_form_offers_people_to_name_as_commander_and_saves_the_choice(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/bcm/incidents")
    page.wait_for_load_state("networkidle", timeout=10000)
    page.evaluate("() => window.bcmOpenModal('incident')")
    page.wait_for_selector("#bcmf_commander_user_id", timeout=8000)

    page.wait_for_selector("#bcmf_commander_user_id option:nth-child(2)", state="attached", timeout=8000)
    assert page.locator("#bcmf_commander_user_id option").first.inner_text() == "Not named"
    first_person = page.locator("#bcmf_commander_user_id option").nth(1).get_attribute("value")
    page.select_option("#bcmf_commander_user_id", first_person)
    page.fill("#bcmf_title", "Power loss at the primary site")
    page.fill("#bcmf_description", "The generator did not start.")
    page.click("#bcmModalForm button[type=submit]")
    page.wait_for_selector("text=Power loss at the primary site", timeout=8000)
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"
