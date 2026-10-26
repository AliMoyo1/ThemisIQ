"""Refresh the landing site's locally served Google Fonts assets.

Run manually from the repository root. Review the generated CSS, fonts and
license notices before committing; this script is never used at request time.
"""

from __future__ import annotations

import hashlib
import re
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
OUT = ROOT / "fonts"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
FAMILIES = {
    "Instrument Sans": ("Instrument+Sans:wght@400;500;600;700", "instrumentsans"),
    "Newsreader": ("Newsreader:ital,opsz,wght@1,6..72,400;1,6..72,500", "newsreader"),
    "Inter": ("Inter:wght@400;500;600;700", "inter"),
}


def download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    license_dir = OUT / "licenses"
    license_dir.mkdir(exist_ok=True)
    faces = []
    for family, (query, slug) in FAMILIES.items():
        css = download(f"https://fonts.googleapis.com/css2?family={query}&display=swap").decode()
        # Google emits several unicode subsets. The Latin face is the last
        # block for each style/weight. Reuse a single WOFF2 when the face is
        # variable and Google returns the same URL for multiple weights.
        selected = {}
        for block in re.findall(r"@font-face\s*\{[^}]+\}", css, flags=re.DOTALL):
            style = re.search(r"font-style:\s*([^;]+);", block)
            weight = re.search(r"font-weight:\s*([^;]+);", block)
            url = re.search(r"url\((https://[^)]+\.woff2)\)", block)
            if style and weight and url:
                selected[(style.group(1), weight.group(1))] = (block, url.group(1))
        if not selected:
            raise RuntimeError(f"No WOFF2 Latin faces received for {family}")
        for block, url in selected.values():
            payload = download(url)
            digest = hashlib.sha256(payload).hexdigest()[:12]
            filename = f"{slug}-{digest}.woff2"
            (OUT / filename).write_bytes(payload)
            faces.append(block.replace(url, f"./{filename}"))
        license_url = f"https://raw.githubusercontent.com/google/fonts/main/ofl/{slug}/OFL.txt"
        license_text = download(license_url).decode("utf-8")
        (license_dir / f"{slug}-OFL.txt").write_text(
            "\n".join(line.rstrip() for line in license_text.splitlines()) + "\n",
            encoding="utf-8",
        )
    (OUT / "fonts.css").write_text(
        "/* Self-hosted landing-page fonts. Regenerate with landing_page/fetch_fonts.py. */\n"
        + "\n\n".join(faces) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
