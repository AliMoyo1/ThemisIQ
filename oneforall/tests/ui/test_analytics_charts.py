"""Interactive analytics charts in the isolated Sage/Dusk browser harness."""
import json
import pytest


def test_analytics_trends_theme_motion_controls_and_resize(login_as, live_app, run_axe):
    page = login_as("super_admin")
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def trend_response(route):
        low = "days=7" in route.request.url
        values = (10, 20, 30) if low else (70, 80, 90)
        payload = [
            {"date": f"2026-10-0{i + 1}", "value": value}
            for i, value in enumerate(values)
        ]
        route.fulfill(status=200, content_type="application/json", body=json.dumps(payload))

    snapshot_posts = []

    def snapshot_response(route):
        snapshot_posts.append(route.request.url)
        route.fulfill(status=200, content_type="application/json", body="{}")

    page.route("**/api/analytics/trends?*", trend_response)
    page.route("**/api/analytics/current", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps([{
            "metric_name": "compliance_pct", "metric_value": 80,
            "module": "aria", "snapshot_date": "2026-10-01",
        }]),
    ))
    page.route("**/api/analytics/snapshot", snapshot_response)

    response = page.goto(f"{live_app}/analytics")
    assert response.status == 200
    page.locator("#chartCompliance .an-chart-point").first.wait_for()
    assert page.locator(".an-chart-area svg").count() == 4
    assert page.locator("#chartCompliance .an-chart-point").count() == 3
    assert page.locator("#chartCompliance .an-chart-line").evaluate(
        "el => getComputedStyle(el).stroke"
    ) == "rgb(24, 123, 85)"

    point = page.locator("#chartCompliance .an-chart-point").first
    point.focus()
    assert page.locator("#chartCompliance .an-chart-tooltip").is_visible()
    assert "70%" in page.locator("#chartCompliance .an-chart-tooltip").inner_text()
    point.press("ArrowRight")
    assert "80%" in page.locator("#chartCompliance .an-chart-tooltip").inner_text()
    assert point.get_attribute("tabindex") == "-1"
    second = page.locator("#chartCompliance .an-chart-point").nth(1)
    assert second.get_attribute("tabindex") == "0"
    second.press("Home")
    assert "70%" in page.locator("#chartCompliance .an-chart-tooltip").inner_text()
    point.hover()
    assert page.locator("#chartCompliance .an-chart-tooltip").is_visible()

    page.locator("#trendDays").select_option("7")
    page.wait_for_function(
        "() => document.querySelector('#chartCompliance .an-chart-point')?.getAttribute('aria-label')?.includes('10%')"
    )

    with page.expect_download() as download:
        page.get_by_role("button", name="Export", exact=True).click()
    assert "analytics" in download.value.suggested_filename

    page.get_by_role("button", name="Refresh Snapshot").click()
    page.wait_for_function("() => !document.querySelector('#snapshotBtn').disabled")
    assert snapshot_posts

    page.locator("#themeToggle").click()
    assert page.locator("html").get_attribute("data-theme") == "dark"
    assert page.locator("#chartCompliance .an-chart-line").evaluate(
        "el => getComputedStyle(el).stroke"
    ) == "rgb(105, 217, 160)"
    assert page.locator("#chartRisks .an-chart-line").evaluate(
        "el => getComputedStyle(el).stroke"
    ) == "rgb(255, 173, 112)"

    page.set_viewport_size({"width": 970, "height": 800})
    page.wait_for_function("""() => {
      const chart = document.querySelector('#chartCompliance');
      const svg = chart.querySelector('svg');
      return Math.abs(Number(svg.viewBox.baseVal.width) - chart.clientWidth) <= 2;
    }""")

    page.emulate_media(reduced_motion="reduce")
    assert page.locator("#chartCompliance .an-chart-series").evaluate(
        "el => getComputedStyle(el).animationDuration"
    ) == "0s"
    violations = run_axe()
    assert not violations, "\n".join(
        f"{v['id']} {n['target']}: {n.get('failureSummary', '')}"
        for v in violations for n in v['nodes']
    )
    assert not errors, errors





@pytest.mark.parametrize("route,arc", [
    ("/", "#ccSlaArc"),
    ("/aria/", "#ariaArcImpl"),
    ("/aria/", "#ariaArcProg"),
    ("/sentinel/", "#snRiskHigh"),
])
def test_dashboard_donut_motion_follows_preference(login_as, live_app, route, arc):
    page = login_as("super_admin")
    page.emulate_media(reduced_motion="reduce")
    response = page.goto(f"{live_app}{route}")
    assert response.status == 200
    ring = page.locator(arc)
    assert ring.count() == 1
    assert ring.evaluate("el => getComputedStyle(el).transitionDuration") == "0s"
    page.locator("#themeToggle").click()
    assert ring.evaluate("el => getComputedStyle(el).transitionDuration") == "0s"
    if arc == "#ccSlaArc":
        assert ring.evaluate("el => getComputedStyle(el).stroke") == "rgb(147, 197, 253)"


def test_latest_analytics_period_wins_when_responses_arrive_out_of_order(login_as, live_app):
    page = login_as("super_admin")
    page.add_init_script("""(() => {
      const originalFetch = window.fetch;
      window.fetch = (input, options) => {
        if (typeof input === 'string' && input.startsWith('/api/analytics/trends?')) {
          const days = new URL(input, location.origin).searchParams.get('days');
          const value = Number(days);
          const body = JSON.stringify([
            {date:'2026-10-01',value},
            {date:'2026-10-02',value:value+1}
          ]);
          return new Promise(resolve => setTimeout(() => resolve(new Response(body, {
            status:200, headers:{'Content-Type':'application/json'}
          })), days === '7' ? 400 : 0));
        }
        return originalFetch(input, options);
      };
    })()""")
    response = page.goto(f"{live_app}/analytics")
    assert response.status == 200
    page.locator("#chartCompliance .an-chart-point").first.wait_for()
    page.locator("#trendDays").select_option("7")
    page.locator("#trendDays").select_option("60")
    page.wait_for_function(
        "() => document.querySelector('#chartCompliance .an-chart-point')?.getAttribute('aria-label')?.includes('60%')"
    )
    page.wait_for_timeout(500)
    assert "60%" in page.locator("#chartCompliance .an-chart-point").first.get_attribute("aria-label")
