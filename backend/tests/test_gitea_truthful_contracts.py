"""Isolated adapter regressions. No provider or restored database access."""
import unittest
from unittest.mock import patch
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.services.gitea_service import GiteaService
from app.services.gitea_account_service import match_campus_user_from_gitea_event, ensure_gitea_account_for_user, ensure_repository_collaborators, RepoPermission
from app.models.gitea_account_binding import GiteaAccountBinding
from app.models.user_account import UserAccount


class Response:
    def __init__(self, status=200, data=None, text=''):
        self.status_code, self.data, self.text = status, data, text
        self.content = b'json'
    def iter_content(self, chunk_size=8192):
        yield self.text.encode()
    def close(self): pass
    def json(self): return self.data
    def raise_for_status(self):
        if self.status_code >= 400: raise requests.HTTPError('secret-token-must-not-leak')


class AdapterContracts(unittest.TestCase):
    def setUp(self):
        self.guard = patch('requests.sessions.Session.request', side_effect=AssertionError('Network denied'))
        self.guard.start()
        self.addCleanup(self.guard.stop)
        self.client = GiteaService(enabled=True, token='synthetic', base_url='http://gitea.test')

    def test_disabled_never_reports_remote_success(self):
        client = GiteaService(enabled=False, token='')
        with self.assertRaises(RuntimeError): client.create_repository(name='x')
        with self.assertRaises(RuntimeError): client.get_repository(owner='o', repo='x')
        with self.assertRaises(RuntimeError): client.add_repository_collaborator(owner='o', repo='x', username='u')
        with self.assertRaises(RuntimeError): client.create_user_token('u')
        self.assertFalse(client.ensure_webhook(owner='o', repo='x', project_id='p')['configured'])
        self.assertFalse(client.create_webhook(owner='o', repo='x', project_id='p'))
        result = client.get_commit_diff(owner='o', repo='x', sha='abc')
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['content'], '')

    def test_diffs_status_truncation_and_pr_path(self):
        with patch('app.services.gitea_service.requests.get', return_value=Response(text='diff --git a/a b/a\n+123456')) as get:
            result = self.client.get_commit_diff(owner='o', repo='x', sha='abc', max_chars=10)
            self.assertEqual(result['content'], 'diff --git')
            self.assertTrue(result['truncated'])
            result = self.client.get_pull_request_diff(owner='o', repo='x', number=7)
            self.assertTrue(get.call_args.args[0].endswith('/pulls/7.diff'))
            self.assertEqual(result['status'], 'available')
        for code, status in [(404, 'not_found'), (500, 'error')]:
            with patch('app.services.gitea_service.requests.get', return_value=Response(code)):
                result = self.client.get_commit_diff(owner='o', repo='x', sha='abc')
                self.assertEqual(result['status'], status)
                self.assertNotIn('secret-token', str(result))

    def test_diff_download_is_bounded_and_closed(self):
        class StreamingResponse(Response):
            consumed = 0
            closed = False
            def iter_content(self, chunk_size=8192):
                for chunk in [b'diff --git a/a b/a\n', b'x'*1000, b'never-read']:
                    self.consumed += 1
                    yield chunk
            def close(self): self.closed = True
        response = StreamingResponse()
        with patch('app.services.gitea_service.requests.get', return_value=response):
            result = self.client.get_commit_diff(owner='o', repo='x', sha='abc', max_chars=10)
        self.assertTrue(result['truncated'])
        self.assertLess(response.consumed, 3)
        self.assertTrue(response.closed)

    def test_repository_success_requires_remote_identity(self):
        for data in ({}, {'name':'x','owner':{'login':'o'}}):
            with patch('app.services.gitea_service.requests.post', return_value=Response(201,data=data)):
                with self.assertRaises(ValueError): self.client.create_repository(name='x')
        with patch('app.services.gitea_service.requests.get', return_value=Response(data={'id':7,'name':'x','owner':{'login':'o'}})):
            result = self.client.get_repository(owner='o',repo='x')
            self.assertEqual(result['giteaRepositoryId'],7)
            self.assertEqual(result['source'],'gitea')

    def test_creation_conflict_does_not_adopt_unrelated_repository(self):
        with patch('app.services.gitea_service.requests.post', return_value=Response(409)), patch('app.services.gitea_service.requests.get', return_value=Response(data={'name':'x','owner':{'login':'o'}})):
            with self.assertRaises(requests.HTTPError): self.client.create_repository(name='x')

    def test_repository_permission_is_for_explicit_user(self):
        with patch('app.services.gitea_service.requests.get', return_value=Response(data={'permission':'admin','user':{'login':'alice'}})) as get:
            self.assertEqual(self.client.get_repository_permission(owner='o', repo='x', username='alice'), 'admin')
            self.assertTrue(get.call_args.args[0].endswith('/collaborators/alice/permission'))
        with patch('app.services.gitea_service.requests.get', return_value=Response(data={'permission':'admin','user':{'login':'other'}})):
            self.assertEqual(self.client.get_repository_permission(owner='o', repo='x', username='alice'), 'none')

    def test_pr_head_drift_rejects_diff(self):
        for metadata in ({'head':{'sha':'new'}}, {'head':{}}):
            with patch('app.services.gitea_service.requests.get', return_value=Response(data=metadata)):
                result = self.client.get_pull_request_diff(owner='o', repo='x', number=7, expected_head_sha='old')
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(result['reason'], 'pr_head_changed')
        old = {'head':{'sha':'old'},'base':{'sha':'base'}}
        new = {'head':{'sha':'new'},'base':{'sha':'base'}}
        with patch('app.services.gitea_service.requests.get', side_effect=[Response(data=old), Response(text='diff --git a/a b/a'), Response(data=new)]):
            result = self.client.get_pull_request_diff(owner='o', repo='x', number=7, expected_head_sha='old')
            self.assertEqual(result['status'], 'unavailable')

    def test_pr_retarget_with_same_head_is_unavailable(self):
        current = {'head':{'sha':'old','ref':'feature/a'},'base':{'sha':'base-new','ref':'release'}}
        with patch('app.services.gitea_service.requests.get', return_value=Response(data=current)):
            result = self.client.get_pull_request_diff(owner='o', repo='x', number=7, expected_head_sha='old', expected_head_ref='feature/a', expected_base_ref='develop', expected_base_sha='base-old')
            self.assertEqual(result['status'], 'unavailable')
            self.assertEqual(result['reason'], 'pr_head_changed')

    def test_hook_existing_url_is_repaired_and_read_back(self):
        url = self.client._webhook_url(project_id='p')
        old = {'id': 3, 'active': False, 'events': ['push'], 'config': {'url': url}}
        good = {'id': 3, 'type': 'gitea', 'active': True, 'events': ['push', 'pull_request'], 'config': {'url': url, 'content_type': 'json'}}
        with patch('app.services.gitea_service.settings.GITEA_WEBHOOK_SECRET', 'synthetic-secret'), patch('app.services.gitea_service.requests.get', side_effect=[Response(data=[old]), Response(data=good)]), patch('app.services.gitea_service.requests.patch', return_value=Response(data=good)) as update:
            result = self.client.ensure_webhook(owner='o', repo='x', project_id='p')
            self.assertTrue(result['configured'])
            self.assertEqual(update.call_args.kwargs['json']['config']['secret'], 'synthetic-secret')
            self.assertEqual(result['secretVerification'], 'write_acknowledged')
            self.assertNotIn('synthetic-secret', str(result))

    def test_hook_422_is_not_success(self):
        with patch('app.services.gitea_service.settings.GITEA_WEBHOOK_SECRET', 'synthetic-secret'), patch('app.services.gitea_service.requests.get', return_value=Response(data=[])), patch('app.services.gitea_service.requests.post', return_value=Response(422)):
            result = self.client.ensure_webhook(owner='o', repo='x', project_id='p')
            self.assertFalse(result['configured'])
            self.assertNotIn('secret-token', str(result))

    def test_hook_rejects_shipped_and_example_secret_placeholders(self):
        from app.services import gitea_service
        for value in (None, '', '  ', 'gezhi_webhook_secret_default', 'replace_with_a_strong_webhook_secret', 'changeme', 'change-me', 'secret', 'replace-me', ' GEZHI_WEBHOOK_SECRET_DEFAULT '):
            self.assertFalse(gitea_service.is_gitea_webhook_secret_configured(value))
            with patch('app.services.gitea_service.settings.GITEA_WEBHOOK_SECRET', value or ''):
                result = self.client.ensure_webhook(owner='o', repo='x', project_id='p')
                self.assertFalse(result['configured'])
                self.assertEqual(result['status'], 'unavailable')
        self.assertTrue(gitea_service.is_gitea_webhook_secret_configured('synthetic-long-random-test-secret-8a19c'))

    def test_hook_readback_failure_and_missing_secret_are_not_success(self):
        url = self.client._webhook_url(project_id='p')
        old = {'id': 3, 'active': True, 'events': ['push'], 'config': {'url': url}}
        with patch('app.services.gitea_service.settings.GITEA_WEBHOOK_SECRET', 'synthetic-secret'), patch('app.services.gitea_service.requests.get', side_effect=[Response(data=[old]), Response(data=old)]), patch('app.services.gitea_service.requests.patch', return_value=Response(data=old)):
            self.assertFalse(self.client.ensure_webhook(owner='o', repo='x', project_id='p')['configured'])
        with patch('app.services.gitea_service.settings.GITEA_WEBHOOK_SECRET', ''):
            self.assertEqual(self.client.ensure_webhook(owner='o', repo='x', project_id='p')['reason'], 'missing_webhook_secret')

    def test_hook_duplicate_is_only_accepted_after_repair_and_readback(self):
        url = self.client._webhook_url(project_id='p')
        good = {'id': 3, 'type':'gitea', 'active': True, 'events': ['push','pull_request'], 'config': {'url': url,'content_type':'json'}}
        with patch('app.services.gitea_service.settings.GITEA_WEBHOOK_SECRET', 'synthetic-secret'), patch('app.services.gitea_service.requests.get', side_effect=[Response(data=[]),Response(data=[good]),Response(data=good)]), patch('app.services.gitea_service.requests.post', return_value=Response(422)), patch('app.services.gitea_service.requests.patch', return_value=Response(data=good)):
            result = self.client.ensure_webhook(owner='o', repo='x', project_id='p')
            self.assertTrue(result['configured'])
            self.assertFalse(result['deliveryVerified'])

    def test_disabled_destructive_mutations_and_membership_do_not_claim_success(self):
        client = GiteaService(enabled=False, token='')
        with self.assertRaises(RuntimeError): client.delete_repository(owner='o', repo='x')
        with self.assertRaises(RuntimeError): client.delete_user_token_by_name('u','t')
        with self.assertRaises(RuntimeError): client.ensure_org_membership('u')

    def test_collaborator_422_is_not_success(self):
        with patch('app.services.gitea_service.requests.put', return_value=Response(422)):
            with self.assertRaises(requests.HTTPError):
                self.client.add_repository_collaborator(owner='o', repo='x', username='u')


