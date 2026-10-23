"""
The charts of every report, drawn once and shown four ways.

A `Chart` block (model.py) becomes a reportlab `Drawing`, a scene of rectangles, lines, text and wedges. The PDF places
that drawing as it is (vector), the HTML print view turns the same scene into an inline SVG, and a DOCX takes a PNG that
a small Pillow rasteriser paints from the same scene. XLSX gets native Excel charts from the same data (render_xlsx).
One geometry, so the four formats cannot disagree about what a chart says.

Design rules, in every chart: a title and a one line takeaway sit with it (the renderers place them), the axes carry a
label and the unit, every mark carries its value as text so a black and white print reads, series run dark to light, and
too little data draws a plain empty state instead of a chart that implies something.
"""
import math
import os
from html import escape as _xml

from reportlab.graphics.shapes import Circle, Drawing, Group, Line, PolyLine, Rect, String, Wedge
from reportlab.pdfbase.pdfmetrics import stringWidth

from core.report_kit import identity, theme
from core.report_kit.model import Chart

ROW_H = 17
BAR_H = 10
LABEL_SIZE = 8
SMALL = 7


# ── Measuring and small drawing helpers ─────────────────────────────────────

def text_width(text, size, bold=False) -> float:
    return stringWidth(text, theme.FONT_BOLD if bold else theme.FONT, size)


def fit(text, size, max_width, bold=False) -> str:
    """The text cut with an ellipsis so that it is no wider than `max_width`."""
    text = identity.pdf_text(text)
    if text_width(text, size, bold) <= max_width:
        return text
    while text and text_width(text + "…", size, bold) > max_width:
        text = text[:-1]
    return text.rstrip() + "…"


def _hex(colour):
    from reportlab.lib.colors import HexColor
    return HexColor(colour)


def _string(drawing, x, y, text, size=LABEL_SIZE, bold=False, colour=theme.INK, anchor="start", italic=False):
    font = theme.FONT_BOLD if bold else (theme.FONT_ITALIC if italic else theme.FONT)
    drawing.add(String(x, y, identity.pdf_text(text), fontName=font, fontSize=size, fillColor=_hex(colour), textAnchor=anchor))


def _rect(drawing, x, y, w, h, fill=None, stroke=None, stroke_width=0.5):
    drawing.add(Rect(x, y, w, h, fillColor=_hex(fill) if fill else None,
                     strokeColor=_hex(stroke) if stroke else None, strokeWidth=stroke_width if stroke else 0))


def _line(drawing, x1, y1, x2, y2, colour=theme.SILVER_LIGHT, width=0.5):
    drawing.add(Line(x1, y1, x2, y2, strokeColor=_hex(colour), strokeWidth=width))


def nice_ticks(maximum, count=4, whole=False) -> list:
    """Round tick values from 0 up to a round number at or above `maximum`; `whole` keeps every tick a whole number."""
    maximum = float(maximum or 1)
    if maximum <= 0:
        maximum = 1.0
    raw = maximum / count
    magnitude = 10 ** math.floor(math.log10(raw))
    for step in ((1, 2, 5, 10) if whole else (1, 2, 2.5, 5, 10)):
        if raw <= step * magnitude:
            step *= magnitude
            break
    if whole:
        step = max(step, 1.0)
    top = math.ceil(maximum / step) * step
    ticks, value = [], 0.0
    while value <= top + step * 0.001:
        ticks.append(value)
        value += step
    return ticks


def _whole(values) -> bool:
    return all(v is None or abs(float(v) - round(float(v))) < 1e-9 for v in values)


def _fmt_value(value, unit="") -> str:
    if value is None:
        return "n/a"
    number = float(value)
    text = identity.fmt_int(number) if abs(number - round(number)) < 1e-9 else identity.fmt_number(number, 1)
    return f"{text}%" if unit == "%" else text


def _fit_ticks(maximum, whole, unit, plot_w) -> list:
    """Round ticks along a horizontal axis, as few as keep their labels apart: four steps, else three, else two."""
    for count in (4, 3, 2):
        ticks = nice_ticks(maximum, count=count, whole=whole)
        if max(text_width(_fmt_value(t, unit), SMALL) for t in ticks) * 1.4 * len(ticks) <= plot_w:
            break
    return ticks


