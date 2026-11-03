"""Group figures must fail safely when SQLite cannot attribute legacy controls to a tenant."""

import pytest
from fastapi import HTTPException

from modules.governance import group_figures as gf
from modules.governance import group_band as gb
from modules.governance import group_issues as gi
from modules.governance import group_packs as gp


@pytest.mark.parametrize("child_status", ["active", "inactive"])
def test_multi_org_sqlite_blocks_figure_publication_and_historical_reads(test_db, child_status):
    db = test_db
    db.execute("INSERT INTO organizations (name, slug, status) VALUES ('Figure Parent', 'fig_guard_parent', 'active')")
    parent = db.execute("SELECT MAX(id) FROM organizations").fetchone()[0]
    db.execute("INSERT INTO organizations (name, slug, status) VALUES ('Figure Child', 'fig_guard_child', %s)",
               (child_status,))
    child = db.execute("SELECT MAX(id) FROM organizations").fetchone()[0]
    db.commit()
    actor = {"id": 123, "org_id": parent, "business_unit_id": None,
             "roles": ["grc_officer"], "is_super_admin": False}

    with pytest.raises(HTTPException) as blocked_publish:
        gf.publish_tenant(child, "fig_guard_child")
    assert blocked_publish.value.status_code == 503
    assert db.execute("SELECT COUNT(*) FROM group_figure_snapshots").fetchone()[0] == 0

    with pytest.raises(HTTPException) as blocked_view:
        gf.view(db, actor, "own")
    assert blocked_view.value.status_code == 503

    # An older snapshot or pack must not become readable just because a later release added the guard.
    with pytest.raises(HTTPException) as blocked_pack:
        gp.get(db, actor, 1)
    assert blocked_pack.value.status_code == 503

    with pytest.raises(HTTPException) as blocked_band_compute:
        gb.compute(parent)
    assert blocked_band_compute.value.status_code == 503
    with pytest.raises(HTTPException) as blocked_band_read:
        gb.read(db, actor)
    assert blocked_band_read.value.status_code == 503

    with pytest.raises(HTTPException) as blocked_issue_publish:
        gi.publish_tenant(child, "fig_guard_child")
    assert blocked_issue_publish.value.status_code == 503
    with pytest.raises(HTTPException) as blocked_issue_read:
        gi.view(db, {**actor, "roles": ["dpo"]}, child, "breach")
    assert blocked_issue_read.value.status_code == 503
