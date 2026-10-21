"""Guided tours in a real browser: every step points at something a person who may take the tour can see, and the
welcome tour runs across pages to the end and ticks the checklist."""
import pytest

# tour id -> a persona who may take it
TOUR_PERSONA = {
    "welcome": "super_admin",
    "governance": "compliance_manager",
    "audit": "audit_lead",
    "privacy": "dpo",
    "resilience": "bcm_manager",
    "enterprise-risk": "risk_owner",
    "operations-risk": "super_admin",
    "ai-governance": "dpo",
    "administration": "super_admin",
}


def _tours(page, live_app):
    return page.evaluate("async () => (await (await fetch('/api/onboarding')).json()).tours")


@pytest.mark.parametrize("tour_id, persona", sorted(TOUR_PERSONA.items()))
def test_every_required_step_is_on_screen_for_someone_who_may_take_the_tour(login_as, live_app, tour_id, persona):
    page = login_as(persona)
    page.set_viewport_size({"width": 1366, "height": 900})
    page.goto(f"{live_app}/")
    tours = {t["id"]: t for t in _tours(page, live_app)}
    assert tour_id in tours, (persona, sorted(tours))
    for step in tours[tour_id]["steps"]:
        if step["optional"]:
            continue
        page.goto(f"{live_app}{step['path']}")
        locator = page.locator(step["selector"]).first
        locator.wait_for(state="attached", timeout=10000)
        locator.scroll_into_view_if_needed()
        assert locator.is_visible(), (tour_id, step["path"], step["selector"])


def test_the_welcome_tour_runs_across_pages_and_ticks_the_checklist(login_as, live_app):
    page = login_as("super_admin")
    page.set_viewport_size({"width": 1366, "height": 900})
    page.goto(f"{live_app}/")
    page.wait_for_function("() => window.ThemisTours")
    steps = [t for t in _tours(page, live_app) if t["id"] == "welcome"][0]["steps"]
    page.evaluate("() => window.ThemisTours.start('welcome')")
    titles = []
    for _ in range(len(steps) + 2):
        pop = page.locator(".tour-pop")
        pop.wait_for(state="visible", timeout=10000)
        titles.append(page.locator("#tourPopTitle").inner_text())
        assert page.locator(".tour-spot").is_visible()
        button = page.locator(".tour-pop .tp-next")
        if button.inner_text() == "Finish":
            button.click()
            break
        button.click()
    assert titles[0] == "Your modules"
    assert titles[-1] == "Ask Themis"
    assert page.url.endswith("/my-work")
    page.locator("#trainerStartView").wait_for(state="visible")
    item = page.locator("#trainerStartView li", has_text="Take the tour: Welcome to ThemisIQ")
    assert "is-done" in (item.get_attribute("class") or "")
    assert page.locator("#trainerStartView button", has_text="Take it again").count() >= 1


def test_escape_ends_a_tour_and_nothing_follows_to_the_next_page(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/")
    page.wait_for_function("() => window.ThemisTours")
    page.evaluate("() => window.ThemisTours.start('welcome')")
    page.locator(".tour-pop").wait_for(state="visible")
    page.keyboard.press("Escape")
    assert not page.locator(".tour-pop").is_visible()
    page.goto(f"{live_app}/my-work")
    page.wait_for_timeout(800)
    assert page.locator(".tour-pop").count() == 0 or not page.locator(".tour-pop").is_visible()


def test_the_get_started_panel_has_no_serious_accessibility_violations(login_as, live_app, run_axe):
    page = login_as("audit_lead")
    page.goto(f"{live_app}/")
    page.wait_for_function("() => window.ThemisTours")
    page.evaluate("() => window.ThemisTours.open()")
    page.locator("#trainerStartView .ts-tour").first.wait_for(state="visible")
    in_panel = [v["id"] for v in run_axe()
                if any("trainer" in str(n["target"]) or "ts-" in str(n["target"]) for n in v["nodes"])]
    assert in_panel == []


def test_asking_themis_offers_take_me_there_and_points_at_the_named_button(login_as, live_app):
    page = login_as("dpo")
    page.set_viewport_size({"width": 1366, "height": 900})
    page.goto(f"{live_app}/")
    page.wait_for_function("() => window.ThemisTours")
    if not page.locator("#trainerPanel.open").count():
        page.locator(".trainer-icon").click()
    page.locator("#trainerTabAsk").click()
    page.locator("#trainerInput").fill("we had a data leak, what do I do?")
    page.locator("#trainerInput").press("Enter")
    go = page.locator(".trainer-go", has_text="Take me there")
    go.wait_for(state="visible", timeout=10000)
    assert "Report Breach" in page.locator("#trainerMessages .trainer-msg.bot").last.inner_text()
    go.click()
    page.wait_for_url("**/sentinel/breaches")
    page.locator(".tour-pop").wait_for(state="visible", timeout=10000)
    assert page.locator("#tourPopTitle").inner_text() == "Report a data breach"
    spot = page.locator(".tour-spot").bounding_box()
    button = page.get_by_role("button", name="Report Breach").first.bounding_box()
    assert spot["x"] <= button["x"] and spot["y"] <= button["y"]
    assert spot["x"] + spot["width"] >= button["x"] + button["width"]
    page.locator(".tour-pop .tp-next", has_text="Got it").click()
    assert not page.locator(".tour-pop").is_visible()


def test_themis_tells_a_role_when_something_is_not_available_to_it(login_as, live_app):
    page = login_as("privacy_analyst")
    page.goto(f"{live_app}/")
    page.wait_for_function("() => window.ThemisTours")
    if not page.locator("#trainerPanel.open").count():
        page.locator(".trainer-icon").click()
    page.locator("#trainerTabAsk").click()
    page.locator("#trainerInput").fill("How do I add a new user?")
    page.locator("#trainerInput").press("Enter")
    page.locator("#trainerMessages .trainer-msg.bot", has_text="isn't available to your role").wait_for(timeout=10000)
    assert page.locator(".trainer-go").count() == 0
