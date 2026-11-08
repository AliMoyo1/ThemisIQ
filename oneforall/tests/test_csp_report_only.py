"""Every page runs under the strict script policy: no inline script, no inline handler, no CDN
(plans/csp-script-migration-2026-10.md). The file keeps its old name so its history stays readable."""

import re
from pathlib import Path

from starlette.requests import Request
from starlette.responses import HTMLResponse

from core import middleware
from config import settings

ROOT = Path(__file__).resolve().parents[1]
HANDLER = re.compile(r"""[\s'"]on[a-z]{3,}\s*=\s*\\?["']""", re.I)
INLINE_SCRIPT = re.compile(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>", re.I)


def _headers(path):
    async def read():
        request = Request({"type": "http", "method": "GET", "path": path,
                           "query_string": b"", "headers": [], "scheme": "https",
                           "server": ("example.test", 443)})

        async def next_response(_):
            return HTMLResponse("<h1>Test</h1>")

        return await middleware.security_headers_middleware(request, next_response)

    # The middleware awaits only a response that is immediately ready.
    # Avoid a Windows event-loop socketpair for this pure header check.
    try:
        read().send(None)
    except StopIteration as done:
        return done.value.headers
    raise AssertionError("header middleware unexpectedly yielded")


def test_every_page_gets_the_strict_script_policy(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", False)
    for path in ("/", "/ai-governance/", "/timeline", "/login", "/grid/audits/7", "/erm/scenario-studio",
                 "/reports/runs/12/print", "/aria/documents/POL-1/workbench", "/evidence-campaigns/",
                 "/readiness/", "/governance/connected/changes", "/docs", "/an/unknown/page"):
        headers = _headers(path)
        policy = headers["Content-Security-Policy"]
        script = policy.split("script-src ", 1)[1].split(";", 1)[0]
        assert "'unsafe-inline'" not in script and "cdn." not in script and "cdnjs." not in script, path
        assert "script-src-attr 'none'" in policy, path
        assert "Content-Security-Policy-Report-Only" not in headers, path


def test_only_the_debug_api_explorer_keeps_inline_scripts(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", True)
    assert "'unsafe-inline'" in _headers("/docs")["Content-Security-Policy"].split("style-src")[0]
    assert "'unsafe-inline'" not in _headers("/").get("Content-Security-Policy").split("style-src")[0]


def test_no_template_regains_inline_execution():
    pages = [p for p in ROOT.rglob("*.html") if not {".venv", "node_modules", "tests"} & set(p.parts)]
    assert len(pages) > 80, "the scan should see every template"
    for page in pages:
        markup = page.read_text(encoding="utf-8")
        assert not HANDLER.search(markup), page
        assert not INLINE_SCRIPT.search(markup), page
        assert "javascript:" not in markup, page


def test_no_script_builds_an_inline_handler_or_script_url():
    """Many pages build their markup in their scripts: those strings must not carry executable attributes either.
    Actions are data attributes read by fixed dispatchers."""
    scripts = [p for p in (ROOT / "static/js").rglob("*.js") if ".min." not in p.name and "vendor" not in p.parts]
    for script in scripts:
        source = script.read_text(encoding="utf-8")
        assert not HANDLER.search(source), f"an inline on... attribute in {script.name}"
        assert "javascript:" not in source, script.name
        assert "eval(" not in source and "new Function" not in source, script.name
