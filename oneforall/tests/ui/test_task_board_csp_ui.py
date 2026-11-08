"""Generated task cards and AI suggestions work without executable attributes."""

import json


def test_generated_task_actions_under_strict_script_policy(login_as, live_app):
    page = login_as("super_admin")
    task = {
        "id": 17, "title": "<img src=x onerror=alert(1)>",
        "description": "Review supplier", "module": "platform",
        "priority": "high", "status": "todo", "due_date": "2026-11-30",
        "assigned_to": None, "assigned_name": None, "tags": None,
        "entity_type": None, "entity_id": None,
    }
    updates = []
    moves = []

    def bulk_response(route):
        updates.append(json.loads(route.request.post_data))
        route.fulfill(status=200, content_type="application/json", body='{"updated":1}')

    page.route("**/api/tasks", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps([task])))
    page.route("**/api/tasks/stats", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body='{"by_status":{"todo":1},"my_pending":0,"overdue":0}'))
    page.route("**/api/tasks/bulk", bulk_response)
    page.route("**/api/tasks/17", lambda route: (
        moves.append(json.loads(route.request.post_data)),
        route.fulfill(status=200, content_type="application/json", body='{"ok":true}')))
    page.route("**/api/tasks/ai-prioritize", lambda route: route.fulfill(
        status=200, content_type="application/json",
        body=json.dumps({"ranked": [{
            "task_id": 17, "rank": 1, "suggested_priority": "critical",
            "rationale": "<svg/onload=alert(1)>",
        }]})))

    response = page.goto(f"{live_app}/tasks")
    assert response.status == 200
    policy = response.headers["content-security-policy"]
    assert "script-src-attr 'none'" in policy
    assert "'unsafe-inline'" not in policy.split("style-src")[0]
    assert page.locator('script:not([src]), [onclick], [onchange], [ondrop], [ondragstart]').count() == 0
    assert page.locator('script[src="/static/js/task_board.js"]').count() == 1

    card = page.locator('.task-card[data-id="17"]')
    card.wait_for()
    assert task["title"] in card.inner_text()
    assert page.locator("#col-todo img[onerror]").count() == 0
    card.focus()
    card.press("Enter")
    page.locator("#taskDrawer.open").wait_for()
    assert page.locator("#ddTitle").input_value() == task["title"]
    page.locator("#tbCloseDrawer").click()

    page.locator("#selectModeBtn").click()
    page.locator('.task-card[data-id="17"] .tc-checkbox').check()
    assert "1 selected" in page.locator("#bbCount").inner_text()
    with page.expect_response("**/api/tasks/bulk"):
        page.locator("#bbPriority").select_option("critical")
    assert updates and updates[0]["ids"] == [17]
    assert updates[0]["updates"] == {"priority": "critical"}

    page.locator("#selectModeBtn").click()
    with page.expect_response("**/api/tasks/17"):
        page.locator('.task-card[data-id="17"]').drag_to(page.locator("#col-in_progress"))
    assert moves and moves[0]["status"] == "in_progress"

    page.locator("#aiPriBtn").click()
    page.locator("#aiPriPanel").wait_for()
    assert page.locator("#aiPriPanel [onclick], #aiPriPanel svg[onload]").count() == 0
    assert "<svg/onload=alert(1)>" in page.locator("#aiPriPanel").inner_text()
    page.locator('[data-ai-action="dismiss"]').click()
    page.locator("#aiPriPanel").wait_for(state="detached")
    assert not page.console_errors
