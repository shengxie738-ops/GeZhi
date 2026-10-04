# Desktop teaching context and test-contract repair

## Scope

- Add read-only teaching context and finite navigation coordination, with current identity/context generations and explicit cancellation
- Prevent superseded requests or confirmations from replacing newer selections, data, errors, or confirmed navigation
- Validate embedded enrollment actor/offering lineage before retention; clear selected context and catalog projections on a current authoritative own-enrollment denial
- Keep transient network failure distinct from authority loss and prevent stale denials from clearing a newer selection
- Record the project's desktop-only design and QA scope in AGENTS.md
- Repair two backend tests: inspect actual configuration declarations instead of an unpublished stage manifest, and validate the current B2 missing-schema capability contract

## Verification

Frontend tests-first regressions reached 13 ordering/lineage assertion failures, followed by two current-enrollment-denial failures. The final frozen candidate passed six separately selected guarded scopes: context 36, teaching navigation 21, legacy navigation 2, authentication transition 3, B1 API contract 27, and capabilities 8. Independent source and evidence review found no remaining blocking issue within this scope.

The two backend test changes were exercised in an isolated Cloud environment: 146 selected synthetic cases passed, including 33 cases in the affected files. These counts overlap and must not be added. Independent static review verified the exact patch against the configuration, fixture, and B2 capability implementation; the tests were not independently rerun in the publication workspace.

## Limits

This is not a full-suite or production-readiness claim. Another unrelated analytics test still depends on the absent stage manifest. Malformed duplicate-page/repeated-cursor response hardening remains a nonblocking follow-up.

The new teaching context/navigation modules are not yet wired into the desktop workbench shell; their hook tests do not certify rendered user journeys. Earlier desktop browser checks covered the previously published application only.

Real MySQL business migrations and the required native lock/transaction acceptance scenarios remain unverified. Backend write safety remains closed with `503 write_safety_unproven`, and frontend mutation availability remains false. No production activation, main merge, or deployment is included.
