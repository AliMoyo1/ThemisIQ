# AI Governance and connected assurance rework

Status: planning only. This file tracks the requested design work. It authorizes no application change or production release.

## Objective

Make ThemisIQ a specialist governance workspace that connects AI use reviews, privacy, audit, risk, continuity, controls, evidence, actions, and reports without creating a second copy of any source record.

## Baseline and constraints

- Planning began on 2026-10-14 after a read-only review of the clean `codex/ai-governance-nav` worktree at `f855c9dab845f2f1668fefa52de187cb3531c0c5`. The user's VPS output reported release `f770d3309b9936ede2633c3ae891a62845638916` healthy. A later production change has not been checked here.
- The main checkout already contains modified plans and untracked work. This plan set adds new files and leaves those existing changes untouched.
- Older October 7 to 12 plans are historical design and implementation records. Their completion labels are not evidence of the current production state.
- AI Governance serves governance specialists. Staff training belongs in a separate staff-facing project. ThemisIQ retains its training history until a deliberate migration and may consume a minimal completion signal later.
- External Google or Microsoft Forms export, reviewed by a specialist, is the first proposed requester path. A bounded invitation form is a later decision.

## Documents and ownership

1. [Programme index](plans/2026-10-governance-rework/README.md) records the decisions, source-of-truth map, dependencies, and relationship to existing plans.
2. [AI Governance specialist workspace](plans/2026-10-governance-rework/01-ai-governance-specialist-workspace.md) defines intake, precedent review, decision work, dashboards, external response, monitoring, roles, and literacy separation.
3. [Evidence Vault and assurance](plans/2026-10-governance-rework/02-evidence-vault-and-assurance.md) defines a scalable library, proof semantics, versions, requests, search, and module reuse.
4. [Specialist module journeys](plans/2026-10-governance-rework/03-specialist-module-journeys.md) defines improvements for Governance, ARIA, GRID, BCM, Sentinel, ERM, ORM, and vendors.
5. [Connected platform and reporting](plans/2026-10-governance-rework/04-platform-truth-navigation-and-reports.md) owns shared dashboards, My Work, search, relationship views, report snapshots, AI assistance, and trust repairs.
6. [Delivery and acceptance](plans/2026-10-governance-rework/05-delivery-and-acceptance.md) sequences the slices and states the security, PostgreSQL, user, and release evidence each needs.
7. [Email notifications and delivery](plans/2026-10-governance-rework/06-email-notifications-and-delivery.md) covers the temporary Gmail sender, current email defects, role and module touch points, templates, deliverability, a durable outbox, and service-identity migration.

## Change log

- 2026-10-14: Reconciled current source with the AI Governance, Vault, PLAN-37, VerifyWise, and CISO Assistant plans. Created the rework documents. No code, migration, configuration, test, commit, push, or deployment was requested or performed.
- 2026-10-14: Added the email delivery plan and linked it into the programme. Reviewed the existing transport, schedulers, role notifications and current Google sender guidance. No mailbox was configured or email sent.
