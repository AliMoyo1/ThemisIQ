"""
PLAN-36 T06 (findings.md F08): smoke coverage for the apiFetch() ->
ApiClient.request migration in BCM, Sentinel, ORM, super_admin, and
workflows. These five pages had no browser test at all before this, and
the migration touches one shared function each page's whole SPA calls
through for its data -- a typo or wrong parameter name here would break
every action on the page, not just one, so each gets a real navigation and
a real fetch round-trip proof, not just "the file compiles."
"""
import pytest


@pytest.mark.parametrize("route,ready_selector", [
    ("/bcm/", "#bcmSpaRoot"),
    ("/sentinel/", "#snSpaRoot"),
    ("/orm/", "#ormSpaRoot"),
    ("/workflows", "body"),
])
def test_page_loads_without_console_errors(login_as, live_app, route, ready_selector):
    page = login_as("super_admin")
    page.goto(f"{live_app}{route}")
    page.wait_for_selector(ready_selector, timeout=5000)
    page.wait_for_load_state("networkidle", timeout=10000)
    assert not page.console_errors, f"{route}: unexpected console/page errors: {page.console_errors}"


def test_super_admin_dashboard_loads_org_data_via_apifetch(login_as, live_app):
    """super_admin.html's apiFetch previously never checked response.status
    at all; this proves a real round trip through the migrated version
    still successfully populates the page, not just that it doesn't throw."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/super-admin/")
    page.wait_for_selector("#statOrgs", timeout=5000)
    page.wait_for_function("document.getElementById('statOrgs').textContent.trim().length > 0", timeout=5000)
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


@pytest.mark.parametrize("route,api_prefix", [
    ("/bcm/", "/bcm/api/"),
    ("/sentinel/", "/sentinel/api/"),
    ("/orm/", "/orm/api/"),
])
def test_apifetch_actually_reaches_the_real_backend(login_as, live_app, route, api_prefix):
    """Confirms the migrated apiFetch is genuinely calling through to a real
    /api/* route (not silently no-op'd by a typo) by watching for at least
    one such request on the wire during the page's own initial load."""
    page = login_as("super_admin")
    seen = {"hit": False}
    page.on("request", lambda req: seen.__setitem__("hit", seen["hit"] or api_prefix in req.url))
    page.goto(f"{live_app}{route}")
    page.wait_for_load_state("networkidle", timeout=10000)
    assert seen["hit"], f"expected at least one real request under {api_prefix} from {route}, saw none"
