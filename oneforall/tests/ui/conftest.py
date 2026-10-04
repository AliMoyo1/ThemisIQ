"""
Real-browser regression harness (PLAN-36 T00).

Requires the dev-only `requirements-browser-dev.txt` (Playwright) and its
downloaded browser binary (`playwright install chromium`). The `browser`
fixture below -- not a module-level import -- is what requires Playwright,
and does so lazily (via pytest.importorskip called from inside the fixture,
at first use) rather than at collection time. That is deliberate, not just
style: importing playwright.sync_api eagerly at collection time was
observed to load its driver/threading machinery into the whole pytest
process before any test runs, which was enough to perturb an unrelated
filesystem-mtime-timing assertion elsewhere in the suite
(test_aria_policy_publication.py::test_purge_expired_trash_leaves_recent_entries,
confirmed by bisecting: fails only when tests/ui is collected, passes with
tests/ui excluded, on an otherwise-identical run). Deferring the import
until a test actually needs a browser confines that side effect to browser
tests only and keeps the default `pytest tests -q` gate unaffected by
Playwright even being installed.

Boots the real ASGI app (main:app) via uvicorn in a background thread
against an isolated, per-session SQLite file -- never the developer's
oneforall.db/themisiq.db and never a configured DATABASE_URL. This is the
only place under tests/ that opens a real TCP socket and drives a real
browser; everything else stays in-process against a stub DB connection
(see tests/conftest.py's test_db fixture).
"""
import os
import secrets
import socket
import threading
import time
from pathlib import Path

import pytest

import database
from core.auth import hash_password
from core.rbac import (
    SUPER_ADMIN, ORG_ADMIN, POLICY_AUTHOR, POLICY_APPROVER, COMPLIANCE_MGR,
    RISK_OWNER, AUDIT_LEAD, BCM_MANAGER, DPO, EMPLOYEE, EXTERNAL_AUDITOR,
)

PERSONA_PASSWORD = "Synthetic-Test-Pass-1!"

# fixture key -> (role_key, is_super_admin)
PERSONAS = {
    "super_admin":        (SUPER_ADMIN, True),
    "org_admin":          (ORG_ADMIN, False),
    "policy_author":      (POLICY_AUTHOR, False),
    "policy_approver":    (POLICY_APPROVER, False),
    "compliance_manager": (COMPLIANCE_MGR, False),
    "risk_owner":         (RISK_OWNER, False),
    "audit_lead":         (AUDIT_LEAD, False),
    "bcm_manager":        (BCM_MANAGER, False),
    "dpo":                (DPO, False),
    "employee":           (EMPLOYEE, False),
    "viewer":             (EXTERNAL_AUDITOR, False),
}


def _free_port() -> int:
    # Windows can assign low ephemeral ports such as 1720, which Chromium
    # rejects with ERR_UNSAFE_PORT before a browser test reaches the app.
    for _ in range(100):
        candidate = 20000 + secrets.randbelow(40000)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", candidate))
            except OSError:
                continue
            return candidate
    raise RuntimeError("UI harness could not find a free browser-safe port")


class _ServerThread(threading.Thread):
    """Runs uvicorn's async server on its own event loop in a daemon thread."""

    def __init__(self, app, host: str, port: int):
        super().__init__(daemon=True)
        import uvicorn
        self.server = uvicorn.Server(
            uvicorn.Config(app, host=host, port=port, log_level="warning")
        )

    def run(self):
        import asyncio
        asyncio.run(self.server.serve())

    def stop(self):
        self.server.should_exit = True
        self.join(timeout=10)


@pytest.fixture(scope="session")
def live_app(tmp_path_factory):
    """Boot the real app against an isolated, disposable SQLite database.

    Refuses to run unless DATABASE_URL is empty (tests/conftest.py forces
    this at collection time for everything under tests/) -- a real browser
    driving a real login flow must never be able to reach a configured
    PostgreSQL DSN, developer DB, or production.
    """
    assert os.environ.get("DATABASE_URL", "") == "", (
        "UI browser harness refuses to start: DATABASE_URL is set. "
        "These tests only run in forced SQLite mode against a disposable file."
    )

    db_path = tmp_path_factory.mktemp("ui_harness") / "ui_test.db"
    assert str(tmp_path_factory.getbasetemp()) in str(db_path), (
        "UI harness database path escaped pytest's tmp directory"
    )
    database._DB_PATH = str(db_path)

    import main as app_module  # import AFTER _DB_PATH is patched

    host, port = "127.0.0.1", _free_port()
    thread = _ServerThread(app_module.app, host, port)
    thread.start()

    base_url = f"http://{host}:{port}"
    import httpx
    deadline = time.time() + 20
    last_exc = None
    healthy = False
    while time.time() < deadline:
        try:
            if httpx.get(f"{base_url}/health", timeout=1).status_code == 200:
                healthy = True
                break
        except Exception as exc:
            last_exc = exc
        time.sleep(0.2)

    if not healthy:
        thread.stop()
        raise RuntimeError(f"UI harness app never became healthy: {last_exc}")

    yield base_url

    thread.stop()


