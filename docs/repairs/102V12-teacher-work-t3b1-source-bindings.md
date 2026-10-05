# Teacher Work T3b1 closed source bindings

Date: 2026-10-05 UTC
Stage: source/AST verification only; production admission remains closed

## Included

- Lazy, request-local bindings for the existing current identity, SQL coordinator, caller-owned storage and dedicated transaction owner
- Exact signed-subject/current-role checks and immutable namespace observations, retaining the first authorized footprint and namespace receipt
- A narrow public READ_OFFERING footprint export that delegates the existing ordered read helper with write=False
- Finalization through the existing T3a request owner, using the original caller root, retained authority, coherent policy and post-flush server time
- Structural registration of the approved /api/teacher/work/capabilities path

Both production open/build entrypoints unconditionally refuse503 before loading real bindings or starting identity/database work. The router exposes only unavailable capabilities with no-store responses. Unsupplied task, list, read and message routes remain absent; no setting or test fact opens admission.

## Verification

Four finite AST/source checks passed. They cover lazy/request-local/closed construction, the exact read-only delegate, unchanged legacy service/endpoint, and structural router registration. The route-prefix regression was observed failing before the one-constant correction, then passed with every prior assertion retained.

These checks only read and parse source. No production module, HTTP framework, identity/teaching adapter, Session, database, physical schema inspection or native transaction was executed. AST results do not establish runtime importability, authorization or usable HTTP behavior.

## Still pending and closed

The original legacy save/service/endpoint remain unchanged. Wiring them requires a real physical registry observer and safe request transaction admission; an unknown fallback must not break existing saves or bypass linkage checks.

Actual account-incarnation/username-reuse safety, namespace durability, current identity, retained teaching authority/policy, MySQL locks/isolation/concurrency, commit uncertainty, HTTP/projections/pagination and legacy integration remain unverified release gates. Teacher Work activation, execution/providers, course writes and classroom publishing remain closed. This is a partial Task3 source slice, not Task3 completion.
