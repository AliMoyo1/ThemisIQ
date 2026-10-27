"""A specialist can inspect register coverage before saving an auditor copy."""


def test_ai_registers_preview_is_readable_and_does_not_save_a_run(login_as, live_app, page):
    login_as("dpo")
    page.goto(f"{live_app}/ai-governance/registers")
    page.get_by_role("heading", name="AI registers").wait_for()
    page.get_by_role("button", name="Preview coverage").first.click()
    page.get_by_role("heading", name="Coverage preview").wait_for()
    assert "systems:" in page.locator("#registerCoverageBody").inner_text()
    assert "Coverage preview ready" in page.locator("#registerNotice").inner_text()
    assert "run=" not in page.url


def test_registers_are_usable_at_phone_width(login_as, live_app, page):
    login_as("dpo")
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"{live_app}/ai-governance/registers")
    page.get_by_role("heading", name="AI registers").wait_for()
    assert page.locator("[data-register-export='ai_systems_register']").is_visible()
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1")


def test_framework_register_opens_preview_before_generation(login_as, live_app, page):
    login_as("compliance_manager")
    page.route("**/api/reports/register-preview?*", lambda route: route.fulfill(json={
        "report_type": "framework_auditor_register", "as_of": "2026-10-27T08:00:00",
        "framework": {"id": int(route.request.url.split("framework_id=")[-1]), "name": "Test"},
        "counts": {"controls": 4, "documents": 2, "evidence": 3},
        "total_gaps": 1, "gaps": [{"control_ref": "A.5.1", "gap": "No accepted operating proof"}],
        "complete": True,
    }))
    page.goto(f"{live_app}/aria/frameworks")
    page.locator("[data-framework-register]").first.click()
    panel = page.locator("#framework-register-preview")
    panel.get_by_text("4 controls", exact=False).wait_for()
    assert panel.get_by_text("A.5.1: No accepted operating proof").count() == 1
    assert panel.get_by_role("button", name="Generate frozen register").is_enabled()
    assert "run=" not in page.url


def test_audit_framework_link_preselects_register(login_as, live_app, page):
    login_as("compliance_manager")
    page.route("**/api/reports/register-preview?*", lambda route: route.fulfill(json={
        "report_type": "framework_auditor_register", "as_of": "2026-10-27T08:00:00",
        "framework": {"id": int(route.request.url.split("framework_id=")[-1]), "name": "Test"},
        "counts": {"controls": 1, "documents": 0, "evidence": 0},
        "total_gaps": 0, "gaps": [], "complete": True,
    }))
    page.goto(f"{live_app}/aria/frameworks")
    framework_id = page.locator("[data-framework-register]").first.get_attribute("data-framework-register")
    page.goto(f"{live_app}/aria/frameworks?register_framework={framework_id}")
    page.locator("#framework-register-preview").get_by_text("1 controls", exact=False).wait_for()
    assert page.locator("#framework-register-generate").is_enabled()


def test_grid_audit_id_is_not_mistaken_for_aria_framework_id(login_as, live_app, page):
    login_as("compliance_manager")
    page.goto(f"{live_app}/aria/frameworks")
    card = page.locator(".fw-card").first
    name = card.locator(".fw-card-name").inner_text().strip()
    aria_id = card.locator("[data-framework-register]").get_attribute("data-framework-register")
    requested = []
    page.route("**/grid/api/audits/9999", lambda route: route.fulfill(json={
        "id": 9999, "framework_id": 9876, "framework_name": name,
    }))
    def preview(route):
        requested.append(route.request.url)
        route.fulfill(json={
            "report_type": "framework_auditor_register", "as_of": "2026-10-27T08:00:00",
            "framework": {"id": int(aria_id), "name": name},
            "counts": {"controls": 1, "documents": 0, "evidence": 0},
            "total_gaps": 0, "gaps": [], "complete": True,
        })
    page.route("**/api/reports/register-preview?*", preview)
    page.goto(f"{live_app}/aria/frameworks?register_from_grid_audit=9999")
    page.locator("#framework-register-preview").get_by_text("1 controls", exact=False).wait_for()
    assert len(requested) == 1 and f"framework_id={aria_id}" in requested[0]
    assert "audit verdicts remain in GRID" in page.locator("#framework-register-preview").inner_text()
