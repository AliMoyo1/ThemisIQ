# Manual keyboard test script (PLAN-36 T07)

This is a human-run script for the things the automated axe-core and
Playwright suites cannot fully prove: whether a focus indicator is
genuinely *perceptible* to a real person (not just present in the
computed style), whether the reading/tab order feels logical end to end,
whether a screen reader actually announces what the markup claims it
announces, and whether a full multi-step task is completable without
ever touching a mouse or trackpad. Automated coverage for the mechanical
parts of these same flows (an element exists, a class toggles, an ARIA
attribute is set) already lives in `oneforall/tests/ui/`; this script is
for the parts that require human judgment.

Run this after any change that touches navigation, modals/drawers,
forms, or focus/keyboard handling — not on every commit.

## Setup

- A desktop browser (Chromium, Firefox, or the deployed target browsers).
  Physically unplug or disable the mouse/trackpad if you can; if not,
  simply don't touch it for the duration of the script.
- Keys used throughout: **Tab** / **Shift+Tab** (move focus forward/
  back), **Enter** / **Space** (activate), **Escape** (close/cancel),
  **Arrow keys** (where a widget documents them, e.g. a select).
- Log in as `super_admin` against a disposable/synthetic tenant, never
  production.

## Part 1 — Global shell (every route)

1. Load `/`. Press Tab once. The skip link ("Skip to main content" or
   similar) must become visible and clearly show a focus indicator.
   Press Enter. Focus must land inside the main content area, not just
   scroll the page.
2. Continue tabbing through the icon sidebar, then the module's own left
   sidebar (if present), then the topbar (notification bell, search if
   present), then into the page content. At every stop, confirm:
   - You can tell *where* focus is without looking away from the
     keyboard — the indicator should be a clearly visible outline or
     ring, not a subtle color shift you'd miss at a glance.
   - The order roughly matches the visual layout (left-to-right,
     top-to-bottom) — nothing jumps to a surprising place.
3. Tab to the notification bell. Press Enter/Space. The notification
   panel should open, and — this is the part automation can't fully
   prove — a screen reader (turn one on: Narrator on Windows, VoiceOver
   on Mac) should announce that a panel opened, not silently change the
   page with no spoken feedback.
4. Trigger a toast (e.g. save something). With a screen reader running,
   confirm the toast's text is actually spoken without you having to
   manually navigate to it — this is what `aria-live="polite"` on
   `#toastContainer` is for; automated tests can only confirm the
   attribute exists, not that a real screen reader honors it correctly
   in your target browser/AT pairing.

## Part 2 — Modals (ModalManager-based)

Pick 3–4 at random from: New Task, Create Report, Register New Risk,
Upload Evidence, Create Webhook, Generate API Key.

1. Trigger the modal by keyboard (Tab to the button, Enter).
2. Confirm focus lands inside the modal immediately — you should not
   need to Tab from the page body to reach it.
3. Tab all the way through every field/button in the modal, then once
   more. Focus must cycle back to the first field, never escaping to
   the page behind it (that page's controls should be completely
   unreachable by Tab while the modal is open).
4. Shift+Tab from the first field. Focus must wrap to the *last* item,
   not stop or jump somewhere unexpected.
5. Press Escape. The modal must close, and focus must return to the
   button that opened it (try to Tab/Shift+Tab immediately after
   closing — you should be exactly where you were before opening it).
6. Repeat once with a field left dirty (typed into) where the modal
   represents a form, to confirm Escape doesn't silently discard data
   in a way the user wasn't warned about (some modals intentionally
   have no such guard — check `progress.md`'s own notes on
   `registerCloseGuard` for which ones currently do).

## Part 3 — Custom drawers/panels (PLAN-36 T07 session continuation)

These predate ModalManager and use a separate `DialogFocus` utility
(`static/js/dialog_focus.js`) for the same properties. Test at least:

- **ERM**: open a risk from the register (click a row — or, for a purer
  keyboard test, Tab to a row's own action control if one exists, note
  in your findings if the only way to open it is a mouse click on the
  row itself, since that would itself be worth flagging). Confirm Tab
  stays inside the drawer, Escape closes it and returns focus to the
  register.
- **People Directory**: open a person's profile drawer, confirm the
  same Tab-trap/Escape/focus-restore behavior.
- **Vendor Directory**: same, for a vendor profile.
- **Sentinel**: open a RoPA (or DPIA/AIIA) record, switch between its
  internal tabs (Data/Systems/Risk) via Tab and Enter — confirm the tab
  buttons themselves are reachable and activatable, and that switching
  tabs doesn't strand focus somewhere invisible.
- **ARIA**: open the "Ask ARIA" floating widget via its button. Confirm
  the same Tab-trap/Escape/restore-to-launcher-button behavior, and that
  the initial focus lands in the question input specifically (not just
  the first element in the panel).
- **Evidence**: open an evidence item's detail panel. Confirm Escape
  closes it. (This one does not yet have a full Tab-trap — see
  `progress.md`'s own note on this being a smaller, Escape-only fix; if
  you find Tab escaping the panel into the page behind it, that is
  known, not a new regression.)

## Part 4 — Filter chips and other converted controls

Pick 2–3 of the filter-chip groups converted from `<span>`/`<div>` to
real `<button>` this session (Task Board priority chips, Timeline period
chips, ERM register status chips, Sentinel's DSR/ROPA/DPIA status
filters, Command Centre's overdue-module filters). For each:

1. Tab to the chip group. Confirm each chip is individually reachable
   via Tab (not skipped).
2. Press Enter or Space on a non-active chip. Confirm it visually
   becomes the active filter and the underlying list/view actually
   filters — not just a class change with no real effect.

## Part 5 — Drag-and-drop alternative (Task Board)

Task Board's kanban columns use native HTML5 drag-and-drop
(`draggable="true"`) to move a card between statuses, which has no
keyboard equivalent by design (WCAG 2.5.7 requires a non-dragging
alternative to exist somewhere, not that the drag gesture itself become
keyboard-operable).

1. Open a task's detail drawer (click a card, or Tab to it and press
   Enter if the card itself is focusable).
2. Confirm the drawer's own Status `<select>` (`#ddStatus`) lets you
   change the task's column/status entirely via keyboard, and that
   saving moves the card exactly as dragging it would have.
3. Note in your findings if this select is hard to find or mislabeled —
   it is the entire accessibility justification for the drag-only board
   view, so it needs to be genuinely discoverable, not just technically
   present.

## Part 6 — A full task, start to finish, no mouse

Pick one and complete it entirely by keyboard:

- Create a new risk in ERM's register, fill every required field, save,
  then reopen it and edit one field.
- Upload a file in Evidence, resolve a duplicate-file prompt if one
  appears, confirm the item now appears in the list.
- Create a webhook, run its Test button, observe the Sending → Delivered/
  Failed states, then delete it.

If you get stuck at any point — a control you can't reach, an action
you can't tell succeeded or failed without looking very closely, a
focus loss you can't recover from without clicking — that is a finding.
Record: the exact route, the exact control, what you expected, what
happened instead.

## Recording findings

Add anything found to `plans/PLAN-36-themisiq-stabilization-and-product-improvements/progress.md`
under the relevant T07 (or later) session, with enough detail (route,
selector if known, exact repro steps) that it can be turned into an
automated regression test once fixed — the same evidentiary standard
every other finding in that file is held to.
