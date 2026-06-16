#!/usr/bin/env python3
"""
cutover.py - Phase N PostgreSQL cutover helper.

Reads the password from /project/secrets/pg_password.txt, creates the
schema, clears seeded data, migrates SQLite data, and writes DATABASE_URL
to oneforall/.env.

Run from /project:
    python3 oneforall/scripts/cutover.py
"""
import os
import sys
import subprocess
import psycopg2

SECRETS_FILE = "/project/secrets/pg_password.txt"
SQLITE_PATH  = "oneforall/data/oneforall.db"
ENV_FILE     = "oneforall/.env"

# ── 1. Read password ─────────────────────────────────────────────────────────

if not os.path.exists(SECRETS_FILE):
    print(f"ERROR: {SECRETS_FILE} not found.")
    sys.exit(1)

pw = open(SECRETS_FILE).read().strip()
if not pw:
    print(f"ERROR: {SECRETS_FILE} is empty.")
    sys.exit(1)

PROD_URL = (
    "postgresql://themisiq:" + pw +
    "@localhost:5432/themisiq"
)

print("=" * 60)
print("Step 1: Password loaded from secrets file.")
print("=" * 60)

# ── 2. Create schema ─────────────────────────────────────────────────────────

print("\nStep 2: Creating PostgreSQL schema via init_db()...")
os.environ["SECRET_KEY"]   = "shadow_temp_key"
os.environ["DEBUG"]        = "true"
os.environ["DATABASE_URL"] = PROD_URL

sys.path.insert(0, "oneforall")
from database import init_db
init_db()
print("Schema created.")

# ── 3. Clear seeded data ─────────────────────────────────────────────────────

print("\nStep 3: Clearing seeded data from init_db()...")
pg = psycopg2.connect(PROD_URL)
pg.autocommit = True
with pg.cursor() as cur:
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    tables = [r[0] for r in cur.fetchall()]
    for t in tables:
        cur.execute(f"TRUNCATE {t} CASCADE")
pg.close()
print(f"Cleared {len(tables)} tables.")

# ── 4. Migrate data ──────────────────────────────────────────────────────────

print("\nStep 4: Migrating SQLite data to production PostgreSQL...")
result = subprocess.run([
    sys.executable,
    "oneforall/scripts/sqlite_to_postgres.py",
    "--sqlite", SQLITE_PATH,
    "--postgres", PROD_URL,
    "--apply",
])
if result.returncode != 0:
    print("\nERROR: Migration failed. Check output above.")
    sys.exit(1)

# ── 5. Write DATABASE_URL to .env ────────────────────────────────────────────

print(f"\nStep 5: Writing DATABASE_URL to {ENV_FILE}...")

lines = []
if os.path.exists(ENV_FILE):
    with open(ENV_FILE) as f:
        lines = [l for l in f.readlines() if not l.startswith("DATABASE_URL=")]

lines.append("DATABASE_URL=" + PROD_URL + "\n")

with open(ENV_FILE, "w") as f:
    f.writelines(lines)

print(f"Written: DATABASE_URL=postgresql://themisiq:***@localhost:5432/themisiq")

# ── Done ─────────────────────────────────────────────────────────────────────

print("\n" + "=" * 60)
print("Cutover preparation complete.")
print("Next steps:")
print("  1. pkill -f 'uvicorn main:app'   (stop the app)")
print("  2. docker compose up -d app       (start against PG)")
print("  3. curl http://localhost:8080/ready")
print("=" * 60)
