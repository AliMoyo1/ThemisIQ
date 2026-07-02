"""
One For All — unified SQLite database.

Single DB file with module-prefixed tables.  WAL mode for concurrency.
All queries use parameterised statements — never interpolate user input.
"""
import sqlite3
import os
import re
import threading
import datetime as _dt
from contextvars import ContextVar
from pathlib import Path
from config import settings

# ── Engine-portable exception types ──────────────────────────────────────────
if settings.is_postgres():
    import psycopg2
    import psycopg2.extras
    import psycopg2.pool
    import psycopg2.extensions
    IntegrityError = psycopg2.IntegrityError
    OperationalError = psycopg2.OperationalError
    # TransactionRollbackError covers DeadlockDetected + SerializationFailure.
    LockError = psycopg2.extensions.TransactionRollbackError
else:
    IntegrityError = sqlite3.IntegrityError
    OperationalError = sqlite3.OperationalError
    LockError = sqlite3.OperationalError

# LIKE operator — ILIKE on PG (case-insensitive), LIKE on SQLite (default ASCII CI)
LIKE_OP: str = "ILIKE" if settings.is_postgres() else "LIKE"

# Resolve DB path relative to this file so it never depends on CWD
_DB_PATH = str(
    (Path(__file__).parent / settings.DB_PATH).resolve()
    if not Path(settings.DB_PATH).is_absolute()
    else Path(settings.DB_PATH)
)

_pg_pool: "psycopg2.pool.ThreadedConnectionPool | None" = None
_pg_pool_lock = threading.Lock()

# Per-request tenant context. Set by tenant middleware after session validation.
# ContextVar is propagated correctly across asyncio tasks unlike thread-local.
_current_tenant: ContextVar = ContextVar("current_tenant", default=None)
_current_org_id: ContextVar = ContextVar("current_org_id", default=None)
_current_is_super: ContextVar = ContextVar("current_is_super", default=False)


def set_current_tenant(slug: str):
    """Set the tenant for the current async context (called by middleware)."""
    _current_tenant.set(slug)


def get_current_tenant() -> str:
    """Return the slug of the current request's tenant, or None for public schema."""
    return _current_tenant.get()


def set_current_org(org_id: "int | None", is_super_admin: bool = False):
    """Set the org context for RLS enforcement in the current async context."""
    _current_org_id.set(org_id)
    _current_is_super.set(is_super_admin)


def _ensure_dir():
    Path(_DB_PATH).parent.mkdir(parents=True, exist_ok=True)


def _read_pg_password() -> str:
    """Read PG password from Docker secret file, falling back to PGPASSWORD env var."""
    secret_file = os.environ.get("PGPASSWORD_FILE", "")
    if secret_file and os.path.isfile(secret_file):
        return Path(secret_file).read_text().strip()
    return os.environ.get("PGPASSWORD", "")


def _get_pg_pool() -> "psycopg2.pool.ThreadedConnectionPool":
    """Return (or lazily create) the module-level PostgreSQL connection pool."""
    global _pg_pool
    if _pg_pool is None:
        with _pg_pool_lock:
            if _pg_pool is None:
                import urllib.parse as _up
                dsn = settings.DATABASE_URL
                pw = _read_pg_password()
                if pw:
                    parts = _up.urlsplit(dsn)
                    host_port = parts.hostname + (f":{parts.port}" if parts.port else "")
                    dsn = _up.urlunsplit(parts._replace(
                        netloc=f"{parts.username}:{_up.quote(pw, safe='')}@{host_port}"
                    ))
                _pg_pool = psycopg2.pool.ThreadedConnectionPool(
                    settings.POSTGRES_POOL_MIN,
                    settings.POSTGRES_POOL_MAX,
                    dsn,
                )
    return _pg_pool


def _pg_normalise_value(v):
    """Convert PostgreSQL datetime/date/timedelta to ISO strings, matching SQLite TEXT output."""
    if isinstance(v, _dt.datetime):
        return v.isoformat(sep=' ')[:19]
    if isinstance(v, _dt.date):
        return v.isoformat()
    if isinstance(v, _dt.timedelta):
        return str(v)
    return v


class _NormRow:
    """Wraps a psycopg2 DictRow, coercing datetime/date values to ISO strings.

    Supports both dict-style (row["col"]) and positional (row[0]) access,
    so every existing call site works without modification.
    """
    __slots__ = ('_r',)

    def __init__(self, row):
        self._r = row

    def __getitem__(self, key):
        return _pg_normalise_value(self._r[key])

    def get(self, key, default=None):
        v = self._r.get(key, default)
        return _pg_normalise_value(v)

    def keys(self):
        return self._r.keys()

    def values(self):
        return [_pg_normalise_value(v) for v in self._r.values()]

    def items(self):
        return [(k, _pg_normalise_value(v)) for k, v in self._r.items()]

    def __iter__(self):
        return iter(self._r.keys())

    def __len__(self):
        return len(self._r)

    def __contains__(self, key):
        return key in self._r

    def __repr__(self):
        return repr(dict(self.items()))


class _NormCursor:
    """Cursor wrapper that applies _NormRow to all fetched rows."""

    def __init__(self, cur):
        self._cur = cur

    def fetchone(self):
        r = self._cur.fetchone()
        return _NormRow(r) if r is not None else None

    def fetchall(self):
        return [_NormRow(r) for r in self._cur.fetchall()]

    def __iter__(self):
        for r in self._cur:
            yield _NormRow(r)

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _PgConnWrapper:
    """Mimics the sqlite3.Connection interface over a pooled psycopg2 connection.

    Uses DictCursor so rows support both row["col"] and row[0] access,
    matching the sqlite3.Row behaviour all existing call sites rely on.
    """

    def __init__(self, pgconn):
        self._conn = pgconn

    def _is_alive(self) -> bool:
        """Check whether the pooled connection is still usable."""
        try:
            self._conn.cursor().execute("SELECT 1")
            self._conn.rollback()
            return True
        except Exception:
            return False

    def execute(self, sql: str, params=None):
        cur = self._conn.cursor(cursor_factory=psycopg2.extras.DictCursor)
        # Pass None (not empty tuple) when no params so psycopg2 skips
        # its % formatter — literal LIKE '%value%' in SQL would otherwise crash.
        try:
            cur.execute(sql, params if params else None)
        except Exception:
            # PostgreSQL marks the whole transaction as aborted after any error.
            # Roll back so subsequent queries on this connection don't all fail
            # with "current transaction is aborted". Re-raise so callers still
            # see the original exception (their try/except blocks still fire).
            try:
                self._conn.rollback()
            except Exception:
                pass
            raise
        return _NormCursor(cur)

    def executemany(self, sql: str, seq):
        cur = self._conn.cursor()
        cur.executemany(sql, seq)
        return cur

    def executescript(self, sql: str):
        """Execute a multi-statement DDL script, silently skipping PRAGMA lines."""
        cur = self._conn.cursor()
        for stmt in sql.split(";"):
            stmt = "\n".join(
                ln for ln in stmt.splitlines()
                if not ln.strip().upper().startswith("PRAGMA")
            ).strip()
            if not stmt:
                continue
            has_sql = any(
                ln.strip() and not ln.strip().startswith("--")
                for ln in stmt.splitlines()
            )
            if has_sql:
                cur.execute(stmt)
        return cur

    def set_tenant(self, slug: str):
        """Set search_path for this connection to the tenant's schema.

        slug='public' keeps the default public schema (used by the default org
        so existing data needs no migration). Any other slug resolves to
        tenant_{slug} with public as fallback (for shared tables like users).
        """
        if slug == "public":
            cur = self._conn.cursor()
            cur.execute("SET search_path TO public")
            return
        safe = re.sub(r"[^a-z0-9_]", "", slug.lower())
        cur = self._conn.cursor()
        cur.execute(f"SET search_path TO tenant_{safe}, public")

    def set_rls_context(self, org_id: "int | None", is_super: bool = False):
        """Set session variables used by RLS policies.

        Uses SET (session-level, not LOCAL) so the value survives COMMIT within
        a single handler that calls commit() mid-flight. _clear_rls_context()
        in close() resets them before the connection returns to the pool.
        """
        cur = self._conn.cursor()
        cur.execute("SET app.current_org_id = %s", (str(org_id) if org_id else '',))
        cur.execute("SET app.is_super_admin = %s", ('true' if is_super else 'false',))
        cur.execute("SET app.bypass_rls = 'false'")

    def set_rls_bypass(self):
        """Grant unrestricted access to RLS-protected tables for this connection."""
        cur = self._conn.cursor()
        cur.execute("SET app.bypass_rls = 'true'")
        cur.execute("SET app.current_org_id = ''")
        cur.execute("SET app.is_super_admin = 'false'")

    def _clear_rls_context(self):
        try:
            cur = self._conn.cursor()
            cur.execute("SET app.current_org_id = ''")
            cur.execute("SET app.is_super_admin = 'false'")
            cur.execute("SET app.bypass_rls = 'false'")
        except Exception:
            pass

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        pool = _get_pg_pool()
        try:
            # Clear RLS context and roll back any open/aborted transaction before
            # returning the connection to the pool. This prevents a failed query
            # or stale org context from poisoning the next caller.
            self._clear_rls_context()
            self._conn.rollback()
        except Exception:
            pool.putconn(self._conn, close=True)
            return
        pool.putconn(self._conn)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc_val, _exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()
        return False


# ── SQLite placeholder-rewriting wrapper (Phase G) ────────────────────────────
_STRLIT_RE    = re.compile(r"'(?:''|[^'])*'")   # protect SQL string literals
_PCT_S_RE     = re.compile(r"%s")
_NAMED_PCT_RE = re.compile(r"%\((\w+)\)s")


def _percent_s_to_question(sql: str) -> str:
    """Replace %s with ? and %(name)s with :name outside SQL string literals.

    All SQL strings in the codebase use %s placeholders (psycopg2-style) after
    Phase G.  This rewriter lets sqlite3 receive what it expects while keeping
    every call site engine-agnostic. Named params %(key)s (used by Sentinel's
    _generic_create) become :key for sqlite3's named-parameter support.
    """
    out, last = [], 0
    for m in _STRLIT_RE.finditer(sql):
        seg = sql[last:m.start()]
        seg = _NAMED_PCT_RE.sub(r":\1", seg)
        seg = _PCT_S_RE.sub("?", seg)
        out.append(seg)
        out.append(m.group(0))
        last = m.end()
    seg = sql[last:]
    seg = _NAMED_PCT_RE.sub(r":\1", seg)
    seg = _PCT_S_RE.sub("?", seg)
    out.append(seg)
    return "".join(out)


class _SqliteConnWrapper:
    """Wraps sqlite3.Connection to accept %s placeholders (psycopg2-style).

    After Phase G all SQL strings in the codebase use %s; this wrapper
    silently rewrites them to ? so SQLite continues to work unchanged.
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def execute(self, sql: str, params=None):
        return self._conn.execute(_percent_s_to_question(sql), params or ())

    def executemany(self, sql: str, seq):
        return self._conn.executemany(_percent_s_to_question(sql), seq)

    def executescript(self, sql: str):
        return self._conn.executescript(sql)   # DDL: no placeholders

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc_val, _exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()
        return False


def _pg_get_conn() -> "_PgConnWrapper":
    """Get a live PostgreSQL connection from the pool."""
    pool = _get_pg_pool()
    conn = pool.getconn()
    wrapper = _PgConnWrapper(conn)
    if not wrapper._is_alive():
        pool.putconn(conn, close=True)
        conn = pool.getconn()
        wrapper = _PgConnWrapper(conn)
    conn.autocommit = False
    return wrapper


def get_db(timeout: int = 15):
    """Return a database connection.

    PostgreSQL: returns a _PgConnWrapper from the thread-safe pool.
    SQLite: returns a _SqliteConnWrapper (rewrites %s → ? transparently).
    Waits up to `timeout` seconds for a write lock (SQLite) or raises on pool
    exhaustion (PostgreSQL) before the global lock-error handler returns a 503.
    """
    if settings.is_postgres():
        wrapper = _pg_get_conn()
        slug = _current_tenant.get()
        if slug:
            wrapper.set_tenant(slug)
        org_id = _current_org_id.get()
        is_super = bool(_current_is_super.get())
        if org_id is not None or is_super:
            wrapper.set_rls_context(org_id, is_super)
        return wrapper
    conn = sqlite3.connect(_DB_PATH, timeout=timeout)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute(f"PRAGMA busy_timeout={timeout * 1000}")
    conn.execute("PRAGMA cache_size=-64000")
    conn.execute("PRAGMA temp_store=MEMORY")
    return _SqliteConnWrapper(conn)


def get_db_background():
    """Return a short-timeout connection for background / scheduler jobs.

    Background jobs must never hold the write queue and block user requests.
    A 3-second timeout means they fail fast and log a warning instead of
    queueing behind a user write.
    """
    return get_db(timeout=3)


def get_db_bypass_rls():
    """Return a connection that bypasses all RLS policies.

    Use ONLY for:
    - Authentication (username lookup before org is known)
    - Session validation (token lookup before org is known)
    - Schema provisioning and migrations
    - Super-admin platform management tasks

    Never use for ordinary user-facing queries.
    """
    if settings.is_postgres():
        wrapper = _pg_get_conn()
        wrapper.set_rls_bypass()
        return wrapper
    return get_db()


def insert_returning_id(db, sql: str, params):
    """Engine-portable INSERT that returns the new row's id.

    SQLite: uses cursor.lastrowid.
    PostgreSQL: appends RETURNING id and reads it back.
    Returns None when ON CONFLICT DO NOTHING suppresses the insert.
    """
    if settings.is_postgres():
        cur = db.execute(sql.rstrip(" ;") + " RETURNING id", params)
        row = cur.fetchone()
        return row["id"] if row else None
    return db.execute(sql, params).lastrowid


# ── Engine-portable date/time SQL helpers ─────────────────────────────────────

def sql_now_offset(offset_expr: str) -> str:
    """SQL fragment for NOW() ± interval, cast to text.
    Use only for TEXT columns (e.g. last_sent TEXT).
    For TIMESTAMPTZ columns use sql_now_ts()."""
    if settings.is_postgres():
        sign, qty, unit = offset_expr[0], *offset_expr[1:].strip().split()
        return f"(NOW() {sign} INTERVAL '{qty} {unit}')::text"
    return f"datetime('now', '{offset_expr}')"


def sql_now_ts(offset_expr: str) -> str:
    """SQL fragment for NOW() ± interval returning a native timestamp.
    Use for columns that are TIMESTAMPTZ in PostgreSQL, i.e. those declared
    TEXT DEFAULT (datetime('now')) in the shared schema — _to_pg_schema
    rewrites those to TIMESTAMPTZ DEFAULT NOW()."""
    if settings.is_postgres():
        sign, qty, unit = offset_expr[0], *offset_expr[1:].strip().split()
        return f"(NOW() {sign} INTERVAL '{qty} {unit}')"
    return f"datetime('now', '{offset_expr}')"


def sql_date_offset(offset_expr: str) -> str:
    """SQL fragment for CURRENT_DATE ± interval, cast to text.
    Use only for TEXT date columns.
    For TIMESTAMPTZ or DATE columns use sql_date_ts()."""
    if settings.is_postgres():
        sign, qty, unit = offset_expr[0], *offset_expr[1:].strip().split()
        return f"(CURRENT_DATE {sign} INTERVAL '{qty} {unit}')::text"
    return f"date('now', '{offset_expr}')"


def sql_date_ts(offset_expr: str) -> str:
    """SQL fragment for CURRENT_DATE ± interval returning a native date/timestamp.
    Use for columns that are TIMESTAMPTZ or DATE in PostgreSQL."""
    if settings.is_postgres():
        sign, qty, unit = offset_expr[0], *offset_expr[1:].strip().split()
        return f"(CURRENT_DATE {sign} INTERVAL '{qty} {unit}')"
    return f"date('now', '{offset_expr}')"


def sql_current_date() -> str:
    """Current date as a text-compatible expression for TEXT date columns.

    PostgreSQL CURRENT_DATE is type 'date'; comparing it to a TEXT column
    raises 'operator does not exist: text < date'. Casting to ::text makes
    the comparison work correctly for ISO-format dates stored as TEXT.
    SQLite's date('now') already returns a text string.
    """
    if settings.is_postgres():
        return "CURRENT_DATE::text"
    return "date('now')"


def sql_current_timestamp() -> str:
    """Current datetime as a text-compatible expression for TEXT datetime columns.

    PostgreSQL NOW() is type 'timestamptz'; comparing it to a TEXT column
    raises 'operator does not exist: text < timestamptz'. Casting to ::text
    returns an ISO-format string comparable with datetime('now') values stored
    as TEXT in both SQLite and PostgreSQL.
    """
    if settings.is_postgres():
        return "NOW()::text"
    return "datetime('now')"


def sql_days_between(col1: str, col2: str) -> str:
    """SQL fragment returning the number of days between two date/timestamp cols."""
    if settings.is_postgres():
        return f"EXTRACT(EPOCH FROM ({col1}::timestamptz - {col2}::timestamptz)) / 86400"
    return f"(julianday({col1}) - julianday({col2}))"


# ─────────────────────────────────────────────────────────────────────────────
# Schema creation
# ─────────────────────────────────────────────────────────────────────────────

_SHARED_TABLES = """
-- ── Multi-tenancy: Organisations & Licences ─────────────────────────────────
-- These tables always live in the public schema.
-- Each org's module data lives in its own tenant_{slug} schema.
-- The "public" slug is special: maps to the public schema directly (default org).
CREATE TABLE IF NOT EXISTS organizations (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    slug       TEXT UNIQUE NOT NULL,
    plan       TEXT DEFAULT 'starter',
    status     TEXT DEFAULT 'active',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS licenses (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    org_id      INTEGER NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    module_keys TEXT NOT NULL DEFAULT 'aria,bcm,erm,grid,orm,sentinel',
    seats       INTEGER DEFAULT 10,
    valid_from  TEXT DEFAULT (datetime('now')),
    valid_until TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

-- ── Users & Auth ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS users (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    username            TEXT UNIQUE NOT NULL,
    email               TEXT UNIQUE NOT NULL,
    full_name           TEXT NOT NULL,
    password_hash       TEXT NOT NULL,
    is_active           INTEGER DEFAULT 1,
    must_change_password INTEGER DEFAULT 0,
    avatar_initials     TEXT,
    last_login          TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS user_roles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role_key    TEXT NOT NULL,
    granted_by  INTEGER REFERENCES users(id),
    granted_at  TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, role_key)
);
CREATE INDEX IF NOT EXISTS idx_user_roles_user ON user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_user_roles_role ON user_roles(role_key);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    token       TEXT UNIQUE NOT NULL,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    ip_address  TEXT,
    user_agent  TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
CREATE INDEX IF NOT EXISTS idx_sessions_user  ON sessions(user_id);

-- ── Two-Factor Authentication (TOTP) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_mfa (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id       INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    totp_secret   TEXT NOT NULL,
    backup_codes  TEXT NOT NULL DEFAULT '[]',
    is_enabled    INTEGER DEFAULT 0,
    enrolled_at   TEXT,
    last_used_at  TEXT,
    created_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_user_mfa_user ON user_mfa(user_id);

-- ── Platform Audit Log ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id),
    username    TEXT,
    module      TEXT,
    action      TEXT NOT NULL,
    entity_type TEXT,
    entity_id   INTEGER,
    details     TEXT,
    ip_address  TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_audit_log_module ON audit_log(module);
CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id);

-- ── Cross-Module Events ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type          TEXT NOT NULL,
    source_module       TEXT NOT NULL,
    source_entity_type  TEXT,
    source_entity_id    INTEGER,
    payload             TEXT,
    status              TEXT DEFAULT 'pending',
    created_by          INTEGER REFERENCES users(id),
    created_at          TEXT DEFAULT (datetime('now')),
    processed_at        TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_status ON events(status);
CREATE INDEX IF NOT EXISTS idx_events_type ON events(event_type);

-- ── Notifications ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module      TEXT,
    title       TEXT NOT NULL,
    message     TEXT,
    link        TEXT,
    is_read     INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);

