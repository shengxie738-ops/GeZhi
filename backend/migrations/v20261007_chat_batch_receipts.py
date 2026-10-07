"""Explicit, identity/hash checked additive receipt installation; never startup.

Caller supplies a dedicated authorized connection. No settings/engine/CLI secrets,
ALTER, DROP, backfill or account mutation. MySQL DDL may survive an error: inspect
again; never promise atomic DDL rollback or erase receipt tombstones to roll back.
"""
from sqlalchemy import inspect, text
from sqlalchemy.sql.ddl import CreateTable

from app.models.chat_batch_receipt import ChatBatchReceipt
from app.services.chat_batch_schema import CONTRACT_HASH, inspect_receipt_schema, mysql_ddl


def observe_database_identity(connection):
    dialect=connection.dialect.name
    if dialect=='mysql':
        row=connection.execute(text('SELECT DATABASE() AS database_name, @@server_uuid AS server_uuid')).mappings().one()
        if not row['database_name'] or not row['server_uuid']:
            raise ValueError('exact database identity required')
        return {'dialect':'mysql','database':row['database_name'],'server_uuid':row['server_uuid']}
    if dialect=='sqlite':
        entries=connection.exec_driver_sql('PRAGMA database_list').all()
        main=[row[2] for row in entries if row[1]=='main']
        if len(main)!=1 or not main[0]:
            raise ValueError('dedicated file database identity required')
        return {'dialect':'sqlite','database':main[0]}
    raise ValueError('supported database identity required')


def preflight_chat_batch_receipts(connection,*,expected_identity,contract_hash):
    if connection.in_transaction():
        raise ValueError('fresh dedicated connection required')
    if contract_hash!=CONTRACT_HASH:
        raise ValueError('exact reviewed receipt contract hash required')
    if observe_database_identity(connection)!=expected_identity:
        raise ValueError('database identity mismatch')
    status=inspect_receipt_schema(connection)
    if status=='incompatible':
        raise ValueError('incompatible receipt schema; no automatic repair')
    observer=inspect(connection)
    if 'chat_messages' not in observer.get_table_names():
        raise ValueError('existing chat_messages participant required')
    if connection.dialect.name=='mysql':
        from app.services.teacher_work.schema_mysql import _resolved_table_issues
        controls=connection.execute(text('SELECT @@session.autocommit AS autocommit, @@session.unique_checks AS unique_checks')).mappings().one()
        if controls['autocommit']!=0 or controls['unique_checks']!=1:
            raise ValueError('transactional session and enabled uniqueness required')
        if observer.get_table_options('chat_messages').get('mysql_engine')!='InnoDB' or _resolved_table_issues(
                connection,expected_identity['database'],('chat_messages',),{'chat_messages'}):
            raise ValueError('persistent transactional InnoDB chat_messages required')
    return {'mode':'fresh' if status=='absent' else 'exact', 'identity':expected_identity,
        'contract_hash':CONTRACT_HASH, 'automatic_startup':False, 'mysql_ddl':mysql_ddl()}


def apply_chat_batch_receipts(connection,*,expected_identity,contract_hash):
    """Install only absent table; exact schema is a no-op, incompatible refused.

    Quiescence and operator authorization are external requirements. A failure
    can leave installed DDL; caller must re-inspect, never blindly drop/retry.
    """
    plan=preflight_chat_batch_receipts(connection,expected_identity=expected_identity,contract_hash=contract_hash)
    created=False
    if plan['mode']=='fresh':
        connection.execute(CreateTable(ChatBatchReceipt.__table__))
        created=True
        connection.commit()
    if observe_database_identity(connection)!=expected_identity or inspect_receipt_schema(connection)!='ready':
        raise ValueError('receipt installation outcome unknown; re-inspect before retry')
    connection.commit()
    return {'completed':True, 'created':created, 'identity':expected_identity,'contract_hash':CONTRACT_HASH}
