"""
Real PostgreSQL initialization tests (PLAN-35 T11 acceptance).

Why this file exists: every other test in this suite forces SQLite
(conftest.py sets DATABASE_URL="" so a developer's real DB is never
touched). That is correct for unit tests but structurally blind to a
whole class of bug -- SQLite tolerates schema shapes PostgreSQL rejects.
Exactly one such bug shipped undetected: aria_policy_drafts and
aria_policy_versions have a cyclic foreign-key dependency (drafts carries
three forward FKs to versions; versions references drafts back). SQLite
allows the forward references at CREATE TABLE time; PostgreSQL raises
`UndefinedTable: relation "aria_policy_versions" does not exist` and the
entire init aborts. It was invisible because nothing here ran init_db()
against a real PostgreSQL.

These tests run against a real PostgreSQL only when TEST_DATABASE_URL is
set (e.g. a throwaway container); they skip otherwise, so the default
SQLite suite is unaffected and CI without a database still passes. To run
them:

    docker run -d --name pg -e POSTGRES_PASSWORD=pg -e POSTGRES_DB=t \
        -p 55432:5432 postgres:18
    TEST_DATABASE_URL="postgresql://postgres:pg@localhost:55432/t" \
        python -m pytest tests/test_postgres_init.py -v

The DB is wiped (DROP SCHEMA public CASCADE) before each test, so it must
point at a disposable database, never a real one.
"""
import os

import pytest

_PG_URL = os.getenv("TEST_DATABASE_URL", "")

pytestmark = pytest.mark.skipif(
    not _PG_URL.startswith("postgresql"),
    reason="TEST_DATABASE_URL not set to a PostgreSQL DSN; skipping real-PG tests.",
)

psycopg2 = pytest.importorskip("psycopg2")
import psycopg2.pool  # noqa: E402
import psycopg2.extras  # noqa: E402
import psycopg2.extensions  # noqa: E402

_WORKFLOW_TABLES = (
    "aria_policy_drafts",
    "aria_policy_versions",
    "aria_document_approvals",
    "aria_policy_publication_jobs",
    "aria_document_number_sequence",
    "scheduler_locks",
)
_DEFERRED_FKS = (
    "fk_aria_drafts_base_version",
    "fk_aria_drafts_copied_version",
    "fk_aria_drafts_committed_version",
)


def _raw_conn():
    """A direct psycopg2 connection (autocommit) independent of the app pool,
    used for schema resets and assertions."""
    conn = psycopg2.connect(_PG_URL)
    conn.autocommit = True
    return conn


def _reset_public_schema():
    conn = _raw_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    finally:
        conn.close()


@pytest.fixture
def pg(monkeypatch):
    """Point the app at the throwaway PostgreSQL with a wiped public schema,
    then restore SQLite mode and drop the pool afterward so this never leaks
    into a later SQLite test running in the same process."""
    import database
    from config import settings

    # database.py binds psycopg2 (and the psycopg2 exception aliases) at import
    # time only when DATABASE_URL is already PostgreSQL. Under pytest, conftest
    # clears DATABASE_URL before that import, so the binding never happened.
    # Inject it now -- exactly what the real VPS process gets for free, since
    # there DATABASE_URL is set before the app starts.
    monkeypatch.setattr(database, "psycopg2", psycopg2, raising=False)
    monkeypatch.setattr(database, "IntegrityError", psycopg2.IntegrityError, raising=False)
    monkeypatch.setattr(database, "OperationalError", psycopg2.OperationalError, raising=False)
    monkeypatch.setattr(database, "LockError",
                        psycopg2.extensions.TransactionRollbackError, raising=False)

    # Close any pool a prior test left open before wiping the schema.
    if getattr(database, "_pg_pool", None) is not None:
        try:
            database._pg_pool.closeall()
        except Exception:
            pass
        database._pg_pool = None

    _reset_public_schema()

    monkeypatch.setenv("DATABASE_URL", _PG_URL)
    monkeypatch.setattr(settings, "DATABASE_URL", _PG_URL)
    # The DSN already carries its password inline; make sure the pool builder
    # does not try to override it from a Docker secret / PGPASSWORD.
    monkeypatch.setattr(database, "_read_pg_password", lambda: "")

    yield database

    # Teardown: drop the pool and clear PG mode so unrelated tests are unaffected.
    if getattr(database, "_pg_pool", None) is not None:
        try:
            database._pg_pool.closeall()
        except Exception:
            pass
        database._pg_pool = None


