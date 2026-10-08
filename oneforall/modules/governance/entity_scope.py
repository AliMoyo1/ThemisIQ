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


# (module, type) -> rule. Capabilities are the ones the module's list and detail routes require.
_KINDS = {
    ("aria", "control"):      _Kind("aria", "module.aria.access"),
    ("aria", "document"):     _Kind("aria", "module.aria.access"),     # org and legacy rules: document_scope_sql
    ("evidence", "item"):     _Kind("", ""),                           # org and unit rules: evidence_scope_sql
    ("sentinel", "ropa"):     _Kind("sentinel", "module.sentinel.access", "business_unit_id"),
    ("sentinel", "breach"):   _Kind("sentinel", "sentinel.breach.manage", "business_unit_id"),
    ("sentinel", "dpia"):     _Kind("sentinel", "sentinel.dpia.manage", "business_unit_id"),
    ("sentinel", "dsr"):      _Kind("sentinel", "sentinel.dsr.manage", "business_unit_id"),
    ("sentinel", "vendor"):   _Kind("sentinel", "sentinel.vendor.manage"),
    ("grid", "audit"):        _Kind("grid", "module.grid.access", "business_unit_id"),
    ("grid", "nc"):           _Kind("grid", "grid.nc.manage", via_audit=True),
    ("grid", "vendor"):       _Kind("grid", "grid.vendor.manage"),
    ("bcm", "plan"):          _Kind("bcm", "module.bcm.access", "business_unit_id"),
    ("bcm", "incident"):      _Kind("bcm", "module.bcm.access", "business_unit_id"),
    ("bcm", "vendor"):        _Kind("bcm", "module.bcm.access"),
    ("erm", "risk"):          _Kind("erm", "erm.risk.view", "business_unit_id"),
    ("erm", "obligation"):    _Kind("erm", "module.erm.access"),
    ("platform", "risk"):     _Kind("erm", "erm.risk.view"),           # the register behind ERM and ORM
    ("orm", "event"):         _Kind("orm", "module.orm.access", "business_unit_id"),
    ("orm", "kri"):           _Kind("orm", "module.orm.access"),
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
