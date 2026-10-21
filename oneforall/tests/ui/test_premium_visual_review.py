"""Browser review of the premium chart and dashboard visual contract.

Runs against the isolated UI harness. Set THEMIS_BROWSER_REVIEW_SCREENSHOTS=1
to save review captures under the git-ignored pics/browser-review directory.
"""
import json
import os
from pathlib import Path

import database


DASHBOARDS = [
    ("/", "command-centre"),
    ("/aria/", "aria"),
    ("/governance/", "governance"),
    ("/grid/", "grid"),
    ("/bcm/", "bcm"),
    ("/sentinel/", "sentinel"),
    ("/erm/", "erm"),
    ("/orm/", "orm"),
    ("/analytics", "analytics"),
]

CHARTS = {
    "/": "#ccSlaPanel",
    "/aria/": "#ariaControlPanel",
    "/grid/": "#gridEvidenceDonut",
    "/bcm/": "#bcmRiskDonut",
    "/sentinel/": "#snRiskDonut",
    "/erm/": "#ermHeatMap",
    "/orm/": "#ormTypeChart",
    "/analytics": "#chartCompliance",
}



def test_premium_dashboards_in_sage_dusk_and_mobile(login_as, live_app, synthetic_tenant):
    page = login_as("super_admin")
    captures = os.environ.get("THEMIS_BROWSER_REVIEW_SCREENSHOTS") == "1"
    output = Path(__file__).resolve().parents[3] / "pics" / "browser-review"
    if captures:
        output.mkdir(parents=True, exist_ok=True)

    for route, name in DASHBOARDS:
        page.set_viewport_size({"width": 1440, "height": 900})
        page.evaluate("localStorage.setItem('ofa-theme', 'light')")
        response = page.goto(f"{live_app}{route}")
        assert response.status == 200, (route, response.status)
        page.wait_for_load_state("networkidle", timeout=15000)
        page.evaluate("() => document.fonts.ready")
        assert page.locator("html").get_attribute("data-theme") in (None, "light")
        assert page.evaluate("getComputedStyle(document.body).fontFamily.includes('Manrope')"), route
        assert page.evaluate("document.fonts.check('400 16px Manrope')"), route
        assert page.locator('script[src*="premium_charts.js"]').count() == 1
        edges = page.evaluate("""() => [...document.querySelectorAll('.stat-card:not(.stat-card-hero)')]
          .map(card => ({
            border: parseFloat(getComputedStyle(card).borderTopWidth),
            stripe: getComputedStyle(card, '::before').content,
            inline: card.style.borderTop
          }))""")
        assert all(e["border"] <= 1.1 and e["stripe"] in ("none", "normal")
                   and not e["inline"] for e in edges), (route, edges)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2"), route
        if captures:
            page.screenshot(path=str(output / f"{name}-sage-desktop.png"), full_page=True)

        page.locator("#themeToggle").click()
        assert page.locator("html").get_attribute("data-theme") == "dark"
        assert page.evaluate("getComputedStyle(document.body).fontFamily.includes('Manrope')"), route
        if captures:
            page.screenshot(path=str(output / f"{name}-dusk-desktop.png"), full_page=True)

        if route in CHARTS:
            chart = page.locator(CHARTS[route])
            assert chart.count() == 1 and chart.is_visible(), (route, CHARTS[route])
            chart.scroll_into_view_if_needed()
            if captures:
                page.screenshot(path=str(output / f"{name}-dusk-chart.png"))

        page.evaluate("document.getElementById('mainContent').scrollTop = 0")
        page.set_viewport_size({"width": 390, "height": 844})
        page.wait_for_timeout(300)
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth + 2"), route
        if route == "/governance/":
            action = page.locator("#govAddBtn").bounding_box()
            assert action and action["width"] > 200 and action["height"] < 65
            assert page.locator("#govSummary .gov-stat").evaluate_all(
                "els => els.every(el => el.getBoundingClientRect().right <= innerWidth + 2)"
            )
        if captures:
            page.screenshot(path=str(output / f"{name}-dusk-mobile.png"), full_page=True)
        if route == "/governance/":
            page.locator('.gov-tab[data-tab="reg"]').click()
            assert "active" in page.locator('.gov-tab[data-tab="reg"]').get_attribute("class")

    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO aria_documents "
            "(doc_id, framework, control_ref, title, version, status, body, "
            "org_id, business_unit_id, owner_user_id, policy_workflow_managed, "
            "owner, approver) "
            "VALUES (%s,'ISO 27001','A.1','Visual Review Document','1.0','Approved',"
            "'Synthetic body',%s,%s,%s,0,'Review Owner','Review Approver')",
            (
                "DOC-VISUAL-REVIEW-01", synthetic_tenant["org_id"],
                synthetic_tenant["business_unit_id"],
                synthetic_tenant["users"]["compliance_manager"]["user_id"],
            ),
        )
        db.commit()
    finally:
        db.close()

    page.context.clear_cookies()
    page = login_as("compliance_manager")
    page.set_viewport_size({"width": 1440, "height": 900})
    page.evaluate("localStorage.setItem('ofa-theme', 'light')")
    response = page.goto(f"{live_app}/aria/documents")
    page.wait_for_load_state("networkidle", timeout=15000)
    if captures:
        page.screenshot(path=str(output / "aria-documents-sage-desktop.png"), full_page=True)
    headers = page.locator(".data-table th")
    assert response.status == 200 and headers.count() > 0, (response.status, page.url, page.locator("body").inner_text()[:250])
    assert all("Manrope" in f for f in headers.evaluate_all(
        "els => els.map(el => getComputedStyle(el).fontFamily)"
    ))
    assert all(t == "none" for t in headers.evaluate_all(
        "els => els.map(el => getComputedStyle(el).textTransform)"
    ))





