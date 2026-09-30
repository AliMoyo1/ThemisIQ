"""PostgreSQL Row Level Security policies for the public schema.

Protects shared tables (users, audit_log, licenses, webhooks,
evidence_items) from cross-tenant reads when the application's connection
pool serves multiple organisations.

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

    # webhooks - defense-in-depth alongside dispatch_event()'s own org_id
    # filter (core/webhooks.py). Registered outbound integration endpoints
    # are tenant-owned; a webhook from one org must never be visible to, or
    # receive events dispatched on behalf of, another org.
    "ALTER TABLE public.webhooks ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.webhooks FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.webhooks",
    f"CREATE POLICY tenant_isolation ON public.webhooks USING {_USING}",

    # evidence_items - defense-in-depth alongside modules/evidence/routes.py's
    # own _scoped_evidence_item org_id check (PLAN-36 T08: this table had no
    # tenant scoping at all -- every list/get/download/update/delete/restore
    # route queried it by plain id with no org filter).
    "ALTER TABLE public.evidence_items ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.evidence_items FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.evidence_items",
    f"CREATE POLICY tenant_isolation ON public.evidence_items USING {_USING}",

    # readiness_findings (PLAN-36 P04) - defense-in-depth alongside
    # modules/readiness/data_service.py's own org_id filter. The rule
    # scanner writes findings for every tenant in one background process
    # (database.list_active_tenants()), so an RLS gap here would be a
    # cross-org data-integrity leak, not just a display bug.
    "ALTER TABLE public.readiness_findings ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.readiness_findings FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.readiness_findings",
    f"CREATE POLICY tenant_isolation ON public.readiness_findings USING {_USING}",

    # evidence_campaigns / evidence_requests (PLAN-36 P05) - defense-in-depth
    # alongside modules/evidence_campaigns/data_service.py's own org_id
    # filter. evidence_request_events has no org_id of its own (scoped via
    # its parent request_id) so it is not listed here, matching this
    # codebase's existing pattern of only policing tables with a direct
    # org_id column (e.g. evidence_links is not separately policed either).
    "ALTER TABLE public.evidence_campaigns ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.evidence_campaigns FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.evidence_campaigns",
    f"CREATE POLICY tenant_isolation ON public.evidence_campaigns USING {_USING}",
    "ALTER TABLE public.evidence_requests ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.evidence_requests FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.evidence_requests",
    f"CREATE POLICY tenant_isolation ON public.evidence_requests USING {_USING}",
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
        _logger.info(
            "RLS policies applied to public.users, public.audit_log, "
            "public.licenses, public.webhooks, public.evidence_items, "
            "public.readiness_findings, public.evidence_campaigns, "
            "public.evidence_requests"
        )
    except Exception as exc:
        _logger.error("RLS policy application failed (non-fatal): %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
