"""
PLAN-36 T06 (findings.md F08, "Command Centre" named explicitly): served at
`/`, the first page every user sees after login. Had no browser coverage at
all. loadDashboard()/loadBriefing() keep their existing quiet-fallback
pattern (a real static fallback object, not just silence) deliberately;
the four genuine mutations (advisory ack, prediction ack, two report
generators) previously showed a generic message or no message at all on
failure and now show the server's real detail.
"""


def test_root_page_loads_without_console_errors(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/")
    page.wait_for_load_state("networkidle", timeout=10000)
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


def test_ack_advisory_shows_the_real_error_and_reenables_on_failure(login_as, live_app):
    """Previously: a failed ack silently reset the button with zero
    indication anything went wrong."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/")
    page.wait_for_load_state("networkidle", timeout=10000)
    page.route("**/api/advisories/1/ack", lambda r: r.fulfill(
        status=403, content_type="application/json",
        body='{"detail": "You do not have permission to acknowledge this advisory."}'))
    result = page.evaluate("""
        async () => {
          const btn = document.createElement('button');
          document.body.appendChild(btn);
          const wrap = document.createElement('div');
          const inner = document.createElement('div');
          wrap.appendChild(inner);
          inner.appendChild(btn);
          document.body.appendChild(wrap);
          await window.ackAdvisory(1, btn);
          return {disabled: btn.disabled, text: btn.textContent};
        }
    """)
    assert result["disabled"] is False
    page.wait_for_selector(".toast-error", timeout=5000)
    assert "do not have permission" in page.locator(".toast-error").inner_text()
