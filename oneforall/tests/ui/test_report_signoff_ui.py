"""Browser check for the frozen Needs attention acknowledgement on saved reports."""

import json


def test_independent_signoff_sends_explicit_assurance_review(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/reports")
    page.wait_for_selector("#reportViewer", state="attached")
    page.evaluate("""() => viewRunData({
      run_id: 777, report_name: 'Synthetic review copy', report_type: 'privacy_overview',
      frozen: true, hash: 'synthetic-hash', result: {}, notes: [], signoffs: [], shares: [],
      retention: {}, can_signoff: true, can_share: false, can_manage_retention: false,
      snapshot: {run: {generated_at: '2026-11-05', definition_version: 1},
                 scope: {org_name: 'Synthetic'}, assurance: {state: 'partial', open: 2,
                 scope_note: 'Two issues in the author scope were visible at generation.'}}
    })""")
    assert page.locator("#reportAssuranceReviewed").count() == 1
    assert "2 open" in page.locator("#viewerGovernance").inner_text()
    def refuse(route):
        route.fulfill(status=400, content_type="application/json",
                      body='{"error":"The frozen assurance state needs review."}')

    page.route("**/api/reports/runs/777/signoff", refuse)
    page.locator("#reportSignoffReason").fill("Reviewed this synthetic snapshot and its limitations")
    with page.expect_request("**/api/reports/runs/777/signoff") as first:
        page.get_by_role("button", name="Record independent decision").click()
    page.wait_for_function("() => document.querySelector('#reportNotice').textContent.includes('needs review')")
    assert json.loads(first.value.post_data)["assurance_reviewed"] is False
    page.locator("#reportAssuranceReviewed").check()
    with page.expect_request("**/api/reports/runs/777/signoff") as second:
        page.get_by_role("button", name="Record independent decision").click()
    assert json.loads(second.value.post_data)["assurance_reviewed"] is True