def _wrap(text, size, max_width, bold=False) -> list:
    words, lines, current = identity.pdf_text(text).split(), [], ""
    for word in words:
        trial = f"{current} {word}".strip()
        if text_width(trial, size, bold) <= max_width or not current:
            current = trial
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [""]


def _axis_title(drawing, width, x_start, x_end, text):
    if text:
        _string(drawing, (x_start + x_end) / 2, 3, fit(text, SMALL + 0.5, width - 10), SMALL + 0.5, colour=theme.SLATE, anchor="middle")


# ── The empty state ─────────────────────────────────────────────────────────

def _empty(chart, width) -> Drawing:
    lines = _wrap(chart.empty_text, LABEL_SIZE, width - 24)
    height = 26 + 11 * len(lines)
    drawing = Drawing(width, height)
    _rect(drawing, 0, 0, width, height, fill=theme.PEARL, stroke=theme.SILVER_LIGHT)
    top = height - 20
    for line in lines:
        _string(drawing, width / 2, top, line, LABEL_SIZE, colour=theme.SLATE, anchor="middle", italic=True)
        top -= 11
    return drawing


def label_lines(text, size, max_width) -> list:
    """A category label as one line, or two when it does not fit on one (the second is cut with an ellipsis if it must be)."""
    text = identity.pdf_text(text)
    if text_width(text, size) <= max_width:
        return [text]
    words, first = text.split(" "), ""
    for index, word in enumerate(words):
        trial = f"{first} {word}".strip()
        if text_width(trial, size) <= max_width:
            first = trial
            continue
        rest = " ".join(words[index:])
        return [first or fit(word, size, max_width), fit(rest, size, max_width)] if first else [fit(text, size, max_width)]
    return [text]


def _draw_label(drawing, x, row_bottom, row_h, lines):
    """Right aligned category label, vertically centred on the row, one or two lines."""
    centre = row_bottom + row_h / 2
    if len(lines) == 1:
        _string(drawing, x, centre - LABEL_SIZE * 0.35, lines[0], LABEL_SIZE, anchor="end")
    else:
        _string(drawing, x, centre + 1.5, lines[0], LABEL_SIZE, anchor="end")
        _string(drawing, x, centre - LABEL_SIZE - 0.5, lines[1], LABEL_SIZE, anchor="end")


# ── Horizontal bars ─────────────────────────────────────────────────────────

def _bar(chart, width) -> Drawing:
    # A missing figure (None) is drawn as "n/a" with no bar. It is never drawn as a zero.
    rows = [(identity.pdf_text(label), None if value is None else float(value)) for label, value in chart.data]
    label_w = min(max(text_width(label, LABEL_SIZE) for label, _ in rows) + 12, width * 0.42)
    lines_of = [label_lines(label, LABEL_SIZE, label_w - 8) for label, _ in rows]
    row_h = ROW_H + (9 if any(len(lines) > 1 for lines in lines_of) else 0)
    value_texts = [_fmt_value(value, chart.unit) for _, value in rows]
    value_w = max(text_width(t, LABEL_SIZE, True) for t in value_texts) + 8
    plot_x, plot_w = label_w, max(width - label_w - value_w - 4, 40)
    top = 15 if chart.y_label else 5
    axis_h = 28
    height = top + len(rows) * row_h + axis_h
    top_value = chart.max_value or max([value for _, value in rows if value is not None] + [1])
    ticks = _fit_ticks(top_value, chart.unit != "%" and _whole(v for _, v in rows), chart.unit, plot_w)
    scale_max = float(chart.max_value) if chart.max_value else ticks[-1]
    drawing = Drawing(width, height)
    if chart.y_label:
        _string(drawing, 0, height - 9, fit(chart.y_label, SMALL + 0.5, width), SMALL + 0.5, colour=theme.SLATE)
    plot_top = height - top
    plot_bottom = axis_h
    for tick in ticks:
        if tick > scale_max + 1e-9:
            continue
        x = plot_x + tick / scale_max * plot_w
        _line(drawing, x, plot_bottom, x, plot_top, theme.SILVER_MIST, 0.6)
        _string(drawing, x, plot_bottom - 10, _fmt_value(tick, chart.unit), SMALL, colour=theme.SLATE, anchor="middle")
    _line(drawing, plot_x, plot_bottom, plot_x, plot_top, theme.SILVER_DEEP, 0.8)
    for index, ((label, value), text) in enumerate(zip(rows, value_texts)):
        y = plot_top - (index + 1) * row_h
        bar_w = 0 if value is None else max(min(value / scale_max, 1.0) * plot_w, 0)
        colour = (chart.colours[index % len(chart.colours)] if chart.colours else theme.SILVER_DEEP)
        _draw_label(drawing, plot_x - 6, y, row_h, lines_of[index])
        if bar_w > 0:
            _rect(drawing, plot_x, y + (row_h - BAR_H) / 2, bar_w, BAR_H, fill=colour, stroke=theme.GRAPHITE, stroke_width=0.4)
        _string(drawing, plot_x + bar_w + 4, y + row_h / 2 - LABEL_SIZE * 0.35, text, LABEL_SIZE, bold=True)
    _axis_title(drawing, width, plot_x, plot_x + plot_w, chart.x_label)
    return drawing


