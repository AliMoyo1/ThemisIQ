# PLAN: regulator grade RoPA, DPIA and AIIA, adaptable by jurisdiction (2026-10-22)

Worktree `.claude/worktrees/sweet-northcutt-aada82`, branch `claude/sweet-northcutt-aada82`. Nothing is committed or pushed.
App code lives in `oneforall/`. Tests run from `oneforall/` with the repo `.venv` python, one pytest session at a time.

Baseline: the uncommitted report exports work of worktree `sad-albattani-5255ea` (core/report_kit, the module reports, the ref column fix) was
copied here on 2026-10-22 15:25 CAT and staged (`git diff --cached` is that baseline; plain `git diff` is this work only). It is a snapshot:
changes made later in the other worktree are not here.

## 0. The request (owner, near verbatim)

1. "The RoPA you made isnt as detailed as required by the regulator. Adapt these gdpr samples into the system and reporting. They should also
   be adaptable for the different jurisdictions as they also require similar levels of detail, like data owners etc."
   Samples: `RoPA-Template.xlsx` (40 columns, one sheet, 23 example rows; `RoPA-Template (1).xlsx` is a byte identical copy),
   `gdpr-ropa-template.md / .pdf / (Instructions).csv` (controller register mapped to Art 30(1)(a)-(g), processor register mapped to
   Art 30(2)(a)-(d), identity block, completion rules).
2. "then these ones are for DPIA and AIIA. Adapt them into the system and reports."
   Samples for the DPIA: `dpia-template.md` and `dpia-template.docx` (14 sections, WP248 screening, risk matrix, Art 36 gate, AI annex),
   the EDPB 2026 DPIA template explainer (50 numbered fields in 7 parts), the Microsoft customizable DPIA (question form), and `dpia temp.docx`
   (14 section enterprise DPIA with cross jurisdiction appendices: UK GDPR, LGPD, CPRA, PIPL, PIPA, ISO 27701, ISO 29134, NIST).
   Samples for the AIIA: `AI-Impact-Assessment.pdf` (ISO 42001 style report) and the Microsoft Responsible AI Impact Assessment template.

Standing rules in force: ThemisIQ only; no em dashes in code, comments or copy; no coloured top borders on cards; report times in CAT; keep the
diff as small as the job allows but never drop validation, security or tests; one pytest session at a time (backend and `tests/ui` apart); do not
commit or push unless asked; decisions taken for the owner are written here with why, cost and how to change them (chat confirmation, NOT sign off).

## 1. Findings so far (about the code as it was)

- F1 RoPA data typed in the form is lost on read. The form saves `recipients`, `processors` and `security_measures` as text; `_ropa_row` reads them
  with `_parse_json(..., [])`, so any text that is not JSON reads back as `[]` (stored raw: `Payroll bureau; Tax office`; read back: `[]`).
  Art 30(1)(d) and (g) content could never reach an export. Probe: scratch `probe_ropa_readback.py`.
- F2 The Controllers register (`sentinel_controllers`, the Controller / DPO page) sends `role`, `agreement_ref` and others that `_CTRL_FIELDS`
  does not list, so every row is saved as the default role `joint_controller`. Same class of bug as the DPIA form (`mitigations`,
  `description`, `risk_level`, `assessor`, `due_date` are sent and dropped by `_DPIA_FIELDS`).
- F3 `PUT /sentinel/api/settings` writes any key of the shared `settings` table for anyone holding `sentinel.ropa.manage`. Not changed here
  (outside the request); the new identity data uses its own whitelisted route. Listed as a follow up.
- F4 The RoPA drawer lists 15 jurisdictions by hand, the DPIA modal 12, the registry holds 21 (`jurisdictions.JURISDICTION_RULES`).

## 2. Decisions taken on the owner's behalf (chat confirmation, NOT sign off)

### D1. One record definition per record type, resolved per regulation (profile driven)
- Decision: a registry (`modules/sentinel/record_profiles/`) defines every field of the RoPA, the DPIA and the AIIA once: key, label, kind, section,
  legal anchor, options, whether it is required and when. A regime (GDPR, UK GDPR, POPIA, ...) changes terms, anchors, option lists and required
  fields without code. The same definition feeds the form, the server side validation, the completeness check, the PDF and the Excel export.
- Why: about 200 fields times 21 regimes cannot be hand coded, and a form and a service that each list their own fields drift (F2, the DPIA).
- Cost: fields that are new live in one JSON `details` column per table, so they are not filterable in SQL (the lists filter in Python; the
  registers are small). Fields that already have a column keep it.
- Change: promote a field to a column by a migration and `store="column"` in its definition.

### D2. Honest legal anchors
- Decision: a regime carries `source_status` as the existing jurisdiction registry does (`researched_unapproved` or `unverified`). Anchors are
  written only where a supplied template or the statute names them (GDPR and UK GDPR Art 30, 35, 36; POPIA section numbers used by the platform's
  own text). Every other regime states "no statutory record of processing provision has been verified" and applies the GDPR layout as good
  practice. Each export prints the status and that a privacy specialist must confirm before filing.
- Why: the registry already refuses to present researched but unapproved rules as law.
- Cost: for Zimbabwe, Kenya, Nigeria and the rest, anchors are blank until a specialist confirms them.
- Change: add anchors in `regimes.py` and set the status.

### D3. Organisation identity (Art 30(1)(a), 30(2)(a)) reuses the Controller / DPO register
- Decision: the primary row of `sentinel_controllers` is the controller identity; its other rows (joint controller, processor, DPO, regulator) fill
  the register's identity block; `sentinel_jurisdiction_config` supplies the DPO and registration number per regulation. Missing columns
  (representative, record owner, last full review) are added to `sentinel_controllers`; `_CTRL_FIELDS` is corrected (F2).
- Why: three places already hold identity data; a fourth would disagree with them.

### D4. Controller and processor registers are one table with a role
- Decision: `sentinel_ropa` keeps one row per activity with `controller_role` (controller, joint controller, processor). The export splits it
  into the Art 30(1) register and the Art 30(2) register. A processor row shows the controller it acts for, the sub-processors and the DPA reference.

### D5. Layout of the documents
- Decision: the PDF is a dossier (identity block, readiness figures with charts, gaps, one record card per activity, legal references). The workbook is the
  wide register in the supplied template's column order (adapted by regime) plus the Art 30(2) register, the gaps and the lists.
- Why: 40 columns cannot be read in a portrait PDF; a regulator asks for the register itself, which is the workbook.

### D6. Out of this round
- Import of a filled template (the workbook export keeps the template's headers so an importer can follow), scheduled review reminders, rule card
  approval of profiles by a specialist, DOCX output. Listed as follow ups when the three stages are done.

## 3. Work plan

- [ ] S0 baseline replayed and staged (done), plan file (this)
- [ ] S1 record definitions: `record_profiles` package (model, regimes, ropa, dpia, aiia), pure Python, unit tests
- [ ] S2 storage: `details` columns, controllers columns, `_CTRL_FIELDS`, readback fix (F1)
- [ ] S3 RoPA service and routes on the profile; profile route; identity route
- [ ] S4 RoPA form (generic record form) and list
- [ ] S5 RoPA regulator pack: PDF dossier and workbook
- [ ] S6 DPIA: profile, service, form, report
- [ ] S7 AIIA: profile, service, form, report
- [ ] S8 verification: backend suite, `tests/ui` suite, real PostgreSQL, capability inventory, samples looked at

## 4. Change log

(2026-10-22, all uncommitted; filled as work lands)

## 5. Verification log

(filled as suites run)
