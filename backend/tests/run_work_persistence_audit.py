"""Explicit subprocess-only bounded Work audit, synthetic SQLite and no network.

Does not launch app.main, migrations, MySQL, providers or the default test suite.
"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--report-json', type=Path)
parser.add_argument('--source-root', type=Path, default=HERE.parent)
parser.add_argument('--child', action='store_true', help=argparse.SUPPRESS)
parser.add_argument('--deletion-probe', action='store_true', help='Run the bounded expected-failure deleted-key proof separately')
parser.add_argument('--race-probe', action='store_true', help='Run the bounded expected-failure concurrency proof separately')
args = parser.parse_args()
source = args.source_root.resolve()
assert (source/'app/api/endpoints/chat.py').is_file()
if not args.child:
    with tempfile.TemporaryDirectory(prefix='gezhi-work-persistence-') as cwd:
        environment = {'PATH': '/usr/bin:/bin', 'HOME': cwd, 'PYTHONDONTWRITEBYTECODE': '1',
            'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1', 'APP_SECRET_KEY': 'synthetic-audit-key', 'DB_PASS': '',
            **{key:'synthetic-unused' for key in ('RAGFLOW_API_KEY','RAGFLOW_BASE_URL','RAGFLOW_AGENT_ID',
                'RAGFLOW_CHAT_ID','RAGFLOW_DATASET_ID','RAGFLOW_PUBLIC_DATASET_IDS','OPENAI_API_KEY','OPENAI_API_BASE')}}
        command = [sys.executable, str(Path(__file__).resolve()), '--child', '--source-root', str(source)]
        if args.report_json: command.extend(['--report-json', str(args.report_json.resolve())])
        if args.race_probe: command.append('--race-probe')
        if args.deletion_probe: command.append('--deletion-probe')
        result = subprocess.run(command, cwd=cwd, env=environment)
    raise SystemExit(result.returncode)

sys.path.insert(0, str(source))
import os
os.environ['GEZHI_WORK_AUDIT_SOURCE']=str(source)
import socket

def blocked(*args, **kwargs):
    raise AssertionError('Network/DNS is forbidden in the Work persistence audit')
for name in ('connect','connect_ex'):
    setattr(socket.socket,name,blocked)
socket.create_connection = socket.getaddrinfo = blocked

# Pin namespace-package resolution before pytest adds the candidate test path.
# This matters for independent baseline replay with --source-root.
import app
app.__path__ = [str(source/'app')]
from app.api import deps
from app.services import chat_history
assert Path(deps.__file__).resolve().is_relative_to(source)
assert Path(chat_history.__file__).resolve().is_relative_to(source)

import pytest
selector = str(HERE/'native_work_persistence_contracts.py')
files = ([selector+'::test_concurrent_paper_replay_returns_one_pair'] if args.race_probe else
         [selector+'::test_deleted_paper_key_never_recreates_deleted_history'] if args.deletion_probe else
         [selector, str(HERE/'test_student_work_capabilities.py'), str(HERE/'test_student_work_skills.py')])
options = []
status = pytest.main([*files,*options,'-q','-o','cache_dir='+str(Path.cwd()/'.pytest_cache')])
inputs = []
for name,module in sorted(sys.modules.items()):
    if name.startswith('app.') and getattr(module,'__file__',None):
        p=Path(module.__file__).resolve()
        assert p.is_relative_to(source), 'Mixed app input: '+str(p)
        b=p.read_bytes()
        inputs.append({'module':name,'path':str(p.relative_to(source)),
            'git_blob_sha':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(),
            'sha256':hashlib.sha256(b).hexdigest()})
for name in ('app/api/endpoints/chat.py','app/api/endpoints/student_work.py','migrations/v20261007_chat_batch_receipts.py'):
    if not (source/name).is_file(): continue
    p=source/name; b=p.read_bytes()
    inputs.append({'module':'source-extracted-or-directly-verified','path':name,
        'git_blob_sha':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest(), 'sha256':hashlib.sha256(b).hexdigest()})
if args.report_json:
    args.report_json.write_text(json.dumps({'exit_code':int(status),'db':'temporary file SQLite',
        'http':'source-extracted chat batch/history/delete/clear/selection handlers and assembled student capabilities router',
        'teacher':'actual SQL repository with test-owned current-account authorization/namespace adapter; assembled production router remains closed on SQLite',
        'not_verified':['full app','MySQL row locking/concurrency','live provider','production data','account incarnation'],
        'inputs':inputs},indent=2)+'\n')
raise SystemExit(status)
