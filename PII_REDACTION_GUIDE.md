# Local PII Redaction for Outbound AI Calls: Build and Implementation Guide

Status: design and build guide, ready to implement. Nothing here is wired in yet.
Audience: an engineer or an AI coding assistant. Every step is explicit and testable.

## 0. What this feature does, in plain language

The app sends text to an external AI provider (Anthropic, OpenAI, Gemini, DeepSeek).
Before that text leaves the machine, we find personal data in it (emails, phone
numbers, ID numbers, card numbers, and so on), swap each piece for a harmless
placeholder token, send the tokenized text to the AI, and then put the real values
back into the AI's reply.

Before:

```
Contact John at john.smith@acme.com about the breach on 555-123-4567.
```

Sent to the AI:

```
Contact John at [[EMAIL_1]] about the breach on [[PHONE_1]].
```

The AI answers using the tokens. We restore the real values in its answer before the
user sees it. The AI never receives the real personal data.

Two rules make this safe and simple:

1. It is OFF by default. It only turns on with an environment variable. When off, the
   code path is skipped entirely and behaviour is identical to today.
2. It only runs for external providers. Local Ollama is skipped, because with Ollama
   the data never leaves the machine, so redaction there would only remove useful
   context for no privacy gain.

## 1. The design in one picture

There are three small pieces:

- Detector: finds personal data and returns a list of spans, where a span is
  `(start, end, label)`. Two interchangeable implementations:
  - `regex` (built in, no dependencies, works on Python 3.14 today).
  - `presidio` (optional, a Docker sidecar, adds names and organisations and places).
- Redactor: replaces each span with a reversible token and remembers the mapping of
  token to original value. This is the same code no matter which detector is used.
- Restorer: puts the original values back into the AI reply using the mapping.

The whole thing plugs into ONE function in the codebase: `_dispatch()` in
`oneforall/core/ai_client.py`. Every AI call in the app already flows through that
one function, so this is a single insertion point, not ten.

## 2. What you need before you start (resources)

Tier 1 (regex, recommended first build):

- Nothing new. Pure Python standard library. Runs on the existing Python 3.14 venv.
- `httpx` and `pytest` are already project dependencies (used only in later phases and
  in tests).

Tier 2 (Presidio sidecar, optional upgrade for names and organisations):

- Docker (Docker Desktop on the Windows dev machine, Docker Engine on the VPS).
- Two container images, pulled from GitHub Container Registry:
  - `ghcr.io/data-privacy-stack/presidio-analyzer`
  - `ghcr.io/data-privacy-stack/presidio-anonymizer` (optional, not required by this
    design because we do our own token mapping; listed for completeness).
- About 1 to 2 GB RAM for the analyzer with its default English model. A smaller model
  is available if memory is tight (see Phase 3 notes).

Do NOT try to `pip install presidio-analyzer` into the main Python 3.14 app venv. It
depends on spaCy, and spaCy has had trouble publishing Python 3.14 wheels. The sidecar
avoids that problem completely by running Presidio in its own container on a Python
version where the wheels are solid.

Reference documentation:

- Presidio install and Docker: https://presidio.dataprivacystack.org/installation/
- Presidio getting started (text): https://presidio.dataprivacystack.org/getting_started/getting_started_text/
- Presidio repository: https://github.com/data-privacy-stack/presidio

## 3. Phase 1: Build the in-process redactor (no dependencies)

### Step 1.1: Create the redactor module

Create a new file at `oneforall/core/pii_redactor.py` with exactly this content:

