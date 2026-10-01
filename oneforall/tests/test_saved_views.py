"""
PLAN-36 P06: saved views (CRUD, filter-JSON allowlist validation, owner vs
shared visibility/edit rights, default-flag uniqueness) and the generic
permission-safe bulk-action engine (authorize/execute separation, atomic
vs best-effort semantics, idempotency replay, audit logging).
"""
import pytest

from modules.saved_views import data_service as svc


def _org(db, org_id=1):
    db.execute("INSERT INTO organizations (id, name, slug) VALUES (%s,%s,%s)",
               (org_id, f"org{org_id}", f"org{org_id}"))


def _user(db, uid, org_id=1, username=None):
    username = username or f"user{uid}"
    db.execute(
        "INSERT INTO users (id, username, email, full_name, password_hash, org_id) "
        "VALUES (%s,%s,%s,%s,'x',%s)", (uid, username, f"{username}@x.com", username, org_id),
    )


def _actor(db, uid):
    row = db.execute("SELECT id, username, org_id FROM users WHERE id=%s", (uid,)).fetchone()
    return dict(row)


@pytest.fixture(autouse=True)
def _schema(monkeypatch):
    """Isolate the module-level schema registry per test -- tests must not
    see schemas another test file (e.g. modules/evidence/routes.py's own
    import-time registration) happened to register first."""
    monkeypatch.setattr(svc, "_SCHEMAS", {})
    svc.register_view_schema(
        "widgets", "list", allowed_params={"status", "q"},
        sortable_fields={"updated_at", "name"}, available_columns={"name", "status"},
    )


@pytest.fixture
def actor(test_db):
    _org(test_db)
    _user(test_db, 1)
    test_db.commit()
    return _actor(test_db, 1)


# ─────────────────────────────────────────────────────────────────────────
# Filter-JSON allowlist validation -- the actual mechanism behind "malicious
# filter JSON cannot alter queries": an unknown key is rejected outright,
# never silently stored or passed through.
# ─────────────────────────────────────────────────────────────────────────

def test_unknown_filter_param_is_rejected(test_db, actor):
    with pytest.raises(svc.SavedViewError) as exc_info:
        svc.create_saved_view(
            test_db, actor, module="widgets", view_key="list", name="My View",
            filter_params={"status": "active", "'; DROP TABLE users; --": "x"},
        )
    assert exc_info.value.code == "INVALID_INPUT"


def test_allowed_filter_params_are_stored_and_returned_unchanged(test_db, actor):
    view = svc.create_saved_view(
        test_db, actor, module="widgets", view_key="list", name="Active widgets",
        filter_params={"status": "active", "q": "foo"},
    )
    assert view["filter_params"] == {"status": "active", "q": "foo"}


def test_unknown_sort_field_is_rejected(test_db, actor):
    with pytest.raises(svc.SavedViewError):
        svc.create_saved_view(
            test_db, actor, module="widgets", view_key="list", name="V",
            sort_field="password_hash",
        )


def test_unregistered_view_is_rejected(test_db, actor):
    with pytest.raises(svc.SavedViewError) as exc_info:
        svc.create_saved_view(test_db, actor, module="widgets", view_key="no_such_view", name="V")
    assert exc_info.value.code == "UNKNOWN_VIEW"


# ─────────────────────────────────────────────────────────────────────────
# Ownership, sharing, default flag
# ─────────────────────────────────────────────────────────────────────────

def test_shared_view_visible_to_others_but_not_editable_by_them(test_db):
    _org(test_db)
    _user(test_db, 1, username="owner")
    _user(test_db, 2, username="other")
    test_db.commit()
    owner = _actor(test_db, 1)
    other = _actor(test_db, 2)

    view = svc.create_saved_view(test_db, owner, module="widgets", view_key="list", name="Shared", shared=True)
    visible_to_other = svc.list_saved_views(test_db, other, "widgets", "list")
    assert any(v["id"] == view["id"] for v in visible_to_other)

    with pytest.raises(svc.SavedViewError) as exc_info:
        svc.update_saved_view(test_db, other, view["id"], name="Hijacked")
    assert exc_info.value.code == "NOT_FOUND"
    with pytest.raises(svc.SavedViewError):
        svc.delete_saved_view(test_db, other, view["id"])


def test_unshared_view_is_not_visible_to_others(test_db):
    _org(test_db)
    _user(test_db, 1, username="owner")
    _user(test_db, 2, username="other")
    test_db.commit()
    owner = _actor(test_db, 1)
    other = _actor(test_db, 2)
    view = svc.create_saved_view(test_db, owner, module="widgets", view_key="list", name="Private")
    assert not any(v["id"] == view["id"] for v in svc.list_saved_views(test_db, other, "widgets", "list"))


def test_views_are_scoped_per_org(test_db):
    _org(test_db, org_id=1)
    _org(test_db, org_id=2)
    _user(test_db, 1, org_id=1)
    _user(test_db, 2, org_id=2, username="otherorg")
    test_db.commit()
    org1_actor = _actor(test_db, 1)
    org2_actor = _actor(test_db, 2)
    svc.create_saved_view(test_db, org1_actor, module="widgets", view_key="list", name="Org1 shared", shared=True)
    assert svc.list_saved_views(test_db, org2_actor, "widgets", "list") == []


