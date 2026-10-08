# 04. Formal, expiring risk acceptance and exceptions

**Status:** Implementation proposal, 2026-10-07. **Priority:** after ERM decision scope and approval contract are settled. **Owner:** ERM risk and treatment; shared approval capability from [VerifyWise decision gates](../verifywise-features/03-approval-gates.md). **Inspiration:** CISO Assistant's [formal risk acceptance](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/concepts/risk-assessments.md).

## User journey

A risk owner selects **Request acceptance** from an ERM risk or contributing-factor treatment. The form explains current and residual exposure, appetite position, compensating controls, missing evidence and expiry. An authorized approver reads a frozen snapshot, approves with conditions or rejects it. The risk page distinguishes **accept proposed**, **approved until [date]**, **expired**, **reopened after change**, and **not accepted**. The owner is prompted to review before expiry. Board reports link to the exact decision, not merely a treatment dropdown.

## Existing anchors and gap

`erm_enterprise_risks` has owner, reviewer, treatment, status and review date. `erm_cf_treatments` permits `treatment_option='accept'`, and `update_treatment()` warns when assurance is below 70%; ERM also has workflow history, appetite thresholds and board packs. In the reviewed modules, those fields do not constitute an immutable, time-limited management approval of exposure. Do not recast historic `accept` values as approved decisions. [PLAN-37](../PLAN-37-connected-compliance-experience.md) already proposes versioned decisions, events and My Work projections.

## Policy decisions before schema work

1. Who may approve by risk category, exposure band and amount, and can requester and approver be the same person? Default to separation for consequential acceptance; make delegation explicit and audited.
2. Is acceptance at whole-risk level, per contributing factor, or both? The pilot should choose one unit and show linked per-CF treatments without double-counting exposure.
3. Which figure is authoritative: current risk, expected residual risk after planned controls, or both? Freeze all relevant numbers and explain their meaning; a future-state residual estimate must not masquerade as today's exposure.
4. What maximum duration and re-review triggers apply? Set tenant policy and a bounded expiry; do not hardcode one universal legal rule.

## Design and build slices

1. **Decision model.** Add a tenant-owned acceptance request/decision record keyed to the ERM source risk and its version/fingerprint. Capture reason, alternatives considered, current and residual scores, appetite comparison, linked effective controls/evidence version IDs, proposed conditions, owner, approver, start and expiry dates, scope, decision and timestamp. Keep append-only transition history. A request is not a risk status change.
2. **Approval flow.** The owner submits; a permitted approver can approve, reject or return with conditions. Revalidate organization, BU, source version, approver capability and separation rules on each transition. Use optimistic concurrency and one transaction for decision/history; emit any downstream event after a successful source transaction through PLAN-37's dependable event path.
3. **Derived display state.** `proposed`, `approved`, `rejected`, `expired`, `revoked`, `needs_re_review` are computed from the latest valid decision, expiry and current source fingerprint. Define precedence for multiple historical decisions. Keep legacy `risk.status='accepted'` visible as **legacy/unverified** until a reviewed migration or reapproval; never auto-backfill an approver.
4. **Review triggers and actions.** Score/appetite changes, failed/removed controls, serious linked incident, changed business scope or expiry reopen the decision for review. Project one due action into My Work and a direct risk-page banner. The [assurance inspector](01-assurance-quality-inspector.md) flags expired or unsupported acceptances without altering the risk score.
5. **Reports and exports.** Board packs show accepted exposure separately from untreated and proposed exposure, with approver, condition and expiry. An export captures the decision and source manifest it relied on; later changes do not silently rewrite past packs.
6. **Exceptions after acceptance is stable.** Reuse the same decision infrastructure for a scoped, temporary policy or control exception linked to its ARIA/GRID source, compensating control, owner, approver and expiry. A policy exception is not a waiver of legal obligations and cannot grant access to its linked evidence.

## Acceptance outcomes

- Selecting `accept` in a treatment never creates an approved risk acceptance. Only a permitted, recorded decision can do that.
- Expired, revoked or materially changed decisions no longer present as current approval, and a reviewer sees the reason and previous snapshot.
- Wrong-org/BU users cannot view the request, approver name, source risk or existence via list, direct URL, notification or board export.
- Request and decision histories survive concurrent review, retries and report regeneration without duplicate approvals.
- Board users can distinguish today's current exposure from a planned residual target and open the exact signed decision.

**Not in the pilot:** silent migration of historical accepted statuses, automated approval by AI, and a separate enterprise-wide exceptions register with its own risk scoring.
