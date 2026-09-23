# ThemisIQ VPS deployment and production acceptance

This runbook applies only to the ThemisIQ checkout at `/project` on the
Hetzner Ubuntu VPS. The web application lives at `/project/oneforall`, the
systemd service is `themisiq-app.service`, and PostgreSQL listens on loopback
port `5434` with database `themisiq`.

Do not paste passwords, API keys, database URLs, environment-file contents, or
raw service definitions into tickets or chat. Commands below display key names
and non-secret safety flags only.

## Release invariants

Do not restart production unless every invariant below is true:

1. A named release commit exists on the remote repository. Replace
   `<RELEASE_SHA>` below with that full commit SHA; never deploy an unspecified
   branch tip.
2. The tracked production worktree is clean.
3. A new PostgreSQL custom-format dump has completed a full isolated restore,
   has at least one application table, has zero invalid indexes, and has a
   SHA-256 sidecar.
4. Key-based SSH as `themisadmin` works and `sudo id -u` prints `0`.
5. The current `/health` and `/ready` probes pass before the change.
6. ARIA policy authoring remains disabled and its organization allowlist is
   empty. Enabling a pilot is a separate change.

The production service intentionally runs one Uvicorn process. The application
starts in-process schedulers during startup; multiple workers would execute
reminders, escalations, retention jobs, and queue drains more than once.

Production configuration comes exclusively from the root-owned
`/etc/themisiq/themisiq.env`. The unit sets
`PYTHON_DOTENV_DISABLED=1`, so the unprivileged `themisiq` process never tries
to read either legacy `/project/.env` file. Keep those legacy files mode 0600;
do not weaken their permissions to make the service start.

The host cron backup at `/project/backup_db.sh` is authoritative. Therefore
`GRID_BACKUP_JOBS_ENABLED=false` prevents the web process from running a
second backup schedule and from attempting the Docker-dependent legacy restore
drill.

## 1. Capture the pre-change record

Run from the `themisadmin` SSH session:

```bash
cd /project
previous_sha="$(sudo git -c safe.directory=/project rev-parse HEAD)"
echo "previous_sha=${previous_sha}"

sudo git -c safe.directory=/project status \
  --porcelain --untracked-files=no
systemctl is-active themisiq-app.service
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/ready
pg_isready -h 127.0.0.1 -p 5434
```

Stop if tracked status prints any path or if any health command fails.

Confirm the latest verified backup and checksum without deleting older files:

```bash
sudo find /project/backups -maxdepth 1 -type f \
  -name 'themisiq_*_verified.dump' \
  -printf '%T@ %p\n' | sort -n | tail -1
sudo find /project/backups -maxdepth 1 -type f \
  -name 'themisiq_*_verified.dump.sha256' \
  -printf '%T@ %p\n' | sort -n | tail -1
```

## 2. Prevent the retired Docker database from returning

The production database is PostgreSQL 18 on host port `5434`. The stopped
`project-db-1` PostgreSQL 16 container is not the live database. Preserve its
volume until a separate retention decision, but prevent automatic restart:

```bash
sudo docker update --restart=no project-db-1
sudo docker inspect project-db-1 \
  --format 'status={{.State.Status}} restart={{.HostConfig.RestartPolicy.Name}}'
```

Expected: `status=exited restart=no`. Do not remove the container or volume in
this deployment.

## 3. Fetch and pin the release

```bash
cd /project
sudo git -c safe.directory=/project fetch --all --prune
sudo git -c safe.directory=/project cat-file -e '<RELEASE_SHA>^{commit}'
sudo git -c safe.directory=/project merge --ff-only '<RELEASE_SHA>'

actual_sha="$(sudo git -c safe.directory=/project rev-parse HEAD)"
test "${actual_sha}" = '<RELEASE_SHA>'
echo "release_sha=${actual_sha}"
```

Stop if the merge is not a fast-forward or the final SHA differs. Do not use
`git reset --hard` and do not delete untracked production files.

This release does not require a production dependency installation unless
`oneforall/requirements.txt` changed in the selected commit range. Check it
explicitly:

```bash
sudo git -c safe.directory=/project diff --name-only \
  "${previous_sha}" '<RELEASE_SHA>' -- oneforall/requirements.txt
```

If that command prints the requirements file, stop and perform a separately
reviewed virtual-environment update before restarting the service.

## 4. Capture the running environment securely

The capture reads the already-running service process, keeps configured keys,
forces production-safe flags, and writes values only to the root-owned
`/etc/themisiq/themisiq.env`. It prints key names, never values.

```bash
cd /project
sudo python3 oneforall/scripts/deploy.py --capture-running-env
sudo stat -c '%a %U:%G %n' /etc/themisiq /etc/themisiq/themisiq.env

sudo grep -E \
  '^(DEBUG|HOST|PORT|GRID_BACKUP_JOBS_ENABLED|ARIA_POLICY_AUTHORING_ENABLED|ARIA_POLICY_AUTHORING_ORG_IDS)=' \
  /etc/themisiq/themisiq.env
```

Expected modes are `700 root:root` for the directory and `600 root:root` for
the file. Expected flags are loopback host, port 8080, backups disabled inside
the app, authoring disabled, and an empty authoring allowlist.

Run the read-only preflight:

```bash
sudo python3 oneforall/scripts/deploy.py
```

Stop on any error.

