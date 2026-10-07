"""Render-only schema plans and simulated introspection, no native DDL execution."""
import importlib
from pathlib import Path
import pytest
ROOT = Path(__file__).resolve().parents[2]


def feature():
    assert (ROOT / 'backend/app/services/byok/schema.py').is_file(), 'Task 4 schema observer missing'
    return importlib.import_module('app.services.byok.schema')


def test_schema_missing_incompatible_fail_closed_and_observer_read_only():
    m = feature()
    empty = m.compare_schema('synthetic-mysql', {})
    assert not empty.available and 'user_model_inventories' in repr(empty)
    valid = m.compare_schema('synthetic-mysql', m.BYOK_SCHEMA_CONTRACT)
    assert valid.available
    import copy
    for key, value in [('engine', 'MyISAM'), ('collation', 'utf8mb4_general_ci')]:
        wrong = copy.deepcopy(m.BYOK_SCHEMA_CONTRACT)
        wrong['user_accounts'][key] = value
        assert not m.compare_schema('synthetic-mysql', wrong).available
    for table in ('user_custom_ai_models', 'user_model_inventories'):
        wrong = copy.deepcopy(m.BYOK_SCHEMA_CONTRACT)
        wrong[table]['foreign_keys'] = []
        assert not m.compare_schema('synthetic-mysql', wrong).available
    wrong = copy.deepcopy(m.BYOK_SCHEMA_CONTRACT)
    wrong['user_custom_ai_models']['indexes'] = []
    assert not m.compare_schema('synthetic-mysql', wrong).available


def test_render_only_schema_plan_identity_hash_preflight_and_future_columns():
    m = feature()
    migration = importlib.import_module('backend_migration_work_byok') if False else m
    plan = m.render_work_byok_schema_plan(
        expected_database_identity='synthetic-mysql',
        existing_schema=m.compare_schema('synthetic-mysql', {})
    )
    assert len(plan.sha256) == 64 and plan.database_identity == 'synthetic-mysql'
    ddl = '\n'.join(plan.statements)
    for word in (
        'ON DELETE CASCADE',
        'user_model_inventories',
        'config_version',
        'credential_envelope',
        'capability_evidence',
        'model_provenance',
        'execution_provenance_digest',
        'model_selection',
        'utf8mb4_bin',
        'InnoDB'
    ):
        assert word in ddl
    assert 'encrypted_api_key TEXT NOT NULL DEFAULT' not in ddl
    assert 'owner_history_review_required' in plan.preflight
    assert not hasattr(plan, 'apply') and (not hasattr(plan, 'execute'))
    with pytest.raises(m.ByokError):
        m.render_work_byok_schema_plan(
            expected_database_identity='different',
            existing_schema=m.compare_schema('synthetic-mysql', {})
        )
    text = (ROOT / 'backend/migrations/v20261007_work_byok.py').read_text()
    assert 'def apply' not in text and 'def upgrade' not in text and ('.execute(' not in text)


def test_no_startup_byok_creation_backfill_or_reencrypt():
    feature()
    text = (ROOT / 'backend/app/core/init_db.py').read_text()
    assert 'user_model_inventory' in text and 'startup_table_allowed' in text
    models = (ROOT / 'backend/app/models/user_custom_ai_model.py').read_text() + (ROOT / 'backend/app/models/user_model_inventory.py').read_text()
    assert models.count('explicit_migration_only') == 2
    assert 'decrypt_secret' not in models and 'mask_api_key' not in models


def test_actual_observer_inspection_reads_only_exact_types_fk_cascade(monkeypatch):
    m = feature()
    from sqlalchemy.dialects import mysql

    class Result:

        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

        def mappings(self):
            return self

        def all(self):
            return self.value

    class Connection:
        dialect = mysql.dialect()
        statements = []

        def execute(self, statement):
            sql = str(statement)
            self.statements.append(sql)
            assert sql.startswith('SELECT')
            if sql == 'SELECT DATABASE()':
                return Result('synthetic-mysql')
            return Result([{
                'TABLE_NAME': name,
                'ENGINE': table['engine'],
                'TABLE_COLLATION': table['collation']
            } for name, table in m.BYOK_SCHEMA_CONTRACT.items()])

    class Type:

        def __new__(cls, value):
            if value.startswith('varchar('):
                return mysql.VARCHAR(int(value[8:-1]), collation='utf8mb4_bin')
            return {
                'bigint': mysql.BIGINT(display_width=20),
                'tinyint(1)': mysql.TINYINT(display_width=1),
                'json': mysql.JSON(),
                'text': mysql.TEXT(),
                'timestamp': mysql.TIMESTAMP()
            }[value]

    class Inspector:

        def get_table_names(self):
            return list(m.BYOK_SCHEMA_CONTRACT)

        def get_columns(self, name):
            return [{
                'name': key,
                'type': Type(value['type']),
                'nullable': value['nullable']
            } for key, value in m.BYOK_SCHEMA_CONTRACT[name]['columns'].items()]

        def get_pk_constraint(self, name):
            return {'constrained_columns': m.BYOK_SCHEMA_CONTRACT[name]['primary_key']}

        def get_foreign_keys(self, name):
            return [dict(
                constrained_columns=x['columns'],
                referred_table=x['referred_table'],
                referred_columns=x['referred_columns'],
                options={'ondelete': x['ondelete']}
            ) for x in m.BYOK_SCHEMA_CONTRACT[name]['foreign_keys']]

        def get_indexes(self, name):
            return [{'column_names': x} for x in m.BYOK_SCHEMA_CONTRACT[name]['indexes']]
    monkeypatch.setattr(m, 'inspect', lambda connection: Inspector())
    conn = Connection()
    observation = m.observe_byok_schema(conn)
    assert observation.available and len(conn.statements) == 2
    conn.dialect = type('Dialect', (), {'name': 'sqlite'})()
    assert not m.observe_byok_schema(conn).available