```python
"""
Local PII redaction for outbound AI calls.

Detects high-liability personal data, replaces it with reversible placeholder
tokens before text leaves the machine, and restores the real values in the AI
reply. The regex detector needs no network and no ML model, so it runs on any
Python 3.10 or newer. An optional Presidio detector can be selected with an
environment variable without changing any of the redact or restore logic.
"""
import os
import re

import httpx

# Order matters: more specific patterns come first so that, for example, a card
# number is not swallowed by the generic phone pattern. Each entry is
# (LABEL, compiled_regex).
_PATTERNS = [
    ("EMAIL", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("IBAN",  re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    ("CARD",  re.compile(r"\b\d{4}[ -]?\d{4}[ -]?\d{4}[ -]?\d{1,4}\b")),
    ("SSN",   re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("IP",    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("PHONE", re.compile(r"\+?\d[\d\s().\-]{7,}\d")),
]


def _dedupe_spans(spans):
    """Sort spans left to right and drop any that overlap one already kept."""
    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept = []
    last_end = -1
    for start, end, label in spans:
        if start >= last_end:
            kept.append((start, end, label))
            last_end = end
    return kept


def _detect(text):
    """Regex detector. Returns a list of (start, end, label) spans."""
    found = []
    for label, rx in _PATTERNS:
        for m in rx.finditer(text):
            found.append((m.start(), m.end(), label))
    return _dedupe_spans(found)


def _detect_presidio(text):
    """
    Presidio sidecar detector. Calls the analyzer service over HTTP and returns
    the same (start, end, label) span shape. If the sidecar is unreachable or
    slow, it falls back to the regex detector so an AI call is never blocked by
    redaction being unavailable.
    """
    url = os.getenv("PRESIDIO_ANALYZER_URL", "http://localhost:5002").rstrip("/")
    try:
        with httpx.Client(timeout=5) as client:
            r = client.post(url + "/analyze", json={"text": text, "language": "en"})
            r.raise_for_status()
            results = r.json()
    except Exception:
        return _detect(text)
    spans = [(item["start"], item["end"], item["entity_type"]) for item in results]
    return _dedupe_spans(spans)


def detect(text):
    """Pick the detector from the environment. Default is the regex detector."""
    if os.getenv("AI_PII_DETECTOR", "regex").lower() == "presidio":
        return _detect_presidio(text)
    return _detect(text)


def redact_many(texts):
    """
    Redact a list of strings using one shared, consistent token space. The same
    original value always maps to the same token, even across different strings,
    so the AI can still reason about repeated entities.

    Returns (list_of_redacted_strings, mapping) where mapping is {token: original}.
    """
    mapping = {}
    seen = {}       # original value -> token, so repeats reuse one token
    counters = {}   # label -> running number
    out_texts = []
    for text in texts:
        if not text:
            out_texts.append(text)
            continue
        parts = []
        cursor = 0
        for start, end, label in detect(text):
            original = text[start:end]
            token = seen.get(original)
            if token is None:
                counters[label] = counters.get(label, 0) + 1
                token = "[[" + label + "_" + str(counters[label]) + "]]"
                seen[original] = token
                mapping[token] = original
            parts.append(text[cursor:start])
            parts.append(token)
            cursor = end
        parts.append(text[cursor:])
        out_texts.append("".join(parts))
    return out_texts, mapping


def redact(text):
    """Single-string convenience wrapper. Returns (redacted_text, mapping)."""
    if not text:
        return text, {}
    reds, mapping = redact_many([text])
    return reds[0], mapping


def restore(text, mapping):
    """Put the real values back into an AI reply."""
    if not text or not mapping:
        return text
    for token, original in mapping.items():
        text = text.replace(token, original)
    return text


def enabled_for(provider):
    """
    True only when the flag is on AND the provider is external. Local Ollama is
    always skipped because its data never leaves the machine.
    """
    on = os.getenv("AI_PII_REDACTION", "off").lower() in ("1", "true", "on", "yes")
    return on and provider != "ollama"


def process_outbound(system, messages):
    """
    Redact the system prompt and every message content with one shared token
    space. Returns (new_system, new_messages, mapping).
    """
    contents = [system] + [m.get("content", "") for m in messages]
    red, mapping = redact_many(contents)
    new_system = red[0]
    new_messages = [{**m, "content": c} for m, c in zip(messages, red[1:])]
    return new_system, new_messages, mapping
```

### Step 1.2: Unit test the redactor

Create `oneforall/tests/test_pii_redactor.py`:

