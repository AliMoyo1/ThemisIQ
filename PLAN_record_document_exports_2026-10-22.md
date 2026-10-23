# PLAN: real, permission gated exports of one DPIA, one continuity plan and one AI impact assessment (2026-10-22)

> Integration note: this is the source worktree's design and verification record. The code has been ported into `codex/claude-integration-2026-10-22`; results below do not verify the integration branch. The integration ledger records the remaining work and release state.

Worktree `.claude/worktrees/kind-cannon-4d360f`, branch `claude/kind-cannon-4d360f`. Nothing is committed or pushed.
App code lives in `oneforall/`. Tests run from `oneforall/` with the repo `.venv` python, one pytest session at a time, the backend
files and `tests/ui` as separate sessions.

This resolves decision D11 and gap G8 of `PLAN_report_exports_2026-10-21.md` (in worktree `sad-albattani-5255ea`, not copied here):
the three record level previews the owner has seen become real downloads on the shared report kit.

Owner additions, mid task (verbatim): "also make sure the reports can link to other relevant documentations. No silos" and then
"they should link via the evidence repository". Read as: other documentation is reached through the Evidence Vault (its own links, each row
opening the file in the Vault), and the records a record is connected to are listed too. D14 says what was built.

Status key: [ ] open, [~] in progress, [x] done, [!] blocked or left on purpose (reason given).

## 0. Starting point (how this worktree was started from the uncommitted kit)

`core/report_kit/` and its adapters are UNCOMMITTED in `sad-albattani-5255ea` (same base commit `bfde22d6` as this worktree). The 62 changed
or new files of that worktree (not its ledger) were copied here byte for byte (SHA-256 checked, 0 mismatches) and STAGED, so that plain
`git diff` in this worktree is only this task's change. Baseline tree object: `1885110e86c03b726e25dd2713ca8faeec728328`
(`git diff 1885110e86c03b726e25dd2713ca8faeec728328` is this task's change including new files that were `git add -N`).
When the owner commits the kit branch, this task's patch applies on top of it (the hand-over note names the patch file).

Sibling notes read: `report-exports-handover.md`, `report-samples/README.md`, `record-documents/builders/*` (the preview builders), and
`dpia-form-handover.md` (the session that fixes O12, the DPIA form dropping what a person types). That fix is a separate, uncommitted branch
(`suspicious-swartz-8c47fe`): it stores `description`, `mitigations`, `owner` and a new `due_date` column. This task reads what `get_dpia` returns and
shows a field when it is stored, so the document needs no change when that fix lands (the owner and due date tiles appear then). It also confirmed
that the Vault is the way to link documents (`entity360`), and that a DPIA's risk is `overall_risk`, never `risk_level`.

## 1. Decisions taken on the owner's behalf (chat confirmation, NOT sign off)

### D12. Each record document is a route gated like the record, read through the module's own scoped read, audited
- Decision: `GET /sentinel/api/dpias/{id}/document` needs `sentinel.dpia.manage` and reads through `_scoped_or_404`;
  `GET /bcm/api/plans/{id}/document` needs `module.bcm.access` and reads through a new `_plan_or_404`;
  `GET /ai-governance/api/assessments/{id}/document` needs `ai_assessment.view` and reads through `assessments.get_assessment`.
  `?format=pdf` (default) or `xlsx`. A record of another unit answers 404 exactly as a missing one. Every download is written to the audit trail
  with the record's reference and the format (never its title, which can name people), and answers through `core.report_kit.respond.download`.
- Why: a record export is a copy that leaves the application; it must not open more than the record's own page opens.
- Cost: a role that can open the module but not the record (a risk owner for a DPIA) gets 403 on the document, as on the record.
- Change: the capability and the read function sit in each route.

### D13. Tier: operational
- Decision: the three are operational reports (working record documents). The board tier is for summaries.
- Change: `theme.OPERATIONAL` in each adapter.

### D14. "No silos": each document ends with the supporting documents in the Evidence Vault and the records connected to it
- Decision: each document ends with two tables, both read through `entity360.get_connected`, the read behind the Connected page and the Case
  report, so a document lists exactly what the same person sees there and is never a second computation. (1) "Documents in the Evidence Vault": the
  Vault files linked to the record (its `proof` list) and to the records it rests on (`entity360.proof_of`: a DPIA's RoPA entry; an assessment's AI
  system, RoPA entry and DPIA; a plan's covered processes). Each row opens the file in the Vault, says what it shows today (the Vault's wording:
  Accepted, Waiting for a reviewer, Returned for changes, Expired, Replaced by a newer version, with the expiry date) and names the other records the same
  file also supports, so records are linked to each other through the repository. (2) "Records connected to this one": the page's connections (a
  proposed or disputed one is marked, as on the page), plus the plain references the page does not list (a DPIA's RoPA entry is a foreign key, not an
  edge; the assessments that cite a DPIA; the exercises and incidents of a plan), each read from this record ("assessed by", "is cited by"), and a
  first row that links to the live record.
