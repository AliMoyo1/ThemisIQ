"""
The DOCX of a report: a cover section with the logo, then the body, with a real header and a real footer on every page.

python-docx. The footer holds the module, who generated the report, when, the tier and "Page n of N" (PAGE and NUMPAGES
fields, so Word counts the pages itself). Charts are the PNG that charts.drawing_to_png paints from the same scene the PDF
draws; every table repeats its header row on each page. Elements added by hand are inserted in schema order, because Word
rejects a file whose properties are out of order.
"""
import io

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

from core.report_kit import charts, identity, theme
from core.report_kit.model import (Callout, Chart, Heading, Kpis, PageBreak, Paragraphs, Report, Table, cell_text)

CONTENT_W_CM = 17.0
CONTENT_W_PT = CONTENT_W_CM / 2.54 * 72

# The order OOXML requires for the children of these property elements.
_ORDERS = {
    "tcPr": ["cnfStyle", "tcW", "gridSpan", "hMerge", "vMerge", "tcBorders", "shd", "noWrap", "tcMar", "textDirection",
             "tcFitText", "vAlign", "hideMark"],
    "pPr": ["pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl", "numPr", "suppressLineNumbers",
            "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku", "wordWrap", "overflowPunct", "topLinePunct",
            "autoSpaceDE", "autoSpaceDN", "bidi", "adjustRightInd", "snapToGrid", "spacing", "ind", "contextualSpacing",
            "mirrorIndents", "suppressOverlap", "jc", "textDirection", "textAlignment", "textboxTightWrap", "outlineLvl",
            "divId", "cnfStyle", "rPr", "sectPr", "pPrChange"],
    "rPr": ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline", "shadow",
            "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing", "w", "kern",
            "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em",
            "lang", "eastAsianLayout", "specVanish", "oMath"],
    "trPr": ["cnfStyle", "divId", "gridBefore", "gridAfter", "wBefore", "wAfter", "cantSplit", "trHeight", "tblHeader",
             "tblCellSpacing", "jc", "hidden"],
}


def _local(element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _put(parent, child):
    """Add `child` to `parent` at the position the schema gives it."""
    order = _ORDERS[_local(parent)]
    rank = order.index(_local(child))
    for existing in parent:
        name = _local(existing)
        if name in order and order.index(name) > rank:
            existing.addprevious(child)
            return child
    parent.append(child)
    return child


def _rgb(hex_colour) -> RGBColor:
    r, g, b = theme.rgb(hex_colour)
    return RGBColor(r, g, b)


def _shade(target, fill):
    """Background shading on a table cell or a paragraph."""
    is_cell = hasattr(target, "_tc")
    properties = target._tc.get_or_add_tcPr() if is_cell else target._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill.lstrip("#"))
    _put(properties, shd)


def _borders(cell, colour=theme.SILVER_LIGHT, size=4, sides=("top", "left", "bottom", "right")):
    box = OxmlElement("w:tcBorders")
    for side in ("top", "left", "bottom", "right"):
        edge = OxmlElement(f"w:{side}")
        if side in sides:
            edge.set(qn("w:val"), "single")
            edge.set(qn("w:sz"), str(size))
            edge.set(qn("w:space"), "0")
            edge.set(qn("w:color"), colour.lstrip("#"))
        else:
            edge.set(qn("w:val"), "nil")
        box.append(edge)
    _put(cell._tc.get_or_add_tcPr(), box)


def _para_border(paragraph, side="bottom", colour=theme.SILVER, size=6):
    box = OxmlElement("w:pBdr")
    edge = OxmlElement(f"w:{side}")
    edge.set(qn("w:val"), "single")
    edge.set(qn("w:sz"), str(size))
    edge.set(qn("w:space"), "4")
    edge.set(qn("w:color"), colour.lstrip("#"))
    box.append(edge)
    _put(paragraph._p.get_or_add_pPr(), box)


