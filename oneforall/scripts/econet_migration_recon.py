#!/usr/bin/env python3
"""
econet_migration_recon.py -- READ-ONLY reconnaissance for PLAN-31 (the
Ecocash / Econet Wireless / Omni -> "Econet Group" org consolidation).

Makes no changes whatsoever -- every query is a SELECT or COUNT. Reports:
  - every organization row (id, name, slug, status)
  - every tenant schema present in the database
  - user counts per organization
  - row counts for every non-empty table in every tenant schema
  - the full business_units tree in every schema, to reveal whether
    Ecocash/Econet Wireless/Omni already have internal sub-structure
    beyond their seeded root

Run from /project on the VPS:
    python3 oneforall/scripts/econet_migration_recon.py

Resolves DATABASE_URL the same way deploy.py does: environment first, then
/project/.env, then rebuilt directly from /project/secrets/pg_password.txt.
A plain root shell login does not have the systemd service's Environment=
vars, so the third path is the one that actually works when run by hand.
"""
import os
import sys

try:
    import psycopg2
except ImportError:
    print("psycopg2 not installed. Run: pip3 install psycopg2-binary --break-system-packages")
    sys.exit(1)

SECRETS_FILE = "/project/secrets/pg_password.txt"


def _resolve_database_url():
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    env_path = "/project/.env"
    if os.path.exists(env_path):
        for line in open(env_path):
            line = line.strip().strip('"').strip("'")
            if line.startswith("DATABASE_URL="):
                candidate = line.split("=", 1)[1].strip().strip('"').strip("'")
                if candidate:
                    return candidate

    if os.path.exists(SECRETS_FILE):
        pw = open(SECRETS_FILE).read().strip()
        return f"postgresql://themisiq:{pw}@localhost:5432/themisiq"

    return None


def main():
    database_url = _resolve_database_url()
    if not database_url:
        print("Could not resolve DATABASE_URL from the environment, /project/.env, "
              f"or {SECRETS_FILE}.")
        sys.exit(1)

    conn = psycopg2.connect(database_url)
    conn.set_session(readonly=True, autocommit=True)
    cur = conn.cursor()

    print("=" * 70)
    print("ORGANIZATIONS")
    print("=" * 70)
    cur.execute("SELECT id, name, slug, plan, status FROM organizations ORDER BY id")
    for row in cur.fetchall():
        print(f"  id={row[0]:<4} name={row[1]:<25} slug={row[2]:<25} plan={row[3]:<12} status={row[4]}")

    print()
    print("=" * 70)
    print("TENANT SCHEMAS")
    print("=" * 70)
    cur.execute(
        "SELECT schema_name FROM information_schema.schemata "
        "WHERE schema_name LIKE 'tenant_%' OR schema_name = 'public' "
        "ORDER BY schema_name"
    )
    schemas = [r[0] for r in cur.fetchall()]
    for s in schemas:
        print(f"  {s}")

    print()
    print("=" * 70)
    print("USERS PER ORGANIZATION")
    print("=" * 70)
    cur.execute(
        "SELECT o.name, o.id, COUNT(u.id) FROM organizations o "
        "LEFT JOIN users u ON u.org_id = o.id "
        "GROUP BY o.name, o.id ORDER BY o.id"
    )
    for row in cur.fetchall():
        print(f"  {row[0]:<25} org_id={row[1]:<4} users={row[2]}")

    print()
    print("=" * 70)
    print("ROW COUNTS PER TABLE, PER SCHEMA (empty tables omitted)")
    print("=" * 70)
    for schema in schemas:
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = %s AND table_type = 'BASE TABLE' "
            "ORDER BY table_name",
            (schema,),
        )
        tables = [r[0] for r in cur.fetchall()]
        print(f"\n--- schema: {schema} ({len(tables)} tables total) ---")
        for t in tables:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{schema}"."{t}"')
                count = cur.fetchone()[0]
                if count > 0:
                    print(f"  {t:<40} {count}")
            except Exception as e:
                print(f"  {t:<40} ERROR: {e}")

    print()
    print("=" * 70)
    print("BUSINESS UNIT STRUCTURE PER SCHEMA")
    print("(non-root rows here = internal sub-structure a flat migration would lose)")
    print("=" * 70)
    for schema in schemas:
        try:
            cur.execute(f'SELECT id, name, parent_id FROM "{schema}".business_units ORDER BY id')
            rows = cur.fetchall()
            print(f"\n--- schema: {schema} ---")
            for r in rows:
                print(f"  id={r[0]:<4} name={r[1]:<30} parent_id={r[2]}")
        except Exception as e:
            print(f"  (no business_units table, or error: {e})")

    cur.close()
    conn.close()
    print()
    print("Recon complete. No changes were made to the database.")


if __name__ == "__main__":
    main()
