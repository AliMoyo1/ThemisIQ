"""Socket-activated parser entry point, run by systemd as an isolated user."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from modules.aria.policy_extract_protocol import serve_once


if __name__ == "__main__":
    raise SystemExit(serve_once(sys.stdin.buffer, sys.stdout.buffer))
