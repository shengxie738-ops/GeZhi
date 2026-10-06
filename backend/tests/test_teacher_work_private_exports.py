"""Finite real-value export boundaries; native HTTP/MySQL are explicit-only."""
import importlib
import errno
import os
import subprocess
import sys
from pathlib import Path
from uuid import UUID
import pytest

BACKEND = Path(__file__).resolve().parents[1]


def feature(name):
    assert (BACKEND / (name.replace('.', '/') + '.py')).is_file(), 'MISSING_EXPORT_FEATURE:' + name
    return importlib.import_module(name)


def test_strict_package_create_and_fixed_retry_wire():
    m = feature('app.schemas.teacher_work_exports')
    body = dict(approval_id=UUID(int=1), input_revision=2, outline_revision=1,
        outline_digest='a'*64, source_digest='b'*64, expected_revision=3)
    assert m.PrivatePackageCreateRequest.model_validate(body).expected_revision == 3
    for change in ({'owner':'teacher'}, {'format':'pptx'}, {'expected_revision':True}, {'source_digest':'B'*64}):
        with pytest.raises(ValueError): m.PrivatePackageCreateRequest.model_validate(body | change)
    assert m.PrivatePackageRetryRequest.model_validate({'expected_attempt':1}).expected_attempt == 1
    for body in ({}, {'expected_attempt':2}, {'expected_attempt':True}, {'expected_attempt':1,'kind':'pptx'}):
        with pytest.raises(ValueError): m.PrivatePackageRetryRequest.model_validate(body)


def test_local_private_storage_tracks_single_inode_and_refuses_overwrite(tmp_path):
    m = feature('app.services.teacher_work.private_storage')
    root = tmp_path/'private'; root.mkdir()
    storage = m.LocalPrivateStorage(root)
    key = m.storage_key(UUID(int=1), UUID(int=2), 'docx')
    storage.publish(key, b'synthetic-bytes')
    assert storage.read(key) == b'synthetic-bytes'
    assert storage.inventory(UUID(int=1), {key}) == {key:15}
    with pytest.raises(ValueError): storage.publish(key, b'replacement')
    assert storage.read(key) == b'synthetic-bytes'
    storage.remove(key)
    assert storage.inventory(UUID(int=1), {key}) == {key:0}


def test_metadata_path_accepts_safe_absence_and_stable_changed_bytes(tmp_path):
    m=feature('app.services.teacher_work.private_storage')
    root=tmp_path/'private';root.mkdir();storage=m.LocalPrivateStorage(root)
    key=m.storage_key(UUID(int=1),UUID(int=2),'docx')
    storage.check_metadata_path(key,allow_absent_owner=True)
    with pytest.raises(ValueError,match='PRIVATE_STORAGE_UNAVAILABLE'):storage.check_metadata_path(key)
    storage.publish(key,b'committed-original')
    (root/key).write_bytes(b'corrupt')
    storage.check_metadata_path(key)
    (root/key).write_bytes(b'')
    storage.check_metadata_path(key)
    (root/key).unlink()
    storage.check_metadata_path(key)


@pytest.mark.parametrize('unsafe',['owner_symlink','leaf_symlink','hardlink','fifo','directory','oversized','root_replaced'])
def test_metadata_path_refuses_unsafe_existing_entries(tmp_path,unsafe):
    m=feature('app.services.teacher_work.private_storage')
    root=tmp_path/'private';root.mkdir();storage=m.LocalPrivateStorage(root)
    key=m.storage_key(UUID(int=1),UUID(int=2),'docx');owner=root/str(UUID(int=1))
    if unsafe=='root_replaced':
        root.rename(tmp_path/'moved');root.mkdir()
    elif unsafe=='owner_symlink':
        target=tmp_path/'target';target.mkdir();owner.symlink_to(target,target_is_directory=True)
    else:
        owner.mkdir()
        if unsafe=='leaf_symlink':(root/key).symlink_to(tmp_path/'absent')
        elif unsafe=='hardlink':
            target=tmp_path/'target';target.write_bytes(b'unsafe-link');os.link(target,root/key)
        elif unsafe=='fifo':os.mkfifo(root/key)
        elif unsafe=='directory':(root/key).mkdir()
        else:
            with (root/key).open('wb') as file:file.truncate(m.FILE_CAP+1)
    with pytest.raises((ValueError,OSError)) as refused:
        storage.check_metadata_path(key,allow_absent_owner=True)
    if unsafe in ('owner_symlink','leaf_symlink'):
        assert isinstance(refused.value,OSError)
        assert refused.value.errno==(errno.ENOTDIR if unsafe=='owner_symlink' else errno.ELOOP)
    else:
        assert type(refused.value) is ValueError and str(refused.value)=='PRIVATE_STORAGE_UNAVAILABLE'


