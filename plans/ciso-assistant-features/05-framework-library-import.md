# 05. Versioned customer framework import

**Status:** Early discovery and conditional one-framework pilot; broad catalogue rollout remains later. Updated 2026-10-08 after the [attachment review](ATTACHMENT-REVIEW-2026-10-08.md). **Owner:** ARIA/GRID framework catalogues and mapping review. **Inspiration:** CISO Assistant's [custom libraries](https://github.com/intuitem/ciso-assistant-community/blob/main/product-docs/configuration/libraries/custom-libraries.md). Start implementation only after direct-mapping semantics, content rights and customer demand are established.

## Value and current state

A customer should be able to bring an internal control standard or licensed regulatory checklist into ThemisIQ without rekeying hundreds of rows. The platform already has `/admin/frameworks`, custom framework creation and activation, `core/framework_service.py` control entry/bulk operations, mappings and a separate ERM `/api/frameworks/import` route. This review did not confirm a general governed, versioned import/update workflow. Import is a content-governance feature, not merely a spreadsheet upload. Begin format/ID discovery early because stable framework editions support reuse and assignments; sequence a production importer after permission, mapping and historic-reference design.

## Discovery before build

Collect two authorized, anonymized customer examples and document the authoritative owner, file format, IDs, hierarchy, applicability conditions, version policy, permitted users, and rights to the source text. Decide whether the imported framework is for ARIA governance, GRID audit, ERM, or a clearly specified combination. Trace current `frameworks`/`controls`, ARIA/GRID mappings, ERM imports, audit snapshots and seed behavior in PostgreSQL before choosing one writer. Determine how later editions affect existing audits and evidence links. Do not ingest CISO Assistant's bundled framework text or mappings merely because they are in its repository; review the [repository license](https://github.com/intuitem/ciso-assistant-community/blob/main/LICENSE.md) and each framework publisher's terms independently.

## Proposed slices

1. **Template and validation.** Define a small CSV/XLSX schema for framework metadata, edition/version, stable external requirement ID, parent ID, structural-versus-assessable flag, title, text, optional guidance and mapping references. Keep stable IDs across editions so a renumbering is an explicit migration, not a new match guessed from title. Reject duplicate IDs, cycles, impossible parent relationships, formula payloads and oversized/unsupported files. Store an upload checksum and owner; never execute spreadsheet content.
2. **Dry-run preview.** Parse into a temporary staging record and show counts, conflicts, missing fields, changed requirement text, removed IDs, mapping impacts and examples before any write. The importer has no access to another tenant's library or audit.
3. **Versioned commit.** Create a new immutable framework edition rather than editing or upserting requirements already used by signed audits. Record actor, source rights declaration, file digest and import manifest. Enforce scoped permissions and one transaction per edition; a failed import leaves the previous edition usable. Decide where edition and node identity live only after tracing existing unified, ARIA, GRID and ERM references.
4. **Impact and migration review.** Show which ARIA controls, GRID audits, mappings and evidence relationships point to the older edition. Suggest renumbered matches but require a reviewer to approve each migration. Historical audit decisions keep the exact prior framework version.
5. **Export and rollback.** Let an authorized owner export the customer-owned edition and mappings in a documented format. “Rollback” means deactivate the new edition and restore the earlier active pointer after dependency checks, not erase historical audit references.

## Acceptance outcomes

- A 500-row customer framework imports through a readable preview with clear errors, bounded resource use and no partially written edition.
- Re-importing the same version/digest is idempotent; changed content requires a new edition and impact review.
- Old signed audits remain reproducible with their original wording, mappings and evidence links.
- An out-of-scope actor cannot discover or import into another tenant/BU; imported text is treated as untrusted data in UI, search, exports and later AI retrieval.

**Not in this plan:** a bulk scrape of global standards, automatic compliance equivalence, live legal interpretation, or cross-tenant framework-content sharing.

**Pilot gate:** One customer-owned framework can be previewed, imported, updated to a second edition and deactivated without changing historic GRID/ARIA decisions. Do not pre-seed third-party ISO, NIST or statutory text until rights, version provenance and maintenance ownership are established.
