"""
PLAN-36 P01: My Work action centre. Real-browser smoke test -- the page
itself (modules/launcher/templates/my_work.html) and its inline JS have no
other browser coverage yet, so this proves it actually renders and fetches
data cleanly, catching the class of defect the default-fail console/page
error gate (tests/ui/conftest.py, T08) exists for.
"""


def test_my_work_page_loads_with_no_console_errors(login_as, live_app):
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/my-work")
    page.wait_for_selector("#myWorkSections .mywork-section", timeout=10000)

    sections = page.locator("#myWorkSections .mywork-section")
    assert sections.count() == 5, "all 5 sections (needs action/waiting/due soon/overdue/completed) must render"

    # The live source-status note names disabled/degraded/truncated sources,
    # rather than claiming the five now-wired sources are still pending.
    note = page.locator("#myWorkPendingNote")
    if note.is_visible():
        assert "Some sources could not be fully checked" in note.inner_text()
    assert "coming in a later release" not in note.inner_text()