-- ── Platform Settings ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS settings (
    key     TEXT PRIMARY KEY,
    value   TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ── Evidence Repository ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evidence_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    description     TEXT,
    file_path       TEXT,
    file_name       TEXT,
    file_size       INTEGER,
    file_hash       TEXT,
    mime_type       TEXT,
    category        TEXT DEFAULT 'general',
    tags            TEXT DEFAULT '',
    version         INTEGER DEFAULT 1,
    parent_id       INTEGER REFERENCES evidence_items(id),
    status          TEXT DEFAULT 'current',
    expiry_date     TEXT,
    uploaded_by     INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS evidence_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id     INTEGER NOT NULL REFERENCES evidence_items(id) ON DELETE CASCADE,
    module          TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    entity_id       INTEGER NOT NULL,
    linked_by       INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_evidence_links_evidence ON evidence_links(evidence_id);
CREATE INDEX IF NOT EXISTS idx_evidence_links_entity ON evidence_links(module, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_evidence_items_category ON evidence_items(category);
CREATE INDEX IF NOT EXISTS idx_evidence_items_status ON evidence_items(status);
-- idx_evidence_items_hash and idx_evidence_items_parent created in _run_migrations
-- after ALTER TABLE adds the columns to pre-existing databases.

-- ── Cross-Module Risk Register ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS risk_register (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    description     TEXT,
    source_module   TEXT,
    source_entity_type TEXT,
    source_entity_id INTEGER,
    category        TEXT DEFAULT 'operational',
    likelihood      INTEGER DEFAULT 3,
    impact          INTEGER DEFAULT 3,
    risk_score      INTEGER GENERATED ALWAYS AS (likelihood * impact) STORED,
    risk_level      TEXT,
    owner_id        INTEGER REFERENCES users(id),
    treatment       TEXT DEFAULT 'mitigate',
    treatment_plan  TEXT,
    status          TEXT DEFAULT 'open',
    review_date     TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_risk_register_module ON risk_register(source_module);
CREATE INDEX IF NOT EXISTS idx_risk_register_status ON risk_register(status);

-- ── Workflow Engine ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_definitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT,
    trigger_module  TEXT,
    trigger_action  TEXT,
    steps_json      TEXT NOT NULL,
    is_active       INTEGER DEFAULT 1,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workflow_instances (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    definition_id   INTEGER NOT NULL REFERENCES workflow_definitions(id),
    entity_module   TEXT,
    entity_type     TEXT,
    entity_id       INTEGER,
    current_step    INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'active',
    started_by      INTEGER REFERENCES users(id),
    started_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS workflow_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id     INTEGER NOT NULL REFERENCES workflow_instances(id),
    step_index      INTEGER NOT NULL,
    action_type     TEXT DEFAULT 'approve',
    assigned_to     INTEGER REFERENCES users(id),
    status          TEXT DEFAULT 'pending',
    comment         TEXT,
    due_at          TEXT,
    acted_at        TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_workflow_instances_status ON workflow_instances(status);
CREATE INDEX IF NOT EXISTS idx_workflow_actions_assigned ON workflow_actions(assigned_to, status);

-- ── SLA Engine ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sla_definitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    module          TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    response_hours  INTEGER,
    resolution_hours INTEGER,
    escalation_hours INTEGER,
    priority        TEXT DEFAULT 'normal',
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sla_instances (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    definition_id   INTEGER NOT NULL REFERENCES sla_definitions(id),
    entity_module   TEXT,
    entity_type     TEXT,
    entity_id       INTEGER,
    started_at      TEXT DEFAULT (datetime('now')),
    response_due    TEXT,
    resolution_due  TEXT,
    escalation_due  TEXT,
    responded_at    TEXT,
    resolved_at     TEXT,
    escalated_at    TEXT,
    status          TEXT DEFAULT 'active',
    breached        INTEGER DEFAULT 0,
    breach_type     TEXT
);

CREATE INDEX IF NOT EXISTS idx_sla_instances_status ON sla_instances(status, breached);

-- ── Communication Templates ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS comm_templates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    category        TEXT DEFAULT 'general',
    module          TEXT,
    subject_template TEXT,
    body_template   TEXT NOT NULL,
    variables_json  TEXT,
    version         INTEGER DEFAULT 1,
    is_active       INTEGER DEFAULT 1,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_comm_templates_category ON comm_templates(category, module);

-- ── User Preferences (dashboard layout etc.) ──────────────────────────────
CREATE TABLE IF NOT EXISTS user_preferences (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    pref_key        TEXT NOT NULL,
    pref_value      TEXT,
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, pref_key)
);

-- ── Reporting Engine ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS report_definitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT,
    report_type     TEXT NOT NULL DEFAULT 'compliance_summary',
    modules         TEXT,
    parameters_json TEXT,
    schedule        TEXT,
    is_active       INTEGER DEFAULT 1,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS report_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    definition_id   INTEGER NOT NULL REFERENCES report_definitions(id),
    status          TEXT DEFAULT 'pending',
    started_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT,
    result_json     TEXT,
    file_path       TEXT,
    error           TEXT,
    triggered_by    TEXT DEFAULT 'manual'
);

CREATE INDEX IF NOT EXISTS idx_report_runs_def ON report_runs(definition_id, started_at DESC);

-- ── API Keys ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS api_keys (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    key_hash        TEXT NOT NULL UNIQUE,
    key_prefix      TEXT NOT NULL,
    scopes          TEXT DEFAULT 'read',
    is_active       INTEGER DEFAULT 1,
    last_used_at    TEXT,
    expires_at      TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_api_keys_hash ON api_keys(key_hash);

-- ── Webhooks ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS webhooks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL,
    secret          TEXT,
    events          TEXT NOT NULL,
    is_active       INTEGER DEFAULT 1,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS webhook_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_id      INTEGER NOT NULL REFERENCES webhooks(id),
    event           TEXT NOT NULL,
    payload_json    TEXT,
    response_code   INTEGER,
    response_body   TEXT,
    success         INTEGER DEFAULT 0,
    attempted_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_webhook_logs_wh ON webhook_logs(webhook_id, attempted_at DESC);

-- ── Compliance Calendar ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS calendar_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    description     TEXT,
    event_type      TEXT NOT NULL,
    module          TEXT,
    entity_type     TEXT,
    entity_id       INTEGER,
    start_date      TEXT NOT NULL,
    end_date        TEXT,
    all_day         INTEGER DEFAULT 1,
    recurrence      TEXT,
    assigned_to     INTEGER REFERENCES users(id),
    status          TEXT DEFAULT 'scheduled',
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_calendar_dates ON calendar_events(start_date, end_date);

-- ── Analytics Snapshots ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analytics_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    metric_value    REAL NOT NULL,
    module          TEXT,
    metadata_json   TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_unique ON analytics_snapshots(snapshot_date, metric_name, module);

-- ── Cross-Module Task Board ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS task_board (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    description     TEXT,
    module          TEXT,
    entity_type     TEXT,
    entity_id       INTEGER,
    assigned_to     INTEGER REFERENCES users(id),
    priority        TEXT DEFAULT 'medium',
    status          TEXT DEFAULT 'todo',
    due_date        TEXT,
    tags            TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_task_board_assigned ON task_board(assigned_to, status);
CREATE INDEX IF NOT EXISTS idx_task_board_due ON task_board(due_date, status);

-- ── Email Reminders (Cross-Module) ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS email_reminders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    module          TEXT NOT NULL,
    entity_type     TEXT,
    entity_id       INTEGER,
    title           TEXT NOT NULL,
    message         TEXT,
    recipient_id    INTEGER REFERENCES users(id),
    recipient_email TEXT NOT NULL,
    remind_at       TEXT NOT NULL,
    repeat_interval TEXT DEFAULT 'none',
    is_sent         INTEGER DEFAULT 0,
    sent_at         TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_reminders_pending ON email_reminders(remind_at, is_sent);

-- ── Unified Frameworks ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS frameworks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,
    description     TEXT,
    color           TEXT DEFAULT '#1E3A5F',
    type            TEXT DEFAULT 'Security',
    relevant_modules TEXT DEFAULT '',
    is_active       INTEGER DEFAULT 1,
    total_controls  INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_frameworks_active ON frameworks(is_active);

-- ── Unified Controls ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS controls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    framework_id    INTEGER NOT NULL REFERENCES frameworks(id) ON DELETE CASCADE,
    ref             TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    category        TEXT,
    doc_type        TEXT DEFAULT 'Policy',
    status          TEXT DEFAULT 'Not Started',
    priority        TEXT DEFAULT 'High',
    owner           TEXT DEFAULT '',
    evidence_ref    TEXT DEFAULT '',
    document_title  TEXT DEFAULT '',
    version         TEXT DEFAULT '1.0',
    target_date     TEXT,
    review_date     TEXT,
    last_updated    TEXT DEFAULT (datetime('now')),
    notes           TEXT DEFAULT '',
    UNIQUE(framework_id, ref)
);
CREATE INDEX IF NOT EXISTS idx_controls_framework ON controls(framework_id);
CREATE INDEX IF NOT EXISTS idx_controls_status ON controls(status);

-- ── Cross-module links ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cross_module_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_module   TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    source_id       INTEGER NOT NULL,
    target_module   TEXT NOT NULL,
    target_type     TEXT NOT NULL,
    target_id       INTEGER NOT NULL,
    relationship    TEXT DEFAULT 'related',
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_xlinks_source ON cross_module_links(source_module, source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_xlinks_target ON cross_module_links(target_module, target_type, target_id);

-- ── People Directory ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS people_directory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name   TEXT NOT NULL,
    email       TEXT,
    phone       TEXT,
    job_title   TEXT,
    department  TEXT,
    manager_id  INTEGER REFERENCES people_directory(id) ON DELETE SET NULL,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    is_active   INTEGER DEFAULT 1,
    notes       TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_people_dept ON people_directory(department);
CREATE INDEX IF NOT EXISTS idx_people_user ON people_directory(user_id);

-- ── Rate Limit Attempts ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS rate_limit_attempts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    key          TEXT NOT NULL,
    attempted_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_rl_key_time ON rate_limit_attempts(key, attempted_at);
"""

# Per-tenant platform tables: created in every tenant schema by provision_tenant_schema().
# These tables hold org-specific data. The global/public schema also gets them via
# init_db() (for the default org), but new orgs get isolated copies in tenant_{slug}.
_PLATFORM_TABLES = """
-- ── Notifications ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS notifications (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    module      TEXT,
    title       TEXT NOT NULL,
    message     TEXT,
    link        TEXT,
    is_read     INTEGER DEFAULT 0,
    created_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);

-- ── Platform Settings ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS settings (
    key     TEXT PRIMARY KEY,
    value   TEXT,
    updated_at TEXT DEFAULT (datetime('now'))
);

-- ── Evidence Repository ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS evidence_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    description     TEXT,
    file_path       TEXT,
    file_name       TEXT,
    file_size       INTEGER,
    file_hash       TEXT,
    mime_type       TEXT,
    category        TEXT DEFAULT 'general',
    tags            TEXT DEFAULT '',
    version         INTEGER DEFAULT 1,
    parent_id       INTEGER REFERENCES evidence_items(id),
    status          TEXT DEFAULT 'current',
    expiry_date     TEXT,
    uploaded_by     INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS evidence_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id     INTEGER NOT NULL REFERENCES evidence_items(id) ON DELETE CASCADE,
    module          TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    entity_id       INTEGER NOT NULL,
    linked_by       INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_evidence_links_evidence ON evidence_links(evidence_id);
CREATE INDEX IF NOT EXISTS idx_evidence_links_entity ON evidence_links(module, entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_evidence_items_category ON evidence_items(category);
CREATE INDEX IF NOT EXISTS idx_evidence_items_status ON evidence_items(status);

-- ── Cross-Module Risk Register ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS risk_register (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    description     TEXT,
    source_module   TEXT,
    source_entity_type TEXT,
    source_entity_id INTEGER,
    category        TEXT DEFAULT 'operational',
    likelihood      INTEGER DEFAULT 3,
    impact          INTEGER DEFAULT 3,
    risk_score      INTEGER GENERATED ALWAYS AS (likelihood * impact) STORED,
    risk_level      TEXT,
    owner_id        INTEGER REFERENCES users(id),
    treatment       TEXT DEFAULT 'mitigate',
    treatment_plan  TEXT,
    status          TEXT DEFAULT 'open',
    review_date     TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_risk_register_module ON risk_register(source_module);
CREATE INDEX IF NOT EXISTS idx_risk_register_status ON risk_register(status);

-- ── Workflow Engine ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_definitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT,
    trigger_module  TEXT,
    trigger_action  TEXT,
    steps_json      TEXT NOT NULL,
    is_active       INTEGER DEFAULT 1,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS workflow_instances (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    definition_id   INTEGER NOT NULL REFERENCES workflow_definitions(id),
    entity_module   TEXT,
    entity_type     TEXT,
    entity_id       INTEGER,
    current_step    INTEGER DEFAULT 0,
    status          TEXT DEFAULT 'active',
    started_by      INTEGER REFERENCES users(id),
    started_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT
);

CREATE TABLE IF NOT EXISTS workflow_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    instance_id     INTEGER NOT NULL REFERENCES workflow_instances(id),
    step_index      INTEGER NOT NULL,
    action_type     TEXT DEFAULT 'approve',
    assigned_to     INTEGER REFERENCES users(id),
    status          TEXT DEFAULT 'pending',
    comment         TEXT,
    due_at          TEXT,
    acted_at        TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_workflow_instances_status ON workflow_instances(status);
CREATE INDEX IF NOT EXISTS idx_workflow_actions_assigned ON workflow_actions(assigned_to, status);

-- ── SLA Engine ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sla_definitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    module          TEXT NOT NULL,
    entity_type     TEXT NOT NULL,
    response_hours  INTEGER,
    resolution_hours INTEGER,
    escalation_hours INTEGER,
    priority        TEXT DEFAULT 'normal',
    is_active       INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sla_instances (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    definition_id   INTEGER NOT NULL REFERENCES sla_definitions(id),
    entity_module   TEXT,
    entity_type     TEXT,
    entity_id       INTEGER,
    started_at      TEXT DEFAULT (datetime('now')),
    response_due    TEXT,
    resolution_due  TEXT,
    escalation_due  TEXT,
    responded_at    TEXT,
    resolved_at     TEXT,
    escalated_at    TEXT,
    status          TEXT DEFAULT 'active',
    breached        INTEGER DEFAULT 0,
    breach_type     TEXT
);

CREATE INDEX IF NOT EXISTS idx_sla_instances_status ON sla_instances(status, breached);

-- ── Communication Templates ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS comm_templates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    category        TEXT DEFAULT 'general',
    module          TEXT,
    subject_template TEXT,
    body_template   TEXT NOT NULL,
    variables_json  TEXT,
    version         INTEGER DEFAULT 1,
    is_active       INTEGER DEFAULT 1,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_comm_templates_category ON comm_templates(category, module);

-- ── User Preferences ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS user_preferences (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    pref_key        TEXT NOT NULL,
    pref_value      TEXT,
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(user_id, pref_key)
);

-- ── Reporting Engine ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS report_definitions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT,
    report_type     TEXT NOT NULL DEFAULT 'compliance_summary',
    modules         TEXT,
    parameters_json TEXT,
    schedule        TEXT,
    is_active       INTEGER DEFAULT 1,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS report_runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    definition_id   INTEGER NOT NULL REFERENCES report_definitions(id),
    status          TEXT DEFAULT 'pending',
    started_at      TEXT DEFAULT (datetime('now')),
    completed_at    TEXT,
    result_json     TEXT,
    file_path       TEXT,
    error           TEXT,
    triggered_by    TEXT DEFAULT 'manual'
);

CREATE INDEX IF NOT EXISTS idx_report_runs_def ON report_runs(definition_id, started_at DESC);

-- ── Webhooks ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS webhooks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    url             TEXT NOT NULL,
    secret          TEXT,
    events          TEXT NOT NULL,
    is_active       INTEGER DEFAULT 1,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS webhook_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    webhook_id      INTEGER NOT NULL REFERENCES webhooks(id),
    event           TEXT NOT NULL,
    payload_json    TEXT,
    response_code   INTEGER,
    response_body   TEXT,
    success         INTEGER DEFAULT 0,
    attempted_at    TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_webhook_logs_wh ON webhook_logs(webhook_id, attempted_at DESC);

-- ── Compliance Calendar ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS calendar_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    description     TEXT,
    event_type      TEXT NOT NULL,
    module          TEXT,
    entity_type     TEXT,
    entity_id       INTEGER,
    start_date      TEXT NOT NULL,
    end_date        TEXT,
    all_day         INTEGER DEFAULT 1,
    recurrence      TEXT,
    assigned_to     INTEGER REFERENCES users(id),
    status          TEXT DEFAULT 'scheduled',
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_calendar_dates ON calendar_events(start_date, end_date);

-- ── Analytics Snapshots ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS analytics_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_date   TEXT NOT NULL,
    metric_name     TEXT NOT NULL,
    metric_value    REAL NOT NULL,
    module          TEXT,
    metadata_json   TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_unique ON analytics_snapshots(snapshot_date, metric_name, module);

-- ── Cross-Module Task Board ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS task_board (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    description     TEXT,
    module          TEXT,
    entity_type     TEXT,
    entity_id       INTEGER,
    assigned_to     INTEGER REFERENCES users(id),
    priority        TEXT DEFAULT 'medium',
    status          TEXT DEFAULT 'todo',
    due_date        TEXT,
    tags            TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_task_board_assigned ON task_board(assigned_to, status);
CREATE INDEX IF NOT EXISTS idx_task_board_due ON task_board(due_date, status);

-- ── Email Reminders ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS email_reminders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    module          TEXT NOT NULL,
    entity_type     TEXT,
    entity_id       INTEGER,
    title           TEXT NOT NULL,
    message         TEXT,
    recipient_id    INTEGER REFERENCES users(id),
    recipient_email TEXT NOT NULL,
    remind_at       TEXT NOT NULL,
    repeat_interval TEXT DEFAULT 'none',
    is_sent         INTEGER DEFAULT 0,
    sent_at         TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_reminders_pending ON email_reminders(remind_at, is_sent);

-- ── Unified Frameworks ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS frameworks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,
    description     TEXT,
    color           TEXT DEFAULT '#1E3A5F',
    type            TEXT DEFAULT 'Security',
    relevant_modules TEXT DEFAULT '',
    is_active       INTEGER DEFAULT 1,
    total_controls  INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_frameworks_active ON frameworks(is_active);

-- ── Unified Controls ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS controls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    framework_id    INTEGER NOT NULL REFERENCES frameworks(id) ON DELETE CASCADE,
    ref             TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    category        TEXT,
    doc_type        TEXT DEFAULT 'Policy',
    status          TEXT DEFAULT 'Not Started',
    priority        TEXT DEFAULT 'High',
    owner           TEXT DEFAULT '',
    evidence_ref    TEXT DEFAULT '',
    document_title  TEXT DEFAULT '',
    version         TEXT DEFAULT '1.0',
    target_date     TEXT,
    review_date     TEXT,
    last_updated    TEXT DEFAULT (datetime('now')),
    notes           TEXT DEFAULT '',
    UNIQUE(framework_id, ref)
);
CREATE INDEX IF NOT EXISTS idx_controls_framework ON controls(framework_id);
CREATE INDEX IF NOT EXISTS idx_controls_status ON controls(status);

-- ── Cross-module links ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS cross_module_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_module   TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    source_id       INTEGER NOT NULL,
    target_module   TEXT NOT NULL,
    target_type     TEXT NOT NULL,
    target_id       INTEGER NOT NULL,
    relationship    TEXT DEFAULT 'related',
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_xlinks_source ON cross_module_links(source_module, source_type, source_id);
CREATE INDEX IF NOT EXISTS idx_xlinks_target ON cross_module_links(target_module, target_type, target_id);

-- ── People Directory ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS people_directory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    full_name   TEXT NOT NULL,
    email       TEXT,
    phone       TEXT,
    job_title   TEXT,
    department  TEXT,
    manager_id  INTEGER REFERENCES people_directory(id) ON DELETE SET NULL,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    is_active   INTEGER DEFAULT 1,
    notes       TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_people_dept ON people_directory(department);
CREATE INDEX IF NOT EXISTS idx_people_user ON people_directory(user_id);
"""

_ARIA_TABLES = """
-- ── ARIA: Frameworks ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aria_frameworks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT UNIQUE NOT NULL,
    description     TEXT,
    color           TEXT DEFAULT '#1A2744',
    total_controls  INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 1,
    relevant_modules TEXT DEFAULT ''
);

-- ── ARIA: Controls ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aria_controls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    framework_id    INTEGER NOT NULL REFERENCES aria_frameworks(id),
    ref             TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    doc_type        TEXT DEFAULT 'Policy',
    category        TEXT,
    status          TEXT DEFAULT 'Not Started',
    priority        TEXT DEFAULT 'High',
    owner           TEXT DEFAULT '',
    document_title  TEXT DEFAULT '',
    version         TEXT DEFAULT '1.0',
    target_date     TEXT,
    review_date     TEXT,
    last_updated    TEXT,
    notes           TEXT DEFAULT '',
    evidence_ref    TEXT DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_aria_controls_fw ON aria_controls(framework_id);

-- ── ARIA: Documents (Policies/Procedures) ───────────────────────────────────
CREATE TABLE IF NOT EXISTS aria_documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    doc_id          TEXT UNIQUE NOT NULL,
    framework       TEXT NOT NULL,
    control_ref     TEXT,
    title           TEXT NOT NULL,
    doc_type        TEXT DEFAULT 'Policy',
    version         TEXT DEFAULT '1.0',
    status          TEXT DEFAULT 'Draft',
    owner           TEXT DEFAULT '',
    approver        TEXT DEFAULT '',
    effective_date  TEXT,
    review_date     TEXT,
    location        TEXT DEFAULT '',
    comments        TEXT DEFAULT '',
    body            TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── ARIA: Document Templates (branding) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS aria_doc_templates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT DEFAULT '',
    doc_type        TEXT DEFAULT 'Policy',
    file_path       TEXT NOT NULL,
    file_name       TEXT NOT NULL,
    file_size       INTEGER DEFAULT 0,
    logo_path       TEXT,
    is_default      INTEGER DEFAULT 0,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── ARIA: Document Revisions (version chain) ──────────────────────────────
CREATE TABLE IF NOT EXISTS aria_doc_revisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER NOT NULL REFERENCES aria_documents(id) ON DELETE CASCADE,
    version         TEXT NOT NULL,
    file_path       TEXT,
    file_name       TEXT,
    file_size       INTEGER DEFAULT 0,
    revision_type   TEXT DEFAULT 'manual',
    notes           TEXT,
    uploaded_by     INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_aria_revisions_doc ON aria_doc_revisions(document_id);

-- ── ARIA: Risks ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aria_risks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id         TEXT UNIQUE NOT NULL,
    framework       TEXT NOT NULL,
    control_ref     TEXT,
    description     TEXT NOT NULL,
    category        TEXT,
    likelihood      INTEGER DEFAULT 3,
    impact          INTEGER DEFAULT 3,
    owner           TEXT DEFAULT '',
    mitigation      TEXT DEFAULT '',
    status          TEXT DEFAULT 'Open',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── ARIA: Evidence ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS aria_evidence (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id     TEXT UNIQUE NOT NULL,
    framework       TEXT NOT NULL,
    control_ref     TEXT,
    description     TEXT NOT NULL,
    evidence_type   TEXT,
    collected_by    TEXT DEFAULT '',
    collection_date TEXT,
    storage_location TEXT DEFAULT '',
    expiry_date     TEXT,
    status          TEXT DEFAULT 'Current',
    notes           TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── ARIA: Ask ARIA (FTS5 search index + Q&A log) ──────────────────────────
CREATE TABLE IF NOT EXISTS aria_ask_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    username    TEXT,
    question    TEXT,
    answer      TEXT,
    covered     INTEGER DEFAULT 1,
    citations   TEXT,
    latency_ms  INTEGER,
    created_at  TEXT DEFAULT CURRENT_TIMESTAMP
);

-- ── ARIA: Cross-Framework Control Mappings (IMS) ────────────────────────────
-- Links equivalent controls across different frameworks so that evidence or
-- policies generated for one can be reused to satisfy the other (IMS concept).
CREATE TABLE IF NOT EXISTS aria_control_mappings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    source_framework_id INTEGER NOT NULL REFERENCES frameworks(id) ON DELETE CASCADE,
    source_control_id   INTEGER NOT NULL REFERENCES controls(id)   ON DELETE CASCADE,
    target_framework_id INTEGER NOT NULL REFERENCES frameworks(id) ON DELETE CASCADE,
    target_control_id   INTEGER NOT NULL REFERENCES controls(id)   ON DELETE CASCADE,
    mapping_type        TEXT DEFAULT 'equivalent',
    notes               TEXT,
    confidence          REAL DEFAULT 1.0,
    created_by          INTEGER REFERENCES users(id),
    created_at          TEXT DEFAULT (datetime('now')),
    UNIQUE(source_control_id, target_control_id)
);
CREATE INDEX IF NOT EXISTS idx_acm_source ON aria_control_mappings(source_framework_id, source_control_id);
CREATE INDEX IF NOT EXISTS idx_acm_target ON aria_control_mappings(target_framework_id, target_control_id);
"""

_GRID_TABLES = """
-- ── GRID: Audits ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_audits (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    framework_id    INTEGER,
    audit_type      TEXT DEFAULT 'External',
    auditor         TEXT,
    lead_id         INTEGER REFERENCES users(id),
    start_date      TEXT,
    end_date        TEXT,
    audit_date      TEXT,
    status          TEXT DEFAULT 'Planning',
    scope           TEXT DEFAULT '',
    objective       TEXT DEFAULT '',
    criteria        TEXT DEFAULT '',
    methodology     TEXT DEFAULT '',
    conclusion      TEXT DEFAULT '',
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: Controls ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_controls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id        INTEGER NOT NULL REFERENCES grid_audits(id),
    framework_id    INTEGER,
    control_id      TEXT,
    name            TEXT NOT NULL,
    description     TEXT,
    risk_level      TEXT DEFAULT 'Medium',
    status          TEXT DEFAULT 'Not Started',
    assignee_id     INTEGER REFERENCES users(id),
    due_date        TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: Evidence Items ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_evidence_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    control_id      INTEGER NOT NULL REFERENCES grid_controls(id),
    name            TEXT NOT NULL,
    description     TEXT,
    required        INTEGER DEFAULT 1
);

-- ── GRID: Evidence Files ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_evidence_files (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_item_id INTEGER REFERENCES grid_evidence_items(id),
    control_id      INTEGER NOT NULL REFERENCES grid_controls(id),
    filename        TEXT NOT NULL,
    original_name   TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    file_size       INTEGER,
    mime_type       TEXT,
    uploaded_by     INTEGER REFERENCES users(id),
    status          TEXT DEFAULT 'Uploaded',
    approved_by     INTEGER REFERENCES users(id),
    approved_at     TEXT,
    version         INTEGER DEFAULT 1,
    expires_at      TEXT,
    expiry_notified INTEGER DEFAULT 0,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: Evidence Versions (audit trail for re-uploads) ────────────────────
CREATE TABLE IF NOT EXISTS grid_evidence_versions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id     INTEGER NOT NULL REFERENCES grid_evidence_files(id) ON DELETE CASCADE,
    version         INTEGER NOT NULL,
    filename        TEXT NOT NULL,
    original_name   TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    file_size       INTEGER,
    mime_type       TEXT,
    uploaded_by     INTEGER REFERENCES users(id),
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: Audit Timeline ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_timeline (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id        INTEGER NOT NULL REFERENCES grid_audits(id),
    title           TEXT NOT NULL,
    date            TEXT NOT NULL,
    status          TEXT DEFAULT 'Pending',
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: Reminders ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_reminders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    control_id      INTEGER REFERENCES grid_controls(id),
    audit_id        INTEGER REFERENCES grid_audits(id),
    user_id         INTEGER NOT NULL REFERENCES users(id),
    frequency       TEXT DEFAULT 'weekly',
    last_sent       TEXT,
    active          INTEGER DEFAULT 1
);

-- ── GRID: AI Suggestions ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_ai_suggestions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    control_id      INTEGER REFERENCES grid_controls(id),
    audit_id        INTEGER REFERENCES grid_audits(id),
    suggestion_type TEXT,
    content         TEXT,
    status          TEXT DEFAULT 'Pending',
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: Non-Conformances ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_non_conformances (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id        INTEGER NOT NULL REFERENCES grid_audits(id),
    control_id      INTEGER REFERENCES grid_controls(id),
    title           TEXT NOT NULL,
    description     TEXT,
    severity        TEXT DEFAULT 'minor',
    status          TEXT DEFAULT 'open',
    assigned_to     INTEGER REFERENCES users(id),
    root_cause      TEXT,
    corrective_action TEXT,
    due_date        TEXT,
    closed_at       TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: NC-Evidence Links (corrective action proof) ─────────────────────
CREATE TABLE IF NOT EXISTS grid_nc_evidence (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    nc_id           INTEGER NOT NULL REFERENCES grid_non_conformances(id) ON DELETE CASCADE,
    evidence_file_id INTEGER NOT NULL REFERENCES grid_evidence_files(id) ON DELETE CASCADE,
    linked_by       INTEGER REFERENCES users(id),
    notes           TEXT,
    linked_at       TEXT DEFAULT (datetime('now')),
    UNIQUE(nc_id, evidence_file_id)
);

-- ── GRID: Reports (persisted generated reports) ─────────────────────────
CREATE TABLE IF NOT EXISTS grid_reports (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id        INTEGER NOT NULL REFERENCES grid_audits(id) ON DELETE CASCADE,
    report_type     TEXT NOT NULL DEFAULT 'pdf',
    title           TEXT NOT NULL,
    filename        TEXT NOT NULL,
    file_path       TEXT NOT NULL,
    file_size       INTEGER DEFAULT 0,
    notes           TEXT,
    generated_by    INTEGER REFERENCES users(id),
    generated_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_grid_reports_audit ON grid_reports(audit_id);

-- ── GRID: Audit Sign-offs ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_audit_signoffs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id        INTEGER NOT NULL REFERENCES grid_audits(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    comment         TEXT,
    signed_at       TEXT DEFAULT (datetime('now')),
    UNIQUE(audit_id, role)
);
CREATE INDEX IF NOT EXISTS idx_grid_signoffs_audit ON grid_audit_signoffs(audit_id);

-- ── GRID: Policy Requests (GRID→ARIA cross-module) ─────────────────────
CREATE TABLE IF NOT EXISTS grid_policy_requests (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id        INTEGER NOT NULL REFERENCES grid_audits(id) ON DELETE CASCADE,
    control_id      INTEGER REFERENCES grid_controls(id),
    framework_name  TEXT NOT NULL,
    control_ref     TEXT,
    title           TEXT NOT NULL,
    description     TEXT,
    requested_by    INTEGER NOT NULL REFERENCES users(id),
    status          TEXT DEFAULT 'pending',
    aria_document_id INTEGER,
    resolved_at     TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_grid_policy_req_audit ON grid_policy_requests(audit_id);

-- ── GRID: Frameworks ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_frameworks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT,
    color           TEXT DEFAULT '#4f8ef7',
    type            TEXT DEFAULT 'Security',
    active          INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── Canonical Vendor Registry (shared identity across all modules) ────────
CREATE TABLE IF NOT EXISTS canonical_vendors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    contact_name    TEXT,
    contact_email   TEXT,
    website         TEXT,
    country         TEXT,
    services        TEXT,
    risk_level      TEXT DEFAULT 'medium',
    status          TEXT DEFAULT 'active',
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_canonical_vendors_name ON canonical_vendors(lower(trim(name)));

-- ── GRID: Vendors ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_vendors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    contact_name    TEXT,
    contact_email   TEXT,
    services        TEXT,
    risk_level      TEXT DEFAULT 'medium',
    status          TEXT DEFAULT 'active',
    frameworks      TEXT,
    contract_expiry TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: Vendor Assessments ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_vendor_assessments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id       INTEGER NOT NULL REFERENCES grid_vendors(id),
    assessment_date TEXT DEFAULT (date('now')),
    score           INTEGER,
    findings        TEXT,
    action_required TEXT,
    assessed_by     INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: Approvals ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_approvals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    evidence_id     INTEGER NOT NULL REFERENCES grid_evidence_files(id),
    stage           INTEGER DEFAULT 1,
    approver_id     INTEGER REFERENCES users(id),
    status          TEXT DEFAULT 'pending',
    comments        TEXT,
    decided_at      TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: Control Mappings ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_control_mappings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_control_id INTEGER NOT NULL REFERENCES grid_controls(id),
    target_control_id INTEGER NOT NULL REFERENCES grid_controls(id),
    mapping_type    TEXT DEFAULT 'equivalent',
    confidence      REAL,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(source_control_id, target_control_id)
);

-- ── GRID: Share Links ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_share_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id        INTEGER NOT NULL REFERENCES grid_audits(id),
    token           TEXT UNIQUE NOT NULL,
    created_by      INTEGER REFERENCES users(id),
    auditor_email   TEXT,
    expires_at      TEXT,
    access_count    INTEGER DEFAULT 0,
    active          INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: Control Comments ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_control_comments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    control_id      INTEGER NOT NULL REFERENCES grid_controls(id),
    user_id         INTEGER REFERENCES users(id),
    content         TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: Compliance Scores ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_compliance_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id        INTEGER NOT NULL REFERENCES grid_audits(id),
    score           INTEGER,
    details         TEXT,
    total_controls  INTEGER DEFAULT 0,
    complete_controls INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: Digest Subscriptions ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_digest_subscriptions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id),
    email           TEXT NOT NULL,
    name            TEXT,
    audit_ids       TEXT DEFAULT 'all',
    active          INTEGER DEFAULT 1,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── GRID: Remote Audit Sessions ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS grid_remote_sessions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    audit_id        INTEGER REFERENCES grid_audits(id),
    title           TEXT NOT NULL,
    description     TEXT,
    session_type    TEXT DEFAULT 'video',
    status          TEXT DEFAULT 'scheduled',
    scheduled_start TEXT,
    scheduled_end   TEXT,
    actual_start    TEXT,
    actual_end      TEXT,
    meeting_link    TEXT,
    auditor_id      INTEGER REFERENCES users(id),
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS grid_remote_participants (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES grid_remote_sessions(id),
    user_id         INTEGER REFERENCES users(id),
    external_name   TEXT,
    external_email  TEXT,
    role            TEXT DEFAULT 'auditee',
    joined_at       TEXT,
    left_at         TEXT
);

CREATE TABLE IF NOT EXISTS grid_remote_findings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES grid_remote_sessions(id),
    control_id      INTEGER REFERENCES grid_controls(id),
    finding_type    TEXT DEFAULT 'observation',
    severity        TEXT DEFAULT 'minor',
    title           TEXT NOT NULL,
    description     TEXT,
    evidence_ref    TEXT,
    raised_by       INTEGER REFERENCES users(id),
    status          TEXT DEFAULT 'open',
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS grid_remote_notes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      INTEGER NOT NULL REFERENCES grid_remote_sessions(id),
    user_id         INTEGER REFERENCES users(id),
    content         TEXT NOT NULL,
    timestamp_offset INTEGER,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_grid_remote_sessions_audit ON grid_remote_sessions(audit_id);
CREATE INDEX IF NOT EXISTS idx_grid_remote_findings_session ON grid_remote_findings(session_id);
"""

_BCM_TABLES = """
-- ── BCM: BIA Records ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_bia_records (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    process_name            TEXT NOT NULL,
    department              TEXT,
    owner                   TEXT,
    description             TEXT,
    rto_hours               INTEGER,
    rpo_hours               INTEGER,
    financial_impact_per_day REAL,
    operational_impact      INTEGER,
    reputational_impact     INTEGER,
    regulatory_impact       INTEGER,
    criticality             TEXT,
    dependencies            TEXT,
    created_at              TEXT DEFAULT (datetime('now')),
    updated_at              TEXT DEFAULT (datetime('now'))
);

-- ── BCM: Risks ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_risks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    category        TEXT,
    description     TEXT,
    likelihood      INTEGER,
    impact          INTEGER,
    score           INTEGER,
    treatment       TEXT,
    mitigation      TEXT,
    owner           TEXT,
    status          TEXT DEFAULT 'open',
    due_date        TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── BCM: Continuity Plans ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_plans (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    plan_type       TEXT,
    department      TEXT,
    scope           TEXT,
    owner           TEXT,
    version         TEXT DEFAULT '1.0',
    status          TEXT DEFAULT 'draft',
    content         TEXT,
    description     TEXT,
    review_frequency TEXT,
    last_reviewed   TEXT,
    next_review     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── BCM: Incidents ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_incidents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    description     TEXT,
    severity        TEXT,
    status          TEXT DEFAULT 'open',
    commander       TEXT,
    affected_systems TEXT,
    impact          TEXT,
    assigned_to     TEXT,
    declared_at     TEXT,
    started_at      TEXT DEFAULT (datetime('now')),
    resolved_at     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bcm_incident_updates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     INTEGER NOT NULL REFERENCES bcm_incidents(id) ON DELETE CASCADE,
    author          TEXT,
    note            TEXT NOT NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── BCM: Exercises ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_exercises (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    type            TEXT,
    scenario        TEXT,
    plan_id         INTEGER REFERENCES bcm_plans(id),
    scheduled_date  TEXT,
    duration_minutes INTEGER,
    facilitator     TEXT,
    participants    TEXT,
    objectives      TEXT,
    status          TEXT DEFAULT 'planned',
    outcome         TEXT,
    aar_summary     TEXT,
    aar_strengths   TEXT,
    aar_improvements TEXT,
    aar_actions     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── BCM: Vendors ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_vendors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    category        TEXT,
    service_provided TEXT,
    owner           TEXT,
    contact_name    TEXT,
    contact_email   TEXT,
    contact_phone   TEXT,
    criticality     TEXT,
    tier            INTEGER DEFAULT 3,
    data_sensitivity TEXT,
    sla             TEXT,
    contract_renewal TEXT,
    risk_score      INTEGER,
    status          TEXT DEFAULT 'active',
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bcm_vendor_assessments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    vendor_id       INTEGER NOT NULL REFERENCES bcm_vendors(id) ON DELETE CASCADE,
    assessed_on     TEXT DEFAULT (date('now')),
    assessor        TEXT,
    score           INTEGER,
    summary         TEXT,
    findings        TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── BCM: Dependency Graph — Nodes ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_dependency_nodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    node_type       TEXT NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    criticality     TEXT,
    ref_table       TEXT,
    ref_id          INTEGER,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── BCM: Dependency Graph — Edges ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_dependency_edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       INTEGER NOT NULL REFERENCES bcm_dependency_nodes(id) ON DELETE CASCADE,
    target_id       INTEGER NOT NULL REFERENCES bcm_dependency_nodes(id) ON DELETE CASCADE,
    label           TEXT,
    strength        INTEGER DEFAULT 3,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bcm_dep_edges_src ON bcm_dependency_edges(source_id);
CREATE INDEX IF NOT EXISTS idx_bcm_dep_edges_tgt ON bcm_dependency_edges(target_id);

-- ── BCM: Compliance Controls ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_compliance_controls (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    framework       TEXT NOT NULL,
    clause          TEXT NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    status          TEXT DEFAULT 'not_started',
    owner           TEXT,
    evidence_notes  TEXT,
    last_reviewed   TEXT,
    next_review     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bcm_compliance_evidence (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    control_id      INTEGER NOT NULL REFERENCES bcm_compliance_controls(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    file_path       TEXT,
    file_type       TEXT,
    uploaded_by     TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── BCM: Training Modules ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_training_modules (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    description     TEXT,
    category        TEXT,
    required_roles  TEXT,
    duration_minutes INTEGER,
    owner           TEXT,
    content         TEXT,
    passing_score   INTEGER DEFAULT 80,
    renewal_months  INTEGER DEFAULT 12,
    status          TEXT DEFAULT 'active',
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bcm_training_attestations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id       INTEGER NOT NULL REFERENCES bcm_training_modules(id) ON DELETE CASCADE,
    user_id         INTEGER REFERENCES users(id),
    user_name       TEXT,
    user_email      TEXT,
    attested_at     TEXT DEFAULT (datetime('now')),
    signature       TEXT,
    score           INTEGER,
    ip              TEXT,
    user_agent      TEXT,
    expires_at      TEXT
);
CREATE INDEX IF NOT EXISTS idx_bcm_attest_module ON bcm_training_attestations(module_id);

-- ── BCM: Documents + RAG ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_documents (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    source_kind     TEXT,
    filename        TEXT,
    mime            TEXT,
    bytes           INTEGER,
    uploaded_by     TEXT,
    tags            TEXT,
    content         TEXT,
    chunk_count     INTEGER DEFAULT 0,
    linked_plan_id  INTEGER REFERENCES bcm_plans(id) ON DELETE SET NULL,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS bcm_document_chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER NOT NULL REFERENCES bcm_documents(id) ON DELETE CASCADE,
    chunk_index     INTEGER NOT NULL,
    content         TEXT NOT NULL,
    token_count     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_bcm_doc_chunks ON bcm_document_chunks(document_id);

CREATE TABLE IF NOT EXISTS bcm_document_queries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER,
    question        TEXT NOT NULL,
    answer          TEXT,
    cited_chunk_ids TEXT,
    provider        TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── BCM: Incident Command Console ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_incident_actions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     INTEGER NOT NULL REFERENCES bcm_incidents(id) ON DELETE CASCADE,
    title           TEXT NOT NULL,
    owner           TEXT,
    status          TEXT DEFAULT 'open',
    priority        TEXT DEFAULT 'normal',
    due_at          TEXT,
    completed_at    TEXT,
    notes           TEXT,
    created_by      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bcm_incact ON bcm_incident_actions(incident_id);

CREATE TABLE IF NOT EXISTS bcm_incident_decisions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     INTEGER NOT NULL REFERENCES bcm_incidents(id) ON DELETE CASCADE,
    decision        TEXT NOT NULL,
    rationale       TEXT,
    decided_by      TEXT,
    decided_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bcm_incdec ON bcm_incident_decisions(incident_id);

CREATE TABLE IF NOT EXISTS bcm_incident_stakeholders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     INTEGER NOT NULL REFERENCES bcm_incidents(id) ON DELETE CASCADE,
    role            TEXT NOT NULL,
    person          TEXT,
    channel         TEXT,
    notified_at     TEXT,
    ack_at          TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bcm_incstake ON bcm_incident_stakeholders(incident_id);

CREATE TABLE IF NOT EXISTS bcm_incident_plan_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    incident_id     INTEGER NOT NULL REFERENCES bcm_incidents(id) ON DELETE CASCADE,
    plan_id         INTEGER NOT NULL REFERENCES bcm_plans(id) ON DELETE CASCADE,
    linked_by       TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(incident_id, plan_id)
);

-- ── BCM: AI Plan Reviews ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_plan_reviews (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL REFERENCES bcm_plans(id) ON DELETE CASCADE,
    reviewer_id     INTEGER,
    reviewer_name   TEXT,
    provider        TEXT,
    overall_score   INTEGER,
    standards       TEXT,
    summary         TEXT,
    strengths       TEXT,
    gaps            TEXT,
    recommendations TEXT,
    section_coverage TEXT,
    raw_response    TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bcm_planrev ON bcm_plan_reviews(plan_id);

-- ── BCM: BIA <-> Plan Coverage Links ───────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_bia_plan_links (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    bia_id          INTEGER NOT NULL REFERENCES bcm_bia_records(id) ON DELETE CASCADE,
    plan_id         INTEGER NOT NULL REFERENCES bcm_plans(id) ON DELETE CASCADE,
    coverage_type   TEXT DEFAULT 'primary',
    notes           TEXT,
    created_by      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(bia_id, plan_id)
);
CREATE INDEX IF NOT EXISTS idx_bcm_biaplan_bia ON bcm_bia_plan_links(bia_id);
CREATE INDEX IF NOT EXISTS idx_bcm_biaplan_plan ON bcm_bia_plan_links(plan_id);

-- ── BCM: Chat Messages ────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_chat_messages (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id),
    role            TEXT NOT NULL,
    content         TEXT NOT NULL,
    provider        TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

-- ── BCM: Crisis Communication Templates (BCM-14) ─────────────────────────
CREATE TABLE IF NOT EXISTS bcm_comm_templates (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    category        TEXT NOT NULL DEFAULT 'general',
    incident_types  TEXT DEFAULT '',
    subject         TEXT,
    body            TEXT NOT NULL,
    variables       TEXT DEFAULT '',
    version         INTEGER DEFAULT 1,
    is_active       INTEGER DEFAULT 1,
    created_by      TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bcm_comms_cat ON bcm_comm_templates(category, is_active);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bcm_comms_title ON bcm_comm_templates(title);

-- ── BCM: Emergency Contact Tree (BCM-15) ──────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_contact_nodes (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    role            TEXT,
    team            TEXT,
    email           TEXT,
    phone           TEXT,
    mobile          TEXT,
    escalation_level INTEGER DEFAULT 1,
    parent_id       INTEGER REFERENCES bcm_contact_nodes(id) ON DELETE SET NULL,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bcm_contacts_parent ON bcm_contact_nodes(parent_id);
CREATE INDEX IF NOT EXISTS idx_bcm_contacts_level ON bcm_contact_nodes(escalation_level);

-- ── BCM: Exercise Scenario Library (BCM-16) ───────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_scenario_library (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    category        TEXT DEFAULT 'general',
    description     TEXT,
    objectives      TEXT,
    injects         TEXT,
    estimated_duration_minutes INTEGER DEFAULT 120,
    difficulty      TEXT DEFAULT 'medium',
    is_builtin      INTEGER DEFAULT 0,
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_bcm_scenario_title ON bcm_scenario_library(title);

-- ── BCM: Plan Activations (BCM-17) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_plan_activations (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    plan_id         INTEGER NOT NULL REFERENCES bcm_plans(id) ON DELETE CASCADE,
    action          TEXT NOT NULL CHECK(action IN ('activated','deactivated')),
    reason          TEXT,
    incident_id     INTEGER REFERENCES bcm_incidents(id) ON DELETE SET NULL,
    activated_by    TEXT NOT NULL,
    activated_by_id INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_bcm_plan_act ON bcm_plan_activations(plan_id, created_at DESC);

-- ── BCM: Reminders ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bcm_reminders (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    kind            TEXT NOT NULL,
    ref_table       TEXT,
    ref_id          INTEGER,
    send_to_email   TEXT NOT NULL,
    subject         TEXT,
    body            TEXT,
    send_at         TEXT NOT NULL,
    sent_at         TEXT,
    status          TEXT DEFAULT 'pending',
    error           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""

_SENTINEL_TABLES = """
-- ── Sentinel: RoPA ──────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentinel_ropa (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_number      TEXT UNIQUE NOT NULL,
    processing_name TEXT NOT NULL,
    department      TEXT,
    owner           TEXT,
    purpose         TEXT,
    legal_basis     TEXT,
    data_categories TEXT,
    special_categories TEXT,
    data_subjects   TEXT,
    recipients      TEXT,
    retention_period TEXT,
    international_transfers TEXT,
    safeguards      TEXT,
    dpia_required   INTEGER DEFAULT 0,
    dpia_id         INTEGER,
    status          TEXT DEFAULT 'active',
    risk_level      TEXT DEFAULT 'low',
    regulation      TEXT DEFAULT 'GDPR',
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── Sentinel: DPIAs ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentinel_dpias (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_number      TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    department      TEXT,
    owner           TEXT,
    processing_type TEXT,
    data_categories TEXT,
    special_categories TEXT,
    data_subjects   TEXT,
    necessity       TEXT,
    proportionality TEXT,
    risks           TEXT,
    mitigations     TEXT,
    consultation    TEXT,
    dpo_opinion     TEXT,
    status          TEXT DEFAULT 'draft',
    risk_level      TEXT DEFAULT 'medium',
    regulation      TEXT DEFAULT 'GDPR',
    ai_assessment   TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── Sentinel: Breaches ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentinel_breaches (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_number      TEXT UNIQUE NOT NULL,
    title           TEXT NOT NULL,
    description     TEXT,
    discovered_date TEXT,
    occurred_date   TEXT,
    reported_date   TEXT,
    severity        TEXT DEFAULT 'medium',
    status          TEXT DEFAULT 'open',
    data_types      TEXT,
    affected_count  INTEGER DEFAULT 0,
    cause           TEXT,
    impact          TEXT,
    containment     TEXT,
    notification_required INTEGER DEFAULT 0,
    authority_notified INTEGER DEFAULT 0,
    subjects_notified INTEGER DEFAULT 0,
    root_cause      TEXT,
    corrective_actions TEXT,
    lessons_learned TEXT,
    ai_analysis     TEXT,
    regulation      TEXT DEFAULT 'GDPR',
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── Sentinel: DSR ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentinel_dsr (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_number      TEXT UNIQUE NOT NULL,
    requester_name  TEXT,
    requester_email TEXT,
    request_type    TEXT,
    regulation      TEXT DEFAULT 'GDPR',
    description     TEXT,
    received_date   TEXT,
    deadline_date   TEXT,
    status          TEXT DEFAULT 'open',
    response_notes  TEXT,
    ai_draft        TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── Sentinel: Vendors ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentinel_vendors (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    type            TEXT DEFAULT 'processor',
    country         TEXT,
    services        TEXT,
    data_types      TEXT,
    data_subjects   TEXT,
    dpa_status      TEXT DEFAULT 'pending',
    dpa_date        TEXT,
    dpa_expiry      TEXT,
    risk_level      TEXT DEFAULT 'medium',
    ai_assessment   TEXT,
    contact_name    TEXT,
    contact_email   TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── Sentinel: Privacy Notices ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentinel_privacy_notices (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    type            TEXT DEFAULT 'external',
    version         TEXT DEFAULT '1.0',
    status          TEXT DEFAULT 'draft',
    effective_date  TEXT,
    review_date     TEXT,
    url             TEXT,
    content_summary TEXT,
    owner           TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── Sentinel: Consent Records ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentinel_consent (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    purpose         TEXT NOT NULL,
    legal_basis     TEXT DEFAULT 'consent',
    data_categories TEXT,
    data_subjects   TEXT,
    collection_method TEXT,
    consent_type    TEXT DEFAULT 'opt-in',
    storage_location TEXT,
    retention_period TEXT,
    withdrawal_method TEXT,
    status          TEXT DEFAULT 'active',
    regulation      TEXT DEFAULT 'GDPR',
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── Sentinel: Joint Controllers ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentinel_controllers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    org_name        TEXT NOT NULL,
    contact_name    TEXT,
    contact_email   TEXT,
    role            TEXT DEFAULT 'joint_controller',
    is_primary      INTEGER DEFAULT 0,
    agreement_date  TEXT,
    agreement_ref   TEXT,
    responsibilities TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── Sentinel: International Transfers ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentinel_transfers (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_number      TEXT,
    destination     TEXT NOT NULL,
    recipient       TEXT,
    purpose         TEXT,
    data_types      TEXT,
    legal_basis     TEXT DEFAULT 'adequacy_decision',
    safeguards      TEXT,
    status          TEXT DEFAULT 'active',
    review_date     TEXT,
    risk_level      TEXT DEFAULT 'medium',
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── Sentinel: Retention Schedule ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sentinel_retention (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category        TEXT NOT NULL,
    data_type       TEXT NOT NULL,
    retention_period TEXT NOT NULL,
    legal_basis     TEXT,
    deletion_method TEXT DEFAULT 'secure_delete',
    responsible     TEXT,
    status          TEXT DEFAULT 'active',
    review_date     TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Sentinel: Security Measures
CREATE TABLE IF NOT EXISTS sentinel_security_measures (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category        TEXT NOT NULL,
    measure_name    TEXT NOT NULL,
    description     TEXT,
    status          TEXT DEFAULT 'implemented',
    review_date     TEXT,
    responsible     TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);


-- Sentinel: Policies
CREATE TABLE IF NOT EXISTS sentinel_policies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_number      TEXT,
    title           TEXT NOT NULL,
    type            TEXT DEFAULT 'policy',
    version         TEXT DEFAULT '1.0',
    status          TEXT DEFAULT 'draft',
    owner           TEXT,
    effective_date  TEXT,
    review_date     TEXT,
    content         TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Sentinel: Training Records
CREATE TABLE IF NOT EXISTS sentinel_training (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_number      TEXT,
    title           TEXT NOT NULL,
    type            TEXT DEFAULT 'awareness',
    audience        TEXT,
    frequency       TEXT DEFAULT 'annual',
    status          TEXT DEFAULT 'scheduled',
    last_delivered  TEXT,
    next_due        TEXT,
    completion_rate REAL DEFAULT 0,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Sentinel: Legitimate Interest Assessments — 3-part test (SENT-14)
CREATE TABLE IF NOT EXISTS sentinel_lia (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ropa_id         INTEGER REFERENCES sentinel_ropa(id) ON DELETE SET NULL,
    title           TEXT NOT NULL,
    regulation      TEXT DEFAULT 'GDPR',
    purpose_desc    TEXT,
    purpose_legit   INTEGER DEFAULT 0,
    purpose_notes   TEXT,
    necessity_desc  TEXT,
    necessity_pass  INTEGER DEFAULT 0,
    alternatives    TEXT,
    necessity_notes TEXT,
    subject_impact  TEXT,
    safeguards      TEXT,
    reasonable_exp  INTEGER DEFAULT 0,
    override_ok     INTEGER DEFAULT 0,
    balance_notes   TEXT,
    overall_result  TEXT DEFAULT 'pending',
    overall_score   INTEGER DEFAULT 0,
    dpo_reviewed    INTEGER DEFAULT 0,
    dpo_notes       TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sentinel_lia_ropa ON sentinel_lia(ropa_id);

-- Sentinel: Data Flows
CREATE TABLE IF NOT EXISTS sentinel_data_flows (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ref_number      TEXT,
    name            TEXT NOT NULL,
    source          TEXT,
    destination     TEXT,
    data_types      TEXT,
    purpose         TEXT,
    legal_basis     TEXT,
    safeguards      TEXT,
    ropa_id         INTEGER REFERENCES sentinel_ropa(id),
    regulation      TEXT,
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- Sentinel: Jurisdiction Configuration (which laws apply to this organisation)
CREATE TABLE IF NOT EXISTS sentinel_jurisdiction_config (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    jurisdiction_key    TEXT UNIQUE NOT NULL,
    is_active           INTEGER DEFAULT 1,
    is_primary          INTEGER DEFAULT 0,
    regulator_contact   TEXT,
    registration_number TEXT,
    dpo_name            TEXT,
    dpo_email           TEXT,
    notes               TEXT,
    activated_at        TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_sentinel_juris ON sentinel_jurisdiction_config(is_active);
"""

# ── ERM + ORM Tables ──────────────────────────────────────────────────────────
_ERM_ORM_TABLES = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

-- ── ERM: Enterprise Risks ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS erm_enterprise_risks (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    title                TEXT NOT NULL,
    description          TEXT,
    category             TEXT DEFAULT 'strategic',
    sub_category         TEXT,
    likelihood           INTEGER DEFAULT 3,
    impact               INTEGER DEFAULT 3,
    velocity             INTEGER DEFAULT 3,
    strategic_objective  TEXT,
    owner_id             INTEGER REFERENCES users(id),
    reviewer_id          INTEGER REFERENCES users(id),
    treatment            TEXT DEFAULT 'mitigate',
    treatment_plan       TEXT,
    residual_likelihood  INTEGER,
    residual_impact      INTEGER,
    status               TEXT DEFAULT 'open',
    board_visibility     INTEGER DEFAULT 0,
    regulation_links     TEXT,
    review_date          TEXT,
    last_reviewed        TEXT,
    source_module        TEXT DEFAULT 'erm',
    source_risk_id       INTEGER,
    created_by           INTEGER REFERENCES users(id),
    created_at           TEXT DEFAULT (datetime('now')),
    updated_at           TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_erm_risks_status   ON erm_enterprise_risks(status);
CREATE INDEX IF NOT EXISTS idx_erm_risks_category ON erm_enterprise_risks(category);
CREATE INDEX IF NOT EXISTS idx_erm_risks_board    ON erm_enterprise_risks(board_visibility);

-- ── ERM: Risk Appetite ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS erm_risk_appetite (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    category        TEXT NOT NULL UNIQUE,
    appetite_level  TEXT NOT NULL DEFAULT 'medium',
    max_score       INTEGER DEFAULT 12,
    description     TEXT,
    tolerance_notes TEXT,
    approved_by     INTEGER REFERENCES users(id),
    effective_date  TEXT,
    review_date     TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── ERM: Risk Library ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS erm_risk_library (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    title                   TEXT NOT NULL,
    description             TEXT,
    category                TEXT,
    default_likelihood      INTEGER DEFAULT 3,
    default_impact          INTEGER DEFAULT 3,
    typical_treatment       TEXT DEFAULT 'mitigate',
    suggested_controls      TEXT,
    applicable_industries   TEXT,
    regulatory_references   TEXT,
    tags                    TEXT,
    is_active               INTEGER DEFAULT 1,
    created_at              TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_erm_library_category ON erm_risk_library(category);
CREATE UNIQUE INDEX IF NOT EXISTS idx_erm_library_title ON erm_risk_library(title);

-- ── ERM: Regulatory Obligations ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS erm_regulatory_obligations (
    id                       INTEGER PRIMARY KEY AUTOINCREMENT,
    regulator                TEXT NOT NULL,
    regulation_name          TEXT NOT NULL,
    obligation               TEXT NOT NULL,
    applicable_departments   TEXT,
    evidence_required        TEXT,
    owner_id                 INTEGER REFERENCES users(id),
    due_date                 TEXT,
    status                   TEXT DEFAULT 'pending',
    linked_controls          TEXT,
    linked_erm_risk_id       INTEGER REFERENCES erm_enterprise_risks(id),
    notes                    TEXT,
    created_by               INTEGER REFERENCES users(id),
    created_at               TEXT DEFAULT (datetime('now')),
    updated_at               TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_erm_obligations_status ON erm_regulatory_obligations(status);

-- ── ERM: Self-Assessments ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS erm_assessments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    title           TEXT NOT NULL,
    type            TEXT DEFAULT 'risk',
    description     TEXT,
    target_audience TEXT,
    status          TEXT DEFAULT 'draft',
    due_date        TEXT,
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS erm_assessment_questions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id   INTEGER NOT NULL REFERENCES erm_assessments(id) ON DELETE CASCADE,
    question        TEXT NOT NULL,
    question_type   TEXT DEFAULT 'scale',
    options         TEXT,
    weight          REAL DEFAULT 1.0,
    order_idx       INTEGER DEFAULT 0,
    required        INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS erm_assessment_responses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id   INTEGER NOT NULL REFERENCES erm_assessments(id),
    question_id     INTEGER NOT NULL REFERENCES erm_assessment_questions(id),
    respondent_id   INTEGER REFERENCES users(id),
    response        TEXT,
    score           REAL,
    notes           TEXT,
    submitted_at    TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_erm_responses_assessment ON erm_assessment_responses(assessment_id);

-- ── ORM: Operational Risk Events ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orm_events (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    title                TEXT NOT NULL,
    description          TEXT,
    event_type           TEXT NOT NULL DEFAULT 'process_failure',
    severity             TEXT DEFAULT 'medium',
    status               TEXT DEFAULT 'open',
    department           TEXT,
    process_affected     TEXT,
    root_cause           TEXT,
    root_cause_category  TEXT,
    financial_impact     REAL DEFAULT 0,
    customers_affected   INTEGER DEFAULT 0,
    downtime_minutes     INTEGER DEFAULT 0,
    detected_at          TEXT,
    resolved_at          TEXT,
    reported_by          INTEGER REFERENCES users(id),
    owner_id             INTEGER REFERENCES users(id),
    corrective_action    TEXT,
    preventive_action    TEXT,
    is_recurring         INTEGER DEFAULT 0,
    parent_event_id      INTEGER REFERENCES orm_events(id),
    erm_risk_id          INTEGER REFERENCES erm_enterprise_risks(id),
    created_at           TEXT DEFAULT (datetime('now')),
    updated_at           TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orm_events_type     ON orm_events(event_type);
CREATE INDEX IF NOT EXISTS idx_orm_events_status   ON orm_events(status);
CREATE INDEX IF NOT EXISTS idx_orm_events_severity ON orm_events(severity);
CREATE INDEX IF NOT EXISTS idx_orm_events_created  ON orm_events(created_at);

-- ── ORM: Key Risk Indicators ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orm_kris (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT,
    metric_type     TEXT DEFAULT 'count',
    threshold_warn  REAL,
    threshold_crit  REAL,
    current_value   REAL DEFAULT 0,
    unit            TEXT DEFAULT 'events',
    frequency       TEXT DEFAULT 'monthly',
    owner_id        INTEGER REFERENCES users(id),
    status          TEXT DEFAULT 'active',
    last_updated    TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── ERM: AI Chat messages ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS erm_chat_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    provider    TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

-- ── ERM: Workflow History ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS erm_risk_workflow_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id     INTEGER NOT NULL REFERENCES erm_enterprise_risks(id) ON DELETE CASCADE,
    from_step   TEXT,
    to_step     TEXT NOT NULL,
    changed_by  INTEGER REFERENCES users(id),
    notes       TEXT,
    changed_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_erm_wf_risk ON erm_risk_workflow_history(risk_id);

-- ── ERM: Key Risk Indicators ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS erm_kris (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT,
    linked_risk_id  INTEGER REFERENCES erm_enterprise_risks(id) ON DELETE SET NULL,
    metric_type     TEXT DEFAULT 'count',
    threshold_warn  REAL,
    threshold_crit  REAL,
    current_value   REAL DEFAULT 0,
    unit            TEXT,
    frequency       TEXT DEFAULT 'monthly',
    owner_id        INTEGER REFERENCES users(id),
    status          TEXT DEFAULT 'active',
    trend           TEXT DEFAULT 'stable',
    last_updated    TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

-- ── ERM: KRI Value History (for trend sparklines) ─────────────────────────────
CREATE TABLE IF NOT EXISTS erm_kri_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kri_id      INTEGER NOT NULL REFERENCES erm_kris(id) ON DELETE CASCADE,
    value       REAL NOT NULL,
    recorded_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_erm_kri_hist ON erm_kri_history(kri_id);

-- ── ERM: Risk Statements Library ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS erm_risk_statements (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    category       TEXT NOT NULL,
    cause          TEXT NOT NULL,
    event          TEXT NOT NULL,
    consequence    TEXT NOT NULL,
    full_statement TEXT,
    tags           TEXT,
    industry       TEXT,
    usage_count    INTEGER DEFAULT 0,
    created_at     TEXT DEFAULT (datetime('now'))
);

-- ── ORM: AI Chat messages ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orm_chat_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id),
    role        TEXT NOT NULL,
    content     TEXT NOT NULL,
    provider    TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

-- ── ORM: KRI history (trend sparklines) ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS orm_kri_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kri_id      INTEGER NOT NULL REFERENCES orm_kris(id) ON DELETE CASCADE,
    value       REAL NOT NULL,
    recorded_at TEXT DEFAULT (datetime('now')),
    recorded_by INTEGER REFERENCES users(id)
);
CREATE INDEX IF NOT EXISTS idx_orm_kri_hist ON orm_kri_history(kri_id);

-- ── ORM: Event workflow history ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orm_event_workflow_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id    INTEGER NOT NULL REFERENCES orm_events(id) ON DELETE CASCADE,
    from_step   TEXT,
    to_step     TEXT NOT NULL,
    changed_by  INTEGER REFERENCES users(id),
    notes       TEXT,
    changed_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orm_evt_wf ON orm_event_workflow_history(event_id);

-- ── ORM: RCSA — Risk Control Self-Assessment ─────────────────────────────────
CREATE TABLE IF NOT EXISTS orm_rcsa_assessments (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    title        TEXT NOT NULL,
    scope        TEXT,
    period_start TEXT,
    period_end   TEXT,
    status       TEXT DEFAULT 'draft',  -- draft|active|under_review|completed
    owner_id     INTEGER REFERENCES users(id),
    due_date     TEXT,
    notes        TEXT,
    created_by   INTEGER REFERENCES users(id),
    created_at   TEXT DEFAULT (datetime('now')),
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS orm_rcsa_risks (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    assessment_id          INTEGER NOT NULL REFERENCES orm_rcsa_assessments(id) ON DELETE CASCADE,
    title                  TEXT NOT NULL,
    category               TEXT DEFAULT 'operational',
    inherent_likelihood    INTEGER DEFAULT 3,
    inherent_impact        INTEGER DEFAULT 3,
    control_effectiveness  INTEGER DEFAULT 3,  -- 1=Ineffective, 3=Partial, 5=Effective
    residual_score         REAL,               -- inherent L×I × (1 − eff/5)
    owner_id               INTEGER REFERENCES users(id),
    notes                  TEXT,
    created_at             TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orm_rcsa_risks ON orm_rcsa_risks(assessment_id);

CREATE TABLE IF NOT EXISTS orm_rcsa_controls (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id               INTEGER NOT NULL REFERENCES orm_rcsa_risks(id) ON DELETE CASCADE,
    name                  TEXT NOT NULL,
    aria_control_id       INTEGER REFERENCES controls(id),
    design_effectiveness  TEXT DEFAULT 'adequate',    -- adequate|inadequate|not_assessed
    operating_effectiveness TEXT DEFAULT 'effective', -- effective|partially_effective|ineffective|not_tested
    test_date             TEXT,
    tested_by             INTEGER REFERENCES users(id),
    evidence_notes        TEXT,
    gap_description       TEXT,
    created_at            TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orm_rcsa_ctrls ON orm_rcsa_controls(risk_id);

CREATE TABLE IF NOT EXISTS orm_rcsa_actions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    control_id  INTEGER NOT NULL REFERENCES orm_rcsa_controls(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    description TEXT,
    owner_id    INTEGER REFERENCES users(id),
    due_date    TEXT,
    status      TEXT DEFAULT 'open',  -- open|in_progress|completed|overdue
    notes       TEXT,
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orm_rcsa_acts ON orm_rcsa_actions(control_id);

-- ── ORM: Event Templates ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS orm_event_templates (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    title                       TEXT NOT NULL,
    description                 TEXT,
    category                    TEXT NOT NULL,   -- Cybersecurity|Data & Privacy|Process & Operations|Technology & Systems|People & HR|Financial & Fraud|Vendor & Third Party|Compliance & Regulatory
    event_type                  TEXT NOT NULL,   -- matches orm_events.event_type
    severity                    TEXT DEFAULT 'medium',
    department                  TEXT,
    process_affected            TEXT,
    root_cause_category         TEXT,
    corrective_action           TEXT,
    preventive_action           TEXT,
    basel_category              TEXT,
    tags                        TEXT,            -- comma-separated
    is_active                   INTEGER DEFAULT 1,
    usage_count                 INTEGER DEFAULT 0,
    created_at                  TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_orm_tmpl_cat ON orm_event_templates(category);

-- ── Production indexes (audit-added) ─────────────────────────────────────────
-- Missing FK and filter indexes identified in production audit
CREATE INDEX IF NOT EXISTS idx_sessions_user        ON sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_grid_controls_audit  ON grid_controls(audit_id);
CREATE INDEX IF NOT EXISTS idx_grid_evi_items_ctrl  ON grid_evidence_items(control_id);
CREATE INDEX IF NOT EXISTS idx_grid_evi_files_ctrl  ON grid_evidence_files(control_id);
CREATE INDEX IF NOT EXISTS idx_grid_evi_files_item  ON grid_evidence_files(evidence_item_id);
CREATE INDEX IF NOT EXISTS idx_sentinel_flows_ropa  ON sentinel_data_flows(ropa_id);
CREATE INDEX IF NOT EXISTS idx_orm_events_parent    ON orm_events(parent_event_id);
CREATE INDEX IF NOT EXISTS idx_orm_events_erm       ON orm_events(erm_risk_id);

-- ── Platform: Predictive AI Risk Predictions ──────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_risk_predictions (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    computed_at         TEXT DEFAULT (datetime('now')),
    delta_p             REAL,          -- 0-100 global risk probability modifier
    delta_cyber         REAL,          -- cyber domain sub-score
    delta_operational   REAL,          -- operational domain sub-score
    delta_compliance    REAL,          -- compliance domain sub-score
    confidence          REAL,          -- 0-1 data completeness confidence
    risk_level          TEXT,          -- low|medium|high|critical
    telemetry_json      TEXT,          -- JSON snapshot of raw metric inputs
    contributions_json  TEXT,          -- JSON per-signal contribution percentages
    advisory_text       TEXT,          -- Claude advisory (NULL if below threshold)
    erm_risk_id         INTEGER REFERENCES erm_enterprise_risks(id),
    acknowledged_by     INTEGER REFERENCES users(id),
    acknowledged_at     TEXT,
    is_active           INTEGER DEFAULT 1
);

-- ── ERM: Risk Rating Frameworks ────────────────────────────────────────────
-- A named, swappable rating methodology (impact dimensions, likelihood,
-- matrix bands, control effectiveness, taxonomy). Seeded per-tenant by
-- _seed_baseline_data(). Each org can eventually own multiple frameworks but
-- only one active at a time (enforced at the app level, not via DB constraint
-- -- matches the existing aria_doc_templates.is_default convention).
CREATE TABLE IF NOT EXISTS erm_risk_frameworks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT NOT NULL,
    description     TEXT,
    is_active       INTEGER DEFAULT 0,
    is_default      INTEGER DEFAULT 0,
    source          TEXT DEFAULT 'built_in',   -- built_in|imported|manual
    created_by      INTEGER REFERENCES users(id),
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS erm_framework_impact_dimensions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    framework_id    INTEGER NOT NULL REFERENCES erm_risk_frameworks(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    order_idx       INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_erm_fw_dims ON erm_framework_impact_dimensions(framework_id);

CREATE TABLE IF NOT EXISTS erm_framework_impact_levels (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    dimension_id    INTEGER NOT NULL REFERENCES erm_framework_impact_dimensions(id) ON DELETE CASCADE,
    level           INTEGER NOT NULL,
    description     TEXT,
    threshold_label TEXT,
    threshold_min   REAL,
    threshold_max   REAL,
    UNIQUE(dimension_id, level)
);

-- scale_type: 'likelihood' | 'impact' | 'control_effectiveness' — all three
-- are flat 5-point label+description scales. 'impact' holds the generic
-- Minor..Catastrophic labels shared across every impact dimension above.
CREATE TABLE IF NOT EXISTS erm_framework_scales (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    framework_id    INTEGER NOT NULL REFERENCES erm_risk_frameworks(id) ON DELETE CASCADE,
    scale_type      TEXT NOT NULL,
    level           INTEGER NOT NULL,
    label           TEXT NOT NULL,
    description     TEXT,
    UNIQUE(framework_id, scale_type, level)
);

CREATE TABLE IF NOT EXISTS erm_framework_bands (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    framework_id    INTEGER NOT NULL REFERENCES erm_risk_frameworks(id) ON DELETE CASCADE,
    band_key        TEXT NOT NULL,
    label           TEXT NOT NULL,
    color           TEXT NOT NULL,
    sort_order      INTEGER DEFAULT 0,
    UNIQUE(framework_id, band_key)
);

CREATE TABLE IF NOT EXISTS erm_framework_matrix_bands (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    framework_id    INTEGER NOT NULL REFERENCES erm_risk_frameworks(id) ON DELETE CASCADE,
    likelihood      INTEGER NOT NULL,
    impact          INTEGER NOT NULL,
    band_key        TEXT NOT NULL,
    UNIQUE(framework_id, likelihood, impact)
);
CREATE INDEX IF NOT EXISTS idx_erm_fw_matrix ON erm_framework_matrix_bands(framework_id);

CREATE TABLE IF NOT EXISTS erm_framework_taxonomy (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    framework_id    INTEGER NOT NULL REFERENCES erm_risk_frameworks(id) ON DELETE CASCADE,
    parent_id       INTEGER REFERENCES erm_framework_taxonomy(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    order_idx       INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_erm_fw_taxonomy ON erm_framework_taxonomy(framework_id);

-- Per-risk impact dimension scores. Keyed by dimension_name (TEXT, no FK)
-- rather than dimension id, because _apply_framework_payload deletes and
-- re-inserts all dimension rows on every framework save (changing ids).
-- dimension_name changes far less often and stale names degrade gracefully.
CREATE TABLE IF NOT EXISTS erm_risk_dimension_scores (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id         INTEGER NOT NULL REFERENCES erm_enterprise_risks(id) ON DELETE CASCADE,
    dimension_name  TEXT NOT NULL,
    score           INTEGER NOT NULL,
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(risk_id, dimension_name)
);
CREATE INDEX IF NOT EXISTS idx_erm_dim_scores_risk
  ON erm_risk_dimension_scores(risk_id);
"""

# ── PostgreSQL schema variants ─────────────────────────────────────────────────
# Applied once at module load; keeps SQLite strings unchanged.
_PG_SCHEMA_SUBS = [
    # Strip SQLite-only pragmas
    (re.compile(r'^[ \t]*PRAGMA\s+\w[^;]*;?\s*$', re.MULTILINE | re.IGNORECASE), ""),
    # Primary key sequence
    (re.compile(r'\bINTEGER PRIMARY KEY AUTOINCREMENT\b'), "SERIAL PRIMARY KEY"),
    # Timestamp column type + default
    (re.compile(r"\bTEXT DEFAULT \(datetime\('now'\)\)"), "TIMESTAMPTZ DEFAULT NOW()"),
    (re.compile(r"\bTEXT DEFAULT \(date\('now'\)\)"), "DATE DEFAULT CURRENT_DATE"),
    # Float columns
    (re.compile(r'\bREAL\b'), "DOUBLE PRECISION"),
]


def _to_pg_schema(sql: str) -> str:
    for pat, repl in _PG_SCHEMA_SUBS:
        sql = pat.sub(repl, sql)
    return sql


_SHARED_TABLES_PG    = _to_pg_schema(_SHARED_TABLES)
_PLATFORM_TABLES_PG  = _to_pg_schema(_PLATFORM_TABLES)
_ARIA_TABLES_PG      = _to_pg_schema(_ARIA_TABLES)
_GRID_TABLES_PG      = _to_pg_schema(_GRID_TABLES)
_BCM_TABLES_PG       = _to_pg_schema(_BCM_TABLES)
_SENTINEL_TABLES_PG  = _to_pg_schema(_SENTINEL_TABLES)
_ERM_ORM_TABLES_PG   = _to_pg_schema(_ERM_ORM_TABLES)


_COLUMN_MIGRATIONS = [
        # (table, column, definition)
        ("aria_frameworks", "is_active", "INTEGER DEFAULT 1"),
        ("aria_frameworks", "relevant_modules", "TEXT DEFAULT ''"),
        ("users", "avatar_initials", "TEXT"),
        ("users", "must_change_password", "INTEGER DEFAULT 0"),
        ("users", "org_id", "INTEGER REFERENCES organizations(id)"),
        ("users", "is_super_admin", "INTEGER DEFAULT 0"),
        ("api_keys", "org_id", "INTEGER REFERENCES organizations(id)"),
        ("audit_log", "org_id", "INTEGER REFERENCES organizations(id)"),
        ("sessions", "mfa_pending", "INTEGER DEFAULT 0"),
        ("controls", "document_title", "TEXT DEFAULT ''"),
        ("controls", "version", "TEXT DEFAULT '1.0'"),
        ("sla_instances", "escalation_due", "TEXT"),
        ("sla_instances", "escalated_at", "TEXT"),
        ("sla_instances", "breach_type", "TEXT"),
        ("evidence_items", "file_hash", "TEXT"),
        ("evidence_items", "parent_id", "INTEGER REFERENCES evidence_items(id)"),
        ("grid_audits", "end_date", "TEXT"),
        ("grid_audits", "scope", "TEXT DEFAULT ''"),
        ("grid_audits", "objective", "TEXT DEFAULT ''"),
        ("grid_audits", "criteria", "TEXT DEFAULT ''"),
        ("grid_audits", "methodology", "TEXT DEFAULT ''"),
        ("grid_audits", "conclusion", "TEXT DEFAULT ''"),
        # CAP lifecycle fields for non-conformances
        ("grid_non_conformances", "preventive_action", "TEXT"),
        ("grid_non_conformances", "target_date", "TEXT"),
        ("grid_non_conformances", "verification_notes", "TEXT"),
        ("grid_non_conformances", "verified_by", "INTEGER REFERENCES users(id)"),
        ("grid_non_conformances", "verified_at", "TEXT"),
        ("grid_non_conformances", "cap_status", "TEXT DEFAULT 'Open'"),
        # Management response workflow
        ("grid_non_conformances", "response_deadline", "TEXT"),
        ("grid_non_conformances", "effectiveness_review", "TEXT"),
        ("grid_non_conformances", "mgmt_response", "TEXT"),
        ("grid_non_conformances", "mgmt_response_by", "INTEGER REFERENCES users(id)"),
        ("grid_non_conformances", "mgmt_response_at", "TEXT"),
        ("grid_non_conformances", "mgmt_response_status", "TEXT"),
        # Follow-up audit linking
        ("grid_audits", "parent_audit_id", "INTEGER REFERENCES grid_audits(id)"),
        # NC carry-forward: tracks which NC in the parent audit this was copied from
        ("grid_non_conformances", "source_nc_id", "INTEGER REFERENCES grid_non_conformances(id)"),
        # Audit sign-off & locking
        ("grid_audits", "is_locked", "INTEGER DEFAULT 0"),
        ("grid_audits", "locked_at", "TEXT"),
        ("grid_audits", "locked_by", "INTEGER REFERENCES users(id)"),
        # ARIA document lifecycle
        ("aria_documents", "ai_draft_body", "TEXT"),
        ("aria_documents", "file_path", "TEXT"),
        ("aria_documents", "file_name", "TEXT"),
        ("aria_documents", "file_size", "INTEGER DEFAULT 0"),
        ("aria_documents", "template_id", "INTEGER REFERENCES aria_doc_templates(id)"),
        ("aria_documents", "branded_file_path", "TEXT"),
        ("aria_documents", "reviewed_by", "INTEGER REFERENCES users(id)"),
        ("aria_documents", "reviewed_at", "TEXT"),
        # Sentinel DPIA — columns referenced by data_service but missing from CREATE TABLE
        ("sentinel_dpias", "org_name", "TEXT"),
        ("sentinel_dpias", "controller_name", "TEXT"),
        ("sentinel_dpias", "dpo_name", "TEXT"),
        ("sentinel_dpias", "dpo_email", "TEXT"),
        ("sentinel_dpias", "activity_type", "TEXT"),
        ("sentinel_dpias", "activity_desc", "TEXT"),
        ("sentinel_dpias", "purpose", "TEXT"),
        ("sentinel_dpias", "legal_basis", "TEXT"),
        ("sentinel_dpias", "special_cats", "TEXT DEFAULT '[]'"),
        ("sentinel_dpias", "subject_count", "TEXT"),
        ("sentinel_dpias", "retention", "TEXT"),
        ("sentinel_dpias", "systems", "TEXT"),
        ("sentinel_dpias", "processors", "TEXT"),
        ("sentinel_dpias", "intl_transfer", "TEXT"),
        ("sentinel_dpias", "transfer_dest", "TEXT"),
        ("sentinel_dpias", "transfer_mech", "TEXT"),
        ("sentinel_dpias", "overall_risk", "TEXT"),
        ("sentinel_dpias", "residual_risk", "TEXT"),
        ("sentinel_dpias", "dpo_consulted", "INTEGER DEFAULT 0"),
        ("sentinel_dpias", "auth_consulted", "INTEGER DEFAULT 0"),
        ("sentinel_dpias", "subjects_consulted", "INTEGER DEFAULT 0"),
        ("sentinel_dpias", "consult_notes", "TEXT"),
        ("sentinel_dpias", "ai_research", "TEXT"),
        ("sentinel_dpias", "ai_full_dpia", "TEXT"),
        # Sentinel RoPA — columns in _ROPA_FIELDS missing from CREATE TABLE
        ("sentinel_ropa", "subject_count", "TEXT"),
        ("sentinel_ropa", "systems", "TEXT"),
        ("sentinel_ropa", "processors", "TEXT"),
        ("sentinel_ropa", "intl_transfers", "TEXT"),
        ("sentinel_ropa", "transfer_dest", "TEXT"),
        ("sentinel_ropa", "transfer_safeguard", "TEXT"),
        ("sentinel_ropa", "security_measures", "TEXT DEFAULT '[]'"),
        ("sentinel_ropa", "ai_risk_notes", "TEXT"),
        ("sentinel_ropa", "review_date", "TEXT"),
        # Sentinel RoPA — DPO fields used when spawning DPIAs
        ("sentinel_ropa", "controller_name", "TEXT"),
        ("sentinel_ropa", "dpo_name", "TEXT"),
        ("sentinel_ropa", "dpo_email", "TEXT"),
        # Sentinel Breach — notification tracking columns
        ("sentinel_breaches", "notify_deadline", "TEXT"),
        ("sentinel_breaches", "breach_notified_24h", "INTEGER DEFAULT 0"),
        ("sentinel_breaches", "breach_notified_6h", "INTEGER DEFAULT 0"),
        # BCM-12/13: BIA MTPD + calculated criticality
        ("bcm_bia_records", "mtpd_hours", "INTEGER"),
        ("bcm_bia_records", "calc_criticality", "TEXT"),
        ("bcm_bia_records", "calc_notes", "TEXT"),
        # BCM-17: Plan activation columns
        ("bcm_plans", "is_active_plan", "INTEGER DEFAULT 0"),
        ("bcm_plans", "activated_at", "TEXT"),
        ("bcm_plans", "activated_by", "TEXT"),
        ("bcm_plans", "activation_reason", "TEXT"),
        # BCM-18: Plan extra fields (UI sends these)
        ("bcm_plans", "plan_type", "TEXT"),
        ("bcm_plans", "department", "TEXT"),
        ("bcm_plans", "description", "TEXT"),
        ("bcm_plans", "review_frequency", "TEXT"),
        # BCM-19: Incident extra fields (UI sends these)
        ("bcm_incidents", "impact", "TEXT"),
        ("bcm_incidents", "assigned_to", "TEXT"),
        ("bcm_incidents", "declared_at", "TEXT"),
        # ── Evidence links — soft-delete audit trail ──
        ("evidence_links", "deleted_at", "TEXT"),
        ("evidence_links", "deleted_by", "INTEGER REFERENCES users(id)"),
        # ── S-1: sentinel_consent — subject + date fields used by data_service ──
        ("sentinel_consent", "subject_id",       "TEXT"),
        ("sentinel_consent", "subject_name",      "TEXT"),
        ("sentinel_consent", "subject_email",     "TEXT"),
        ("sentinel_consent", "consent_date",      "TEXT"),
        ("sentinel_consent", "expiry_date",       "TEXT"),
        ("sentinel_consent", "withdrawal_date",   "TEXT"),
        ("sentinel_consent", "evidence",          "TEXT"),
        # ── S-2: sentinel_controllers — richer controller/DPO/regulator profile ──
        ("sentinel_controllers", "registration_number", "TEXT"),
        ("sentinel_controllers", "country",             "TEXT"),
        ("sentinel_controllers", "address",             "TEXT"),
        ("sentinel_controllers", "sector",              "TEXT"),
        ("sentinel_controllers", "controller_name",     "TEXT"),
        ("sentinel_controllers", "controller_email",    "TEXT"),
        ("sentinel_controllers", "controller_phone",    "TEXT"),
        ("sentinel_controllers", "dpo_name",            "TEXT"),
        ("sentinel_controllers", "dpo_email",           "TEXT"),
        ("sentinel_controllers", "dpo_phone",           "TEXT"),
        ("sentinel_controllers", "regulator_name",      "TEXT"),
        ("sentinel_controllers", "regulator_ref",       "TEXT"),
        ("sentinel_controllers", "regulation",          "TEXT DEFAULT 'GDPR'"),
        # ── S-3: sentinel_transfers — extra fields used by data_service ──
        ("sentinel_transfers", "ropa_id",          "INTEGER REFERENCES sentinel_ropa(id)"),
        ("sentinel_transfers", "transfer_type",    "TEXT"),
        ("sentinel_transfers", "safeguard_detail", "TEXT"),
        ("sentinel_transfers", "adequacy_decision","TEXT"),
        ("sentinel_transfers", "frequency",        "TEXT"),
        ("sentinel_transfers", "volume",           "TEXT"),
        # ── S-4: sentinel_retention — extra fields used by data_service ──
        ("sentinel_retention", "trigger_event", "TEXT"),
        ("sentinel_retention", "regulation",    "TEXT DEFAULT 'GDPR'"),
        # ── S-5: sentinel_security_measures — extra fields used by data_service ──
        ("sentinel_security_measures", "implementation_date", "TEXT"),
        ("sentinel_security_measures", "evidence",            "TEXT"),
        ("sentinel_security_measures", "regulation",          "TEXT DEFAULT 'GDPR'"),
        # ── S-6: sentinel_policies — rich policy management fields ──
        ("sentinel_policies", "department",    "TEXT"),
        ("sentinel_policies", "regulation",    "TEXT DEFAULT 'GDPR'"),
        ("sentinel_policies", "file_path",     "TEXT"),
        ("sentinel_policies", "file_name",     "TEXT"),
        ("sentinel_policies", "expiry_date",   "TEXT"),
        ("sentinel_policies", "approved_by",   "TEXT"),
        ("sentinel_policies", "approved_date", "TEXT"),
        ("sentinel_policies", "next_review",   "TEXT"),
        ("sentinel_policies", "tags",          "TEXT"),
        # ── S-7: sentinel_training — individual attendance record fields ──
        ("sentinel_training", "training_name",   "TEXT"),
        ("sentinel_training", "training_type",   "TEXT"),
        ("sentinel_training", "staff_name",      "TEXT"),
        ("sentinel_training", "staff_email",     "TEXT"),
        ("sentinel_training", "department",      "TEXT"),
        ("sentinel_training", "completion_date", "TEXT"),
        ("sentinel_training", "expiry_date",     "TEXT"),
        ("sentinel_training", "score",           "REAL"),
        ("sentinel_training", "passed",          "INTEGER DEFAULT 0"),
        ("sentinel_training", "certificate_no",  "TEXT"),
        ("sentinel_training", "trainer",         "TEXT"),
        ("sentinel_training", "regulation",      "TEXT DEFAULT 'GDPR'"),
        # ── Ask ARIA: user feedback on Q&A responses ──────────────────────────
        ("aria_ask_log",      "feedback",       "INTEGER DEFAULT NULL"),
        # ── IMS: Integrated audit support columns on grid_audits ──────────────
        ("grid_audits", "is_integrated", "INTEGER DEFAULT 0"),
        ("grid_audits", "framework_ids",  "TEXT DEFAULT NULL"),
        # ── IMS: Auto-mapper metadata on aria_control_mappings ──────────────
        ("aria_control_mappings", "auto_generated", "INTEGER DEFAULT 0"),
        ("aria_control_mappings", "match_method",   "TEXT DEFAULT 'manual'"),
        # ── ERM: Enhanced risk scoring & workflow columns ──────────────────────
        ("erm_enterprise_risks", "qualitative_score",    "TEXT DEFAULT NULL"),
        ("erm_enterprise_risks", "inherent_score",       "INTEGER DEFAULT NULL"),
        ("erm_enterprise_risks", "residual_score",       "INTEGER DEFAULT NULL"),
        ("erm_enterprise_risks", "risk_statement",       "TEXT DEFAULT NULL"),
        ("erm_enterprise_risks", "workflow_step",        "TEXT DEFAULT 'draft'"),
        ("erm_enterprise_risks", "response_deadline",    "TEXT DEFAULT NULL"),
        ("erm_enterprise_risks", "effectiveness_rating", "INTEGER DEFAULT NULL"),
        # ── ORM: Event workflow + SLA + Basel III ──────────────────────────────
        ("orm_events", "workflow_step",       "TEXT DEFAULT 'identified'"),
        ("orm_events", "response_due_at",     "TEXT DEFAULT NULL"),
        ("orm_events", "resolution_due_at",   "TEXT DEFAULT NULL"),
        ("orm_events", "basel_category",      "TEXT DEFAULT NULL"),
        # ── ORM: KRI trend tracking ────────────────────────────────────────────
        ("orm_kris",   "trend",               "TEXT DEFAULT 'stable'"),
        # ── ORM: KRI auto-update from event type ──────────────────────────────
        ("orm_kris",   "auto_update_event_type", "TEXT DEFAULT NULL"),
        ("orm_kris",   "auto_update_notes",      "TEXT DEFAULT NULL"),
        # ── Canonical vendor linkage across modules ────────────────────────────
        ("sentinel_vendors", "canonical_id", "INTEGER REFERENCES canonical_vendors(id)"),
        ("grid_vendors",     "canonical_id", "INTEGER REFERENCES canonical_vendors(id)"),
        ("bcm_vendors",      "canonical_id", "INTEGER REFERENCES canonical_vendors(id)"),
        # ── Sentinel vendor extra fields in _VENDOR_FIELDS ────────────────────
        ("sentinel_vendors", "website",    "TEXT"),
        ("sentinel_vendors", "regulation", "TEXT DEFAULT 'GDPR'"),
        # ── Webhook org isolation ──────────────────────────────────────────────
        ("webhooks", "org_id", "INTEGER REFERENCES organizations(id)"),
        # ── ERM appetite breach deduplication ──────────────────────────────────
        ("erm_risk_appetite", "last_breach_notified_at", "TEXT"),
        # ── Workflow actions: columns added after initial PG table creation ───
        ("workflow_actions", "due_at", "TEXT"),
        ("workflow_actions", "acted_at", "TEXT"),
]


def _run_sqlite_alters(conn):
    """SQLite-only: ALTER TABLE ADD COLUMN for schema evolution and UNIQUE index creation."""
    for table, column, definition in _COLUMN_MIGRATIONS:
        try:
            conn.execute(f"SELECT {column} FROM {table} LIMIT 1")
        except OperationalError:
            # Column doesn't exist — add it
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
    conn.commit()

    # ── Create indexes that depend on migrated columns ──
    _POST_MIGRATION_INDEXES = [
        "CREATE INDEX IF NOT EXISTS idx_evidence_items_hash ON evidence_items(file_hash)",
        "CREATE INDEX IF NOT EXISTS idx_evidence_items_parent ON evidence_items(parent_id)",
        # S-9: Performance indexes for high-frequency status/regulation filters
        "CREATE INDEX IF NOT EXISTS idx_bcm_incidents_status    ON bcm_incidents(status)",
        "CREATE INDEX IF NOT EXISTS idx_bcm_risks_status        ON bcm_risks(status)",
        "CREATE INDEX IF NOT EXISTS idx_sent_breaches_status    ON sentinel_breaches(status)",
        "CREATE INDEX IF NOT EXISTS idx_sent_breaches_reg       ON sentinel_breaches(regulation)",
        "CREATE INDEX IF NOT EXISTS idx_sent_dsr_status         ON sentinel_dsr(status)",
        "CREATE INDEX IF NOT EXISTS idx_sent_dsr_deadline       ON sentinel_dsr(deadline_date)",
        "CREATE INDEX IF NOT EXISTS idx_sent_ropa_regulation    ON sentinel_ropa(regulation)",
        "CREATE INDEX IF NOT EXISTS idx_sent_ropa_status        ON sentinel_ropa(status)",
        "CREATE INDEX IF NOT EXISTS idx_sent_ropa_risk          ON sentinel_ropa(risk_level)",
        "CREATE INDEX IF NOT EXISTS idx_sent_dpias_regulation   ON sentinel_dpias(regulation)",
        "CREATE INDEX IF NOT EXISTS idx_sent_dpias_status       ON sentinel_dpias(status)",
        "CREATE INDEX IF NOT EXISTS idx_sent_retention_review   ON sentinel_retention(review_date)",
        # Canonical-vendor cross-module joins (P2 perf fix — used by get_vendor_directory)
        "CREATE INDEX IF NOT EXISTS idx_sent_vendors_canonical  ON sentinel_vendors(canonical_id)",
        "CREATE INDEX IF NOT EXISTS idx_grid_vendors_canonical  ON grid_vendors(canonical_id)",
        "CREATE INDEX IF NOT EXISTS idx_bcm_vendors_canonical   ON bcm_vendors(canonical_id)",
        # Hot WHERE / ORDER BY paths surfaced by audit
        "CREATE INDEX IF NOT EXISTS idx_audit_log_action        ON audit_log(action)",
        "CREATE INDEX IF NOT EXISTS idx_audit_log_created       ON audit_log(created_at)",
        "CREATE INDEX IF NOT EXISTS idx_task_board_assignee     ON task_board(assigned_to)",
        "CREATE INDEX IF NOT EXISTS idx_email_reminders_due     ON email_reminders(remind_at, is_sent)",
        # P1 concurrency fix — make canonical_vendors dedup and cross_module_links dedup atomic.
        # Wrapped in the loop's try/except so existing duplicate data does not break startup.
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_canonical_vendors_name_uq "
        "ON canonical_vendors(lower(trim(name)))",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_xlinks_dedup_uq "
        "ON cross_module_links("
        "source_module, source_type, source_id, "
        "target_module, target_type, target_id, relationship)",
        # Phase C: UNIQUE indexes required by ON CONFLICT DO NOTHING on seed tables
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_bcm_comms_title ON bcm_comm_templates(title)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_bcm_scenario_title ON bcm_scenario_library(title)",
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_erm_library_title ON erm_risk_library(title)",
        # Security hardening: indexes for high-traffic query patterns
        "CREATE INDEX IF NOT EXISTS idx_bcm_exercises_status ON bcm_exercises(status)",
        "CREATE INDEX IF NOT EXISTS idx_bcm_vendors_status ON bcm_vendors(status)",
        "CREATE INDEX IF NOT EXISTS idx_bcm_training_status ON bcm_training_modules(status)",
        "CREATE INDEX IF NOT EXISTS idx_bcm_chat_user ON bcm_chat_messages(user_id, created_at DESC)",
        "CREATE INDEX IF NOT EXISTS idx_bcm_attest_user ON bcm_training_attestations(user_id)",
        "CREATE INDEX IF NOT EXISTS idx_erm_risks_status ON erm_risks(status)",
        "CREATE INDEX IF NOT EXISTS idx_erm_risks_module ON erm_risks(module)",
        "CREATE INDEX IF NOT EXISTS idx_orm_events_status ON orm_events(status)",
        "CREATE INDEX IF NOT EXISTS idx_sessions_expires ON sessions(expires_at)",
        "CREATE INDEX IF NOT EXISTS idx_task_board_status ON task_board(status)",
        "CREATE INDEX IF NOT EXISTS idx_task_board_created_by ON task_board(created_by)",
        "CREATE INDEX IF NOT EXISTS idx_workflow_inst_def ON workflow_instances(definition_id)",
        "CREATE INDEX IF NOT EXISTS idx_calendar_assigned ON calendar_events(assigned_to)",
        "CREATE INDEX IF NOT EXISTS idx_calendar_created_by ON calendar_events(created_by)",
    ]
    for idx_sql in _POST_MIGRATION_INDEXES:
        try:
            conn.execute(idx_sql)
        except (OperationalError, IntegrityError) as exc:
            # OperationalError: column not yet migrated; safe to skip.
            # IntegrityError: existing duplicate data prevents UNIQUE creation —
            # log a warning so admins can dedupe manually, then continue.
            import logging as _log
            _log.getLogger("oneforall.migrations").warning(
                "Skipped index (likely duplicate data or missing column): %s — %s",
                idx_sql.split("ON")[0].strip(), exc,
            )
    conn.commit()

    # ── Data migration: auto-link existing vendors to canonical_vendors ──────
    try:
        for tbl in ("sentinel_vendors", "grid_vendors", "bcm_vendors"):
            unlinked = conn.execute(
                f"SELECT id, name, contact_email FROM {tbl} WHERE canonical_id IS NULL"
            ).fetchall()
            for row in unlinked:
                norm = (row[1] or "").strip().lower()
                if not norm:
                    continue
                existing = conn.execute(
                    "SELECT id FROM canonical_vendors WHERE lower(trim(name))=%s", (norm,)
                ).fetchone()
                if existing:
                    cid = existing[0]
                else:
                    cid = insert_returning_id(conn,
                        "INSERT INTO canonical_vendors (name, contact_email) VALUES (%s,%s)",
                        (row[1].strip(), row[2]),
                    )
                conn.execute(
                    f"UPDATE {tbl} SET canonical_id=%s WHERE id=%s", (cid, row[0])
                )
        conn.commit()
    except Exception:
        pass


def _seed_baseline_data(conn):
    """Seed reference data — runs on both SQLite and PostgreSQL."""
    # ── Data migration: ensure all expected frameworks exist ──
    _EXPECTED_FRAMEWORKS = [
        ("ISO 27001:2022", "Information Security Management System", "#1E3A5F", "aria,grid"),
        ("ISO 42001", "Artificial Intelligence Management System", "#6A0572", "aria,grid"),
        ("SOC 2 Type II", "Service Organization Control 2", "#0B5345", "aria,grid"),
        ("PCI DSS v4.0", "Payment Card Industry Data Security Standard", "#7D6608", "aria,grid"),
        ("GDPR", "General Data Protection Regulation (EU) 2016/679", "#154360", "sentinel,aria"),
        ("Zimbabwe CDPA", "Cyber and Data Protection Act [Chapter 12:07]", "#145A32", "sentinel"),
        ("HIPAA", "Health Insurance Portability and Accountability Act", "#6E2F03", "sentinel,aria"),
        ("ISO 9001:2015", "Quality Management System", "#1B4F72", "aria,grid"),
        ("ISO 22301:2019", "Business Continuity Management System", "#7B241C", "bcm,aria,grid"),
        ("ISO 27701:2019", "Privacy Information Management System", "#4A235A", "sentinel,aria"),
        ("ISO 20000-1:2018", "IT Service Management System", "#0E6251", "aria,grid"),
        ("ISO 27017:2015", "Cloud Security Controls", "#1A5276", "aria,grid"),
        ("ISO 31000:2018", "Risk Management Guidelines", "#784212", "aria,bcm,grid"),
        ("ISO 14001:2015", "Environmental Management System", "#1D8348", "aria,grid"),
        ("ISO 50001:2018", "Energy Management System", "#117A65", "aria,grid"),
    ]
    # Seed unified frameworks table
    try:
        existing = {}
        for row in conn.execute(
            "SELECT name, relevant_modules FROM frameworks"
        ).fetchall():
            existing[row[0]] = row[1] or ""
        for name, desc, color, modules in _EXPECTED_FRAMEWORKS:
            if name not in existing:
                conn.execute(
                    "INSERT INTO frameworks (name, description, color, relevant_modules, is_active) "
                    "VALUES (%s, %s, %s, %s, 1)",
                    (name, desc, color, modules),
                )
            elif existing[name] != modules:
                conn.execute(
                    "UPDATE frameworks SET relevant_modules=%s WHERE name=%s",
                    (modules, name),
                )
        conn.commit()
    except Exception:
        pass

    # ── Seed BCM communication templates (BCM-14) ────────────────────────────
    _BCM_COMM_TEMPLATES = [
        ("Ransomware — Internal Staff Alert", "all-staff", "ransomware,cyber",
         "URGENT: Ransomware Incident — Action Required",
         "Dear Team,\n\nWe are currently responding to a ransomware incident that has affected some of our systems. Our IT and BCM teams are actively working to contain the situation.\n\n**Immediate actions required from all staff:**\n1. Do NOT open any suspicious emails or attachments.\n2. Disconnect your device from the network if you notice unusual activity.\n3. Contact the IT helpdesk immediately at {{helpdesk_number}}.\n4. Do not attempt to recover files yourself.\n\nUpdates will be provided every {{update_interval}} hours.\n\n{{incident_commander_name}}\n{{incident_commander_role}}",
         "helpdesk_number,update_interval,incident_commander_name,incident_commander_role"),
        ("Data Centre Failure — Customer Notice", "external", "outage,infrastructure",
         "Service Disruption Notice — {{service_name}}",
         "Dear Customer,\n\nWe are writing to inform you of a service disruption affecting {{service_name}} since {{incident_time}}.\n\n**Current status:** {{current_status}}\n**Estimated resolution:** {{eta}}\n**Impact:** {{impact_description}}\n\nOur team is working urgently to restore full service. We will provide updates every {{update_interval}} hours or as the situation develops.\n\nWe sincerely apologise for any inconvenience caused.\n\n{{contact_name}}\n{{contact_title}}\n{{company_name}}",
         "service_name,incident_time,current_status,eta,impact_description,update_interval,contact_name,contact_title,company_name"),
        ("Regulatory Authority Notification", "authority", "breach,regulatory",
         "Notifiable Incident — {{ref_number}} — {{company_name}}",
         "Dear {{authority_name}},\n\nIn accordance with {{regulation}} Article {{article}}, we are notifying you of an incident that occurred on {{incident_date}}.\n\n**Incident Reference:** {{ref_number}}\n**Nature of incident:** {{incident_description}}\n**Data subjects affected:** Approximately {{affected_count}}\n**Categories of personal data:** {{data_categories}}\n**Likely consequences:** {{consequences}}\n**Measures taken:** {{measures_taken}}\n\nWe will provide a further update by {{next_update_date}}.\n\n{{dpo_name}}\nData Protection Officer\n{{company_name}}\n{{dpo_contact}}",
         "authority_name,regulation,article,incident_date,ref_number,incident_description,affected_count,data_categories,consequences,measures_taken,next_update_date,dpo_name,company_name,dpo_contact"),
        ("Key Person Unavailability — Internal", "internal", "people,personnel",
         "Business Continuity Update — Temporary Role Coverage",
         "Dear {{team_name}} Team,\n\nDue to the unexpected unavailability of {{person_name}} ({{role}}), temporary arrangements are in place effective immediately.\n\n**Acting coverage:** {{coverage_name}} will assume responsibilities for {{duration}}.\n\n**Key contacts during this period:**\n- {{coverage_name}}: {{coverage_contact}}\n- Escalation: {{escalation_contact}}\n\n**Business continuity measures in place:**\n{{continuity_measures}}\n\nPlease direct all queries to the acting contact above.\n\n{{sender_name}}\n{{sender_role}}",
         "team_name,person_name,role,coverage_name,duration,coverage_contact,escalation_contact,continuity_measures,sender_name,sender_role"),
        ("Media Holding Statement", "media", "all",
         "Statement on {{incident_type}} — {{company_name}}",
         "{{company_name}} is aware of {{incident_type_description}} and is taking immediate action.\n\nThe safety of our {{stakeholder_type}} and the security of our operations remain our highest priorities. We are working with {{relevant_authorities}} to fully assess the situation.\n\nWe will provide a further update at {{next_update_time}}.\n\nMedia enquiries: {{media_contact}}\n{{media_contact_number}}",
         "incident_type,company_name,incident_type_description,stakeholder_type,relevant_authorities,next_update_time,media_contact,media_contact_number"),
        ("Supply Chain Disruption — Partner Notice", "external", "supply_chain,vendor",
         "Supply Chain Disruption Notice — Impact on {{service_type}} Services",
         "Dear {{partner_name}},\n\nWe are writing to advise you of a supply chain disruption affecting {{service_type}} services.\n\n**Affected services:** {{affected_services}}\n**Expected duration:** {{estimated_duration}}\n**Impact on your operations:** {{impact_description}}\n\n**Alternative arrangements:**\n{{alternative_arrangements}}\n\nYour account manager {{account_manager}} will contact you directly to discuss any specific impacts.\n\n{{sender_name}}\n{{sender_role}}",
         "partner_name,service_type,affected_services,estimated_duration,impact_description,alternative_arrangements,account_manager,sender_name,sender_role"),
    ]
    try:
        existing_tmpl = conn.execute("SELECT COUNT(*) FROM bcm_comm_templates WHERE is_builtin=1 OR is_builtin IS NULL").fetchone()[0]
        if existing_tmpl == 0:
            for title, cat, inc_types, subject, body, variables in _BCM_COMM_TEMPLATES:
                conn.execute(
                    "INSERT INTO bcm_comm_templates "
                    "(title, category, incident_types, subject, body, variables, is_active, created_by) "
                    "VALUES (%s, %s, %s, %s, %s, %s, 1, 'system') ON CONFLICT DO NOTHING",
                    (title, cat, inc_types, subject, body, variables),
                )
            conn.commit()
    except Exception:
        pass

    # ── Seed BCM scenario library (BCM-16) ────────────────────────────────────
    import json as _json
    _BCM_SCENARIOS = [
        ("Ransomware Attack", "cyber",
         "Simulates a ransomware incident targeting critical business systems. Tests the organisation's ability to isolate, assess, and recover encrypted systems while maintaining business continuity.",
         "1. Assess and contain the incident\n2. Invoke BC plans for affected systems\n3. Test stakeholder communications\n4. Validate backup and recovery procedures",
         _json.dumps([
             {"time": "T+0", "inject": "IT reports multiple servers showing ransomware encryption messages. File access has stopped."},
             {"time": "T+30min", "inject": "Ransomware has spread to the secondary server. Backup connectivity is confirmed."},
             {"time": "T+2h", "inject": "Attacker demands contact. Legal and comms teams need to be briefed."},
             {"time": "T+4h", "inject": "Backups from 48 hours ago confirmed intact. Recovery timeline requested by management."},
             {"time": "T+8h", "inject": "Regulators enquire about personal data impact. DPO assessment required."},
         ]), 240, "hard"),
        ("Data Centre Power Failure", "physical",
         "A total power failure at the primary data centre forces failover to the DR site. Tests RTO/RPO objectives and IT recovery procedures.",
         "1. Invoke DR plan and failover procedures\n2. Validate RTO/RPO compliance\n3. Test stakeholder communications\n4. Test return-to-primary procedures",
         _json.dumps([
             {"time": "T+0", "inject": "Primary DC loses power. UPS provides 20 minutes of runtime."},
             {"time": "T+15min", "inject": "Generator fails to start. DR site activation must begin."},
             {"time": "T+1h", "inject": "Core systems restored on DR site. Some applications still offline."},
             {"time": "T+3h", "inject": "Customer complaints increasing. Comms team requests status update."},
             {"time": "T+6h", "inject": "Primary DC power restored. Begin return-to-primary planning."},
         ]), 180, "medium"),
        ("Pandemic / Mass Staff Absence", "people",
         "Simulates 40% staff absence due to a pandemic or contagious illness. Tests remote working capabilities, cross-training, and critical function coverage.",
         "1. Activate remote working provisions\n2. Identify critical function gaps\n3. Prioritise operations under reduced capacity\n4. Test communications to staff and customers",
         _json.dumps([
             {"time": "Day 1", "inject": "20% of staff absent. Remote working activated for all eligible staff."},
             {"time": "Day 3", "inject": "Absence rate rises to 40%. Three critical roles have no backup coverage."},
             {"time": "Day 5", "inject": "Key customer is unable to reach their account team. Escalation required."},
             {"time": "Day 7", "inject": "Government advises extended restrictions. 6-week duration now expected."},
             {"time": "Day 14", "inject": "Staff morale and fatigue becoming operational concern. Wellness protocols needed."},
         ]), 180, "medium"),
        ("Critical Vendor Failure", "supply_chain",
         "A tier-1 vendor becomes insolvent or suffers a major outage. Tests the organisation's vendor resilience and ability to activate contingency suppliers.",
         "1. Assess operational impact of vendor failure\n2. Invoke vendor contingency arrangements\n3. Test communication to affected stakeholders\n4. Validate SLA and contractual positions",
         _json.dumps([
             {"time": "T+0", "inject": "Critical vendor confirms insolvency. Services will cease in 48 hours."},
             {"time": "T+4h", "inject": "Contingency vendor contacted. Lead time is 5 days for onboarding."},
             {"time": "T+24h", "inject": "Affected business unit reports it cannot operate without the vendor service."},
             {"time": "T+36h", "inject": "Legal team advises on contractual claims. Insurance notification required."},
             {"time": "T+48h", "inject": "Vendor service terminated. Manual workaround procedures must be enacted."},
         ]), 150, "hard"),
        ("Building Denial / Evacuation", "physical",
         "The primary office building is made inaccessible due to fire, flooding, or civil disruption. Tests invocation of alternative site and remote working plans.",
         "1. Evacuate safely and account for all staff\n2. Activate alternative site arrangements\n3. Restore critical functions within RTO\n4. Communicate to customers and stakeholders",
         _json.dumps([
             {"time": "T+0", "inject": "Fire alarm activated. Building evacuation in progress. Cause unknown."},
             {"time": "T+1h", "inject": "Fire service confirms building inaccessible for minimum 24 hours."},
             {"time": "T+2h", "inject": "5% of staff without laptops. Hot-desking at DR site is limited."},
             {"time": "T+8h", "inject": "Building access extended to 5 days. Full remote working must be sustained."},
             {"time": "T+24h", "inject": "Media ask about the fire. Corporate comms holding statement required."},
         ]), 120, "easy"),
        ("Cyber Breach — Data Exfiltration", "cyber",
         "A sophisticated attacker exfiltrates sensitive personal data over several weeks before detection. Tests the organisation's breach response, regulatory notification, and forensic investigation.",
         "1. Contain the breach and preserve evidence\n2. Assess scope of data exfiltrated\n3. Invoke GDPR 72-hour notification process\n4. Manage media and regulatory communications",
         _json.dumps([
             {"time": "T+0", "inject": "SIEM alerts to unusual outbound data transfers over the past 3 weeks."},
             {"time": "T+2h", "inject": "Forensics confirms 50,000 customer records exfiltrated. GDPR clock starts."},
             {"time": "T+24h", "inject": "Regulator must be notified within 48 hours. DPO assessment needed."},
             {"time": "T+48h", "inject": "Media has received a tip-off. Holding statement required immediately."},
             {"time": "T+72h", "inject": "Regulator notification due. Subject notification assessment required."},
         ]), 210, "hard"),
        ("Loss of Key IT System", "cyber",
         "A critical business application fails and cannot be restored within its RTO. Tests manual workaround procedures and prioritisation of business functions.",
         "1. Invoke manual workaround procedures\n2. Prioritise critical functions under degraded IT\n3. Communicate impact to affected business units\n4. Manage vendor escalation and recovery",
         _json.dumps([
             {"time": "T+0", "inject": "Core ERP system crashes. Vendor support engaged. Initial assessment 4-hour fix."},
             {"time": "T+4h", "inject": "Vendor unable to resolve. Estimates 24-hour downtime. Manual procedures required."},
             {"time": "T+8h", "inject": "Finance team unable to process payroll due in 3 days. Escalation needed."},
             {"time": "T+24h", "inject": "Workaround failing for order processing. Customer deliveries at risk."},
             {"time": "T+48h", "inject": "System restored. Data integrity validation and catch-up plan needed."},
         ]), 150, "medium"),
        ("Extreme Weather Event", "physical",
         "Severe weather prevents staff from reaching the office and disrupts supply chains. Tests remote working resilience and stakeholder communications during extended disruption.",
         "1. Activate remote working for all staff\n2. Assess supply chain disruption\n3. Monitor staff welfare and welfare of vulnerable employees\n4. Plan for extended disruption",
         _json.dumps([
             {"time": "Day 1", "inject": "Severe weather warning issued. Staff advised not to travel to office."},
             {"time": "Day 2", "inject": "Flooding blocks access roads. 30% of staff cannot work remotely."},
             {"time": "Day 3", "inject": "Key supplier cannot deliver. Critical stock levels at risk."},
             {"time": "Day 5", "inject": "Weather forecast extends disruption for 5 more days."},
             {"time": "Day 7", "inject": "Staff welfare concern raised for those without heating or power."},
         ]), 120, "easy"),
    ]
    try:
        existing_scen = conn.execute("SELECT COUNT(*) FROM bcm_scenario_library WHERE is_builtin=1").fetchone()[0]
        if existing_scen == 0:
            for title, cat, desc, objectives, injects, duration, difficulty in _BCM_SCENARIOS:
                conn.execute(
                    "INSERT INTO bcm_scenario_library "
                    "(title, category, description, objectives, injects, estimated_duration_minutes, difficulty, is_builtin) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,1) ON CONFLICT DO NOTHING",
                    (title, cat, desc, objectives, injects, duration, difficulty),
                )
            conn.commit()
    except Exception:
        pass

    # ── Seed active jurisdictions from existing RoPA regulation values ─────────
    try:
        from modules.sentinel.jurisdictions import JURISDICTION_RULES
        existing_configs = {row[0] for row in conn.execute(
            "SELECT jurisdiction_key FROM sentinel_jurisdiction_config"
        ).fetchall()}

        if not existing_configs:
            # New install — GDPR is the default primary
            conn.execute(
                "INSERT INTO sentinel_jurisdiction_config "
                "(jurisdiction_key, is_active, is_primary) VALUES (%s, 1, 1) ON CONFLICT DO NOTHING",
                ("GDPR",),
            )
            # Honour any jurisdictions already in use
            used = {row[0] for row in conn.execute(
                "SELECT DISTINCT regulation FROM sentinel_ropa WHERE regulation IS NOT NULL"
            ).fetchall() if row[0] in JURISDICTION_RULES}
            for reg in used:
                if reg != "GDPR":
                    conn.execute(
                        "INSERT INTO sentinel_jurisdiction_config "
                        "(jurisdiction_key, is_active, is_primary) VALUES (%s, 1, 0) ON CONFLICT DO NOTHING",
                        (reg,),
                    )
            conn.commit()
        elif not conn.execute(
            "SELECT 1 FROM sentinel_jurisdiction_config WHERE is_primary=1"
        ).fetchone():
            # Existing install with no primary — promote the first active one
            first = conn.execute(
                "SELECT jurisdiction_key FROM sentinel_jurisdiction_config "
                "WHERE is_active=1 LIMIT 1"
            ).fetchone()
            if first:
                conn.execute(
                    "UPDATE sentinel_jurisdiction_config SET is_primary=1 "
                    "WHERE jurisdiction_key=%s", (first[0],),
                )
            conn.commit()
    except Exception:
        pass

    # ── Seed ERM risk appetite defaults ──────────────────────────────────────
    try:
        existing_appetite = conn.execute("SELECT COUNT(*) FROM erm_risk_appetite").fetchone()[0]
        if existing_appetite == 0:
            _APPETITE_SEEDS = [
                ("Strategic Risk",          "low",    9,  "Strategic risks are treated with a low appetite, board-level review required"),
                ("Operational Risk",        "medium", 12, "Operational risks tolerated up to medium level with appropriate controls"),
                ("Compliance & Legal Risk", "low",    6,  "Zero tolerance for compliance breaches, immediate escalation required"),
                ("Financial Risk",          "medium", 12, "Financial risks managed within approved budget and insurance cover"),
                ("Reputational Risk",       "low",    9,  "Reputational risks actively managed, proactive communication required"),
                ("Technology Risk",         "medium", 15, "Technology risks mitigated through redundancy and security controls"),
                ("Third Party Risk",        "medium", 12, "Vendor/supplier risks managed through due diligence and contracts"),
                ("Environmental Risk",      "high",   20, "Environmental risks accepted within regulatory limits"),
            ]
            for cat, lvl, max_s, desc in _APPETITE_SEEDS:
                conn.execute(
                    "INSERT INTO erm_risk_appetite (category, appetite_level, max_score, description) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (cat, lvl, max_s, desc),
                )
            conn.commit()
    except Exception:
        pass

    # ── Seed ERM risk library ─────────────────────────────────────────────────
    try:
        existing_library = conn.execute("SELECT COUNT(*) FROM erm_risk_library").fetchone()[0]
        if existing_library == 0:
            _LIBRARY_SEEDS = [
                # (title, description, category, likelihood, impact, treatment, controls, industries, regulations, tags)
                ("Ransomware Attack","Malicious encryption of critical systems demanding payment","Technology Risk",4,5,"mitigate","MFA, backups, EDR, patch management","all","ISO 27001, NIST CSF","cyber,ransomware,critical"),
                ("Data Breach - PII Exposure","Unauthorised access to or disclosure of personal data","Compliance & Legal Risk",3,5,"mitigate","Access controls, encryption, DLP","all","GDPR, POPIA, HIPAA","data,privacy,gdpr"),
                ("Key Person Dependency","Critical operations reliant on single individual","Operational Risk",3,4,"mitigate","Knowledge transfer, cross-training, succession planning","all","","hr,operational"),
                ("Cloud Provider Outage","Primary cloud/SaaS provider unavailability","Technology Risk",3,4,"mitigate","Multi-cloud, SLA monitoring, DR plan","all","ISO 22301","cloud,availability,dr"),
                ("Supplier Bankruptcy / Failure","Key supplier ceases operations unexpectedly","Third Party Risk",2,5,"mitigate","Supplier due diligence, alternative suppliers, contracts","all","","vendor,supply_chain"),
                ("Internal Fraud","Employee misappropriation of funds or assets","Operational Risk",2,5,"mitigate","Segregation of duties, audit trails, background checks","financial,telecom","","fraud,internal"),
                ("Regulatory Non-Compliance","Failure to meet legal or regulatory requirements","Compliance & Legal Risk",3,5,"avoid","Compliance register, legal review, training","all","GDPR, ISO 27001, POPIA","regulatory,compliance"),
                ("Pandemic / Health Crisis","Widespread illness impacting workforce availability","Strategic Risk",2,4,"mitigate","Remote work capability, succession planning, BCM","all","ISO 22301","pandemic,bcm,strategic"),
                ("Natural Disaster","Flood, earthquake, fire affecting primary facilities","Strategic Risk",2,5,"mitigate","Business continuity plan, off-site backups, insurance","all","ISO 22301","disaster,bcm"),
                ("Zero-Day Vulnerability","Exploitation of previously unknown software vulnerability","Technology Risk",3,5,"mitigate","Vulnerability management, threat intelligence, patch SLAs","all","ISO 27001, NIST","cyber,vulnerability"),
                ("Currency / FX Exposure","Adverse exchange rate movements impacting financials","Financial Risk",3,3,"mitigate","Hedging, multi-currency accounts, FX policy","financial","","financial,fx"),
                ("Liquidity Risk","Inability to meet short-term financial obligations","Financial Risk",2,5,"mitigate","Cash flow forecasting, credit facilities, reserves","financial","","financial,liquidity"),
                ("Reputational Damage - Social Media","Viral negative content damaging brand perception","Reputational Risk",3,4,"mitigate","Social media policy, PR response plan, monitoring","all","","reputation,social"),
                ("Phishing / Social Engineering","Staff tricked into disclosing credentials or transferring funds","Operational Risk",4,4,"mitigate","Security awareness training, MFA, email filtering","all","ISO 27001","phishing,human_error"),
                ("Access Control Failure","Inappropriate access to sensitive systems or data","Compliance & Legal Risk",3,4,"mitigate","IAM, privilege review, PAM, access logging","all","ISO 27001, GDPR","access,iam"),
                ("Third-Party Data Breach","Vendor or partner suffers breach exposing shared data","Third Party Risk",3,5,"mitigate","Vendor assessments, DPAs, contract clauses","all","GDPR, POPIA","vendor,data,privacy"),
                ("Business Email Compromise (BEC)","Fraudulent email redirection of payments","Operational Risk",3,5,"mitigate","Email authentication, payment verification, training","financial,telecom","","bec,fraud,email"),
                ("GDPR Consent Failure","Processing personal data without valid consent basis","Compliance & Legal Risk",3,4,"avoid","Consent management, privacy notices, DPO oversight","all","GDPR, POPIA","gdpr,consent,privacy"),
                ("IT Disaster Recovery Gap","Critical systems lack tested recovery procedures","Technology Risk",3,4,"mitigate","DR plan, regular testing, RTO/RPO definition","all","ISO 22301, ISO 27001","dr,it,recovery"),
                ("Talent Retention Risk","Loss of skilled staff to competitors","Operational Risk",3,3,"mitigate","Competitive compensation, engagement, succession planning","all","","hr,talent,operational"),
                ("Regulatory Action / Fine","Regulator investigates or fines the organisation","Compliance & Legal Risk",2,5,"avoid","Compliance programme, legal monitoring, self-assessment","all","GDPR, POPIA, ISO","regulatory,fine"),
                ("Payment System Failure","Critical payment processing unavailable","Technology Risk",3,5,"mitigate","Redundant payment rails, manual fallback, monitoring","financial,telecom","ISO 22301","payments,availability"),
                ("SIM Swap / Telecoms Fraud","Fraudulent number porting enabling account takeover","Operational Risk",4,4,"mitigate","Multi-factor auth, verification controls, fraud monitoring","telecom","","telecom,fraud,sim"),
                ("Contact Centre Data Leak","Agent accidentally or intentionally discloses customer PII","Operational Risk",3,4,"mitigate","Screen recording policy, CRM access controls, training","telecom,financial","GDPR","contact_centre,data,privacy"),
                ("AI / Model Risk","AI model produces harmful, biased, or incorrect outputs","Technology Risk",3,4,"mitigate","AI governance, model validation, human oversight","all","ISO 42001","ai,model,technology"),
            ]
            for row in _LIBRARY_SEEDS:
                conn.execute(
                    "INSERT INTO erm_risk_library "
                    "(title, description, category, default_likelihood, default_impact, "
                    "typical_treatment, suggested_controls, applicable_industries, "
                    "regulatory_references, tags) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    row,
                )
            conn.commit()
    except Exception:
        pass

    # ── Seed ERM Risk Rating Framework (OmniContact default template) ────────
    try:
        existing_fw = conn.execute("SELECT COUNT(*) FROM erm_risk_frameworks").fetchone()[0]
        if existing_fw == 0:
            fw_id = insert_returning_id(
                conn,
                "INSERT INTO erm_risk_frameworks (name, description, is_active, is_default, source) "
                "VALUES (%s,%s,1,1,'built_in')",
                ("OmniContact Rating System",
                 "Default multi-dimension risk rating methodology: financial and qualitative "
                 "impact scoring across 7 factors, frequency-based likelihood, a 5-band risk "
                 "matrix, control effectiveness, and a 2-level risk taxonomy."),
            )

            # impact dimensions — Financial Exposure's 3 sub-metrics first, then the
            # qualitative dimensions, matching the source template's order. Each level
            # tuple is (description, threshold_label, threshold_min, threshold_max).
            _DIMENSIONS = [
                ("Financial Exposure — % Revenue", [
                    ("X < 0.1%", "X < 0.1% (< $583,170)", None, 0.001),
                    ("0.1% ≤ X < 0.4%", "0.1% ≤ X < 0.4% ($583,170–$2,332,681)", 0.001, 0.004),
                    ("0.4% ≤ X < 0.6%", "0.4% ≤ X < 0.6% ($2,332,681–$3,499,022)", 0.004, 0.006),
                    ("0.6% ≤ X < 0.8%", "0.6% ≤ X < 0.8% ($3,499,022–$4,665,363)", 0.006, 0.008),
                    ("X ≥ 0.8%", "X ≥ 0.8% (> $4,665,363)", 0.008, None),
                ]),
                ("Financial Exposure — % EBITDA", [
                    ("X < 0.5%", "X < 0.5% (< $1,350,444)", None, 0.005),
                    ("0.5% ≤ X < 1.0%", "0.5% ≤ X < 1.0% ($1,350,444–$2,700,888)", 0.005, 0.01),
                    ("1.0% ≤ X < 1.5%", "1.0% ≤ X < 1.5% ($2,700,888–$4,051,332)", 0.01, 0.015),
                    ("1.5% ≤ X < 2.0%", "1.5% ≤ X < 2.0% ($4,051,332–$5,401,777)", 0.015, 0.02),
                    ("X ≥ 2.0%", "X ≥ 2.0% (> $5,401,777)", 0.02, None),
                ]),
                ("Financial Exposure — % Total Assets", [
                    ("X < 0.05%", "X < 0.05% (< $500,200)", None, 0.0005),
                    ("0.05% ≤ X < 0.15%", "0.05% ≤ X < 0.15% ($500,200–$1,500,600)", 0.0005, 0.0015),
                    ("0.15% ≤ X < 0.25%", "0.15% ≤ X < 0.25% ($1,500,600–$2,501,000)", 0.0015, 0.0025),
                    ("0.25% ≤ X < 0.35%", "0.25% ≤ X < 0.35% ($2,501,000–$3,501,400)", 0.0025, 0.0035),
                    ("X ≥ 0.35%", "X ≥ 0.35% (> $3,501,400)", 0.0035, None),
                ]),
                ("Brand Damage", [
                    ("No impact on brand.", None, None, None),
                    ("Impact is isolated to a small group of existing customers. Damage is reversible.", None, None, None),
                    ("Negative impact is regional, is in the public domain, but with limited publicity.", None, None, None),
                    ("Negative impact is regional with widespread publicity, or national/global with limited publicity.", None, None, None),
                    ("Long-term irreparable damage. Negative impact is national or global and is widely publicised.", None, None, None),
                ]),
                ("Regulatory / Legal Action", [
                    ("No breaches of regulatory or contractual obligations.", None, None, None),
                    ("Breaches of regulatory or contractual obligations are confined to an isolated incident or incidents. Not systemic.", None, None, None),
                    ("Breach of regulatory or contractual obligations with costs to the business or client, and increased scrutiny from the regulator or the customer.", None, None, None),
                    ("Regulatory censure or action. Significant breach of rules or contract. Possibility of action against specific member(s) of senior management.", None, None, None),
                    ("Public regulatory fines, censure, or major litigation potential. Possibility of imprisonment for senior management.", None, None, None),
                ]),
                ("Customer / Operations", [
                    ("Failures are isolated or limited to a small number of internal personnel.", None, None, None),
                    ("Failure limited to a small group of customers or one business relationship.", None, None, None),
                    ("Systemic failure, impacts a specific customer group, transaction types or agents. Excludes sales practices.", None, None, None),
                    ("Systemic failure impacts multiple product groups, transaction types, or an entire distribution channel. Includes sales practices.", None, None, None),
                    ("Catastrophic failure impacting a broad spectrum of customer groups and distribution channels (e.g. core system failure, systemic fraud).", None, None, None),
                ]),
                ("Environment", [
                    ("Impact can be managed as part of daily activity, minimum environmental harm.", None, None, None),
                    ("Short-term (less than 1 year), localised environmental damage or loss of ecological amenities that could be reversed with minimal effort.", None, None, None),
                    ("Medium-term (1–10 years), localised environmental damage or loss of ecological amenities that might be reversed with intensive efforts.", None, None, None),
                    ("Long-term (greater than 10 years), widespread environmental damage or loss of ecological amenity.", None, None, None),
                    ("Permanent (greater than 100 years), widespread and significant environmental damage or loss of ecological amenity.", None, None, None),
                ]),
                ("People", [
                    ("Impact can be managed as part of daily activities; no injury potential, limited to first aid with a maximum impact of 1 day lost time. Localised HR problems resulting in employee dissatisfaction.", None, None, None),
                    ("Single lost time injury. Medium scale loss or unavailability of critical staff for under 1 week (industrial action, pandemic, worker dissatisfaction or terminations). Inability to attract and retain qualified personnel in non-critical roles.", None, None, None),
                    ("Isolated instances of chronic disease; multiple lost time injuries. Medium scale loss or unavailability of critical staff for under 1 week. Inability to attract and retain qualified personnel in critical roles.", None, None, None),
                    ("Single fatality or multiple permanent disabilities; multiple cases of chronic disease. Large scale loss or unavailability of critical staff (1 week to 1 month).", None, None, None),
                    ("Multiple fatalities. Large scale loss or unavailability of critical staff for more than 1 month.", None, None, None),
                ]),
                ("Media", [
                    ("No press reporting. Stakeholder concerns resulting in an informal warning to employees.", None, None, None),
                    ("State media reporting for more than 3 days. Stakeholder concerns resulting in disciplinary action on employees.", None, None, None),
                    ("State media reporting for more than 3 days. Stakeholder concerns resulting in a Manager resigning.", None, None, None),
                    ("Days of national media reporting. Shareholding Ministers' concerns resulting in reduction of delegated authority.", None, None, None),
                    ("Sustained adverse national/international media reporting. Shareholding Ministers' concerns resulting in intervention/take-over of decision making; COO departs and Board is restructured.", None, None, None),
                ]),
            ]
            for dim_idx, (dim_name, levels) in enumerate(_DIMENSIONS):
                dim_id = insert_returning_id(
                    conn,
                    "INSERT INTO erm_framework_impact_dimensions (framework_id, name, order_idx) VALUES (%s,%s,%s)",
                    (fw_id, dim_name, dim_idx),
                )
                for lvl, (desc, thresh_label, tmin, tmax) in enumerate(levels, start=1):
                    conn.execute(
                        "INSERT INTO erm_framework_impact_levels "
                        "(dimension_id, level, description, threshold_label, threshold_min, threshold_max) "
                        "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (dim_id, lvl, desc, thresh_label, tmin, tmax),
                    )

            # flat 5-point scales: likelihood + generic impact labels + control effectiveness.
            # Control effectiveness is seeded 1=Ineffective..5=Effective (ORM's existing
            # direction, orm_rcsa_risks/data_service.py:554 residual=inherent*(1-eff/5)) —
            # the source template's own 1=Strong..5=Weak direction is incompatible with that
            # formula (it would zero out residual risk for the weakest controls), so the
            # narrative labels below are the template's, deliberately reassigned to the
            # opposite level numbers.
            _SCALES = {
                "likelihood": [
                    (1, "Rare", "In more than / every 5 years"),
                    (2, "Infrequent", "Within the next / every 3-5 years"),
                    (3, "Occasional", "Within the next / every 1-3 years"),
                    (4, "Frequent", "Within the next / every 1 year"),
                    (5, "Imminent", "Within the next / every quarter"),
                ],
                "impact": [
                    (1, "Minor", None),
                    (2, "Moderate", None),
                    (3, "Significant", None),
                    (4, "Severe", None),
                    (5, "Catastrophic", None),
                ],
                "control_effectiveness": [
                    (1, "Weak or Non-existent",
                     "The control processes and management's mitigating activities do not allow for "
                     "effective management of the risk; there is no reduction in the frequency and/or "
                     "impact of the risk event."),
                    (2, "Marginally Adequate",
                     "The processes and management's mitigating activities allow for marginal management "
                     "of the risk; there is minimal reduction in frequency and/or impact. Major gaps and "
                     "deficiencies have been identified."),
                    (3, "Adequate",
                     "The control processes and management's mitigating activities allow for effective "
                     "management of the risk, reducing the frequency and/or impact of the risk event "
                     "occurring. Opportunities remain for improvement or additional compensating controls."),
                    (4, "Reasonably Strong",
                     "The control processes and management's mitigating activities are more than adequate "
                     "and allow for management of the risk, reducing frequency and/or impact; incremental "
                     "opportunities for improvement remain."),
                    (5, "Strong",
                     "The control processes and management's mitigating procedures are strong and allow "
                     "for effective management of the risk, significantly reducing the frequency and/or "
                     "impact of the risk. This does not mean there is no exposure to risk or that risk has "
                     "been reduced to zero."),
                ],
            }
            for scale_type, rows in _SCALES.items():
                for level, label, desc in rows:
                    conn.execute(
                        "INSERT INTO erm_framework_scales (framework_id, scale_type, level, label, description) "
                        "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (fw_id, scale_type, level, label, desc),
                    )

            # 5-band matrix — colors match the source template's own cell fills.
            _BANDS = [
                ("very_low", "Very Low", "#00B050", 0),
                ("low",      "Low",      "#92D050", 1),
                ("moderate", "Moderate", "#FFFF00", 2),
                ("high",     "High",     "#FFC000", 3),
                ("critical", "Critical", "#FF0000", 4),
            ]
            for band_key, label, color, sort_order in _BANDS:
                conn.execute(
                    "INSERT INTO erm_framework_bands (framework_id, band_key, label, color, sort_order) "
                    "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (fw_id, band_key, label, color, sort_order),
                )
            _valid_bands = {b[0] for b in _BANDS}

            # matrix is asymmetric (a hand-tuned governance grid, not a formula) — stored
            # explicitly rather than derived from a likelihood*impact cutoff.
            _MATRIX = {
                1: ["very_low", "very_low", "low",      "low",      "moderate"],
                2: ["very_low", "very_low", "low",      "moderate", "moderate"],
                3: ["very_low", "low",      "moderate", "high",     "high"],
                4: ["low",      "moderate", "high",     "high",     "critical"],
                5: ["low",      "moderate", "high",     "critical", "critical"],
            }
            for likelihood, row in _MATRIX.items():
                for impact, band_key in enumerate(row, start=1):
                    if band_key not in _valid_bands:
                        raise ValueError(f"seed error: unknown band_key {band_key!r}")
                    conn.execute(
                        "INSERT INTO erm_framework_matrix_bands (framework_id, likelihood, impact, band_key) "
                        "VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                        (fw_id, likelihood, impact, band_key),
                    )

            # 2-level taxonomy — Strategic/Reputational/Legal & Regulatory/Credit/Financial
            # have no sub-categories in the source template (left blank there too).
            _TAXONOMY = [
                ("Strategic Risk", []),
                ("Operational Risk", ["People", "Processes", "Systems", "Fraud", "Physical Assets"]),
                ("Compliance & Legal Risk", []),
                ("Credit Risk", []),
                ("Financial Risk", []),
                ("Reputational Risk", []),
                ("Technology Risk", ["Cybersecurity", "Infrastructure", "Data"]),
                ("Third Party Risk", ["Vendor Management", "Outsourcing", "Supply Chain"]),
                ("Environmental Risk", []),
                ("Market Risk", ["Exchange Rate", "Liquidity", "Interest Rate", "Competition"]),
            ]
            for idx, (name, children) in enumerate(_TAXONOMY):
                parent_id = insert_returning_id(
                    conn,
                    "INSERT INTO erm_framework_taxonomy (framework_id, parent_id, name, order_idx) "
                    "VALUES (%s,NULL,%s,%s)",
                    (fw_id, name, idx),
                )
                for cidx, child_name in enumerate(children):
                    conn.execute(
                        "INSERT INTO erm_framework_taxonomy (framework_id, parent_id, name, order_idx) "
                        "VALUES (%s,%s,%s,%s)",
                        (fw_id, parent_id, child_name, cidx),
                    )
            conn.commit()
    except Exception:
        pass

    # ── Idempotent taxonomy extension: add missing L1 nodes + rename ─────────
    # The original seed had 7 L1 taxonomy nodes; this migration adds the 3 new
    # ones and renames "Legal & Regulatory Risk" to "Compliance & Legal Risk".
    try:
        fw_row = conn.execute(
            "SELECT id FROM erm_risk_frameworks WHERE is_active=1"
        ).fetchone()
        if fw_row:
            _fw_id = fw_row[0] if isinstance(fw_row, (tuple, list)) else fw_row["id"]
            conn.execute(
                "UPDATE erm_framework_taxonomy SET name=%s WHERE framework_id=%s AND name=%s",
                ("Compliance & Legal Risk", _fw_id, "Legal & Regulatory Risk"),
            )
            _NEW_TAXONOMY_NODES = [
                ("Technology Risk", ["Cybersecurity", "Infrastructure", "Data"]),
                ("Third Party Risk", ["Vendor Management", "Outsourcing", "Supply Chain"]),
                ("Environmental Risk", []),
            ]
            for _t_name, _t_children in _NEW_TAXONOMY_NODES:
                exists = conn.execute(
                    "SELECT id FROM erm_framework_taxonomy WHERE framework_id=%s AND name=%s AND parent_id IS NULL",
                    (_fw_id, _t_name),
                ).fetchone()
                if not exists:
                    _max_ord = conn.execute(
                        "SELECT COALESCE(MAX(order_idx),0) FROM erm_framework_taxonomy WHERE framework_id=%s AND parent_id IS NULL",
                        (_fw_id,),
                    ).fetchone()
                    _next_ord = ((_max_ord[0] if isinstance(_max_ord, (tuple, list)) else _max_ord["COALESCE(MAX(order_idx),0)"]) or 0) + 1
                    _parent_id = insert_returning_id(
                        conn,
                        "INSERT INTO erm_framework_taxonomy (framework_id, parent_id, name, order_idx) VALUES (%s,%s,%s,%s)",
                        (_fw_id, None, _t_name, _next_ord),
                    )
                    for _ci, _cname in enumerate(_t_children):
                        conn.execute(
                            "INSERT INTO erm_framework_taxonomy (framework_id, parent_id, name, order_idx) VALUES (%s,%s,%s,%s)",
                            (_fw_id, _parent_id, _cname, _ci),
                        )
            conn.commit()
    except Exception:
        pass

    # ── Idempotent category rename: old slug-style -> taxonomy names ─────────
    # Safe: if already migrated, WHERE matches zero rows. Runs every startup.
    try:
        _CATEGORY_RENAMES = {
            "strategic": "Strategic Risk", "operational": "Operational Risk",
            "compliance": "Compliance & Legal Risk", "financial": "Financial Risk",
            "reputational": "Reputational Risk", "technology": "Technology Risk",
            "third_party": "Third Party Risk", "environmental": "Environmental Risk",
            "data_breach": "Technology Risk", "privacy": "Compliance & Legal Risk",
        }
        for old, new in _CATEGORY_RENAMES.items():
            conn.execute("UPDATE erm_enterprise_risks SET category=%s WHERE category=%s", (new, old))
            conn.execute("UPDATE erm_risk_appetite SET category=%s WHERE category=%s", (new, old))
            conn.execute("UPDATE erm_risk_library SET category=%s WHERE category=%s", (new, old))
        conn.commit()
    except Exception:
        pass

    # ── Recompute qualitative_score against the active framework matrix ──────
    # Unconditional (not count-gated): the seeded matrix is asymmetric so it
    # won't reproduce the old flat likelihood*impact cutoffs cell-for-cell.
    # Safe to run every startup since it's a pure function of stored
    # likelihood/impact. Kept in its own try/except so a failure here can
    # never suppress the framework-seeding block above, or vice versa.
    try:
        band_map = {(r[0], r[1]): r[2] for r in conn.execute(
            "SELECT mb.likelihood, mb.impact, mb.band_key FROM erm_framework_matrix_bands mb "
            "JOIN erm_risk_frameworks f ON f.id=mb.framework_id WHERE f.is_active=1"
        ).fetchall()}
        if band_map:
            for rid, likelihood, impact in conn.execute(
                "SELECT id, likelihood, impact FROM erm_enterprise_risks"
            ).fetchall():
                band = band_map.get((likelihood or 3, impact or 3), "moderate")
                conn.execute(
                    "UPDATE erm_enterprise_risks SET qualitative_score=%s WHERE id=%s",
                    (band, rid),
                )
            conn.commit()
    except Exception:
        pass

    # Keep aria_frameworks in sync (backward compat)
    try:
        existing_aria = {row[0] for row in conn.execute(
            "SELECT name FROM aria_frameworks"
        ).fetchall()}
        for name, desc, color, modules in _EXPECTED_FRAMEWORKS:
            if name not in existing_aria:
                conn.execute(
                    "INSERT INTO aria_frameworks (name, description, color, relevant_modules, is_active) "
                    "VALUES (%s, %s, %s, %s, 1)",
                    (name, desc, color, modules),
                )
        conn.commit()
    except Exception:
        pass


    # ── Seed ORM Event Templates ──────────────────────────────────────────────
    # (title, description, category, event_type, severity, department,
    #  process_affected, root_cause_category, corrective_action, preventive_action,
    #  basel_category, tags)
    _ORM_EVENT_TEMPLATES = [
        # ── Cybersecurity ──────────────────────────────────────────────────────
        ("Ransomware Attack",
         "Ransomware has encrypted critical systems or files, preventing normal business operations. Multiple systems may be affected.",
         "Cybersecurity", "system_failure", "critical", "IT / Security",
         "Server & File Management", "system",
         "1. Immediately isolate affected systems from the network.\n2. Engage incident response team and notify senior management.\n3. Assess scope using unaffected systems — identify encrypted files/servers.\n4. Check backups for integrity; initiate restore from last clean backup.\n5. Notify law enforcement and relevant regulators if personal data is involved.",
         "1. Enforce offline/immutable backups tested monthly.\n2. Deploy endpoint detection and response (EDR) on all devices.\n3. Implement network segmentation to limit lateral movement.\n4. Run quarterly phishing and security awareness training.\n5. Maintain and test an up-to-date incident response playbook.",
         "business_disruption", "ransomware,cyber,encryption,malware"),

        ("Phishing / Social Engineering Attack",
         "One or more employees received targeted phishing emails, resulting in credential compromise or malicious software installation.",
         "Cybersecurity", "fraud", "high", "IT / Security",
         "Email & Communications", "people",
         "1. Reset compromised credentials immediately and enforce MFA.\n2. Quarantine affected devices for forensic analysis.\n3. Notify affected users and HR.\n4. Scan mail gateway logs for similar messages and block sender.",
         "1. Deploy advanced email filtering (DMARC, SPF, DKIM).\n2. Run regular simulated phishing exercises.\n3. Enforce MFA on all systems and accounts.\n4. Establish a clear 'report suspicious email' process.",
         "external_fraud", "phishing,social-engineering,email,credentials"),

        ("Unauthorised System Access",
         "Unauthorised access to a system, application, or data store was detected, potentially resulting in data theft or modification.",
         "Cybersecurity", "system_failure", "critical", "IT / Security",
         "Access Management", "system",
         "1. Immediately revoke compromised credentials and active sessions.\n2. Preserve system logs for forensic investigation.\n3. Determine scope of access and identify any data exfiltrated.\n4. Notify DPO if personal data was accessed.",
         "1. Enforce principle of least privilege across all systems.\n2. Implement privileged access management (PAM) tooling.\n3. Enable real-time alerting on unusual login patterns.\n4. Conduct quarterly access rights reviews.",
         "internal_fraud", "unauthorised-access,intrusion,credentials"),

        ("DDoS / Service Disruption Attack",
         "A Distributed Denial of Service attack has overwhelmed internet-facing infrastructure, causing service degradation or complete outage.",
         "Cybersecurity", "outage", "high", "IT / Security",
         "Network & Infrastructure", "external",
         "1. Engage DDoS mitigation provider and activate scrubbing services.\n2. Notify ISP and CDN provider.\n3. Switch to backup connectivity or rate-limit traffic at perimeter.\n4. Update stakeholders on service restoration ETA.",
         "1. Subscribe to a managed DDoS mitigation service.\n2. Maintain a DDoS response runbook with ISP contact numbers.\n3. Deploy rate limiting and bot-detection on all public endpoints.\n4. Conduct annual resilience testing including DDoS simulation.",
         "business_disruption", "ddos,network,outage,cyber"),

        ("Malware / Virus Detection",
         "Malware or a virus has been detected on one or more endpoints or servers. System integrity may be compromised.",
         "Cybersecurity", "system_failure", "high", "IT / Security",
         "Endpoint Management", "system",
         "1. Quarantine infected device(s) from the network immediately.\n2. Run full antivirus/EDR scan across the environment.\n3. Identify the malware variant and assess scope of compromise.\n4. Wipe and rebuild affected systems from clean images if necessary.",
         "1. Maintain up-to-date antivirus and EDR on all endpoints.\n2. Disable AutoRun and restrict USB/removable media.\n3. Patch all operating systems and software on a defined schedule.\n4. Restrict administrative rights to IT-approved accounts only.",
         "business_disruption", "malware,virus,endpoint,security"),

        ("Insider Threat",
         "An employee or contractor has intentionally or negligently accessed, modified, or exfiltrated sensitive data or systems beyond their authorisation.",
         "Cybersecurity", "fraud", "critical", "HR / Legal",
         "Data Governance", "people",
         "1. Suspend the individual's access pending investigation.\n2. Preserve all relevant logs, emails, and access records.\n3. Engage HR, Legal, and if warranted, law enforcement.\n4. Notify affected parties and regulators if required by law.",
         "1. Implement data loss prevention (DLP) tooling.\n2. Monitor privileged user activity with UEBA tools.\n3. Enforce separation of duties for sensitive processes.\n4. Conduct background checks and periodic recertification of access rights.",
         "internal_fraud", "insider-threat,data-theft,privilege-abuse"),

        # ── Data & Privacy ─────────────────────────────────────────────────────
        ("Personal Data Breach",
         "Personal data has been accidentally or unlawfully accessed, disclosed, altered, or destroyed. Regulatory notification obligations may apply.",
         "Data & Privacy", "system_failure", "critical", "Privacy / Legal",
         "Data Processing", "system",
         "1. Contain the breach — stop ongoing access or disclosure.\n2. Notify DPO within 72 hours of discovery.\n3. Assess risk to data subjects and determine notification obligation.\n4. Document the breach in the breach register.",
         "1. Implement data encryption at rest and in transit.\n2. Apply strict access controls and regular access reviews.\n3. Train all staff on data handling and breach reporting procedures.\n4. Conduct annual DPIA reviews of high-risk processing activities.",
         "clients_products", "data-breach,privacy,gdpr,personal-data"),

        ("Data Exfiltration",
         "Sensitive data has been transferred outside the organisation without authorisation, either through malicious action or misconfiguration.",
         "Data & Privacy", "fraud", "critical", "IT / Security",
         "Data Transfer Controls", "system",
         "1. Immediately block the exfiltration channel (cloud upload, email, USB).\n2. Determine what data was exfiltrated and who it belongs to.\n3. Engage legal counsel and notify DPO.\n4. Preserve evidence for forensic analysis and potential litigation.",
         "1. Deploy data loss prevention (DLP) tools across endpoints and email.\n2. Restrict access to bulk data exports via RBAC.\n3. Monitor for unusual large-volume data transfers in SIEM.\n4. Classify sensitive data and apply protective labels.",
         "clients_products", "exfiltration,data-theft,dlp"),

        ("Unauthorised Data Disclosure",
         "Sensitive data was inadvertently disclosed to an unauthorised party, e.g., email sent to wrong recipient, public cloud bucket misconfigured.",
         "Data & Privacy", "human_error", "high", "Operations",
         "Data Sharing", "people",
         "1. Recall the email or request deletion by recipient where possible.\n2. Restrict the exposed asset (e.g., set cloud bucket to private).\n3. Assess nature and sensitivity of data disclosed.\n4. Notify DPO and evaluate regulatory reporting obligation.",
         "1. Implement email recipient verification tools (e.g., Egress, Mimecast).\n2. Require approval for bulk data exports or external file sharing.\n3. Conduct annual data classification and handling training.\n4. Audit cloud storage permissions quarterly.",
         "execution_delivery", "disclosure,data-handling,email,cloud"),

        ("Regulatory Data Compliance Violation",
         "A breach of data protection obligations has been identified, e.g., unlawful retention, processing without consent, or international transfer violation.",
         "Data & Privacy", "process_failure", "high", "Compliance / Legal",
         "Regulatory Compliance", "process",
         "1. Cease the non-compliant processing activity immediately.\n2. Notify DPO and document the violation in the compliance register.\n3. Assess need for regulatory self-reporting (e.g., ICO, POTRAZ).\n4. Review and remediate related processes and policies.",
         "1. Maintain an up-to-date Record of Processing Activities (RoPA).\n2. Conduct DPIAs for all high-risk processing activities.\n3. Schedule annual compliance audits against applicable data regulations.\n4. Enforce data minimisation principles in all new systems.",
         "clients_products", "compliance,gdpr,data-protection,regulatory"),

        # ── Process & Operations ───────────────────────────────────────────────
        ("Payment Processing Failure",
         "The payment processing system has failed or produced errors, preventing transactions from completing and resulting in revenue loss.",
         "Process & Operations", "system_failure", "high", "Finance / Operations",
         "Payment Processing", "system",
         "1. Switch to manual payment processing or fallback gateway immediately.\n2. Identify the root cause — network, gateway, or application failure.\n3. Communicate downtime to customers and merchants.\n4. Reconcile all failed transactions after restoration.",
         "1. Implement payment gateway redundancy with automatic failover.\n2. Test payment systems as part of DR exercises quarterly.\n3. Maintain a manual payment fallback procedure.\n4. Monitor payment success rates in real time with auto-alerting.",
         "business_disruption", "payment,transaction,gateway,revenue"),

        ("SLA / Service Level Breach",
         "A key service level agreement has been breached, falling below the contracted performance metrics. Penalties and customer dissatisfaction may result.",
         "Process & Operations", "process_failure", "medium", "Operations",
         "Service Delivery", "process",
         "1. Notify affected client(s) immediately and acknowledge the breach.\n2. Conduct root cause analysis and document contributing factors.\n3. Provide a remediation plan with a timeline to the client.\n4. Review SLA terms to confirm penalty or cure provisions.",
         "1. Implement real-time SLA monitoring dashboards.\n2. Set internal early-warning thresholds at 80% of SLA limit.\n3. Review SLA feasibility at contract renewal for all key accounts.\n4. Conduct monthly SLA performance reviews with operations leadership.",
         "clients_products", "sla,service-level,contract,performance"),

        ("Manual Processing Error",
         "A human error in a manual process resulted in incorrect data entry, miscalculation, or incorrect execution of a business transaction.",
         "Process & Operations", "human_error", "medium", "Operations",
         "Manual Operations", "people",
         "1. Identify and reverse the erroneous transaction where possible.\n2. Notify affected parties (customers, counterparts, management).\n3. Document the error and the corrective steps taken.\n4. Review other recent manual transactions for similar errors.",
         "1. Implement dual-control (four-eyes) checks on high-risk manual transactions.\n2. Automate recurring manual processes where feasible.\n3. Maintain clear, step-by-step procedural guides for critical tasks.\n4. Provide refresher training on high-risk manual procedures.",
         "execution_delivery", "manual-process,human-error,data-entry"),

        ("Workflow / Approval Process Breakdown",
         "A key internal workflow has broken down due to system failure, missing approvals, or process bypass, resulting in unauthorised or uncontrolled actions.",
         "Process & Operations", "process_failure", "medium", "Operations",
         "Internal Controls", "process",
         "1. Halt all in-flight transactions using the affected workflow.\n2. Identify what bypassed the process and assess the impact.\n3. Apply emergency manual controls until the workflow is restored.\n4. Review all decisions made during the breakdown period.",
         "1. Implement automated workflow enforcement with mandatory approval gates.\n2. Generate alerts when approvals are bypassed or overridden.\n3. Conduct regular process walkthroughs with control owners.\n4. Test workflow controls as part of annual internal audits.",
         "execution_delivery", "workflow,approval,internal-controls"),

        ("Document / Records Control Failure",
         "Critical business documents, contracts, or records were lost, misfiled, improperly modified, or inaccessible, impacting operations or compliance.",
         "Process & Operations", "process_failure", "medium", "Compliance / Operations",
         "Records Management", "process",
         "1. Attempt to recover the document from backups, version history, or email.\n2. Assess business and compliance impact of the missing/corrupted record.\n3. Notify legal if contracts or regulated documents are affected.\n4. Document the incident and any recovery actions taken.",
         "1. Implement a document management system with versioning and access controls.\n2. Define and enforce document retention policies.\n3. Back up critical records separately from general file storage.\n4. Conduct annual records management audits.",
         "execution_delivery", "records,documents,compliance,version-control"),

        # ── Technology & Systems ───────────────────────────────────────────────
        ("System / Application Outage",
         "A core business application or platform is unavailable, preventing users from carrying out business operations.",
         "Technology & Systems", "outage", "high", "IT",
         "Application Management", "system",
         "1. Trigger the incident response and escalate to IT management.\n2. Attempt restart/failover to standby systems.\n3. Communicate estimated recovery time to affected business units.\n4. Invoke business continuity procedures for critical processes.",
         "1. Implement high-availability (HA) architecture for critical systems.\n2. Maintain a tested disaster recovery (DR) plan with RTO/RPO targets.\n3. Monitor system availability 24/7 with automated alerting.\n4. Conduct regular DR failover tests at least annually.",
         "business_disruption", "outage,downtime,availability,application"),

        ("Database Failure / Corruption",
         "A critical database has failed, become unavailable, or data corruption has been detected, affecting dependent applications and data integrity.",
         "Technology & Systems", "system_failure", "critical", "IT",
         "Database Management", "system",
         "1. Take the affected application offline to prevent further data corruption.\n2. Engage database administrator to assess scope of failure or corruption.\n3. Restore from last verified clean backup.\n4. Validate data integrity after restoration before returning to production.",
         "1. Implement database replication with automated failover.\n2. Schedule and test database backups daily; verify integrity monthly.\n3. Use database integrity monitoring tools.\n4. Apply database change management through a controlled process.",
         "business_disruption", "database,corruption,backup,data-integrity"),

        ("Network / Connectivity Failure",
         "A network outage or connectivity failure has disrupted communications between systems, branches, or to cloud services.",
         "Technology & Systems", "outage", "high", "IT",
         "Network Infrastructure", "system",
         "1. Identify the affected network segment and scope of the outage.\n2. Activate backup or failover connectivity (secondary ISP, 4G/5G).\n3. Notify affected business units and provide estimated resolution time.\n4. Engage ISP or network vendor for support if external cause.",
         "1. Implement redundant network paths with automatic failover.\n2. Monitor network availability and latency in real time.\n3. Maintain and test backup connectivity options.\n4. Include network failure scenarios in annual DR testing.",
         "business_disruption", "network,connectivity,outage,isp"),

        ("Software Deployment Failure",
         "A software release or patch deployment has caused system instability, application errors, or data issues in production.",
         "Technology & Systems", "system_failure", "high", "IT",
         "Software Delivery", "process",
         "1. Roll back to the previous stable version immediately.\n2. Assess impact on data integrity — check for corrupted records.\n3. Conduct post-mortem to identify the cause of the deployment failure.\n4. Communicate impact and resolution timeline to affected users.",
         "1. Enforce mandatory testing in staging environment before production deployment.\n2. Implement automated rollback capability in CI/CD pipeline.\n3. Require change approval from IT and business owners for significant releases.\n4. Deploy during low-traffic maintenance windows.",
         "execution_delivery", "deployment,release,rollback,ci-cd"),

        ("Hardware Failure",
         "Critical hardware (server, storage, network device) has failed, impacting system availability and potentially causing data loss.",
         "Technology & Systems", "system_failure", "high", "IT",
         "Infrastructure Management", "system",
         "1. Identify failed hardware component and switch to standby/spare.\n2. Procure replacement hardware and initiate vendor SLA if under warranty.\n3. Restore from backup if data loss has occurred.\n4. Document the failure and update asset register.",
         "1. Maintain hot/warm spare hardware for critical components.\n2. Monitor hardware health metrics proactively (SMART, temperature, fan).\n3. Enforce hardware lifecycle management and replacement schedules.\n4. Maintain a hardware inventory with warranty and end-of-life dates.",
         "physical_assets", "hardware,server,storage,infrastructure"),

        # ── People & HR ────────────────────────────────────────────────────────
        ("Employee Error Causing Financial Loss",
         "An employee made an error resulting in financial loss, incorrect disbursement, or erroneous commitment to a third party.",
         "People & HR", "human_error", "high", "Operations / Finance",
         "Financial Operations", "people",
         "1. Halt any further payments or commitments related to the error.\n2. Quantify the financial impact and notify Finance and senior management.\n3. Pursue recovery from counterparty where feasible.\n4. Document the error and remediation steps.",
         "1. Implement dual-control on all significant financial transactions.\n2. Enforce transaction limits with mandatory escalation above threshold.\n3. Ensure adequate coverage and backup for critical financial roles.\n4. Provide regular training on financial procedures and controls.",
         "execution_delivery", "human-error,financial,disbursement,employee"),

        ("Key Person Unavailability",
         "A key employee in a critical role is unexpectedly unavailable, creating a single point of failure and disrupting business operations.",
         "People & HR", "human_error", "medium", "HR / Operations",
         "People Management", "people",
         "1. Activate the documented cover/backup arrangement for the role.\n2. Brief the acting person on urgent priorities and ongoing matters.\n3. Notify key stakeholders of the temporary coverage arrangement.\n4. Escalate to management if cover cannot be provided within required timeframe.",
         "1. Document deputy/succession arrangements for all critical roles.\n2. Cross-train team members to cover critical processes.\n3. Maintain current procedure guides for all time-sensitive tasks.\n4. Include key person risk in annual business impact analysis.",
         "people_practices", "key-person,single-point-of-failure,succession,hr"),

        ("Unauthorised Action by Employee",
         "An employee has performed an action outside their authorised scope, including system changes, financial transactions, or disclosure of information.",
         "People & HR", "fraud", "high", "HR / Legal",
         "Access & Authorisation Controls", "people",
         "1. Suspend the employee's access and place on administrative leave pending investigation.\n2. Preserve evidence of the unauthorised action.\n3. Engage HR, Legal, and where warranted, law enforcement.\n4. Assess impact of the unauthorised action and implement remediation.",
         "1. Enforce strict role-based access control and least-privilege principles.\n2. Implement activity logging and anomaly detection for privileged actions.\n3. Conduct regular access recertification reviews.\n4. Establish a clear disciplinary policy for policy violations.",
         "internal_fraud", "unauthorised-action,employee,policy-breach,hr"),

        ("Staff Training Non-Compliance",
         "A significant number of employees have failed to complete mandatory training (e.g., AML, data protection, security awareness), creating regulatory and operational risk.",
         "People & HR", "process_failure", "medium", "HR / Compliance",
         "Training & Development", "people",
         "1. Generate a report of all non-compliant staff and notify their line managers.\n2. Set a firm deadline for completion with escalation to senior management.\n3. Block access to sensitive systems for critically non-compliant staff where proportionate.\n4. Report non-compliance rate to the relevant governance committee.",
         "1. Automate training assignment and deadline tracking in an LMS.\n2. Include training compliance metrics in quarterly HR reports.\n3. Tie mandatory training completion to performance review process.\n4. Schedule refresher training before regulatory deadlines.",
         "people_practices", "training,compliance,mandatory-training,regulatory"),

        # ── Financial & Fraud ──────────────────────────────────────────────────
        ("Internal Fraud",
         "An employee has committed or is suspected of committing fraud, including falsification of records, misappropriation of funds, or misuse of company assets.",
         "Financial & Fraud", "fraud", "critical", "Finance / HR",
         "Financial Controls", "people",
         "1. Suspend the employee's access immediately.\n2. Preserve all relevant records and refrain from confronting the individual.\n3. Engage Legal and HR; consider involving law enforcement.\n4. Quantify financial loss and pursue recovery options including insurance.",
         "1. Implement segregation of duties in all financial processes.\n2. Conduct regular internal audits and unannounced spot checks.\n3. Maintain a confidential whistleblowing channel.\n4. Perform pre-employment background checks for financial roles.",
         "internal_fraud", "fraud,internal,misappropriation,financial-crime"),

        ("External Payment Fraud",
         "Fraudsters have exploited payment channels (wire transfer, cheque, online banking) to redirect funds or make unauthorised payments.",
         "Financial & Fraud", "fraud", "critical", "Finance",
         "Payment Processing", "external",
         "1. Contact the bank immediately to recall the payment.\n2. Freeze affected accounts and change authentication credentials.\n3. Notify law enforcement and file a fraud report.\n4. Review all recent payment transactions for additional fraudulent activity.",
         "1. Implement callback verification for all large or unusual payments.\n2. Enforce dual authorisation for all payments above a defined threshold.\n3. Train Finance staff to recognise Business Email Compromise (BEC) tactics.\n4. Use out-of-band verification for changes to payee bank details.",
         "external_fraud", "payment-fraud,wire-fraud,bec,financial-crime"),

        ("Card Fraud / Skimming",
         "Fraudulent use of customer or company payment cards has been detected, resulting in unauthorised transactions or financial loss.",
         "Financial & Fraud", "fraud", "high", "Finance / Operations",
         "Card Management", "external",
         "1. Cancel affected cards immediately and issue replacements.\n2. Notify customers of the fraud and advise them to check statements.\n3. Report to card scheme (Visa/Mastercard) and acquiring bank.\n4. Inspect all card terminals and ATMs for skimming devices if applicable.",
         "1. Implement real-time transaction monitoring with fraud scoring.\n2. Migrate to chip-and-PIN/contactless for all card transactions.\n3. Inspect ATMs and card terminals regularly for tampering.\n4. Educate customers on secure card usage and reporting mechanisms.",
         "external_fraud", "card-fraud,skimming,payment-card,pci"),

        ("Financial Misstatement / Reporting Error",
         "A material error has been identified in financial statements, management accounts, or regulatory reports, requiring restatement or correction.",
         "Financial & Fraud", "process_failure", "high", "Finance / Compliance",
         "Financial Reporting", "process",
         "1. Notify CFO and Audit Committee immediately.\n2. Halt distribution of the erroneous report.\n3. Quantify the error and prepare a corrected version.\n4. Assess regulatory reporting obligations (e.g., mandatory restatement).",
         "1. Implement automated reconciliation and exception reporting.\n2. Enforce independent review of all financial reports before publication.\n3. Conduct a quarterly ledger review by internal audit.\n4. Maintain a clear financial close checklist with sign-off requirements.",
         "execution_delivery", "financial-reporting,misstatement,restatement,audit"),

        # ── Vendor & Third Party ───────────────────────────────────────────────
        ("Vendor Service Disruption",
         "A key vendor or service provider has experienced an outage or service degradation that is impacting your organisation's operations.",
         "Vendor & Third Party", "vendor_failure", "high", "Procurement / Operations",
         "Vendor Management", "external",
         "1. Activate alternative supplier or manual workaround procedures.\n2. Contact vendor account manager and escalate to their incident management team.\n3. Assess business impact and communicate to affected stakeholders.\n4. Document the disruption for vendor performance review.",
         "1. Qualify and maintain approved secondary/backup vendors for critical services.\n2. Include business continuity requirements in all vendor contracts.\n3. Conduct annual vendor risk assessments and business continuity testing.\n4. Monitor vendor SLA performance on a monthly basis.",
         "execution_delivery", "vendor,third-party,service-disruption,supplier"),

        ("Third Party Data Breach",
         "A vendor or data processor has experienced a data breach that includes your organisation's data or that of your customers.",
         "Vendor & Third Party", "vendor_failure", "critical", "Privacy / Legal",
         "Vendor Data Management", "external",
         "1. Contact the vendor immediately to obtain a full incident report.\n2. Notify DPO and assess notification obligations under data protection law.\n3. Terminate or restrict data access to the affected vendor.\n4. Notify affected customers if their personal data was involved.",
         "1. Include mandatory breach notification obligations in all data processor contracts.\n2. Conduct annual data processor due diligence and security audits.\n3. Minimise data shared with third parties to what is strictly necessary.\n4. Maintain a third-party data processing register.",
         "clients_products", "third-party,data-breach,vendor,data-processor"),

        ("Supplier Delivery Failure",
         "A supplier has failed to deliver goods, services, or materials on time, impacting production, customer commitments, or operations.",
         "Vendor & Third Party", "vendor_failure", "medium", "Operations / Procurement",
         "Supply Chain Management", "external",
         "1. Contact supplier urgently to establish cause and revised delivery date.\n2. Activate alternative suppliers or substitute goods where available.\n3. Notify affected customers or internal teams of the delay.\n4. Assess any penalty clauses in the supplier contract.",
         "1. Maintain a panel of pre-approved alternative suppliers for critical inputs.\n2. Hold safety stock levels for high-criticality materials.\n3. Monitor supplier lead times and flag at-risk deliveries proactively.\n4. Include delivery performance KPIs in supplier contracts.",
         "execution_delivery", "supply-chain,delivery,supplier,procurement"),

        ("Outsourced Process Failure",
         "A business process outsourced to a third party has failed or produced errors, impacting service quality, compliance, or financial outcomes.",
         "Vendor & Third Party", "vendor_failure", "high", "Operations / Compliance",
         "Outsourced Operations", "external",
         "1. Suspend the outsourced process pending investigation.\n2. Quantify impact on customers, finances, and compliance obligations.\n3. Invoke contractual escalation and remedy provisions.\n4. Take the process in-house temporarily if required.",
         "1. Define and monitor KPIs for all outsourced processes.\n2. Conduct regular governance meetings and quarterly business reviews with outsourcers.\n3. Maintain the ability to bring the process in-house within a defined timeframe.\n4. Include right-to-audit clauses in outsourcing contracts.",
         "execution_delivery", "outsourcing,bpo,third-party,process"),

        # ── Compliance & Regulatory ────────────────────────────────────────────
        ("Regulatory Reporting Failure",
         "A statutory or regulatory report has been filed late, incompletely, or with material errors, potentially triggering regulatory sanction.",
         "Compliance & Regulatory", "process_failure", "high", "Compliance / Finance",
         "Regulatory Reporting", "process",
         "1. Notify the regulator proactively before the deadline where possible.\n2. File the corrected or late report as soon as practicable.\n3. Prepare a written explanation for the regulator.\n4. Conduct root cause analysis and implement remediation.",
         "1. Maintain a regulatory reporting calendar with early-warning alerts.\n2. Assign a named owner and backup for each regulatory submission.\n3. Automate data extraction for recurring regulatory reports where possible.\n4. Conduct dry-run submissions one week before regulatory deadlines.",
         "execution_delivery", "regulatory-reporting,compliance,filing,regulator"),

        ("Licence / Permit Breach",
         "The organisation has operated outside the conditions of a regulatory licence, permit, or authorisation, creating regulatory and reputational risk.",
         "Compliance & Regulatory", "process_failure", "critical", "Compliance / Legal",
         "Licensing & Permits", "process",
         "1. Immediately cease the activity that breaches the licence conditions.\n2. Notify the board and legal counsel.\n3. Proactively report to the relevant regulator before they identify it.\n4. Prepare a remediation plan demonstrating how compliance will be restored.",
         "1. Maintain a register of all licences, permits, and authorisations with expiry dates.\n2. Conduct quarterly compliance reviews against licence conditions.\n3. Assign a named compliance officer responsible for each licence.\n4. Brief relevant staff on licence conditions and required controls.",
         "clients_products", "licence,permit,regulatory,authorisation"),

        ("Anti-Money Laundering (AML) Alert",
         "A transaction or customer activity pattern has triggered an AML alert indicating potential money laundering, requiring investigation and possible regulatory reporting.",
         "Compliance & Regulatory", "fraud", "critical", "Compliance / MLRO",
         "AML Monitoring", "process",
         "1. Place an immediate hold on the flagged account or transaction.\n2. Escalate to the Money Laundering Reporting Officer (MLRO) within 24 hours.\n3. Conduct an Enhanced Due Diligence (EDD) review of the customer.\n4. If suspicion is confirmed, file a Suspicious Activity Report (SAR) with the Financial Intelligence Unit.",
         "1. Implement an automated transaction monitoring system with risk-based rules.\n2. Ensure all customer due diligence (CDD/KYC) files are current and complete.\n3. Conduct annual AML training for all relevant staff.\n4. Review and update AML risk appetite and monitoring rules annually.",
         "clients_products", "aml,money-laundering,compliance,sar,kyc"),
    ]
    try:
        existing_tmpl = conn.execute(
            "SELECT COUNT(*) FROM orm_event_templates"
        ).fetchone()[0]
        if existing_tmpl == 0:
            for (title, description, category, event_type, severity, department,
                 process_affected, rcc, corrective, preventive, basel, tags) in _ORM_EVENT_TEMPLATES:
                conn.execute(
                    "INSERT INTO orm_event_templates "
                    "(title, description, category, event_type, severity, department, "
                    "process_affected, root_cause_category, corrective_action, preventive_action, "
                    "basel_category, tags, is_active) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,1)",
                    (title, description, category, event_type, severity, department,
                     process_affected, rcc, corrective, preventive, basel, tags),
                )
            conn.commit()
    except Exception:
        pass


def _run_pg_alters(conn) -> None:
    """PG equivalent of _run_sqlite_alters: adds schema-evolution columns using ADD COLUMN IF NOT EXISTS."""
    for table, column, definition in _COLUMN_MIGRATIONS:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {definition}")
        except Exception:
            pass
    conn.commit()


def _run_pg_fk_cascades(conn) -> None:
    """PostgreSQL: ensure critical FK constraints have correct ON DELETE behaviour.

    Inline REFERENCES in CREATE TABLE get auto-named constraints. This function
    finds them via information_schema, drops them, and re-adds with the correct
    ON DELETE rule. Safe to call multiple times - skips if rule already correct.
    """
    _FK_FIXES = [
        # Child rows that cannot exist without their parent
        ("workflow_actions",    "instance_id",       "workflow_instances",   "id", "CASCADE"),
        ("report_runs",         "definition_id",      "report_definitions",   "id", "CASCADE"),
        ("webhook_logs",        "webhook_id",         "webhooks",             "id", "CASCADE"),
        ("sla_instances",       "definition_id",      "sla_definitions",      "id", "CASCADE"),
        ("grid_controls",       "audit_id",           "grid_audits",          "id", "CASCADE"),
        ("grid_evidence_items", "control_id",         "grid_controls",        "id", "CASCADE"),
        ("grid_evidence_files", "evidence_item_id",   "grid_evidence_items",  "id", "CASCADE"),
        ("grid_evidence_files", "control_id",         "grid_controls",        "id", "CASCADE"),
        ("aria_controls",       "framework_id",       "aria_frameworks",      "id", "CASCADE"),
        # User-owned records: remove when user is deleted
        ("user_preferences",    "user_id",            "users",                "id", "CASCADE"),
        ("api_keys",            "user_id",            "users",                "id", "CASCADE"),
        # Audit trail references: nullify (don't delete) when user is removed
        ("audit_log",           "user_id",            "users",                "id", "SET NULL"),
        ("task_board",          "assigned_to",        "users",                "id", "SET NULL"),
        ("task_board",          "created_by",         "users",                "id", "SET NULL"),
        ("workflow_instances",  "started_by",         "users",                "id", "SET NULL"),
        ("workflow_actions",    "assigned_to",        "users",                "id", "SET NULL"),
        ("calendar_events",     "assigned_to",        "users",                "id", "SET NULL"),
        ("calendar_events",     "created_by",         "users",                "id", "SET NULL"),
        ("email_reminders",     "recipient_id",       "users",                "id", "SET NULL"),
        ("email_reminders",     "created_by",         "users",                "id", "SET NULL"),
        ("risk_register",       "owner_id",           "users",                "id", "SET NULL"),
        ("risk_register",       "created_by",         "users",                "id", "SET NULL"),
    ]
    import logging as _log
    _logger = _log.getLogger("oneforall.migrations")
    for table, col, ref_table, ref_col, action in _FK_FIXES:
        try:
            rows = conn.execute("""
                SELECT tc.constraint_name, rc.delete_rule
                FROM information_schema.table_constraints tc
                JOIN information_schema.key_column_usage kcu
                    ON tc.constraint_name = kcu.constraint_name
                    AND tc.table_schema = kcu.table_schema
                JOIN information_schema.referential_constraints rc
                    ON tc.constraint_name = rc.constraint_name
                    AND tc.table_schema = rc.constraint_schema
                WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_name = %s
                    AND kcu.column_name = %s
                    AND tc.table_schema = current_schema()
            """, (table, col)).fetchall()
            for row in rows:
                cname, current_rule = row["constraint_name"], row["delete_rule"]
                expected = action.replace(" ", "_")
                if current_rule == expected:
                    continue
                conn.execute(f'ALTER TABLE "{table}" DROP CONSTRAINT IF EXISTS "{cname}"')
                conn.execute(
                    f'ALTER TABLE "{table}" ADD FOREIGN KEY ({col}) '
                    f'REFERENCES "{ref_table}"({ref_col}) ON DELETE {action}'
                )
            conn.commit()
        except Exception as exc:
            try:
                conn.execute("ROLLBACK")
            except Exception:
                pass
            _logger.warning("FK cascade fix skipped for %s.%s: %s", table, col, exc)


def provision_tenant_schema(slug: str) -> None:
    """Create a new tenant schema with all module tables and baseline seed data.

    Only runs on PostgreSQL. Safe to call multiple times (CREATE IF NOT EXISTS).
    slug='public' is the default org and maps to the existing public schema;
    no schema creation is needed for it.
    """
    if not settings.is_postgres():
        return
    if slug == "public":
        return

    safe = re.sub(r"[^a-z0-9_]", "", slug.lower())
    schema_name = f"tenant_{safe}"

    # Use a raw pool connection so we can control search_path manually.
    pool = _get_pg_pool()
    pg_conn = pool.getconn()
    wrapper = _PgConnWrapper(pg_conn)
    if not wrapper._is_alive():
        pool.putconn(pg_conn, close=True)
        pg_conn = pool.getconn()
        wrapper = _PgConnWrapper(pg_conn)
    pg_conn.autocommit = False
    # Provisioning needs full access to public schema tables (users, licenses).
    wrapper.set_rls_bypass()
    conn = wrapper
    try:
        from psycopg2 import sql as psql
        pg_conn.cursor().execute(psql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(psql.Identifier(schema_name)))
        conn.commit()
        pg_conn.cursor().execute(psql.SQL("SET search_path TO {}, public").format(psql.Identifier(schema_name)))
        # Create platform + module tables inside the tenant schema.
        conn.executescript(_PLATFORM_TABLES_PG)
        conn.executescript(_ARIA_TABLES_PG)
        conn.executescript(_GRID_TABLES_PG)
        conn.executescript(_BCM_TABLES_PG)
        conn.executescript(_SENTINEL_TABLES_PG)
        conn.executescript(_ERM_ORM_TABLES_PG)
        conn.commit()
        # Apply column migrations (idempotent — catches column-already-exists errors).
        _run_pg_alters(conn)
        _run_pg_fk_cascades(conn)
        # Seed baseline reference data (frameworks, regulations, etc.).
        _seed_baseline_data(conn)
        conn.commit()
    finally:
        try:
            pg_conn.rollback()
        except Exception:
            pass
        pool.putconn(pg_conn)


def init_db():
    """Create all tables if they don't exist, then run migrations and seed data."""
    _ensure_dir()
    conn = get_db_bypass_rls()
    try:
        if settings.is_postgres():
            conn.executescript(_SHARED_TABLES_PG)
            conn.executescript(_ARIA_TABLES_PG)
            conn.executescript(_GRID_TABLES_PG)
            conn.executescript(_BCM_TABLES_PG)
            conn.executescript(_SENTINEL_TABLES_PG)
            conn.executescript(_ERM_ORM_TABLES_PG)
        else:
            conn.executescript(_SHARED_TABLES)
            conn.executescript(_ARIA_TABLES)
            conn.executescript(_GRID_TABLES)
            conn.executescript(_BCM_TABLES)
            conn.executescript(_SENTINEL_TABLES)
            conn.executescript(_ERM_ORM_TABLES)
        conn.commit()
        if settings.is_postgres():
            _run_pg_alters(conn)
            _run_pg_fk_cascades(conn)
        else:
            _run_sqlite_alters(conn)
        _seed_baseline_data(conn)
        conn.commit()
        if settings.is_postgres():
            from core.rls import apply_rls_policies
            apply_rls_policies(conn)
    finally:
        conn.close()
