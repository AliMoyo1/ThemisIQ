"""
The banded group score and its leak tests (plan 21, slice 4).

The tests attack the band the way a subsidiary's senior could: know your own score, watch the band over weeks, and
subtract. They check the rules that bound that, and that the answer 'not available' never says why.
"""
import itertools
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from modules.governance import group_band as gb
from modules.governance import group_figures as gf


def _id(db, table, **fields):
    keys = list(fields)
    db.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})",
               [fields[k] for k in keys])
    db.commit()
    return db.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]


def _future(days=90):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(tzinfo=None).isoformat()


ALL = json.dumps({"figure_measures": list(gf.PUBLISHABLE)})


def _org(db, name):
    return _id(db, "organizations", name=name, slug=name.lower().replace(" ", "_") + "_band", status="active")


def _edge(db, parent, child, terms=ALL):
    return _id(db, "org_relationships", parent_org_id=parent, child_org_id=child, status="active", purpose="Group",
               child_ack_by=1, privacy_review_by=2, legal_review_by=3, terms_json=terms, review_due_at=_future())


def _score(db, org, value, *, hours_ago=0, modules=("aria", "grid")):
    """Publish module health figures whose mean is `value`."""
    as_of = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).replace(tzinfo=None).isoformat()
    for m in modules:
        _id(db, "group_figure_snapshots", source_org_id=org, measure_key=f"cc.module_health:{m}", module=m,
            state="measured", value=value, window_text="", detail_json="{}", method_version="t", as_of=as_of,
            publication_version=1 + int(_count(db, org)), content_hash=f"h{org}{m}{as_of}")


def _count(db, org):
    return db.execute("SELECT COUNT(*) FROM group_figure_snapshots WHERE source_org_id=%s", (org,)).fetchone()[0]


def _user(db, org, key, role="grc_officer"):
    uid = _id(db, "users", username=key, email=key + "@example.invalid", full_name=key, password_hash="t",
              org_id=org, is_active=1)
    db.execute("INSERT INTO user_roles (user_id,role_key) VALUES (%s,%s)", (uid, role))
    db.commit()
    return {"id": uid, "org_id": org, "business_unit_id": None, "roles": [role], "is_super_admin": False}


@pytest.fixture
def group(test_db):
    db = test_db
    parent, a, b = _org(db, "Band Parent"), _org(db, "Band A"), _org(db, "Band B")
    _edge(db, parent, a)
    _edge(db, parent, b)
    for org, score in ((parent, 70), (a, 82), (b, 41)):
        _score(db, org, score)
    return db, parent, a, b


def _week(offset):
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(weeks=offset)


# ── the maths ───────────────────────────────────────────────────────────────

def test_a_small_cohort_gets_three_bands_and_a_larger_one_five():
    assert [gb.scale_for(n) for n in (3, 4, 5, 6, 20)] == [3, 3, 3, 5, 5]
    assert [gb.band_of(s, 3) for s in (0, 33.3, 33.4, 66.6, 66.7, 100)] == [1, 1, 2, 2, 3, 3]
    assert [gb.band_of(s, 5) for s in (0, 19.9, 20, 59.9, 60, 99.9, 100)] == [1, 1, 2, 3, 4, 5, 5]


def test_an_organizations_score_is_the_mean_of_its_module_health_only():
    assert gb.entity_score({"cc.module_health:aria": 80, "cc.module_health:grid": 60, "cc.open_breaches": 9}) == 70
    assert gb.entity_score({"cc.open_breaches": 9}) is None


@pytest.mark.parametrize("n", [3, 4, 5])
def test_the_formula_bounds_what_a_viewer_can_infer_about_one_other_organization_by_brute_force(n):
    """Enumerate every score vector on a coarse grid consistent with the viewer's own score and the band, and check the
    formula is never narrower than the real spread of any single other organization."""
    grid = [0, 25, 50, 75, 100]
    scale = gb.scale_for(n)
    for own, band in itertools.product(grid, range(1, scale + 1)):
        lo, hi = gb.edges(band, scale)
        feasible = [others for others in itertools.product(grid, repeat=n - 1)
                    if lo <= (own + sum(others)) / n < hi or (band == scale and (own + sum(others)) / n == 100)]
        if not feasible:
            continue
        spreads = [max(o[i] for o in feasible) - min(o[i] for o in feasible) for i in range(n - 1)]
        assert gb.inference_width(n, own, band, scale) >= max(spreads) - 1e-9, (n, own, band)


