"""Read-only MySQL schema observation and deterministic render-only DDL plans.

No connection is opened here and no apply/upgrade function exists. Runtime
comparison is conservative: exact types, nullability, ownership cascades,
engine/collation and owner/version index are required. Inspection is evidence
of metadata only; native locking/snapshot acceptance is a separate gate.
"""
from dataclasses import dataclass
import hashlib
import json
import re
from sqlalchemy import inspect, text
from app.services.byok.errors import ByokError


def _table(columns, primary_key, foreign_keys=(), indexes=()):
    return {
        'columns': columns,
        'primary_key': list(primary_key),
        'foreign_keys': list(foreign_keys),
        'indexes': [list(x) for x in indexes],
        'engine': 'InnoDB',
        'collation': 'utf8mb4_bin'
    }


def _cols(**values):
    columns = {name: {
        'type': kind.rstrip('?'),
        'nullable': kind.endswith('?')
    } for name, kind in values.items()}
    for name in ('username', 'user_id'):
        if name in columns:
            columns[name]['collation'] = 'utf8mb4_bin'
    return columns


def _observed_column(column, table_collation, dialect):
    datatype = column['type']
    kind = datatype.compile(dialect=dialect).lower() if hasattr(
        datatype,
        'compile'
    ) else str(datatype).lower()
    kind = re.split('\\s+(?:character set|collate)\\b', kind, maxsplit=1)[0]
    kind = re.sub('\\b(bigint|integer|int)\\(\\d+\\)', '\\1', kind)
    result = {'type': kind, 'nullable': bool(column['nullable'])}
    if column['name'] in ('username', 'user_id'):
        result['collation'] = getattr(datatype, 'collation', None) or table_collation
    return result
FK = {
    'columns': ['user_id'],
    'referred_table': 'user_accounts',
    'referred_columns': ['username'],
    'ondelete': 'CASCADE'
}
BYOK_SCHEMA_CONTRACT = {
    'user_accounts': _table(
        _cols(username='varchar(255)', role='varchar(32)'),
        ('username',),
    ),
    'user_model_inventories': _table(
        _cols(user_id='varchar(255)', account_instance_id='varchar(64)', inventory_revision='bigint'),
        ('user_id',),
        (FK,),
    ),
    'user_custom_ai_models': _table(
        _cols(
            id='varchar(64)',
            user_id='varchar(255)',
            owner_binding_token='varchar(64)?',
            name='varchar(64)',
            provider='varchar(64)',
            api_type='varchar(64)',
            adapter_id='varchar(64)?',
            base_url='varchar(512)',
            encrypted_api_key='text',
            credential_envelope='json?',
            credential_state='varchar(32)',
            config_version='bigint',
            credential_version='bigint',
            consent_version='bigint',
            destination_digest='varchar(64)?',
            capability_evidence='json',
            probe_generations='json',
            response_model_aliases='json',
            model_ids='json',
            is_active='tinyint(1)',
            created_at='timestamp?',
            updated_at='timestamp?',
        ),
        ('id',),
        (FK,),
        (('user_id', 'id', 'config_version'),),
    ),
}
FUTURE_SAFE_COLUMNS = {
    'chat_messages': {
        'model_provenance': 'JSON NULL',
        'model_completion_state': 'VARCHAR(16) NULL',
        'delivery_state': 'VARCHAR(16) NULL',
        'persistence_state': 'VARCHAR(16) NULL',
    },
    'teacher_work_tasks': {'model_selection': 'JSON NULL'},
    'teacher_work_runs': {
        'model_selection': 'JSON NULL',
        'model_provenance': 'JSON NULL',
        'model_provenance_digest': 'VARCHAR(64) NULL',
        'execution_provenance_digest': 'VARCHAR(64) NULL',
        'model_completion_state': 'VARCHAR(16) NULL',
    },
}


@dataclass(frozen=True)
class ByokSchemaObservation:
    database_identity: str
    available: bool
    issues: tuple[str, ...]
    tables: dict


@dataclass(frozen=True)
class ReviewedSchemaPlan:
    database_identity: str
    statements: tuple[str, ...]
    sha256: str
    preflight: tuple[str, ...]


