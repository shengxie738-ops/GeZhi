"""Physical private-task gates and the finite legacy-save lock guard."""


def _require_transactional_participants(connection):
    """Observe the two existing tables that participate in locks and rollback."""
    from sqlalchemy import text
    from app.services.teacher_work.schema_mysql import _resolved_table_issues
    names = ("user_accounts", "domain_records")
    # Open each resolved table without reading account secrets or creating row
    # locks; transaction-duration metadata locks retain these physical targets.
    connection.execute(text("SELECT username FROM user_accounts LIMIT 0"))
    connection.execute(text("SELECT id FROM domain_records LIMIT 0"))
    schema_name = connection.execute(text("SELECT DATABASE()")).scalar_one()
    if type(schema_name) is not str or not schema_name:
        raise ValueError("selected database required")
    rows = connection.execute(text("SELECT TABLE_NAME AS name, TABLE_TYPE AS kind, ENGINE AS engine "
        "FROM information_schema.tables WHERE TABLE_SCHEMA=DATABASE() "
        "AND TABLE_NAME IN ('user_accounts','domain_records')")).mappings().all()
    present = {row["name"] for row in rows}
    if (len(rows) != 2 or present != set(names)
            or any(row["kind"] != "BASE TABLE" or row["engine"] != "InnoDB" for row in rows)
            or _resolved_table_issues(connection, schema_name, names, present)):
        raise ValueError("persistent InnoDB participants required")


def require_private_schema(transport):
    from sqlalchemy import text
    from app.services.teacher_work.authorization import WorkAuthorizationError
    from app.services.teacher_work.schema_mysql import observe_teacher_work_mysql
    from app.services.teacher_work.schema_mysql_v3 import observe_teacher_work_mysql_v3
    from pymysql.constants.SERVER_STATUS import SERVER_STATUS_IN_TRANS
    transport._verify()
    connection = transport.connection
    try:
        if not observe_teacher_work_mysql(connection).ready and not observe_teacher_work_mysql_v3(connection).ready:
            raise ValueError('exact completed private schema required')
        _require_transactional_participants(connection)
        isolation, autocommit = connection.execute(text(
            "SELECT @@session.transaction_isolation, @@session.autocommit")).one()
        # MySQL has no @@in_transaction. PyMySQL's SELECT EOF does not refresh
        # Connection.server_status; this literal non-DML OK packet does.
        connection.execute(text("DO 0"))
        status = connection.connection.driver_connection.server_status
        if (isolation != "READ-COMMITTED" or type(autocommit) is not int or autocommit != 0
                or type(status) is not int or not status & SERVER_STATUS_IN_TRANS):
            raise ValueError("physical session required")
        transport._verify()
    except Exception:
        raise WorkAuthorizationError("TEACHER_WORK_SCHEMA_UNAVAILABLE", 503) from None


def prepare_legacy_save(session, subject, draft_id):
    """No namespace creation; all checks precede the original payload write.

    Account locks serialize Work first-create with a legacy save even when no
    owner lease exists. Existing leases and drafts precede task locks.
    """
    from sqlalchemy import select, text
    from app.models.domain_record import DomainRecord
    from app.models.teacher_work import OwnerRunLease, WorkTask
    from app.services.current_identity import load_current_account
    from app.services.teacher_work.authorization import CurrentAccountFacts, WorkAuthorizationError, require_current_teacher_facts
    from app.services.teacher_work.schema_mysql import observe_teacher_work_mysql
    from app.services.teacher_work.schema import TEACHER_WORK_SCHEMA_CONTRACT
    try:
        connection = session.connection()  # Bind this Session's physical root first.
        if connection.dialect.name != "mysql" or session.new or session.dirty or session.deleted:
            raise ValueError("clean MySQL root required")
        report = observe_teacher_work_mysql(connection)
        if (report.dialect == "mysql" and not report.issues
                and set(report.missing_tables) == set(TEACHER_WORK_SCHEMA_CONTRACT["tables"])
                and not report.observation.get("tables") and not report.ledger_present):
            return  # Proven entirely absent, preserving the original legacy behavior.
        if not report.ready:
            from app.services.teacher_work.schema_mysql_v3 import observe_teacher_work_mysql_v3
            report=observe_teacher_work_mysql_v3(connection)
        if not report.ready or connection.execute(text("SELECT @@session.autocommit")).scalar_one() != 0:
            raise ValueError("complete verified registry required")
        _require_transactional_participants(connection)
        with session.no_autoflush:
            account = load_current_account(session, subject, lock=True)
            require_current_teacher_facts(subject, CurrentAccountFacts(account.username, account.role))
            leases = session.scalars(select(OwnerRunLease).where(OwnerRunLease.owner == subject)
                .execution_options(populate_existing=True).with_for_update().limit(2)).all()
            if len(leases) > 1:
                raise ValueError("exact lease required")
            if draft_id is None:
                return  # Original server-generated legacy ID has no existing draft.
            drafts = session.scalars(select(DomainRecord).where(DomainRecord.module == "teacher_lesson_prep",
                DomainRecord.record_type == "draft", DomainRecord.record_key == draft_id, DomainRecord.owner_id == subject)
                .execution_options(populate_existing=True).with_for_update().limit(2)).all()
            if len(drafts) > 1:
                raise ValueError("exact draft required")
            stored_key = draft_id
            if drafts:
                draft = drafts[0]
                if ((draft.module, draft.record_type, draft.owner_id) != ("teacher_lesson_prep", "draft", subject)
                        or type(draft.record_key) is not str or not 1 <= len(draft.record_key) <= 255):
                    raise ValueError("exact stored draft binding required")
                # Legacy text collations may match a differently cased key.
                # Protect the actual locked row that JsonStore would overwrite.
                stored_key = draft.record_key
            tasks = session.scalars(select(WorkTask).where(WorkTask.owner_subject == subject,
                WorkTask.lesson_draft_id.in_((draft_id, stored_key))).execution_options(populate_existing=True).with_for_update().limit(2)).all()
            if tasks:
                raise WorkAuthorizationError("LINKED_LEGACY_WRITE_CONFLICT", 409)
    except WorkAuthorizationError:
        raise
    except Exception:
        raise WorkAuthorizationError("TEACHER_WORK_SCHEMA_UNAVAILABLE", 503) from None
