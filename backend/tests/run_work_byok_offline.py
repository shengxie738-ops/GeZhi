#!/usr/bin/env python3
"""Run only reviewed suites with clean environment, pinned imports and I/O fences."""
from __future__ import annotations
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / 'docs/work-byok-source-manifest.json'


def _load_manifest():
    return json.loads(MANIFEST.read_text(encoding='utf-8'))


def _validate_nodes(nodes, manifest):
    approved = set(manifest['reviewed_python_suites'])
    if not nodes:
        raise ValueError('OFFLINE_TEST_SELECTION_REQUIRED')
    for node in nodes:
        path, *selector = node.split('::')
        if path not in approved or not (ROOT / path).is_file() or any(not s or not s.replace('_', '').isalnum() for s in selector):
            raise ValueError('OFFLINE_TEST_NOT_REGISTERED')
    return nodes


def _pins(manifest):
    mismatches = []
    for entry in manifest['source_pins']:
        p = ROOT / entry['path']
        if not p.is_file() or not p.resolve().is_relative_to(ROOT) or hashlib.sha256(p.read_bytes()).hexdigest() != entry['sha256']:
            mismatches.append(entry['path'])
    return mismatches


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--test', action='append', default=[])
    parser.add_argument('--all-reviewed-byok', action='store_true')
    parser.add_argument('--report-json')
    parser.add_argument('--_child', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    manifest = _load_manifest()
    if args.all_reviewed_byok and args.test:
        parser.error('choose --test or --all-reviewed-byok')
    try:
        nodes = _validate_nodes(manifest['reviewed_python_suites'] if args.all_reviewed_byok else args.test, manifest)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    mismatches = _pins(manifest)
    if mismatches:
        print('OFFLINE_SOURCE_PIN_MISMATCH', file=sys.stderr)
        return 2
    if not args._child:
        try:
            importlib.metadata.version('pytest')
        except importlib.metadata.PackageNotFoundError:
            print('OFFLINE_ENVIRONMENT_GATE: pytest missing', file=sys.stderr)
            return 3
        report_path = Path(args.report_json).resolve() if args.report_json else None
        with tempfile.TemporaryDirectory(prefix='gezhi-byok-offline-') as temp:
            temp = Path(temp)
            (temp / 'home').mkdir()
            child_report = temp / 'report.json'
            env = {'PATH': os.defpath, 'HOME': str(temp / 'home'), 'TMPDIR': str(temp),
                   'LANG': 'C.UTF-8', 'LC_ALL': 'C.UTF-8', 'PYTEST_DISABLE_PLUGIN_AUTOLOAD': '1',
                   'WORK_BYOK_OFFLINE_CHILD': '1', 'PYTHONDONTWRITEBYTECODE': '1'}
            command = [sys.executable, '-I', str(Path(__file__).resolve()), '--_child', '--report-json', str(child_report)]
            for node in nodes:
                command += ['--test', node]
            completed = subprocess.run(command, cwd=temp, env=env, capture_output=True, text=True)
            print(completed.stdout, end='')
            print(completed.stderr, end='', file=sys.stderr)
            if child_report.is_file():
                report = json.loads(child_report.read_text())
                if report_path:
                    report_path.parent.mkdir(parents=True, exist_ok=True)
                    report_path.write_text(json.dumps(report, indent=2) + '\n')
            elif report_path:
                report_path.parent.mkdir(parents=True, exist_ok=True)
                report_path.write_text(json.dumps({'status': 'child_failed_before_report', 'exit_code': completed.returncode}) + '\n')
            return completed.returncode
    if os.environ.get('WORK_BYOK_OFFLINE_CHILD') != '1' or Path.cwd().is_relative_to(ROOT) or os.environ.get('PYTEST_DISABLE_PLUGIN_AUTOLOAD') != '1':
        print('OFFLINE_INVALID_CHILD_ENVIRONMENT', file=sys.stderr)
        return 2
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(ROOT / 'backend'))
    sys.path.insert(0, str(ROOT / 'backend/tests/support'))
    # Pytest is imported before the fence so its well-known own runtime can load;
    # no test collection or plugins happen until the fence is installed.
    import pytest
    from work_byok_offline import install_fences, source_report
    install_fences(ROOT, manifest)
    code = int(pytest.main(['-q', '--confcutdir=' + str(ROOT / 'backend/tests'),
                            '--noconftest', '--rootdir=' + str(ROOT), '-c', '/dev/null', '-p', 'no:cacheprovider',
                            '--basetemp=' + str(Path.cwd() / 'pytest'),
                            *[str(ROOT / node.split('::')[0]) + ''.join('::' + s for s in node.split('::')[1:]) for node in nodes]]))
    report = source_report() | {'status': 'passed' if code == 0 else 'failed', 'exit_code': code,
        'tests': nodes, 'interpreter': sys.executable, 'python': sys.version,
        'dependencies': {name: importlib.metadata.version(name) for name in ('pytest', 'pydantic')},
        'manifest_sha256': hashlib.sha256(MANIFEST.read_bytes()).hexdigest(),
        'real_environment_accesses': []}
    if report['unexpected_io'] or report['source_pin_mismatches']:
        code = 1
        report['status'], report['exit_code'] = 'failed', code
    if args.report_json:
        Path(args.report_json).write_text(json.dumps(report, indent=2) + '\n')
    return code


if __name__ == '__main__':
    raise SystemExit(main())
