# PLAN-14: Fix Ask ARIA AI - Error Handling + UX Improvements

## Status: COMPLETE (2026-07-15)

## Root causes found

1. **`routes.py:2882`** - dead-code error logger: checks `result.get("ok", True)` but the
   key is `"success"`, so the block never fires and the overwrite `result["error"] = "AI
   processing failed"` does nothing. The ask_service error IS returned to the frontend as-is.
   Fix: correct the key and drop the overwrite so better messages flow through.

2. **`ask_service.py:542-557`** - generic error message: RuntimeError from an expired/missing
   API key gives the same "AI processing failed" as a network timeout. User can't tell if
   it's a config issue vs temporary failure.
   Fix: check error message text to distinguish key-not-configured vs call-failed.

3. **`ask.html` catch block** - network/JSON-parse errors (e.g. server returned HTML 500):
   `typing.remove()` runs, a brief toast appears, but no error bubble is added to the chat.
   User sees their message with no response and the typing indicator gone.
   Fix: add an error bubble in the catch block too.

## Files

- `oneforall/modules/aria/routes.py` - fix dead-code block lines 2882-2884
- `oneforall/modules/aria/ask_service.py` - better error messages lines 542-557
- `oneforall/modules/aria/templates/ask.html` - fix catch block around line 650

## GRID compliance chat check

`grid/routes.py:1472` raises `HTTPException(502, str(e))` - this is a non-JSON
502 response. The GRID chat frontend needs to handle this. Checking separately.

## Changes log

- [x] Fix `ask_service.py` error messages: RuntimeError "not configured" vs general failure
- [x] Fix `routes.py` dead-code: correct key from "ok" to "success", drop overwrite
- [x] Fix `ask.html` catch block: add error bubble to chat on network/parse errors
- [x] py_compile all touched files: OK
- [x] pytest full suite: 114/114 passing
- [x] Fix `ask.html` button: change type="submit" to type="button" + explicit click handler
  - Root cause of "message disappears": if the IIFE threw before the submit listener
    attached, the type="submit" button would do a GET form submission, reloading the page
  - Fix: button is now type="button" (cannot cause accidental form submission); click
    handler calls form.requestSubmit() which fires the submit event as before
  - Added sendBtn.disabled guard in submit handler to prevent double-submission
  - Fixed em dash in catch block error message (memory rule: no em dashes)
- [x] pytest full suite: 114/114 passing (after button fix)
- [x] Fix IIFE SyntaxError root cause: Jinja2 autoescape was HTML-encoding quotes in tojson output
  - The `tojson` filter returned `Markup(json.dumps(...))` which should prevent escaping, but
    the full Jinja2 template rendering pipeline still produced `&#34;SY&#34;` (confirmed via fetch)
  - Root fix: change `var USER_INI = {{ ... |tojson }};` to `var USER_INI = "{{ ... }}";`
    (initials are 2 alpha chars, no HTML special chars, safe to embed directly)
  - This eliminates the SyntaxError that prevented ALL event listeners from registering
- [x] Build multi-turn conversation memory (last 3 Q&A pairs = 6 turns)
  - `ai_generator.py`: added optional `messages` param to `_call_ai` for full history
  - `ask_service.py`: added `conversation_history: list = None` param to `ask()`; prepends
    last 6 history turns before the new user message when calling `_call_ai`
  - `routes.py`: added `history: str = Form("")` to `api_ask`; parses JSON list; caps at 6
  - `ask.html`: added `conversationHistory = []` state; appends Q&A pair after each success;
    sends `history` JSON field with each request; clears on "New Chat"
- [x] Remove duplicate input listener (was at bottom of IIFE, already registered at top)
- [x] py_compile all touched files: OK
- [x] pytest full suite: 114/114 passing
- [x] Browser verified: send button, char counter, rebuild button all work; ARIA responds
