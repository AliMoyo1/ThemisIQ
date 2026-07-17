# Execution Plans — ranked by leverage

Each PLAN-*.md in this folder is self-contained: goal, exact files,
ordered steps, edge cases, and verifiable acceptance criteria. They are
written to be executed top-to-bottom without needing to ask questions.

## Round 1 status: ALL COMPLETE

| Plan | Status | Commit |
|---|---|---|
| [PLAN-01](PLAN-01-audit-log-tenant-isolation.md) | DONE | `af5e80d`, `1218657` |
| [PLAN-02](PLAN-02-dependency-vulnerabilities.md) | DONE | `af5e80d` |
| [PLAN-04](PLAN-04-repo-hygiene.md) | DONE | `7d8efa7` |
| [PLAN-03](PLAN-03-task-workflow-race-conditions.md) | DONE (2026-07-15) | see plan file |
| [PLAN-05](PLAN-05-governance-t12-unified-controls.md) | DONE | `6daa517`, `3e6fdb8`, `ec4f99f`, `fed4542`, `de48e60` |

## Round 2 — functionality, cross-module communication, and UX (PLAN-06..10)

Written after a functionality/UX exploration pass. Key finding grounding
this set: **nothing in the platform can navigate to a specific record** —
global search, the workflows entity helper, and notifications all link to
module roots. Fixing that (PLAN-06) multiplies the value of everything
that follows.

## Round 2 status: ALL COMPLETE

| Plan | Status | Commit |
|---|---|---|
| [PLAN-06](PLAN-06-entity-deep-links-command-palette.md) | DONE | `9a17658` |
| [PLAN-07](PLAN-07-related-items-cross-module-linking.md) | DONE | `1d6cf5f`, `e99ae5f` |
| [PLAN-08](PLAN-08-governance-timeline.md) | DONE | `1d6cf5f`, `e99ae5f` |
| [PLAN-09](PLAN-09-morning-briefing-advisories.md) | DONE | `a00198f` |
| [PLAN-10](PLAN-10-evidence-confidence-score.md) | DONE | `1d6cf5f` |

## Round 3 — completing the approved Governance Graph Tier 1 + Tier 2 (PLAN-11..13)

Written after assessing the master slice document
(`~/.claude/plans/graceful-shimmying-oasis.md`) against the actual repo
state. Assessment findings:

- Rating-framework Slices 1, 2, 3+4: **implemented AND committed**
  (`30a4081`, `67f4d38`) — the document's "not yet committed" notes are stale.
- Excel Risk Register Import: the document says PLANNED but it **already
  shipped** in commit `51ba39f` (parser, preview/commit endpoints, full
  UI). No plan needed.
- Governance roadmap: T1.1 done (`6df4505`); T1.2 = PLAN-05; T2.1/2.3/2.4
  = PLAN-10/09/08. The approved-but-unplanned remainder is T1.3, T1.4,
  and T2.2+T4.2-lite — that is Round 3.

## Round 3 status: ALL COMPLETE

| Plan | Status | Commit |
|---|---|---|
| [PLAN-11](PLAN-11-t13-control-effectiveness-engine.md) | DONE | `61af256` |
| [PLAN-12](PLAN-12-t14-residual-risk-engine.md) | DONE | `79d811b` |
| [PLAN-13](PLAN-13-drift-detection-regulatory-inbox.md) | DONE (2026-07-15) | see plan file |

## Round 4 — navigation and first impressions (PLAN-16, PLAN-17)

**Scope decision (2026-07-09):** the glassmorphism redesign and icon
replacement (former PLAN-14 and PLAN-15) were CANCELLED at the user's
request after reviewing a mockup — the existing aesthetic stays exactly
as it is. Do not recreate those plans. The two surviving plans are
behavior-only:

| Rank | Plan | What | Impact | Effort | Constraint |
|---|---|---|---|---|---|
| 1 | [PLAN-16](PLAN-16-navigation-upgrade.md) | Expanding labeled nav rail with pin persistence, section labels, module color dots | Navigation self-explains without hover-hunting | ~1 day | Zero visual redesign: current rail colors, icons, and styles preserved |
| 2 | [PLAN-17](PLAN-17-first-impressions-refresh.md) | Command Centre greeting + attention summary; login functional polish (dark-mode bootstrap, autofocus, submit guard) | Personal, informative first screen; no login white-flash | ~half day | Additive only; screenshot-diff proof that everything else is pixel identical |

