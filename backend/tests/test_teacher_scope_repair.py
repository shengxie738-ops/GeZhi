"""Synthetic in-memory tests: no restored database or external services."""
import asyncio
import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.api.endpoints import analytics, dashboard
from app.models.domain_record import DomainRecord
from app.models.user_account import UserAccount
from app.models.student_profile import StudentProfile
from app.repositories.json_store import JsonStore
from app.schemas.teacher_learning_diagnosis import ReviewNoteRequest, WatchFlagRequest
from app.services.learning_diagnosis.teacher_review_service import TeacherLearningDiagnosisReviewService


class TeacherScopeRepairTest(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        for model in (DomainRecord, UserAccount, StudentProfile):
            model.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.store = JsonStore(self.db)
        self.auth = {'sub': 'teacher-a', 'role': 'teacher'}
        for sid in ('1001', '1002'):
            self.db.add(UserAccount(username=sid, role='student', class_name='same editable class'))
        self.db.commit()
        self.roster = {'1001'}
        self.patches = [patch.object(module, 'teacher_student_ids', side_effect=lambda _: set(self.roster), create=True)
                        for module in (analytics, dashboard, __import__('app.services.learning_diagnosis.teacher_review_service', fromlist=['x']))]
        for p in self.patches: p.start()
        for sid in ('1001', '1002'):
            self.store.upsert('exams', 'mistake', 'm'+sid, {'studentId': sid, 'knowledgeTags': [sid], 'wrongCount': 3}, owner_id=sid)
            self.store.upsert('learning_diagnosis', 'snapshot', 's'+sid, {'student_id': sid, 'version': 1, 'assessments': [{'mastery_score': 30}]}, owner_id=sid)

    def tearDown(self):
        for p in self.patches: p.stop()
        self.db.close()
        self.engine.dispose()

    def run_async(self, coroutine):
        return asyncio.run(coroutine)['data']

    def test_student_list_excludes_same_class_unassigned_student(self):
        rows = self.run_async(analytics.get_student_list(payload=self.auth, db=self.db))
        self.assertEqual([x['username'] for x in rows], ['1001'])

    def test_empty_roster_overview_has_no_people_or_foreign_evidence(self):
        self.roster.clear()
        data = self.run_async(analytics.get_overview_stats(payload=self.auth, db=self.db))
        self.assertEqual(data['summary']['studentCount'], 0)
        for key in ('weakPoints', 'actionQueue', 'aiAdvices', 'interactionRecords'):
            self.assertEqual(data[key], [], key)

    def test_broadcast_dispatch_targets_only_roster_and_real_counts(self):
        data = self.run_async(analytics.dispatch_student_interaction(analytics.FreePayload(type='nudge'), auth=self.auth, db=self.db))
        record = data['record']
        self.assertEqual(record['studentIds'], ['1001'])
        self.assertEqual(record['pendingCount'], 1)
        self.assertEqual(self.store.list_payloads('analytics', 'nudge', owner_id='1002'), [])

    def test_foreign_dispatch_rejected_before_any_write(self):
        count = self.db.query(DomainRecord).count()
        with self.assertRaises(HTTPException):
            self.run_async(analytics.dispatch_student_interaction(analytics.FreePayload(target={'studentIds':['1002']}), auth=self.auth, db=self.db))
        self.assertEqual(self.db.query(DomainRecord).count(), count)

    def test_review_queue_and_detail_scoped(self):
        service = TeacherLearningDiagnosisReviewService(self.db)
        self.assertEqual([x['snapshot']['student_id'] for x in service.list_reviews('teacher-a')['reviews']], ['1001'])
        self.assertEqual(service.get_detail('s1001','teacher-a')['snapshot']['student_id'], '1001')
        with self.assertRaises(HTTPException): service.get_detail('s1002','teacher-a')

    def test_foreign_review_mutations_rejected_without_writes(self):
        service = TeacherLearningDiagnosisReviewService(self.db)
        count = self.db.query(DomainRecord).count()
        for call in (lambda: service.add_note('s1002','teacher-a',ReviewNoteRequest(comment='no')),
                     lambda: service.upsert_watch_flag('1002','teacher-a',WatchFlagRequest()),
                     lambda: service.delete_watch_flag('1002','teacher-a')):
            with self.assertRaises(HTTPException): call()
        self.assertEqual(self.db.query(DomainRecord).count(), count)

    def test_dashboard_overview_only_assigned_evidence(self):
        kwargs = {'db': self.db, 'auth': self.auth}
        data = self.run_async(dashboard.get_teacher_class_overview(**kwargs))
        self.assertEqual(data['mistakes']['total'], 1)
        self.assertEqual(data['mistakes']['hotTopics'], [{'tag': '1001', 'count': 1}])

    def test_dashboard_foreign_intervention_rejected(self):
        kwargs = {'db': self.db, 'auth': self.auth}
        count = self.db.query(DomainRecord).count()
        with self.assertRaises(HTTPException):
            self.run_async(dashboard.create_teacher_intervention(dashboard.FreePayload(targetUserId='1002'), **kwargs))
        self.assertEqual(self.db.query(DomainRecord).count(), count)

    def test_interaction_student_self_completion_preserved(self):
        record = self.run_async(analytics.dispatch_student_interaction(analytics.FreePayload(), auth=self.auth, db=self.db))['record']
        data = self.run_async(analytics.mark_interaction_complete(record['id'], analytics.FreePayload(), auth={'sub':'1001','role':'student'}, db=self.db))
        self.assertEqual(data['completedCount'], 1)
        again = self.run_async(analytics.mark_interaction_complete(record['id'], analytics.FreePayload(), auth={'sub':'1001','role':'student'}, db=self.db))
        self.assertTrue(again['alreadyCompleted'])

    def test_empty_roster_dispatch_rejected_not_48(self):
        self.roster.clear()
        with self.assertRaises(HTTPException):
            self.run_async(analytics.dispatch_intervention_task(analytics.FreePayload(), auth=self.auth, db=self.db))

    def test_teacher_cache_and_patch_do_not_cross_teacher_boundary(self):
        record = self.run_async(analytics.dispatch_student_interaction(analytics.FreePayload(), auth=self.auth, db=self.db))['record']
        other = {'sub':'teacher-b','role':'teacher'}
        self.assertEqual(self.run_async(analytics.get_interaction_records(payload=other, db=self.db, x_gezhi_client=None)), [])
        with self.assertRaises(HTTPException):
            self.run_async(analytics.update_interaction_record(record['id'], analytics.FreePayload(status='completed'), auth=other, db=self.db))
        self.assertEqual(self.store.get_payload('analytics','interaction',record['id'])['status'], 'running')
        self.run_async(analytics.update_interaction_record(record['id'], analytics.FreePayload(studentIds=['1002']), auth=self.auth, db=self.db))
        self.assertEqual(self.store.get_payload('analytics','interaction',record['id'])['studentIds'], ['1001'])

    def test_student_visibility_and_completion_never_broadcast_to_foreign_student(self):
        record = self.run_async(analytics.dispatch_student_interaction(analytics.FreePayload(), auth=self.auth, db=self.db))['record']
        self.store.upsert('analytics','interaction','legacy-unbounded', {'title':'legacy'})
        data = self.run_async(dashboard.get_student_interactions('1002', db=self.db, auth={'sub':'1002','role':'student'}))
        self.assertEqual(data['interactions'], [])
        with self.assertRaises(HTTPException):
            self.run_async(analytics.mark_interaction_complete(record['id'], analytics.FreePayload(), auth={'sub':'1002','role':'student'}, db=self.db))

    def test_empty_roster_generators_and_reviews_are_empty(self):
        self.roster.clear()
        for fn in (analytics.generate_ai_advices, analytics.generate_action_queue):
            self.assertEqual(self.run_async(fn(auth=self.auth, db=self.db)), [])
        service = TeacherLearningDiagnosisReviewService(self.db)
        self.assertEqual(service.list_reviews('teacher-a')['summary']['total'], 0)
        self.assertEqual(service.weak_points('teacher-a'), {'weak_points':[], 'count':0})

    def test_overview_evidence_and_cached_results_drop_revoked_roster(self):
        data = self.run_async(analytics.get_overview_stats(payload=self.auth, db=self.db))
        self.assertEqual(data['summary']['studentCount'], 1)
        self.assertEqual([x['id'] for x in data['weakPoints']], ['m1001'])
        other = self.run_async(analytics.get_action_queue(payload={'sub':'teacher-b','role':'teacher'}, db=self.db))
        self.assertEqual(other, [])
        self.roster.clear()
        self.assertEqual(self.run_async(analytics.get_ai_intervention_advices(payload=self.auth, db=self.db)), [])
        self.assertEqual(self.run_async(analytics.get_action_queue(payload=self.auth, db=self.db)), [])

    def test_dispatch_does_not_allow_user_supplied_record_key_collision(self):
        first = self.run_async(analytics.dispatch_student_interaction(analytics.FreePayload(id='chosen'), auth=self.auth, db=self.db))['record']
        second = self.run_async(analytics.dispatch_student_interaction(analytics.FreePayload(id='chosen'), auth=self.auth, db=self.db))['record']
        self.assertNotEqual(first['id'], second['id'])
