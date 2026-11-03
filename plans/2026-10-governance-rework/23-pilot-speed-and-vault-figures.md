# Plan 23: group pilot, search speed and the Vault claim figures

**Status:** Built and run on branch `claude/group-completion` (PR 42), 2026-11-03. Not merged.

**Owner's words (chat, 2026-11-03):** "The DPO will be chosen during onboarding and user creation. Remember this is a SAAS. Can you do the pilot tests, measure search speed and build the 3 vault evidence measures."

## 1. What this changes in plan 22's open list

- **Named DPO per customer group** is no longer an owner step. ThemisIQ is sold as a service: each customer names its own DPO when its organization is set up and its people are created (the DPO role is granted on the user administration page, as any role is). The product's part is to make that step hard to miss: the getting-started checklist of a customer administrator shows "Name your Data Protection Officer" until an active person in the organization holds the DPO role. Without a DPO, no relationship's sharing terms can be privacy reviewed, so no group sharing starts (that is enforced already).
- **Pilot, search speed and the Vault claim figures** are built here.

## 2. Slices

| # | What | Done when |
|---|---|---|
| P1 | Vault claim figures: `vault.linked`, `vault.current_proof`, `vault.accepted` built from the Vault's own coverage code (`coverage_for`), for the whole organization, limited to licensed modules; publishable as group figures | builder, registry owner, publishable list, tests |
| P2 | DPO onboarding item on the administrator checklist | test |
| P3 | Search speed: p95 of scoped metadata search and known-item discovery at 500 and 5,000 files, on SQLite and on real PostgreSQL with the ordinary (non-bypass) role | measured numbers recorded below, a repeatable script |
| P4 | Pilot: a synthetic parent and two subsidiaries on disposable data, through the real app over HTTP with real sign-in, walking the group journey and the negative paths (wrong tenant, wrong unit, revoked grant) | pilot test passes; results recorded below |

## 3. Decisions (chat confirmation, not sign-off)

| Decision | Why | Cost | How to change it |
|---|---|---|---|
| The DPO is named by each customer when its people are set up; the product only reminds the administrator | It is a service: the customer, not the operator, knows who its DPO is, and the role is already granted like any other | A customer can leave it undone; then no group sharing can start (enforced), and the checklist keeps asking | Make naming a DPO a required step of tenant creation |
| One Vault claim figure per measure for the whole organization, over every kind of record the Vault measures | The Vault page already counts exactly this (`coverage_for`); one share per measure is what a parent can compare across companies | A parent does not see which kind of record (controls, risks, plans) is weak | Add a figure per module, keyed like the framework register (`vault.accepted:<module>`) |
| The pilot and the speed measurement are scripts plus a SQLite smoke test, not part of the PostgreSQL lane | They need their own throwaway database and an ordinary login role, which the lane's shared database does not give | The PostgreSQL run is by hand (commands below) | Add a CI job with its own PostgreSQL service that runs both scripts |
| A reviewer who cannot open the released proof is told why (409) instead of "not found" | Found by the pilot: the parent's second reviewer had no named grant and was stuck. They already see the request, so the reason tells them nothing new | None | Revert in `group_requests.review_release` |
| The pilot's timings are the system's, not a person's | No real users took part; plan 19's median task times and correction rates need people | Human task times are still unmeasured | Run the same tasks with the first customer group's specialists and record their times |

## 4. Build log

- 2026-11-03: P1 and P2 committed (`5ee2e47a`): `modules/evidence/claim_metrics.py` builds `vault.linked`, `vault.current_proof` and `vault.accepted` from `coverage_for`, limited to licensed modules for a whole-organization build; registry owner and wording updated; `vault.*` added to the publishable measures. The getting-started checklist shows "Name your Data Protection Officer" to a customer administrator until an active person holds the DPO role.
- 2026-11-03: P3 committed (`d2cfa2db`): `scripts/measure_vault_search.py`.
- 2026-11-03: P4: `scripts/pilot_group_oversight.py` and `tests/test_pilot_scripts.py` (runs both scripts on SQLite). The pilot found that a parent reviewer without a named grant was told only "not found" when accepting proof: fixed in `group_requests.review_release` (409 with what to do), test updated.

## 5. Results

### Search speed (plan 19 target: under one second for metadata search)

Measured with `scripts/measure_vault_search.py`. Each size gets:
- one organization, with a viewer confined to one business unit;
- a hidden unit holding a fifth as many files;
- a second organization with the same titles;
- indexed text for a third of the files.

Each query is first checked for the right answer: the known item comes first, and nothing from the hidden unit or the other organization appears. It is then timed 40 times after 3 warm-up runs. This is the server's time for the library code. It does not include page rendering or the network.

PostgreSQL 18 (Docker on the laptop, which adds about 0.8 ms per round trip), a tenant schema per organization, run as an ordinary login role under row level security:

| Files seen | Query | Matches | p50 ms | p95 ms | max ms |
|---|---|---|---|---|---|
| 500 | Browse, first page | 500 | 26.5 | 31.6 | 41.3 |
| 500 | Metadata search, common word | 209 | 29.5 | 40.1 | 43.7 |
| 500 | Metadata search, nothing matches | 0 | 29.2 | 33.4 | 40.7 |
| 500 | Known item by reference | 1 | 29.5 | 40.9 | 41.5 |
| 500 | Known item by words (Find evidence) | 1 | 29.1 | 32.1 | 35.3 |
| 500 | Known item by file text | 1 | 29.3 | 33.0 | 35.0 |
| 5000 | Browse, first page | 5000 | 39.6 | 43.6 | 44.0 |
| 5000 | Metadata search, common word | 2083 | 54.9 | 62.5 | 68.2 |
| 5000 | Metadata search, nothing matches | 0 | 67.3 | 73.2 | 76.1 |
| 5000 | Known item by reference | 1 | 70.1 | 75.6 | 77.9 |
| 5000 | Known item by words (Find evidence) | 1 | 67.6 | 232.7 | 367.5 |
| 5000 | Known item by file text | 1 | 68.4 | 79.7 | 91.4 |

SQLite, same data: every p95 between 26.7 and 63.0 ms.

Every p95 is well under the one-second target. The one to watch as a library grows is Find evidence by words at 5,000 files (p95 233 ms): each word adds a scan of titles, file names, tags, descriptions and indexed text.

The 30-second target for finding a known document is a person's time and was not measured. The system's share of it is under 0.1 seconds.

To repeat on PostgreSQL, from `oneforall/`, against a throwaway database whose name starts with `themisiq_test_`: set `SPEED_DATABASE_URL` and run `python scripts/measure_vault_search.py`.

### Pilot: a synthetic parent and two subsidiaries

`scripts/pilot_group_oversight.py` sets up Pilot Holdings, Pilot Mining and Pilot Retail the way the service sets up a customer: organization, licence, tenant schema, people and roles, and each customer's own DPO. It then:
- enrols every person in two-step sign-in;
- signs each one in through the real `/login` and `/mfa/verify` forms;
- runs the journey through the whole application over HTTP.

No AI provider is called.

**Result: 21 of 21 steps passed** on PostgreSQL 18, with a tenant schema per customer and every request made as an ordinary role under row level security. The same result on SQLite.

| Step | Who | Result |
|---|---|---|
| Everyone signs in with a password and a second factor | 16 people | passed |
| The platform operator proposes both relationships | operator | passed |
| A customer administrator cannot propose a relationship | Holdings admin | refused, as it must |
| Another subsidiary's DPO cannot review Mining's terms | Retail DPO | refused |
| Mining acknowledges; its DPO records privacy and legal | Mining admin, DPO | active |
| Retail acknowledges; its DPO and compliance manager review | Retail admin, DPO, CM | active |
| Mining's DPO approves the rights, its GRC officer releases a document | Mining DPO, GRC | released |
| A person confined to one business unit cannot release another unit's file | Mining unit GRC | refused |
| Holdings' administrator grants named access | Holdings admin | 4 grants |
| Task: find a known subsidiary document | Holdings GRC | found and opened |
| Nobody without a named grant opens it (parent colleague, sibling, auditor, unit user) | 4 people | 4 refusals |
| A question over released documents returns the cited passage | Holdings GRC | cited passage |
| Task: request unknown proof by requirement and accept it | Holdings GRC, Retail CM and GRC, Holdings admin and CM | accepted (after the fix below) |
| Task: record a child policy exception; the parent sees the outcome, not the reasons | Holdings DPO and GRC, Mining admin, GRC, CM | passed |
| Subsidiary figures published and read, Vault claim figures included | operator, Holdings GRC | 35 Mining figures |
| A sibling cannot read Mining's figures | Retail GRC | refused |
| A board pack built and issued by a second person | Holdings GRC, CM | integrity check passed |
| Task: resolve an auditor question in an audit room | Holdings GRC, audit lead, external auditor | answered with a citation |
| Task: file a new version; the old release stops, the new one is released | Mining GRC, DPO, Holdings GRC | passed |
| A revoked grant ends access at once, in the same session | Holdings admin, GRC | passed |
| Mining's access log records every parent read | check | passed |

What the pilot found:

1. **Fixed:** the parent's second reviewer, accepting a subsidiary's proof without a named grant to open it, got "Not found." and no way forward. They now get a 409 that says what to do.
2. **Noted, SQLite only:** on SQLite all organizations share one database, so a whole-organization figure build counted another organization's control. Mining showed 36 figures, one of them for a framework it has no controls in. On PostgreSQL, where each customer has its own schema, Mining correctly showed 35. Production runs PostgreSQL, but a development or demonstration copy on SQLite can show another organization's control counts in group figures.

To repeat on PostgreSQL: set `PILOT_DATABASE_URL` to a throwaway database whose name starts with `themisiq_test_` and run `python scripts/pilot_group_oversight.py` from `oneforall/`.

### Not covered here

- Plan 19's timed specialist tasks with people: median time, filing correction rate, suggestion acceptance, request turnaround, support questions. These need the first customer group's specialists.
- "Explain a restated score" and mobile usability were not part of this pilot.
- Release steps (schema dry run, verified backup and restore, count and hash comparison, rollback, a walkthrough after release) belong to deployment.
