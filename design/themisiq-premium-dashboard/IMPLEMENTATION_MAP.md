# Sage / Dusk application mapping

The design study in this directory is illustrative. Live metrics, permissions, routes, forms, and stored data remain in their existing templates and services.

| Surface | Existing entry point | Application treatment |
| --- | --- | --- |
| Core shell and module pages | `oneforall/templates/base_shell.html` | Load shared theme last; Sage is default, Dusk follows the existing `ofa-theme` dark setting; keep responsive layout and keyboard behavior. |
| Command Centre and platform work | `oneforall/modules/launcher/templates/platform_base.html`, `my_dashboard.html` | Use self-hosted typography, glass cards, muted depth, blue accent, reactive hover states and the live dashboard hero. |
| Governance, Audit, Resilience, Privacy, Enterprise Risk, Operations Risk | `aria`, `grid`, `bcm`, `sentinel`, `erm`, `orm` module templates | Keep each module's existing accent; tint selected navigation, dashboard headers, hero cards, charts, and focus treatment against Sage/Dusk surfaces. |
| Shared workspaces | `evidence`, `evidence_campaigns`, `readiness`, `saved_views`, Governance Settings | Use shell-neutral accent except Settings purple; align Evidence Vault filter colors with their source modules. Saved Views is a shared utility, not a new route. |
| Authentication and entry | `launcher/login.html`, `mfa_verify.html`, `launcher.html`; error page | Align standalone pages with the same palettes and typography. |
| Public shared audit | `grid/shared_audit.html` | Sage glass report presentation; retain read-only data and link behavior. |
| Legacy admin shell | `launcher/base.html` | Match Sage/Dusk variables if it renders. |
| Design preview | `design/themisiq-premium-dashboard` | Default to Sage, retain Dusk option, remove the decorative eyebrow line. |

Implementation rules: use the existing local font assets (`DM Sans`, `Cormorant Garamond`); apply module colors as accents rather than repainting semantic status; replace colored card top strokes and sweeping card sheen with subtle lighting; retain visible keyboard focus and reduced-motion behavior. The dash in the screenshot is the mockup's `.eyebrow::before`; remove that rule rather than editing meaningful hyphens or date ranges in application data.