def compare_schema(database_identity, existing):
    issues = []
    for name, expected in BYOK_SCHEMA_CONTRACT.items():
        actual = existing.get(name)
        if not isinstance(actual, dict):
            issues.append(name + ':missing')
            continue
        for option in ('engine', 'collation', 'primary_key'):
            if actual.get(option) != expected[option]:
                issues.append(name + ':' + option)
        for column, definition in expected['columns'].items():
            if actual.get('columns', {}).get(column) != definition:
                issues.append(name + ':column:' + column)
        for fk in expected['foreign_keys']:
            if fk not in actual.get('foreign_keys', []):
                issues.append(name + ':ownership_cascade')
        for index in expected['indexes']:
            if index not in actual.get('indexes', []):
                issues.append(name + ':owner_version_index')
    return ByokSchemaObservation(database_identity, not issues, tuple(issues), existing)


def observe_byok_schema(connection):
    """Caller supplies a connection; SELECT/inspector only, never migration."""
    try:
        if connection.dialect.name != 'mysql':
            return compare_schema('unsupported-dialect', {})
        identity = connection.execute(text('SELECT DATABASE()')).scalar_one()
        if not isinstance(identity, str) or not identity:
            raise ValueError('database identity required')
        inspector = inspect(connection)
        names = set(inspector.get_table_names())
        tables = {}
        metadata = connection.execute(text('SELECT TABLE_NAME, ENGINE, TABLE_COLLATION FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()')).mappings().all()
        options = {r['TABLE_NAME']: r for r in metadata}
        for name in dict.fromkeys((*BYOK_SCHEMA_CONTRACT, *FUTURE_SAFE_COLUMNS)):
            if name not in names:
                continue
            try:
                info = options.get(name, {})
                columns = {row['name']: _observed_column(
                    row,
                    info.get('TABLE_COLLATION'),
                    connection.dialect
                ) for row in inspector.get_columns(name)}
                fks = [{
                    'columns': r['constrained_columns'],
                    'referred_table': r['referred_table'],
                    'referred_columns': r['referred_columns'],
                    'ondelete': r.get('options', {}).get('ondelete', '').upper() if r.get('referred_schema') in (None, identity) else 'EXTERNAL_SCHEMA_REJECTED'
                } for r in inspector.get_foreign_keys(name)]
                info = options.get(name, {})
                tables[name] = {
                    'columns': columns,
                    'primary_key': inspector.get_pk_constraint(name).get('constrained_columns', []),
                    'foreign_keys': fks,
                    'indexes': [r['column_names'] for r in inspector.get_indexes(name)],
                    'engine': info.get('ENGINE'),
                    'collation': info.get('TABLE_COLLATION')
                }
            except Exception:
                if name in BYOK_SCHEMA_CONTRACT:
                    raise
                # Do not fabricate absence or make future metadata a CRUD gate.
                # A migration render still requires a complete future observation.
                tables[name] = {'observation_unavailable': True}
        return compare_schema(identity, tables)
    except Exception:
        return compare_schema('observation-unavailable', {})


