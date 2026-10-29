# 21. Group figures (G1): frozen figures, the three views, not reporting

**Status:** Plan and build log, 2026-10-29. Implements stage 2 of [19 Evidence Vault and group oversight](19-evidence-vault-and-group-oversight.md) (group relationship and figures) at its smallest useful size. Builds on the relationship, grant, row level security and role work already merged from PR 40. The owner asked for this slice after the merge (chat, 2026-10-29).

## 1. Scope

In: each tenant publishes frozen, hashed figures of the registered Command Centre metrics; the group reads those figures in three views (Econet alone, one subsidiary, the whole group); a tenant that has not reported shows **not reporting**, never zero.

Out, still withheld: the **banded group score for subsidiary seniors** (stays off until the inference tests in plan 19 section 10 pass), exports and packs, restatement, level 2 registers, and any figure that is not already a registered metric.

## 2. Design

| Part | Decision |
| --- | --- |
| Source of the numbers | `modules/launcher/command_metrics.build`, the same builders the Command Centre uses, run inside the tenant for the whole organization. Nothing is recalculated for the group. |
| What is published | Per metric: key, state, value, window, as-of, method version, and `detail` only when it is a flat map of numbers (for example risks by level). Never a label that came from a record, a note, a source name that is not a table name, a title or a free text field. A metric whose module is not licensed to the tenant is not published. |
| Storage | `public.group_figure_snapshots`, append only. Row: source organization, measure key, state, value, window, as-of, method version, detail (numbers only), publication version, content hash. No update or delete policy. |
| Who can read a row | The source organization; the parent organization of an **active, reviewed** relationship. A child never reads its parent's rows and a sibling reads nothing. Enforced by row level security and again in the service. |
| Who may ask | `group.figure.view_exact` (Chief GRC Officer, Compliance Manager, Audit Lead, DPO) **and** a named, unexpired `figure.view` grant on that relationship, using the existing grant table, so a person can be limited to one subsidiary and every grant is reviewed and expires. |
| Role filter | The Chief GRC Officer and Compliance Manager see every published metric; the Audit Lead sees audit, evidence and platform figures; the DPO sees privacy figures. A metric outside the role's modules is omitted, so neither its number nor its existence is sent. |
| Not reporting | A subsidiary with an active relationship and no figure newer than 48 hours is shown as not reporting, with the date of its last figure. It never contributes a zero to a total. |
| Rollup | Sums only for metrics defined as counts (no denominator). Shares and levels are shown per entity and marked not additive. |
| Cadence | Daily scheduled job (configurable setting `group.figures.interval_hours`, default 24) with a cross-process lease; the platform operator can also publish one tenant on demand. |
| Disclosure | Counts, small numbers and trends can still reveal things; this slice publishes figures to a parent that already has an active, reviewed relationship and a named grant, and it records every read in the shared access log. The privacy reviewer must approve each customer's published measure list before real data flows (plan 19 section 10). |

## 3. Build log

- 2026-10-29: plan written.
- 2026-10-29: built. `public.group_figure_snapshots` (append only, forced row level security: the source reads its own rows, the parent of an active relationship reads its children's, nobody can update or delete, a child never reads its parent's); `group_view_grants` accepts `figure.view` (check widened, with an idempotent PostgreSQL migration); capability `group.figure.view_exact`; `modules/governance/group_figures.py` (sanitize, collect, publish_tenant, publish_all, views, view, totals); routes `GET /governance/group/figures/` (page, 404 for other roles), `GET /governance/api/group/figures/views`, `GET /governance/api/group/figures?view=own|group|subsidiary`, `POST /governance/api/group/figures/publish` (platform operator); a daily job in the governance scheduler (02:30 UTC, cross-process lease); the sharing form offers a "View group figures" grant.
- Tests: 15 service tests (what may be published, append only versions and hash, licence filter, grants and masking, role filter, not reporting, additive totals only, trend, audit log), 5 browser tests (three views, silent subsidiary, DPO limited, masked page and API), and a real PostgreSQL test with three provisioned tenants (publish from tenant schemas, parent reads child, child never reads parent, sibling reads only itself, no write to another tenant's rows, no update or delete).

## 4. What is not in this slice

- The banded group score for subsidiary seniors. Still withheld until the inference tests pass.
- The figures are the Command Centre set (`cc.*` metrics and module health). The module dashboards' own metrics (`bcm.*`, `sentinel.*` in the registry) are not published yet.
- No restatement flow, no group packs or exports.
- A figure that is published is visible to every granted holder of the role family; the privacy reviewer's per-customer approval of the measure list is a gate before real data (plan 19 section 10), not enforced in code.
- The default publish cadence is daily at 02:30 UTC; the setting named in section 2 is not wired yet.
