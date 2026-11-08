# Policy extraction worker: VPS install, 2026-11-09 09:00 CAT

Session booked by the owner in chat on 2026-11-08. Source of truth for the units and their release order: [policy-extract-service.md](../oneforall/docs/policy-extract-service.md). This file turns that order into single commands for the Hetzner console. Each step is one command; type them one at a time as root.

## Why it must happen before the release

After PR 46 is deployed, ARIA policy import on Linux sends every uploaded DOCX or PDF to this worker. If the worker is missing, the import returns 503 and parses nothing in the app. So the units go in first, then the code. The old app ignores the socket, so installing it early is safe.

## Before 09:00

- PR 46 is merged on GitHub (owner step). The steps below read the unit files from `origin/master`. To install before the merge, use `origin/codex/finish-assurance-security-2026-11-05` in steps 3 and 4 instead.
- A database backup is taken as for any release.

## Install the units (no app restart yet)

1. Fetch the release commit without switching the running code:

```bash
git -C /project fetch origin
```

2. Confirm the commit is the PR 46 merge:

```bash
git -C /project log -1 --oneline origin/master
```

3. Install the socket unit from that commit:

```bash
git -C /project show origin/master:oneforall/scripts/systemd/themisiq-policy-extract.socket > /etc/systemd/system/themisiq-policy-extract.socket
```

4. Install the per-request service unit from that commit:

```bash
git -C /project show origin/master:oneforall/scripts/systemd/themisiq-policy-extract@.service > /etc/systemd/system/themisiq-policy-extract@.service
```

5. Set the socket unit's mode:

```bash
chmod 0644 /etc/systemd/system/themisiq-policy-extract.socket
```

6. Set the service unit's mode:

```bash
chmod 0644 /etc/systemd/system/themisiq-policy-extract@.service
```

7. Reload systemd:

```bash
systemctl daemon-reload
```

8. Enable and start the socket:

```bash
systemctl enable --now themisiq-policy-extract.socket
```

9. Check it is active and listening:

```bash
systemctl status themisiq-policy-extract.socket --no-pager
```

10. Check owner, mode and type. Expected output: `themisiq 600 socket`

```bash
stat -c '%U %a %F' /run/themisiq-policy-extract.sock
```

11. Check the memory headroom. The socket accepts at most 4 parses at once and each may use up to 1 GB:

```bash
free -m
```

If `git -C /project` reports "dubious ownership", the checkout belongs to another user. Stop there and we will run the steps as that user rather than change git's safety setting.

## Switch the code

12. Update `/project` to the release commit the way the normal release does, then run the read-only preflight. It refuses if the installed units differ from the checkout, if a reload is pending, or if the socket has the wrong owner or mode:

```bash
/project/oneforall/.venv/bin/python /project/oneforall/scripts/deploy.py
```

If ARIA policy authoring is enabled in `/etc/themisiq/themisiq.env`, the preflight also needs the existing `--authorize-aria-policy-authoring-org-ids` list and `--accept-aria-policy-authoring-known-limitations`, exactly as at the last release.

13. Restart through the normal release (`deploy.py --apply --restart` with the same options), then check health:

```bash
systemctl status themisiq-app.service --no-pager
```

## Prove it works

14. In the browser, as an authorized ARIA specialist, import a small synthetic DOCX (no customer content). Expected result: suggestions and source anchors appear.
15. Look at the worker's log for that request:

```bash
journalctl -u 'themisiq-policy-extract@*' -n 20 --no-pager
```

16. Confirm the sandbox the host actually applied:

```bash
systemctl show themisiq-policy-extract@probe.service -p DynamicUser -p PrivateNetwork -p IPAddressDeny -p ProtectSystem -p MemoryMax
```

17. Negative test, part 1: stop the socket.

```bash
systemctl stop themisiq-policy-extract.socket
```

18. In the browser, import the same synthetic DOCX again. Expected result: a 503 refusal, with no parsing inside the app.
19. Negative test, part 2: restore the socket straight away.

```bash
systemctl start themisiq-policy-extract.socket
```

20. Repeat steps 9 and 10 to confirm the socket is back with the right owner and mode.

## Capacity (during the first licensed framework import pilot)

Run a real-size licensed framework import and watch these two commands while it runs:

```bash
systemctl status themisiq-policy-extract.socket --no-pager
```

```bash
free -m
```

Record the number of documents, the largest file size, the time per document, and any 503 or timeout (each request is capped at 45 seconds). If imports queue behind the limit of 4 at once, raising `MaxConnections` is a unit change: it goes through the repo and a release, never a hand edit on the host.

## Rollback

If the new code is rolled back, the socket can stay installed; the old app does not use it. Do not restore an older database snapshot over newer accepted records.

## Session log

| Time (CAT) | Step | Result |
| --- | --- | --- |
| | | |
