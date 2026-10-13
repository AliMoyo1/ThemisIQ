"""A Vault change that can lower a control's effectiveness score rescores that control at once.

The score earns 35 of its 100 points from live, current, unexpired evidence linked to the
canonical control. Unlinking, archiving, deleting or expiring that evidence used to leave the
stored score (and the ERM residual risk computed from it) as it was until the 03:00 UTC job.
The routes now rescore the controls the change touched, after the change itself has committed,
and a failure to rescore never undoes or fails the user's action.
"""
import asyncio
import json
import types

import pytest

import core.middleware as middleware
import modules.evidence.routes as vault
import modules.governance.effectiveness as eff

ADMIN = {"id": 1, "username": "admin", "org_id": None, "business_unit_id": None,
         "is_super_admin": 1, "roles": ["super_admin"]}
EARNED = 35  # evidence_uploaded 20 + evidence_valid 15
BASE = 10    # a control with no owner, no automation and no incidents still earns no_recent_incidents


@pytest.fixture(autouse=True)
def as_admin(monkeypatch):
    async def current_user(request):
        return ADMIN

    monkeypatch.setattr(middleware, "get_current_user", current_user)


def _insert(db, table, **cols):
    cur = db.execute(
        f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        tuple(cols.values()),
    )
    db.commit()
    return cur.lastrowid


def _request(payload=None):
    request = types.SimpleNamespace(
        state=types.SimpleNamespace(user=ADMIN), url=types.SimpleNamespace(path="/evidence/x"),
        query_params={}, headers={},
    )

    async def _json():
        return payload or {}

    request.json = _json
    return request


def _call(handler, *args, payload=None):
    response = asyncio.run(handler(_request(payload), *args))
    return response.status_code, json.loads(response.body)


class _World:
    """Two controls, each with one current evidence item live-linked to it, both freshly scored."""

    def __init__(self, db):
        self.db = db
        _insert(db, "users", id=1, username="admin", email="admin@example.test", full_name="Admin",
                password_hash="x")
        self.control = _insert(db, "canonical_controls", title="Scored control")
        self.other_control = _insert(db, "canonical_controls", title="Untouched control")
        self.item, self.link = self._evidence(self.control)
        self.other_item, _ = self._evidence(self.other_control)
        eff.recompute_controls_by_ids(db, [self.control, self.other_control])
        db.commit()

    def _evidence(self, control):
        item = _insert(self.db, "evidence_items", title=f"Evidence for {control}", status="current")
        link = _insert(self.db, "evidence_links", evidence_id=item, module="grid",
                       entity_type="canonical_control", entity_id=control)
        return item, link

    def score(self, control=None):
        return eff.get_control_score(self.db, control or self.control)["score"]


@pytest.fixture
def world(test_db):
    w = _World(test_db)
    assert w.score() == BASE + EARNED and w.score(w.other_control) == BASE + EARNED
    return w


def _assert_only_the_touched_control_dropped(w):
    assert w.score() == BASE
    assert eff.get_control_score(w.db, w.control)["evidence_uploaded"] == 0
    assert w.score(w.other_control) == BASE + EARNED


def test_unlinking_evidence_rescores_the_control(world):
    status, _ = _call(vault.api_evidence_link_delete, world.link)
    assert status == 200
    _assert_only_the_touched_control_dropped(world)


def test_archiving_evidence_rescores_the_controls_it_was_linked_to(world):
    status, _ = _call(vault.api_evidence_delete, world.item)
    assert status == 200
    _assert_only_the_touched_control_dropped(world)


def test_bulk_archiving_rescores_the_controls_of_every_item(world):
    status, body = _call(vault.api_evidence_bulk_archive, payload={"ids": [world.item]})
    assert status == 200 and body["ok"]
    _assert_only_the_touched_control_dropped(world)


def test_permanently_deleting_an_archived_item_that_kept_its_links_rescores(world):
    # Archived through the edit route, which leaves the links alone: the score already dropped,
    # then deleting removes the links for good and the score must still be right.
    _call(vault.api_evidence_update, world.item, payload={"status": "archived"})
    _assert_only_the_touched_control_dropped(world)
    status, _ = _call(vault.api_evidence_permanent_delete, world.item)
    assert status == 200
    _assert_only_the_touched_control_dropped(world)


def test_changing_status_or_expiry_in_the_edit_route_rescores(world):
    assert _call(vault.api_evidence_update, world.item, payload={"expiry_date": "2000-01-01"})[0] == 200
    _assert_only_the_touched_control_dropped(world)


def test_editing_only_the_title_does_not_rescore(world, monkeypatch):
    calls = []
    monkeypatch.setattr(eff, "recompute_controls_by_ids", lambda db, ids: calls.append(ids))
    assert _call(vault.api_evidence_update, world.item, payload={"title": "Renamed"})[0] == 200
    assert calls == []


def test_a_failure_to_rescore_never_undoes_or_fails_the_users_action(world, monkeypatch):
    def broken(db, ids):
        raise RuntimeError("scoring is down")

    monkeypatch.setattr(eff, "recompute_controls_by_ids", broken)
    status, body = _call(vault.api_evidence_link_delete, world.link)
    assert (status, body) == (200, {"success": True})
    removed = world.db.execute("SELECT deleted_at FROM evidence_links WHERE id=%s", (world.link,)).fetchone()
    assert removed["deleted_at"] is not None
    assert world.score() == BASE + EARNED, "the nightly job will catch the stale score up"
