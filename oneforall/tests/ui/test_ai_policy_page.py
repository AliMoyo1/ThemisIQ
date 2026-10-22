"""
AI governance G1c: the AI Policy page in a real browser.

An organization administrator sees what the platform currently does, sets a policy, sees at once what each feature
will do under it, and finds the saved policy again after a reload. Nobody else reaches the page, a policy that would
silently widen access is not sent, and the page has no accessibility violations and no sideways scroll on a phone.
"""

import pytest

import database


@pytest.fixture(autouse=True)
def _start_and_end_with_no_policy(synthetic_tenant):
    """The harness database lasts the whole session; every test here begins from an organization with no policy."""
    def clear():
        db = database.get_db()
        try:
            db.execute("DELETE FROM settings WHERE key LIKE 'ai.policy.org%'")
            db.commit()
        finally:
            db.close()

    clear()
    yield
    clear()


def _open(login_as, live_app, persona="org_admin"):
    page = login_as(persona)
    page.goto(f"{live_app}/admin/ai-policy")
    page.wait_for_selector("#panel:not([hidden])")
    return page


def _feature_row(page, label):
    return page.locator("#featureRows tr", has=page.locator(f"td:text-is('{label}')"))


def test_the_page_starts_with_ai_blocked_until_a_policy_is_approved(login_as, live_app):
    page = _open(login_as, live_app)
    assert "No policy has been approved" in page.locator("#policyState").inner_text()
    assert "AI requests are blocked" in page.locator("#policyState").inner_text()
    assert not page.locator("#enabled").is_checked()
    assert not page.locator("#approvePolicy").is_checked()
    assert page.locator("input[name='providerMode'][value='any']").is_checked()
    assert page.locator("#categoryList input:checked").count() == 4
    assert page.locator("#featureRows input:checked").count() == page.locator("#featureRows input").count() >= 50
    assert set(page.locator("#featureRows [data-effect]").all_inner_texts()) == {"Off: AI features are off"}
    assert page.locator("#activeProvider").inner_text().strip() != ""


def test_a_saved_policy_shows_its_effect_at_once_and_survives_a_reload(login_as, live_app):
    page = _open(login_as, live_app)
    page.check("#enabled")
    page.check("input[name='providerMode'][value='only']")
    page.check("#providerList input[value='anthropic']")
    page.check("#providerList input[value='ollama']")
    page.uncheck("#categoryList input[value='personal']")
    _feature_row(page, "Ask ARIA").locator("input").uncheck()
    page.fill("#budget", "12345")

    # Before saving, the table already says what each feature will do.
    assert "personal data is not allowed" in _feature_row(page, "Assess a breach").locator("[data-effect]").inner_text()
    assert "switched off" in _feature_row(page, "Ask ARIA").locator("[data-effect]").inner_text()
    assert _feature_row(page, "Draft a policy").locator("[data-effect]").inner_text() == "On"

    page.check("#approvePolicy")
    page.click("#saveBtn")
    page.wait_for_selector("#saveStatus:text-is('Saved')")
    assert "A policy is set" in page.locator("#policyState").inner_text()

    page.reload()
    page.wait_for_selector("#panel:not([hidden])")
    assert page.locator("input[name='providerMode'][value='only']").is_checked()
    assert page.locator("#providerList input:checked").evaluate_all("els => els.map(e => e.value).sort()") == [
        "anthropic", "ollama"]
    assert not page.locator("#categoryList input[value='personal']").is_checked()
    assert page.locator("#categoryList input:checked").count() == 3
    assert not _feature_row(page, "Ask ARIA").locator("input").is_checked()
    assert page.input_value("#budget") == "12345"
    assert "personal data is not allowed" in _feature_row(page, "Assess a breach").locator("[data-effect]").inner_text()

    # Switching AI off as a whole shows on every row.
    page.uncheck("#enabled")
    assert set(page.locator("#featureRows [data-effect]").all_inner_texts()) == {"Off: AI features are off"}


def test_naming_only_some_providers_but_choosing_none_is_not_sent(login_as, live_app):
    page = _open(login_as, live_app)
    page.check("#enabled")
    page.check("#approvePolicy")
    sent = []
    page.on("request", lambda r: sent.append(r.method) if r.url.endswith("/api/admin/ai-policy") and r.method == "PUT" else None)
    page.check("input[name='providerMode'][value='only']")
    page.click("#saveBtn")
    page.wait_for_selector("#saveStatus:has-text('Choose at least one provider')")
    assert sent == [], "an empty list would have meant any provider"


def test_the_server_refusal_is_shown_and_nothing_is_marked_saved(login_as, live_app):
    page = _open(login_as, live_app)
    page.check("#enabled")
    page.check("#approvePolicy")
    page.route("**/api/admin/ai-policy", lambda r: r.fulfill(
        status=400, content_type="application/json", body='{"ok": false, "error": "Unknown provider: nope."}')
        if r.request.method == "PUT" else r.continue_())
    page.click("#saveBtn")
    page.wait_for_selector("#saveStatus:has-text('Not saved')")
    assert "Unknown provider: nope." in page.locator("#saveStatus").inner_text()


def test_other_roles_cannot_open_the_page(login_as, live_app):
    page = login_as("employee")
    response = page.goto(f"{live_app}/admin/ai-policy")
    assert response.status == 403
    assert page.locator("#panel").count() == 0


def test_the_page_has_no_serious_accessibility_violations(login_as, live_app, run_axe):
    page = _open(login_as, live_app)
    assert run_axe() == []


def test_the_page_fits_a_phone_without_sideways_scroll(login_as, live_app):
    page = _open(login_as, live_app)
    page.set_viewport_size({"width": 375, "height": 812})
    page.wait_for_timeout(200)
    assert page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
