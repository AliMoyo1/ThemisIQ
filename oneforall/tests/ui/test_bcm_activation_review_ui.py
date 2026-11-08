"""The continuity activation dialog sends the visible control review result."""


def test_activation_shows_dependencies_and_submits_the_check(live_app, page, login_as):
    submitted = []

    def plans(route):
        request = route.request
        if request.url.endswith("/bcm/api/plans"):
            route.fulfill(status=200, content_type="application/json", body='{"records":[{"id":8123,"title":"Recovery plan","status":"approved","is_active_plan":0}]}')
        elif request.url.endswith("/bcm/api/plans/8123"):
            route.fulfill(status=200, content_type="application/json", body='{"id":8123,"title":"Recovery plan","control_dependencies":[{"id":9213,"ref":"BC-1","title":"Recovery test","status":"Implemented"}]}')
        elif request.url.endswith("/bcm/api/plans/8123/activate"):
            submitted.append(request.post_data_json)
            route.fulfill(status=200, content_type="application/json", body='{"ok":true}')
        else:
            route.continue_()

    login_as("super_admin")
    page.route("**/bcm/api/plans**", plans)
    page.route("**/bcm/api/incidents", lambda route: route.fulfill(
        status=200, content_type="application/json", body='{"records":[]}'))
    page.goto(f"{live_app}/bcm/plans")
    page.get_by_text("Recovery plan").first.wait_for()
    page.evaluate("bcmActivatePlan(8123)")
    modal = page.locator("#activateModal")
    modal.get_by_text("BC-1 Recovery test").wait_for()
    modal.locator(".bcm-control-result").select_option("not_working")
    modal.get_by_role("button", name="Activate Plan").click()
    page.wait_for_function("() => !document.getElementById('activateModal')")
    assert submitted and submitted[0]["control_review"] == [{"id": 9213, "result": "not_working"}]
    assert not [error for error in page.console_errors if "/bcm/" in error], page.console_errors