def _run(paragraph, text, size=10, bold=False, italic=False, colour=theme.INK, caps=False, spacing=None, raw=False):
    """Add a styled run. `raw` keeps the text exactly (a tab, a trailing blank); otherwise it is cleaned."""
    run = paragraph.add_run(text if raw else identity.clean_text(text))
    run.font.name = theme.DOCX_FONT
    run._element.rPr.rFonts.set(qn("w:eastAsia"), theme.DOCX_FONT)
    run.font.size = Pt(size)
    run.bold = bold
    run.italic = italic
    run.font.color.rgb = _rgb(colour)
    if caps:
        run.font.all_caps = True
    if spacing:
        element = OxmlElement("w:spacing")
        element.set(qn("w:val"), str(int(spacing * 20)))
        _put(run._element.rPr, element)
    return run


def _link(paragraph, text, url, size=10, colour=theme.GRAPHITE):
    """A clickable run: an external hyperlink relationship, so Word keeps the address. Underlined, in graphite (no blue)."""
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), paragraph.part.relate_to(url, RT.HYPERLINK, is_external=True))
    link.set(qn("w:history"), "1")
    run = _run(paragraph, text, size=size, colour=colour)
    run.font.underline = True
    link.append(run._element)
    paragraph._p.append(link)
    return run


def _field(paragraph, instruction, size=8, colour=theme.SLATE, bold=False):
    """A Word field (PAGE, NUMPAGES): Word fills in the number itself when it lays the document out."""
    def part():
        return _run(paragraph, "", size=size, colour=colour, bold=bold, raw=True)

    begin = OxmlElement("w:fldChar")
    begin.set(qn("w:fldCharType"), "begin")
    part()._element.append(begin)
    instr = OxmlElement("w:instrText")
    instr.set(qn("xml:space"), "preserve")
    instr.text = f" {instruction} "
    part()._element.append(instr)
    separate = OxmlElement("w:fldChar")
    separate.set(qn("w:fldCharType"), "separate")
    part()._element.append(separate)
    _run(paragraph, "1", size=size, colour=colour, bold=bold, raw=True)
    end = OxmlElement("w:fldChar")
    end.set(qn("w:fldCharType"), "end")
    part()._element.append(end)


def _space(paragraph, before=0, after=0):
    paragraph.paragraph_format.space_before = Pt(before)
    paragraph.paragraph_format.space_after = Pt(after)


def _para(container, text="", size=10, bold=False, italic=False, colour=theme.INK, align=None, before=0, after=4):
    paragraph = container.add_paragraph()
    if text:
        _run(paragraph, text, size, bold, italic, colour)
    if align is not None:
        paragraph.alignment = align
    _space(paragraph, before, after)
    return paragraph


def _set_widths(table, widths_cm):
    table.autofit = False
    for row in table.rows:
        for index, cell in enumerate(row.cells):
            cell.width = Cm(widths_cm[index])


def _row_flag(row, name):
    flag = OxmlElement(f"w:{name}")
    flag.set(qn("w:val"), "true")
    _put(row._tr.get_or_add_trPr(), flag)


# ── Cover ───────────────────────────────────────────────────────────────────

def _cover(doc, meta):
    board = meta.tier == theme.BOARD
    picture_par = doc.add_paragraph()
    picture_par.add_run().add_picture(str(theme.LOGO_PATH), width=Cm(4.2))
    _space(picture_par, 30, 12)

    chip = doc.add_paragraph()
    _run(chip, f" {meta.tier_chip} ", size=9, bold=True, colour=theme.WHITE if board else theme.INK, spacing=1.2)
    _shade(chip, theme.GRAPHITE if board else theme.SILVER)
    chip.paragraph_format.right_indent = Cm(CONTENT_W_CM - 5.6)     # keeps the shading to the width of a label
    _space(chip, 10, 10)

    band = doc.add_table(rows=1, cols=1)
    band.alignment = WD_TABLE_ALIGNMENT.LEFT
    cell = band.cell(0, 0)
    _shade(cell, theme.GRAPHITE if board else theme.SILVER_LIGHT)
    _borders(cell, sides=())
    _run(cell.paragraphs[0], meta.title, size=26, bold=True, colour=theme.WHITE if board else theme.GRAPHITE)
    _space(cell.paragraphs[0], 14, 4)
    if meta.subtitle:
        sub = cell.add_paragraph()
        _run(sub, meta.subtitle, size=12, colour=theme.SILVER_LIGHT if board else theme.SLATE)
        _space(sub, 0, 14)
    _set_widths(band, [CONTENT_W_CM])
    _para(doc, "", after=8)

    facts = doc.add_table(rows=0, cols=2)
    for label, value in meta.cover_rows():
        row = facts.add_row()
        _row_flag(row, "cantSplit")
        _run(row.cells[0].paragraphs[0], label, size=8, bold=True, colour=theme.SLATE, caps=True, spacing=0.6)
        _run(row.cells[1].paragraphs[0], value, size=11)
        for cell in row.cells:
            _borders(cell, theme.SILVER_LIGHT, 4, sides=("bottom",))
            _space(cell.paragraphs[0], 5, 5)
    _set_widths(facts, [4.2, CONTENT_W_CM - 4.2])
    _para(doc, f"{theme.PRODUCT_NAME}  |  {theme.TAGLINE}  |  {meta.confidentiality}", size=8, colour=theme.SLATE, before=26)


