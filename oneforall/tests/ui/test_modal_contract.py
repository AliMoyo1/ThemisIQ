"""
PLAN-36 T02 (findings.md F02): shared modal contract, real browser.

Every modal below used to be outer `.modal` / inner `.modal-content`, which
the shared shell's CSS (`.modal-overlay.open{display:flex}`) has no rule
for -- the dialog stayed in normal document flow and never became an
overlay. Each is now migrated to the canonical outer `.modal-overlay` /
inner `.modal` contract, opened/closed through the new shared
`ModalManager` (static/js/modal_manager.js) instead of ad-hoc
classList calls.

One parametrized test proves the full open/close/focus/Escape/keyboard
contract for every migrated modal that opens from a simple, always-visible
trigger button. Two further tests cover the two migrated dialogs whose open
path doesn't fit that shape: the API-key reveal modal (only reachable by
submitting the generate form) and Link Evidence (only reachable from an
existing evidence item's detail view).
"""
import database
import pytest

# (persona, route, trigger selector, modal id)
MODALS = [
    ("compliance_manager", "/tasks", 'button:has-text("New Task")', "newTaskModal"),
    ("compliance_manager", "/reports", 'button:has-text("+ New Report")', "newReportModal"),
    ("super_admin", "/risk-register", 'button:has-text("+ New Risk")', "newRiskModal"),  # registering is the administrator's
    ("compliance_manager", "/calendar", 'button:has-text("Add Event")', "eventModal"),
    ("super_admin", "/admin/api-keys", 'button:has-text("+ Generate Key")', "newKeyModal"),
    ("super_admin", "/admin/webhooks", 'button:has-text("+ New Webhook")', "newWhModal"),
    ("compliance_manager", "/evidence/", 'button:has-text("+ Upload")', "uploadModal"),
    ("super_admin", "/admin/frameworks", 'button:has-text("+ Custom Framework")', "newFwModal"),
]


@pytest.mark.parametrize(
    "persona,route,trigger,modal_id", MODALS, ids=[m[3] for m in MODALS]
)
def test_modal_open_close_focus_and_escape(
    login_as, live_app, persona, route, trigger, modal_id,
):
    page = login_as(persona)
    page.goto(f"{live_app}{route}")
    overlay = page.locator(f"#{modal_id}")

    # Closed by default -- not occupying normal page flow.
    assert not overlay.is_visible(), f"{modal_id} must start closed"

    page.click(trigger)
    page.wait_for_selector(f"#{modal_id}.open", timeout=5000)
    assert overlay.is_visible()
    assert overlay.evaluate("el => getComputedStyle(el).display") == "flex"
    assert overlay.evaluate("el => getComputedStyle(el).position") == "fixed"

    # Canonical dialog semantics are on the markup itself, not inferred.
    assert overlay.get_attribute("role") == "dialog"
    assert overlay.get_attribute("aria-modal") == "true"
    assert overlay.get_attribute("aria-labelledby"), f"{modal_id} needs an accessible name"

    focused_inside = page.evaluate(
        "id => document.getElementById(id).contains(document.activeElement)", modal_id,
    )
    assert focused_inside, f"initial focus did not land inside {modal_id}"

    # Escape closes it.
    page.keyboard.press("Escape")
    page.wait_for_selector(f"#{modal_id}", state="hidden", timeout=5000)
    assert not overlay.is_visible()

    # Re-open, this time close via the header close button.
    page.click(trigger)
    page.wait_for_selector(f"#{modal_id}.open", timeout=5000)
    page.click(f"#{modal_id} .modal-close")
    page.wait_for_selector(f"#{modal_id}", state="hidden", timeout=5000)
    assert not overlay.is_visible()

    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


