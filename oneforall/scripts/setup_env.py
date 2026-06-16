#!/usr/bin/env python3
"""
setup_env.py - Adds missing SECRET_KEY to oneforall/.env.

Run from /project:
    python3 oneforall/scripts/setup_env.py
"""
import os
import secrets

ENV_FILE = "oneforall/.env"

existing = ""
if os.path.exists(ENV_FILE):
    existing = open(ENV_FILE).read()

lines = [l for l in existing.splitlines() if not l.startswith("SECRET_KEY=")]

key = secrets.token_hex(32)
lines.append("SECRET_KEY=" + key)

with open(ENV_FILE, "w") as f:
    f.write("\n".join(lines) + "\n")

print("SECRET_KEY written to", ENV_FILE)
print("Restart the app to pick it up:")
print("  docker compose restart app")
