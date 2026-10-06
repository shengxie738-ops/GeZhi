"""Offline integrity of retained original native HTTP download bytes."""
import base64
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from zipfile import ZipFile

import pytest

FIXTURES = Path(__file__).parent / 'fixtures'
SOURCE = 'teacher_work_private_exports_http_contract.native.json'
COMPANION = 'teacher_work_private_exports_http_original_bytes.native.json'
SOURCE_SHA = 'fb9d5699b5795699399719df7a0d1f02959737578be0be9cb735afebebc0b71a'
COMPANION_SHA = '9a8b5e2761b52bccbf085959832267c03f7bee69be34a1852789e951c7faa6e8'
PAYLOADS = {
    'pptx': (49387, 'e64917953724cb5afa9cda8f3a96d5564f2ce4ff9602ba5c3f86bceba46c3daf'),
    'docx': (34865, '94fb8bdeb52d642eb28fa2273539a7383e12f4fa10597326a370df2b3a7bff1f'),
}


def load(name):
    return json.loads((FIXTURES / name).read_text(encoding='utf-8'))


def test_original_bytes_match_immutable_capture_and_exact_headers():
    assert sha256((FIXTURES / SOURCE).read_bytes()).hexdigest() == SOURCE_SHA
    assert sha256((FIXTURES / COMPANION).read_bytes()).hexdigest() == COMPANION_SHA
    source, companion = load(SOURCE), load(COMPANION)
    assert len(source['examples']) == 137
    captured = {e['name']: e for e in source['examples'] if 'binary' in e}
    included = {e['case_id']: e for e in companion['examples']}
    omitted = {e['case_id']: e for e in companion['omitted_examples']}
    assert len(captured) == 13 and len(included) == len(companion['examples']) == 12
    assert set(omitted) == {'access_flags_tampering_and_historical_download-13'}
    assert not set(included) & set(omitted) and set(included) | set(omitted) == set(captured)
    assert companion['provenance']['source_fixture_sha256'] == SOURCE_SHA
    assert companion['provenance']['backend_commit'] == 'f5ddac341f18f3d50b913373d29e760e4111c3f7'
    assert companion['provenance']['regenerated'] is False
    assert companion['provenance']['new_database_run'] is False
    assert set(companion['payloads']) == {value[1] for value in PAYLOADS.values()}
    for case_id, example in included.items():
        original = captured[case_id]
        assert example['request'] == original['request']
        assert example['response'] == original['response']
        assert example['response']['status'] == 200
        assert {k: example['original_evidence'][k] for k in original['evidence']} == original['evidence']
        assert example['sha256'] == example['payload_sha256'] == original['binary']['sha256']
        assert example['byte_size'] == original['binary']['byte_size']
        assert example['response']['headers']['content-length'] == str(example['byte_size'])
        payload = companion['payloads'][example['payload_sha256']]
        raw = base64.b64decode(payload['base64'], validate=True)
        assert len(raw) == example['byte_size'] and sha256(raw).hexdigest() == example['sha256']
    assert omitted[next(iter(omitted))]['captured_binary'] == captured[next(iter(omitted))]['binary']


@pytest.mark.parametrize('kind', ['pptx', 'docx'])
def test_original_office_bytes_pass_crc_and_captured_version_validation(kind):
    from app.schemas.teacher_work import PackageVersionDTO
    from app.services.teacher_work.exporters.validation import validate_office_bytes
    size, digest = PAYLOADS[kind]
    payload = load(COMPANION)['payloads'][digest]
    raw = base64.b64decode(payload['base64'], validate=True)
    assert payload['kind'] == kind and payload['byte_size'] == size and payload['sha256'] == digest
    assert len(raw) == size and sha256(raw).hexdigest() == digest
    assert base64.b64encode(raw).decode('ascii') == payload['base64']
    with ZipFile(BytesIO(raw)) as archive:
        assert archive.testzip() is None
        assert ('ppt/presentation.xml' if kind == 'pptx' else 'word/document.xml') in archive.namelist()
        for name in archive.namelist():
            archive.read(name)
    created = next(e for e in load(SOURCE)['examples'] if e['name'] == 'real_private_package_create_and_download-2')
    version = PackageVersionDTO.model_validate_json(json.dumps(created['response']['body']['data']['version']))
    assert validate_office_bytes(kind, raw, version).valid
