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
| 2 | [PLAN-19](PLAN-19-ropa-dpia-integration.md) | RoPA ↔ DPIA link + prefill + drift banner | Kills the retyping the user reported; schema hooks already half-exist | ~1-2 days | DONE (2026-07-17) |
| 3 | [PLAN-20](PLAN-20-aiia-ai-impact-assessment.md) | AIIA assessment type in Sentinel | The explicitly requested AIIA option, with editable dimensions and ERM-consistent banding | ~3-4 days | Explicit ask; independent of everything else |
| 4 | [PLAN-21](PLAN-21-ai-controls-catalogue-aims-engine.md) | Editable AI controls catalogue (96 seeded) + AIMS/ORAAT risk engine in ORM | Digitizes the org's real ISO 42001 working model; strongest differentiator of the batch | ~1-1.5 weeks | Largest slice; resolves a scoring contradiction in the source sheets with one documented convention |
| 5 | [PLAN-22](PLAN-22-bia-questionnaire-engine.md) | ISO 22301 BIA questionnaire engine in BCM | Impact-over-time grids, recovery resources, suggested RTO | ~3-4 days | High value, least urgent; independent |

**Round 5 execution order: 18 → 19 → 20 → 21 → 22.** 19/20/21/22 are
mutually independent; only PLAN-18's Part B (BU scoping) should precede
the others so their list endpoints inherit the scope pattern from day one.

## Round 6 - ERM v2: the mind-map redesign (PLAN-23..28)

Grounded in the user's `ERM Module.xmind` mind map (read 2026-07-17,
including all node notes) plus a full code exploration of the ERM module,
the T1.2/T1.3/T1.4 governance-controls engines, and the framework tables.
Key architectural findings baked into these plans:

- The T1.4 residual formula `L x I x (1 - eff/100)` is structurally the
  mind map's RRR formula; ICE scoring slots in as a new top-precedence
  tier of `recompute_residual_for_risk`, not a rebuild.
- `canonical_controls` + `risk_controls` already exist; the P2sT2 control
  library is a category column on canonical_controls, not a new table.
- The mind map's LoA/RRR wording contradicts its own multiplier table;
  PLAN-23 documents the single self-consistent convention (LoA = avg ICE,
  LoR = 1 - LoA, RRR = LoR x IRR, EMV-r = LoR x EMV-i) that reproduces
  every number in the source table.
- User constraints: keep existing ERM tables and extend them; retire the
  old 1-5 effectiveness_rating in favour of ICE (column kept, writes
  stopped).

| Rank | Plan | What | Why this rank |
|---|---|---|---|
| 1 | [PLAN-23](PLAN-23-erm-cf-ice-engine.md) | Contributing factors, ICE engine, frozen IRR, EMV, risk refs, pillars, score history (backend only) | Every other plan reads these tables and numbers; highest leverage, zero UI risk |
| 2 | [PLAN-24](PLAN-24-erm-assessment-workspace.md) | Risk form + drawer UI: CF editor, ICE selectors, LoA/LoR/RRR/EMV-r live strip, P2sT2 picker, AI suggest, CSV | Makes the engine usable daily; completes the identification + assessment loop |
| 3 | [PLAN-25](PLAN-25-erm-cf-treatments.md) | Per-CF treatments: TR numbers, Exploit, Accept-at-70 rule, EMV-a, due dates | Completes the CF lifecycle; depends only on 23 (24 recommended) |
| 4 | [PLAN-26](PLAN-26-erm-dashboard-v2.md) | Dashboard v2: RRR >= 15 watchlist, IRR/RRR/LoA/LoR averages, EMV totals, trajectory graph, filters | The visible payoff; where "measurable and comparable over time" lands |
| 5 | [PLAN-27](PLAN-27-erm-objectives-pillars.md) | Objectives registry (strategic/standard/departmental), risk_context, pillars admin | Assessment-context metadata; enriches filters and identification, nothing blocks on it |
| 6 | [PLAN-28](PLAN-28-erm-external-context.md) | External context: emerging risk inbox + AI horizon scan with LIVE web-search grounding (Anthropic server-side web search tool, cited sources, domain allowlist; knowledge-only fallback for other providers) | Differentiator; revised 2026-07-18 from knowledge-only to live grounding after confirming API support |