```python
from core.pii_redactor import redact, redact_many, restore


def test_email_round_trip():
    text = "Contact John at john.smith@acme.com about the breach."
    red, mapping = redact(text)
    assert "john.smith@acme.com" not in red
    assert "[[EMAIL_1]]" in red
    assert restore(red, mapping) == text


def test_repeat_value_reuses_one_token():
    text = "a@x.com wrote to a@x.com"
    red, mapping = redact(text)
    assert red.count("[[EMAIL_1]]") == 2
    assert len(mapping) == 1


def test_text_with_no_pii_is_unchanged():
    text = "The control was operating effectively."
    red, mapping = redact(text)
    assert red == text
    assert mapping == {}


def test_shared_token_space_across_messages():
    reds, mapping = redact_many(["email a@x.com", "again a@x.com"])
    assert reds[0].endswith("[[EMAIL_1]]")
    assert reds[1].endswith("[[EMAIL_1]]")
    assert len(mapping) == 1


def test_restore_ignores_plain_text():
    assert restore("nothing to change", {"[[EMAIL_1]]": "a@x.com"}) == "nothing to change"
```

Run it. On the Windows dev machine, from the `oneforall` directory:

```powershell
python -m pytest tests/test_pii_redactor.py -q
```

Expected output ends with:

```
5 passed
```

### Done when (Phase 1 gate)

- The file `oneforall/core/pii_redactor.py` exists and imports without error.
- `python -m pytest tests/test_pii_redactor.py -q` reports `5 passed`.
- No other file has been changed yet. The app behaves exactly as before.

## 4. Phase 2: Wire it into the single AI chokepoint

### Step 2.1: Read the current function

Open `oneforall/core/ai_client.py` and find `_dispatch()`. It currently looks like this:

```python
def _dispatch(messages, system, max_tokens, model) -> dict:
    p = _provider()
    model = model or _model_for_provider(p)

    # Prepend GRC domain guardrail to every system prompt
    system = _GRC_GUARDRAIL + "\n\n" + (system or "") if system else _GRC_GUARDRAIL

    if p == "anthropic":
        text, meta = _anthropic(messages, system, max_tokens, model)
    elif p == "deepseek":
        text, meta = _openai_compat(...)
    elif p == "gemini":
        text, meta = _gemini(messages, system, max_tokens, model)
    elif p == "openai":
        text, meta = _openai_compat(...)
    elif p == "ollama":
        text, meta = _openai_compat(...)
    else:
        raise RuntimeError(f"Unknown AI_PROVIDER: {p}")
    return {"text": text, **meta}
```

### Step 2.2: Add three small blocks

Change it to this. The provider branch in the middle is unchanged. Only the marked
blocks are new. Do not remove any existing `elif` branch.

```python
def _dispatch(messages, system, max_tokens, model) -> dict:
    p = _provider()
    model = model or _model_for_provider(p)

    # Prepend GRC domain guardrail to every system prompt
    system = _GRC_GUARDRAIL + "\n\n" + (system or "") if system else _GRC_GUARDRAIL

    # --- PII redaction, outbound (new) ----------------------------------
    from core.pii_redactor import enabled_for, process_outbound, restore
    pii_map = {}
    if enabled_for(p):
        system, messages, pii_map = process_outbound(system, messages)
    # --------------------------------------------------------------------

    if p == "anthropic":
        text, meta = _anthropic(messages, system, max_tokens, model)
    elif p == "deepseek":
        text, meta = _openai_compat(
            messages, system, max_tokens, model,
            _key("DEEPSEEK_API_KEY"),
            "https://api.deepseek.com/v1/chat/completions",
            "DEEPSEEK_API_KEY",
        )
    elif p == "gemini":
        text, meta = _gemini(messages, system, max_tokens, model)
    elif p == "openai":
        text, meta = _openai_compat(
            messages, system, max_tokens, model,
            _key("OPENAI_API_KEY"),
            "https://api.openai.com/v1/chat/completions",
            "OPENAI_API_KEY",
        )
    elif p == "ollama":
        host = getattr(settings, "OLLAMA_HOST", "http://localhost:11434").rstrip("/")
        text, meta = _openai_compat(
            messages, system, max_tokens, model,
            "",
            f"{host}/v1/chat/completions",
            "",
        )
    else:
        raise RuntimeError(f"Unknown AI_PROVIDER: {p}")

    # --- PII restore, inbound (new) -------------------------------------
    if pii_map:
        text = restore(text, pii_map)
    # --------------------------------------------------------------------

    return {"text": text, **meta}
```

Notes for the implementer:

- The `import` is inside the function on purpose. It keeps module load unchanged and
  costs nothing when the feature is off.
