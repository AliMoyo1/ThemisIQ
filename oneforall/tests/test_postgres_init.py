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
from uuid import uuid4

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
import psycopg2.errors  # noqa: E402
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


def test_plan36_exercise_calendar_and_metrics_schema_on_real_postgres(pg):
    """Fresh PostgreSQL must create the new BCM and shared projections in FK order."""
    pg.init_db()
    present = _tables_present(pg)
    for table in (
        "bcm_exercise_readiness", "bcm_exercise_participants",
        "bcm_exercise_events", "bcm_exercise_actions",
        "capability_state_daily",
    ):
        assert table in present
    conn = pg.get_db_bypass_rls()
    try:
        rows = conn.execute(
            "SELECT table_name,column_name FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name IN "
            "('calendar_events','task_board','bcm_exercises','workflow_instances','sla_instances')"
        ).fetchall()
        columns = {(row["table_name"], row["column_name"]) for row in rows}
        assert {("calendar_events", "org_id"),
                ("calendar_events", "business_unit_id"),
                ("task_board", "reminder_key"),
                ("bcm_exercises", "report_hash"),
                ("bcm_exercises", "aar_signed_off_at"),
                ("workflow_instances", "org_id"),
                ("sla_instances", "org_id")} <= columns
    finally:
        conn.close()


def test_plan36_super_admin_target_uses_real_tenant_schema(pg):
    """A target selection must write the target schema and reject a missing schema."""
    from fastapi import HTTPException
    from modules.launcher.routes_workflows import _bind_target_org

    pg.init_db()
    db = pg.get_db_bypass_rls()
    try:
        target_id = pg.insert_returning_id(
            db,
            "INSERT INTO organizations (name,slug) VALUES ('Target schema','targetschema')",
            (),
        )
        missing_id = pg.insert_returning_id(
            db,
            "INSERT INTO organizations (name,slug) VALUES ('Missing schema','missingschema')",
            (),
        )
        db.commit()
    finally:
        db.close()
    pg.provision_tenant_schema("targetschema")

    db = pg.get_db()
    try:
        assert _bind_target_org(db, target_id, {"is_super_admin": True})
        assert db.execute("SELECT current_schema() AS name").fetchone()["name"] == "tenant_targetschema"
        pg.insert_returning_id(
            db,
            "INSERT INTO sla_definitions (name,module,entity_type) "
            "VALUES ('Target-only SLA','bcm','incident')",
            (),
        )
        db.commit()
    finally:
        db.close()

    with pg.tenant_context(target_id, "targetschema", is_super_admin=False):
        db = pg.get_db()
        try:
            assert db.execute(
                "SELECT id FROM sla_definitions WHERE name='Target-only SLA'"
            ).fetchone()
        finally:
            db.close()
    db = pg.get_db()
    try:
        assert not db.execute(
            "SELECT id FROM sla_definitions WHERE name='Target-only SLA'"
        ).fetchone()
        with pytest.raises(HTTPException) as exc:
            _bind_target_org(db, missing_id, {"is_super_admin": True})
        assert exc.value.status_code == 503
    finally:
        db.close()


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


def _column_exists(database, table: str, column: str) -> bool:
    conn = database.get_db_bypass_rls()
    try:
        row = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema=current_schema() AND table_name=%s AND column_name=%s",
            (table, column),
        ).fetchone()
        return row is not None
    finally:
        conn.close()


# ── PLAN-36 T09: extend this file with the T03/T04/F14 migrations that only
# ever ran against SQLite locally this whole plan -- init_db()'s ADD COLUMN
# IF NOT EXISTS / RLS-policy paths are PostgreSQL-only code that SQLite
# testing structurally cannot exercise at all (see this file's own opening
# docstring for the precedent: a cyclic-FK bug shipped invisibly the same
# way). ──────────────────────────────────────────────────────────────────

def test_erm_risk_library_gets_org_id_column_on_real_postgres(pg):
    """T03 (findings.md F13): erm_risk_library.org_id must exist so
    modules/erm/data_service.py's _library_can_manage tenant check has a
    real column to read on Postgres, not just SQLite."""
    pg.init_db()
    assert _column_exists(pg, "erm_risk_library", "org_id")
    assert _column_exists(pg, "erm_risk_library", "created_by")


def test_evidence_items_gets_org_id_column_and_rls_policy_on_real_postgres(pg):
    """F14 (findings.md addendum, 2026-09-30): evidence_items had no tenant
    scoping at all. Proves both halves of the fix actually apply on real
    Postgres, not just SQLite: the org_id column (app-level check in
    modules/evidence/routes.py's _scoped_evidence_item) and the RLS policy
    (core/rls.py, defense-in-depth)."""
    pg.init_db()
    assert _column_exists(pg, "evidence_items", "org_id")

    conn = pg.get_db_bypass_rls()
    try:
        policy = conn.execute(
            "SELECT polname FROM pg_policy p "
            "WHERE p.polrelid = 'public.evidence_items'::regclass "
            "AND p.polname = 'tenant_isolation'"
        ).fetchone()
        assert policy is not None, "evidence_items has no tenant_isolation RLS policy"

        forced = conn.execute(
            "SELECT relforcerowsecurity FROM pg_class "
            "WHERE oid = 'public.evidence_items'::regclass"
        ).fetchone()
        assert forced[0] is True, "evidence_items must FORCE row level security"
    finally:
        conn.close()

    # The CI DSN uses postgres, which always bypasses RLS, even when FORCE
    # is set. Exercise the policy with a disposable non-superuser role while
    # retaining the application's set_rls_context() behavior.
    setup = pg.get_db_bypass_rls()
    try:
        setup.execute(
            "INSERT INTO organizations (name, slug, plan, status) VALUES "
            "('PG RLS Org A', 'pg-rls-org-a', 'enterprise', 'active'), "
            "('PG RLS Org B', 'pg-rls-org-b', 'enterprise', 'active')"
        )
        setup.commit()
        org_a = setup.execute(
            "SELECT id FROM organizations WHERE slug='pg-rls-org-a'"
        ).fetchone()[0]
        org_b = setup.execute(
            "SELECT id FROM organizations WHERE slug='pg-rls-org-b'"
        ).fetchone()[0]
        setup.execute(
            "INSERT INTO evidence_items (title, org_id) VALUES (%s, %s)",
            ("Org A RLS Probe", org_a),
        )
        setup.commit()
    finally:
        setup.close()

    role_name = "themisiq_rls_probe_" + uuid4().hex[:12]
    role_created = False
    try:
        role_admin = _raw_conn()
        try:
            with role_admin.cursor() as cur:
                cur.execute(sql.SQL("CREATE ROLE {} NOLOGIN NOSUPERUSER NOBYPASSRLS")
                            .format(sql.Identifier(role_name)))
                role_created = True
                cur.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}")
                            .format(sql.Identifier(role_name)))
                cur.execute(sql.SQL("GRANT SELECT ON public.evidence_items TO {}")
                            .format(sql.Identifier(role_name)))
        finally:
            role_admin.close()

        def visible_for(org_id):
            raw = _raw_conn()
            try:
                scoped = pg._PgConnWrapper(raw)
                scoped.set_rls_context(org_id)
                scoped.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(role_name)))
                attrs = scoped.execute(
                    "SELECT r.rolsuper, r.rolbypassrls, "
                    "row_security_active('public.evidence_items'::regclass) AS rls_active "
                    "FROM pg_roles r WHERE r.rolname=current_user"
                ).fetchone()
                assert attrs is not None
                assert attrs["rolsuper"] is False
                assert attrs["rolbypassrls"] is False
                assert attrs["rls_active"] is True
                return scoped.execute(
                    "SELECT title FROM public.evidence_items "
                    "WHERE title='Org A RLS Probe'"
                ).fetchall()
            finally:
                # This connection was opened outside the app pool solely for
                # the probe; never return a SET ROLE session to that pool.
                raw.close()

        assert visible_for(None) == [], "RLS must fail closed without org context"
        assert visible_for(org_b) == [], (
            "org B's RLS-scoped role could read org A's evidence row"
        )
        assert len(visible_for(org_a)) == 1, (
            "positive control failed: org A's RLS-scoped role could not read its own row"
        )
    finally:
        if role_created:
            role_admin = _raw_conn()
            try:
                with role_admin.cursor() as cur:
                    cur.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name)))
                    cur.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name)))
            finally:
                role_admin.close()


