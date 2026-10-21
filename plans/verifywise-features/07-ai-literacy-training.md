# 07 · AI literacy and role-based training

**Inspiration:** VerifyWise [training tracking](https://verifywise.ai/user-guide/training/training-tracking). **Priority:** after inventory; can pilot in parallel with approvals. **Size:** M.

## Existing ThemisIQ anchor

BCM has `bcm_training_modules` and `bcm_training_attestations`, including score, signature, renewal, and expiry. Sentinel has `sentinel_training` records for privacy education. These represent different concepts and should be reconciled before creating an organization-wide AI training experience. Keep existing history intact.

## User journey

An administrator defines an AI literacy course and the roles or AI uses it applies to. A staff member sees one clear assignment in My Work, completes the learning and a short knowledge check or acknowledgment, then sees when renewal is due. A governance reviewer sees coverage by role, business unit, and AI use, with denominators and overdue records. Training evidence can support an AI use's review without automatically approving it.

## Build slices

- **A (domain reconciliation):** distinguish course content, session delivery, individual completion/attestation, assignment, and requirement. Determine whether BCM module/attestation data can become a common training service while preserving BCM ownership; map Sentinel records as history, not fictitious individual completions. Plan a migration only after reviewing real data shapes.
- **B (AI course pilot):** add role/BU/AI-use targeting, assignments, quiz or acknowledgment, due/renewal rules, reminders, and completion evidence. Use existing users and My Work; make “not assigned”, “in progress”, “completed”, “expired”, and “not evidenced” distinct. Limit training content edits to appropriate roles.
- **C (reporting):** show current coverage and exceptions with filterable, permission-aware drill-down. Link completed records to the AI-use workspace and reviewed audit packs; export only the audience and fields the recipient is allowed to see.

## Acceptance gates

- The same person's completion is counted once for the relevant course version; course revision and renewal retain prior attestations and their dates.
- A manager can distinguish aggregate course scheduling from an individual's verified completion, and a learner can understand the next action without administrator help.
- Org/BU restrictions apply to assignments, training results, exports, and reminders; training status does not change approval or compliance status on its own.

**Out of scope for first slice:** a full learning-management system, surveillance ranking of individuals, and auto-generated certifications.
