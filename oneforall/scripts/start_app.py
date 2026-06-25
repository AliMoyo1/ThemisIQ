#!/usr/bin/env python3
"""
start_app.py - Start the ThemisIQ app with environment loaded from .env files.

Run from /project:
    python3 oneforall/scripts/start_app.py

For background (survives console close):
    nohup python3 oneforall/scripts/start_app.py >> /project/app.log 2>&1 &
"""
import os
import subprocess
import sys

# Load project-level .env (POSTGRES_PASSWORD, SECRET_KEY)
for env_file in ["/project/.env", "oneforall/.env"]:
    if os.path.exists(env_file):
        for line in open(env_file):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, val = line.split("=", 1)
                os.environ.setdefault(key.strip(), val.strip())

db_url = os.environ.get("DATABASE_URL", "(not set)")
has_secret = bool(os.environ.get("SECRET_KEY"))

print("Starting ThemisIQ on port 8080...")
print("DATABASE_URL:", "****" if db_url != "(not set)" else "(not set)")


if not has_secret:
    print("ERROR: SECRET_KEY not found in .env files. Run:")
    print("  python3 oneforall/scripts/add_secret_key.py")
    sys.exit(1)

# Use sys.executable to find the correct Python, then run uvicorn as a module.
# This avoids PATH issues where uvicorn isn't on the system PATH.
os.execv(sys.executable, [
    sys.executable, "-m", "uvicorn",
    "main:app",
    "--host", "0.0.0.0",
    "--port", "8080",
    "--app-dir", "oneforall",
])
