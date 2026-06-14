# Phase N — PostgreSQL Cutover & Rollback Plan

**Target date:** Saturday, maintenance window 18:00–20:00 CAT  
**VPS:** ubuntu-4gb-hel1-1 (77.42.36.84)  
**Author:** Reviewed before each cutover attempt

---

## 1. Pre-Cutover Checklist (complete before Saturday)

All items must be ✅ before proceeding to Phase N.

- [ ] Shadow loop ran ≥ 48 hours with 0 parity failures across all 8 cycles
- [ ] Shadow loop ran ≥ 48 hours with 0 warm-replay failures across all 8 cycles
- [ ] Fresh SQLite backup taken within 1 hour of cutover start
- [ ] Production PG container started and healthy (see Step 2 below)
- [ ] Fresh data migration to production PG completed with PARITY PASS
- [ ] `/health` and `/ready` endpoints tested against SQLite (baseline)
- [ ] All 6 modules manually smoke-tested (login → navigate → create record)
- [ ] GitHub repo set to private
- [ ] Someone available on standby for 2 hours post-cutover

---

## 2. Production PG Setup (do before maintenance window)

Production PG runs on port **5432**, separate from shadow PG (port 5433).

### 2a. Create production docker-compose

File already exists at `docker-compose.yml`. Start the production DB:

```bash
cd /project
docker compose up -d db
# Wait for healthy:
docker compose ps
```

### 2b. Migrate data to production PG

```bash
cd /project
export PROD_URL="postgresql://themisiq:CHANGE_ME@localhost:5432/themisiq"

python3 oneforall/scripts/run_shadow.py --prod
# (or run manually:)
SECRET_KEY=shadow_temp_key DEBUG=true \
    DATABASE_URL=$PROD_URL \
    python3 -c "import sys; sys.path.insert(0,'oneforall'); from database import init_db; init_db()"

python3 oneforall/scripts/sqlite_to_postgres.py \
    --sqlite oneforall/data/oneforall.db \
    --postgres $PROD_URL \
    --apply
```

Must end with: `[migrate] Parity: PASS`

---

## 3. Cutover Procedure

### T-60 min: Take SQLite backup

```bash
cp /project/oneforall/data/oneforall.db \
   /project/oneforall/data/oneforall_pre_cutover_$(date +%Y%m%d_%H%M%S).db
```

Verify backup exists and is non-zero:
```bash
ls -lh /project/oneforall/data/oneforall_pre_cutover_*.db
```

### T-5 min: Notify users (if any active)

Post maintenance notice. ThemisIQ will be unavailable for up to 15 minutes.

### T-0: Flip to PostgreSQL

**Step 1** — Stop the app:
```bash
# If running via uvicorn directly:
pkill -f "uvicorn main:app"
# If running via docker:
docker compose stop app
```

**Step 2** — Update DATABASE_URL in the environment file:
```bash
# Edit .env or however DATABASE_URL is set in production:
echo 'DATABASE_URL=postgresql://themisiq:CHANGE_ME@localhost:5432/themisiq' >> /project/oneforall/.env
```

**Step 3** — Start the app against PostgreSQL:
```bash
# Verify DATABASE_URL is picked up:
cd /project && SECRET_KEY=$SECRET_KEY DATABASE_URL=$PROD_URL \
    python3 -c "import sys; sys.path.insert(0,'oneforall'); from config import settings; print(settings.is_postgres())"
# Must print: True

# Start app:
docker compose up -d app
# or:
nohup uvicorn main:app --host 0.0.0.0 --port 8080 >> /project/app.log 2>&1 &
```

**Step 4** — Verify `/health` and `/ready`:
```bash
curl http://localhost:8080/health
curl http://localhost:8080/ready
# Both must return 200
```

**Step 5** — Smoke test (5 minutes):
- [ ] Log in successfully
- [ ] ARIA module loads framework list
- [ ] GRID module shows audits
- [ ] Create one test record, verify it persists on page reload
- [ ] Check app logs for errors: `tail -20 /project/app.log`

---

## 4. Go / No-Go Decision