# ── Header and footer ───────────────────────────────────────────────────────

def _plain(paragraph, doc):
    """Use the Normal style so the Header and Footer styles' own tab stops do not pull a tab to the wrong place."""
    paragraph.style = doc.styles["Normal"]
    paragraph.text = ""


def _footer(section, meta, doc):
    section.footer.is_linked_to_previous = False
    footer = section.footer
    first = footer.paragraphs[0]
    _plain(first, doc)
    _para_border(first, "top", theme.SILVER, 6)
    first.paragraph_format.tab_stops.add_tab_stop(Cm(CONTENT_W_CM), WD_TAB_ALIGNMENT.RIGHT)
    _run(first, f"{meta.footer_module()}   |   {meta.footer_who()}", size=8, colour=theme.INK)
    _run(first, "\t", size=8, raw=True)
    _run(first, meta.tier_label, size=8, bold=True, colour=theme.INK)
    _space(first, 0, 1)
    second = footer.add_paragraph(style=doc.styles["Normal"])
    second.paragraph_format.tab_stops.add_tab_stop(Cm(CONTENT_W_CM), WD_TAB_ALIGNMENT.RIGHT)
    _run(second, f"{meta.footer_when()}   |   {meta.confidentiality}", size=8, colour=theme.SLATE)
    _run(second, "\tPage ", size=8, colour=theme.SLATE, bold=True, raw=True)
    _field(second, "PAGE", bold=True)
    _run(second, " of ", size=8, colour=theme.SLATE, bold=True, raw=True)
    _field(second, "NUMPAGES", bold=True)
    _space(second, 0, 0)


def _header(section, meta, doc):
    section.header.is_linked_to_previous = False
    paragraph = section.header.paragraphs[0]
    _plain(paragraph, doc)
    paragraph.paragraph_format.tab_stops.add_tab_stop(Cm(CONTENT_W_CM), WD_TAB_ALIGNMENT.RIGHT)
    _run(paragraph, theme.PRODUCT_NAME, size=9, bold=True, colour=theme.GRAPHITE)
    _run(paragraph, "\t" + identity.ellipsize(meta.title, 90), size=8, colour=theme.SLATE, raw=True)
    _para_border(paragraph, "bottom", theme.SILVER, 6)


# ── Blocks ──────────────────────────────────────────────────────────────────

def _heading(doc, block: Heading):
    paragraph = doc.add_paragraph(style="Heading 1")
    _run(paragraph, block.text, size=16, bold=True, colour=theme.GRAPHITE)
    _space(paragraph, 14, 2)
    paragraph.paragraph_format.keep_with_next = True
    _para_border(paragraph, "bottom", theme.SILVER, 8)
    if block.intro:
        _para(doc, block.intro, size=9, colour=theme.SLATE, before=3, after=6)


def _kpis(doc, block: Kpis):
    if block.title:
        _para(doc, block.title, size=10, bold=True, colour=theme.GRAPHITE, before=4, after=2)
    items = list(block.items)
    per_row = 4 if len(items) > 3 else max(len(items), 1)
    for start in range(0, len(items), per_row):
        row_items = items[start:start + per_row]
        table = doc.add_table(rows=1, cols=per_row)
        table.alignment = WD_TABLE_ALIGNMENT.LEFT
        for index in range(per_row):
            cell = table.cell(0, index)
            if index >= len(row_items):
                _borders(cell, sides=())
                continue
            kpi = row_items[index]
            _shade(cell, theme.PEARL)
            _borders(cell, theme.SILVER_LIGHT, 6)
            first = cell.paragraphs[0]
            _run(first, kpi.label, size=7, bold=True, colour=theme.SLATE, caps=True, spacing=0.4)
            _space(first, 3, 0)
            value = cell.add_paragraph()
            _run(value, kpi.value, size=18, bold=True, colour=theme.TONES.get(kpi.tone, theme.GRAPHITE))
            _space(value, 0, 0)
            if kpi.note:
                note = cell.add_paragraph()
                _run(note, kpi.note, size=8, colour=theme.SLATE)
                _space(note, 0, 3)
        _set_widths(table, [CONTENT_W_CM / per_row] * per_row)
        _para(doc, "", size=4, after=2)