### Controlled ARIA policy-authoring pilot

The normal capture, preflight and apply commands above deliberately keep ARIA
policy authoring disabled. Do not enable it until the readiness and explicit
acceptance steps in `oneforall/docs/aria-policy-authoring.md` sections 9-10 are
complete for the selected organization.

The enabled preflight additionally requires a fresh preview-worker heartbeat
and inspects the live container against the isolation contract. Starting an
unlabeled worker, a mutable image tag, or a worker with extra mounts, ports,
secrets or network access does not satisfy this gate.

For an authorized pilot, first configure the root-owned environment with a
non-empty, organization-specific allow-list. Preflight and apply then require
both of the following options every time:

```bash
sudo python3 oneforall/scripts/deploy.py \
  --authorize-aria-policy-authoring-org-ids '<ORG_ID[,ORG_ID...]>' \
  --accept-aria-policy-authoring-known-limitations

sudo python3 oneforall/scripts/deploy.py --apply --restart \
  --authorize-aria-policy-authoring-org-ids '<ORG_ID[,ORG_ID...]>' \
  --accept-aria-policy-authoring-known-limitations
```

The supplied IDs must exactly match `ARIA_POLICY_AUTHORING_ORG_IDS`. These
options do not modify the environment, do not bypass tenant authorization,
and cannot be used with environment capture or secret scrubbing. Omitting
either option keeps deployment fail-closed. A global administrator with no
organization context is still denied; use a scoped account in the pilot
organization for acceptance testing.

## 5. Apply the hardened service

This is the controlled restart point:

```bash
sudo python3 oneforall/scripts/deploy.py --apply --restart
```

The command archives the old unit and drop-ins under
`/root/themisiq-rollbacks`, installs the non-root loopback-only unit, restarts
the service, first imports the dependencies and application configuration as
the `themisiq` account, and checks `/health` and `/ready`. If service
verification fails, it restores the previous unit configuration and attempts
one restart. It does not roll back the Git checkout; use section 9 if the old
unit cannot run the new code.

## 6. Verify the live runtime

```bash
systemctl is-active themisiq-app.service
systemctl is-enabled themisiq-app.service
systemctl show themisiq-app.service \
  -p User -p Group -p MainPID -p NRestarts -p NoNewPrivileges \
  --no-pager

sudo ss -ltnp | grep -E ':(5434|8080)[[:space:]]'
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/ready

sudo journalctl -u themisiq-app.service \
  --since '-10 minutes' --no-pager \
  | grep -Ei 'error|exception|traceback|failed' || true
```

Required results:

- service active and enabled;
- `User=themisiq`, `Group=themisiq`, and `NoNewPrivileges=yes`;
- application listener only on `127.0.0.1:8080`;
- PostgreSQL only on loopback port `5434`;
- both probes return HTTP 200;
- no startup traceback or repeated restart.

Verify from a separate machine as well:

```bash
curl -fsS https://themisiq.net/health
curl -fsSI https://themisiq.net/login
```

Use the production hostname actually configured in the reverse proxy if it is
different. Confirm TLS validity, the login response, and security headers.

## 7. Make the verified backup implementation durable

Install the repository copy over the cron target and run it once. The script
publishes a backup only after a complete temporary restore succeeds.

```bash
sudo install -o root -g root -m 700 \
  /project/oneforall/scripts/production_backup.sh \
  /project/backup_db.sh
sudo bash -n /project/backup_db.sh
sudo timeout --signal=TERM --kill-after=30s 15m /project/backup_db.sh
```

Expected output includes `backup=PASS`, a positive table count, and
`invalid_indexes=0`. Confirm root cron still runs it at 02:00 and all backup
files remain mode 0600.

## 8. Remove duplicate legacy secrets

Only after section 6 passes:

```bash
sudo python3 /project/oneforall/scripts/deploy.py --scrub-legacy-secrets
sudo stat -c '%a %U:%G %n' /project/.env /project/oneforall/.env
```

This removes secret-bearing assignments from the two legacy files while the
authoritative values remain in `/etc/themisiq/themisiq.env`. It does not print
secret values. Re-run both health probes afterward.

Do not rotate the database password or application secret in the same change
window. Secret rotation is a separate procedure with its own rollback point.

## 9. Rollback

If the deployment command reports failure, first read its error and check
whether the restored unit is healthy:

```bash
systemctl status themisiq-app.service --no-pager
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/ready
```

If the new code itself prevents recovery, return the checkout to the exact SHA
recorded in section 1 without discarding files:

```bash
cd /project
sudo git -c safe.directory=/project switch --detach "${previous_sha}"
sudo systemctl restart themisiq-app.service
curl -fsS http://127.0.0.1:8080/health
curl -fsS http://127.0.0.1:8080/ready
```

Do not scrub legacy secrets until the release is stable. Do not delete the
verified backup, rollback unit, old Docker volume, or previous Git commit during
the acceptance window.

## 10. Deferred gates

These are not implied by a successful application restart:

- Offsite backup upload and a restore initiated from the offsite copy.
- Operating-system package upgrade and required reboot.
- ARIA preview worker deployment and digest pinning.
- Per-organization ARIA authoring pilot enablement.
- Removal of the retired Docker database and its volume.
- Cleanup of unrelated ODIN containers or Nginx configuration; that belongs to
  the separate ODIN project and must not be changed under this runbook.
