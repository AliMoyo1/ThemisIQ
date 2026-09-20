"""Focused regressions for publication retries and PostgreSQL session hygiene."""

import core.events
import database
from database import insert_returning_id
from modules.aria import policy_publication as publication


def _running_publication_job(db) -> dict:
    db.execute(
        "INSERT INTO organizations (id, name, slug) VALUES (1,'Test Org','test-org')"
    )
    document_id = insert_returning_id(
        db,
        "INSERT INTO aria_documents "
        "(doc_id, framework, control_ref, title, version, status, org_id, "
        " policy_workflow_managed) "
        "VALUES ('POL-0001','ISO 27001','A.1','Access Policy','1.0','Approved',1,1)",
        (),
    )
    version_id = insert_returning_id(
        db,
        "INSERT INTO aria_policy_versions "
        "(org_id, document_id, version_major, version_minor, version, state, origin) "
        "VALUES (1,%s,1,0,'1.0','approved','authored')",
        (document_id,),
    )
    job_id = insert_returning_id(
        db,
        "INSERT INTO aria_policy_publication_jobs "
        "(org_id, policy_version_id, document_id, publication_key, state, attempts, "
        " lease_until, lease_token) "
        "VALUES (1,%s,%s,'publication-test','running',1,'2999-01-01T00:00:00','lease-1')",
        (version_id, document_id),
    )
    db.commit()
    return dict(db.execute(
        "SELECT * FROM aria_policy_publication_jobs WHERE id=%s", (job_id,)
    ).fetchone())


def _skip_completed_copy_work(monkeypatch) -> None:
    monkeypatch.setattr(publication, "_copy_to_evidence_vault", lambda *args: 1)
    monkeypatch.setattr(publication, "_copy_to_grid_evidence", lambda *args: [])
    monkeypatch.setattr("modules.aria.ask_service.reindex_document", lambda *args: None)


def test_emit_exception_uses_the_bounded_retry_path(test_db, monkeypatch):
    job = _running_publication_job(test_db)
    _skip_completed_copy_work(monkeypatch)
    monkeypatch.setattr(
        core.events,
        "emit",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("event bus unavailable")),
    )

    outcome = publication.process_job(test_db, job, is_postgres=False)

    assert outcome == "retry_scheduled"
    row = test_db.execute(
        "SELECT state, lease_token, next_attempt_at, last_error "
        "FROM aria_policy_publication_jobs WHERE id=%s",
        (job["id"],),
    ).fetchone()
    assert row["state"] == "pending"
    assert row["lease_token"] is None
    assert row["next_attempt_at"] is not None
    assert "event bus unavailable" in row["last_error"]


def test_failed_event_status_retains_event_id_for_retry(test_db, monkeypatch):
    job = _running_publication_job(test_db)
    _skip_completed_copy_work(monkeypatch)
    event_id = insert_returning_id(
        test_db,
        "INSERT INTO events "
        "(event_type, source_module, source_entity_type, source_entity_id, payload, status) "
        "VALUES ('aria.policy.published','aria','document',1,'{}','failed')",
        (),
    )
    test_db.commit()
    monkeypatch.setattr(core.events, "emit", lambda *args, **kwargs: event_id)

    outcome = publication.process_job(test_db, job, is_postgres=False)

    assert outcome == "retry_scheduled"
    row = test_db.execute(
        "SELECT state, event_id, last_error FROM aria_policy_publication_jobs WHERE id=%s",
        (job["id"],),
    ).fetchone()
    assert row["state"] == "pending"
    assert row["event_id"] == event_id
    assert "status=failed" in row["last_error"]


def test_postgres_scheduler_lock_is_atomic_and_public_qualified(monkeypatch):
    class _Cursor:
        def __init__(self, row):
            self._row = row

        def fetchone(self):
            return self._row

    class _Db:
        def __init__(self, row):
            self.row = row
            self.calls = []
            self.commits = 0

        def execute(self, sql, params=None):
            self.calls.append((sql, params))
            return _Cursor(self.row)

        def commit(self):
            self.commits += 1

    monkeypatch.setattr(database.settings, "is_postgres", lambda: True)

    winner = _Db({"lock_name": "retention"})
    assert database.try_acquire_scheduler_lock(winner, "retention", 60) is True
    sql, params = winner.calls[0]
    assert "INSERT INTO public.scheduler_locks" in sql
    assert "ON CONFLICT" in sql
    assert "RETURNING" in sql
    assert winner.commits == 1

    loser = _Db(None)
    assert database.try_acquire_scheduler_lock(loser, "retention", 60) is False
    assert len(loser.calls) == 1
    assert loser.commits == 1


def test_postgres_pool_return_resets_and_commits_tenant_session_state(monkeypatch):
    events = []

    class _Cursor:
        def execute(self, sql, params=None):
            events.append(("execute", sql, params))

    class _RawConnection:
        def cursor(self, *args, **kwargs):
            return _Cursor()

        def rollback(self):
            events.append(("rollback",))

        def commit(self):
            events.append(("commit",))

    class _Pool:
        def putconn(self, conn, close=False):
            events.append(("putconn", close))

    monkeypatch.setattr(database, "_get_pg_pool", lambda: _Pool())
    wrapper = database._PgConnWrapper(_RawConnection())

    wrapper.close()

    assert events[0] == ("rollback",)
    sql = [entry[1] for entry in events if entry[0] == "execute"]
    assert "SET search_path TO public" in sql
    assert "SET app.current_org_id = ''" in sql
    assert "SET app.is_super_admin = 'false'" in sql
    assert "SET app.bypass_rls = 'false'" in sql
    assert ("commit",) in events
    assert events[-1] == ("putconn", False)
    assert events.index(("commit",)) < events.index(("putconn", False))
