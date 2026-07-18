# PLAN: Replace deprecated Claude model IDs

Date: 2026-07-18
Branch: claude/vibrant-keller-d6587a (worktree ecstatic-jemison-1ec81a)

## Problem

The fallback model "claude-sonnet-4-20250514" is deprecated and its retirement
date (June 15, 2026) has passed. API calls that hit the fallback now fail with
404 not_found_error. The WA bridge separately hardcodes "claude-sonnet-4",
which was never a valid model ID.

## Changes

1. oneforall/config.py line 52: ANTHROPIC_MODEL env default
   "claude-sonnet-4-20250514" to "claude-sonnet-5" (current Sonnet alias).
2. oneforall/core/ai_client.py line 51: provider map fallback
   "claude-sonnet-4-20250514" to "claude-sonnet-5".
3. oneforall/core/ai_client.py line 56: unknown-provider fallback
   "claude-sonnet-4-20250514" to "claude-sonnet-5".
4. themisiq_wa_bridge/app/config.py line 62: ai_model default
   "claude-sonnet-4" to "claude-opus-4-8". This value follows the bridge's own
   PLAN-03-bridge-alignment.md, which prescribes claude-opus-4-8 for this exact
   field, not claude-sonnet-5.
5. themisiq_wa_bridge/.env.example line 35: AI_MODEL=claude-sonnet-4 to
   AI_MODEL=claude-opus-4-8, also per PLAN-03.

Out of scope: themisiq_wa_bridge/plans/*.md already reference claude-opus-4-8
(valid alias), no edits needed there.

## Verification

- py_compile on the three touched .py files.
- Full pytest suite from the repo root.
- VPS .env: cannot be checked from this machine. Whether ANTHROPIC_MODEL is set
  on the VPS is unknown; if it is set to a retired ID, the fallback fix will
  not help there. Flagged in the summary.

## Change log

- DONE Edit 1: oneforall/config.py line 52, ANTHROPIC_MODEL default now claude-sonnet-5
- DONE Edit 2: oneforall/core/ai_client.py line 51, provider map fallback now claude-sonnet-5
- DONE Edit 3: oneforall/core/ai_client.py line 56, unknown-provider fallback now claude-sonnet-5
- DONE Edit 4: themisiq_wa_bridge/app/config.py line 62, ai_model default now claude-opus-4-8
- DONE Edit 5: themisiq_wa_bridge/.env.example line 35, AI_MODEL now claude-opus-4-8
- DONE py_compile on all three .py files: OK
- DONE pytest from repo root: 114 passed. themisiq_wa_bridge/tests/test_smoke.py
  fails at collection with ModuleNotFoundError: pydantic_settings. Pre-existing
  environment gap (fails at app/config.py line 16 import, before the edited
  line); the rest of the suite ran with --ignore=themisiq_wa_bridge.
- DONE local env check: oneforall/.env exists but does NOT set ANTHROPIC_MODEL,
  so the local app was running on the retired fallback. VPS .env not checkable
  from this machine; status unknown.
