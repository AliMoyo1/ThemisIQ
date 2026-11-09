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


# ── Styles (plans/2026-11-zoom-and-style-policy.md) ──────────────────────────────────────────────────────────────────

STYLE_TAG = re.compile(r"<style\b[^>]*>", re.I)
TEMPLATE_NONCE = 'nonce="{{ request.state.csp_nonce }}"'


def _policy_and_nonce(path="/"):
    seen = {}

    async def read():
        request = Request({"type": "http", "method": "GET", "path": path, "query_string": b"", "headers": [],
                           "scheme": "https", "server": ("example.test", 443)})

        async def next_response(req):
            seen["nonce"] = req.state.csp_nonce
            return HTMLResponse("<h1>Test</h1>")

        return await middleware.security_headers_middleware(request, next_response)

    try:
        read().send(None)
    except StopIteration as done:
        return done.value.headers["Content-Security-Policy"], seen["nonce"]
    raise AssertionError("header middleware unexpectedly yielded")


def _directive(policy, name):
    for part in policy.split(";"):
        words = part.split()
        if words and words[0] == name:
            return words[1:]
    return None


def test_style_elements_need_the_nonce_of_their_own_response(monkeypatch):
    monkeypatch.setattr(settings, "DEBUG", False)
    first, nonce = _policy_and_nonce()
    second, other = _policy_and_nonce()
    assert len(nonce) >= 22 and nonce != other, "a fresh, unguessable nonce for every response"
    assert _directive(first, "style-src-elem") == ["'self'", f"'nonce-{nonce}'"]
    assert f"'nonce-{other}'" in second and f"'nonce-{nonce}'" not in second
    # The fallback for older browsers must not name a nonce: that would switch off its 'unsafe-inline' for style
    # attributes too and strip every page of its layout.
    assert _directive(first, "style-src") == ["'self'", "'unsafe-inline'"]
    # Every page refuses style attributes, injected or not.
    for path in ("/", "/ai-governance/registers", "/erm/register", "/login", "/reports/runs/12/print", "/an/unknown"):
        policy, page_nonce = _policy_and_nonce(path)
        assert _directive(policy, "style-src-attr") == ["'none'"], path
        assert _directive(policy, "style-src-elem") == ["'self'", f"'nonce-{page_nonce}'"], path


STYLE_ATTR = re.compile(r"""\bstyle\s*=\s*\\?["']""", re.I)
SET_STYLE_ATTR = re.compile(r"""setAttribute\(\s*['"]style['"]""")


def _pages():
    return [p for p in ROOT.rglob("*.html") if not {".venv", "node_modules", "tests"} & set(p.parts)]


def _project_scripts():
    return [p for p in (ROOT / "static/js").rglob("*.js") if ".min." not in p.name and "vendor" not in p.parts]


def test_no_page_or_script_writes_a_style_attribute():
    """The browser drops every style="..." (style-src-attr 'none'). Fixed styles are classes or data-s tokens, a
    starting display is data-sd and a value filled in at run time is data-sv (static/js/style_tokens.js), or a script
    sets element.style, which the policy allows."""
    for page in _pages():
        assert not STYLE_ATTR.search(page.read_text(encoding="utf-8")), f"{page.relative_to(ROOT)} writes a style attribute"
    for script in _project_scripts():
        source = script.read_text(encoding="utf-8")
        assert not STYLE_ATTR.search(source), f"{script.name} writes a style attribute into markup"
        assert not SET_STYLE_ATTR.search(source), f"{script.name} sets a style attribute"
        # small element helpers take {style: '...'} and copy every key with setAttribute: style must go to cssText
        if re.search(r"""[{,]\s*style\s*:\s*['"`]""", source):
            assert ".style.cssText = " in source, f"{script.name} passes style: to a helper that may set the attribute"
    # HTML that Python serves to a browser (emails are not pages and keep their inline styles)
    for module in ("core/report_kit/render_html.py", "core/report_kit/charts.py"):
        assert not re.search(r"""\sstyle=\\?["']""", (ROOT / module).read_text(encoding="utf-8")), module