def test_modal_focus_trap_cycles_and_returns_to_trigger(login_as, live_app):
    """Tab from the last focusable element wraps to the first (and back via
    Shift+Tab), and closing restores focus to the button that opened it --
    tested against one representative modal since all migrated modals share
    the same ModalManager focus-trap implementation."""
    page = login_as("compliance_manager")
    page.goto(f"{live_app}/tasks")
    trigger = page.locator('button:has-text("New Task")')
    trigger.click()
    page.wait_for_selector("#newTaskModal.open", timeout=5000)

    items = page.locator(
        "#newTaskModal .modal-header button, #newTaskModal .modal-body :is(input, select, textarea, button, a[href])"
    )
    first_handle = items.first.element_handle()
    last_handle = items.last.element_handle()

    items.last.focus()
    page.keyboard.press("Tab")
    wrapped_to_first = page.evaluate(
        "(el) => document.activeElement === el", first_handle,
    )
    assert wrapped_to_first, "Tab from the last focusable element must wrap to the first, not leave the modal"

    page.keyboard.press("Shift+Tab")
    wrapped_to_last = page.evaluate(
        "(el) => document.activeElement === el", last_handle,
    )
    assert wrapped_to_last, "Shift+Tab from the first focusable element must wrap to the last, not leave the modal"

    page.keyboard.press("Escape")
    page.wait_for_selector("#newTaskModal", state="hidden", timeout=5000)
    same_element = page.evaluate(
        "(trigger) => document.activeElement === trigger", trigger.element_handle()
    )
    assert same_element, "focus must return to the trigger button after close"
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


@pytest.mark.parametrize(
    "persona,route,trigger,modal_id",
    [MODALS[0], MODALS[6]],  # newTaskModal, uploadModal -- representative sample
    ids=["newTaskModal", "uploadModal"],
)
def test_modal_fits_mobile_viewport_without_body_overflow(
    login_as, live_app, persona, route, trigger, modal_id,
):
    page = login_as(persona)
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{live_app}{route}")
    page.click(trigger)
    page.wait_for_selector(f"#{modal_id}.open", timeout=5000)

    overflow = page.evaluate(
        "() => document.body.scrollWidth > window.innerWidth"
    )
    assert not overflow, f"{modal_id} causes horizontal body overflow at 390x844"


def test_api_key_generate_then_reveal_modal_transition(login_as, live_app):
    """The two-step generate -> reveal flow: closing one migrated modal and
    opening another in the same click handler must not fight over the
    shared focus-trap/scroll-lock state ModalManager tracks as a stack."""
    page = login_as("super_admin")
    page.goto(f"{live_app}/admin/api-keys")

    page.click('button:has-text("+ Generate Key")')
    page.wait_for_selector("#newKeyModal.open", timeout=5000)
    page.fill("#keyName", "UI Harness Key")
    page.click('#keyForm button[type="submit"]')

    page.wait_for_selector("#revealModal.open", timeout=5000)
    page.wait_for_selector("#newKeyModal", state="hidden", timeout=5000)
    assert page.locator("#revealModal").get_attribute("role") == "dialog"
    focused_inside = page.evaluate(
        "() => document.getElementById('revealModal').contains(document.activeElement)"
    )
    assert focused_inside, "focus did not move into the reveal modal"

    page.keyboard.press("Escape")
    page.wait_for_selector("#revealModal", state="hidden", timeout=5000)
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"


def test_link_evidence_modal_from_an_existing_item(login_as, live_app, synthetic_tenant):
    """Link Evidence opens from a real evidence item's detail view, not a
    static top-of-page button -- covered separately from the parametrized
    table above because its trigger path needs a seeded row first."""
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO evidence_items (title, category, uploaded_by, org_id) "
            "VALUES ('UI Harness Evidence', 'general', %s, %s)",
            (synthetic_tenant["users"]["compliance_manager"]["user_id"],
             synthetic_tenant["org_id"]),
        )
        db.commit()
        evidence_id = db.execute(
            "SELECT id FROM evidence_items WHERE title='UI Harness Evidence'"
        ).fetchone()["id"]
    finally:
        db.close()

    page = login_as("compliance_manager")
    page.goto(f"{live_app}/evidence/")
    page.evaluate("id => openDetail(id)", evidence_id)
    page.click('button:has-text("Link to...")')
    page.wait_for_selector("#linkToModal.open", timeout=5000)

    overlay = page.locator("#linkToModal")
    assert overlay.get_attribute("role") == "dialog"
    assert overlay.get_attribute("aria-modal") == "true"

    page.keyboard.press("Escape")
    page.wait_for_selector("#linkToModal", state="hidden", timeout=5000)
    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"
