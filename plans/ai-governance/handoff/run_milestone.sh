#!/bin/bash
# The three full lanes of a milestone, one after the other (one pytest session at a time).
#
#   AIGOV_TEST_DATABASE_URL   a throwaway PostgreSQL whose database name starts with themisiq_test_
#                             (the recipe is in the memory file reference_test_environment.md; the guard also needs
#                             THEMISIQ_ALLOW_DESTRUCTIVE_PG_TESTS=1, set below). Never point it at a real database.
#   LANE_OUT                  where the three output files go (default: ~/aigov-lanes)
#
# Run from anywhere:  bash plans/ai-governance/handoff/run_milestone.sh
# Each output file ends with a line "exit: <code>". Wait for it with a background until-grep loop, because a foreground
# sleep is blocked in this environment.
set -u
: "${AIGOV_TEST_DATABASE_URL:?set AIGOV_TEST_DATABASE_URL to a throwaway themisiq_test_* database}"
S="${LANE_OUT:-$HOME/aigov-lanes}"
mkdir -p "$S"
HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE/../../../oneforall"
PY="../.venv/Scripts/python.exe"
rm -f "$S/m_backend.txt" "$S/m_pg.txt" "$S/m_ui.txt"
env -u TEST_DATABASE_URL $PY -m pytest -q -p no:warnings -o addopts="--tb=short" --ignore=tests/ui > "$S/m_backend.txt" 2>&1
echo "exit: $?" >> "$S/m_backend.txt"
THEMISIQ_ALLOW_DESTRUCTIVE_PG_TESTS=1 TEST_DATABASE_URL="$AIGOV_TEST_DATABASE_URL" $PY -m pytest -q -p no:warnings -o addopts="--tb=short" tests/test_postgres_init.py > "$S/m_pg.txt" 2>&1
echo "exit: $?" >> "$S/m_pg.txt"
env -u TEST_DATABASE_URL $PY -m pytest -q -p no:warnings -o addopts="--tb=short" tests/ui > "$S/m_ui.txt" 2>&1
echo "exit: $?" >> "$S/m_ui.txt"
