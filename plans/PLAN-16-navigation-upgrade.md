# PLAN-16: Navigation upgrade — labeled expanding rail (existing aesthetic preserved)

## HARD CONSTRAINT

**Zero aesthetic changes.** The user explicitly cancelled the visual
redesign. This plan changes navigation BEHAVIOR only. The rail keeps its
current dark `#0f172a` background, current icon SVGs, current active
style (`background:var(--accent)`), current tooltips in collapsed mode,
current fonts, current everything. No new design tokens, no glass
classes, no icon replacements, no color changes. If a step tempts you to
"improve" a color or shadow, do not.

## Goal

The 64px icon-only rail (`templates/_icon_sidebar.html`) hides what each
icon means behind hover tooltips, and module identity is invisible until
you click. Upgrade: the rail expands to show text labels (hover to peek,
click a pin to keep it open, choice persists per user via localStorage),
entries gain section labels (Main / Modules / Platform) and per-module
color dots — using only the colors and styles that already exist.

## Exact files to touch

1. `oneforall/templates/_icon_sidebar.html` — labels, sections, dots, pin button
2. `oneforall/templates/_icon_sidebar_styles.html` — expansion CSS
   (READ it first; rail styles are split between this partial and
   base_shell.html lines ~186-230 — put ALL new rules in the partial)
3. `oneforall/templates/base_shell.html` — nothing, unless the width var
   forces it (see edge cases)

## Step-by-step order

### Step 1 — Expansion CSS (in `_icon_sidebar_styles.html`)

```css
.icon-sidebar{transition:width .22s cubic-bezier(.4,0,.2,1)}
@media (hover:hover){.icon-sidebar:hover{width:208px}}
.icon-sidebar.pinned{width:208px}
.icon-sidebar .nav-label{display:none;font-size:12.5px;font-weight:600;
  white-space:nowrap;color:inherit;margin-left:10px}
.icon-sidebar.pinned .nav-label{display:inline}
@media (hover:hover){.icon-sidebar:hover .nav-label{display:inline}}
.icon-sidebar.pinned .icon-nav-tooltip{display:none !important}
@media (hover:hover){.icon-sidebar:hover .icon-nav-tooltip{display:none !important}}
.icon-sidebar .nav-section-label{display:none;font-size:10px;font-weight:700;
  letter-spacing:.08em;text-transform:uppercase;color:#475569;
  padding:10px 14px 4px;align-self:flex-start}
.icon-sidebar.pinned .nav-section-label{display:block}
@media (hover:hover){.icon-sidebar:hover .nav-section-label{display:block}}
.icon-sidebar .mod-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0;
  display:none;margin-left:auto}
.icon-sidebar.pinned .mod-dot{display:inline-block}
@media (hover:hover){.icon-sidebar:hover .mod-dot{display:inline-block}}
.icon-nav-item{justify-content:flex-start;padding-left:14px;width:100%}
.icon-sidebar:not(.pinned):not(:hover) .icon-nav-item{justify-content:center;padding-left:0}
@media (prefers-reduced-motion:reduce){.icon-sidebar{transition:none}}
```

Colors used above (`#475569` section labels) match the rail's existing
muted tone (`color:#64748b` on items, `#94a3b8` hover — verify against
the current styles and pick the closest EXISTING gray; do not introduce
a new palette).

### Step 2 — Markup (in `_icon_sidebar.html`)

For every `<a class="icon-nav-item">`: after the `<svg>`, add
`<span class="nav-label">…</span>` with the same text the tooltip uses
(keep the tooltip element unchanged — it still serves collapsed mode).

Add section labels: `<div class="nav-section-label">Main</div>` before
the Command Centre link, `Modules` before the first module link,
`Platform` before the governance/admin cluster.

Module links get a trailing color dot:
`<span class="mod-dot" style="background:#7d6527"></span>` — hex per
module copied EXACTLY from base_shell's `[data-module]` accent values:
aria `#7d6527`, grid `#059669`, bcm `#3d4660`, sentinel `#3b5bdb`,
erm `#881337`, orm `#7c3a0a`. (Literals are correct here: the rail shows
all modules at once, so `var(--accent)` — which resolves to the current
module only — cannot be used.)

