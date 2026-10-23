"""Build static/icons/sprite.svg from Lucide icons (ISC licence, see static/icons/LICENSE-lucide.txt).

Run from oneforall/ with the GitHub CLI signed in:  python scripts/build_icon_sprite.py

Every icon the app uses is listed in ICONS. Add a name here, rerun, and reference it as
<svg class=ic aria-hidden=true><use href=/static/icons/sprite.svg#ic-NAME></use></svg>
(unquoted attribute values, so the same text is safe inside single-quoted, double-quoted and template-literal strings).
"""
import re
import subprocess
import sys
from pathlib import Path

ICONS = sorted("""
alarm-clock arrow-right asterisk banknote bell bot brain building calculator calendar chart-column circle-check
circle-x clipboard-list clock cloud database dollar-sign file-pen file-text folder-open graduation-cap globe file-clock
hourglass house image inbox key landmark laptop library lightbulb link loader lock lock-open mail map medal
megaphone message-square microscope monitor package paperclip pencil plug refresh-cw rocket save scale scroll-text search send
settings shield siren smartphone sparkles syringe target telescope thumbs-down thumbs-up timer toolbox trash
trending-up triangle-alert truck user users wrench zap sun moon
""".split())

OUT = Path(__file__).resolve().parent.parent / "static" / "icons"


def lucide(path: str) -> str:
    return subprocess.run(
        ["gh", "api", "-H", "Accept: application/vnd.github.raw", f"repos/lucide-icons/lucide/contents/{path}"],
        check=True, capture_output=True, text=True, encoding="utf-8").stdout


def inner(svg: str) -> str:
    body = re.search(r"<svg[^>]*>(.*)</svg>", svg, re.S).group(1)
    return re.sub(r"\s+", " ", body).strip()


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    symbols = []
    for name in ICONS:
        try:
            body = inner(lucide(f"icons/{name}.svg"))
        except subprocess.CalledProcessError:
            print(f"no Lucide icon named {name}", file=sys.stderr)
            return 1
        symbols.append(f'<symbol id="ic-{name}" viewBox="0 0 24 24">{body}</symbol>')
    # A filled dot for status (colour comes from the .ic-dot classes in icons.css), the only symbol not from Lucide.
    symbols.append('<symbol id="ic-dot" viewBox="0 0 24 24"><circle cx="12" cy="12" r="6" fill="currentColor" stroke="none"/></symbol>')
    sprite = ('<svg xmlns="http://www.w3.org/2000/svg" style="display:none">\n'
              "<!-- Icons: Lucide, ISC licence, see LICENSE-lucide.txt. Built by scripts/build_icon_sprite.py. -->\n"
              + "\n".join(symbols) + "\n</svg>\n")
    (OUT / "sprite.svg").write_text(sprite, encoding="utf-8", newline="\n")
    (OUT / "LICENSE-lucide.txt").write_text(lucide("LICENSE"), encoding="utf-8", newline="\n")
    print(f"wrote {len(symbols)} symbols, {len(sprite):,} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
