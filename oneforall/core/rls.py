"""PostgreSQL Row Level Security policies for the public schema.

Protects shared tables (users, audit_log, licenses, webhooks,
evidence_items) from cross-tenant reads when the application's connection
pool serves multiple organisations.

Context variables (PostgreSQL session settings):
  app.current_org_id  - integer org id as text, set per request
  app.is_super_admin  - 'true' / 'false'
  app.bypass_rls      - 'true' to skip all policies (auth layer, provisioning)

ENABLE + FORCE ROW LEVEL SECURITY also subjects table owners to the policies.
PostgreSQL superusers and roles with BYPASSRLS always bypass them, even with
FORCE. The application role must therefore be NOSUPERUSER and NOBYPASSRLS
for these policies to provide defense in depth.
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

_GROUP_REL_USING = """(
    COALESCE(current_setting('app.bypass_rls', true), '') = 'true'
    OR COALESCE(current_setting('app.is_super_admin', true), '') = 'true'
    OR (NULLIF(current_setting('app.current_org_id', true), '') IS NOT NULL
        AND (parent_org_id = NULLIF(current_setting('app.current_org_id', true), '')::int
             OR child_org_id = NULLIF(current_setting('app.current_org_id', true), '')::int))
)"""
_GROUP_SHARED_USING = """(
    COALESCE(current_setting('app.bypass_rls', true), '') = 'true'
    OR (NULLIF(current_setting('app.current_org_id', true), '') IS NOT NULL
        AND (source_org_id = NULLIF(current_setting('app.current_org_id', true), '')::int
             OR viewer_org_id = NULLIF(current_setting('app.current_org_id', true), '')::int))
)"""
_GROUP_SOURCE_USING = """(
    COALESCE(current_setting('app.bypass_rls', true), '') = 'true'
    OR (NULLIF(current_setting('app.current_org_id', true), '') IS NOT NULL
        AND source_org_id = NULLIF(current_setting('app.current_org_id', true), '')::int)
)"""

_STMTS = [
    "ALTER TABLE public.org_relationships ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.org_relationships FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS group_edge_orgs ON public.org_relationships",
    f"CREATE POLICY group_edge_orgs ON public.org_relationships FOR SELECT USING {_GROUP_REL_USING}",
    "DROP POLICY IF EXISTS group_edge_create ON public.org_relationships",
    "CREATE POLICY group_edge_create ON public.org_relationships FOR INSERT "
    "WITH CHECK (COALESCE(current_setting('app.bypass_rls', true),'')='true' OR "
    "COALESCE(current_setting('app.is_super_admin', true),'')='true')",
    "DROP POLICY IF EXISTS group_edge_child_review ON public.org_relationships",
    "CREATE POLICY group_edge_child_review ON public.org_relationships FOR UPDATE "
    "USING (child_org_id = NULLIF(current_setting('app.current_org_id', true),'')::int) "
    "WITH CHECK (child_org_id = NULLIF(current_setting('app.current_org_id', true),'')::int)",
    "DROP POLICY IF EXISTS group_edge_platform_end ON public.org_relationships",
    "CREATE POLICY group_edge_platform_end ON public.org_relationships FOR UPDATE "
    "USING (COALESCE(current_setting('app.is_super_admin', true),'')='true') "
    "WITH CHECK (COALESCE(current_setting('app.is_super_admin', true),'')='true')",

    "ALTER TABLE public.group_view_grants ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.group_view_grants FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS group_grants_orgs ON public.group_view_grants",
    f"CREATE POLICY group_grants_orgs ON public.group_view_grants FOR SELECT USING {_GROUP_SHARED_USING}",
    "DROP POLICY IF EXISTS group_grants_viewer_write ON public.group_view_grants",
    "CREATE POLICY group_grants_viewer_write ON public.group_view_grants FOR INSERT "
    "WITH CHECK (viewer_org_id = NULLIF(current_setting('app.current_org_id', true),'')::int)",
    "DROP POLICY IF EXISTS group_grants_viewer_revoke ON public.group_view_grants",
    "CREATE POLICY group_grants_viewer_revoke ON public.group_view_grants FOR UPDATE "
    "USING (viewer_org_id = NULLIF(current_setting('app.current_org_id', true),'')::int) "
    "WITH CHECK (viewer_org_id = NULLIF(current_setting('app.current_org_id', true),'')::int)",

    "ALTER TABLE public.group_document_rights ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.group_document_rights FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS group_rights_source ON public.group_document_rights",
    f"CREATE POLICY group_rights_source ON public.group_document_rights USING {_GROUP_SOURCE_USING}",

    "ALTER TABLE public.group_document_publications ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.group_document_publications FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS group_publications_orgs ON public.group_document_publications",
    f"CREATE POLICY group_publications_orgs ON public.group_document_publications FOR SELECT USING {_GROUP_SHARED_USING}",
    "DROP POLICY IF EXISTS group_publications_source_write ON public.group_document_publications",
    f"CREATE POLICY group_publications_source_write ON public.group_document_publications FOR INSERT WITH CHECK {_GROUP_SOURCE_USING}",
    "DROP POLICY IF EXISTS group_publications_source_revoke ON public.group_document_publications",
    f"CREATE POLICY group_publications_source_revoke ON public.group_document_publications FOR UPDATE USING {_GROUP_SOURCE_USING} WITH CHECK {_GROUP_SOURCE_USING}",

    "ALTER TABLE public.group_access_events ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.group_access_events FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS group_events_orgs ON public.group_access_events",
    f"CREATE POLICY group_events_orgs ON public.group_access_events FOR SELECT USING {_GROUP_SHARED_USING}",
    "DROP POLICY IF EXISTS group_events_insert ON public.group_access_events",
    f"CREATE POLICY group_events_insert ON public.group_access_events FOR INSERT WITH CHECK {_GROUP_SHARED_USING}",

    "ALTER TABLE public.group_evidence_requests ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.group_evidence_requests FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS group_requests_parties ON public.group_evidence_requests",
    "CREATE POLICY group_requests_parties ON public.group_evidence_requests FOR SELECT "
    "USING (COALESCE(current_setting('app.bypass_rls',true),'')='true' OR "
    "requester_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int OR "
    "source_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int)",
    "DROP POLICY IF EXISTS group_requests_parent_create ON public.group_evidence_requests",
    "CREATE POLICY group_requests_parent_create ON public.group_evidence_requests FOR INSERT "
    "WITH CHECK (requester_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int)",
    "DROP POLICY IF EXISTS group_requests_source_review ON public.group_evidence_requests",
    "CREATE POLICY group_requests_source_review ON public.group_evidence_requests FOR UPDATE "
    "USING (source_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int) "
    "WITH CHECK (source_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int)",
    "DROP POLICY IF EXISTS group_requests_parent_revise ON public.group_evidence_requests",
    "CREATE POLICY group_requests_parent_revise ON public.group_evidence_requests FOR UPDATE "
    "USING (requester_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int "
    "AND status='clarification') "
    "WITH CHECK (requester_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int "
    "AND status='requested')",

    "ALTER TABLE public.group_request_verdicts ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.group_request_verdicts FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS group_request_verdicts_parties ON public.group_request_verdicts",
    "CREATE POLICY group_request_verdicts_parties ON public.group_request_verdicts FOR SELECT "
    "USING (COALESCE(current_setting('app.bypass_rls',true),'')='true' OR "
    "EXISTS (SELECT 1 FROM public.group_evidence_requests r "
    "WHERE r.id=request_id AND r.requester_org_id=group_request_verdicts.requester_org_id "
    "AND (r.requester_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int "
    "OR r.source_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int)))",
    "DROP POLICY IF EXISTS group_request_verdicts_parent_insert ON public.group_request_verdicts",
    "CREATE POLICY group_request_verdicts_parent_insert ON public.group_request_verdicts FOR INSERT "
    "WITH CHECK (requester_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int "
    "AND EXISTS (SELECT 1 FROM public.group_evidence_requests r "
    "JOIN public.group_document_publications p ON p.id=group_request_verdicts.publication_id "
    "WHERE r.id=request_id AND r.requester_org_id=group_request_verdicts.requester_org_id "
    "AND r.status='fulfilled' AND r.publication_id=p.id "
    "AND p.relationship_id=r.relationship_id AND p.viewer_org_id=r.requester_org_id "
    "AND p.source_org_id=r.source_org_id))",

    "ALTER TABLE public.group_request_mappings ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.group_request_mappings FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS group_request_mappings_source ON public.group_request_mappings",
    f"CREATE POLICY group_request_mappings_source ON public.group_request_mappings USING {_GROUP_SOURCE_USING} WITH CHECK {_GROUP_SOURCE_USING}",
    "ALTER TABLE public.group_policy_adoptions ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.group_policy_adoptions FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS group_policy_adoptions_child ON public.group_policy_adoptions",
    "DROP POLICY IF EXISTS group_policy_adoptions_view ON public.group_policy_adoptions",
    "CREATE POLICY group_policy_adoptions_view ON public.group_policy_adoptions FOR SELECT "
    "USING (viewer_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int)",
    "DROP POLICY IF EXISTS group_policy_adoptions_propose ON public.group_policy_adoptions",
    "CREATE POLICY group_policy_adoptions_propose ON public.group_policy_adoptions FOR INSERT "
    "WITH CHECK (viewer_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int)",
    "DROP POLICY IF EXISTS group_policy_adoptions_review ON public.group_policy_adoptions",
    "CREATE POLICY group_policy_adoptions_review ON public.group_policy_adoptions FOR UPDATE "
    "USING (viewer_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int) "
    "WITH CHECK (viewer_org_id=NULLIF(current_setting('app.current_org_id',true),'')::int)",
    # users
    "ALTER TABLE public.users ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.users FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.users",
    f"CREATE POLICY tenant_isolation ON public.users USING {_USING}",

    # audit_log - SELECT (and any UPDATE or DELETE) restricted by org; INSERT is
    # unrestricted so system events can be logged without org context. The write
    # policy used to be FOR ALL USING (true), and permissive policies are OR-ed,
    # so it also let every role read every organization's entries; it is now
    # INSERT only (tests/test_postgres_init.py checks both halves).
    "ALTER TABLE public.audit_log ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.audit_log FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation_select ON public.audit_log",
    "DROP POLICY IF EXISTS tenant_isolation_write ON public.audit_log",
    f"CREATE POLICY tenant_isolation_select ON public.audit_log FOR SELECT USING {_USING}",
    "CREATE POLICY tenant_isolation_write ON public.audit_log FOR INSERT WITH CHECK (true)",

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
    "ALTER TABLE public.evidence_companies ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.evidence_companies FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.evidence_companies",
    f"CREATE POLICY tenant_isolation ON public.evidence_companies USING {_USING} WITH CHECK {_USING}",
    "ALTER TABLE public.evidence_company_events ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.evidence_company_events FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.evidence_company_events",
    f"CREATE POLICY tenant_isolation ON public.evidence_company_events USING {_USING} WITH CHECK {_USING}",
    "ALTER TABLE public.evidence_unit_company_mappings ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.evidence_unit_company_mappings FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.evidence_unit_company_mappings",
    f"CREATE POLICY tenant_isolation ON public.evidence_unit_company_mappings USING {_USING} WITH CHECK {_USING}",
    "ALTER TABLE public.evidence_unit_company_events ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.evidence_unit_company_events FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.evidence_unit_company_events",
    f"CREATE POLICY tenant_isolation ON public.evidence_unit_company_events USING {_USING} WITH CHECK {_USING}",

    # Parsed document text is more sensitive than its metadata. Public rows
    # get the same organization guard; business-unit access is checked via
    # the evidence_items join in every read path.
    "ALTER TABLE public.evidence_text_index ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.evidence_text_index FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.evidence_text_index",
    f"CREATE POLICY tenant_isolation ON public.evidence_text_index USING {_USING}",

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

    # saved_views / bulk_action_runs (PLAN-36 P06) - defense-in-depth
    # alongside modules/saved_views/data_service.py's own org_id filter.
    # saved_views in particular can be marked `shared`, which is only ever
    # meant to share within one organization -- an RLS gap here would let a
    # shared view (and the filter/sort/column preferences inside it) leak
    # across organizations, not just across users within one.
    "ALTER TABLE public.saved_views ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.saved_views FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.saved_views",
    f"CREATE POLICY tenant_isolation ON public.saved_views USING {_USING}",
    "ALTER TABLE public.bulk_action_runs ENABLE ROW LEVEL SECURITY",
    "ALTER TABLE public.bulk_action_runs FORCE ROW LEVEL SECURITY",
    "DROP POLICY IF EXISTS tenant_isolation ON public.bulk_action_runs",
    f"CREATE POLICY tenant_isolation ON public.bulk_action_runs USING {_USING}",
]


def apply_rls_policies(db) -> None:
    """Apply (or refresh) RLS policies on shared public-schema tables.

    Idempotent: DROP POLICY IF EXISTS + CREATE means it is safe to call on
    every startup. Only meaningful on PostgreSQL; no-ops on SQLite.
    A failed installation aborts PostgreSQL startup because shared public
    tables are not isolated by tenant schemas. Request paths must also retain
    explicit organization filters.
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
            "public.evidence_text_index, "
            "public.readiness_findings, public.evidence_campaigns, "
            "public.evidence_requests, public.saved_views, "
            "public.bulk_action_runs"
        )
    except Exception as exc:
        _logger.error("RLS policy installation failed; refusing startup: %s", exc)
        try:
            db.rollback()
        except Exception:
            pass
        raise RuntimeError("RLS policy installation failed") from exc
