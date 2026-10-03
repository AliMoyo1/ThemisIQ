"""Smoke the shared shell controls in the isolated browser app."""
import pytest


@pytest.mark.parametrize("route,module,persona", [
    ("/", "platform", "super_admin"), ("/aria/", "aria", "super_admin"), ("/grid/", "grid", "super_admin"),
    ("/bcm/", "bcm", "super_admin"), ("/sentinel/", "sentinel", "super_admin"), ("/erm/", "erm", "super_admin"),
    ("/orm/", "orm", "super_admin"), ("/governance/", "governance", "compliance_manager"),
])
def test_module_rail_link_navigates_to_its_dashboard(login_as, live_app, route, module, persona):
    page = login_as(persona)
    page.goto(f"{live_app}/")
    page.locator(f'.icon-sidebar a.icon-nav-item[href="{route}"]').click()
    page.wait_for_load_state("networkidle", timeout=15000)
    assert page.locator("body").get_attribute("data-module") == module
    assert page.locator(".icon-sidebar a.icon-nav-item.active").get_attribute("href") == route


def test_global_shell_controls_open_and_close(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/")
    page.wait_for_load_state("networkidle", timeout=15000)
    failures = []
    page.on("response", lambda response: failures.append((response.url, response.status)) if response.status >= 500 else None)

    page.locator("#railPin").click()
    assert page.locator(".icon-sidebar").evaluate("el => el.classList.contains('pinned')")
    page.locator("#railPin").click()
    assert not page.locator(".icon-sidebar").evaluate("el => el.classList.contains('pinned')")

    page.locator(".sidebar-toggle").click()
    assert page.locator("#moduleSidebar").evaluate("el => el.classList.contains('collapsed')")
    page.locator(".sidebar-toggle").click()
    assert not page.locator("#moduleSidebar").evaluate("el => el.classList.contains('collapsed')")

    page.locator("#notifBtn").click()
    assert page.locator("#notifBtn").get_attribute("aria-expanded") == "true"
    assert page.locator("#notifPanel").evaluate("el => el.classList.contains('show')")
    with page.expect_response("**/api/notifications/read-all") as mark_response:
        page.get_by_role("button", name="Mark all read").click()
    assert mark_response.value.status == 200
    page.locator("#notifBtn").click()
    assert page.locator("#notifBtn").get_attribute("aria-expanded") == "false"

    page.get_by_role("button", name="Set email reminder").click()
    assert page.locator("#reminderModal").is_visible()
    assert page.locator("#reminderModal").bounding_box()["width"] >= 1000
    page.get_by_role("button", name="Create Reminder").click()
    assert page.locator("#remTitle").evaluate("el => el.validity.valueMissing")
    page.locator("#reminderModal button").first.click()
    assert not page.locator("#reminderModal").is_visible()

    page.locator(".icon-sidebar-user").click()
    assert page.locator("#userDropdown").evaluate("el => el.classList.contains('show')")
    page.locator(".icon-sidebar-user").click()
    assert not page.locator("#userDropdown").evaluate("el => el.classList.contains('show')")

    page.keyboard.press("Control+k")
    assert page.locator("#globalSearch").evaluate("el => document.activeElement === el")
    page.locator("#globalSearch").fill("risk")
    page.locator("#searchResults").wait_for(state="visible", timeout=10000)
    page.keyboard.press("Escape")
    assert not page.locator("#searchResults").is_visible()
    assert not failures, failures


def test_dusk_shell_popovers_have_no_serious_axe_violations(login_as, live_app, run_axe):
    page = login_as("super_admin")
    page.goto(f"{live_app}/")
    page.evaluate("localStorage.setItem('ofa-theme','dark')")
    page.reload()
    page.wait_for_load_state("networkidle", timeout=15000)

    page.locator("#notifBtn").click()
    violations = run_axe()
    assert not violations, ("Dusk notifications popover", [(v["id"], [(n["target"], n["failureSummary"]) for n in v["nodes"]]) for v in violations])
    page.locator("#notifBtn").click()

    page.get_by_role("button", name="Set email reminder").click()
    violations = run_axe()
    assert not violations, ("Dusk reminder dialog", [(v["id"], [(n["target"], n["failureSummary"]) for n in v["nodes"]]) for v in violations])
    page.locator("#reminderModal button").first.click()

    page.locator(".icon-sidebar-user").click()
    violations = run_axe()
    assert not violations, ("Dusk account menu", [(v["id"], [(n["target"], n["failureSummary"]) for n in v["nodes"]]) for v in violations])