def _fk_constraints(database):
    conn = database.get_db_bypass_rls()
    try:
        rows = conn.execute(
            "SELECT constraint_name FROM information_schema.table_constraints "
            "WHERE table_name='aria_policy_drafts' AND constraint_type='FOREIGN KEY' "
            "AND constraint_name LIKE 'fk_aria_drafts_%' AND table_schema=current_schema()"
        ).fetchall()
        return sorted(r["constraint_name"] for r in rows)
    finally:
        conn.close()


def _tables_present(database):
    conn = database.get_db_bypass_rls()
    try:
        rows = conn.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema=current_schema()"
        ).fetchall()
        return {r["table_name"] for r in rows}
    finally:
        conn.close()


def test_fresh_init_builds_the_workflow_schema_on_real_postgres(pg):
    """The exact scenario that failed acceptance: init_db() against a fresh
    PostgreSQL. Before the _break_pg_fk_cycle fix this raised UndefinedTable
    on the first ARIA CREATE and aborted."""
    pg.init_db()  # must not raise

    present = _tables_present(pg)
    for t in _WORKFLOW_TABLES:
        assert t in present, f"{t} was not created"

    assert _fk_constraints(pg) == sorted(_DEFERRED_FKS), (
        "the three deferred drafts->versions FKs must be re-added after both tables exist"
    )


def test_reinit_is_idempotent(pg):
    """An 'upgrade' over an already-initialized DB: running init_db() again
    must not raise and must not duplicate the deferred FK constraints."""
    pg.init_db()
    pg.init_db()  # second pass, everything already exists

    assert _fk_constraints(pg) == sorted(_DEFERRED_FKS), (
        "re-init must leave exactly the three constraints, not duplicate them"
    )


def test_upgrade_from_a_pre_workflow_database(pg):
    """Faithful edffc9a -> 041edec delta: a fully-initialized DB that then has
    the workflow tables removed (as production, 15 commits behind, does not
    have them at all), re-initialized. The workflow tables and their deferred
    FKs must come back cleanly against a database that already holds every
    other table and its data."""
    pg.init_db()

    conn = pg.get_db_bypass_rls()
    try:
        # Drop exactly the PLAN-35 workflow tables, as if this DB predated them.
        conn.execute(
            "DROP TABLE IF EXISTS "
            "aria_document_approvals, aria_policy_publication_jobs, "
            "aria_policy_versions, aria_policy_drafts, "
            "aria_document_number_sequence, scheduler_locks CASCADE"
        )
        conn.commit()
    finally:
        conn.close()

    present_after_drop = _tables_present(pg)
    assert "aria_policy_drafts" not in present_after_drop  # sanity: really gone

    pg.init_db()  # the upgrade

    present = _tables_present(pg)
    for t in _WORKFLOW_TABLES:
        assert t in present, f"{t} was not recreated on upgrade"
    assert _fk_constraints(pg) == sorted(_DEFERRED_FKS)


def test_deferred_fk_is_actually_enforced_not_just_present(pg):
    """A constraint that exists but is not enforced would be worthless. Insert
    a draft whose base_version_id points at a nonexistent version and require
    PostgreSQL to reject it -- proving the re-added FK is a real, enforced
    constraint, not a cosmetic row in the catalog."""
    pg.init_db()

    conn = pg.get_db_bypass_rls()
    try:
        conn.execute(
            "INSERT INTO organizations (name, slug) VALUES ('T','t-pg-init')"
        )
        org_id = conn.execute(
            "SELECT id FROM organizations WHERE slug='t-pg-init'"
        ).fetchone()["id"]
        conn.commit()

        with pytest.raises(Exception) as exc_info:
            conn.execute(
                "INSERT INTO aria_policy_drafts (id, org_id, base_version_id) "
                "VALUES ('draft-pg-1', %s, 999999)",
                (org_id,),
            )
            conn.commit()
        # psycopg2 raises ForeignKeyViolation (a subclass of IntegrityError).
        assert "foreign key" in str(exc_info.value).lower() or \
               "violates" in str(exc_info.value).lower()
    finally:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        conn.close()
