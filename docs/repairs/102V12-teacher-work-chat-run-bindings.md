# Teacher Work closed chat run-model binding repair

Date: 2026-10-05 UTC
Stage: source binding repair; production admission remains closed

## Change

The request-local bootstrap omitted the optional run-model binding when calling
`build_sql_repository`, leaving `repository.run_rows` unset. Any future chat
operation using that binding would return `RUN_PERSISTENCE_UNAVAILABLE`.

The existing lazy constructor now supplies
`run_models=SqlRunModels(WorkRun, WorkMessage)`. Task-only factory callers keep
their optional behavior. No adapter, transaction, route, provider or gate changes
are included.

## Verification

- The new exact-import/argument AST regression first failed at the missing
  `run_models` binding, then all five wiring/source checks passed
- The unchanged reviewed SQL5 manifest
  `3fc69441609ecc32cfed7757a5a2b42df3e4f96407b11fb1e11942921a4236cf`
  passed all five recording-port tests with zero guard denials, including actual
  factory binding with and without run models
- That frozen SQL run matches the current adapter, Work model and SQL test
  bytes; its coordinator and persistence sources are older frozen versions
- `git diff --check` passed

Both public bootstrap factories still unconditionally refuse admission before
real identity/database work. The router still exposes only unavailable
capabilities. These checks do not establish runtime bootstrap importability,
live HTTP/chat functionality, physical MySQL behavior or production readiness.
No application startup, real SQLAlchemy Session/engine/connection, DBAPI,
database, provider, browser or service was executed.
