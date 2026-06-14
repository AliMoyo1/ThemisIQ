# ThemisIQ — PostgreSQL Migration Plan v2 (VPS Deployment)

**Status:** Sign-off received 2026-06-13 — decisions P-5..P-7 locked. Ready to schedule kick-off.
**Supersedes:** Original migration plan
**Target deployment:** Linux VPS, Cloudflare-fronted at themisiq.net
**Source:** Reviewed against codebase + risk audit in `PG_MIGRATION_AUDIT.md`
**Author:** Senior Backend audit pass, 2026-06-13

---

## Sign-off decisions (LOCKED 2026-06-13)

| ID | Decision | Value | Implication |
|---|---|---|---|
| **P-5** | Timestamp type on PG | **TIMESTAMPTZ** (all timestamp columns) | Rejects "keep TEXT" option; ~50+ read sites doing `datetime.fromisoformat(row["col"])` need refactoring because psycopg2 returns `datetime` objects, not strings. Phase H scope grows. |
| **P-6** | PG hosting | **Co-located on the same VPS** (docker-compose: postgres:16-alpine + PgBouncer + app on private bridge network) | No external managed DB. Docker secrets manage credentials. SSL still enabled on the private bridge for defense-in-depth. |
| Offsite backup | Destination | **Cloudflare R2** (S3-compatible) | rclone with R2 endpoint; access key + secret in Docker secrets; R2 free egress makes restore drills cheap. Bucket lifecycle policy enforces 90-day retention. |
| Maintenance window | Cutover slot | **Saturday 18:00 CAT** (Africa/Harare = UTC+2 → 16:00 UTC) | Lowest user activity. 1-hour advertised window, 30-min target. Must be confirmed at least 7 days before. |
| 4-eyes reviewer | Cutover authority | **Trusted engineer / architect** (name TBD; must be confirmed ≥7 days pre-cutover) | Co-signs cutover go/no-go; co-monitors smoke test; has explicit rollback authority. |
| **P-7** | Formal rollback plan | **Mandatory** (gates Phase N) | Standalone document, peer-reviewed, time-boxed, dry-run on staging at least once. Cutover cannot proceed until this artifact is signed off. See new Phase N-pre below. |

---

## Guiding principle

**The app must never be in a "half-migrated" state where dev or prod can't roll back in <10 minutes.** Every phase below leaves the codebase in a working state on the current engine (SQLite) and is independently revertible. PG mode is gated by a single environment variable (`DATABASE_URL`); flipping it back to empty returns the app to SQLite without code changes.

This is achieved through six structural controls applied at every phase:

| # | Control | What it gives us |
|---|---|---|
| C-1 | **Dual-mode at runtime** | A single `DATABASE_URL` env var switches engines. No code rebuild to roll back. |
| C-2 | **Test gate per phase** | `pytest` must pass on SQLite at the end of every phase. PG-specific tests gate Phase H+. |
| C-3 | **Pre-flight verifier** | Before any prod cutover, `scripts/verify_pg_parity.py` confirms schema, row counts, key relationships. |
| C-4 | **Versioned backups before every prod-touching step** | `pg_dump` + uploads zip retained 90 days for the cutover window; encrypted at rest. |
| C-5 | **Shadow-read phase before cutover** | PG runs in read-only shadow mode for 48 h, comparing query results to SQLite. |
| C-6 | **Single-command rollback** | Each phase documents the exact rollback command. Rollback is a tested path, not a hope. |

---

## Deployment context — VPS specifics

This changes several decisions vs the original plan:

| Decision | VPS implication |
|---|---|
| TLS to DB | Co-located PG (P-6): `sslmode=require` still enabled on the Docker bridge for defense-in-depth. PG configured with `ssl=on` + self-signed cert in compose. |
| PG exposure | `5432` **never** exposed to the public internet. Bind to `127.0.0.1` or Docker network only. Cloudflare DNS does not proxy raw PG. |
| Connection pooler | Add **PgBouncer** as a separate container, transaction-mode pooling. Initial sizing: 2 uvicorn workers × 10 in-app pool max = 20 connections; PG default `max_connections=100`. PgBouncer flattens that to ~25 backend conns. (Workers raised post-launch once observed load justifies it — see worker-scaling note in Phase E.) |
| Backups offsite | **Cloudflare R2** (S3-compatible) via rclone. R2 access key + secret stored as Docker secrets. Bucket lifecycle rule deletes objects after 90 days. Free egress means restore drills cost nothing. |
| Container user | `Dockerfile` runs as non-root (`USER 1000:1000`). All host volumes owned by that UID. |
| Process supervisor | uvicorn under `docker compose` with `restart: unless-stopped`. systemd unit on the host supervises Docker itself. |
| Reverse proxy | nginx (or Caddy) terminates on VPS port 80/443 with Let's Encrypt; proxies to `app:8080`. Cloudflare in front for DDoS / WAF. |
| Log persistence | App logs to stdout → Docker JSON-file driver with rotation (`max-size: 10m`, `max-file: 5`) + `journald` for systemd. |
| Resource caps | `mem_limit` + `cpus` set on each container in compose. Prevents one OOM from killing the VPS. |
| Firewall | `ufw` allow 22, 80, 443 only. Outbound: 587 (SMTP), 443 (Anthropic/AI), 5432 (only if external PG). |
| Time | VPS in UTC. App scheduler still runs in `Africa/Harare` timezone via APScheduler — confirmed cron works regardless of host TZ. |

---

## Pre-flight checks — must complete before any code changes

