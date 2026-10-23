"""
The HTML print view of a report: a cover, the body, a footer on every printed page, and print CSS.

A page the browser prints (or saves as PDF). The same blocks as the PDF, with the charts as inline SVG made from the same
scene. Every dynamic value goes through `esc()`. The footer is a fixed element that the browser repeats on each printed
page; "Page n of N" uses CSS page margin boxes, which Chrome and Edge (131 and later) draw, and which other browsers leave
out. The PDF download always has the page numbers.
"""
from html import escape as _escape

from core.report_kit import charts, identity, theme
from core.report_kit.model import (Callout, Chart, Heading, Kpis, PageBreak, Paragraphs, Report, Table, cell_text)

FULL_PT = 482.0
HALF_PT = 234.0


def esc(value) -> str:
    return _escape("" if value is None else str(value), quote=True)


_CSS_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 .,:;()_/+#@'|-")


def css_string(text) -> str:
    """The content of a CSS string literal, safe inside a style element: every character outside a short plain list is
    written as a CSS hex escape, so a quote, a backslash, a line break or the start of a closing style tag in a name
    cannot end the string or the element."""
    return "".join(c if c in _CSS_SAFE else f"\\{ord(c):x} " for c in identity.clean_text(text, keep_newlines=False))


def _css(footer_line_a: str, footer_line_b: str) -> str:
    t = theme
    footer_font = f'font:7.5pt {t.UI_FONT_STACK}'
    return f"""
:root{{--ink:{t.INK};--graphite:{t.GRAPHITE};--gunmetal:{t.GUNMETAL};--slate:{t.SLATE};--silver-deep:{t.SILVER_DEEP};
--silver:{t.SILVER};--silver-light:{t.SILVER_LIGHT};--silver-mist:{t.SILVER_MIST};--pearl:{t.PEARL};
--bad:{t.BAD};--warn:{t.WARN};--good:{t.GOOD};--font:{t.UI_FONT_STACK}}}
*{{box-sizing:border-box}}
html{{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
body{{margin:0;background:#fff;color:var(--ink);font-family:var(--font);font-size:10pt;line-height:1.45}}
.sheet{{max-width:182mm;margin:0 auto;padding:0 6mm}}
.toolbar{{position:sticky;top:0;z-index:5;display:flex;gap:12px;align-items:center;justify-content:center;padding:10px;
background:var(--pearl);border-bottom:1px solid var(--silver)}}
.toolbar button{{font:600 13px var(--font);padding:7px 18px;border-radius:6px;border:1px solid var(--graphite);
background:var(--graphite);color:#fff;cursor:pointer}}
.toolbar span{{font-size:12px;color:var(--slate)}}
.cover{{min-height:250mm;padding:22mm 14mm 18mm;margin:10mm 0;display:flex;flex-direction:column;page-break-after:always;
break-after:page;border-radius:6px;position:relative}}
.cover.tier-operational{{background:linear-gradient(90deg,var(--silver-light) 0,var(--silver-deep) 4%,var(--silver-light) 8%,var(--pearl) 8.4%);
color:var(--ink)}}
.cover.tier-board{{background:linear-gradient(160deg,var(--graphite) 0,var(--gunmetal) 55%,#4a5159 100%);color:#fff}}
.cover .plate{{display:inline-block;align-self:flex-start;background:var(--pearl);padding:8px;border-radius:12px}}
.cover.tier-operational .plate{{background:transparent;padding:0}}
.cover img.logo{{width:42mm;height:42mm;display:block}}
.cover .chip{{align-self:flex-start;margin-top:14mm;padding:5px 16px;border-radius:999px;font:700 8.5pt var(--font);
letter-spacing:.16em}}
.tier-operational .chip{{background:var(--silver);color:var(--ink)}}
.tier-board .chip{{background:var(--silver-light);color:var(--graphite)}}
.cover h1{{font-size:27pt;line-height:1.2;margin:9mm 0 3mm;font-weight:800;letter-spacing:.01em;overflow-wrap:anywhere}}
.tier-operational h1{{color:var(--graphite)}}
.cover .subtitle{{font-size:12.5pt;margin:0 0 6mm}}
.tier-operational .subtitle{{color:var(--slate)}}.tier-board .subtitle{{color:var(--silver-light)}}
.cover hr{{border:0;border-top:1px solid var(--silver);margin:4mm 0 7mm;width:100%}}
.cover dl{{display:grid;grid-template-columns:34mm 1fr;gap:3.2mm 6mm;margin:0}}
.cover dt{{font:700 7.5pt var(--font);letter-spacing:.14em;text-transform:uppercase;padding-top:1mm}}
.tier-operational dt{{color:var(--slate)}}.tier-board dt{{color:var(--silver)}}
.cover dd{{margin:0;font-size:10.5pt;overflow-wrap:anywhere}}
.cover .band{{margin-top:auto;padding-top:10mm;font-size:8pt;display:flex;justify-content:space-between;
color:var(--slate)}}
.tier-board .band{{color:var(--silver-light)}}
h2.section{{font-size:15pt;margin:9mm 0 1mm;color:var(--graphite);border-bottom:1px solid var(--silver);padding-bottom:2mm;
break-after:avoid;page-break-after:avoid}}
p.intro{{margin:2mm 0 4mm;color:var(--slate);font-size:9pt;break-after:avoid;page-break-after:avoid}}
.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:3mm;margin:3mm 0}}
.kpi{{background:var(--pearl);border:1px solid var(--silver-light);padding:3mm 4mm;border-radius:4px;break-inside:avoid}}
.kpi .l{{font:700 7pt var(--font);letter-spacing:.08em;text-transform:uppercase;color:var(--slate)}}
.kpi .v{{font:800 19pt var(--font);color:var(--graphite);line-height:1.2}}
.kpi .v.good{{color:var(--good)}}.kpi .v.warn{{color:var(--warn)}}.kpi .v.bad{{color:var(--bad)}}
.kpi .n{{font-size:7.5pt;color:var(--slate)}}
.chart{{margin:4mm 0;break-inside:avoid;page-break-inside:avoid}}
.chart h3{{font-size:10pt;margin:0;color:var(--graphite)}}
.chart p{{margin:0 0 1.5mm;font-size:8.5pt;font-style:italic;color:var(--slate)}}
.pair{{display:grid;grid-template-columns:1fr 1fr;gap:6mm;break-inside:avoid}}
table.data{{width:100%;border-collapse:collapse;font-size:8pt;margin:2mm 0}}
table.data thead{{display:table-header-group}}
table.data th{{background:var(--silver);color:var(--ink);text-align:left;padding:4px 5px;border-bottom:1.5px solid var(--silver-deep)}}
table.data td{{padding:4px 5px;border-bottom:1px solid var(--silver-light);vertical-align:top;overflow-wrap:anywhere}}
table.data td a{{color:var(--graphite);text-decoration:underline}}
table.data tbody tr:nth-child(even){{background:var(--silver-mist)}}
table.data tr{{break-inside:avoid;page-break-inside:avoid}}
.r,table.data th.r{{text-align:right}}.c,table.data th.c{{text-align:center}}
h3.tt{{font-size:10pt;margin:6mm 0 1mm;color:var(--graphite);break-after:avoid}}
.note{{font-size:8pt;color:var(--slate);margin:1mm 0 4mm}}
.empty{{background:var(--pearl);border:1px solid var(--silver-light);padding:3mm;font-size:8.5pt;color:var(--slate);font-style:italic}}
.callout{{background:var(--pearl);border:1px solid var(--silver);padding:3.5mm 5mm;margin:4mm 0;break-inside:avoid;border-radius:4px}}
.callout h3{{margin:0 0 1.5mm;font-size:10pt;color:var(--graphite)}}.callout ul{{margin:0;padding-left:5mm}}
.callout li{{margin:.5mm 0;font-size:9.5pt}}
.para h3{{font-size:10pt;margin:5mm 0 1mm;color:var(--graphite)}}.para .label{{font-size:8pt;font-style:italic;color:var(--slate)}}
.para p{{margin:0 0 2.5mm}}
.toolbar .warn{{display:none;color:var(--bad)}}
html.no-margin-boxes .toolbar .warn{{display:inline}}
@page{{size:A4;margin:14mm 14mm 26mm 14mm;
@bottom-left{{content:"{footer_line_a}\\A {footer_line_b}";white-space:pre;{footer_font};color:{t.INK};
border-top:0.7pt solid {t.SILVER};vertical-align:top;padding-top:3mm;text-align:left;width:80%}}
@bottom-right{{content:"Page " counter(page) " of " counter(pages);{footer_font};font-weight:600;color:{t.SLATE};
border-top:0.7pt solid {t.SILVER};vertical-align:top;padding-top:3mm;text-align:right;width:20%}}}}
@media print{{
.toolbar{{display:none}}.sheet{{max-width:none;padding:0}}
.cover{{margin:0;border-radius:0;min-height:256mm;height:256mm}}
}}
"""


