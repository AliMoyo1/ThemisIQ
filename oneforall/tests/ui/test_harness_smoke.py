"""
PLAN-36 T00 completion-gate proof.

Not a feature regression test -- proves the harness itself works end to
end in a real browser against a real (isolated) running instance: login,
navigation, one modal open/close, and one read-only API call. Uses
aria.documents.add_document.open from action_registry.json deliberately,
because that modal already uses the canonical .modal-overlay/.modal
contract (findings.md F02 is about the *other* templates); this test is
about the harness, not about proving a fix.
"""
import json
import os

_REGISTRY_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "action_registry.json")


def _action(action_id: str) -> dict:
    with open(_REGISTRY_PATH, encoding="utf-8") as f:
        registry = json.load(f)
    return next(a for a in registry["actions"] if a["id"] == action_id)


def test_login_navigation_modal_and_readonly_api(login_as, live_app):
    login = _action("auth.login.submit")
    nav = _action("nav.launcher.command_centre")
    modal = _action("aria.documents.add_document.open")

    # 1. Login (real form submit, real session cookie).
    page = login_as("policy_author")
    assert page.url.rstrip("/") == live_app.rstrip("/"), (
        f"expected to land on {live_app}/ after login, got {page.url}"
    )

    # 2. Navigation: the shell renders and its Command Centre nav item is present.
    assert page.locator(nav["selector"]).count() > 0, (
        f"nav selector {nav['selector']!r} not found after login"
    )

    # 3. Modal open/close, using the canonical (already-correct) ARIA modal.
    page.goto(f"{live_app}{modal['route']}")
    overlay = page.locator("#addModal")
    assert "open" not in (overlay.get_attribute("class") or ""), (
        "#addModal should start closed"
    )
    page.click(modal["selector"])
    page.wait_for_selector("#addModal.open", timeout=5000)
    assert overlay.is_visible(), "#addModal did not become visible after Add Document click"

    page.click("[onclick=\"closeModal('addModal')\"]")
    page.wait_for_selector("#addModal", state="hidden", timeout=5000)
    assert "open" not in (overlay.get_attribute("class") or "")

    # 4. One read-only API call, through the same authenticated browser
    # context (shares the session cookie with `page`).
    api = page.request.get(f"{live_app}/aria/api/templates")
    assert api.status == 200, f"read-only API call failed: {api.status} {api.text()[:200]}"
    assert isinstance(api.json(), list)

    assert not page.console_errors, f"unexpected console/page errors: {page.console_errors}"