@pytest.mark.parametrize("n", [3, 4, 5, 6, 8])
def test_whenever_a_band_is_shown_the_viewer_keeps_the_minimum_doubt_about_every_other_organization(n):
    scale = gb.scale_for(n)
    shown = hidden = 0
    for own in range(0, 101):
        for band in range(1, scale + 1):
            if own + 100 * (n - 1) < n * gb.edges(band, scale)[0] or own >= n * gb.edges(band, scale)[1] and band < scale:
                continue  # this band cannot occur for this viewer
            if gb.viewer_may_see(n, own, band, scale, 3, 40.0):
                shown += 1
                assert gb.inference_width(n, own, band, scale) >= 40.0, (n, own, band)
            else:
                hidden += 1
    assert shown > 0, "the rule must leave the band visible in ordinary cases"
    assert hidden > 0 or n >= 5, "with three or four organizations an extreme band is hidden from some viewers"


def test_a_band_that_would_reveal_the_others_is_hidden_from_that_viewer_only():
    # Viewer score 20 in a group of three: a top band (mean at least 67) forces both others to at least 80, 20 points of doubt.
    assert not gb.viewer_may_see(3, 20, 3, 3, 3, 40.0)
    assert gb.viewer_may_see(3, 20, 2, 3, 3, 40.0)
    assert gb.viewer_may_see(3, 90, 3, 3, 3, 40.0), "someone already high learns little from a high band"
    assert gb.viewer_may_see(3, 40, 3, 3, 3, 40.0), "exactly the minimum doubt is allowed"


def test_two_organizations_are_never_enough_and_the_floors_cannot_be_configured_away():
    assert not gb.viewer_may_see(2, 50, 2, 3, 1, 0.0), "a setting cannot lower the cohort below the floor"
    assert not gb.viewer_may_see(3, 50, 2, 3, 3, 101.0), "a stricter setting is honoured"
    # Viewer 10 in the top band leaves 10 points of doubt: below the floor of 30, whatever the setting says.
    assert not gb.viewer_may_see(3, 10, 3, 3, 3, 0.0)


def test_the_decision_uses_only_the_cohort_the_band_and_the_viewers_own_score():
    """It must not take any other organization's score: otherwise 'withheld' would tell the viewer about them."""
    import inspect
    assert list(inspect.signature(gb.viewer_may_see).parameters) == ["n", "own", "band", "scale", "min_cohort", "min_width"]


# ── computing a band ────────────────────────────────────────────────────────

def test_a_band_is_made_once_per_week_and_the_exact_score_stays_parent_only(group):
    db, parent, a, b = group
    first = gb.compute(parent)
    again = gb.compute(parent)
    assert first["id"] == again["id"] and first["status"] == "published" and (first["band"], first["scale"]) == (2, 3)  # mean 64.3
    public_columns = {r[1] for r in db.execute("PRAGMA table_info(group_band_publications)").fetchall()}
    assert not public_columns & {"mean_score", "cohort_size", "cohort_hash", "score"}, public_columns
    internal = db.execute("SELECT cohort_size, mean_score FROM group_band_internal WHERE parent_org_id=%s", (parent,)).fetchone()
    assert internal["cohort_size"] == 3 and round(internal["mean_score"], 1) == 64.3


def test_fewer_than_three_reporting_organizations_publish_nothing_for_anyone(group):
    db, parent, a, b = group
    db.execute("DELETE FROM group_figure_snapshots WHERE source_org_id=%s", (b,))
    db.commit()
    result = gb.compute(parent)
    assert result["status"] == "withheld" and result["band"] is None
    for org in (a, b):
        assert gb.read(db, _user(db, org, f"v{org}")) == {"state": "not_available"}


def test_a_silent_organization_is_left_out_of_the_cohort_not_counted_as_zero(group):
    db, parent, a, b = group
    db.execute("DELETE FROM group_figure_snapshots WHERE source_org_id=%s", (b,))
    db.commit()
    _score(db, b, 5, hours_ago=gf.STALE_HOURS + 10)
    result = gb.compute(parent)
    assert result["status"] == "withheld"
    internal = db.execute("SELECT cohort_size FROM group_band_internal WHERE parent_org_id=%s", (parent,)).fetchone()
    assert internal["cohort_size"] == 2


def test_a_subsidiary_reads_a_band_and_a_trend_and_nothing_else(group):
    db, parent, a, b = group
    gb.compute(parent)
    seen = gb.read(db, _user(db, a, "band_viewer_a"))
    assert seen["state"] == "shown" and (seen["band"], seen["of"]) == (2, 3) and seen["label"] == "Fair" and seen["trend"] == "new"
    assert set(seen) == {"state", "band", "of", "label", "trend", "period", "as_of"}
    text = json.dumps(seen).lower()
    for forbidden in ("score", "cohort", "mean", "sibling", "band b", "organization"):
        assert forbidden not in text.replace("label", "")