def test_evidence_vault_search_and_scope_run_on_real_postgres(pg):
    """Evidence Vault Phase 1a (design/evidence-vault/PHASE-1A.md, T8): plain LIKE is case
    sensitive on PostgreSQL but the shared Vault search is not, and the shared scope and
    paged-list SQL must execute here, not only on SQLite."""
    pg.init_db()
    from modules.evidence.scope import current_library_sql, evidence_scope_sql, evidence_search_sql

    conn = pg.get_db_bypass_rls()
    try:
        conn.execute(
            "INSERT INTO organizations (name, slug, plan, status) "
            "VALUES ('PG Vault Org', 'pg-vault-org', 'enterprise', 'active')"
        )
        conn.execute("INSERT INTO business_units (name, code, is_active) VALUES ('PG Vault Unit A', 'PGVA', 1)")
        conn.execute("INSERT INTO business_units (name, code, is_active) VALUES ('PG Vault Unit B', 'PGVB', 1)")
        conn.commit()
        org = conn.execute("SELECT id FROM organizations WHERE slug='pg-vault-org'").fetchone()[0]
        bu_a = conn.execute("SELECT id FROM business_units WHERE code='PGVA'").fetchone()[0]
        bu_b = conn.execute("SELECT id FROM business_units WHERE code='PGVB'").fetchone()[0]
        for title, bu in (("Access Review Q3", None), ("100% complete", None),
                          ("Unit A policy", bu_a), ("Unit B policy", bu_b)):
            conn.execute(
                "INSERT INTO evidence_items (title, org_id, business_unit_id, status) VALUES (%s,%s,%s,'current')",
                (title, org, bu),
            )
        conn.commit()

        plain = conn.execute(
            "SELECT COUNT(*) FROM evidence_items WHERE title LIKE %s", ("%access review%",)
        ).fetchone()[0]
        assert plain == 0, "plain LIKE was expected to be case sensitive on PostgreSQL"

        def titles(user, term=""):
            scope_sql, scope_params = evidence_scope_sql(user)
            search_sql, search_params = evidence_search_sql(term)
            rows = conn.execute(
                "SELECT e.title FROM evidence_items e "
                f"WHERE {current_library_sql()} AND {scope_sql} AND {search_sql} "
                "ORDER BY e.updated_at DESC, e.id DESC LIMIT %s OFFSET %s",
                [*scope_params, *search_params, 25, 0],
            ).fetchall()
            return {r["title"] for r in rows}

        unit_a = {"org_id": org, "business_unit_id": bu_a, "is_super_admin": 0}
        assert titles(unit_a, "ACCESS review") == {"Access Review Q3"}
        assert titles(unit_a, "%") == {"100% complete"}
        assert titles(unit_a) == {"Access Review Q3", "100% complete", "Unit A policy"}
        assert titles({"org_id": None, "business_unit_id": None, "is_super_admin": 0}) == set()
        assert len(titles({"is_super_admin": 1})) == 4
    finally:
        conn.close()


def test_warm_replay_queries_execute_on_real_postgres(pg):
    """T04 (findings.md F05): scripts/warm_replay.py's queries were fixed
    for stale table/column names found on SQLite; this is the same
    every-query-executes proof tests/test_warm_replay.py already does, run
    against a real Postgres schema instead, since %s-placeholder SQL that
    is valid SQLite is not guaranteed valid Postgres."""
    pg.init_db()
    from scripts.warm_replay import _QUERIES

    conn = pg.get_db_bypass_rls()
    try:
        failures = []
        for label, query, params in _QUERIES:
            try:
                conn.execute(query, params).fetchall()
            except Exception as exc:
                failures.append(f"{label}: {exc}")
        assert not failures, "Invalid warm-replay queries on real Postgres:\n" + "\n".join(failures)
    finally:
        conn.close()


def test_global_search_ignores_case_and_treats_wildcards_literally_on_real_postgres(pg, monkeypatch):
    """The topbar search used plain LIKE, which is case sensitive on PostgreSQL but not on SQLite
    (so the suite never saw it) and let the user's own % and _ act as wildcards.
    tests/test_global_search_like.py proves the rows on SQLite with case_sensitive_like on; this runs
    the same route on real PostgreSQL, so every block's SQL executes here and the engine itself
    gives the same answer."""
    pg.init_db()
    import asyncio
    import json
    import types

    import core.middleware as middleware
    import modules.launcher.routes_platform as plat

    conn = pg.get_db_bypass_rls()
    try:
        conn.execute("INSERT INTO frameworks (name) VALUES ('PG Search Framework')")
        framework_id = conn.execute("SELECT id FROM frameworks WHERE name='PG Search Framework'").fetchone()[0]
        for statement, params in (
            ("INSERT INTO controls (framework_id, ref, name) VALUES (%s,%s,%s)",
             (framework_id, "PGS-1", "Annual Quartz Ledger control")),
            ("INSERT INTO aria_documents (doc_id, framework, title) VALUES (%s,%s,%s)",
             ("PGS-DOC-1", "ISO 27001", "Annual Quartz Ledger policy")),
            ("INSERT INTO risk_register (title) VALUES (%s)", ("Annual Quartz Ledger gap",)),
            ("INSERT INTO erm_regulatory_obligations (regulator, regulation_name, obligation) VALUES (%s,%s,%s)",
             ("Regulator", "Data Act", "File the ANNUAL QUARTZ LEDGER each year")),
        ):
            conn.execute(statement, params)
        for name in ("Acme Payroll", "Zq5% Ltd", "Zq50 Ltd", "Zq_b Ltd", "Zqxb Ltd",
                     "Zq! Ltd", "Zq Ltd", "Zq:\\temp Ltd", "Zq:temp Ltd"):
            conn.execute("INSERT INTO sentinel_vendors (name) VALUES (%s)", (name,))
        conn.commit()

        plain = conn.execute(
            "SELECT COUNT(*) FROM sentinel_vendors WHERE name LIKE %s", ("%acme%",)
        ).fetchone()[0]
        assert plain == 0, "plain LIKE was expected to be case sensitive on PostgreSQL"
    finally:
        conn.close()

    async def current_user(request):
        return request.state.user

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    admin = {"id": 1, "username": "pgsearch", "org_id": None, "business_unit_id": None,
             "is_super_admin": 1, "roles": ["super_admin"]}

    def hits(term):
        request = types.SimpleNamespace(
            state=types.SimpleNamespace(user=admin),
            url=types.SimpleNamespace(path="/api/search"),
            query_params={"q": term},
        )
        body = json.loads(asyncio.run(plat.api_global_search(request)).body)
        return {(r["type"], r["title"]) for r in body["results"]}

    for term in ("quartz ledger", "QUARTZ LEDGER", "qUaRtZ lEdGeR"):
        assert hits(term) == {
            ("control", "PGS-1 - Annual Quartz Ledger control"),
            ("document", "Annual Quartz Ledger policy"),
            ("risk", "Annual Quartz Ledger gap"),
            ("obligation", "Data Act"),
        }, term
    assert hits("zq5%") == {("vendor", "Zq5% Ltd")}
    assert hits("zq_b") == {("vendor", "Zq_b Ltd")}
    assert hits("zq!") == {("vendor", "Zq! Ltd")}
    assert hits("zq:\\temp") == {("vendor", "Zq:\\temp Ltd")}


# ── Tenant/RLS session scope must survive a rolled-back transaction ──────────
# get_db() and get_db_bypass_rls() apply the tenant search_path and the RLS
# settings with session-level SET. PostgreSQL undoes a SET together with the
# transaction it was issued in, and _PgConnWrapper.execute() rolls the whole
# transaction back on any error. A call site that catches the error and keeps
# using the same connection must still be in the same tenant and RLS scope.