**Round 4 execution order: 16 → 17.** Independent of Rounds 1-3.

## Round 4 status: OPEN

| Plan | Status |
|---|---|
| [PLAN-16](PLAN-16-navigation-upgrade.md) | OPEN |
| [PLAN-17](PLAN-17-first-impressions-refresh.md) | OPEN |

## Interstitial — ARIA Ask fixes (PLAN-14)

Fixes implemented between Rounds 4 and 5 in response to observed regressions:
error-handling in ask_service.py + catch block in ask.html + multi-turn
conversation memory + greeting handling.

## PLAN-14 status: DONE

| Plan | Status | Commits |
|---|---|---|
| [PLAN-14](PLAN-14-aria-ask-fixes.md) | DONE (2026-07-15) | `dca159a`, `ae4bb53`, `2872206`, `ab4c24c` |

## Round 5 — security round 2 + privacy/AI/BCM assessment engines (PLAN-18..22)

Grounded in a read of the user's five working Excel files (BIA
questionnaire, AI Impact questionnaire, AIMS risk assessment, ISO 42001
ORAAT, AI controls catalogue) plus a code audit of Sentinel schemas and
the auth/upload stack. Recurring design rules across all five plans:
catalogues, dimensions, and row labels are DATA (per-tenant editable,
never hardcoded), every new table carries `business_unit_id` for SBU
federation, and scoring reuses the platform's existing band/effectiveness
conventions.

| Rank | Plan | What | Impact | Effort | Why this rank |
|---|---|---|---|---|---|
| 1 | [PLAN-18](PLAN-18-security-round-2.md) | Org-enforced MFA (Part A: DONE `af5e80d`), SBU data scoping (Part B: DONE 2026-07-16), upload magic-byte checks (Part C: DONE 2026-07-16) | Closes the three real remaining security gaps; SBU scoping is the multi-tenant interior wall | ~3-4 days | Security asked first; SBU isolation is customer-visible |
| 2 | [PLAN-19](PLAN-19-ropa-dpia-integration.md) | RoPA ↔ DPIA link + prefill + drift banner | Kills the retyping the user reported; schema hooks already half-exist | ~1-2 days | Smallest effort, immediate daily-use payoff |
| 3 | [PLAN-20](PLAN-20-aiia-ai-impact-assessment.md) | AIIA assessment type in Sentinel | The explicitly requested AIIA option, with editable dimensions and ERM-consistent banding | ~3-4 days | Explicit ask; independent of everything else |
| 4 | [PLAN-21](PLAN-21-ai-controls-catalogue-aims-engine.md) | Editable AI controls catalogue (96 seeded) + AIMS/ORAAT risk engine in ORM | Digitizes the org's real ISO 42001 working model; strongest differentiator of the batch | ~1-1.5 weeks | Largest slice; resolves a scoring contradiction in the source sheets with one documented convention |
| 5 | [PLAN-22](PLAN-22-bia-questionnaire-engine.md) | ISO 22301 BIA questionnaire engine in BCM | Impact-over-time grids, recovery resources, suggested RTO | ~3-4 days | High value, least urgent; independent |

**Round 5 execution order: 18 → 19 → 20 → 21 → 22.** 19/20/21/22 are
mutually independent; only PLAN-18's Part B (BU scoping) should precede
the others so their list endpoints inherit the scope pattern from day one.

## Recommended execution order

**Round 1 first: 1 → 2 → 4 → 3 → 5.**

Rationale: PLAN-01 and PLAN-02 are launch-safety items with small blast
radius — land and deploy them first. PLAN-04 is an hour and removes a
standing risk every future commit inherits. PLAN-03 hardens correctness
before real multi-user load arrives. PLAN-05 is the next roadmap slice
and assumes a calm, green baseline.

**Cherry-pick note:** PLAN-05 Phase 0 (the `applications.vendor_id` FK
ordering hazard) is a two-line fix that should land IMMEDIATELY even if
the rest of PLAN-05 waits — it breaks provisioning of brand-new tenant
orgs on PostgreSQL, i.e. new-customer onboarding.

## Standing constraints for whoever executes these

- Never use em dashes in copy or comments; use colon/comma/period.
- Any command given to the user for the VPS: one command per step, never
  chained with && and never containing the pipe character.
- Verify with `py_compile` + full pytest + a live browser pass before
  calling anything done. Clean up all test data afterwards.
- Do not commit until the slice's acceptance criteria all pass; one
  focused commit per plan (PLAN-05: one commit per phase).
