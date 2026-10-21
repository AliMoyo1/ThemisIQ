# 11. Follow-up plan: the items the first build left

**Status:** Written 2026-10-15, after the owner said "Lets deal with this" about the five items the first build of plans 04 to 06
reported as not built. This file is the plan and the running log for that work; the build record goes into
[07](07-implementation-ledger.md) when each part is verified. Committed as `cbf9372` and pushed on the branch `claude/plan-04-platform-truth`.

## What can be built, and what cannot

| Item | What is buildable now | What still needs something outside the code |
| --- | --- | --- |
| E4 provider cutover | The seams a cutover needs: pause and resume the outbox, a deliveries by provider comparison, a runbook | A managed sender identity (domain, SPF, DKIM, DMARC, an account). Nothing in the repository can create it |
| BCM incident mail | A named incident commander (a person, not free text) on an incident, mailed when named or changed; the exercise owner and reviewer mailed for an upcoming exercise | Approved incident clock and alternate contact runbook (owner decisions 3 and 7). Plan owner and training owner are free text and stay unmailed |
| AI Governance review and decision mail | A named reviewer on a request and a named decider on a decision request, with the separation rules, My Work and mail for the named person | Nothing external. The default (nobody named) stays in-app only, as the plan requires |
| Cross-module digests, quiet hours | Per person: a daily or weekly My Work summary, quiet hours with a UTC offset, and one place to set them | Whether a tenant may override the platform defaults (owner decision 4). Built platform wide, opt in |
| Predictive number traceability | Each signal of a prediction carries its rule, window, formula term and the records behind it, frozen with the prediction; a reviewer can dispute a signal beside it | None |
| Manager team view | "My team's" in My Work: the people in the units the viewer heads, with counts and top overdue items read through the viewer's own scope | None |

## Defaults chosen (confirmed by the owner, 2026-10-15)

The owner answered "Go with your recommendations but explain them in the ledger". The five defaults below are therefore
adopted decisions. Two refinements that were put to the owner with them (a team lies inside the head's own scope; only
assigned work is counted against a person) are adopted too. The reasons, the cost of each and how to change it are in
[07](07-implementation-ledger.md) under "Decisions taken (owner, 2026-10-15) and why".

1. **A team** is the active people of the business units a person heads (`business_units.head_user_id`) and their sub-units. No
   new schema. A person who heads no unit has no team view.
2. **A named reviewer or decider is optional.** Nobody named: the in-app notice goes to everyone in scope, as before, and no
   email is sent. Named: only that person is mailed. Reviewers assign reviewers; reviewers and deciders assign deciders. The
   assignee must hold the capability, be able to open the record, and not be its requester; a decider must also not be the
   owner of the use when separation is required.
3. **Summaries and quiet hours are opt in and platform wide**, set by each person on their profile. Quiet hours use a fixed
   UTC offset in 15 minute steps. Critical mail ignores quiet hours and every preference.
4. **The incident commander is a named user**, chosen in the incident form; the existing free text field stays as a label.
5. **A prediction's trace is frozen with it**: record ids and the numbers they produced, not a live recount.

## Order and checks

| Step | Work | Focused checks |
| --- | --- | --- |
| 1 | E4 seams: pause and resume, comparison by provider, runbook | `test_email_outbox.py` (pause, comparison), admin route test |
| 2 | Preferences: quiet hours, daily and weekly summary, the profile | `test_email_outbox.py` (quiet hours), `test_email_producers.py` (summaries), profile browser test |
| 3 | BCM: commander user, incident and exercise mail | `test_email_producers.py` (BCM) |
| 4 | AI Governance: named reviewer and decider, handlers, My Work, mail, UI | `tests/test_ai_governance_assignment.py`, review desk browser test |
| 5 | Predictive trace and dispute | `tests/test_predictive_trace.py`, Command Centre browser test |
| 6 | Team view | `tests/test_my_work_team.py`, My Work browser test |
| 7 | Ledger, completion record and inventory updated; full backend, PostgreSQL lane, browser subset | the stage table of the ledger |

## Log

(Each part is recorded here as it is built; the ledger gets the finished entry.)

**Step 1, E4 seams (built, focused tests green).** `core/email_outbox.py`: `PAUSE_KEY`, `is_paused`, `set_paused` (a pause
holds every message but `critical`, held messages stay queued and are not an attempt), `by_provider(db, days)` and `summary()`
now carries `paused` and `by_provider`. `POST /api/admin/email-outbox/pause`; the Email page shows the state, a Pause or Resume
button and the provider comparison. Runbook: [12](12-email-cutover-runbook.md). Not built: the managed sender identity itself.

