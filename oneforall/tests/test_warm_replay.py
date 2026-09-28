"""
Code-review finding (2026-09-28): scripts/warm_replay.py had two bugs
that combined to make it report success on a real regression:

1. Four queries in _QUERIES referenced columns/tables that don't exist
   (users.role, grid_ncs, grid_evidence, erm_obligations) -- fixed
   directly in _QUERIES, not tested here (no DB fixture is needed to
   see that the fixed table/column names exist; see database.py).
2. A query erroring on one or both sides was classified SKIP, which
   never contributed to fail_count/failures and therefore never
   affected the exit code -- so those four permanently-broken queries
   silently reported SKIP on every run, forever, while the script still
   exited 0. This file tests the fix: _classify() (factored out of
   main() specifically so this is testable without real database
   connections) has no SKIP outcome at all -- any error is FAIL.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.warm_replay import _classify


def test_both_sides_erroring_is_fail_not_skip():
    """Red proof for this test (temporarily restoring the old SKIP
    branches in _classify's would-be equivalent): this asserts FAIL,
    which the old code classified as SKIP with no failure message and no
    contribution to a non-zero exit code."""
    status, sq_display, pg_display, msg = _classify("both:broken", None, None)
    assert status == "FAIL"
    assert msg is not None, "a FAIL must always carry a message main() can surface and exit non-zero for"


def test_sqlite_only_erroring_is_fail_not_skip():
    status, sq_display, pg_display, msg = _classify("sqlite:broken", None, [(3,)])
    assert status == "FAIL"
    assert msg is not None


def test_pg_only_erroring_is_fail():
    """This side was already FAIL before the fix -- confirms the fix
    didn't accidentally change this pre-existing, correct case."""
    status, sq_display, pg_display, msg = _classify("pg:broken", [(3,)], None)
    assert status == "FAIL"
    assert msg is not None


def test_matching_results_pass():
    status, sq_display, pg_display, msg = _classify("match", [(3,)], [(3,)])
    assert status == "PASS"
    assert msg is None


def test_mismatched_results_fail():
    status, sq_display, pg_display, msg = _classify("mismatch", [(3,)], [(4,)])
    assert status == "FAIL"
    assert msg is not None
