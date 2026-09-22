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
SQLite suite is unaffected. They are intentionally destructive and require
both a database name beginning with "themisiq_test_" and an explicit
"THEMISIQ_ALLOW_DESTRUCTIVE_PG_TESTS=1" acknowledgement. For example:

    docker run -d --name themisiq-pg-test -e POSTGRES_PASSWORD=pg \
        -e POSTGRES_DB=themisiq_test_policy_schema \
        -p 127.0.0.1:55432:5432 postgres:18
    THEMISIQ_ALLOW_DESTRUCTIVE_PG_TESTS=1 \
        TEST_DATABASE_URL="postgresql://postgres:pg@localhost:55432/themisiq_test_policy_schema" \
        python -m pytest oneforall/tests/test_postgres_init.py -v

The target's public and tenant_* schemas are wiped before each test. The
two-part guard is checked before any connection or DROP is attempted.
"""
import os
from urllib.parse import unquote, urlparse

import pytest

_PG_URL = os.getenv("TEST_DATABASE_URL", "")
_DESTRUCTIVE_ACK = os.getenv("THEMISIQ_ALLOW_DESTRUCTIVE_PG_TESTS", "")
_TEST_DB_PREFIX = "themisiq_test_"


def _validate_destructive_test_target(url: str, acknowledgement: str) -> str:
    """Return the parsed database name or reject the target without connecting."""
    parsed = urlparse(url)
    if parsed.scheme not in {"postgres", "postgresql"}:
        raise ValueError("TEST_DATABASE_URL must use postgres:// or postgresql://")
    database_name = unquote(parsed.path.lstrip("/"))
    if not database_name or "/" in database_name:
        raise ValueError("TEST_DATABASE_URL must identify exactly one database")
    if not database_name.startswith(_TEST_DB_PREFIX):
        raise ValueError(
            f"destructive PostgreSQL tests require a database named {_TEST_DB_PREFIX}*"
        )
    if acknowledgement != "1":
        raise ValueError(
            "set THEMISIQ_ALLOW_DESTRUCTIVE_PG_TESTS=1 to acknowledge schema deletion"
        )
    return database_name


if _PG_URL:
    try:
        _EXPECTED_DB_NAME = _validate_destructive_test_target(
            _PG_URL, _DESTRUCTIVE_ACK
        )
    except ValueError as exc:
        raise pytest.UsageError(str(exc)) from exc
else:
    _EXPECTED_DB_NAME = ""

pytestmark = pytest.mark.skipif(
    not _PG_URL,
    reason="TEST_DATABASE_URL not set to a PostgreSQL DSN; skipping real-PG tests.",
)

psycopg2 = pytest.importorskip("psycopg2")
from psycopg2 import sql  # noqa: E402
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
_REQUIRED_POLICY_FKS = (
    ("aria_policy_drafts", "base_version_id", "aria_policy_versions", "id"),
    ("aria_policy_drafts", "copied_from_version_id", "aria_policy_versions", "id"),
    ("aria_policy_drafts", "committed_version_id", "aria_policy_versions", "id"),
    ("aria_documents", "current_policy_version_id", "aria_policy_versions", "id"),
    ("evidence_items", "aria_policy_version_id", "aria_policy_versions", "id"),
    ("grid_evidence_files", "aria_policy_version_id", "aria_policy_versions", "id"),
)


def _raw_conn():
    """A direct psycopg2 connection (autocommit) independent of the app pool,
    used for schema resets and assertions."""
    conn = psycopg2.connect(_PG_URL)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT current_database()")
        actual_database = cur.fetchone()[0]
    if (
        actual_database != _EXPECTED_DB_NAME
        or not actual_database.startswith(_TEST_DB_PREFIX)
    ):
        conn.close()
        raise RuntimeError(
            "refusing destructive PostgreSQL test against an unexpected database"
        )
    return conn


def _reset_public_schema():
    conn = _raw_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT schema_name FROM information_schema.schemata "
                "WHERE schema_name ~ '^tenant_'"
            )
            for (schema_name,) in cur.fetchall():
                cur.execute(
                    sql.SQL("DROP SCHEMA {} CASCADE").format(
                        sql.Identifier(schema_name)
                    )
                )
            cur.execute("DROP SCHEMA public CASCADE")
            cur.execute("CREATE SCHEMA public")
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


def _policy_fk_shapes(database, tenant: str = ""):
    conn = database.get_db_bypass_rls()
    try:
        if tenant:
            conn.set_tenant(tenant)
        schema_name = conn.execute(
            "SELECT current_schema() AS schema_name"
        ).fetchone()["schema_name"]
        rows = conn.execute(
            "SELECT tc.table_name, kcu.column_name, "
            "ccu.table_schema AS referenced_schema, "
            "ccu.table_name AS referenced_table, "
            "ccu.column_name AS referenced_column "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "ON tc.constraint_catalog=kcu.constraint_catalog "
            "AND tc.constraint_schema=kcu.constraint_schema "
            "AND tc.constraint_name=kcu.constraint_name "
            "AND tc.table_schema=kcu.table_schema "
            "AND tc.table_name=kcu.table_name "
            "JOIN information_schema.constraint_column_usage ccu "
            "ON tc.constraint_catalog=ccu.constraint_catalog "
            "AND tc.constraint_schema=ccu.constraint_schema "
            "AND tc.constraint_name=ccu.constraint_name "
            "WHERE tc.constraint_type='FOREIGN KEY' "
            "AND tc.table_schema=current_schema()"
        ).fetchall()
        return schema_name, {
            (
                row["table_name"],
                row["column_name"],
                row["referenced_schema"],
                row["referenced_table"],
                row["referenced_column"],
            )
            for row in rows
        }
    finally:
        conn.close()


def _assert_required_policy_fks(database, tenant: str = ""):
    schema_name, shapes = _policy_fk_shapes(database, tenant)
    for table, column, ref_table, ref_column in _REQUIRED_POLICY_FKS:
        assert (
            table, column, schema_name, ref_table, ref_column
        ) in shapes, (
            f"missing same-schema FK {table}.{column} -> "
            f"{ref_table}.{ref_column}"
        )


def _tables_present(database, tenant: str = ""):
    conn = database.get_db_bypass_rls()
    try:
        if tenant:
            conn.set_tenant(tenant)
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
    _assert_required_policy_fks(pg)


def test_reinit_is_idempotent(pg):
    """An 'upgrade' over an already-initialized DB: running init_db() again
    must not raise and must not duplicate the deferred FK constraints."""
    pg.init_db()
    pg.init_db()  # second pass, everything already exists

    assert _fk_constraints(pg) == sorted(_DEFERRED_FKS), (
        "re-init must leave exactly the three constraints, not duplicate them"
    )
    _assert_required_policy_fks(pg)


def test_tenant_schema_policy_fks_never_fall_back_to_public(pg):
    pg.init_db()
    pg.provision_tenant_schema("reviewtenant")

    schema_name, _ = _policy_fk_shapes(pg, "reviewtenant")
    assert schema_name == "tenant_reviewtenant"
    _assert_required_policy_fks(pg, "reviewtenant")

    conn = pg.get_db_bypass_rls()
    try:
        conn.set_tenant("reviewtenant")
        ready, missing = pg.aria_policy_workflow_schema_ready(conn)
        assert ready, missing
    finally:
        conn.close()


def test_erm_scan_job_table_exists_in_public_and_tenant_schemas(pg):
    pg.init_db()
    assert "erm_emerging_scan_jobs" in _tables_present(pg)

    pg.provision_tenant_schema("scanqueue")
    assert "erm_emerging_scan_jobs" in _tables_present(pg, "scanqueue")


def test_reinit_repairs_existing_projection_columns_after_workflow_loss(pg):
    """CASCADE can remove FKs while leaving their source columns in place."""
    pg.init_db()

    conn = pg.get_db_bypass_rls()
    try:
        conn.execute(
            "DROP TABLE IF EXISTS "
            "aria_document_approvals, aria_policy_publication_jobs, "
            "aria_policy_versions, aria_policy_drafts, "
            "aria_document_number_sequence, scheduler_locks CASCADE"
        )
        conn.commit()
    finally:
        conn.close()

    _, shapes = _policy_fk_shapes(pg)
    for table, column, ref_table, ref_column in _REQUIRED_POLICY_FKS[3:]:
        assert not any(
            shape[0] == table and shape[1] == column
            for shape in shapes
        ), f"sanity: {table}.{column} FK should have been removed by CASCADE"

    pg.init_db()
    _assert_required_policy_fks(pg)


def test_upgrade_from_a_pre_workflow_database(pg):
    """Focused pre-workflow shape simulation.

    Preserve legacy document data while removing the workflow tables and all
    five columns introduced for policy authoring. Re-initialization must
    restore the complete shape and every same-schema policy-version FK.
    """
    pg.init_db()

    conn = pg.get_db_bypass_rls()
    try:
        conn.execute(
            "INSERT INTO aria_documents (doc_id, framework, title) "
            "VALUES ('legacy-pg-doc', 'ISO 27001', 'Legacy policy')"
        )
        conn.commit()

        conn.execute(
            "DROP TABLE IF EXISTS "
            "aria_document_approvals, aria_policy_publication_jobs, "
            "aria_policy_versions, aria_policy_drafts, "
            "aria_document_number_sequence, scheduler_locks CASCADE"
        )
        for table, column in (
            ("aria_documents", "current_policy_version_id"),
            ("aria_documents", "policy_workflow_managed"),
            ("aria_doc_templates", "is_active"),
            ("evidence_items", "aria_policy_version_id"),
            ("grid_evidence_files", "aria_policy_version_id"),
        ):
            conn.execute(
                f"ALTER TABLE {table} DROP COLUMN IF EXISTS {column} CASCADE"
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
    _assert_required_policy_fks(pg)

    conn = pg.get_db_bypass_rls()
    try:
        preserved = conn.execute(
            "SELECT title FROM aria_documents WHERE doc_id='legacy-pg-doc'"
        ).fetchone()
        assert preserved and preserved["title"] == "Legacy policy"
        ready, missing = pg.aria_policy_workflow_schema_ready(conn)
        assert ready, missing
    finally:
        conn.close()


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


def test_init_fails_closed_when_required_fk_cannot_be_restored(pg):
    """An orphan must make startup fail, and readiness must report the FK."""
    pg.init_db()

    conn = pg.get_db_bypass_rls()
    try:
        conn.execute(
            "INSERT INTO organizations (name, slug) "
            "VALUES ('Orphan Test','orphan-pg-init')"
        )
        org_id = conn.execute(
            "SELECT id FROM organizations WHERE slug='orphan-pg-init'"
        ).fetchone()["id"]
        conn.execute(
            "ALTER TABLE aria_policy_drafts "
            "DROP CONSTRAINT fk_aria_drafts_base_version"
        )
        conn.execute(
            "INSERT INTO aria_policy_drafts (id, org_id, base_version_id) "
            "VALUES ('draft-orphan-pg', %s, 999999999)",
            (org_id,),
        )
        conn.commit()

        ready, missing = pg.aria_policy_workflow_schema_ready(conn)
        assert not ready
        assert "constraint:fk_aria_drafts_base_version" in missing
    finally:
        conn.close()

    with pytest.raises(
        RuntimeError,
        match="Required ARIA policy workflow foreign keys could not be ensured",
    ):
        pg.init_db()


def test_destructive_target_validator_rejects_unsafe_targets():
    assert _validate_destructive_test_target(
        "postgresql://postgres:pg@localhost/themisiq_test_guard", "1"
    ) == "themisiq_test_guard"

    with pytest.raises(ValueError, match="database named"):
        _validate_destructive_test_target(
            "postgresql://postgres:pg@localhost/themisiq", "1"
        )
    with pytest.raises(ValueError, match="acknowledge"):
        _validate_destructive_test_target(
            "postgresql://postgres:pg@localhost/themisiq_test_guard", ""
        )


def test_fk_cycle_rewriter_is_exact_and_fails_closed_on_drift():
    import database

    ddl = """CREATE TABLE IF NOT EXISTS aria_policy_drafts (
    base_version_id INTEGER REFERENCES aria_policy_versions(id),
    copied_from_version_id INTEGER REFERENCES aria_policy_versions(id),
    committed_version_id INTEGER REFERENCES aria_policy_versions(id)
);"""
    rewritten = database._break_pg_fk_cycle(ddl)
    assert "REFERENCES aria_policy_versions(id)" not in rewritten

    drifted = ddl.replace(
        "copied_from_version_id INTEGER",
        "copied_from_version_id BIGINT",
    )
    with pytest.raises(RuntimeError, match="copied_from_version_id"):
        database._break_pg_fk_cycle(drifted)
