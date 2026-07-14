# PLAN-17: First impressions — Command Centre greeting + login polish (existing aesthetic preserved)

## HARD CONSTRAINT

**Zero aesthetic changes.** No glass layer, no icon replacements, no new
colors, no card redesigns. The existing tiles, charts, badges, and icons
stay exactly as they are. This plan ADDS a small personalized greeting
block to the Command Centre and fixes functional polish gaps on the
login page — both using only classes and tokens that already exist in
base_shell.html.

## Goal

Two small, high-visibility touches:

1. **Command Centre greeting** — the first screen of every session
   currently opens cold. Add a greeting row above the stat tiles:
   time-of-day salutation with the user's first name, a one-line
   attention summary computed from data the page ALREADY fetches
   ("3 items need your attention: 2 critical risks, 1 overdue audit"),
   and the current date. Styled with the page's existing heading and
   muted-text styles only.
2. **Login polish** — functional fixes only: dark-mode bootstrap so
   dark-theme users do not get a white flash, autofocus on the username
   field, `autocomplete` attributes, and a "signing in…" disabled state
   on submit. The visual design stays untouched.

## Exact files to touch

1. `oneforall/templates/command_centre.html`
2. The login template — locate via
   `grep -rn "TemplateResponse" oneforall/modules/launcher/routes_auth.py`
   and open the referenced file

## Step-by-step order

### Step 1 — Command Centre greeting markup

READ the top of the content area in `command_centre.html` first (find
where the page heading / date range sits). Insert ABOVE the first stat
row:

```html
<div style="display:flex;align-items:flex-end;justify-content:space-between;gap:16px;margin-bottom:18px">
  <div>
    <div id="ccGreeting" style="font-size:20px;font-weight:700;color:var(--text)">
      Welcome back{% if user and (user.full_name or user.username) %}, {{ (user.full_name or user.username).split(' ')[0] }}{% endif %}
    </div>
    <div id="ccAttention" style="font-size:12.5px;color:var(--muted);margin-top:3px">Loading your day…</div>
  </div>
  <div id="ccToday" style="font-size:12px;color:var(--text-mid);font-family:var(--mono)"></div>
</div>
```

Inline styles reference ONLY existing tokens (`--text`, `--muted`,
`--text-mid`, `--mono`) — match the exact font sizes already used by
the page's other headings (READ them and copy; the sizes above are
placeholders to align with what exists).

### Step 2 — Greeting JS

In the page's existing script block (near `populateStats()`):

```js
(function(){
  var h = new Date().getHours();
  var word = h < 12 ? 'Good morning' : (h < 17 ? 'Good afternoon' : 'Good evening');
  var g = document.getElementById('ccGreeting');
  if(g) g.textContent = g.textContent.replace('Welcome back', word);
  var t = document.getElementById('ccToday');
  if(t) t.textContent = new Date().toLocaleDateString(undefined,
      {weekday:'short', day:'numeric', month:'short', year:'numeric'});
})();
```

Client-side on purpose: the server is UTC and would greet half the world
with the wrong daypart.

### Step 3 — Attention summary

READ `populateStats()` and identify the fields already present in the
stats payload for: critical/high risk count, open findings count,
overdue/upcoming reviews. At the END of `populateStats()` add:

```js
var bits = [];
if (typeof critHigh === 'number' && critHigh > 0) bits.push(critHigh + ' critical/high risk' + (critHigh>1?'s':''));
if (typeof openFindings === 'number' && openFindings > 0) bits.push(openFindings + ' open finding' + (openFindings>1?'s':''));
var att = document.getElementById('ccAttention');
if (att) att.textContent = bits.length
  ? bits.join(' and ') + ' need your attention'
  : 'All clear. Nothing urgent today.';
```

(Variable names above are placeholders — bind to the REAL local
variables/fields the function already extracts. Do not fetch anything
new.)

### Step 4 — Login functional polish

READ the login template fully, then:

1. **Dark-mode bootstrap**: check whether the login page sets
   `data-theme` before paint (grep how base_shell does it — a
   localStorage read in an early inline script). If the login page
   lacks it, replicate that exact snippet in the login `<head>`.
2. **Autofocus**: add `autofocus` to the username input.
3. **Autocomplete**: `autocomplete="username"` on username,
   `autocomplete="current-password"` on password.
4. **Submit state**: on form submit, disable the button and set its
   label to "Signing in…" (plain JS, 3 lines, inline). This prevents
   double-submits that burn the nginx login rate-limit budget.
5. Nothing else. No layout, color, or copy changes.

### Step 5 — Verify + commit

- Command Centre: greeting shows correct daypart + first name; the
  attention line matches the tile numbers on screen; single-word and
  empty full_name accounts do not break (test with the `bcm` seed user
  whose name is two words, and create/check one single-word name).
- All existing tiles/charts unchanged (screenshot diff vs pre-change).
- Login: dark-mode preference respected with no white flash (set dark,
  log out, reload); wrong-password path re-enables the submit button
  (server re-renders the page, so a fresh load — confirm the disabled
  state does not persist via bfcache: test browser Back after login).
- Commit: `Add Command Centre greeting and login polish`.

## Edge cases a weaker model would miss

- **Jinja `.split()` on None crashes the template** — the
  `(user.full_name or user.username)` guard must stay inside the
  `{% if %}` so a missing user (should not happen on an authed page,
  but error pages reuse templates) renders plain "Welcome back".
- **Daypart from CLIENT time, not server** — the VPS is UTC; Zimbabwe
  is UTC+2. Server-rendered "Good morning" would be wrong for hours
  every day.
- **The attention line must bind to variables `populateStats()` already
  has** — adding a new fetch would slow first paint and duplicate
  logic. If the function stores values only into DOM, read them back
  from the DOM ids instead (`parseInt(el.textContent)` with NaN
  guards).
- **bfcache and the disabled submit button**: after a failed login the
  server re-renders (fresh state), but browser Back from a successful
  login can restore the page from bfcache WITH the button disabled.
  Add a `pageshow` handler that re-enables it
  (`window.addEventListener('pageshow', reset)`).
- **Do not touch the form action, field names, or add JS-driven
  submission** — `POST /login` is rate-limited at nginx by exact
  location match; anything that changes the path or method breaks
  login for everyone.
- **`toLocaleDateString(undefined, …)`** uses the browser locale —
  correct here; do not hardcode en-US.
- **The greeting block sits above tiles that animate in with
  `.animate-fade-up` delays** — if the page applies staggered
  animation classes to direct children of the container you insert
  into, your new block may inherit an animation delay; either reuse
  the page's `anim-1` pattern deliberately or place the block outside
  the animated container.

## Acceptance criteria

1. Screenshot diff: everything below the new greeting row is pixel
   identical to pre-change, light and dark.
2. Greeting daypart matches local machine time; date renders in local
   format; first name correct for two-word, one-word, and NULL
   full_name accounts.
3. Attention line equals the on-screen tile numbers in all three
   states (both counts, one count, all-clear).
4. Login: no white flash in dark mode; password manager autofill works
   (autocomplete attributes present); double-click on Sign In sends
   exactly one POST (check the nginx/uvicorn access log); Back after
   login leaves a usable button.
5. Zero console errors on both pages.
