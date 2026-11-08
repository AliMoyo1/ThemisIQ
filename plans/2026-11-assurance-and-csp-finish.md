# Assurance, Themis retrieval and CSP continuation

Updated 2026-11-05. This ledger covers the work started after the Vault scope merge. It does not mark a production release complete.

The [current build status](CURRENT-BUILD-STATUS-2026-11-05.md) reconciles this branch against other active and superseded plans. A red-to-green DPIA regression demonstrated that its completion event silently confirmed a keyword match against the legacy `aria_controls` table. The new scoped review path uses canonical `controls` and requires a specialist's explicit decision. Old system-created links used IDs from a different `aria_controls` table, so they are quarantined as `legacy_control` candidates and cannot be accepted through the canonical picker without a verified crosswalk. Focused SQLite, disposable PostgreSQL migration and DPIA browser checks passed.

## Existing approaches reviewed before implementation

| Project or guide | Licence and maintenance | Fit and decision |
| --- | --- | --- |
| [Haystack](https://github.com/deepset-ai/haystack) | Apache-2.0; active repository and releases | Its component retrieval pattern is useful, but adding a provider-connected pipeline would duplicate ThemisIQ's scoped index and widen its data egress. Pattern only; no package or code copied. |
| [LangChain retriever interface](https://github.com/langchain-ai/langchain/blob/master/libs/core/langchain_core/retrievers.py) | MIT; actively developed | Its retriever boundary is useful as an interface idea, but a new dependency adds a broad supply chain for a narrow local query. Pattern only; no package or code copied. |
| [OWASP CSP guidance](https://cheatsheetseries.owasp.org/cheatsheets/Content_Security_Policy_Cheat_Sheet.html) | Public guidance | Report-only observation before enforcement and removal of inline handlers align with the current migration. No library is required. |

For the reviewed repositories, no runtime package was added. This avoids install hooks, credential or environment reads, unexpected provider calls, telemetry and licence obligations from new code. The implementation reuses current module scope, Vault text index and report snapshot services. The source reviews are design inputs, not a security certification of upstream code.

## Delivery contract and state

| Work | Current branch state | Release gate |
| --- | --- | --- |
| GRID assignment overlap | An active-control reservation and unique index serialize competing open assignments, with cancellation/closure releasing it. Existing duplicate open rows halt migration for repair rather than choosing a winner. | Focused SQLite and disposable PostgreSQL collision/migration tests; inspect historical duplicates before deployment. |
| GRID audit reuse | Operational report names only active reuse decisions whose source audits and controls remain in the viewer's scope. | Unit and browser checks for source provenance, hidden-source exclusion and CSV/PDF output. |
| Needs attention | Command Centre shows a scoped open count with measured/partial/not measured state. New saved reports freeze this state; an independent approver acknowledges open/partial issues. | Validate partial-source behavior and sign-off across roles; never interpret a zero from a partial scan as assurance. |
| Themis cross-record retrieval | The selected record and one-hop confirmed links are authorized again; only current Vault versions, accepted linked proof, scoped files and exact matching index hashes can supply local excerpts. Replies cite source, version, hash and text offsets, or abstain. | Wrong-tenant/unit, stale-hash, unreviewed-proof, superseded-version, prompt-injection and browser checks. |
| Provider-assisted drafting | Deferred until a separate privacy, data-minimization, citation and model-output review; current retrieval remains local. | Approved per-organization data policy and an evaluation set before any provider route is wired. |
| Global CSP | AI Governance and Reports already enforce strict scripts. Legacy pages still have inline handlers and blocks; a restrictive report-only header observes them without breaking those pages. | Replace all legacy executable inline code and dynamic handlers, test each module in browser, then remove enforced `script-src 'unsafe-inline'`. |

The latest static scan found 43 HTML files with common inline event attributes and 44 HTML files with script blocks. These are approximate search counts, not parsed executable counts. They demonstrate why a global CSP switch is not yet safe. Inline styles are a separate migration decision. Report-only policy intentionally has no collection endpoint so page URLs and private record paths are not sent to a new service.

## Security invariants

- Client page paths are hints. Owning module scope and Vault scope are rechecked server-side for every requested record and excerpt. Wrong-unit and nonexistent IDs receive the same unavailable answer.
- A title, description, index hit or AI output never grants access or establishes that a control is effective. The quote is an exact slice of indexed bytes; a hash/version mismatch abstains.
- Report snapshots and independent decisions stay immutable and auditable. The reader's current access is checked again when a saved run is opened.
- No provider receives evidence text in this slice. If provider drafting is enabled later, treat document text as untrusted data and require source-bound citations and explicit human review.

## Remaining release checks

1. Run focused backend tests and the targeted report UI flow; record exact counts and failures.
2. Run the disposable PostgreSQL lane with real concurrent assignments and migration fixtures. The release must stop if historical open assignments collide.
3. Run browser smoke for Command Centre, GRID audit report, Themis citations and report sign-off, followed by the relevant CI lane.
4. Continue CSP by module. Maintain a count of remaining inline handlers and script blocks in each PR; enforce only when representative workflows for every role and module pass under the strict policy.

## Local validation, 2026-11-05

Later in the same worktree, two focused browser tests passed (Command Centre partial count and DPIA review). Disposable PostgreSQL tests passed for the tenant DPIA quarantine, fail-closed required migration, GRID assignment scope and audit reuse. Focused SQLite tests passed for report retention hold racing the purge scan, report sign-off refusing unmeasured assurance, AIIA approval-history preservation, BCM activation, and Themis retrieval beyond the first 250 IDs. These checks do not constitute full CI or a production migration. The detailed residual build and operational gates are in [current build status](CURRENT-BUILD-STATUS-2026-11-05.md).

- Focused GRID assignment, Needs attention, Themis retrieval, CSP and report acknowledgement checks passed together (21 tests). A separate GRID audit report plus report/attention batch passed (9 tests). Python compilation, Node syntax checks and `git diff --check` passed.
- The browser harness was attempted. A sandboxed run could not bind its disposable loopback port. A permitted retry started from the repository parent and could not find `login.html` because this harness resolves templates relative to `oneforall`; it did not exercise the card. It must be rerun with `oneforall` as the working directory when the local socket permission is available.
- The disposable PostgreSQL environment is not configured in this worktree (`TEST_DATABASE_URL` unset). An existing Docker test container was seen, but the subsequent port diagnostic was rejected because automatic approval review hit its usage limit. The new PostgreSQL uniqueness assertion has been added to the test source but has not been executed. Do not claim a PostgreSQL pass.
- Existing route tests that call `asyncio.run` stall in this Windows environment during report generation; the new frozen-snapshot and sign-off checks use the synchronous service path and an I/O-free coroutine driver. The broader report-route lane remains a release gate.

### Continuation evidence

- A confirmed document-register XLSX now enters the scoped Vault with the reviewed hash and each claim exposes its source artifact. Preview bytes expire after seven days, identical current bytes reuse one artifact within one tenant and unit, and the Vault refuses permanent deletion while claims reference the workbook. Six focused SQLite checks and a disposable PostgreSQL two-tenant check passed. Customer-specific retention and legal holds for the workbook remain open; the file is an unverified source, not an approved policy.

### Platform AI evaluation dependency review (2026-11-06)

Before adding an execution dependency, inspected the upstream repositories and manifests:

| Project | Licence and maintenance evidence | Fit and supply-chain/privacy decision |
| --- | --- | --- |
| [Promptfoo](https://github.com/promptfoo/promptfoo) | MIT `LICENSE`; a commit was visible on 2026-11-06. | Strong test-case/provider design, but its Node build and publish scripts, provider integrations and analytics surface are excessive for an embedded Python service. Do not install it in the web process. |
| [DeepEval](https://github.com/confident-ai/deepeval) | `pyproject.toml` declares Apache-2.0; a commit was visible on 2026-11-05. | Python fit, but a wide dependency graph includes OpenAI, PostHog, telemetry and pytest plugins. Installing it would broaden outbound/data exposure and the test process. Do not install by default. |
| [Ragas](https://github.com/vibrantlabsai/ragas) | Apache-2.0 `LICENSE`; the most recent commit returned by the repository search was 2026-02-24. | Useful RAG metric concepts, but the default manifest includes datasets, LangChain, OpenAI and optional integrations. Too broad for synthetic in-app checks; do not install by default. |

The preferred build is a small, versioned **synthetic fixture runner** using existing ThemisIQ service calls. It must keep fixtures free of tenant content, record exact feature/build/test-set versions, compare expected refusal/citation/scope outcomes deterministically, and mark an unavailable provider as *not measured*. A provider-backed case may run only after the organization's AI policy approves the provider and data categories. The runner must not make a case pass by model grading its own answer, or call a synthetic check a real customer-system evaluation. **First part built in this worktree:** Ask ARIA's exact-citation verifier is exercised with five synthetic cases, no provider or tenant access, with public operator-only history and independent review. The run records a source-code hash of the answer path, verifier and fixture definitions rather than a deploy SHA; changing the answer path makes an old run stale, but the fixtures still do not execute or grade that path. `ai_evaluation_runs` remains the separate customer-application evidence table; customer-system execution and other first-party feature sets are still open.
- BCM plan activation now pages confirmed relationships and linked impact analyses rather than silently stopping at 200. A regression with 201 direct controls plus one control reached through the 201st impact analysis passed. The relationship and BCM service lane passed 71 tests with the Windows-hanging route integration test excluded; that route lane remains unverified.
- A disposable PostgreSQL concurrency check passed for a report hold set after the purge scan. Browser checks passed for report sign-off and Themis citation rendering; a 5,000-item local retrieval check passed. These focused results supersede the older “not executed” notes above, but do not establish a full-stage or CI pass.
- Relationship traversal now uses stable ID cursors for BCM activation and AIIA suggestions. Eight focused AIIA/BCM tests passed, including a hidden first page. The broader 3,520-test Windows backend run stopped on a pre-existing `asyncio.run` route-test hang after about 100 tests; it was interrupted and must not be recorded as passed.
- Authentication pages now enforce strict script policy after the password-change meter and MFA setup actions moved to static files. The focused policy tests, Node syntax checks and two real-browser checks passed. Login, the strength hint and inert MFA actions were exercised; MFA enrollment and code verification still need an isolated configured-key run.
- A combined 47-case backend regression exposed five local-midnight fixture failures. GRID assignment and Needs attention test helpers now use the same UTC date source as the application. The 17 affected cases and all 47 cases passed on rerun. No production clock rule was changed.
- Profile email preferences now run from a static script under enforced strict CSP. Four browser preference flows and one unscoped-platform-administrator browser check passed. The latter found and repaired a Command Centre attention card offered without an organization even though the API correctly returned 403. This does not complete the other legacy module script migrations.
- The local policy extraction worker now refuses JSON above the parent's 1.5 MB response limit before writing to its stdout pipe, so an oversized extraction cannot first accumulate in the web process. A focused regression checks that it emits no bytes on that path. A dedicated low-privilege worker identity and network isolation remain open deployment architecture work.
- Administrator MFA settings, Metrics and Diagnostics now run under strict script policy from static scripts. Four browser flows passed, including a disconnected MFA save and a generated Diagnostics link with quotes and an untrusted status string. This is another CSP slice; global enforcement is still blocked by legacy inline code.

### Isolated document extraction design, 2026-11-06

Before coding, reviewed three maintained open-source sandbox approaches:

| Project | License, operation and fit | Supply chain and privacy conclusion |
| --- | --- | --- |
| [Bubblewrap](https://github.com/containers/bubblewrap) | LGPL-2.0-or-later; unprivileged mount, PID and network namespaces. Active releases. Small runtime, but Ubuntu user namespace policy may prevent it and same host UID still sees app-readable files. | No project code or install scripts imported. It would add an OS dependency and a user-namespace assumption to this release. |
| [Firejail](https://github.com/netblue30/firejail) | GPL-2.0; namespace and seccomp wrapper, actively maintained. Its setuid design adds a privilege-bearing program to the web host. | Rejected for this narrow parser boundary; no third-party package or telemetry added. |
| [gVisor](https://github.com/google/gvisor) | Apache-2.0; OCI runtime with a userspace kernel, actively maintained. Stronger isolation at substantially greater operational complexity for a single on-demand parser. | Deferred as disproportionate; no container image or external network call added. |

Selected the host's existing systemd service and socket facilities instead, using the documented `Accept=yes` inetd-style per-connection service. `oneforall/modules/aria/policy_extract_protocol.py` sends document bytes, never a private file path. A dedicated dynamic UID with `PrivateNetwork=yes`, `IPAddressDeny=any`, `ProtectSystem=strict`, `ProtectHome=yes`, no application environment and a 45-second runtime limit parses one request. Production returns 503 when the worker is unavailable; it cannot silently use the same-UID fallback. [Deployment order and host checks](../oneforall/docs/policy-extract-service.md) are an operational gate. Focused protocol, intake and deploy tests passed locally (Windows skips its UNIX-socket roundtrip); the unit syntax was inspected with `systemd-analyze verify` in WSL, which could not resolve the production `/project` executable. A real installed-service and network-denial exercise remains required before release.
