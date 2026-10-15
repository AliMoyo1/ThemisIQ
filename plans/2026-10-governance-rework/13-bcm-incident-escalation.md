# 13. BCM incident acknowledgement and escalation

**Status:** Written 2026-10-15, after the owner answered "go for it" to the recommendation in the ledger ("Recommendations
for what code cannot do"). This file is the plan and the running log; the build record goes into
[07](07-implementation-ledger.md) when it is verified.

## What the owner approved

- Acknowledgement windows by severity: **critical 15 minutes, high 30, medium 60**. Low has no clock.
- **The BCM manager is the first alternate.**
- The build: record the acknowledgement on the incident, escalate once by mail and in the app when the window ends, and show
  the state on the incident.

The approval was silent on the rules below. Each is the smallest reading that makes the approved behaviour work, and each is
written down so it can be changed on purpose.

## Rules, and why

1. **The clock starts when the incident is declared** with a severity that has a window. It **restarts when the commander
   changes** (a new person must acknowledge), and it **shortens when the severity is raised** (a medium incident that becomes
   critical is due 15 minutes from then, or at the old time if that is sooner). Lowering the severity does not extend it. It
   stops at acknowledgement, resolution or closure. *Why:* a clock that never restarts would hold a new commander to a
   deadline set for someone else; one that could be lengthened by editing the severity would be a way to switch it off.
2. **Who acknowledges:** the named commander, or anyone who may manage incidents (BCM manager, incident commander, super
   administrator) and can open the incident. A person who names **themselves** as commander has acknowledged by doing so.
   *Why:* the alternate must be able to take an incident over, and a person who declares an incident and commands it is
   plainly aware of it, so a false escalation after 15 minutes would only teach people to ignore the message.
3. **Who is told when the window ends without an acknowledgement:** the active BCM managers of the organization who can
   open the incident (its unit); when there is none, the organization's super administrators. Never a platform operator.
   An incident with **no named commander** is treated the same way (its clock runs from declaration): the alternate is
   asked to name one. *Why:* an incident nobody is named on is the case the clock exists for. Organization administrators
   are not the fallback because they cannot open Business Continuity.
4. **Once.** One escalation per clock. A changed commander restarts the clock and may escalate again. *Why:* a repeating
   alarm for one unacknowledged incident would be a nag, and the second person to be told is the same person.
5. **What is sent:** an in-app notice to each alternate and the critical email `bcm.escalation`, both with the reference
   and a link and never the title (the title stays in the incident; the email ignores quiet hours and preferences, as a
   critical message does). The commander's own message says how long they have.
6. **Incidents declared before this change have no clock** and are never escalated. Low severity has none. The incident a
   confirmed Sentinel breach opens (it has no commander) starts its clock when it is opened; the tier names that handler
   writes, `major` and `significant`, are read as high and medium.
7. **Precision:** a job runs every minute, so an escalation is at most a minute late.

## Order and checks

| Step | Work | Checks |
| --- | --- | --- |
| 1 | Policy module `modules/bcm/escalation.py`: windows, due time, state, alternates | `tests/test_bcm_escalation.py` (policy) |
| 2 | Four additive columns; the clock set on create, restarted on update | `tests/test_bcm_escalation.py` (clock) |
| 3 | Acknowledge route; state in the incident responses | route tests in the same file |
| 4 | The minute job; in-app notice; template `bcm.escalation`; send-time check | the same file; `test_email_templates.py` |
| 5 | The incident console and list show the state; Acknowledge button | `tests/ui/test_bcm_incident_escalation_ui.py` |
| 6 | PostgreSQL case | `tests/test_postgres_init.py` |
| 7 | Ledger, inventories, capability inventory; focused, full and browser lanes | the stage table of the ledger |

## Log

**Steps 1 to 5 (built, focused tests green).** `modules/bcm/escalation.py` (windows, due time, state, alternates, the
job and the claim); four nullable columns on `bcm_incidents` (`ack_due_at`, `acknowledged_at`, `acknowledged_by`,
`escalated_at`); the clock is set when an incident is declared and restarted in `update_incident` (new commander, reopened,
severity raised); `POST /bcm/api/incidents/{id}/acknowledge` (the named commander or a person who manages incidents, inside
their unit scope; the first acknowledgement stands; 409 when resolved or closed); the incident list and detail carry
`ack_state`, `ack_minutes` and `acknowledged_by_name`; an every minute job in the BCM scheduler; the template
`bcm.escalation` and a `minutes` field on `bcm.incident` (version 2); a send-time check in the outbox (the incident is
still live and unacknowledged, and the recipient can still open it); the console header and the list show the state with an
Acknowledge button. The Sentinel breach handler's incident gets a clock too. Tests: 21 in `tests/test_bcm_escalation.py`,
4 in `tests/ui/test_bcm_incident_escalation_ui.py`, one PostgreSQL case.
