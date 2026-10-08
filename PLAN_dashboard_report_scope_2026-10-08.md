# Dashboard and report business-unit scope

## Scope

Close wrong-unit title, count, ID, and saved-result signals in the Command Centre, launcher reporting engine, related links, analytics snapshots, and unified risk register.

## Findings and change log

1. Removed duplicate legacy `/api/links` handlers. The validated Related Items POST is now the only handler; link deletion also rechecks current visibility.
2. Added shared, explicit table-to-entity scopes for Command Centre and report queries. Restricted dashboards use visible rows; super administrators retain the organization-wide view.
3. Limited report definitions to their owner, validated report types, and bound report runs to the viewer's access fingerprint. Restricted runs do not persist result JSON and are recalculated when opened.
4. Restricted organization-wide predictive advisories and analytics snapshots to super administrators until scoped historical storage exists.
5. Scoped the unified risk register to visible ERM risks for restricted users. Legacy platform risk rows have no reliable business-unit field and are hidden from those users in the list, statistics, detail, and topbar search.
6. Corrected TEXT review-date comparisons for PostgreSQL in Command Centre queries.

## Verification

- Disposable SQLite wrong-unit suite: `tests/test_entity_scope.py` passed.
- Broader backend suite excluding UI and real-PG files passed from `oneforall/`.
- Browser suites: Command Centre layout, analytics charts, and dashboard migration passed when run from `oneforall/`.
- Disposable PostgreSQL: the new dashboard and report scope case passed against `themisiq_test_scope_metrics`.
- Python compilation and `git diff --check` passed.

## Follow-up

Add trustworthy business-unit ownership to legacy platform risks and SLA/workflow records, then restore their restricted-user cards and saved trends. Organization-wide API keys are a separate access model and need a separate review before BU claims are made for API v1.
