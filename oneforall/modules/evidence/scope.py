"""Shared evidence_items visibility and search predicates. Every read path must use these."""
from core.sql_like import ci_like, like_pattern
from modules.governance.data_service import bu_scope_ids

_SEARCH_COLUMNS = ("title", "file_name", "tags", "description")


def _alias(alias: str) -> str:
    if not alias.isidentifier():
        raise ValueError("alias must be a plain SQL identifier")
    return alias


def evidence_scope_sql(user: dict, alias: str = "e") -> tuple[str, list]:
    """WHERE fragment and params for the rows this user may see. NULL business unit means organization wide."""
    a = _alias(alias)
    if user.get("is_super_admin"):
        return "(1 = 1)", []
    org_id = user.get("org_id")
    if not org_id:
        return "(1 = 0)", []
    scope = bu_scope_ids(user) or []
    if not scope:
        return f"({a}.org_id = %s AND {a}.business_unit_id IS NULL)", [org_id]
    marks = ",".join(["%s"] * len(scope))
    return (
        f"({a}.org_id = %s AND ({a}.business_unit_id IS NULL OR {a}.business_unit_id IN ({marks})))",
        [org_id, *scope],
    )


def current_library_sql(alias: str = "e") -> str:
    """Default views hide archived and superseded rows; they are reachable only through explicit views."""
    return f"{_alias(alias)}.status NOT IN ('archived', 'superseded')"


def evidence_search_sql(term: str, alias: str = "e") -> tuple[str, list]:
    """Case-insensitive substring match over title, filename, tags and description. A blank term adds no constraint."""
    a = _alias(alias)
    if not term or not term.strip():
        return "(1 = 1)", []
    clause = " OR ".join(ci_like(f"{a}.{col}") for col in _SEARCH_COLUMNS)
    return f"({clause})", [like_pattern(term)] * len(_SEARCH_COLUMNS)