def _provision_scoped_org(database, slug: str) -> int:
    """init_db(), an organizations row and a provisioned tenant schema.

    The public schema gets a decoy sla_definitions row and the tenant schema
    its own, so a connection that silently falls back to public is visible in
    the data it reads and not only in its settings."""
    database.init_db()
    setup = database.get_db_bypass_rls()
    try:
        org_id = database.insert_returning_id(
            setup,
            "INSERT INTO organizations (name,slug) VALUES (%s,%s)",
            (slug, slug),
        )
        setup.execute(
            "INSERT INTO sla_definitions (name,module,entity_type) "
            "VALUES ('public-decoy','bcm','incident')"
        )
        setup.commit()
    finally:
        setup.close()
    database.provision_tenant_schema(slug)

    with database.tenant_context(org_id, slug, is_super_admin=False):
        scoped = database.get_db()
        try:
            scoped.execute(
                "INSERT INTO sla_definitions (name,module,entity_type) "
                "VALUES ('tenant-row','bcm','incident')"
            )
            scoped.commit()
        finally:
            scoped.close()
    return org_id


def _session_scope(db) -> dict:
    """The connection's live tenant/RLS settings and its backend pid."""
    row = db.execute(
        "SELECT pg_backend_pid() AS pid, "
        "current_setting('search_path') AS search_path, "
        "current_setting('app.current_org_id', true) AS org_id, "
        "current_setting('app.is_super_admin', true) AS is_super, "
        "current_setting('app.bypass_rls', true) AS bypass"
    ).fetchone()
    return {k: row[k] for k in ("pid", "search_path", "org_id", "is_super", "bypass")}


def _sla_names(db) -> list:
    return [r["name"] for r in db.execute(
        "SELECT name FROM sla_definitions ORDER BY name"
    ).fetchall()]


def _swallow_one_failed_statement(db) -> None:
    """A statement PostgreSQL rejects, caught the way the app's
    try/except-and-continue call sites catch it."""
    with pytest.raises(psycopg2.errors.UndefinedTable):
        db.execute("SELECT 1 FROM no_such_table_for_rollback_probe")


def test_get_db_scope_survives_a_caught_failed_statement(pg):
    org_id = _provision_scoped_org(pg, "rollbackscope")
    with pg.tenant_context(org_id, "rollbackscope", is_super_admin=False):
        db = pg.get_db()
        try:
            before = _session_scope(db)
            assert before["search_path"] == "tenant_rollbackscope, public"
            assert before["org_id"] == str(org_id)
            assert (before["is_super"], before["bypass"]) == ("false", "false")
            assert _sla_names(db) == ["tenant-row"]

            _swallow_one_failed_statement(db)

            assert _session_scope(db) == before, (
                "tenant/RLS session settings were reverted by the rollback that "
                "followed a failed statement"
            )
            assert _sla_names(db) == ["tenant-row"], (
                "after the failed statement the connection read the public schema"
            )
        finally:
            db.close()


def test_get_db_scope_survives_an_explicit_rollback(pg):
    org_id = _provision_scoped_org(pg, "rollbackexplicit")
    with pg.tenant_context(org_id, "rollbackexplicit", is_super_admin=False):
        db = pg.get_db()
        try:
            before = _session_scope(db)
            _swallow_one_failed_statement(db)
            db.rollback()  # the `except: db.rollback()` call-site pattern
            assert _session_scope(db) == before
            db.rollback()  # and a rollback with nothing left to roll back
            assert _session_scope(db) == before
            assert _sla_names(db) == ["tenant-row"]
        finally:
            db.close()


def test_bypass_connection_keeps_bypass_after_a_caught_failed_statement(pg):
    pg.init_db()
    db = pg.get_db_bypass_rls()
    try:
        before = _session_scope(db)
        assert before["bypass"] == "true"
        _swallow_one_failed_statement(db)
        assert _session_scope(db) == before, (
            "a bypass connection lost app.bypass_rls after a failed statement"
        )
    finally:
        db.close()


def test_super_admin_target_scope_survives_a_caught_failed_statement(pg):
    """_bind_target_org() re-binds the schema and RLS context after get_db()
    has already returned, so the scope it sets lives in the caller's open
    transaction too."""
    from modules.launcher.routes_workflows import _bind_target_org

    target_id = _provision_scoped_org(pg, "targetscope")
    with pg.tenant_context(None, None, is_super_admin=True):
        db = pg.get_db()
        try:
            assert _bind_target_org(db, target_id, {"is_super_admin": True})
            before = _session_scope(db)
            assert before["search_path"] == "tenant_targetscope, public"
            assert before["org_id"] == str(target_id)
            assert before["is_super"] == "true"
            assert _sla_names(db) == ["tenant-row"]

            _swallow_one_failed_statement(db)

            assert _session_scope(db) == before, (
                "the super-admin target scope was reverted by a failed statement"
            )
            assert _sla_names(db) == ["tenant-row"]
        finally:
            db.close()


def test_closed_connection_returns_to_the_pool_with_clean_scope(pg):
    """Guard for close(): whatever keeps the scope alive during a request must
    not leak it to the next pool user, including after a failed statement."""
    org_id = _provision_scoped_org(pg, "cleanscope")
    with pg.tenant_context(org_id, "cleanscope", is_super_admin=False):
        db = pg.get_db()
        try:
            scoped_pid = _session_scope(db)["pid"]
            _swallow_one_failed_statement(db)
        finally:
            db.close()

    # Nothing is bound now, so get_db() applies nothing: what we read is
    # exactly what close() left behind on the pooled connection.
    again = pg.get_db()
    try:
        after = _session_scope(again)
        assert after["pid"] == scoped_pid, "pool handed back a different backend"
        assert after["search_path"] == "public"
        assert after["org_id"] == ""
        assert (after["is_super"], after["bypass"]) == ("false", "false")
    finally:
        again.close()


def _bare_session_after(pg, monkeypatch, call):
    """Run call(), then open a get_db() with no tenant or org bound.

    Returns (backend pids the pool handed out during call(), that session's
    state). The pids let the caller prove the bare session reused the
    connection under test, since a different one would make the check vacuous.
    """
    pool = pg._get_pg_pool()
    handed_out = []
    real_getconn = pool.getconn

    def spy(*args, **kwargs):
        conn = real_getconn(*args, **kwargs)
        handed_out.append(conn.get_backend_pid())
        return conn

    with monkeypatch.context() as patch:
        patch.setattr(pool, "getconn", spy)
        call()

    db = pg.get_db()
    try:
        row = db.execute(
            "SELECT pg_backend_pid() AS pid, "
            "current_setting('search_path') AS search_path, "
            "current_setting('app.bypass_rls', true) AS bypass_rls, "
            "current_setting('app.current_org_id', true) AS org_id, "
            "current_setting('app.is_super_admin', true) AS is_super"
        ).fetchone()
        return handed_out, dict(row.items())
    finally:
        db.close()


def _assert_pool_connection_is_clean(handed_out, state):
    assert state["pid"] == handed_out[0], (
        "bare get_db() did not reuse the connection under test, "
        "so this check would be vacuous"
    )
    assert state["search_path"] == "public"
    assert state["bypass_rls"] == "false"
    assert state["org_id"] == ""
    assert state["is_super"] == "false"


def test_provision_tenant_schema_returns_a_clean_connection_to_the_pool(pg, monkeypatch):
    """provision_tenant_schema() sets RLS bypass and a tenant search_path, and
    the DDL commits them, so its pooled connection must be reset before putconn().
    The lane's user is a superuser, so assert on the settings, not on RLS rows."""
    pg.init_db()
    handed_out, state = _bare_session_after(
        pg, monkeypatch, lambda: pg.provision_tenant_schema("contamorg")
    )
    _assert_pool_connection_is_clean(handed_out, state)


def test_migrate_all_tenant_schemas_returns_a_clean_connection_to_the_pool(pg, monkeypatch):
    """Same contract for the startup migration. It only commits its SETs when
    there is a tenant schema to walk, so provision one first."""
    pg.init_db()
    pg.provision_tenant_schema("contamorg")
    pg.get_db().close()  # reset whatever provisioning left, so only the migration is measured
    handed_out, state = _bare_session_after(
        pg, monkeypatch, pg._migrate_all_tenant_schemas
    )
    _assert_pool_connection_is_clean(handed_out, state)


# ── Savepoints must survive a failed statement (PLAN_pg_savepoint_wrapper_fix.md) ──
# _PgConnWrapper.execute() rolls the whole transaction back on any error. That
# destroyed every open SAVEPOINT too, so the ROLLBACK TO SAVEPOINT in the two
# call sites that use them (readiness rules, saved-view bulk actions) raised
# InvalidSavepointSpecification and all earlier uncommitted work was lost.

