"""
PLAN-35 T02: centralized authorization for the ARIA policy workflow.

Routes, services, search, downloads, and integration adapters should call
into this module rather than re-deriving scope/ownership rules inline.
Section references below are to plans/PLAN-35-aria-policy-authoring-flow.md.

Scope note on legacy (pre-authoring) documents: `aria_documents.org_id` is a
nullable migration column (PLAN-35 T01) and most existing rows predate it.
Locking down visibility for every such row the moment this module lands
would hide the entire existing document library until each row is adopted
(PLAN-35 section 4.8, a lazy, per-document, later process). So the org/BU
predicates below apply in full to any row that is either explicitly scoped
(`org_id` set) or already adopted (`policy_workflow_managed=1`); an
unmanaged legacy row with org_id still NULL keeps today's unrestricted
visibility until it is actually adopted. This is intentionally incremental,
not a loophole: T08 ("close legacy bypasses") is where the remaining
unscoped legacy paths get closed, not this module in isolation.

`users.deleted_at` does not exist in this codebase (verified directly against
database.py; there is no such column or migration entry) -- user removal
here is `is_active=0` (soft) or the row no longer existing at all (hard
delete, several FKs use ON DELETE CASCADE). Every "the account still exists
and isn't deleted" check below is `is_active=1` combined with a real JOIN
against `users` (which naturally excludes hard-deleted rows), not a
deleted_at comparison.
"""
from __future__ import annotations

from modules.governance.data_service import bu_scope_ids
from core.rbac import has_capability


# ─────────────────────────────────────────────────────────────────────────
# Org / BU read and create scope
# ─────────────────────────────────────────────────────────────────────────

def _is_legacy_unmanaged(record: dict) -> bool:
    return record.get("org_id") is None and not record.get("policy_workflow_managed")


def document_read_ok(actor: dict, document: dict) -> bool:
    """Section 5.1 read rules. `document` needs at least org_id,
    business_unit_id, and policy_workflow_managed keys."""
    if _is_legacy_unmanaged(document):
        return True  # see module docstring: unmigrated legacy row, unchanged visibility
    if document.get("org_id") != actor.get("org_id"):
        return False
    scope = bu_scope_ids(actor)
    if scope is None:
        return True  # super admin: all BUs in the (already-matched) active org
    bu_id = document.get("business_unit_id")
    if bu_id is None:
        return True  # explicitly organization-wide row
    return int(bu_id) in scope


def document_edit_ok(actor: dict, document: dict) -> bool:
    """Section 5.2: edit_any within scope, or edit_own when the actor is
    the recorded owner. owner_user_id is compared as an id, never a name
    (section 5's I07 -- ownership is a user id, not an authorization key)."""
    if not document_read_ok(actor, document):
        return False
    if has_capability(actor, "aria.policy.edit_any"):
        return True
    if not has_capability(actor, "aria.policy.edit_own"):
        return False
    owner_id = document.get("owner_user_id")
    return owner_id is not None and int(owner_id) == int(actor["id"])


def document_scope_sql(actor: dict) -> tuple[str, list]:
    """SQL WHERE fragment (parenthesized, ready to AND into an existing
    query) + params implementing the exact same rule as document_read_ok,
    for list/count queries where fetch-then-filter in Python would be
    wasteful. Assumes the query's base table exposes org_id,
    business_unit_id, and policy_workflow_managed columns directly (alias
    them if the query joins other tables under those names)."""
    legacy_unmanaged = "(org_id IS NULL AND COALESCE(policy_workflow_managed,0)=0)"

    scope = bu_scope_ids(actor)
    if scope is None:  # super admin: any BU within the matching org
        managed = "(org_id=%s)"
        return f"({legacy_unmanaged} OR {managed})", [actor.get("org_id")]

    placeholders = ",".join(["%s"] * len(scope))
    managed = f"(org_id=%s AND (business_unit_id IS NULL OR business_unit_id IN ({placeholders})))"
    return f"({legacy_unmanaged} OR {managed})", [actor.get("org_id"), *scope]


def template_scope_sql(actor: dict, include_inactive: bool = False) -> tuple[str, list]:
    """Same shape as document_scope_sql for aria_doc_templates: a legacy
    (org_id NULL) template stays visible to everyone, matching the existing
    behavior until it is explicitly scoped; a scoped template follows the
    normal org/BU read rule. Soft-retired templates (is_active=0) are
    excluded unless include_inactive is requested (e.g. an admin template
    management view)."""
    legacy = "(t.org_id IS NULL)"
    scope = bu_scope_ids(actor)
    if scope is None:
        managed = "(t.org_id=%s)"
        params = [actor.get("org_id")]
    else:
        placeholders = ",".join(["%s"] * len(scope))
        managed = f"(t.org_id=%s AND (t.business_unit_id IS NULL OR t.business_unit_id IN ({placeholders})))"
        params = [actor.get("org_id"), *scope]

    where = f"({legacy} OR {managed})"
    if not include_inactive:
        where = f"({where} AND COALESCE(t.is_active,1)=1)"
    return where, params


