# Student Work: provider-preserving paper drawer

## Scope

This stage fixes a real frontend interaction defect. The installed plugin-detail
button previously cleared `selectedPluginDetail` before passing it to the search
drawer. Opening the drawer also submitted a hardcoded `DeepSeek` query, sometimes
against fallback installed providers rather than the user's chosen provider.

The new atomic detail action captures the selection first. The drawer resolves it
against the registered live-source catalog, rejects unavailable selections without
changing the current drawer, cancels superseded searches, clears stale state, and
opens idle. Only explicit user submission runs a query. Existing account and search
generation fences continue to reject late results.

## Verification (2026-10-05 UTC)

- Initial regression run: 20 cases, 6 passed and 14 failed on the old code
- Additional unavailable-selection run: 3 cases failed on the old return contract
- Final targeted run: 23 passed, 0 failed, 0 skipped
- Related academic/plugin/paper regression set: 117 passed, 0 failed, 0 skipped;
  this count includes the 23 targeted cases and is not additive
- Independent source review found no blocking issue

The tests compile the installed Vue detail-button markup and exercise the real
hook and all four search adapters with synthetic, URL-checked transport. They cover
arXiv, OpenAlex, Crossref and Europe PMC; idle opening; explicit/empty submission;
reopening during an outstanding search; account changes; and invalid selections.

The related regression command was:

```sh
node --test --test-concurrency=1 frontend/tests/{academicAggregate,academicBoundary,academicPlugins,academicProviders,academicRepair,paperSearchFlow,paperSearchOutcome,paperWorkflow,pluginMarket,paperDrawerSelection}.test.mjs
```

No browser, real-provider request, application server or database was started.
This stage does not establish live-provider availability or full-system readiness.
The new handler's exposure through `main.js` was reviewed directly; the hook tests
alone do not establish full application bootstrap. Teacher Work and Academic
Reviewer skill work are separate stages and are not included in this change.
