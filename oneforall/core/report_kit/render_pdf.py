"""
The PDF of a report: a cover with the logo, then the body, and the footer on every page.

Reportlab platypus. The cover is painted on the canvas (a dark gunmetal cover for a board report, a light silver one for an
operational report); the body is built from the report's blocks; the footer (module, who, when, tier, "Page n of N") is
painted on every page, the cover included, once the page count is known.
"""
import io

from reportlab.lib import colors as rl_colors
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib.utils import simpleSplit
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (BaseDocTemplate, CondPageBreak, Frame, HRFlowable, KeepTogether, NextPageTemplate,
                                PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle)

from core.report_kit import charts, identity, theme
from core.report_kit.model import (Callout, Chart, Heading, Kpis, PageBreak as PageBreakBlock, Paragraphs, Report,
                                   Table as TableBlock, cell_text)

PAGE_W, PAGE_H = A4
MARGIN_X = theme.PAGE_MARGIN_X * mm
MARGIN_TOP = theme.PAGE_MARGIN_TOP * mm
MARGIN_BOTTOM = theme.PAGE_MARGIN_BOTTOM * mm
FRAME_W = PAGE_W - 2 * MARGIN_X
FRAME_H = PAGE_H - MARGIN_TOP - MARGIN_BOTTOM
BAND_H = 74            # the cover's bottom band, which also carries the footer text


def _c(hex_colour):
    return rl_colors.HexColor(hex_colour)


def _styles() -> dict:
    base = dict(fontName=theme.FONT, textColor=_c(theme.INK), alignment=TA_LEFT)
    return {
        "body": ParagraphStyle("tiq_body", fontSize=9.5, leading=13.5, spaceAfter=6, **base),
        "small": ParagraphStyle("tiq_small", fontSize=8, leading=11, **{**base, "textColor": _c(theme.SLATE)}),
        "h1": ParagraphStyle("tiq_h1", fontSize=15, leading=19, spaceBefore=14, spaceAfter=3, keepWithNext=1,
                             **{**base, "fontName": theme.FONT_BOLD, "textColor": _c(theme.GRAPHITE)}),
        "intro": ParagraphStyle("tiq_intro", fontSize=9, leading=12.5, spaceAfter=8, **{**base, "textColor": _c(theme.SLATE)}),
        "h2": ParagraphStyle("tiq_h2", fontSize=10, leading=13, spaceBefore=6, spaceAfter=1, keepWithNext=1,
                             **{**base, "fontName": theme.FONT_BOLD, "textColor": _c(theme.GRAPHITE)}),
        "takeaway": ParagraphStyle("tiq_takeaway", fontSize=8.5, leading=11.5, spaceAfter=4,
                                   **{**base, "fontName": theme.FONT_ITALIC, "textColor": _c(theme.SLATE)}),
        "th": ParagraphStyle("tiq_th", fontSize=8, leading=10, **{**base, "fontName": theme.FONT_BOLD}),
        "td": ParagraphStyle("tiq_td", fontSize=8, leading=10.2, **base),
        "kpi_label": ParagraphStyle("tiq_kl", fontSize=7, leading=9, **{**base, "fontName": theme.FONT_BOLD, "textColor": _c(theme.SLATE)}),
        "kpi_note": ParagraphStyle("tiq_kn", fontSize=7.5, leading=9.5, **{**base, "textColor": _c(theme.SLATE)}),
        "callout_title": ParagraphStyle("tiq_ct", fontSize=9.5, leading=12.5, spaceAfter=3,
                                        **{**base, "fontName": theme.FONT_BOLD, "textColor": _c(theme.GRAPHITE)}),
        "callout": ParagraphStyle("tiq_c", fontSize=8.8, leading=12, leftIndent=11, bulletIndent=0, spaceAfter=2, **base),
    }


# ── Cover ───────────────────────────────────────────────────────────────────

