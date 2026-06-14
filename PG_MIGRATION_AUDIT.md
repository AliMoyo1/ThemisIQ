# PostgreSQL Migration Plan — Audit & Risk Register

**Audited against:** ThemisIQ codebase at `C:\Projects\One For All\One For All\oneforall`
**Date:** 2026-06-13
**Audit goal:** Verify the proposed PG migration plan against the actual code; surface gaps and risks before any code change.

---

## Verdict

The plan is **directionally correct but materially incomplete**. Executed as written, the application will fail to start on PostgreSQL (PRAGMA in schema string, `executescript` not in psycopg2), schedulers will crash on every cron (SQLite date math everywhere), and the ARIA "Ask ARIA" search feature will be silently broken (FTS5 → no PG equivalent in plan). At least **8 CRITICAL gaps** must be closed before execution.

---

## Inventory — plan claims vs. reality

| Claim | Plan says | Actual | Status |
|---|---|---|---|
| Files touching DB | 40 | 48 (`db.execute`/`cur.execute`/`cursor.execute`) | Plan undercounted by ~20% |
| `?` SQL placeholders | ~618 | 1,169 raw `?` occurrences across 45 files (includes non-SQL); ~600 placeholders is a defensible lower bound | Order of magnitude correct |
| `INSERT OR IGNORE` files | 12 listed | **13 — `main.py` startup migration missed** | Gap |
| `INSERT OR REPLACE` files | 2 | 2 (matches) | OK |
| `LIKE → ILIKE` files | "~6" | **14 files, ~45 occurrences** | Plan undercounted by 2× |
| `.lastrowid` count | "grep to find" | **89 occurrences across 22 files** | Plan deferred |
| `aiosqlite` unused | Yes | Confirmed — only in `requirements.txt` | OK |
| Tables | 131 | Schema strings define 130+ tables | Approx. matches |

---

## CRITICAL gaps (will break in production)

### C1. FTS5 / Ask ARIA search has no PG equivalent in the plan
`modules/aria/ask_service.py` lines 33–58, 326–356.

```sql
CREATE VIRTUAL TABLE IF NOT EXISTS aria_ask_index USING fts5(...)
SELECT ... bm25(aria_ask_index) AS score FROM aria_ask_index WHERE aria_ask_index MATCH ?
```

PostgreSQL has no FTS5. The plan omits this entirely. Without action, the "Ask ARIA" Q&A feature (a core ARIA capability) silently returns empty results.