- `enabled_for(p)` already handles both the on/off flag and the "skip Ollama" rule, so
  `_dispatch` stays clean.
- `create_message_web_search` in the same file is a separate function. Leave it for
  now. It is Anthropic-only and used by one feature. Redacting it is a later, optional
  extension (see Section 8). It does not affect the main path.

### Step 2.3: Test the wiring with no network

Create `oneforall/tests/test_pii_dispatch.py`:

```python
import core.ai_client as ai


def test_dispatch_redacts_outbound_and_restores_inbound(monkeypatch):
    monkeypatch.setenv("AI_PII_REDACTION", "on")
    monkeypatch.setattr(ai, "_provider", lambda: "anthropic")

    captured = {}

    def fake_anthropic(messages, system, max_tokens, model):
        captured["messages"] = messages
        # The model echoes the last token back to us.
        token = messages[0]["content"].split()[-1]
        return "Acknowledged " + token, {"model": model, "input_tokens": 0, "output_tokens": 0}

    monkeypatch.setattr(ai, "_anthropic", fake_anthropic)

    out = ai.create_message([{"role": "user", "content": "email a@x.com"}])

    # 1) No raw personal data was sent to the provider.
    assert "a@x.com" not in captured["messages"][0]["content"]
    assert "[[EMAIL_1]]" in captured["messages"][0]["content"]
    # 2) The real value was restored in the reply shown to the caller.
    assert "a@x.com" in out


def test_off_by_default_sends_raw(monkeypatch):
    monkeypatch.delenv("AI_PII_REDACTION", raising=False)
    monkeypatch.setattr(ai, "_provider", lambda: "anthropic")

    captured = {}

    def fake_anthropic(messages, system, max_tokens, model):
        captured["messages"] = messages
        return "ok", {"model": model, "input_tokens": 0, "output_tokens": 0}

    monkeypatch.setattr(ai, "_anthropic", fake_anthropic)
    ai.create_message([{"role": "user", "content": "email a@x.com"}])

    # With the flag unset, behaviour is unchanged: raw text goes through.
    assert "a@x.com" in captured["messages"][0]["content"]
```

Run it:

```powershell
python -m pytest tests/test_pii_dispatch.py -q
```

Expected output ends with:

```
2 passed
```

### Step 2.4: Turn it on and confirm the whole suite is still green

Run the full test suite to prove nothing else broke:

```powershell
python -m pytest tests -q
```

Expected: the previous passing count plus the new tests, zero failures.

### Done when (Phase 2 gate)

- Both new dispatch tests pass.
- The full `python -m pytest tests -q` run has zero failures.
- With `AI_PII_REDACTION` unset, a real AI feature behaves exactly as before.
- With `AI_PII_REDACTION=on`, a real AI feature still works and personal data does not
  appear in the outbound request. You can confirm the outbound content in the test
  above, which captures exactly what the provider function received.

## 5. Phase 3 (optional): Add the Presidio sidecar for names and organisations

The regex detector catches structured data (emails, phones, IDs, cards, IBANs, IPs).
It does not catch free-text names, organisations, or places. Presidio adds those with a
language model. This phase is optional and additive. If you skip it, everything from
Phases 1 and 2 keeps working.

### Step 3.1: Start the analyzer container (VPS, bash)

Pull the image:

```bash
docker pull ghcr.io/data-privacy-stack/presidio-analyzer
```

Run it, mapping host port 5002 to the container port 3000:

```bash
docker run -d --name presidio-analyzer -p 5002:3000 ghcr.io/data-privacy-stack/presidio-analyzer:latest
```

Confirm it is running:

```bash
docker ps
```

You should see `presidio-analyzer` in the list with status `Up`.

### Step 3.2: Confirm detection works

Send one test request. This is a single line, safe to paste:

```bash
curl -X POST http://localhost:5002/analyze -H "Content-Type: application/json" -d "{\"text\": \"My name is John Smith\", \"language\": \"en\"}"
```

Expected: a JSON array containing an object with `"entity_type": "PERSON"` and numeric
`start`, `end`, and `score` fields. If you see that, detection works.

### Step 3.3: Point the app at the sidecar

