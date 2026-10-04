"""Sage/Dusk browser contract and control census on the isolated UI harness."""
from pathlib import Path

import pytest


THEMED_ROUTES = [
    ("/", "platform"),
    ("/aria/", "aria"),
    ("/grid/", "grid"),
    ("/bcm/", "bcm"),
    ("/sentinel/", "sentinel"),
    ("/erm/", "erm"),
    ("/orm/", "orm"),
    ("/evidence", "evidence"),
    ("/evidence-campaigns", "evidence_campaigns"),
    ("/readiness", "readiness"),
    ("/governance", "governance"),
]


@pytest.mark.parametrize("route,module", THEMED_ROUTES)
def test_module_theme_switch_persists_and_cards_keep_the_module_context(
    login_as, live_app, route, module,
):
    page = login_as("super_admin")
    server_errors = []
    page.on("response", lambda response: server_errors.append((response.url, response.status)) if response.status >= 500 else None)
    response = page.goto(f"{live_app}{route}")
    assert response.status == 200, (route, response.status)
    page.wait_for_load_state("networkidle", timeout=15000)
    assert page.locator("body").get_attribute("data-module") == module
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()") == "#e9ebe5"
    assert not server_errors, (route, server_errors)
    assert page.locator("#themeToggle").is_visible()
    page.locator("#themeToggle").click()
    assert page.locator("html").get_attribute("data-theme") == "dark"
    assert page.evaluate("localStorage.getItem('ofa-theme')") == "dark"
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()") == "#0b1420"
    page.reload()
    page.wait_for_load_state("networkidle", timeout=15000)
    assert page.locator("html").get_attribute("data-theme") == "dark"
    assert page.locator("body").get_attribute("data-module") == module
    page.locator("#themeToggle").click()
    assert page.evaluate("localStorage.getItem('ofa-theme')") == "light"
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()") == "#e9ebe5"


def test_sign_in_controls_and_standalone_theme(page, live_app):
    page.goto(f"{live_app}/login")
    page.wait_for_load_state("networkidle", timeout=15000)
    assert page.locator("body").get_attribute("data-premium") == "login"
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--premium-page').trim()") == "#e9ebe5"
    page.locator("#password").fill("sample-only")
    page.locator("#pwToggle").click()
    assert page.locator("#password").get_attribute("type") == "text"
    page.locator("#pwToggle").click()
    assert page.locator("#password").get_attribute("type") == "password"
    assert page.locator("#aegis-particles").count() == 0
    assert not page.locator(".card-beams").is_visible()
    page.evaluate("localStorage.setItem('ofa-theme','dark')")
    page.reload()
    assert page.locator("html").get_attribute("data-theme") == "dark"
    assert page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--premium-page').trim()") == "#0b1420"


ACCEPTANCE_ROUTES = [
    "/", "/tasks", "/reports", "/calendar",
    "/risk-register", "/people", "/admin/users", "/admin/api-keys",
    "/admin/webhooks", "/admin/email", "/aria/documents",
    "/erm/register", "/erm/library", "/erm/external", "/evidence",
    "/grid/", "/bcm/", "/sentinel/", "/orm/", "/governance",
]


@pytest.mark.parametrize("route", ACCEPTANCE_ROUTES)
def test_visible_buttons_have_names_across_acceptance_routes(login_as, live_app, route):
    page = login_as("super_admin")
    page.goto(f"{live_app}{route}")
    page.wait_for_load_state("networkidle", timeout=15000)
    buttons = page.locator("button:visible, [role='button']:visible")
    assert buttons.count() > 0, route
    unnamed = buttons.evaluate_all("""els => els.filter(el => {
      const name = el.getAttribute('aria-label') || el.getAttribute('title') ||
                   el.innerText || el.textContent || '';
      return !name.trim();
    }).map(el => el.outerHTML.slice(0,180))""")
    assert not unnamed, (route, unnamed)


@pytest.mark.parametrize("route", ACCEPTANCE_ROUTES)
def test_dusk_acceptance_routes_have_no_serious_axe_violations(login_as, live_app, run_axe, route):
    page = login_as("super_admin")
    page.goto(f"{live_app}{route}")
    page.evaluate("localStorage.setItem('ofa-theme', 'dark')")
    page.reload()
    page.wait_for_load_state("networkidle", timeout=15000)
    violations = run_axe()
    assert not violations, (route, [(v["id"], [(n["target"], n["failureSummary"]) for n in v["nodes"]]) for v in violations])


