"""
One shape for a number that a dashboard shows (plans/2026-10-governance-rework/04 section 2).

A number is never shown without saying what it is:

* measured: read from its source. A measured zero is still a number, with its window and denominator.
* not_measured: nothing defines or records it yet. There is no value, and the note says what to set up.
* unavailable: the source could not be read. There is no value; this is not a count of zero.
* partial: some sources contributed and some did not. The value is only what contributed, and the missing sources are named.
* stale: a prior value, shown with the date it belongs to.

A metric the viewer may not see is not a state: the caller leaves it out, so neither a count nor its existence is sent.
"""
import logging

from core.timeutils import utcnow

log = logging.getLogger("oneforall.metrics")

MEASURED, NOT_MEASURED, UNAVAILABLE, PARTIAL, STALE = "measured", "not_measured", "unavailable", "partial", "stale"
STATES = (MEASURED, NOT_MEASURED, UNAVAILABLE, PARTIAL, STALE)
UNAVAILABLE_NOTE = "This could not be read just now. That is not a count of zero."


def _now() -> str:
    return utcnow().strftime("%Y-%m-%d %H:%M:%S")


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def metric(key, label, state, *, value=None, definition="", denominator=None, window=None, as_of=None, drilldown=None,
           note=None, action=None, sources=None, detail=None) -> dict:
    if state not in STATES:
        raise ValueError(f"Unknown metric state: {state!r}")
    if state in (NOT_MEASURED, UNAVAILABLE):
        value = None
    elif not _is_number(value):
        raise ValueError(f"A {state} metric needs a number, not {value!r}")
    if state == STALE and not as_of:
        raise ValueError("A stale metric needs the date its value belongs to")
    if state == MEASURED and as_of is None:
        as_of = _now()
    return {"key": key, "label": label, "state": state, "value": value, "definition": definition,
            "denominator": denominator, "window": window, "as_of": as_of, "drilldown": drilldown, "note": note,
            "action": action, "sources": sources, "detail": detail}


def measured(key, label, value, **kw) -> dict:
    return metric(key, label, MEASURED, value=value, **kw)


def not_measured(key, label, note, **kw) -> dict:
    return metric(key, label, NOT_MEASURED, note=note, **kw)


def unavailable(key, label, **kw) -> dict:
    kw.setdefault("note", UNAVAILABLE_NOTE)
    return metric(key, label, UNAVAILABLE, **kw)


def partial(key, label, value, *, sources_ok, sources_missing, **kw) -> dict:
    if not sources_missing:
        raise ValueError("A partial metric names the sources that did not contribute")
    return metric(key, label, PARTIAL, value=value, sources={"available": list(sources_ok), "missing": list(sources_missing)}, **kw)


def stale(key, label, value, *, as_of, **kw) -> dict:
    return metric(key, label, STALE, value=value, as_of=as_of, **kw)


def guarded(key, label, build, **fallback) -> dict:
    """Run `build()`, which returns a metric. Any failure, or anything that is not a metric, becomes `unavailable`."""
    try:
        got = build()
        if isinstance(got, dict) and got.get("state") in STATES and "key" in got:
            return got
        raise TypeError("a metric builder must return a metric")
    except Exception:
        log.warning("Metric %s could not be read", key, exc_info=True)
        return unavailable(key, label, **{k: v for k, v in fallback.items() if k in ("definition", "drilldown", "window", "sources")})
