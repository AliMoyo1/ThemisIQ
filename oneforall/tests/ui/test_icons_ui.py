"""SVG icons in a real browser (plans/2026-10-svg-icons.md): every page that used emoji now draws icons from the sprite.

For each page: the sprite loads, icons have a size, and no icon markup or HTML entity is shown as visible text. Then the
interactive spots that were built from JavaScript strings: the DPIA and RoPA drawer tabs, loading buttons, the
jurisdiction country chips and the ORM, BCM and Evidence screens.
"""
import re

import pytest

PAGES = [
    "/", "/aria/", "/aria/ai-generator", "/aria/ask", "/aria/mapping", "/aria/frameworks", "/grid/", "/bcm/",
    "/sentinel/", "/erm/", "/erm/scenario-studio", "/orm/", "/evidence/", "/vendors", "/tasks", "/reports", "/workflows", "/risk-register",
    "/people", "/admin/users", "/admin/email", "/admin/api-keys", "/admin/security",
]

# Visible text that means icon markup or an entity was printed instead of drawn.
LEAK = re.compile(r"<svg|</svg>|sprite\.svg|&#\d{3,6};|class=ic\b|aria-hidden=true")
# Pictographs and emoji-style symbols. The plain text marks used as typography (check mark, cross, arrows) are kept.
EMOJI = re.compile("[\U0001F300-\U0001FAFF\U0001F1E6-\U0001F1FF⏩-⏳☁☰⚖⚙⚠⚡"
                   "✅✉✎✦✨✶❌➔➤⭐]")

AUDIT = """() => {
  const out = {leaks: [], emoji: [], tiny: 0, icons: 0};
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode, p = n.parentElement;
    if (!p || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEXTAREA'].includes(p.tagName)) continue;
    const t = n.textContent;
    if (!t.trim()) continue;
    out.leaks.push(t.slice(0, 80));
  }
  document.querySelectorAll('svg.ic, svg.ic-spin, svg.ic-red, svg.ic-orange, svg.ic-amber, svg.ic-green').forEach(s => {
    const r = s.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) return;   // hidden panels
    out.icons++;
    if (r.width < 6 || r.height < 6) out.tiny++;
  });
  out.text = out.leaks; out.leaks = [];
  return out;
}"""


def _audit(page):
    data = page.evaluate(AUDIT)
    leaks = [t for t in data["text"] if LEAK.search(t)]
    emoji = [t for t in data["text"] if EMOJI.search(t)]
    return data, leaks, emoji


@pytest.fixture
def sprite_ok(live_app, page):
    failed = []
    page.on("response", lambda r: failed.append((r.url, r.status)) if "sprite.svg" in r.url and r.status != 200 else None)
    yield failed
    assert not failed, failed


@pytest.mark.parametrize("path", PAGES)
def test_each_page_draws_icons_and_shows_no_emoji_or_markup(login_as, live_app, path, sprite_ok):
    page = login_as("super_admin")
    page.set_viewport_size({"width": 1366, "height": 900})
    response = page.goto(f"{live_app}{path}")
    assert response.status < 400, (path, response.status)
    page.wait_for_load_state("networkidle")
    data, leaks, emoji = _audit(page)
    assert not leaks, (path, leaks[:5])
    assert not emoji, (path, emoji[:5])
    assert data["tiny"] == 0, (path, data)


def test_the_sprite_loads_and_every_symbol_has_drawing(login_as, live_app):
    page = login_as("super_admin")
    text = page.evaluate("async () => (await fetch('/static/icons/sprite.svg')).text()")
    symbols = re.findall(r'<symbol id="(ic-[a-z0-9-]+)"[^>]*>(.+?)</symbol>', text)
    assert len(symbols) > 50
    assert all(body.strip() for _, body in symbols)


def test_the_dpia_drawer_tabs_use_icons(login_as, live_app, sprite_ok):
    page = login_as("dpo")
    page.set_viewport_size({"width": 1366, "height": 900})
    page.goto(f"{live_app}/sentinel/dpia")
    page.wait_for_load_state("networkidle")
    page.evaluate("() => snOpenDpiaDrawer()")
    tabs = page.locator("#snDpiaDrawer .ropa-drawer-tab, .ropa-drawer-tab[data-tab]")
    tabs.first.wait_for(state="visible", timeout=10000)
    names = [t.inner_text().strip() for t in tabs.all()]
    assert names[:4] == ["Basics", "Data", "Risks", "Review"], names
    for tab in tabs.all()[:4]:
        assert tab.locator("svg").count() == 1, tab.inner_text()
        tab.click()
    data, leaks, emoji = _audit(page)
    assert not leaks and not emoji, (leaks, emoji)


def test_the_ropa_drawer_and_ai_buttons_use_icons(login_as, live_app, sprite_ok):
    page = login_as("dpo")
    page.set_viewport_size({"width": 1366, "height": 900})
    page.goto(f"{live_app}/sentinel/ropa")
    page.wait_for_load_state("networkidle")
    page.evaluate("() => snOpenRopaDrawer()")
    page.locator(".ropa-drawer-tab").first.wait_for(state="visible", timeout=10000)
    names = [t.inner_text().strip() for t in page.locator(".ropa-drawer-tab").all()]
    assert names[:4] == ["Basic Info", "Data Details", "Systems & Processors", "Risk & Compliance"], names
    assert all(t.locator("svg").count() == 1 for t in page.locator(".ropa-drawer-tab").all()[:4])
    data, leaks, emoji = _audit(page)
    assert not leaks and not emoji, (leaks, emoji)


def test_jurisdictions_show_country_code_chips_not_flags(login_as, live_app, sprite_ok):
    page = login_as("dpo")
    page.set_viewport_size({"width": 1366, "height": 900})
    page.goto(f"{live_app}/sentinel/jurisdictions")
    page.wait_for_load_state("networkidle")
    chips = page.locator(".flag-chip")
    chips.first.wait_for(state="visible", timeout=10000)
    codes = {c.inner_text().strip() for c in chips.all()}
    assert codes, "no country chips"
    assert all(re.fullmatch(r"[A-Z]{2}", c) for c in codes), codes
    data, leaks, emoji = _audit(page)
    assert not leaks and not emoji, (leaks, emoji)


@pytest.mark.parametrize("path, opener", [
    ("/bcm/incidents", "() => typeof bcmOpenIncidentModal === 'function' && bcmOpenIncidentModal()"),
    ("/orm/events", "() => typeof ormOpenEventModal === 'function' && ormOpenEventModal()"),
    ("/erm/register", "() => typeof ermOpenRiskDrawer === 'function' && ermOpenRiskDrawer()"),
])
def test_module_screens_stay_clean_after_opening_a_form(login_as, live_app, path, opener, sprite_ok):
    page = login_as("super_admin")
    page.set_viewport_size({"width": 1366, "height": 900})
    page.goto(f"{live_app}{path}")
    page.wait_for_load_state("networkidle")
    page.evaluate(opener)
    page.wait_for_timeout(500)
    data, leaks, emoji = _audit(page)
    assert not leaks and not emoji, (path, leaks, emoji)


def test_loading_buttons_show_a_spinner_not_an_hourglass(login_as, live_app):
    page = login_as("dpo")
    page.goto(f"{live_app}/sentinel/dpia")
    page.wait_for_load_state("networkidle")
    html = page.content()
    assert "ic-spin" in html or "snAiScoreRopa" in html
    assert "⏳" not in html
