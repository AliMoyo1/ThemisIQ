"""
PLAN-36 P04: concrete detection rules, one real instance per named category
in task_plan.md's P04 implementation list. Each is deterministic and
read-only (no UPDATE/INSERT/DELETE against the tables it inspects).

Scoping note, confirmed by reading database.py rather than assumed: tables
that carry a real `org_id` column (aria_*, evidence_items) are shared
across tenants even on Postgres (RLS-protected, core/rls.py), so their
rules filter by org_id explicitly. Tables that are only ever
business_unit_id-scoped (grid_controls, business_units itself) have no
org_id column at all -- on Postgres they live in a genuinely separate
per-tenant schema (the caller's tenant_context binding is what scopes
them, matching every other per-tenant scheduler job in this codebase,
e.g. modules/aria/scheduler.py); on SQLite (dev/test only) they are not
tenant-isolated at all, a pre-existing limitation this rule set does not
attempt to work around.

Extending coverage: task_plan.md's own implementation list names many more
concrete columns than the one instance per category built here (see
progress.md's P04 session entry for the full list found during discovery).
Adding one is: write a RawFinding-returning function, decorate it with
@register_rule("SOME_CODE"), done -- run_rules_for_org() picks it up
automatically via the registry, no other wiring required.
"""
from __future__ import annotations

from core.timeutils import utcnow
from modules.readiness.data_service import RawFinding, register_rule


# ─────────────────────────────────────────────────────────────────────────
# 1. Missing organization/SBU/owner
# ─────────────────────────────────────────────────────────────────────────