**Step 2, preferences (built).** Quiet hours (`HH:MM-HH:MM` with a UTC offset in 15 minute steps), `email.mode`
(immediate or daily), `email.weekly`, `email.action`, all on the profile and validated by `/api/my-email-preferences`. Mail that
is not critical is postponed to the end of quiet hours without using an attempt. Daily mode suppresses the individual action
mail that the summary then covers. `modules/launcher/summary_mail.py` asks for one `summary.mywork` per person per day (or week)
from the My Work counts; nothing is sent for zero. Opt in; `OPTED_IN` templates bypass `preference_off` but not suppression.

**Step 3, BCM mail (built).** `bcm_incidents.commander_user_id`, a commander chosen from `GET /bcm/api/people` in the incident
form, mail `bcm.incident` (critical) when named or changed; `bcm.exercise` to the owner of a planned exercise from the BCM
scheduler. The free text commander stays as a label. Still unmailed on purpose: plan owner and training owner (free text).

**Step 4, AI Governance named reviewer and decider (built).** `ai_use_intake_requests.assigned_reviewer_id`,
`ai_use_decisions.assigned_decider_id`; `modules/ai_governance/assignment.py` (eligibility: capability, can open the
application, not the requester, not the owner of the use when separation is required); routes under `/api/review/requests/{id}`
and `/api/decisions/{id}`; handlers mail only the named person; My Work shows an item named to another person as waiting.
Nobody named stays in-app only.

**Step 5, predictive trace and dispute (built, focused tests green).** `core/predictive_risk.py` keeps, frozen in
`telemetry_json.trace`, up to 25 record ids and weights per signal and the count; `SIGNALS` and `WEIGHTS` name the rule, window
and weight. `modules/launcher/predictive_trace.py` turns that into what a reviewer reads, filtered through the viewer's scope
(a record the viewer may not open is counted, never named). `GET /api/predictive-risk/trace` and
`POST /api/predictive-risk/{id}/disputes` (super administrators, as the panel is); a dispute is a note in
`ai_risk_prediction_notes` and edits nothing. "Why this number?" on the Command Centre panel. Tests: 19 in
`tests/test_predictive_trace.py`, 3 in `tests/ui/test_predictive_trace_ui.py` (one is an axe check of the open trace). A term below zero (a recent exercise) is shown as
lowering the score; the stored share is an absolute value and is not shown for it. Predictions made before this change say they
cannot be traced and show their figures only.

**Step 6, the team view (built, focused tests green).** `my_work_service.get_team_work(user, unit_id)` and
`GET /api/my-work/team`; the sources of My Work are now one function of a person (`_collect`), so the page and the team view
read the same code. A team is the active people of the units the viewer heads that lie inside their own scope, and the units
below. For each person (25 at most; `unit_id` narrows a larger team) four counts (overdue, due soon, to act on, waiting on
others) and the five oldest overdue items. Only work **assigned** to a person is counted: evidence expiring, open incidents,
statutory deadlines, evidence waiting for any reviewer and notifications are shared queues and are not charged to anyone, and
an AI decision or request counts only when it is named to the person. An item outside the viewer's own unit scope is not read
at all, and a title from a module the viewer may not open is counted and not named. "My team's" appears on My Work only for a
person who heads a unit. Tests: 12 in `tests/test_my_work_team.py`, 1 in `tests/test_ai_governance_assignment.py`, 3 in
`tests/ui/test_my_work_team_ui.py` (one is an axe check of the team view). Drive-by, same page: the title, source and basis of a My Work item ran together on one line
and the Load more button was never hidden (a `hidden` attribute loses to a `display` rule); both fixed in the template.

**Step 7, verification and records (done 2026-10-15).** Full backend 2599 passed, 1 failed (a test list that did not name the
two BCM templates; corrected), 72 skipped; real PostgreSQL 72 of 72; the browser subset of 36 files 253 passed with 14 failures
of which 12 were the machine being suspended and 2 were axe findings that depend on data and order, all passing when run again.
One of those two (the notification list was not keyboard focusable) was a real, older defect and is fixed with a regression
test; the other (amber badge contrast on the ERM register) is recorded and not changed. The owner confirmed the defaults on the
same day: "Go with your recommendations but explain them in the ledger"; the reasons are in the ledger under "Decisions
taken". Open for the owner: a managed sender identity, and the BCM acknowledgement windows and alternate contact.
