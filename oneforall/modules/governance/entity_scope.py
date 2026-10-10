"""Which records of each kind a user may see, for the features that read across modules.

Topbar search, Related Items and the cross-module vendor views must never show more than the
owning module's own list and detail routes do. That means the same capability, and the same
business unit rule: a NULL unit is organization wide, anything else has to sit inside the
caller's own subtree (so a parent unit sees its children and a child does not see its parent).
One definition here so those features cannot drift apart from the modules. An unknown kind is
invisible.

The Evidence Vault keeps its own resolver (modules/evidence/routes.py _target_scope_sql); this
is the part that search and Related Items share, to be folded together with it later.
"""
from typing import NamedTuple

from core.rbac import has_capability, user_modules
from modules.aria.policy_access import document_scope_sql
from modules.evidence.scope import evidence_scope_sql
from modules.governance.data_service import bu_scope_ids


class _Kind(NamedTuple):
    module: str               # licence module the capability belongs to ("" when none)
    capability: str           # what the owning module's own routes require ("" when only a sign-in)
    bu: str = ""              # business unit column ("" when the table has none)
    via_audit: bool = False   # no unit of its own: follows its grid audit's
    table: str = ""           # set on every kind that has (or follows) a unit, so record_unit can read it


# (module, type) -> rule. Capabilities are the ones the module's list and detail routes require.
_KINDS = {
    ("aria", "control"):      _Kind("aria", "module.aria.access"),
    # org and legacy rules: document_scope_sql, which is also why `bu` is not what limits it
    ("aria", "document"):     _Kind("aria", "module.aria.access", "business_unit_id", table="aria_documents"),
    ("evidence", "item"):     _Kind("", ""),                           # org and unit rules: evidence_scope_sql
    ("sentinel", "ropa"):     _Kind("sentinel", "module.sentinel.access", "business_unit_id", table="sentinel_ropa"),
    ("sentinel", "breach"):   _Kind("sentinel", "sentinel.breach.manage", "business_unit_id", table="sentinel_breaches"),
    ("sentinel", "dpia"):     _Kind("sentinel", "sentinel.dpia.manage", "business_unit_id", table="sentinel_dpias"),
    ("sentinel", "dsr"):      _Kind("sentinel", "sentinel.dsr.manage", "business_unit_id", table="sentinel_dsr"),
    ("sentinel", "vendor"):   _Kind("sentinel", "sentinel.vendor.manage"),
    ("grid", "audit"):        _Kind("grid", "module.grid.access", "business_unit_id", table="grid_audits"),
    ("grid", "nc"):           _Kind("grid", "grid.nc.manage", via_audit=True, table="grid_non_conformances"),
    ("grid", "control"):      _Kind("grid", "module.grid.access", via_audit=True, table="grid_controls"),
    ("grid", "vendor"):       _Kind("grid", "grid.vendor.manage"),
    ("bcm", "plan"):          _Kind("bcm", "module.bcm.access", "business_unit_id", table="bcm_plans"),
    ("bcm", "incident"):      _Kind("bcm", "module.bcm.access", "business_unit_id", table="bcm_incidents"),
    ("bcm", "exercise"):      _Kind("bcm", "module.bcm.access", "business_unit_id", table="bcm_exercises"),
    ("bcm", "vendor"):        _Kind("bcm", "module.bcm.access"),
    ("erm", "risk"):          _Kind("erm", "erm.risk.view", "business_unit_id", table="erm_enterprise_risks"),
    ("erm", "obligation"):    _Kind("erm", "module.erm.access"),
    # The register behind ERM and ORM, and the SLA clocks and workflow instances: all three store the unit
    # of the record they are about, or of whoever created them (see owner_unit). SLA clocks and workflow
    # instances need only a sign-in, like the Workflows module itself.
    ("platform", "risk"):     _Kind("erm", "erm.risk.view", "business_unit_id", table="risk_register"),
    ("platform", "sla"):      _Kind("", "", "business_unit_id", table="sla_instances"),
    ("platform", "workflow"): _Kind("", "", "business_unit_id", table="workflow_instances"),
    ("orm", "event"):         _Kind("orm", "module.orm.access", "business_unit_id", table="orm_events"),
    ("orm", "kri"):           _Kind("orm", "module.orm.access"),
    ("platform", "task"):     _Kind("", "", "business_unit_id", table="task_board"),
}


