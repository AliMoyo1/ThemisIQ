---
name: thinking-trace
description: Add an expandable "agent thinking" trace (collapsed header that says "Thinking" while an AI call is in flight, settles to "Thought for Ns", stays expandable to show the steps that ran) to an AI-facing page. Use when the user asks to add a thinking indicator, agent trace, or step-by-step "thinking" UI near a chat, AI generation, or AI search feature — in this repo (ThemisIQ/oneforall) or when porting the same pattern into a different themed app.
---

# Thinking trace widget

A collapsible trace that sits above an AI response: shimmering "Thinking" while
a call is in flight, rows revealing one at a time (spinner → checkmark), then
settling into a quiet "Thought for Ns" that stays expandable. Four content
variants: **steps** (checklist), **reasoning** (prose), **search** (query +
source links), **coding** (tool trace with file/diff stats).

The original source for this pattern is a React/Tailwind mockup driven by a
canned demo timer (`reference/ThinkingState.reference.tsx` in this skill
directory). It is **not** meant to be dropped in as-is — two things always
need adapting:

1. **Theming.** The mockup hardcodes its own token names (`--ink`, `--ink-2`,
   `--ink-3`, `--line`, `--hover`, `--accent`, `--orange`, `--green`, Tailwind
   utility classes). A real app has its own design tokens. Map, don't copy.
2. **The driver.** The mockup's `STAGES = [800, 600, 1800, 2600, 1600]` timer
   fakes progress regardless of what's actually happening. A real integration
   must be driven by the real async call: never claim "done" before the real
   response lands, and never sit frozen mid-sequence after it already has.

## In this repo (ThemisIQ / oneforall)

The adapted, production version already exists — reuse it, don't recreate it:

- **Component**: [`oneforall/static/js/thinking-trace.js`](../../../oneforall/static/js/thinking-trace.js)
  — vanilla JS IIFE exposing `window.ThinkingTrace.open(container, opts)`,
  matching the codebase's existing convention for this kind of widget (see
  the sibling `static/js/ai-guidance-dialog.js`: no framework, no build step,
  inline-styled with `var(--token)` + literal fallbacks, injected on demand).
- **Wired into**:
  - `modules/aria/templates/ask.html` — chat "thinking…" → `addThinking()` /
    `doAsk()`, variant `steps`, settled trace stays visible in chat history
    above the answer.
  - `modules/aria/templates/ai_generator.html` — `setPolicyLoading()` /
    `setGapLoading()`, variant `steps`, trace is destroyed rather than
    settled since the whole loading panel disappears on completion.
  - `modules/sentinel/templates/index.html` — four surfaces: `snSendChat()`
    (Sentinel's own separate AI chat, same settle-and-persist pattern as
    ARIA's, but built with `insertAdjacentHTML` — see gotcha below),
    `snAiSuggestRisks()`, `snSubmitGenerateNotice()`, `snSubmitDraftPolicy()`
    (all three: destroy-before-replace into an existing status/panel div).
  - `modules/erm/templates/index.html` — two surfaces: `extRunScan()` (the
    emerging-risk web-search scanner) and `ermBoardReport()` (board
    narrative generator), both destroy-before-hide into a newly-added mount
    div (neither surface had a dedicated loading area before this).
- **Include it** via `<script src="/static/js/thinking-trace.js"></script>`.
  Added to `modules/aria/templates/base.html`'s `extra_scripts` block (both
  ARIA pages above extend it), and directly to `modules/sentinel/templates/index.html`
  and `modules/erm/templates/index.html`'s own `extra_scripts` blocks (these
  two are monolithic SPA templates with no shared base to hook into).
  **Check this on every page you wire, every time** — ERM's script tag was
  planned but not actually added in one pass of this work; nothing failed
  loudly, `window.ThinkingTrace` was just silently `undefined` and every
  call would have thrown the moment a real (non-erroring) AI response came
  back. Live-verifying caught it immediately (`typeof window.ThinkingTrace`
  in the console); reading the diff back would not have, since the missing
  line is an *absence*, not a visible mistake.

