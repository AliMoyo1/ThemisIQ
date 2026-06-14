# Evidence — Cross-Module Evidence Vault

A single store of evidence files shared across all modules. Files are
content-addressed by SHA-256 hash (so the same file uploaded twice
deduplicates) and tagged with module/entity owners. Background scheduler
sends expiry reminders at 30 / 7 / 1 days before each evidence item's
expiry date.

## Mounts

- `/evidence/` — list.
- `/evidence/upload`, `/evidence/{id}`, `/evidence/{id}/download`.
- `/evidence/api/*` — JSON CRUD.

## Tables

- `evidence_items` — file metadata: path, hash, mime, parent, owners, expiry.
- Files on disk: under `EVIDENCE_DIR` (env-configurable, defaults under `data/`).
  Filenames are `uuid4.ext` to prevent traversal.

## Events

(No outgoing events.)

## Files

| File | Role |
|---|---|
| `routes.py` | Upload, download, listing, deletion |
| `scheduler.py` | Expiry notification cron |
| `__init__.py` | Empty (kept for module discovery) |

## Notes

- Upload validates content type, generates a random filename, and stores the
  hash for dedup.
- `evidence_items.parent_id` lets modules attach evidence to specific
  controls / breaches / incidents; the cross-module link is also recorded in
  `cross_module_links` when needed.