def _insert_org(database, slug: str) -> int:
    setup = database.get_db_bypass_rls()
    try:
        org_id = database.insert_returning_id(
            setup, "INSERT INTO organizations (name,slug) VALUES (%s,%s)", (slug, slug)
        )
        setup.commit()
        return org_id
    finally:
        setup.close()


def _setting(database, key: str):
    check = database.get_db_bypass_rls()
    try:
        row = check.execute("SELECT value FROM settings WHERE key=%s", (key,)).fetchone()
        return row["value"] if row else None
    finally:
        check.close()


def test_a_failed_statement_inside_a_savepoint_keeps_the_work_before_it(pg):
    pg.init_db()
    db = pg.get_db_bypass_rls()
    try:
        db.execute("INSERT INTO settings (key, value) VALUES ('sp_before', 'kept')")
        db.execute("SAVEPOINT probe")
        db.execute("INSERT INTO settings (key, value) VALUES ('sp_inside', 'undone')")
        _swallow_one_failed_statement(db)
        db.execute("ROLLBACK TO SAVEPOINT probe")
        db.execute("RELEASE SAVEPOINT probe")
        db.commit()
    finally:
        db.close()
    assert _setting(pg, "sp_before") == "kept"
    assert _setting(pg, "sp_inside") is None


def test_a_failed_statement_without_a_savepoint_still_rolls_the_transaction_back(pg):
    pg.init_db()
    db = pg.get_db_bypass_rls()
    try:
        db.execute("INSERT INTO settings (key, value) VALUES ('sp_none', 'lost')")
        _swallow_one_failed_statement(db)
        db.execute("SELECT 1")  # usable again without a manual rollback
        db.commit()
    finally:
        db.close()
    assert _setting(pg, "sp_none") is None


def test_an_outer_rollback_to_savepoint_discards_the_inner_one_and_a_bad_one_is_unrecoverable(pg):
    pg.init_db()
    db = pg.get_db_bypass_rls()
    try:
        db.execute("INSERT INTO settings (key, value) VALUES ('sp_nested_base', 'lost')")
        db.execute("SAVEPOINT outer_sp")
        db.execute("SAVEPOINT inner_sp")
        db.execute("ROLLBACK TO SAVEPOINT outer_sp")  # also destroys inner_sp
        with pytest.raises(psycopg2.errors.InvalidSavepointSpecification):
            db.execute("ROLLBACK TO SAVEPOINT inner_sp")
        # A savepoint statement that itself fails cannot be recovered from: the
        # wrapper must have rolled everything back so the connection is usable.
        db.execute("SELECT 1")
        db.commit()
    finally:
        db.close()
    assert _setting(pg, "sp_nested_base") is None


def test_scope_survives_a_failed_statement_inside_a_savepoint(pg):
    org_id = _provision_scoped_org(pg, "spscope")
    with pg.tenant_context(org_id, "spscope", is_super_admin=False):
        db = pg.get_db()
        try:
            before = _session_scope(db)
            db.execute("SAVEPOINT scope_probe")
            _swallow_one_failed_statement(db)
            db.execute("ROLLBACK TO SAVEPOINT scope_probe")
            db.execute("RELEASE SAVEPOINT scope_probe")
            assert _session_scope(db) == before
            assert _sla_names(db) == ["tenant-row"]
        finally:
            db.close()


def test_readiness_run_keeps_earlier_findings_when_a_later_rule_fails(pg, monkeypatch):
    from modules.readiness import data_service as readiness

    pg.init_db()
    org_id = _insert_org(pg, "readinessorg")
    readiness._ensure_rules_imported()

    def good_rule(db, org):
        return [readiness.RawFinding(
            rule_code="good_rule", severity="low", module="platform",
            entity_type="probe", entity_id="1", message="written before the failure")]

    def bad_rule(db, org):
        db.execute("SELECT 1 FROM no_such_table_for_readiness_probe")
        return []

    monkeypatch.setattr(readiness, "_RULES", {"good_rule": good_rule, "bad_rule": bad_rule})
    monkeypatch.setattr(readiness, "_RULE_MODULES", {})
    db = pg.get_db_bypass_rls()
    try:
        counts = readiness.run_rules_for_org(db, org_id)
    finally:
        db.close()

    assert counts["failed_rules"] == ["bad_rule"]
    assert counts["new"] == 1
    check = pg.get_db_bypass_rls()
    try:
        rows = check.execute(
            "SELECT rule_code FROM readiness_findings WHERE org_id=%s", (org_id,)
        ).fetchall()
        assert [r["rule_code"] for r in rows] == ["good_rule"]
    finally:
        check.close()


def test_bulk_action_applies_the_other_ids_when_one_fails(pg):
    from modules.saved_views.data_service import execute_bulk_action

    pg.init_db()
    org_id = _insert_org(pg, "bulkorg")
    setup = pg.get_db_bypass_rls()
    try:
        user_id = pg.insert_returning_id(
            setup,
            "INSERT INTO users (username,email,full_name,password_hash,org_id) VALUES (%s,%s,%s,%s,%s)",
            ("bulkuser", "bulkuser@example.test", "Bulk User", "x", org_id),
        )
        setup.commit()
    finally:
        setup.close()
    actor = {"id": user_id, "username": "bulkuser", "org_id": org_id}

    def authorize(db, who, rid):
        return True, None

    def apply(db, who, rid):
        db.execute("INSERT INTO settings (key, value) VALUES (%s, 'applied')", (f"bulk_probe_{rid}",))
        if rid == 2:
            db.execute("SELECT 1 FROM no_such_table_for_bulk_probe")

    db = pg.get_db_bypass_rls()
    try:
        result = execute_bulk_action(
            db, actor, module="probe", action_name="apply", record_ids=[1, 2, 3],
            authorize_fn=authorize, execute_fn=apply,
        )
    finally:
        db.close()

    assert result["applied"] == [1, 3]
    assert [item["id"] for item in result["skipped"]] == [2]
    assert _setting(pg, "bulk_probe_1") == "applied"
    assert _setting(pg, "bulk_probe_2") is None
    assert _setting(pg, "bulk_probe_3") == "applied"


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


# ── Ask ARIA index tenancy on real PostgreSQL ────────────────────────────────
# SQLite cannot model what the ask index depends on here: an unqualified table
# name resolving through search_path to the shared public schema, and the
# ALTER TABLE upgrade of an existing PostgreSQL table. The same scoping rules
# are covered on FTS5 by test_aria_ask_scoping.py.

_PRE_SCOPING_ASK_INDEX_DDL = """CREATE TABLE public.aria_ask_index (
    id           SERIAL PRIMARY KEY,
    content_type TEXT NOT NULL DEFAULT '',
    content_id   TEXT NOT NULL DEFAULT '',
    title        TEXT NOT NULL DEFAULT '',
    section      TEXT NOT NULL DEFAULT '',
    body         TEXT NOT NULL DEFAULT '',
    owner        TEXT NOT NULL DEFAULT '',
    framework    TEXT NOT NULL DEFAULT '',
    control_ref  TEXT NOT NULL DEFAULT '',
    url_path     TEXT NOT NULL DEFAULT '',
    body_tsv     tsvector GENERATED ALWAYS AS (
        setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
        setweight(to_tsvector('english', coalesce(section, '')), 'B') ||
        setweight(to_tsvector('english', coalesce(body, '')), 'C')
    ) STORED
)"""


def _make_org(database, slug, provision=True):
    """An organizations row, plus its tenant schema unless provision=False
    (such an org lives in the public schema). Returns the org id."""
    db = database.get_db_bypass_rls()
    try:
        org_id = database.insert_returning_id(
            db,
            "INSERT INTO organizations (name, slug, plan, status) "
            "VALUES (%s, %s, 'enterprise', 'active')",
            (slug, slug),
        )
        db.commit()
    finally:
        db.close()
    if provision:
        database.provision_tenant_schema(slug)
    return org_id


def _raw_rows(sql_text, params=None):
    """Rows over a raw autocommit connection: independent of the app pool and
    of any search_path, so every query names its schema."""
    conn = _raw_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(sql_text, params)
            return cur.fetchall()
    finally:
        conn.close()


