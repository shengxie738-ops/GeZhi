# 102V12 checkpoint: Teaching courses, offerings and local roles

Implemented the B1 backend course and offering lifecycle, including source-owned course metadata, draft offering creation with an explicit owner role, activation, archival and restoration. Course-local role grants, interval updates, explicit account-role rebinding and revocation preserve stable relationship history without changing global account roles.

The standalone adapters use strict commands, current account and trusted-policy checks, immutable original receipts, one access event per accepted intent, and commit-before-success responses. Missing or invisible scopes return 404; a visible shell with insufficient permission returns 403. Same-course visibility is evaluated from read-only relationship snapshots at the final authorization time. A readiness-order correction preserves honest schema refusal without broadening collection SQL permissions.

Production teaching writes remain unavailable behind the unchanged write_safety_unproven gate. This is a source and synthetic-verification checkpoint, with no deployment, activation or real MySQL readiness claim. Independent adversarial replay verification remains unavailable; defensive replay protections have static review and ordinary regression coverage only.

Verified scopes, reported separately:
- Course and lifecycle: 29/29
- Course-local roles: 18/18
- Isolated ASGI and strict commands: 33/33
- Prior receipt, session and write-HTTP regressions: 36/36, 3/3 and 8/8
- Prior model, mocked migration, policy, authority and reader regressions: 12/12, 35/35, 22/22, 22/22 and 11/11

All listed scopes passed with zero errors or skips. Counts overlap and are not a combined coverage total. Real MySQL isolation, row locks, constraint contention and production rollout still require separate evidence. Aggregate application mounting and roster-preview/application implementation are outside this checkpoint.