def test_storage_rejects_static_root_links_unknown_and_double_copies(tmp_path):
    m = feature('app.services.teacher_work.private_storage')
    root=tmp_path/'private';root.mkdir()
    with pytest.raises(ValueError): m.LocalPrivateStorage(root, static_roots=(tmp_path,))
    link=tmp_path/'link';link.symlink_to(root,target_is_directory=True)
    with pytest.raises(ValueError): m.LocalPrivateStorage(link)
    storage=m.LocalPrivateStorage(root)
    key=m.storage_key(UUID(int=1),UUID(int=2),'pptx')
    storage.publish(key,b'actual')
    namespace=root/str(UUID(int=1))
    (namespace/'unknown').write_bytes(b'unknown')
    with pytest.raises(ValueError): storage.inventory(UUID(int=1),{key})
    (namespace/'unknown').unlink()
    (namespace/(Path(key).name+'.tmp')).write_bytes(b'other-copy')
    with pytest.raises(ValueError): storage.inventory(UUID(int=1),{key})
    for invalid in ('../escape','/absolute',key+'/child',str(UUID(int=3))+'/'+Path(key).name):
        with pytest.raises(ValueError): storage.inventory(UUID(int=1),{invalid})


def test_storage_rejects_resolved_public_alias_and_unresolved_symlinks(tmp_path):
    m=feature('app.services.teacher_work.private_storage')
    physical=tmp_path/'physical-public';physical.mkdir()
    private=physical/'private-exports';private.mkdir()
    public=tmp_path/'static';public.symlink_to(physical,target_is_directory=True)
    with pytest.raises(ValueError,match='PRIVATE_STORAGE_UNAVAILABLE'):
        m.LocalPrivateStorage(private,static_roots=(public,))
    safe=tmp_path/'safe-private';safe.mkdir()
    assert m.LocalPrivateStorage(safe,static_roots=(public,)).root==safe
    unresolved=tmp_path/'broken-static';unresolved.symlink_to(tmp_path/'missing-target',target_is_directory=True)
    with pytest.raises(ValueError,match='PRIVATE_STORAGE_UNAVAILABLE'):
        m.LocalPrivateStorage(safe,static_roots=(unresolved,))
    loop=tmp_path/'loop-static';loop.symlink_to(loop,target_is_directory=True)
    with pytest.raises(ValueError,match='PRIVATE_STORAGE_UNAVAILABLE'):
        m.LocalPrivateStorage(safe,static_roots=(loop,))
    # Absent optional public directories have no serving target; still compare
    # their lexical path and every existing ancestor, without requiring them.
    assert m.LocalPrivateStorage(safe,static_roots=(tmp_path/'optional-missing-public',)).root==safe
    mounted=tmp_path/'mounted';(mounted/'a').mkdir(parents=True)
    second_private=mounted/'public'/'private';second_private.mkdir(parents=True)
    deployment=tmp_path/'deployment';deployment.mkdir()
    alias=deployment/'alias';alias.symlink_to(mounted/'a',target_is_directory=True)
    with pytest.raises(ValueError,match='PRIVATE_STORAGE_UNAVAILABLE'):
        m.LocalPrivateStorage(second_private,static_roots=(alias/'..'/'public',))


def test_office_supervisor_returns_real_validated_bytes():
    m=feature('app.services.teacher_work.office_execution')
    from tests.test_teacher_work_exporters import _version, _slides
    version=_version(_slides())
    for kind in ('pptx','docx'):
        raw, verdict=m.build_validated_office(kind,version,timeout_seconds=30)
        assert raw[:2]==b'PK' and verdict.valid
        from app.services.teacher_work.exporters.validation import validate_office_bytes
        assert validate_office_bytes(kind,raw,version).valid


