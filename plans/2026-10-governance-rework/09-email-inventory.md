# 09. Email inventory and decisions (plan 06, phase E0)

**Status:** Built from source on 2026-10-15, on the branch `claude/plan-04-platform-truth`; the "State now" column was brought
up to date the same day, after E1 and E2 were built (see the ledger entry "plan 06"). It is the E0 deliverable of
[06](06-email-notifications-and-delivery.md): what sends mail, to whom, what each path claimed about delivery, and which
decisions only the owner can make. Nothing here read or changed a mailbox, a credential, a DNS record or a schedule on any
server. It does not claim that any real person missed a message.

## Every path that sends mail

All of them end in `core/email.py` `send_email`, which dispatches to SMTP, Microsoft Graph or SendGrid. Messages asked for
through the outbox are sent by its worker, once a minute, from the reminder scheduler's process.

| Path | Trigger | Recipient | Before this work | State now |
| --- | --- | --- | --- | --- |
| `core/reminder_scheduler.py` | every 5 minutes, `email_reminders` due | the address stored on the reminder | HTML built from unescaped title and message; a reminder with no address was marked sent; a console fallback marked it sent; recurring reminders rescheduled with a SQLite-only `datetime()` call | Escaped; marked sent only when the provider accepted; no usable address is `suppressed` and stays visible; logged only stays due and says so; five attempts, then `permanent_failure`; recurrence computed in Python; runs once per organization |
| `modules/sentinel/scheduler.py` breach monitor | hourly, under 24 and under 6 hours before the notification deadline | `sentinel_dpo_email`, else `dpo_email`, else **the first active user in the table** | the "notified" flag was set after calling a helper that returns nothing, so a failed or console-only send was recorded as delivered; the link was `#`; the body named the breach title | Through the outbox as `privacy.deadline`, priority critical, once per person and threshold. Recipients are the active users who hold the DPO role in the organization and the user whose address is the configured DPO address, never the first user. The message has the reference, the recorded deadline and a link. The in-app notice is made once, and says when nobody is named. The `breach_notified_*` flags now mean only that administrators were told in the app |
| `modules/sentinel/scheduler.py` DSR monitor | daily 08:00, 7, 3 and 1 days before | the same DPO address | the data subject's name was in the body | `privacy.dsr` through the outbox, priority critical (a person cannot turn it off): reference and date only |
| `modules/evidence/scheduler.py` expiry | daily 09:00 UTC, 30, 7 and 1 days | the user who uploaded the item | title and name interpolated without escaping, a relative link (`/evidence/`) that cannot work in a mail client, no result checked | `evidence.renew` through the outbox, one message per item, owner, expiry date and bucket (a missed day never loses a threshold). Absolute link, reference not title |
| `modules/grid/scheduler.py` reminders, expiry alerts, escalations, response deadlines, finding escalations | daily cron | control subscriber, control assignee, the audit lead | **every GRID mail raised `NameError` while rendering** (`os` was not imported in `email_service.py`), so none was ever sent; `last_sent` and `expiry_notified` were set after the call without checking its result; the escalation join made every administrator of the database a "manager" of every control; legacy branding and a default `localhost` link | `control.reminder`, `evidence.renew`, `audit.escalation`, `audit.deadline` through the outbox, one per person, action and threshold (once a day, week or month as chosen; escalations once a week). An escalation goes to the audit lead, else the administrators of the same organization, never the assignee. No result flag is kept: the outbox row is the record |
| `modules/grid/scheduler.py` weekly digest | Mondays 07:00 | `grid_digest_subscriptions` | every audit was sent to every subscriber, whatever that person may open | `summary.weekly`: only subscribers with an active account, counting only the audits that person may open, so the number and the list behind the link are the same set |
| `modules/grid/scheduler.py` vault expiry | daily 08:45 | the uploader | the same people as the Evidence job, daily for thirty days | Asks the Evidence job's function, under the same key: one message |
| `modules/grid/routes.py` NC assignment | a finding is assigned or created with an assignee | the assignee | best effort, swallowed, result ignored; none at creation | `audit.finding` through the outbox, also at creation |
| `modules/grid/routes.py` audit share | an administrator creates a share link | the auditor, an active account with GRID access in the organization | a bearer-style token in the link; the origin is validated (`APP_URL`, https) | Direct send kept (a link that works only for the signed-in recipient); the subject has no audit name; the creator sees `email_status`. Token expiry and revocation review is open |
| `modules/launcher/task_service.py` task created for someone else | a task is created with an assignee | the assignee | in-app notice only | `action.assigned` through the outbox, after the task and its notice are committed. Updating or bulk assigning a task notifies nobody, in the app or by mail |
| `main.py` demo request | the public form | the administrator address | called `send_email(body_text=...)`, which the function did not accept: the exception was caught, so the message was never sent | The function takes a plain text part; the data is escaped; a provider that did not accept it is logged |
| `modules/launcher/routes_admin.py` test | an administrator presses Send test | the administrator | in console mode it answered "Sent via console" | Says *the provider accepted it*, *nothing was sent* or *the provider did not accept it*, and asks whether it arrived |
| `core/email_outbox.py` failure report | the worker, every minute, sends at most once a day per count | the administrators of the organization | none | `delivery.failure`: how many messages ended as a permanent failure in the last seven days. A critical failure is also shown in the app at its first failure, not after the retries |
| `modules/ai_governance/handlers.py` | a request is submitted or a decision is asked; a reviewer or decider is named | everyone in scope in the app; **by email only the person named** | no mail | Nobody named: in the app only, as before (the plan forbids a broadcast to every possible decider). A reviewer of a request (`assigned_reviewer_id`) or the decider of a decision request (`assigned_decider_id`) is named from a list of people who hold the capability, can open the use and are not its requester (nor, when separation is required, its owner). The person is told in the app and by `action.assigned` (reference `AIR-<id>`, route `/ai-governance/review`) or `decision.ready` (reference `AID-<id>`, route `/ai-governance/systems/<id>`). Checked again when sent: still submitted or proposed, still named, still allowed. A transfer stops the earlier message; taking the name off tells nobody by mail |
| `modules/bcm/routes.py` incident | an incident is created or updated with a commander (a user chosen from `GET /bcm/api/people`) | the named commander | no mail | `bcm.incident` through the outbox, priority critical, once per incident and person; checked again when sent (the incident is open and the person is still its commander). The free text commander stays as a label and is never mailed |
| `modules/bcm/escalation.py` job | every minute, an incident whose acknowledgement window ended (15 minutes critical, 30 high, 60 medium) | the BCM managers of the organization who can open the incident, else the super administrators who can | none | `bcm.escalation` through the outbox, priority critical, once per incident and clock (reference and a link, never the title), and an in-app notice. Checked again when sent: the incident is still live and unacknowledged, and the person can still open it. With nobody able to open it, the administrators are told in the app, without the reference |
| `modules/bcm/scheduler.py` exercises | daily, a planned exercise due within 14 days whose reminder task was just made | the exercise owner (`owner_id`) | a `_send` helper that nothing calls | `bcm.exercise` through the outbox, one per exercise, owner and threshold. Plan owner and training owner are free text and are not mailed |
| `modules/launcher/summary_mail.py` | the outbox worker, every minute, for people who opted in | the person | none | `summary.mywork`: how many items need action, are due soon or overdue on that person's My Work, once a day (daily mode) or once a week (weekly option), after 07:00 local time, never for zero. Counts come from `get_my_work`, so they are what the person sees. Opt in on the profile; the master switch for action mail does not turn it off |
| `modules/launcher/routes_auth.py` preferences | a person on their profile | themselves | one switch for action mail | `GET` and `PUT /api/my-email-preferences`: action mail on or off, immediate or daily, a weekly summary, quiet hours (`HH:MM` to `HH:MM`) with a UTC offset in 15 minute steps. Mail that is not critical waits for the end of quiet hours without using an attempt; critical mail ignores every preference |
| `modules/launcher/routes_admin.py` pause | an administrator presses Pause sending | none | none | `POST /api/admin/email-outbox/pause`: holds every message but a critical one; held messages stay queued; the page shows a notice while it is on and lists deliveries by provider for the last 30 days. Runbook: [12](12-email-cutover-runbook.md) |