Add two environment variables so the app uses the Presidio detector instead of regex.
On the VPS, add these two lines to the app environment file (the `.env` the service
already loads), each on its own line:

```
AI_PII_DETECTOR=presidio
PRESIDIO_ANALYZER_URL=http://localhost:5002
```

Keep `AI_PII_REDACTION=on` as well. No code change is needed. The `detect()` router in
the redactor reads `AI_PII_DETECTOR` and switches automatically.

### Step 3.4: Restart the app service

Reload the service definition:

```bash
systemctl daemon-reload
```

Restart the app:

```bash
systemctl restart themisiq-app.service
```

### Done when (Phase 3 gate)

- `docker ps` shows `presidio-analyzer` up.
- The curl test returns a `PERSON` entity.
- With `AI_PII_DETECTOR=presidio`, a request whose text contains a person name shows a
  `[[PERSON_1]]` token in the outbound payload (verify with a capture test like the one
  in Step 2.3, but using a name instead of an email, and with the sidecar running).
- If you stop the container, AI calls still succeed, because `_detect_presidio` falls
  back to regex on any error. Verify by stopping the container and confirming AI
  features still respond.

## 6. Points of failure and their solutions

| # | Failure | Why it happens | Solution (already handled or the fix to apply) |
|---|---------|----------------|-----------------------------------------------|
| 1 | `pip install presidio-analyzer` fails on Python 3.14 | spaCy Python 3.14 wheels have been unreliable | Do not install Presidio into the app venv. Use the Docker sidecar (Phase 3). Tier 1 needs no install at all. |
| 2 | Presidio sidecar is down or slow | Container stopped, restarting, or overloaded | Already handled: `_detect_presidio` catches any error and falls back to regex, so AI calls never fail. Add a health check that pings `/analyze` on a schedule if you want alerts. |
| 3 | The AI changes a token in its reply (case or spacing) so restore misses it | Language models sometimes rewrite text | The user then sees a token instead of a real value. This is safe (no data leaked), only cosmetic. To reduce it: add a system-prompt line telling the model to keep `[[...]]` tokens verbatim (Section 8), and use the tolerant restore in Section 8. |
| 4 | Over-redaction removes context the AI needs, lowering answer quality | A conservative name or org detector is still imperfect | Keep the detector conservative. Because tokens are consistent per value, the model can still reason about the same entity. Add a per-call opt-out for low-risk internal calls (Section 8). Spot-check output quality (Section 7). |
| 5 | Under-redaction leaks a personal detail | Regex alone misses names; any detector misses novel formats | Layer detectors: regex plus Presidio NER. Add custom regex for local formats (national ID, mobile ranges) as extra `_PATTERNS` entries (Section 8). Test against a sample set (Section 7). |
| 6 | A user literally types a string that looks like a token, for example `[[EMAIL_1]]` | Extremely rare user input | The delimiter `[[LABEL_N]]` is uncommon. If you want certainty, escape any pre-existing `[[` in input before redacting. Not worth doing unless a real case appears. |
| 7 | Added latency on each AI call | NER inference and, for the sidecar, one HTTP round trip | Redaction runs only for external providers and only when on. Regex is a few milliseconds. The sidecar call has a 5 second timeout and falls back to regex. Reuse of the model is handled by the container, which loads it once. |
| 8 | Redaction corrupts a JSON prompt a caller built | Tokens inserted into structured text | Tokens contain only letters, digits, underscores, and square brackets. They contain no quotes or braces, so JSON stays valid. Safe by construction. |
| 9 | Streaming responses are not restored | Restore needs the full reply text | The current calls are non-streaming and return full text, so this is fine today. If streaming is added later, restore after the full text is assembled. |
| 10 | Wrong language for the NER model | Presidio analyzer defaults to English | App content is English, so the default is correct. If other languages are added, load the matching model in the sidecar and pass the right `language` value. |

## 7. Success criteria and how to test each one

Successful implementation means all of the following are true and demonstrated.

