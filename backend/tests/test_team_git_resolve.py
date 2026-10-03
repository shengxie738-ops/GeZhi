"""Unit tests for resolve_team_project_id and find_project_id_by_repo_name (Task 1)."""
import os
import unittest

os.environ.setdefault("RAGFLOW_API_KEY", "test")
os.environ.setdefault("RAGFLOW_BASE_URL", "http://localhost")
os.environ.setdefault("RAGFLOW_AGENT_ID", "test")
os.environ.setdefault("RAGFLOW_CHAT_ID", "test")
os.environ.setdefault("RAGFLOW_DATASET_ID", "test")
os.environ.setdefault("RAGFLOW_PUBLIC_DATASET_IDS", "")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("OPENAI_API_BASE", "http://localhost")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.domain_record import DomainRecord
from app.models import git_coach  # Register the additive isolated-test schema.
from app.models.user_account import UserAccount
from app.services.team_git_service import (
    find_project_id_by_repo_name,
    resolve_team_project_id,
    create_collaboration_project,
)

engine = create_engine("sqlite:///:memory:")
DomainRecord.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine)


def _fresh_db():
    db = SessionLocal()
    # Production IDs are permanent; isolate each synthetic test database.
    DomainRecord.metadata.drop_all(engine)
    DomainRecord.metadata.create_all(engine)
    db.add_all([UserAccount(username=name, role="student", password_hash="fixture") for name in ("leader", "alice", "bob")])
    db.commit()
    return db


class TestFindProjectIdByRepoName(unittest.TestCase):
    def setUp(self):
        self.db = _fresh_db()

    def tearDown(self):
        self.db.close()

    def _create_project(self, project_id: str, repo_name: str):
        """直接写入一个带 repository.repoName 的项目记录。"""
        create_collaboration_project(
            self.db,
            {
                "id": project_id,
                "title": f"Test {project_id}",
                "teamName": "TestTeam",
                "leaderId": "leader",
                "members": ["alice"],
                "repoName": repo_name,
            },
            actor={"username": "leader", "role": "student"},
        )
        # 补充 repository.repoName 字段（create 可能不写入 repository 块）
        from app.repositories.json_store import JsonStore
        from app.services.team_git_service import MODULE, PROJECT
        store = JsonStore(self.db)
        project = store.get_payload(MODULE, PROJECT, project_id)
        if project:
            project.setdefault("repository", {}).update(repoName=repo_name, giteaOwner="campus", giteaRepositoryId=71)
            store.upsert(MODULE, PROJECT, project_id, project, owner_id="leader", status="active")

    def test_find_by_exact_repo_name(self):
        """按精确 repoName 反查应返回对应的 project_id。"""
        self._create_project("huffman-team", "huffman-coding")
        found = find_project_id_by_repo_name(self.db, "huffman-coding")
        self.assertEqual(found, "huffman-team")

    def test_find_by_full_name_with_org(self):
        """full_name 为 campus/repo 格式时，取最后一段匹配。"""
        self._create_project("sort-team", "bubble-sort")
        found = find_project_id_by_repo_name(self.db, "campus/bubble-sort")
        self.assertEqual(found, "sort-team")

    def test_find_by_project_id(self):
        """repoName 不存在时，用 project id 也应能找到。"""
        self._create_project("my-project-id", "anything-else")
        found = find_project_id_by_repo_name(self.db, "my-project-id")
        self.assertIsNotNone(found)

    def test_not_found_returns_none(self):
        """找不到时返回 None。"""
        self._create_project("some-project", "some-repo")
        found = find_project_id_by_repo_name(self.db, "totally-different-repo-xyz")
        self.assertIsNone(found)

    def test_case_insensitive(self):
        """匹配应该忽略大小写。"""
        self._create_project("huffman-team2", "Huffman-Coding-Upper")
        found = find_project_id_by_repo_name(self.db, "huffman-coding-upper")
        self.assertEqual(found, "huffman-team2")


