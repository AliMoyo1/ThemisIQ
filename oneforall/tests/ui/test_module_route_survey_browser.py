"""Smoke every BCM and ORM SPA view in the isolated browser."""


BCM_VIEWS = (
    "bia", "plans", "incidents", "exercises", "risks", "dependencies",
    "training", "reports", "chat", "documents", "compliance", "vendors",
    "comms", "contacts", "scenarios",
)
ORM_VIEWS = ("events", "indicators", "reports", "chat", "assessment", "ai-controls", "aims")


def test_all_bcm_and_orm_views_render_without_button_or_server_errors(live_app, page, login_as):
    login_as("super_admin")
    server_errors = []
    page.on("response", lambda response: server_errors.append((response.url, response.status))
            if response.status >= 500 else None)
    for module, views in (("bcm", BCM_VIEWS), ("orm", ORM_VIEWS)):
        for view in views:
            response = page.goto(f"{live_app}/{module}/{view}")
            assert response.status == 200, (module, view, response.status)
            page.wait_for_load_state("networkidle", timeout=15000)
            assert page.locator(f"#view-{view}.active").count() == 1, (module, view)
            empty_inline = page.locator(f"#view-{view} button[onclick='']:visible")
            assert empty_inline.count() == 0, (module, view)
            assert not server_errors, (module, view, server_errors)
