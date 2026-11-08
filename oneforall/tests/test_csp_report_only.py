"""Legacy pages observe strict script violations without breaking their current UI."""

import re
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse

from core import middleware


def test_legacy_html_has_nonblocking_strict_script_probe():
    async def read(path):
        request = Request({"type": "http", "method": "GET", "path": path,
                           "query_string": b"", "headers": [], "scheme": "https",
                           "server": ("example.test", 443)})

        async def next_response(_):
            return HTMLResponse("<h1>Test</h1>")

        return await middleware.security_headers_middleware(request, next_response)

    def run_without_network_loop(path):
        # The middleware awaits only a response that is immediately ready.
        # Avoid a Windows event-loop socketpair for this pure header check.
        try:
            read(path).send(None)
        except StopIteration as done:
            return done.value
        raise AssertionError("header middleware unexpectedly yielded")

    legacy = run_without_network_loop("/")
    assert "'unsafe-inline'" in legacy.headers["Content-Security-Policy"]
    probe = legacy.headers["Content-Security-Policy-Report-Only"]
    assert "script-src-attr 'none'" in probe and "'unsafe-inline'" not in probe
    assert "report-uri" not in probe
    for path in ("/ai-governance/", "/timeline", "/profile", "/metrics", "/admin/security", "/admin/diagnostics", "/admin/logs", "/admin/webhooks", "/login", "/change-password", "/mfa/setup", "/mfa/verify",
                 "/grid", "/grid/", "/grid/audits/7", "/grid/assignments/", "/grid/reuse/",
                 "/grid/api/share-links/validate/" + "a" * 43,
                 "/erm", "/erm/", "/erm/register", "/erm/scenario-studio"):
        strict = run_without_network_loop(path)
        assert "'unsafe-inline'" not in strict.headers["Content-Security-Policy"].split("style-src")[0]
        assert "Content-Security-Policy-Report-Only" not in strict.headers


def test_strict_report_and_ai_templates_do_not_regain_inline_execution():
    root = Path(__file__).resolve().parents[1]
    pages = [*sorted((root / "modules/ai_governance/templates").glob("*.html")),
             root / "modules/launcher/templates/reports.html",
             root / "modules/launcher/templates/mfa_setup.html",
             root / "modules/launcher/templates/login.html",
             root / "modules/launcher/templates/change_password.html",
             root / "modules/launcher/templates/mfa_verify.html",
             root / "modules/launcher/templates/profile.html",
             root / "modules/launcher/templates/admin_security.html",
             root / "modules/launcher/templates/metrics.html",
             root / "modules/launcher/templates/diagnostics.html",
             root / "modules/launcher/templates/admin_logs.html",
             root / "modules/launcher/templates/admin_webhooks.html",
             root / "modules/launcher/templates/timeline.html",
             *sorted((root / "modules/grid/templates").glob("*.html")),
             *sorted((root / "modules/erm/templates").glob("*.html"))]
    for page in pages:
        markup = page.read_text(encoding="utf-8")
        assert not re.search(r"\bon[a-z]+\s*=", markup, re.I), page
        assert not re.search(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>", markup, re.I), page


def test_grid_and_erm_generate_no_inline_handler_or_script_url():
    """GRID and ERM build most of their markup in their scripts: those strings must not carry executable attributes
    either. Their actions are data attributes read by fixed dispatchers (plan: csp-script-migration)."""
    root = Path(__file__).resolve().parents[1]
    for name in ("grid_index.js", "erm_index.js", "erm_scenario_studio.js"):
        source = (root / "static/js" / name).read_text(encoding="utf-8")
        assert not re.search(r"""[\s'"]on[a-z]{3,}\s*=\s*\\?["']""", source), f"an inline on... attribute in {name}"
        assert "javascript:" not in source, name
        assert "eval(" not in source and "new Function" not in source, name
