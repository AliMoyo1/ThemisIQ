# 20. Group oversight across tenants

**Status:** Proposed plan, 2026-10-28. Nothing here is built, tested or deployed. Settles open decision 1 of [19 Evidence Vault company navigation](19-evidence-vault-company-and-lifecycle.md): the group and its subsidiaries are **separate tenants**. Builds on the tenant model (schema per tenant, row level security, one license per organization) and does not relax it.

## 1. Decisions taken by the owner (chat, 2026-10-28)

These are confirmed in chat by the owner, not signed off by a privacy or legal reviewer.

1. Econet is the group company. EcoCash and OmniContact are subsidiaries, each a **separate tenant with its own license**.
2. **Group visibility is mandatory.** A subsidiary does not opt in and cannot switch it off. It can see what the group sees (transparency).
3. Sensitive documents and similar material move only through a **request pipeline**: the group requester asks, the subsidiary decides and fulfils.
4. Some work is shared. The **group DPO, who also covers legal**, looks at issues across the whole group.
5. Subsidiary senior roles may see the **overall group score** and **group-published documentation** (published versions only, never drafts). They never see another subsidiary.
6. **Group pricing is included by default** in the licenses; it is not a separate add-on.
7. The group score display for subsidiaries, and the choice of senior roles, were delegated to the planner (sections 4 and 5).
8. **Legal falls under the Data Protection Officer.** There is no separate legal role: the group DPO covers group legal matters, and the capabilities for group cases and requests sit with the DPO role.

## 2. The three views

| View | Who | Source |
| --- | --- | --- |
| Econet alone | Econet roles, as today | Econet's own tenant |
| One subsidiary | Its own roles, plus named group roles under the group relationship | That subsidiary's own tenant |
| Econet Group | Senior group roles only | Econet's own data plus what each subsidiary reports |

The Econet-alone view must be switchable from the group view: a group senior user sees Econet's own compliance without the subsidiaries mixed in, then the group rollup, then any one subsidiary.

## 3. Mechanism

No query ever crosses a tenant boundary. Group visibility is built from four parts held in the shared (public) schema and enforced in the source tenant.

1. **Organization relationship.** `org_relationships`: parent organization, child organization, status, start and end date, created by the platform operator at license time. Not editable by a subsidiary administrator. A subsidiary administrator can read it and the list of what the group may see.
2. **Group roles as capabilities.** New capabilities, never inferred from existing role names alone (section 5).
3. **Snapshots for level 1.** Each tenant publishes frozen, hashed compliance figures on a schedule: module, measure, value, method version, as-of time. The group rollup reads snapshots only. A tenant that has not reported shows **not reporting**, never zero. A lapsed license or an ended relationship removes the tenant from the rollup immediately.
4. **Requests and group cases for everything else** (sections 6 and 7). Drill-down and documents are produced inside the subsidiary's tenant under its own permission checks, then returned or shared.

## 4. What each level carries, and the group score display

| Level | Content | Personal data |
| --- | --- | --- |
| 1 Figures | Scores per framework and module, counts, overdue items, open issues by severity, as-of date and method version | None. Numbers only. |
| 2 Registers | Named fields only: titles, owners (staff business contact), status, dates, severity, deadlines, source reference | Staff names and work emails only. Free text fields are excluded. Data subject requests and consent records appear as **count and deadline only**, never names, emails or details. |
| 3 Documents | Group-published documents flow down freely. Subsidiary documents flow up only through the request pipeline. | Withheld, redacted or released per request by the subsidiary's classification and reviewer. |

The first release carries level 1 and the published group documents, and level 2 for the issue register used by the group DPO and group legal. Level 2 for other modules and any level 3 flow up only after the privacy review in section 8.

**Group score shown to subsidiary senior roles (decided).** Show the group score as a **band with a trend**, not an exact figure: five bands (for example Strong, Good, Fair, Weak, Critical) and an up, flat or down arrow against the previous period, plus the date and the method version. Reason: with three entities, an exact group score less the viewer's own contribution would reveal the other subsidiary's score. A band is coarse enough to prevent that. Group roles see exact figures and the per-subsidiary breakdown. The group score for a subsidiary viewer excludes nothing silently: if a tenant is not reporting, the band says so.

