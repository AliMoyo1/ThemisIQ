# Evidence Vault current proof and policy layout check, 2026-11-08

Branch `claude/vault-current-proof-policy-layout`, from `master` 7df569a0 (PR 47 merge). The owner asked in chat on 2026-11-08 to go with the recommendations and build items 1 and 2 of the "what's next" answer. This is chat confirmation, not sign-off.

## What the code already settles (checked before building)

The Evidence Vault design plan (`design/evidence-vault/PLAN.md`) lists five Phase 0 decisions as open. Later plans (governance rework 02 and 05, `modules/evidence/proof.py`) already built three of them, so they are recorded, not rebuilt:

| Phase 0 question | Already in the code | Where |
| --- | --- | --- |
| What counts as current proof for coverage | Three separate measures: live link, current proof (current version, not expired, not turned down by a reviewer) and accepted. The Vault coverage panel, the Command Centre "without proof" card and the Vault claim figures all use current proof. | `proof.current_sql`, `routes.coverage_for`, `first_screen.proof`, `claim_metrics` |
| Links when a new version is added | **Add a new version** exists in the drawer. The new version gets a proposed link for every live link of the old one whose record the uploader may open; it waits for its own review (an accepted verdict is never inherited). The old version keeps its links as history and is marked superseded. | `proof.carry_forward`, `api_evidence_upload` `replace_id` |
| Expiry reminders | Stay on the Task Board plus the email outbox (30, 7 and 1 days). | `modules/evidence/scheduler.py` |

My recommendation said "a new version takes over the live links". The built behaviour is stricter (links are proposed and wait for review), so it stays.

## 1. Current proof everywhere, and the module rule

### 1a. Module rule for who can open a file (built here)

**Gap:** `evidence_scope_sql` decides visibility by organization and business unit only. A person in the right unit can open a file linked only to records in a module they cannot use, for example a breach record in Privacy, or a DPIA when they lack DPIA access.

**First attempt, narrowed during the build:** applying the rule to every module hid proof that people attach while answering GRID audit questions from My Work, because respondents do not hold a GRID licence (`grid.assignment.respond` is open to every role). Two existing GRID assignment tests caught it.

**Decision (chat confirmation, not sign-off):** a file linked to a **Privacy record or AI impact assessment** (`RESTRICTING_MODULES = ("sentinel",)`) is visible only to someone who may open at least one kind of record it is linked to, or who uploaded it. Links to other modules never hide a file. A file with no live link follows the Vault's own permission (organization and unit), as today.
- Why: evidence attached to a breach, DPIA, data subject request or processing record can hold personal data; the Privacy capabilities are the boundary its module already enforces.
- Cost: someone without breach access no longer sees breach-only files they did not upload. A link to a kind the registry does not know neither grants nor hides.
- Limit: the rule is per kind of record (module licence plus the owning capability), not per record. The record's own unit is not rechecked here; the file's own unit scope still applies.
- How to change: `modules/evidence/scope.py` `RESTRICTING_MODULES` (add a module key to restrict it the same way) and `_module_rule_sql`.

### 1b. Counts that still include lapsed files (built here)

These figures counted every live link, including archived items, replaced versions and expired files, and ignored the viewer's scope. They now count current proof the viewer may open, with the same definition as the Vault:
- ARIA framework page: evidence count per control.
- ARIA frameworks list: evidence count per framework.
- ERM risk controls: evidence count per linked canonical control.
- Command Centre (scoped view): evidence and expiring counts use the Vault scope rule, and the evidence count leaves out archived and replaced items, as the Vault list does.

### 1c. ERM risk control routes skipped the unit check (security fix, found while doing 1b)

`GET/POST /erm/api/risks/{id}/controls`, `DELETE /erm/api/risks/{id}/controls/{control}` and `GET .../suggest-ice` did not check that the risk is in the caller's business unit, unlike the contributing factor routes beside them. A unit-scoped user could list, link or unlink controls on another unit's risk by ID. All four now call `_check_risk_scope` (404 for an out-of-scope risk, as elsewhere).

## 2. Layout check for composed policies

**Gap (plan 18, P3 gate):** composing an imported DOCX (new cover, new body, cleared headers) has a PDF preview and a "compared" checkbox, but nothing tells the author what the recompose lost: footnotes whose text is gone, cross-references to removed text, a landscape section folded into portrait, a contents table with stale page numbers, missing tables, images or links.