def _picture(paragraph, chart: Chart, width_pt: float, width_cm: float):
    drawing = charts.build_drawing(chart, width_pt)
    shape = paragraph.add_run().add_picture(io.BytesIO(charts.drawing_to_png(drawing)), width=Cm(width_cm))
    shape._inline.docPr.set("descr", charts.alt_text(chart)[:250])
    shape._inline.docPr.set("title", chart.title[:120])


def _chart(doc, block: Chart):
    title = _para(doc, block.title, size=10, bold=True, colour=theme.GRAPHITE, before=6, after=0)
    title.paragraph_format.keep_with_next = True
    take = _para(doc, charts.takeaway(block), size=9, italic=True, colour=theme.SLATE, after=2)
    take.paragraph_format.keep_with_next = True
    holder = doc.add_paragraph()
    _picture(holder, block, CONTENT_W_PT, CONTENT_W_CM)
    _space(holder, 0, 8)


def _chart_pair(doc, left: Chart, right: Chart):
    table = doc.add_table(rows=1, cols=2)
    half_cm, half_pt = CONTENT_W_CM / 2 - 0.3, CONTENT_W_PT / 2 - 9
    for cell, chart in zip(table.rows[0].cells, (left, right)):
        _borders(cell, sides=())
        first = cell.paragraphs[0]
        _run(first, chart.title, size=10, bold=True, colour=theme.GRAPHITE)
        _space(first, 4, 0)
        take = cell.add_paragraph()
        _run(take, charts.takeaway(chart), size=9, italic=True, colour=theme.SLATE)
        _space(take, 0, 2)
        _picture(cell.add_paragraph(), chart, half_pt, half_cm)
    _row_flag(table.rows[0], "cantSplit")
    _set_widths(table, [CONTENT_W_CM / 2, CONTENT_W_CM / 2])
    _para(doc, "", size=4, after=4)


def _table(doc, block: Table):
    if block.title:
        paragraph = _para(doc, block.title, size=10, bold=True, colour=theme.GRAPHITE, before=6, after=2)
        paragraph.paragraph_format.keep_with_next = True
    rows = block.shown()
    if not rows:
        _para(doc, block.empty_text, size=9, italic=True, colour=theme.SLATE, after=6)
        return
    columns = block.columns
    table = doc.add_table(rows=1 + len(rows), cols=len(columns))
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    total_weight = sum(col.weight for col in columns) or 1.0
    widths = [CONTENT_W_CM * col.weight / total_weight for col in columns]
    align = {"left": WD_ALIGN_PARAGRAPH.LEFT, "right": WD_ALIGN_PARAGRAPH.RIGHT, "center": WD_ALIGN_PARAGRAPH.CENTER}
    for index, col in enumerate(columns):
        cell = table.cell(0, index)
        _shade(cell, theme.SILVER)
        _borders(cell, theme.SILVER_DEEP, 4, sides=("bottom",))
        _run(cell.paragraphs[0], col.header, size=8, bold=True, colour=theme.INK)
        cell.paragraphs[0].alignment = align.get(col.align, WD_ALIGN_PARAGRAPH.LEFT)
        _space(cell.paragraphs[0], 2, 2)
    _row_flag(table.rows[0], "tblHeader")
    for r, row in enumerate(rows, start=1):
        _row_flag(table.rows[r], "cantSplit")
        for index, col in enumerate(columns):
            cell = table.cell(r, index)
            if r % 2 == 0:
                _shade(cell, theme.SILVER_MIST)
            _borders(cell, theme.SILVER_LIGHT, 4)
            text = cell_text(row.get(col.key), col.kind)
            url = identity.safe_link(row.get(col.link)) if col.link else ""
            if url:
                _link(cell.paragraphs[0], text, url, size=8)
            else:
                _run(cell.paragraphs[0], text, size=8)
            cell.paragraphs[0].alignment = align.get(col.align, WD_ALIGN_PARAGRAPH.LEFT)
            _space(cell.paragraphs[0], 2, 2)
    _set_widths(table, widths)
    notes = " ".join(n for n in (block.truncation_note(), block.note) if n)
    _para(doc, notes, size=8, colour=theme.SLATE, before=3, after=8)


