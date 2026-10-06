# 102V12 lesson_outline@1 independent MySQL extension

Base: `d7f1a293ad5b1a434cf6914a13fedc370bf9bd8a`. This stage supplies pure proposal types/parser and one separately prepared MySQL table. Repository, runtime, HTTP generation and explicit adoption are subsequent stages; schema readiness does not authorize production generation. The core private/offering live gates stay closed.

The global DomainRecord has no exact receipt uniqueness and retains MySQL TEXT65535. A dedicated native JSON record table provides deterministic typed PK/unique/FK/CHECK facts without changing that existing table. Core teacher_work v3 remains13 tables/hash `7b3c31472a928e37bb31bb4ae96c75d6aa7674beeecfdc39ccc08e5ae943f65c`. The independent component teacher_work_material_proposals/version1/hash `e6c93af0bf516a51ba387476f43db6481154cbc5f1498a659efef44d7be07887` is completed only after physical verification.

## Preparation boundaries

Call `apply_teacher_work_proposals_mysql(connection, expected_identity, contract_hash=PROPOSAL_CONTRACT_HASH)` on a fresh dedicated MySQL connection after explicit core fresh-v2 and v3 preparation. `DatabaseIdentity` explicitly pins selected database/server UUID/datadir/socket. No automatic startup migration or create_all exists. Existing active transactions, disabled FK/unique checks, temporary shadows, wrong identity/hash, v2-only core, partial/unledgered/wrong existing proposal structures refuse. Fully completed exact replay is SELECT/SHOW-only. DDL cannot be rolled back; a retained unledgered table after failure is reported and refused, never silently resumed or dropped.

The added table teacher_work_material_proposal_records has PK(run_id,record_type,record_key), UNIQUE(outline_id), run/task/outline FKs and enforced typed record CHECKs. input/result use key=run_id and outline=NULL; lineage uses key=nonnull outline_id. Payload is native JSON, creation time DATETIME(6), owner/task/run explicit. Single-column FKs prove existence; official repository locks/typed decoding must prove same-owner/task linkage. Official paths will be INSERT-only; this is not a claim that database administrators cannot UPDATE/DELETE valid rows.

## Reproducible verification

From backend with the prepared Python dependencies and Docker/pinned official MySQL image:

```sh
PYTHONPATH=.:tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q tests/test_teacher_work_proposals.py tests/test_teacher_work_mysql_schema.py tests/test_teacher_work_private_materials.py
PYTHONPATH=.:tests /tmp/gezhi-mysql-venv/bin/python -m pytest -q -s tests/native_teacher_work_proposals_schema.py
```

Native files are deliberately not named test_*. Ordinary pytest discovery never connects to MySQL. The native fixture accepts no external DB URL/credentials: it owns a random network-none official8.4.10 container and synthetic disposable databases via Unix socket, then drops them and stops/removes its exact container/volumes.

Observed at this stage:74 focused unit/regression cases passed,48 proposal cases. Full existing+new Teacher Work unit suite243 passed. Native22 migration/physical cases passed, followed by2 additional actual INSERT/COMMIT-lost-ack cases passed. After independent review, the complete24-case native command was rerun by the controller:24 passed in52.21s (/tmp/gezhi-proposals-sdd/stage-1-native-all.log). Lost INSERT after real SQL reports UNKNOWN/ledger_written=null; new connection sees physical target but no receipt, and fresh preparation refuses. Lost COMMIT after real commit still reports UNKNOWN/null; independent connection confirms the receipt and exact repeated preparation is read-only. No unknown outcome becomes assumed success.

First real SQL: MySQL8.4.10, connection8, UUID b5ba0cac-c149-11f1-a357-65598fbf1321, /var/lib/mysql/, /run/gezhi-native/mysql.sock, skip_networking1, STRICT_TRANS_TABLES, FK/unique checks1. Actual catalogs verify CHECK3819, FK1452, unique/PK1062, JSON Unicode and DATETIME6 roundtrip. Three owned server teardowns recorded stopped=true,exit_code0,removed_with_volumes=true,baseline_preserved=true; no preexisting container was running at start.

Raw stage evidence: /tmp/gezhi-proposals-sdd/task-1-*.log; /tmp/gezhi-tw-native-fkx_0_zl/first-sql.json; /tmp/gezhi-tw-native-4pc3g4wg/proposal-schema.json; /tmp/gezhi-tw-native-njplrb0h/proposal-lost-{insert,commit}-ack.json; all three cleanup.json files. The controller rerun additionally recorded /tmp/gezhi-tw-native-znogw0l5/cleanup.json with clean exit0/removal/baseline preservation. These are current execution artifacts; later publication will package the evidence.

The128KiB typed candidate bound does not waive the saved draft65535 limit. Completion must reuse the actual manual-save serialization including receipt/origin overhead and fail with PROPOSAL_DRAFT_TOO_LARGE before COMPLETE if it cannot fit. No truncation, original cap expansion or automatic adoption/save/approval/export is authorized. Existing task/chat DTOs and old HTTP fixtures remain unchanged; the frozen proposal contract defines its new bounded owner-scoped discovery list.

CI has not been verified; no denied-query retry or alternate query path was attempted.
