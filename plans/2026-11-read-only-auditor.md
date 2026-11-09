# External auditor: comments only, never files

Branch `claude/auditor-comment-only`, from master b26c9536 (PR 52 merged 2026-11-09 22:25 CAT). On 2026-11-09 the owner said in chat: "an external auditor should only be able to put comments and not file anything". This answers finding F5 in [2026-11-relationship-service-fold.md](2026-11-relationship-service-fold.md). Decisions are chat confirmation, not sign-off.

## Survey

- The role is described as "Read-only access to controls, evidence, and audit logs" (`core/rbac.py`), but nothing enforced it centrally. Its capabilities include `module.aria.access`, `module.grid.access`, `governance.entities.view`, `aria.ask_ai`, `group.room.enter` and `ai_pack.receive`.
- A scan of every write route (POST, PUT, PATCH, DELETE) found about 240 that an External Auditor could reach on their decorator alone: 148 that need only a sign-in (all Vault writes, tasks, calendar, risks, reports, workflows, links, GRID assignments, governance packs and rooms) and about 40 ARIA writes that need only ARIA access. Some refuse inside the route body, many do not. Example: the Vault accepted an auditor's upload, edit and `auditor_signed` verification.
- Comments that exist today: questions in an auditor room (`/governance/api/group/rooms/{id}/messages`, auditors already allowed) and GRID control comments (`/grid/api/controls/{id}/comments`, needed `grid.control.update_own`, which the auditor lacks).
- Every signed-in write passes through `require_auth` or `require_capability` (the admin `_require_cap` and `require_module` are aliases). The exceptions are sign-in itself (`/login`, `/mfa/verify`), super administrator routes, the public demo form and the API v1 key routes, whose keys only an administrator issues.

## Decisions

| Decision | Why | Cost | How to change |
| --- | --- | --- | --- |
| D1. A person whose every role is read-only (`READ_ONLY_ROLES = {external_auditor}`) gets a 403 for any write, checked in `require_auth` and `require_capability` before the route runs. | One check in front of every route, so a route that forgets its own capability cannot let an auditor file anything. | A future auditor action must be added to the list on purpose. | `READ_ONLY_ROLES` and `_READ_ONLY_WRITES` in `core/rbac.py`. |
| D2. What they may still send: their own sign-out, password, two-step sign-in, email and dashboard preferences and notifications; reading through a form (the platform guide, Ask ARIA and its rating, the Vault's question search); comments (auditor room questions, GRID control comments). | "Only comments". The reading forms change nothing. | They cannot generate Word exports of AI policy drafts, create tasks, reminders, calendar events or saved views. | `_READ_ONLY_WRITES`. |
| D3. External auditors may comment on GRID controls in their scope (`grid.control.comment`). | It is where an outside auditor's remarks belong, and the owner's words allow comments. | Audit staff see auditor comments in the control drawer. | Remove `EXTERNAL_AUDITOR` from `grid.control.comment`. |
| D4. Someone who holds another role as well writes as that role allows. | The rule describes the read-only role, not a person; an employee who is also named as an auditor still files their own work. | None. | `is_read_only`. |
| D5. The Vault hides Upload, Batch upload and every edit control in the file drawer for a read-only person (`can_file`, `can_change`). | They would only meet a refusal. | None. | `evidence_page` and `api_evidence_get` in `modules/evidence/routes.py`, `evidence_vault.js`. |

Other modules still show their buttons to an auditor; pressing one gives the read-only message. Hiding them module by module is a follow-up.

Still open: any staff member can mark their own file `auditor_signed` (+40 confidence). Now that auditors file nothing, that label is always a self-claim. Product decision.

## Evidence

| Check | Result |
| --- | --- |
| `tests/test_read_only_role.py` (the rule, real requests through the Vault, ARIA and GRID routers, a mixed-role person, and a scan proving every write route passes through the decorators) | 37 passed. Without the middleware change the Vault case fails; the ARIA cases assert the read-only message, so they prove the rule fired first. |
| 90 backend files using the auditor role, capabilities, GRID, Vault, evidence, group rooms and relationships | 1636 passed, 101 skipped |
| 22 Vault, GRID, download and style browser files | 124 passed, 1 failed: the batch DOCX test (signs in as a compliance manager, so the rule does not affect it) timed out under load and passed alone |
| New `tests/ui/test_read_only_vault_ui.py` and the three other browser files that sign in as the auditor (`viewer`) | 20 passed, 1 skipped |

## Change log

- 2026-11-09: survey, D1 to D5, built.