def may_view_kind(user: dict, key: tuple) -> bool:
    """True when the user holds what the owning module requires to open records of this kind."""
    kind = _KINDS.get(key)
    if kind is None:
        return False
    if kind.capability and not has_capability(user, kind.capability):
        return False
    return not kind.module or kind.module in user_modules(user)


def entity_scope_sql(key: tuple, user: dict, alias: str = "") -> tuple[str, list]:
    """Parenthesized WHERE fragment and params for the rows of `key` this user may see.

    "(1 = 0)" when the user lacks the capability or the kind is unknown. `alias` is the table
    alias used in the query ("" when the query has a single unaliased table)."""
    if alias and not alias.isidentifier():
        raise ValueError("alias must be a plain SQL identifier")
    kind = _KINDS.get(key)
    if kind is None or not may_view_kind(user, key):
        return "(1 = 0)", []
    if key == ("aria", "document"):
        return document_scope_sql(user)  # unqualified columns, like the module's own queries
    if key == ("evidence", "item"):
        return evidence_scope_sql(user, alias or "evidence_items")
    if not (kind.bu or kind.via_audit):
        return "(1 = 1)", []
    scope = bu_scope_ids(user)
    if scope is None:  # super admin
        return "(1 = 1)", []
    prefix = f"{alias}." if alias else ""
    marks = ",".join(["%s"] * len(scope))
    if kind.via_audit:
        return (
            f"({prefix}audit_id IN (SELECT id FROM grid_audits "
            f"WHERE business_unit_id IS NULL OR business_unit_id IN ({marks})))",
            list(scope),
        )
    column = prefix + kind.bu
    return f"({column} IS NULL OR {column} IN ({marks}))", list(scope)


# ── Who owns a new row ──────────────────────────────────────────────────────

# Names callers use for a registered kind: the event handlers say non_conformance and enterprise_risk,
# the workflow form offers policy. A name nothing registers is simply unknown.
_TYPE_ALIASES = {"non_conformance": "nc", "enterprise_risk": "risk", "policy": "document"}
_MAX_ID = 2 ** 31 - 1  # an INTEGER primary key; a larger number is not a record and would only raise in PostgreSQL


def record_unit(db, module, entity_type, entity_id, user=None) -> tuple[bool, "int | None"]:
    """(known, business_unit_id) of the record a platform risk, SLA clock or workflow instance is about.

    `known` is False when the reference names nothing we can place: a kind that is not registered, no usable
    id, a row that is not there, or (when `user` is given) a record that user cannot open. A record that is
    organization wide is (True, None). Nothing here raises for a bad reference, because the workflow form
    takes a free-text type and an optional id and must keep working.
    """
    module = str(module or "").strip().lower()
    entity_type = str(entity_type or "").strip().lower()
    key = (module, _TYPE_ALIASES.get(entity_type, entity_type))
    kind = _KINDS.get(key)
    if kind is None or not kind.table or not (kind.bu or kind.via_audit):
        return False, None
    try:
        record_id = int(entity_id)
    except (TypeError, ValueError):
        return False, None
    if not 0 < record_id <= _MAX_ID:
        return False, None
    scope, params = ("(1 = 1)", []) if user is None else entity_scope_sql(key, user, "t")
    if kind.via_audit:
        source, unit = f"{kind.table} t JOIN grid_audits a ON a.id = t.audit_id", "a.business_unit_id"
    else:
        source, unit = f"{kind.table} t", f"t.{kind.bu}"
    row = db.execute(f"SELECT {unit} FROM {source} WHERE t.id = %s AND {scope}", [record_id, *params]).fetchone()
    return (True, row[0]) if row else (False, None)


def owner_unit(db, module, entity_type, entity_id, *, user=None, user_id=None) -> "int | None":
    """The business unit a new platform risk, SLA clock or workflow instance belongs to.

    The unit of the record it is about, when that is a registered kind (and, if `user` is given, one that
    user can open); otherwise the unit of whoever created it; otherwise None, which is organization wide.
    Pass `user` from a request, so nobody can place a row in a unit they cannot see by naming its record.
    Pass `user_id` from a background handler, which acts for a user it has already authorized.
    """
    known, unit = record_unit(db, module, entity_type, entity_id, user)
    if known:
        return unit
    if user is not None:
        return user.get("business_unit_id") or None
    if user_id is None:
        return None
    row = db.execute("SELECT business_unit_id FROM users WHERE id = %s", (user_id,)).fetchone()
    return (row[0] or None) if row else None
