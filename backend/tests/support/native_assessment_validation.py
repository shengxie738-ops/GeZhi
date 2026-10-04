"""Test-owned finite native validation admission, never production activation.

Nothing here starts MySQL, creates/migrates/seeds a schema, reads credentials, or
installs an override in a production app. A separately reviewed native launcher
must provide its exact frozen manifest and an already authorized Engine. The
source/synthetic suite exercises only a genuine SQLite refusal of this factory.
"""
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import importlib
import json
from pathlib import Path
import re
from types import CodeType
from uuid import UUID

from fastapi import FastAPI, HTTPException
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.pool import NullPool

from app.models.user_account import UserAccount
from app.models.teaching import Course, Offering, TeachingRole, Enrollment, WriteReceipt, AccessEvent, RosterPreview
from app.services.teaching.schema import DatabaseIdentity, B1_CONTRACT_HASH, b1_tables, inspect_teaching_schema
from app.services.teaching.assessment_schema import B2_CONTRACT_HASH, b2_tables, inspect_assessment_schema
from app.services.teaching.sessions import B2RequestOwner, open_b2_teaching_session, open_teaching_session
from app.services.teaching.types import ASSESSMENT_WRITE_ACTIONS, ScopeRef, TeachingAction, TeachingPolicyInputs, WriteIntent

# Exact relevant execution/source contract. This inventory helper is not an
# approval: the launcher must use the separately reviewed frozen values.
CODE_PATHS = (
    'backend/app/api/endpoints/teaching.py', 'backend/app/api/endpoints/teaching_assessment.py',
    'backend/app/core/config.py', 'backend/app/core/database.py', 'backend/app/core/security.py',
    'backend/app/models/user_account.py', 'backend/app/models/teaching.py',
    'backend/app/models/teaching_assessment.py', 'backend/app/models/teaching_schema.py',
    'backend/app/schemas/teaching.py', 'backend/app/schemas/teaching_assessment.py',
    'backend/app/services/current_identity.py', 'backend/app/services/teaching/access.py',
    'backend/app/services/teaching/assessment_access.py', 'backend/app/services/teaching/assessment_schema.py',
    'backend/app/services/teaching/assessment_types.py', 'backend/app/services/teaching/assessment_writes.py',
    'backend/app/services/teaching/assignments.py', 'backend/app/services/teaching/assessment_pagination.py',
    'backend/app/services/teaching/policy.py', 'backend/app/services/teaching/releases.py',
    'backend/app/services/teaching/schema.py', 'backend/app/services/teaching/sessions.py',
    'backend/app/services/teaching/submissions.py', 'backend/app/services/teaching/types.py',
    'backend/app/services/teaching/writes.py',
    'backend/tests/support/native_assessment_validation.py',
    'backend/tests/test_teaching_native_assessment_validation.py',
)
_REPO = Path(__file__).resolve().parents[3]
_TABLES = (UserAccount.__table__, *b1_tables(), *b2_tables())
SEED_TABLE_NAMES = tuple(table.name for table in _TABLES)
_DIGEST = re.compile(r'[0-9a-f]{64}\Z', re.ASCII)


def _deny(reason='native_validation_unavailable'):
    raise HTTPException(503, reason)


def current_code_contract():
    return tuple((name, sha256((_REPO/name).read_bytes()).hexdigest()) for name in CODE_PATHS)


@dataclass(frozen=True)
class SeedInventory:
    table: str
    primary_keys: tuple[tuple, ...]
    row_digest: str

    def __post_init__(self):
        if (self.table not in SEED_TABLE_NAMES or type(self.primary_keys) is not tuple
                or any(type(key) is not tuple or any(type(value) not in {str, int} for value in key) for key in self.primary_keys)
                or len(set(self.primary_keys)) != len(self.primary_keys)
                or not isinstance(self.row_digest, str) or not _DIGEST.fullmatch(self.row_digest)):
            raise ValueError('exact immutable seed inventory required')


