"""The group work page shows only actions the signed-in specialist may perform."""

from playwright.sync_api import expect
import json


def test_group_sharing_specialist_page_and_scoped_search(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/evidence/group/")
    expect(page.get_by_role("heading", name="Group sharing")).to_be_visible()
    expect(page.locator("#gsPropose")).to_be_hidden()
    expect(page.locator("#gsPublish")).to_be_visible()
    search = page.get_by_label("Find a source document by title")
    search.fill("nonexistent-specific-title-4727")
    expect(page.locator("#gsEvidenceResult")).to_contain_text("0 matching source documents shown")
    expect(page.locator("#gsPublish select[name=evidence_id] option")).to_have_count(1)


def test_group_grants_can_page_and_open_an_older_review(login_as, live_app):
    page = login_as("org_admin")
    def grant_response(route):
        page_number = int(route.request.url.rsplit("page=", 1)[1])
        ids = range(1, 51) if page_number == 1 else range(51, 52)
        route.fulfill(status=200, content_type="application/json", body=json.dumps({
            "items": [{"id": number, "source_name": "Child Co", "recipient_name": f"Person {number}",
                       "user_id": number, "capability": "document.view", "can_review": True,
                       "review_due_at": "2026-12-01T00:00:00Z", "expires_at": "2026-12-15T00:00:00Z",
                       "review_overdue": False, "last_matching_access_at": None} for number in ids],
            "page": page_number, "has_more": page_number == 1,
        }))
    page.route("**/evidence/api/group/grants?page=*", grant_response)
    page.goto(f"{live_app}/evidence/group/")
    expect(page.locator("#gsGrantRows .gs-row")).to_have_count(50)
    page.get_by_role("button", name="Show more access grants").click()
    expect(page.locator("#gsGrantRows .gs-row")).to_have_count(51)
    page.locator("#gsGrantRows .gs-row").last.get_by_role("button", name="Review access").click()
    expect(page.locator("#gsReviewTarget")).to_contain_text("Person 51")


def test_group_grant_queue_live_route_for_own_tenant(login_as, live_app):
    page = login_as("org_admin")
    page.goto(f"{live_app}/evidence/group/")
    expect(page.locator("#gsGrantResult")).to_contain_text("active grants shown")
    response = page.evaluate("""async () => {
      const r = await fetch('/evidence/api/group/grants?page=1');
      return {status: r.status, body: await r.json()};
    }""")
    assert response["status"] == 200
    assert response["body"]["page"] == 1
    assert response["body"]["items"] == []
