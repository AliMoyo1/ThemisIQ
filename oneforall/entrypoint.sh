#!/usr/bin/env bash
set -euo pipefail

# Load PG password from Docker secret file into PGPASSWORD so psycopg2
# and pg_dump can authenticate without embedding the password in DATABASE_URL.
if [ -f "${PGPASSWORD_FILE:-}" ]; then
    PGPASSWORD=$(cat "$PGPASSWORD_FILE")
    export PGPASSWORD
fi

# Run Alembic schema migrations once, before uvicorn workers spawn.
# This avoids the race condition where multiple workers each try to migrate.
if [ -n "${DATABASE_URL:-}" ]; then
    echo "[entrypoint] Running Alembic migrations..."
    alembic upgrade head
fi

echo "[entrypoint] Starting uvicorn (workers=${WORKERS:-2})..."
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port 8080 \
    --workers "${WORKERS:-2}"
