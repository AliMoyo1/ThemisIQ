"""
Real browser: the report buttons on the Privacy, Enterprise Risk, Operations Risk and Resilience pages.

Each module page offers its report where the person looks for it. A click is traced to the address the page opens (the page's
`window.open` is replaced by a recorder, so no popup is involved), and that address is then fetched with the same session: it must
be the document, not an error page. The role rule is part of what is checked: a role that cannot open the breach list is not
offered the breach report.
"""
import re

PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _record_opens(page):
    page.evaluate("() => { window.__opened = []; window.open = (url) => { window.__opened.push(url); return null; }; }")


def _opened(page):
    return page.evaluate("() => window.__opened")


def _labels(page):
    """The tile labels as written in the page (inner_text would return them upper cased by the page's CSS)."""
    return [text.strip() for text in page.locator("#view-reports .stat-card .stat-label").all_text_contents()]


def _reports_page(page, live_app, module):
    page.goto(f"{live_app}/{module}/reports")
    page.wait_for_selector("#view-reports", state="visible")


def _fetch(page, live_app, path):
    return page.request.get(live_app + path)


def _is_document(response, content_type, stem):
    disposition = response.headers.get("content-disposition", "")
    return (response.status == 200 and response.headers.get("content-type", "").startswith(content_type)
            and re.fullmatch(rf'attachment; filename="{stem}_\d{{8}}_\d{{4}}\.(pdf|xlsx|csv)"', disposition) is not None
            and response.headers.get("x-content-type-options") == "nosniff")


def test_the_privacy_reports_page_downloads_each_document_for_a_data_protection_officer(login_as, page, live_app):
    login_as("dpo")
    _reports_page(page, live_app, "sentinel")
    cards = page.locator("#view-reports .stat-card")
    assert _labels(page) == ["Audit Trail", "RoPA Report", "Compliance Score", "Breach Report"]
    # the tile is filled once the score has been read: it says a figure or "Not measured", never the old `--%`
    page.wait_for_function("() => /^(Not measured|\\d+%)$/.test(document.getElementById('snCompScore').textContent.trim())")
    _record_opens(page)
    cards.filter(has_text="Audit Trail").click()
    cards.filter(has_text="RoPA Report").locator(".stat-label").click()
    cards.filter(has_text="RoPA Report").get_by_role("button", name="Excel").click()
    cards.filter(has_text="Compliance Score").locator(".stat-label").click()
    cards.filter(has_text="Breach Report").locator(".stat-label").click()
    assert _opened(page) == ["/sentinel/api/audit/export", "/sentinel/api/reports/ropa?format=pdf", "/sentinel/api/reports/ropa?format=xlsx",
                             "/sentinel/api/reports/compliance?format=pdf", "/sentinel/api/reports/breach?format=pdf"]
    assert _is_document(_fetch(page, live_app, "/sentinel/api/audit/export"), "text/csv", "ThemisIQ_privacy_audit_trail")
    assert _is_document(_fetch(page, live_app, "/sentinel/api/reports/ropa?format=pdf"), PDF, "ThemisIQ_privacy_ropa")
    assert _is_document(_fetch(page, live_app, "/sentinel/api/reports/ropa?format=xlsx"), XLSX, "ThemisIQ_privacy_ropa")
    assert _is_document(_fetch(page, live_app, "/sentinel/api/reports/compliance?format=pdf"), PDF, "ThemisIQ_privacy_compliance_score")
    assert _is_document(_fetch(page, live_app, "/sentinel/api/reports/breach?format=pdf"), PDF, "ThemisIQ_privacy_breach_register")


def test_a_privacy_analyst_is_not_offered_the_breach_report_and_is_refused_it(login_as, page, live_app):
    login_as("privacy_analyst")
    _reports_page(page, live_app, "sentinel")
    assert _labels(page) == ["Audit Trail", "RoPA Report", "Compliance Score"]
    assert _fetch(page, live_app, "/sentinel/api/reports/breach?format=pdf").status == 403
    assert _is_document(_fetch(page, live_app, "/sentinel/api/reports/ropa?format=pdf"), PDF, "ThemisIQ_privacy_ropa")


def _board_report_button(login_as, page, live_app, persona, module, path, stem):
    login_as(persona)
    _reports_page(page, live_app, module)
    button = page.get_by_role("button", name="Board Report PDF")
    assert button.is_visible()
    assert page.get_by_role("button", name="AI Narrative").count() + page.get_by_role("button", name="Generate AI Narrative").count() >= 1
    _record_opens(page)
    button.click()
    assert _opened(page) == [path]
    assert _is_document(_fetch(page, live_app, path), PDF, stem)
    assert _is_document(_fetch(page, live_app, path + "?format=xlsx"), XLSX, stem)


def test_the_enterprise_risk_page_offers_the_board_report_document(login_as, page, live_app):
    _board_report_button(login_as, page, live_app, "risk_owner", "erm", "/erm/api/board-report/document", "ThemisIQ_enterprise_risk_board_report")


def test_the_operations_risk_page_offers_the_board_report_document(login_as, page, live_app):
    _board_report_button(login_as, page, live_app, "risk_owner", "orm", "/orm/api/board-report/document", "ThemisIQ_operations_risk_board_report")


def test_the_resilience_page_offers_the_board_report_document(login_as, page, live_app):
    _board_report_button(login_as, page, live_app, "bcm_manager", "bcm", "/bcm/api/board-report/document", "ThemisIQ_continuity_board_report")
