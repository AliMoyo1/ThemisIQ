"""
One For All — Unified Role-Based Access Control.

Capability-based permission system.  Users hold roles; roles grant
capabilities.  Route guards check capabilities, never role strings directly.
"""
from __future__ import annotations
from typing import Iterable

# ── Platform Role Keys ───────────────────────────────────────────────────────
SUPER_ADMIN       = "super_admin"
COMPLIANCE_MGR    = "compliance_manager"
POLICY_AUTHOR     = "policy_author"
POLICY_APPROVER   = "policy_approver"
CONTROL_OWNER     = "control_owner"
RISK_OWNER        = "risk_owner"
AUDIT_LEAD        = "audit_lead"
AUDITOR           = "auditor"
BCM_MANAGER       = "bcm_manager"
INCIDENT_COMMANDER = "incident_commander"
BCM_RESPONDER     = "bcm_responder"
DPO               = "dpo"
PRIVACY_ANALYST   = "privacy_analyst"
EMPLOYEE          = "employee"
EXTERNAL_AUDITOR  = "external_auditor"

ALL_ROLES = [
    SUPER_ADMIN, COMPLIANCE_MGR, POLICY_AUTHOR, POLICY_APPROVER,
    CONTROL_OWNER, RISK_OWNER, AUDIT_LEAD, AUDITOR,
    BCM_MANAGER, INCIDENT_COMMANDER, BCM_RESPONDER,
    DPO, PRIVACY_ANALYST, EMPLOYEE, EXTERNAL_AUDITOR,
]

ROLE_LABELS = {
    SUPER_ADMIN:        "Super Administrator",
    COMPLIANCE_MGR:     "Compliance Manager",
    POLICY_AUTHOR:      "Policy Author",
    POLICY_APPROVER:    "Policy Approver",
    CONTROL_OWNER:      "Control Owner",
    RISK_OWNER:         "Risk Owner",
    AUDIT_LEAD:         "Audit Lead",
    AUDITOR:            "Auditor",
    BCM_MANAGER:        "BCM Manager",
    INCIDENT_COMMANDER: "Incident Commander",
    BCM_RESPONDER:      "BCM Responder",
    DPO:                "Data Protection Officer",
    PRIVACY_ANALYST:    "Privacy Analyst",
    EMPLOYEE:           "Employee",
    EXTERNAL_AUDITOR:   "External Auditor",
}

ROLE_DESCRIPTIONS = {
    SUPER_ADMIN:        "Full platform access across all modules. User management.",
    COMPLIANCE_MGR:     "Full ARIA access; read access to other modules.",
    POLICY_AUTHOR:      "Drafts and edits policies in ARIA.",
    POLICY_APPROVER:    "Reviews and approves policies in ARIA.",
    CONTROL_OWNER:      "Updates assigned controls in ARIA.",
    RISK_OWNER:         "Updates assigned risks in ARIA and BCM.",
    AUDIT_LEAD:         "Creates and manages audits in GRID.",
    AUDITOR:            "Works on audit controls and evidence in GRID.",
    BCM_MANAGER:        "Full BCM module access.",
    INCIDENT_COMMANDER: "Manages incident response in BCM.",
    BCM_RESPONDER:      "Updates incidents and executes plans in BCM.",
    DPO:                "Full Data Protection Sentinel access.",
    PRIVACY_ANALYST:    "Manages RoPA, DPIA, DSR in Sentinel.",
    EMPLOYEE:           "Read-only on approved content; can use AI assistants.",
    EXTERNAL_AUDITOR:   "Read-only access to controls, evidence, and audit logs.",
}

# Module the role primarily belongs to (for UI grouping)
ROLE_MODULE = {
    SUPER_ADMIN:        "platform",
    COMPLIANCE_MGR:     "aria",
    POLICY_AUTHOR:      "aria",
    POLICY_APPROVER:    "aria",
    CONTROL_OWNER:      "aria",
    RISK_OWNER:         "platform",
    AUDIT_LEAD:         "grid",
    AUDITOR:            "grid",
    BCM_MANAGER:        "bcm",
    INCIDENT_COMMANDER: "bcm",
    BCM_RESPONDER:      "bcm",
    DPO:                "sentinel",
    PRIVACY_ANALYST:    "sentinel",
    EMPLOYEE:           "platform",
    EXTERNAL_AUDITOR:   "platform",
}

