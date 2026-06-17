#!/usr/bin/env python3
"""One-time Nginx setup for themisiq.net and app.themisiq.net.

Run on the VPS as root:
    python3 /project/setup_nginx.py
"""
import os
import shutil
import subprocess
import sys

NGINX_CONF = """server {
    listen 80;
    server_name themisiq.net www.themisiq.net;
    root /var/www/themisiq;
    index index.html;
    location / {
        try_files $uri $uri/ =404;
    }
}

server {
    listen 80;
    server_name app.themisiq.net;
    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
"""


def run(cmd):
    print("  Running:", cmd)
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.stdout.strip():
        print(result.stdout.strip())
    if result.stderr.strip():
        print(result.stderr.strip())
    return result.returncode


def main():
    repo_root = os.path.dirname(os.path.abspath(__file__))

    print("[1] Installing Nginx (skipped if already present)...")
    if shutil.which("nginx") is None:
        rc = run("apt install nginx -y")
        if rc != 0:
            print("ERROR: apt install nginx failed.")
            sys.exit(1)
    else:
        print("    Nginx already installed.")

    print("[2] Writing Nginx config...")
    conf_path = "/etc/nginx/sites-available/themisiq"
    with open(conf_path, "w") as fh:
        fh.write(NGINX_CONF)
    print("    Written:", conf_path)

    print("[3] Enabling site...")
    link = "/etc/nginx/sites-enabled/themisiq"
    if os.path.lexists(link):
        os.remove(link)
    os.symlink(conf_path, link)
    print("    Symlink created:", link)

    print("[4] Copying landing page folder (HTML + all images)...")
    src_dir = os.path.join(repo_root, "landing_page")
    web_root = "/var/www/themisiq"
    os.makedirs(web_root, exist_ok=True)
    for fname in os.listdir(src_dir):
        src = os.path.join(src_dir, fname)
        if os.path.isfile(src) and not fname.endswith(".docx"):
            shutil.copy2(src, os.path.join(web_root, fname))
            print("    Copied:", fname)

    print("[5] Testing Nginx config...")
    rc = run("nginx -t")
    if rc != 0:
        print("ERROR: Nginx config test failed. Fix the error above and re-run.")
        sys.exit(1)

    print("[6] Restarting Nginx...")
    run("systemctl restart nginx")

    print()
    print("Done.")
    print("  themisiq.net     -> landing page at /var/www/themisiq/index.html")
    print("  app.themisiq.net -> proxy to localhost:8080")


if __name__ == "__main__":
    if os.geteuid() != 0:
        print("This script must be run as root.")
        sys.exit(1)
    main()
