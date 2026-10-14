"""
The shared shape of a number a dashboard shows (plans/2026-10-governance-rework/04 section 2).

Written by hand. The point is that a number never stands in for "I could not read it" or "nothing defines it": a measured
zero keeps its zero, a source that failed or was never defined carries no value at all, and a partial or stale value says
what is missing or how old it is.
"""
import pytest

from core import metric_state as ms


def test_a_measured_zero_is_a_number_with_its_window_and_denominator():
    m = ms.measured("open_breaches", "Open breaches", 0, definition="Breaches not yet closed", window="today",
                    denominator={"value": 12, "label": "breaches on record"}, drilldown="/sentinel/?status=open")
    assert (m["state"], m["value"]) == ("measured", 0)
    assert m["denominator"] == {"value": 12, "label": "breaches on record"} and m["window"] == "today"
    assert m["drilldown"] == "/sentinel/?status=open" and m["as_of"], "a measured value says when it was read"


@pytest.mark.parametrize("state", [ms.NOT_MEASURED, ms.UNAVAILABLE])
def test_a_value_is_never_carried_when_nothing_was_measured_or_the_source_failed(state):
    m = ms.metric("k", "Label", state, value=7, note="why")
    assert m["value"] is None and m["state"] == state


def test_an_unknown_state_is_refused():
    with pytest.raises(ValueError):
        ms.metric("k", "Label", "fine", value=1)


def test_a_measured_metric_needs_a_value_but_not_a_non_zero_one():
    with pytest.raises(ValueError):
        ms.metric("k", "Label", ms.MEASURED)
    assert ms.metric("k", "Label", ms.MEASURED, value=0)["value"] == 0
    with pytest.raises(ValueError):
        ms.metric("k", "Label", ms.MEASURED, value="3")
    with pytest.raises(ValueError):
        ms.metric("k", "Label", ms.MEASURED, value=True)


def test_not_measured_says_what_is_missing_and_what_to_do():
    m = ms.not_measured("exercise_coverage", "Exercise coverage", "No exercise frequency is defined.",
                        action={"label": "Define it", "url": "/bcm/settings"})
    assert m["state"] == "not_measured" and m["value"] is None
    assert m["note"] == "No exercise frequency is defined." and m["action"] == {"label": "Define it", "url": "/bcm/settings"}


def test_unavailable_uses_one_standard_sentence_and_can_say_which_source_failed():
    m = ms.unavailable("rights", "Open DSRs", sources=["sentinel"])
    assert m["state"] == "unavailable" and m["value"] is None and m["sources"] == ["sentinel"]
    assert "not a count of zero" in m["note"]


def test_guarded_turns_any_failure_into_unavailable_and_keeps_the_label():
    def broken():
        raise RuntimeError("the table is gone")
    m = ms.guarded("k", "Label", broken, definition="what it counts", drilldown="/x")
    assert (m["state"], m["value"], m["label"]) == ("unavailable", None, "Label")
    assert m["definition"] == "what it counts" and m["drilldown"] == "/x"


def test_guarded_passes_a_good_result_through_and_rejects_anything_else():
    good = ms.measured("k", "Label", 3)
    assert ms.guarded("k", "Label", lambda: good) is good
    assert ms.guarded("k", "Label", lambda: 3)["state"] == "unavailable", "a bare number is not a metric"
    assert ms.guarded("k", "Label", lambda: None)["state"] == "unavailable"


def test_partial_names_the_sources_that_did_not_contribute():
    m = ms.partial("exposure", "Exposure", 14, sources_ok=["erm"], sources_missing=["bcm", "sentinel"])
    assert (m["state"], m["value"]) == ("partial", 14)
    assert m["sources"] == {"available": ["erm"], "missing": ["bcm", "sentinel"]}
    with pytest.raises(ValueError):
        ms.partial("exposure", "Exposure", 14, sources_ok=["erm"], sources_missing=[])


def test_stale_keeps_its_old_value_with_the_date_it_belongs_to():
    m = ms.stale("score", "Control score", 71, as_of="2026-09-01 08:00:00")
    assert (m["state"], m["value"], m["as_of"]) == ("stale", 71, "2026-09-01 08:00:00")
    with pytest.raises(ValueError):
        ms.stale("score", "Control score", 71, as_of=None)


def test_a_metric_always_has_the_same_keys_so_a_page_can_rely_on_them():
    keys = {"key", "label", "state", "value", "definition", "denominator", "window", "as_of", "drilldown", "note", "action",
            "sources", "detail"}
    for m in (ms.measured("a", "A", 1), ms.not_measured("b", "B", "n"), ms.unavailable("c", "C"),
              ms.partial("d", "D", 2, sources_ok=["x"], sources_missing=["y"]), ms.stale("e", "E", 3, as_of="2026-01-01")):
        assert set(m) == keys