def _add_aria_document(database, doc_id, org_id, body, business_unit_id=None, framework="ISO 27001"):
    db = database.get_db()
    try:
        db.execute(
            "INSERT INTO aria_documents (doc_id, framework, title, body, org_id, "
            "business_unit_id, policy_workflow_managed, status, owner) "
            "VALUES (%s, %s, %s, %s, %s, %s, 0, 'Approved', 'owner')",
            (doc_id, framework, f"Title {doc_id}", body, org_id, business_unit_id),
        )
        db.commit()
    finally:
        db.close()


def _ask_with_stub_model(question, user, monkeypatch):
    """ask() with the AI call replaced. Returns everything sent to the model."""
    import asyncio
    import json
    from modules.aria import ask_service

    sent = []

    async def fake_call_ai(system, user_msg, max_tokens=4000, messages=None):
        sent.append(f"{system}\n{user_msg}\n{json.dumps(messages)}")
        return "Stub answer.", {}

    monkeypatch.setattr(ask_service, "_call_ai", fake_call_ai)
    asyncio.run(ask_service.ask(question, user=user))
    return "\n".join(sent)


def test_ask_index_write_from_a_tenant_stays_in_its_own_schema_on_real_postgres(pg, monkeypatch):
    """A tenant with no aria_ask_index of its own used to resolve the
    unqualified name through search_path to public.aria_ask_index. The
    publication worker's reindex_document then deleted the default org's chunk
    for the same DOC id and wrote the tenant's policy text into the default
    org's index. Ids come from per-schema sequences (both start at DOC-0001),
    so the default org's document post-filter accepted the foreign chunk."""
    from modules.aria import ask_service

    pg.init_db()
    default_org = _make_org(pg, "askdefault", provision=False)
    tenant_org = _make_org(pg, "asktenant")

    def as_default_org():
        # The default org runs against the public schema under slug 'public'.
        return pg.tenant_context(default_org, "public", is_super_admin=False)

    with as_default_org():
        ask_service.init_index()  # public.aria_ask_index exists, as it does once the default org uses Ask
        _add_aria_document(pg, "DOC-0001", default_org, "public handbook quarterly report")
        ask_service.reindex_document("DOC-0001")
    with pg.tenant_context(tenant_org, "asktenant", is_super_admin=False):
        _add_aria_document(pg, "DOC-0001", tenant_org, "TENANTSECRET quarterly revenue forecast")
        ask_service.reindex_document("DOC-0001")  # the publication worker's call

    asker = {"id": 1, "org_id": default_org, "business_unit_id": None, "is_super_admin": False}
    with as_default_org():
        sent = _ask_with_stub_model("quarterly", asker, monkeypatch)
    assert "public handbook" in sent, "the default org must still reach its own document"
    assert "TENANTSECRET" not in sent

    assert _raw_rows("SELECT to_regclass('tenant_asktenant.aria_ask_index') IS NOT NULL")[0][0]
    assert _raw_rows(
        "SELECT count(*) FROM public.aria_ask_index WHERE body LIKE %s", ("%TENANTSECRET%",)
    )[0][0] == 0
    assert _raw_rows(
        "SELECT count(*) FROM tenant_asktenant.aria_ask_index WHERE body LIKE %s", ("%TENANTSECRET%",)
    )[0][0] == 1


def test_pre_scoping_ask_index_is_upgraded_in_place_on_real_postgres(pg):
    from modules.aria import ask_service

    pg.init_db()
    org_id = _make_org(pg, "askupgrade", provision=False)
    db = pg.get_db_bypass_rls()
    try:
        bu_id = pg.insert_returning_id(
            db, "INSERT INTO public.business_units (name, is_active) VALUES ('Finance', 1)", ()
        )
        db.execute(
            "INSERT INTO public.aria_documents (doc_id, framework, title, body, org_id, "
            "business_unit_id, policy_workflow_managed, status, owner) "
            "VALUES ('DOC-0001', 'ISO 27001', 'T', 'b', %s, %s, 0, 'Approved', 'o')",
            (org_id, bu_id),
        )
        db.execute(_PRE_SCOPING_ASK_INDEX_DDL)
        db.execute(
            "INSERT INTO public.aria_ask_index (content_type, content_id, title, body) "
            "VALUES ('document', 'DOC-0001', 'T', 'document chunk')"
        )
        db.execute(
            "INSERT INTO public.aria_ask_index (content_type, content_id, title, body) "
            "VALUES ('risk', 'RISK-0001', 'R', 'risk chunk')"
        )
        db.commit()
    finally:
        db.close()

    with pg.tenant_context(org_id, "public", is_super_admin=False):  # how default-org users run
        ask_service.init_index()
        ask_service.init_index()  # idempotent once upgraded

    rows = _raw_rows(
        "SELECT content_type, content_id, org_id, business_unit_id "
        "FROM public.aria_ask_index ORDER BY id"
    )
    assert rows == [
        ("document", "DOC-0001", org_id, bu_id),  # existing rows kept, document scope backfilled
        ("risk", "RISK-0001", None, None),        # no source owner: stays unscoped until a rebuild
    ]


def test_ask_search_filters_in_sql_before_the_top_k_cut_on_real_postgres(pg):
    from modules.aria import ask_service

    pg.init_db()
    org_x = _make_org(pg, "asksearchx", provision=False)
    org_y = _make_org(pg, "asksearchy", provision=False)
    asker = {"id": 1, "org_id": org_y, "business_unit_id": None, "is_super_admin": False}

    with pg.tenant_context(org_y, "public", is_super_admin=False):  # both orgs share the public schema
        ask_service.init_index()
        db = pg.get_db()
        try:
            other_bu = pg.insert_returning_id(
                db, "INSERT INTO business_units (name, is_active) VALUES ('Elsewhere', 1)", ()
            )
            db.commit()
        finally:
            db.close()

        for i in range(10):
            _add_aria_document(pg, f"DOC-X{i:02d}", org_x, "backup backup backup backup restore backup")
        _add_aria_document(
            pg, "DOC-Y1", org_y,
            "annual training onboarding travel visitors parking catering and once backup procedures",
        )
        _add_aria_document(pg, "DOC-Y2", org_y, "backup procedures for another unit", business_unit_id=other_bu)
        for doc_id in [f"DOC-X{i:02d}" for i in range(10)] + ["DOC-Y1", "DOC-Y2"]:
            ask_service.reindex_document(doc_id)

        # Precondition: unscoped, org X's documents fill the top 8 and org Y's is cut.
        unscoped = _raw_rows(
            "SELECT content_id FROM public.aria_ask_index "
            "WHERE body_tsv @@ to_tsquery('english', 'backup:*') "
            "ORDER BY ts_rank_cd(body_tsv, to_tsquery('english', 'backup:*')) DESC LIMIT 8"
        )
        assert "DOC-Y1" not in {r[0] for r in unscoped}

        # A user with no business unit sees org Y's organization-wide document only:
        # not org X's, and not org Y's document in a unit outside their scope.
        assert [c["content_id"] for c in ask_service.search("backup", user=asker)] == ["DOC-Y1"]
        # The framework-filtered query finds nothing, so the unfiltered fallback runs
        # (second query against the real server); it must stay scoped.
        widened = ask_service.search("backup", framework_filter="SOC 2", user=asker)
        assert [c["content_id"] for c in widened] == ["DOC-Y1"]


def test_rebuild_all_in_a_tenant_stamps_controls_and_risks_with_it_on_real_postgres(pg):
    from modules.aria import ask_service

    pg.init_db()
    org_id = _make_org(pg, "askrebuild")
    with pg.tenant_context(org_id, "askrebuild", is_super_admin=False):
        db = pg.get_db()
        try:
            fw_id = pg.insert_returning_id(
                db, "INSERT INTO frameworks (name) VALUES ('Ask rebuild framework')", ()
            )
            db.execute(
                "INSERT INTO controls (framework_id, ref, name, description, category, owner) "
                "VALUES (%s, 'ASK.1', 'Recovery drills', 'Quarterly drills', 'Resilience', 'owner')",
                (fw_id,),
            )
            db.execute(
                "INSERT INTO aria_risks (risk_id, framework, description, category, owner, "
                "mitigation, status) VALUES ('RISK-0001', 'ISO 27001', 'Ransomware exposure', "
                "'Cyber', 'owner', 'Offline backups', 'Open')"
            )
            db.commit()
        finally:
            db.close()
        assert ask_service.rebuild_all() >= 2

    rows = _raw_rows(
        "SELECT content_type, org_id FROM tenant_askrebuild.aria_ask_index "
        "WHERE control_ref = 'ASK.1' OR content_id = 'RISK-0001' ORDER BY content_type"
    )
    assert rows == [("control", org_id), ("risk", org_id)]


