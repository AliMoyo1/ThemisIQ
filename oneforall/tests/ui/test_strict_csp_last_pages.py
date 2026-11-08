"""The last pages moved off inline scripts (plans/csp-script-migration-2026-10.md): the Command Centre, the report print
view, data readiness, evidence campaigns and the error page. Each runs under the strict script policy with no console
error, and its buttons still work through listeners."""
from playwright.sync_api import expect


def _watch(page):
    problems = []
    page.on("console", lambda m: problems.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: problems.append(str(e)))
    return problems


def _strict(response, path):
    policy = response.headers["content-security-policy"]
    script = policy.split("script-src ", 1)[1].split(";", 1)[0]
    assert "'unsafe-inline'" not in script and "script-src-attr 'none'" in policy, path
    assert "content-security-policy-report-only" not in response.headers, path


def test_the_command_centre_works_through_its_listener(login_as, live_app):
    page = login_as("super_admin")
    problems = _watch(page)
    _strict(page.goto(f"{live_app}/"), "/")
    page.wait_for_load_state("networkidle")
    assert page.locator("[onclick],[onmouseover],[onmouseout]").count() == 0
    assert page.evaluate("document.getElementById('ccPageConfig').dataset.isAdmin") == "1"

    body = page.locator("#prBody")
    was_open = body.is_visible()  # the panel may already be open on load
    page.locator("#prBar").click()
    expect(body).to_be_hidden() if was_open else expect(body).to_be_visible()
    page.locator("#prBar").click()
    expect(body).to_be_visible() if was_open else expect(body).to_be_hidden()

    chips = page.locator("#ccModuleFilters [data-cc-filter]")
    if chips.count() > 1:
        chips.nth(1).click()
        expect(chips.nth(1)).to_have_class("filter-chip active")

    page.evaluate("""() => {
        const a = document.createElement('div');
        a.setAttribute('data-cc-href', '//evil.example/');
        a.id = 'ccPlanted';
        a.textContent = 'planted';
        document.body.appendChild(a);
    }""")
    page.locator("#ccPlanted").click()
    page.wait_for_timeout(300)
    assert page.url.rstrip("/") == live_app.rstrip("/"), "a link to another site is refused"

    page.locator('[data-cc-href="/workflows"]').first.click()
    expect(page).to_have_url(f"{live_app}/workflows")
    assert problems == [], problems


def test_the_report_print_view_prints_under_the_strict_policy(login_as, live_app):
    page = login_as("compliance_manager")
    run = page.evaluate("""async () => {
        const r = await fetch('/api/reports/quick-run', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                                          body: JSON.stringify({report_type: 'audit_status'})});
        return r.json();
    }""")
    problems = _watch(page)
    path = f"/reports/runs/{run['run_id']}/print"
    _strict(page.goto(f"{live_app}{path}"), path)
    page.evaluate("() => { window.__printed = 0; window.print = () => { window.__printed += 1; }; }")
    page.locator("[data-report-print]").click()
    assert page.evaluate("window.__printed") == 1
    assert problems == [], problems


def test_readiness_and_evidence_campaigns_load_from_their_own_scripts(login_as, live_app):
    page = login_as("super_admin")
    problems = _watch(page)
    _strict(page.goto(f"{live_app}/readiness"), "/readiness")
    expect(page.locator("#rdTableBody")).not_to_contain_text("Loading", timeout=10000)
    _strict(page.goto(f"{live_app}/evidence-campaigns"), "/evidence-campaigns")
    expect(page.locator("#ecCampaignsTab")).not_to_contain_text("Loading", timeout=10000)
    page.locator('.ec-tab[data-tab="mine"]').click()
    expect(page.locator("#ecMineTab")).to_be_visible()
    assert problems == [], problems


def test_the_error_page_goes_back_without_a_script_url(login_as, live_app):
    page = login_as("employee")
    page.goto(f"{live_app}/workflows")
    response = page.goto(f"{live_app}/no-such-page-anywhere")
    assert response.status == 404
    _strict(response, "/no-such-page-anywhere")
    expect(page.locator(".error-title")).to_be_visible()
    back = page.get_by_role("link", name="Go Back")
    expect(back).to_have_attribute("href", "/")
    back.click()
    expect(page).to_have_url(f"{live_app}/workflows")