@dataclass(frozen=True)
class NativeValidationManifest:
    run_id: str
    identity: DatabaseIdentity
    expires_at: datetime
    policy: TeachingPolicyInputs
    scopes: tuple[ScopeRef, ...]
    actor_id: str
    learner_ids: tuple[str, ...]
    code_contract: tuple[tuple[str, str], ...]
    seed_inventory: tuple[SeedInventory, ...]
    b1_contract_hash: str = B1_CONTRACT_HASH
    b2_contract_hash: str = B2_CONTRACT_HASH
    actions: frozenset[TeachingAction] = ASSESSMENT_WRITE_ACTIONS

    def __post_init__(self):
        if not isinstance(self.run_id, str):
            raise ValueError('an exact UUID4 run identifier is required')
        run = UUID(self.run_id)
        if str(run) != self.run_id or run.version != 4:
            raise ValueError('an exact UUID4 run identifier is required')
        prefix = 'nv_'+run.hex[:12]+'_'
        institution = 'nv-'+run.hex[:16]
        if (type(self.identity) is not DatabaseIdentity or self.identity.schema_name != 'nv_'+run.hex[:16]
                or type(self.policy) is not TeachingPolicyInputs or self.policy.institution_id != institution
                or not self.policy.enabled or not self.policy.assignments_enabled
                or self.policy.feedback_enabled or self.policy.revisions_enabled
                or self.policy.generation != 'native-'+self.run_id
                or self.policy.trusted_delegations_json != '{}'):
            raise ValueError('one finite synthetic native identity/policy is required')
        if (not isinstance(self.expires_at, datetime) or self.expires_at.tzinfo is None
                or self.expires_at.utcoffset().total_seconds() != 0):
            raise ValueError('an exact UTC run expiry is required')
        if (type(self.scopes) is not tuple or not self.scopes or len(set(self.scopes)) != len(self.scopes)
                or any(type(scope) is not ScopeRef or scope.kind != 'offering'
                       or scope.institution_id != institution for scope in self.scopes)):
            raise ValueError('exact synthetic offering scopes are required')
        if (not isinstance(self.actor_id, str) or not self.actor_id.startswith(prefix)
                or type(self.learner_ids) is not tuple or not self.learner_ids
                or tuple(sorted(set(self.learner_ids))) != self.learner_ids
                or any(not isinstance(value, str) or not value.startswith(prefix) for value in self.learner_ids)
                or self.actor_id in self.learner_ids):
            raise ValueError('only the exact synthetic actor/learner inventory is allowed')
        try:
            roster = json.loads(self.policy.trusted_roster_json)
        except (ValueError, TypeError):
            raise ValueError('an exact immutable synthetic roster is required') from None
        if roster != {self.actor_id:list(self.learner_ids)}:
            raise ValueError('the policy roster must equal the synthetic seed inventory')
        if (type(self.code_contract) is not tuple or tuple(name for name, _ in self.code_contract) != CODE_PATHS
                or any(not isinstance(digest, str) or not _DIGEST.fullmatch(digest) for _, digest in self.code_contract)):
            raise ValueError('the complete exact reviewed code contract is required')
        if (type(self.seed_inventory) is not tuple
                or tuple(item.table for item in self.seed_inventory) != SEED_TABLE_NAMES
                or any(type(item) is not SeedInventory for item in self.seed_inventory)):
            raise ValueError('the complete exact immutable seed inventory is required')
        if (type(self.actions) is not frozenset or self.actions != ASSESSMENT_WRITE_ACTIONS
                or self.b1_contract_hash != B1_CONTRACT_HASH or self.b2_contract_hash != B2_CONTRACT_HASH):
            raise ValueError('only the unchanged finite B2/code/schema contracts are allowed')


