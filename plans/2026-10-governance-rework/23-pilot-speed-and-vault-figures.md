# Plan 23: group pilot, search speed and the Vault claim figures

**Status:** In progress on branch `claude/group-completion` (PR 42), started 2026-11-03.

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

(Filled in as slices finish.)

## 4. Build log

(Filled in as slices finish.)

## 5. Results

(Filled in as slices finish.)
