# 102V12 material proposal persistence and explicit adoption

This stage follows `999df63aa18c9e5b3b8e9ef36274ac2dc56cf66c`. It supplies the synchronous proposal repository, dedicated request finalization and optional origin on the existing explicit material save. Runtime, proposal HTTP routes and shared execution capacity are subsequent work. The new `TEACHER_WORK_PRIVATE_MATERIAL_PROPOSALS_ENABLED` flag defaults to false; production live gates remain closed.

## Official persistence boundary

`PrivateProposalRepository` uses existing account/owner lease/draft/task locks and a separate outline-run decoder/CAS cache. Existing chat-only run guards and chat finalizer types are unchanged. The exact core v3 schema and independent proposal extension are required. Official input/result/lineage paths only INSERT deterministic, strictly decoded records; database administrators remain outside this append-only guarantee.

Input records freeze the original server context, full command and typed provider context. The original owner namespace and working revision stay outside the provider prompt. Admission selects an owned persisted assistant reply with a uniquely classified completed chat run at the current input revision. Exact-key replay compares every command field before new freshness/material restrictions; changed bodies conflict. Discovery is read-only and bounded to 20 retained runs, and refuses corrupt or overflowing states.

Reservation persists one attempt/call/token before dispatch. Completion writes an exact result and releases the matching lease in the same transaction. Positive publication rechecks identity, source/input/message and deadline during final owner revalidation after flush. Charged cancellation/expiry retains the active token and lease until caller settlement. Historical completed reads remain readable after the deadline and report current adoption freshness separately.

The repository returns detached candidates. `finish_proposal_outcome(value, mode=...)` finalizes the original physical request root; candidates alone are never proof of commit. A narrow proposal binding adapter preserves controlled repository errors during final held checks without widening the shared request owner or chat error family.

## Material save compatibility

`PrivateMaterialSaveRequest` adds only optional `origin_proposal_run_id`. Omission and null remove only that new top-level field from the request digest, preserving historical manual receipts. A new provided origin must resolve to an owned, completed, fresh proposal on this task. Teacher edits are permitted. The existing manual snapshot retains `skill_versions=[]`; exact provenance is stored in a separate immutable lineage record atomically with snapshot/draft/task/receipt.

Exact save replay resolves the original receipt before current input/source freshness checks and verifies historical lineage, without duplicates. A new key using a consumed or stale origin rejects. Later manual edits omit the consumed origin; an exact network replay retains its original body and key. Manual saves without an origin do not load or require the proposal extension.

`prepare_manual_save` is the actual serializer used by real saves and completion's dry preparation. It preserves opaque draft extras, requirements and existing bounded receipts. Lesson enters the original draft; slides live in the immutable outline. Preview reserves a legal 128-codepoint/512-byte receipt key, fixed-width UUID/digest and a six-fractional-digit UTC timestamp. Origin is separate lineage, so no invented draft metadata is counted. The original 65,535-byte TEXT cap and receipt limits stay unchanged. An oversized intended save rejects completion with `PROPOSAL_DRAFT_TOO_LARGE`; nothing is truncated or automatically saved.

## Reproducible verification

From `backend`, using the prepared dependencies and pinned official MySQL 8.4.10 image:

```sh
PYTHONPATH=.:tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q tests/test_teacher_work_*.py
PYTHONPATH=.:tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s tests/native_teacher_work_proposal_repository.py tests/native_teacher_work_proposal_origins.py tests/native_teacher_work_private_materials.py::test_original_draft_text_limit_is_controlled_before_mysql_write tests/native_teacher_work_private_materials.py::test_http_original_draft_exact_capacity_and_one_byte_over
```

Native files require explicit selection. The fixture creates only its own network-disabled disposable MySQL container and synthetic schemas, uses a Unix socket and real SQLAlchemy/PyMySQL/ORM/current signed identity, and tears down its exact container and volumes. Chat source records are created through official admit/reserve/complete methods; no provider is called in repository tests. No app.main, browser/mobile, production database, real student data or live AI is involved.

Implementation verification: 262 ordinary cases passed. Native 33 cases passed: 29 repository, two missing/foreign origin refusals, and two unchanged real SQL/HTTP TEXT boundary cases. Covered actual DBAPI unknown commit before/after acknowledgement for admission/reservation/completion/save, unique/CAS and rollback boundaries, stale readable results, edited save/approval/historical replay, final after-flush deadline rejection, retained run limits and read/config separation. Every owned server cleanup recorded normal exit, container/volume removal and preserved baseline.

An unknown acknowledgement is always reported as `COMMIT_OUTCOME_UNKNOWN`. Independent new connections distinguish pre-commit absence from post-commit durable facts. No unknown write authorizes redispatch or a fabricated receipt. Runtime settlement and HTTP provider dispatch still require the subsequent stage.

Independent specification and code-quality review passed with no blockers. The reviewer inspected raw fault/cleanup evidence and verified all 14 source/test/contract manifest hashes; it did not rerun tests. The controller additionally reran all 262 ordinary cases (17.17s) and the complete combined 33-case native command above (236.58s). Its three owned servers, `/tmp/gezhi-tw-native-mhr1s0c0`, `/tmp/gezhi-tw-native-y16l23kz` and `/tmp/gezhi-tw-native-d_uiaiu6`, all stopped with exit 0, were removed with volumes and preserved baseline service state. Evidence and review are recorded under `/tmp/gezhi-proposals-sdd/task-2-*` and `stage-2-*`; stage publication packages them separately. All five existing chat/material/export HTTP JSON fixtures retain their exact hashes. Unit AST helpers add only the two named proposal operations while retaining every old entry and exact equality. The frozen chat helper's historical byte hash is retained after removing exactly one required, explicitly authorized new dictionary line; its behavioral bytes and AST remain pinned.

CI remains unverified. No denied CI query was retried or routed through another tool.