def _source_code(function, relative_path, qualified_name):
    """Reject in-memory substitutions without importing/executing source anew."""
    path = (_REPO/relative_path).resolve()
    if (not callable(function) or getattr(function, '__qualname__', None) != qualified_name
            or not hasattr(function, '__code__') or Path(function.__code__.co_filename).resolve() != path):
        _deny('native_code_contract_changed')
    compiled = compile(path.read_bytes(), function.__code__.co_filename, 'exec')
    def find(code):
        for item in code.co_consts:
            if isinstance(item, CodeType):
                if item.co_qualname == qualified_name:
                    return item
                value = find(item)
                if value is not None:
                    return value
        return None
    expected = find(compiled)
    if expected is None or expected != function.__code__:
        _deny('native_code_contract_changed')


def _unsubstituted_contract():
    targets = (
        ('app.services.teaching.access','require_teaching_schema','backend/app/services/teaching/schema.py','require_teaching_schema'),
        ('app.services.teaching.assessment_access','require_assessment_schema','backend/app/services/teaching/assessment_schema.py','require_assessment_schema'),
        ('app.services.teaching.writes','_require_write_safety','backend/app/services/teaching/writes.py','_require_write_safety'),
        ('app.services.teaching.writes','_require_transaction','backend/app/services/teaching/writes.py','_require_transaction'),
        ('app.services.teaching.writes','_server_clock','backend/app/services/teaching/writes.py','_server_clock'),
        ('app.services.current_identity','resolve_current_account','backend/app/services/current_identity.py','resolve_current_account'),
        ('app.api.endpoints.teaching','resolve_current_account','backend/app/services/current_identity.py','resolve_current_account'),
        ('app.services.teaching.access','load_current_account','backend/app/services/current_identity.py','load_current_account'),
        ('app.api.endpoints.teaching','get_teaching_account','backend/app/api/endpoints/teaching.py','get_teaching_account'),
        ('app.api.endpoints.teaching_assessment','get_b2_request_account','backend/app/api/endpoints/teaching_assessment.py','get_b2_request_account'),
    )
    for module, name, path, qualified in targets:
        _source_code(getattr(importlib.import_module(module), name), path, qualified)
    for module, class_name in (('assignments','_AssignmentOperation'), ('releases','_ReleaseOperation'), ('submissions','_SubmissionOperation')):
        cls = getattr(importlib.import_module('app.services.teaching.'+module), class_name)
        for method in ('collect_locks','validate_new','apply_new'):
            _source_code(getattr(cls, method), 'backend/app/services/teaching/'+module+'.py', class_name+'.'+method)


def _identity(connection):
    row = connection.execute(text('SELECT DATABASE(), @@server_uuid, @@datadir, @@socket')).one()
    return DatabaseIdentity(*row)


def _verify_connection(connection, manifest):
    if connection.dialect.name != 'mysql' or _identity(connection) != manifest.identity:
        _deny('native_identity_mismatch')
    if not inspect_teaching_schema(connection).ready or not inspect_assessment_schema(connection).ready:
        _deny('native_schema_unverified')
    if set(inspect(connection).get_table_names()) != set(SEED_TABLE_NAMES):
        _deny('native_seed_inventory_mismatch')


def inventory_on(connection):
    """Read-only complete inventory, for a separately approved seed manifest."""
    from app.services.teaching.writes import _json
    from app.services.teaching.access import _utc
    result = []
    for table in _TABLES:
        rows = [dict(row) for row in connection.execute(table.select()).mappings()]
        values = [{name:_utc(value) if isinstance(value, datetime) else value
                   for name, value in row.items()} for row in rows]
        values.sort(key=lambda row: _json(tuple(row[column.name] for column in table.primary_key)))
        keys = tuple(tuple(row[column.name] for column in table.primary_key) for row in values)
        result.append(SeedInventory(table.name, keys, sha256(_json(values).encode()).hexdigest()))
    return tuple(result)