@pytest.fixture(scope="session")
def synthetic_tenant(live_app):
    """One disposable organization, one business unit, and one user per
    persona in PERSONAS -- all inside the SQLite file live_app just booted."""
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO organizations (name, slug, plan, status) "
            "VALUES ('UI Harness Org', 'ui-harness-org', 'enterprise', 'active')"
        )
        db.commit()
        org_id = db.execute(
            "SELECT id FROM organizations WHERE slug='ui-harness-org'"
        ).fetchone()["id"]
        db.execute(
            "INSERT INTO licenses (org_id, module_keys, seats) "
            "VALUES (%s, 'aria,bcm,erm,grid,orm,sentinel', 999)",
            (org_id,),
        )
        db.commit()

        users = {}
        for key, (role_key, is_super) in PERSONAS.items():
            username = f"uiharness_{key}"
            db.execute(
                "INSERT INTO users "
                "(username, email, full_name, password_hash, org_id, "
                "is_super_admin, must_change_password) "
                "VALUES (%s, %s, %s, %s, %s, %s, 0)",
                (username, f"{username}@example.test", role_key.replace("_", " ").title(),
                 hash_password(PERSONA_PASSWORD),
                 None if is_super else org_id,
                 1 if is_super else 0),
            )
            db.commit()
            user_id = db.execute(
                "SELECT id FROM users WHERE username=%s", (username,)
            ).fetchone()["id"]
            db.execute(
                "INSERT INTO user_roles (user_id, role_key) VALUES (%s, %s)",
                (user_id, role_key),
            )
            db.commit()
            users[key] = {"username": username, "password": PERSONA_PASSWORD,
                          "user_id": user_id, "org_id": org_id}

        from modules.governance.data_service import (
            create_business_unit, assign_user_business_unit,
        )
        bu_id = create_business_unit({"name": "UI Harness SBU"})
        for key, info in users.items():
            if key != "super_admin":
                assign_user_business_unit(info["user_id"], bu_id)

        return {"org_id": org_id, "business_unit_id": bu_id, "users": users}
    finally:
        db.close()


@pytest.fixture(scope="session")
def browser():
    sync_api = pytest.importorskip("playwright.sync_api")
    with sync_api.sync_playwright() as p:
        b = p.chromium.launch(headless=True)
        yield b
        b.close()


@pytest.fixture
def page(browser, request):
    """A fresh browser context/page per test, with console/page errors
    collected onto `page.console_errors` so any test can assert
    `assert not page.console_errors` instead of re-wiring listeners.

    PLAN-36 T08: unless the test is marked `@pytest.mark.expected_page_errors`,
    this is also an autouse gate -- any uncaught console/page error fails the
    test by default instead of silently passing when nothing happened to
    check `page.console_errors` directly. "Failed to load resource" is
    excluded from the gate (not from the raw list): Chromium logs that for
    *any* non-2xx fetch/XHR response or network-level failure regardless of
    whether the page's own JS handled it correctly, which is exactly what
    several deliberate-failure tests already relied on before this gate
    existed (see test_webhook_admin_ui.py / test_email_settings_error_detail.py) --
    the real signal for those is their own explicit UI assertion, not the
    browser's own resource-load log line.
    """
    context = browser.new_context()
    pg = context.new_page()
    pg.console_errors = []

    def _on_console(msg):
        if msg.type != "error":
            return
        loc = msg.location or {}
        where = f"{loc.get('url', '')}:{loc.get('lineNumber', '?')}" if loc else ""
        pg.console_errors.append(f"{msg.text} ({where})" if where else msg.text)

    def _on_pageerror(exc):
        stack = getattr(exc, "stack", None)
        pg.console_errors.append(f"{exc} | stack: {stack}" if stack else str(exc))

    pg.on("console", _on_console)
    pg.on("pageerror", _on_pageerror)
    yield pg
    context.close()
    if not request.node.get_closest_marker("expected_page_errors"):
        gated_errors = [e for e in pg.console_errors if "Failed to load resource" not in e]
        assert not gated_errors, (
            "Uncaught console/page errors during test (PLAN-36 T08 default-fail "
            "policy): " + "; ".join(gated_errors) + ". If this test deliberately "
            "exercises a failure path, mark it "
            "@pytest.mark.expected_page_errors('reason') instead."
        )


_AXE_CORE_JS = None  # lazily read once; large (~550KB), no need to re-read per test


@pytest.fixture
def run_axe(page):
    """Callable: run_axe() -> list of critical/serious axe-core violations
    on the page's current state (PLAN-36 T07). Injects a locally vendored
    axe-core (tests/ui/vendor/axe.min.js, not a live CDN fetch, so this has
    no network dependency at test time) and runs a real accessibility scan
    via axe.run(), the same engine browser devtools' own a11y panels use.

    Only critical/serious are returned by default -- matching T07's own
    completion gate ("zero critical/serious automated violations"); moderate/
    minor findings are a separate, documented-with-owner category the gate
    doesn't block on. Pass impacts=(...) to widen it for a specific test.
    """
    global _AXE_CORE_JS
    if _AXE_CORE_JS is None:
        axe_path = Path(__file__).parent / "vendor" / "axe.min.js"
        _AXE_CORE_JS = axe_path.read_text(encoding="utf-8")

    def _do(impacts=("critical", "serious")):
        page.add_script_tag(content=_AXE_CORE_JS)
        results = page.evaluate("async () => await axe.run()")
        return [v for v in results["violations"] if v["impact"] in impacts]

    return _do


@pytest.fixture
def login_as(page, live_app, synthetic_tenant):
    """Callable: login_as('risk_owner') -> logs the real /login form in via
    the real browser, returns the same `page` already navigated past login."""

    def _do(persona: str):
        creds = synthetic_tenant["users"][persona]
        page.goto(f"{live_app}/login")
        page.fill("#username", creds["username"])
        page.fill("#password", creds["password"])
        page.click("#submitBtn")
        page.wait_for_load_state("networkidle")
        assert "/login" not in page.url, (
            f"login_as({persona!r}) did not leave /login; still on {page.url}"
        )
        return page

    return _do
