# PLAN-05: Governance and Go-Live Gate (execute Part B inside ThemisIQ)

No code prerequisite. Can start immediately and run in parallel with PLAN-01 to 04. MUST be fully complete before PLAN-04 Step 10 (Meta webhook go-live). This is the release gate defined by the DPIA (section B.11).

## Goal

Execute the DPIA's required artefacts USING ThemisIQ itself (dogfooding the platform on its own new AI feature):

1. A DPIA record for the WhatsApp assistant in Sentinel.
2. New sub-processors (Meta/Twilio, LLM vendor) added to the vendor/ROPA register.
3. AI risk register entries (hallucination risk R4 and tenant-leak risk R1) in ERM.
4. The privacy notice text finalised (it ships in the bridge code).
5. The Legitimate Interests Assessment (LIA) attached as evidence.
6. A recorded sign-off trail (DPO + controller) before enabling the channel.

## Files/records to touch

- ThemisIQ UI (production tenant used for ThemisIQ's own governance): Sentinel DPIAs, Sentinel Vendors, ERM risk register, Evidence vault
- `themisiq_wa_bridge\ThemisIQ_WhatsApp_Assistant_Plan.md` (status header update)
- `themisiq_wa_bridge\app\main.py` (only if the notice text changes)

## Steps in order

### Step 1: Create the DPIA record in Sentinel

Sentinel, DPIAs, New DPIA. Fill:

- Title: `WhatsApp AI Assistant (ThemisIQ Bridge)`
- Description: copy section B.2 of `ThemisIQ_WhatsApp_Assistant_Plan.md` (nature, scope, purposes table) into the description/processing fields.
- Processing type: `New channel / AI-assisted query of existing records`
- Data categories: `User identifiers (phone to tenant mapping), message content, record excerpts, LLM prompts and completions`
- Data subjects: `Authorised staff users; indirectly, data subjects referenced in queried records`
- Necessity: copy B.3 first bullet. Proportionality: copy B.3 second bullet.
- Risks: paste the B.4 risk register rows R1 to R9 (text form is fine).
- Mitigations: paste the B.5 measures M1 to M13.
- DPO opinion: `Acceptable for Phase 1 (read-only) subject to M6/M9 confirmation. Any write actions or special-category modules re-open this DPIA.`
- Status: leave `draft` until Step 6.

### Step 2: Register the new sub-processors as vendors

Sentinel, Vendors. Create two records:

1. Name `Meta Platforms Inc. (WhatsApp Business Platform)` (or `Twilio Inc.` if that route was chosen). Type `processor`. Services: `Messaging transport for the ThemisIQ WhatsApp assistant`. Data types: `Phone numbers, message content and metadata`. DPA status: set to `pending` until the Meta/Twilio DPA (they publish standard DPAs) is reviewed, then `signed`. Note data residency findings in the notes field.
2. Name = the LLM vendor in use (for example `Anthropic`). Services: `LLM inference for assistant answers and drafting`. Data types: `Prompt text possibly containing record excerpts`. Notes: record the zero-retention / no-training confirmation reference (DPIA M6/M9) and the DPA/addendum status.

### Step 3: AI risks into the ERM register

ERM, new enterprise risks:

1. Title: `WhatsApp assistant returns hallucinated compliance advice (R4)`. Category: operational (or the platform's AI-risk category if one exists). Likelihood 3, Impact 4. Treatment: mitigate. Treatment plan: `All AI answers labelled as AI-generated and requiring verification; Phase 1 read-only, no autonomous actions (M7, M8); human-in-the-loop for all decisions.`
2. Title: `Cross-tenant data exposure via the WhatsApp bridge (R1/R2)`. Likelihood 2, Impact 5. Treatment: mitigate. Treatment plan: `Per-tenant scoped read-only API keys; admin-managed number-to-tenant binding; bridge-side RBAC gate; append-only audit; HMAC verification both directions (M1-M5).`

If ThemisIQ's ISO 42001 / AI controls area (core `ai_controls`) supports registering AI systems, also register the assistant there with: model provider, model id, purpose, no-auto-execute control, and the notice requirement. If that area has no UI yet, record the same facts in the DPIA notes field instead.

### Step 4: Attach evidence

Evidence vault (or DPIA attachments):

- `ThemisIQ_WhatsApp_Assistant_Plan.md` (the architecture + DPIA document)
- The LIA: write a one-page Legitimate Interests Assessment (purpose test, necessity test, balancing test) based on B.8. Conclusion: legitimate interests of the controller in operational efficiency for its own authorised staff, low intrusion, notice given, opt-out available by unlinking the number.
- The LLM vendor retention/DPA confirmation (screenshot or document).
- The Meta or Twilio DPA reference.

### Step 5: Finalise the privacy notice

The notice currently shipped in `app\main.py` (`PRIVACY_NOTICE`) reads: processing under GDPR/CDPA, 90-day log retention, AI-generated answers, help command. Confirm with the DPO (Ali) that this wording is final; if changed, update the constant in `main.py` and re-run the bridge tests. The notice must state: who processes, purpose, retention, AI-generated content warning, and how to stop (contact administrator to unlink the number).

### Step 6: Sign-off and status flips

1. DPIA record: status to the platform's approved/completed value, DPO opinion filled, date recorded.
2. Update `ThemisIQ_WhatsApp_Assistant_Plan.md` header: change `Status: DRAFT` to `Status: APPROVED (DPO + controller), <date>`, and tick the B.11 checklist boxes in the file.
3. Record controller sign-off (email or signed page) into the evidence vault.
4. Only now may PLAN-04 Step 10 (Meta webhook enable) be executed.

### Step 7: Post-launch governance hooks

- Add a review task/calendar entry: `WhatsApp assistant DPIA review` at 6 months, and a trigger note: any write-action feature or special-category module re-opens the DPIA (B.6 warning).
- Confirm the 90-day message-log posture: the bridge deliberately does not store message bodies; the audit log stores actions only. Record this in the DPIA as implemented-by-design.
- Add a monthly check of the bridge audit log for `rbac_denied` and `unbound_user` spikes (M10 anomaly monitoring) to whichever recurring ops checklist exists.

## Edge cases a weaker model would miss

1. **This plan is the GATE, not paperwork after the fact.** The DPIA states approvals are required BEFORE build/go-live (B.11). The technical plans can be built and tested offline, but the Meta webhook must not be enabled in production until Step 6 is complete.
2. **Two distinct retention clocks:** message logs 90 days versus audit log 7 years. The bridge design satisfies both by never storing message bodies at all; do not "fix" the bridge to log message text for debugging.
3. **The LLM zero-retention confirmation (M6/M9) is a blocking item**, not a nice-to-have. If the current `AI_PROVIDER` tier trains on API data, either switch tier/provider or document the risk acceptance explicitly with the controller's signature.
4. **Special-category modules stay out** (M13): the bridge's tenant map must not include `bcm` health-adjacent data modules for any user in Phase 1. Check the pilot user's modules list against this.
5. **Per-tenant DPIA responsibility:** ThemisIQ customers are controllers of their tenants. If the assistant is offered to customer tenants (not just ThemisIQ's own org), each controller needs its own notice and sign-off; the MVP pilot should therefore run on ThemisIQ's own tenant only.
6. **CDPA (Zimbabwe SI 155 of 2024) applies alongside GDPR** given POTRAZ registration; the DPIA record should name both regulations (the Sentinel regulation field defaults to GDPR; set it to both if the field allows, otherwise note CDPA in the description).
7. **The plan document's own status header must change.** Leaving `Status: DRAFT` in a signed-off artefact fails an audit consistency check.

## Acceptance criteria (verify each)

1. Sentinel shows a DPIA titled `WhatsApp AI Assistant (ThemisIQ Bridge)` with risks R1-R9, measures M1-M13, DPO opinion, and approved status with a date.
2. Two new vendor records exist (messaging transport + LLM vendor) with DPA status and notes on retention/data residency.
3. ERM register contains the two AI risks with treatment plans, visible in the risk register views.
4. Evidence vault holds: the plan document, the LIA, the LLM retention confirmation, the DPA reference, and the controller sign-off.
5. `ThemisIQ_WhatsApp_Assistant_Plan.md` header shows APPROVED with date, and every B.11 checkbox is ticked.
6. The privacy notice in `app\main.py` matches the DPO-approved wording exactly.
7. A 6-month DPIA review task/calendar entry exists.
8. Only after 1 to 7: the Meta webhook is live (PLAN-04 Step 10) and the first-interaction notice is confirmed received on the pilot phone.