## Findings that are not mail transport

- **Secrets in the settings table.** The SMTP password, the Graph client secret and the SendGrid key were stored in the
  `settings` table, obscured with repeating XOR against a key derived from `SECRET_KEY`. That is obfuscation. The admin page
  now refuses to save a new password there unless the operator sets `EMAIL_ALLOW_DB_SECRETS` (they are deployment secrets:
  `SMTP_PASS`, `MS_CLIENT_SECRET`, `SENDGRID_API_KEY`), still reads a stored one so a running installation does not stop,
  reports it as obscured and not encrypted, and has a confirmed Clear stored secrets action for after rotation.
- **The sender.** `smtp_from` was used as the visible From address whatever mailbox authenticated, and the shipped default is
  a placeholder. For the Gmail path the From is now the authenticated mailbox with the configured name; a configured address
  that is not the mailbox is a warning in the sender health panel, not silently used.
- **TLS.** STARTTLS ran without verifying the server certificate. It now uses a verified default context.
- **Header injection.** The recipient and subject were put in headers as given. Line breaks are removed and a recipient must
  be one plain address.
- **A summary sent to a person who cannot open its rows.** Fixed for the GRID digest (above).
- **Scheduled jobs and tenants.** The GRID, Sentinel, Evidence and reminder jobs used a bare connection. By the contract in
  `database.list_active_tenants`, that stays on the public schema, so on PostgreSQL they would have seen none of an
  organization's rows. Each now runs once per organization. Read from the code, not observed on the deployed installation.