def test_all_preview_controls_change_state_or_open_their_surface(browser):
    preview = Path(__file__).resolve().parents[3] / "design" / "themisiq-premium-dashboard" / "index.html"
    context = browser.new_context()
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    try:
        page.goto(preview.as_uri(), wait_until="domcontentloaded")
        page.wait_for_selector("#metrics .metric", timeout=10000)
        assert page.locator("html").get_attribute("data-theme") == "sage"
        assert page.locator(".eyebrow").first.evaluate("el => getComputedStyle(el,'::before').content") in ("none", "normal")
        for theme in ("dusk", "sage"):
            button = page.locator(f".theme-button[data-theme='{theme}']")
            button.click()
            assert page.locator("html").get_attribute("data-theme") == theme
            assert button.get_attribute("aria-pressed") == "true"
        for button in page.locator(".nav-btn").all():
            scope = button.get_attribute("data-scope")
            button.click()
            assert page.locator("html").get_attribute("data-module") == scope
            assert button.get_attribute("aria-current") == "page"
        for period in (7, 30, 90):
            button = page.locator(f".period-button[data-range='{period}']")
            button.click()
            assert button.get_attribute("aria-pressed") == "true"
            assert f"{period}-day view" in page.locator("#chartSummary").inner_text()
        page.locator("#glassRange").evaluate("el => { el.value = 85; el.dispatchEvent(new Event('input', {bubbles:true})); }")
        assert page.locator("#glassValue").inner_text() == "85"
        page.locator("#motionButton").click()
        assert page.locator("#motionButton").get_attribute("aria-pressed") == "false"
        page.locator("#notificationButton").click()
        assert page.locator("#notificationButton").get_attribute("aria-expanded") == "true"
        page.locator("#notificationButton").click()
        assert page.locator("#notificationButton").get_attribute("aria-expanded") == "false"
        page.locator("#refreshButton").click()
        assert "show" in (page.locator("#toast").get_attribute("class") or "")
        for trigger in ("briefButton", "allPrioritiesButton", "chartInfoButton",
                        "signalInfoButton", "activityInfoButton"):
            page.locator(f"#{trigger}").click()
            assert page.locator("#detailDialog").evaluate("el => el.open")
            page.locator("#detailDone").click()
            assert not page.locator("#detailDialog").evaluate("el => el.open")
        for signal in page.locator(".signal-button").all():
            signal.click()
            assert page.locator("#detailDialog").evaluate("el => el.open")
            page.locator("#detailClose").click()
        page.locator("#searchButton").click()
        assert page.locator("#searchDialog").evaluate("el => el.open")
        page.locator("#searchInput").fill("governance")
        page.locator(".search-result").first.click()
        assert not page.locator("#searchDialog").evaluate("el => el.open")
        assert page.locator("html").get_attribute("data-module") in ("aria", "governance")
        page.locator("#searchButton").click()
        page.locator("#searchClose").click()
        assert not page.locator("#searchDialog").evaluate("el => el.open")
        page.locator("#prioritiesButton").click()
        assert not errors, errors
    finally:
        context.close()


@pytest.mark.parametrize("width", [390, 768])
def test_mobile_navigation_is_fully_hidden_until_opened(login_as, live_app, width):
    page = login_as("super_admin")
    page.set_viewport_size({"width": width, "height": 844})
    page.goto(f"{live_app}/")
    page.wait_for_load_state("networkidle", timeout=15000)
    page.wait_for_timeout(300)  # let the drawer transform finish
    drawer = page.locator("#moduleSidebar")
    assert drawer.bounding_box()["x"] + drawer.bounding_box()["width"] <= 1
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    if width == 390:
        tiles = page.locator(".cc-modules-grid > .glass-module")
        assert tiles.count() >= 2
        assert tiles.first.bounding_box()["width"] >= 150
    if width <= 600:
        toggle = page.locator(".mobile-nav-toggle")
        toggle.click()
        page.wait_for_timeout(300)
        assert drawer.bounding_box()["x"] >= 0
        assert page.locator("body").evaluate("el => el.classList.contains('drawer-open')")
        toggle.click()
        page.wait_for_timeout(300)
        assert drawer.bounding_box()["x"] + drawer.bounding_box()["width"] <= 1
