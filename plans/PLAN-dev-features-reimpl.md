# Dev Branch Features: Clean Re-implementation in Production

## Status: IN PROGRESS

Re-implementing 4 features from ThemisIQ-dev branches into production
with all bugs fixed and org_id tenant isolation added.

## Feature 1: WhatsApp Connector
**Source:** dev commit 88af0d6
**Files:**
- core/notifications.py: add _whatsapp_url(), send_whatsapp(), update notify_connectors/connectors_status
- modules/launcher/routes_admin.py: add whatsapp GET/save/test/delete endpoints
- modules/launcher/templates/admin_connectors.html: add WhatsApp panel + JS
**Bugs fixed from dev:**
- setStatus JS: two-way ternary didn't handle 'whatsapp' (rewrite to use if/else chain)
- Duplicate MFA section removed
**Status:** NOT STARTED

## Feature 2: Governance Timeline
**Source:** dev commit 319d69e
**Files:**
- modules/launcher/routes_platform.py: _EVENT_LABELS, _ENTITY_TYPE_ALIAS, api_timeline(), timeline_page()
- modules/launcher/templates/timeline.html: full SPA page
- templates/_icon_sidebar.html: timeline nav icon
**Bugs fixed from dev:**
- Missing org_id WHERE filter on audit_log query (CRITICAL tenant isolation)
- Added capability gate (platform.view_audit)
**Status:** NOT STARTED

## Feature 3: Evidence Confidence Score
**Source:** dev commit 080a469
**Files:**
- database.py: 4 column migrations (verification_method, verified_by, verified_at, confidence_score)
- modules/evidence/routes.py: compute_confidence(), recompute_confidence(), verify/unverify endpoints
- modules/evidence/templates/evidence_index.html: confBadge, detail drawer, verify modal
**Bugs fixed from dev:**
- Scheduler import from nonexistent data_service (use routes.recompute_confidence instead)
- Missing org_id isolation on verify endpoints
- Column migrations placed in _COLUMN_MIGRATIONS list (not standalone ALTER TABLE)
**Status:** NOT STARTED

## Feature 4: Related Items Panel
**Source:** dev commit 3c2a7f2
**Files:**
- modules/launcher/routes_platform.py: _LINKABLE registry, GET/POST/DELETE link endpoints
- static/js/related_items.js: RelatedItems.mount() component
- 3 module templates: mount the component in entity drawers
**Bugs fixed from dev:**
- JS crash: doLink/unlink defined as window.RelatedItems.X but referenced as bare names in IIFE return
- Connection leak: open db2 per link row in GET; batch into single query instead
- Relationship values misaligned with core/links.py (dev had triggered instead of triggers, plus missing implements/escalated_to/derived_from/audits/elevated_to)
- Missing org_id isolation on all 3 endpoints
**Status:** NOT STARTED

## Implementation Order
1. WhatsApp Connector (simplest, isolated to notifications)
2. Evidence Confidence Score (isolated to evidence module)
3. Governance Timeline (reads audit_log, no schema changes)
4. Related Items Panel (cross-module, builds on existing cross_module_links)

## Change Log
- [start] Created plan file
- [done] Feature 1: WhatsApp Connector - core/notifications.py, routes_admin.py, admin_connectors.html
- [done] Feature 2: Governance Timeline - routes_platform.py (api_timeline + timeline_page), timeline.html, _icon_sidebar.html
- [done] Feature 3: Evidence Confidence Score - database.py (4 column migrations), routes.py (compute_confidence, recompute_confidence, verify endpoints, wired into update/link create/delete), evidence_index.html (confBadge, drawer section, table column)
- [done] Feature 4: Related Items Panel - routes_platform.py (3 endpoints, batched title lookup, org_id isolation), static/js/related_items.js (fixed JS crash: doLink/unlink now in return object directly)
