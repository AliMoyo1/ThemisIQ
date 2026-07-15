# PLAN-T1.3: Control Effectiveness Engine

## Status: COMPLETE

## Goal
Auto-compute a 0-100 effectiveness score for every canonical control based on
7 binary factors. Score updates on audit completion, control status change,
ORM high/critical event, evidence expiry, and a nightly full recompute.

## Scoring factors (weights sum to 100)

| Factor | Weight | Pass condition |
|---|---|---|
| evidence_uploaded | 20 | At least 1 non-expired evidence_link where entity_type='canonical_control' |
| evidence_valid | 15 | No linked evidence expiring within 7 days |
| audit_passed | 20 | A grid_audit completed within the last 365 days covers this control (via canonical_control_id) |
| tested_recently | 15 | last_tested_at within test_frequency_days (default 90) |
| owner_reviewed | 10 | owner_user_id is set |
| automated | 10 | automation is not 'manual' and not NULL |
| no_recent_incidents | 10 | No high/critical orm_events in last 90 days linked via risk_controls |

## Files changed

1. `database.py` -- new `control_effectiveness_scores` table + `last_scored_at` column migration
2. `modules/governance/effectiveness.py` (NEW) -- scoring engine
3. `modules/governance/scheduler.py` (NEW) -- nightly 03:00 UTC recompute
4. `main.py` -- wire governance scheduler
5. `core/event_handlers.py` -- 3 new handlers
6. `modules/evidence/scheduler.py` -- recompute controls after expiry tasks
7. `modules/governance/data_service.py` -- LEFT JOIN score in list_canonical_controls
8. `modules/governance/routes.py` -- GET /api/controls/{cid}/effectiveness
9. `modules/governance/templates/index.html` -- Score column in controls table

## Change log

- [x] Add control_effectiveness_scores table to database.py
- [x] Add last_scored_at to _COLUMN_MIGRATIONS
- [x] Create modules/governance/effectiveness.py
- [x] Create modules/governance/scheduler.py
- [x] Wire governance scheduler in main.py
- [x] Add 3 event handlers in core/event_handlers.py
- [x] Update evidence/scheduler.py to recompute after expiry
- [x] Update list_canonical_controls to LEFT JOIN scores
- [x] Add GET /api/controls/{cid}/effectiveness endpoint + POST recompute
- [x] Add Score column to governance UI (red/amber/green/blue badge)
- [x] py_compile clean on all 8 touched files
- [x] 91/91 stable tests pass (pre-existing failures unchanged)
- [x] Commit