def _wrapped(canv, text, x, y, width, font, size, leading, colour, max_lines):
    """Draw wrapped text down from `y`; the last allowed line ends in an ellipsis when the text is longer."""
    lines = simpleSplit(identity.pdf_text(text), font, size, width)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = charts.fit(lines[-1] + " …", size, width, bold=(font == theme.FONT_BOLD))
    canv.setFillColor(_c(colour))
    canv.setFont(font, size)
    for line in lines:
        canv.drawString(x, y, line)
        y -= leading
    return y


def _gradient_band(canv, x, y, w, h, stops, horizontal=True):
    """A metallic band: a linear gradient through the given colours."""
    canv.saveState()
    path = canv.beginPath()
    path.rect(x, y, w, h)
    canv.clipPath(path, stroke=0, fill=0)
    positions = [i / (len(stops) - 1) for i in range(len(stops))]
    if horizontal:
        canv.linearGradient(x, y, x + w, y, [_c(s) for s in stops], positions)
    else:
        canv.linearGradient(x, y, x, y + h, [_c(s) for s in stops], positions)
    canv.restoreState()


def _draw_cover(canv, meta):
    board = meta.tier == theme.BOARD
    canv._tiq_kind = "cover_board" if board else "cover"
    canv.saveState()
    # Ground
    canv.setFillColor(_c(theme.GRAPHITE if board else theme.PEARL))
    canv.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
    if board:
        # Brushed metal: translucent silver planes at slight angles give the dark cover its depth.
        for alpha, (y0, y1, y2) in ((0.05, (250, 470, 842)), (0.07, (120, 320, 560)), (0.09, (0, 160, 330))):
            canv.saveState()
            canv.setFillColor(_c(theme.SILVER))
            canv.setFillAlpha(alpha)
            path = canv.beginPath()
            path.moveTo(0, y0)
            path.lineTo(PAGE_W, y1)
            path.lineTo(PAGE_W, y2)
            path.lineTo(0, min(y2, y0 + 300))
            path.close()
            canv.drawPath(path, stroke=0, fill=1)
            canv.restoreState()
    else:
        _gradient_band(canv, 0, 0, 22, PAGE_H, [theme.SILVER_LIGHT, theme.SILVER_DEEP, theme.SILVER_LIGHT], horizontal=False)
        canv.setFillColor(_c(theme.SILVER_MIST))
        canv.rect(22, 0, 4, PAGE_H, stroke=0, fill=1)

    left = MARGIN_X + (0 if board else 14)
    # Logo: on a pearl plate on the dark cover, straight on the light one. The asset is the existing ThemisIQ logo.
    logo_top = PAGE_H - 52
    if board:
        canv.setFillColor(_c(theme.PEARL))
        canv.roundRect(left, logo_top - 138, 138, 138, 14, stroke=0, fill=1)
        canv.drawImage(str(theme.LOGO_PATH), left + 9, logo_top - 129, 120, 120, mask="auto", preserveAspectRatio=True)
        title_top = logo_top - 138
    else:
        canv.drawImage(str(theme.LOGO_PATH), left - 6, logo_top - 132, 132, 132, mask="auto", preserveAspectRatio=True)
        title_top = logo_top - 132
    text_w = PAGE_W - left - MARGIN_X

    # Tier chip (letter spaced; the spacing is part of the graphics state, so it is kept inside save and restore)
    chip_top = title_top - 34
    canv.saveState()
    canv.setFillColor(_c(theme.SILVER_LIGHT if board else theme.SILVER))
    chip_w = canv.stringWidth(meta.tier_chip, theme.FONT_BOLD, 8.5) + 1.6 * (len(meta.tier_chip) - 1) + 26
    canv.roundRect(left, chip_top - 22, chip_w, 22, 11, stroke=0, fill=1)
    canv.setFillColor(_c(theme.GRAPHITE if board else theme.INK))
    text = canv.beginText(left + 13, chip_top - 15)
    text.setFont(theme.FONT_BOLD, 8.5)
    text.setCharSpace(1.6)
    text.textOut(meta.tier_chip)
    canv.drawText(text)
    canv.restoreState()

    # Title and subtitle
    y = chip_top - 22 - 40
    y = _wrapped(canv, meta.title, left, y, text_w, theme.FONT_BOLD, 28, 33, theme.WHITE if board else theme.GRAPHITE, 3)
    if meta.subtitle:
        y = _wrapped(canv, meta.subtitle, left, y - 4, text_w, theme.FONT, 12.5, 17, theme.SILVER_LIGHT if board else theme.SLATE, 2)
    y -= 12
    canv.setStrokeColor(_c(theme.SILVER_DEEP if board else theme.SILVER))
    canv.setLineWidth(0.8)
    canv.line(left, y, left + text_w, y)
    y -= 26

    # The labelled facts: scope, period, module, who, when
    label_colour = theme.SILVER if board else theme.SLATE
    value_colour = theme.WHITE if board else theme.INK
    for label, value in meta.cover_rows():
        if y < BAND_H + 40:
            break
        canv.setFillColor(_c(label_colour))
        canv.setFont(theme.FONT_BOLD, 7.5)
        canv.drawString(left, y, label.upper())
        y = _wrapped(canv, value, left + 112, y, text_w - 112, theme.FONT, 10, 13, value_colour, 3)
        y -= 11

    # Bottom band: carries the footer text and the product line
    if board:
        _gradient_band(canv, 0, 0, PAGE_W, BAND_H, [theme.SILVER_DEEP, theme.SILVER_LIGHT, theme.SILVER_DEEP])
    else:
        canv.setFillColor(_c(theme.GUNMETAL))
        canv.rect(0, 0, PAGE_W, BAND_H, stroke=0, fill=1)
    canv.setFillColor(_c(theme.GRAPHITE if board else theme.SILVER_LIGHT))
    canv.setFont(theme.FONT_BOLD, 8)
    canv.drawString(left, BAND_H - 15, theme.PRODUCT_NAME)
    canv.setFont(theme.FONT, 8)
    canv.drawString(left + 46, BAND_H - 15, theme.TAGLINE)
    canv.drawRightString(PAGE_W - MARGIN_X, BAND_H - 15, identity.pdf_text(meta.confidentiality))
    canv.restoreState()


