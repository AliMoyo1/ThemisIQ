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

_POLICY = """
-- Suppress error if the policy already exists (DROP + CREATE for idempotency).
DO $$
BEGIN

  -- ── users ───────────────────────────────────────────────────────────────────
  ALTER TABLE public.users ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.users FORCE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS tenant_isolation ON public.users;
  CREATE POLICY tenant_isolation ON public.users
    USING (
      COALESCE(current_setting('app.bypass_rls',      true), '') = 'true'
      OR COALESCE(current_setting('app.is_super_admin', true), '') = 'true'
      OR (
        NULLIF(current_setting('app.current_org_id', true), '') IS NOT NULL
        AND org_id = NULLIF(current_setting('app.current_org_id', true), '')::int
      )
    );

  -- ── audit_log ───────────────────────────────────────────────────────────────
  -- INSERT policy is permissive so system events (no user context) can be
  -- written without bypass. SELECT is restricted by org.
  ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.audit_log FORCE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS tenant_isolation_select ON public.audit_log;
  DROP POLICY IF EXISTS tenant_isolation_write  ON public.audit_log;
  CREATE POLICY tenant_isolation_select ON public.audit_log
    FOR SELECT
    USING (
      COALESCE(current_setting('app.bypass_rls',      true), '') = 'true'
      OR COALESCE(current_setting('app.is_super_admin', true), '') = 'true'
      OR (
        NULLIF(current_setting('app.current_org_id', true), '') IS NOT NULL
        AND org_id = NULLIF(current_setting('app.current_org_id', true), '')::int
      )
    );
  CREATE POLICY tenant_isolation_write ON public.audit_log
    FOR ALL
    USING (true)
    WITH CHECK (true);

  -- ── licenses ────────────────────────────────────────────────────────────────
  ALTER TABLE public.licenses ENABLE ROW LEVEL SECURITY;
  ALTER TABLE public.licenses FORCE ROW LEVEL SECURITY;
  DROP POLICY IF EXISTS tenant_isolation ON public.licenses;
  CREATE POLICY tenant_isolation ON public.licenses
    USING (
      COALESCE(current_setting('app.bypass_rls',      true), '') = 'true'
      OR COALESCE(current_setting('app.is_super_admin', true), '') = 'true'
      OR (
        NULLIF(current_setting('app.current_org_id', true), '') IS NOT NULL
        AND org_id = NULLIF(current_setting('app.current_org_id', true), '')::int
      )
    );

END $$;
"""


def apply_rls_policies(db) -> None:
    """Apply (or refresh) RLS policies on shared public-schema tables.

    Safe to call multiple times: DROP POLICY IF EXISTS + CREATE inside a DO
    block means it is fully idempotent.  Only meaningful on PostgreSQL; no-ops
    on SQLite.
    """
    from config import settings
    if not settings.is_postgres():
        return
    db.executescript(_POLICY)
    db.commit()