def test_every_page_loads_the_style_tokens_first():
    """Every full page (one with a <head>) loads the token stylesheet and the script that applies data-sd and data-sv,
    and loads them before its own styles so a page rule can still override a token with !important as before."""
    heads = [p for p in _pages() if re.search(r"<head[\s>]", p.read_text(encoding="utf-8"))]
    assert len(heads) >= 10
    for page in heads:
        markup = page.read_text(encoding="utf-8")
        head = markup[:markup.index("</head>")]
        css, js = head.rfind("<link", 0, head.find("/static/css/style-tokens.css")), head.find('<script src="/static/js/style_tokens.js')
        assert css > 0 and js > 0 and "/static/css/style-tokens.css" in head, f"{page.relative_to(ROOT)} does not load the style tokens"
        first_style = min([i for i in (head.find("<style"), head.find('rel="stylesheet"')) if i >= 0] or [len(head)])
        assert css <= first_style, f"{page.relative_to(ROOT)} loads a stylesheet before the tokens"
        assert "defer" not in head[js:head.index(">", js)], "style_tokens.js must run as the page is parsed"


def test_every_token_a_page_uses_has_its_rule():
    rules = set(re.findall(r'\[data-s="(s[0-9a-f]{7})"\]', (ROOT / "static/css/style-tokens.css").read_text(encoding="utf-8")))
    assert len(rules) > 1500
    used = set()
    for source in [*_pages(), *_project_scripts()]:
        used.update(re.findall(r"""data-s=\\?["'](s[0-9a-f]{7})""", source.read_text(encoding="utf-8")))
    assert used and used <= rules, sorted(used - rules)[:10]


def test_every_style_element_in_a_page_carries_the_nonce():
    pages = [p for p in ROOT.rglob("*.html") if not {".venv", "node_modules", "tests"} & set(p.parts)]
    for page in pages:
        tags = STYLE_TAG.findall(page.read_text(encoding="utf-8"))
        if "static" in page.relative_to(ROOT).parts:
            assert not tags, f"{page.name} is served as a file and cannot carry a nonce: link a stylesheet instead"
        for tag in tags:
            assert TEMPLATE_NONCE in tag, f"{page.relative_to(ROOT)}: {tag}"


def test_the_shells_page_css_slot_holds_rules_only():
    """`extra_styles` sits inside the shell's own <style>. A page that opens a <style> element there nests it: the
    nested tag breaks the page's first rule and its end tag closes the shell's block early. Closing the shell's block
    first and then adding style elements (as the ARIA base does) is fine."""
    shell = (ROOT / "templates/base_shell.html").read_text(encoding="utf-8")
    slot = "{% block extra_styles %}{% endblock %}"
    assert shell.index(slot) < shell.index("</style>") and shell[shell.index(slot) + len(slot):].lstrip().startswith("</style>")
    pages = [p for p in ROOT.rglob("*.html") if not {".venv", "node_modules", "tests"} & set(p.parts)]
    for page in pages:
        for block in re.findall(r"\{%\s*block extra_styles\s*%\}(.*?)\{%\s*endblock", page.read_text(encoding="utf-8"), re.S):
            if "<style" in block:
                assert "</style" in block and block.index("</style") < block.index("<style"), page.relative_to(ROOT)


def test_styles_built_outside_templates_carry_the_nonce():
    scripts = [p for p in (ROOT / "static/js").rglob("*.js") if ".min." not in p.name and "vendor" not in p.parts]
    for script in scripts:
        source = script.read_text(encoding="utf-8")
        if re.search(r"createElement\(\s*['\"]style['\"]\s*\)", source):
            assert ".nonce = " in source, f"{script.name} creates a <style> without the page's nonce"
        code = "\n".join(line for line in source.splitlines() if not line.lstrip().startswith(("//", "*", "/*")))
        for tag in STYLE_TAG.findall(code):
            assert "nonce=" in tag, f"{script.name} writes {tag}"
    python = [p for p in ROOT.rglob("*.py") if not {".venv", "tests"} & set(p.parts)]
    for module in python:
        for line in module.read_text(encoding="utf-8").splitlines():
            if "<style" in line and not line.lstrip().startswith("#"):
                assert "<style{nonce_attr}>" in line, f"{module.relative_to(ROOT)}: {line.strip()}"