def _draw_header(canv, meta):
    canv._tiq_kind = "body"
    canv.saveState()
    top = PAGE_H - 34
    canv.setFillColor(_c(theme.GRAPHITE))
    canv.setFont(theme.FONT_BOLD, 9)
    canv.drawString(MARGIN_X, top, theme.PRODUCT_NAME)
    canv.setFillColor(_c(theme.SLATE))
    canv.setFont(theme.FONT, 8)
    canv.drawRightString(PAGE_W - MARGIN_X, top, charts.fit(meta.title, 8, FRAME_W - 90))
    canv.setStrokeColor(_c(theme.SILVER))
    canv.setLineWidth(0.7)
    canv.line(MARGIN_X, top - 7, PAGE_W - MARGIN_X, top - 7)
    canv.restoreState()


# ── Footer, with the page count known ───────────────────────────────────────

class _NumberedCanvas(rl_canvas.Canvas):
    def __init__(self, *args, meta=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._tiq_meta = meta
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_footer(total)
            super().showPage()
        super().save()

    def _draw_footer(self, total):
        meta = self._tiq_meta
        kind = getattr(self, "_tiq_kind", "body")
        if kind == "cover_board":
            text_colour, soft = theme.GRAPHITE, theme.GRAPHITE
        elif kind == "cover":
            text_colour, soft = theme.SILVER_LIGHT, theme.SILVER
        else:
            text_colour, soft = theme.GRAPHITE, theme.SLATE
        self.saveState()
        if kind == "body":
            self.setStrokeColor(_c(theme.SILVER))
            self.setLineWidth(0.7)
            self.line(MARGIN_X, 52, PAGE_W - MARGIN_X, 52)
        right_a = identity.pdf_text(meta.tier_label)
        right_b = f"Page {self._pageNumber} of {total}"
        self.setFont(theme.FONT_BOLD, 7.5)
        right_w = max(self.stringWidth(right_a, theme.FONT_BOLD, 7.5), self.stringWidth(right_b, theme.FONT_BOLD, 7.5)) + 14
        room = PAGE_W - 2 * MARGIN_X - right_w
        line_a = charts.fit(f"{meta.footer_module()}   |   {meta.footer_who()}", 7.5, room, bold=False)
        line_b = charts.fit(f"{meta.footer_when()}   |   {meta.confidentiality}", 7.5, room)
        self.setFillColor(_c(text_colour))
        self.setFont(theme.FONT, 7.5)
        self.drawString(MARGIN_X, 38, line_a)
        self.setFillColor(_c(soft))
        self.drawString(MARGIN_X, 27, line_b)
        self.setFillColor(_c(text_colour))
        self.setFont(theme.FONT_BOLD, 7.5)
        self.drawRightString(PAGE_W - MARGIN_X, 38, right_a)
        self.setFillColor(_c(soft))
        self.drawRightString(PAGE_W - MARGIN_X, 27, right_b)
        self.restoreState()


# ── Blocks to flowables ─────────────────────────────────────────────────────

def _p(text, style) -> Paragraph:
    return Paragraph(identity.markup_safe(text).replace("\n", "<br/>"), style)


def _kpis(block: Kpis, styles) -> list:
    out = []
    if block.title:
        out.append(_p(block.title, styles["h2"]))
    per_row = 4 if len(block.items) > 3 else max(len(block.items), 1)
    gap = 6
    tile_w = (FRAME_W - gap * (per_row - 1)) / per_row
    items = list(block.items)
    for start in range(0, len(items), per_row):
        row = items[start:start + per_row]
        cells, widths, style = [], [], []
        for index, kpi in enumerate(row):
            value_style = ParagraphStyle("tiq_kv", fontName=theme.FONT_BOLD, fontSize=19, leading=23,
                                         textColor=_c(theme.TONES.get(kpi.tone, theme.GRAPHITE)))
            content = [_p(kpi.label.upper(), styles["kpi_label"]), _p(kpi.value, value_style)]
            if kpi.note:
                content.append(_p(kpi.note, styles["kpi_note"]))
            col = index * 2
            cells.append(content)
            widths.append(tile_w)
            style += [("BACKGROUND", (col, 0), (col, 0), _c(theme.PEARL)), ("BOX", (col, 0), (col, 0), 0.6, _c(theme.SILVER_LIGHT))]
            if index < len(row) - 1:
                cells.append("")
                widths.append(gap)
        table = Table([cells], colWidths=widths, hAlign="LEFT")
        table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 9),
                                   ("RIGHTPADDING", (0, 0), (-1, -1), 6), ("TOPPADDING", (0, 0), (-1, -1), 7),
                                   ("BOTTOMPADDING", (0, 0), (-1, -1), 8)] + style))
        out += [table, Spacer(1, 6)]
    return out


