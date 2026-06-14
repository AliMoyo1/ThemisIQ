"""
Phase F helper — inventory all TEXT columns that store timestamps or dates.

Reads the live SQLite DB, queries sqlite_master for column info, and writes
.migration/timestamp_columns.json so Phase H (Alembic column-type migration)
knows exactly which columns to ALTER to TIMESTAMPTZ / DATE.

Usage:
    python scripts/inventory_timestamp_columns.py
    python scripts/inventory_timestamp_columns.py --db path/to/other.db

Output: .migration/timestamp_columns.json
"""
import sys
import sqlite3
import json
import re
from pathlib import Path

# Patterns that mark a column as holding a timestamp or date value.
_TIMESTAMP_NAMES = re.compile(
    r'(_at|_time|_on|last_login|last_reviewed|activated_at|locked_at|signed_at)$',
    re.IGNORECASE,
)
_DATE_NAMES = re.compile(
    r'(_date|due_date|start_date|end_date|review_date|reminder_date|expiry_date|'
    r'notify_deadline|response_deadline)$',
    re.IGNORECASE,
)

# Also flag columns whose DDL default is datetime('now') or date('now').
_DATETIME_DEFAULT = re.compile(r"datetime\s*\(\s*'now'\s*\)", re.IGNORECASE)
_DATE_DEFAULT     = re.compile(r"date\s*\(\s*'now'\s*\)", re.IGNORECASE)


def _db_path() -> str:
    if len(sys.argv) >= 3 and sys.argv[1] == "--db":
        return sys.argv[2]
    # Resolve relative to oneforall/ directory
    here = Path(__file__).parent.parent
    from config import settings  # type: ignore
    db = settings.DB_PATH
    return str((here / db).resolve() if not Path(db).is_absolute() else Path(db))


def main():
    db_file = _db_path()
    conn = sqlite3.connect(db_file)
    conn.row_factory = sqlite3.Row

    tables = [
        row["name"]
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        ).fetchall()
    ]

    results = {"timestamptz": [], "date": []}

    for tbl in tables:
        for col in conn.execute(f"PRAGMA table_info({tbl})").fetchall():
            col_name = col["name"]
            col_type = (col["type"] or "").upper()
            dflt = col["dflt_value"] or ""

            if col_type != "TEXT":
                continue  # only TEXT columns need potential type changes

            entry = {"table": tbl, "column": col_name, "default": dflt or None}

            if _DATETIME_DEFAULT.search(dflt) or _TIMESTAMP_NAMES.search(col_name):
                results["timestamptz"].append(entry)
            elif _DATE_DEFAULT.search(dflt) or _DATE_NAMES.search(col_name):
                results["date"].append(entry)

    conn.close()

    out_dir = Path(__file__).parent.parent / ".migration"
    out_dir.mkdir(exist_ok=True)
    out_file = out_dir / "timestamp_columns.json"
    out_file.write_text(json.dumps(results, indent=2))

    ts_count = len(results["timestamptz"])
    dt_count = len(results["date"])
    print(f"Wrote {out_file}")
    print(f"  TIMESTAMPTZ candidates : {ts_count}")
    print(f"  DATE candidates        : {dt_count}")
    print(f"  Total                  : {ts_count + dt_count}")


if __name__ == "__main__":
    main()