**Fix:** Replace FTS5 with PG's `tsvector` + GIN index + `to_tsquery()` + `ts_rank_cd()`. Add a dedicated table `aria_ask_index` with a `body_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', body)) STORED`. Rewrite `_build_fts_query()` to produce `to_tsquery` syntax (`term1 | term2:*` style). Estimated: 1 file, ~200 LOC change.

### C2. SQLite date/time math in 20 files — not in placeholder script
SQLite-only constructs the `?`→`%s` script will miss:

| Construct | Occurrences | Examples |
|---|---|---|
| `date('now', '+/-N days')` | 44 across 12 files | `grid/scheduler.py:112,342,446`, `evidence/routes.py:75,802,821`, `bcm/scheduler.py:95,156,217`, `sentinel/scheduler.py:371`, `launcher/routes_dashboard.py:156,315`, `evidence/routes.py:75`, `erm/data_service.py:696,700,708` |
| `datetime('now', '-N days')` | 249 across 18 files | `grid/scheduler.py:62,63`, `erm/data_service.py:696`, etc. |
| `julianday('now') - julianday(col)` | 3 sites | `core/predictive_risk.py:107,141`, `erm/data_service.py:1091` |
| `datetime(col)` cast | several | `grid/scheduler.py:62` `datetime(r.last_sent) < datetime('now', '-6 days')` |

**Fix:** All become PG syntax:
- `date('now', '+30 days')` → `CURRENT_DATE + INTERVAL '30 days'`
- `datetime('now', '-7 days')` → `NOW() - INTERVAL '7 days'`
- `julianday('now') - julianday(col)` → `EXTRACT(EPOCH FROM (NOW() - col::timestamptz)) / 86400`

This is the largest blind spot in the plan. Without it, all 5 schedulers crash on every cron, dashboards return errors, expiry warnings stop firing. Recommend a **second automated script** (`scripts/pg_migrate_date_functions.py`) targeting these specific patterns, or sed-style find/replace with manual review.

### C3. `_run_migrations()` contains seed data — plan would skip it on PG
Plan says: "Guard with `if not is_postgres()` — PostgreSQL schema evolution is handled by Alembic going forward."

But `_run_migrations()` in `database.py` (lines 2162–3057) does **more than ALTER TABLE**:
- 15 expected frameworks (lines 2448–2479)
- 6 BCM communication templates (2482–2521)
- 8 BCM exercise scenarios (2522–2618)
- ERM risk appetite seeds (2664–2684)
- 25 ERM library entries (2686–2728)
- ~32 ORM event templates (2747–3057)
- Jurisdiction configuration (2620–2661)
- Canonical vendor linking data migration (2419–2445)

Guarding the entire function with `if not is_postgres()` would mean **zero seed data on PG**. The app launches but every module renders empty pickers.

**Fix:** Split `_run_migrations()` into:
- `_run_sqlite_only_alters()` — guarded
- `_run_data_seeds(conn)` — runs on both backends (with `?` → `%s` applied, and `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING` applied)

### C4. `PRAGMA` statements **inside the schema string** for ERM/ORM tables
`database.py` lines 1777–1778:

```python
_ERM_ORM_TABLES = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
...
```

Plan only removes PRAGMAs from `get_db()`. Running this schema string against PG raises `SyntaxError: PRAGMA`. **`init_db()` fails on first PG startup.**

**Fix:** Remove these two lines from the schema string (they are redundant — `get_db()` already sets them in SQLite).

### C5. `executescript()` doesn't exist in psycopg2
`database.py:3065-3070` calls `conn.executescript(_SHARED_TABLES)` 6 times. `ask_service.py:55` calls `db.executescript(_FTS_DDL)` once.

psycopg2 cursors have no `executescript`. The `_PgConnWrapper` in the plan doesn't implement it.

**Fix:** Add `executescript(sql)` method to `_PgConnWrapper` that splits on `;` (excluding semicolons inside string literals) and executes each statement, OR wraps the whole thing in a single `cur.execute(sql)` — psycopg2 supports multi-statement strings via simple query protocol when no parameters are passed.

### C6. Backup loses upload files + leaks DB password
`modules/grid/scheduler.py:285–319` — current `perform_backup()` backs up **BOTH** `data/oneforall.db` AND `data/grid_uploads/` into a single zip. Plan replaces this with `pg_dump` only — **the uploads backup vanishes**. Customer evidence files, signed reports, and uploaded policy PDFs would have no scheduled backup.

Additionally, plan's `subprocess.run(["pg_dump", settings.DATABASE_URL, ...])` puts the **DB password on the command line**. On Windows Task Manager and `ps aux` on Linux, this leaks. Per project rules ("no security flaws"), this is a hard fail.

**Fix:**
1. Keep the zip approach — `pg_dump` writes inside the zip, plus existing uploads dir.
2. Use `PGPASSWORD` env var or a `.pgpass` file. Strip password from `DATABASE_URL` before passing to `pg_dump`:
```python
import urllib.parse
parsed = urllib.parse.urlparse(settings.DATABASE_URL)
env = {**os.environ, "PGPASSWORD": parsed.password or ""}
sanitized_url = settings.DATABASE_URL.replace(f":{parsed.password}@", ":***@")
subprocess.run(["pg_dump", "--no-owner", "--no-acl",
                "-h", parsed.hostname, "-p", str(parsed.port or 5432),
                "-U", parsed.username, "-d", parsed.path.lstrip("/")],
               env=env, ...)
