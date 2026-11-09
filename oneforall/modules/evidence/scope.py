"""Shared evidence_items visibility and search predicates. Every read path must use these."""
from core.sql_like import ci_like, like_pattern
from modules.governance.data_service import bu_scope_ids

_SEARCH_COLUMNS = ("title", "file_name", "tags", "description")


def _alias(alias: str) -> str:
    if not alias.isidentifier():
        raise ValueError("alias must be a plain SQL identifier")
    return alias


def _kinds_sql(link: str, kinds: dict) -> tuple[str, list]:
    """OR of (module, entity types) pairs for a link alias; kinds is module -> set of entity types."""
    parts, params = [], []
    for module in sorted(kinds):
        types = sorted(kinds[module])
        parts.append(f"({link}.module = %s AND {link}.entity_type IN ({','.join(['%s'] * len(types))}))")
        params.extend([module, *types])
    return "(" + " OR ".join(parts) + ")", params


# Modules whose records hold personal data or sensitive AI system detail: Privacy (breaches, DPIAs, data subject
# requests, processing records, privacy vendor reviews) and AI impact assessments, which are still stored under it.
# Other modules' links do not restrict a file, because people answer audit questions and evidence requests from My
# Work without that module's licence.
RESTRICTING_MODULES = ("sentinel",)


def _module_rule_sql(user: dict, a: str) -> tuple[str, list]:
    """The module rule: a file linked to a restricting kind of record the user may not open is visible to them only when
    they may open some other kind it is linked to, or uploaded it. A file with no such link follows the Vault's own
    scope. A link to a kind the registry does not know neither grants nor hides. Empty when nothing is restricted."""
    from modules.governance.entity_scope import kinds_by_access  # entity_scope imports this module
    allowed, denied = kinds_by_access(user)
    denied = {module: types for module, types in denied.items() if module in RESTRICTING_MODULES}
    if not denied:
        return "", []
    denied_sql, denied_params = _kinds_sql("evl_rule", denied)
    rule = (f"NOT EXISTS (SELECT 1 FROM evidence_links evl_rule WHERE evl_rule.evidence_id = {a}.id "
            f"AND evl_rule.deleted_at IS NULL AND {denied_sql})")
    params = list(denied_params)
    if allowed:
        allowed_sql, allowed_params = _kinds_sql("evl_rule", allowed)
        rule += (f" OR EXISTS (SELECT 1 FROM evidence_links evl_rule WHERE evl_rule.evidence_id = {a}.id "
                 f"AND evl_rule.deleted_at IS NULL AND {allowed_sql})")
        params.extend(allowed_params)
    if user.get("id"):
        rule += f" OR {a}.uploaded_by = %s"
        params.append(user["id"])
    return f"({rule})", params


def evidence_scope_sql(user: dict, alias: str = "e") -> tuple[str, list]:
    """WHERE fragment and params for the rows this user may see. NULL business unit means organization wide, and the
    module rule (`_module_rule_sql`) hides a file linked to Privacy records the user may not open."""
    a = _alias(alias)
    if user.get("is_super_admin"):
        return "(1 = 1)", []
    org_id = user.get("org_id")
    if not org_id:
        return "(1 = 0)", []
    scope = bu_scope_ids(user) or []
    if not scope:
        where, params = f"{a}.org_id = %s AND {a}.business_unit_id IS NULL", [org_id]
    else:
        marks = ",".join(["%s"] * len(scope))
        where = f"{a}.org_id = %s AND ({a}.business_unit_id IS NULL OR {a}.business_unit_id IN ({marks}))"
        params = [org_id, *scope]
    rule, rule_params = _module_rule_sql(user, a)
    if rule:
        where += f" AND {rule}"
        params.extend(rule_params)
    return f"({where})", params


def current_library_sql(alias: str = "e") -> str:
    """Default views hide archived and superseded rows; they are reachable only through explicit views."""
    return f"{_alias(alias)}.status NOT IN ('archived', 'superseded')"


def evidence_search_sql(term: str, alias: str = "e") -> tuple[str, list]:
    """Match metadata or text from the exact indexed version of a visible evidence row."""
    a = _alias(alias)
    if not term or not term.strip():
        return "(1 = 1)", []
    clause = " OR ".join(ci_like(f"{a}.{col}") for col in _SEARCH_COLUMNS)
    text_match = ci_like("ti.content_text")
    clause += (f" OR EXISTS (SELECT 1 FROM evidence_text_index ti WHERE ti.evidence_id = {a}.id "
               f"AND ti.status = 'indexed' AND ti.file_hash = {a}.file_hash "
               f"AND COALESCE(ti.org_id,-1) = COALESCE({a}.org_id,-1) "
               f"AND COALESCE(ti.business_unit_id,-1) = COALESCE({a}.business_unit_id,-1) "
               f"AND {text_match})")
    return f"({clause})", [like_pattern(term)] * (len(_SEARCH_COLUMNS) + 1)