# Visual tone for role badges in admin UI
ROLE_CHIP_TONE = {
    SUPER_ADMIN:        "bad",       # red — powerful, rare
    COMPLIANCE_MGR:     "info",      # blue
    POLICY_AUTHOR:      "good",      # green
    POLICY_APPROVER:    "purple",
    CONTROL_OWNER:      "warn",      # amber
    RISK_OWNER:         "warn",
    AUDIT_LEAD:         "info",
    AUDITOR:            "info",
    BCM_MANAGER:        "warn",
    INCIDENT_COMMANDER: "bad",
    BCM_RESPONDER:      "good",
    DPO:                "purple",
    PRIVACY_ANALYST:    "info",
    EMPLOYEE:           "neutral",
    EXTERNAL_AUDITOR:   "neutral",
}

# ── Capabilities ─────────────────────────────────────────────────────────────
# Maps capability name → set of roles that hold it.

CAPABILITIES: dict[str, set[str]] = {
    # ── Platform ─────────────────────────────────────────────────
    "platform.manage_users":      {SUPER_ADMIN},
    "platform.manage_settings":   {SUPER_ADMIN},
    "platform.view_audit_log":    {SUPER_ADMIN, COMPLIANCE_MGR, DPO, EXTERNAL_AUDITOR},
    "manage_frameworks":          {SUPER_ADMIN, COMPLIANCE_MGR, AUDIT_LEAD},

    # ── Module access ────────────────────────────────────────────
    "module.aria.access":     {SUPER_ADMIN, COMPLIANCE_MGR, POLICY_AUTHOR, POLICY_APPROVER,
                               CONTROL_OWNER, RISK_OWNER, EMPLOYEE, EXTERNAL_AUDITOR,
                               AUDIT_LEAD, DPO},
    "module.grid.access":     {SUPER_ADMIN, AUDIT_LEAD, AUDITOR, COMPLIANCE_MGR,
                               EXTERNAL_AUDITOR, DPO},
    "module.bcm.access":      {SUPER_ADMIN, BCM_MANAGER, INCIDENT_COMMANDER, BCM_RESPONDER,
                               RISK_OWNER, COMPLIANCE_MGR, EMPLOYEE},
    "module.sentinel.access": {SUPER_ADMIN, DPO, PRIVACY_ANALYST, COMPLIANCE_MGR},

    # ── ARIA capabilities ────────────────────────────────────────
    "aria.policy.create":       {SUPER_ADMIN, COMPLIANCE_MGR, POLICY_AUTHOR},
    "aria.policy.edit_own":     {SUPER_ADMIN, COMPLIANCE_MGR, POLICY_AUTHOR},
    "aria.policy.edit_any":     {SUPER_ADMIN, COMPLIANCE_MGR},
    "aria.policy.approve":      {SUPER_ADMIN, COMPLIANCE_MGR, POLICY_APPROVER},
    "aria.policy.delete":       {SUPER_ADMIN, COMPLIANCE_MGR},
    "aria.policy.generate_ai":  {SUPER_ADMIN, COMPLIANCE_MGR, POLICY_AUTHOR},
    "aria.control.update_own":  {SUPER_ADMIN, COMPLIANCE_MGR, CONTROL_OWNER},
    "aria.control.update_any":  {SUPER_ADMIN, COMPLIANCE_MGR},
    "aria.risk.add":            {SUPER_ADMIN, COMPLIANCE_MGR, RISK_OWNER},
    "aria.risk.update_own":     {SUPER_ADMIN, COMPLIANCE_MGR, RISK_OWNER},
    "aria.risk.update_any":     {SUPER_ADMIN, COMPLIANCE_MGR},
    "aria.documents.export":    {SUPER_ADMIN, COMPLIANCE_MGR, POLICY_AUTHOR, POLICY_APPROVER,
                                 EXTERNAL_AUDITOR},
    "aria.ask_ai":              set(ALL_ROLES),

    # ── GRID capabilities ────────────────────────────────────────
    "grid.audits.view":             {SUPER_ADMIN, AUDIT_LEAD, AUDITOR, COMPLIANCE_MGR,
                                     EXTERNAL_AUDITOR},
    "grid.audits.manage":           {SUPER_ADMIN, AUDIT_LEAD},
    "grid.audit.create":            {SUPER_ADMIN, AUDIT_LEAD},
    "grid.audit.edit":              {SUPER_ADMIN, AUDIT_LEAD},
    "grid.audit.delete":            {SUPER_ADMIN},
    "grid.control.assign":        {SUPER_ADMIN, AUDIT_LEAD},
    "grid.control.update_own":    {SUPER_ADMIN, AUDIT_LEAD, AUDITOR},
    "grid.control.update_any":    {SUPER_ADMIN, AUDIT_LEAD},
    "grid.evidence.upload":       {SUPER_ADMIN, AUDIT_LEAD, AUDITOR},
    "grid.evidence.approve":      {SUPER_ADMIN, AUDIT_LEAD},
    "grid.evidence.delete":       {SUPER_ADMIN},
    "grid.ai.parse_checklist":    {SUPER_ADMIN, AUDIT_LEAD},
    "grid.ai.gap_analysis":       {SUPER_ADMIN, AUDIT_LEAD, AUDITOR},
    "grid.ai.report":             {SUPER_ADMIN, AUDIT_LEAD},
    "grid.reminder.manage":       {SUPER_ADMIN, AUDIT_LEAD, AUDITOR},
    "grid.nc.manage":             {SUPER_ADMIN, AUDIT_LEAD},
    "grid.vendor.manage":         {SUPER_ADMIN, AUDIT_LEAD},
    "grid.share.manage":          {SUPER_ADMIN, AUDIT_LEAD},
    "grid.cross_mapping.manage":  {SUPER_ADMIN, AUDIT_LEAD, AUDITOR},

    # ── BCM capabilities ─────────────────────────────────────────
    "bcm.bia.manage":             {SUPER_ADMIN, BCM_MANAGER},
    "bcm.risk.manage":            {SUPER_ADMIN, BCM_MANAGER, RISK_OWNER},
    "bcm.plan.create":            {SUPER_ADMIN, BCM_MANAGER},
    "bcm.plan.edit":              {SUPER_ADMIN, BCM_MANAGER},
    "bcm.plan.approve":           {SUPER_ADMIN, BCM_MANAGER},
    "bcm.plan.manage":            {SUPER_ADMIN, BCM_MANAGER},
    "bcm.incident.declare":       {SUPER_ADMIN, BCM_MANAGER, INCIDENT_COMMANDER},
    "bcm.incident.manage":        {SUPER_ADMIN, BCM_MANAGER, INCIDENT_COMMANDER},
    "bcm.incident.update":        {SUPER_ADMIN, BCM_MANAGER, INCIDENT_COMMANDER, BCM_RESPONDER},
    "bcm.exercise.manage":        {SUPER_ADMIN, BCM_MANAGER},
    "bcm.vendor.manage":          {SUPER_ADMIN, BCM_MANAGER},
    "bcm.report.generate":        {SUPER_ADMIN, BCM_MANAGER},
    "bcm.compliance.manage":      {SUPER_ADMIN, BCM_MANAGER, COMPLIANCE_MGR},
    "bcm.training.manage":        {SUPER_ADMIN, BCM_MANAGER},
    "bcm.document.manage":        {SUPER_ADMIN, BCM_MANAGER},
    "bcm.dependency.manage":      {SUPER_ADMIN, BCM_MANAGER},
    "bcm.ai.use":                 {SUPER_ADMIN, BCM_MANAGER, INCIDENT_COMMANDER, BCM_RESPONDER},
    "bcm.ai.chat":                {SUPER_ADMIN, BCM_MANAGER, INCIDENT_COMMANDER, BCM_RESPONDER},

    # ── Evidence Vault capabilities ─────────────────────────────
    "evidence.delete":            {SUPER_ADMIN, COMPLIANCE_MGR},

    # ── Sentinel capabilities ────────────────────────────────────
    "sentinel.ropa.manage":           {SUPER_ADMIN, DPO, PRIVACY_ANALYST},
    "sentinel.dpia.manage":           {SUPER_ADMIN, DPO, PRIVACY_ANALYST},
    "sentinel.breach.manage":         {SUPER_ADMIN, DPO},
    "sentinel.dsr.manage":            {SUPER_ADMIN, DPO, PRIVACY_ANALYST},
    "sentinel.consent.manage":        {SUPER_ADMIN, DPO, PRIVACY_ANALYST},
    "sentinel.vendor.manage":         {SUPER_ADMIN, DPO},
    "sentinel.privacy_notice.manage": {SUPER_ADMIN, DPO, PRIVACY_ANALYST},
    "sentinel.controller.manage":     {SUPER_ADMIN, DPO},
    "sentinel.transfer.manage":       {SUPER_ADMIN, DPO, PRIVACY_ANALYST},
    "sentinel.retention.manage":      {SUPER_ADMIN, DPO, PRIVACY_ANALYST},
    "sentinel.ai.assess":             {SUPER_ADMIN, DPO, PRIVACY_ANALYST},

    # ── ERM capabilities ──────────────────────────────────────────────
    "module.erm.access":         {SUPER_ADMIN, RISK_OWNER, COMPLIANCE_MGR, AUDIT_LEAD, BCM_MANAGER, DPO},
    "erm.risk.manage":           {SUPER_ADMIN, RISK_OWNER},
    "erm.risk.view":             {SUPER_ADMIN, RISK_OWNER, COMPLIANCE_MGR, AUDIT_LEAD, BCM_MANAGER, DPO},
    "erm.appetite.manage":       {SUPER_ADMIN, RISK_OWNER},
    "erm.library.manage":        {SUPER_ADMIN, RISK_OWNER},
    "erm.obligations.manage":    {SUPER_ADMIN, RISK_OWNER, COMPLIANCE_MGR, DPO},
    "erm.assessment.manage":     {SUPER_ADMIN, RISK_OWNER, COMPLIANCE_MGR},
    "erm.ai.use":                {SUPER_ADMIN, RISK_OWNER, COMPLIANCE_MGR},
    "erm.report.generate":       {SUPER_ADMIN, RISK_OWNER, COMPLIANCE_MGR},
    "erm.kri.manage":            {SUPER_ADMIN, RISK_OWNER},
    "erm.statements.manage":     {SUPER_ADMIN, RISK_OWNER, COMPLIANCE_MGR},
    "erm.framework.manage":      {SUPER_ADMIN, RISK_OWNER},

    # ── ORM capabilities ──────────────────────────────────────────────
    "module.orm.access":         {SUPER_ADMIN, RISK_OWNER, COMPLIANCE_MGR, BCM_MANAGER, AUDIT_LEAD},
    "orm.event.log":             {SUPER_ADMIN, RISK_OWNER, COMPLIANCE_MGR, BCM_MANAGER, INCIDENT_COMMANDER, EMPLOYEE},
    "orm.event.manage":          {SUPER_ADMIN, RISK_OWNER, COMPLIANCE_MGR},
    "orm.kri.manage":            {SUPER_ADMIN, RISK_OWNER},
    "orm.report.generate":       {SUPER_ADMIN, RISK_OWNER, COMPLIANCE_MGR},
    "orm.ai.use":                {SUPER_ADMIN, RISK_OWNER, COMPLIANCE_MGR},
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _role_set(user: dict | None) -> set[str]:
    """Extract role keys from a user dict."""
    if not user:
        return set()
    roles = user.get("roles") or []
    return set(roles)


def has_role(user: dict | None, *role_keys: str) -> bool:
    """True if user holds any of the given roles."""
    return bool(_role_set(user) & set(role_keys))


def has_capability(user: dict | None, capability: str) -> bool:
    """True if any of the user's roles grants this capability."""
    allowed = CAPABILITIES.get(capability)
    if allowed is None:
        return False  # Unknown capability — deny
    return bool(_role_set(user) & allowed)


def any_capability(user: dict | None, caps: Iterable[str]) -> bool:
    return any(has_capability(user, c) for c in caps)


def user_modules(user: dict | None) -> list[str]:
    """Return list of module keys the user can access.

    Combines the role-based capability check with the org's licensed modules:
    a user only sees a module if their role grants access AND their tenant has
    a licence for it. Super admins bypass the licence check.
    """
    role_grants = []
    for mod in ("aria", "grid", "bcm", "sentinel", "erm", "orm"):
        if has_capability(user, f"module.{mod}.access"):
            role_grants.append(mod)
    if not user or user.get("is_super_admin"):
        return role_grants
    licensed = user.get("licensed_modules")
    if licensed is None:
        return role_grants
    licensed_set = set(licensed)
    return [m for m in role_grants if m in licensed_set]


def user_capabilities(user: dict | None) -> set[str]:
    """Return all capabilities the user holds."""
    roles = _role_set(user)
    caps = set()
    for cap, allowed_roles in CAPABILITIES.items():
        if roles & allowed_roles:
            caps.add(cap)
    return caps
