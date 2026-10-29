"""
Group figures (plan 21): what a tenant may publish, who may read it, and the three views.

Service level on SQLite. The row level security of the shared table is tested against real PostgreSQL in
tests/test_postgres_init.py.
"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import HTTPException

from modules.governance import group_figures as gf


def _id(db, table, **fields):
    keys = list(fields)
    db.execute(f"INSERT INTO {table} ({', '.join(keys)}) VALUES ({', '.join(['%s'] * len(keys))})",
               [fields[k] for k in keys])
    db.commit()
    return db.execute(f"SELECT MAX(id) FROM {table}").fetchone()[0]


def _actor(db, org, key, role):
    uid = _id(db, "users", username=key, email=key + "@example.invalid", full_name=key,
              password_hash="test", org_id=org, is_active=1)
    db.execute("INSERT INTO user_roles (user_id,role_key) VALUES (%s,%s)", (uid, role))
    db.commit()
    return {"id": uid, "org_id": org, "business_unit_id": None, "roles": [role], "is_super_admin": False}


def _future(days=30):
    return (datetime.now(timezone.utc) + timedelta(days=days)).replace(tzinfo=None).isoformat()


ALL_MEASURES = json.dumps({"figure_measures": list(gf.PUBLISHABLE)})


@pytest.fixture
def world(test_db):
    db = test_db
    parent = _id(db, "organizations", name="Parent Co", slug="fig_parent", status="active")
    child = _id(db, "organizations", name="Child Co", slug="fig_child", status="active")
    other = _id(db, "organizations", name="Other Co", slug="fig_other", status="active")
    sibling = _id(db, "organizations", name="Sibling Co", slug="fig_sibling", status="active")
    relation = _id(db, "org_relationships", parent_org_id=parent, child_org_id=child, status="active",
                   purpose="Group", child_ack_by=1, privacy_review_by=2, legal_review_by=3,
                   terms_json=ALL_MEASURES, review_due_at=_future(90))
    relation_other = _id(db, "org_relationships", parent_org_id=parent, child_org_id=other, status="active",
                         purpose="Group", child_ack_by=1, privacy_review_by=2, legal_review_by=3,
                         terms_json=ALL_MEASURES, review_due_at=_future(90))
    users = {
        "grc": _actor(db, parent, "fig_grc", "grc_officer"),
        "dpo": _actor(db, parent, "fig_dpo", "dpo"),
        "audit": _actor(db, parent, "fig_audit", "audit_lead"),
        "employee": _actor(db, parent, "fig_employee", "employee"),
        "child_grc": _actor(db, child, "fig_child_grc", "grc_officer"),
        "sibling_grc": _actor(db, sibling, "fig_sibling_grc", "grc_officer"),
    }
    return db, parent, child, other, sibling, relation, relation_other, users


def _grant(db, relation, parent, child, user, *, days=30, review=7, revoked=False):
    return _id(db, "group_view_grants", relationship_id=relation, source_org_id=child, viewer_org_id=parent,
               user_id=user["id"], capability="figure.view", expires_at=_future(days), review_due_at=_future(review),
               revoked_at=_future(0) if revoked else None, granted_by=999)


def _snapshot(db, org, key, value, *, module="", state="measured", as_of=None, detail=None, version=1):
    return _id(db, "group_figure_snapshots", source_org_id=org, measure_key=key, module=module, state=state,
               value=value, window_text="", detail_json=json.dumps(detail or {}), method_version="t",
               as_of=as_of or datetime.now(timezone.utc).replace(tzinfo=None).isoformat(),
               publication_version=version, content_hash="h" + str(version) + key + str(org))


# ── what may leave a tenant ─────────────────────────────────────────────────

def test_only_registered_numeric_figures_with_numeric_detail_are_published():
    good = {"key": "cc.open_breaches", "state": "measured", "value": 3,
            "detail": {"critical": 1, "note": "Jane Moyo leaked it", "module": "sentinel", "x y": 2, "bad/key": 5}}
    row = gf.sanitize(good)
    assert row["measure_key"] == "cc.open_breaches" and row["value"] == 3.0
    assert row["module"] == "sentinel"
    assert row["detail"] == {"critical": 1, "module": "sentinel", "x y": 2}, "free text and odd keys never leave"
    assert gf.sanitize({**good, "key": "cc.not_a_metric"}) is None
    assert gf.sanitize({**good, "state": "excellent"}) is None
    assert gf.sanitize({**good, "value": True}) is None
    assert gf.sanitize({**good, "value": "7"}) is None
    assert gf.sanitize({**good, "key": None}) is None
    health = gf.sanitize({"key": "cc.module_health:aria", "state": "measured", "value": 80.0, "detail": {"of": 10}})
    assert health["module"] == "aria"


def test_publishing_freezes_figures_append_only_with_versions_and_a_hash(world):
    db, parent, child, *_ = world
    first = gf.publish_tenant(child, "fig_child")
    second = gf.publish_tenant(child, "fig_child")
    assert first > 5 and second == first
    rows = db.execute("SELECT measure_key, publication_version, content_hash FROM group_figure_snapshots "
                      "WHERE source_org_id=%s ORDER BY id", (child,)).fetchall()
    assert len(rows) == first * 2
    by_key = {}
    for r in rows:
        by_key.setdefault(r["measure_key"], []).append((r["publication_version"], r["content_hash"]))
    assert all([v for v, _ in versions] == [1, 2] and versions[0][1] != versions[1][1] and len(versions[0][1]) == 64
               for versions in by_key.values())
    # Nothing outside the registered metrics, and no text from a record, is stored.
    stored = db.execute("SELECT detail_json FROM group_figure_snapshots WHERE source_org_id=%s", (child,)).fetchall()
    assert all(isinstance(json.loads(r["detail_json"]), dict) for r in stored)


def test_a_module_the_organization_is_not_licensed_for_publishes_nothing(world):
    db, parent, child, *_ = world
    db.execute("INSERT INTO licenses (org_id, module_keys, seats) VALUES (%s,'aria',10)", (child,))
    db.commit()
    gf.publish_tenant(child, "fig_child")
    modules = {r["module"] for r in db.execute(
        "SELECT DISTINCT module FROM group_figure_snapshots WHERE source_org_id=%s", (child,)).fetchall()}
    assert modules <= {"", "aria"}, modules


# ── who may read ────────────────────────────────────────────────────────────

def test_a_role_without_the_capability_cannot_open_the_views(world):
    db, *_, users = world
    with pytest.raises(HTTPException) as denied:
        gf.views(db, users["employee"])
    assert denied.value.status_code == 403
    with pytest.raises(HTTPException):
        gf.view(db, users["employee"], "own")


def test_without_a_named_grant_no_subsidiary_is_listed_or_readable(world):
    db, parent, child, other, sibling, relation, _, users = world
    gf.publish_tenant(child, "fig_child")
    listed = gf.views(db, users["grc"])
    assert listed["subsidiaries"] == [] and listed["group"] is False
    for which, org in (("subsidiary", child), ("group", None)):
        with pytest.raises(HTTPException) as masked:
            gf.view(db, users["grc"], which, org)
        assert masked.value.status_code == 404
    _grant(db, relation, parent, child, users["grc"])
    assert [s["org_id"] for s in gf.views(db, users["grc"])["subsidiaries"]] == [child]
    assert gf.view(db, users["grc"], "subsidiary", child)["entities"][0]["name"] == "Child Co"


def test_an_expired_or_revoked_grant_or_a_grant_to_someone_else_shows_nothing(world):
    db, parent, child, other, sibling, relation, _, users = world
    gf.publish_tenant(child, "fig_child")
    _grant(db, relation, parent, child, users["grc"], revoked=True)
    _grant(db, relation, parent, child, users["grc"], days=-2, review=-5)
    _grant(db, relation, parent, child, users["dpo"])
    assert gf.views(db, users["grc"])["subsidiaries"] == []
    assert [s["org_id"] for s in gf.views(db, users["dpo"])["subsidiaries"]] == [child]
    with pytest.raises(HTTPException):
        gf.view(db, users["grc"], "subsidiary", child)


def test_a_grant_covers_one_subsidiary_and_the_others_are_masked(world):
    db, parent, child, other, sibling, relation, relation_other, users = world
    gf.publish_tenant(child, "fig_child")
    gf.publish_tenant(other, "fig_other")
    _grant(db, relation, parent, child, users["grc"])
    assert [s["name"] for s in gf.views(db, users["grc"])["subsidiaries"]] == ["Child Co"]
    with pytest.raises(HTTPException) as masked:
        gf.view(db, users["grc"], "subsidiary", other)
    assert masked.value.status_code == 404
    names = [e["name"] for e in gf.view(db, users["grc"], "group")["entities"]]
    assert names == ["Parent Co", "Child Co"], "the group view holds only what this person may read"


def test_a_child_or_an_unrelated_organization_reads_nothing_about_others(world):
    db, parent, child, other, sibling, relation, _, users = world
    gf.publish_tenant(parent, "fig_parent")
    gf.publish_tenant(child, "fig_child")
    for who in ("child_grc", "sibling_grc"):
        assert gf.views(db, users[who])["subsidiaries"] == []
        for which in ("group", "subsidiary"):
            with pytest.raises(HTTPException) as masked:
                gf.view(db, users[who], which, parent)
            assert masked.value.status_code == 404
        own = gf.view(db, users[who], "own")["entities"][0]
        assert own["org_id"] == users[who]["org_id"], "a tenant reads only itself"


# ── role filter ─────────────────────────────────────────────────────────────

def test_each_role_sees_only_its_families_and_the_rest_is_omitted(world):
    db, parent, child, other, sibling, relation, _, users = world
    for key, module, value in (("cc.open_breaches", "sentinel", 2), ("cc.grid_open_audit_controls", "grid", 4),
                               ("cc.critical_high_risks", "erm", 1), ("cc.overdue_actions", "", 3)):
        _snapshot(db, child, key, value, module=module)
    for who in ("grc", "dpo", "audit"):
        _grant(db, relation, parent, child, users[who])

    def keys(who):
        return {f["key"] for f in gf.view(db, users[who], "subsidiary", child)["entities"][0]["figures"]}
    assert keys("grc") == {"cc.open_breaches", "cc.grid_open_audit_controls", "cc.critical_high_risks", "cc.overdue_actions"}
    assert keys("dpo") == {"cc.open_breaches"}
    assert keys("audit") == {"cc.grid_open_audit_controls", "cc.overdue_actions"}


# ── not reporting, and totals ───────────────────────────────────────────────

def test_a_subsidiary_that_has_not_reported_is_not_reporting_and_never_zero(world):
    db, parent, child, other, sibling, relation, relation_other, users = world
    _grant(db, relation, parent, child, users["grc"])
    _grant(db, relation_other, parent, other, users["grc"])
    _snapshot(db, parent, "cc.open_breaches", 2, module="sentinel")
    _snapshot(db, child, "cc.open_breaches", 5, module="sentinel")
    old = (datetime.now(timezone.utc) - timedelta(hours=gf.STALE_HOURS + 5)).replace(tzinfo=None).isoformat()
    _snapshot(db, other, "cc.open_breaches", 100, module="sentinel", as_of=old)
    data = gf.view(db, users["grc"], "group")
    state = {e["name"]: e for e in data["entities"]}
    assert state["Child Co"]["state"] == "reporting"
    assert state["Other Co"]["state"] == "not_reporting" and state["Other Co"]["figures"] == []
    assert state["Other Co"]["last_reported"] == old
    total = next(t for t in data["totals"] if t["key"] == "cc.open_breaches")
    assert total["value"] == 7.0, "the stale figure is not added, and nothing stands in for it as zero"
    assert (total["entities_counted"], total["entities_total"]) == (2, 3)


def test_a_tenant_with_no_figures_at_all_is_not_reporting(world):
    db, parent, child, other, sibling, relation, _, users = world
    _grant(db, relation, parent, child, users["grc"])
    entity = gf.view(db, users["grc"], "subsidiary", child)["entities"][0]
    assert entity["state"] == "not_reporting" and entity["last_reported"] is None


def test_only_counts_are_added_and_shares_and_partial_figures_are_not(world):
    db, parent, child, other, sibling, relation, _, users = world
    _grant(db, relation, parent, child, users["grc"])
    for org in (parent, child):
        _snapshot(db, org, "cc.open_breaches", 2, module="sentinel")
        _snapshot(db, org, "cc.module_health:aria", 80, module="aria", detail={"of": 10})
    _snapshot(db, child, "cc.overdue_actions", 9, state="partial")
    _snapshot(db, parent, "cc.overdue_actions", 1)
    data = gf.view(db, users["grc"], "group")
    keys = {t["key"]: t for t in data["totals"]}
    assert keys["cc.open_breaches"]["value"] == 4.0
    assert "cc.module_health:aria" not in keys, "a share cannot be added"
    # a partial figure is shown per organization but does not enter the total
    assert keys["cc.overdue_actions"]["value"] == 1.0 and keys["cc.overdue_actions"]["entities_counted"] == 1


def test_the_latest_figure_wins_and_the_previous_one_is_the_trend(world):
    db, parent, child, other, sibling, relation, _, users = world
    _grant(db, relation, parent, child, users["grc"])
    _snapshot(db, child, "cc.open_breaches", 2, module="sentinel", version=1)
    _snapshot(db, child, "cc.open_breaches", 5, module="sentinel", version=2)
    figure = gf.view(db, users["grc"], "subsidiary", child)["entities"][0]["figures"][0]
    assert (figure["value"], figure["previous"]) == (5.0, 2.0)


# ── audit ───────────────────────────────────────────────────────────────────

def test_reading_a_subsidiary_is_recorded_in_the_shared_log(world):
    db, parent, child, other, sibling, relation, _, users = world
    gf.publish_tenant(child, "fig_child")
    _grant(db, relation, parent, child, users["grc"])
    gf.view(db, users["grc"], "subsidiary", child)
    gf.view(db, users["grc"], "group")
    db.commit()
    events = db.execute("SELECT action, source_org_id, viewer_org_id, actor_id FROM group_access_events "
                        "WHERE action='figures_view' ORDER BY id").fetchall()
    assert [(e["source_org_id"], e["viewer_org_id"], e["actor_id"]) for e in events] == [
        (child, parent, users["grc"]["id"])] * 2
    # reading one's own figures is not a cross-organization read and is not logged
    gf.view(db, users["grc"], "own")
    assert db.execute("SELECT COUNT(*) FROM group_access_events WHERE action='figures_view'").fetchone()[0] == 2


def test_an_unknown_view_is_refused(world):
    db, *_, users = world
    with pytest.raises(HTTPException) as bad:
        gf.view(db, users["grc"], "everything")
    assert bad.value.status_code == 422


# ── the approved measure list and the cadence ───────────────────────────────

def test_a_child_publishes_only_the_measures_its_terms_approve(world):
    db, parent, child, other, sibling, relation, relation_other, users = world
    db.execute("UPDATE org_relationships SET terms_json=%s WHERE id=%s",
               (json.dumps({"figure_measures": ["cc.open_breaches", "cc.module_health"]}), relation))
    db.commit()
    gf.publish_tenant(child, "fig_child")
    keys = {r["measure_key"] for r in db.execute(
        "SELECT DISTINCT measure_key FROM group_figure_snapshots WHERE source_org_id=%s", (child,)).fetchall()}
    assert keys and all(k.split(":")[0] in ("cc.open_breaches", "cc.module_health") for k in keys), keys


def test_a_child_with_no_approved_measures_publishes_nothing_and_a_parent_is_unrestricted(world):
    db, parent, child, other, sibling, relation, relation_other, users = world
    db.execute("UPDATE org_relationships SET terms_json='{}' WHERE id=%s", (relation,))
    db.commit()
    assert gf.publish_tenant(child, "fig_child") == 0
    assert gf.publish_tenant(parent, "fig_parent") > 5, "an organization that is nobody's child publishes its own figures"


def test_a_narrowed_term_hides_figures_published_earlier(world):
    db, parent, child, other, sibling, relation, relation_other, users = world
    _grant(db, relation, parent, child, users["grc"])
    _snapshot(db, child, "cc.open_breaches", 5, module="sentinel")
    _snapshot(db, child, "cc.overdue_actions", 9)
    db.execute("UPDATE org_relationships SET terms_json=%s WHERE id=%s",
               (json.dumps({"figure_measures": ["cc.open_breaches"]}), relation))
    db.commit()
    figures = gf.view(db, users["grc"], "subsidiary", child)["entities"][0]["figures"]
    assert [f["key"] for f in figures] == ["cc.open_breaches"]


def test_the_terms_accept_only_known_measures():
    assert gf.validate_measures(None) == []
    assert gf.validate_measures(["cc.open_breaches", "cc.overdue_actions"]) == ["cc.open_breaches", "cc.overdue_actions"]
    for bad in ("cc.open_breaches", ["cc.not_real"], ["cc.open_breaches", "cc.open_breaches"], [3], {"a": 1}):
        with pytest.raises(HTTPException):
            gf.validate_measures(bad)


def test_the_cadence_setting_decides_which_tenants_are_due(world):
    db, parent, child, other, sibling, relation, relation_other, users = world
    assert gf.interval_hours() == 24
    db.execute("INSERT INTO settings (key, value) VALUES ('group.figures.interval_hours', '6')")
    db.commit()
    assert gf.interval_hours() == 6
    db.execute("UPDATE settings SET value='9999' WHERE key='group.figures.interval_hours'")
    db.commit()
    assert gf.interval_hours() == 168, "clamped"
    db.execute("UPDATE settings SET value='soon' WHERE key='group.figures.interval_hours'")
    db.commit()
    assert gf.interval_hours() == 24
    fresh = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(tzinfo=None).isoformat()
    _snapshot(db, child, "cc.open_breaches", 1, module="sentinel", as_of=fresh)
    assert gf._due(db, child, 24) is False and gf._due(db, child, 1) is True and gf._due(db, other, 24) is True


# ── reconciliation and lineage ──────────────────────────────────────────────

def test_a_figure_that_changes_between_two_reads_is_published_as_unavailable_never_as_a_number(world, monkeypatch):
    db, parent, child, other, sibling, relation, relation_other, users = world
    real = gf._build
    calls = {"n": 0}

    def flaky(org_id, slug):
        calls["n"] += 1
        rows = real(org_id, slug)
        if calls["n"] == 2 and "cc.open_breaches" in rows:  # the second read disagrees
            rows["cc.open_breaches"] = {**rows["cc.open_breaches"], "value": 99.0}
        return rows
    monkeypatch.setattr(gf, "_build", flaky)
    gf.publish_tenant(child, "fig_child")
    row = db.execute("SELECT state, value FROM group_figure_snapshots WHERE source_org_id=%s AND measure_key='cc.open_breaches'",
                     (child,)).fetchone()
    assert (row["state"], row["value"]) == ("unavailable", None)
    lineage = db.execute("SELECT reconciliation, reason FROM group_figure_lineage WHERE source_org_id=%s "
                         "AND measure_key='cc.open_breaches'", (child,)).fetchone()
    assert lineage["reconciliation"] == "failed" and "changed" in lineage["reason"]
    others = db.execute("SELECT DISTINCT reconciliation FROM group_figure_lineage WHERE source_org_id=%s "
                        "AND measure_key<>'cc.open_breaches'", (child,)).fetchall()
    assert [r["reconciliation"] for r in others] == ["ok"]


def test_impossible_figures_do_not_reconcile():
    base = {"measure_key": "cc.open_breaches", "state": "measured", "value": 3.0}
    assert gf.reconcile(base, dict(base)) == ""
    assert gf.reconcile({**base, "value": -1.0}, {**base, "value": -1.0})
    assert gf.reconcile({**base, "value": float("nan")}, {**base, "value": float("nan")})
    assert gf.reconcile({**base, "measure_key": "cc.module_health:aria", "value": 140.0},
                        {**base, "measure_key": "cc.module_health:aria", "value": 140.0})
    assert gf.reconcile(base, None)
    assert gf.reconcile({**base, "state": "measured", "value": None}, {**base, "value": None})


def test_every_published_figure_has_lineage_that_only_its_own_organization_holds(world):
    db, parent, child, other, sibling, relation, relation_other, users = world
    written = gf.publish_tenant(child, "fig_child")
    lineage = db.execute("SELECT run_id, definition_text, reconciliation, snapshot_id FROM group_figure_lineage "
                         "WHERE source_org_id=%s", (child,)).fetchall()
    assert len(lineage) == written and len({r["run_id"] for r in lineage}) == 1
    assert all(r["definition_text"] and r["reconciliation"] == "ok" and r["snapshot_id"] for r in lineage)
    # the view never returns lineage, only the figure
    _grant(db, relation, parent, child, users["grc"])
    figure = gf.view(db, users["grc"], "subsidiary", child)["entities"][0]["figures"][0]
    assert "definition_text" not in json.dumps(figure) and "run_id" not in figure


# ── restatement ─────────────────────────────────────────────────────────────

def _restate_world(world):
    db, parent, child, other, sibling, relation, relation_other, users = world
    proposer = _actor(db, child, "fig_child_proposer", "grc_officer")
    reviewer = _actor(db, child, "fig_child_reviewer", "compliance_manager")
    _grant(db, relation, parent, child, users["grc"])
    original = _snapshot(db, child, "cc.open_breaches", 5, module="sentinel")
    return db, parent, child, relation, users, proposer, reviewer, original


def test_a_correction_needs_a_second_person_and_publishes_a_new_snapshot_that_points_at_the_original(world):
    db, parent, child, relation, users, proposer, reviewer, original = _restate_world(world)
    rid = gf.propose_restatement(db, proposer, "cc.open_breaches", 3, "Two duplicate breach records were merged", "2026-10")
    db.commit()
    with pytest.raises(HTTPException) as same:
        gf.review_restatement(db, proposer, rid, "approved", "I agree with myself entirely")
    assert same.value.status_code == 403 or same.value.status_code == 409
    with pytest.raises(HTTPException) as same_person:
        gf.review_restatement(db, {**proposer, "roles": ["compliance_manager"]}, rid, "approved", "I agree with myself entirely")
    assert same_person.value.status_code == 409
    done = gf.review_restatement(db, reviewer, rid, "approved", "Checked against the breach register")
    db.commit()
    assert done["status"] == "approved" and done["replacement_snapshot_id"] > original
    old = db.execute("SELECT value FROM group_figure_snapshots WHERE id=%s", (original,)).fetchone()
    assert old["value"] == 5.0, "the original is never edited"
    figure = gf.view(db, users["grc"], "subsidiary", child)["entities"][0]["figures"][0]
    assert (figure["value"], figure["restated"], figure["previous"]) == (3.0, True, 5.0)
    assert figure["restatement_reason"] == "Two duplicate breach records were merged"
    row = db.execute("SELECT restates_snapshot_id, publication_version FROM group_figure_snapshots WHERE id=%s",
                     (done["replacement_snapshot_id"],)).fetchone()
    assert row["restates_snapshot_id"] == original and row["publication_version"] == 2


def test_a_rejected_correction_changes_nothing_and_a_pending_one_blocks_another(world):
    db, parent, child, relation, users, proposer, reviewer, original = _restate_world(world)
    rid = gf.propose_restatement(db, proposer, "cc.open_breaches", 1, "Believed to be too high at the time", "")
    db.commit()
    with pytest.raises(HTTPException) as pending:
        gf.propose_restatement(db, proposer, "cc.open_breaches", 2, "Another reason entirely, recorded", "")
    assert pending.value.status_code == 409
    assert gf.review_restatement(db, reviewer, rid, "rejected", "The register does not support it")["status"] == "rejected"
    db.commit()
    figure = gf.view(db, users["grc"], "subsidiary", child)["entities"][0]["figures"][0]
    assert (figure["value"], figure["restated"]) == (5.0, False)
    with pytest.raises(HTTPException) as again:
        gf.review_restatement(db, reviewer, rid, "approved", "Deciding twice should not work")
    assert again.value.status_code == 404


def test_corrections_must_be_possible_and_belong_to_the_proposers_own_figures(world):
    db, parent, child, relation, users, proposer, reviewer, original = _restate_world(world)
    for bad in (-1, float("nan"), "3", True, None):
        with pytest.raises(HTTPException) as impossible:
            gf.propose_restatement(db, proposer, "cc.open_breaches", bad, "A sufficiently long reason", "")
        assert impossible.value.status_code == 422
    with pytest.raises(HTTPException):
        gf.propose_restatement(db, proposer, "cc.module_health:aria", 150, "A sufficiently long reason", "")
    with pytest.raises(HTTPException):
        gf.propose_restatement(db, proposer, "cc.open_breaches", 2, "short", "")
    with pytest.raises(HTTPException):
        gf.propose_restatement(db, proposer, "cc.not_a_figure", 2, "A sufficiently long reason", "")
    parent_proposer = _actor(db, parent, "fig_parent_proposer", "grc_officer")
    with pytest.raises(HTTPException) as none:
        gf.propose_restatement(db, parent_proposer, "cc.open_breaches", 2, "A sufficiently long reason", "")
    assert none.value.status_code == 404, "the parent has published nothing to correct and cannot correct the child's figure"


def test_only_the_source_sees_or_reviews_its_corrections_and_roles_are_limited(world):
    db, parent, child, relation, users, proposer, reviewer, original = _restate_world(world)
    rid = gf.propose_restatement(db, proposer, "cc.open_breaches", 4, "Reclassified after the review", "")
    db.commit()
    assert [r["id"] for r in gf.list_restatements(db, reviewer)] == [rid]
    assert gf.list_restatements(db, reviewer)[0]["can_review"] is True
    assert gf.list_restatements(db, proposer)[0]["can_review"] is False
    assert gf.list_restatements(db, users["sibling_grc"]) == []
    assert gf.list_restatements(db, users["grc"]) == [], "the parent never lists a child's corrections"
    with pytest.raises(HTTPException) as outsider:
        gf.review_restatement(db, {**users["grc"], "roles": ["compliance_manager"]}, rid, "approved", "Not my figure at all")
    assert outsider.value.status_code == 404
    for who in ("employee",):
        with pytest.raises(HTTPException) as denied:
            gf.propose_restatement(db, users[who], "cc.open_breaches", 4, "A sufficiently long reason", "")
        assert denied.value.status_code == 403