def _kpis(block: Kpis) -> str:
    cells = []
    for kpi in block.items:
        tone = kpi.tone if kpi.tone in ("good", "warn", "bad") else ""
        note = f'<div class="n">{esc(kpi.note)}</div>' if kpi.note else ""
        cells.append(f'<div class="kpi"><div class="l">{esc(kpi.label)}</div><div class="v {tone}">{esc(kpi.value)}</div>{note}</div>')
    title = f'<h3 class="tt">{esc(block.title)}</h3>' if block.title else ""
    return f'{title}<div class="kpis">{"".join(cells)}</div>'


def _chart(block: Chart, width_pt: float) -> str:
    drawing = charts.build_drawing(block, width_pt)
    svg = charts.drawing_to_svg(drawing, label=charts.alt_text(block))
    return (f'<figure class="chart" style="margin:4mm 0"><h3>{esc(block.title)}</h3><p>{esc(charts.takeaway(block))}</p>{svg}</figure>')


def _cell(row, col) -> str:
    """One table value, as an anchor when the column names a row key holding a safe address."""
    text = esc(cell_text(row.get(col.key), col.kind))
    url = identity.safe_link(row.get(col.link)) if col.link else ""
    return f'<a href="{esc(url)}" rel="noopener noreferrer">{text}</a>' if url else text


