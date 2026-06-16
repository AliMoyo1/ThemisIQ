#!/usr/bin/env bash
set -euo pipefail

# Load PG password from Docker secret file into PGPASSWORD so psycopg2
# and pg_dump can authenticate without embedding the password in DATABASE_URL.
if [ -f "${PGPASSWORD_FILE:-}" ]; then
    PGPASSWORD=$(cat "$PGPASSWORD_FILE")
    export PGPASSWORD
fi

# Run Alembic schema migrations once, before uvicorn workers spawn.
# Only runs if there are actual migration version files to apply.
if [ -n "${DATABASE_URL:-}" ]; then
    VERSION_COUNT=$(find alembic/versions -name '*.py' ! -name '__init__.py' 2>/dev/null | wc -l)
    if [ "$VERSION_COUNT" -gt 0 ]; then
        echo "[entrypoint] Running Alembic migrations ($VERSION_COUNT version files)..."
        alembic upgrade head
    else
        echo "[entrypoint] No Alembic migration versions found, skipping."
    fi
fi

echo "[entrypoint] Starting uvicorn (workers=${WORKERS:-2})..."
exec uvicorn main:app \
    --host 0.0.0.0 \
    --port 8080 \
    --workers "${WORKERS:-2}"