def render_work_byok_schema_plan(*, expected_database_identity, existing_schema):
    if not isinstance(
        existing_schema,
        ByokSchemaObservation
    ) or type(expected_database_identity) is not str or (not expected_database_identity) or (expected_database_identity != existing_schema.database_identity):
        raise ByokError('BYOK_STORAGE_UNAVAILABLE')
    statements = []
    tables = existing_schema.tables
    if any(tables.get(name, {}).get('observation_unavailable') for name in FUTURE_SAFE_COLUMNS):
        raise ByokError('BYOK_STORAGE_UNAVAILABLE')
    for name, contract in BYOK_SCHEMA_CONTRACT.items():
        if name == 'user_accounts':
            # Account ownership conversion is necessary only if observations differ.
            if name not in tables:
                continue
            if tables[name].get('engine') != 'InnoDB':
                statements.append('ALTER TABLE user_accounts ENGINE=InnoDB;')
            if tables[name].get('collation') != 'utf8mb4_bin':
                statements.append('ALTER TABLE user_accounts CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;')
            for column, definition in contract['columns'].items():
                if tables[name].get('columns', {}).get(column) != definition:
                    sql = definition['type'].upper()
                    if definition.get('collation'):
                        sql += ' COLLATE ' + definition['collation']
                    sql += ' NULL' if definition['nullable'] else ' NOT NULL'
                    if column == 'role':
                        sql += " DEFAULT 'student'"
                    statements.append(f'ALTER TABLE user_accounts MODIFY COLUMN {column} {sql};')
            continue
        actual = tables.get(name)
        if actual:
            if actual.get('engine') != 'InnoDB':
                statements.append(f'ALTER TABLE {name} ENGINE=InnoDB;')
            if actual.get('collation') != 'utf8mb4_bin':
                statements.append(f'ALTER TABLE {name} CONVERT TO CHARACTER SET utf8mb4 COLLATE utf8mb4_bin;')
        defs = []
        for col, definition in contract['columns'].items():
            sql = definition['type'].upper()
            if definition.get('collation'):
                sql += ' COLLATE ' + definition['collation']
            sql += ' NULL' if definition['nullable'] else ' NOT NULL'
            if col in ('config_version',):
                sql += ' DEFAULT 1'
            elif col in ('credential_version', 'consent_version', 'inventory_revision'):
                sql += ' DEFAULT 0'
            elif col == 'credential_state':
                sql += " DEFAULT 'legacy_reentry_required'"
            elif col == 'name':
                sql += " DEFAULT 'Custom model'"
            elif col == 'is_active':
                sql += ' DEFAULT 0'
            elif col in ('capability_evidence', 'model_ids'):
                sql += ' DEFAULT (JSON_ARRAY())'
            elif col in ('probe_generations', 'response_model_aliases'):
                sql += ' DEFAULT (JSON_OBJECT())'
            defs.append(f'{col} {sql}')
            if actual and actual.get('columns', {}).get(col) != definition:
                verb = 'MODIFY' if col in actual.get('columns', {}) else 'ADD'
                statements.append(f'ALTER TABLE {name} {verb} COLUMN {col} {sql};')
        constraints = [f"PRIMARY KEY ({', '.join(contract['primary_key'])})"]
        for fk in contract['foreign_keys']:
            fkname = 'fk_byok_' + name + '_account'
            sql = f'CONSTRAINT {fkname} FOREIGN KEY (user_id) REFERENCES user_accounts (username) ON DELETE CASCADE'
            constraints.append(sql)
            if actual and fk not in actual.get('foreign_keys', []):
                statements.append(f'ALTER TABLE {name} ADD {sql};')
        for cols in contract['indexes']:
            sql = f"INDEX ix_byok_owner_config_version ({', '.join(cols)})"
            constraints.append(sql)
            if actual and cols not in actual.get('indexes', []):
                statements.append(f'ALTER TABLE {name} ADD {sql};')
        if not actual:
            statements.append(f"CREATE TABLE {name} ({', '.join(defs + constraints)}) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin;")
    for name, columns in FUTURE_SAFE_COLUMNS.items():
        # Existing teacher/student tables must be present before applying this plan.
        for column, definition in columns.items():
            actual = tables.get(name, {}).get('columns', {}).get(column)
            expected = {'type': definition.removesuffix(' NULL').lower(), 'nullable': True}
            if actual != expected:
                verb = 'ADD' if actual is None else 'MODIFY'
                statements.append(f'ALTER TABLE {name} {verb} COLUMN {column} {definition};')
    preflight = (
        'explicit_migration_authorization_required',
        'exact_database_identity_required',
        'backup_and_restore_plan_required',
        'owner_history_review_required',
        'orphan_and_duplicate_owner_review_required',
        'account_collation_fk_compatibility_required',
        'existing_teacher_student_tables_required',
        'mysql_8_0_16_or_later_required',
        'nonsecret_metadata_defaults_review_required',
        'legacy_rows_unbound_reentry_only',
        'no_decrypt_backfill_or_reencryption',
        'native_mysql_fk_snapshot_lock_acceptance_required',
        'ddl_review_separate_from_application_review'
    )
    payload = {
        'database_identity': expected_database_identity,
        'statements': statements,
        'preflight': preflight
    }
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return ReviewedSchemaPlan(expected_database_identity, tuple(statements), digest, preflight)