@register_rule("MISSING_RISK_OWNER")
def missing_risk_owner(db, org_id: int) -> list[RawFinding]:
    """An enterprise risk with nobody accountable for it -- erm_enterprise_risks
    has no org_id column (BU-scoped only, see module docstring), so this
    query relies on tenant_context binding, not an explicit filter."""
    rows = db.execute(
        "SELECT id, title FROM erm_enterprise_risks WHERE owner_id IS NULL AND status != 'closed'"
    ).fetchall()
    return [
        RawFinding(
            rule_code="MISSING_RISK_OWNER", severity="high", module="erm",
            entity_type="erm_enterprise_risk", entity_id=str(r["id"]),
            message=f"Risk \"{r['title']}\" has no assigned owner.",
        )
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────
# 2. Deleted or inactive assignee
# ─────────────────────────────────────────────────────────────────────────

@register_rule("INACTIVE_CONTROL_ASSIGNEE")
def inactive_control_assignee(db, org_id: int) -> list[RawFinding]:
    """A GRID control assigned to a user who can no longer act on it --
    modules/grid/scheduler.py's own reminder jobs silently `continue` past
    exactly this case (LEFT JOIN users, `if not email: continue`), so a
    stale assignment here explains a reminder that will never fire."""
    rows = db.execute(
        "SELECT c.id, c.name, c.assignee_id FROM grid_controls c "
        "JOIN users u ON u.id = c.assignee_id "
        "WHERE u.is_active = 0 AND c.status NOT IN ('Complete','Closed')"
    ).fetchall()
    return [
        RawFinding(
            rule_code="INACTIVE_CONTROL_ASSIGNEE", severity="medium", module="grid",
            entity_type="grid_control", entity_id=str(r["id"]),
            message=f"Control \"{r['name']}\" is assigned to a deactivated user (id {r['assignee_id']}).",
        )
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────
# 3. Broken cross-module reference
# ─────────────────────────────────────────────────────────────────────────

@register_rule("BROKEN_FRAMEWORK_REFERENCE")
def broken_framework_reference(db, org_id: int) -> list[RawFinding]:
    """grid_controls.framework_id is a bare INTEGER with no real FK to the
    (global, shared) frameworks table -- a value that doesn't resolve is a
    silent broken reference, not caught by any constraint today."""
    rows = db.execute(
        "SELECT c.id, c.name, c.framework_id FROM grid_controls c "
        "WHERE c.framework_id IS NOT NULL "
        "AND NOT EXISTS (SELECT 1 FROM frameworks f WHERE f.id = c.framework_id)"
    ).fetchall()
    return [
        RawFinding(
            rule_code="BROKEN_FRAMEWORK_REFERENCE", severity="medium", module="grid",
            entity_type="grid_control", entity_id=str(r["id"]),
            message=f"Control \"{r['name']}\" references framework_id {r['framework_id']}, which does not exist.",
        )
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────
# 4. Missing policy template/build
# ─────────────────────────────────────────────────────────────────────────

@register_rule("ARIA_DRAFT_MISSING_BUILD")
def aria_draft_missing_build(db, org_id: int) -> list[RawFinding]:
    """A draft claiming to be built ('ready') or already committed with no
    build_id/template_id recorded -- the service layer never produces this
    combination through its own normal calls, so a real hit here means
    either a bug or direct database tampering, not routine user activity."""
    rows = db.execute(
        "SELECT id, state FROM aria_policy_drafts WHERE org_id=%s "
        "AND state IN ('ready','committed') "
        "AND (build_id IS NULL OR template_id IS NULL)",
        (org_id,),
    ).fetchall()
    return [
        RawFinding(
            rule_code="ARIA_DRAFT_MISSING_BUILD", severity="critical", module="aria",
            entity_type="aria_policy_draft", entity_id=r["id"],
            message=f"Draft is '{r['state']}' but has no recorded build/template.",
        )
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────
# 5. Invalid lifecycle combination
# ─────────────────────────────────────────────────────────────────────────

@register_rule("ARIA_VERSION_STATE_MISMATCH")
def aria_version_state_mismatch(db, org_id: int) -> list[RawFinding]:
    """A version's state and its approved_at timestamp disagree -- either
    is possible only through a bug or direct tampering; confirm_draft/
    decide_approval always set both together."""
    rows = db.execute(
        "SELECT id, document_id, version, state FROM aria_policy_versions WHERE org_id=%s "
        "AND ((state = 'approved' AND approved_at IS NULL) "
        "OR (state != 'approved' AND approved_by IS NOT NULL))",
        (org_id,),
    ).fetchall()
    findings = []
    for r in rows:
        doc = db.execute("SELECT doc_id FROM aria_documents WHERE id=%s", (r["document_id"],)).fetchone()
        doc_id = doc["doc_id"] if doc else None
        findings.append(RawFinding(
            rule_code="ARIA_VERSION_STATE_MISMATCH", severity="high", module="aria",
            entity_type="aria_policy_version", entity_id=str(r["id"]),
            message=f"Version {r['version']} has state '{r['state']}' inconsistent with its approval fields.",
            remediation_route=f"/aria/documents?open={doc_id}" if doc_id else None,
        ))
    return findings


# ─────────────────────────────────────────────────────────────────────────
# 6. Stale queue/lease
# ─────────────────────────────────────────────────────────────────────────

@register_rule("STALE_PUBLICATION_LEASE")
def stale_publication_lease(db, org_id: int) -> list[RawFinding]:
    """A publication job claimed ('running') whose lease has already
    expired without being reclaimed -- claim_next_job() only reclaims on
    its own next poll; a worker crashing mid-job can leave one sitting here
    until then."""
    now = utcnow().isoformat()
    rows = db.execute(
        "SELECT id, document_id, attempts FROM aria_policy_publication_jobs WHERE org_id=%s "
        "AND state = 'running' AND lease_until IS NOT NULL AND lease_until < %s",
        (org_id, now),
    ).fetchall()
    findings = []
    for r in rows:
        doc = db.execute("SELECT doc_id FROM aria_documents WHERE id=%s", (r["document_id"],)).fetchone()
        doc_id = doc["doc_id"] if doc else None
        findings.append(RawFinding(
            rule_code="STALE_PUBLICATION_LEASE", severity="high", module="aria",
            entity_type="aria_policy_publication_job", entity_id=str(r["id"]),
            message=f"Publication job has an expired lease after {r['attempts']} attempt(s) and has not been reclaimed.",
            remediation_route=f"/aria/documents?open={doc_id}" if doc_id else None,
        ))
    return findings


# ─────────────────────────────────────────────────────────────────────────
# 7. Overdue evidence/review
# ─────────────────────────────────────────────────────────────────────────

@register_rule("EVIDENCE_EXPIRED_UNFLAGGED")
def evidence_expired_unflagged(db, org_id: int) -> list[RawFinding]:
    """Evidence past its own expiry_date that the record's own status
    field has not been updated to reflect -- modules/evidence/scheduler.py's
    _expiry_check() sends 30/7/1-day *warnings* but (confirmed by reading
    it) never flips status itself, so a genuinely expired item can sit
    marked 'current' indefinitely if nobody acts on those emails."""
    today = utcnow().date().isoformat()
    rows = db.execute(
        "SELECT id, title, expiry_date FROM evidence_items WHERE org_id=%s "
        "AND expiry_date IS NOT NULL AND expiry_date < %s AND status = 'current'",
        (org_id, today),
    ).fetchall()
    return [
        RawFinding(
            rule_code="EVIDENCE_EXPIRED_UNFLAGGED", severity="medium", module="evidence",
            entity_type="evidence_item", entity_id=str(r["id"]),
            message=f"\"{r['title']}\" expired on {r['expiry_date']} but is still marked current.",
        )
        for r in rows
    ]


# ─────────────────────────────────────────────────────────────────────────
# 8. Capability/config prerequisite not met
# ─────────────────────────────────────────────────────────────────────────

@register_rule("ARIA_AUTHORING_NO_TEMPLATE")
def aria_authoring_no_template(db, org_id: int) -> list[RawFinding]:
    """Policy authoring is enabled for this org, but it has no active
    document template -- every draft build would fail with BUILD_REQUIRED
    the moment anyone tried, a real workflow-blocking gap this centre
    exists to surface before a user hits it. Reuses the exact feature-flag
    function the authoring endpoints themselves gate on, rather than
    re-deriving "is authoring on" from settings directly."""
    from modules.aria.policy_access import policy_authoring_enabled_for
    if not policy_authoring_enabled_for(org_id):
        return []
    row = db.execute(
        "SELECT COUNT(*) AS n FROM aria_doc_templates WHERE org_id=%s AND is_active=1", (org_id,),
    ).fetchone()
    if row and row["n"] > 0:
        return []
    return [RawFinding(
        rule_code="ARIA_AUTHORING_NO_TEMPLATE", severity="high", module="aria",
        entity_type="organization", entity_id=str(org_id),
        message="Policy authoring is enabled for this organization, but no active document template exists yet.",
        remediation_route="/aria/templates",
    )]