def test_rendered_schema_artifact_record(capsys):
    m = feature()
    import copy, json
    observation = m.compare_schema(
        'SYNTHETIC-NOT-PRODUCTION',
        {'user_accounts': copy.deepcopy(m.BYOK_SCHEMA_CONTRACT['user_accounts'])}
    )
    plan = m.render_work_byok_schema_plan(
        expected_database_identity='SYNTHETIC-NOT-PRODUCTION',
        existing_schema=observation
    )
    assert plan.statements and plan.sha256
    with capsys.disabled():
        print('WORK_BYOK_REVIEW_PLAN_JSON:' + json.dumps(
            {'database_identity': plan.database_identity, 'sha256': plan.sha256, 'statements': plan.statements, 'preflight': plan.preflight, 'native_ddl_executed': False, 'native_schema_observed': False},
            separators=(',', ':')
        ))


def test_schema_observer_rejects_cross_database_account_foreign_key(monkeypatch):
    m = feature()
    from sqlalchemy.dialects import mysql

    class Result:

        def __init__(self, value):
            self.value = value

        def scalar_one(self):
            return self.value

        def mappings(self):
            return self

        def all(self):
            return self.value

    class Connection:
        dialect = mysql.dialect()

        def execute(self, sql):
            if str(sql) == 'SELECT DATABASE()':
                return Result('synthetic-mysql')
            return Result([{
                'TABLE_NAME': name,
                'ENGINE': 'InnoDB',
                'TABLE_COLLATION': 'utf8mb4_bin'
            } for name in m.BYOK_SCHEMA_CONTRACT])

    class Type:

        def __new__(cls, value):
            if value.startswith('varchar('):
                return mysql.VARCHAR(int(value[8:-1]), collation='utf8mb4_bin')
            return {
                'bigint': mysql.BIGINT(display_width=20),
                'tinyint(1)': mysql.TINYINT(display_width=1),
                'json': mysql.JSON(),
                'text': mysql.TEXT(),
                'timestamp': mysql.TIMESTAMP()
            }[value]

    class Inspector:

        def get_table_names(self):
            return list(m.BYOK_SCHEMA_CONTRACT)

        def get_columns(self, name):
            return [{
                'name': key,
                'type': Type(value['type']),
                'nullable': value['nullable']
            } for key, value in m.BYOK_SCHEMA_CONTRACT[name]['columns'].items()]

        def get_pk_constraint(self, name):
            return {'constrained_columns': m.BYOK_SCHEMA_CONTRACT[name]['primary_key']}

        def get_foreign_keys(self, name):
            return [dict(
                constrained_columns=x['columns'],
                referred_table=x['referred_table'],
                referred_schema='other-database',
                referred_columns=x['referred_columns'],
                options={'ondelete': 'CASCADE'}
            ) for x in m.BYOK_SCHEMA_CONTRACT[name]['foreign_keys']]

        def get_indexes(self, name):
            return [{'column_names': x} for x in m.BYOK_SCHEMA_CONTRACT[name]['indexes']]
    monkeypatch.setattr(m, 'inspect', lambda connection: Inspector())
    assert not m.observe_byok_schema(Connection()).available


def test_schema_future_existing_wrong_type_requires_explicit_alter():
    m = feature()
    import copy
    existing = copy.deepcopy(m.BYOK_SCHEMA_CONTRACT)
    existing['teacher_work_runs'] = {'columns': {'model_provenance': {'type': 'text', 'nullable': False}}}
    plan = m.render_work_byok_schema_plan(
        expected_database_identity='synthetic-mysql',
        existing_schema=m.compare_schema('synthetic-mysql', existing)
    )
    assert 'ALTER TABLE teacher_work_runs MODIFY COLUMN model_provenance JSON NULL;' in plan.statements