@pytest.mark.parametrize('operation',['read','inventory'])
def test_fifo_storage_entry_is_rejected_without_blocking(tmp_path,operation):
    root=tmp_path/'private';root.mkdir()
    owner=root/str(UUID(int=1));owner.mkdir()
    key=f'{UUID(int=1)}/{UUID(int=2)}.docx'
    os.mkfifo(root/key)
    code='''import sys
from uuid import UUID
from app.services.teacher_work.private_storage import LocalPrivateStorage
s=LocalPrivateStorage(sys.argv[1])
try:
    s.read(sys.argv[2]) if sys.argv[3]=='read' else s.inventory(UUID(int=1),{sys.argv[2]})
except ValueError as e:
    assert str(e)=='PRIVATE_STORAGE_UNAVAILABLE'
else:
    raise AssertionError('FIFO accepted')
'''
    completed=subprocess.run([sys.executable,'-B','-c',code,str(root),key,operation],timeout=2,capture_output=True)
    assert completed.returncode==0,completed.stderr.decode()


@pytest.mark.parametrize('fault',['separate_inode','symlink'])
def test_cleanup_refuses_incoherent_candidates_before_unlink(tmp_path,fault):
    m=feature('app.services.teacher_work.private_storage')
    root=tmp_path/'private';root.mkdir();storage=m.LocalPrivateStorage(root)
    key=m.storage_key(UUID(int=1),UUID(int=2),'docx')
    owner=root/str(UUID(int=1));owner.mkdir()
    temporary=root/(key+'.tmp');temporary.write_bytes(b'staging')
    final=root/key
    if fault=='separate_inode':final.write_bytes(b'final')
    else:final.symlink_to(temporary)
    with pytest.raises(ValueError,match='PRIVATE_STORAGE_UNAVAILABLE'):storage.remove(key)
    assert temporary.read_bytes()==b'staging'
    assert final.exists()