class AttributionContracts(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite:///:memory:')
        UserAccount.__table__.create(self.engine)
        GiteaAccountBinding.__table__.create(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.db.close)
        for name, num in [('author', 1), ('pusher', 2)]:
            self.db.add(UserAccount(username=name, role='student', real_name='Shared Name', student_id=str(num)))
            self.db.add(GiteaAccountBinding(campus_user_id=name, gitea_user_id=num, gitea_username='stu_'+str(num), gitea_email=str(num)+'@gezhi.local', sync_status='synced'))
        self.db.commit()

    def test_legacy_mock_binding_requires_remote_user_verification(self):
        account = self.db.query(UserAccount).filter_by(username='author').one()
        binding = self.db.query(GiteaAccountBinding).filter_by(campus_user_id='author').one()
        binding.sync_status = 'mock'
        self.db.commit()
        client = GiteaService(enabled=True, token='synthetic')
        with patch.object(client,'create_user', side_effect=RuntimeError('unavailable')), patch.object(client,'get_user', return_value=None), patch.object(client,'ensure_org_membership', return_value=True):
            identity = ensure_gitea_account_for_user(self.db, account, gitea=client)
        self.assertEqual(identity.sync_status, 'failed')

    def test_disabled_account_and_collaborator_are_unavailable(self):
        account = self.db.query(UserAccount).filter_by(username='author').one()
        binding = self.db.query(GiteaAccountBinding).filter_by(campus_user_id='author').one()
        binding.sync_status = 'mock'
        binding.gitea_user_id = None
        self.db.commit()
        client = GiteaService(enabled=False, token='')
        identity = ensure_gitea_account_for_user(self.db, account, gitea=client)
        self.assertEqual(identity.sync_status, 'unavailable')
        result = ensure_repository_collaborators(self.db, 'o', 'r', [RepoPermission('author','write')], gitea=client)
        self.assertEqual(result[0]['status'], 'unavailable')

    def test_author_email_beats_bound_pusher(self):
        result = match_campus_user_from_gitea_event(self.db, sender_username='stu_2', commit_author={'email': '1@gezhi.local'})
        self.assertEqual(result['campusUserId'], 'author')
        self.assertEqual(result['source'], result['matchSource'])

    def test_unmatched_author_never_uses_pusher_or_display_name(self):
        for author in ({'name': 'Shared Name'}, {'email': 'other@example.test'}, {}):
            result = match_campus_user_from_gitea_event(self.db, sender_username='stu_2', commit_author=author)
            self.assertEqual(result['campusUserId'], '')
            self.assertEqual(result['matchSource'], 'unmatched')

    def test_actor_only_and_canonical_author(self):
        result = match_campus_user_from_gitea_event(self.db, sender_username='stu_2')
        self.assertEqual(result['campusUserId'], 'pusher')
        result = match_campus_user_from_gitea_event(self.db, sender_username='stu_2', commit_author={'username':'stu_1'})
        self.assertEqual(result['campusUserId'], 'author')

    def test_campus_username_collision_is_not_a_binding(self):
        result = match_campus_user_from_gitea_event(self.db, commit_author={'username':'author'})
        self.assertEqual(result['campusUserId'], '')
        self.assertEqual(result['matchSource'], 'unmatched')

    def test_conflicting_author_identifiers_are_ambiguous(self):
        result = match_campus_user_from_gitea_event(self.db, commit_author={'username':'stu_2','email':'1@gezhi.local'})
        self.assertEqual(result['campusUserId'], '')
        self.assertEqual(result['matchSource'], 'ambiguous')
