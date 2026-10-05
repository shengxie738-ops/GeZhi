# Teacher Work T3a authorization and request workflow

Date: 2026-10-04 UTC
Stage: pure production-helper verification; feature and integration gates remain closed

## Included

- Exact signed-subject/current-account checks: invalid identity401 and current-student403, without trusting an old teacher role claim
- Immutable namespace observation and receipt decisions: reads cannot create a namespace; a first write may propose one server UUID under an already-held authority footprint
- Exact task owner/namespace/scope authorization: private tasks need no teaching access; offering-bound tasks require readable teaching authority for the exact READ_OFFERING scope
- A single-use caller-owned request workflow: flush, verify bindings and namespace, obtain coherent current policy and a fresh server time, evaluate the same retained footprint, confirm commit, then return the candidate
- Controlled failed/uncertain outcomes: cleanup attempts never establish physical rollback, and an uncertain commit never becomes success or triggers automatic replay
- Legacy save preparation using the existing owner-mutex/original-draft/Task primitives and save guard, preserving original draft ID, created_at, raw content and envelope extras

The final pre-commit workflow preserves the exact typed repository409 outcome and its fresh-reconciliation requirement after cleanup. Unknown errors remain sanitized503. Linked legacy no-revision saves refuse409; unknown or incompatible registry observations refuse mutation. Only confirmed physical registry absence may delegate the original save path.

## Verification

53 unique finite pure source/contract cases passed: nine new authorization/request-workflow/legacy cases and the retained 44 coordinator/legacy/contract cases. The controlled-conflict regression was observed failing before the minimal typed-error fix, then passed with the earlier checks retained.

The tests invoke production helpers with supplied immutable facts, queued row observations and recording transports. They establish decision and call-order evidence. They use no actual identity, teaching, HTTP service, SQL adapter, Session, database or native commit/rollback operation.

## Still pending and closed

T3b must provide actual current identity, immutable namespace resolution, retained read-only teaching authority/policy, a dedicated request transaction owner, real registry observations, HTTP/projection/pagination and legacy endpoint/service wiring. The existing legacy service and editor retain their previous behavior.

Account-incarnation/username-reuse safety, physical schema/namespace durability, MySQL locks/isolation/concurrency, post-wait authority and real commit uncertainty remain release blockers. These pure receipts do not certify those gates. Teacher Work activation, execution/providers, course writes and classroom publishing remain closed. This is a bounded T3a source slice, not full Task3 completion.