class TestResolveTeamProjectId(unittest.TestCase):
    def setUp(self):
        self.db = _fresh_db()

    def tearDown(self):
        self.db.close()

    def _create_project(self, project_id: str, repo_name: str):
        create_collaboration_project(
            self.db,
            {
                "id": project_id,
                "title": f"Test {project_id}",
                "teamName": "ResolveTeam",
                "leaderId": "leader",
                "members": ["bob"],
                "repoName": repo_name,
            },
            actor={"username": "leader", "role": "student"},
        )
        from app.repositories.json_store import JsonStore
        from app.services.team_git_service import MODULE, PROJECT
        store = JsonStore(self.db)
        project = store.get_payload(MODULE, PROJECT, project_id)
        if project:
            project.setdefault("repository", {}).update(repoName=repo_name, giteaOwner="campus", giteaRepositoryId=71)
            store.upsert(MODULE, PROJECT, project_id, project, owner_id="leader", status="active")

    def test_valid_project_id_returns_same(self):
        """有效 project_id 直接命中，不走反查。"""
        self._create_project("known-project", "known-repo")
        result = resolve_team_project_id(self.db, "known-project", {"repository": {"id": 71, "name": "known-repo", "owner": {"login": "campus"}}})
        self.assertEqual(result, "known-project")

    def test_invalid_project_id_rejects_matching_repo_name(self):
        """错误路径不能被匹配的仓库名绕过。"""
        self._create_project("real-project", "real-repo")
        payload = {"repository": {"name": "real-repo", "full_name": "campus/real-repo"}}
        with self.assertRaises(FileNotFoundError):
            resolve_team_project_id(self.db, "wrong-id-xyz", payload)

    def test_invalid_project_id_rejects_matching_full_name(self):
        """完整仓库名称也不能替换错误路径。"""
        self._create_project("full-name-project", "full-name-repo")
        payload = {"repository": {"name": "other-name", "full_name": "campus/full-name-repo"}}
        with self.assertRaises(FileNotFoundError):
            resolve_team_project_id(self.db, "bad-id", payload)

    def test_both_fail_raises_file_not_found(self):
        """project_id 无效 + payload 也匹配不上 → FileNotFoundError。"""
        self._create_project("existing-project", "existing-repo")
        payload = {"repository": {"name": "nonexistent-repo"}}
        with self.assertRaises(FileNotFoundError) as ctx:
            resolve_team_project_id(self.db, "bad-id", payload)
        self.assertIn("team project not found", str(ctx.exception))

    def test_empty_payload_raises_file_not_found(self):
        """project_id 无效 + 空 payload → FileNotFoundError。"""
        with self.assertRaises(FileNotFoundError):
            resolve_team_project_id(self.db, "bad-id", {})


    def test_existing_path_requires_complete_bound_repository_identity(self):
        self._create_project("bound", "bound-repo")
        valid = {"id": 71, "name": "bound-repo", "full_name": "campus/bound-repo", "owner": {"login": "campus"}}
        for changed in ({"id": 72}, {"name": "other"}, {"owner": {"login": "outsider"}}, {"full_name": "outsider/bound-repo"}):
            with self.subTest(changed=changed), self.assertRaises(PermissionError):
                resolve_team_project_id(self.db, "bound", {"repository": {**valid, **changed}})
        with self.assertRaises(ValueError):
            resolve_team_project_id(self.db, "bound", {})
        self.assertEqual(resolve_team_project_id(self.db, "bound", {"repository": valid}), "bound")

    def test_missing_remote_binding_requires_verification_without_mutation(self):
        from app.repositories.json_store import JsonStore
        from app.services.team_git_service import MODULE, PROJECT
        self._create_project("unverified", "unverified-repo")
        store = JsonStore(self.db)
        project = store.get_payload(MODULE, PROJECT, "unverified")
        project["repository"].pop("giteaRepositoryId")
        store.upsert(MODULE, PROJECT, "unverified", project, owner_id="leader", status="active")
        before = store.get_payload(MODULE, PROJECT, "unverified")
        with self.assertRaisesRegex(FileExistsError, "binding_verification_required"):
            resolve_team_project_id(self.db, "unverified", {"repository": {
                "id": 71, "name": "unverified-repo", "owner": {"login": "campus"}}})
        self.assertEqual(store.get_payload(MODULE, PROJECT, "unverified"), before)

    def test_unknown_project_id_is_not_created_by_failed_webhook_resolution(self):
        before = self.db.query(DomainRecord).count()
        payload = {"repository": {"name": "missing-repo", "full_name": "campus/missing-repo"}}

        with self.assertRaises(FileNotFoundError):
            resolve_team_project_id(self.db, "legacy-missing-project", payload)

        after = self.db.query(DomainRecord).count()
        self.assertEqual(after, before)


if __name__ == "__main__":
    unittest.main(verbosity=2)
