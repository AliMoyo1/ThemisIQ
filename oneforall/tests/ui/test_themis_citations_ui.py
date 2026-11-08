"""Themis shows exact local citations and keeps source links on this origin."""

import json


def test_themis_displays_current_version_citations_without_unsafe_links(login_as, live_app):
    page = login_as("dpo")
    page.goto(f"{live_app}/")
    digest = "a" * 64
    answer = {
        "answer": 'These exact excerpts occur in the current indexed documents I can open.\n[1] “Recovery within four hours.”',
        "source": "records",
        "sources": [
            {"label": "Recovery policy", "path": "/evidence/?open=item:7", "version": 3,
             "record_id": 7, "section": "Recovery", "start": 10, "end": 37,
             "file_hash": digest},
            {"label": "Unsafe source", "path": "javascript:alert(1)", "version": 1},
        ],
    }
    page.route("**/api/trainer/ask", lambda route: route.fulfill(
        status=200, content_type="application/json", body=json.dumps(answer)))
    if not page.locator("#trainerPanel.open").count():
        page.locator(".trainer-icon").click()
    page.locator("#trainerTabAsk").click()
    page.locator("#trainerInput").fill("What does the recovery policy say?")
    page.locator("#trainerInput").press("Enter")
    message = page.locator("#trainerMessages .trainer-msg.bot").last
    message.locator(".trainer-sources a").wait_for(timeout=10000)
    assert "Recovery within four hours" in message.inner_text()
    assert "version 3" in message.inner_text()
    assert "text offsets 10–37" in message.inner_text()
    assert f"SHA-256 {digest[:12]}" in message.inner_text()
    assert message.locator(".trainer-sources a").count() == 1
    assert message.locator(".trainer-sources a").first.get_attribute("href") == "/evidence/?open=item:7"