def _verify_fresh_seed(connection, manifest):
    if inventory_on(connection) != manifest.seed_inventory:
        _deny('native_seed_inventory_mismatch')
    rows = {table.name:[dict(row) for row in connection.execute(table.select()).mappings()] for table in _TABLES}
    empty = {table.name for table in b2_tables()} | {WriteReceipt.__tablename__, AccessEvent.__tablename__, RosterPreview.__tablename__}
    if any(rows[name] for name in empty):
        _deny('native_seed_not_fresh')
    accounts = rows[UserAccount.__tablename__]
    if ({row['username'] for row in accounts} != {manifest.actor_id, *manifest.learner_ids}
            or any(row['role'] != ('teacher' if row['username'] == manifest.actor_id else 'student') for row in accounts)):
        _deny('native_seed_inventory_mismatch')
    institution = manifest.policy.institution_id
    courses, offerings = rows[Course.__tablename__], rows[Offering.__tablename__]
    scopes = {scope.id for scope in manifest.scopes}
    if (not courses or {row['id'] for row in offerings} != scopes
            or any(row['institution_id'] != institution or row['source_teacher_id'] != manifest.actor_id for row in courses)
            or any(row['institution_id'] != institution or row['course_id'] not in {c['id'] for c in courses}
                   or row['state'] != 'active' for row in offerings)):
        _deny('native_seed_inventory_mismatch')
    roles, enrollments = rows[TeachingRole.__tablename__], rows[Enrollment.__tablename__]
    if ({(row['offering_id'],row['subject_id']) for row in roles} != {(scope,manifest.actor_id) for scope in scopes}
            or {(row['offering_id'],row['student_id']) for row in enrollments}
                != {(scope,learner) for scope in scopes for learner in manifest.learner_ids}
            or any(row['institution_id'] != institution or row['status'] != 'active' for row in (*roles,*enrollments))):
        _deny('native_seed_inventory_mismatch')


class NativeValidationRun:
    """Revocable engine/run/identity/code/policy/seed-bound test capability."""
    _CONSTRUCTION = object()

    def __init__(self, engine, manifest, token):
        if token is not self._CONSTRUCTION:
            raise TypeError('use the reviewed native validation factory')
        self._engine, self._manifest = engine, manifest
        self.closed = False
        self.owners = []
        self.observations = []

    @property
    def engine(self):
        return self._engine

    @property
    def manifest(self):
        return self._manifest

    @classmethod
    def open(cls, engine, manifest):
        # A real SQLite negative must precede every schema/identity/admission SQL.
        if not isinstance(engine, Engine) or engine.dialect.name != 'mysql':
            _deny()
        # A new SQLAlchemy wrapper alone does not imply a new DBAPI connection.
        # Native observers must never reuse a returned writer connection.
        if type(engine.pool) is not NullPool:
            _deny('native_observer_pool_unverified')
        if type(manifest) is not NativeValidationManifest:
            _deny()
        if (engine.url.database != manifest.identity.schema_name
                or engine.url.query.get('unix_socket') != manifest.identity.socket):
            _deny('native_identity_mismatch')
        run = cls(engine, manifest, cls._CONSTRUCTION)
        run.require_open()
        with engine.connect() as connection:
            _verify_connection(connection, manifest)
            _verify_fresh_seed(connection, manifest)
        return run

    def require_open(self):
        if self.closed or datetime.now(timezone.utc) >= self.manifest.expires_at:
            _deny('native_run_closed')
        if type(self.engine.pool) is not NullPool:
            _deny('native_observer_pool_unverified')
        if current_code_contract() != self.manifest.code_contract:
            _deny('native_code_contract_changed')
        _unsubstituted_contract()

    def _new_owner(self, session, connection):
        self.require_open()
        _verify_connection(connection, self.manifest)
        owner = NativeValidationOwner(self, session, connection, self._CONSTRUCTION)
        self.owners.append(owner)
        return owner

    @contextmanager
    def request_owner(self):
        self.require_open()
        with open_b2_teaching_session(self.engine, policy_inputs=self.manifest.policy,
                                     owner_factory=self._new_owner) as owner:
            yield owner

    @contextmanager
    def read_session(self):
        self.require_open()
        with open_teaching_session(self.engine) as db:
            _verify_connection(db.connection(), self.manifest)
            db.info['teaching_policy_provider'] = lambda: self.manifest.policy
            yield db

    def close(self):
        self.closed = True
        for owner in self.owners:
            owner.close(preserve_exception=True)