## 5. Roles (selected from the existing role set)

Existing roles are in `core/rbac.py`. None of them gains group access by name; a person holds a group capability only when granted it, and only roles listed here can be granted it.

| Role | Group side (Econet tenant) | Subsidiary side |
| --- | --- | --- |
| Chief GRC Officer (`grc_officer`) | Full group view, exact scores and per-subsidiary breakdown, levels 1 and 2, create and track requests, run group cases | See the group band and group-published documents, decide requests aimed at the subsidiary |
| Compliance Manager (`compliance_manager`) | Level 1 exact, level 2 for policy, control and audit registers, create requests | Group band and group documents, decide requests |
| Data Protection Officer (`dpo`), including group legal matters | Level 1 privacy figures, level 2 issue register for the whole group (counts and deadlines, no subjects), create requests, run and join group cases | Group band and group documents, decide privacy and legal requests |
| Audit Lead (`audit_lead`) | Level 1, level 2 audit register, create audit evidence requests | Group band and group documents, decide audit evidence requests |
| Super Administrator | Configures relationships and licenses. **No** group content access through this path unless also granted a group role. | Same |
| Risk Owner, BCM Manager | Not in the first release. Level 1 for their module can follow. | None |
| Org Administrator, Policy Author and Approver, Control Owner, Auditor, Privacy Analyst, BCM Responder, Incident Commander, Employee, External Auditor | No group access | No group access |

There is no legal role in the platform today and none is added: by the owner's decision legal falls under the DPO, so the group DPO holds the group case and issue register capabilities. If the group later wants a separate legal reviewer, that is a new role and a new decision.

New capabilities (names provisional): `group.score.view_exact`, `group.score.view_band`, `group.register.view`, `group.request.create`, `group.request.decide`, `group.case.participate` (DPO), `group.documents.view_published`, `group.relationship.manage` (platform operator only). Each is added to the capability inventory and tested per role.

A group role can be limited to one subsidiary: a person may hold the grant for EcoCash only. Grants are assigned by the group's Chief GRC Officer and listed to the subsidiary.

## 6. Request pipeline (sensitive documents and detail)

1. A group user with `group.request.create` opens a request from a group view or a group case: subsidiary, what is wanted (a document, a register extract, an answer), why, the period, the group case it relates to, and the needed-by date.
2. It lands in the subsidiary's request queue (and My Work) for a user holding `group.request.decide` for that domain. The subsidiary reviewer sees the request, the requester and their role, and the stated reason.
3. The subsidiary **approves, narrows or declines**, with a reason. Declining is a recorded outcome; there is no override by the group. If the group needs to compel disclosure, that is a contract and escalation matter outside the platform.
4. An approved item is released by the subsidiary into the request: a Vault document or generated pack, with redaction applied and classification checked in the subsidiary's tenant. The release has an expiry and is revocable. The group user receives a time-limited, logged read, not a copy that lives on in the group tenant by default.
5. Audit in both tenants: who asked, who decided, what was released, who opened it and when. Reminders and escalation follow the shared notification service; unanswered requests age visibly in both queues.

The request pipeline reuses the Vault's evidence-request and review concepts where they fit; it does not create a second document repository.

## 7. Group cases (collaboration of the group DPO and legal)

A **group case** is a record in the group tenant that tracks an issue across subsidiaries: for example a breach affecting two entities, a regulator inquiry, or a policy exception. Participants are named people from the group and, when invited, a named person from a subsidiary.

- The group DPO (covering legal) sees level 2 issue information for the whole group (severity, status, authority notification state, deadlines), with no data subject details.
- Details come through requests (section 6), attached to the case.
- A subsidiary participant sees only their own subsidiary's part of the case and the group's published position. They are not shown other subsidiaries' material.
- A case never copies a subsidiary's record into the group tenant; it holds references and released, expiring items.

## 8. Personal data and privacy review

