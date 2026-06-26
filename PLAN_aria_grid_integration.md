# PLAN: ARIA-GRID Auto-Attachment Integration

## What exists already (don't duplicate)
- `attach_aria_policy_as_evidence(control_id, aria_doc_id, user_id)` in grid/data_service.py — creates a grid_evidence_files record with file_path="aria://documents/{id}"
- `list_aria_policies(framework_name, control_ref)` — already uses LIKE for comma-separated refs
- `GET /api/aria-policies` and `POST /api/controls/{cid}/attach-aria-policy` — manual attach works
- ARIA documents edit modal already has a multi-ref tag picker (edit-control-search / edit-ctrl-tags / hidden edit-control-ref)
- control_ref field already split by comma on display (line 802 documents.html)

## What's broken
- Download endpoint `/api/evidence/file/{eid}/download` tries `Path("aria://documents/5").exists()` — 404 on any ARIA-linked file
- Download-all ZIP skips ARIA-linked files silently
- No auto-trigger on ARIA document save/upload

## What's missing
1. Auto-attach trigger in ARIA routes (add_document, update_document, upload_document_revision)
2. Bulk auto-scan endpoint `POST /api/audits/{aid}/auto-attach-policies`
3. `GET /api/controls/{cid}/suggested-policies` (unattached matching policies)
4. Visual distinction for ARIA-linked evidence rows in GRID (_evFileHtml)
5. Suggested policies panel when a control is opened
6. Auto-attach button on the audit toolbar

## Exact Changes

### A. grid/data_service.py
Add after `attach_aria_policy_as_evidence`:
- `auto_attach_aria_policies_for_document(aria_doc_id, system_user_id=0)` — called by ARIA after save; finds all active-audit GRID controls matching this doc's framework+refs and attaches
- `auto_attach_aria_policies_to_audit(audit_id, system_user_id=0)` — bulk scan for one audit
- `get_suggested_aria_policies(control_id)` — returns matching ARIA docs NOT yet attached to this control

### B. grid/routes.py
- Fix `api_evidence_download`: detect `aria://` prefix in file_path, extract doc_id, redirect to `/aria/documents/{doc_id}/download`
- Fix `api_evidence_download_all`: skip files where file_path starts with `aria://` (add a note in ZIP with filename "see-aria-library.txt")
- Add `POST /api/audits/{aid}/auto-attach-policies` calling `ds.auto_attach_aria_policies_to_audit(aid)`
- Add `GET /api/controls/{cid}/suggested-policies` calling `ds.get_suggested_aria_policies(cid)`

### C. aria/routes.py
- In `add_document()`: after commit, if control_ref, spawn auto-attach (import grid ds)
- In `update_document()`: after commit, if control_ref in updated fields, spawn auto-attach
- In `upload_document_revision()`: after commit, spawn auto-attach

### D. grid/templates/index.html
- In `_evFileHtml`: detect `f.mime_type === 'application/x-aria-policy'`, render differently:
  - Purple "ARIA Policy" badge instead of file extension colour
  - Download button points to `/aria/documents/{doc_id}/download`
  - Remove "Upload new version" button (can't version an ARIA-linked ref)
  - Show framework + control ref from notes (parse `framework=` and `ref=`)
- Add function `loadSuggestedPolicies(cid)` that fetches `/grid/api/controls/{cid}/suggested-policies`
- Add suggested-policies section in the control detail panel, rendered after evidence list
- Add "Auto-Attach" button in audit toolbar/header (calls `POST /grid/api/audits/{aid}/auto-attach-policies`)

## Status
- [x] A: data_service additions
- [x] B: routes fixes + new endpoints
- [x] C: ARIA auto-trigger
- [x] D: frontend changes
