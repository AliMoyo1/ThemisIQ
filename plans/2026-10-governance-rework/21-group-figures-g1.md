# 21. Group figures (G1): frozen figures, the group views, the banded score, the issue register and packs

**Status:** Built and verified on branch `claude/group-figures`, 2026-10-29. Not merged: the owner will merge once everything is built (chat, 2026-10-29). Implements stage 2 of [19 Evidence Vault and group oversight](19-evidence-vault-and-group-oversight.md) (group relationship and figures). Builds on the relationship, grant, row level security and role work merged from PR 40. Decisions below are owner direction given in chat, not a formal sign-off.

## 1. Scope

In, all built:

- **S0/G1 core.** Each tenant publishes frozen, hashed figures of the registered Command Centre metrics. The group reads them in three views (Econet alone, one subsidiary, the whole group). A tenant that has not reported shows **not reporting**, never zero.
- **S1 measure gate and cadence.** A relationship's reviewed terms list the measures the child may publish (none by default). The publish interval is a platform setting.
- **S2 reconciliation and lineage.** Two independent builds must agree before a figure is published as a number; every figure carries its lineage.
- **S3 restatement.** A correction is proposed by one person and approved by another, and publishes a new snapshot that points at the original.
- **S4 banded group score** for subsidiary senior roles, with disclosure controls and leak tests.
- **S5 level-2 issue register.** Individual breaches, requests, DPIAs and RoPA entries by reference, with fixed fields only; consent as counts.
- **S6 group packs.** A frozen, signed-off, reproducible set of figures with PDF and Excel export.

Out, still: the **auditor room** (see section 6), any metric that is not a `cc.*` metric, emailing a pack.

## 2. Design

| Part | Decision |
| --- | --- |
| Source of the numbers | `modules/launcher/command_metrics.build`, the same builders the Command Centre uses, run inside the tenant for the whole organization. Nothing is recalculated for the group. |
| What is published | Per metric: key, state, value, window, as-of, method version, and `detail` only when it is a flat map of numbers. Never a label that came from a record, a note, a title or a free text field. A metric whose module is not licensed to the tenant is not published. |
| Which measures | Only those the relationship's reviewed terms list (`figure_measures`). The default is none. Terms are re-checked when a parent reads, so narrowing them stops reading what was already published. |
| Storage | `public.group_figure_snapshots`, append only; no update or delete policy. |
| Who can read a row | The source organization; the parent of an **active, reviewed** relationship. A child never reads its parent's rows and a sibling reads nothing. Row level security and the service both enforce it. |
| Who may ask | `group.figure.view_exact` (Chief GRC Officer, Compliance Manager, Audit Lead, DPO) **and** a named, unexpired `figure.view` grant. |
| Role filter | The Chief GRC Officer and Compliance Manager see every published metric; the Audit Lead sees audit, evidence and platform figures; the DPO sees privacy figures. A metric outside the role's modules is omitted, so neither its number nor its existence is sent. |
| Not reporting | No figure newer than 48 hours. It never contributes a zero. |
| Rollup | Sums only for metrics defined as counts. Shares and levels are shown per entity and marked not additive. |
| Cadence | Hourly job with a cross-process lease; the platform setting `group.figures.interval_hours` (1 to 168, default 24) decides which tenants are due. The platform operator can also publish one tenant on demand. |
| Access log | Every read of a subsidiary's figures, register or pack is written to `group_access_events`. |

## 3. The banded group score (S4)

A subsidiary senior role (Chief GRC Officer, Compliance Manager, Audit Lead, DPO; capability `group.figure.view_band`) sees one thing about the group: a band, a trend against the last published period, and when it was made. Never an exact score, who is in the group, how many there are, or why a band is absent.

**What the leak tests found.** The first design (five bands, one worst-case rule for every viewer) failed my own brute-force test for a group of three: knowing your own score and a five-band group result narrows a sibling to a few points. The design that passes is:

- **Adaptive scale.** Three bands (Weak, Fair, Strong) for fewer than six reporting organizations, five from six.
- **Per-viewer, per-band doubt rule.** A band is shown to a viewer only if, knowing their own score, they cannot narrow any single other organization below a minimum range (default 40 points, floor 30). Judged on the actual band, never on the worst case. A viewer with no score of their own is judged by the worst own score.
- **Minimum cohort** of three reporting organizations (default 3, floor 3). The settings `group.band.min_cohort` and `group.band.min_width` can only be made stricter than the floors.
- **Hysteresis** of 3 points past an edge before the band moves, **one band per parent per ISO week**, and **no band for the week after the set of reporting organizations changed**, so a member joining, leaving or going quiet cannot be read off a band change.
- **Not reporting is left out of the cohort, never counted as zero.**
- The exact mean and cohort are stored in a parent-only table. A subsidiary reads its own viewer row and its parent's publication, never the internal row (tested on PostgreSQL).

**Trade-off, stated plainly.** "Not available" is one answer for every reason, but a viewer whose band is extreme for them is told nothing, which is itself a small signal that the band is extreme. That is less than showing it. A band older than 14 days is not shown.

**Residual risk.** This is a rule-based bound, not a formal differential privacy guarantee. A determined insider who watches their own score and the band across many weeks could still learn something about movement in the sum of the others. The privacy reviewer should decide whether the band is acceptable for each customer before real data flows.

## 4. The issue register (S5)

