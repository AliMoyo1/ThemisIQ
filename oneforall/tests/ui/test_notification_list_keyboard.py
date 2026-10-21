"""
A person with more notifications than fit the popover can scroll the list from the keyboard. The list scrolls once it
holds about seven rows; a scrollable region that cannot take focus leaves a keyboard user unable to read the rest
(axe: scrollable-region-focusable). It used to appear only in a long session, where an administrator had collected
enough notices.
"""
import database


def test_a_long_notification_list_takes_focus_and_has_no_serious_violations(login_as, live_app, synthetic_tenant, run_axe):
    admin = synthetic_tenant["users"]["super_admin"]["user_id"]
    db = database.get_db()
    try:
        for i in range(14):
            db.execute(
                "INSERT INTO notifications (user_id, module, title, message, link, is_read) "
                "VALUES (%s, 'platform', %s, 'A notice for the keyboard test', '/my-work', 0)",
                (admin, f"Keyboard test notice {i:02d}"))
        db.commit()
    finally:
        db.close()
    try:
        page = login_as("super_admin")
        page.goto(f"{live_app}/")
        page.wait_for_load_state("networkidle", timeout=15000)
        page.locator("#notifBtn").click()
        page.wait_for_selector("#notifList [data-nid]", timeout=8000)
        assert page.locator("#notifList").evaluate("el => el.scrollHeight > el.clientHeight"), "the list scrolls"

        page.locator("#notifList").focus()
        assert page.evaluate("document.activeElement && document.activeElement.id") == "notifList"
        violations = run_axe()
        assert not violations, "; ".join(f"{v['id']}: {v['help']}" for v in violations)
    finally:
        db = database.get_db()
        try:
            db.execute("DELETE FROM notifications WHERE user_id = %s AND title LIKE 'Keyboard test notice %%'", (admin,))
            db.commit()
        finally:
            db.close()
