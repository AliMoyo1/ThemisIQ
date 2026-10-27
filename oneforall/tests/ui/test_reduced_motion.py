"""
PLAN-36 T07 (step 8, "reduced motion"): a repo-wide scan for `infinite`-
looping CSS animations found ~25 across 8 templates. Loading spinners and
button-loading shimmer were deliberately left alone (brief, functional
feedback, not the kind of gratuitous/ambient motion prefers-reduced-motion
targets). Every purely decorative or ambient one -- the login page's
pulsing background glows/beams/corners plus its two mousemove-driven
parallax effects, the trainer bubble's attention ring, the tooltip-mode
glow, AI "typing" dots, and three small "live/overdue" status-dot pulses
-- now stops under `prefers-reduced-motion: reduce`, verified here via
Playwright's real media-feature emulation (not a simulated/mocked
preference).
"""


def test_login_page_does_not_fetch_video_under_reduced_motion(page, live_app):
    """Reduced motion gets the poster without fetching the looping video."""
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/login")
    page.wait_for_load_state("load")
    assert page.locator("#loginBackground").get_attribute("src") is None
    assert not page.locator("#bgMotionToggle").is_visible()
    assert page.locator("#loginForm").is_visible()


def test_login_page_video_starts_on_desktop_without_the_preference(page, live_app):
    """The desktop media starts after the form, while the old effects are absent."""
    from playwright.sync_api import expect

    page.emulate_media(reduced_motion="no-preference")
    page.goto(f"{live_app}/login")
    expect(page.locator("#loginBackground")).to_have_attribute(
        "src", "/static/media/login/network-1080p-v1.mp4"
    )
    assert page.locator("#loginForm").is_visible()
    assert page.locator(".card-beams, .scene-spot").count() == 0


def test_login_card_has_no_tilt(page, live_app):
    """Mouse movement does not shift the sign-in form over the video."""
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/login")
    page.wait_for_selector(".login-card")
    box = page.eval_on_selector(".login-card", "el => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; }")
    page.mouse.move(box["x"] + 5, box["y"] + 5)
    page.mouse.move(box["x"] + box["w"] - 5, box["y"] + box["h"] - 5)
    transform = page.eval_on_selector(".login-card", "el => getComputedStyle(el).transform")
    assert transform == "none"


def test_login_form_and_module_summary_fit_a_narrow_phone(page, live_app):
    page.set_viewport_size({"width": 320, "height": 568})
    page.goto(f"{live_app}/login")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    assert page.get_by_label("Username").is_visible()
    assert page.get_by_label("Password", exact=True).is_visible()
    assert page.locator("#submitBtn").is_visible()
    assert page.locator(".login-modules li").count() == 7
    assert page.locator("#loginBackground").get_attribute("src") is None


def test_trainer_pulse_and_typing_dots_stop_under_reduced_motion(login_as, live_app):
    page = login_as("super_admin")
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/")
    page.wait_for_selector(".trainer-pulse")
    name = page.eval_on_selector(".trainer-pulse", "el => getComputedStyle(el).animationName")
    assert name == "none"