def test_rebuild_ask_index_script_rebuilds_the_chosen_tenant_on_real_postgres(pg, capsys):
    from scripts import rebuild_ask_index

    pg.init_db()
    org_id = _make_org(pg, "askscript")
    with pg.tenant_context(org_id, "askscript", is_super_admin=False):
        db = pg.get_db()
        try:
            db.execute(
                "INSERT INTO aria_risks (risk_id, framework, description, category, owner, "
                "mitigation, status) VALUES ('RISK-0001', 'ISO 27001', 'Ransomware exposure', "
                "'Cyber', 'owner', 'Offline backups', 'Open')"
            )
            db.commit()
        finally:
            db.close()

    assert rebuild_ask_index.main(["--slug", "askscript"]) == 0
    assert capsys.readouterr().out.startswith("askscript: ")
    assert _raw_rows(
        "SELECT org_id FROM tenant_askscript.aria_ask_index WHERE content_id = 'RISK-0001'"
    ) == [(org_id,)]
    assert rebuild_ask_index.main(["--slug", "no-such-org"]) == 2


def test_rebuild_index_from_a_tenant_never_drops_the_shared_public_index_on_real_postgres(pg):
    """DROP TABLE aria_ask_index resolves through search_path, so a tenant with no table of its
    own used to drop the default organization's index from public."""
    from modules.aria import ask_service

    pg.init_db()
    default_org = _make_org(pg, "dropdefault", provision=False)
    tenant_org = _make_org(pg, "droptenant")
    with pg.tenant_context(default_org, "public", is_super_admin=False):
        ask_service.init_index()
    with pg.tenant_context(tenant_org, "droptenant", is_super_admin=False):
        ask_service.rebuild_index()
    assert _raw_rows(
        "SELECT to_regclass('public.aria_ask_index') IS NOT NULL, "
        "to_regclass('tenant_droptenant.aria_ask_index') IS NOT NULL"
    )[0] == (True, True)


def test_deleting_an_org_user_survives_a_table_missing_from_its_cleanup_on_real_postgres(pg, monkeypatch):
    """The user-deletion cleanup skips tables it cannot update. On PostgreSQL a skipped statement rolled
    the whole transaction back, undoing the reassignments made before it, and the final DELETE then hit
    a foreign key (events.created_by). Each optional step now runs in its own savepoint."""
    import asyncio
    import json
    import types

    import modules.launcher.routes_super_admin as super_admin

    pg.init_db()
    org_id = _make_org(pg, "deluser", provision=False)
    conn = pg.get_db_bypass_rls()
    try:
        uid = pg.insert_returning_id(
            conn,
            "INSERT INTO users (username, email, full_name, password_hash, org_id) "
            "VALUES ('doomed', 'doomed@example.test', 'Doomed', 'x', %s)",
            (org_id,),
        )
        event = pg.insert_returning_id(
            conn,
            "INSERT INTO events (event_type, source_module, created_by) VALUES ('test.event', 'platform', %s)",
            (uid,),
        )  # events.created_by has a plain foreign key: the delete is blocked until it is reassigned
        conn.execute("DROP TABLE IF EXISTS grid_share_links CASCADE")  # a schema that predates this table
        conn.commit()
    finally:
        conn.close()

    root = {"id": 0, "username": "root", "org_id": None, "business_unit_id": None, "is_super_admin": 1,
            "roles": ["super_admin"]}

    async def current_user(request):
        return root

    monkeypatch.setattr(super_admin, "get_current_user", current_user)
    request = types.SimpleNamespace(state=types.SimpleNamespace(user=root),
                                    url=types.SimpleNamespace(path="/x"), query_params={})
    response = asyncio.run(super_admin.delete_org_user(request, org_id, uid))

    assert response.status_code == 200 and json.loads(response.body) == {"ok": True}
    assert _raw_rows("SELECT count(*) FROM users WHERE id = %s", (uid,))[0][0] == 0
    assert _raw_rows("SELECT created_by FROM events WHERE id = %s", (event,)) == [(None,)]


def test_scoped_search_and_related_items_run_on_real_postgres(pg, monkeypatch):
    """The scope SQL (business unit lists, the grid audit subquery, the ARIA and Vault rules) must
    parse and give the right rows on PostgreSQL, where the plain SQLite suite cannot show it:
    a unit A user sees unit A and organization wide records, never unit B's, in topbar search and in
    Related Items, and cannot link to a record they cannot open."""
    import asyncio
    import json
    import types

    import core.middleware as middleware
    import modules.launcher.routes_platform as plat

    pg.init_db()
    org_id = _make_org(pg, "scopeorg", provision=False)
    conn = pg.get_db_bypass_rls()
    try:
        unit = {
            tag: pg.insert_returning_id(
                conn, "INSERT INTO business_units (name, is_active) VALUES (%s, 1)", (f"PG Unit {tag}",)
            )
            for tag in ("A", "B")
        }
        user_ids = {
            name: pg.insert_returning_id(
                conn,
                "INSERT INTO users (username, email, full_name, password_hash, org_id, business_unit_id) "
                "VALUES (%s, %s, %s, 'x', %s, %s)",
                (name, f"{name}@example.test", name, org_id, unit["A"]),
            )
            for name in ("scope_dpo", "scope_audit_lead")
        }
        rows = {}
        for tag in ("A", "B"):
            audit = pg.insert_returning_id(
                conn, "INSERT INTO grid_audits (name, business_unit_id) VALUES (%s, %s)", (f"Scope audit {tag}", unit[tag])
            )
            rows["breach", tag] = pg.insert_returning_id(
                conn,
                "INSERT INTO sentinel_breaches (ref_number, title, business_unit_id) VALUES (%s, %s, %s)",
                (f"BR-{tag}", f"Scope probe breach {tag}", unit[tag]),
            )
            rows["nc", tag] = pg.insert_returning_id(
                conn, "INSERT INTO grid_non_conformances (audit_id, title) VALUES (%s, %s)",
                (audit, f"Scope probe nc {tag}"),
            )
            rows["doc", tag] = pg.insert_returning_id(
                conn,
                "INSERT INTO aria_documents (doc_id, framework, title, org_id, business_unit_id, "
                "policy_workflow_managed) VALUES (%s, 'ISO 27001', %s, %s, %s, 0)",
                (f"SCOPE-{tag}", f"Scope probe policy {tag}", org_id, unit[tag]),
            )
            rows["evidence", tag] = pg.insert_returning_id(
                conn,
                "INSERT INTO evidence_items (title, org_id, business_unit_id, status) VALUES (%s, %s, %s, 'current')",
                (f"Scope probe evidence {tag}", org_id, unit[tag]),
            )
        anchor = pg.insert_returning_id(conn, "INSERT INTO erm_enterprise_risks (title) VALUES ('Scope probe anchor risk')", ())
        fresh_breach = pg.insert_returning_id(
            conn,
            "INSERT INTO sentinel_breaches (ref_number, title, business_unit_id) VALUES ('BR-A2', 'Scope probe breach A2', %s)",
            (unit["A"],),
        )
        for kind, module, entity in (("breach", "sentinel", "breach"), ("nc", "grid", "nc"), ("doc", "aria", "document"),
                                     ("evidence", "evidence", "item")):
            for tag in ("A", "B"):
                conn.execute(
                    "INSERT INTO cross_module_links (source_module, source_type, source_id, target_module, "
                    "target_type, target_id) VALUES ('erm', 'risk', %s, %s, %s, %s)",
                    (anchor, module, entity, rows[kind, tag]),
                )
        conn.commit()
    finally:
        conn.close()

    async def current_user(request):
        return request.state.user

    monkeypatch.setattr(middleware, "get_current_user", current_user)

    def persona(name, role):
        return {"id": user_ids[name], "username": name, "org_id": org_id, "business_unit_id": unit["A"],
                "is_super_admin": 0, "roles": [role]}

    dpo, lead = persona("scope_dpo", "dpo"), persona("scope_audit_lead", "audit_lead")

    def request(user, query=None, payload=None):
        req = types.SimpleNamespace(state=types.SimpleNamespace(user=user), url=types.SimpleNamespace(path="/x"),
                                    query_params=query or {})
        if payload is not None:
            async def _json():
                return payload

            req.json = _json
        return req

    def call(coro):
        response = asyncio.run(coro)
        return response.status_code, json.loads(response.body)

    _, body = call(plat.api_global_search(request(dpo, {"q": "Scope probe"})))
    titles = {r["title"] for r in body["results"]}
    assert {"Scope probe breach A", "Scope probe policy A", "Scope probe evidence A"} <= titles
    assert not {t for t in titles if t.endswith(" B")}, titles

    _, related = call(plat.api_links_get(request(dpo), "erm", "risk", anchor))
    assert {r["title"] for r in related} == {
        "Scope probe breach A", "Scope probe policy A", "Scope probe evidence A"}
    _, related = call(plat.api_links_get(request(lead), "erm", "risk", anchor))
    assert {r["title"] for r in related} == {"Scope probe nc A", "Scope probe policy A", "Scope probe evidence A"}

    def link_to(user, breach_id):
        return call(plat.api_links_create(request(user, payload={
            "source_module": "erm", "source_type": "risk", "source_id": anchor,
            "target_module": "sentinel", "target_type": "breach", "target_id": breach_id,
            "relationship": "related"})))

    assert link_to(dpo, rows["breach", "B"]) == link_to(dpo, 987654)  # unreachable looks exactly like missing
    assert link_to(dpo, rows["breach", "B"])[0] == 404
    status, made = link_to(dpo, fresh_breach)
    assert status == 201 and made["ok"]
    assert _raw_rows("SELECT user_id, entity_id FROM audit_log WHERE action = 'link_create'") == [
        (user_ids["scope_dpo"], made["link_id"])]


