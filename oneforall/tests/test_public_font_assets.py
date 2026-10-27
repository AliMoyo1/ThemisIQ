"""Guard public pages against broken or third-party font delivery."""

import re
from pathlib import Path


LANDING = Path(__file__).resolve().parents[2] / "landing_page"


def test_public_pages_load_local_fonts_and_every_referenced_face_exists():
    for page in ("index.html", "features.html", "privacy.html", "terms.html"):
        html = (LANDING / page).read_text(encoding="utf-8")
        assert "fonts/fonts.css" in html, page
        assert "fonts.googleapis.com" not in html, page
        assert "fonts.gstatic.com" not in html, page

    css = (LANDING / "fonts" / "fonts.css").read_text(encoding="utf-8")
    faces = re.findall(r"url\(\./([\w-]+\.woff2)\)", css)
    assert faces
    for face in faces:
        assert (LANDING / "fonts" / face).read_bytes()[:4] == b"wOF2"

    for family in ("instrumentsans", "newsreader", "inter"):
        assert (LANDING / "fonts" / "licenses" / f"{family}-OFL.txt").is_file()

    for page in ("privacy.html", "terms.html"):
        html = (LANDING / page).read_text(encoding="utf-8")
        assert "cdn.tailwindcss.com" not in html
        assert "tailwind.min.css" in html