- Level 1 carries no personal data, so it can ship first and avoids most cross-entity questions.
- Staff names and work emails appear in level 2 registers as business contact data, with a visible notice.
- Data subject requests, consent records, breach narrative, incident narrative and free text never appear above level 1 except as counts and deadlines. Scrubbing happens in the subsidiary's tenant before anything is copied or returned, never after it reaches the group.
- File contents can hold anything; only the request pipeline moves a subsidiary file, with the subsidiary's own classification and redaction decision.
- **Legal review needed before level 2 goes beyond the issue register, and before any level 3:** whether intra-group sharing counts as a transfer under the regimes that apply to each subsidiary (for example the Zimbabwe Cyber and Data Protection Act), the lawful basis, an intra-group data sharing agreement, and a DPIA. This plan does not assert legal conclusions. A named privacy reviewer at Econet owns it (open decision 3).
- Group access logs record who looked, not what personal data they saw, and avoid raw search text.

## 9. Licensing

- Each organization keeps its own license row and seats. The parent license carries the **group module** automatically; each subsidiary license automatically includes receiving the group band and group-published documents. No separate purchase.
- If a subsidiary's license lapses, it leaves the group rollup and shows not reporting. Its historical snapshots remain for the group's own audit trail under the group's retention rules.

## 10. Security rules

- No relaxation of `org_id` predicates or row level security. Group data is read from snapshots, or produced inside the subsidiary tenant under the subsidiary's checks.
- Group capability checks, tenant checks and relationship status are all evaluated server side on every request; masked responses (not found) for anything the viewer may not know exists.
- A group user in one subsidiary view never sees another subsidiary's name, count or existence through search, autocomplete, empty states, latency or error wording.
- Relationship ends, grants withdrawn or a role removed take effect on the next request; cached rollups and released items expire.
- The platform operator account that creates relationships has no automatic content access.

## 11. Delivery slices

| Slice | Build | Gate |
| --- | --- | --- |
| G0 Inventory and decisions | Inventory the personal data actually present in each module's columns and free text; confirm the tenant setup and licenses of Econet, EcoCash, OmniContact; agree the role mapping and group counsel role; agree the score bands and publishing cadence; start the legal review in section 8. | Written inventory, named privacy reviewer, decisions recorded. No code. |
| G1 Relationship and snapshots | `org_relationships`, group capabilities, tenant snapshot publisher and the group rollup with the three views, not reporting states, banded group score for subsidiary seniors. | Two-tenant and three-tenant non-disclosure tests; a subsidiary cannot see a sibling; capability inventory regenerated; real PostgreSQL tests. |
| G2 Published group documents | Group-published (never draft) documents shown to subsidiary senior roles in their own tenant. | Published only, version pinned; drafts never visible; revocation tested. |
| G3 Requests and group cases | Request pipeline with decline, narrow and expiring release; group cases for DPO and counsel; level 2 issue register without data subject details. | Personal data scrub tests; audit in both tenants; no copy persists after expiry. |
| G4 Further registers and packs | Level 2 for other modules and group packs, after the privacy review. | Legal sign-off recorded; adversarial wrong-tenant tests. |

Plan 19 (company navigation) continues for Econet's **own** business units. Its company facet is not a cross-tenant mechanism.

## 12. Open decisions

1. ~~Group counsel role~~ Settled: legal falls under the DPO (decision 8).
2. Snapshot cadence (daily is the proposed default) and who may trigger an early refresh.
3. The named privacy reviewer and the legal reviewer at Econet for section 8.
4. Whether a group case may ever ask a subsidiary participant to see another subsidiary's released item. Recommendation: no.
5. How an unanswered or declined request escalates inside the group, outside the platform.

## 13. Research before build

Survey done 2026-10-28, before G1, as the owner's instructions require. Method: web search and reading each project's public page or documentation; licence, last push and archive status from the GitHub API. **Nothing was installed, executed or copied, and no data was sent to any of these projects.** The conclusion is to build the small mechanism in-house and borrow patterns only.