def test_ask_page_count_reads_the_tenants_own_index_on_real_postgres(pg):
    from modules.aria import ask_service

    pg.init_db()
    default_org = _make_org(pg, "countdefault", provision=False)
    tenant_org = _make_org(pg, "counttenant")
    with pg.tenant_context(default_org, "public", is_super_admin=False):
        ask_service.init_index()
        _add_aria_document(pg, "DOC-0001", default_org, "public handbook quarterly report")
        ask_service.reindex_document("DOC-0001")
        default_user = {"org_id": default_org, "business_unit_id": None, "is_super_admin": False}
        assert ask_service.indexed_count(default_user) == 1
    with pg.tenant_context(tenant_org, "counttenant", is_super_admin=False):
        tenant_user = {"org_id": tenant_org, "business_unit_id": None, "is_super_admin": False}
        assert ask_service.indexed_count(tenant_user) == 0, "its own empty index, not the default org's"
    assert _raw_rows("SELECT to_regclass('tenant_counttenant.aria_ask_index') IS NOT NULL")[0][0]


def test_module_list_searches_ignore_case_on_real_postgres(pg, monkeypatch):
    """PostgreSQL's LIKE is case sensitive; these searches used it (finding H3 of the PG audit)."""
    import asyncio
    import json
    import types

    import modules.bcm.data_service as bcm_ds
    import modules.erm.data_service as erm_ds
    import modules.launcher.routes_admin as admin_routes
    import modules.sentinel.data_service as sentinel_ds
    import core.middleware as middleware

    pg.init_db()
    conn = pg.get_db_bypass_rls()
    try:
        ropa = pg.insert_returning_id(
            conn, "INSERT INTO sentinel_ropa (ref_number, processing_name) VALUES ('R-1', 'Quartz Ledger Payroll')", ())
        pg.insert_returning_id(
            conn, "INSERT INTO sentinel_ropa (ref_number, processing_name) VALUES ('R-2', 'Quartz 50 Ledger')", ())
        statement = pg.insert_returning_id(
            conn,
            "INSERT INTO erm_risk_statements (category, cause, event, consequence, tags) "
            "VALUES ('Cyber', 'c', 'e', 'q', 'Cyber,Ransomware')", ())
        doc = pg.insert_returning_id(conn, "INSERT INTO bcm_documents (title) VALUES ('Plan')", ())
        chunk = pg.insert_returning_id(
            conn,
            "INSERT INTO bcm_document_chunks (document_id, chunk_index, content) VALUES (%s, 0, 'Quartz recovery steps')",
            (doc,))
        log_id = pg.insert_returning_id(
            conn,
            "INSERT INTO audit_log (username, action, module) VALUES ('Alice.Smith', 'Exported Quartz Report', 'platform')",
            ())
        conn.commit()
    finally:
        conn.close()

    assert [r["id"] for r in sentinel_ds.list_ropa(search="QUARTZ 5% ledger")] == []
    assert [r["id"] for r in sentinel_ds.list_ropa(search="quartz ledger")] == [ropa]
    assert [r["id"] for r in erm_ds.list_statements(tags="ransomware")] == [statement]
    assert [r["id"] for r in bcm_ds.search_chunks(["QUARTZ", "Recovery"])] == [chunk]

    root = {"id": 0, "username": "root", "org_id": None, "business_unit_id": None, "is_super_admin": 1,
            "roles": ["super_admin"]}

    async def current_user(request):
        return root

    monkeypatch.setattr(middleware, "get_current_user", current_user)
    for query in ({"action": "quartz report"}, {"user": "alice.smith"}):
        request = types.SimpleNamespace(state=types.SimpleNamespace(user=root), url=types.SimpleNamespace(path="/x"),
                                        query_params=query)
        body = json.loads(asyncio.run(admin_routes.admin_api_logs(request)).body)
        assert [row["id"] for row in body["logs"]] == [log_id], query


def test_vault_rescoring_and_grid_reattach_run_on_real_postgres(pg):
    import modules.evidence.routes as vault
    import modules.governance.effectiveness as eff
    import modules.grid.data_service as grid_ds

    pg.init_db()
    conn = pg.get_db_bypass_rls()
    try:
        control = pg.insert_returning_id(conn, "INSERT INTO canonical_controls (title) VALUES ('PG scored control')", ())
        item = pg.insert_returning_id(conn, "INSERT INTO evidence_items (title, status) VALUES ('PG proof', 'current')", ())
        link = pg.insert_returning_id(
            conn,
            "INSERT INTO evidence_links (evidence_id, module, entity_type, entity_id) "
            "VALUES (%s, 'grid', 'canonical_control', %s)", (item, control))
        audit = pg.insert_returning_id(conn, "INSERT INTO grid_audits (name) VALUES ('PG attach audit')", ())
        grid_control = pg.insert_returning_id(
            conn, "INSERT INTO grid_controls (audit_id, name) VALUES (%s, 'PG attach control')", (audit,))
        eff.recompute_controls_by_ids(conn, [control])
        conn.commit()
        assert eff.get_control_score(conn, control)["score"] == 45
        conn.execute("UPDATE evidence_links SET deleted_at = CURRENT_TIMESTAMP WHERE id = %s", (link,))
        conn.commit()
    finally:
        conn.close()

    vault._rescore_controls([control])  # a fresh connection, after the change committed
    assert _raw_rows("SELECT score FROM control_effectiveness_scores WHERE control_id = %s", (control,)) == [(10,)]

    first = grid_ds.attach_vault_item_to_grid_control(grid_control, item, None)
    conn = pg.get_db_bypass_rls()
    try:
        conn.execute(
            "UPDATE evidence_links SET deleted_at = CURRENT_TIMESTAMP WHERE module = 'grid' AND entity_type = 'control'")
        conn.commit()
    finally:
        conn.close()
    assert grid_ds.attach_vault_item_to_grid_control(grid_control, item, None) == first
    assert _raw_rows(
        "SELECT count(*) FILTER (WHERE deleted_at IS NULL), count(*) FROM evidence_links "
        "WHERE module = 'grid' AND entity_type = 'control' AND entity_id = %s", (grid_control,)) == [(1, 2)]


# ── Row level security with a role that is NOT a superuser ───────────────────
# The lane connects as a superuser, and a superuser bypasses RLS, so every other test here can only
# check session settings. These switch the session to an ordinary role (SET ROLE) so the policies in
# core/rls.py really filter rows.

_RLS_PROBE_ROLE = "themisiq_rls_probe"


