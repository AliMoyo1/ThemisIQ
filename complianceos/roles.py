"""
ARIA — role and capability model.

Roles are additive: a user may hold any subset of the 8 role keys below.
Permissions are computed from role → capability mappings, not role strings
directly, so the matrix can evolve without touching individual routes.

Ownership scoping for `control_owner` and `risk_owner` is handled at the
route level against the `owner` field on the underlying record; this module
only answers "does the user hold this capability *at all*".
"""

from __future__ import annotations
from typing import Iterable

# ── Role keys ─────────────────────────────────────────────────────────────────
ADMIN             = "admin"
COMPLIANCE_MGR    = "compliance_manager"
POLICY_AUTHOR     = "policy_author"
POLICY_APPROVER   = "policy_approver"
CONTROL_OWNER     = "control_owner"
RISK_OWNER        = "risk_owner"
EMPLOYEE          = "employee"
EXTERNAL_AUDITOR  = "external_auditor"

ALL_ROLES = [
    ADMIN, COMPLIANCE_MGR, POLICY_AUTHOR, POLICY_APPROVER,
    CONTROL_OWNER, RISK_OWNER, EMPLOYEE, EXTERNAL_AUDITOR,
]

# Human-readable labels (shown in admin UI + role chips)
ROLE_LABELS = {
    ADMIN:            "System Administrator",
    COMPLIANCE_MGR:   "Compliance Manager",
    POLICY_AUTHOR:    "Policy Author",
    POLICY_APPROVER:  "Policy Approver",
    CONTROL_OWNER:    "Control Owner",
    RISK_OWNER:       "Risk Owner",
    EMPLOYEE:         "Employee",
    EXTERNAL_AUDITOR: "External Auditor",
}

ROLE_DESCRIPTIONS = {
    ADMIN:            "Full system access; only role that can manage users.",
    COMPLIANCE_MGR:   "Full access to policies, controls, risks, and the AI generator across all frameworks.",
    POLICY_AUTHOR:    "Drafts and edits policies; cannot approve their own work.",
    POLICY_APPROVER:  "Reviews and approves/publishes drafts submitted by authors.",
    CONTROL_OWNER:    "Updates status and evidence on controls where they are named as owner.",
    RISK_OWNER:       "Updates mitigation and status on risks where they are named as owner.",
    EMPLOYEE:         "Reads approved policies and uses Ask ARIA. Default role for new users.",
    EXTERNAL_AUDITOR: "Read-only access to approved documents, controls, and the audit log.",
}

# Visual tone for chips on the admin UI. Keys map to cream/olive theme accents.
ROLE_CHIP_TONE = {
    ADMIN:            "bad",     # red-ish — powerful, rare
    COMPLIANCE_MGR:   "info",    # blue
    POLICY_AUTHOR:    "good",    # green
    POLICY_APPROVER:  "purple",
    CONTROL_OWNER:    "warn",    # amber
    RISK_OWNER:       "warn",
    EMPLOYEE:         "neutral",
    EXTERNAL_AUDITOR: "neutral",
}

# ── Capabilities ──────────────────────────────────────────────────────────────
# Canonical capability names used throughout the codebase.
# Route handlers should call `has_capability(user, "cap_name")` rather than
# checking role strings directly.

