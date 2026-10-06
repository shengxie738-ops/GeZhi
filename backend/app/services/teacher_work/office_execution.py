"""Owned hard-bounded Office subprocess; children have no SQL/storage/AI ports."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from datetime import datetime
from uuid import UUID
from app.schemas.teacher_work import BODY_LIMIT, PackageVersionDTO, ValidationSummary
from app.services.teacher_work.exporters.validation import FILE_CAP


class OfficeTerminationUnknown(RuntimeError):
    """No receipt proving the owned child exited; never authorize early retry."""


def _stop(child):
    try:
        if child.poll() is None:child.kill()
        child.communicate(timeout=5)
    except Exception:
        try:stopped=child.poll() is not None
        except Exception:stopped=False
        if not stopped:raise OfficeTerminationUnknown('OFFICE_TERMINATION_UNKNOWN') from None


def build_validated_office(kind,version,*,timeout_seconds=30):
    if kind not in ('pptx','docx') or type(version) is not PackageVersionDTO or not 0<timeout_seconds<=30:
        raise ValueError('INVALID_EXPORT_INPUT')
    payload=version.model_dump_json().encode('utf-8')
    if len(payload)>BODY_LIMIT:raise ValueError('INVALID_EXPORT_INPUT')
    backend=str(Path(__file__).resolve().parents[3])
    try:
        child=subprocess.Popen([sys.executable,'-B','-m','app.services.teacher_work.office_execution',kind],
            stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            env={'PATH':os.defpath,'PYTHONPATH':backend,'LANG':'C.UTF-8'},start_new_session=True)
    except OSError:raise ValueError('OFFICE_EXECUTION_FAILED') from None
    try:
        try: output,_=child.communicate(payload,timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _stop(child)
            raise ValueError('OFFICE_STAGE_TIMEOUT') from None
        except OSError:
            _stop(child)
            raise ValueError('OFFICE_EXECUTION_FAILED') from None
        if child.returncode!=0 or len(output)>FILE_CAP+65536:raise ValueError('OFFICE_EXECUTION_FAILED')
        header,raw=output.split(b'\n',1)
        verdict=json.loads(header)
        if 'error' in verdict:
            code=verdict['error']
            raise ValueError(code if type(code) is str and re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}',code) else 'OFFICE_EXECUTION_FAILED')
        summary=ValidationSummary.model_validate_json(json.dumps(verdict['validation']))
        if not summary.valid or not 0<len(raw)<=FILE_CAP:raise ValueError('INVALID_OFFICE_PACKAGE')
        return raw,summary
    finally:
        if child.poll() is None:
            _stop(child)


def _decode_version(payload):
    # Immutable array prevalidators enter Python strict mode. Reconstruct only
    # declared UUID/date fields; never disable strict validation or drop extras.
    from app.schemas.teacher_work import LessonSnapshot, SlideSnapshot, EvidenceSnapshotDTO
    value=json.loads(payload)
    for name in ('version_id','task_id','run_id','base_version_id'):
        if value.get(name) is not None:value[name]=UUID(value[name])
    value['created_at']=datetime.fromisoformat(value['created_at'].replace('Z','+00:00'))
    value['lesson']=LessonSnapshot.model_validate(value['lesson'])
    pages=[]
    for page in value['slides']:
        page['evidence_refs']=tuple(UUID(ref) for ref in page['evidence_refs'])
        pages.append(SlideSnapshot.model_validate(page))
    value['slides']=tuple(pages)
    evidence=[]
    for item in value['source_snapshots']:
        for name in ('evidence_id','task_id','ref_id'):
            if item.get(name) is not None:item[name]=UUID(item[name])
        item['acquired_at']=datetime.fromisoformat(item['acquired_at'].replace('Z','+00:00'))
        evidence.append(EvidenceSnapshotDTO.model_validate(item))
    value['source_snapshots']=tuple(evidence)
    return PackageVersionDTO.model_validate(value)


def _child(kind):
    from app.schemas.teacher_work import SlideModel
    from app.services.teacher_work.exporters.theme import ThemeVersion
    from app.services.teacher_work.exporters.validation import validate_office_bytes
    try:
        payload=sys.stdin.buffer.read(BODY_LIMIT+1)
        if len(payload)>BODY_LIMIT:raise ValueError('INVALID_EXPORT_INPUT')
        version=_decode_version(payload)
        if kind=='pptx':
            from app.services.teacher_work.exporters.pptx import build_pptx
            raw=build_pptx(SlideModel(slides=version.slides),ThemeVersion())
        elif kind=='docx':
            from app.services.teacher_work.exporters.docx import build_docx
            raw=build_docx(version.lesson)
        else:raise ValueError('INVALID_EXPORT_INPUT')
        verdict=validate_office_bytes(kind,raw,version)
        if not verdict.valid:raise ValueError(verdict.checks[0])
        header={'validation':verdict.model_dump(mode='json')}
    except Exception as error:
        code=str(error) if type(error) is ValueError and re.fullmatch(r'[A-Z][A-Z0-9_]{0,63}',str(error)) else 'OFFICE_EXECUTION_FAILED'
        raw=b'';header={'error':code}
    sys.stdout.buffer.write(json.dumps(header,ensure_ascii=False,separators=(',',':')).encode('utf-8')+b'\n'+raw)


if __name__=='__main__':_child(sys.argv[1])