| Criterion | How to test it | Pass condition |
|-----------|----------------|----------------|
| Redactor is correct and reversible | `python -m pytest tests/test_pii_redactor.py -q` | `5 passed` |
| No personal data leaves the machine when on | `test_dispatch_redacts_outbound_and_restores_inbound` in Step 2.3 | Passes: outbound content has the token, not the raw value |
| Real values are restored in the reply | Same test, second assertion | Passes: the reply contains the real value |
| Off by default, no behaviour change | `test_off_by_default_sends_raw` in Step 2.3 | Passes: raw value goes through when the flag is unset |
| Nothing else broke | `python -m pytest tests -q` | Zero failures, previous count plus new tests |
| Ollama path is untouched | Set provider to `ollama` in a capture test and confirm content is unchanged even with the flag on | Raw content passes through for Ollama |
| Sidecar detects names (if Phase 3 used) | The curl call in Step 3.2 | A `PERSON` entity is returned |
| Sidecar failure never blocks AI | Stop the container, then use an AI feature | AI feature still responds (regex fallback) |
| Answer quality is acceptable | Human spot check: run three or four real AI features (for example a risk summary and a legal-basis suggestion) with the flag on, read the outputs | Outputs are as useful as before, allowing for tokenised entities |

Optional red-team check for coverage: prepare a small text file with one example of each
category you care about (a name, an email, a phone, a national ID, a card number) and
run it through `redact` in a Python shell. Confirm each category is tokenised. This is
the fastest way to see a gap and decide whether to add a custom pattern.

## 8. Custom improvements that will not break anything

Each of these is additive. The base build keeps working if you skip them.

1. Tell the model to preserve tokens. In the caller or in the guardrail, add one line
   to the system prompt: "Keep any text of the form [[LABEL_NUMBER]] exactly as it is."
   This improves restore reliability. Purely additive.

2. Tolerant restore. Replace the body of `restore` with a version that also matches
   tokens the model spaced or recased. This is a superset of exact matching, so it can
   only restore more, never less:

   ```python
   import re as _re

   def restore(text, mapping):
       if not text or not mapping:
           return text
       for token, original in mapping.items():
           inner = token[2:-2]  # drop the [[ and ]]
           pattern = _re.compile(r"\[\[\s*" + _re.escape(inner) + r"\s*\]\]", _re.IGNORECASE)
           text = pattern.sub(lambda _m: original, text)
       return text
   ```

3. Custom recognisers for local formats. Add entries to `_PATTERNS` for the identifiers
   that matter in your region, for example a national ID or a mobile number range. Put
   more specific patterns before the generic `PHONE` pattern:

   ```python
   ("NATIONAL_ID", re.compile(r"\b\d{2}-\d{6,7}[A-Z]\d{2}\b")),
   ```

   Additive. Existing detection is unaffected.

4. Card number sanity check. Reduce false positives on `CARD` by keeping only matches
   that pass the Luhn checksum. A small helper function applied inside the detector.
   Additive filter, never removes a real card.

5. Per-call opt-out. For a specific low-risk internal AI call, let the caller pass a
   flag that skips redaction for that call only. Default stays on. Additive parameter.

6. Redaction counts in the audit log. After `process_outbound`, log only the counts per
   category (for example "redacted 2 EMAIL, 1 PHONE"), never the values. For a
   compliance product this is valuable evidence that the control is active. Additive,
   stores no personal data.

7. Extend to the web-search call. Apply the same `enabled_for` and `process_outbound`
   and `restore` around `create_message_web_search`. Additive, follows the same pattern.

8. Reuse one HTTP client for the sidecar. If sidecar traffic grows, hold a module-level
   `httpx.Client` instead of creating one per call. Performance only.

## 9. Kill switch and rollback

- Kill switch: set `AI_PII_REDACTION=off` or remove the variable, then restart the app.
  The redaction code path is skipped entirely and behaviour is identical to before the
  feature existed.
- Full rollback: remove the two new blocks from `_dispatch()` in
  `oneforall/core/ai_client.py`, then delete `oneforall/core/pii_redactor.py` and the
  two test files. Nothing else references them.

## 10. Recommended build order (summary)

1. Phase 1: build and unit test the regex redactor. No app change yet. Lowest risk.
2. Phase 2: wire it into `_dispatch()`, off by default, and test with no network.
3. Turn it on in development, run a few real AI features, confirm quality.
4. Ship with regex only. This alone covers the highest-liability structured data.
5. Phase 3 later, if names and organisations must also be covered: add the Presidio
   sidecar and flip one environment variable. No code change.
