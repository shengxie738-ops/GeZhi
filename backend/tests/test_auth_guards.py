"""HTTP 层认证护栏测试（负向 + 正向）。

验证所有加固端点在真实 HTTP 层（TestClient）正确接线：
- 无 token / 伪造 token → 401
- 学生访问他人数据 → 403
- 学生访问教师专用端点 → 403
- 学生自访问 / 教师访问 → 200
"""

import os
import unittest
import json
from unittest.mock import patch

os.environ.setdefault("RAGFLOW_API_KEY", "test")
os.environ.setdefault("RAGFLOW_BASE_URL", "http://localhost")
os.environ.setdefault("RAGFLOW_AGENT_ID", "test")
os.environ.setdefault("RAGFLOW_CHAT_ID", "test")
os.environ.setdefault("RAGFLOW_DATASET_ID", "test")
os.environ.setdefault("RAGFLOW_PUBLIC_DATASET_IDS", "")
os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("OPENAI_API_BASE", "http://localhost")

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.database import Base, get_db
from app.core.security import create_access_token
from fastapi import FastAPI
from app.api.api import api_router
from app.core.config import settings

app = FastAPI()
app.include_router(api_router, prefix="/api")
from app.models.student_profile import StudentProfile
from app.models.user_account import UserAccount

STUDENT = "23001020119"
OTHER = "20230001"
TEACHER = "teacher_chen"


class AuthGuardTest(unittest.TestCase):
    def setUp(self):
        self.roster = patch.object(settings, "TEACHER_STUDENT_ASSIGNMENTS", json.dumps({TEACHER: [STUDENT]}))
        self.roster.start()
        self.addCleanup(self.roster.stop)
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(bind=self.engine)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

        def override_get_db():
            db = self.SessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        db = self.SessionLocal()
        db.add(UserAccount(username=STUDENT, role="student", password_hash="", real_name="测试学生"))
        db.add(UserAccount(username=OTHER, role="student", password_hash="", real_name="另一学生"))
        db.add(UserAccount(username=TEACHER, role="teacher", password_hash="", real_name="测试教师"))
        db.add(StudentProfile(user_id=STUDENT, knowledge=70, pace=60))
        db.commit()
        db.close()
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)

    def _auth(self, username, role):
        return {"Authorization": f"Bearer {create_access_token(username, role)}"}

    def test_missing_token_returns_401_everywhere(self):
        endpoints = [
            "/api/analytics/students/me?user_id=" + STUDENT,
            "/api/analytics/students",
            "/api/user/info/" + STUDENT,
            "/api/user/knowledge?user_id=" + STUDENT,
            "/api/profile/" + STUDENT,
            "/api/profile/summary?user_id=" + STUDENT,
            "/api/ranked/student/" + STUDENT + "/dashboard",
            "/api/exams/student/" + STUDENT + "/overview",
            "/api/exams/teacher/dashboard",
            "/api/journal/events?user_id=" + STUDENT,
        ]
        for ep in endpoints:
            with self.subTest(endpoint=ep):
                self.assertEqual(self.client.get(ep).status_code, 401, ep)

    def test_forged_token_returns_401(self):
        resp = self.client.get(
            "/api/profile/" + STUDENT,
            headers={"Authorization": "Bearer forged.token.value"},
        )
        self.assertEqual(resp.status_code, 401)

    def test_student_cannot_read_others_private_data(self):
        headers = self._auth(STUDENT, "student")
        endpoints = [
            "/api/analytics/students/me?user_id=" + OTHER,
            "/api/user/info/" + OTHER,
            "/api/user/knowledge?user_id=" + OTHER,
            "/api/profile/" + OTHER,
            "/api/ranked/student/" + OTHER + "/dashboard",
            "/api/exams/student/" + OTHER + "/overview",
            "/api/journal/events?user_id=" + OTHER,
        ]
        for ep in endpoints:
            with self.subTest(endpoint=ep):
                self.assertEqual(self.client.get(ep, headers=headers).status_code, 403, ep)

    def test_student_cannot_access_teacher_endpoints(self):
        headers = self._auth(STUDENT, "student")
        endpoints = [
            "/api/analytics/students",
            "/api/analytics/overview",
            "/api/analytics/advices",
            "/api/exams/teacher/dashboard",
            "/api/exams/teacher/error-analysis",
        ]
        for ep in endpoints:
            with self.subTest(endpoint=ep):
                self.assertEqual(self.client.get(ep, headers=headers).status_code, 403, ep)

    def test_student_self_access_ok(self):
        headers = self._auth(STUDENT, "student")
        for ep in [
            "/api/user/info/" + STUDENT,
            "/api/profile/" + STUDENT,
            "/api/profile/summary?user_id=" + STUDENT,
        ]:
            with self.subTest(endpoint=ep):
                self.assertEqual(self.client.get(ep, headers=headers).status_code, 200, ep)

    def test_teacher_cannot_read_unassigned_student(self):
        response = self.client.get("/api/profile/" + OTHER, headers=self._auth(TEACHER, "teacher"))
        self.assertEqual(response.status_code, 403)

    def test_teacher_can_read_student_and_teacher_views(self):
        headers = self._auth(TEACHER, "teacher")
        for ep in [
            "/api/analytics/students/me?user_id=" + STUDENT,
            "/api/profile/" + STUDENT,
            "/api/ranked/student/" + STUDENT + "/dashboard",
            "/api/analytics/students",
            "/api/exams/teacher/dashboard",
        ]:
            with self.subTest(endpoint=ep):
                self.assertEqual(self.client.get(ep, headers=headers).status_code, 200, ep)


if __name__ == "__main__":
    unittest.main()
