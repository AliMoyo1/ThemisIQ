# Phase M — Shadow Mode Runbook

**Duration:** 48 hours minimum  
**Goal:** Validate that shadow PostgreSQL matches production SQLite before cutover.  
**Prod impact:** Zero — SQLite app runs unchanged throughout.

---

## Step 1 — Take a fresh prod backup

```bash
# From the app container or locally with sqlite3 installed
python -c "from modules.grid.scheduler import perform_backup; perform_backup()"
# Or simply copy the DB file directly:
cp data/oneforall.db data/oneforall_pre_shadow_$(date +%Y%m%d_%H%M%S).db
```

---

## Step 2 — Start the shadow PG container

```bash
# On the VPS, alongside the running SQLite app:
docker compose -f docker-compose.shadow.yml up -d

# Verify it's ready:
docker compose -f docker-compose.shadow.yml ps
# shadow-db should show "healthy"
```

Shadow PG is on port 5433 (prod is 5432 — no conflict).  
Connection URL: `postgresql://themisiq:shadow_pass@localhost:5433/themisiq_shadow`

---

## Step 3 — Create the schema in shadow PG

The schema is created automatically by the first `sqlite_to_postgres.py` run via `init_db()`.  
Alternatively, apply it manually:

```bash
DATABASE_URL=postgresql://themisiq:shadow_pass@localhost:5433/themisiq_shadow \
    python -c "from database import init_db; init_db()"
```

---

## Step 4 — Start the 48-hour shadow loop

```bash
cd /app   # or wherever oneforall/ is on the VPS

nohup python scripts/shadow_mode_loop.py \
    --sqlite data/oneforall.db \
    --postgres postgresql://themisiq:shadow_pass@localhost:5433/themisiq_shadow \
    --hours 48 \
    --interval-hours 6 \
    > shadow_mode.log 2>&1 &

echo "Shadow loop PID: $!"
tail -f shadow_mode.log
```

The loop:
1. **Initial migration** — copies all SQLite rows to shadow PG (takes ~2–10 min)
2. **Every 6 hours** — re-syncs new rows (idempotent ON CONFLICT DO NOTHING)
3. **After each sync** — runs parity check + warm replay
4. **After 48 hours** — prints PASS/FAIL summary and exits

---

## Step 5 — Monitor

```bash
# Watch the log in real time:
tail -f shadow_mode_YYYYMMDD_HHMMSS.log

# Manual parity check at any time:
python scripts/verify_pg_parity.py \
    --sqlite data/oneforall.db \
    --postgres postgresql://themisiq:shadow_pass@localhost:5433/themisiq_shadow

# Manual warm replay at any time:
python scripts/warm_replay.py \
    --sqlite data/oneforall.db \
    --postgres postgresql://themisiq:shadow_pass@localhost:5433/themisiq_shadow
```

---

## Step 6 — Acceptance criteria (all must be true before Phase N)

- [ ] Shadow loop ran for **48 hours** without aborting
- [ ] **Zero** parity failures across all 8 cycles
- [ ] **Zero** warm replay failures across all 8 cycles
- [ ] Backup verification job (Job 12, 03:00 CAT) ran and passed at least once during shadow period
- [ ] Weekly digest (Job 4, Monday 07:00 CAT) ran without errors (check grid scheduler log)
- [ ] The `shadow_mode_YYYYMMDD_HHMMSS.log` ends with `PASS`

If any criterion is not met: investigate, fix, and restart shadow mode from Step 1.

---

## Step 7 — Teardown shadow PG

```bash
# After cutover is complete and shadow PG is no longer needed:
docker compose -f docker-compose.shadow.yml down -v
# -v removes the pgdata_shadow volume (shadow data is discarded; prod PG has the real data)
```

---

## Rollback

If shadow mode reveals data issues:

```bash
# Stop the shadow loop
kill $(pgrep -f shadow_mode_loop.py)

# Tear down shadow PG
docker compose -f docker-compose.shadow.yml down -v

# Production SQLite is untouched — no rollback needed.
```

---

## What the shadow loop does NOT test

- Write path under concurrent load (that's Phase N production)
- Scheduler jobs running against PG (schedulers still hit SQLite during shadow)
- Alembic migration chain (tested separately against staging PG)

These are intentional: shadow mode is purely a **data fidelity** check.
