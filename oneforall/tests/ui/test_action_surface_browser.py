"""Census of rendered controls across the principal application views.

This detects unnamed controls, malformed inline handlers, and handler names
that would be undefined if the user activated them. Mutation behavior is
covered by focused workflow tests; the census has no side effects.
"""

ROUTES = [
    "/", "/projects", "/tasks", "/workflows", "/reports", "/calendar",
    "/analytics", "/risk-register", "/vendors", "/evidence",
    "/aria/", "/aria/documents", "/aria/frameworks", "/aria/risks",
    "/grid/", "/grid/audits", "/grid/controls", "/grid/vendors",
    "/sentinel/", "/sentinel/ropa", "/sentinel/dpia", "/sentinel/breaches", "/sentinel/dsr", "/sentinel/vendors",
    "/erm/", "/erm/register", "/erm/scenario-studio",
    "/governance/",
] + [f"/bcm/{view}" for view in (
    "bia", "plans", "incidents", "exercises", "risks", "dependencies",
    "training", "reports", "chat", "documents", "compliance", "vendors",
    "comms", "contacts", "scenarios",
)] + [f"/orm/{view}" for view in (
    "events", "indicators", "reports", "chat", "assessment", "ai-controls", "aims",
)]


def test_rendered_button_names_and_inline_handlers(login_as, live_app):
    page = login_as("super_admin")
    checked = 0
    for route in ROUTES:
        response = page.goto(f"{live_app}{route}")
        assert response.status == 200, (route, response.status)
        page.wait_for_load_state("networkidle", timeout=15000)
        result = page.evaluate("""() => {
          const issues = [];
          const controls = [...document.querySelectorAll('button, input[type=button], input[type=submit]')];
          controls.forEach(el => {
            if (!el.getClientRects().length || getComputedStyle(el).visibility === 'hidden') return;
            const name = (el.getAttribute('aria-label') || el.getAttribute('title') || el.textContent || el.value || '').trim();
            if (!name) issues.push(['unnamed button', el.outerHTML.slice(0, 140)]);
          });
          document.querySelectorAll('[onclick]').forEach(el => {
            const action = el.getAttribute('onclick');
            if (!action?.trim()) { issues.push(['empty click handler', el.outerHTML.slice(0, 140)]); return; }
            try { new Function('event', action); }
            catch(e) { issues.push(['invalid click handler', action.slice(0, 120)]); return; }
            const match = action.match(/^\\s*(?:return\\s+)?([A-Za-z_$][\\w$]*)\\s*\\(/);
            if (match && !['if', 'switch', 'for', 'while', 'function'].includes(match[1])) {
              try { if (typeof eval(match[1]) !== 'function') issues.push(['missing handler', match[1]]); }
              catch(e) { issues.push(['missing handler', match[1]]); }
            }
          });
          return {count: controls.length, issues};
        }""")
        checked += result["count"]
        assert not result["issues"], (route, result["issues"][:12])
        assert not page.console_errors, (route, page.console_errors[:6])
    assert checked > 300, checked
