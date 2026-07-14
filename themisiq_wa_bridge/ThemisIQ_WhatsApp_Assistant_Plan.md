# ThemisIQ WhatsApp Assistant — Planning Document
### Part A: Technical Architecture & MVP Scope  ·  Part B: Data Protection Impact Assessment (DPIA)

**Version 0.1 (Draft for review)**
**Prepared:** 2026-07-10
**Author:** AI-assisted draft (for Ali Moyo — DPO / ISO 42001 Lead)
**Status:** DRAFT — not yet approved. Requires DPO sign-off + controller sign-off before build.

> Scope of this document: a WhatsApp-connected AI assistant that lets authorised ThemisIQ users interact with the platform (read records, trigger AI generation, ask compliance questions) from a mobile messaging channel. It is a *new processing activity* and a *new AI system* under the platform's existing governance.

---

# PART A — Technical Architecture & MVP Scope

## A.1 System context (from ThemisIQ Platform Manual v1.0)

ThemisIQ is a FastAPI (Python) app on Linux VPS, behind Cloudflare + Nginx, PostgreSQL with **per-tenant schema isolation**. It already exposes:

- **REST API** — Command Centre → Developer → API Keys. Keys are shown once, scoped **read-only / read-write per module**, revocable, with a usage log.
- **Webhooks** — Command Centre → Developer → Webhooks. HTTPS endpoint + secret; HMAC-SHA256 signed payloads (`X-ThemisIQ-Signature`); event types include `risk.created`, `breach.declared`, `dsr.received`, `document.approved`, `kri.threshold.breached`, etc. Failed deliveries retried 3× with backoff.
- **AI providers** — Claude / DeepSeek / Ollama / OpenAI / Gemini, selected via `AI_PROVIDER` env var. Used today for AI Policy Generation, gap analysis, board reports.

This means the platform is already integration-ready. The WhatsApp assistant is an *external client* of these existing surfaces — minimal changes to ThemisIQ core are required.

## A.2 Target architecture

```
                         ┌─────────────────────────────────────────────┐
   WhatsApp user         │            THEMISIQ (themisiq.net)           │
   (authorised          │  FastAPI app · RBAC · multi-tenant PG        │
    ThemisIQ user)      │                                             │
        │               │   • REST API (scoped keys)  ◄──┐            │
        │ text          │   • Webhooks (HMAC out)  ──────┤            │
        ▼               │   • AI Provider (Claude etc.)  │            │
   ┌──────────┐  webhook │                               │            │
   │ WhatsApp │──────────▶│   ┌──────────────────────────┴─────────┐  │
   │ Business │  message  │   │      ThemisIQ Bridge (NEW)          │  │
   │ Platform │◀─────────│   │      (small FastAPI service)        │  │
   │ (Meta/   │  reply    │   │  • verify signature                │  │
   │  Twilio) │          │   │  • map WA user → tenant + role      │  │
   └──────────┘          │   │  • enforce per-user RBAC/scopes      │  │
                         │   │  • call ThemisIQ REST API            │  │
                         │   │  • orchestrate LLM (intent+answer)   │  │
                         │   │  • rate limit / audit every call     │  │
                         │   └──────────────────────────────────────┘ │
                         └─────────────────────────────────────────────┘
```

## A.3 Components & responsibilities

| Component | Responsibility | New? |
|---|---|---|
| WhatsApp Business Platform (Meta Cloud API **or** Twilio) | Receive inbound messages via webhook; send replies via API; phone-number verification | No (external) |
| **ThemisIQ Bridge** | The new service. Authenticates the WhatsApp user, maps them to a tenant + role, enforces RBAC, calls ThemisIQ REST API, orchestrates the LLM, audits every action, rate-limits | **YES** |
| ThemisIQ REST API | Source of truth for records (Sentinel/ERM/ARIA/Command Centre). Called with a **per-tenant scoped API key** | No (exists) |
| ThemisIQ Webhooks | Optional: push events (e.g. `breach.declared`, `kri.threshold.breached`) *into* the bridge so the assistant can proactively alert users | No (exists) |
| LLM provider | Natural-language understanding + answer/policy drafting | No (exists) |

