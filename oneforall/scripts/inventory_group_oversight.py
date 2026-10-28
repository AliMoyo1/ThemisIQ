#!/usr/bin/env python3
"""Read-only inventory for plans 19 and 20 (group oversight across tenants), slice G0.

It answers, for every tenant on the server:
  1. which organizations and licenses exist, and how many people use each;
  2. how each tenant's business-unit tree looks (are the subsidiaries units or separate organizations);
  3. where personal data actually sits: for a fixed list of columns, how many rows hold a value;
  4. how many Evidence Vault items have no business unit (visible to the whole organization) and how many of those
     mention an organization or unit name, which are candidates for narrowing;
  5. how many evidence families and versions exist (a family is a root item; versions chain by parent_id).

The command has no write mode. It prints counts and organization or business-unit names only. It never prints a
person's name, an email address, a record title, a file name, document content, a connection string or an
environment value. Every statement is a SELECT and each tenant is read inside a READ ONLY transaction.

Run on the server as root from /project/oneforall so the production environment file can be read:
    .venv/bin/python3 scripts/inventory_group_oversight.py
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# Columns that can hold a person's data, by table. Only the count of rows holding a value is reported.
PERSONAL_COLUMNS = {
    "users": ("full_name", "email"),
    "people_directory": ("full_name", "email", "phone"),
    "sentinel_dsr": ("requester_name", "requester_email"),
    "sentinel_consent": ("subject_id", "subject_name", "subject_email"),
    "sentinel_training": ("staff_name", "staff_email"),
    "sentinel_controllers": ("contact_name", "contact_email", "controller_phone", "dpo_name", "dpo_email", "dpo_phone"),
    "sentinel_vendors": ("contact_name", "contact_email"),
    "bcm_vendors": ("contact_name", "contact_email", "contact_phone"),
    "grid_vendors": ("contact_name", "contact_email"),
    "canonical_vendors": ("contact_name", "contact_email"),
    "bcm_contact_nodes": ("name", "email", "phone", "mobile"),
    "bcm_training_attestations": ("user_name", "user_email", "signature", "ip"),
    "grid_remote_participants": ("external_name", "external_email"),
    "grid_share_links": ("auditor_email",),
    "grid_digest_subscriptions": ("email", "name"),
    "email_reminders": ("recipient_email",),
    "audit_log": ("username", "ip_address"),
    "sessions": ("ip_address",),
    "aria_ask_log": ("username",),
    "ai_use_intake_requests": ("requester",),
    "ai_external_responses": ("requester",),
    "demo_requests": ("name", "email", "ip_address"),
}

# Free text that a person can fill with anything, including names and case details.
FREE_TEXT_COLUMNS = {
    "sentinel_dsr": ("description", "response_notes", "ai_draft"),
    "sentinel_breaches": ("description", "cause", "impact", "containment", "root_cause", "corrective_actions", "lessons_learned",
                          "remediation", "ai_analysis", "ai_assessment", "notes"),
    "sentinel_consent": ("notes",),
    "sentinel_dpias": ("description", "notes", "consult_notes"),
    "sentinel_ropa": ("notes",),
    "bcm_incidents": ("description", "impact"),
    "bcm_plans": ("content", "description"),
    "grid_non_conformances": ("description", "root_cause", "corrective_action", "preventive_action", "verification_notes"),
    "erm_enterprise_risks": ("description", "risk_context"),
    "orm_events": ("description", "root_cause", "corrective_action", "preventive_action"),
    "aria_documents": ("body",),
    "evidence_items": ("description",),
    "task_board": ("description",),
    "notifications": ("message",),
}

# Tables the group view would count; only the row count is reported.
LEVEL_ONE_TABLES = (
    "controls", "aria_documents", "erm_enterprise_risks", "sentinel_breaches", "sentinel_dsr", "sentinel_ropa",
    "sentinel_dpias", "bcm_incidents", "bcm_plans", "bcm_exercises", "grid_audits", "grid_non_conformances",
    "orm_events", "evidence_items", "task_board",
)

IDENT = re.compile(r"[a-z_][a-z0-9_]*")
_TOKEN_MIN = 4


def _ident(name: str) -> str:
    if not IDENT.fullmatch(name):
        raise ValueError("unexpected identifier")
    return name


def existing_columns(db, schema: "str | None", sqlite: bool) -> "dict[str, set[str]]":
    """{table: {columns}} for the tables this inventory reads."""
    wanted = set(PERSONAL_COLUMNS) | set(FREE_TEXT_COLUMNS) | set(LEVEL_ONE_TABLES) | {
        "business_units", "evidence_items", "organizations", "licenses"}
    found: dict[str, set[str]] = {}
    if sqlite:
        for table in sorted(wanted):
            rows = db.execute(f"PRAGMA table_info({_ident(table)})").fetchall()
            if rows:
                found[table] = {r["name"] for r in rows}
        return found
    rows = db.execute(
        "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema=%s", (schema,)).fetchall()
    for r in rows:
        if r["table_name"] in wanted:
            found.setdefault(r["table_name"], set()).add(r["column_name"])
    return found


def _count(db, sql: str, params=()) -> int:
    if not sql.lstrip().upper().startswith("SELECT"):
        raise ValueError("read only: SELECT statements only")
    row = db.execute(sql, params).fetchone()
    return int(row["n"] or 0)


def unit_tree(db, cols) -> dict:
    """Shape of the business unit tree, with unit names (organizational structure, not personal data)."""
    if not {"id", "name", "parent_id"} <= cols.get("business_units", set()):
        return {"available": False}
    rows = db.execute("SELECT id, name, parent_id FROM business_units ORDER BY id").fetchall()
    by_id = {r["id"]: r for r in rows}

    def depth(row, seen=()):
        parent = row["parent_id"]
        if parent is None or parent not in by_id or parent in seen:
            return 0
        return 1 + depth(by_id[parent], seen + (row["id"],))

    return {"available": True, "units": len(rows), "roots": [r["name"] for r in rows if r["parent_id"] is None],
            "max_depth": max((depth(r) for r in rows), default=0),
            "names": [r["name"] for r in rows]}


def personal_columns(db, cols) -> dict:
    """{table.column: rows holding a value} for the fixed list of personal data columns that exist."""
    out = {}
    for table, columns in PERSONAL_COLUMNS.items():
        for column in columns:
            if column in cols.get(table, set()):
                t, c = _ident(table), _ident(column)
                out[f"{t}.{c}"] = _count(db, f"SELECT COUNT(*) AS n FROM {t} WHERE {c} IS NOT NULL AND {c} <> ''")
    return out


def free_text_columns(db, cols) -> dict:
    out = {}
    for table, columns in FREE_TEXT_COLUMNS.items():
        for column in columns:
            if column in cols.get(table, set()):
                t, c = _ident(table), _ident(column)
                out[f"{t}.{c}"] = _count(db, f"SELECT COUNT(*) AS n FROM {t} WHERE {c} IS NOT NULL AND {c} <> ''")
    return out


def row_counts(db, cols) -> dict:
    return {t: _count(db, f"SELECT COUNT(*) AS n FROM {_ident(t)}") for t in LEVEL_ONE_TABLES if t in cols}


def name_tokens(names) -> "list[str]":
    """Lower case words of organization and unit names that could appear in a document title."""
    tokens = set()
    for name in names:
        for token in re.findall(r"[A-Za-z0-9]+", str(name or "")):
            if len(token) >= _TOKEN_MIN:
                tokens.add(token.lower())
    return sorted(tokens)


def evidence_exposure(db, cols, tokens) -> dict:
    """Items with no business unit (visible to the whole organization), and how many mention a name token."""
    have = cols.get("evidence_items", set())
    if not {"id", "business_unit_id"} <= have:
        return {"available": False}
    out = {"available": True, "items": _count(db, "SELECT COUNT(*) AS n FROM evidence_items"),
           "no_unit": _count(db, "SELECT COUNT(*) AS n FROM evidence_items WHERE business_unit_id IS NULL")}
    if "parent_id" in have:
        out["families"] = _count(db, "SELECT COUNT(*) AS n FROM evidence_items WHERE parent_id IS NULL")
        out["versions_in_chains"] = _count(db, "SELECT COUNT(*) AS n FROM evidence_items WHERE parent_id IS NOT NULL")
    text_cols = [c for c in ("title", "file_name") if c in have]
    if text_cols:
        by_token = {}
        for token in tokens:
            like = "%" + token.replace("%", "").replace("_", "") + "%"
            clause = " OR ".join(f"LOWER({_ident(c)}) LIKE %s" for c in text_cols)
            n = _count(db, f"SELECT COUNT(*) AS n FROM evidence_items WHERE business_unit_id IS NULL AND ({clause})",
                       tuple(like for _ in text_cols))
            if n:
                by_token[token] = n
        out["no_unit_mentioning_a_name"] = by_token
    return out


def inventory_one(db, schema: "str | None" = None, sqlite: bool = True, extra_names=()) -> dict:
    cols = existing_columns(db, schema, sqlite)
    tree = unit_tree(db, cols)
    names = list(extra_names) + (tree.get("names") or [])
    return {"units": tree, "row_counts": row_counts(db, cols), "personal": personal_columns(db, cols),
            "free_text": free_text_columns(db, cols), "evidence": evidence_exposure(db, cols, name_tokens(names))}


def organizations(db, cols) -> "list[dict]":
    if "organizations" not in cols:
        return []
    out = []
    for o in db.execute("SELECT id, name, slug, status, plan FROM organizations ORDER BY id").fetchall():
        entry = {"id": o["id"], "name": o["name"], "slug": o["slug"], "status": o["status"], "plan": o["plan"],
                 "licenses": []}
        if "licenses" in cols:
            for lic in db.execute(
                    "SELECT module_keys, seats, valid_from, valid_until FROM licenses WHERE org_id=%s ORDER BY id",
                    (o["id"],)).fetchall():
                entry["licenses"].append({"modules": lic["module_keys"], "seats": lic["seats"],
                                          "from": lic["valid_from"], "until": lic["valid_until"]})
        out.append(entry)
    return out


def print_inventory(label: str, data: dict) -> None:
    tree = data["units"]
    print(f"== {label}")
    if tree.get("available"):
        print(f"  business units: {tree['units']} (depth {tree['max_depth']}); roots: {', '.join(map(str, tree['roots'])) or 'none'}")
        if tree["units"] <= 60:
            print(f"  unit names: {', '.join(map(str, tree['names']))}")
    else:
        print("  business units: unavailable")
    print("  row counts: " + (", ".join(f"{k}={v}" for k, v in data["row_counts"].items()) or "none"))
    pers = data["personal"]
    print("  personal data columns holding a value:")
    for key, n in pers.items():
        if n:
            print(f"    {key}: {n}")
    print("    (columns not listed are empty or absent)")
    print("  free text columns holding a value:")
    for key, n in data["free_text"].items():
        if n:
            print(f"    {key}: {n}")
    ev = data["evidence"]
    if ev.get("available"):
        print(f"  evidence: items={ev['items']} no_unit={ev['no_unit']} families={ev.get('families', 'n/a')} "
              f"versions_in_chains={ev.get('versions_in_chains', 'n/a')}")
        for token, n in (ev.get("no_unit_mentioning_a_name") or {}).items():
            print(f"    no-unit items whose title or file name mentions '{token}': {n}")
    else:
        print("  evidence: unavailable")


def main() -> int:
    from deploy import DEFAULT_ENV_FILE, parse_env_file  # noqa: E402

    production_env = parse_env_file(DEFAULT_ENV_FILE)
    for key in ("DATABASE_URL", "PGPASSWORD_FILE", "PGPASSWORD"):
        value = production_env.get(key)
        if value:
            os.environ.setdefault(key, value)
    from config import settings  # noqa: E402
    from database import get_db_bypass_rls  # noqa: E402

    if not settings.is_postgres():
        print("PostgreSQL connection is required; no inventory was run.", file=sys.stderr)
        return 2
    db = get_db_bypass_rls()
    try:
        db.execute("SET TRANSACTION READ ONLY")
        cols = existing_columns(db, "public", sqlite=False)
        orgs = organizations(db, cols)
        print("ORGANIZATIONS (public registry)")
        for o in orgs:
            print(f"  org {o['id']}: {o['name']} (slug {o['slug']}, {o['status']}, plan {o['plan']})")
            for lic in o["licenses"]:
                print(f"    license: modules={lic['modules']} seats={lic['seats']} from={lic['from']} until={lic['until']}")
        users = db.execute(
            "SELECT org_id, COUNT(*) AS n FROM users WHERE is_active=1 GROUP BY org_id ORDER BY org_id").fetchall()
        print("  active users by organization id: " + ", ".join(f"{u['org_id']}={u['n']}" for u in users))
        schemas = ["public"] + [r["schema_name"] for r in db.execute(
            "SELECT schema_name FROM information_schema.schemata WHERE schema_name LIKE 'tenant_%%' ORDER BY schema_name"
        ).fetchall()]
        db.rollback()
        org_names = [o["name"] for o in orgs]
        for schema in schemas:
            if schema != "public" and not re.fullmatch(r"tenant_[a-z0-9_]+", schema):
                raise RuntimeError("Unexpected tenant schema name; inventory stopped before querying it.")
            slug = "public" if schema == "public" else schema[len("tenant_"):]
            db.set_tenant(slug)
            db.execute("SET TRANSACTION READ ONLY")
            data = inventory_one(db, schema, sqlite=False, extra_names=org_names)
            print_inventory(f"schema {schema}", data)
            db.rollback()
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
