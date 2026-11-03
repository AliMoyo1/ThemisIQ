#!/usr/bin/env python3
"""Measure Evidence Vault search speed at 500 and 5,000 files (plan 23, P3; plan 19 acceptance).

Seeds a disposable organization per size, then times the Vault's own library code (`_library_page`, the code behind
/evidence/api/items and Find evidence) for a person confined to one business unit. Each query is checked for the right
answer before it is timed, so a fast wrong answer cannot pass: the known item is found, nothing from a hidden unit or
another organization appears.

Never point this at a real database. It refuses unless the database is a throwaway one:
  SQLite (default): a new file in a temporary folder.
  PostgreSQL: SPEED_DATABASE_URL naming a database whose name starts with themisiq_test_. The app's tables are created
  as that (superuser) login, each organization gets its own tenant schema as in production, and every query is then run
  as an ordinary login role that is subject to row level security (NOSUPERUSER, NOBYPASSRLS).

Run from oneforall/:  python scripts/measure_vault_search.py [--runs 40] [--sizes 500 5000] [--json out.json]
"""
from __future__ import annotations

import argparse
import json
import math
import os
import secrets
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

PG_URL = os.environ.get("SPEED_DATABASE_URL", "")
if PG_URL:
    if not urlsplit(PG_URL).path.lstrip("/").startswith("themisiq_test_"):
        sys.exit("SPEED_DATABASE_URL must name a throwaway database whose name starts with themisiq_test_")
    os.environ["DATABASE_URL"] = PG_URL
else:
    os.environ["DATABASE_URL"] = ""
os.environ.setdefault("SECRET_KEY", secrets.token_hex(32))

import database  # noqa: E402
from config import settings  # noqa: E402

TOPICS = ("Access control policy", "Incident response plan", "Supplier due diligence", "Data retention schedule",
          "Business continuity test", "Board minutes", "Training record", "Risk assessment")
FILLER = ("The organisation keeps this record to show how the requirement is met in practice. Owners review it on the "
          "agreed cycle and record any change, the reason for it and who approved it. ") * 8
PROBE_ROLE = "themisiq_speed_probe"


def _p(values, q):
    ordered = sorted(values)
    return ordered[max(0, math.ceil(q * len(ordered)) - 1)]


