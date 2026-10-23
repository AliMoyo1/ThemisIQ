"""The application uses SVG icons from one sprite and no emoji (plans/2026-10-svg-icons.md).

These checks read the source, so they run without a browser: no emoji or emoji-style symbol in a template, script,
stylesheet or Python string; every icon reference names a symbol that exists in the sprite; and icon markup is never
placed where it would be shown as text (inside an escape call, an attribute value or an option).
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("templates", "modules", "static", "core")
SKIP_PARTS = {"vendor", "icons", "__pycache__"}
EXTS = {".html", ".js", ".css", ".py", ".md", ".txt"}

# Pictographs and emoji-style symbols. Arrows, check marks and the middle dot used as typography are not listed.
EMOJI = re.compile(
    "[\U0001F300-\U0001FAFF\U0001F000-\U0001F2FF\u2600-\u27BF\u2B50\u2B55\u2B1B\u2B1C\u231A\u231B\u23E9-\u23F3"
    "\u23F8-\u23FA\u25B6\u25C0\u25FB-\u25FE\u2934\u2935\u3030\u303D\u3297\u3299\U0001F1E6-\U0001F1FF]"
)
TYPOGRAPHY = set("\u2713\u2714\u2715\u2716\u2717\u2718\u2605\u2606\u25B6\u25C0\u2022\u2192\u2190\u2191\u2193\u2197\u2198"
                 "\u21BB\u2026\u00B7\u2318\u2610\u2611\u2612\u2660\u2663\u2665\u2666\u2670\u2692\u267B\u2603\u2600"
                 "\u263E\u263D\u2699")
ENTITY = re.compile(r"&#(x[0-9a-fA-F]+|\d+);")
ESCAPE = re.compile(r"\\u\{([0-9a-fA-F]+)\}|\\U([0-9a-fA-F]{8})|\\u([0-9a-fA-F]{4})")
USE = re.compile(r"sprite\.svg#(ic-[a-z0-9-]+)")


def _files():
    for d in SCAN_DIRS:
        for path in (ROOT / d).rglob("*"):
            if path.is_file() and path.suffix in EXTS and not (SKIP_PARTS & set(path.parts)):
                yield path


def _is_emoji(ch):
    return bool(EMOJI.fullmatch(ch)) and ch not in TYPOGRAPHY


def _emoji_in(text):
    found = [m.group(0) for m in EMOJI.finditer(text) if _is_emoji(m.group(0))]
    for m in ENTITY.finditer(text):
        raw = m.group(1)
        cp = int(raw[1:], 16) if raw[0] == "x" else int(raw)
        if cp < 0x110000 and _is_emoji(chr(cp)):
            found.append(f"&#{raw};")
    for m in ESCAPE.finditer(text):
        raw = m.group(1) or m.group(2) or m.group(3)
        cp = int(raw, 16)
        if cp < 0x110000 and _is_emoji(chr(cp)):
            found.append(m.group(0))
    return found


def test_no_emoji_anywhere_in_the_application():
    offenders = {}
    for path in _files():
        hits = _emoji_in(path.read_text(encoding="utf-8", errors="ignore"))
        if hits:
            offenders[str(path.relative_to(ROOT)).replace("\\", "/")] = hits[:5]
    assert not offenders, f"emoji found (use an icon from static/icons/sprite.svg instead): {offenders}"


def test_every_icon_reference_exists_in_the_sprite():
    sprite = (ROOT / "static" / "icons" / "sprite.svg").read_text(encoding="utf-8")
    symbols = set(re.findall(r'<symbol id="(ic-[a-z0-9-]+)"', sprite))
    assert len(symbols) > 50
    missing = {}
    for path in _files():
        for name in USE.findall(path.read_text(encoding="utf-8", errors="ignore")):
            if name not in symbols:
                missing.setdefault(str(path.relative_to(ROOT)).replace("\\", "/"), set()).add(name)
    assert not missing, f"icons referenced but not in the sprite: {missing}"


def test_icon_markup_is_never_placed_where_it_would_show_as_text():
    bad = []
    escape_call = re.compile(r"\b(?:esc|escHtml|escChartAttr|escapeHtml|escTrainer)\([^()\n]{0,120}<svg class=")
    in_attribute = re.compile(r"""(?:title|placeholder|aria-label|alt|value)=["'][^"'<>]*<svg class=""")
    in_option = re.compile(r"<option[^>]*>[^<]{0,40}<svg class=")
    text_assign = re.compile(r"(?:textContent|innerText)\s*=\s*['\"`][^'\"`\n]*<svg class=")
    for path in _files():
        if path.suffix not in {".html", ".js"}:
            continue
        for n, line in enumerate(path.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
            for rule, name in ((escape_call, "inside an escape call"), (in_attribute, "inside an attribute"),
                               (in_option, "inside an option"), (text_assign, "assigned as text")):
                if rule.search(line):
                    bad.append(f"{path.relative_to(ROOT)}:{n} {name}")
    assert not bad, "\n".join(bad)


def test_the_sprite_keeps_its_licence_and_loads_from_the_shell():
    assert "ISC License" in (ROOT / "static" / "icons" / "LICENSE-lucide.txt").read_text(encoding="utf-8")
    shell = (ROOT / "templates" / "base_shell.html").read_text(encoding="utf-8")
    assert "/static/css/icons.css" in shell
    css = (ROOT / "static" / "css" / "icons.css").read_text(encoding="utf-8")
    assert ".ic," in css and "prefers-reduced-motion" in css
