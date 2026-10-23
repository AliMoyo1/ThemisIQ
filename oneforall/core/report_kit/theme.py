"""
The one look of every ThemisIQ report.

Silver and graphite, with depth. Graphite carries the text; silver carries fills, rules and bands, because silver is
not a text colour on white. Red, amber and green stay for the places where the meaning needs them (a status chip, a
figure that is over its limit) and are dark enough to read when printed grey. Nothing else is defined elsewhere:
the PDF, DOCX, XLSX and HTML renderers all read these constants, so changing a value here changes every report.
"""
from datetime import timedelta, timezone
from pathlib import Path

# ── Graphite: text and the dark covers ──────────────────────────────────────
INK = "#1F2328"         # body text on white or silver (contrast above 12 to 1 on white)
GRAPHITE = "#2E3338"    # headings, the board cover
GUNMETAL = "#3A4047"    # dark bands, table header on a dark ground
SLATE = "#5C646C"       # secondary text on white (contrast about 6 to 1)

# ── Silver: fills, rules, bands, chart series ───────────────────────────────
SILVER_DEEP = "#8A9199"
SILVER = "#B8BEC6"
SILVER_LIGHT = "#D5D9DE"
SILVER_MIST = "#E8EBEE"
PEARL = "#F4F6F8"
WHITE = "#FFFFFF"

# ── Meaning: only where red, amber or green says something ──────────────────
BAD = "#A32A22"
WARN = "#9A5B00"
GOOD = "#2E7D32"
TONES = {"neutral": GRAPHITE, "good": GOOD, "warn": WARN, "bad": BAD}

# Chart series run dark to light, so a black and white print still tells them apart. Every chart also writes its
# values on the marks, so colour is never the only carrier of the figure.
SERIES = [GRAPHITE, SLATE, SILVER_DEEP, SILVER, SILVER_LIGHT]
# Where the order itself is severity (critical to low), the darkest mark is the most severe one.
SEVERITY_ORDER = ["critical", "high", "medium", "low"]

# ── Tiers ───────────────────────────────────────────────────────────────────
BOARD, OPERATIONAL = "board", "operational"
TIERS = {
    BOARD: {"label": "Board report", "chip": "BOARD REPORT",
            "meaning": "Short and decision oriented: headline measures, the movement, the top items and what needs a decision."},
    OPERATIONAL: {"label": "Operational report", "chip": "OPERATIONAL REPORT",
                  "meaning": "The working detail: every measure, the supporting charts and the record level tables."},
}

# ── Time ────────────────────────────────────────────────────────────────────
# The application stores naive UTC. A report shows UTC first, as the stored value, and the local time beside it.
# CAT is a fixed UTC+2 with no daylight saving, so it needs no time zone database and renders the same on Windows
# and Ubuntu. To show another zone, change this one pair.
DISPLAY_ZONE_NAME = "CAT"
DISPLAY_ZONE = timezone(timedelta(hours=2), DISPLAY_ZONE_NAME)

# ── Page geometry (millimetres) ─────────────────────────────────────────────
PAGE_MARGIN_X = 18
PAGE_MARGIN_TOP = 22
PAGE_MARGIN_BOTTOM = 24
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"
# The family used by HTML and DOCX, which cannot rely on Helvetica being installed.
UI_FONT_STACK = '"Segoe UI", "Helvetica Neue", Helvetica, Arial, sans-serif'
DOCX_FONT = "Calibri"

# The existing logo asset (transparent PNG), under oneforall/static. No logo is drawn or invented here.
LOGO_PATH = Path(__file__).resolve().parents[2] / "static" / "img" / "themisiq-logo-clear.png"
LOGO_URL = "/static/img/themisiq-logo-clear.png"
PRODUCT_NAME = "ThemisIQ"
TAGLINE = "Governance, risk, compliance and privacy"


def rgb(hex_colour: str) -> tuple:
    """(r, g, b) as 0..255 integers."""
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def rgb_float(hex_colour: str) -> tuple:
    """(r, g, b) as 0..1 floats, the form reportlab canvases take."""
    r, g, b = rgb(hex_colour)
    return r / 255, g / 255, b / 255


def series_colour(index: int) -> str:
    return SERIES[index % len(SERIES)]


def ink_on(fill_hex: str) -> str:
    """The text colour that stays readable on a given fill: white on dark fills, ink on light ones."""
    r, g, b = rgb(fill_hex)
    luminance = 0.2126 * (r / 255) ** 2.2 + 0.7152 * (g / 255) ** 2.2 + 0.0722 * (b / 255) ** 2.2
    return WHITE if luminance < 0.18 else INK