```
3. Respect existing `BACKUP_PATH` env var; don't hardcode.
4. Add backup verification step: `pg_restore --list backup.dump` or `gunzip -t backup.sql.gz` post-write.
5. Add backup encryption at rest (compliance data) — at minimum, mention in plan that backups need filesystem encryption or GPG.

### C7. Alembic `upgrade head` on startup races with `--workers 4`
Plan: `main.py` startup calls `command.upgrade(alembic_cfg, "head")`. With `uvicorn --workers 4`, **four worker processes call this concurrently on startup**. Alembic does take a lock via `alembic_version`, but race conditions during initial migration can still cause `relation already exists` errors and worker startup failures.

**Fix:** One of:
1. Pre-uvicorn init container: Dockerfile `ENTRYPOINT ["./entrypoint.sh"]` that runs `alembic upgrade head` once, then `exec uvicorn ...`.
2. PG advisory lock around the upgrade (`SELECT pg_advisory_lock(...)`).
3. Only worker 0 runs migration (detect via env var).

Option 1 is cleanest.

### C8. TIMESTAMPTZ vs TEXT — semantic change not addressed
Plan's schema mapping: `TEXT` (with `datetime('now')` default) → `TIMESTAMPTZ DEFAULT NOW()`.

But the codebase has hundreds of patterns like:
- `db.execute("UPDATE x SET updated_at=? WHERE id=?", (utcnow().isoformat(), ...))` — writes ISO string
- `datetime.fromisoformat(row["expires_at"])` — reads as string
- `WHERE x.expiry_date > date('now')` — TEXT comparison

If columns become TIMESTAMPTZ, psycopg2 returns `datetime` objects for them. `datetime.fromisoformat(datetime_obj)` raises TypeError. **Every read site needs adjustment.**

**Fix — pick one:**
- **(A) Keep TEXT columns in PG** — simplest. Set timestamps in app as ISO strings throughout. Sacrifices indexability and PG date functions, but matches existing app behavior.
- **(B) Switch to TIMESTAMPTZ properly** — touch every `fromisoformat()` (~50 sites) and replace TEXT comparisons with proper PG date arithmetic. Larger change but more idiomatic.

Plan implies (B) but doesn't budget for the read-side work. Recommendation: **(A) for migration, (B) as follow-up** — get to PG faster, refactor types later.

---

## HIGH-severity gaps (silent corruption / data loss)

### H1. SQLite exception types caught explicitly
- `main.py:280–281` — `@app.exception_handler(sqlite3.OperationalError)` global handler.
- `core/auto_mapper.py:430,460` — `sqlite3.OperationalError`, `sqlite3.IntegrityError`.
- `core/vendor_link.py:53` — `sqlite3.IntegrityError`.
- `modules/aria/ask_service.py:340,348,355` — three FTS5 fallbacks.
- `tests/test_canonical_vendor.py:72` — `pytest.raises(sqlite3.IntegrityError)`.
- `database.py:2365,2408` — `sqlite3.OperationalError`, `sqlite3.IntegrityError`.

In PG mode these catches never trigger; the equivalent `psycopg2.errors.UniqueViolation` / `SerializationFailure` bubbles up as 500s.

**Fix:** Add `database.DatabaseLockError`, `database.IntegrityError` aliases:
```python
if is_postgres():
    import psycopg2.errors as _pgerr
    IntegrityError = _pgerr.IntegrityError
    LockError = _pgerr.OperationalError  # plus DeadlockDetected, etc.
else:
    IntegrityError = sqlite3.IntegrityError
    LockError = sqlite3.OperationalError
```
Replace all `sqlite3.*` exception catches with `database.*`.

### H2. `.lastrowid` — 89 sites across 22 files
Plan defers to "grep to find". psycopg2 cursors return `None` from `.lastrowid` for any non-OID table (i.e. all of them). Every site silently returns `None` instead of the new row's ID — IDs disappear into `INSERT INTO link_table (parent_id, ...) VALUES (NULL, ...)`.

Top affected files:
- `modules/bcm/data_service.py` — 23 sites
- `modules/grid/data_service.py` — 23 sites
- `modules/erm/data_service.py` — 9 sites
- `modules/orm/data_service.py` — 7 sites
- `core/event_handlers.py` — 10 sites
- `modules/aria/routes.py` — 4 sites
- Others — 13 sites

**Fix:** Append `RETURNING id` to every `INSERT` followed by `.lastrowid`, then change `.lastrowid` to `.fetchone()["id"]`. This is mechanical but high-volume. Consider a helper:
```python
def insert_returning_id(db, sql, params):
    if is_postgres():
        row = db.execute(sql.rstrip(";") + " RETURNING id", params).fetchone()
        return row["id"]
    else:
        return db.execute(sql, params).lastrowid
