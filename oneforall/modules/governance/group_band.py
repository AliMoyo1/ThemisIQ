"""The banded group score that subsidiary senior roles may see (plan 21, slice 4).

A subsidiary is shown one thing about the group: a band from one to five, a trend against the last published period, and
when it was made. It is never shown an exact score, who is in the group, how many there are, or why a band is absent.

Why it is built this way. With three organizations an exact group score minus your own contribution is a sibling's
score. A band is coarse enough to bound that, but only if the rules around it hold, so they are code, not settings:

* a minimum cohort (three reporting organizations), three bands for a small cohort and five for a larger one, and a
  minimum remaining uncertainty for any single other organization: a band is shown to a viewer only if, knowing
  their own score, they still cannot narrow any other organization to less than that many points. Where the band
  would be that revealing for this viewer, they are told it is not available. That decision depends on the band,
  so it reveals at most that the band is extreme for them, which is less than showing it;
* one band per parent per ISO week, held until the score has clearly crossed an edge (hysteresis), so a small
  oscillation near an edge cannot be read as a sibling's movement;
* a week with no band when the set of reporting organizations changed since the last period, so a member joining,
  leaving or going quiet cannot be read off the band change;
* an organization that is not reporting is left out of the cohort, never counted as zero.

The exact score and the cohort stay in a parent-only table.
"""
import hashlib
import json
import logging
from datetime import datetime, timedelta

from fastapi import HTTPException

from config import settings
from core.rbac import has_capability
from core.timeutils import utcnow
from database import get_db_bypass_rls
from modules.governance import group_figures as gf

log = logging.getLogger("oneforall.group_band")

SMALL_COHORT = 6             # below this many reporting organizations the scale has three bands, from here five
LABELS = {3: {1: "Weak", 2: "Fair", 3: "Strong"}, 5: {1: "Critical", 2: "Weak", 3: "Fair", 4: "Good", 5: "Strong"}}
HYSTERESIS = 3.0             # points past a band edge before the published band moves
FLOOR_COHORT = 3             # the settings cannot go below these
FLOOR_WIDTH = 30.0
DEFAULT_COHORT = 3
DEFAULT_WIDTH = 40.0         # any single other organization stays uncertain over at least this many points
FRESH_DAYS = 14              # a band older than this is not shown


def _table(name: str) -> str:
    return f"public.{name}" if settings.is_postgres() else name


def _setting(db, key: str, default, floor, cast):
    try:
        row = db.execute("SELECT value FROM settings WHERE key=%s", (key,)).fetchone()
        return max(floor, cast(row["value"])) if row else default
    except Exception:
        return default


def scale_for(n: int) -> int:
    """How many bands a cohort of n reporting organizations is shown in."""
    return 3 if n < SMALL_COHORT else 5


