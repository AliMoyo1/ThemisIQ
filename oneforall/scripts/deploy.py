#!/usr/bin/env python3
"""
deploy.py - Complete deployment setup for ThemisIQ on the VPS.

Does everything needed to get the app running on production PostgreSQL:
  1. Installs Python dependencies (pip install -r requirements.txt)
  2. Ensures SECRET_KEY exists in /project/.env
  3. Verifies PostgreSQL is reachable on localhost:5432
  4. Writes a systemd service file for the app
  5. Starts (or restarts) the service

Run from /project:
    python3 oneforall/scripts/deploy.py

After this, the app runs as a systemd service that survives reboots and
console disconnects. Manage it with:
    systemctl status themisiq-app
    systemctl restart themisiq-app
    journalctl -u themisiq-app -f
"""
import os
import secrets
import subprocess
import sys
import time

PROJECT_DIR  = "/project"
ENV_FILE     = "/project/.env"
APP_ENV_FILE = "/project/oneforall/.env"
SECRETS_FILE = "/project/secrets/pg_password.txt"
SERVICE_FILE = "/etc/systemd/system/themisiq-app.service"
REQUIREMENTS = "/project/oneforall/requirements.txt"

def run(cmd, check=True):
    print(f"  $ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(f"    {result.stdout.strip()}")
    if result.returncode != 0 and check:
        print(f"    ERROR: {result.stderr.strip()}")
        sys.exit(1)
    return result


# ── Step 1: Check Python dependencies ────────────────────────────────────────

print("=" * 60)
print("Step 1: Checking Python dependencies...")
print("=" * 60)

REQUIRED_IMPORTS = [
    ("fastapi", "fastapi"),
    ("uvicorn", "uvicorn"),
    ("psycopg2", "psycopg2-binary"),
    ("dotenv", "python-dotenv"),
    ("jinja2", "jinja2"),
    ("multipart", "python-multipart"),
    ("bcrypt", "bcrypt"),
    ("docx", "python-docx"),
    ("apscheduler", "apscheduler"),
    ("alembic", "alembic"),
    ("itsdangerous", "itsdangerous"),
    ("httpx", "httpx"),
    ("aiofiles", "aiofiles"),
    ("openpyxl", "openpyxl"),
    ("reportlab", "reportlab"),
]

missing = []
for module_name, pip_name in REQUIRED_IMPORTS:
    try:
        __import__(module_name)
        print(f"  {module_name}: OK")
    except ImportError:
        missing.append(pip_name)
        print(f"  {module_name}: MISSING")

if missing:
    print(f"\n  Installing missing packages: {', '.join(missing)}")
    result = run(
        f"{sys.executable} -m pip install {' '.join(missing)} -q --break-system-packages",
        check=False,
    )
    if result.returncode != 0:
        print("\n  pip install failed. Install build dependencies first:")
        print("    apt-get install -y libpq-dev python3-dev")
        print("  Then re-run this script.")
        sys.exit(1)
else:
    print("  All dependencies present.")
print()


# ── Step 2: Ensure secrets and env vars ──────────────────────────────────────

print("=" * 60)
print("Step 2: Checking environment variables...")
print("=" * 60)

# Read existing project .env
env_vars = {}
if os.path.exists(ENV_FILE):
    for line in open(ENV_FILE):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env_vars[k.strip()] = v.strip()

# Ensure POSTGRES_PASSWORD
if "POSTGRES_PASSWORD" not in env_vars:
    if os.path.exists(SECRETS_FILE):
        pw = open(SECRETS_FILE).read().strip()
        env_vars["POSTGRES_PASSWORD"] = pw
        print("  Loaded POSTGRES_PASSWORD from secrets file.")
    else:
        print("  ERROR: No POSTGRES_PASSWORD in .env and no secrets file found.")
        print(f"  Create {SECRETS_FILE} first.")
        sys.exit(1)

# Ensure SECRET_KEY
if "SECRET_KEY" not in env_vars:
    env_vars["SECRET_KEY"] = secrets.token_hex(32)
    print("  Generated new SECRET_KEY.")

# Write project .env
with open(ENV_FILE, "w") as f:
    for k, v in env_vars.items():
        f.write(f"{k}={v}\n")
print(f"  Saved {ENV_FILE} ({len(env_vars)} vars)")

# Also ensure oneforall/.env has DATABASE_URL and SECRET_KEY
app_vars = {}
if os.path.exists(APP_ENV_FILE):
    for line in open(APP_ENV_FILE):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            app_vars[k.strip()] = v.strip()

pw = env_vars["POSTGRES_PASSWORD"]
db_url = f"postgresql://themisiq:{pw}@localhost:5432/themisiq"
app_vars["DATABASE_URL"] = db_url
app_vars["SECRET_KEY"] = env_vars["SECRET_KEY"]

with open(APP_ENV_FILE, "w") as f:
    for k, v in app_vars.items():
        f.write(f"{k}={v}\n")
print(f"  Saved {APP_ENV_FILE} ({len(app_vars)} vars)")
print()


# ── Step 3: Verify PostgreSQL is reachable ───────────────────────────────────

print("=" * 60)
print("Step 3: Verifying PostgreSQL connection...")
print("=" * 60)

try:
    import psycopg2
    conn = psycopg2.connect(db_url)
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM pg_tables WHERE schemaname = 'public'")
        table_count = cur.fetchone()[0]
    conn.close()
    print(f"  Connected. {table_count} tables in public schema.")
    if table_count == 0:
        print("  WARNING: No tables found. Run cutover.py first:")
        print("    python3 oneforall/scripts/cutover.py")
        sys.exit(1)
except Exception as e:
    print(f"  ERROR: Cannot connect to PostgreSQL: {e}")
    print("  Is the db container running? Check: docker compose ps")
    sys.exit(1)
print()


# ── Step 4: Write systemd service ────────────────────────────────────────────

print("=" * 60)
print("Step 4: Writing systemd service...")
print("=" * 60)

# Build environment lines for the service from both .env files
all_env = {}
all_env.update(app_vars)
all_env.update(env_vars)

env_lines = "\n".join(f'Environment="{k}={v}"' for k, v in all_env.items())

service_content = f"""[Unit]
Description=ThemisIQ Web Application
After=docker.service network.target
Requires=docker.service

[Service]
Type=simple
WorkingDirectory={PROJECT_DIR}
{env_lines}
ExecStart={sys.executable} -m uvicorn main:app --host 0.0.0.0 --port 8080 --app-dir oneforall --workers 2
StandardOutput=append:/project/app.log
StandardError=append:/project/app.log
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
"""

with open(SERVICE_FILE, "w") as f:
    f.write(service_content)
print(f"  Written: {SERVICE_FILE}")
print()


# ── Step 5: Start the service ────────────────────────────────────────────────

print("=" * 60)
print("Step 5: Starting ThemisIQ app service...")
print("=" * 60)

run("systemctl daemon-reload")
run("systemctl enable themisiq-app")
run("systemctl restart themisiq-app")

print("  Waiting 5 seconds for startup...")
time.sleep(5)

result = run("systemctl is-active themisiq-app", check=False)
status = result.stdout.strip()

if status == "active":
    print(f"  Service is ACTIVE.")
else:
    print(f"  Service status: {status}")
    print("  Check logs: tail -50 /project/app.log")
    sys.exit(1)

# Test health endpoint
print("  Testing health endpoint...")
time.sleep(2)
health = run("curl -fsS http://localhost:8080/health 2>&1", check=False)
if health.returncode == 0:
    print(f"  /health: {health.stdout.strip()}")
else:
    print("  /health not responding yet. Give it a few more seconds, then check:")
    print("    curl http://localhost:8080/health")
    print("    tail -50 /project/app.log")

print()
print("=" * 60)
print("Deployment complete.")
print()
print("Manage the app:")
print("  systemctl status themisiq-app")
print("  systemctl restart themisiq-app")
print("  tail -50 /project/app.log")
print("=" * 60)
