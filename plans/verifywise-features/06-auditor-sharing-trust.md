# 06 · Auditor sharing and customer trust

**Inspiration:** VerifyWise [share links](https://verifywise.ai/user-guide/ai-governance/share-links) and [AI Trust Center](https://verifywise.ai/user-guide/ai-governance/ai-trust-center). **Priority:** after Vault scope and version gates. **Size:** M.

## Existing ThemisIQ anchor

GRID already has `grid_share_links` and authenticated audit-scoped APIs in `oneforall/modules/grid/routes.py` (create/validate/revoke). Current creation is capability-checked, targets a same-organization signed-in GRID recipient, and has expiry. Evidence Vault plans library search, versions, verification, and scoped access. This feature **extends** the existing restricted share flow; it is not a new public audit-link system.

## User journey

An audit owner selects a specific audit, control set, and permitted evidence versions to assemble a **review pack**. A review screen lists included records, missing or expired proof, redactions, intended recipient, expiry, and download rights. The owner issues access to a named, authenticated recipient. The recipient sees a clean read-only pack with an index, scope, source dates, and clearly marked gaps. The owner can revoke access and see access history. A separate later trust page can publish only approved, intentionally public organization statements.

## Build slices

- **A (extend GRID sharing):** preserve current signed-in, same-org, permission-checked recipient model. Add pack manifest and per-item authorization on view/download, exact Vault version IDs, expiry/revocation, optional watermark, access log, and safe export. A snapshot must remain stable even when source records change, while clearly flagging revoked or no-longer-permitted content.
- **B (cross-module pack):** after Vault search/scope is stable, let the audit owner include permitted ARIA policies, Sentinel assessments, BCM exercise records, ERM risks, and ORM controls via links to authoritative records. A reviewed copy/export has a manifest and explicit coverage status; links never bypass the home module's access rules.
- **C (optional trust page):** separate publishing permission, content approval, expiration/review date, preview, and public-safe field allowlist. No automatic publication of customer documents, evidence, badges, assessment results, or compliance claims.

## Acceptance gates

- A revoked, expired, wrong-recipient, wrong-org, or permission-lost share yields no pack metadata or file content. Direct object URLs and exports obey the same checks as the page.
- The manifest reproduces the selected record and evidence versions, pack owner, intended audience, generation time, unresolved gaps, and access events.
- An auditor can find the requested proof and its context without navigating the full app; the owner can correct or withdraw a pack without destroying the original audit record.

**Out of scope for first slice:** anonymous public evidence links and claims that a control is compliant merely because a file is attached.
