# Authority intelligence and auditor registers

**Status:** Proposed implementation plan, 26 October 2026. No application behavior or production configuration changes are made by these documents.

## Outcome

ThemisIQ detects changes in approved external sources without asking an AI model to decide whether a law or standard changed. Specialists review captured source differences, interpret their applicability, and connect approved findings to controls, AI uses and risks. An auditor can then request a complete, reproducible register of documents and evidence for a selected framework. AI specialists can maintain and export the AI systems and AI risk registers from the same records they use for day-to-day governance.

| Plan | Owner and scope |
| --- | --- |
| [01 Source accuracy](01-source-accuracy.md) | Shared authority registry, guarded capture, deterministic comparison, grounded interpretation, human review; Sentinel, Governance and ERM consumers |
| [02 Registers and exports](02-registers-and-exports.md) | Framework document/evidence register, AI systems register, AI risk register, in-app maintenance, reviewed spreadsheet import and complete auditor exports |
| [03 Delivery and acceptance](03-delivery-and-acceptance.md) | Dependencies, ordered slices, permission and data-quality gates, tests, pilot and release checks |
| [04 Implementation and release](04-implementation-and-release.md) | Built scope, operational gates and deployment handoff; distinguishes merged code from live approval |

## Ownership decision

- **Governance / ARIA** owns the selected framework, controls, governed policies and the framework register entry point. **Evidence Vault** owns artifact bytes, immutable versions and links; a link alone is not an accepted audit proof.
- **GRID Audit** owns audit-specific testing and verdicts. It can open the same framework register with an audit filter and build a reviewed audit pack; it must not maintain a second document register.
- **AI Governance** owns AI-use inventory, specialist review and decisions. **Governance applications** own application identity, **ORM AIMS** owns AI risk assessment and treatment, and **ERM** owns enterprise exposure/acceptance. AI Governance shows a joined register, not duplicate risk rows.
- **Platform Reports** owns frozen exports, sign-off, sharing, retention and download audit. Module pages provide contextual entry points. A saved report's data is a scoped snapshot, not a live query masquerading as a historical record.
- **Sentinel** owns privacy jurisdiction review and operational rule cards; **Governance** owns regulatory updates and control-impact review; **ERM** owns emerging-risk triage. The shared source service owns capture provenance, not legal conclusions.

## Existing work to reuse

The checked code baseline is master `c88907a8` plus the isolated login branch; it must be reconciled with the target branch before implementation. Sentinel already has pinned sources, per-organization cadence, stored raw/text hashes and DPO review. The AI client has provider web-search citation metadata, Governance has a manual regulatory inbox and exact-reference matching, and ERM has a web-grounded horizon path. ARIA has a controls workbook and policy intake; Vault has versions and reviewed links; AI Governance has application-linked profiles; ORM has AIMS assessments and risks; Reports has a shared XLSX/PDF kit and saved-run controls. None of these is, by itself, the three requested complete registers.

## Workbook examples inspected

- The supplied IMS document-control workbook contains 129 numbered register entries (counted from the Document Register sheet on 27 October 2026), including current and superseded records. The earlier estimate of 103 was incorrect. Its owner, dates, approval and control-reference columns guide reconciliation, but its free-text references are not automatically trusted mappings. Its filename says v4.1, the register banner says v3.9, and the revision sheet ends at v3.7; an import preview flags these as conflicting source metadata.
- The AI systems workbook contains eight inventory rows. Its cover and inventory display different version labels. Import preview must flag that conflict.
- The AI risk workbook contains ten risks and nine treatment rows. One risk lacks a treatment row; at least one stated risk level conflicts with the workbook's scoring legend. Import must flag discrepancies without silently recalculating or declaring the spreadsheet authoritative.

The original workbooks are examples and potential import data, not instructions, proof that their status is current, or approved ISO text. Never seed them into another tenant.

## Non-negotiable accuracy rules

1. A fetch failure is **unknown/error**, never unchanged. Raw-byte change, extracted-text change, potentially relevant change, and specialist-approved legal or control impact are distinct states.
2. A model cannot create a source-change fact, approve applicability, alter a legal deadline, mark a control effective, accept evidence or sign an auditor register. A citation URL or matching domain does not prove a claim.
3. Every AI claim offered as source-grounded must identify the exact permitted capture and passage, its hash, retrieval time and source rights. Unsupported claims are removed or rendered **cannot verify**.
4. Every exported row is derived from an authorized source record or clearly marked as manually entered/unverified. Missing data is blank or `Not recorded`, never invented, zero or approved by default.
5. A register includes **every authorized detail row** in scope. Large exports run in the background or split workbook sheets; they do not silently apply a 60-, 100- or 200-row display limit.

## Relationship to existing plans

This programme extends [Sentinel living law](../2026-10-sentinel-living-law.md), [Governance regulatory inbox](../PLAN-13-drift-detection-regulatory-inbox.md), [ERM external context](../PLAN-28-erm-external-context.md), [AI Governance integration](../ai-governance/01-domain-and-integrations.md), [policy intake](../2026-10-governance-rework/18-policy-intake-and-document-composition.md), [Evidence Vault assurance](../2026-10-governance-rework/02-evidence-vault-and-assurance.md) and [platform reporting](../2026-10-governance-rework/04-platform-truth-navigation-and-reports.md). Those plans remain authoritative for each module's own workflow. This programme specifies the shared capture and the three cross-module report products; it does not reset their current implementation ledgers.