### Theme token mapping used

| Mockup token | ThemisIQ token | Notes |
|---|---|---|
| `--ink` / `--ink-2` / `--ink-3` | `--text` / `--text-mid` / `--muted` | primary/secondary/tertiary text |
| `--line` | `--border2` | `--border` alone is too faint (0.06 alpha) to read as a rail |
| `--hover` / `--hover-2` | `--surface2` | row hover background |
| `--inset` | `--surface3` | selected/pressed row (coding variant) |
| `--accent` (search dot) | `--accent` | this app's per-module accent (ARIA = gold) |
| `--orange` | `--warn` | |
| `--green` / `--red` (diff) | `--good` / `--bad` | |
| `font-mono` (Tailwind) | `var(--mono)` | JetBrains Mono, already defined at `:root` |
| Tailwind `rounded-[6px]` etc. | literal `6px`/`8px` | this app has no Tailwind; hand-written CSS |

All tokens are defined in `templates/base_shell.html`'s `:root` /
`[data-theme="dark"]` blocks. Re-read that file before touching this widget
again — it's the single source of truth for the palette, and it changes
independently of this skill.

### The real-async driver (`ThinkingTrace.open` / `.settle` / `.destroy`)

```js
var trace = window.ThinkingTrace.open(mountEl, {
  variant: 'steps',                 // steps | reasoning | search | coding
  activeLabel: 'Thinking',
  rows: [
    { primary: 'Searching the knowledge base' },
    { primary: 'Reading the most relevant sources' },
    { primary: 'Writing the answer' }
  ]
});

// ... await the real fetch/call here ...

trace.settle({
  doneLabel: 'Thought for 6 seconds',   // omit to auto-compute from elapsed time
  appendRows: [{ primary: 'Found 3 sources' }]   // optional, e.g. data only known post-response
});
// or, if the surface just hides/discards the whole loading area on completion
// (nothing to settle visually — see ai_generator.html): trace.destroy();
```

Behaviour contract, load-bearing — don't regress these when touching the file:

- Rows reveal one at a time on a timer (`stepDelay`, default 900ms) but
  **hold on the second-to-last row** until `settle()` is called. It never
  auto-advances to "done" on its own.
- `settle()` immediately reveals whatever hasn't shown yet — if the real call
  finished fast, the user never sees a fake "still working" state.
- Auto-expanded while working; auto-collapses ~900ms after `settle()` *unless*
  the user has manually toggled it (`manualExpanded` overrides forever after).
- Always stays in the DOM and clickable after settling — chat surfaces should
  leave it in history (don't call `.destroy()` after `.settle()`; that
  defeats the point of an inspectable trace).
- `prefers-reduced-motion: reduce` disables the shimmer/spin animation.

### The `insertAdjacentHTML` gotcha (chat-style, growing-container surfaces)

