"""The plan 23 pilot and search speed scripts keep working (each runs on its own throwaway SQLite file)."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _run(*args):
    env = {k: v for k, v in os.environ.items()
           if k not in ("DATABASE_URL", "PILOT_DATABASE_URL", "SPEED_DATABASE_URL")}
    return subprocess.run([sys.executable, *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=600)


def test_the_group_pilot_walks_every_step():
    done = _run("scripts/pilot_group_oversight.py")
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    assert "21 of 21 steps passed" in done.stdout


def test_the_search_speed_script_checks_answers_and_reports_percentiles():
    done = _run("scripts/measure_vault_search.py", "--sizes", "30", "--runs", "3")
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    assert "| 30 | Known item by file text | 1 |" in done.stdout
