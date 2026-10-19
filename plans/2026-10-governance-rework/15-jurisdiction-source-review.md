# Sentinel jurisdiction source review

Research date: 2026-10-19. This is a source dossier for specialist review, not an approved rule set. A legal or privacy specialist must confirm applicability, trigger facts, effective dates, local practice and wording before approving a Sentinel rule card. Do not import these notes as approved cards or send a regulator notification automatically.

## Source-backed draft interpretations

| Jurisdiction and notice | Primary source | What the source supports | What the software must still decide |
| --- | --- | --- | --- |
| EU GDPR, supervisory authority breach notice | [Regulation (EU) 2016/679, Article 33](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32016R0679) | Controller notice without undue delay and, where feasible, within 72 hours of awareness, unless the breach is unlikely to risk individuals' rights and freedoms. Late notice needs reasons. | Establish awareness, risk threshold, competent authority and any phased notice. The 72 hour figure is conditional, not a blanket deadline for every incident. |
| UK GDPR, regulator breach notice | [UK GDPR Article 33](https://www.legislation.gov.uk/eur/2016/679/article/33) | Controller notice without undue delay and, where feasible, within 72 hours of awareness, unless unlikely to risk individuals' rights and freedoms. | Establish awareness, risk threshold and competent regulator under current UK law. |
| Zimbabwe CDPA, Authority breach notice | [Cyber and Data Protection Act, section 19, statutory text at ZimLII](https://zimlii.org/akn/zw/act/2021/5/eng%402022-03-11) | A controller must notify the Authority within 24 hours of a security breach affecting data it processes. The Act defines the Data Protection Authority as POTRAZ. | Section 19 does not explicitly say which event starts the 24 hours. A specialist must document that interpretation and any applicable regulations or Authority guidance. The old 72 hour code value was wrong. |
| South Africa POPIA, security compromise | [POPIA section 22, Department of Justice PDF](https://www.justice.gov.za/legislation/acts/2013-004.pdf); [Information Regulator process guidance](https://inforegulator.org.za/wp-content/uploads/2020/07/Guidelines-on-completing-a-Security-Compromise-Notification-ito-Section-22-POPIA.pdf) | Where there are reasonable grounds to believe that personal information was accessed or acquired by an unauthorised person, notify the Regulator and, subject to the statutory exceptions, affected data subjects as soon as reasonably possible after discovery. | No fixed number of hours is stated in section 22. Assess the reason for any delay, the affected persons and current regulator submission procedure. |
| Kenya DPA, commissioner breach notice | [Data Protection Act 2019 section 43, ODPC PDF](https://www.odpc.go.ke/wp-content/uploads/2024/02/TheDataProtectionAct__No24of2019.pdf); [General Regulations 2021, regulations 37 and 38](https://www.odpc.go.ke/wp-content/uploads/2024/03/THE-DATA-PROTECTION-GENERAL-REGULATIONS-2021-1.pdf) | If unauthorised access or acquisition presents a real risk of harm, a controller must notify the Data Commissioner without delay and within 72 hours of awareness. | Record the real-risk assessment, awareness time, controller/processor status and affected-subject communication separately. |
| California consumer rights request | [California Attorney General CCPA guidance](https://oag.ca.gov/privacy/ccpa) | The guidance says businesses normally respond within 45 calendar days, with a further 45 days if they notify the consumer. | This is a consumer request rule, not a universal breach-to-regulator countdown. California breach notice is addressed under separate law. |

## Data subject request timing is request-specific

- EU GDPR Article 12(3) requires action without undue delay and within one calendar month, with a possible two-month extension for complexity or number of requests and notice of extension within the first month. [Official regulation](https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX%3A32016R0679). A fixed 30 day addition does not always equal a calendar month.
- The UK ICO describes a one calendar month limit for subject access, with rules for ID, clarification, extensions and non-working days. [Current ICO guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/individual-rights/right-of-access/what-should-we-consider-when-responding-to-a-request/). This needs a calendar-aware implementation before a legal due date is claimed.
- Kenya General Regulations 2021 regulation 9(4) says an access request must be complied with within seven days. [Kenya Law statutory text](https://new.kenyalaw.org/akn/ke/act/ln/2021/263/eng%402022-01-14). The old generic 21 day claim was not substantiated. Seven days in the legacy registry is now an internal review target for mixed request types; it must not be labelled the legal limit for every type.
- South African personal information access is tied to POPIA section 23 and PAIA procedures. [POPIA](https://www.justice.gov.za/legislation/acts/2013-004.pdf) and [government PAIA information](https://www.justice.gov.za/paia/paia.htm). The registry's generic 30 day DSR number is only an internal target until request-specific applicability is reviewed.
- No statutory general 30 day DSR response period for Zimbabwe CDPA was established in this review. The registry's 30 day value is an internal target only.

## Legacy registry disposition

The legacy list in modules/sentinel/jurisdictions.py has 21 entries. Only the claims above were checked against primary sources in this review. Nigeria, Ghana, UAE, Saudi Arabia, Qatar, Bahrain, Canada PIPEDA, Canada Bill C-11, Brazil, India, Singapore, Australia, New Zealand, Japan and South Korea remain unverified. Do not present any of those entries as legally approved clocks. In particular, an entry named after a bill must not imply that the bill is in force.

The registry now carries separate research states for breach and data subject request periods. Jurisdiction cards and email refer to internal review targets. Unverified breach notes no longer repeat legacy notice claims. Researched states also remain unapproved until a specialist creates and an independent DPO approves a versioned rule card.

Existing breach rows retain their stored deadline when a legacy registry value is corrected. Review every affected open Zimbabwe record; do not silently rewrite an active incident's clock. Record the interpreted statutory trigger, the revised internal target and the specialist who made the change.

For every jurisdiction, the specialist should create a sourced rule card with notice type, trigger definition, period or ASAP state, timezone, effective dates, applicability conditions and a reviewed summary. A different authorised DPO approves the card. An individual breach then needs documented trigger facts and applicability before the rule can supply an operational deadline. The existing broad registry clock remains indicative and may be an earlier internal escalation target.

## Release acceptance still needed

1. Specialist checks the official source version and any later amendments or binding rules.
2. Specialist confirms the exact regulated actor, notice recipient, trigger, threshold, exceptions and effective date.
3. Independent DPO approves wording in a versioned Sentinel card.
4. A breach owner records sourced facts and notification decision for each applicable jurisdiction.
5. User interface and email use only the approved card for legal wording; other targets remain labelled internal.