```
Then transform `cur.lastrowid` → `insert_returning_id(db, sql, params)`.

### H3. LIKE → ILIKE — silent search regression
Plan: "6 files". **Reality: 14 files, ~45 occurrences.** SQLite `LIKE` is case-insensitive for ASCII by default; PG `LIKE` is case-sensitive.

After migration, every search box that uses `LIKE %term%` returns case-sensitive results — users typing "iso 27001" find nothing because the data says "ISO 27001". No error is raised. **Silent feature regression** across global search, evidence search, vendor search, audit search, etc.

Files (all 14):
- `modules/launcher/routes_platform.py` (api_global_search — 15 LIKE sites)
- `modules/sentinel/data_service.py` (8 sites)
- `modules/grid/data_service.py` (4 sites)
- `modules/erm/data_service.py` (2 sites)
- `modules/aria/routes.py` (2 sites)
- `modules/launcher/routes_admin.py` (2 sites)
- `modules/evidence/routes.py` (2 sites)
- `core/event_handlers.py` (3 sites)
- `core/framework_service.py` (1 site)
- `modules/bcm/data_service.py` (1 site)
- `modules/bcm/scheduler.py` (1 site)
- `modules/evidence/scheduler.py` (1 site)
- `seeds/control_mappings.py` (2 sites)

**Fix:** Replace all `LIKE` with `ILIKE` in PG mode. Either:
- Define `_LIKE = "ILIKE" if is_postgres() else "LIKE"` and string-interpolate at construction time (low risk — operator, not value).
- Mechanical search-and-replace — `LIKE ?` → `ILIKE ?` is safe everywhere in this codebase (no LIKE relies on case-sensitivity).

Recommend the second approach: simpler diff, no runtime branch.

### H4. `_PgConnWrapper` semantics undefined
Plan sketches `_PgConnWrapper` but skips critical detail:
- Existing pattern: `db = get_db(); db.execute(...).fetchone(); ...; db.close()` — `.close()` must return conn to pool, not close it.
- `.execute(sql, params)` returns a cursor — does each call open a new cursor (cursor proliferation) or reuse one (state collision)?
- `.commit()` / `.rollback()` semantics.
- `.row_factory = sqlite3.Row` → `cursor_factory=RealDictCursor` per cursor or per connection.
- `db.execute(...).rowcount` after UPDATE — must work (plan doesn't show).
- Context-manager behavior (`with conn:`) — psycopg2 auto-commits inside `with` block, which differs from sqlite3.

**Fix:** Spec out `_PgConnWrapper` precisely before writing it. Suggest:
```python
class _PgConnWrapper:
    def __init__(self, conn, pool):
        self._conn, self._pool = conn, pool
        self._cursors = []
    def execute(self, sql, params=None):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        self._cursors.append(cur)
        cur.execute(sql, params or ())
        return cur
    def executescript(self, sql):
        cur = self._conn.cursor()
        cur.execute(sql)
        cur.close()
    def commit(self): self._conn.commit()
    def rollback(self): self._conn.rollback()
    def close(self):
        for c in self._cursors:
            try: c.close()
            except Exception: pass
        self._cursors = []
        self._pool.putconn(self._conn)
    def __enter__(self): return self
    def __exit__(self, *a): self.close()