def test_only_one_default_per_owner_per_view(test_db, actor):
    first = svc.create_saved_view(test_db, actor, module="widgets", view_key="list", name="A", is_default=True)
    second = svc.create_saved_view(test_db, actor, module="widgets", view_key="list", name="B", is_default=True)
    views = {v["id"]: v for v in svc.list_saved_views(test_db, actor, "widgets", "list")}
    assert views[first["id"]]["is_default"] == 0
    assert views[second["id"]]["is_default"] == 1


# ─────────────────────────────────────────────────────────────────────────
# Generic bulk-action engine
# ─────────────────────────────────────────────────────────────────────────

def _seed_widgets(test_db, org_id=1):
    for i in (1, 2, 3):
        test_db.execute("INSERT INTO task_board (id, title, business_unit_id) VALUES (%s, %s, NULL)", (i, f"W{i}"))
    test_db.commit()


def test_bulk_action_reauthorizes_every_record_not_just_the_selection(test_db, actor):
    """The core acceptance line: 'a mixed authorized/unauthorized selection
    cannot mutate unauthorized rows.'"""
    _seed_widgets(test_db)

    def authorize(db, a, rid):
        return (rid != 2, "id 2 is deliberately unauthorized" if rid == 2 else None)

    applied_ids = []

    def execute(db, a, rid):
        applied_ids.append(rid)

    result = svc.execute_bulk_action(
        test_db, actor, module="widgets", action_name="test_action", record_ids=[1, 2, 3],
        authorize_fn=authorize, execute_fn=execute,
    )
    assert result["applied"] == [1, 3]
    assert applied_ids == [1, 3]
    assert len(result["skipped"]) == 1
    assert result["skipped"][0]["id"] == 2


def test_atomic_mode_applies_nothing_if_any_record_fails_authorization(test_db, actor):
    executed = []

    def authorize(db, a, rid):
        return (rid != 2, "nope" if rid == 2 else None)

    def execute(db, a, rid):
        executed.append(rid)

    result = svc.execute_bulk_action(
        test_db, actor, module="widgets", action_name="test_atomic", record_ids=[1, 2, 3],
        authorize_fn=authorize, execute_fn=execute, atomic=True,
    )
    assert result["applied"] == []
    assert executed == []
    assert len(result["skipped"]) == 3


def test_a_record_level_execution_failure_does_not_block_the_others(test_db, actor):
    def authorize(db, a, rid):
        return True, None

    def execute(db, a, rid):
        if rid == 2:
            raise ValueError("simulated failure")

    result = svc.execute_bulk_action(
        test_db, actor, module="widgets", action_name="test_partial_fail", record_ids=[1, 2, 3],
        authorize_fn=authorize, execute_fn=execute,
    )
    assert result["applied"] == [1, 3]
    assert any(s["id"] == 2 for s in result["skipped"])


def test_bulk_action_writes_one_bounded_audit_log_row(test_db, actor):
    svc.execute_bulk_action(
        test_db, actor, module="widgets", action_name="test_audit", record_ids=[1, 2, 3],
        authorize_fn=lambda db, a, rid: (True, None), execute_fn=lambda db, a, rid: None,
    )
    rows = test_db.execute(
        "SELECT * FROM audit_log WHERE module='widgets' AND action='test_audit'"
    ).fetchall()
    assert len(rows) == 1
    assert "3 of 3" in rows[0]["details"]


def test_idempotency_key_replay_does_not_re_execute(test_db, actor):
    """Red/green-relevant: task_plan.md's own 'idempotency keys for
    retryable bulk operations' -- a retried call with the same key must
    return the original outcome, not run execute_fn a second time."""
    call_count = {"n": 0}

    def execute(db, a, rid):
        call_count["n"] += 1

    first = svc.execute_bulk_action(
        test_db, actor, module="widgets", action_name="test_idem", record_ids=[1, 2],
        authorize_fn=lambda db, a, rid: (True, None), execute_fn=execute,
        idempotency_key="retry-key-1",
    )
    assert call_count["n"] == 2
    assert first["idempotent_replay"] is False

    second = svc.execute_bulk_action(
        test_db, actor, module="widgets", action_name="test_idem", record_ids=[1, 2],
        authorize_fn=lambda db, a, rid: (True, None), execute_fn=execute,
        idempotency_key="retry-key-1",
    )
    assert call_count["n"] == 2  # not incremented again
    assert second["idempotent_replay"] is True
    assert second["applied"] == first["applied"]


def test_different_idempotency_keys_both_execute(test_db, actor):
    call_count = {"n": 0}

    def execute(db, a, rid):
        call_count["n"] += 1

    svc.execute_bulk_action(
        test_db, actor, module="widgets", action_name="test_idem2", record_ids=[1],
        authorize_fn=lambda db, a, rid: (True, None), execute_fn=execute, idempotency_key="key-a",
    )
    svc.execute_bulk_action(
        test_db, actor, module="widgets", action_name="test_idem2", record_ids=[1],
        authorize_fn=lambda db, a, rid: (True, None), execute_fn=execute, idempotency_key="key-b",
    )
    assert call_count["n"] == 2
