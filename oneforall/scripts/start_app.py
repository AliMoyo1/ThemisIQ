#!/usr/bin/env python3
"""
start_app.py - Start the ThemisIQ app with environment loaded from oneforall/.env.

Run from /project:
    python3 oneforall/scripts/start_app.py
"""
import os
import subprocess
import sys

ENV_FILE = "oneforall/.env"

if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip())

print("Starting ThemisIQ on port 8080...")
print("DATABASE_URL:", os.environ.get("DATABASE_URL", "(not set)"))
print("SECRET_KEY set:", bool(os.environ.get("SECRET_KEY")))

os.execvp("uvicorn", [
    "uvicorn", "main:app",
    "--host", "0.0.0.0",
    "--port", "8080",
    "--app-dir", "oneforall",
])
