"""
PLAN-36 T07 (findings.md F09): the ERM register/library/external-context/
obligations/assessments status and industry filter chips were
`<span class="erm-chip" ...>` wired only via a plain `addEventListener
('click', ...)` in initChips() -- mouse-only, unreachable by Tab, not
activatable with Enter/Space. initChips() itself is agnostic to element
tag (it only does querySelectorAll('.erm-chip') + addEventListener), so
converting every erm-chip span to a real <button type="button"> needed no
JavaScript changes to make click-based filtering keep working; it only
adds the native keyboard support buttons carry for free.
"""


def test_register_status_chips_are_buttons_and_keyboard_operable(login_as, live_app):
    """Red proof for this test (temporarily reverting regFilterBar's chips
    back to <span>): the 'Open' chip is not in the Tab order and Enter has
    no effect on it, so .active never moves off 'All'. Restored, this
    passes."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/erm/register")
    page.wait_for_load_state("networkidle")
    # initChips() wires the click handlers only after ermLoadRegister()'s
    # own fetch resolves; networkidle above is what guarantees that has
    # already happened by the time we interact with the chips below.
    page.wait_for_selector("#regFilterBar .erm-chip")
    tags = page.eval_on_selector_all(
        "#regFilterBar .erm-chip", "els => els.map(e => e.tagName)"
    )
    assert all(t == "BUTTON" for t in tags), tags

    open_chip = page.locator('#regFilterBar .erm-chip[data-status="open"]')
    open_chip.focus()
    assert "erm-chip" in (page.evaluate("document.activeElement.className") or "")
    page.keyboard.press("Enter")
    assert "active" in (open_chip.get_attribute("class") or "")
    all_chip = page.locator('#regFilterBar .erm-chip[data-status=""]')
    assert "active" not in (all_chip.get_attribute("class") or "")
