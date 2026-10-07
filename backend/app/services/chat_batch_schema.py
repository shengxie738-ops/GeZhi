"""Read-only exact physical receipt preflight; no startup/DDL/config side effects."""
import hashlib
import json
import re

from sqlalchemy import inspect, text
from sqlalchemy.sql.ddl import CreateTable
from sqlalchemy.dialects.mysql import dialect as mysql_dialect

from app.models.chat_batch_receipt import ChatBatchReceipt

TABLE = ChatBatchReceipt.__table__
CONTRACT = {
    'version':1, 'table':TABLE.name,
    'columns':{'owner_key':('binary',1020,False), 'request_key':('binary',512,False),
        'request_digest':('string',64,False), 'agent_mode':('string',32,False),
        'conversation_id':('string',64,True), 'project_id':('string',64,True),
        'state':('string',16,False), 'user_message_id':('integer',None,True),
        'assistant_message_id':('integer',None,True)},
    'primary_key':['owner_key','request_key'],
    'checks':{c.name:str(c.sqltext) for c in TABLE.constraints if hasattr(c,'sqltext')},
    'mysql_engine':'InnoDB',
}
CONTRACT_HASH = hashlib.sha256(json.dumps(CONTRACT,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def mysql_ddl():
    return str(CreateTable(TABLE).compile(dialect=mysql_dialect()))


def _normalized_check(value):
    from app.services.teacher_work.schema_mysql import _check
    normalized = _check(value)
    # MySQL serializes SQL != as <>. Canonicalize only operator tokens;
    # Quoted text is never changed by this operator-token replacement.
    return re.sub(r"('(?:''|\\.|[^'])*'|\"(?:\"\"|\\.|[^\"])*\")|<>",
        lambda match: match.group(1) if match.group(1) is not None else "!=", normalized)


def inspect_receipt_schema(connection):
    """Return absent/ready/incompatible without mutating database state."""
    from sqlalchemy import BINARY, VARBINARY, Integer, LargeBinary, String
    dialect=connection.dialect.name
    if dialect not in ('mysql','sqlite'):
        return 'incompatible'
    observer=inspect(connection)
    if TABLE.name not in observer.get_table_names():
        return 'absent'
    # Pin the resolved physical table on this transaction before inspecting it.
    connection.execute(text('SELECT owner_key FROM chat_batch_receipts LIMIT 0'))
    columns={c['name']:c for c in observer.get_columns(TABLE.name)}
    if set(columns)!=set(CONTRACT['columns']):
        return 'incompatible'
    for name,(kind,length,nullable) in CONTRACT['columns'].items():
        value=columns[name]; column_type=value['type']
        expected={'binary':(LargeBinary,BINARY,VARBINARY),'string':String,'integer':Integer}[kind]
        if not isinstance(column_type,expected) or value['nullable'] is not nullable:
            return 'incompatible'
        if kind=='binary' and dialect=='mysql' and type(column_type) is not VARBINARY:
            return 'incompatible'
        if kind=='string' or kind=='binary' and dialect=='mysql':
            if column_type.length!=length:
                return 'incompatible'
    if observer.get_pk_constraint(TABLE.name)['constrained_columns']!=CONTRACT['primary_key']:
        return 'incompatible'
    if observer.get_unique_constraints(TABLE.name) or observer.get_foreign_keys(TABLE.name):
        return 'incompatible'
    if any(index.get('unique') for index in observer.get_indexes(TABLE.name)):
        return 'incompatible'
    actual={c['name']:_normalized_check(c['sqltext']) for c in observer.get_check_constraints(TABLE.name)}
    expected={name:_normalized_check(value) for name,value in CONTRACT['checks'].items()}
    if actual!=expected:
        return 'incompatible'
    if dialect=='mysql':
        from app.services.teacher_work.schema_mysql import _resolved_table_issues
        controls=connection.execute(text('SELECT @@session.autocommit AS autocommit, @@session.unique_checks AS unique_checks')).mappings().one()
        if controls['autocommit']!=0 or controls['unique_checks']!=1:
            return 'incompatible'
        schema=connection.execute(text('SELECT DATABASE()')).scalar_one()
        names=(TABLE.name,'chat_messages')
        if not schema or _resolved_table_issues(connection,schema,names,set(names)):
            return 'incompatible'
        constraints=connection.execute(text("SELECT CONSTRAINT_NAME, ENFORCED FROM INFORMATION_SCHEMA.TABLE_CONSTRAINTS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='chat_batch_receipts' AND CONSTRAINT_TYPE='CHECK'")).all()
        if {name for name,enforced in constraints}!=set(CONTRACT['checks']) or any(enforced!='YES' for name,enforced in constraints):
            return 'incompatible'
        primary=connection.execute(text("SELECT COLUMN_NAME, SUB_PART, NON_UNIQUE, SEQ_IN_INDEX, INDEX_TYPE "
            "FROM INFORMATION_SCHEMA.STATISTICS WHERE TABLE_SCHEMA=DATABASE() "
            "AND TABLE_NAME='chat_batch_receipts' AND INDEX_NAME='PRIMARY' ORDER BY SEQ_IN_INDEX")).all()
        if [tuple(row) for row in primary] != [('owner_key',None,0,1,'BTREE'),('request_key',None,0,2,'BTREE')]:
            return 'incompatible'
        from app.services.teacher_work.schema_mysql import _column_valid
        physical=connection.execute(text("SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type, "
            "COLUMN_TYPE AS column_type, IS_NULLABLE AS is_nullable, COLUMN_DEFAULT AS column_default, "
            "CHARACTER_MAXIMUM_LENGTH AS character_maximum_length, CHARACTER_OCTET_LENGTH AS character_octet_length, "
            "CHARACTER_SET_NAME AS character_set_name, COLLATION_NAME AS collation_name, EXTRA AS extra, "
            "GENERATION_EXPRESSION AS generation_expression FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME='chat_batch_receipts'")).mappings().all()
        by_name={row['column_name']:row for row in physical}
        if len(by_name)!=len(physical) or set(by_name)!=set(CONTRACT['columns']):
            return 'incompatible'
        for name,(kind,length,nullable) in CONTRACT['columns'].items():
            typename={'binary':f'varbinary({length})','string':f'varchar({length})','integer':'integer'}[kind]
            if not _column_valid(by_name[name],{'type':typename,'nullable':nullable},repair_default=False):
                return 'incompatible'
        options=connection.execute(text("SELECT t.TABLE_TYPE AS table_type, t.ENGINE AS engine, "
            "t.TABLE_COLLATION AS table_collation, c.CHARACTER_SET_NAME AS character_set_name "
            "FROM INFORMATION_SCHEMA.TABLES t LEFT JOIN INFORMATION_SCHEMA.COLLATION_CHARACTER_SET_APPLICABILITY c "
            "ON c.COLLATION_NAME=t.TABLE_COLLATION WHERE t.TABLE_SCHEMA=DATABASE() "
            "AND t.TABLE_NAME='chat_batch_receipts'")).mappings().all()
        if len(options)!=1 or any(options[0].get(k)!=v for k,v in
            {'table_type':'BASE TABLE','engine':'InnoDB','table_collation':'utf8mb4_bin','character_set_name':'utf8mb4'}.items()):
            return 'incompatible'
        # MySQL physical participants, not ORM options, must support rollback.
        for name in names:
            if observer.get_table_options(name).get('mysql_engine')!='InnoDB':
                return 'incompatible'
    return 'ready'


def paper_batch_readiness(db):
    try:
        ready=inspect_receipt_schema(db.connection())=='ready'
    except Exception:
        ready=False
    return {'available':ready, 'reason':None if ready else 'paper_batch_schema_unavailable'}
