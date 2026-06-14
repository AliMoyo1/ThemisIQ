#!/usr/bin/env bash
# lint_sqlite_isms.sh — CI gate for SQLite-specific SQL that won't run on PostgreSQL.
#
# Usage:
#   bash scripts/lint_sqlite_isms.sh          # exits 1 if violations found
#   bash scripts/lint_sqlite_isms.sh --warn   # exits 0 (warnings only, for migration in progress)
#
# Intentional exclusions:
#   database.py     — contains SQLite schema DDL and the helper functions themselves
#   scripts/        — migration/tooling scripts (reference SQLite intentionally)
#   seeds/          — seed data may still use INSERT OR IGNORE (Phase C remnant)
#   core/timeutils.py — has 'datetime('now')' in a docstring comment

set -euo pipefail

WARN_ONLY=0
if [[ "${1:-}" == "--warn" ]]; then
    WARN_ONLY=1
fi

FAIL=0
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# Files to scan: all .py except the intentional exclusions
EXCLUDE_FILES="database.py"
EXCLUDE_DIRS="scripts seeds"

_grep_py() {
    local pattern="$1"
    local label="$2"
    local results
    results=$(
        grep -rn --include="*.py" "$pattern" "$ROOT" 2>/dev/null | \
        grep -v "/$EXCLUDE_FILES:" | \
        grep -v "/scripts/" | \
        grep -v "/seeds/" | \
        grep -v "core/timeutils.py" | \
        grep -v "^Binary" || true
    )
    if [[ -n "$results" ]]; then
        echo "==> FOUND: $label"
        echo "$results"
        echo
        FAIL=1
    fi
}

# ── SQLite date functions ─────────────────────────────────────────────────────
_grep_py "julianday(" "julianday() — use sql_days_between() helper instead"
_grep_py "datetime('now'" "datetime('now') — use CURRENT_TIMESTAMP (no-offset) or sql_now_offset() helper"
_grep_py "date('now'" "date('now') — use CURRENT_DATE (no-offset) or sql_date_offset() helper"

# ── SQLite-only INSERT syntax ─────────────────────────────────────────────────
_grep_py "INSERT OR IGNORE" "INSERT OR IGNORE — use INSERT ... ON CONFLICT DO NOTHING"
_grep_py "INSERT OR REPLACE" "INSERT OR REPLACE — use INSERT ... ON CONFLICT DO UPDATE SET"

# ── SQLite cursor attribute ───────────────────────────────────────────────────
# Allow it in database.py (the helper itself) but not in app code
_grep_py '\.lastrowid' ".lastrowid — use insert_returning_id() or RETURNING id clause"

# ── SQLite AUTOINCREMENT ──────────────────────────────────────────────────────
# AUTOINCREMENT is valid in database.py schema strings; flag in app code only
_grep_py "AUTOINCREMENT" "AUTOINCREMENT in app code — should only appear in database.py schema strings"

# ── Summary ──────────────────────────────────────────────────────────────────
if [[ $FAIL -eq 0 ]]; then
    echo "lint_sqlite_isms: PASS — no SQLite-isms found in app code"
    exit 0
fi

if [[ $WARN_ONLY -eq 1 ]]; then
    echo "lint_sqlite_isms: WARN — SQLite-isms found (--warn mode, not failing)"
    exit 0
fi

echo "lint_sqlite_isms: FAIL — fix the patterns above before PostgreSQL cutover"
exit 1
