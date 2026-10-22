#!/usr/bin/env bash
# Restore the full ThemisIQ proxy from a pinned source commit while preserving
# the installed public landing-page headers. Run on the VPS from /project.
set -Eeuo pipefail

cd /project
source_commit=05edcc77c5cedc5bb523adae1edab5b2bce79ea5
source_path=oneforall/scripts/nginx/themisiq

sudo git -c safe.directory=/project fetch origin codex/security-finish-2026-10-21
test "$(sudo git -c safe.directory=/project rev-parse FETCH_HEAD)" = "$source_commit"

candidate=$(mktemp /tmp/themisiq-nginx.XXXXXX)
trap 'sudo rm -f -- "$candidate"' EXIT
sudo git -c safe.directory=/project show "$source_commit:$source_path" > "$candidate"
# /tmp is sticky and root may not reopen a user-owned file for writing.
# Transfer ownership before the privileged Python rewrite below.
sudo chown root:root -- "$candidate"

target=$(readlink -f /etc/nginx/sites-enabled/themisiq)
case "$target" in
    /etc/nginx/sites-available/*|/etc/nginx/sites-enabled/*) ;;
    *) echo 'Unexpected nginx site target; no change made' >&2; exit 1 ;;
esac

# Only read header names and lines in the landing server. Do not print them.
sudo python3 - "$candidate" "$target" <<'PY'
from pathlib import Path
import sys

candidate, installed = (Path(arg) for arg in sys.argv[1:])
source = candidate.read_text()
current = installed.read_text()
landing_start = current.index("server_name themisiq.net www.themisiq.net;")
landing_end = current.index("location / {", landing_start)
headers = [line for line in current[landing_start:landing_end].splitlines()
           if line.strip().startswith("add_header ")]
required = {"X-Content-Type-Options", "Referrer-Policy", "X-Frame-Options",
            "Permissions-Policy", "Content-Security-Policy"}
found = {line.strip().split()[1] for line in headers}
if found != required or len(headers) != len(required):
    raise SystemExit("Landing header set changed; no nginx change made")
anchor = "    index index.html;\n"
if source.count(anchor) != 1 or source.count("server_name monitor.themisiq.net;") != 1:
    raise SystemExit("Pinned nginx source was unexpected; no nginx change made")
source = source.replace(anchor, anchor + "\n".join(headers) + "\n", 1)
candidate.write_text(source)
PY

backup_dir=/root/themisiq-nginx-backups
sudo install -d -m 0700 -- "$backup_dir"
backup="$backup_dir/themisiq-pre-security-$(date -u +%Y%m%dT%H%M%SZ)"
sudo cp -a -- "$target" "$backup"
restore() {
    sudo cp -a -- "$backup" "$target"
    sudo nginx -t
    sudo systemctl reload nginx
}

if ! sudo install -m 0644 -- "$candidate" "$target"; then
    echo 'Candidate install failed; restoring nginx site' >&2
    restore
    exit 1
fi
if ! sudo nginx -t; then
    echo 'Candidate syntax failed; restoring nginx site' >&2
    restore
    exit 1
fi
if ! sudo systemctl reload nginx; then
    echo 'Nginx reload failed; restoring nginx site' >&2
    restore
    exit 1
fi

if ! sudo cmp -s -- "$candidate" "$target"; then
    echo 'Installed nginx site differs from candidate; restoring site' >&2
    restore
    exit 1
fi

http_code() {
    local code
    if code=$(curl -sS --max-time 4 -o /dev/null -w '%{http_code}' -H "Host: $1" "http://127.0.0.1$2" 2>/dev/null); then
        printf '%s' "$code"
    else
        printf '000'
    fi
}
routes_ok() {
    test "$(http_code app.themisiq.net /health)" = 200 &&
    test "$(http_code monitor.themisiq.net /health)" = 200 &&
    test "$(http_code monitor.themisiq.net /)" = 404 &&
    test "$(http_code themisiq.net /)" = 200
}

# A successful reload signal can return before nginx's new workers serve requests.
ready=0
for attempt in $(seq 1 20); do
    if routes_ok; then ready=1; break; fi
    sleep 1
done
if (( ready == 0 )); then
    printf 'Route codes: app_health=%s monitor_health=%s monitor_root=%s landing_root=%s\n' \
        "$(http_code app.themisiq.net /health)" \
        "$(http_code monitor.themisiq.net /health)" \
        "$(http_code monitor.themisiq.net /)" \
        "$(http_code themisiq.net /)" >&2
    echo 'Nginx route probe failed; restoring site' >&2
    restore
    exit 1
fi
printf 'nginx_site=updated\nbackup=%s\n' "$backup"