def _rls_probe_world(pg):
    """Two organizations with one evidence item each, plus the restricted role. Returns the org ids."""
    pg.init_db()  # installs the policies
    org_a = _make_org(pg, "rlsorga", provision=False)
    org_b = _make_org(pg, "rlsorgb", provision=False)
    admin = pg.get_db_bypass_rls()
    try:
        for org_id, label in ((org_a, "A"), (org_b, "B")):
            admin.execute(
                "INSERT INTO evidence_items (title, org_id, status) VALUES (%s, %s, 'current')",
                (f"RLS item {label}", org_id),
            )
        admin.execute(
            "DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '" + _RLS_PROBE_ROLE + "') THEN "
            "CREATE ROLE " + _RLS_PROBE_ROLE + " NOLOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$"
        )
        admin.execute("GRANT USAGE ON SCHEMA public TO " + _RLS_PROBE_ROLE)
        admin.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO " + _RLS_PROBE_ROLE)
        admin.execute("GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO " + _RLS_PROBE_ROLE)
        admin.commit()
    finally:
        admin.close()
    return org_a, org_b


def _become_restricted(db):
    """SET ROLE is transactional like every SET, so commit it: a later rollback must not undo it."""
    db.execute("SET ROLE " + _RLS_PROBE_ROLE)
    db.commit()


def _release_role(db):
    db.execute("RESET ROLE")
    db.commit()
    db.close()


def _visible_titles(db):
    return {r["title"] for r in db.execute("SELECT title FROM evidence_items").fetchall()}


def test_rls_policies_filter_rows_by_organization_for_an_ordinary_role_on_real_postgres(pg):
    org_a, org_b = _rls_probe_world(pg)

    for org, expected in ((org_a, {"RLS item A"}), (org_b, {"RLS item B"})):
        with pg.tenant_context(org, "public", is_super_admin=False):
            db = pg.get_db()
            try:
                _become_restricted(db)
                assert _visible_titles(db) == expected
                assert db.execute("SELECT current_setting('is_superuser')").fetchone()[0] == "off"
            finally:
                _release_role(db)

    with pg.tenant_context(org_a, "public", is_super_admin=True):  # the super admin flag opens every row
        db = pg.get_db()
        try:
            _become_restricted(db)
            assert _visible_titles(db) == {"RLS item A", "RLS item B"}
        finally:
            _release_role(db)

    db = pg.get_db_bypass_rls()  # authentication and provisioning
    try:
        _become_restricted(db)
        assert _visible_titles(db) == {"RLS item A", "RLS item B"}
    finally:
        _release_role(db)


def test_rls_rejects_a_write_for_another_organization_on_real_postgres(pg):
    org_a, org_b = _rls_probe_world(pg)
    with pg.tenant_context(org_a, "public", is_super_admin=False):
        db = pg.get_db()
        try:
            _become_restricted(db)
            db.execute("INSERT INTO evidence_items (title, org_id, status) VALUES ('mine', %s, 'current')", (org_a,))
            db.commit()
            with pytest.raises(psycopg2.errors.InsufficientPrivilege):
                db.execute(
                    "INSERT INTO evidence_items (title, org_id, status) VALUES ('theirs', %s, 'current')", (org_b,)
                )
            assert _visible_titles(db) == {"RLS item A", "mine"}
        finally:
            _release_role(db)
    assert _raw_rows("SELECT count(*) FROM evidence_items WHERE title = 'theirs'")[0][0] == 0


def test_rls_scope_survives_a_failed_statement_and_does_not_reach_the_next_borrower_on_real_postgres(pg):
    """The wrapper rolls the transaction back when a statement fails, which used to undo the
    organization setting and leave a caller who caught the error reading with no scope at all; and a
    connection returned to the pool must not carry its organization to whoever borrows it next."""
    org_a, _ = _rls_probe_world(pg)

    # Turn the pooled connection into the ordinary role first and hand it back (close() resets the
    # scope but not the role), so the organization setting below is not committed along with SET ROLE.
    prepared = pg.get_db()
    _become_restricted(prepared)
    prepared.close()

    with pg.tenant_context(org_a, "public", is_super_admin=False):
        db = pg.get_db()
        try:
            assert db.execute("SELECT current_user").fetchone()[0] == _RLS_PROBE_ROLE, "same pooled connection"
            assert _visible_titles(db) == {"RLS item A"}
            with pytest.raises(psycopg2.errors.UndefinedTable):
                db.execute("SELECT * FROM a_table_that_is_not_there")
            assert _visible_titles(db) == {"RLS item A"}, "still scoped to the organization after the failure"
        finally:
            _release_role(db)

    # The same pooled connection comes back with no organization at all: nothing is visible.
    stranger = pg.get_db()
    try:
        _become_restricted(stranger)
        assert _visible_titles(stranger) == set(), "the previous borrower's organization must be gone"
    finally:
        _release_role(stranger)


def test_a_backup_code_cannot_be_spent_twice_on_real_postgres(pg, monkeypatch):
    """The compare-and-set write needs a real row count; this runs it on PostgreSQL, with a competing
    request squeezed in between the check and the write."""
    import core.mfa as mfa

    pg.init_db()
    conn = pg.get_db_bypass_rls()
    try:
        uid = pg.insert_returning_id(
            conn,
            "INSERT INTO users (username, email, full_name, password_hash) VALUES ('mfa_pg', 'mfa_pg@example.test', 'M', 'x')",
            (),
        )
        conn.commit()
    finally:
        conn.close()
    _secret, codes = mfa.start_enrollment(uid)
    conn = pg.get_db_bypass_rls()
    try:
        conn.execute("UPDATE user_mfa SET is_enabled = 1 WHERE user_id = %s", (uid,))
        conn.commit()
    finally:
        conn.close()

    assert mfa.verify_code(uid, codes[0]) is True
    assert mfa.verify_code(uid, codes[0]) is False

    real_checkpw = mfa.bcrypt.checkpw
    competing = []

    def checkpw(plain, hashed):
        ok = real_checkpw(plain, hashed)
        if ok and not competing:
            competing.append(True)
            assert mfa.verify_code(uid, codes[1]) is True  # another request spends the same code first
        return ok

    monkeypatch.setattr(mfa.bcrypt, "checkpw", checkpw)
    assert mfa.verify_code(uid, codes[1]) is False


def test_scoped_dashboard_and_reports_run_on_real_postgres(pg):
    """Cross-module metrics must parse on PostgreSQL and exclude sibling BU rows."""
    from modules.launcher.scoped_metrics import scoped_count
    from modules.launcher.routes_dashboard import _scoped_command_stats
    from modules.launcher.routes_reports import _report_result

    pg.init_db()
    org = _make_org(pg, "metric_scope", provision=False)
    db = pg.get_db_bypass_rls()
    try:
        units = {}
        for tag in ("A", "B"):
            units[tag] = pg.insert_returning_id(
                db, "INSERT INTO business_units (name, is_active) VALUES (%s, 1)", (tag,),
            )
            db.execute(
                "INSERT INTO sentinel_breaches "
                "(ref_number, title, status, business_unit_id) VALUES (%s, %s, 'open', %s)",
                (f"BR-{tag}", f"Private breach {tag}", units[tag]),
            )
            db.execute(
                "INSERT INTO grid_audits (name, status, business_unit_id) "
                "VALUES (%s, 'Planning', %s)", (f"Private audit {tag}", units[tag]),
            )
            db.execute(
                "INSERT INTO evidence_items (title, org_id, business_unit_id, status) "
                "VALUES (%s, %s, %s, 'current')", (f"Private evidence {tag}", org, units[tag]),
            )
            db.execute(
                "INSERT INTO erm_enterprise_risks "
                "(title, likelihood, impact, business_unit_id) VALUES (%s, 4, 4, %s)",
                (f"Private risk {tag}", units[tag]),
            )
        db.commit()
        user = {"id": 999, "org_id": org, "business_unit_id": units["A"],
                "is_super_admin": 0, "roles": ["dpo"]}
        assert scoped_count(db, user, "sentinel_breaches") == 1
        assert _report_result(db, user, "privacy_overview")["breaches_open"] == 1
        assert _report_result(db, user, "executive_brief")["audits_active"] == 1
        risk_report = _report_result(db, user, "risk_report")
        assert risk_report["total_open"] == 1
        assert "Private risk B" not in str(risk_report)
        stats = _scoped_command_stats(db, user)
        assert stats["evidence_count"] == 1
        assert stats["sentinel_open_breaches"] == 0
        assert "Private breach B" not in str(stats)
    finally:
        db.close()
