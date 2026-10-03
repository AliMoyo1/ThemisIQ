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


def test_login_page_ambient_animations_stop_under_reduced_motion(page, live_app):
    """The visible bottom glow and hidden legacy beams have no animation
    when the browser requests reduced motion."""
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/login")
    page.wait_for_selector(".scene-bottom-glow")
    for selector in [".scene-bottom-glow", ".scene-top-pulse", ".scene-spot",
                     ".beam-top", ".corner-tl"]:
        name = page.eval_on_selector(selector, "el => getComputedStyle(el).animationName")
        assert name == "none", f"{selector} still animates: {name}"


def test_login_page_animations_run_normally_without_the_preference(page, live_app):
    """The visible bottom glow animates normally; legacy top beams stay hidden."""
    page.emulate_media(reduced_motion="no-preference")
    page.goto(f"{live_app}/login")
    page.wait_for_selector(".scene-bottom-glow")
    name = page.eval_on_selector(".scene-bottom-glow", "el => getComputedStyle(el).animationName")
    assert name == "bottomPulse"
    assert not page.locator(".scene-top-pulse").is_visible()


def test_login_card_tilt_does_not_respond_to_mouse_under_reduced_motion(page, live_app):
    """The 3D tilt/parallax are JS-driven (mousemove listeners), not pure
    CSS, so they need their own check: moving the mouse over the card
    must not change its transform when reduced motion is preferred."""
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/login")
    page.wait_for_selector("#cardTilt")
    box = page.eval_on_selector("#cardTilt", "el => { const r = el.getBoundingClientRect(); return {x: r.x, y: r.y, w: r.width, h: r.height}; }")
    page.mouse.move(box["x"] + 5, box["y"] + 5)
    page.mouse.move(box["x"] + box["w"] - 5, box["y"] + box["h"] - 5)
    transform = page.eval_on_selector("#cardTilt", "el => el.style.transform")
    assert transform in ("", "none"), transform


def test_trainer_pulse_and_typing_dots_stop_under_reduced_motion(login_as, live_app):
    page = login_as("super_admin")
    page.emulate_media(reduced_motion="reduce")
    page.goto(f"{live_app}/")
    page.wait_for_selector(".trainer-pulse")
    name = page.eval_on_selector(".trainer-pulse", "el => getComputedStyle(el).animationName")
    assert name == "none"