**Research (GitHub, 2026-11-08):**
- `JSv4/Python-Redlines` (MIT) and its engine Docxodus: tracked-change redlines; ships .NET binaries and compares text, not layout loss. Rejected: native binary dependency on the VPS, wrong question.
- `docxaudit` (PyPI): renders a DOCX and compares with a PDF; small, unclear maintenance. Rejected: adds a renderer path we already have (LibreOffice preview).
- `docx2python`: extraction only. `Ignema/docx-compare`, `codeterrayt/docx-comparison-tool`: plain text diffs.
- Chosen: a small structural inventory in-house on python-docx and lxml, already dependencies, using parts python-docx has already parsed. No new package, no network, no provider.

**Built:** `modules/aria/policy_layout_check.py`. Composition takes an inventory of the retained source blocks and of the candidate, and reports:
- **Lost** (blocks until acknowledged): footnote or endnote references without their text, cross-references or internal links to removed text, a page layout change (orientation or page size) that no longer applies, fewer tables, missing images or external links, a header or footer kind that disappeared without the "clear headers" choice.
- **Check** (blocks until acknowledged): a contents table (update it in Word, page numbers were generated before composing), other fields that update on open, tracked changes or comments left in the text, a first-page header that now sits on the new cover.
- **Changed by your choice** (shown only): headers cleared, cover or body replaced, blocks excluded.

**Decision (chat confirmation, not sign-off):** a candidate with any Lost or Check finding is not created until the author records a reason (10 to 500 characters). The reason, who gave it and when are stored in the candidate's renderer manifest, whose hash travels with the version into approval. Why: plan 18 says any loss is shown before confirmation and blocks publication. Cost: one more step for documents with complex layouts. How to change: `policy_layout_check.BLOCKING`.

The rendered look is still approved by people: the existing PDF preview, the compared checkbox, the independent approver, and the customer pilot.

**Screen:** the import page shows a "Layout check" section under "Create review candidate": each finding with a chip (Lost, Check in Word, Your choice or a note), and, when something needs review, a reason box and "Create candidate with these findings". A refused reason stays in the box for editing. After a reload the findings and the recorded reason are still shown with the candidate.

**Safety:** findings describe and count; they never quote document text. A field name is kept only when it is a short keyword (`[A-Z][A-Z0-9]{0,19}`), otherwise it is recorded as OTHER. Parts python-docx has not parsed (footnotes, endnotes) are read with an lxml parser that resolves no entities and makes no network call; the archive was already validated by `policy_storage.validate_docx`.

## Evidence

| Check | Result |
| --- | --- |
| Module rule (`tests/test_evidence_privacy_link_rule.py`): employee, DPO, privacy analyst, GRID respondent, uploader, list, item, download and stats | 6 passed |
| Counts and ERM unit check (`tests/test_evidence_counts_current_proof.py`) | 7 passed |
| Layout check (`tests/test_policy_layout_check.py`): clean cover, lost landscape section, broken cross-reference, contents table, missing footnote text, first-page header, tracked changes, no document text in findings, reason rules, refusal then acknowledgement through `create_candidate` | 15 passed |
| Existing Vault, GRID, scope and Themis groups after the first, too-wide rule | 5 failed (two GRID respondent cases, three tests using a made-up role); all pass after narrowing |
| Policy intake, drafts, build, workflow routes, versions, gate, storage | 118 passed |
| Policy import browser journeys, including the new layout check journey (refusal, short reason kept, reason accepted, shown after reload) | 5 passed; light and dark screenshots checked |
| Related SQLite groups (Vault, GRID, ERM, ARIA policy, dashboard, Command Centre, CSP, platform guide, Sentinel, registers, effectiveness, onboarding) | 1043 passed |
| Browser groups (Vault, GRID, ERM, Command Centre, frameworks) | 127 passed |
| PostgreSQL lane `tests/test_postgres_init.py` (disposable PG container) | 100 passed (16 minutes); new `test_evidence_privacy_link_rule_runs_on_real_postgres` and the two Vault PG tests: 3 passed |
| Capability inventory check, `git diff --check`, JS syntax, JS unit tests | clean; 4 passed |

## Change log

- 2026-11-08: branch created from master 7df569a0; plan written after checking the code.
- 2026-11-08: module rule built, narrowed to Privacy and AI impact assessment links after GRID respondent tests failed; counts moved to current proof; ERM risk-control unit check added; layout check built with screen and tests.
