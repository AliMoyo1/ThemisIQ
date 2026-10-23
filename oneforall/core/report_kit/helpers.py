"""
Small builders every report adapter needs, so each module's report shapes its figures the same way.

Pure functions over plain values: no request, no database. An adapter turns counts into chart rows with these, and the table
beside the chart is built from the same counts.
"""
from core.report_kit import identity, theme
from core.report_kit.model import Col, Kpi, Table

ROWS_IN_DOCUMENT = 60          # a record level table longer than this is cut in the PDF, DOCX and print view (never in XLSX)

SEVERITY_COLOUR = {"critical": theme.GRAPHITE, "high": theme.SLATE, "medium": theme.SILVER_DEEP, "low": theme.SILVER,
                   "unrated": theme.SILVER_LIGHT}


def label(key) -> str:
    """A stored value as a reader writes it: `under_review` is `Under review`; nothing at all is `No status`."""
    text = "No status" if key in (None, "", "none") else str(key).replace("_", " ")
    return text[:1].upper() + text[1:]


def lines(value) -> list:
    """A stored value as a list of non blank lines: a list as it is, a text split at its line breaks."""
    if isinstance(value, (list, tuple)):
        return [part for item in value for part in str(item).splitlines() if part.strip()]
    return [part.strip() for part in str(value or "").splitlines() if part.strip()]


def facts_table(title, pairs, sheet_name="") -> Table:
    """A two column table of what a record states, one row per pair. A pair with no value reads `Not recorded`, so a gap in the
    record is visible in the document and is never a blank or a guess."""
    rows = [{"k": k, "v": v if v not in (None, "", [], ()) else "Not recorded"} for k, v in pairs]
    return Table(title, [Col("Item", "k", weight=1.3), Col("Recorded", "v", weight=3.2)], rows, sheet_name=sheet_name,
                 empty_text="Nothing is recorded.")


def slices(rows, limit=5, other="Other states"):
    """At most `limit` slices: the first ones as they come, the remainder together, so a donut never repeats a colour."""
    rows = [(name, value) for name, value in rows if value]
    if len(rows) <= limit:
        return rows
    return rows[: limit - 1] + [(other, sum(value for _, value in rows[limit - 1:]))]


def empty(reason) -> str:
    return f"{reason} There is nothing to chart."


def metric_kpi(metric, text=None, note="", tone="neutral"):
    """A headline measure from a `core.metric_state` metric, or None when the viewer may not open it (the dashboard leaves it
    out too). A measured number is shown, as `text` when the caller formats it; a metric that was not measured, or could not
    be read, says so with its own reason and is never drawn as a zero."""
    if metric is None:
        return None
    state, value = metric.get("state"), metric.get("value")
    if state == "not_measured" or (state == "unavailable" and value is None):
        return Kpi(metric["label"], "Not measured" if state == "not_measured" else "Unavailable", metric.get("note") or "")
    if value is None:
        return Kpi(metric["label"], "n/a", metric.get("note") or "")
    if state == "partial":
        note = f"Some sources could not be read. {note}".strip()
    elif state == "stale":
        note = f"As of {identity.format_day(metric.get('as_of'))}. {note}".strip()
    return Kpi(metric["label"], text if text is not None else identity.fmt_int(value), note, tone if value else "neutral")


def tidy_number(value, digits=1) -> str:
    """`11.2`, and `60` rather than `60.0`: a figure with no decimal part is written without one, as the pages write it."""
    text = identity.fmt_number(value, digits)
    return text[:-2] if text.endswith(".0") else text


def leader(rows, total, group, noun, group_plural=None, noun_plural=None) -> str:
    """One sentence under a bar chart: the largest group and its share, or, when several tie for the top, that they do (a tie is
    never reported as one group leading). `rows` is `[(name, count)]`, largest first."""
    if not rows or not total:
        return ""
    count = rows[0][1]
    tied = [name for name, value in rows if value == count]
    if len(tied) > 1:
        return f"{identity.plural(len(tied), group, group_plural)} are tied for the largest share: {identity.plural(count, noun, noun_plural)} each."
    return (f"{rows[0][0]} is the largest {group}: {identity.fmt_int(count)} of {identity.plural(total, noun, noun_plural)} "
            f"({identity.pct(count, total)}%).")


def by_count(counts: dict, none_label="Not recorded", limit=None, other="Other") -> list:
    """`[(label, n)]` from a dict of counts, the largest first (ties by name); a missing key reads `none_label`. With `limit`,
    the tail is folded into one `other` row so a bar chart stays readable."""
    rows = {}
    for key, value in counts.items():
        name = none_label if key in (None, "") else identity.clean_text(key, keep_newlines=False)
        rows[name] = rows.get(name, 0) + value
    ordered = sorted(rows.items(), key=lambda kv: (-kv[1], kv[0].lower()))
    if limit and len(ordered) > limit:
        ordered = ordered[: limit - 1] + [(other, sum(v for _, v in ordered[limit - 1:]))]
    return ordered


def severity_rows(counts: dict, unrated="Not rated"):
    """(rows, colours) for a chart of counts by severity: critical, high, medium, low in that order, then any other value by
    size. Each row's colour follows its severity, so the darkest mark is always the most severe one."""
    folded = {}
    for key, value in counts.items():
        lowered = "" if key is None else str(key).strip().lower()
        folded[lowered] = folded.get(lowered, 0) + value
    rows = [(label(k), folded[k]) for k in theme.SEVERITY_ORDER if folded.get(k)]
    others = {}
    for key, value in folded.items():
        if key not in theme.SEVERITY_ORDER and value:
            name = unrated if key == "" else label(key)
            others[name] = others.get(name, 0) + value
    rows += sorted(others.items(), key=lambda kv: (-kv[1], kv[0]))
    colours = [SEVERITY_COLOUR.get(name.lower(), theme.SILVER_LIGHT) for name, _ in rows]
    return rows, colours