def _chart_parts(chart: Chart, width: float, styles) -> list:
    return [_p(chart.title, styles["h2"]), _p(charts.takeaway(chart), styles["takeaway"]),
            charts.build_drawing(chart, width)]


def _chart(chart: Chart, styles) -> list:
    return [KeepTogether(_chart_parts(chart, FRAME_W, styles)), Spacer(1, 8)]


def _chart_pair(left: Chart, right: Chart, styles) -> list:
    half = (FRAME_W - 14) / 2
    table = Table([[_chart_parts(left, half - 4, styles), _chart_parts(right, half - 4, styles)]],
                  colWidths=[half, half + 0], hAlign="LEFT")
    table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (0, 0), 14), ("RIGHTPADDING", (1, 0), (1, 0), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    return [KeepTogether([table]), Spacer(1, 8)]


def _cell_markup(row, col) -> str:
    """One table value as Paragraph markup: a clickable, underlined link when the column names a row key holding a safe address."""
    text = identity.markup_safe(cell_text(row.get(col.key), col.kind))
    url = identity.safe_link(row.get(col.link)) if col.link else ""
    return f'<a href="{url.replace("&", "&amp;")}" color="{theme.GRAPHITE}"><u>{text}</u></a>' if url else text


def _table(block: TableBlock, styles) -> list:
    # A long table must be free to run over pages, so its title is not tied to it with keepWithNext (reportlab would then
    # push the whole table to a fresh page and leave the previous one empty). A conditional break stops an orphan title.
    title_style = ParagraphStyle("tiq_h2_table", parent=styles["h2"], keepWithNext=0)
    out = [CondPageBreak(110), _p(block.title, title_style)] if block.title else [CondPageBreak(90)]
    columns = block.columns
    total_weight = sum(col.weight for col in columns) or 1.0
    widths = [FRAME_W * col.weight / total_weight for col in columns]
    head_align = {"left": TA_LEFT, "right": TA_RIGHT, "center": 1}
    header = [Paragraph(identity.markup_safe(col.header),
                        ParagraphStyle(f"th_{i}", parent=styles["th"], alignment=head_align.get(col.align, TA_LEFT)))
              for i, col in enumerate(columns)]
    rows = block.shown()
    if not rows:
        empty = Table([[_p(block.empty_text, styles["small"])]], colWidths=[FRAME_W])
        empty.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _c(theme.PEARL)), ("BOX", (0, 0), (-1, -1), 0.5, _c(theme.SILVER_LIGHT)),
                                   ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
        return out + [empty, Spacer(1, 8)]
    data = [header]
    for row in rows:
        data.append([Paragraph(_cell_markup(row, col), ParagraphStyle(f"td_{i}", parent=styles["td"], alignment=head_align.get(col.align, TA_LEFT)))
                     for i, col in enumerate(columns)])
    table = Table(data, colWidths=widths, repeatRows=1, splitByRow=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), _c(theme.SILVER)), ("LINEBELOW", (0, 0), (-1, 0), 0.8, _c(theme.SILVER_DEEP)),
             ("GRID", (0, 1), (-1, -1), 0.3, _c(theme.SILVER_LIGHT)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
             ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5)]
    for i in range(2, len(data), 2):
        style.append(("BACKGROUND", (0, i), (-1, i), _c(theme.SILVER_MIST)))
    table.setStyle(TableStyle(style))
    out.append(table)
    notes = " ".join(n for n in (block.truncation_note(), block.note) if n)
    if notes:
        out.append(_p(notes, styles["small"]))
    out.append(Spacer(1, 8))
    return out