Pin button at the bottom, above the admin/user cluster:

```html
<button class="icon-nav-item" id="railPin" aria-label="Pin navigation labels"
        onclick="tiqToggleRail()">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="9 18 15 12 9 6"/></svg>
  <span class="nav-label">Collapse</span>
</button>
```

Immediately AFTER the closing `</div>` of the rail, an inline pre-paint
script:

```html
<script>
(function(){
  var el=document.querySelector('.icon-sidebar');
  if(el && localStorage.getItem('tiqRailPinned')==='1') el.classList.add('pinned');
  window.tiqToggleRail=function(){
    var p=el.classList.toggle('pinned');
    localStorage.setItem('tiqRailPinned', p?'1':'0');
    var arrow=document.querySelector('#railPin svg');
    if(arrow) arrow.style.transform = p?'rotate(180deg)':'';
    setTimeout(function(){window.dispatchEvent(new Event('resize'))},250);
  };
  if(el && el.classList.contains('pinned')){
    var arrow=document.querySelector('#railPin svg');
    if(arrow) arrow.style.transform='rotate(180deg)';
  }
})();
</script>
```

### Step 3 — Verify

Desktop 1366px and 1024px, light and dark, on Command Centre + two
module pages:
- Collapsed rail is pixel-identical to today (64px, icons centered,
  tooltips on hover — compare against a pre-change screenshot).
- Hover expands with labels + sections + dots; mouse-out collapses.
- Pin persists across reloads and navigation with no flash of collapsed
  state on load.
- Touch emulation: first tap navigates; rail never expands on tap.
- Charts on ERM/Command Centre re-fit after pin toggle (the resize
  event dispatch).
- Keyboard: tab reaches every link and the pin button; Enter activates.

Commit: `Add expanding labeled navigation rail with pin persistence`.

## Edge cases a weaker model would miss

- **`@media (hover:hover)` around every `:hover` rule** — without it,
  the first tap on touch devices expands the rail instead of
  navigating. The pin path works on touch; hover-peek is desktop-only
  by design.
- **The pre-paint script placement matters**: inline immediately after
  the rail markup, NOT in DOMContentLoaded — otherwise pinned users see
  a collapse-then-expand flash on every page load.
- **Tooltip suppression needs `!important`** — the existing rule
  `.icon-nav-item:hover .icon-nav-tooltip{display:block}` has equal
  specificity; source order alone is not reliable across the two style
  locations.
- **Expanding pushes the layout** (the rail is in normal flex flow).
  Charts measured at mount distort — hence the debounced resize event
  in the toggle. Hover-peek also pushes layout briefly; that is
  accepted behavior (matches how VS Code's rail behaves), do not switch
  to overlay positioning, which would cover content.
- **`--icon-sidebar-w` stays 64px.** Grep it first: if any element
  offsets by the var, hover expansion will overlap it — test those
  pages specifically. Do not change the var; the transition overrides
  width directly on the element.
- **The user dropdown anchors to the bottom cluster**
  (base_shell.html ~line 227) — the pin button goes ABOVE the divider
  of that cluster so dropdown positioning math is untouched.
- **`justify-content` flip between collapsed/expanded** must not move
  icons: verify the icon column optically aligns at 64px in both rules
  (the collapsed selector wins only when neither pinned nor hovered).
- **Governance icon is capability-gated** (`can_governance_view`) —
  section label "Platform" must render inside the same conditional if
  governance is its only member, or it shows a heading over nothing
  for unprivileged users. Check which links live in that section and
  gate the label with the same Jinja condition as its first visible
  item.

## Acceptance criteria

1. Screenshot diff: collapsed rail identical to pre-change.
2. Pin survives 3 reloads + cross-module navigation, no flash.
3. All six module dots match the `[data-module]` accent hexes
   byte-for-byte (view-source check).
4. Touch: tap navigates, never expands.
5. No JS errors on any page; charts re-fit after toggling pin on the
   ERM dashboard.
6. A user without governance capability sees no orphaned "Platform"
   section label.