- Links are absolute and built from the configured `APP_URL` (`core.email.app_origin`, https only), never from the request's Host header. With no
  `APP_URL` the rows are listed without links and the table says so.
- A record or file the reader may not open is left out, with no count and no hint (the relationship service's rule). A source that could not be read says
  so (`entity360` marks it unavailable) and is never shown as empty.
- Why: the owner asked that reports link to other relevant documentation and that they link via the evidence repository.
- Cost: more reads per document, bounded (50 files per record by `entity360`, 15 records whose files are read).
- Not done in the source worktree: filing the generated PDF itself into the Vault. That needed an upload permission, a retention and version rule and a decision
  on whether every download was kept. The 23 October integration addendum below supersedes this for the three record exports.
- Change: `modules/governance/connected_records.py` (what is added around the page's read) and `Col.link` in the kit (how a link is drawn).

### D15. The report kit draws links in every format
- Decision: a table column can name the row key that holds its link (`Col.link`). PDF: a clickable annotation; DOCX: a hyperlink run; XLSX: a cell
  hyperlink; HTML print view: an anchor. Link text is graphite and underlined (no blue, D4). Only absolute `https` URLs (or `http` for localhost) are drawn as links.
- Cost: four renderers touched. Change: `identity.safe_link` decides what may be a link.

### D16. Buttons
- DPIA: a PDF button in the row actions (the viewer keeps its text download). Plan: a PDF button in the plans list row. Assessment: a "Download PDF"
  button on the record and a PDF link in its list row. The routes also serve `?format=xlsx`; the pages offer the PDF.

### D17. The BCM plan routes apply the business unit rule
- Decision: `get_plan` takes `bu_scope` like `get_incident` and the routes read through `_plan_or_404`. Applied to the detail, reviews, activations, update,
  delete, activate, deactivate and AI review routes, and to the active plans list and the coverage links (`list_bia_plan_links(plan_id, bu_scope)`).
  Before, only the detail and AI review routes checked: another unit's plan could be read (reviews, activations, coverage), changed, deleted, activated and
  stood down by id.
- Cost: a person with `bcm.plan.manage` in one unit can no longer act on another unit's plan (404). Plans made in the app carry no unit (`create_plan` never
  stores one, so every such plan is organization wide), so in practice this changes behaviour only for plans that have one (imported or assigned).
- Change: `modules/bcm/routes.py` (`_plan_or_404`) and `modules/bcm/data_service.py`.

### D18. A DPIA's rating is `overall_risk`; a missing rating reads n/a
- Decision: the document prints `overall_risk` and `residual_risk` only. `risk_level` is a column that defaults to `medium` for every row and is not written
  by the form, so the page's Risk column shows Medium for a DPIA nobody rated; the document says `n/a` (not rated) instead of repeating that default.
- Change: `modules/sentinel/dpia_document.py`.

### D19. What the documents say about AI text and consultation
- Decision: AI drafted text is labelled "Written by the AI assistant. The application does not record that a person reviewed it" (the preview said it had
  not been reviewed, which the application cannot know). Consultation facts read "recorded as consulted" or "no consultation is recorded"; the form has no
  field for the authority or the data subjects, so those two read "Not recorded" rather than "No".

## 2. Work plan

- [x] P1 plan file, baseline staged (this file)
- [x] P2 kit: `Col.link`, `identity.safe_link`, renderers (PDF, DOCX, XLSX, HTML), markdown blocks (`core/report_kit/markdown.py`), tests (`tests/test_report_kit_links.py`)
- [x] P3 `modules/governance/connected_records.py` (built on `entity360`), `entity360.proof_of`, files carry `id` and `category`
- [x] P4 adapters: `modules/sentinel/dpia_document.py`, `modules/bcm/plan_document.py`, `modules/ai_governance/assessment_document.py`
- [x] P5 routes (three), BCM plan scope fix, audit, buttons
- [x] P6 tests with known data (`tests/test_record_documents.py`, `tests/ui/test_record_document_buttons.py`)
- [x] P7 PDFs rendered from a seeded world through the routes and looked at (notes folder `record-documents-wired/`)
- [~] P8 `scripts/capability_inventory.py` (done), backend suite, `tests/ui` suite (separate sessions)
- [ ] P9 mutation checks (tests fail on the old behaviour), hand-over note and patch file in the shared notes folder

## 3. Change log

2026-10-22 (CAT), all uncommitted. Baseline = the mirrored kit (section 0).

Kit (`oneforall/core/report_kit/`):
- `model.py` `Col.link`: the row key that holds a cell's address. `identity.py` `safe_link`: only an absolute https address (http for localhost), ASCII, with a
  host, no credentials and no character that could end an attribute or a markup tag; leading and trailing blanks are trimmed.
- `render_pdf.py` `_cell_markup` (clickable annotation, underlined graphite), `render_docx.py` `_link` (external hyperlink relationship, schema order kept),
  `render_xlsx.py` (cell hyperlink, underlined, never a formula), `render_html.py` `_cell` (anchor with `rel="noopener noreferrer"`).
- `markdown.py` new: Markdown text (an AI draft, a plan body) as `Paragraphs` and `Table` blocks; every non blank line stays a line; markup reduced to words.
- `helpers.py`: `lines` (a stored value as lines) and `facts_table` (two column table of what a record states; a gap reads `Not recorded`).

Documents and the closing section:
- `modules/sentinel/dpia_document.py`, `modules/bcm/plan_document.py`, `modules/ai_governance/assessment_document.py` new: the three documents (D13, D18, D19).
- `modules/governance/connected_records.py` new: `section()` builds the two closing tables (D14) on `entity360`.
- `modules/governance/entity360.py`: `proof_of()` (the proof section alone, for a record the viewer may open), and each proof item now carries `id` and `category`
  (additive: no consumer reads a key that moved).
- `modules/evidence/proof.py` `link_state_label()` (one definition of what a link shows today) and `modules/ai_governance/workspace.py` uses it (was the same six lines).

Routes, scope, audit:
- `GET /sentinel/api/dpias/{id}/document`, `GET /bcm/api/plans/{id}/document`, `GET /ai-governance/api/assessments/{id}/document` (D12); audit actions
  `dpia_exported`, `plan_exported`, `ai_assessment_exported`.
- `modules/bcm/routes.py` `_plan_or_404` on every plan route, `modules/bcm/data_service.py` `get_plan(bu_scope)`, `list_active_plans(bu_scope)`,
  `list_bia_plan_links(plan_id, bu_scope)` (which also returns each process's recovery time objective and criticality) (D17).

Pages:
- `modules/sentinel/templates/index.html` PDF button in the DPIA row actions; `modules/bcm/templates/index.html` PDF button in the plans list row;
  `static/js/ai_governance_assessments.js` "Download PDF" on the record and a Document column in the list (D16).

Docs:
- `docs/generated/capability_inventory.json` and `.md` regenerated with `scripts/capability_inventory.py` (1130 routes, three new), three routes annotated in
  `docs/capability_annotations.json`.

Tests (new): `tests/test_record_documents.py`, `tests/test_report_kit_links.py`, `tests/ui/test_record_document_buttons.py`.

## 4. Findings

Found while building. F = fixed here, O = left open, with the reason.

- F1 (D17) The BCM plan reviews, activations, coverage, update, delete, activate and deactivate routes, and the active plan list, did not apply the business unit rule.
- F2 The plan page named another unit's process in a plan's coverage list (a plan of one unit or organization wide that covers another unit's process).
- O1 `create_plan` stores no business unit, so a plan made in the app is organization wide whoever made it (an assessment is filed under the author's or the system's
  unit). Whether a new plan should take its author's unit is a product decision; the unit rule above already holds for plans that have one.
- O2 The DPIA list shows `risk_level` (default `medium`) as the risk of every DPIA that was not rated; the form writes `overall_risk` only. The document uses
  `overall_risk` (D18). The sibling session proposed deciding `risk_level` separately.
- O3 A DPIA's RoPA link is a foreign key, not a relationship edge, so the connected page does not list the RoPA entry; the document adds it, read through the registry's scope.
- O4 The `esc()` helper of the Sentinel template, and its copies in the BCM, ERM, ORM and GRID templates, does not escape quotes, so stored text can end an attribute
  (reported by the sibling session; the buttons added here pass the title through `esc()` into an `aria-label` like the neighbouring buttons do). Proposed as its own task.
- O5 A PDF of a record could be filed into the Evidence Vault as a document of its own (see D14, not done on purpose).
- O6 Other reports (the RoPA register, the board reports) can adopt `Col.link` with one line per table; only the three record documents carry links today.

## 5. Verification log

(commands and results, filled as each lane finishes)

## 23 October integration addendum

The source-worktree notes above describe its state before integration. In the integration worktree, DPIA, AI impact and continuity plan exports now file their PDF/XLSX bytes as a pending-review Vault item linked to the scoped source record. The semantic fingerprint ignores rendering time and downloader, so a repeat export creates no new Vault item; a changed report becomes the next version. The current and two preceding versions have a dedicated Vault view. Older versions are archived with bytes retained until a retention and legal-hold rule authorizes any purge. The export is refused if filing fails. New continuity plans inherit the author's business unit for access; their typed process owner may be any named person or team. Historical organization-wide plans are listed by the read-only release audit and are not backfilled automatically.
