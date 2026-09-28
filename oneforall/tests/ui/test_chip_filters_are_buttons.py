"""
PLAN-36 T07 (F09, "convert interactive div/span controls into button/a
href elements"): completes the interactive-chip sweep session 2 started
with ERM's 24 register/library/etc. filter chips. A full repo scan (every
`<span>`/`<div>` with a "chip" class, cross-checked against every
`querySelectorAll('...chip...')`/`addEventListener` wiring site) found
these additional real instances -- filter chips wired with individual
inline `onclick` attributes (bcm, grid, task_board, command_centre) or a
single delegated listener (timeline, ARIA's ask.html), converted to real
`<button type="button">` the same way. The same scan also found several
already-correct `.chip`-style controls (vendor_directory, workflows,
ERM's p2st2/orm/sentinel's chip-pick) that were already buttons, and
purely decorative "chip" badges with no click handler at all (row-chip,
ims-fw-chip, bcm-ctrl-chip, role-chip, tl-meta-chip, orm-cat-chip,
sentinel's per-tag filter-chip at line ~3601) that were correctly left
as spans -- adding button semantics to a non-interactive element would
itself be an accessibility anti-pattern.
"""
import pytest


@pytest.mark.parametrize("route,selector", [
    ("/bcm/incidents", ".filter-bar .filter-chip"),
    ("/grid/audits", "#gridStatusFilters .filter-chip"),
])
def test_module_filter_chips_are_buttons(login_as, live_app, route, selector):
    page = login_as("super_admin")
    page.goto(f"{live_app}{route}")
    page.wait_for_load_state("networkidle")
    tags = page.eval_on_selector_all(selector, "els => els.map(e => e.tagName)")
    assert tags, f"no chips found for {selector}"
    assert all(t == "BUTTON" for t in tags), tags


def test_task_board_priority_chips_are_buttons(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/tasks")
    page.wait_for_selector(".tb-pri-chip")
    tags = page.eval_on_selector_all(".tb-pri-chip", "els => els.map(e => e.tagName)")
    assert len(tags) == 5
    assert all(t == "BUTTON" for t in tags), tags


def test_timeline_period_chips_are_buttons_and_keyboard_operable(login_as, live_app):
    """Red proof for this test (temporarily reverting the 3 period chips
    back to <span>): Tab never reaches the 30-day chip and Enter has no
    effect, so .tl-chip.active stays on the 7-day chip. Restored, this
    passes."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/timeline")
    page.wait_for_selector(".tl-chip")
    chip_30 = page.locator('.tl-chip[data-days="30"]')
    assert chip_30.evaluate("el => el.tagName") == "BUTTON"
    chip_30.focus()
    page.keyboard.press("Enter")
    assert "active" in (chip_30.get_attribute("class") or "")


def test_command_centre_overdue_filter_chips_are_buttons(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/")
    page.wait_for_load_state("networkidle")
    chips = page.locator("#ccModuleFilters .filter-chip")
    if chips.count() == 0:
        pytest.skip("no overdue items rendered #ccModuleFilters for this fixture")
    tags = page.eval_on_selector_all("#ccModuleFilters .filter-chip", "els => els.map(e => e.tagName)")
    assert all(t == "BUTTON" for t in tags), tags


def test_erm_chat_prompt_chips_are_buttons(login_as, live_app):
    page = login_as("super_admin")
    page.goto(f"{live_app}/erm/")
    page.wait_for_load_state("networkidle")
    chips = page.locator(".chat-prompt-chip")
    if chips.count() == 0:
        pytest.skip("chat panel not rendered in this fixture state")
    tags = page.eval_on_selector_all(".chat-prompt-chip", "els => els.map(e => e.tagName)")
    assert all(t == "BUTTON" for t in tags), tags


def test_decorative_chips_remain_plain_spans_not_over_converted(login_as, live_app):
    """Guards against the opposite mistake: a non-interactive display
    badge should NOT have been turned into a button (that would falsely
    advertise it as actionable to keyboard/AT users)."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/aria/documents")
    page.wait_for_load_state("networkidle")
    tags = page.eval_on_selector_all(".row-chip", "els => els.map(e => e.tagName)")
    if not tags:
        pytest.skip("no document rows seeded for .row-chip in this fixture")
    assert all(t == "SPAN" for t in tags), tags