def _paragraphs(block: Paragraphs, styles) -> list:
    out = [_p(block.title, styles["h2"])]
    if block.label:
        out.append(_p(block.label, styles["small"]))
    out += [_p(text, styles["body"]) for text in block.paragraphs if identity.clean_text(text)]
    return out + [Spacer(1, 4)]


def _callout(block: Callout, styles) -> list:
    content = [_p(block.title, styles["callout_title"])]
    content += [Paragraph(identity.markup_safe(item), styles["callout"], bulletText="•") for item in block.items]
    box = Table([[content]], colWidths=[FRAME_W])
    box.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), _c(theme.PEARL)), ("BOX", (0, 0), (-1, -1), 0.7, _c(theme.SILVER)),
                             ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
                             ("TOPPADDING", (0, 0), (-1, -1), 9), ("BOTTOMPADDING", (0, 0), (-1, -1), 8)]))
    return [KeepTogether([box]), Spacer(1, 10)]


def _lead_height(blocks, i) -> float:
    """How tall the chart (or the pair of half width charts) is that a heading at `i` leads into, or 0 when it leads into anything
    else. reportlab cannot tie a heading to a keep-together chart, so the heading asks for the room itself."""
    first = blocks[i + 1] if i + 1 < len(blocks) else None
    if not isinstance(first, Chart):
        return 0
    second = blocks[i + 2] if i + 2 < len(blocks) else None
    if first.half and isinstance(second, Chart) and second.half:
        half = (FRAME_W - 14) / 2 - 4
        return max(charts.build_drawing(c, half).height for c in (first, second)) + 44
    return charts.build_drawing(first, FRAME_W).height + 44