```

### H5. Connection pool exhaustion under load
Plan: `POSTGRES_POOL_MAX=20`. With 4 uvicorn workers, 5 schedulers, and 11 cron jobs, plus user requests, 20 is tight. Worse: every call to `get_db()` checks out a NEW connection. The existing code pattern `db = get_db(); ... db.close()` works on SQLite (file handle, cheap) but stresses a connection pool.

**Fix:** Either (a) raise default to 50 with hard upper bound, (b) introduce request-scoped DB dependency via FastAPI `Depends()`, (c) document that pool sizing is per-worker × workers.

### H6. Test fixture incompatibility
`tests/conftest.py:29` — `monkeypatch.setattr(database, "_DB_PATH", str(tmp_path / "test.db"))`. With PG mode, `_DB_PATH` is gone. Plan acknowledges but doesn't show the working fixture.

**Fix:** Either:
- Keep SQLite for tests (set `DATABASE_URL=""` in conftest, ensure dual-mode `is_postgres()` returns False).
- Switch tests to PG — per-test transactional fixtures wrapping the entire test in `BEGIN; ROLLBACK`, never committing. Faster than per-test schema rebuilds.

Recommend the first for now; the second as follow-up.

### H7. Data migration script — edge cases unaddressed
- **Generated column conflict:** `risk_register.risk_score INTEGER GENERATED ALWAYS AS (likelihood * impact) STORED`. Inserting `risk_score` from SQLite into PG fails — `cannot insert into column "risk_score"`. Plan needs `SELECT *` with explicit column lists per table.
- **Foreign key ordering:** Plan doesn't specify table migration order. Children before parents → FK violations. Need topological sort or `SET CONSTRAINTS ALL DEFERRED`.
- **Sequence reset off-by-one:** Plan: `SELECT setval('table_id_seq', COALESCE(MAX(id),1))`. This sets `is_called=true`, so next insert returns `MAX(id)+1`. Correct, but if `MAX(id)=0` (empty table after migration of zero rows), next insert gives 2 instead of 1. Use `setval(seq, MAX(id), MAX(id) > 0)` for safety.
- **Timestamp coercion:** TEXT timestamps in SQLite vary: `'2024-01-15'`, `'2024-01-15 10:30:00'`, ISO with `T`, literal `'datetime(\'now\')'` for old default. Plan says "with fallback" — needs to handle: empty string, NULL, ISO date-only, ISO datetime, ISO with timezone.

### H8. `INSERT OR IGNORE` plan misses `main.py`
`main.py:81-86`:
```python
db2.execute(
    "INSERT OR IGNORE INTO frameworks ...",
    (...),
)
```
Plan's 12-file list doesn't include this. Adds one site to fix.

---

## MEDIUM-severity gaps

### M1. Docker compose security defaults
- `ports: ["5432:5432"]` — exposes PG on host's port 5432. Plan notes "remove in production" — but easy to forget. Bind to `"127.0.0.1:5432:5432"` by default.
- `POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}` from `.env` — fine, but no minimum-length / complexity check. Add a startup assertion in `config.py` rejecting weak DB passwords in production.
- No `read_only: true` on app container, no `cap_drop: [ALL]`, no `security_opt: no-new-privileges`. Plan to harden for enterprise deployment.

### M2. Windows hosting — Docker Desktop assumptions
Project rule says "enterprise tool to be hosted on a windows laptop". Plan's docker-compose mounts `./backups`, `./uploads` (POSIX-relative). On Windows, these map under WSL2 paths and have different file-locking semantics. `pg_dump` from inside a Linux container writing to a Windows-host-mounted volume is slow and can corrupt large backups. Mention in plan or recommend native PG install on Windows + native Python app instead of Docker.

### M3. Backup retention — no verify, no offsite, no encryption
Plan: 30-day local retention, `gzip` compression. For an enterprise GRC tool storing compliance data:
- No verify step after write (`gunzip -t`)
- No offsite copy (S3, blob, etc.) — single-host failure loses all backups
- No encryption at rest

These are out of scope for migration but worth flagging.

### M4. `ON CONFLICT` conflict targets — verify uniqueness
Plan lists tables for `INSERT OR IGNORE → ON CONFLICT DO NOTHING` but doesn't confirm each table has a UNIQUE constraint matching the conflict target. Verified during audit:
- `aria_control_mappings` — `UNIQUE(source_control_id, target_control_id)` ✓
- `bcm_comm_templates` — no UNIQUE; `INSERT OR IGNORE` only works because tested via `existing_tmpl == 0` check. Either add `UNIQUE(title)` or use the count guard.
- `bcm_scenario_library` — no UNIQUE; same situation.
- `orm_event_templates` — no UNIQUE; same.
- `erm_risk_appetite` — `UNIQUE(category)` ✓
- `erm_risk_library` — no UNIQUE; need to add or use guard.

**Fix:** Audit each `INSERT OR IGNORE` site for matching UNIQUE constraint; add constraints where missing, OR keep the count-guarded pattern that already exists in seeds.

---

## LOW-severity / notes

- `RANDOM()` in `modules/aria/routes.py:2044` — works in both engines. ✓
- `lower(trim(name))` expression indexes — works in PG. ✓
- `GENERATED ALWAYS AS (...) STORED` for `risk_score` — PG 12+ supports identical syntax. ✓
- `CHECK(action IN (...))` — works in PG. ✓
- `CURRENT_TIMESTAMP` default in `aria_ask_log.created_at` (line 646) — works in PG. ✓
- `ON CONFLICT` already used in 5 places — codebase partially PG-compatible already. ✓
- `aiosqlite` removable — confirmed. ✓

---

## Recommended execution order (revised)

1. **Pre-work — audit accept gates**
   - Approve this risk register
   - Decide: TIMESTAMPTZ migration approach (recommend Option A — keep TEXT)
   - Decide: deployment target (Docker vs. native PG on Windows)

2. **Phase A — code changes that work on SQLite too** (no PG required, no behavioral change)
   - Add `is_postgres()` helper to `config.py` (returns False always, until DATABASE_URL set)
   - Add `database.IntegrityError` / `database.LockError` aliases
   - Refactor `_run_migrations()` — split into ALTER section and seed section
   - Replace `LIKE ?` with `ILIKE ?` everywhere (works on SQLite via PRAGMA `case_sensitive_like = 0` — currently default)
     - **Actually no — SQLite doesn't support ILIKE.** Use the conditional operator approach.
   - Introduce `insert_returning_id(db, sql, params)` helper, refactor all 89 `.lastrowid` sites
   - Replace all `sqlite3.OperationalError`/`IntegrityError` catches with `database.*`
   - Run pytest — should still pass on SQLite

3. **Phase B — PG-compatible SQL rewrites** (still works on SQLite)
   - Convert `INSERT OR IGNORE` → `ON CONFLICT DO NOTHING` (works on SQLite 3.24+, PG)
   - Convert `INSERT OR REPLACE` → `ON CONFLICT DO UPDATE` (works on both)
   - For each conflict site, verify UNIQUE constraint exists or add it
   - Run pytest

4. **Phase C — Build PG infrastructure** (no app changes yet)
   - `Dockerfile`, `docker-compose.yml` (with security hardening from M1)
   - Initial Alembic config (don't auto-generate yet)
   - Document password handling (`PGPASSWORD` / `.pgpass`)
   - Stand up dev PG instance, validate connection

5. **Phase D — Dual-mode `database.py` rewrite**
   - Implement `_PgConnWrapper` (full spec from H4)
   - Branch schema strings: SQLite version (unchanged) + PG version (no PRAGMA, SERIAL, TIMESTAMPTZ-or-TEXT decision applied)
   - Implement `executescript` for PG (multi-statement support)
   - `init_db()` dispatches by mode
   - Write `scripts/pg_migrate_placeholders.py` — `?` → `%s` script with multi-line / triple-string handling
   - Dry-run, review diff, apply

6. **Phase E — Date/time function migration** (CRITICAL — biggest blind spot in original plan)
   - Write `scripts/pg_migrate_date_functions.py`:
     - `date('now', '+N days')` → `(CURRENT_DATE + INTERVAL 'N days')`
     - `datetime('now', '-N days')` → `(NOW() - INTERVAL 'N days')`
     - `julianday('now') - julianday(X)` → `EXTRACT(EPOCH FROM (NOW() - X::timestamptz)) / 86400`
     - `datetime(X)` casts → `X::timestamptz`
   - Run script in `--dry-run` mode against all 20 affected files
   - Manual review (date math has subtle semantic shifts — esp. timezone handling between `CURRENT_DATE` and TEXT comparisons)
   - Apply

7. **Phase F — FTS5 → tsvector migration** (CRITICAL)
   - Rewrite `modules/aria/ask_service.py`:
     - Drop `CREATE VIRTUAL TABLE`, replace with real table + `body_tsv tsvector` + GIN index
     - Replace `MATCH ?` with `body_tsv @@ to_tsquery(?, ?)` (language as first arg)
     - Replace `bm25(table)` with `ts_rank_cd(body_tsv, query)`
     - Rewrite `_build_fts_query()` to PG `to_tsquery` syntax

8. **Phase G — Alembic + startup**
   - Generate initial Alembic migration from rewritten PG schema
   - Refactor `main.py` startup to **not** call Alembic upgrade — put it in Dockerfile entrypoint
   - Add `psycopg2.errors.OperationalError` to global exception handler (or use `database.LockError`)

9. **Phase H — Backup refactor**
   - Rewrite `perform_backup()`:
     - Keep zip approach including `data/grid_uploads/`
     - `pg_dump` via env-var password (not command line)
     - Respect existing `BACKUP_PATH` env var
     - Add `gunzip -t` / `pg_restore --list` verification step
     - Log dump size + verification result

10. **Phase I — Data migration script**
    - `scripts/sqlite_to_postgres.py`:
      - Topologically sort tables by FK
      - Per-table column list excluding GENERATED columns
      - Timestamp coercion with full edge-case coverage
      - `ON CONFLICT DO NOTHING` per UNIQUE constraint OR truncate-then-insert pattern
      - Sequence reset with `is_called` flag
      - Row count parity check; exit non-zero on mismatch
      - Dry-run mode

11. **Phase J — Tests**
    - Update `tests/conftest.py` to keep SQLite for tests
    - Add `TEST_DATABASE_URL` opt-in path for PG integration tests
    - Add new PG-specific tests: concurrent writes, connection pool, backup/restore round-trip

12. **Phase K — Smoke test on PG**
    - All 6 modules
    - All 11 scheduled jobs
    - Backup trigger + restore round-trip
    - Global search (verifies ILIKE)
    - Ask ARIA Q&A (verifies tsvector migration)
    - 3 concurrent browser sessions writing

---

## Files the original plan did not mention but must be touched

| File | Why |
|---|---|
| `oneforall/main.py` lines 81-86 | INSERT OR IGNORE in startup migration |
| `oneforall/main.py` lines 280-302 | sqlite3.OperationalError global handler |
| `oneforall/core/auto_mapper.py` lines 430, 460 | sqlite3 exception catches |
| `oneforall/core/vendor_link.py` line 53 | sqlite3.IntegrityError catch |
| `oneforall/core/predictive_risk.py` lines 107, 141 | julianday() expressions |
| `oneforall/core/event_handlers.py` line 1858 | LIKE → ILIKE (LOWER(col) LIKE pattern) |
| `oneforall/modules/erm/data_service.py` line 1091 | julianday() expression |
| `oneforall/modules/aria/ask_service.py` (entire file) | FTS5 → tsvector |
| `oneforall/modules/aria/ask_service.py` lines 340, 348, 355 | sqlite3.OperationalError catches |
| `oneforall/modules/sentinel/scheduler.py` line 371 | date('now', '+30 days') |
| `oneforall/modules/bcm/scheduler.py` lines 69, 95, 156, 217 | date math + LIKE |
| `oneforall/modules/evidence/scheduler.py` line 59 | LIKE pattern |
| `oneforall/modules/evidence/routes.py` lines 75, 802, 821 | date math |
| `oneforall/modules/launcher/routes_dashboard.py` lines 156, 315 | date math |
| `oneforall/modules/launcher/routes_platform.py` lines 106-224 | 15 LIKE sites in api_global_search |
| `oneforall/tests/test_canonical_vendor.py` line 72 | sqlite3.IntegrityError in assertion |
| `oneforall/.env.example` | DATABASE_URL example |

---

## Bottom line

The original plan correctly identifies the spine of the migration but misses (in descending impact order):
1. **FTS5 search infrastructure** for the Ask ARIA feature
2. **SQLite date/time math** in 20+ files of business logic
3. **Seed data** inside `_run_migrations()` that the plan would skip
4. **PRAGMA inside the ERM schema string** that crashes init
5. **`executescript` API gap** in psycopg2
6. **Backup losing uploads + leaking DB password**
7. **Alembic race condition** with multiple uvicorn workers
8. **TIMESTAMPTZ type semantics** breaking read paths

Closing these gaps approximately doubles the plan's scope and adds **~1 week of careful work** beyond what the original plan implies. I recommend proceeding in phases A→K above rather than the linear order in the original plan.

Would you like me to:
- (a) draft the revised execution plan as a fresh document for sign-off, or
- (b) start executing Phase A (the SQLite-compatible code changes that have zero risk), or
- (c) write the two missing scripts (`pg_migrate_date_functions.py`, dual-mode `_PgConnWrapper` spec) for review before any application code changes?