def test_office_timeout_kills_and_joins_owned_actual_child(monkeypatch):
    m=feature('app.services.teacher_work.office_execution')
    from tests.test_teacher_work_exporters import _version,_slides
    children=[];original=subprocess.Popen
    def sleeping(*args,**kwargs):
        child=original([sys.executable,'-B','-c','import time; time.sleep(20)'],**kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(m.subprocess,'Popen',sleeping)
    with pytest.raises(ValueError,match='OFFICE_STAGE_TIMEOUT'):m.build_validated_office('pptx',_version(_slides()),timeout_seconds=.15)
    assert len(children)==1 and children[0].poll() is not None


def test_office_known_spawn_error_is_bounded_failure(monkeypatch):
    m=feature('app.services.teacher_work.office_execution')
    from tests.test_teacher_work_exporters import _version,_slides
    def unavailable(*args,**kwargs):raise OSError('synthetic process unavailable')
    monkeypatch.setattr(m.subprocess,'Popen',unavailable)
    with pytest.raises(ValueError,match='OFFICE_EXECUTION_FAILED'):m.build_validated_office('pptx',_version(_slides()))


def test_exact_package_list_wire_exists_and_is_bounded():
    m=feature('app.schemas.teacher_work_exports')
    assert hasattr(m,'PrivatePackageList'),'MISSING_AUTHENTICATED_PACKAGE_REOPEN_LIST'
    assert set(m.PrivatePackageList.model_fields)=={'task','items','next_before','truncated'}
    assert set(m.PackageListEntry.model_fields)=={'version_id','version_no','run_id','approval_id','created_at','stage','attempt','artifacts'}
    assert set(m.PackageArtifactSummary.model_fields)=={'artifact_id','kind','state','download_available'}


def test_list_consistency_rejects_unbounded_or_incoherent_page():
    from datetime import datetime,timezone
    m=feature('app.schemas.teacher_work_exports')
    from app.schemas.teacher_work import WorkTaskDTO
    task=WorkTaskDTO(task_id=UUID(int=1),owner_subject='synthetic',owner_storage_id=UUID(int=2),title='合成',topic='合成',audience='合成',
        duration_minutes=45,target_slide_count=8,lesson_draft_id='synthetic',input_revision=1,working_revision=1,created_at=datetime.now(timezone.utc),updated_at=datetime.now(timezone.utc))
    artifacts=tuple(m.PackageArtifactSummary(artifact_id=UUID(int=i),kind=kind,state='FAILED',download_available=False) for i,kind in ((3,'pptx'),(4,'docx')))
    first=m.PackageListEntry(version_id=UUID(int=5),version_no=2,run_id=UUID(int=6),approval_id=UUID(int=7),created_at=datetime.now(timezone.utc),stage='FAILED',attempt=1,artifacts=artifacts)
    second=first.model_copy(update={'version_id':UUID(int=8),'version_no':1})
    m.PrivatePackageList(task=task,items=(first,second),next_before=None,truncated=False)
    for items,cursor,truncated in (((first,)*21,None,False),((second,first),None,False),((first,first),None,False),((first,),None,True),((first,),second.version_id,True),((first,),first.version_id,False)):
        with pytest.raises(ValueError):m.PrivatePackageList(task=task,items=items,next_before=cursor,truncated=truncated)
    with pytest.raises(ValueError):m.PackageArtifactSummary(artifact_id=UUID(int=3),kind='pptx',state='PENDING',download_available=True)


def test_unconfirmed_child_termination_is_not_stopped_receipt(monkeypatch):
    m=feature('app.services.teacher_work.office_execution')
    child=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(20)'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL)
    original_kill=child.kill
    try:
        def refuse():raise OSError('synthetic kill unconfirmed')
        monkeypatch.setattr(child,'kill',refuse)
        with pytest.raises(m.OfficeTerminationUnknown,match='OFFICE_TERMINATION_UNKNOWN'):m._stop(child)
        assert child.poll() is None
    finally:
        original_kill();child.communicate(timeout=5)
    assert child.poll() is not None


def test_capabilities_require_exact_false_keys_and_known_reasons():
    m=feature('app.schemas.teacher_work_exports')
    good={'create':False,'read':True,'retry':False,'download':True,'storage_configured':True,
        'reasons':{'create':'materials_unavailable','retry':'materials_unavailable'}}
    m.PrivatePackageCapabilities.model_validate(good)
    for reasons in ({'create':'materials_unavailable'},{**good['reasons'],'read':'materials_unavailable'},{'create':'unknown','retry':'materials_unavailable'}):
        with pytest.raises(ValueError):m.PrivatePackageCapabilities.model_validate(good|{'reasons':reasons})


def test_summary_can_report_ready_bytes_unavailable_but_never_nonready_downloadable():
    m=feature('app.schemas.teacher_work_exports')
    body={'artifact_id':UUID(int=1),'kind':'pptx','state':'READY','download_available':False}
    assert m.PackageArtifactSummary.model_validate(body).download_available is False
    for state in ('PENDING','BUILDING','VALIDATING','FAILED'):
        with pytest.raises(ValueError):m.PackageArtifactSummary.model_validate(body|{'state':state,'download_available':True})


def test_missing_leaf_is_distinct_from_missing_or_unsafe_owner_directory(tmp_path):
    m=feature('app.services.teacher_work.private_storage')
    root=tmp_path/'private';root.mkdir();storage=m.LocalPrivateStorage(root)
    key=m.storage_key(UUID(int=1),UUID(int=2),'docx')
    storage.publish(key,b'owned-synthetic')
    (root/key).unlink()
    absent=getattr(m,'PrivateArtifactAbsent',None)
    assert absent is not None,'typed safely resolved missing leaf required'
    with pytest.raises(absent):storage.read(key)
    owner=root/str(UUID(int=1));owner.rmdir()
    with pytest.raises(ValueError) as caught:storage.read(key)
    assert not isinstance(caught.value,absent)
    target=tmp_path/'other-owner';target.mkdir();owner.symlink_to(target,target_is_directory=True)
    with pytest.raises(OSError):storage.read(key)


@pytest.mark.parametrize('race',['owner_replace','root_replace'])
def test_missing_leaf_never_hides_directory_identity_race(tmp_path,monkeypatch,race):
    m=feature('app.services.teacher_work.private_storage')
    root=tmp_path/'private';root.mkdir();storage=m.LocalPrivateStorage(root)
    key=m.storage_key(UUID(int=1),UUID(int=2),'docx')
    storage.publish(key,b'owned-synthetic');(root/key).unlink()
    original=m.os.open
    def replace(path,flags,*args,**kwargs):
        if path==Path(key).name and kwargs.get('dir_fd') is not None:
            if race=='owner_replace':
                owner=root/str(UUID(int=1));owner.rename(root/'old-owner');owner.mkdir()
            else:
                root.rename(tmp_path/'old-private');root.mkdir();(root/str(UUID(int=1))).mkdir()
        return original(path,flags,*args,**kwargs)
    monkeypatch.setattr(m.os,'open',replace)
    with pytest.raises((ValueError,OSError)) as caught:storage.read(key)
    assert not isinstance(caught.value,m.PrivateArtifactAbsent)