**Round 6 execution order: 23 -> 24 -> 25 -> 26 -> 27 -> 28.** 25/26/27 are
mutually independent once 23 is in; 28 last. Round 6 is independent of the
open PLAN-16/17 and PLAN-20/21/22 items, with one interaction noted in
PLAN-23 Step 6: when PLAN-21 (AI controls catalogue) executes, its seeds
should also set `p2st2_category` on canonical_controls.

**Round 6 integration map (assessed 2026-07-18).** Touchpoints the
executor must respect; each is specified inside the relevant plan:

- Auto-elevation (core/event_handlers.py `_insert_erm_risk`) bypasses
  create_enterprise_risk; PLAN-23 Step 5b patches it so GRID findings,
  BCM risks/incidents, and Sentinel breaches get risk_ref/IRR/RRR at
  insert time, not at next restart.
- T1.3 effectiveness engine keeps cascading into
  recompute_residual_for_risk; once a risk has any ICE score, tier 1 of
  the new ladder makes that cascade a no-op for it (documented in
  PLAN-23). DECIDED 2026-07-18: ORM converges onto the ICE scale.
  PLAN-21's AIMS/ORAAT engine adopts ICE percent input from day one (see
  its Alignment section; legacy ORAAT 1-10 maps as 100 - score*10);
  ORM RCSA's 1-5 scale converts in the queued PLAN-29 (Round 7), written
  after Round 6 has bedded in.
- DECIDED 2026-07-18: appetite compares RESIDUAL exposure,
  COALESCE(rrr, likelihood*impact) vs max_score, shipping as PLAN-26
  Step 1b (dashboard stats, get_appetite_status, and the two
  event-handler checks). Unassessed risks behave identically because
  rrr defaults to IRR, so the switch is non-disruptive on day one.
- Evidence per control flows through the existing evidence_links
  machinery (entity_type canonical_control, plus the grid/aria
  auto-mirror); PLAN-24 adds a per-control evidence count chip and
  deep-link, no new upload surface.
- BU federation: standalone new tables (erm_pillars, erm_objectives,
  erm_emerging_risks) carry business_unit_id; child tables (CFs,
  treatments, score history) scope through risk_id. New endpoints mirror
  the bu_scope_ids pattern from the risk detail endpoint.
- Exec dashboard, heatmap, and band badges remain inherent/band-based
  lenses alongside the new RRR posture (PLAN-26 documents coexistence to
  avoid the partial-migration trap the framework slice fought).
- PLAN-28's grounded scan depends on core/ai_client.py; a separate
  background task is replacing that file's retired default model id, and
  the scan pins its own ERM_SCAN_MODEL either way.

## Round 6 status: PLAN-23 through PLAN-28 ALL DONE - Round 6 complete

| Plan | Status |
|---|---|
| [PLAN-23](PLAN-23-erm-cf-ice-engine.md) | DONE (2026-07-19) |
| [PLAN-24](PLAN-24-erm-assessment-workspace.md) | DONE (2026-07-19) |
| [PLAN-25](PLAN-25-erm-cf-treatments.md) | DONE (2026-07-19) |
| [PLAN-26](PLAN-26-erm-dashboard-v2.md) | DONE (2026-07-19) |
| [PLAN-27](PLAN-27-erm-objectives-pillars.md) | DONE (2026-07-19) |
| [PLAN-28](PLAN-28-erm-external-context.md) | DONE (2026-07-19) |

## Round 7 (queued, plan not yet written)

| Plan | What | Trigger to write it |
|---|---|---|
| PLAN-29 | ORM RCSA converges onto the ICE scale: control_effectiveness 1-5 becomes ice_score percent (map 1..5 -> 10/30/50/70/90), residual formula becomes IRR x (100 - ice)/100, RCSA UI dropdown swaps to the shared ICE selector | Decided 2026-07-18. Write after Round 6 (23-26 minimum) is live and validated in daily use, so ERM and ORM/AIMS converge on one proven convention |

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
