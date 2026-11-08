# Two-step sign-in journeys, AI feature checks and workbook retention, 2026-11-08

Branch `claude/mfa-ai-checks-workbook-retention`, from `master` 65065500 (PR 46 merge). The owner asked in chat on 2026-11-08 to build items 1, 2 and 3 of the "what's next" list from the [build status ledger](CURRENT-BUILD-STATUS-2026-11-05.md). This is chat confirmation, not sign-off.

## 1. Two-step sign-in, end to end in a browser

**Why:** the ledger recorded that real MFA verification and enrollment had never been exercised in a browser; only the setup page loading was.

**Research:** none needed; this tests code already in the repo (`pyotp` TOTP, Fernet-encrypted secrets, bcrypt backup codes).

**Built:**
- `tests/ui/test_mfa_journeys_ui.py`, two journeys with a fresh user each and a throwaway encryption key:
  - voluntary: enroll (a wrong code is refused first), secret stored encrypted, sign-in stops at the code page, the enrollment code cannot be replayed, a later code works, a backup code works once only, turning MFA off needs the password;
  - organization requires MFA: a new person is held on setup, enrolls, then reaches the app; turning it off is refused; the next sign-in asks for a code.
- `tests/test_mfa_pending_session.py`: backend checks of the two fixes below.

**Bug found and fixed:** enrollment forced by the organization's policy failed every time. While the session was pending, the page shell's background `/api/notifications` call was redirected to `/mfa/verify`, which rendered a page and issued a new CSRF cookie, so the setup form's token no longer matched and the code was refused.
- `core/middleware.py`: a pending session now gets a plain 401 JSON answer on `/api/` paths instead of a redirect (pages still go to `/mfa/verify`).
- `modules/launcher/routes_auth.py`: `/mfa/verify` sends a pending person who has no authenticator yet to `/mfa/setup`, where they can enroll, instead of a code page where no code can match.

## 2. Synthetic checks for every built-in AI feature

**Why:** only Ask ARIA had a provider-free check. The CSP finish plan asked for a small runner that checks refusal, scope and citation outcomes deterministically and marks model output as not measured.

**Research:** done in `plans/2026-11-assurance-and-csp-finish.md` (DeepEval and Ragas rejected: wide dependency graphs with telemetry and provider clients). The runner stays in-house.

**Built:**
- `modules/ai_governance/platform_evaluations.py`: a registry of fixture sets. New set `ai-policy.refusal` applies to every feature in `core/ai_policy.FEATURES`. With synthetic stored policies and no database, it checks the decision `core/ai_policy.authorize` makes once it has read a policy:
  - allowed when provider, feature and data kinds are allowed (the control case);
  - refused when AI is off, when an enabled policy was never approved by a named manager, when the policy is unreadable, for a provider it does not name, when the feature is switched off, and for each kind of data the feature declares when that kind is not allowed;
  - the feature declares its data kinds and has a written declaration.
  The run records a hash of the policy code, the cases and the feature's declaration, so changing any of them marks old runs stale. Model output is recorded as not measured.
- Ask ARIA keeps its citation identity set; the operator chooses which set to run.
- Route accepts an optional `test_set`; the operator page shows "Synthetic checks" on every feature with one run button per set.

**Limits:** these checks prove the policy gate, not what a model answers. The "no saved policy" refusal happens in the database read and stays covered by `tests/test_ai_policy.py`. The call-site guard (`tests/test_ai_call_guard.py`) still proves every call passes through the gate.

## 3. Retention and legal holds for document register source workbooks

**Why:** confirmed register workbooks are filed in the Vault and could not be deleted at all while claims point to them; they followed no customer retention choice or hold. The owner adopted "customers choose their own schedules".

**Decisions (chat confirmation, not sign-off):**
- No period until the customer chooses one: workbooks are kept. No legal period is assumed. Cost: storage grows until a customer chooses. Change: set a period on `/reports`.
- A chosen period applies to newly confirmed workbooks, as the saved-report period does. Existing workbooks get a date individually. Cost: older workbooks need a date set by hand. Change: a one-off backfill if a customer asks.
- When due, only the file is removed. The Vault record (archived), its SHA-256 hash and the register claims stay, so a claim still shows its source. Cost: the bytes are gone for good. Change: a hold keeps them.
- A legal hold always wins over a date; the purge locks the row so a hold set during the pass wins.
- The people who already own report retention (`platform.report.retention.manage`: org admin, compliance manager, GRC officer) manage workbook retention too. Change: a separate capability if a customer wants different owners.

**Built:**
- `modules/aria/register_source_retention.py`, table `register_source_retention` (in the tenant schema beside the register tables).
- Filing a confirmed workbook starts its retention record (`document_register_intake.confirm`).
- Daily pass in `advisory_scheduler._expire_document_register_previews`, per tenant, at most 100 files a pass.
- `GET/POST /api/registers/source-retention-policy` (Reports page form) and `POST /evidence/api/items/{id}/source-retention` (Vault drawer section with date, hold and a required reason). Both are audited.

## Evidence

| Check | Result |
| --- | --- |
| MFA browser journeys plus the existing setup page test | 4 passed |
| MFA, security, session, onboarding backend | 82 passed, plus 2 new pending-session tests |
| Platform evaluations, AI policy, declarations, call guard, CSP | 132 passed |
| Platform evaluations browser | 2 passed |
| Workbook retention plus register intake | 15 passed |
| Workbook retention browser | 1 passed |
| Evidence, reports, CSP, platform guide, security, onboarding groups | 294 passed |
| PostgreSQL lane `tests/test_postgres_init.py` (disposable PG container) | 100 passed (13 minutes), before the retention assertions were added |
| Extended PG register source test plus schema test | 2 passed: the retention row lives in the tenant schema under a non-bypass role, another tenant's pass touches nothing, the owning tenant's pass removes the file and keeps the hash |

## Change log

- 2026-11-08: branch created from master 65065500; items 1 to 3 built and tested as above.
- 2026-11-08: PostgreSQL register source test extended with retention in the tenant schema and cross-tenant purge isolation.
