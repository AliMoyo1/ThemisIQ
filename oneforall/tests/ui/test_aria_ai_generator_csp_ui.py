"""ARIA's policy generator remains usable with inline scripts and handlers blocked."""


def test_policy_generator_navigation_under_strict_script_policy(login_as, live_app):
    page = login_as("super_admin")
    response = page.goto(f"{live_app}/aria/ai-generator")
    assert response.status == 200
    csp = response.headers["content-security-policy"]
    assert "script-src-attr 'none'" in csp
    assert "'unsafe-inline'" not in csp.split("style-src")[0]
    assert page.locator('script[src="/static/js/aria_ai_generator.js"]').count() == 1
    assert page.locator('script[src="/static/js/aria_pdf_bootstrap.mjs"]').count() == 1
    assert page.locator("[onclick], [onchange], [oninput], [onsubmit]").count() == 0

    page.locator('.gen-tab[data-tab="gap"]').click()
    assert "active" in page.locator("#tab-gap").get_attribute("class")
    page.locator('.gen-tab[data-tab="policy"]').click()
    assert "active" in page.locator("#tab-policy").get_attribute("class")

    if page.locator("#recentHeader").count():
        header = page.locator("#recentHeader")
        header.focus()
        page.keyboard.press("Enter")
        assert page.locator("#recentList").evaluate("(el) => el.style.display") == "none"
        page.keyboard.press("Enter")
        assert page.locator("#recentList").evaluate("(el) => el.style.display") == "flex"

    if page.locator("#fwSelect option").count() > 1:
        page.locator("#fwSelect").select_option(index=1)
        assert page.locator("#ctrlSearch").is_enabled()
    page.wait_for_function("() => !!window.pdfjsLib")
    assert not page.console_errors
