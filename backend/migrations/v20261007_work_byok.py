"""Review-only Work BYOK schema planner. Intentionally has no execution API.

Obtain read-only observations in the separately authorized environment, render
and review the returned statements/hash/preflight, then request explicit native
migration authorization. This module does not connect, execute DDL, backfill,
decrypt legacy credentials, re-encrypt or create a production keyring.
"""
from app.services.byok.schema import render_work_byok_schema_plan


def render_plan(*, expected_database_identity, existing_schema):
    return render_work_byok_schema_plan(
        expected_database_identity=expected_database_identity,
        existing_schema=existing_schema
    )
