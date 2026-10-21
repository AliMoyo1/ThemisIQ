# G7 release startup repair

## Finding

The 2026-10-13 production restart at `dfaa357` failed while seeding users. After database initialization, the startup count queried `public.users` without an RLS context, saw zero rows, and attempted to insert bootstrap users. PostgreSQL rejected the insert under the users RLS policy. The previous application commit is healthy after rollback.

## Change log

- Use the existing privileged database connection only for startup's global user existence check and default organization bootstrap.
- Use the same connection in the explicit first-run seed script, so an actually empty PostgreSQL database can bootstrap.
- Keep ordinary request connections scoped and close privileged connections after each bootstrap operation.

## Release gate

- Review the diff for any broader RLS bypass.
- Obtain normal CI results before another production restart.
- Recheck production health and readiness after deploy, then pilot the AI Governance rollout deliberately.
