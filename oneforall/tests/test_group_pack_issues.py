"""Group packs (plan 22, C8): issue register counts are frozen and checked, their runs survive pruning, and a pack's
retention and legal hold are recorded without anything being deleted."""
import hashlib
import json

import pytest
from fastapi import HTTPException

from modules.governance import group_issues as gi
from modules.governance import group_packs as gp
from modules.governance import group_figures as gf
from tests.test_group_packs import _future, _id, _make, _now, _user, world  # noqa: F401 (fixture)


def _run(db, org, issue_type, rows):
    payload = json.dumps(rows, sort_keys=True, separators=(",", ":"))
    run = _id(db, "group_issue_runs", source_org_id=org, issue_type=issue_type, published_at=_now(), row_count=len(rows),
              truncated=0, content_hash=hashlib.sha256(f"{org}:{issue_type}:{payload}".encode()).hexdigest())
    for row in rows:
        _id(db, "group_issue_rows", run_id=run, source_org_id=org, issue_type=issue_type, ref_number=row["ref"],
            fields_json=json.dumps(row["fields"], sort_keys=True))
    return run


@pytest.fixture
def issues(world):
    db, parent, child, relation, users, snaps = world
    db.execute("UPDATE org_relationships SET terms_json=%s WHERE id=%s",
               (json.dumps({"figure_measures": list(gf.PUBLISHABLE), "issue_types": ["dsr", "consent"]}), relation))
    for who in ("grc", "audit"):
        _id(db, "group_view_grants", relationship_id=relation, source_org_id=child, viewer_org_id=parent,
            user_id=users[who]["id"], capability="issue.view", expires_at=_future(30), review_due_at=_future(7),
            granted_by=999)
    dsr = _run(db, child, "dsr", [{"ref": "DSR-1", "fields": {"status": "open", "request_type": "access"}},
                                  {"ref": "DSR-2", "fields": {"status": "open"}},
                                  {"ref": "DSR-3", "fields": {"status": "completed"}}])
    consent = _run(db, child, "consent", [{"ref": "consent-summary", "fields": {"active": 40, "withdrawn": 2}}])
    return db, parent, child, relation, users, dsr, consent


def _issues(pack, name="Pack Child"):
    entity = next(e for e in pack["entities"] if e["name"] == name)
    return {i["type"]: (i["total"], i["counts"]) for i in entity["issues"]}


def test_a_pack_freezes_issue_counts_never_rows_and_shows_them_under_the_register_rules(issues):
    db, parent, child, relation, users, dsr, consent = issues
    pack_id = _make(db, users)
    stored = db.execute("SELECT manifest_json FROM group_packs WHERE id=%s", (pack_id,)).fetchone()[0]
    assert "DSR-1" not in stored and "access" not in stored, "a pack holds counts, never a reference or a field"
    pack = gp.get(db, users["grc"], pack_id)
    assert pack["integrity"] == "passed"
    assert _issues(pack) == {"dsr": (3, {"completed": 1, "open": 2}), "consent": (1, {"active": 40, "withdrawn": 2})}
    assert all(not e.get("issues") for e in gp.get(db, users["audit"], pack_id)["entities"]), \
        "the Audit Lead holds an issue grant but not the register role"
    assert all(not e.get("issues") for e in gp.get(db, users["comp"], pack_id)["entities"]), "no issue grant, no counts"
    db.execute("UPDATE org_relationships SET terms_json=%s WHERE id=%s",
               (json.dumps({"figure_measures": list(gf.PUBLISHABLE), "issue_types": ["consent"]}), relation))
    db.commit()
    assert set(_issues(gp.get(db, users["grc"], pack_id))) == {"consent"}, "narrowed terms stop showing a type"


def test_the_frozen_counts_are_checked_against_the_run(issues):
    db, parent, child, relation, users, dsr, consent = issues
    pack_id = _make(db, users)
    db.execute("UPDATE group_issue_rows SET fields_json=%s WHERE run_id=%s AND ref_number='DSR-3'",
               (json.dumps({"status": "open"}), dsr))
    db.commit()
    assert gp.get(db, users["grc"], pack_id)["integrity"] == "failed"


def test_runs_a_pack_froze_are_never_pruned(issues):
    db, parent, child, relation, users, dsr, consent = issues
    pack_id = _make(db, users)
    for _ in range(gi.KEEP_RUNS + 1):
        _run(db, child, "dsr", [])
    gi.publish_tenant(child, "pk_child")
    kept = {r[0] for r in db.execute("SELECT id FROM group_issue_runs WHERE source_org_id=%s AND issue_type='dsr'",
                                     (child,)).fetchall()}
    assert dsr in kept and len(kept) == gi.KEEP_RUNS + 1, "the pack's run is kept on top of the latest 30"
    assert gp.get(db, users["grc"], pack_id)["integrity"] == "passed"


def test_retention_and_legal_hold_are_recorded_with_history_and_nothing_is_deleted(issues):
    db, parent, child, relation, users, dsr, consent = issues
    pack_id = _make(db, users)
    assert gp.get(db, users["comp"], pack_id)["retention"] is None
    for who, until, hold, reason, code in (("emp", _future(400)[:10], False, "Board records policy", 403),
                                           ("audit", _future(400)[:10], False, "Board records policy", 403),
                                           ("comp", "2020-01-01", False, "Board records policy", 422),
                                           ("comp", _future(400)[:10], "yes", "Board records policy", 422),
                                           ("comp", _future(400)[:10], False, "short", 422)):
        with pytest.raises(HTTPException) as bad:
            gp.set_retention(db, users[who], pack_id, until, hold, reason)
        assert bad.value.status_code == code, who
    with pytest.raises(HTTPException) as foreign:
        gp.set_retention(db, users["child_comp"], pack_id, _future(400)[:10], False, "Board records policy")
    assert foreign.value.status_code == 404
    gp.set_retention(db, users["comp"], pack_id, _future(2000)[:10], False, "Board records are kept seven years")
    kept = gp.set_retention(db, users["grc"], pack_id, _future(2500)[:10], True, "Regulator inquiry opened")
    db.commit()
    assert kept["legal_hold"] is True and kept["reason"] == "Regulator inquiry opened"
    assert db.execute("SELECT COUNT(*) FROM group_pack_retention WHERE pack_id=%s", (pack_id,)).fetchone()[0] == 2
    pack = gp.get(db, users["comp"], pack_id)
    assert pack["retention"]["legal_hold"] is True and pack["integrity"] == "passed"
    from core.report_kit.render_pdf import render_pdf
    from core.report_kit.render_xlsx import render_xlsx
    grc_pack = gp.get(db, users["grc"], pack_id)
    report = gp.build_report(users["grc"], "Pack Parent", grc_pack)
    assert render_pdf(report)[:4] == b"%PDF" and render_xlsx(report)[:2] == b"PK"