def _heading(block: Heading, styles, lead=0) -> list:
    rule = HRFlowable(width="100%", thickness=0.8, color=_c(theme.SILVER), spaceAfter=6)
    rule.keepWithNext = 1       # the heading, its rule and its intro travel with what follows, so none is left alone at a page foot
    need = 46 + (24 if block.intro else 0) + lead     # the heading, its rule and its intro, then the chart that follows
    out = [CondPageBreak(min(max(130, need), FRAME_H - 30)), _p(block.text, styles["h1"]), rule]
    if block.intro:
        out.append(_p(block.intro, ParagraphStyle("tiq_intro_k", parent=styles["intro"], keepWithNext=1)))
    return out


def _flowables(report: Report, styles) -> list:
    story, blocks, i = [], report.blocks, 0
    while i < len(blocks):
        block = blocks[i]
        if isinstance(block, Heading):
            story += _heading(block, styles, _lead_height(blocks, i))
        elif isinstance(block, Kpis):
            story += _kpis(block, styles)
        elif isinstance(block, Chart):
            nxt = blocks[i + 1] if i + 1 < len(blocks) else None
            if block.half and isinstance(nxt, Chart) and nxt.half:
                story += _chart_pair(block, nxt, styles)
                i += 1
            else:
                story += _chart(block, styles)
        elif isinstance(block, TableBlock):
            story += _table(block, styles)
        elif isinstance(block, Paragraphs):
            story += _paragraphs(block, styles)
        elif isinstance(block, Callout):
            story += _callout(block, styles)
        elif isinstance(block, PageBreakBlock):
            story.append(PageBreak())
        i += 1
    return story


# ── Entry point ─────────────────────────────────────────────────────────────

def render_pdf(report: Report) -> bytes:
    """The report as PDF bytes."""
    meta = report.meta
    buffer = io.BytesIO()
    doc = BaseDocTemplate(
        buffer, pagesize=A4, leftMargin=MARGIN_X, rightMargin=MARGIN_X, topMargin=MARGIN_TOP, bottomMargin=MARGIN_BOTTOM,
        title=identity.pdf_text(meta.title)[:200], author=identity.pdf_text(meta.who)[:200],
        subject=identity.pdf_text(f"{meta.module_label}: {meta.tier_label}")[:200], creator=theme.PRODUCT_NAME,
        keywords=identity.pdf_text(f"{theme.PRODUCT_NAME}, {meta.tier_label}")[:200])
    body_frame = Frame(MARGIN_X, MARGIN_BOTTOM, FRAME_W, PAGE_H - MARGIN_TOP - MARGIN_BOTTOM, leftPadding=0, rightPadding=0,
                       topPadding=0, bottomPadding=0, id="body")
    cover_frame = Frame(MARGIN_X, BAND_H, FRAME_W, 10, leftPadding=0, rightPadding=0, topPadding=0, bottomPadding=0, id="cover")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame], onPage=lambda c, d: _draw_cover(c, meta)),
        PageTemplate(id="body", frames=[body_frame], onPage=lambda c, d: _draw_header(c, meta)),
    ])
    styles = _styles()
    story = [Spacer(1, 1), NextPageTemplate("body"), PageBreak()] + _flowables(report, styles)
    doc.build(story, canvasmaker=lambda *a, **k: _NumberedCanvas(*a, meta=meta, **k))
    return buffer.getvalue()
