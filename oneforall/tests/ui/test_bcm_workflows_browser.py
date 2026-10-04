"""Browser contracts for dependency mapping and crisis message activation."""


def test_dependency_mapping_node_and_connection_actions(live_app, page, login_as):
    login_as("super_admin")
    page.goto(f"{live_app}/bcm/dependencies")
    page.locator("#bcmDepGrid").wait_for()
    page.get_by_role("button", name="Add Node").click()
    page.locator("#bcmModalForm").wait_for()
    page.locator("#bcmf_name").fill("Primary service")
    page.locator("#bcmf_node_type").select_option("System")
    page.locator("#bcmModalForm button[type=submit]").click()
    page.locator("#bcmDepGrid .dep-node:has-text('Primary service')").wait_for()
    page.get_by_role("button", name="Add Node").click()
    page.locator("#bcmf_name").fill("Customer portal")
    page.locator("#bcmf_node_type").select_option("Application")
    page.locator("#bcmModalForm button[type=submit]").click()
    page.locator("#bcmDepGrid .dep-node:has-text('Customer portal')").wait_for()
    page.locator("#bcmConnectNodesBtn").click()
    page.locator("#depConnectionModal").wait_for()
    page.locator("#depSource").select_option(label="Primary service")
    page.locator("#depTarget").select_option(label="Customer portal")
    page.locator("#depLabel").fill("hosts")
    page.get_by_role("button", name="Connect", exact=True).click()
    page.locator("#bcmDepConnections").get_by_text("Primary service").wait_for()
    page.locator("#bcmDepGrid .dep-node:has-text('Primary service')").get_by_role("button", name="Impact chain").click()
    page.locator("#depImpactModal").get_by_text("Customer portal").wait_for()


def test_crisis_starter_can_be_saved_and_activated(live_app, page, login_as):
    login_as("super_admin")
    page.goto(f"{live_app}/bcm/comms")
    page.get_by_role("button", name="Starter messages").click()
    page.locator("#commsStarterModal").get_by_role("button", name="Use draft").first.click()
    page.locator("#commsModal").wait_for()
    assert page.locator("#ct_title").input_value() == "Initial staff alert"
    page.locator("#commsModal").get_by_role("button", name="Save Template").click()
    card = page.locator("#commsGrid .card:has-text('Initial staff alert')")
    card.wait_for()
    card.get_by_role("button", name="Activate").click()
    page.locator("#commsActivateModal").wait_for()
    page.locator("#commsActivateModal [data-comms-var]").first.wait_for()
    assert page.locator("#commsCopyActivated").is_disabled()
    for input_el in page.locator("#commsActivateModal [data-comms-var]").all():
        input_el.fill("Verified detail")
    assert page.locator("#commsCopyActivated").is_enabled()
    assert "{{" not in page.locator("#commsActivatedText").inner_text()



def test_bcm_viewer_sees_usable_read_only_workflows(live_app, page, login_as):
    login_as("employee")
    page.goto(f"{live_app}/bcm/dependencies")
    page.locator("#bcmDepGrid").wait_for()
    assert page.get_by_role("button", name="Add Node").count() == 0
    assert page.get_by_role("button", name="Connect nodes").count() == 0
    page.goto(f"{live_app}/bcm/comms")
    page.locator("#commsGrid").wait_for()
    assert page.get_by_role("button", name="New Template").count() == 0
    assert page.get_by_role("button", name="Starter messages").count() == 0
