# 14. Hardening pack: outbox purge, send limit, task assignment mail, badge contrast

**Status:** Written 2026-10-15, after the owner answered "do this" to the recommendation made in the ledger (the open items
of plan 06 that code can close, and the two accessibility findings of follow-up 11). The plan and its running log; the build
record goes into [07](07-implementation-ledger.md) when it is verified.

## What is built, and the reasons

1. **A purge of old deliveries.** A delivery that ended (accepted, suppressed, failed for good, or logged only) more than
   180 days ago is deleted, once a day per organization. Waiting and retrying rows are never touched. *Why 180 days:* the
   rows hold a recipient, a reference and a status, not a message, so they are small; what they are for after a few weeks is
   only the question "was this sent" and, for a job that asks again every period, the dedupe key. Deleting the key means an
   item that is still unresolved after 180 days is asked for once more, which is a reminder and not a defect. A shorter
   window would repeat reminders sooner; a longer one keeps recipients' delivery history for no use. Owner decision 5 in
   [09](09-email-inventory.md) (retention and processor terms) is still the owner's to confirm: the number is a constant,
   `RETENTION_DAYS`.
2. **A send limit per minute.** At most 20 non-critical messages are handed to the provider in a minute, across every
   organization, because they all leave through one account. Critical messages are not counted and are never held. A
   suppressed message is not a send and is not counted. *Why 20:* the application has a 200-message daily limit within each
   tenant; 20 a minute paces a burst such as bulk assignment or a deadline run. The daily limit is not a provider-wide cap
   across tenants, so a shared sender needs a separate account-wide limit before a live mail pilot. The minute limit is the
   constant `PER_MINUTE`.
3. **Mail when a task is handed to someone.** Updating a task so that it belongs to someone else, and assigning a group of
   tasks, tell the new assignee in the app and by email (until now only creating a task did). A group is one message, "N tasks
   are assigned to you", not N: a person who is given forty tasks is told once. The person who made the change is not told.
   *Why one message:* the daily cap and the person's inbox are both shared resources.
4. **Badge text that passes.** The 10 pixel bold badges used the amber, green and red fill tints as text colours and fell to
   about 3:1. They now use a darker text token in the light theme (`--badge-amber`, `--badge-green`, `--badge-red`) and the
   unchanged colours in the dark theme. Only text on badges changes; fills, icons and borders are as they were.

## Order and checks

| Step | Work | Checks |
| --- | --- | --- |
| 1 | `purge_old` and its daily run | `tests/test_email_outbox.py` |
| 2 | The per minute budget in `deliver_due` and `deliver_all_tenants` | `tests/test_email_outbox.py` |
| 3 | `tasks.assigned`, the reassignment notice, the update and bulk routes | `tests/test_task_assignment_mail.py` |
| 4 | Badge tokens | `tests/ui/test_badge_contrast.py` |
| 5 | Ledger, inventory, capability inventory; focused, full, PostgreSQL and browser lanes | the stage table of the ledger |

## Log

**Step 4 (built).** `--badge-amber`, `--badge-green` and `--badge-red` in the shell, used by `.badge-high`, `.badge-progress`,
`.badge-low`, `.badge-complete`, `.badge-critical` and `.badge-overdue`. The test seeds one row of each in the BCM incident
list and the ERM register and asks axe about both themes; it fails on the earlier colours (3.07 and 3.14 to 1) and passes
now. Green and red were included because the same probe measured them below the minimum too.

**Steps 1 to 3 (built, focused tests green).** `core/email_outbox.py`: `PER_MINUTE` (20) and a `budget` shared by every
organization's pass (`deliver_due(budget=...)`, one budget made in `deliver_all_tenants`); `_deliver_one` reports when the
provider was actually called, and only that spends the budget; `RETENTION_DAYS` (180), `purge_old` and a once a day run per
organization in the worker pass. `core/email_templates.py`: `tasks.assigned` (a count and a link). `modules/launcher/
task_service.py`: `tell_new_assignee` (one notice and one email, one task as a task and a group as one batch message, never
to the person who made the change, a hand over has its own key so a task given away and given again is told again);
`routes_platform.py`: `api_task_update` and `api_tasks_bulk_update` call it for the tasks that really changed hands. Tests:
5 added to `tests/test_email_outbox.py`, 7 in `tests/test_task_assignment_mail.py`, the template sample, and one
PostgreSQL case.

**Step 5 (verified, 2026-10-15).** Full backend 2633 passed, 74 skipped, 0 failed; real PostgreSQL 73 of 74 in the lane and
the one case, whose test data was wrong (not the code), passes on its own; browser 43 files, 350 passed, 1 skipped, 0 failed.
Committed as `ecccbad`.
