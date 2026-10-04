# Teacher Work contract foundation

Date: 2026-10-05
Stage: Task 1 source foundation; not an enabled teacher Work feature.

## Included

- Strict teacher task, message, command, outline and artifact contracts
- Immutable version DTOs, UTC timestamps, bounded UTF-8 content and canonical digests
- Capability projection that remains closed when required facts are missing
- Dedicated declarative table definitions and supplied-observation schema checks
- Additive preparation/check description only; no SQL installer or startup DDL
- Disabled-by-default configuration and an empty private storage-root setting

## Verification

The same 21 finite contract cases were checked before and after the review fixes.
The corrected baseline had 18 passes and three intended assertion failures;
the final candidate had 21 passes, with no setup errors or access denials.
The three fixes cover Unicode C1 controls, MySQL message byte capacity and
malformed existing schema-ledger observations. An earlier environment-blocked
attempt is not counted as a clean test result.

These checks execute pure contracts and supplied-fact comparisons. Model
declarations are inspected as source; no real database, ORM session, DDL,
provider, browser or Office-file integration was exercised. The schema check
does not establish connection or transaction safety. Complete independent
model/physical-schema alignment remains a later integration check.

## Next

Task persistence, legacy-draft transaction participation, server authorization,
AI execution, file generation and the teacher UI remain subsequent stages.
No classroom publishing or existing course-write capability is enabled here.
