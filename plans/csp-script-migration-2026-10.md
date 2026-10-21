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