## A.4 Integration approach

- **Inbound (user → action):** WhatsApp webhook → Bridge verifies payload → Bridge identifies the user (see A.5) → Bridge calls ThemisIQ REST API using a **read-only key scoped to that user's modules** → formats reply → posts to WhatsApp.
- **Proactive (event → user):** ThemisIQ Webhook (`breach.declared`, `kri.threshold.breached`, `task.overdue`, etc.) → Bridge verifies HMAC → Bridge maps `organisation_id` to subscribed users → sends alert via WhatsApp API.
- **AI drafting:** Bridge calls the LLM (reusing the same provider ThemisIQ already uses) to interpret free text, draft policy/DSR text, or summarise records returned from the API.

## A.5 Authentication & tenancy model (important)

Per-tenant schema isolation means **the bridge must never mix tenants**. Recommended model:

1. Each WhatsApp number/account is pre-linked to **one ThemisIQ user ID + tenant** (binding done once in admin, not inferable from the message).
2. The bridge holds a **single read-only API key per tenant**, scoped to the minimum modules the assistant needs (start: Sentinel read, ERM read, Command Centre read).
3. The bridge enforces the user's **role-based permissions** — a user can only ask for what their ThemisIQ role permits. The bot is not a privilege escalation path.
4. Bridge logs every call (who, what, when, tenant) — feeds both ThemisIQ audit expectations and the DPIA record.

## A.6 MVP scope — Phase 1 (recommended first release)

Keep Phase 1 **read-only + Q&A** to minimise risk and satisfy the DPIA's necessity test:

- ✅ *"List my open DPIAs / DSRs / breaches"* → Sentinel API read
- ✅ *"What's our current risk score / KRI status?"* → ERM / Command Centre read
- ✅ *"Summarise document/policy X"* → ARIA read
- ✅ *"Draft a GDPR breach-notification text for incident #N"* → LLM (no write)
- ✅ *"What does CDPA / GDPR require for X?"* → LLM knowledge answer
- ✅ Proactive alerts via webhook (breach declared, KRI breached, task overdue)
- ❌ No writes to live records in Phase 1 (no "close this risk", no "approve document")

## A.7 Out of scope (later phases, post-DPIA-review)

- Write actions (create risk, update control status, approve document) — needs expanded DPIA + stronger auth (MFA re-prompt inside WhatsApp flow).
- Multi-tenant shared numbers / public unauthenticated bots.
- Voice / media processing (heightened special-category risk).

## A.8 Suggested bridge tech stack