CAPABILITIES: dict[str, set[str]] = {
    # User management + system
    "manage_users":       {ADMIN},
    "rebuild_index":      {ADMIN},

    # Policy / document lifecycle
    "create_policy":      {ADMIN, COMPLIANCE_MGR, POLICY_AUTHOR},
    "edit_any_policy":    {ADMIN, COMPLIANCE_MGR},
    "edit_own_policy":    {ADMIN, COMPLIANCE_MGR, POLICY_AUTHOR},
    "approve_policy":     {ADMIN, COMPLIANCE_MGR, POLICY_APPROVER},
    "delete_policy":      {ADMIN},
    "generate_policy_ai": {ADMIN, COMPLIANCE_MGR, POLICY_AUTHOR},

    # Controls
    "update_any_control": {ADMIN, COMPLIANCE_MGR},
    "update_own_control": {ADMIN, COMPLIANCE_MGR, CONTROL_OWNER},

    # Risks
    "add_risk":           {ADMIN, COMPLIANCE_MGR, RISK_OWNER},
    "update_any_risk":    {ADMIN, COMPLIANCE_MGR},
    "update_own_risk":    {ADMIN, COMPLIANCE_MGR, RISK_OWNER},

    # Visibility
    "view_drafts":        {ADMIN, COMPLIANCE_MGR, POLICY_AUTHOR, POLICY_APPROVER,
                           CONTROL_OWNER, RISK_OWNER},
    "view_audit_log":     {ADMIN, COMPLIANCE_MGR, POLICY_AUTHOR, POLICY_APPROVER,
                           EXTERNAL_AUDITOR},
    "export_data":        {ADMIN, COMPLIANCE_MGR, POLICY_AUTHOR, POLICY_APPROVER,
                           EXTERNAL_AUDITOR},

    # Everyone authenticated
    "ask_aria":           set(ALL_ROLES),
    "view_dashboard":     set(ALL_ROLES),
}


# ── Helpers ───────────────────────────────────────────────────────────────────
def _role_set(user: dict | None) -> set[str]:
    """Extract a role set from a user dict. Tolerates missing keys."""
    if not user:
        return set()
    roles = user.get("roles") or []
    # Back-compat: if roles list is empty, fall back to the legacy `role` field.
    if not roles and user.get("role"):
        roles = [user["role"]]
    return set(roles)


def has_role(user: dict | None, *role_keys: str) -> bool:
    """True if user holds any of the given roles."""
    return bool(_role_set(user) & set(role_keys))


def has_capability(user: dict | None, capability: str) -> bool:
    """True if any of the user's roles grants this capability."""
    allowed = CAPABILITIES.get(capability)
    if allowed is None:
        # Unknown capability — deny by default to avoid silent bypasses.
        return False
    return bool(_role_set(user) & allowed)


def any_capability(user: dict | None, caps: Iterable[str]) -> bool:
    return any(has_capability(user, c) for c in caps)


def migrate_legacy_role(legacy: str | None) -> list[str]:
    """Map an old single-role string to the new role list.

    admin   → [admin]
    auditor → [external_auditor]
    viewer  → [employee]
    anything unrecognised → [employee]
    """
    if not legacy:
        return [EMPLOYEE]
    key = legacy.strip().lower()
    mapping = {
        "admin":   [ADMIN],
        "auditor": [EXTERNAL_AUDITOR],
        "viewer":  [EMPLOYEE],
    }
    return mapping.get(key, [EMPLOYEE])


def can_edit_control(user: dict, control: dict | None) -> bool:
    """Authoritative check for whether a user may edit a specific control."""
    if has_capability(user, "update_any_control"):
        return True
    if not has_capability(user, "update_own_control"):
        return False
    if not control:
        return False
    owner = (control.get("owner") or "").strip().lower()
    name = (user.get("full_name") or "").strip().lower()
    uname = (user.get("username") or "").strip().lower()
    return bool(owner) and (owner == name or owner == uname)


def can_edit_risk(user: dict, risk: dict | None) -> bool:
    if has_capability(user, "update_any_risk"):
        return True
    if not has_capability(user, "update_own_risk"):
        return False
    if not risk:
        return False
    owner = (risk.get("owner") or "").strip().lower()
    name = (user.get("full_name") or "").strip().lower()
    uname = (user.get("username") or "").strip().lower()
    return bool(owner) and (owner == name or owner == uname)


def can_approve_policy(user: dict, document: dict | None) -> bool:
    """Separation of duties: cannot approve your own draft."""
    if not has_capability(user, "approve_policy"):
        return False
    if not document:
        return False
    author = (document.get("owner") or "").strip().lower()
    me = (user.get("full_name") or "").strip().lower()
    uname = (user.get("username") or "").strip().lower()
    # If the current user is the document's author/owner, they can only approve
    # when they hold admin or compliance_manager — i.e. the self-approval
    # restriction applies to pure policy_approver role.
    if author and (author == me or author == uname):
        return has_role(user, ADMIN, COMPLIANCE_MGR)
    return True