| # | Check | Owner | Status |
|---|---|---|---|
| P-1 | Take a verified backup of `data/oneforall.db` + `data/grid_uploads/` + `data/evidence/` from current prod. Store outside the VPS (S3 or local laptop). Test restore on a scratch host. | Ali | ☐ |
| P-2 | Pin Python version: confirm prod runs 3.11 (matches Dockerfile). | Ali | ☐ |
| P-3 | Inventory all currently-running schedulers — confirm 11 jobs across 5 schedulers from `main.py` (GRID, Sentinel, BCM, Evidence, Reminder). | Ali | ☐ |
| P-4 | Capture current prod row counts per table (`SELECT name, COUNT(*) FROM each table`). Store as baseline for data-migration parity check. | Migration script | ☐ |
| P-5 | ~~Decide TIMESTAMPTZ vs TEXT~~ → **LOCKED: TIMESTAMPTZ**. Audit all `fromisoformat(row["col"])` reads — list provided in Phase H. | Ali + reviewer | ☑ |
| P-6 | ~~Decide co-located vs external PG~~ → **LOCKED: co-located on same VPS** via docker-compose. | Ali | ☑ |
| P-7 (was: staging VPS) | Allocate staging VPS (or scratch namespace on prod VPS) for full rehearsal. | Ali | ☐ |
| **P-7-rollback** (new, MANDATORY) | Write & sign off `ROLLBACK_PLAN.md` (Phase N-pre details below). Cutover blocked until this exists, is peer-reviewed by the 4-eyes reviewer, and has been dry-run on staging at least once with a measured rollback time. | Ali + reviewer | ☐ |
| P-8 | Provision Cloudflare R2 bucket (`themisiq-backups`), generate access key + secret, store in Docker secrets, configure lifecycle rule (90-day delete). | Ali | ☐ |
| P-9 | Confirm 4-eyes reviewer name + availability for Saturday 18:00 CAT slot at least 7 days before cutover. | Ali | ☐ |
| P-10 | Schedule the maintenance window in advance — email users 7 days out, then 24 hours out, then 1 hour out. | Ali | ☐ |
| P-11 | Provision a small monitoring VPS (or accept that Uptime Kuma on the prod VPS won't detect prod-VPS outages — recommend separate host). | Ali | ☐ |
| P-12 | Pick an alert channel — at minimum email; recommend Slack/Telegram webhook for louder alerts. Test it. | Ali | ☐ |

---

## Phased execution — 12 phases, each independently revertible

### Legend
- 🟢 **Zero-risk on SQLite** — code change keeps current behavior, no schema/data touched
- 🟡 **Code change with new tests** — risk contained to test gate
- 🔴 **Prod-data-touching** — needs full backup + tested rollback

---

### Phase A — Compatibility shims & helpers 🟢

**Goal:** Add abstractions so the rest of the work can be expressed as conditional code. Zero behavioral change on SQLite.

**Steps:**
1. Add to `config.py`:
   ```python
   DATABASE_URL: str = os.getenv("DATABASE_URL", "")
   POSTGRES_POOL_MIN: int = int(os.getenv("POSTGRES_POOL_MIN", "2"))
   POSTGRES_POOL_MAX: int = int(os.getenv("POSTGRES_POOL_MAX", "10"))   # per worker; PgBouncer handles real fan-out

   @staticmethod
   def is_postgres() -> bool:
       return bool(os.getenv("DATABASE_URL", "").startswith("postgresql"))
   ```
   Expose `from config import settings; settings.is_postgres()`.

2. Add to `database.py` (top-of-file shim — always loads, never calls psycopg2 yet):
   ```python
   import sqlite3
   IntegrityError = sqlite3.IntegrityError   # rebind in Phase D
   LockError = sqlite3.OperationalError
   OperationalError = sqlite3.OperationalError
   ```

3. Add helper used by all subsequent INSERT refactors:
   ```python
   def insert_returning_id(db, sql, params):
       """Engine-portable 'INSERT ... RETURNING id'.
       In SQLite uses .lastrowid; in PG appends RETURNING id and reads it back."""
       if settings.is_postgres():
           cur = db.execute(sql.rstrip(" ;") + " RETURNING id", params)
           return cur.fetchone()["id"]
       return db.execute(sql, params).lastrowid
   ```

4. Add the LIKE-operator shim used by search queries:
   ```python
   LIKE_OP = "ILIKE" if settings.is_postgres() else "LIKE"
   ```
   Used at SQL construction time (operator, not value — safe).

**Test gate:**
- `pytest` passes (no behavior change expected).
- `python -c "from database import IntegrityError, LockError, insert_returning_id"` succeeds.

**Rollback:** `git revert <commit>` — pure additive, no risk.

**Non-breakage controls:**
- Helper functions are tested by unit tests added in this phase.
- No existing call sites are modified yet.

---

### Phase B — Refactor INSERT sites to use `insert_returning_id` 🟢

**Goal:** Eliminate the 89 `.lastrowid` sites mechanically. Still SQLite.

**Steps:**
1. Mechanical refactor across 22 files (script-assisted):

   `before:`
   ```python
   cur = db.execute("INSERT INTO bcm_plans (...) VALUES (?,?,?)", (...))
   plan_id = cur.lastrowid
   ```
   `after:`
   ```python
   plan_id = insert_returning_id(db, "INSERT INTO bcm_plans (...) VALUES (?,?,?)", (...))
   ```

2. Two edge cases needing manual review:
   - **`modules/grid/data_service.py:221`** — `inserted_ids[(uf_id, c[0])] = (cur2.lastrowid, uf_id)` (inside a loop, cur2 reused)
   - **`modules/grid/data_service.py:991`** — `return cur.lastrowid if cur.rowcount > 0 else None` (conditional)
   These keep the explicit cursor pattern.

3. Add a regression test: insert a row in every module's primary table, assert the returned ID matches a follow-up `SELECT MAX(id)`.

**Test gate:**
- `pytest` passes including the new ID-roundtrip tests.
- `grep -rn "\.lastrowid" oneforall/` returns ≤ 2 sites (the conditional edge cases above).

**Rollback:** `git revert`. Behavior on SQLite is unchanged because the helper falls through to `.lastrowid`.

**Non-breakage controls:**
- New regression test exercises every INSERT path before deploy.
- The helper is dual-mode — flipping to PG later only changes the helper internals.

---

### Phase C — `INSERT OR IGNORE` / `INSERT OR REPLACE` → `ON CONFLICT` 🟢

**Goal:** Replace SQLite-only DML with SQL that runs on both SQLite (3.24+) and PG.

**Steps:**
1. Confirm SQLite version on prod ≥ 3.24 (`python -c "import sqlite3; print(sqlite3.sqlite_version)"`). If lower, this phase blocks until SQLite is upgraded (Python 3.11 ships 3.39+).

2. For each `INSERT OR IGNORE`, identify the conflict target (UNIQUE constraint column(s)). The 13 sites:

   | File | Table | Conflict target | UNIQUE exists? |
   |---|---|---|---|
   | `main.py:81` | `frameworks` | `(name)` | ✅ from CREATE TABLE |
   | `database.py:2436` | `canonical_vendors` | needs index `idx_canonical_vendors_name_uq` | ✅ created in migrations |
   | `database.py:2474` | `frameworks` | `(name)` | ✅ |
   | `database.py:2513` | `bcm_comm_templates` | needs `(title)` | ❌ **add UNIQUE first** |
   | `database.py:2611` | `bcm_scenario_library` | needs `(title)` | ❌ **add UNIQUE first** |
   | `database.py:2631,2642` | `sentinel_jurisdiction_config` | `(jurisdiction_key)` | ✅ |
   | `database.py:2680` | `erm_risk_appetite` | `(category)` | ✅ |
   | `database.py:2720` | `erm_risk_library` | needs `(title)` | ❌ **add UNIQUE first** |
   | `database.py:2738` | `aria_frameworks` | `(name)` | ✅ |
   | `core/auto_mapper.py` | `aria_control_mappings` | `(source_control_id, target_control_id)` | ✅ |
   | `core/framework_service.py` | various | per-call | review per site |
   | `core/links.py` | `cross_module_links` | composite | from idx_xlinks_dedup_uq |
   | `modules/aria/routes.py` | per-call | review per site |
   | `modules/bcm/data_service.py` | per-call | review per site |
   | `modules/evidence/routes.py` | per-call | review per site |
   | `modules/grid/data_service.py` | per-call | review per site |
   | `modules/launcher/routes_admin.py` | per-call | review per site |
   | `modules/launcher/routes_dashboard.py` | per-call | review per site |
   | `seeds/control_mappings.py` | per-call | review per site |
   | `seeds/seed.py` | per-call | review per site |

3. For tables missing a UNIQUE constraint, **add the constraint first** via the existing `_run_migrations()` post-migration index list (these are `IF NOT EXISTS`, safe to re-run):
   ```sql
   CREATE UNIQUE INDEX IF NOT EXISTS idx_bcm_comm_templates_title ON bcm_comm_templates(title);
   CREATE UNIQUE INDEX IF NOT EXISTS idx_bcm_scenario_library_title ON bcm_scenario_library(title);
   CREATE UNIQUE INDEX IF NOT EXISTS idx_erm_risk_library_title ON erm_risk_library(title);
   ```
   Wrapped in the existing try/except — if duplicate data exists, the index fails to create and the seed-guards (count-checks) handle dedup as today.

4. Rewrite each `INSERT OR IGNORE INTO foo (...) VALUES (...)` as `INSERT INTO foo (...) VALUES (...) ON CONFLICT (target_cols) DO NOTHING`.

5. The two `INSERT OR REPLACE` sites become `... ON CONFLICT (target) DO UPDATE SET col = excluded.col`.

**Test gate:**
- `pytest` passes.
- Boot a fresh SQLite DB via `init_db()`, confirm seeds load.
- Boot against an EXISTING SQLite DB (copy of prod), confirm idempotent re-seed (no duplicates).

**Rollback:** `git revert`. Schema indexes from step 3 are `IF NOT EXISTS` and harmless on rollback.

**Non-breakage controls:**
- Two pytest runs: cold-start (empty DB) and warm-start (against a copy of prod DB).
- ON CONFLICT syntax verified against SQLite 3.24+ via test suite.

---

### Phase D — Exception type abstraction 🟢

**Goal:** Replace every `sqlite3.OperationalError` / `sqlite3.IntegrityError` catch with `database.OperationalError` / `database.IntegrityError` so PG mode just swaps the shim.

**Steps:**
1. Update the Phase A shim — make it conditional:
   ```python
   if settings.is_postgres():
       import psycopg2
       import psycopg2.errors
       IntegrityError = psycopg2.errors.IntegrityError
       OperationalError = psycopg2.errors.OperationalError
       LockError = (psycopg2.errors.DeadlockDetected,
                    psycopg2.errors.SerializationFailure,
                    psycopg2.errors.OperationalError)
   else:
       IntegrityError = sqlite3.IntegrityError
       OperationalError = sqlite3.OperationalError
       LockError = sqlite3.OperationalError
   ```

2. Replace all catches across 6 files:
   - `main.py:280-281` global handler → `database.LockError` (must be a tuple of types).
   - `database.py:2365,2408` → `database.OperationalError`, `database.IntegrityError`.
   - `core/auto_mapper.py:430,460` → same.
   - `core/vendor_link.py:53` → same.
   - `modules/aria/ask_service.py:340,348,355` → `database.OperationalError`.
   - `tests/test_canonical_vendor.py:72` → `database.IntegrityError` (test imports it).

**Test gate:** `pytest`.

**Rollback:** `git revert`.

**Non-breakage controls:**
- New test: deliberately trigger a UNIQUE constraint violation and assert `database.IntegrityError` is raised. Runs on both engines later.

---

### Phase E — Build PG infrastructure on staging (no app changes) 🟡

**Goal:** Stand up PG infrastructure on the staging VPS. App still talks to SQLite. Validates the deployment shape before we depend on it.

**Steps:**
1. Create `Dockerfile` (project root) — non-root, slim, no dev tools in final image:
   ```dockerfile
   FROM python:3.11-slim AS base
   RUN apt-get update && apt-get install -y --no-install-recommends \
       libpq5 postgresql-client \
    && rm -rf /var/lib/apt/lists/*
   RUN useradd --create-home --uid 1000 themisiq
   WORKDIR /app
   COPY --chown=themisiq:themisiq oneforall/requirements.txt .
   RUN pip install --no-cache-dir -r requirements.txt
   COPY --chown=themisiq:themisiq oneforall/ .
   USER themisiq
   EXPOSE 8080
   ENTRYPOINT ["./entrypoint.sh"]
   ```

2. Create `entrypoint.sh` — handles migrations once, then exec uvicorn:
   ```bash
   #!/usr/bin/env bash
   set -euo pipefail
   if [ -n "${DATABASE_URL:-}" ]; then
     echo "[entrypoint] Running Alembic migrations..."
     alembic upgrade head
   fi
   echo "[entrypoint] Starting uvicorn (workers=${WORKERS:-2})..."
   exec uvicorn main:app --host 0.0.0.0 --port 8080 --workers "${WORKERS:-2}"
   ```
   Solves the C7 race condition from the audit — single-process migration before workers spawn.

   **Worker sizing — start conservative.** Initial deployment uses `WORKERS=2` (not 4). Rationale:
   - This is a single-tenant compliance tool with handful-to-dozens of concurrent users — not a public SaaS.
   - Each worker holds a 10-connection PG pool; 2 workers × 10 = 20 backend conns is comfortable on a VPS-sized PG.
   - 2 workers also halves memory footprint at idle (~150 MB per worker for FastAPI + ARIA AI clients).
   - APScheduler runs ONCE per worker — with 2 workers, two scheduler processes race for cron locks. APScheduler handles this via DB-backed jobstore, but fewer workers = less lock contention.
   - Headroom for vertical scale: raise to 4 only when p95 latency or request queueing is observed (see monitoring in N-pre-monitor).

3. Create `docker-compose.yml` — VPS-hardened:
   ```yaml
   services:
     db:
       image: postgres:16-alpine
       restart: unless-stopped
       environment:
         POSTGRES_DB: themisiq
         POSTGRES_USER: themisiq
         POSTGRES_PASSWORD_FILE: /run/secrets/pg_password
       secrets: [pg_password]
       volumes:
         - pgdata:/var/lib/postgresql/data
       healthcheck:
         test: ["CMD-SHELL", "pg_isready -U themisiq"]
         interval: 5s
         timeout: 3s
         retries: 10
       # Bind to loopback ONLY — never expose 5432 publicly
       ports: ["127.0.0.1:5432:5432"]
       mem_limit: 1g
       cpus: 1.5
       logging: { driver: json-file, options: { max-size: "10m", max-file: "5" } }

     pgbouncer:
       image: edoburu/pgbouncer:1.21.0
       restart: unless-stopped
       environment:
         DB_HOST: db
         DB_USER: themisiq
         DB_PASSWORD_FILE: /run/secrets/pg_password
         DB_NAME: themisiq
         POOL_MODE: transaction
         MAX_CLIENT_CONN: 200
         DEFAULT_POOL_SIZE: 25
       secrets: [pg_password]
       depends_on: { db: { condition: service_healthy } }
       mem_limit: 128m
       logging: { driver: json-file, options: { max-size: "5m", max-file: "3" } }

     app:
       build: .
       restart: unless-stopped
       environment:
         DATABASE_URL: postgresql://themisiq@pgbouncer:5432/themisiq
         PGPASSWORD_FILE: /run/secrets/pg_password
         WORKERS: "2"   # start conservative; raise to 4 after observed load justifies it
       env_file: oneforall/.env
       secrets: [pg_password]
       depends_on: { pgbouncer: { condition: service_started } }
       volumes:
         - ./data/backups:/app/data/backups
         - ./data/grid_uploads:/app/data/grid_uploads
         - ./data/evidence:/app/data/evidence
       mem_limit: 1g
       cpus: 2
       logging: { driver: json-file, options: { max-size: "10m", max-file: "5" } }
       healthcheck:
         test: ["CMD", "curl", "-fsS", "http://localhost:8080/health"]
         interval: 30s
         timeout: 5s
         retries: 3

   secrets:
     pg_password:
       file: ./secrets/pg_password.txt

   volumes:
     pgdata:
   ```
   Critical security choices:
   - Password via Docker secret (file, not env), avoids `ps`/log leakage.
   - `DATABASE_URL` has **no password** — app reads `PGPASSWORD_FILE` and sets `PGPASSWORD` for psycopg2 at connect time.
   - `127.0.0.1:5432:5432` — PG never on public iface.
   - PgBouncer in front of PG handles connection fanout — multiple uvicorn workers can each open their own pool without blowing past PG's `max_connections`.
   - Healthchecks gate startup ordering.
   - Memory/CPU limits prevent OOM cascade.

4. Add `.env.example` lines:
   ```
   DATABASE_URL=postgresql://themisiq@pgbouncer:5432/themisiq
   POSTGRES_POOL_MIN=2
   POSTGRES_POOL_MAX=10
   BACKUP_PATH=data/backups
   BACKUP_RETAIN_DAYS=30
   BACKUP_OFFSITE_RCLONE_REMOTE=     # e.g., s3:themisiq-backups
   ```

5. Stand up the stack on staging VPS. **App container will fail to fully start** because the app still expects SQLite — that's expected. Validate that `db` and `pgbouncer` containers come up healthy. Then `docker compose down`.

**Test gate:**
- `docker compose up db pgbouncer` — both healthy in <30 s.
- `psql -h 127.0.0.1 -U themisiq -d themisiq -c '\dt'` from VPS shell — empty DB confirmed.
- `nmap` from outside VPS confirms 5432 not reachable.

**Rollback:** `docker compose down -v` (drops the volume too — no prod data yet).

**Non-breakage controls:**
- Prod is untouched throughout this phase.
- Staging is a copy; teardown is trivial.

---

### Phase F — Dual-mode `database.py` rewrite 🟡

**Goal:** `database.py` works against either engine based on `DATABASE_URL`. Default (empty) keeps SQLite behavior bit-identical.

**Steps:**
1. Refactor the connection layer:
   ```python
   _pg_pool = None
   _pg_password = None

   def _read_pg_password():
       global _pg_password
       if _pg_password is not None:
           return _pg_password
       path = os.getenv("PGPASSWORD_FILE")
       if path and Path(path).exists():
           _pg_password = Path(path).read_text().strip()
       else:
           _pg_password = os.getenv("PGPASSWORD", "")
       return _pg_password

   def _get_pg_pool():
       global _pg_pool
       if _pg_pool is None:
           import psycopg2.pool
           pwd = _read_pg_password()
           _pg_pool = psycopg2.pool.ThreadedConnectionPool(
               settings.POSTGRES_POOL_MIN, settings.POSTGRES_POOL_MAX,
               dsn=settings.DATABASE_URL, password=pwd,
               sslmode=os.getenv("PGSSLMODE", "prefer"),
               application_name="themisiq",
               connect_timeout=10,
           )
       return _pg_pool

   def get_db(timeout: int = 15):
       if settings.is_postgres():
           pool = _get_pg_pool()
           conn = pool.getconn()
           conn.autocommit = False
           return _PgConnWrapper(conn, pool)
       # ── SQLite path: UNCHANGED ──
       conn = sqlite3.connect(_DB_PATH, timeout=timeout)
       conn.row_factory = sqlite3.Row
       conn.execute("PRAGMA journal_mode=WAL")
       ...
       return conn
   ```

2. Full `_PgConnWrapper` implementation:
   ```python
   class _PgConnWrapper:
       """Mimics the sqlite3.Connection interface we actually use.
       Tracks open cursors so .close() can return the connection to the pool."""
       def __init__(self, conn, pool):
           self._conn, self._pool = conn, pool
           self._cursors = []

       def execute(self, sql, params=None):
           import psycopg2.extras
           cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
           self._cursors.append(cur)
           cur.execute(sql, params or ())
           return cur

       def executescript(self, sql):
           # psycopg2 supports multi-statement strings when no params are passed.
           # Strip empty trailing statements; drop SQLite-only PRAGMAs defensively.
           cleaned = "\n".join(
               line for line in sql.splitlines()
               if not line.strip().upper().startswith("PRAGMA ")
           )
           cur = self._conn.cursor()
           cur.execute(cleaned)
           cur.close()

       def commit(self):    self._conn.commit()
       def rollback(self):  self._conn.rollback()

       def close(self):
           for c in self._cursors:
               try: c.close()
               except Exception: pass
           self._cursors.clear()
           # Return to pool — DO NOT close the underlying conn.
           try: self._pool.putconn(self._conn)
           except Exception: pass

       # Allow `with get_db() as db:` patterns
       def __enter__(self): return self
       def __exit__(self, exc_type, exc_val, exc_tb):
           if exc_type: self.rollback()
           else: self.commit()
           self.close()
   ```

3. Split `_run_migrations()` into two functions (resolves audit C3):
   - `_run_sqlite_alters(conn)` — the `ALTER TABLE ADD COLUMN` loop. Wrapped in `if not settings.is_postgres():`.
   - `_seed_baseline_data(conn)` — all the seed data (frameworks, BCM templates, ORM templates, ERM library, jurisdictions, canonical vendors). Runs on **both** engines. Uses `INSERT ... ON CONFLICT DO NOTHING` from Phase C.

4. Strip the SQLite `PRAGMA` lines from `_ERM_ORM_TABLES` schema string (audit C4). They are harmless to remove because `get_db()` (SQLite path) already sets them.

5. Provide two schema-string variants:
   - `_SHARED_TABLES_SQLITE = "..."` — current strings.
   - `_SHARED_TABLES_PG = "..."` — generated by find/replace per the P-5 TIMESTAMPTZ decision:
     - `INTEGER PRIMARY KEY AUTOINCREMENT` → `SERIAL PRIMARY KEY` (or `BIGSERIAL` for high-volume tables like `audit_log`, `events`, `notifications`, `webhook_logs`, `analytics_snapshots` — review per table)
     - `TEXT DEFAULT (datetime('now'))` → `TIMESTAMPTZ DEFAULT NOW()`
     - `TEXT DEFAULT (date('now'))` → `DATE DEFAULT CURRENT_DATE`
     - `TEXT DEFAULT CURRENT_TIMESTAMP` → `TIMESTAMPTZ DEFAULT NOW()`
     - Plain `TEXT` timestamp columns referenced as datetimes in code (`created_at`, `updated_at`, `*_at`, `*_date`, `last_*`, `expires_at`, `notify_deadline`, `next_review`, `acted_at`, etc.) → `TIMESTAMPTZ` (no default if none existed)
     - `*_date` columns that are pure dates (no time component used) → `DATE`
     - `REAL` → `DOUBLE PRECISION`
     - `BLOB` (none in this codebase, but defensively) → `BYTEA`

6. **TIMESTAMPTZ column inventory** — build it now, before code refactoring in Phase H. Generate `scripts/inventory_timestamp_columns.py` that walks both `_SHARED_TABLES_SQLITE` and the rest, classifies each `TEXT` column by name pattern and `datetime/date('now')` default, and outputs `.migration/timestamp_columns.json` — the authoritative mapping used by the data migration script (Phase L) and the read-site refactor (Phase H).

6. `init_db()` dispatches:
   ```python
   def init_db():
       _ensure_dir()
       conn = get_db()
       try:
           if settings.is_postgres():
               conn.executescript(_SHARED_TABLES_PG)
               conn.executescript(_ARIA_TABLES_PG)
               ...
           else:
               conn.executescript(_SHARED_TABLES_SQLITE)
               ...
           conn.commit()
           if not settings.is_postgres():
               _run_sqlite_alters(conn)
           _seed_baseline_data(conn)
       finally:
           conn.close()
   ```

7. `main.py` startup: drop the duplicate framework migration block (lines 70–88) — it's redundant with `_seed_baseline_data`. The remaining startup logic stays.

**Test gate:**
- `DATABASE_URL=` (empty) → `pytest` passes (SQLite path).
- `DATABASE_URL=postgresql://...staging...` → `init_db()` boots cleanly against staging PG, all 130+ tables created (`SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public'`), all seeds populated.
- Spin app on staging PG, hit `/health` and `/ready` — both return 200.

**Rollback:** `git revert`. Staging DB is wiped via `docker compose down -v`.

**Non-breakage controls:**
- SQLite path is intentionally **bit-identical** to current behavior — no test changes needed for the SQLite test suite.
- Prod (still SQLite) is untouched.
- Staging PG validates the PG path before any prod cutover.

---

### Phase G — Run the placeholder migration script 🟡

**Goal:** Convert all `?` SQL placeholders to `%s` across the codebase. After this, code only runs against PG (or SQLite via a compatibility shim — see below).

**Critical decision point:** psycopg2 uses `%s`; sqlite3 uses `?`. We need ONE of:
- **(G-a) Convert to `%s` and use a thin sqlite3 wrapper** that rewrites `%s` → `?` for the SQLite path. ←  **recommended**
- (G-b) Maintain two parallel codebases (untenable).
- (G-c) Use a query builder library (SQLAlchemy core) — large refactor, out of scope.

**Steps (G-a path):**
1. Add to `_PgConnWrapper` for PG path: nothing extra — psycopg2 takes `%s` natively.

2. Add a `_SqliteConnWrapper` for the SQLite path that rewrites placeholders:
   ```python
   class _SqliteConnWrapper:
       def __init__(self, conn):
           self._conn = conn
       def execute(self, sql, params=None):
           # Rewrite psycopg2-style %s placeholders to sqlite3-style ?
           # Skip rewriting inside string literals.
           rewritten = _percent_s_to_question(sql)
           return self._conn.execute(rewritten, params or ())
       def executescript(self, sql):
           return self._conn.executescript(sql)
       def commit(self):   self._conn.commit()
       def rollback(self): self._conn.rollback()
       def close(self):    self._conn.close()
       def __enter__(self): return self
       def __exit__(self, *a): self.close()

   _STRING_LITERAL_RE = re.compile(r"'(?:''|[^'])*'")
   _PLACEHOLDER_RE = re.compile(r"%s")
   def _percent_s_to_question(sql: str) -> str:
       """Replace %s with ? outside string literals."""
       out, last = [], 0
       for m in _STRING_LITERAL_RE.finditer(sql):
           out.append(_PLACEHOLDER_RE.sub("?", sql[last:m.start()]))
           out.append(m.group(0))
           last = m.end()
       out.append(_PLACEHOLDER_RE.sub("?", sql[last:]))
       return "".join(out)
   ```
   This makes the SQLite path equally portable.

3. Write `scripts/pg_migrate_placeholders.py`:
   - Walks `oneforall/**/*.py`.
   - For each file, parses with `ast` to find `.execute(...)` and `.executemany(...)` calls.
   - For each string-literal first argument, replaces `?` with `%s` outside its own string literals.
   - Skips f-string SQL (already PG-compat or needs manual review).
   - `--dry-run` prints diff per file.
   - `--apply` writes in place. Prints `N files changed, M replacements`.
   - Writes a manifest `scripts/.placeholder_migration.json` for auditability.

4. Run dry-run, review the diff (focus on dynamic SQL builders like `bcm/data_service.py:834` — `" AND ".join("content LIKE ?" for _ in query_terms)` — which uses `?` inside a generator; the script's AST visitor must handle this).

5. Apply.

6. Activate the SQLite wrapper:
   ```python
   def get_db(timeout: int = 15):
       if settings.is_postgres():
           ...  # as in Phase F
       conn = sqlite3.connect(_DB_PATH, timeout=timeout)
       conn.row_factory = sqlite3.Row
       conn.execute("PRAGMA journal_mode=WAL")
       ...
       return _SqliteConnWrapper(conn)
   ```

**Test gate:**
- `pytest` passes against SQLite (placeholders rewritten back to `?` transparently).
- `pytest` against staging PG also passes (set `DATABASE_URL` in a separate pytest run).
- `grep -rn "execute.*?\s*['\"]" oneforall/` finds no SQL with `?` placeholders.

**Rollback:** `git revert` reverses the placeholder substitution. The wrappers are additive — leaving them in place is fine.

**Non-breakage controls:**
- The SQLite rewriter is **the** safety net. If it has a bug, every SQLite test fails immediately — we never ship a broken SQLite path to prod.
- Manifest of changes is committed alongside the code for review.

---

### Phase H — Date/time function migration + TIMESTAMPTZ read-site refactor 🟡

**Goal:** Replace SQLite-only date/time SQL functions with portable expressions **and** adapt every read site that assumes timestamps are TEXT strings (because TIMESTAMPTZ returns `datetime` objects from psycopg2). This is the largest single phase because of the P-5 decision to use TIMESTAMPTZ.

**H.1 — Read-site refactor (TIMESTAMPTZ implication)**

Build a small portable accessor:
```python
# core/timeutils.py
def to_dt(value):
    """Engine-portable: TEXT or datetime → datetime.
    Returns None if value is empty/None."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    # SQLite path: TEXT timestamp string
    # Handle: 'YYYY-MM-DD', 'YYYY-MM-DD HH:MM:SS', ISO with T/Z
    s = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return datetime.strptime(s[:10], "%Y-%m-%d")

def to_iso(value):
    """For places that need an ISO string out (templates, JSON responses)."""
    dt = to_dt(value)
    return dt.isoformat() if dt else ""
```

Then sweep these patterns codebase-wide:

| Before (SQLite-only assumption) | After (engine-portable) |
|---|---|
| `datetime.fromisoformat(row["expires_at"])` | `to_dt(row["expires_at"])` |
| `datetime.fromisoformat(row["expires_at"].replace("Z",""))` | `to_dt(row["expires_at"])` |
| `datetime.strptime(d["deadline_date"][:10], "%Y-%m-%d").date()` | `to_dt(d["deadline_date"]).date()` |
| Bare reads passed into Jinja templates expecting ISO strings | `to_iso(row["created_at"])` at the JSON/template boundary |

Affected sites (from grep, expect ~50–80):
- `modules/grid/scheduler.py:122,175,351,406,453` — `datetime.fromisoformat(ev["expires_at"])` etc.
- `modules/sentinel/scheduler.py:142,281` — `datetime.fromisoformat(b["notify_deadline"].replace("Z",""))`, `datetime.strptime(d["deadline_date"][:10], ...)`
- `modules/erm/data_service.py` — multiple sites
- `modules/orm/data_service.py` — multiple sites
- `modules/sentinel/data_service.py:318,375` — `disc + timedelta(...)`, `rec + timedelta(...)` — `disc` and `rec` need to come from `to_dt(...)` not `datetime.fromisoformat(...)`
- All Jinja templates rendering `*_at` / `*_date` directly — switch to `to_iso(...)` in the route handlers
- All JSON responses — psycopg2 returns `datetime`, `json.dumps` rejects them; either pass through FastAPI's `jsonable_encoder` or coerce with `to_iso` at the boundary

**H.2 — Date arithmetic helpers (unchanged from earlier draft)**

Add the three helpers to `database.py`:

```python
def sql_now_offset(offset_expr: str) -> str:
    """Return an SQL fragment for 'now() ± interval'."""
    if settings.is_postgres():
        sign, qty, unit = offset_expr[0], offset_expr[1:].strip().split()
        return f"(NOW() {sign} INTERVAL '{qty} {unit}')"
    return f"datetime('now', '{offset_expr}')"

def sql_date_offset(offset_expr: str) -> str:
    if settings.is_postgres():
        sign, qty, unit = offset_expr[0], offset_expr[1:].strip().split()
        return f"(CURRENT_DATE {sign} INTERVAL '{qty} {unit}')"
    return f"date('now', '{offset_expr}')"

def sql_days_between(col1: str, col2: str) -> str:
    if settings.is_postgres():
        return f"EXTRACT(EPOCH FROM ({col1}::timestamptz - {col2}::timestamptz)) / 86400"
    return f"(julianday({col1}) - julianday({col2}))"
```

**Strategy:** Build a tiny date-arithmetic helper that the SQL string composes against:

```python
# database.py
def sql_now_offset(offset_expr: str) -> str:
    """Return an SQL fragment for 'now() ± interval'.
    offset_expr like "+30 days", "-7 days", "-6 days"."""
    if settings.is_postgres():
        return f"(NOW() {offset_expr.split()[0]} INTERVAL '{offset_expr.split()[0].lstrip('+-')} {offset_expr.split()[1]}')"
    return f"datetime('now', '{offset_expr}')"

def sql_date_offset(offset_expr: str) -> str:
    if settings.is_postgres():
        return f"(CURRENT_DATE {offset_expr.split()[0]} INTERVAL '{offset_expr.split()[0].lstrip('+-')} {offset_expr.split()[1]}')"
    return f"date('now', '{offset_expr}')"

def sql_days_between(col1: str, col2: str) -> str:
    """Days between col1 and col2 as a number."""
    if settings.is_postgres():
        return f"EXTRACT(EPOCH FROM ({col1}::timestamptz - {col2}::timestamptz)) / 86400"
    return f"(julianday({col1}) - julianday({col2}))"
```

**H.3 — Execution steps:**
1. Add `to_dt()` and `to_iso()` to `core/timeutils.py` (H.1 helpers).
2. Add the three SQL helpers above to `database.py` (H.2 helpers).
3. Sweep H.1 read sites — write a code-mod script (`scripts/refactor_timestamp_reads.py`) that AST-matches `datetime.fromisoformat(<expr>)`, `datetime.strptime(<expr>[:10], "%Y-%m-%d")` and proposes `to_dt(<expr>)` replacements. Manual review per file (the strptime → date() call shape varies).
4. Write `scripts/pg_migrate_date_functions.py` — purely advisory, generates a candidate-changes report. No autorewrite (semantics are subtle).
5. Manual refactor of the 20 affected files for SQL date math using the report. Patterns:
   - `"... <= date('now', '+30 days')"` → `f"... <= {sql_date_offset('+30 days')}"`
   - `"... < datetime('now', '-7 days')"` → `f"... < {sql_now_offset('-7 days')}"`
   - `"CAST(julianday('now') - julianday(created_at) AS INTEGER)"` → `f"CAST({sql_days_between(\"'now'\", 'created_at')} AS INTEGER)"`

   Files affected:
   - `core/predictive_risk.py:107,141`
   - `modules/erm/data_service.py:696,700,708,1091`
   - `modules/bcm/scheduler.py:95,156,217`
   - `modules/evidence/routes.py:75,802,821`
   - `modules/launcher/routes_dashboard.py:156,315`
   - `modules/sentinel/scheduler.py:371`
   - `modules/grid/scheduler.py:62,63,112,342,446`
   - `modules/launcher/routes_dashboard.py:156,315`

6. Add unit tests per scheduler that exercise the date-filtered query (using fixed wall-clock via freezegun) — ensures the migrated SQL returns identical row sets on both engines.

7. Update `modules/grid/scheduler.py:565` `UPDATE evidence_items SET status='archived', updated_at=datetime('now')` — use Python `utcnow()` value (psycopg2 binds datetime → TIMESTAMPTZ, sqlite3 binds via adapter to ISO TEXT):
   ```python
   db.execute("UPDATE evidence_items SET status='archived', updated_at=%s WHERE ...",
              (utcnow(),))
   ```

8. Add CI lint: `scripts/lint_sqlite_isms.sh`:
   ```bash
   #!/bin/bash
   set -e
   bad=$(grep -rn -E "datetime\('now'|date\('now'|julianday\(|fromisoformat\(row\[" oneforall/ | grep -v "to_dt\|sql_now_offset\|sql_date_offset\|sql_days_between" || true)
   if [ -n "$bad" ]; then echo "SQLite-ism leak:"; echo "$bad"; exit 1; fi
   ```
   Wire into pre-commit hook so new SQLite-only code can't sneak back in post-migration.

**Test gate:**
- Existing pytest suite still passes (SQLite — same SQL is generated).
- New scheduler tests pass on both engines.
- `scripts/lint_sqlite_isms.sh` returns 0.
- Manually run each affected scheduler on staging PG, confirm log output identical to SQLite staging run.

**Rollback:** `git revert`. Helpers are additive — leaving them in place is safe.

**Non-breakage controls:**
- New per-scheduler tests catch regressions before deploy.
- The advisory script's report is committed for traceability.
- The `sql_*_offset` helpers route through `is_postgres()` — flipping back to SQLite restores original SQL.

---

### Phase I — FTS5 → tsvector for Ask ARIA 🟡

**Goal:** Reimplement the Ask ARIA search infrastructure for PG, with the SQLite path unchanged.

**Steps:**
1. Rewrite `modules/aria/ask_service.py` `_FTS_DDL` and `init_index()`:
   ```python
   _FTS_DDL_SQLITE = """
   CREATE VIRTUAL TABLE IF NOT EXISTS aria_ask_index USING fts5(
       content_type, content_id, title, section, body, owner, framework,
       control_ref, url_path, tokenize = 'porter unicode61'
   );
   """
   _FTS_DDL_PG = """
   CREATE TABLE IF NOT EXISTS aria_ask_index (
       id            SERIAL PRIMARY KEY,
       content_type  TEXT NOT NULL,
       content_id    TEXT NOT NULL,
       title         TEXT,
       section       TEXT DEFAULT '',
       body          TEXT NOT NULL,
       owner         TEXT,
       framework     TEXT,
       control_ref   TEXT,
       url_path      TEXT,
       body_tsv      tsvector GENERATED ALWAYS AS (
           setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
           setweight(to_tsvector('english', coalesce(section, '')), 'B') ||
           setweight(to_tsvector('english', coalesce(body, '')), 'C')
       ) STORED
   );
   CREATE INDEX IF NOT EXISTS idx_aria_ask_index_tsv ON aria_ask_index USING GIN (body_tsv);
   CREATE INDEX IF NOT EXISTS idx_aria_ask_index_cid ON aria_ask_index (content_type, content_id);
   """
   ```

2. Rewrite `_build_fts_query()` to produce PG `to_tsquery` syntax:
   ```python
   def _build_fts_query(question: str) -> str:
       tokens = [t.lower() for t in _TOKEN_RE.findall(question)]
       tokens = [t for t in tokens if t not in _STOPWORDS and len(t) > 2]
       tokens = list(dict.fromkeys(tokens))[:12]
       if not tokens:
           return ""
       if settings.is_postgres():
           # PG to_tsquery: 'term1:* | term2:* | ...'
           return " | ".join(f"{re.sub(r'[^a-z0-9]', '', t)}:*" for t in tokens if t)
       # SQLite FTS5: 'term1* OR term2* ...'
       return " OR ".join(f"{t}*" for t in tokens)
   ```

3. Rewrite `search()`:
   ```python
   def search(question, k=8, framework_filter=""):
       q = _build_fts_query(question)
       if not q: return []
       db = get_db()
       try:
           if settings.is_postgres():
               sql = ("SELECT content_type, content_id, title, section, body, "
                      "owner, framework, control_ref, url_path, "
                      "ts_rank_cd(body_tsv, to_tsquery('english', %s)) AS score "
                      "FROM aria_ask_index "
                      "WHERE body_tsv @@ to_tsquery('english', %s) ")
               if framework_filter:
                   rows = db.execute(sql + "AND framework = %s ORDER BY score DESC LIMIT %s",
                                     (q, q, framework_filter, k)).fetchall()
                   if not rows:
                       rows = db.execute(sql + "ORDER BY score DESC LIMIT %s",
                                         (q, q, k)).fetchall()
               else:
                   rows = db.execute(sql + "ORDER BY score DESC LIMIT %s",
                                     (q, q, k)).fetchall()
           else:
               # ── existing SQLite FTS5 path unchanged ──
               ...
       finally:
           db.close()
       return [dict(r) for r in rows]
   ```

4. Index population in `_clear_by` / index-rebuild paths — works on both because they're simple `DELETE` + `INSERT`.

5. Add a one-off rebuild command for cutover:
   ```python
   def rebuild_index():
       """Drop and rebuild the aria_ask_index from source tables."""
       ...
   ```
   Run after Phase L's data migration so the index is freshly built from migrated data.

**Test gate:**
- New search test: index 20 sample policies, query with 5 representative questions, assert top-k results match on both engines (set comparison, not order).
- Existing ARIA pytest passes on SQLite.

**Rollback:** `git revert`. SQLite FTS5 path is preserved.

**Non-breakage controls:**
- Dual implementation: SQLite path untouched, PG path additive.
- Functional test asserts ranking parity on a curated dataset.

---

### Phase J — Alembic baseline 🟡

**Goal:** Capture the now-PG-clean schema in Alembic so future schema changes have a managed migration path.

**Steps:**
1. `pip install alembic==1.13.1`, add to `requirements.txt`.

2. `alembic init alembic` in `oneforall/`.

3. Edit `alembic/env.py`:
   ```python
   from config import settings
   config.set_main_option("sqlalchemy.url",
       settings.DATABASE_URL.replace("postgresql://",
           f"postgresql://themisiq:{_read_pg_password()}@", 1)
       if not settings.DATABASE_URL.startswith("postgresql://themisiq:")
       else settings.DATABASE_URL)
   ```
   (Inject the password from the secret file at runtime — never in alembic.ini.)

4. Generate the baseline migration:
   ```bash
   DATABASE_URL=postgresql://... alembic revision --autogenerate -m "baseline_themisiq_schema"
   ```
   Hand-review the generated migration — autogenerate misses CHECK constraints, expression indexes, GENERATED columns.

5. Wipe the staging PG, run `alembic upgrade head` from scratch, confirm 130+ tables created.

6. Update `entrypoint.sh` (already in Phase E): it runs `alembic upgrade head` once at container start, before workers.

**Test gate:**
- `alembic upgrade head` on a fresh PG creates all expected tables.
- `alembic downgrade base` cleanly drops everything.

**Rollback:** Delete the `alembic/` directory and the Alembic dependency.

**Non-breakage controls:**
- The autogenerated migration is **hand-reviewed and committed** before being run on staging — not blindly trusted.
- `init_db()` continues to work alongside Alembic; we'll deprecate `init_db()` for the PG path post-cutover but it's the fallback during transition.

---

### Phase K — Backup refactor 🟡

**Goal:** A backup script that works on both engines, doesn't leak credentials, doesn't lose uploads, and ships offsite.

**Steps:**
1. Rewrite `modules/grid/scheduler.py:perform_backup()`:
   ```python
   def perform_backup() -> None:
       import gzip, urllib.parse
       backup_dir = Path(os.getenv("BACKUP_PATH", "data/backups"))
       backup_dir.mkdir(parents=True, exist_ok=True)
       stamp = utcnow().strftime("%Y%m%d_%H%M%S")
       zip_path = backup_dir / f"themisiq-{stamp}.zip"
       if zip_path.exists():
           log.info("Backup already exists: %s", zip_path.name); return

       # 1. Snapshot the DB INTO the zip (don't write SQL to disk first)
       with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
           if settings.is_postgres():
               parsed = urllib.parse.urlparse(settings.DATABASE_URL)
               env = {**os.environ,
                      "PGPASSWORD": _read_pg_password(),
                      "PGSSLMODE": os.getenv("PGSSLMODE", "prefer")}
               cmd = ["pg_dump", "--no-owner", "--no-acl", "--format=custom",
                      "-h", parsed.hostname or "localhost",
                      "-p", str(parsed.port or 5432),
                      "-U", parsed.username or "themisiq",
                      "-d", (parsed.path or "/themisiq").lstrip("/")]
               res = subprocess.run(cmd, capture_output=True, env=env, timeout=600)
               if res.returncode != 0:
                   log.error("pg_dump failed: %s", res.stderr.decode()[:500])
                   zip_path.unlink(missing_ok=True); return
               zf.writestr("themisiq.dump", res.stdout)
           else:
               db_path = Path("data/oneforall.db")
               if db_path.exists():
                   zf.write(db_path, "oneforall.db")

           # 2. Include uploads + evidence (BOTH engines)
           for src_dir, arc_prefix in [
               (Path("data/grid_uploads"), "grid_uploads"),
               (Path("data/evidence"), "evidence"),
           ]:
               if src_dir.is_dir():
                   for fpath in src_dir.rglob("*"):
                       if fpath.is_file():
                           zf.write(fpath, f"{arc_prefix}/{fpath.relative_to(src_dir)}")

       # 3. Verify the zip
       try:
           with zipfile.ZipFile(zip_path, "r") as zf:
               if zf.testzip() is not None:
                   raise RuntimeError("zip integrity check failed")
       except Exception as e:
           log.error("Backup verify failed, removing: %s", e)
           zip_path.unlink(missing_ok=True); return

       # 4. Offsite copy to Cloudflare R2 (best-effort)
       remote = os.getenv("BACKUP_OFFSITE_RCLONE_REMOTE", "")  # e.g., "r2:themisiq-backups"
       if remote:
           try:
               # rclone with R2 config in /home/themisiq/.config/rclone/rclone.conf
               # (mounted from Docker secret to keep keys out of image).
               # Server-side encryption is enabled at the bucket level.
               result = subprocess.run(
                   ["rclone", "copy", str(zip_path), remote,
                    "--s3-no-check-bucket", "--retries", "3",
                    "--retries-sleep", "10s"],
                   capture_output=True, timeout=900,
               )
               if result.returncode != 0:
                   log.warning("R2 offsite backup failed: %s", result.stderr.decode()[:500])
               else:
                   log.info("R2 offsite backup OK: %s", zip_path.name)
           except Exception as e:
               log.warning("Offsite backup failed: %s", e)

       # 5. Local retention
       retain_days = int(os.getenv("BACKUP_RETAIN_DAYS", "30"))
       cutoff = utcnow().timestamp() - retain_days * 86400
       for old in backup_dir.glob("themisiq-*.zip"):
           if old.stat().st_mtime < cutoff:
               old.unlink(); log.info("Pruned %s", old.name)

       log.info("Backup OK: %s (%d KB)", zip_path.name, zip_path.stat().st_size // 1024)
   ```

2. Add `restore` companion (`scripts/restore_backup.py`) for documented DR:
   ```bash
   python scripts/restore_backup.py backups/themisiq-20260613_020000.zip --target-db $DATABASE_URL
   # OR pull from R2 first:
   python scripts/restore_backup.py r2:themisiq-backups/themisiq-20260613_020000.zip --target-db $DATABASE_URL
   ```
   - If source is `r2:` prefix: `rclone copy <remote> /tmp/` first.
   - Extracts uploads/evidence to disk.
   - Pipes `themisiq.dump` to `pg_restore --clean --if-exists`.
   - Validates row counts post-restore.

3. Add a `scripts/test_backup_restore.py` script that **runs in CI per release**:
   - Creates a staging PG with synthetic data.
   - Calls `perform_backup()`.
   - Drops the DB, restores from the backup.
   - Asserts row counts match.

4. Configure R2 bucket:
   - Name: `themisiq-backups`
   - Public access: **disabled**
   - Object lifecycle rule: delete after 90 days
   - Server-side encryption: enabled (R2 default)
   - Generate API token scoped to: `Object Read & Write` for this bucket only
   - Store credentials in Docker secret `r2_credentials.txt` containing the rclone config block:
     ```
     [r2]
     type = s3
     provider = Cloudflare
     access_key_id = <token>
     secret_access_key = <secret>
     endpoint = https://<account-id>.r2.cloudflarestorage.com
     acl = private
     ```
   - Mount as `/home/themisiq/.config/rclone/rclone.conf` in the app container.

**Test gate:**
- Local: `python -c "from modules.grid.scheduler import perform_backup; perform_backup()"` produces a verifiable zip.
- Staging: PG dump → restore round-trip succeeds and row counts match.
- Manual: tail Docker logs during backup, confirm **no password appears** in any log line or process listing.

**Rollback:** `git revert` restores the old SQLite-zip backup function. Since the old function still works for SQLite, this is safe.

**Non-breakage controls:**
- Old SQLite path is preserved within the same function via the `if settings.is_postgres()` branch.
- Verify-zip step (`zf.testzip()`) ensures a bad backup is deleted, not retained as a false-positive.
- CI-runnable restore test.

---

### Phase L — Data migration script 🔴

**Goal:** Move every row from prod SQLite → staging PG, with parity verification.

**Steps:**
1. `scripts/sqlite_to_postgres.py`:
   ```
   python scripts/sqlite_to_postgres.py \
       --sqlite data/oneforall.db \
       --postgres $DATABASE_URL \
       [--dry-run] [--tables table1,table2,...] [--verify-only]
   ```

2. Implementation outline:
   - Parses SQLite schema to extract column lists per table.
   - **Excludes GENERATED columns** (e.g., `risk_register.risk_score`).
   - **Topologically sorts** tables by FK references so parents go first. Use a 3-pass approach: tables with no FKs → tables whose FK targets are already migrated → repeat.
   - For each table:
     1. `SELECT col1, col2, ... FROM sqlite_table` (explicit columns, no `SELECT *`).
     2. Coerce timestamps: any value matching `^\d{4}-\d{2}-\d{2}` is left as TEXT. Empty strings → NULL.
     3. Batch INSERT into PG using `psycopg2.extras.execute_batch` (100 rows/batch).
     4. `INSERT INTO ... ON CONFLICT DO NOTHING` so partial reruns are safe.
   - After all tables: `SELECT setval(pg_get_serial_sequence('table', 'id'), GREATEST(COALESCE(MAX(id), 1), 1), MAX(id) IS NOT NULL) FROM table` for each table — handles empty tables correctly.
   - Parity report: row count per table side-by-side. Exits non-zero on mismatch.

3. Rehearse on staging:
   - Copy prod SQLite DB to staging VPS (offline copy from your laptop).
   - `python scripts/sqlite_to_postgres.py --sqlite copy.db --postgres $DATABASE_URL --dry-run`
   - Review report. Re-rehearse with `--apply`.
   - Run `scripts/verify_pg_parity.py` (next step).

4. `scripts/verify_pg_parity.py` — independent verifier:
   - Connects to both engines.
   - For each table: row count, MD5 of `array_agg(id ORDER BY id)`, sample-row content compare for 5 random rows.
   - Outputs PASS/FAIL per table.

**Test gate:**
- Staging migration parity report shows 0 mismatched tables.
- Sample queries through the running app (against staging PG) return same data as prod (against SQLite). Test 5 key views: ARIA dashboard, GRID audit detail, BCM plans list, Sentinel RoPA, ERM risk register.

**Rollback (cutover not started):** drop the staging PG database, the SQLite source is untouched.

**Non-breakage controls:**
- Prod remains on SQLite throughout; only a **copy** of prod SQLite touches staging PG.
- Independent verifier (`verify_pg_parity.py`) — separate code path from the migrator catches migrator bugs.
- `--dry-run` default forces conscious `--apply`.

---

### Phase M — Shadow mode (read-only validation against live data) 🔴

**Goal:** With prod still serving from SQLite, run a **shadow PG instance** populated from a fresh prod backup. Periodically diff its query results against prod. Build confidence before cutover.

**Steps:**
1. Take a fresh prod backup (`perform_backup()`).
2. On the VPS, spin up the PG container alongside the running SQLite app.
3. Restore prod data into PG via `scripts/sqlite_to_postgres.py`.
4. Run `scripts/verify_pg_parity.py` continuously for 48 h with a 6-hourly re-sync (sqlite → PG delta sync, or fresh full migration).
5. **Don't yet flip `DATABASE_URL` in prod.** The app continues on SQLite.
6. During shadow mode, also run a "warm replay" — capture a sample of recent read queries (from access logs) and execute them against PG, comparing row sets to SQLite.

**Test gate:** 48-hour shadow window with zero parity failures, plus warm-replay diff = empty.

**Rollback:** Tear down the shadow PG container; prod was never touched.

**Non-breakage controls:**
- Production traffic still goes to SQLite throughout. PG is read-only.
- 48 hours captures at least one full backup cycle, one weekly digest (Monday morning), and several days of scheduler runs.

---

### Phase N-pre-monitor — Monitoring before go-live 🔴 (MANDATORY, gates Phase N)

**Goal:** Three observability primitives are running and verified **before** cutover. Without them, a silent failure during or after cutover is invisible until users complain.

**M.1 — Uptime Kuma (uptime / health monitoring)**

Self-hosted on the same VPS (or, better, on a separate small VPS to survive prod outages):
```yaml
# Add to docker-compose.yml on monitoring host
services:
  uptime-kuma:
    image: louislam/uptime-kuma:1
    restart: unless-stopped
    volumes:
      - kuma_data:/app/data
    ports: ["127.0.0.1:3001:3001"]   # reverse-proxy via nginx with basic auth
    mem_limit: 256m

volumes:
  kuma_data:
```

Configure monitors:
- HTTPS `https://themisiq.net/health` — 30s interval, 3 retries before alert, expect 200.
- HTTPS `https://themisiq.net/ready` — 1m interval, expect 200 (catches DB connectivity drops).
- TCP `127.0.0.1:5432` from app host — 1m interval, catches PG-container-down.
- HTTPS `https://themisiq.net/login` — 5m interval, expect 200, content match "ThemisIQ" (catches reverse-proxy/template breakage).
- Push monitor "scheduler heartbeat" — `core/reminder_scheduler.py` pings Kuma at end of each run; alert if no ping in 90 minutes (catches silent scheduler death).

Alert channels: email to Ali + 4-eyes reviewer + Slack/Telegram webhook. Quiet hours: never (compliance tool, must alert 24/7).

Status page: public read-only page at `https://status.themisiq.net` (separate Cloudflare subdomain) so users self-serve outage info.

**M.2 — Daily backup verification**

A cron-driven verifier that confirms the daily 02:00 CAT backup is not corrupt and is restorable. **A backup nobody tests is not a backup.**

Add `scripts/verify_latest_backup.py`:
```python
#!/usr/bin/env python3
"""Run daily at 03:00 CAT — verifies the most recent backup
is structurally sound by listing pg_dump contents and unpacking
the zip. Does NOT restore (that's the weekly drill, M.4)."""
import subprocess, sys, zipfile
from pathlib import Path

BACKUP_DIR = Path(__file__).parent.parent / "data" / "backups"
latest = max(BACKUP_DIR.glob("themisiq-*.zip"), key=lambda p: p.stat().st_mtime, default=None)
if latest is None or (latest.stat().st_mtime < (... < 24h ago)):
    raise SystemExit("FAIL: no backup in last 24h")

# 1. Zip integrity
with zipfile.ZipFile(latest) as zf:
    bad = zf.testzip()
    if bad: raise SystemExit(f"FAIL: corrupt entry {bad}")
    if "themisiq.dump" not in zf.namelist():
        raise SystemExit("FAIL: pg_dump missing from zip")
    zf.extract("themisiq.dump", "/tmp/")

# 2. pg_dump structural check (does not need a DB)
res = subprocess.run(["pg_restore", "--list", "/tmp/themisiq.dump"],
                     capture_output=True, timeout=60)
if res.returncode != 0 or b"TABLE DATA" not in res.stdout:
    raise SystemExit("FAIL: pg_restore --list rejected the dump")

# 3. R2 presence — confirm the offsite copy made it
res = subprocess.run(["rclone", "lsf", f"r2:themisiq-backups/{latest.name}"],
                     capture_output=True, timeout=30)
if res.returncode != 0:
    raise SystemExit(f"FAIL: {latest.name} not found on R2")

print(f"PASS: {latest.name} verified ({latest.stat().st_size // 1024} KB)")
```

Wire to APScheduler as a 12th job (`backup_verify_check`) running 03:00 CAT daily. On FAIL: writes to logs, raises critical-severity notification via existing `_notify_admins`, pings Uptime Kuma push monitor "backup-verify" (which alerts if no ping in 25h).

**M.3 — Disk-space alerts**

VPS-level (because Docker can't see itself running out). Three primitives:

1. **systemd timer or root cron** `/etc/cron.daily/disk-check`:
   ```bash
   #!/bin/bash
   THRESHOLD=80
   for mount in / /var/lib/docker /home; do
       usage=$(df --output=pcent "$mount" 2>/dev/null | tail -1 | tr -d ' %')
       [ -z "$usage" ] && continue
       if [ "$usage" -ge "$THRESHOLD" ]; then
           echo "DISK ALERT: $mount at ${usage}%" | mail -s "[ThemisIQ VPS] Disk at ${usage}%" ali@example.com
       fi
   done
   ```
   Two-tier: 80% = warn, 90% = critical (separate cron entry, with louder destination — Slack webhook, not email).

2. **Uptime Kuma push monitor** "disk-headroom" — the cron above pings it on success; Kuma alerts if no ping in 25h (catches the cron itself failing).

3. **Docker volume monitor** — the PG `pgdata` volume and the `data/backups`/`data/grid_uploads`/`data/evidence` host bind mounts:
   ```bash
   # Add to disk-check above
   pg_size=$(docker exec themisiq-db-1 du -sh /var/lib/postgresql/data | cut -f1)
   echo "[$(date)] pgdata size: $pg_size" >> /var/log/themisiq-disk.log
   ```
   Log rotated weekly, kept for 6 months — gives a growth-rate baseline so capacity decisions are data-driven.

**M.4 — Weekly restore drill (in addition to daily verify)**

Sunday 04:00 CAT — pull yesterday's backup from R2, restore into a scratch PG container, row-count check against prod. Failure pages on-call. This is what M.2 doesn't do (M.2 only structurally validates; M.4 actually restores).

Add `scripts/weekly_restore_drill.py` — invoked by APScheduler. Spins up `postgres:16-alpine` in a temp Docker container with `--rm`, restores, runs verify_pg_parity against prod (read-only diff query — row counts only, not row content), tears down. Total runtime budget: 30 minutes.

**Acceptance criteria for Phase N-pre-monitor:**
- Uptime Kuma running, alert channels tested (deliberately break `/health` for 90s, confirm email + Slack alert fires; restore).
- `verify_latest_backup.py` running on schedule, has succeeded for **at least 3 consecutive days** before cutover.
- Disk-space cron has fired and logged at least 2 times before cutover.
- Weekly restore drill has run **at least once** successfully on staging PG.
- Status page reachable, content correct.

**Without M.1, M.2, M.3, and M.4 verifiably running, Phase N (cutover) does not proceed.**

**Effort:** 1 day to stand up + 3 days of soak time waiting for daily/weekly cycles to demonstrate they work.

---

### Phase N-pre — Formal Rollback Plan 🔴 (MANDATORY, gates Phase N — per P-7)

**Goal:** A separate signed-off document covering every realistic failure mode of cutover, with measured rollback timings from a dry run on staging. **Phase N cannot start until this artifact is approved and rehearsed.**

**Deliverable:** `ROLLBACK_PLAN.md` in the repo root, containing:

1. **Rollback decision authority** — named individual (the 4-eyes reviewer) authorised to call rollback. Backup decision-maker named in case primary is unreachable.

2. **Rollback decision tree** — for each smoke-test failure mode, the explicit YES/NO action:
   | Symptom | Auto-rollback or escalate? | Threshold |
   |---|---|---|
   | `/health` returns 5xx for >60s after cutover | Auto-rollback | T+18 hard limit |
   | Any one smoke-test item fails | Investigate 5min, then escalate | Within window |
   | Two or more smoke-test items fail | Auto-rollback | Immediate |
   | PG connection error rate >1% in 5 minutes | Auto-rollback | Immediate |
   | Scheduler crashes within 1 hour post-cutover | Investigate, escalate | If non-trivial |
   | Single non-critical module renders error | Hot-patch attempt within window, else rollback | 15min budget |
   | Data anomaly reported by user | Triage; rollback if confirmed | Same day |

3. **Three rollback procedures**, each measured by dry-run:

   **R-1: Soft rollback (env-var flip, <5 min)** — for any failure within the maintenance window before traffic is restored.
   ```bash
   # 1. Edit docker-compose .env: comment out DATABASE_URL
   # 2. docker compose up -d app
   # 3. Confirm /health returns 200
   # 4. Confirm logs show "Initialising database..." from SQLite path
   # 5. Run smoke tests again on SQLite
   ```
   Expected time: 3–5 minutes. Data risk: zero (prod SQLite file untouched throughout cutover).

   **R-2: Mid-flight rollback (within 1 hour post-cutover)** — if a serious bug is found after traffic is restored but before any significant new data has been written to PG.
   ```bash
   # 1. Re-enable Cloudflare maintenance page (page rule).
   # 2. Stop app: docker compose stop app
   # 3. Quick-export new PG rows: scripts/export_pg_delta.py --since "<cutover timestamp>"
   #    Captures any rows created in PG that aren't in the pre-cutover SQLite snapshot.
   # 4. Flip DATABASE_URL=, restart app on SQLite.
   # 5. Apply delta (manually inspect first; auto-import if safe).
   # 6. Confirm /health, lift maintenance page.
   ```
   Expected time: 15–30 minutes. Data risk: low if delta is small; manual review of delta is required.

   **R-3: Hard rollback (>1 hour post-cutover, significant divergence)** — if a critical bug is found late and PG already has substantial new data. This is the **worst case** we're explicitly planning for.
   ```bash
   # 1. Re-enable maintenance page.
   # 2. Full pg_dump of current PG state to a separate file.
   # 3. Stop app.
   # 4. Make irreversible decision: which data set is the source of truth?
   #    Option A: keep PG data, fix bug forward in PG.
   #    Option B: revert to pre-cutover SQLite, accept loss of post-cutover data.
   #    This is a business decision, not a technical one.
   # 5. If Option A: hot-patch forward.
   #    If Option B: restore pre-cutover SQLite backup, run scripts/export_pg_delta.py
   #    for forensic record, restart on SQLite, communicate data loss to affected users.
   ```
   Expected time: 1–3 hours. **Required to be communicated to users**.

4. **Pre-cutover backup verification checklist:**
   - [ ] Prod SQLite DB backed up to laptop AND to R2.
   - [ ] Backup tested by restoring to staging within last 24 hours.
   - [ ] Uploads and evidence directories backed up.
   - [ ] PG dump from staging (last shadow sync) backed up to R2.
   - [ ] All three R-1, R-2, R-3 procedures dry-run on staging at least once. Times recorded.

5. **Communication templates** — pre-written stakeholder messages for each rollback scenario.

6. **Post-rollback retrospective trigger** — any rollback must trigger an incident review within 48 hours; document follows the standard ThemisIQ incident review template.

**Acceptance criteria for Phase N-pre:**
- Document exists, peer-reviewed, signed by Ali + 4-eyes reviewer.
- All three rollback procedures dry-run on staging, with timings recorded in the document.
- Decision tree reviewed against the smoke test checklist (Phase N).
- Communication templates approved.

**Without these, Phase N does not proceed.** This is the P-7 gate.

---

### Phase N — Cutover 🔴 (the actual switch)

**Goal:** Flip prod from SQLite to PG with a maintenance window.

**Locked schedule:** Saturday 18:00 CAT (16:00 UTC). 1-hour advertised window, 30-minute target.

**Pre-cutover (T-7d):** Email users: "Scheduled maintenance Saturday 18:00 CAT, expected 1 hour. ThemisIQ will be read-only/offline."

**Pre-cutover (T-24h):**
1. Resend user email reminder.
2. Final pre-cutover backup of prod SQLite + uploads + evidence taken, verified, copied to R2 AND to local laptop.
3. Final dress rehearsal on staging: full migration + smoke test + measured cutover time + R-1/R-2/R-3 rollback dry-run.
4. Cutover runbook printed. Rollback decision tree printed. Both Ali AND 4-eyes reviewer have copies.
5. 4-eyes reviewer confirms availability via call or message.

**Pre-cutover (T-1h):**
1. Final user email: "Maintenance starts in 1 hour."
2. 4-eyes reviewer joins voice call.
3. Both have shells on the VPS and the rollback runbook open.

**Cutover window (estimated 30 minutes):**
1. `T+0`: Enable maintenance page (Cloudflare page rule → static "Maintenance" HTML). Confirm.
2. `T+1`: Stop the app container (`docker compose stop app`). Schedulers stop.
3. `T+2`: Final SQLite backup → S3.
4. `T+3`: Final `sqlite_to_postgres.py --apply --postgres $DATABASE_URL` against prod PG (which has been kept in sync via shadow mode).
5. `T+10`: `scripts/verify_pg_parity.py` against prod SQLite + prod PG. Must PASS or **abort**.
6. `T+15`: Set `DATABASE_URL=postgresql://themisiq@pgbouncer:5432/themisiq` in the app container's `.env`.
7. `T+16`: `docker compose up -d app` — entrypoint runs `alembic upgrade head` (should be no-op, schema already there), starts uvicorn.
8. `T+18`: Hit `/health` and `/ready` — both 200.
9. `T+19`: Smoke test checklist (see N+1 below). Each item passes or we initiate rollback.
10. `T+25`: Remove Cloudflare maintenance page.
11. `T+30`: Monitor logs for 1 hour, then declare cutover complete.

**Smoke test checklist (must all pass before lifting maintenance):**
- Login as admin user.
- Dashboard renders without errors.
- ARIA: open document list, open a single document, view body.
- GRID: open an audit, view controls, upload one evidence file.
- BCM: open a plan, edit a field, save.
- Sentinel: open RoPA, list breaches.
- ERM: open enterprise risks list.
- ORM: open events list.
- Evidence Vault: list items, view detail.
- Global search: search "policy" and "iso", confirm results.
- Ask ARIA: ask 2 known-good questions, confirm citations.
- Trigger a manual backup (`perform_backup()`), confirm zip created and verified.
- Check `/health` and `/ready` end-to-end.

**Rollback (if any smoke test fails):** Execute the appropriate procedure from `ROLLBACK_PLAN.md` (Phase N-pre):
- **Within window, before traffic restored:** R-1 (soft rollback, ~3–5 min).
- **Within 1 hour post-cutover:** R-2 (mid-flight rollback, ~15–30 min).
- **Beyond 1 hour with diverged data:** R-3 (hard rollback, business decision required).

Both Ali AND the 4-eyes reviewer must agree on the rollback decision per the documented authority chain.

The key non-breakage property: **the prod SQLite file is never modified during cutover.** PG is a fresh copy. Rolling back R-1 is a single env-var flip + container restart, measured at 3–5 minutes in the dry-run.

---

### Phase O — Post-cutover hardening (1 week after) 🟢

**Goal:** Tighten security and operational posture once PG is the source of truth.

**Steps:**
1. After 7 days of clean PG operation, archive the last-known-good SQLite backup to cold storage; remove SQLite-specific test fixtures.
2. Rotate the PG password (the migration-time password was visible to anyone watching the cutover):
   ```bash
   docker compose exec db psql -U themisiq -c "ALTER ROLE themisiq PASSWORD 'new-strong-password'"
   ```
   Update `secrets/pg_password.txt`. Restart `app` and `pgbouncer`.
3. Enable PG's `pg_stat_statements`, set up basic query monitoring.
4. Confirm offsite backups have been arriving daily for 7 days. Test a restore from the most recent offsite backup on a scratch instance.
5. Confirm Cloudflare WAF / rate-limit rules are active.
6. Add automated daily restore-test to a scratch DB (catches silent backup corruption).
7. Schedule a quarterly DR drill: restore from offsite into a scratch VPS, validate.

---

## Cross-cutting controls summary

| Control | Where it applies | What it prevents |
|---|---|---|
| `is_postgres()` runtime switch | Phases A onward | Single rollback point; no rebuild needed |
| `_PgConnWrapper` / `_SqliteConnWrapper` | Phase F+G | Identical app code on both engines |
| `insert_returning_id` helper | Phase B | 89 silent-None bugs |
| `database.IntegrityError` shim | Phase D | Exception-type rebinding |
| `sql_*_offset` helpers | Phase H | Date math portability |
| Engine-conditional FTS5/tsvector | Phase I | Search feature preserved |
| Dual schema strings | Phase F | PG syntax errors at init |
| `entrypoint.sh` for migrations | Phase E | Alembic race with workers |
| `PGPASSWORD_FILE` + Docker secret | Phase E+K | Credential leakage on command line and in logs |
| Bind PG to 127.0.0.1 | Phase E | Public PG exposure |
| PgBouncer in front of PG | Phase E | Connection exhaustion |
| Zip-with-uploads backup | Phase K | Backup losing customer evidence |
| Backup verify step | Phase K | Silent backup corruption |
| Offsite backup | Phase K+O | VPS loss |
| `scripts/verify_pg_parity.py` | Phases L, M, N | Data migration silent loss |
| Shadow mode (Phase M) | Phase M | Cutover on unvalidated PG |
| Maintenance window + pre-flight backup | Phase N | Catastrophic cutover failure |
| Single-env-var rollback path | Phase N | Locked into broken PG |
| Quarterly DR drill | Phase O | Backup-restore atrophy |

---

## Acceptance criteria for each phase (Definition of Done)

A phase is **done** only when **all** of these are true:

1. Code committed to a feature branch, peer-reviewed.
2. `pytest` passes locally on SQLite path with new tests.
3. (Phase F+) `pytest` passes against staging PG.
4. Documented rollback command verified to work.
5. CHANGELOG entry written.
6. No new `TODO` or `FIXME` introduced without an issue link.
7. No new dependency added without a security note (pinned version, hash, source).
8. Branch deployed to staging, smoke-tested for the affected modules.
9. Merged to `main` only after items 1–8.

---

## Risk register (residual, after controls applied)

| Risk | Mitigation in plan | Residual |
|---|---|---|
| psycopg2 build fails on VPS | Use `psycopg2-binary` (pre-built wheels) | Low |
| PG version drift (16 → 17) breaks GENERATED column syntax | Pin `postgres:16-alpine` in compose | Very low |
| Connection pool exhaustion under load spike | PgBouncer + per-worker pool=10 + alerting | Low |
| Backup → restore time exceeds maintenance window for large data | Pre-cutover shadow-sync keeps PG hot; only delta replays at cutover | Low |
| Cloudflare → nginx misconfiguration after maintenance | Pre-cutover dry-run of maintenance page on/off | Low |
| Schedules run during cutover & corrupt data | Schedulers stop with app at T+1; restart at T+18 | Very low |
| Password rotation forgotten in Phase O | Tracked as ticket; alert if `password_last_changed > 90d` | Low |
| New developer writes SQLite-only SQL post-migration | CI lint: `grep -r "datetime('now'" oneforall/ \|\| true` — warn if found | Low |
| Disk fills with backups | Retention prune in `perform_backup`; disk-usage alert at 80% (Phase N-pre-monitor M.3) | Low |
| Silent backup corruption | Daily `verify_latest_backup.py` + weekly restore drill (Phase N-pre-monitor M.2, M.4) | Very low |
| Prod outage undetected | Uptime Kuma multi-monitor + push heartbeats (Phase N-pre-monitor M.1) | Low |
| Scheduler dies silently | Push heartbeat to Uptime Kuma at end of each scheduler run | Low |
| Worker count insufficient under real load | Start with WORKERS=2, raise to 4 via env-var change + container restart (no code) once monitoring shows queueing | Low |

---

## Estimated timeline

| Phase | Effort | Risk |
|---|---|---|
| Pre-flight | 0.5 day | none |
| A — Shims | 0.5 day | none |
| B — `.lastrowid` refactor | 1.5 days | low |
| C — INSERT OR IGNORE | 0.5 day | none |
| D — Exception types | 0.5 day | none |
| E — Infra on staging | 1 day | none |
| F — `database.py` rewrite | 2 days | medium |
| G — Placeholder script | 1 day | medium |
| H — Date functions + TIMESTAMPTZ read-site refactor | **3 days** (was 1.5; TIMESTAMPTZ adds ~50–80 read-site edits) | medium |
| I — FTS5 → tsvector | 1.5 days | medium |
| J — Alembic baseline | 0.5 day | low |
| K — Backup refactor (with R2) | 1 day | low |
| L — Data migration script | 2 days (TIMESTAMPTZ coercion adds care; the same `timestamp_columns.json` from Phase F drives both sides) | medium |
| M — Shadow mode | 2 days (mostly wait time) | low |
| **N-pre-monitor — Uptime Kuma + backup verify + disk alerts (NEW)** | **1 day active + 3 days soak** | high if skipped |
| **N-pre — Rollback plan + dry-runs** | **1.5 days** | high if skipped |
| N — Cutover | 0.5 day (30-min target window, 1-hour advertised) | high |
| O — Post-cutover | spread over 1 week | low |
| **Total active work** | **~20 days** (was 19) | |
| **Wall-clock** (with shadow + monitoring soak window) | **~4.5 weeks** | |

---

## Sign-off

By approving this plan, you accept:

- The **19-day engineering estimate** (revised from 16 to account for the TIMESTAMPTZ read-site refactor).
- Phase N (cutover) will use the **Saturday 18:00 CAT** maintenance window (1 hour advertised, 30 minutes target).
- A staging VPS is available throughout (or a scratch namespace on prod that won't be touched).
- **P-5 (TIMESTAMPTZ)** is now in scope — the read-side refactor of ~50–80 sites happens in Phase H.
- **P-6 (co-located PG)** — single docker-compose with postgres:16-alpine + PgBouncer + app.
- Cloudflare R2 will host offsite backups via rclone.
- **P-7 (formal rollback plan)** is mandatory — the cutover (Phase N) is gated by a signed, dry-run rollback plan (Phase N-pre).
- **Pre-go-live monitoring** (Uptime Kuma + daily backup verification + disk-space alerts + weekly restore drill) is mandatory — cutover (Phase N) is also gated by Phase N-pre-monitor.
- Initial uvicorn worker count is **2** (raised to 4 only when observed load justifies).

**Decisions LOCKED (signed off 2026-06-13):**

| Decision | Value |
|---|---|
| P-5 timestamps | TIMESTAMPTZ |
| P-6 PG hosting | Co-located on the VPS |
| Backups offsite | Cloudflare R2 |
| Maintenance window | Saturday 18:00 CAT |
| 4-eyes reviewer | Trusted engineer / architect (name TBD ≥7 days pre-cutover) |
| P-7 rollback plan | Mandatory |

**Approver:** Ali Moyo                **Date:** 2026-06-13

---

*Remaining items to action before kick-off:*

1. Provision Cloudflare R2 bucket + generate scoped API token (pre-flight P-8).
2. Confirm 4-eyes reviewer name + book in calendar (pre-flight P-9). Hard deadline: 7 days before cutover.
3. Allocate staging VPS (pre-flight P-7-was-staging).
4. Provision the monitoring VPS or decide to co-locate Uptime Kuma on prod (pre-flight P-11).
5. Pick the alert channel and test it end-to-end (pre-flight P-12).
6. Decide first kick-off date — Phase A can start immediately as it's zero-risk on SQLite.
7. Begin drafting `ROLLBACK_PLAN.md` in parallel with Phase A (it's a multi-week artifact, not a last-week one).
8. Begin Uptime Kuma setup in parallel — needs 3+ days of "soak time" successfully observing the SQLite-era prod before cutover, so start early.
