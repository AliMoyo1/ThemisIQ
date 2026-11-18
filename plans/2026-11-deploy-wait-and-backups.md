# Deploy startup wait, backup schedule check, local work (2026-11-16)

Owner request in chat: "do these fixes", for the findings after the 2026-11-16 release (see [vps-policy-worker-install-2026-11-09.md](vps-policy-worker-install-2026-11-09.md)). Decisions below are chat confirmation, not sign-off.

## Findings

| # | Finding | Outcome |
| --- | --- | --- |
| F1 | `deploy.py` waited 20 s for `/health`; the first start after the release took about two minutes (about 20 s per tenant schema). It reported failure, restored an identical unit and restarted, and systemd killed the start mid-migration. | Fixed in code (D1, D2). |
| F2 | No proof that the nightly backup still runs. The documented scheduler is root cron running `/project/backup_db.sh` at 02:00 host time (UTC); section 7 (install the verified script over it) was never run. | Verified 2026-11-18 (see change log). |
| F3 | Real-size import throughput is unmeasured; a second import while one parses gets a 503. | Owner step in the licensed import pilot (D4). |
| F4 | Main checkout is 189 commits behind master with 45 tracked edits; VPS notes uncommitted; synthetic DOCX in the worktree. | Notes included on this branch; DOCX moved to the session scratchpad; main checkout left alone (D5). |
| F5 | PR 54 counts GRID proof for mapped controls, so effectiveness scores and ERM residual risk can change at the next rescoring. | Watch item, no code change. |

## Decisions

- **D1 Startup wait 600 s, deadline based.** `probe` polls every 2 s until the deadline, prints progress every 15 s, and stops early if the service is `failed` or `inactive`, or if systemd's automatic restart count (`NRestarts`) rises, because `Restart=on-failure` shows a crash as `activating`. `--startup-wait SECONDS` (30 to 3600) overrides. Why: a schema-changing start needs minutes and grows with tenants. Cost: a start that hangs without failing takes up to 10 minutes to report. Change: the `STARTUP_WAIT_SECONDS` constant or the option.
- **D2 No restore and restart when the unit did not change.** Restoring an identical unit fixes nothing and the restart interrupts startup work. A changed unit (or removed drop-ins) is still restored and restarted once. Why: this is exactly what killed the 2026-11-16 start. Cost: the operator inspects a failed start by hand. Change: `unit_changed` in `deploy.py`.
- **D3 Keep root cron as the backup scheduler; verify it rather than add a systemd timer.** Why: one scheduler, already the documented authority; a second would run two backups. Cost: cron failures are silent, so section 7 now includes a next-morning file check. Change: replace the cron line with a timer in a later change if failures go unseen.
- **D4 Keep the 503 for a concurrent import; no automatic retry in the app.** Why: the client cannot tell systemd's over-limit drop from a parse that crashed on a hostile file, so a retry could re-parse that file. Cost: a user whose import collides retries by hand. Change: measure in the pilot, then raise `MaxConnections` through the repo.
- **D5 Do not touch the main checkout.** The session guard refuses git in it, and reconciling its edits is the owner's decision. A backup command was given in chat.

## Change log

- 2026-11-16: branch `claude/deploy-startup-wait` from master 6084f9e. `deploy.py`: `probe(url, expected, deadline)`, `verify_runtime(startup_wait)`, `unit_changed`, `restart_and_verify`, `--startup-wait`. Eight new tests in `tests/test_production_deploy.py` (slow schema start, deadline, service death, crash restart, identical unit not restarted, changed unit restored, option range). `PRODUCTION_DEPLOYMENT.md` sections 5 and 7 updated. Release session notes and ledger entries included (uncommitted until the owner asks).
- Checks: `tests/test_production_deploy.py` and `tests/test_policy_extract_protocol.py`, 50 passed, 1 skipped (UNIX-socket case on Windows).
- 2026-11-18 08:27 CAT, server: old `/project/backup_db.sh` saved to `/root/backup_db.sh.pre-2026-11-16`; repository script installed (root, 700), syntax OK, run once: backup=PASS, 1267 tables, 87 MB, 0 invalid indexes. Root crontab: `0 2 * * * /project/backup_db.sh >> /project/backups/backup.log 2<&1` (`2<&1` duplicates the same way as `2>&1` in sh, so errors reach the log). `/project/backups` holds a verified dump and `.sha256` for every night from 2026-09-22 to 2026-11-18, all mode 0600: the nightly schedule was already running the verified script. F2 closed.
- Open from F2: no retention or offsite copy. Dumps are about 6.7 MB a night and are never pruned (the deferred offsite gate in the deployment guide section 10 still applies).
- 2026-11-18 08:30 CAT, laptop: main checkout's tracked edits saved by the owner to `C:\Users\isadmin\main-checkout-edits-2026-11-16.patch` (286 KB, 45 files, binary-safe); the checkout itself is unchanged. Untracked files there are not in the patch. F4 closed apart from the owner's reconciliation.