def test_the_band_needs_the_permission_and_an_active_parent(group):
    db, parent, a, b = group
    gb.compute(parent)
    with pytest.raises(HTTPException) as employee:
        gb.read(db, _user(db, a, "band_employee", "employee"))
    assert employee.value.status_code == 404
    outsider = _org(db, "Band Outsider")
    with pytest.raises(HTTPException) as unrelated:
        gb.read(db, _user(db, outsider, "band_outsider"))
    assert unrelated.value.status_code == 404
    with pytest.raises(HTTPException):
        gb.read(db, _user(db, parent, "band_parent_user"))  # a parent is not a subsidiary; it reads exact figures


def test_withheld_looks_the_same_whatever_the_reason(group):
    db, parent, a, b = group
    reasons = []
    gb.compute(parent)
    db.execute("UPDATE group_band_viewers SET visible=0 WHERE child_org_id=%s", (a,))   # doubt too small
    db.commit()
    reasons.append(gb.read(db, _user(db, a, "wh1")))
    db.execute("UPDATE group_band_publications SET status='withheld', band=NULL")        # cohort or membership
    db.commit()
    reasons.append(gb.read(db, _user(db, b, "wh2")))
    db.execute("UPDATE group_band_publications SET status='published', band=3, computed_at=%s",
               ((datetime.now(timezone.utc) - timedelta(days=gb.FRESH_DAYS + 2)).replace(tzinfo=None).isoformat(),))
    db.execute("UPDATE group_band_viewers SET visible=1")
    db.commit()
    reasons.append(gb.read(db, _user(db, b, "wh3")))                                       # too old
    assert reasons == [{"state": "not_available"}] * 3


# ── watching over time ──────────────────────────────────────────────────────

def _everyone(db, parent, a, b, value):
    for org in (parent, a, b):
        db.execute("DELETE FROM group_figure_snapshots WHERE source_org_id=%s", (org,))
    db.commit()
    for org in (parent, a, b):
        _score(db, org, value)


def test_a_small_move_across_an_edge_does_not_change_the_published_band(group):
    db, parent, a, b = group
    first = gb.compute(parent, _week(0))
    assert (first["band"], first["scale"]) == (2, 3)  # mean 64.3, the next edge is 66.7
    _everyone(db, parent, a, b, 68)
    second = gb.compute(parent, _week(1))
    assert (second["status"], second["band"], second["trend"]) == ("published", 2, "flat"), "within three points: held"


def test_a_clear_move_does_change_the_band_and_shows_the_trend(group):
    db, parent, a, b = group
    gb.compute(parent, _week(0))
    _everyone(db, parent, a, b, 90)
    up = gb.compute(parent, _week(1))
    assert (up["band"], up["trend"]) == (3, "up")
    _everyone(db, parent, a, b, 20)
    down = gb.compute(parent, _week(2))
    assert (down["band"], down["trend"]) == (1, "down")


def test_a_change_in_who_is_reporting_withholds_that_week_so_a_member_cannot_be_read_off_the_band(group):
    db, parent, a, b = group
    c = _org(db, "Band C")
    _edge(db, parent, c)
    _score(db, c, 95)
    gb.compute(parent, _week(0))                       # four reporting organizations
    db.execute("DELETE FROM group_figure_snapshots WHERE source_org_id=%s", (c,))
    db.commit()                                        # one of them goes quiet
    second = gb.compute(parent, _week(1))
    assert second["status"] == "withheld"
    assert gb.read(db, _user(db, a, "member_viewer")) == {"state": "not_available"}
    third = gb.compute(parent, _week(2))               # the cohort is stable again: published again
    assert third["status"] == "published"


def test_the_same_week_is_not_recomputed_so_scores_cannot_be_probed_by_timing_a_refresh(group):
    db, parent, a, b = group
    first = gb.compute(parent, _week(0))
    db.execute("DELETE FROM group_figure_snapshots WHERE source_org_id=%s", (b,))
    db.commit()
    _score(db, b, 0)
    assert gb.compute(parent, _week(0))["id"] == first["id"]


# ── who can see which rows ──────────────────────────────────────────────────

def test_only_the_parent_has_exact_figures_and_a_child_cannot_obtain_them_through_the_band_route(group):
    db, parent, a, b = group
    gb.compute(parent)
    user = _user(db, a, "child_probe")
    assert "mean_score" not in json.dumps(gb.read(db, user))
    with pytest.raises(HTTPException):
        gf.view(db, user, "group")  # no figure.view grant, and not the parent