- **FastAPI (Python)** — matches ThemisIQ; reuses its middleware patterns (sanitize, body-limit, CORS-block).
- Hosted same VPS or separate, behind Cloudflare (the manual already uses it for WAF/bot-mgmt/DDoS).
- Secrets in `.env` (not git — the manual's F-01/F-02/F-08 show past secret-exposure findings; keep discipline).
- Audit log table (append-only), retention aligned to ThemisIQ's 7-year minimum.
- Rate limiting on the inbound webhook (protect against WhatsApp spam / cost blow-up).

## A.9 Key design decisions to lock before build

1. **Thin read-only MVP first** (A.6) — proves value, bounds the DPIA.
2. **Per-tenant API keys, least privilege** — use ThemisIQ's existing scoped keys.
3. **HMAC verify both directions** — inbound WA payload + outbound ThemisIQ webhook.
4. **No secrets in URLs / git** (learned from the platform's own findings F-01/F-08).
5. **Explicit privacy notice** shown on first interaction ("This bot processes your instructions under GDPR/CDPA; logs are retained X days").

---

# PART B — DATA PROTECTION IMPACT ASSESSMENT (DPIA)

**Frameworks applied:** GDPR Articles 35 & 30 · Zimbabwe CDPA SI 155 of 2024 · ISO/IEC 42001:2023 (AI management system) · ISO 27701 (privacy info management).

## B.1 Does a DPIA apply? (Art. 35 trigger analysis)

A DPIA is required where processing is "likely to result in a high risk." This project meets **multiple** criteria:

- ✅ Large-scale evaluation of personal data (DPIAs, DSRs, breach records of data subjects) — Art. 35(3)(a)
- ✅ Systematic monitoring (proactive webhook alerts on individuals' compliance matters) — Art. 35(3)(c)
- ✅ Innovative technology / AI-driven profiling & decision support — Art. 35(3)(b) + ISO 42001
- ✅ Processing of special-category-adjacent data possible (health/BCM, DSARs) in Sentinel/BCM modules

**Conclusion: DPIA is mandatory.** Proceed only after DPO + controller sign-off.

## B.2 Nature, scope, context, purposes

| Field | Detail |
|---|---|
| **Controller** | ThemisIQ operator / customer organisation (per tenant) |
| **Processors (new)** | (1) WhatsApp Business Platform — Meta Platforms Inc.; OR Twilio Inc. (2) LLM provider already in use (Anthropic/DeepSeek/OpenAI/Gemini) |
| **Data subjects** | Authorised ThemisIQ users (staff); indirectly, the data subjects named in Sentinel/ERM/DSR records they query |
| **Personal data processed** | User identifier (phone→tenant mapping), message content (may contain names, incident details, DSR references), ThemisIQ record excerpts returned to the user, LLM prompt/completion text |
| **Purpose** | Enable authorised users to query and receive compliance information from ThemisIQ via a mobile messaging channel; proactive compliance alerts |
| **Lawful basis (primary)** | **Art. 6(1)(f) legitimate interests** (operational efficiency for the controller's own staff) — *or* Art. 6(1)(b) where the user is bound by employment/contract. DPIA itself does not determine basis; see B.8. |
| **Retention** | Message logs: proposed **90 days** (tunable); audit log: **7 years** per ThemisIQ policy (B.9) |

## B.3 Necessity & proportionality

- **Necessary?** The channel delivers compliance info to mobile staff who are not at a desktop — a genuine operational need, especially for breach/KRI alerts with statutory deadlines.
- **Proportionate?** Yes *if* Phase 1 is read-only and scoped to the user's own tenant/role. Write-actions (later phases) would require re-assessment.
- **Less intrusive alternative?** A mobile-responsive web view exists; however WhatsApp is the channel users actually monitor in real time. The intrusion is low and consent/notice-based.

## B.4 Risk to rights & freedoms — risk register

| ID | Risk | Affected | Likelihood | Severity | Measure (see B.5) |
|---|---|---|---|---|---|
| R1 | Unauthorised access to another tenant's data (tenant-mapping flaw) | All subjects in other tenants | Low | High | M1, M2, M3 |
| R2 | Privilege escalation via the bot (user acts beyond role) | Users | Low | High | M2, M4 |
| R3 | Intercepted/leaked message content in transit or at Meta/Twilio | Data subjects | Medium | Medium | M5, M6 |
| R4 | LLM hallucination → wrong compliance advice → wrong decision | Users, subjects | Medium | High | M7, M8 |
| R5 | LLM provider trains on / retains prompt data (confidential record excerpts) | Data subjects, controller | Medium | High | M6, M9 |
| R6 | Missing/incomplete audit trail → undetectable misuse | Controller | Low | Medium | M4, M10 |
| R7 | Excessive retention of message logs → breach blast-radius | All | Low | Medium | M11 |
| R8 | WhatsApp account takeover → impersonation of assistant | Users | Low | Medium | M12 |
| R9 | Special-category data (health/BCM) surfaced without need | Data subjects | Low | High | M2, M13 |

## B.5 Mitigating measures

- **M1** Per-tenant API keys; bridge never crosses tenant boundaries (A.5).
- **M2** Bridge enforces the user's ThemisIQ RBAC; only returns what the role permits; modules scoped to minimum (read-only).
- **M3** Bind WA number → tenant+user **once in admin**; never infer tenancy from message content.
- **M4** Every action audited (who/what/when/tenant) in append-only log; aligned to ThemisIQ 7-yr retention.
- **M5** TLS enforced end-to-end; webhook payloads HMAC-verified both directions.
- **M6** Use **zero-retention / enterprise** LLM tier; never send full record bodies to the LLM — send only minimal fields needed; redact names where possible.
- **M7** LLM answers flagged "AI-generated, verify before acting"; bot does not auto-execute.
- **M8** Phase 1 read-only; no autonomous writes/decisions.
- **M9** DPA with LLM vendor; confirm no training-on-data clause (ISO 42001 A.6.x / supplier control).
- **M10** Rate limiting + anomaly alerting on the bridge.
- **M11** Message logs retained **90 days** then auto-purged; audit log separate and longer.
- **M12** WA Business account with 2FA; monitor for suspicious send patterns.
- **M13** Suppress special-category modules from MVP; require explicit opt-in + DPIA addendum before enabling.

## B.6 Residual risk & conclusion

After M1–M13, residual risk is **LOW–MEDIUM** for Phase 1 (read-only, scoped, audited, notice-based). This is acceptable **provided** sign-offs below are obtained and M6/M9 (LLM zero-retention + DPA) are confirmed before go-live.

> ⚠️ Any move to **write actions** or **special-category modules** re-opens this DPIA and requires a supplementary assessment.

## B.7 Sub-processors to add to the ROPA / processor register

| Sub-processor | Role | Required artefact |
|---|---|---|
| Meta Platforms Inc. (WhatsApp Business) **or** Twilio Inc. | Messaging transport | DPA / sub-processor entry; document data residency & lawful basis for transferring message metadata |
| LLM vendor (existing) | Inference | Confirm zero-retention; DPA addendum if not already covering this use |

These join the processors already in ThemisIQ's ROPA (Cloudflare, Nginx host, PostgreSQL, Sentry, PostHog, UptimeRobot).

## B.8 Lawful basis (to finalise with controller)

- **Primary:** Art. 6(1)(f) legitimate interests — efficiency for the controller's staff. A **Legitimate Interests Assessment (LIA)** should accompany this DPIA.
- **Alternative where applicable:** Art. 6(1)(b) contractual necessity (employment/engagement).
- **Special-category data (if later enabled):** Art. 9 condition required (e.g. Art. 9(2)(b) employment/social-security, or explicit consent) — out of MVP scope.

## B.9 Retention & deletion

- **Message content logs:** 90 days, then automated purge (tunable per tenant policy).
- **Audit log (who/what/when/tenant):** 7 years, immutable, per ThemisIQ audit-log policy.
- **LLM prompt/completion:** not persisted by the bridge; rely on vendor zero-retention (M6).

## B.10 ISO 42001 angle (AI governance)

This assistant is an **AI system** under ISO/IEC 42001. As ISO 42001 Lead Implementer you'll want:
- AI Policy + Statement of Applicability entries covering the bot.
- AI risk register item: *"Hallucinated compliance advice"* (R4) — treatment = M7/M8 + human-in-the-loop.
- Document the model provider, prompting approach, and the no-auto-execute control in the AI risk register.
- Note in the bot's privacy notice that responses are AI-generated.

## B.11 Required approvals before build

- [ ] DPO review & sign-off (Ali Moyo)
- [ ] Controller / Senior management sign-off
- [ ] Legitimate Interests Assessment (LIA) attached
- [ ] LLM vendor zero-retention + DPA confirmed (M6/M9)
- [ ] ROPA updated with new sub-processors (B.7)
- [ ] Privacy notice for the bot drafted (first-interaction message)

---

## Appendix — Open questions for the controller

1. Meta Cloud API vs Twilio — which (affects sub-processor + cost + data residency)?
2. Which modules in MVP — Sentinel + ERM + Command Centre (recommended) or narrower?
3. Retention: accept 90-day message log default, or shorter?
4. Will proactive webhook alerts be enabled at launch, or MVP read-only first?
