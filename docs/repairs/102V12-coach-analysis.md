# Coach analysis repair plan

Scope: pure, read-only computation in git_coach_service.py; authoritative workflow heuristics in git_workflow_rules.py. Durable execution/persistence and Gitea adapters are parallel work.

1. Add offline regressions for malformed JSON, missing/truncated diff provenance, commit isolation, real author match contract, PR refs, configured default branches, context identity and no snapshot writes; observe failures.
2. Separate computation from persistence. Consume structured evidence; model calls require real available evidence and explicit bounded client configuration. Keep deterministic violations authoritative and expose limited score meaning.
3. Normalize event/ref contracts; stable context keys; no unverified merge-message exemption; honest unmatched identity.
4. Run focused and broader offline tests; document contracts, exclusions and remaining live acceptance work. No real external calls, business DB, commits or pushes.

Completed: 56 focused tests pass under the existing offline runner. Model JSON/schema, canonical membership and evidence regressions verified; no whole-project writes remain. PR expected-head adapter contract integrated. Full-suite collection encountered three refused guarded MySQL connections and executed no tests; no rerun while parallel files change. Final aggregate results and deployment limits are recorded in 102V12-AI-Git-教练交付说明.txt.

Reviewer follow-ups corrected: direct no-autoflush snapshot read replaces legacy mutating loader; expected_repository_key fences rebind before inference; PR passes expected head/base ref and SHA context to adapter. All new regressions observed failing before fix.

Final identity guard uses canonical giteaRepositoryId (legacy only when absent), rejecting changed/missing/null ID before inference for accepted event repository IDs. Four red→green zero-provider-call regressions included. In-memory test tombstones isolated; 56 focused tests pass.