def _paragraphs(doc, block: Paragraphs):
    _para(doc, block.title, size=10, bold=True, colour=theme.GRAPHITE, before=6, after=1).paragraph_format.keep_with_next = True
    if block.label:
        _para(doc, block.label, size=8, italic=True, colour=theme.SLATE, after=3)
    for text in block.paragraphs:
        if identity.clean_text(text):
            _para(doc, text, size=10, after=6)


def _callout(doc, block: Callout):
    table = doc.add_table(rows=1, cols=1)
    cell = table.cell(0, 0)
    _shade(cell, theme.PEARL)
    _borders(cell, theme.SILVER, 6)
    first = cell.paragraphs[0]
    _run(first, block.title, size=10, bold=True, colour=theme.GRAPHITE)
    _space(first, 4, 3)
    for item in block.items:
        paragraph = cell.add_paragraph()
        _run(paragraph, "•  " + item, size=9.5)
        paragraph.paragraph_format.left_indent = Cm(0.4)
        paragraph.paragraph_format.first_line_indent = Cm(-0.4)
        _space(paragraph, 0, 2)
    _set_widths(table, [CONTENT_W_CM])
    _para(doc, "", size=4, after=6)


# ── Entry point ─────────────────────────────────────────────────────────────

def render_docx(report: Report) -> bytes:
    """The report as DOCX bytes."""
    meta = report.meta
    doc = Document()
    props = doc.core_properties
    props.title = identity.clean_text(meta.title, keep_newlines=False)[:200]
    props.author = identity.clean_text(meta.who, keep_newlines=False)[:200]
    props.subject = f"{meta.module_label}: {meta.tier_label}"
    props.keywords = f"{theme.PRODUCT_NAME}, {meta.tier_label}"
    props.comments = f"Generated by {theme.PRODUCT_NAME}"

    normal = doc.styles["Normal"]
    normal.font.name = theme.DOCX_FONT
    normal.font.size = Pt(10)
    normal.font.color.rgb = _rgb(theme.INK)
    for name in ("Heading 1",):
        style = doc.styles[name]
        style.font.name = theme.DOCX_FONT
        style.font.color.rgb = _rgb(theme.GRAPHITE)

    section = doc.sections[0]
    section.page_width, section.page_height = Cm(21.0), Cm(29.7)
    section.left_margin = section.right_margin = Cm(2.0)
    section.top_margin, section.bottom_margin = Cm(2.2), Cm(2.4)
    section.footer_distance = Cm(1.0)
    _footer(section, meta, doc)
    _cover(doc, meta)

    body = doc.add_section(WD_SECTION.NEW_PAGE)
    body.left_margin = body.right_margin = Cm(2.0)
    body.top_margin, body.bottom_margin = Cm(2.4), Cm(2.4)
    body.footer_distance = Cm(1.0)
    _header(body, meta, doc)
    _footer(body, meta, doc)      # its own footer part: a reader that does not inherit a footer still shows one

    blocks, i = report.blocks, 0
    while i < len(blocks):
        block = blocks[i]
        if isinstance(block, Heading):
            _heading(doc, block)
        elif isinstance(block, Kpis):
            _kpis(doc, block)
        elif isinstance(block, Chart):
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            if block.half and isinstance(nxt, Chart) and nxt.half:
                _chart_pair(doc, block, nxt)
                i += 1
            else:
                _chart(doc, block)
        elif isinstance(block, Table):
            _table(doc, block)
        elif isinstance(block, Paragraphs):
            _paragraphs(doc, block)
        elif isinstance(block, Callout):
            _callout(doc, block)
        elif isinstance(block, PageBreak):
            doc.add_page_break()
        i += 1

    buffer = io.BytesIO()
    doc.save(buffer)
    return buffer.getvalue()