def _seed_org(name, slug, size, *, with_hidden):
    """One organization with a unit the viewer sees and, when asked, a unit they do not. Returns (org, unit, viewer)."""
    db = database.get_db_bypass_rls()
    try:
        org = database.insert_returning_id(
            db, "INSERT INTO organizations (name, slug, plan, status) VALUES (%s,%s,'enterprise','active')", (name, slug))
        db.execute("INSERT INTO licenses (org_id, module_keys, seats) VALUES (%s,'aria,bcm,erm,grid,orm,sentinel',99)",
                   (org,))
        db.commit()
    finally:
        db.close()
    database.provision_tenant_schema(slug)
    with database.tenant_context(org, slug, is_super_admin=True):
        db = database.get_db()
        try:
            unit = database.insert_returning_id(
                db, "INSERT INTO business_units (name, is_active) VALUES ('Seen unit',1)", ())
            hidden = database.insert_returning_id(
                db, "INSERT INTO business_units (name, is_active) VALUES ('Hidden unit',1)", ())
            viewer = database.insert_returning_id(
                db, "INSERT INTO users (username, email, full_name, password_hash, org_id, business_unit_id, is_active) "
                    "VALUES (%s,%s,'Speed viewer','x',%s,%s,1)", (slug + "_viewer", slug + "@example.invalid", org, unit))
            db.execute("INSERT INTO user_roles (user_id, role_key) VALUES (%s,'compliance_manager')", (viewer,))
            rows = [(i, unit) for i in range(size)]
            if with_hidden:
                rows += [(size + i, hidden) for i in range(size // 5)]
            for i, owner_unit in rows:
                topic = TOPICS[i % len(TOPICS)]
                digest = secrets.token_hex(32)
                item = database.insert_returning_id(
                    db, "INSERT INTO evidence_items (title, description, file_name, file_hash, tags, category, status, "
                        "org_id, business_unit_id, uploaded_by) VALUES (%s,%s,%s,%s,%s,'general','current',%s,%s,%s)",
                    (f"{topic} {i:05d}", f"{topic} kept for the {2020 + i % 7} cycle.", f"DOC-{i:05d}.pdf", digest,
                     "policy,2026" if i % 3 == 0 else "record", org, owner_unit, viewer))
                if i % 3 == 0:
                    db.execute(
                        "INSERT INTO evidence_text_index (evidence_id, org_id, business_unit_id, file_hash, "
                        "indexer_version, status, content_text) VALUES (%s,%s,%s,%s,'speed','indexed',%s)",
                        (item, org, owner_unit, digest, FILLER + f" Reference clause-{i:05d}-zeta."))
            db.commit()
        finally:
            db.close()
    return org, unit, viewer


def _as_probe_role():
    """Run every later query as an ordinary login role under row level security, as the application does."""
    password = secrets.token_urlsafe(18)
    db = database.get_db_bypass_rls()
    try:
        db.execute("DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '" + PROBE_ROLE + "') THEN "
                   "CREATE ROLE " + PROBE_ROLE + " LOGIN NOSUPERUSER NOBYPASSRLS; END IF; END $$")
        db.execute(f"ALTER ROLE {PROBE_ROLE} WITH LOGIN PASSWORD %s", (password,))
        schemas = [r[0] for r in db.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname = 'public' OR nspname LIKE 'tenant_%%'").fetchall()]
        for schema in schemas:
            db.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO {PROBE_ROLE}')
            db.execute(f'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA "{schema}" TO {PROBE_ROLE}')
            db.execute(f'GRANT USAGE ON ALL SEQUENCES IN SCHEMA "{schema}" TO {PROBE_ROLE}')
        db.commit()
    finally:
        db.close()
    database._pg_pool.closeall()
    database._pg_pool = None
    parts = urlsplit(PG_URL)
    netloc = f"{PROBE_ROLE}:{password}@{parts.hostname}" + (f":{parts.port}" if parts.port else "")
    settings.DATABASE_URL = urlunsplit(parts._replace(netloc=netloc))
    database._read_pg_password = lambda: ""
    check = database.get_db()
    try:
        row = check.execute("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user").fetchone()
        assert not row[0] and not row[1], "the measuring role must be subject to row level security"
    finally:
        check.close()


def _queries(size):
    known, words, text = size // 3 * 2, size // 2, (size // 3) * 3 - 3
    return [
        ("Browse, first page", {}, None),
        ("Metadata search, common word", {"q": "policy"}, None),
        ("Metadata search, nothing matches", {"q": "zzqx-nothing"}, None),
        ("Known item by reference", {"q": f"DOC-{known:05d}"}, f"DOC-{known:05d}.pdf"),
        ("Known item by words (Find evidence)", {"words": f"Supplier {words - words % 8 + 2:05d}"},
         f"DOC-{words - words % 8 + 2:05d}.pdf"),
        ("Known item by file text", {"q": f"clause-{text:05d}-zeta"}, f"DOC-{text:05d}.pdf"),
    ]


def measure(sizes, runs):
    from modules.evidence.routes import _library_page
    plan = []
    for size in sizes:
        slug = f"speed_{size}_{secrets.token_hex(3)}"
        org, unit, viewer = _seed_org(f"Speed {size}", slug, size, with_hidden=True)
        # Another organization with the same titles: its rows must never be returned.
        _seed_org(f"Speed other {size}", slug + "_other", size, with_hidden=False)
        plan.append((size, org, slug, unit, viewer))
    if PG_URL:
        _as_probe_role()
    results = []
    for size, org, slug, unit, viewer in plan:
        user = {"id": viewer, "org_id": org, "business_unit_id": unit, "roles": ["compliance_manager"],
                "is_super_admin": False, "username": slug + "_viewer"}
        for label, qp, expect in _queries(size):
            with database.tenant_context(org, slug, is_super_admin=False):
                page = _library_page(user, qp)
                names = [item.get("file_name") for item in page["items"]]
                assert all(item.get("org_id") in (org, None) for item in page["items"]), "another organization leaked"
                assert all(item.get("business_unit_id") in (unit, None) for item in page["items"]), "a hidden unit leaked"
                if expect:
                    assert names and names[0] == expect, (label, expect, names[:3])
                if label.startswith("Browse"):
                    assert page["total"] == size, (label, page["total"])
                for _ in range(3):
                    _library_page(user, qp)
                timings = []
                for _ in range(runs):
                    start = time.perf_counter()
                    _library_page(user, qp)
                    timings.append((time.perf_counter() - start) * 1000)
            results.append({"files": size, "query": label, "matches": page["total"], "runs": runs,
                            "p50_ms": round(_p(timings, 0.50), 1), "p95_ms": round(_p(timings, 0.95), 1),
                            "max_ms": round(max(timings), 1)})
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--runs", type=int, default=40)
    parser.add_argument("--sizes", type=int, nargs="+", default=[500, 5000])
    parser.add_argument("--json")
    args = parser.parse_args()
    if not PG_URL:
        database._DB_PATH = str(Path(tempfile.mkdtemp(prefix="vault_speed_")) / "speed.db")
    database.init_db()
    engine = "PostgreSQL, ordinary role under row level security" if PG_URL else "SQLite"
    results = measure(args.sizes, args.runs)
    print(f"Evidence Vault search speed ({engine}, {args.runs} timed runs per query)\n")
    print("| Files seen | Query | Matches | p50 ms | p95 ms | max ms |")
    print("|---|---|---|---|---|---|")
    for r in results:
        print(f"| {r['files']} | {r['query']} | {r['matches']} | {r['p50_ms']} | {r['p95_ms']} | {r['max_ms']} |")
    if args.json:
        Path(args.json).write_text(json.dumps({"engine": engine, "results": results}, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