def band_of(score: float, scale: int) -> int:
    return max(1, min(scale, int(score // (100.0 / scale)) + 1))


def edges(band: int, scale: int) -> "tuple[float, float]":
    width = 100.0 / scale
    return (band - 1) * width, band * width


def entity_score(figures: "dict[str, float]") -> "float | None":
    """An organization's score: the mean share of its records in their good state, over the modules it reports."""
    values = [v for k, v in figures.items() if k.startswith("cc.module_health:") and v is not None]
    return sum(values) / len(values) if values else None


def inference_width(n: int, own: float, band: int, scale: int) -> float:
    """What the group band lets the holder of score `own` conclude about ONE other organization, as the width of the
    range that organization's score can still lie in, when the band says the mean of n organizations is in `band`.
    All scores lie in 0 to 100. The others' scores sum to between n*lo - own and n*hi - own."""
    lo, hi = edges(band, scale)
    others = n - 1
    if others < 1:
        return 0.0
    low_sum, high_sum = n * lo - own, n * hi - own
    return max(0.0, min(100.0, high_sum) - max(0.0, low_sum - 100.0 * (others - 1)))


def viewer_may_see(n: int, own: "float | None", band: int, scale: int, min_cohort: int, min_width: float) -> bool:
    """Show this band to this viewer? Only in a large enough cohort, and only if they cannot narrow any other
    organization below the minimum doubt. A viewer with no score of their own is judged by their worst possible one."""
    if n < max(FLOOR_COHORT, min_cohort):
        return False
    owns = [own] if own is not None else [i * 1.0 for i in range(0, 101, 5)]
    return min(inference_width(n, a, band, scale) for a in owns) >= max(FLOOR_WIDTH, min_width)


def _period(now: datetime) -> str:
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def _cohort(db, parent_org_id: int, now: datetime) -> "list[dict]":
    """Reporting organizations with a score: the parent and its active, reviewed children."""
    stamp = now.isoformat()
    children = db.execute(
        f"SELECT r.child_org_id AS org_id, r.terms_json AS terms_json FROM {_table('org_relationships')} r "
        "WHERE r.parent_org_id=%s AND r.status='active' "
        "AND (r.child_ack_by IS NOT NULL OR r.notice_deemed_at IS NOT NULL) "
        "AND r.privacy_review_by IS NOT NULL AND r.legal_review_by IS NOT NULL AND r.review_due_at>%s",
        (parent_org_id, stamp)).fetchall()
    members = [{"org_id": parent_org_id, "approved": None}] + [
        {"org_id": c["org_id"], "approved": gf._approved(c["terms_json"])} for c in children]
    out = []
    for member in members:
        latest = gf._latest(db, member["org_id"], None)
        reporting, _ = gf._reporting(latest)
        if not reporting:
            continue
        if member["approved"] is not None and "cc.module_health" not in member["approved"]:
            continue
        figures = {k: v["row"]["value"] for k, v in latest.items()
                   if v["row"]["state"] == "measured" and v["row"]["value"] is not None}
        score = entity_score(figures)
        if score is not None:
            out.append({"org_id": member["org_id"], "score": score})
    return out


def compute(parent_org_id: int, now: "datetime | None" = None) -> dict:
    """Make this week's band for one parent, once. Returns the stored publication."""
    now = now or utcnow()
    period = _period(now)
    db = get_db_bypass_rls()
    try:
        existing = db.execute(
            f"SELECT * FROM {_table('group_band_publications')} WHERE parent_org_id=%s AND period_key=%s",
            (parent_org_id, period)).fetchone()
        if existing:
            return dict(existing)
        min_cohort = _setting(db, "group.band.min_cohort", DEFAULT_COHORT, FLOOR_COHORT, int)
        min_width = _setting(db, "group.band.min_width", DEFAULT_WIDTH, FLOOR_WIDTH, float)
        cohort = _cohort(db, parent_org_id, now)
        n = len(cohort)
        cohort_hash = hashlib.sha256(",".join(str(i) for i in sorted(c["org_id"] for c in cohort)).encode()).hexdigest()
        mean = sum(c["score"] for c in cohort) / n if n else None
        last = db.execute(
            f"SELECT p.*, i.cohort_hash AS cohort_hash FROM {_table('group_band_publications')} p "
            f"JOIN {_table('group_band_internal')} i ON i.parent_org_id=p.parent_org_id AND i.period_key=p.period_key "
            "WHERE p.parent_org_id=%s ORDER BY p.id DESC LIMIT 1", (parent_org_id,)).fetchone()
        last_published = db.execute(
            f"SELECT band, scale FROM {_table('group_band_publications')} WHERE parent_org_id=%s AND status='published' "
            "ORDER BY id DESC LIMIT 1", (parent_org_id,)).fetchone()
        scale = scale_for(n)
        status, band, trend = "published", None, "new"
        if n < max(FLOOR_COHORT, min_cohort):
            status = "withheld"
        elif last and last["cohort_hash"] != cohort_hash:
            status = "withheld"  # the set of reporting organizations changed: say nothing this period
        if status == "published":
            band = band_of(mean, scale)
            if last_published and last_published["scale"] == scale:
                held = last_published["band"]
                lo, hi = edges(held, scale)
                if band != held and lo - HYSTERESIS <= mean < hi + HYSTERESIS:
                    band = held  # not clearly across an edge: keep the published band
                trend = "up" if band > held else "down" if band < held else "flat"
        db.execute(
            f"INSERT INTO {_table('group_band_publications')} (parent_org_id,period_key,status,band,scale,trend,computed_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s)", (parent_org_id, period, status, band, scale, trend, now.isoformat()))
        db.execute(
            f"INSERT INTO {_table('group_band_internal')} (parent_org_id,period_key,cohort_hash,cohort_size,mean_score) "
            "VALUES (%s,%s,%s,%s,%s)", (parent_org_id, period, cohort_hash, n, mean))
        scores = {c["org_id"]: c["score"] for c in cohort}
        children = db.execute(
            f"SELECT child_org_id FROM {_table('org_relationships')} WHERE parent_org_id=%s AND status='active'",
            (parent_org_id,)).fetchall()
        for child in children:
            cid = child["child_org_id"]
            visible = (status == "published"
                       and viewer_may_see(n, scores.get(cid), band, scale, min_cohort, min_width))
            db.execute(
                f"INSERT INTO {_table('group_band_viewers')} (parent_org_id,period_key,child_org_id,visible) "
                "VALUES (%s,%s,%s,%s)", (parent_org_id, period, cid, 1 if visible else 0))
        db.commit()
        return dict(db.execute(
            f"SELECT * FROM {_table('group_band_publications')} WHERE parent_org_id=%s AND period_key=%s",
            (parent_org_id, period)).fetchone())
    finally:
        db.close()


def compute_all() -> int:
    db = get_db_bypass_rls()
    try:
        parents = [r["parent_org_id"] for r in db.execute(
            f"SELECT DISTINCT parent_org_id FROM {_table('org_relationships')} WHERE status='active'").fetchall()]
    finally:
        db.close()
    done = 0
    for parent in parents:
        try:
            compute(parent)
            done += 1
        except Exception:
            log.warning("Group band: computing failed for organization %s", parent, exc_info=True)
    return done


def read(db, actor: dict) -> dict:
    """The band a subsidiary's senior role may see, or the single answer 'not available'. The answer never says why."""
    if not actor.get("org_id") or not has_capability(actor, "group.figure.view_band"):
        raise HTTPException(404, "Not found")
    now = utcnow()
    edge = db.execute(
        f"SELECT r.parent_org_id AS parent_org_id FROM {_table('org_relationships')} r "
        "WHERE r.child_org_id=%s AND r.status='active' "
        "AND (r.child_ack_by IS NOT NULL OR r.notice_deemed_at IS NOT NULL) "
        "AND r.privacy_review_by IS NOT NULL AND r.legal_review_by IS NOT NULL AND r.review_due_at>%s",
        (actor["org_id"], now.isoformat())).fetchone()
    if not edge:
        raise HTTPException(404, "Not found")
    unavailable = {"state": "not_available"}
    row = db.execute(
        f"SELECT p.period_key, p.status, p.band, p.scale, p.trend, p.computed_at, v.visible "
        f"FROM {_table('group_band_publications')} p "
        f"JOIN {_table('group_band_viewers')} v ON v.parent_org_id=p.parent_org_id AND v.period_key=p.period_key "
        "AND v.child_org_id=%s WHERE p.parent_org_id=%s ORDER BY p.id DESC LIMIT 1",
        (actor["org_id"], edge["parent_org_id"])).fetchone()
    if not row or row["status"] != "published" or not row["visible"] or row["band"] is None:
        return unavailable
    try:
        if datetime.fromisoformat(row["computed_at"]) < now - timedelta(days=FRESH_DAYS):
            return unavailable
    except ValueError:
        return unavailable
    return {"state": "shown", "band": row["band"], "of": row["scale"], "label": LABELS[row["scale"]][row["band"]],
            "trend": row["trend"], "period": row["period_key"], "as_of": row["computed_at"]}
