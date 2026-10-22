# Removing inline script execution from ThemisIQ

Current application CSP in `oneforall/core/middleware.py` retains `script-src 'unsafe-inline'`. It must stay until every inline script block and HTML event handler is migrated. Removing it today would disable navigation, forms and module actions.

## Current inventory and first slice

The shared `oneforall/templates/base_shell.html` now uses event listeners for its static shell actions and rendered search/modal actions. Its five executable script blocks were moved, in the same load order, to `oneforall/static/js/shell_*.js`. The AI policy admin page script was also moved to `oneforall/static/js/admin_ai_policy.js`. A read-only search on 2026-10-21 found 1,546 remaining HTML lines with common inline event attributes across module templates after the shell slice. The largest files were ERM (231), ORM (176), GRID (171), BCM (165), Sentinel (149) and Evidence Vault (106). The count is a migration estimate, not a complete parser-based security finding.

## Migration order

1. Extract script blocks that have no template variables into versioned files under `oneforall/static/js`. Carry server values through escaped `data-*` attributes or `application/json` data with no executable inline text. Preserve load order and existing public APIs used by module scripts.
2. For each module, replace constant event attributes with named controls and `addEventListener`. For repeated rows use one delegated listener plus validated `data-action` values. Keep dynamic IDs and user text as data only. Start with ERM, ORM, GRID, BCM, Sentinel and Evidence Vault based on the inventory above.
3. Search generated HTML as well as static templates for handlers and `javascript:` URLs. A static template search alone misses strings assembled in JavaScript or returned from the server.
4. Move legitimate third-party bootstraps to reviewed local files where possible, restrict external script hosts to those actually used, and set an appropriate `connect-src` for the configured provider. Do not add a blanket nonce to every script tag or allow an arbitrary host to restore behavior.
5. Introduce a report-only script policy without `unsafe-inline` and inspect violations on representative pages for every role and module. After fixing them and confirming critical workflows, enforce the strict policy. Keep `style-src` as a separate decision because inline style attributes are also widespread.

Track remaining handler and inline-block counts in each migration PR. Do not claim CSP enforcement while `script-src 'unsafe-inline'` remains installed.

## Continuation on the landing-page master, 2026-10-21

The AI Governance templates now use one static bootstrap script. Page-specific values move through HTML-escaped `data-*` attributes. The shared shell already loads external scripts, so HTML responses under `/ai-governance/` can enforce a script policy without `unsafe-inline`, disallow script attributes, and omit the general CDN hosts. Other routes keep the existing policy until their handlers move out of executable attributes.

Stored names and descriptions were also removed from inline handlers in the ARIA control, mapping and template views, GRID framework, vendor and audit actions, BCM's Sentinel dependency prompt and resource controls, Sentinel's transfer and jurisdiction actions, ERM risk deletion and AI-assisted assessment actions, workflow actions, and administrator actions. Evidence Vault internal links, Sentinel notices and ERM external-source links now reject unsafe URL schemes. The shared shell and common module HTML-escape helpers now encode quote characters when their result is used inside HTML attributes. HTML escaping does not make a value safe inside JavaScript source, so remaining dynamic handlers still need to be replaced.

The current static search still finds roughly 1,500 inline event attributes across module templates. This is a migration inventory, not evidence of an active exploit. The remaining module pages must receive the same data-attribute and listener treatment before the global `unsafe-inline` exception can be removed. Browser exercise is required before enforcing any stricter policy beyond AI Governance.

## Shared guide correction, 2026-10-22

The enforced AI Governance script policy exposed an overlooked common include: `_platform_trainer.html` still contained an executable inline block and six inline event handlers. The guide logic now loads from `static/js/platform_trainer.js`, and its controls use event listeners. This preserves the strict AI Governance policy and the guide's open, close, and tooltip interactions. Accessibility tests load their locally vendored axe script through a test-only same-origin route, so the tests do not need an inline-script exception. Focused AI Governance assessment, guide, and security-header tests passed locally; the full browser run remains a separate release gate.
