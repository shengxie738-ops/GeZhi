# Gitea adapter and attribution repair plan

Scope: adapter availability/provenance, commit and PR diff envelopes, verified webhook configuration, collaborator truthfulness, author-first identity matching. Source-only; no real credentials, provider calls, database baselines, or account access changes.

1. Add failing isolated regressions with network denial and in-memory SQLite.
2. Replace mock production success with unavailable outcomes; ensure callers can distinguish remote evidence.
3. Provision hooks through documented config map, always write current secret and required active/events, then read back public configuration. Never infer success from URL or 422 alone. Secret verification means acknowledged write plus readback, not observed signed delivery.
4. Return bounded structured diffs; official PR endpoint `/repos/{owner}/{repo}/pulls/{index}.diff`.
5. Resolve actual author confirmed binding/canonical username before actor; reject ambiguous names and unmatched metadata.
6. Run targeted regression suites; report incompatible historical mock tests and migration semantics.

References: https://docs.gitea.com/api/operations/repo-edit-hook/ ; https://docs.gitea.com/api/operations/repo-download-pull-diff-or-patch/ ; https://docs.gitea.com/usage/repository/webhooks

## Implemented contracts

- Repository creation/get and mutations raise `GiteaUnavailableError` when provider configuration is absent. No production mock repository/token/user provisioning. Repository responses require remote numeric ID/owner/name and carry `source=gitea`, `status=available`, `giteaRepositoryId`. Conflicts never adopt an unrelated repository.
- `get_repository_permission(owner, repo, username)` checks the explicitly named actor, validates returned login, and returns read/write/admin/owner/none. Source: https://docs.gitea.com/api/operations/repo-get-repo-permissions/
- Hook configuration returns `configured=false` on absence/errors/invalid readback. Existing URL matches are rewritten with current secret, active/events/content type and wildcard branch filter; 422 requires a discoverable duplicate then the same repair/readback. `secretVerification=write_acknowledged`, `deliveryVerified=false` explicitly distinguish configuration from observed signed delivery. Secret config map support is the existing Gitea API contract; server version compatibility and an actual signed delivery still require deployment acceptance.
- Diff envelopes: status/content/source/truncated/limits/reason. No error text can become a diff. Streaming downloads and returned characters are bounded, empty/invalid/404/error explicit. PR requests accept expected_head_sha, expected_head_ref, expected_base_sha, expected_base_ref. They check expected event context before fetching and all revision fields after fetching; drift/retarget is unavailable.
- Confirmed author bindings require synced status, remote ID, and an existing campus account. Commit metadata always precedes actor identity. Explicit empty author never falls back to pusher. Conflicting bindings are ambiguous. Display names, email local parts, and cross-namespace username coincidence never manufacture attribution. Actor-only matching requires omitting commit_author. Both source and matchSource are emitted for compatibility.
- Account provisioning reports pending/unavailable/failed/synced truthfully. Legacy mock bindings are not promoted merely because they contain an ID; next synchronization verifies a real provider user. Collaborator failures never become mock/synced.

## Migration and validation

No SQL schema migration. Existing persisted mock/ready artifacts are not retroactively verified. Re-run explicitly authorized repository binding/setup and account synchronization after deployment; saved UI must retain unverified state until remote checks succeed. Unbound legacy email-only authors become unmatched, which is intentional. Pure repository_urls remains usable for display without asserting remote existence.

Targeted offline tests: 38 passed (21 new regressions, 15 account tests, 2 account API tests), 2026-10-02. Existing six mock/legacy assumptions were updated; regressions were observed failing before implementation. One existing Pydantic settings deprecation warning remains. `git diff --check` passed. Aggregate tests use an isolated synthetic database and exclude destructive or external-service operations. No live Gitea, external credentials, real LLM, account persistent access, or business database used.

## Final hardening: default webhook secret rejection

Added shared `is_gitea_webhook_secret_configured(secret)` and applied it before hook provisioning/network access. It rejects blank values, shipped config/example placeholders (`gezhi_webhook_secret_default`, `replace_with_a_strong_webhook_secret`) and exact common development markers (`changeme`, `change-me`, `secret`, `replace-me`), ignoring case and surrounding whitespace. Signature verification imports the same helper through the permissions repair. It does not claim to measure entropy; operators must supply a dedicated random secret. No actual configured keys were inspected or logged. New test observed red before implementation; final adapter/account/API subset **39 passed** with existing deprecation warning only; diff check clean.