# ── Stacked bars: the parts of one total, one row per item ──────────────────

def _stack(chart, width) -> Drawing:
    rows = [(identity.pdf_text(label), [(identity.pdf_text(name), 0 if value is None else float(value)) for name, value in segments])
            for label, segments in chart.data]
    names = []
    for _, segments in rows:
        for name, _ in segments:
            if name not in names:
                names.append(name)
    colours = {name: (chart.colours[i % len(chart.colours)] if chart.colours else theme.series_colour(i))
               for i, name in enumerate(names)}
    totals = [sum(value for _, value in segments) for _, segments in rows]
    label_w = min(max(text_width(label, LABEL_SIZE) for label, _ in rows) + 12, width * 0.36)
    lines_of = [label_lines(label, LABEL_SIZE, label_w - 8) for label, _ in rows]
    row_h = ROW_H + (9 if any(len(lines) > 1 for lines in lines_of) else 0)
    total_texts = [_fmt_value(t, chart.unit) for t in totals]
    total_w = max(text_width(t, LABEL_SIZE, True) for t in total_texts) + 8
    plot_x, plot_w = label_w, max(width - label_w - total_w - 4, 40)
    top = 15 if chart.y_label else 5
    legend_lines = _legend_layout(names, width)
    axis_h = 28 + 12 * len(legend_lines)
    height = top + len(rows) * row_h + axis_h
    ticks = _fit_ticks(chart.max_value or max(totals + [1]), _whole(totals), chart.unit, plot_w)
    scale_max = float(chart.max_value) if chart.max_value else ticks[-1]
    drawing = Drawing(width, height)
    if chart.y_label:
        _string(drawing, 0, height - 9, fit(chart.y_label, SMALL + 0.5, width), SMALL + 0.5, colour=theme.SLATE)
    plot_top = height - top
    plot_bottom = axis_h
    for tick in ticks:
        if tick > scale_max + 1e-9:
            continue
        x = plot_x + tick / scale_max * plot_w
        _line(drawing, x, plot_bottom, x, plot_top, theme.SILVER_MIST, 0.6)
        _string(drawing, x, plot_bottom - 10, _fmt_value(tick, chart.unit), SMALL, colour=theme.SLATE, anchor="middle")
    _line(drawing, plot_x, plot_bottom, plot_x, plot_top, theme.SILVER_DEEP, 0.8)
    for index, ((label, segments), text) in enumerate(zip(rows, total_texts)):
        y = plot_top - (index + 1) * row_h
        _draw_label(drawing, plot_x - 6, y, row_h, lines_of[index])
        x = plot_x
        for name, value in segments:
            seg_w = max(min(value / scale_max, 1.0) * plot_w, 0)
            if seg_w <= 0:
                continue
            _rect(drawing, x, y + (row_h - BAR_H) / 2, seg_w, BAR_H, fill=colours[name], stroke=theme.WHITE, stroke_width=0.8)
            if seg_w >= 15:
                _string(drawing, x + seg_w / 2, y + row_h / 2 - SMALL * 0.35, _fmt_value(value), SMALL, bold=True,
                        colour=theme.ink_on(colours[name]), anchor="middle")
            x += seg_w
        _string(drawing, plot_x + sum(min(v / scale_max, 1.0) * plot_w for _, v in segments) + 4,
                y + row_h / 2 - LABEL_SIZE * 0.35, text, LABEL_SIZE, bold=True)
    _axis_title(drawing, width, plot_x, plot_x + plot_w, chart.x_label)
    _draw_legend(drawing, legend_lines, names, colours, base_y=axis_h - 24 - 0)
    return drawing


