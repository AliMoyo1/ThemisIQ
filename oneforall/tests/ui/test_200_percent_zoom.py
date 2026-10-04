"""
PLAN-36 T07 (step 8, "200 percent zoom"): WCAG 1.4.10 (Reflow) requires
content to remain usable without horizontal scrolling at 400% zoom on a
1280px-wide design, which is equivalent to testing reflow at a 320px-wide
viewport. 200% zoom on the same 1280px design is the milder, more common
case: equivalent to a 640px-wide viewport. This checks the plan's own
named T07 acceptance routes at 640x800 for horizontal body overflow,
reusing the exact technique test_modal_contract.py's own mobile-viewport
check already established (`document.body.scrollWidth > window.
innerWidth`) at a different breakpoint. The product is explicitly
desktop-first (task_plan.md T08 step 5), so this is checking graceful
degradation at a zoomed-in desktop width, not mobile-first responsive
design.
"""
import pytest


ROUTES = [
    ("/", "super_admin"),
    ("/tasks", "super_admin"),
    ("/reports", "super_admin"),
    ("/calendar", "super_admin"),
    ("/risk-register", "super_admin"),
    ("/people", "super_admin"),
    ("/admin/users", "super_admin"),
    ("/admin/api-keys", "super_admin"),
    ("/admin/webhooks", "super_admin"),
    ("/admin/email", "super_admin"),
    ("/aria/documents", "super_admin"),
    ("/erm/register", "super_admin"),
    ("/erm/library", "super_admin"),
    ("/erm/external", "super_admin"),
    ("/evidence", "super_admin"),
    ("/grid/", "super_admin"),
    ("/bcm/", "super_admin"),
    ("/sentinel/", "super_admin"),
    ("/orm/", "super_admin"),
    ("/governance", "super_admin"),
]

# route -> reason. Same discipline as test_axe_acceptance_routes.py's own
# KNOWN_FAILURES: every entry here is a real, found, not-yet-fixed
# overflow, not a blanket allowlist.
KNOWN_FAILURES = {}


@pytest.mark.parametrize("route,persona", ROUTES)
def test_route_has_no_horizontal_overflow_at_200_percent_zoom(
    login_as, live_app, route, persona,
):
    page = login_as(persona)
    page.set_viewport_size({"width": 640, "height": 800})
    page.goto(f"{live_app}{route}")
    page.wait_for_load_state("networkidle", timeout=10000)
    overflow = page.evaluate("() => document.body.scrollWidth > window.innerWidth")

    if overflow and route in KNOWN_FAILURES:
        pytest.xfail(KNOWN_FAILURES[route])
    assert not overflow, f"{route}: horizontal body overflow at 640x800 (200% zoom equivalent)"
