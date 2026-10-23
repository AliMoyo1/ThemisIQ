"""
Real browser: the PDF button beside a DPIA, a continuity plan and an AI impact assessment (decision D16 of
PLAN_record_document_exports_2026-10-22.md).

Each record offers its document where the person looks at the record. A click is traced to the address the page opens (the page's
`window.open` is replaced by a recorder, so no popup is involved) or, for a link, to its address, and that address is then fetched
with the same session: it must be the document, not an error page. The DPIA viewer keeps its plain text download. The role rule is
part of what is checked: a role that cannot open the record is refused the document.
"""
import re
import uuid

from modules.bcm import data_service as bcm_ds
from modules.sentinel import data_service as sentinel_ds
from tests.ui.test_ai_governance_assessments_ui import _create
from tests.ui.test_report_buttons import PDF, _fetch, _is_document, _opened, _record_opens


def _tag():
    return uuid.uuid4().hex[:8]


def test_a_data_protection_officer_downloads_a_dpia_from_its_row_and_the_viewer_keeps_its_text_download(login_as, page, live_app):
    title = f"DPIA {_tag()}"
    dpia = sentinel_ds.create_dpia({"title": title, "status": "completed", "overall_risk": "high", "residual_risk": "medium",
                                    "ai_full_dpia": "# Assessment\n\n## 1. Description\nA draft written by the assistant."}, business_unit_id=None)
    ref = sentinel_ds.get_dpia(dpia)["ref_number"]
    login_as("dpo")
    page.goto(f"{live_app}/sentinel/dpia")
    button = page.get_by_role("link", name=f"Download PDF of {title}")
    button.wait_for()
    assert button.get_attribute("href") == f"/sentinel/api/dpias/{dpia}/document"  # a link, so it downloads where the page is
    assert _is_document(_fetch(page, live_app, f"/sentinel/api/dpias/{dpia}/document"), PDF, re.escape(f"ThemisIQ_privacy_{ref}"))
    # the viewer of the AI draft still has its own plain text download
    page.locator("tr", has_text=title).get_by_title("View generated document").click()
    assert page.locator(".doc-viewer-head button", has_text="Download").is_visible()
    assert page.locator(".doc-viewer-head button", has_text="Copy").is_visible()


def test_a_continuity_manager_downloads_a_plan_from_its_row(login_as, page, live_app):
    title = f"Plan {_tag()}"
    plan = bcm_ds.create_plan({"title": title, "status": "approved", "version": "1.2", "owner": "Test Owner",
                               "content": "# Plan\n\n## 1. Purpose\nRestore the service.\n\n## 2. Steps\n1. Declare\n2. Recover"})
    login_as("bcm_manager")
    page.goto(f"{live_app}/bcm/plans")
    button = page.get_by_role("link", name=f"Download PDF of {title}")
    button.wait_for()
    assert button.get_attribute("href") == f"/bcm/api/plans/{plan}/document"
    stem = re.escape(f"ThemisIQ_continuity_plan_{plan}_{title.replace(' ', '_')}")
    assert _is_document(_fetch(page, live_app, f"/bcm/api/plans/{plan}/document"), PDF, stem)


def test_a_privacy_officer_downloads_an_assessment_from_its_page_and_from_the_list(login_as, page, live_app):
    title = f"Assessment {_tag()}"
    login_as("dpo")
    assessment = _create(page, live_app, title)
    path = f"/ai-governance/api/assessments/{assessment}/document"
    link = page.locator("#aigAssessmentHeader").get_by_role("link", name="Download PDF")
    assert link.get_attribute("href") == path
    reference = page.locator("#aigAssessmentHeader .aig-ref").inner_text()
    assert _is_document(_fetch(page, live_app, path), PDF, re.escape(f"ThemisIQ_ai_governance_{reference}"))
    page.goto(f"{live_app}/ai-governance/assessments?q={title.replace(' ', '+')}")
    row = page.locator("tr", has=page.locator(f"a:has-text('{title}')"))
    row.wait_for()
    assert row.get_by_role("link", name=f"PDF of {reference}").get_attribute("href") == path


QUOTED = 'Quote " autofocus onfocus="window.__injected=1" x="'


def _attributes(button):
    return sorted(button.evaluate("el => el.getAttributeNames()"))


def test_a_dpia_title_with_a_quote_cannot_add_attributes_to_its_button(login_as, page, live_app):
    """The page builds the row as text, and its escape helper leaves quotes alone: a stored title must stay inside the attribute."""
    sentinel_ds.create_dpia({"title": QUOTED + _tag()}, business_unit_id=None)
    login_as("dpo")
    page.goto(f"{live_app}/sentinel/dpia")
    button = page.locator("tr", has_text="autofocus").get_by_title("Download this assessment as a PDF")
    button.wait_for()
    assert _attributes(button) == ["aria-label", "class", "href", "style", "title"], "no attribute came from the title"
    assert button.get_attribute("aria-label").startswith("Download PDF of Quote \" autofocus onfocus=")
    assert page.evaluate("window.__injected") is None


def test_a_plan_title_with_a_quote_cannot_add_attributes_to_its_button(login_as, page, live_app):
    bcm_ds.create_plan({"title": QUOTED + _tag()})
    login_as("bcm_manager")
    page.goto(f"{live_app}/bcm/plans")
    button = page.locator("tr", has_text="autofocus").get_by_title("Download this plan as a PDF")
    button.wait_for()
    assert _attributes(button) == ["aria-label", "class", "href", "style", "title"], "no attribute came from the title"
    assert button.get_attribute("aria-label").startswith("Download PDF of Quote \" autofocus onfocus=")
    assert page.evaluate("window.__injected") is None


def test_nobody_signed_out_is_given_a_document(page, live_app):
    for path in ("/sentinel/api/dpias/1/document", "/bcm/api/plans/1/document", "/ai-governance/api/assessments/1/document"):
        response = page.request.get(live_app + path, max_redirects=0)
        assert response.status in (302, 303) and "/login" in response.headers.get("location", ""), (path, response.status)


def test_a_role_that_cannot_open_the_record_is_refused_the_document(login_as, page, live_app):
    dpia = sentinel_ds.create_dpia({"title": f"DPIA {_tag()}"}, business_unit_id=None)
    plan = bcm_ds.create_plan({"title": f"Plan {_tag()}"})
    login_as("employee")        # reaches the continuity module, not the DPIAs and not the AI impact assessments
    assert _fetch(page, live_app, f"/sentinel/api/dpias/{dpia}/document").status == 403
    assert _fetch(page, live_app, "/ai-governance/api/assessments/1/document").status == 403
    assert _is_document(_fetch(page, live_app, f"/bcm/api/plans/{plan}/document"), PDF, "ThemisIQ_continuity_plan_" + str(plan) + "_Plan_[0-9a-f]{8}")
