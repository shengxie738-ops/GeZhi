# Paper receipt CHECK syntax correction, R3

## Exact baseline and reproduced native failure

Published baseline: `c5916ca6c4782712b62c4687a1801be016ec295c`, branch102V12. GitHub Connector reads confirmed both changed existing targets match accepted R2 bytes: `backend/app/services/chat_batch_schema.py` and `backend/tests/native_work_persistence_contracts.py`. R1/R2 frozen directories remain unchanged.

The separate native Cloud task `01a11509-dc29-73af-8ed6-e9e76ed1e002` reported MySQL8.0.39 installation confirmation failing because the server reflects SQL `!=` as equivalent `<>`. The actual reflected pair CHECK is saved verbatim in `backend/tests/fixtures/chat_batch_mysql8039_checks.json`. SQLAlchemy reflection removes catalog quote escaping; this patch uses the reflected expression supplied by that executor, not a guessed `/tmp` file or dot database observation.

The previous normalizer produced identical expressions except:

- Expected: `user_message_id!=assistant_message_id`
- Observed: `user_message_id<>assistant_message_id`

Consequently, the application rejected its newly installed physical table and raised `receipt installation outcome unknown; re-inspect before retry`. The Cloud executor reported both transcript and receipt row counts0 and paused dependent positive tests. It did not edit product source or bypass the guard.

## Narrow change

Only the receipt-specific `_normalized_check` changes in production. After the existing shared formatter, it canonicalizes unquoted `<>` operator tokens to `!=`. Single/double quoted text, doubled quotes and backslash escapes are protected from this replacement. It does not alter the shared Teacher Work normalizer, model, migration, table definition, contract hash, transaction/ownership logic, response codes, or frontend behavior.

Other comparisons remain distinct: equality, NULL-safe equality and ordered comparisons; changed literal contents; changed Boolean grouping; and a weaker pair constraint admitting zero message IDs. Existing physical column/charset/default/generated/integer/PK/engine/session checks remain unchanged.

## Red → green evidence

The exact captured expression and full supplied-MySQL-schema port initially produced4 expected failures with89 passes. Two additional quoted-text controls exposed a too-broad initial token replacement; those were red before protecting double quoted text.

Final focused command:

```sh
python backend/tests/run_work_persistence_audit.py --report-json /tmp/paper-receipt-r3.json
```

Result: **95 passed** (the existing80 cases plus15 narrow syntax controls). The full schema positive uses captured MySQL reflection and supplied catalog facts; it is not a native database execution by dot. Weaker-schema and quoted/operator/grouping negative controls pass.

## Native acceptance remains pending

No actual database, credential, provider, Docker, production DDL, Git publication or external data action ran in this dot executor. The existing isolated venv was reused without new dependencies.

After independent review/publication, the Cloud executor must re-inspect the already installed, zero-row table at the exact new commit and exercise the existing-schema no-op apply path. Do not drop/recreate the table or mistake this dot syntax replay for complete MySQL transaction/concurrency acceptance. Resume the paused positive lifecycle tests only after the corrected physical guard succeeds.
