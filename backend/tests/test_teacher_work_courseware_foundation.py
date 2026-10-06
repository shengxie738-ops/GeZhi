"""Synthetic offline tests, never evidence of deployment readiness."""
import hashlib
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from dataclasses import replace
from uuid import UUID

class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('app.services.teacher_work.courseware_snapshot'), 'bounded snapshot foundation missing')
        from app.services.teacher_work import courseware_snapshot as s
        self.s = s
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'frontend'
        self.folder = self.root / 'AI_technology'; self.folder.mkdir(parents=True)
        self.path = self.folder / 'sample.pdf'; self.path.write_bytes(b'synthetic non-PDF bytes')
        self.key = 'courseware-' + hashlib.sha256(b'ai_technology/sample.pdf').hexdigest()[:24]
        self.selection = s.AuthorizedSelection('teacher', UUID(int=1), UUID(int=2), UUID(int=3), 1, (self.key,), 'policy-1', True, source_root=str(self.root))
    def capture(self, **kwargs):
        return self.s.capture_selected(self.root, self.selection, authorize=kwargs.pop('authorize', lambda value: value), **kwargs)
    def test_default_deny_before_io(self):
        denied = replace(self.selection, shared_library_enabled=False)
        with self.assertRaises(self.s.CoursewareSourceError) as caught:
            self.s.capture_selected(self.root / 'absent', denied, authorize=lambda value:value)
        self.assertEqual(caught.exception.code, 'COURSEWARE_POLICY_UNAVAILABLE')
    def test_root_is_bound_to_authorization(self):
        different=Path(self.tmp.name)/'other-root'
        (different/'AI_technology').mkdir(parents=True)
        (different/'AI_technology'/'sample.pdf').write_bytes(b'unauthorized root content')
        with self.assertRaises(self.s.CoursewareSourceError):
            self.s.capture_selected(different,self.selection,authorize=lambda value:value)
    def test_detached_bytes_hash_binding(self):
        result = self.capture(); resource = result.resources[0]
        self.assertEqual(result.selection, self.selection)
        self.assertEqual(resource.data, self.path.read_bytes())
        self.assertEqual(resource.sha256, hashlib.sha256(resource.data).hexdigest())
        self.assertEqual((resource.resource_id, resource.extension), (self.key, '.pdf'))
        self.path.write_bytes(b'changed'); self.assertNotEqual(resource.data, self.path.read_bytes())
    def test_manifest_repr_omits_source_bytes_and_root(self):
        manifest=self.capture()
        self.assertNotIn('synthetic non-PDF bytes',repr(manifest))
        self.assertNotIn(str(self.root),repr(manifest))
    def test_auth_substitution_revocation(self):
        for change in ({'subject':'other'}, {'task_id':UUID(int=99)}, {'input_revision':2}, {'policy_generation':'new'}):
            with self.subTest(change=change), self.assertRaises(self.s.CoursewareSourceError):
                self.capture(authorize=lambda value:replace(value, **change))
        calls=[]
        def revoked(value):
            calls.append(1)
            return value if len(calls)==1 else replace(value, shared_library_enabled=False)
        with self.assertRaises(self.s.CoursewareSourceError): self.capture(authorize=revoked)
        self.assertEqual(len(calls), 2)
    def test_invalid_or_missing_ids(self):
        for ids in ((self.key,self.key), ('../../secret',), ('courseware-'+'0'*24,)):
            with self.subTest(ids=ids), self.assertRaises(self.s.CoursewareSourceError):
                self.s.capture_selected(self.root, replace(self.selection,resource_ids=ids),authorize=lambda value:value)
    def test_symlinks_hardlinks_rejected(self):
        other=Path(self.tmp.name)/'external.pdf'; other.write_bytes(b'other'); self.path.unlink(); self.path.symlink_to(other)
        with self.assertRaises(self.s.CoursewareSourceError): self.capture()
        self.path.unlink(); os.link(other,self.path)
        with self.assertRaises(self.s.CoursewareSourceError): self.capture()
        alias=Path(self.tmp.name)/'alias'; alias.symlink_to(self.root,target_is_directory=True)
        with self.assertRaises(self.s.CoursewareSourceError):
            self.s.capture_selected(alias,replace(self.selection,source_root=str(alias)),authorize=lambda value:value)
    def test_collision(self):
        (self.folder/'SAMPLE.pdf').write_bytes(b'collision')
        with self.assertRaises(self.s.CoursewareSourceError): self.capture()
    def test_symlink_casefold_alias_is_ambiguous(self):
        (self.folder/'SAMPLE.pdf').symlink_to(self.path)
        with self.assertRaises(self.s.CoursewareSourceError): self.capture()
    def test_source_mutated_during_read_is_rejected(self):
        from unittest.mock import patch
        original_read = os.read
        changed = []
        def mutating_read(fd, amount):
            data = original_read(fd, amount)
            if data and not changed:
                changed.append(True)
                self.path.write_bytes(b'Z' * len(data))
            return data
        with patch.object(self.s.os, 'read', side_effect=mutating_read):
            with self.assertRaises(self.s.CoursewareSourceError) as caught: self.capture()
        self.assertEqual(caught.exception.code, 'COURSEWARE_SOURCE_CHANGED')
    def test_fifo_is_rejected_without_open_block(self):
        self.path.unlink(); os.mkfifo(self.path)
        with self.assertRaises(self.s.CoursewareSourceError): self.capture()
    def test_ancestor_symlink_and_missing_course_fail(self):
        alias=Path(self.tmp.name)/'ancestor'; alias.symlink_to(self.root.parent,target_is_directory=True)
        with self.assertRaises(self.s.CoursewareSourceError):
            self.s.capture_selected(alias/'frontend',replace(self.selection,source_root=str(alias/'frontend')),authorize=lambda value:value)
        self.path.unlink(); self.folder.rmdir()
        with self.assertRaises(self.s.CoursewareSourceError): self.capture()
    def test_budgets(self):
        n=self.path.stat().st_size
        self.assertEqual(len(self.capture(limits=self.s.SnapshotLimits(file_bytes=n,total_bytes=n)).resources),1)
        (self.folder/'nested'/'nested').mkdir(parents=True)
        for limits in (self.s.SnapshotLimits(file_bytes=n-1),self.s.SnapshotLimits(total_bytes=n-1),self.s.SnapshotLimits(entries=1),self.s.SnapshotLimits(depth=1)):
            with self.subTest(limits=limits),self.assertRaises(self.s.CoursewareSourceError): self.capture(limits=limits)
        ticks=iter((0.0,100.0))
        with self.assertRaises(self.s.CoursewareSourceError): self.capture(monotonic=lambda:next(ticks))
    def test_hash_not_stat_cache(self):
        before=self.capture(); st=self.path.stat(); self.path.write_bytes(b'X'*st.st_size); os.utime(self.path,ns=(st.st_atime_ns,st.st_mtime_ns))
        after=self.capture(); self.assertNotEqual(before.resources[0].sha256,after.resources[0].sha256)
        self.assertNotEqual(before.manifest_digest,after.manifest_digest)
    def test_unselected_bytes_not_read(self):
        with (self.folder/'large.pdf').open('wb') as stream: stream.truncate(40*1024*1024)
        self.assertEqual(len(self.capture().resources),1)
    def test_reauthorization_cannot_return_after_deadline(self):
        clock=[0.0]; calls=[]
        def authority(value):
            calls.append(1)
            if len(calls)==2: clock[0]=100.0
            return value
        with self.assertRaises(self.s.CoursewareSourceError) as caught:
            self.capture(authorize=authority,monotonic=lambda:clock[0])
        self.assertEqual(caught.exception.code,'COURSEWARE_SOURCE_TIMEOUT')
    def test_limit_validation(self):
        for kwargs in ({'file_bytes':0},{'entries':True},{'seconds':float('nan')},{'total_bytes':100*1024*1024}):
            with self.subTest(kwargs=kwargs),self.assertRaises(self.s.CoursewareSourceError): self.s.SnapshotLimits(**kwargs)
if __name__=='__main__': unittest.main()