**GO criteria** (all must be true at T+5 min):
- `/ready` returns 200
- Login works
- No exceptions in app.log
- Test record created and visible after reload

**NO-GO triggers** (roll back immediately if any are true):
- App fails to start
- `/ready` returns non-200
- Login fails or throws 500
- Database connection errors in logs
- Any data visible in UI that doesn't match pre-cutover SQLite state
- Response times > 3× baseline (indicates PG connection pool issue)

---

## 5. Rollback Procedure

**Time limit:** If GO criteria not met within **20 minutes** of flip, roll back.

### Step R1 — Stop the app:
```bash
pkill -f "uvicorn main:app"
# or:
docker compose stop app
```

### Step R2 — Remove DATABASE_URL (reverts to SQLite):
```bash
# Remove or comment out DATABASE_URL from .env:
# Edit /project/oneforall/.env and remove the DATABASE_URL line
# OR set it to empty:
sed -i '/DATABASE_URL/d' /project/oneforall/.env
```

### Step R3 — Restore SQLite backup (only if data was written to SQLite during window):
```bash
# Check if SQLite was written to during the window:
ls -lh /project/oneforall/data/oneforall.db
# If modified time is AFTER T-0, the backup is clean; restore it:
cp /project/oneforall/data/oneforall_pre_cutover_YYYYMMDD_HHMMSS.db \
   /project/oneforall/data/oneforall.db
```

> **Note:** During the cutover attempt, if the app was pointing at PG, SQLite
> was NOT written to. The pre-cutover backup should be identical to the live
> SQLite file. Only restore the backup if you suspect the SQLite file was
> modified unexpectedly.

### Step R4 — Restart the app on SQLite:
```bash
docker compose up -d app
# or:
nohup uvicorn main:app --host 0.0.0.0 --port 8080 >> /project/app.log 2>&1 &
```

### Step R5 — Verify rollback:
```bash
curl http://localhost:8080/ready
# Must return 200
```

Log in and confirm data is intact.

**Rollback is complete.** Total expected time: under 5 minutes.

---

## 6. Post-Rollback

1. Document what went wrong (specific error, time of failure)
2. Do NOT delete the production PG — keep it for investigation
3. Schedule a post-mortem before attempting Phase N again
4. Fix the root cause, extend shadow mode by another 48h, then retry

---

## 7. Post-Cutover Hardening (Phase O — within 24h of successful cutover)

- [ ] Rotate PostgreSQL password (change from `shadow_pass` / default)
- [ ] Remove SQLite backup files older than 30 days
- [ ] Archive `oneforall/data/oneforall.db` to read-only (rename to `.db.archive`)
- [ ] Enable `pg_stat_statements` extension for query monitoring
- [ ] Update backup scheduler to use `pg_dump` instead of SQLite zip
- [ ] Run Alembic baseline: `alembic revision --autogenerate -m "baseline"` + `alembic stamp head`
- [ ] Teardown shadow PG: `docker compose -f docker-compose.shadow.yml down -v`
- [ ] Schedule quarterly DR drill (restore from `pg_dump` to staging)

---

## 8. Key File Locations

| Item | Path |
|------|------|
| SQLite database | `/project/oneforall/data/oneforall.db` |
| Pre-cutover backup | `/project/oneforall/data/oneforall_pre_cutover_*.db` |
| App log | `/project/app.log` |
| Shadow loop log | `/project/shadow.log` |
| Shadow PG compose | `/project/docker-compose.shadow.yml` |
| Production PG compose | `/project/docker-compose.yml` |
| Environment file | `/project/oneforall/.env` |
| Migration script | `/project/oneforall/scripts/sqlite_to_postgres.py` |
| Parity verifier | `/project/oneforall/scripts/verify_pg_parity.py` |

---

## 9. Contacts & Escalation

- **Decision maker for rollback:** Ali Moyo (alimoyo58@gmail.com)
- **Rollback authority:** Any single person can trigger rollback unilaterally
  — no approval needed if NO-GO criteria are met.
- **Time limit is hard:** 20 minutes, no exceptions.
