#!/usr/bin/env python3
"""
add_secret_key.py - Generates a SECRET_KEY and adds it to /project/.env.

The project-level .env is read by Docker Compose for variable substitution.
Run from /project:
    python3 oneforall/scripts/add_secret_key.py
"""
import os
import secrets

PROJECT_ENV = "/project/.env"

existing = ""
if os.path.exists(PROJECT_ENV):
    existing = open(PROJECT_ENV).read()

lines = [l for l in existing.splitlines() if l and not l.startswith("SECRET_KEY=")]

key = secrets.token_hex(32)
lines.append("SECRET_KEY=" + key)

with open(PROJECT_ENV, "w") as f:
    f.write("\n".join(lines) + "\n")

print("Written SECRET_KEY to", PROJECT_ENV)
print("Now run: docker compose up -d app")
