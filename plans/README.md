# Execution Plans — ranked by leverage

Each PLAN-*.md in this folder is self-contained: goal, exact files,
ordered steps, edge cases, and verifiable acceptance criteria. They are
written to be executed top-to-bottom without needing to ask questions.

## Ranking (leverage = impact ÷ effort, pre-launch weighting)

| Rank | Plan | What | Impact | Effort | Why this rank |
|---|---|---|---|---|---|
| 1 | [PLAN-01](PLAN-01-audit-log-tenant-isolation.md) | Audit log tenant isolation | Cross-org data leak visible to customers | ~half day | Confirmed live security/privacy bug; customers already noticed it |
| 2 | [PLAN-02](PLAN-02-dependency-vulnerabilities.md) | Patch starlette CVEs, pin floating deps | Closes 2 GitHub-flagged vulns; reproducible builds | ~half day | Known CVEs on the serving stack of a compliance product |
| 3 | [PLAN-04](PLAN-04-repo-hygiene.md) | Untrack dev DB, add .gitignore, fix committer identity | Repo contains a database with password hashes; one `git add .` from leaking demo/pentest docs | ~1 hour | Cheapest insurance in the list |
| 4 | [PLAN-03](PLAN-03-task-workflow-race-conditions.md) | Task board + ERM workflow races | Last open HIGH from the bug audit; data corruption under concurrent users | ~1 day | Matters more as user count grows post-launch |
| 5 | [PLAN-05](PLAN-05-governance-t12-unified-controls.md) | Governance Graph T1.2: canonical controls + risk_controls bridge | Unlocks T1.3 effectiveness engine and T1.4 residual engine (the roadmap's core differentiators) | ~1-2 weeks | Highest strategic value, largest effort — do after the safety items |

## Round 2 — functionality, cross-module communication, and UX (PLAN-06..10)

Written after a functionality/UX exploration pass. Key finding grounding
this set: **nothing in the platform can navigate to a specific record** —
global search, the workflows entity helper, and notifications all link to
module roots. Fixing that (PLAN-06) multiplies the value of everything
that follows.

| Rank | Plan | What | Impact | Effort | Why this rank |
|---|---|---|---|---|---|
| 1 | [PLAN-06](PLAN-06-entity-deep-links-command-palette.md) | Entity deep links + Ctrl+K palette | Search, notifications, workflows, and every future feature become navigable; platform-wide UX lift | ~2-3 days | The enabler: three other plans depend on its `?open=type:id` convention |
| 2 | [PLAN-07](PLAN-07-related-items-cross-module-linking.md) | Related Items panel + manual linking API | cross_module_links becomes user-facing; the "one brain" experience in every drawer | ~2-3 days | The explicit cross-module-communication ask, made tangible |
| 3 | [PLAN-08](PLAN-08-governance-timeline.md) | Governance Timeline page | Cross-module causality view; strong demo value | ~1-2 days | Cheapest feature in the backlog — the events table already records everything |
| 4 | [PLAN-09](PLAN-09-morning-briefing-advisories.md) | Proactive daily briefing (advisories) | First proactive AI surface; CGRCO opens the app to findings, not silence | ~2-3 days | Differentiator vs every reactive-AI competitor; math-first so near-zero AI cost |
| 5 | [PLAN-10](PLAN-10-evidence-confidence-score.md) | Evidence confidence score | Trust signal auditors notice; feeds the T1.3 effectiveness engine | ~1-2 days | Solid but standalone; least coupled to the rest |

**Round 2 execution order: 06 → 07 → 08 → 09 → 10** (06 unlocks 07/08;
09 and 10 are independent and can be reordered freely).

**Interleaving with Round 1:** land Round 1's safety items (PLAN-01, 02,
04 and PLAN-05 Phase 0) before starting Round 2. PLAN-08 should not
merge audit_log data until PLAN-01 is deployed. PLAN-05 (T1.2) and
Round 2 touch different files and can proceed in parallel.

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

| Rank | Plan | What | Impact | Effort | Why this rank |
|---|---|---|---|---|---|
| 1 | [PLAN-11](PLAN-11-t13-control-effectiveness-engine.md) | T1.3 Control Effectiveness Engine | Effectiveness becomes derived and living — the roadmap's own "single highest-leverage delivery"; feeds T1.4 and the health score | ~1 week | Core differentiator; requires PLAN-05 first |
| 2 | [PLAN-12](PLAN-12-t14-residual-risk-engine.md) | T1.4 Unified Residual Risk Engine | Ends the ERM-vs-ORM residual contradiction; residuals react to control reality with auditable provenance | ~3-4 days | Completes approved Tier 1; requires PLAN-11 |
| 3 | [PLAN-13](PLAN-13-drift-detection-regulatory-inbox.md) | Drift detection + Regulatory Inbox (T2.2 + T4.2-lite) | Regulatory changes become tracked work items automatically | ~3-4 days | Independent of Tier 1 — can ship any time, even first |

**Round 3 execution order: PLAN-05 → 11 → 12, with 13 slotted anywhere
(it has no dependencies).**

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
| 1 | [PLAN-18](PLAN-18-security-round-2.md) | Org-enforced MFA, SBU data scoping, upload magic-byte checks | Closes the three real remaining security gaps; SBU scoping is the multi-tenant interior wall | ~3-4 days | Security asked first; SBU isolation is customer-visible |
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