def _legend_layout(names, width) -> list:
    lines, current, used = [], [], 0.0
    for name in names:
        item_w = 14 + text_width(name, SMALL) + 12
        if current and used + item_w > width:
            lines.append(current)
            current, used = [], 0.0
        current.append(name)
        used += item_w
    if current:
        lines.append(current)
    return lines


def _draw_legend(drawing, lines, names, colours, base_y):
    y = base_y
    for line in lines:
        x = 0
        for name in line:
            _rect(drawing, x, y, 8, 8, fill=colours[name], stroke=theme.GRAPHITE, stroke_width=0.3)
            _string(drawing, x + 12, y + 1, name, SMALL, colour=theme.INK)
            x += 14 + text_width(name, SMALL) + 12
        y -= 12


# ── Donut ───────────────────────────────────────────────────────────────────

def _donut(chart, width) -> Drawing:
    rows = [(identity.pdf_text(label), 0 if value is None else float(value)) for label, value in chart.data]
    total = sum(value for _, value in rows)  # a missing figure adds nothing to the whole; the adapters leave it out
    compact = width < 330          # a half width chart: the legend goes under the ring, full width
    diameter = min(110, width * 0.5) if compact else min(124, width * 0.42)
    radius, hole = diameter / 2, diameter / 2 * 0.58
    legend_rows = len(rows)
    height = (diameter + 14 + legend_rows * 14 + 4) if compact else max(diameter + 16, legend_rows * 15 + 16)
    drawing = Drawing(width, height)
    cx = width / 2 if compact else radius + 6
    cy = height - radius - 6 if compact else height / 2
    colours = [(chart.colours[i % len(chart.colours)] if chart.colours else theme.series_colour(i)) for i in range(len(rows))]
    live = [(i, v) for i, (_, v) in enumerate(rows) if v > 0]
    angle = 90.0
    if len(live) == 1:
        i = live[0][0]
        drawing.add(Circle(cx, cy, radius, fillColor=_hex(colours[i]), strokeColor=_hex(theme.GRAPHITE), strokeWidth=0.4))
    else:
        for i, value in live:
            sweep = value / total * 360.0
            drawing.add(Wedge(cx, cy, radius, angle - sweep, angle, radius1=0, fillColor=_hex(colours[i]),
                              strokeColor=_hex(theme.WHITE), strokeWidth=1.2))
            angle -= sweep
    drawing.add(Circle(cx, cy, hole, fillColor=_hex(theme.WHITE), strokeColor=None, strokeWidth=0))
    if chart.centre:
        _string(drawing, cx, cy - 4, fit(chart.centre, 15, hole * 1.7, True), 15, bold=True, colour=theme.GRAPHITE, anchor="middle")
    legend_x = 0 if compact else cx + radius + 22
    step = 14 if compact else 15
    y = (cy - radius - 20) if compact else (height / 2 + legend_rows * step / 2 - 11)
    value_x = width - 4
    for i, (label, value) in enumerate(rows):
        _rect(drawing, legend_x, y, 8, 8, fill=colours[i], stroke=theme.GRAPHITE, stroke_width=0.3)
        share = identity.pct(value, total)
        text = _fmt_value(value) + (f"  ({share}%)" if share is not None else "")
        text_w = text_width(text, LABEL_SIZE, True)
        _string(drawing, legend_x + 13, y + 1, fit(label, LABEL_SIZE, max(value_x - text_w - legend_x - 20, 30)), LABEL_SIZE)
        _string(drawing, value_x, y + 1, text, LABEL_SIZE, bold=True, anchor="end")
        y -= step
    return drawing