class NativeValidationOwner(B2RequestOwner):
    """Constructed only by this test factory; rejects B1 and unknown actions."""
    def __init__(self, run, session, connection, token):
        if (type(run) is not NativeValidationRun or token is not run._CONSTRUCTION
                or connection.engine is not run.engine):
            _deny('invalid_native_owner')
        self.run = run
        super().__init__(session, connection)
        # Test-only native diagnostics, before kernel locks/staging/t0/t1.
        # Never query the writer after final admission to obtain an identity.
        self.native_connection_id = connection.execute(text('SELECT CONNECTION_ID()')).scalar_one()
        if type(self.native_connection_id) is not int or self.native_connection_id <= 0:
            _deny('native_connection_identity_unavailable')

    def require_admission(self, session, intent, scope, mutation):
        self.run.require_open()
        self._require_bound(session)
        manifest = self.run.manifest
        if (self not in self.run.owners or type(intent) is not WriteIntent
                or intent.action not in manifest.actions or intent.action not in ASSESSMENT_WRITE_ACTIONS
                or scope != intent.scope or scope not in manifest.scopes
                or intent.actor_id not in {manifest.actor_id, *manifest.learner_ids}
                or self.pending is not None or self.connection.engine is not self.run.engine
                or self.connection.dialect.name != 'mysql'
                or session.info.get('teaching_policy_provider', lambda:None)() is not manifest.policy):
            _deny('invalid_native_owner')
        from app.services.teaching import assignments, releases, submissions, writes
        classes = {
            TeachingAction.ASSIGNMENT_CREATE:assignments._AssignmentOperation,
            TeachingAction.ASSIGNMENT_UPDATE:assignments._AssignmentOperation,
            TeachingAction.ASSIGNMENT_PRIVATE_UPDATE:assignments._AssignmentOperation,
            TeachingAction.ASSIGNMENT_FREEZE:assignments._AssignmentOperation,
            TeachingAction.RELEASE_PREVIEW:releases._ReleaseOperation,
            TeachingAction.RELEASE_CREATE:releases._ReleaseOperation,
            TeachingAction.SUBMISSION_CREATE:submissions._SubmissionOperation,
        }
        if (type(mutation) is not classes[intent.action]
                or set(vars(mutation)) != (set() if intent.action == TeachingAction.SUBMISSION_CREATE else {'purpose','action','shape_type'})
                or getattr(mutation, 'action', intent.action) != intent.action):
            _deny('invalid_native_operation')
        writes._require_transaction(session)


def native_asgi_app(run):
    """Isolated native app: B2 owner override plus dedicated read/recovery DB.

    No identity/service/schema/clock/transaction/gate substitutions. Mounting
    ordinary B1 routes does not admit B1: they retain their hard-closed execution.
    """
    if type(run) is not NativeValidationRun:
        raise TypeError('one factory-verified native validation run is required')
    run.require_open()
    from app.api.endpoints import teaching, teaching_assessment
    app = FastAPI()
    app.include_router(teaching.router, prefix='/api')
    app.include_router(teaching_assessment.router, prefix='/api')
    async def owner_dependency():
        with run.request_owner() as owner:
            yield owner
    async def read_dependency():
        with run.read_session() as db:
            yield db
    app.dependency_overrides[teaching_assessment.get_b2_write_owner] = owner_dependency
    app.dependency_overrides[teaching.get_teaching_db] = read_dependency
    return app
