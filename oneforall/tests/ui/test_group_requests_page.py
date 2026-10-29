"""Proof request navigation stays available to authorized specialists."""

from playwright.sync_api import expect


def test_proof_request_page_empty_state_and_vault_navigation(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/evidence/group/requests/")
    expect(page.get_by_role("heading", name="Proof requests")).to_be_visible()
    expect(page.locator("#grStatus")).not_to_contain_text("unavailable")
    expect(page.locator("#grList")).to_contain_text("No proof requests in your scope")
    expect(page.locator("#grCreate")).to_be_hidden()
    page.get_by_role("link", name="Evidence Vault").first.click()
    expect(page.locator(".page-title")).to_contain_text("Evidence Vault")


def test_policy_adoption_page_requires_named_parent_policy(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/evidence/group/adoption/")
    expect(page.get_by_role("heading", name="Policy adoption")).to_be_visible()
    expect(page.locator("#gaList")).to_contain_text("No published parent policies")
    expect(page.locator("#gaMore")).to_be_hidden()


def test_verdict_history_does_not_render_inaccessible_release_or_html(login_as, live_app):
    page = login_as("compliance_manager")
    page.route("**/evidence/api/group/requests?page=1", lambda route: route.fulfill(json={
        "items": [{"id": 91, "requirement_ref": "Parent requirement", "status": "fulfilled",
                   "purpose": "Review proof", "needed_by": "2099-01-01", "period_start": None,
                   "period_end": None, "is_source": False, "verdict": "accepted",
                   "can_revise": False, "can_map": False, "can_fulfill": False,
                   "can_review_verdict": False, "released_publication_id": None}],
        "relationships": [], "has_more": False,
    }))
    page.route("**/evidence/api/group/requests/91/verdict-history", lambda route: route.fulfill(json={
        "items": [
            {"outcome": "accepted", "reviewed_at": "2026-10-29", "reason": "Reviewed",
             "released_publication_id": 41, "title": "<script>alert(1)</script>"},
            {"outcome": "returned", "reviewed_at": "2026-10-28", "reason": "Wrong period",
             "released_publication_id": None, "title": None},
        ],
    }))
    page.goto(f"{live_app}/evidence/group/requests/")
    page.get_by_role("button", name="Decision history").click()
    expect(page.locator(".gr-history-item")).to_have_count(2)
    expect(page.locator(".gr-history-item script")).to_have_count(0)
    expect(page.get_by_role("link", name="<script>alert(1)</script>")).to_have_attribute(
        "href", "/evidence/api/group/publications/41")
    expect(page.get_by_text("This release is no longer available to you")).to_be_visible()