def test_chart_entrance_respects_reduced_motion(login_as, live_app):
    page = login_as("super_admin")
    page.add_init_script("""(() => {
      window.__premiumLineAnimations = 0;
      const original = Element.prototype.animate;
      Element.prototype.animate = function (...args) {
        if (this.matches('.an-chart-line')) window.__premiumLineAnimations++;
        return original.apply(this, args);
      };
    })()""")
    payload = json.dumps([
        {"date": "2026-10-01", "value": 70},
        {"date": "2026-10-02", "value": 80},
        {"date": "2026-10-03", "value": 90},
    ])
    page.route("**/api/analytics/trends?*", lambda route: route.fulfill(
        status=200, content_type="application/json", body=payload
    ))
    page.route("**/api/analytics/current", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps([{
            "metric_name": "compliance_pct", "metric_value": 90,
            "module": "aria", "snapshot_date": "2026-10-03",
        }])
    ))

    def live_response(route):
        response = route.fetch()
        data = response.json()
        data["compliance_pct"] = 90
        route.fulfill(response=response, body=json.dumps(data))

    page.route("**/api/command-centre/stats", live_response)
    page.goto(f"{live_app}/analytics")
    line = page.locator("#chartCompliance .an-chart-line")
    line.wait_for()
    line.scroll_into_view_if_needed()
    page.wait_for_function("() => window.__premiumLineAnimations > 0")
    assert page.locator("#compVal").inner_text() == "90%"
    if os.environ.get("THEMIS_BROWSER_REVIEW_SCREENSHOTS") == "1":
        output = Path(__file__).resolve().parents[3] / "pics" / "browser-review"
        output.mkdir(parents=True, exist_ok=True)
        page.locator("#chartCompliance").locator("..").screenshot(
            path=str(output / "analytics-populated-sage-chart.png")
        )
        page.locator("#themeToggle").click()
        page.locator("#chartCompliance").locator("..").screenshot(
            path=str(output / "analytics-populated-dusk-chart.png")
        )

    page.emulate_media(reduced_motion="reduce")
    page.reload()
    line = page.locator("#chartCompliance .an-chart-line")
    line.wait_for()
    line.scroll_into_view_if_needed()
    page.wait_for_timeout(950)
    assert page.evaluate("window.__premiumLineAnimations") == 0