def test_schema_account_column_collation_repair_is_explicit():
    m = feature()
    import copy
    observed = copy.deepcopy(m.BYOK_SCHEMA_CONTRACT)
    observed['user_accounts']['columns']['username']['collation'] = 'utf8mb4_general_ci'
    observation = m.compare_schema('synthetic-mysql', observed)
    assert not observation.available
    plan = m.render_work_byok_schema_plan(expected_database_identity='synthetic-mysql', existing_schema=observation)
    assert 'ALTER TABLE user_accounts MODIFY COLUMN username VARCHAR(255) COLLATE utf8mb4_bin NOT NULL;' in plan.statements


@pytest.mark.parametrize('future_state', ['complete', 'partial', 'wrong_type', 'unavailable'])
def test_r1_actual_observer_keeps_present_future_columns(monkeypatch, future_state):
    m = feature()
    from sqlalchemy.dialects import mysql
    import copy
    tables = copy.deepcopy(m.BYOK_SCHEMA_CONTRACT)
    for name, columns in m.FUTURE_SAFE_COLUMNS.items():
        tables[name] = {
            'columns': {key: {'type': definition.removesuffix(' NULL').lower(), 'nullable': True}
                        for key, definition in columns.items()},
            'engine': 'InnoDB', 'collation': 'utf8mb4_bin',
            'primary_key': [], 'foreign_keys': [], 'indexes': [],
        }
    if future_state == 'partial':
        del tables['teacher_work_runs']['columns']['execution_provenance_digest']
    elif future_state == 'wrong_type':
        tables['teacher_work_runs']['columns']['model_provenance']['type'] = 'text'

    class Result:
        def __init__(self, value):
            self.value = value
        def scalar_one(self):
            return self.value
        def mappings(self):
            return self
        def all(self):
            return self.value

    class Connection:
        dialect = mysql.dialect()
        def execute(self, statement):
            assert str(statement).startswith('SELECT')
            if str(statement) == 'SELECT DATABASE()':
                return Result('SYNTHETIC-R1-DATABASE')
            return Result([{'TABLE_NAME': name, 'ENGINE': table['engine'],
                            'TABLE_COLLATION': table['collation']} for name, table in tables.items()])

    def datatype(value):
        if value.startswith('varchar('):
            return mysql.VARCHAR(int(value[8:-1]), collation='utf8mb4_bin')
        return {'bigint': mysql.BIGINT(display_width=20), 'tinyint(1)': mysql.TINYINT(display_width=1),
                'json': mysql.JSON(), 'text': mysql.TEXT(), 'timestamp': mysql.TIMESTAMP()}[value]

    class Inspector:
        def get_table_names(self):
            return list(tables)
        def get_columns(self, name):
            if future_state == 'unavailable' and name == 'teacher_work_runs':
                raise RuntimeError('SYNTHETIC-FUTURE-OBSERVATION-UNAVAILABLE')
            return [{'name': key, 'type': datatype(value['type']), 'nullable': value['nullable']}
                    for key, value in tables[name]['columns'].items()]
        def get_pk_constraint(self, name):
            return {'constrained_columns': tables[name]['primary_key']}
        def get_foreign_keys(self, name):
            return [dict(constrained_columns=x['columns'], referred_table=x['referred_table'],
                         referred_columns=x['referred_columns'], options={'ondelete': x['ondelete']})
                    for x in tables[name]['foreign_keys']]
        def get_indexes(self, name):
            return [{'column_names': x} for x in tables[name]['indexes']]

    monkeypatch.setattr(m, 'inspect', lambda connection: Inspector())
    observation = m.observe_byok_schema(Connection())
    assert observation.available
    assert set(m.FUTURE_SAFE_COLUMNS) <= set(observation.tables)
    if future_state == 'unavailable':
        assert observation.tables['teacher_work_runs']['observation_unavailable']
        with pytest.raises(m.ByokError, match='BYOK_STORAGE_UNAVAILABLE'):
            m.render_work_byok_schema_plan(expected_database_identity='SYNTHETIC-R1-DATABASE', existing_schema=observation)
        return
    plan = m.render_work_byok_schema_plan(expected_database_identity='SYNTHETIC-R1-DATABASE',
                                         existing_schema=observation)
    if future_state == 'complete':
        assert plan.statements == ()
    elif future_state == 'partial':
        assert plan.statements == ('ALTER TABLE teacher_work_runs ADD COLUMN execution_provenance_digest VARCHAR(64) NULL;',)
    else:
        assert plan.statements == ('ALTER TABLE teacher_work_runs MODIFY COLUMN model_provenance JSON NULL;',)