- A tenant publishes, per approved type, a **run** of sanitized rows: `breach`, `dsr`, `dpia`, `ropa`, and `consent` as one summary row of counts by status.
- **Field contract.** Each type has an allowlist of fields, each with its own pattern or fixed vocabulary (dates must be real calendar dates; severities, statuses, request types and regulations come from fixed lists; counts are bounded integers; flags are 0 or 1). **A value that does not fit is published as nothing, never as the text it held.** A free-typed breach type that is not in the vocabulary becomes `other`. A reference that is not a plain reference becomes `<type>-<id>`. References are generated by the system, not typed.
- Titles, descriptions, requester names and emails, notes, owners and AI text never leave. The leak test fills every free-text column of every Sentinel register with a canary and asserts it is nowhere in the shared tables.
- **Gates, all four required:** the terms list the type (`issue_types`, none by default), a named unexpired `issue.view` grant, the role (`group.issue.view`: Chief GRC Officer, Compliance Manager, DPO; the Audit Lead is not included because the register is privacy data), and the subsidiary is licensed for Sentinel. A figure grant does not open issues and an issue grant does not open figures. An unapproved type looks like an unknown one.
- Limits: 2,000 rows per type per run (the cut is shown), the latest 30 runs per type are kept and older ones pruned (platform job only), a register not refreshed for 48 hours shows as not reporting with no rows.

## 5. Group packs (S6)

- A pack holds a **manifest of snapshot ids and a hash**, not numbers. Opening it reloads exactly those rows (never the latest), recomputes every snapshot's own hash and the manifest hash, and shows "integrity check passed" or a failure notice. Reopening is reproducible.
- **Sign-off.** One person freezes it (Chief GRC Officer, Compliance Manager); a different person signs it off or rejects it (Compliance Manager, Audit Lead, DPO). The decision is final, and on PostgreSQL a decided pack cannot be updated or deleted (the update policy only matches `proposed`).
- **Not a way round the grants.** A reader sees only subsidiaries they currently hold a figure grant for, only measures the terms still approve, and only their role's module families. Everything else is left out without a placeholder.
- **Corrections** after issue do not change the pack. The pack page and the exports show a "Corrections since this pack was frozen" notice built from later restatements.
- Export: PDF and Excel on the shared report kit as a board report, with the status, sign-off and fingerprint on the first page. A draft is labelled "Draft: not signed off".

## 6. Honest gaps

- **Auditor room: deferred.** It needs external identities, time-boxed access and its own legal terms. The grant model here covers named internal users only. Doing it properly is a separate plan.
- **Only `cc.*` metrics** (Command Centre and module health) are published. The module dashboards' own metrics are not.
- **No nested groups.** A parent reads its direct children only, and a child can have one active parent.
- **Privacy reviewer approval is a process gate, not enforced in code.** The terms default to publishing nothing, which is the safeguard until a named reviewer approves each customer's measure and issue lists.
- **The pack contains figures only.** Issue register rows and the band are not in packs.
- **Existing SQLite development databases** keep the old `group_view_grants` check, so `issue.view` grants need a fresh database there. PostgreSQL is migrated by an idempotent alter.
- Pack and register reads write access-log rows, so they are not pure reads.
- **A pack whose relationship has ended cannot be re-checked.** Row level security stops the former parent reading the former child's snapshots, so the integrity check reports a failure for that pack rather than a pass. That is the safe direction, but the wording does not yet say "cannot be checked".
- **Figures and the register are published for the whole organization**, not split by business unit, as the figures already were. A subsidiary that needs a unit-level split needs a new decision.

## 7. Build log

- 2026-10-29: core (G1): snapshots table, forced row level security, `group.figure.view_exact`, `modules/governance/group_figures.py`, the page and API, the hourly job, the figure grant in the sharing form.
- 2026-10-29: S1 measure gate and cadence: terms accept `figure_measures`, the publish job honours the interval setting.
- 2026-10-29: S2 reconciliation and lineage (`group_figure_lineage`, source-only).
- 2026-10-29: S3 restatement (`group_figure_restatements`, corrections panel on the page).
- 2026-10-29: S4 band: `group_band.py`, three tables with row level security, `/governance/api/group/band`, 24 tests.
- 2026-10-29: S5 issue register: `group_issues.py`, two tables, `issue.view` grant, `issue_types` in terms, panel on the page, 16 service tests, a PostgreSQL test and 2 browser tests.
- 2026-10-29: S6 packs: `group_packs.py`, `group_packs` table, five routes, panel on the page, 10 service tests, a PostgreSQL immutability test and 3 browser tests.
- A stale-response guard on the figures page, found by a flaky browser test: a slow earlier answer no longer replaces the view the person has since chosen.

## 8. Verification

- Full backend suite (SQLite): one failure, the guard `test_no_silent_database_swallows`, which found two unlogged database errors in my new code (`group_band._setting`, `group_figures.interval_hours`). Both now log through `core.best_effort.swallowed`; the guard and the group tests pass.
- After the fix: 190 passed, 7 skipped on the group, capability, RBAC and guard selection.
- Browser: `tests/ui/test_group_figures_page.py` 12 passed.
- PostgreSQL lane (real PG 18, restricted role): passed, including the three new row level security tests (band, restatement and lineage; issue register; decided pack immutability).
- `scripts/capability_inventory.py --check` passes with the regenerated inventory.
- Not run: the whole backend suite again after the two-line logging fix (the guard and group tests were).