| Project | What it offers for this problem | Licence, maintenance | Decision |
| --- | --- | --- | --- |
| [CISO Assistant community](https://github.com/intuitem/ciso-assistant-community) (GRC platform) | The closest product. It has "multi-level domains" and role based access inside one instance. Advanced multi-tenancy for large organizations and MSPs is described as a separate effort (CA Hub) and its page does not say what is in the free edition. | Repository pushed 2026-10-28, not archived. Files outside `enterprise/` are AGPL-3.0; the `enterprise/` directory is under a commercial licence, and GitHub reports the repository licence as unrecognised. | No code reuse: the AGPL and commercial split is a licensing risk for embedding, and a single-instance domain tree is not our separate-tenant case. Treat as competitor reference only. |
| [OpenFGA](https://github.com/openfga/openfga) and [its multi-tenant guide](https://openfga.dev/docs/use-cases/multi-tenant-saas) | Relationship tuples. Tenant isolation is the default; a resource can be granted to a user of another organization through the same model, and a `parent` relation lets permissions follow an edge. | Apache-2.0, pushed 2026-10-28. | Borrow the idea: an explicit, revocable relationship record per grant, default deny. Do not adopt the server: a separate authorization service adds a second trust boundary for a few relationship rows. |
| [SpiceDB](https://github.com/authzed/spicedb), [Ory Keto](https://github.com/ory/keto), [Casbin](https://github.com/apache/casbin), [Cerbos](https://github.com/cerbos/cerbos) | Authorization engines of the same family (Zanzibar style or policy engines). | All Apache-2.0; SpiceDB, Casbin and Cerbos active in October 2026, Keto last pushed 2026-09-04. Only repository metadata was checked. | Not adopted, for the same reason as OpenFGA. |
| [ZITADEL](https://github.com/zitadel/zitadel) and [its organizations article](https://zitadel.com/blog/multi-tenancy-with-organizations) | **Granted projects:** one organization grants a project and a subset of roles to another; the grantor controls it and removing the grant removes every authorization that came from it. Organizations are flat, not a tree. | AGPL-3.0, pushed 2026-10-28. | Borrow the semantics (grantor controlled, revocation cascades, narrowed role subset). No code: AGPL, and it is an identity provider. |
| [Keycloak](https://github.com/keycloak/keycloak) organizations | A second tier of organizations inside a realm; a user can belong to several. No native parent and child tree found. | Apache-2.0, very active. | Not a fit: it is login and membership, not data oversight. |
| PostgreSQL row level security patterns (vendor and community articles) | A dedicated reporting role with its own permissive policy can read across tenants; analytics across tenants is costly, which supports precomputed rollups. | PostgreSQL feature, no dependency. | We deliberately avoid a cross-tenant reporting role: snapshots published per tenant keep the boundary intact. Nothing found covers leak resistant snapshots (banding, minimum reporting entities), so that part is our own design and gets adversarial tests. |
| [Eclipse EDC](https://github.com/eclipse-edc/Connector) (data space connector) | Contract negotiation between organizations before data moves, the closest published pattern to the request and release pipeline. | Apache-2.0, pushed 2026-10-28. Only repository metadata was checked; not read in depth. | Borrow the idea of an explicit request, a recorded decision and an expiring release. Far too heavy to run. |
| Eramba | Searched for the public repository; the name did not resolve on GitHub. Not assessed. | Unknown. | Not assessed. |

**Result:** no open source GRC product or access control component provides a ready parent and child oversight with mandatory visibility, snapshot rollup and a request and release pipeline. The mechanism in sections 3 and 6 is small (a relationship table, capabilities, a snapshot table, a request and release record) and is built in the existing codebase. Patterns taken: explicit revocable grants (OpenFGA, ZITADEL), grantor-controlled cascade on revocation (ZITADEL), request then decision then expiring release (EDC). Risks noted for any later adoption: the AGPL and commercial split of CISO Assistant, the AGPL of ZITADEL, and the added trust boundary of any external authorization service. This survey is an input to the plan, not a legal opinion on licences.

## 14. Log

- 2026-10-28: plan written from the owner's decisions in chat. Group score band and the senior role selection chosen by the planner and recorded for the owner to confirm.
- 2026-10-28: owner decided legal falls under the DPO; the proposed group counsel role is dropped. Open source survey done (section 13); conclusion: build in-house, borrow patterns.
