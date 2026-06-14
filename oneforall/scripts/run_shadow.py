#!/usr/bin/env python3
"""
run_shadow.py — One-command shadow mode setup: schema + migration + loop start.

Usage (on VPS):
    cd /project
    python3 oneforall/scripts/run_shadow.py
"""
import os
import subprocess
import sys

SHADOW_PG_URL = "postgresql://themisiq:shadow_pass@localhost:5433/themisiq_shadow"
SQLITE_PATH = "oneforall/data/oneforall.db"

os.environ["SECRET_KEY"] = "shadow_temp_key"
os.environ["DEBUG"] = "true"
os.environ["DATABASE_URL"] = SHADOW_PG_URL

# Step 1: Create schema via init_db()
print("=" * 60)
print("Step 1: Creating PG schema via init_db()...")
print("=" * 60)
sys.path.insert(0, "oneforall")
from database import init_db
init_db()
print("Schema created.\n")

# Step 1b: Clear any data seeded by init_db() so migration inserts real SQLite data
print("Clearing seeded data...")
import psycopg2
pg = psycopg2.connect(SHADOW_PG_URL)
pg.autocommit = True
with pg.cursor() as cur:
    cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
    tables = [r[0] for r in cur.fetchall()]
    for t in tables:
        cur.execute(f"TRUNCATE {t} CASCADE")
pg.close()
print(f"Cleared {len(tables)} tables.\n")

# Step 2: Run data migration
print("=" * 60)
print("Step 2: Migrating SQLite data to shadow PG...")
print("=" * 60)
result = subprocess.run([
    sys.executable,
    "oneforall/scripts/sqlite_to_postgres.py",
    "--sqlite", SQLITE_PATH,
    "--postgres", SHADOW_PG_URL,
    "--apply",
])
if result.returncode != 0:
    print("\nMigration failed. Fix errors above and re-run.")
    sys.exit(1)

print("\nDone. To start the 48h shadow loop, run:")
print(f"  nohup python3 oneforall/scripts/shadow_mode_loop.py \\")
print(f"    --sqlite {SQLITE_PATH} \\")
print(f"    --postgres '{SHADOW_PG_URL}' \\")
print(f"    --hours 48 --interval-hours 6 > shadow.log 2>&1 &")