Any surface that keeps *appending* messages to a growing container (a chat
log) and mounts the trace as one of those messages must never touch that
container with `container.innerHTML += '<div>...</div>'` again after the
trace is mounted. `innerHTML +=` reserializes the *entire* subtree to a
string and reparses it — every existing child, including the trace's live
DOM (its header button's click listener, its pending collapse `setTimeout`)
gets silently replaced by an inert, listener-less copy. Nothing throws;
the trace just freezes expanded forever and stops responding to clicks.

Use `container.insertAdjacentHTML('beforeend', '...')` instead for every
append that happens *after* `ThinkingTrace.open()` — it only adds new
nodes and never touches siblings that already exist. `snSendChat()` in
`modules/sentinel/templates/index.html` is the reference example (it used
to build every message via `innerHTML +=`; converting the ones after the
trace mount to `insertAdjacentHTML` was a required part of adding the
trace there, not a style preference). If a surface you're wiring builds
messages this way, check for this before assuming a straight port of the
`open()`/`settle()` calls is enough.

### The "search" variant needs real per-source data, not just "web search happened"

Don't reach for the `search` variant just because the backend call is
web-search-backed. It needs an actual `row.href`/`row.secondary` per
source to render as a clickable link — if the route only returns a count
and a boolean (`{"created": N, "grounded": bool}`, as ERM's
`/erm/api/emerging/scan` does), there is nothing honest to put in those
rows. Check the actual route handler's response shape
(`modules/<module>/routes.py`) before picking a variant, not just the
docstring or the endpoint name. ERM's scanner looked like the obvious
`search`-variant candidate going in; it shipped as `steps` once the
response shape turned out not to carry per-source data to the frontend.

### Applying it to a new surface in this repo

1. Find the real async call the surface makes (`fetch(...)`, `await ...json()`).
2. Add `<script src="/static/js/thinking-trace.js"></script>` if that page's
   base template doesn't already load it — **then verify it actually
   loaded** (`typeof window.ThinkingTrace === 'object'` in the browser
   console) before trusting the rest of the wiring. Don't assume the tag
   landed just because you intended to add it earlier in the same session.
3. Check whether the surface appends to a growing container (chat-style) —
   if so, read the insertAdjacentHTML gotcha above before touching it.
4. Pick 2-4 short, present-tense row labels that describe what the backend
   route *actually does* for that call — don't reuse generic ice-cream-demo
   copy. Check the route handler in `modules/<module>/routes.py` if unsure
   what the call does step-by-step, and see the search-variant note above
   before picking anything other than `steps`.
5. `open()` right before the fetch; `settle()` (chat/persistent surfaces) or
   `destroy()` (surfaces where the loading area itself disappears on
   completion) in both the success and error/catch paths. If there's no
   existing dedicated loading area to mount into (many small AI-triggering
   buttons only swap their own `textContent` to a spinner glyph with no
   surrounding panel), don't force one in — a multi-row trace crammed into
   a small icon-button context reads as broken, not polished. Either add a
   small mount div near the trigger (as done for ERM's two surfaces, which
   had none) if the operation is substantial enough to warrant it, or leave
   the existing minimal treatment alone.
6. Live-verify in the browser per this project's standing rule — start the
   dev server, trigger the real call, confirm timing/expand-collapse/dark
   mode, check the console for errors, and check `read_network_requests`
   for the actual response code (a fast failure and a fast success can look
   identical from a screenshot taken a moment too late — check the network
   log, not just the absence of a visible error, before concluding a path
   was actually exercised). A slow local HTTP handler or an artificial
   `await new Promise(r => setTimeout(r, 3000))` swap-in is the fastest way
   to see the mid-flight optimistic reveal if the real backend call is
   normally too fast to observe.

## Applying this pattern to a different app

If asked to add this same widget somewhere that isn't ThemisIQ (a different
themed app, React or otherwise):

1. **Find the app's real design tokens first** — don't guess or invent ones.
   Look for a `:root` CSS custom-property block, a Tailwind theme config, or
   a design-tokens file. Confirm dark-mode strategy (media query vs.
   `data-theme` attribute) before writing any color.
2. **Match the app's existing component convention**, not the mockup's. If
   the app is React, a component is fine — but still replace the `STAGES`
   timer with a real async driver (open/settle/destroy, as above), not a
   fixed-duration `useEffect` chain. If the app has no framework, port to
   vanilla JS/CSS following whatever pattern its own codebase already uses
   for similar small interactive widgets (check for a sibling utility file
   before inventing a new pattern).
3. **Only wire in variants that have a real counterpart.** Don't force a
   `search` variant with source cards onto a surface that has no list of
   sources to show, and don't ship a `coding` tool-trace variant into an app
   with no file-editing AI feature. Build the underlying component with all
   variants (cheap, keeps it reusable) but only *integrate* the ones that fit
   real surfaces — this was the deciding factor for ThemisIQ (`coding` exists
   in the component but is not wired into any page, since ThemisIQ is a
   compliance platform, not a code-editing tool).
4. Verify live in a browser before calling it done, same as any other UI
   change — this class of bug (theming edge cases, dark mode, a slow-endpoint
   timing bug) is essentially invisible from reading the code alone.
