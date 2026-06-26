"""PostgreSQL Row Level Security policies for the public schema.

Protects shared tables (users, audit_log, licenses) from cross-tenant reads
when the application's connection pool serves multiple organisations.

Context variables (PostgreSQL session settings):
  app.current_org_id  - integer org id as text, set per request
  app.is_super_admin  - 'true' / 'false'
  app.bypass_rls      - 'true' to skip all policies (auth layer, provisioning)

ENABLE + FORCE ROW LEVEL SECURITY is used so even superuser connections
(the typical app role) are constrained by the policies.
"""
import logging

_logger = logging.getLogger(__name__)

_USING = """(
    COALESCE(current_setting('app.bypass_rls', true), '') = 'true'
    OR COALESCE(current_setting('app.is_super_admin', true), '') = 'true'
    OR (
      NULLIF(current_setting('app.current_org_id', true), '') IS NOT NULL
      AND org_id = NULLIF(current_setting('app.current_org_id', true), '')::int
    )
  )"""

_STMTS = [
    # users
    "ALTER TABLE public.users ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.users FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.users",
    f"CREATE POLICY tenant_isolation ON public.users USING {_USING}",

    # audit_log - SELECT restricted by org; writes are unrestricted so system
    # events can be logged without org context
    "ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.audit_log FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation_select ON public.audit_log",
    "DROP POLICY IF EXISTS tenant_isolation_write ON public.audit_log",
    f"CREATE POLICY tenant_isolation_select ON public.audit_log FOR SELECT USING {_USING}",
    "CREATE POLICY tenant_isolation_write ON public.audit_log FOR ALL USING (true) WITH CHECK (true)",

    # licenses
    "ALTER TABLE public.licenses ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.licenses FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.licenses",
    f"CREATE POLICY tenant_isolation ON public.licenses USING {_USING}",
]


def apply_rls_policies(db) -> None:
    """Apply (or refresh) RLS policies on shared public-schema tables.

    Idempotent: DROP POLICY IF EXISTS + CREATE means it is safe to call on
    every startup. Only meaningful on PostgreSQL; no-ops on SQLite.
    Errors are logged and swallowed so a policy failure does not prevent the
    app from starting (schema-level isolation still protects tenant data).
    """
    from config import settings
    if not settings.is_postgres():
        return
    try:
        for stmt in _STMTS:
            db.execute(stmt)
        db.commit()
        _logger.info("RLS policies applied to public.users, public.audit_log, public.licenses")
    except Exception as exc:
        _logger.error("RLS policy application failed (non-fatal): %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