def resolve_create_bu(actor: dict, requested_bu_id, org_wide: bool) -> tuple[int | None, str | None]:
    """Section 5.1 "for creation" rules. Returns (business_unit_id, error).
    error is None on success; business_unit_id is None for an intentional
    organization-wide record. Never turns a missing/omitted BU into broad
    scope by accident -- org_wide must be explicitly requested and capable."""
    if org_wide:
        if not has_capability(actor, "aria.policy.edit_any"):
            return None, "Organization-wide scope requires the edit-any capability."
        return None, None

    scope = bu_scope_ids(actor)  # None = super admin, unrestricted within org
    if requested_bu_id is None:
        default_bu = actor.get("business_unit_id")
        return (int(default_bu) if default_bu else None), None

    requested_bu_id = int(requested_bu_id)
    if scope is not None and requested_bu_id not in scope:
        return None, "That business unit is outside your authorized scope."
    return requested_bu_id, None


# ─────────────────────────────────────────────────────────────────────────
# Approver eligibility (section 5.2)
# ─────────────────────────────────────────────────────────────────────────

def eligible_approvers(db, document: dict, exclude_user_ids: set[int]) -> list[dict]:
    """Active, same-org users who hold aria.policy.approve, can read this
    document's scope, and are not the owner/creator/any content contributor/
    the requester. exclude_user_ids is the caller's responsibility to build
    from owner_user_id + draft creator + author_user_ids_json + requester --
    this function does not know about drafts, only documents. Re-run this at
    both submission and decision time (role/BU/activation can change)."""
    org_id = document.get("org_id")
    if org_id is None:
        return []  # unmanaged legacy document: no scoped org to search within

    candidates = [dict(r) for r in db.execute(
        "SELECT u.id, u.username, u.full_name, u.org_id, u.business_unit_id, "
        "COALESCE(u.is_super_admin, 0) AS is_super_admin "
        "FROM users u WHERE u.org_id=%s AND u.is_active=1",
        (org_id,),
    ).fetchall()]

    eligible = []
    for candidate in candidates:
        if candidate["id"] in exclude_user_ids:
            continue
        candidate["roles"] = [r[0] for r in db.execute(
            "SELECT role_key FROM user_roles WHERE user_id=%s", (candidate["id"],)
        ).fetchall()]
        if not has_capability(candidate, "aria.policy.approve"):
            continue
        if not document_read_ok(candidate, document):
            continue
        eligible.append(candidate)
    return eligible


def is_eligible_approver(db, candidate_user_id: int, document: dict, exclude_user_ids: set[int]) -> bool:
    return any(c["id"] == candidate_user_id for c in eligible_approvers(db, document, exclude_user_ids))


def can_decide(actor: dict, approval: dict) -> bool:
    """Section 5.2 "Decide" row: aria.policy.approve, and the actor IS the
    assigned approver. No override -- not even for super admins (section
    5's confirmed decision), and this function has no admin-bypass branch
    to accidentally reintroduce one."""
    if not has_capability(actor, "aria.policy.approve"):
        return False
    return int(approval.get("approver_id") or -1) == int(actor["id"])


# ─────────────────────────────────────────────────────────────────────────
# Locked document-number allocator (section 4.6)
# ─────────────────────────────────────────────────────────────────────────

def reserve_document_number(db, is_postgres: bool) -> str:
    """Atomically reserve and return the next DOC-XXXX number, replacing
    every ad hoc MAX()+1 read (routes.py's api_generate_policy and
    upload_new_document both do this today, uncontended). Row-locks the
    singleton sequence row for the duration of the read-modify-write so two
    concurrent callers cannot observe and reserve the same number.

    Caller owns the transaction boundary: this function does not commit,
    call it inside the same transaction as the INSERT that consumes the
    reserved number, and commit once, together.
    """
    if is_postgres:
        row = db.execute(
            "SELECT next_value FROM aria_document_number_sequence WHERE id=1 FOR UPDATE"
        ).fetchone()
    else:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT next_value FROM aria_document_number_sequence WHERE id=1"
        ).fetchone()

    if row is None:
        next_value = 1
        db.execute(
            "INSERT INTO aria_document_number_sequence (id, next_value) VALUES (1, %s)",
            (next_value + 1,),
        )
    else:
        next_value = row[0]
        db.execute(
            "UPDATE aria_document_number_sequence SET next_value=%s WHERE id=1",
            (next_value + 1,),
        )
    return "DOC-%04d" % next_value