def _table(block: Table) -> str:
    title = f'<h3 class="tt">{esc(block.title)}</h3>' if block.title else ""
    rows = block.shown()
    if not rows:
        return f'{title}<div class="empty">{esc(block.empty_text)}</div>'
    align = {"right": "r", "center": "c"}
    head = "".join(f'<th class="{align.get(c.align, "")}" scope="col">{esc(c.header)}</th>' for c in block.columns)
    body = "".join("<tr>" + "".join(
        f'<td class="{align.get(c.align, "")}">{_cell(row, c)}</td>' for c in block.columns) + "</tr>"
        for row in rows)
    notes = " ".join(n for n in (block.truncation_note(), block.note) if n)
    note = f'<div class="note">{esc(notes)}</div>' if notes else ""
    return f'{title}<table class="data"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>{note}'


def _blocks(report: Report) -> str:
    out, blocks, i = [], report.blocks, 0
    while i < len(blocks):
        block = blocks[i]
        if isinstance(block, Heading):
            intro = f'<p class="intro">{esc(block.intro)}</p>' if block.intro else ""
            out.append(f'<h2 class="section">{esc(block.text)}</h2>{intro}')
        elif isinstance(block, Kpis):
            out.append(_kpis(block))
        elif isinstance(block, Chart):
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            if block.half and isinstance(nxt, Chart) and nxt.half:
                out.append(f'<div class="pair">{_chart(block, HALF_PT)}{_chart(nxt, HALF_PT)}</div>')
                i += 1
            else:
                out.append(_chart(block, FULL_PT))
        elif isinstance(block, Table):
            out.append(_table(block))
        elif isinstance(block, Paragraphs):
            label = f'<div class="label">{esc(block.label)}</div>' if block.label else ""
            paragraphs = "".join(f"<p>{esc(identity.clean_text(t))}</p>" for t in block.paragraphs if identity.clean_text(t))
            out.append(f'<div class="para"><h3>{esc(block.title)}</h3>{label}{paragraphs}</div>')
        elif isinstance(block, Callout):
            items = "".join(f"<li>{esc(item)}</li>" for item in block.items)
            out.append(f'<div class="callout"><h3>{esc(block.title)}</h3><ul>{items}</ul></div>')
        elif isinstance(block, PageBreak):
            out.append('<div style="break-after:page;page-break-after:always"></div>')
        i += 1
    return "".join(out)


_SUPPORT_CHECK = ("(function(){var m=/(?:Chrome|Edg)\\/(\\d+)/.exec(navigator.userAgent);"
                  "if(!m||parseInt(m[1],10)<131){document.documentElement.classList.add('no-margin-boxes');}})();")


def render_html(report: Report, *, logo_url: str = theme.LOGO_URL, print_button: bool = True) -> str:
    """The print view as a full HTML document."""
    meta = report.meta
    facts = "".join(f"<dt>{esc(label)}</dt><dd>{esc(value)}</dd>" for label, value in meta.cover_rows())
    subtitle = f'<p class="subtitle">{esc(meta.subtitle)}</p>' if meta.subtitle else ""
    toolbar = ('<div class="toolbar"><button type="button" onclick="window.print()">Print or save as PDF</button>'
               '<span>Turn on background graphics in the print dialog for the full silver look.</span>'
               '<span class="warn">This browser may leave out the footer and page numbers. Print from Chrome or Edge, or '
               'download the PDF.</span></div>' if print_button else "")
    footer_a = css_string(f"{meta.footer_module()}   |   {meta.footer_who()}")
    footer_b = css_string(f"{meta.footer_when()}   |   {meta.confidentiality}   |   {meta.tier_label}")
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="robots" content="noindex, nofollow">'
        f"<title>{esc(meta.title)}</title><style>{_css(footer_a, footer_b)}</style>"
        f"<script>{_SUPPORT_CHECK}</script></head>"
        f'<body class="report tier-{esc(meta.tier)}">{toolbar}<div class="sheet">'
        f'<section class="cover tier-{esc(meta.tier)}" aria-label="Cover">'
        f'<span class="plate"><img class="logo" src="{esc(logo_url)}" alt="ThemisIQ"></span>'
        f'<span class="chip">{esc(meta.tier_chip)}</span><h1>{esc(meta.title)}</h1>{subtitle}<hr><dl>{facts}</dl>'
        f'<div class="band"><span><strong>{esc(theme.PRODUCT_NAME)}</strong> &nbsp;{esc(theme.TAGLINE)}</span>'
        f'<span>{esc(meta.confidentiality)}</span></div></section>'
        f"<main>{_blocks(report)}</main></div></body></html>"
    )
