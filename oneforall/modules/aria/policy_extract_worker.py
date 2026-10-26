"""Small subprocess entry point for bounded, local policy text extraction.

The parent passes only a server-created private file path. This process does
not receive service credentials or a database connection. It writes one JSON
result to stdout; parser diagnostics stay out of client responses.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) != 4:
        return 2
    source, extension, filename = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
    if extension not in (".docx", ".pdf") or not source.is_file():
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from modules.aria.policy_parser import extract

    if source.stat().st_size > 25 * 1024 * 1024:
        return 2
    result = extract(source.read_bytes(), extension, filename)
    sys.stdout.write(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