## Decisions only the owner can make (06 section 10)

1. Is the temporary account consumer Gmail or Google Workspace, and which organization owns it?
2. Which exact From and Reply-To address, and who monitors replies and bounces? Until answered, every message says it is
   operational and not to be replied to, and `SMTP_REPLY_TO` is empty.
3. Which critical alerts need an alternate human contact, and who owns that runbook per tenant? Until answered, a critical
   message that fails tells the organization's administrators in the app at the first failure. A BCM incident now mails its
   named commander as a critical message, and the BCM managers are told once when nobody acknowledges it in time
   (follow-up 12: 15, 30 and 60 minutes, adopted by the owner on 2026-10-15). The alternate contact for privacy deadlines
   is not built.
4. May a tenant customize digest frequency, quiet hours and sender identity, or are they platform wide for the pilot?
   **Decided (owner, 2026-10-15): platform wide.** Each person chooses their own action mail, daily or weekly summary and
   quiet hours; a tenant cannot override them and the sender identity is the platform's. The reasons are in the ledger under
   "Decisions taken".
5. Which delivery metadata retention and provider data processing terms are approved? Outbox rows are kept; there is no purge.
6. Does the pilot include only test recipients or a named governance team, and what is the measured daily volume? The cap is
   200 accepted messages a day per organization for everything that is not critical (a constant, `DAILY_CAP`).
7. Which role authors the legal clocks and alternate contacts of Sentinel and BCM (E3)? Until answered, the breach message
   states the deadline the application recorded and does not state the legal rule.

## What was built (E1 and E2) and what was not (E3, E4)

E1 (sender safety and truthful status) and E2 (the outbox, the catalogue and the pilot paths: finding assignment, evidence
expiry, task assignment, and the GRID jobs) are built and verified locally; the ledger entry "plan 06" has the checks and
the Not done list. E3 is built for Sentinel breach and request deadlines on the common contract, the GRID weekly summary,
and (follow-up 11) the BCM incident and exercise mail, the named AI Governance reviewer and decider, and the opt in My Work
summary with quiet hours. Not built: a BCM escalation clock and alternate contact, jurisdiction wording, and external
invitations. E4 (provider cutover): the seams are built (pause, comparison by provider, [the runbook](12-email-cutover-runbook.md));
the managed sender identity it needs does not exist yet, so no cutover has been run.
