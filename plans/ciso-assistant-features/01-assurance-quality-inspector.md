# 01. Assurance quality inspector

**Status:** Implementation proposal, 2026-10-07. **Priority:** first CISO-inspired slice. **Owner:** shared assurance read model over existing ARIA, GRID, ERM, BCM and Vault records; each specialist module remains the write owner. **Inspiration:** CISO Assistant's [X-rays](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/features/x-rays.md).

## User journey

A compliance manager opens **Needs attention**, sees a small set of ranked, deduplicated issues, selects “Compliant control has no current proof”, reads the exact rule and source versions, and chooses **Fix in GRID** or **Request evidence**. After the owning record is corrected, reevaluation closes the issue. A reviewer can explain a false positive or an accepted exception without changing the underlying source state. The same issue appears on the control and in a pre-report quality sweep, not as three separate tasks.

## Current-state anchor and boundaries

- `oneforall/core/advisor.py` already generates daily signals such as expiring evidence and overdue audits. `oneforall/modules/launcher/my_work_service.py` aggregates action sources. Canonical controls and `control_effectiveness_scores` are in `oneforall/database.py`; Vault has evidence items/links and a current-proof plan.
- [Evidence Vault](../../design/evidence-vault/PLAN.md) owns search, versions and verification. [PLAN-37](../PLAN-37-connected-compliance-experience.md) owns scoped relationship resolution and the event contract. This inspector computes *quality observations*; it does not own evidence, control status, or a second task board.
- PLAN-37 records title exposure in Related Items and topbar search. Close or isolate those paths before any cross-module issue list. Local Vault Phase 1a is not yet a shipped prerequisite; recheck the relevant files and PostgreSQL behavior.

## First release: four explainable rules

| Rule | Trigger | Severity and interpretation | Fix owner |
| --- | --- | --- | --- |
| `proof_missing` | A reviewed compliance claim requires proof but has no current, visible, accepted evidence version directly or through its control | Warning; an attachment by itself is not a compliant verdict | GRID/ARIA assessment, or Vault request |
| `proof_stale` | A claim relies solely on expired, rejected, superseded or integrity-failed proof | Warning, or error if the source claim's own rules require live proof | Vault version/review and source assessment |
| `risk_basis_unexplained` | ERM residual exposure is lower but the recorded treatment/control basis is absent, stale or unreviewed | Review prompt first; do not label calculated ICE scores invalid without checking the ERM convention | ERM risk/treatment |
| `owner_or_review_missing` | A required audit, BCM exercise or assessment review is overdue and has no accountable owner/next action | Warning; reuse an existing task or request | Source module / My Work |

After [formal acceptance](04-risk-acceptance-and-exceptions.md) ships, add `risk_acceptance_expired` and `risk_acceptance_basis_changed`. Start with rules whose semantics can be agreed with module owners; keep applicability and evidence requirements configurable by claim type. Do not apply one blanket rule to every document or control.

## Design and build slices

1. **Define the claim contract.** Inventory the actual ARIA and GRID status values, evidence link paths, Vault version/currentness rules, ERM score/treatment fields, BU semantics and owning routes. Specify `applicable`, `implemented`, `tested`, `evidenced`, `reviewer_accepted`, and `unknown` separately. Record each rule's input fields, effective date and severity.
2. **Build a scoped evaluator.** The input is actor + organization + permitted BU/module scope + optional source record. Resolve every source through the permission-checked service from PLAN-37; no unfiltered aggregate or title query. Return a stable issue key `(org, rule_id, rule_version, source_type, source_id, source_fingerprint)` plus source IDs/versions, evaluated time, severity, explanation and safe deep link. A changed fingerprint opens a new review obligation; a unchanged run is idempotent.
3. **Start without an all-record full scan on page load.** Evaluate one record on its detail page and a bounded, paginated organization queue from indexed source candidates. Add scheduled incremental evaluation after the source events are dependable; a failed evaluation leaves the previous result marked stale rather than silently green. Choose derived query versus materialized issue table after measuring the 500/5,000-evidence-item cases.
4. **Add the action surface.** A compact “Needs attention” view groups by severity and rule, offers filters/saved views, shows the reason and source date, and opens the owning record. The Command Centre shows a scoped count and top actions. My Work links to the same issue only when an accountable action exists; the advisor can summarize without recomputing truth.
5. **Review false positives.** A dismiss/exception record contains issue fingerprint, actor, reason, optional expiry and reviewer; permission-checked source changes or expiry reopen it. It never changes the underlying compliance state or hides an issue from an authorized oversight view without a visible reason.
6. **Use as a report gate.** Before an audit/board pack, show unresolved errors and warnings and require an authorized reviewer to acknowledge them. Do not auto-block all exports until rule quality and false-positive rates have been reviewed with pilot users.

## Acceptance outcomes

- A reviewer can trace every issue to the exact source and evidence version and open the correct owning form; closing the source gap closes the same issue on reevaluation.
- Wrong-org, wrong-BU and missing-module users receive no issue count, title, link or existence signal for an inaccessible record, including exports and notifications.
- Repeated evaluation does not create duplicate issues/tasks. A source read failure is visible as **unknown/stale**, not “no issues”.
- At 500 and 5,000 evidence items, the list remains paginated and usable; keyboard, screen reader, 200% zoom and reduced-motion paths are included in release acceptance.
- Measure issue precision, median time to resolve and reopened-after-change rate in a pilot before widening the rules.

**Not in the first release:** AI-generated compliance verdicts, automatic remediation, a new evidence store, a new task engine, and a hardcoded claim that every compliant item must have the same kind of attachment.
