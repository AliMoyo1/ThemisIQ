# ThemisIQ Platform Demo Plan

## Demo Details
- Duration: 2 hours (120 minutes)
- Format: Microsoft Teams screen-share
- Date: Friday 3 July 2026
- Presenter: You (platform builder/developer)

## Audience
- IT Risk and Compliance
- Cybersecurity team
- Internal Audit
- Stakeholder/Sustainability Manager
- Data Protection Officer/team

## Strategic Goals
1. Show how ThemisIQ eliminates the spreadsheet/SharePoint/Cura silos
2. Demonstrate real cross-module intelligence (not just a list of features)
3. Let each audience member see their own domain, then show how it connects to everyone else's
4. Subtly demonstrate your technical depth and vision without overtly pitching yourself


---

## PRE-DEMO CHECKLIST (do this 30 min before)

- [ ] Clean test data from the database (delete BCM TEST-DELETE, MW-FIX-TEST entries, Sentinel test breaches #9/#10, ERM test risk #244/#248, duplicate AI predictive risks #251-254)
- [ ] Confirm app is running on localhost:8080
- [ ] Log in as System Administrator
- [ ] Open these tabs ready to switch between:
  - Tab 1: Command Centre (localhost:8080/launcher/)
  - Tab 2: Sentinel Breaches (localhost:8080/sentinel/breaches)
  - Tab 3: GRID Audit #15 (localhost:8080/grid/audits/15)
  - Tab 4: ERM Dashboard (localhost:8080/erm/)
  - Tab 5: BCM Incidents (localhost:8080/bcm/)
- [ ] Turn on dark mode (looks more polished on screen-share)
- [ ] Close all other desktop apps to avoid notifications
- [ ] Test your mic and screen-share before the call


---

## AGENDA (120 minutes)

| Time | Segment | Duration | Primary Audience |
|------|---------|----------|-----------------|
| 0:00 | Opening: The Problem We Solve | 5 min | Everyone |
| 0:05 | Command Centre Tour | 10 min | Everyone |
| 0:15 | SCENARIO 1: Breach Response Pipeline | 25 min | Data Protection, Cybersecurity, Audit |
| 0:40 | SCENARIO 2: Ransomware to Enterprise Risk | 20 min | BCM, IT Risk, Cybersecurity |
| 1:00 | Break / Q&A checkpoint | 5 min | Everyone |
| 1:05 | SCENARIO 3: Predictive Risk Intelligence | 15 min | IT Risk, Compliance, Board-level |
| 1:20 | Module Quick Tours (ARIA, ORM, Evidence Vault) | 15 min | Governance, Compliance |
| 1:35 | Killer Features Highlights | 10 min | Everyone |
| 1:45 | Architecture and Scalability | 5 min | Technical |
| 1:50 | Q&A and Discussion | 10 min | Everyone |


---

## SEGMENT 1: OPENING (5 min)

### Screen: Command Centre (localhost:8080/launcher/)

### Talking Points

"Thank you all for joining. I want to show you something I have been building. ThemisIQ is an integrated GRC platform that connects all the compliance, risk, and audit functions into a single system.

Right now we manage compliance across Cura, SharePoint, email, and various spreadsheets. The challenge is that when something happens, like a data breach, the information needs to flow to at least five different people and three different systems. Notifications get missed, audits happen in isolation, and nobody has the full picture.

ThemisIQ solves this by connecting everything. When a breach is detected, the system automatically creates audit tasks, escalates risks, triggers notification deadlines, and feeds predictive intelligence. No manual handoffs. No spreadsheet updates.

Let me show you what I mean."


---

## SEGMENT 2: COMMAND CENTRE TOUR (10 min)

### Screen: Command Centre (localhost:8080/launcher/)

### Script

"This is the Command Centre. Think of it as your mission control for the entire GRC programme. Every module reports into this single view."

**Point to the module cards:**
"You can see all six modules: Governance (ARIA), Audit (GRID), Resilience (BCM), Privacy (Sentinel), Enterprise Risk (ERM), and Operations Risk (ORM). Each one is a full application, not just a tab."

**Point to the Predictive Risk Intelligence card:**
"This is one of the killer features. The Predictive Risk Intelligence engine continuously pulls signals from every module and computes an overall risk posture. Right now it is showing CRITICAL at 83% confidence, because we have active breaches and appetite violations. I will come back to this in detail later."

**Point to the Breach Notification Deadline card:**
"This is live. We have 3 breach notifications due within 48 hours. The system knows the regulatory deadline for each jurisdiction, whether that is GDPR's 72-hour rule or Zimbabwe CDPA's requirements, and it counts down automatically. No more tracking deadlines in a spreadsheet."

**Point to the module tiles:**
"The key insight is: you only see the Command Centre. But underneath, six specialized modules are all sharing data, creating cross-module links, and feeding that predictive engine. Let me show you how this works in practice with a real scenario."


---

## SEGMENT 3: SCENARIO 1 - BREACH RESPONSE PIPELINE (25 min)

### The Story
A cloud storage misconfiguration exposed customer PII. Watch how ThemisIQ handles it across 5 modules automatically.

### This is the strongest demo scenario. It shows the full breach-to-audit-to-risk pipeline.

### Step 1: The Breach (Sentinel) - 5 min

**Navigate to: Sentinel > Data Breaches**

**Script:**
"Let us start where incidents begin: Data Protection. A cloud storage misconfiguration was discovered. The DPO logs it as a data breach."

**Click on breach #6 (Customer Database Exposure via Misconfigured Cloud Storage)**

"Notice the system has already done several things:
- Classified the severity as HIGH
- Identified the regulation as GDPR
- Calculated the 72-hour notification deadline
- Shows the breach status workflow (Detected, Contained, Resolved)

But here is where it gets interesting. Look at what happened automatically when this breach was confirmed..."

### Step 2: Auto-Created Audit (GRID) - 8 min

**Navigate to: GRID > Audits > Audit #15**

**Script:**
"The moment the breach was confirmed, ThemisIQ automatically created a post-incident audit in the GRID module. You did not have to email the audit team. You did not have to create a ticket. The system created it, linked it back to the original breach, and tagged it with the regulation.

Look at the audit name: 'Post-Incident Audit [GDPR]: Customer Database Exposure via Misconfigured Cloud Storage'. It carries the context forward."

**Point to the 12 controls:**
"Now watch this. The audit was created with zero controls. The auditor clicks 'AI Checklist'..."

**Click the AI Checklist button (demonstrate if AI is available, otherwise explain):**
"The AI reads the original breach details, the applicable regulation, the ARIA policies we have on file, and generates a tailored checklist. Not a generic template. Items specific to this breach:
- 'Compromised access revoked' for containment
- 'Affected systems isolated'
- 'Supervisory authority notified within 72 hours' for GDPR compliance
- 'Root cause analysis completed' for investigation
- 'Security controls updated' for remediation

Each item has evidence requirements. The system auto-matches these against our Evidence Vault. If we already have a 'Breach Containment Report' uploaded, it links it automatically."

**Scroll through the 12 controls:**
"12 tailored audit items, each with a status workflow, assignee field, and evidence links. What used to take 2 days of audit planning happened in 10 seconds."

### Step 3: Auto-Created ERM Risk (ERM) - 7 min

**Navigate to: ERM > Risk Register**

**Script:**
"Simultaneously, the breach created an enterprise risk. Find 'Data Breach Risk: Customer Database Exposure' on the register.

The system automatically scored it: Likelihood 5, Impact 5, giving an inherent score of 25, which our rating framework classifies as CRITICAL."

**Open the risk drawer:**
"Look at the risk details. The category is 'Compliance & Legal Risk'. Now look at the Appetite panel on the left."

**Point to the Appetite Status panel:**
"The Compliance & Legal Risk appetite is set to LOW with a maximum score of 6. This risk scores 25. That is over 4x the appetite threshold. The system flags this as an APPETITE BREACH immediately. No waiting for the quarterly review."

### Step 4: Connect the dots (5 min)

**Navigate back to Command Centre:**

**Script:**
"So from a single breach event:
1. Sentinel logged the breach and started the notification countdown
2. GRID created a post-incident audit with 12 AI-generated checklist items
3. ERM created a critical risk and flagged an appetite breach
4. Evidence Vault auto-matched relevant documents
5. The Predictive Risk Intelligence engine updated the overall risk posture

Five modules. Zero manual handoffs. In Cura and SharePoint, this same workflow involves at least 6 emails, 3 spreadsheet updates, a separate audit request, and someone manually checking if we have exceeded our risk appetite. Typically takes 2 to 3 days. Here it happened in real time."

### Key Comparison to Current Tools

"In Cura:
- You log the breach manually
- Someone emails the audit team to start a post-incident review
- The auditor opens a new assessment from scratch
- Someone else manually updates the risk register
- Nobody checks risk appetite until the quarterly review

In ThemisIQ, every step is automated, linked, and auditable."


---

## SEGMENT 4: SCENARIO 2 - RANSOMWARE TO ENTERPRISE RISK (20 min)

### The Story
A ransomware attack on core financial systems triggers BCM incident response. Watch how it flows into Enterprise Risk.

### Step 1: The Incident (BCM) - 7 min

**Navigate to: BCM > Incidents**

**Script:**
"Now a different entry point. The cybersecurity team detects a ransomware attack on core financial systems. The BCM Manager logs it as a critical incident."

**Click on incident: Ransomware Attack on Core Financial Systems**

"Notice:
- Severity: CRITICAL
- Status: Open (actively being managed)
- The BCM module tracks the incident lifecycle: detection, response, recovery

But again, ThemisIQ does not stop at BCM. The moment this incident was declared, the system propagated it across modules."

### Step 2: Auto-Escalation to ERM (7 min)

**Navigate to: ERM > Dashboard**

**Script:**
"Look at the dashboard. 'BCM Incident: Ransomware Attack on Core Financial Systems' appears as a critical enterprise risk. Likelihood 5, Impact 5, score 25.

The system placed it in the 'Operational Risk' category. Now look at the appetite status: Operational Risk has a medium appetite with max score 12. This risk at 25 is double the threshold. Another appetite breach."

**Click into the heatmap:**
"The heatmap tells the story visually. See the cluster in the top-right corner? Four critical risks, all at L5 x I5. Two from data breaches, one from the ransomware attack, one from a stolen laptop incident. The board can see the concentration immediately."

### Step 3: Predictive Intelligence Update (6 min)

**Navigate to: Command Centre > Predictive Risk Intelligence card**

**Script:**
"Now the Predictive Risk Intelligence engine. It has pulled signals from all modules:
- Sentinel Breaches: 86% of the signal. We have active, unresolved breaches.
- ERM Appetite Breaches: 10%. Two categories are over threshold.
- BCM Staleness: 4%. Our continuity plans have not been exercised recently.

The engine computes: Cyber risk delta is +100%. Compliance delta is +60.4%. Overall confidence: 83%.

This is not a static score. It recalculates every time something changes in any module. A new breach, a resolved incident, an updated risk assessment: all feed back into this engine."

### Key Point for Cybersecurity Audience

"For the cybersecurity team specifically: when you log a security incident, the system does not just track it in isolation. It creates a risk entry that the board sees, triggers appetite breach alerts that risk owners see, and feeds the predictive engine that the CISO sees. One event, full visibility across the organization."


---

## SEGMENT 5: BREAK / Q&A CHECKPOINT (5 min)

**Script:**
"Let me pause here. We have seen two real scenarios. Any questions so far before I show you the predictive intelligence in more detail?"

This is a good moment to gauge the room. If people are excited, use the energy. If someone asks about a specific module, pivot to show it.


---

## SEGMENT 6: SCENARIO 3 - PREDICTIVE RISK INTELLIGENCE DEEP DIVE (15 min)

### The Story
The Command Centre shows a CRITICAL alert. Drill into what is driving it and how the system helps prioritize response.

### Step 1: The Alert (5 min)

**Navigate to: Command Centre > Predictive Risk Intelligence card**

**Script:**
"This card is the executive summary. CRITICAL risk level, 83% confidence. But what makes this powerful is the breakdown."

**Point to Domain Breakdown:**
"Three risk domains:
- Cyber: 100%. We have active, uncontained breaches. This is the primary driver.
- Compliance: 60.4%. We have regulatory notification deadlines approaching.
- Operational: 29.9%. The ransomware incident is still open.

The engine weighted these based on the actual signals, not a subjective assessment."

**Point to Signal Contributions:**
"And here is exactly what is feeding each domain:
- 86% from Sentinel Breaches (active breaches with open notification deadlines)
- 10% from ERM Appetite Breaches (two categories over their threshold)
- 4% from BCM Staleness (continuity plans not exercised recently)
- 0% from GRID Non-Conformances (our audits are clean)
- 0% from ORM Recurring Events (no repeat operational events)
- 0% from ARIA Compliance Gap (our policy compliance is at 100%)

This gives the board and the CISO a data-driven view of where to focus resources. Right now: resolve the breaches first, then address the appetite violations."

### Step 2: Breach Notification Countdown (5 min)

**Point to the Breach Notification Deadline cards:**

"These countdown cards are live. They show exactly how much time remains to notify the relevant supervisory authority for each breach.

Notice the jurisdictions:
- GDPR / National DPA has a 72-hour deadline
- Zimbabwe CDPA / POTRAZ also has a 72-hour deadline but different authority contact details

The system tracks each jurisdiction separately. In a multi-jurisdictional organization, you might have the same incident requiring notification to multiple authorities with different deadlines. ThemisIQ handles this automatically."

### Step 3: What Happens When You Fix Things (5 min)

**Script:**
"Here is the important part. When the DPO marks the authority as notified, the countdown card clears. When the breach is resolved, the Sentinel contribution drops. When the risk score comes down below appetite, the ERM breach clears. The predictive engine recalculates.

This is a living system. It does not just report bad news. It shows you progress. When you resolve issues, the overall risk posture improves in real time. That is something a quarterly risk review in a spreadsheet can never do."


---

## SEGMENT 7: MODULE QUICK TOURS (15 min)

### ARIA - Governance (5 min)

**Navigate to: ARIA (Governance)**

**Script:**
"ARIA handles policy and compliance management. You can create and manage policy documents with version control, link them to compliance frameworks like ISO 27001, and track their approval workflow.

We have 4 policies loaded. The AI can generate policy drafts based on your selected framework, and it respects your organization's custom instructions.

For the compliance team: this replaces the SharePoint document library where policies live today. Version history, approval workflows, and framework mapping are all built in."

### ORM - Operations Risk (3 min)

**Navigate to: ORM (Operations Risk)**

**Script:**
"ORM tracks day-to-day operational events: near-misses, incidents, loss events. It has RCSA worksheets, Key Risk Indicators with threshold alerts, and event logging.

When an operational event repeats, the system flags it. If it crosses a KRI threshold, it feeds the predictive engine. It connects to ERM so operational events can escalate to enterprise risks when needed."

### Evidence Vault (3 min)

**Navigate to: Command Centre > Evidence Repository**

**Script:**
"The Evidence Vault is a central repository for all compliance evidence. 25 items currently stored: breach records, incident records, control assessments.

The key feature: when GRID creates audit checklist items with evidence requirements, the vault auto-matches existing documents. You do not need to hunt through SharePoint to find if you already have a penetration test report or a breach containment record. The system knows."

### Reports and Board Reporting (4 min)

**Navigate to: Command Centre > Generate Board Report**

**Script:**
"Every module can export CSV. But the real feature is the Board Report generator. One click generates a cross-module executive summary covering all modules: ERM risk posture, active breaches, audit status, BCM readiness, compliance gaps.

This is the report your board committee receives. Built from live data, not manually assembled from five different sources."


---

## SEGMENT 8: KILLER FEATURES HIGHLIGHTS (10 min)

### Rapid-fire through the features that differentiate ThemisIQ

**1. AI Integration (2 min)**
"Every module has an AI assistant. The AI generates audit checklists, suggests legal bases for data processing, drafts policy documents, prioritizes tasks, and auto-links evidence. It is not a chatbot. It understands the compliance context."

**2. Cross-Module Links (2 min)**
"Every record can link to records in other modules. A breach links to its audit, its ERM risk, its BCM incident, and its evidence. You can trace any compliance event across the entire GRC lifecycle."

**3. Risk Rating Framework (2 min)**
**Navigate to: ERM > Rating Guide**
"The risk scoring is not hardcoded. Organizations can bring their own risk rating framework. 9 impact dimensions, 5 likelihood levels, a configurable 5x5 matrix. The framework can be exported, imported, and customized per organization."

**4. Multi-Tenant Architecture (2 min)**
"Each organization gets its own isolated database schema. Data is completely separated. A holding company can run multiple subsidiaries, each with their own risk appetite, policies, and compliance programme. All managed from one platform."

**5. Workflow Engine (2 min)**
"Built-in workflow templates for every process: breach response, audit lifecycle, risk assessment, incident management. Workflows can be customized per organization. Task board with drag-and-drop for managing work items across all modules."


---

## SEGMENT 9: ARCHITECTURE AND SCALABILITY (5 min)

### For the technical audience

**Script:**
"For those interested in the technical side:
- Built on Python with FastAPI, a modern async web framework
- PostgreSQL database with per-tenant schema isolation
- AI integration via Claude API with fallback stubs when AI is unavailable
- Role-based access control with granular capabilities per module
- Full audit log of every action
- RESTful API for every function, enabling future integration with other systems
- Deployed on Linux with systemd, standard infrastructure

The platform is designed to scale. Adding a new module follows a consistent pattern. Adding a new organization is a one-click operation that provisions their entire environment."


---

## SEGMENT 10: Q&A AND DISCUSSION (10 min)

### Prepared answers for likely questions

**Q: How does this compare to Cura?**
"Cura is strong for individual risk management but it operates as a standalone tool. When a breach happens in Sentinel, someone has to manually update Cura's risk register. ThemisIQ does this automatically. The cross-module intelligence, the AI features, and the predictive engine are capabilities Cura does not offer."

**Q: How does this compare to SharePoint?**
"SharePoint is a document store, not a compliance system. It does not understand regulatory deadlines, risk appetites, or audit workflows. ThemisIQ uses SharePoint-level document management in the Evidence Vault, but adds compliance context on top."

**Q: Can we import our existing data?**
"Yes. The ERM module supports Excel import for risk registers, with fuzzy matching for categories and owners. CSV export is available from every module. The API also supports bulk operations."

**Q: What about access control?**
"Role-based access control with granular capabilities. The DPO sees Privacy and relevant ERM risks. The BCM Manager sees Resilience and BCM-related risks. The auditor sees GRID and can read ERM. A super admin sees everything. Roles are configurable."

**Q: Is this production-ready?**
"The platform is functional and being prepared for deployment. It runs on a VPS with PostgreSQL, behind a reverse proxy. The codebase has automated tests, and we are doing pre-launch security review."

**Q: Who built this?**
"I designed and built the entire platform. The architecture, the database schema, the module design, the AI integrations, the cross-module intelligence engine. It is a demonstration of what modern GRC technology can look like when built from scratch with integration as the core design principle, rather than bolting modules together after the fact."


---

## CLOSING STATEMENT (1 min)

"Thank you for your time today. What I hope you take away is this: compliance, risk, and audit do not have to live in separate silos. When they are connected, you get intelligence, not just information. You get proactive alerts, not quarterly surprises. And you get a single source of truth that everyone, from the DPO to the board, can rely on.

I am happy to do deeper dives into any specific module with the relevant team. Thank you."


---

## DEMO FLOW CHEAT SHEET (quick reference during the demo)

### Scenario 1: Breach Response Pipeline
```
Sentinel breach #6 (Customer Database Exposure)
  -> GRID audit #15 (12 AI checklist items)
  -> ERM risk #239 (L5 I5 = critical, appetite breach)
  -> Evidence Vault auto-match
  -> Predictive engine update
```

### Scenario 2: Ransomware to Enterprise Risk
```
BCM incident #12 (Ransomware Attack on Core Financial Systems)
  -> ERM risk #243 (L5 I5 = critical, Operational Risk appetite breach)
  -> Predictive engine: ops delta 29.9%
  -> Heatmap: top-right cluster of critical risks
```

### Scenario 3: Predictive Risk Intelligence
```
Command Centre > Predictive Risk card
  -> CRITICAL, 83% confidence
  -> Cyber 100%, Compliance 60.4%, Operational 29.9%
  -> Signal breakdown: 86% breaches, 10% appetite, 4% BCM
  -> Breach countdown cards with jurisdiction deadlines
```

### Quick Navigation
- Command Centre: /launcher/
- Sentinel Breaches: /sentinel/ > Data Breaches nav link
- GRID Audit #15: /grid/audits/15
- ERM Dashboard: /erm/
- ERM Risk Register: /erm/ > Risk Register nav link
- BCM Incidents: /bcm/ > Incidents nav link
- Evidence Vault: /launcher/ > Evidence Repository nav link
- ARIA Governance: /aria/


---

## DATA CLEANUP BEFORE DEMO

Run these deletions to remove test/debug data:

BCM incidents to delete: #1, #3, #4, #5, #7, #13, #14, #15, #16, #17, #18, #20 (all TEST/DEBUG entries)
BCM closed verifications to delete: #2, #6

ERM risks to delete: #244 (MW-FIX-TEST-ERM), #248 (Test Breach Event risk)
ERM duplicate predictive alerts to delete: #251, #252, #253, #254

Sentinel breaches to delete: #9 (Test Breach for Event), #10 (Test Breach Event)

Grid audit to delete: #17 (Post-Incident Audit for Test Breach Event)

Evidence vault items to clean: any with "TEST-DELETE", "MW-FIX-TEST", "Debug" in title

Cross-module links to clean: any with source_id > 1000 (bogus test IDs)

After cleanup, remaining clean data:
- 2 real Sentinel breaches (#6 GDPR, #11 Zimbabwe CDPA)
- 4 real BCM incidents (#8, #12, #19, #21)
- 6 real ERM risks (#239, #243, #247, #249, #250 plus 1 strategic)
- 5 real Grid audits (#7, #8, #15, #16, #18)
- Clean evidence vault items
- Clean cross-module links
