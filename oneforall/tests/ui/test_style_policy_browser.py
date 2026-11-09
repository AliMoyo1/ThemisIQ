"""
Every <style> a page renders runs under the per-response nonce, and a <style> without it is refused
(plans/2026-11-zoom-and-style-policy.md). Each route below holds at least one <style> block: the shell, the module
pages with their own, the error page, and the two scripts that add one at run time.
"""
import pytest

ROUTES = [
    "/", "/evidence/", "/evidence/batch/", "/evidence/companies/", "/governance/attention/", "/governance/group/figures/",
    "/governance/group/rooms/", "/grid/", "/grid/assignments/", "/grid/reuse/", "/ai-governance/registers", "/aria/",
    "/aria/documents", "/aria/ask", "/aria/mapping", "/aria/ai-generator", "/aria/policy-imports", "/bcm/", "/sentinel/",
    "/erm/", "/admin/frameworks", "/super-admin", "/mfa/setup", "/an/unknown/page",
]

_STYLES = """() => [...document.querySelectorAll('style')].map(s => ({
  applied: !!s.sheet && s.sheet.cssRules.length > 0, nonced: !!s.nonce, id: s.id || s.textContent.slice(0, 40)
}))"""


@pytest.mark.parametrize("route", ROUTES)
def test_every_style_block_on_the_page_is_applied_under_the_nonce(login_as, live_app, route):
    page = login_as("super_admin")
    refused = []
    page.on("console", lambda m: "Content Security Policy" in m.text and "style" in m.text and refused.append(m.text))
    response = page.goto(f"{live_app}{route}")
    page.wait_for_load_state("networkidle", timeout=15000)
    policy = response.headers.get("content-security-policy", "")
    assert "style-src-elem 'self' 'nonce-" in policy, route
    styles = page.evaluate(_STYLES)
    assert styles, f"{route} should hold a <style> block"
    for style in styles:
        assert style["applied"] and style["nonced"], f"{route}: {style['id']}"
    assert refused == [], f"{route}: {refused[:2]}"


@pytest.mark.expected_page_errors("the test injects a style without the nonce, and the browser reports refusing it")
def test_a_style_without_the_nonce_is_refused_and_the_print_window_keeps_its_own(login_as, live_app):
    """An injected <style> does nothing. The ARIA generator's print window inherits the page's policy, so the one it
    writes carries the page's nonce."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/aria/ai-generator")
    page.wait_for_load_state("networkidle", timeout=15000)
    injected = page.evaluate("""() => {
      const d = document.createElement('div'); d.innerHTML = '<style>body{outline:7px solid rgb(1, 2, 3)}</style>';
      document.body.appendChild(d);
      return getComputedStyle(document.body).outlineWidth;
    }""")
    assert injected != "7px", "an injected style without the nonce must not apply"
    with page.expect_popup() as popup_info:
        page.evaluate("""() => {
          const n = document.querySelector('style[nonce]').nonce;
          const w = window.open('', '_blank');
          w.document.write('<html><head><style nonce="' + n + '">body{color:rgb(1, 2, 3)}</style></head><body>x</body></html>');
          w.document.close();
        }""")
    popup = popup_info.value
    assert popup.evaluate("getComputedStyle(document.body).color") == "rgb(1, 2, 3)"


# ── Pages that refuse every style attribute (STRICT_STYLE_PREFIXES) ─────────────────────────────────────────────────

STRICT_ROUTES = [
    "/ai-governance/", "/ai-governance/platform-features", "/ai-governance/systems", "/ai-governance/registers",
    "/ai-governance/monitoring", "/ai-governance/assessments", "/ai-governance/assessments/new",
    "/ai-governance/decisions", "/ai-governance/regulatory", "/ai-governance/packs", "/ai-governance/register",
    "/ai-governance/requests", "/ai-governance/review", "/ai-governance/import",
]


def _refusals(page):
    found = []
    page.on("console", lambda m: "Content Security Policy" in m.text and "style" in m.text and found.append(m.text))
    return found


@pytest.mark.parametrize("persona", ["super_admin", "dpo"])
def test_ai_governance_pages_open_with_style_attributes_refused(login_as, live_app, persona):
    page = login_as(persona)
    refused = _refusals(page)
    for route in STRICT_ROUTES:
        response = page.goto(f"{live_app}{route}")
        page.wait_for_load_state("networkidle", timeout=15000)
        assert "style-src-attr 'none'" in response.headers.get("content-security-policy", ""), route
        assert refused == [], f"{route}: {refused[:2]}"
        assert "!important" not in page.inner_text("body"), f"{route}: style rules are showing as page text"


@pytest.mark.expected_page_errors("the test injects a style attribute, and the browser reports refusing it")
def test_the_shell_works_with_style_attributes_refused(login_as, live_app):
    """Every pop-up the shell builds (notifications, search, shortcuts, reminder, Themis, related items) opens styled
    under the strict rule, and a style attribute injected into the page does nothing."""
    page = login_as("super_admin")
    refused = _refusals(page)
    page.goto(f"{live_app}/ai-governance/")
    page.wait_for_load_state("networkidle", timeout=15000)

    page.click("#notifBtn")
    page.keyboard.press("Escape")
    page.fill("#globalSearch", "zzqx-nothing")
    page.wait_for_selector(".sh-search-none")
    assert page.eval_on_selector("#searchResults", "e => getComputedStyle(e).position") == "absolute"
    page.fill("#globalSearch", "")
    page.mouse.click(700, 500)
    page.keyboard.press("?")
    assert page.eval_on_selector("#shortcutsPanel", "e => getComputedStyle(e).display") == "flex"
    assert page.eval_on_selector(".sh-sc-card", "e => getComputedStyle(e).borderRadius") == "16px"
    page.click("#shortcutsPanel .sh-sc-close")
    assert page.eval_on_selector("#shortcutsPanel", "e => getComputedStyle(e).display") == "none"
    page.click("#reminderOpenBtn")
    assert page.eval_on_selector("#reminderModal", "e => getComputedStyle(e).display") == "flex"
    assert page.eval_on_selector("#remTitle", "e => getComputedStyle(e).borderRadius") == "8px"
    page.click(".sh-rem-close")
    assert page.eval_on_selector("#reminderModal", "e => getComputedStyle(e).display") == "none"
    page.click("[data-trainer-action=toggle] >> nth=0")
    assert page.eval_on_selector(".tr-title-icon", "e => getComputedStyle(e).width") == "18px"

    heading = page.evaluate("""() => {
      const box = document.createElement('div'); document.getElementById('mainContent').appendChild(box);
      RelatedItems.mount(box, 'erm', 'risk', 987654, {canEdit: true});
      return getComputedStyle(box.querySelector('.ri-heading')).textTransform;
    }""")
    assert heading == "uppercase"
    assert refused == [], refused[:2]
    injected = page.evaluate("""() => {
      const d = document.createElement('div'); d.innerHTML = '<p id="zzInjected" style="margin-left:77px">x</p>';
      document.getElementById('mainContent').appendChild(d);
      return getComputedStyle(document.getElementById('zzInjected')).marginLeft;
    }""")
    assert injected != "77px", "an injected style attribute must not apply"
