# 08 · Contextual AI advisor for compliance work

**Inspiration:** VerifyWise's [AI Advisor](https://verifywise.ai/platform/ai-advisor) and evidence/search patterns; ThemisIQ's opportunity is assistance **inside the record and next action**, not a separate generic chat destination. **Priority:** after scoped search and record contracts. **Size:** L.

## Existing ThemisIQ anchor

Ask ARIA, AI policy generation, Sentinel assessments, BCM planning, Vault search, and global search already offer useful pieces. The [Evidence Vault plan](../../design/evidence-vault/PLAN.md) owns its own “Find evidence” assistant. The first gate is to verify retrieval/index tenant and BU scoping before any cross-module answer.

Two more gates are verified open (code read and one reproduction on 2026-10-07; see [PLAN-37 Section 2 and Appendix A](../PLAN-37-connected-compliance-experience.md)). Related Items and topbar search already show other business units' titles, so scoped retrieval cannot sit on them until they are fixed. And the AI call layer has no shared wrapper: about 70 references in 15 files call `create_message` or `_call_ai`, the signature carries no actor, organization, or feature, usage is not logged (except Ask ARIA's Q&A log), and there is no per-organization provider or data-category policy. Build the AI service foundation (PLAN-37 Slice 1b) first.

## User journey

On a policy, AIIA, DPIA, BCP, risk, control, or audit record, the user chooses a precise action: **Find relevant proof**, **Explain this status**, **Draft the next section**, or **Suggest related records**. The assistant knows the current record and the user's permissions. It returns short, source-linked facts; separates gaps and suggestions; and offers a reviewable draft. A person confirms each write in the owning module. If AI is unavailable, the same sources and manual form remain reachable.

## Build slices

- **A (trusted retrieval):** one permission-aware search and citation contract shared with Vault/global search. Validate source access both before retrieval and immediately before displaying a title, snippet, citation, or draft. Treat document, OCR, email, and web content as untrusted. Provide no-match and stale-source states. Retrieval adapters apply the viewer's module and business-unit scope per source; none reads an unscoped aggregate. Every model call goes through the single wrapper, which refuses a provider or data category the organization has not allowed and records the actor, organization, feature, source IDs, and cost; a guard test fails if code calls the model any other way.
- **B (Find and Explain):** pilot on AI-use workspace and one assessment. Use deterministic state/rule calculations from source services; the model explains why, with citations and a visible “open source” path. Measure top-result relevance, hallucination, citation validity, correction rate, latency, and cost on an anonymized evaluation set.
- **C (Prepare and Suggest):** start with a DPIA/AIIA section and BCP outline, then ARIA policy/procedure/record revisions. Show the source facts, missing inputs, proposed text, and differences before saving as a draft. Evidence/control/link suggestions require explicit confirmation and provenance. Never auto-publish, approve, close, or assert legal applicability.

## Acceptance gates

- Evaluation finds zero unauthorized snippets/citations and every factual answer has a resolvable permitted source or an explicit uncertainty marker. A prompt-injected source cannot override tool or workflow policy.
- No model call bypasses the wrapper (guard test); the organization policy is enforced before the call; usage is attributable per organization and feature; the scope test matrix passes for every source the assistant reads.
- A user can discard or edit a draft without changing the source record; accepted drafts carry author, model/version, source IDs/versions, and approval status.
- Representative users complete a real task faster or with fewer navigation errors than the manual path; AI cost and response time stay within piloted limits.

**Out of scope for first slice:** an autonomous compliance agent, uncited regulatory conclusions, and one chatbot with unrestricted access to every module.