# ── Line ────────────────────────────────────────────────────────────────────

def _line_chart(chart, width) -> Drawing:
    points = [(identity.pdf_text(label), 0 if value is None else float(value)) for label, value in chart.data]
    left, right = 38, 12
    plot_w = width - left - right
    plot_h = 104
    top = 16 if chart.y_label else 8
    axis_h = 34
    height = top + plot_h + axis_h
    ticks = nice_ticks(chart.max_value or max([v for _, v in points] + [1]), whole=chart.unit != "%" and _whole(v for _, v in points))
    scale_max = ticks[-1]
    drawing = Drawing(width, height)
    if chart.y_label:
        _string(drawing, 0, height - 9, fit(chart.y_label, SMALL + 0.5, width), SMALL + 0.5, colour=theme.SLATE)
    plot_top = height - top
    plot_bottom = axis_h
    for tick in ticks:
        y = plot_bottom + tick / scale_max * plot_h
        _line(drawing, left, y, left + plot_w, y, theme.SILVER_MIST, 0.6)
        _string(drawing, left - 5, y - 2.5, _fmt_value(tick, chart.unit), SMALL, colour=theme.SLATE, anchor="end")
    _line(drawing, left, plot_bottom, left + plot_w, plot_bottom, theme.SILVER_DEEP, 0.8)
    count = len(points)
    inset = 10          # the first and last point sit clear of the axis labels
    xs = [left + inset + ((plot_w - 2 * inset) * (i / (count - 1) if count > 1 else 0.5)) for i in range(count)]
    ys = [plot_bottom + v / scale_max * plot_h for _, v in points]
    drawing.add(PolyLine([c for pair in zip(xs, ys) for c in pair], strokeColor=_hex(theme.GRAPHITE), strokeWidth=1.6))
    label_every = max(1, math.ceil(count / max(1, int(plot_w // 52))))
    peak = max(range(count), key=lambda i: points[i][1])
    for i, ((label, value), x, y) in enumerate(zip(points, xs, ys)):
        drawing.add(Circle(x, y, 2.6, fillColor=_hex(theme.SILVER), strokeColor=_hex(theme.GRAPHITE), strokeWidth=0.9))
        if i in (0, count - 1, peak) or count <= 8:
            _string(drawing, x, y + 6, _fmt_value(value, chart.unit), SMALL, bold=True, anchor="middle")
        if i % label_every == 0 or i == count - 1:
            _string(drawing, x, plot_bottom - 11, fit(label, SMALL, plot_w / max(count / label_every, 1) + 6), SMALL,
                    colour=theme.SLATE, anchor="middle")
    _axis_title(drawing, width, left, left + plot_w, chart.x_label)
    return drawing


# ── Entry points ────────────────────────────────────────────────────────────

def usable(chart: Chart) -> bool:
    """A chart that has something to say. A line needs two readings to be a trend."""
    if chart.is_empty():
        return False
    return not (chart.kind == "line" and len(chart.data) < 2)


def build_drawing(chart: Chart, width: float) -> Drawing:
    """The chart as a reportlab drawing of the given width in points; an empty state when there is too little data."""
    if not usable(chart):
        message = chart.empty_text
        if chart.kind == "line" and not chart.is_empty():
            message = "A trend needs at least two readings. Run the report again later to see the movement."
        return _empty(Chart(kind=chart.kind, title=chart.title, data=[], empty_text=message), width)
    builder = {"bar": _bar, "stack": _stack, "donut": _donut, "line": _line_chart}.get(chart.kind)
    if builder is None:
        raise ValueError(f"Unknown chart kind: {chart.kind}")
    return builder(chart, width)


def takeaway(chart: Chart) -> str:
    """The one line under a chart: the adapter's own sentence when it wrote one, else a plain statement computed from the
    same data, so that a chart is never shown without its conclusion."""
    if chart.takeaway:
        return identity.clean_text(chart.takeaway, keep_newlines=False)
    if not usable(chart):
        return "There is not enough data to draw a conclusion."
    if chart.kind == "bar" or chart.kind == "donut":
        rows = [(label, float(value or 0)) for label, value in chart.data]
        total = sum(value for _, value in rows)
        label, top = max(rows, key=lambda r: r[1])
        share = identity.pct(top, total)
        return f"{label} is the largest group: {_fmt_value(top, chart.unit)}" + (f", {share}% of the total." if share is not None and chart.unit != "%" else ".")
    if chart.kind == "stack":
        totals = [(label, sum(float(v or 0) for _, v in segments)) for label, segments in chart.data]
        label, top = max(totals, key=lambda r: r[1])
        return f"{label} has the most: {_fmt_value(top)} in total."
    first, last = chart.data[0], chart.data[-1]
    change = float(last[1] or 0) - float(first[1] or 0)
    direction = "up" if change > 0 else "down" if change < 0 else "unchanged"
    return f"From {first[0]} to {last[0]} the value is {direction}" + (f" by {_fmt_value(abs(change), chart.unit)}." if change else ".")


def alt_text(chart: Chart) -> str:
    """The data of a chart as one sentence, for a screen reader or a missing image."""
    if not usable(chart):
        return f"{chart.title}: no chart, {chart.empty_text}"
    if chart.kind == "stack":
        body = "; ".join(f"{label}: " + ", ".join(f"{name} {_fmt_value(value)}" for name, value in segments)
                         for label, segments in chart.data)
    else:
        body = "; ".join(f"{label} {_fmt_value(value, chart.unit)}" for label, value in chart.data)
    return identity.clean_text(f"{chart.title}. {body}.", keep_newlines=False)


# ── The scene as flat primitives, for SVG and PNG ───────────────────────────

def _colour(value):
    """(r, g, b, a) 0..255, or None for no colour."""
    if value is None:
        return None
    alpha = getattr(value, "alpha", 1)
    return int(round(value.red * 255)), int(round(value.green * 255)), int(round(value.blue * 255)), int(round(alpha * 255))


def primitives(drawing) -> list:
    """The shapes of a drawing with absolute coordinates, as plain dicts (y still measured from the bottom)."""
    out = []

    def walk(node, dx=0.0, dy=0.0):
        for shape in node.contents:
            if isinstance(shape, Group):
                t = getattr(shape, "transform", (1, 0, 0, 1, 0, 0))
                walk(shape, dx + t[4], dy + t[5])
            elif isinstance(shape, Rect):
                out.append({"t": "rect", "x": shape.x + dx, "y": shape.y + dy, "w": shape.width, "h": shape.height,
                            "fill": _colour(shape.fillColor), "stroke": _colour(shape.strokeColor), "sw": shape.strokeWidth or 0})
            elif isinstance(shape, Line):
                out.append({"t": "line", "x1": shape.x1 + dx, "y1": shape.y1 + dy, "x2": shape.x2 + dx, "y2": shape.y2 + dy,
                            "stroke": _colour(shape.strokeColor), "sw": shape.strokeWidth or 0.5})
            elif isinstance(shape, String):
                out.append({"t": "text", "x": shape.x + dx, "y": shape.y + dy, "s": shape.text, "size": shape.fontSize,
                            "bold": "Bold" in shape.fontName, "italic": "Oblique" in shape.fontName,
                            "fill": _colour(shape.fillColor), "anchor": shape.textAnchor})
            elif isinstance(shape, Circle):
                out.append({"t": "circle", "cx": shape.cx + dx, "cy": shape.cy + dy, "r": shape.r,
                            "fill": _colour(shape.fillColor), "stroke": _colour(shape.strokeColor), "sw": shape.strokeWidth or 0})
            elif isinstance(shape, Wedge):
                out.append({"t": "wedge", "cx": shape.centerx + dx, "cy": shape.centery + dy, "r": shape.radius,
                            "r1": shape.radius1 or 0, "a0": shape.startangledegrees, "a1": shape.endangledegrees,
                            "fill": _colour(shape.fillColor), "stroke": _colour(shape.strokeColor), "sw": shape.strokeWidth or 0})
            elif isinstance(shape, PolyLine):
                pts = list(shape.points)
                out.append({"t": "poly", "pts": [(pts[i] + dx, pts[i + 1] + dy) for i in range(0, len(pts), 2)],
                            "stroke": _colour(shape.strokeColor), "sw": shape.strokeWidth or 0.5})

    walk(drawing)
    return out


def _wedge_points(p, steps=48) -> list:
    """The outline of a wedge or ring sector as (x, y) points, y measured from the bottom."""
    a0, a1 = math.radians(p["a0"]), math.radians(p["a1"])
    count = max(int(abs(a1 - a0) / (2 * math.pi) * steps), 2)
    outer = [(p["cx"] + p["r"] * math.cos(a0 + (a1 - a0) * k / count), p["cy"] + p["r"] * math.sin(a0 + (a1 - a0) * k / count))
             for k in range(count + 1)]
    if p["r1"]:
        inner = [(p["cx"] + p["r1"] * math.cos(a0 + (a1 - a0) * k / count), p["cy"] + p["r1"] * math.sin(a0 + (a1 - a0) * k / count))
                 for k in range(count, -1, -1)]
        return outer + inner
    return [(p["cx"], p["cy"])] + outer


def _css(colour) -> str:
    if colour is None:
        return "none"
    return f"rgb({colour[0]},{colour[1]},{colour[2]})" if colour[3] == 255 else f"rgba({colour[0]},{colour[1]},{colour[2]},{colour[3] / 255:.2f})"


def drawing_to_svg(drawing, label="") -> str:
    """An inline SVG of the scene. It scales to the width of its box, so the print view and the screen both fit."""
    width, height = drawing.width, drawing.height
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" width="100%" '
             f'preserveAspectRatio="xMinYMin meet" role="img" aria-label="{_xml(label, quote=True)}" '
             f'style="max-width:{width:g}pt;height:auto;display:block">']
    for p in primitives(drawing):
        kind = p["t"]
        if kind == "rect":
            parts.append(f'<rect x="{p["x"]:.2f}" y="{height - p["y"] - p["h"]:.2f}" width="{p["w"]:.2f}" height="{p["h"]:.2f}" '
                         f'fill="{_css(p["fill"])}" stroke="{_css(p["stroke"])}" stroke-width="{p["sw"]:g}"/>')
        elif kind == "line":
            parts.append(f'<line x1="{p["x1"]:.2f}" y1="{height - p["y1"]:.2f}" x2="{p["x2"]:.2f}" y2="{height - p["y2"]:.2f}" '
                         f'stroke="{_css(p["stroke"])}" stroke-width="{p["sw"]:g}"/>')
        elif kind == "text":
            anchor = {"start": "start", "middle": "middle", "end": "end"}.get(p["anchor"], "start")
            weight = ' font-weight="700"' if p["bold"] else ""
            style = ' font-style="italic"' if p["italic"] else ""
            parts.append(f'<text x="{p["x"]:.2f}" y="{height - p["y"]:.2f}" font-size="{p["size"]:g}" text-anchor="{anchor}"'
                         f'{weight}{style} fill="{_css(p["fill"])}" font-family=\'{theme.UI_FONT_STACK}\'>{_xml(p["s"])}</text>')
        elif kind == "circle":
            parts.append(f'<circle cx="{p["cx"]:.2f}" cy="{height - p["cy"]:.2f}" r="{p["r"]:.2f}" fill="{_css(p["fill"])}" '
                         f'stroke="{_css(p["stroke"])}" stroke-width="{p["sw"]:g}"/>')
        elif kind == "wedge":
            pts = " ".join(f"{x:.2f},{height - y:.2f}" for x, y in _wedge_points(p))
            parts.append(f'<polygon points="{pts}" fill="{_css(p["fill"])}" stroke="{_css(p["stroke"])}" stroke-width="{p["sw"]:g}" '
                         f'stroke-linejoin="round"/>')
        elif kind == "poly":
            pts = " ".join(f"{x:.2f},{height - y:.2f}" for x, y in p["pts"])
            parts.append(f'<polyline points="{pts}" fill="none" stroke="{_css(p["stroke"])}" stroke-width="{p["sw"]:g}" '
                         f'stroke-linejoin="round" stroke-linecap="round"/>')
    parts.append("</svg>")
    return "".join(parts)


def _font_files():
    import reportlab
    folder = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
    return {"regular": os.path.join(folder, "Vera.ttf"), "bold": os.path.join(folder, "VeraBd.ttf"),
            "italic": os.path.join(folder, "VeraIt.ttf")}


def drawing_to_png(drawing, scale=3) -> bytes:
    """A PNG of the scene on white, painted with Pillow. Text is fitted to the width Helvetica would take, so the PNG
    lays out the same as the PDF and the SVG."""
    import io

    from PIL import Image, ImageDraw, ImageFont

    files = _font_files()
    width, height = int(math.ceil(drawing.width * scale)), int(math.ceil(drawing.height * scale))
    image = Image.new("RGBA", (width, height), (255, 255, 255, 255))
    pen = ImageDraw.Draw(image, "RGBA")
    cache = {}

    def font_for(size, bold, italic):
        key = (round(size * scale, 2), bold, italic)
        if key not in cache:
            path = files["bold"] if bold else files["italic"] if italic else files["regular"]
            cache[key] = ImageFont.truetype(path, max(int(round(size * scale)), 1))
        return cache[key]

    def Y(y):
        return height - y * scale

    def X(x):
        return x * scale

    for p in primitives(drawing):
        kind = p["t"]
        if kind == "rect":
            box = [X(p["x"]), Y(p["y"] + p["h"]), X(p["x"] + p["w"]), Y(p["y"])]
            pen.rectangle(box, fill=p["fill"], outline=p["stroke"], width=max(int(round(p["sw"] * scale)), 1) if p["stroke"] else 0)
        elif kind == "line":
            pen.line([X(p["x1"]), Y(p["y1"]), X(p["x2"]), Y(p["y2"])], fill=p["stroke"], width=max(int(round(p["sw"] * scale)), 1))
        elif kind == "text":
            bold, italic = p["bold"], p["italic"]
            target = text_width(p["s"], p["size"], bold)
            font = font_for(p["size"], bold, italic)
            natural = font.getlength(p["s"]) / scale
            if natural > target > 0:
                font = ImageFont.truetype(files["bold"] if bold else files["italic"] if italic else files["regular"],
                                          max(int(round(p["size"] * scale * target / natural)), 1))
            anchor = {"start": "ls", "middle": "ms", "end": "rs"}.get(p["anchor"], "ls")
            pen.text((X(p["x"]), Y(p["y"])), p["s"], font=font, fill=p["fill"] or (0, 0, 0, 255), anchor=anchor)
        elif kind == "circle":
            r = p["r"] * scale
            pen.ellipse([X(p["cx"]) - r, Y(p["cy"]) - r, X(p["cx"]) + r, Y(p["cy"]) + r], fill=p["fill"],
                        outline=p["stroke"], width=max(int(round(p["sw"] * scale)), 1) if p["stroke"] else 0)
        elif kind == "wedge":
            pts = [(X(x), Y(y)) for x, y in _wedge_points(p)]
            pen.polygon(pts, fill=p["fill"], outline=p["stroke"])
        elif kind == "poly":
            pts = [(X(x), Y(y)) for x, y in p["pts"]]
            pen.line(pts, fill=p["stroke"], width=max(int(round(p["sw"] * scale)), 1), joint="curve")
    buffer = io.BytesIO()
    image.convert("RGB").save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
