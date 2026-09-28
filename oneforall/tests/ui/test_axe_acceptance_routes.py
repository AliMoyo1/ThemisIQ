"""
PLAN-36 T07 (step 9): automated axe-core checks across the plan's named
acceptance routes. Fails on any critical/serious violation -- matching
T07's own completion gate ("zero critical/serious automated violations on
acceptance routes"). A route with a known, not-yet-fixed finding is marked
xfail with the specific violation id and why, rather than silently
skipped or left to fail the whole suite -- this file should always show
the true current state, not a stale "all green" from before a regression.

Route list matches task_plan.md's own "Acceptance routes" line for T07,
mapped to the actual URL and the persona that can reach it.
"""
import pytest


ROUTES = [
    ("/", "super_admin"),
    ("/my-dashboard", "super_admin"),
    ("/tasks", "super_admin"),
    ("/reports", "super_admin"),
    ("/calendar", "super_admin"),
    ("/risk-register", "super_admin"),
    ("/people", "super_admin"),
    ("/admin/users", "super_admin"),
    ("/admin/api-keys", "super_admin"),
    ("/admin/webhooks", "super_admin"),
    ("/admin/email", "super_admin"),
    ("/aria/documents", "super_admin"),
    ("/erm/register", "super_admin"),
    ("/erm/library", "super_admin"),
    ("/erm/external", "super_admin"),
    ("/evidence", "super_admin"),
    ("/grid/", "super_admin"),
    ("/bcm/", "super_admin"),
    ("/sentinel/", "super_admin"),
    ("/orm/", "super_admin"),
    ("/governance", "super_admin"),
]

# route -> {violation_id: reason}. Every entry here is a real, found,
# not-yet-fixed finding -- not a blanket allowlist. A route only xfails when
# EVERY violation currently found on it is accounted for here; an
# unexpected new violation type still fails loudly rather than riding along
# on an existing entry. Remove the specific id (or the whole route entry
# once none remain) in the same change that fixes it.
#
# Empty as of 2026-09-25 T07 session 2: every color-contrast finding
# (GRID's .btn-primary/.nav-item.active; ARIA's and Sentinel's .module-name;
# my-dashboard's --good text; ERM library's catColors chips) was precisely
# diagnosed by direct contrast-ratio measurement, then fixed with the
# user's explicit sign-off on the approach (darken only the specific
# failing text/background usages, reusing an existing darker "-mid"/"-dark"
# accent variant per module where the numbers showed one already cleared
# 4.5:1, computing a new minimally-darkened same-hue color only where no
# existing variant did). See progress.md for the exact ratios and colors.
KNOWN_FAILURES = {}


@pytest.mark.parametrize("route,persona", ROUTES)
def test_acceptance_route_has_no_critical_or_serious_violations(
    login_as, live_app, run_axe, route, persona,
):
    page = login_as(persona)
    page.goto(f"{live_app}{route}")
    page.wait_for_load_state("networkidle", timeout=10000)
    violations = run_axe()

    known = KNOWN_FAILURES.get(route, {})
    unexpected = [v for v in violations if v["id"] not in known]
    if violations and not unexpected:
        reasons = "; ".join(f"{v['id']}: {known[v['id']]}" for v in violations)
        pytest.xfail(reasons)

    assert not unexpected, (
        f"{route}: {len(unexpected)} unexpected critical/serious "
        "violation(s) not in KNOWN_FAILURES: "
        + ", ".join(f"{v['id']} ({len(v['nodes'])} node(s))" for v in unexpected)
    )
