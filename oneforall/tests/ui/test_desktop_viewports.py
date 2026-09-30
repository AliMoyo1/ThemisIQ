"""
PLAN-36 T08 (step 5: "Test at least desktop 1366x768 and 1920x1080 plus
mobile regression 390x844 for shell/modal overflow; product remains
desktop-first").

390x844 mobile-regression modal coverage already exists
(test_modal_contract.py::test_modal_fits_mobile_viewport_without_body_overflow)
and 640x800 (200% zoom equivalent) shell coverage already exists
(test_200_percent_zoom.py). This file adds the two named desktop sizes: the
same T07 acceptance route list for shell overflow, plus the same two
representative modals test_modal_contract.py already uses for its mobile
check, so both edges named in the step (shell and modal) are covered at both
sizes.
"""
import pytest

DESKTOP_VIEWPORTS = [(1366, 768), (1920, 1080)]
_VIEWPORT_IDS = [f"{w}x{h}" for w, h in DESKTOP_VIEWPORTS]

# Same acceptance routes as test_200_percent_zoom.py (T07).
ROUTES = [
    ("/", "super_admin"),
    ("/my-dashboard", "super_admin"),
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

# route/modal -> reason, keyed like test_200_percent_zoom.py's own
# KNOWN_FAILURES: only a real, found, not-yet-fixed overflow goes here.
KNOWN_FAILURES = {}


@pytest.mark.parametrize("width,height", DESKTOP_VIEWPORTS, ids=_VIEWPORT_IDS)
@pytest.mark.parametrize("route,persona", ROUTES)
def test_route_has_no_horizontal_overflow_at_desktop_viewport(
    login_as, live_app, route, persona, width, height,
):
    page = login_as(persona)
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{live_app}{route}")
    page.wait_for_load_state("networkidle", timeout=10000)
    overflow = page.evaluate("() => document.body.scrollWidth > window.innerWidth")

    key = f"{route}@{width}x{height}"
    if overflow and key in KNOWN_FAILURES:
        pytest.xfail(KNOWN_FAILURES[key])
    assert not overflow, f"{route}: horizontal body overflow at {width}x{height}"


# Same two representative modals as
# test_modal_contract.py::test_modal_fits_mobile_viewport_without_body_overflow.
MODALS = [
    ("compliance_manager", "/tasks", 'button:has-text("New Task")', "newTaskModal"),
    ("compliance_manager", "/evidence/", 'button:has-text("+ Upload")', "uploadModal"),
]


@pytest.mark.parametrize("width,height", DESKTOP_VIEWPORTS, ids=_VIEWPORT_IDS)
@pytest.mark.parametrize(
    "persona,route,trigger,modal_id", MODALS, ids=[m[3] for m in MODALS]
)
def test_modal_fits_desktop_viewport_without_body_overflow(
    login_as, live_app, persona, route, trigger, modal_id, width, height,
):
    page = login_as(persona)
    page.set_viewport_size({"width": width, "height": height})
    page.goto(f"{live_app}{route}")
    page.click(trigger)
    page.wait_for_selector(f"#{modal_id}.open", timeout=5000)

    overflow = page.evaluate("() => document.body.scrollWidth > window.innerWidth")
    assert not overflow, f"{modal_id} causes horizontal body overflow at {width}x{height}"
