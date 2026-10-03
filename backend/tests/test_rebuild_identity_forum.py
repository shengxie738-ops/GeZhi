"""A reconstruction acceptance: isolated ASGI and synthetic SQLite only.

No app.main/api aggregation, live services, migrations or business data.
The guarded launcher supplies synthetic settings and an in-memory database
module before collection. Only UserAccount and DomainRecord tables are used.
"""
import json
from pathlib import Path

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.api import deps
from app.api.endpoints import auth, forum, user_center
from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token
from app.models.domain_record import DomainRecord
from app.models.user_account import UserAccount
from app.repositories.json_store import JsonStore


@pytest.fixture
def harness(monkeypatch, tmp_path):
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    UserAccount.__table__.create(engine)
    DomainRecord.__table__.create(engine)
    sessions = sessionmaker(bind=engine, autoflush=False)
    with sessions() as db:
        for username, role, name in [
            ("student", "student", "学生老师"), ("other", "student", "另一学生"),
            ("teacher", "teacher", "真正教师"), ("moderator", "student", "版主"),
        ]:
            db.add(UserAccount(username=username, role=role, real_name=name, password_hash="", avatar_path=f"{username}.png"))
        db.commit()

    def isolated_db():
        with sessions() as db:
            yield db

    app = FastAPI()
    for router in [forum.router, auth.router, user_center.router]:
        app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = isolated_db

    @app.get("/probe/identity")
    def identity(payload=Depends(deps.get_auth_payload)):
        return {"sub": payload["sub"], "role": payload["role"]}

    @app.get("/probe/teacher")
    def teacher(payload=Depends(deps.require_teacher)):
        return {"sub": payload["sub"]}

    @app.get("/probe/scope/{target}")
    def scope(target: str, payload=Depends(deps.get_auth_payload)):
        deps.ensure_self_or_teacher(target, payload)
        return {"target": target}

    # Intentionally exclude paused Gitea serializers from this acceptance scope.
    monkeypatch.setattr(auth, "serialize_gitea_summary", lambda db, account: {})
    monkeypatch.setattr(user_center, "serialize_gitea_summary", lambda db, account: {})
    # Also redirect the historical __file__-derived path during RED. Never write
    # the frozen repository's real app/static/avatars directory.
    avatar_directory = tmp_path / "static" / "avatars"
    monkeypatch.setattr(user_center, "__file__", str(tmp_path / "api" / "endpoints" / "user_center.py"))
    monkeypatch.setattr(user_center, "AVATAR_DIRECTORY", avatar_directory, raising=False)
    monkeypatch.setattr(settings, "TEACHER_STUDENT_ASSIGNMENTS", json.dumps({"teacher": ["student"]}))
    had_moderators = hasattr(settings, "FORUM_MODERATOR_IDS")
    old_moderators = getattr(settings, "FORUM_MODERATOR_IDS", None)
    object.__setattr__(settings, "FORUM_MODERATOR_IDS", "[]")
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, sessions, avatar_directory
    if had_moderators:
        object.__setattr__(settings, "FORUM_MODERATOR_IDS", old_moderators)
    else:
        object.__delattr__(settings, "FORUM_MODERATOR_IDS")
    engine.dispose()


def headers(username="student", role="student", **extra):
    return {"Authorization": "Bearer " + create_access_token(username, role), **extra}


def new_post(client, actor="student", **data):
    response = client.post("/api/forum/posts", headers=headers(actor), json={"title": "Question", "content": "Body", **data})
    assert response.status_code == 200, response.text
    return response.json()["data"]


def stored(sessions, record_type="post"):
    with sessions() as db:
        return [(row.record_key, row.owner_id, row.role, json.loads(row.payload)) for row in db.query(DomainRecord).filter_by(module="forum", record_type=record_type).all()]


@pytest.mark.parametrize("authorization", [None, "Bearer forged", "Basic x"])
def test_protected_routes_reject_invalid_identity(harness, authorization):
    client, _, _ = harness
    incoming = {} if authorization is None else {"Authorization": authorization}
    assert client.get("/probe/identity", headers=incoming).status_code == 401
    assert client.post("/api/forum/posts", headers=incoming, json={"title": "x"}).status_code == 401


def test_signed_subject_without_canonical_account_fails_closed(harness):
    client, _, _ = harness
    assert client.get("/probe/identity", headers=headers("deleted", "teacher")).status_code == 401
    assert client.get("/api/auth/me", headers=headers("deleted", "teacher")).status_code == 401


def test_deleted_account_revokes_issued_token(harness):
    client, sessions, _ = harness
    token = headers("teacher", "teacher")
    assert client.get("/probe/teacher", headers=token).status_code == 200
    with sessions() as db:
        db.delete(db.get(UserAccount, "teacher"))
        db.commit()
    assert client.get("/probe/teacher", headers=token).status_code == 401
    assert client.post("/api/forum/posts", headers=token, json={"title": "x"}).status_code == 401


def test_current_role_revokes_stale_teacher_privilege_without_blocking_own_write(harness):
    client, sessions, _ = harness
    token = headers("teacher", "teacher")
    with sessions() as db:
        db.get(UserAccount, "teacher").role = "student"
        db.commit()
    assert client.get("/probe/identity", headers=token).json() == {"sub": "teacher", "role": "student"}
    assert client.get("/probe/teacher", headers=token).status_code == 403
    assert client.get("/probe/scope/student", headers=token).status_code == 403
    response = client.post("/api/forum/posts", headers=token, json={"title": "own"})
    assert response.status_code == 200
    assert response.json()["data"]["authorRole"] == "student"


def test_current_teacher_role_and_trusted_roster_are_used(harness):
    client, _, _ = harness
    # A legitimate role change is authorized by the current account, not token role.
    token = headers("teacher", "student")
    assert client.get("/probe/teacher", headers=token).status_code == 200
    assert client.get("/probe/scope/student", headers=token).status_code == 200
    assert client.get("/probe/scope/other", headers=token).status_code == 403
    assert client.get("/probe/scope/student", headers=headers("other", "teacher")).status_code == 403


def test_unknown_current_role_is_not_an_authenticated_student(harness):
    client, sessions, _ = harness
    with sessions() as db:
        db.get(UserAccount, "student").role = "operator"
        db.commit()
    assert client.get("/probe/identity", headers=headers()).status_code == 401
    assert client.post("/api/forum/posts", headers=headers(), json={"title": "x"}).status_code == 401


def test_auth_me_preserves_envelope_and_uses_current_account(harness):
    client, _, _ = harness
    response = client.get("/api/auth/me", headers=headers("student", "teacher"))
    assert response.status_code == 200
    assert response.json()["success"] is True
    assert response.json()["data"]["role"] == "student"
    assert response.json()["data"]["username"] == "student"


def test_post_write_allowlist_and_server_identity(harness):
    client, sessions, _ = harness
    post = new_post(client, id="forced", author="老师(教师)", authorId="teacher", authorUsername="teacher", authorRole="teacher", avatar="https://evil.invalid/avatar", isAi=True, provenance="AI", isPinned=True, replies=[{"id": "fake"}], teacherId="teacher", likes=99, views=99, categoryLabel="fake", tags=["hello"])
    assert post["id"] != "forced"
    assert post["authorId"] == post["authorUsername"] == "student"
    assert post["authorRole"] == "student"
    assert post["author"] == "学生老师"
    assert post["avatar"] == "/static/avatars/student.png"
    assert post["isAi"] is False
    assert post["provenance"] == "verified_account"
    assert not post.get("isPinned") and "teacherId" not in post
    assert post["replies"] == [] and post["likes"] == 0 and post["views"] == 1
    assert stored(sessions)[0][1:3] == ("student", "student")


def test_client_id_cannot_overwrite_an_existing_post(harness):
    client, sessions, _ = harness
    original = new_post(client)
    other = new_post(client, "other", id=original["id"], content="replacement")
    assert other["id"] != original["id"]
    assert len(stored(sessions)) == 2


def test_reply_identity_allowlist_and_no_fake_ai_audit(harness):
    client, sessions, _ = harness
    post = new_post(client)
    response = client.post(f"/api/forum/posts/{post['id']}/replies", headers=headers(), json={"id": "spoof", "content": "reply", "author": "教师", "authorRole": "teacher", "authorId": "teacher", "avatar": "evil", "isAi": True, "provenance": "AI"})
    assert response.status_code == 200
    reply = response.json()["data"]
    assert reply["id"] != "spoof"
    assert reply["authorId"] == "student" and reply["authorRole"] == "student"
    assert reply["author"] == "学生老师" and reply["avatar"] == "/static/avatars/student.png"
    assert reply["isAi"] is False and reply["provenance"] == "verified_account"
    assert stored(sessions, "ai_reply_log") == []
    identity = stored(sessions, "reply_identity")
    assert len(identity) == 1 and identity[0][1:3] == ("student", "student")


def test_reply_to_missing_post_is_not_a_ghost_post(harness):
    client, sessions, _ = harness
    response = client.post("/api/forum/posts/missing/replies", headers=headers(), json={"content": "x"})
    assert response.status_code == 404
    assert stored(sessions) == []


def test_teacher_answer_requires_server_provenance_not_display_name(harness):
    client, _, _ = harness
    post = new_post(client)
    client.post(f"/api/forum/posts/{post['id']}/replies", headers=headers(), json={"content": "student", "author": "张老师(教师)", "authorRole": "teacher"})
    assert post["id"] in {p["id"] for p in client.get("/api/forum/unanswered-qna").json()["data"]}
    response = client.post(f"/api/forum/posts/{post['id']}/replies", headers=headers("teacher", "student"), json={"content": "teacher"})
    assert response.status_code == 200
    assert response.json()["data"]["authorRole"] == "teacher"
    assert post["id"] not in {p["id"] for p in client.get("/api/forum/unanswered-qna").json()["data"]}


def test_legacy_fake_teacher_markers_are_not_verification(harness):
    client, sessions, _ = harness
    with sessions() as db:
        JsonStore(db).upsert("forum", "post", "legacy", {"id": "legacy", "category": "qna", "replies": [{"id": "legacy-reply", "author": "教师老师", "authorId": "teacher", "authorRole": "teacher", "provenance": "verified_account"}]})
    assert "legacy" in {p["id"] for p in client.get("/api/forum/unanswered-qna").json()["data"]}


def test_only_verified_owner_or_explicit_moderator_can_delete(harness):
    client, sessions, _ = harness
    post = new_post(client)
    assert client.delete(f"/api/forum/posts/{post['id']}", headers=headers("other")).status_code == 403
    assert client.delete(f"/api/forum/posts/{post['id']}", headers=headers("teacher", "teacher")).status_code == 403
    assert client.delete(f"/api/forum/posts/{post['id']}", headers=headers()).status_code == 200
    assert stored(sessions) == []


def test_legacy_unknown_owner_cannot_be_adopted_by_name_or_payload(harness):
    client, sessions, _ = harness
    with sessions() as db:
        JsonStore(db).upsert("forum", "post", "legacy", {"author": "学生老师", "authorId": "student", "authorUsername": "student", "provenance": "verified_account"})
    assert client.delete("/api/forum/posts/legacy", headers=headers()).status_code == 403
    assert len(stored(sessions)) == 1


ADMIN_WRITES = [
    ("put", "/api/forum/posts/{post}/pin?pinned=true", None),
    ("post", "/api/forum/announcements", {"title": "notice"}),
    ("post", "/api/forum/hottopics", {"tag": "x"}),
    ("put", "/api/forum/hottopics/weight", {"tag": "x", "change": 3}),
    ("delete", "/api/forum/hottopics?tag=x", None),
    ("put", "/api/forum/ai-replies/logs/log", {"content": "edited", "status": "approved"}),
]


@pytest.mark.parametrize("method,path,body", ADMIN_WRITES)
def test_admin_routes_reject_auth_fail_response_and_ordinary_teacher(harness, method, path, body):
    client, sessions, _ = harness
    post = new_post(client)
    target = path.format(post=post["id"])
    kwargs = {} if body is None else {"json": body}
    assert getattr(client, method)(target, **kwargs).status_code == 401
    assert getattr(client, method)(target, headers=headers("teacher", "teacher"), **kwargs).status_code == 403
    assert len(stored(sessions)) == 1
    assert stored(sessions, "announcement") == [] and stored(sessions, "hot_topic") == []


@pytest.mark.parametrize("allowlist", ["not-json", "{}", '[123]', '"moderator"'])
def test_malformed_moderator_config_fails_closed(harness, allowlist):
    client, _, _ = harness
    object.__setattr__(settings, "FORUM_MODERATOR_IDS", allowlist)
    assert client.post("/api/forum/hottopics", headers=headers("moderator"), json={"tag": "x"}).status_code == 403


def test_explicit_moderator_actions_and_owned_identity_survive_updates(harness):
    client, sessions, _ = harness
    object.__setattr__(settings, "FORUM_MODERATOR_IDS", '["moderator"]')
    post = new_post(client)
    token = headers("moderator")
    assert client.put(f"/api/forum/posts/{post['id']}/pin?pinned=true", headers=token).status_code == 200
    assert client.post("/api/forum/announcements", headers=token, json={"title": "notice", "authorId": "teacher", "id": "spoof"}).status_code == 200
    assert client.post("/api/forum/hottopics", headers=token, json={"tag": "x"}).status_code == 200
    assert client.put("/api/forum/hottopics/weight", headers=token, json={"tag": "x", "change": 2}).status_code == 200
    assert client.delete("/api/forum/hottopics?tag=x", headers=token).status_code == 200
    client.put(f"/api/forum/posts/{post['id']}/like", headers=headers("other"))
    client.put(f"/api/forum/posts/{post['id']}/view")
    client.post(f"/api/forum/posts/{post['id']}/replies", headers=headers("other"), json={"content": "x"})
    rows = [row for row in stored(sessions) if row[0] == post["id"]]
    assert len(rows) == 1 and rows[0][1:3] == ("student", "student")
    for key in ["authorId", "authorUsername", "authorRole", "author", "avatar", "provenance", "isAi"]:
        assert rows[0][3][key] == post[key]
    assert client.delete(f"/api/forum/posts/{post['id']}", headers=token).status_code == 200


def test_ai_audit_is_pointer_allowlisted_and_preserves_reply_identity(harness):
    client, sessions, _ = harness
    object.__setattr__(settings, "FORUM_MODERATOR_IDS", '["moderator"]')
    post = new_post(client)
    response = client.post(f"/api/forum/posts/{post['id']}/replies", headers=headers("teacher", "teacher"), json={"content": "original"})
    reply = response.json()["data"]
    with sessions() as db:
        JsonStore(db).upsert("forum", "ai_reply_log", "log", {"id": "log", "postId": post["id"], "replyId": reply["id"], "content": "original", "status": "pending_audit"})
    result = client.put("/api/forum/ai-replies/logs/log", headers=headers("moderator"), json={"content": "edited", "status": "approved", "postId": "bad", "replyId": "bad", "authorId": "other", "authorRole": "student", "isAi": True})
    assert result.status_code == 200
    log = stored(sessions, "ai_reply_log")[0][3]
    assert log["postId"] == post["id"] and log["replyId"] == reply["id"]
    changed = stored(sessions)[0][3]["replies"][0]
    assert changed["content"] == "edited"
    for key in ["authorId", "authorRole", "avatar", "provenance", "isAi"]:
        assert changed[key] == reply[key]
    assert client.put("/api/forum/ai-replies/logs/missing", headers=headers("moderator"), json={"content": "x"}).status_code == 404


def test_public_and_miniprogram_reads_and_reply_envelopes_remain_compatible(harness):
    client, _, _ = harness
    post = new_post(client)
    for route in ["posts", "announcements", "hottopics", "unanswered-qna"]:
        assert client.get("/api/forum/" + route).status_code == 200
    response = client.get("/api/forum/posts", headers={"X-Gezhi-Client": "miniprogram"})
    assert response.status_code == 200
    response = client.post(f"/api/forum/posts/{post['id']}/replies", headers=headers(**{"X-Gezhi-Client": "miniprogram"}), json={"content": "mini"})
    assert response.status_code == 200 and response.json()["data"]["content"] == "mini"


def test_utf8_json_storage_ceiling_rejects_post_and_reply_without_partial_write(harness):
    client, sessions, _ = harness
    response = client.post("/api/forum/posts", headers=headers(), json={"title": "large", "content": "汉" * 23000})
    assert response.status_code == 422
    assert stored(sessions) == []
    post = new_post(client)
    response = client.post(f"/api/forum/posts/{post['id']}/replies", headers=headers(), json={"content": "汉" * 23000})
    assert response.status_code == 422
    assert stored(sessions)[0][3]["replies"] == []
    assert stored(sessions, "reply_identity") == []


def test_small_utf8_post_is_accepted(harness):
    client, _, _ = harness
    assert new_post(client, content="汉" * 1000)["content"] == "汉" * 1000


@pytest.mark.parametrize("operation", ["reply", "notice", "pin", "audit"])
def test_multirecord_failure_rolls_back_all_forum_changes(harness, monkeypatch, operation):
    client, sessions, _ = harness
    object.__setattr__(settings, "FORUM_MODERATOR_IDS", '["moderator"]')
    post = new_post(client)
    if operation == "audit":
        reply = client.post(f"/api/forum/posts/{post['id']}/replies", headers=headers(), json={"content": "original"}).json()["data"]
        with sessions() as db:
            JsonStore(db).upsert("forum", "ai_reply_log", "log", {"id": "log", "postId": post["id"], "replyId": reply["id"], "content": "original"})
    before = {kind: stored(sessions, kind) for kind in ["post", "reply_identity", "announcement", "ai_reply_log"]}
    original = JsonStore.upsert
    calls = 0

    def fail_second(self, *args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(self, *args, **kwargs)
        if calls == 2:
            raise RuntimeError("synthetic transaction failure")
        return result

    monkeypatch.setattr(JsonStore, "upsert", fail_second)
    if operation == "reply":
        result = client.post(f"/api/forum/posts/{post['id']}/replies", headers=headers(), json={"content": "x"})
    elif operation == "notice":
        result = client.post("/api/forum/announcements", headers=headers("moderator"), json={"title": "x"})
    elif operation == "pin":
        result = client.put(f"/api/forum/posts/{post['id']}/pin?pinned=true", headers=headers("moderator"))
    else:
        result = client.put("/api/forum/ai-replies/logs/log", headers=headers("moderator"), json={"content": "edited"})
    assert result.status_code == 500
    assert calls == 2
    assert {kind: stored(sessions, kind) for kind in before} == before


def test_missing_avatar_target_does_not_create_file(harness):
    client, sessions, directory = harness
    token = headers("teacher", "teacher")
    monkey = settings.TEACHER_STUDENT_ASSIGNMENTS
    object.__setattr__(settings, "TEACHER_STUDENT_ASSIGNMENTS", '{"teacher":["missing"]}')
    response = client.post("/api/user/upload_avatar", headers=token, data={"username": "missing"}, files={"file": ("avatar.png", b"image", "image/png")})
    object.__setattr__(settings, "TEACHER_STUDENT_ASSIGNMENTS", monkey)
    assert response.status_code == 404
    assert not directory.exists()
    with sessions() as db:
        assert db.get(UserAccount, "missing") is None


def test_avatar_success_uses_safe_unique_filename_and_updates_only_existing_account(harness):
    client, sessions, directory = harness
    response = client.post("/api/user/upload_avatar", headers=headers(), data={"username": "student"}, files={"file": ("../../evil.png", b"image", "image/png")})
    assert response.status_code == 200
    with sessions() as db:
        filename = db.get(UserAccount, "student").avatar_path
    assert filename != "student.png" and Path(filename).name == filename
    assert (directory / filename).read_bytes() == b"image"
    assert response.json()["avatar_url"] == "/static/avatars/" + filename


def test_avatar_commit_failure_removes_uncommitted_file_and_preserves_old_path(harness, monkeypatch):
    client, sessions, directory = harness
    directory.mkdir(parents=True)
    old_file = directory / "student.png"
    old_file.write_bytes(b"old")

    def fail_commit(self):
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    response = client.post("/api/user/upload_avatar", headers=headers(), data={"username": "student"}, files={"file": ("avatar.png", b"new", "image/png")})
    assert response.status_code == 500
    assert sorted(path.name for path in directory.iterdir()) == ["student.png"]
    assert old_file.read_bytes() == b"old"
    with sessions() as db:
        assert db.get(UserAccount, "student").avatar_path == "student.png"


def test_post_deletion_atomically_removes_sidecar_and_pin_announcement(harness):
    client, sessions, _ = harness
    object.__setattr__(settings, "FORUM_MODERATOR_IDS", '["moderator"]')
    post = new_post(client)
    client.post(f"/api/forum/posts/{post['id']}/replies", headers=headers("teacher", "teacher"), json={"content": "answer"})
    client.put(f"/api/forum/posts/{post['id']}/pin?pinned=true", headers=headers("moderator"))
    assert len(stored(sessions, "reply_identity")) == 1
    assert client.delete(f"/api/forum/posts/{post['id']}", headers=headers()).status_code == 200
    assert stored(sessions) == [] and stored(sessions, "reply_identity") == []
    assert stored(sessions, "announcement") == []
    assert client.get("/api/forum/posts").json()["data"] == []


def test_post_deletion_commit_failure_restores_post_and_metadata(harness, monkeypatch):
    client, sessions, _ = harness
    object.__setattr__(settings, "FORUM_MODERATOR_IDS", '["moderator"]')
    post = new_post(client)
    client.post(f"/api/forum/posts/{post['id']}/replies", headers=headers("teacher", "teacher"), json={"content": "answer"})
    client.put(f"/api/forum/posts/{post['id']}/pin?pinned=true", headers=headers("moderator"))
    before = {kind: stored(sessions, kind) for kind in ["post", "reply_identity", "announcement"]}

    def fail_commit(self):
        raise RuntimeError("synthetic deletion commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    assert client.delete(f"/api/forum/posts/{post['id']}", headers=headers()).status_code == 500
    assert {kind: stored(sessions, kind) for kind in before} == before


def test_public_permissions_are_server_derived_for_anonymous_owner_student_and_moderator(harness):
    client, sessions, _ = harness
    object.__setattr__(settings, "FORUM_MODERATOR_IDS", '["moderator"]')
    post = new_post(client)
    with sessions() as db:
        JsonStore(db).upsert("forum", "post", "legacy-permissions", {"id": "legacy-permissions", "author": "学生老师", "authorId": "student", "authorRole": "teacher", "avatar": "https://evil.invalid/a", "provenance": "verified_account", "permissions": {"canDelete": True}})
    expected = [
        ({}, {"canDelete": False, "canPin": False, "canReply": False}),
        (headers(), {"canDelete": True, "canPin": False, "canReply": True}),
        (headers("other"), {"canDelete": False, "canPin": False, "canReply": True}),
        (headers("moderator"), {"canDelete": True, "canPin": True, "canReply": True}),
    ]
    for token, permissions in expected:
        response = client.get("/api/forum/posts", headers=token)
        assert response.status_code == 200
        posts = {value["id"]: value for value in response.json()["data"]}
        assert posts[post["id"]]["permissions"] == permissions
        legacy = posts["legacy-permissions"]
        assert legacy["provenance"] == "legacy_unknown"
        assert legacy["authorRole"] == "" and legacy["avatar"] == ""
        assert legacy["authorId"] == ""
        assert legacy["permissions"]["canDelete"] == permissions["canPin"]
        for forbidden in ["password_hash", "phone", "student_id", "class_name"]:
            assert forbidden not in json.dumps(posts)
    assert client.get("/api/forum/posts", headers={"Authorization": "Bearer forged"}).status_code == 401


def test_forum_context_uses_current_identity_and_default_empty_moderation(harness):
    client, _, _ = harness
    assert client.get("/api/forum/context").status_code == 401
    context = client.get("/api/forum/context", headers=headers("teacher", "student"))
    assert context.status_code == 200
    assert context.json()["data"] == {"username": "teacher", "role": "teacher", "canPost": True, "canModerate": False}
    object.__setattr__(settings, "FORUM_MODERATOR_IDS", '["moderator"]')
    assert client.get("/api/forum/context", headers=headers("moderator")).json()["data"]["canModerate"] is True


def test_public_verified_avatar_comes_from_current_account_and_legacy_reply_stays_unknown(harness):
    client, sessions, _ = harness
    post = new_post(client)
    with sessions() as db:
        db.get(UserAccount, "student").avatar_path = "current.png"
        row = db.query(DomainRecord).filter_by(record_key=post["id"], record_type="post").one()
        value = json.loads(row.payload)
        value["replies"] = [{"id": "legacy", "author": "Teacher", "avatar": "https://evil.invalid/x", "authorId": "teacher", "authorRole": "teacher", "isAi": True, "provenance": "verified_account"}]
        row.payload = json.dumps(value)
        db.commit()
    public = client.get("/api/forum/posts").json()["data"][0]
    assert public["avatar"] == "/static/avatars/current.png"
    assert public["replies"][0]["provenance"] == "legacy_unknown"
    assert public["replies"][0]["authorRole"] == "" and public["replies"][0]["avatar"] == ""
    assert public["replies"][0]["isAi"] is None


def test_export_actual_http_permission_contract(harness, tmp_path):
    client, sessions, _ = harness
    object.__setattr__(settings, "FORUM_MODERATOR_IDS", '["moderator"]')
    post = new_post(client)
    with sessions() as db:
        JsonStore(db).upsert("forum", "post", "legacy-fixture", {"id": "legacy-fixture", "author": "Student", "authorId": "student", "authorRole": "teacher", "provenance": "verified_account"})
    fixtures = {}
    for label, token in [("anonymous", {}), ("owner", headers()), ("student", headers("other")), ("moderator", headers("moderator"))]:
        response = client.get("/api/forum/posts", headers=token)
        assert response.status_code == 200
        fixtures[label] = response.json()
        if token:
            context = client.get("/api/forum/context", headers=token)
            assert context.status_code == 200
            fixtures[label + "Context"] = context.json()
    assert fixtures["anonymous"]["data"][0].get("permissions") is not None
    (tmp_path / "forum-http-permission-fixtures.json").write_text(json.dumps(fixtures, ensure_ascii=False, indent=2), encoding="utf-8")


@pytest.fixture
def direct_harness(harness, monkeypatch):
    """Real six endpoint routers; only downstream workflow/provider imports inert.

    This proves HTTP authentication wiring, not diagnosis or lesson-prep logic.
    Never load the paused GitPracticeService import graph from DiagnosisWorkflow.
    """
    import importlib
    import sys
    from types import ModuleType, SimpleNamespace

    workflow_module = ModuleType("app.services.learning_diagnosis.workflow")
    calls = {"workflow": 0, "lesson_config": 0}

    class InertWorkflow:
        def __init__(self, db):
            calls["workflow"] += 1
            self.store = SimpleNamespace(get_snapshot=lambda snapshot, student: {"id": snapshot, "student_id": student})

    workflow_module.DiagnosisWorkflow = InertWorkflow
    lesson_module = ModuleType("app.services.teacher_lesson_prep.service")
    def public_config():
        calls["lesson_config"] += 1
        return {"synthetic": True}

    lesson_module.lesson_prep_service = SimpleNamespace(public_config=public_config)
    monkeypatch.setitem(sys.modules, workflow_module.__name__, workflow_module)
    monkeypatch.setitem(sys.modules, lesson_module.__name__, lesson_module)
    client, sessions, directory = harness
    for name in ["dashboard", "homework", "language", "learning_diagnosis", "teacher_learning_diagnosis", "teacher_lesson_prep"]:
        module = importlib.import_module("app.api.endpoints." + name)
        if name == "learning_diagnosis":
            monkeypatch.setattr(module, "DiagnosisWorkflow", InertWorkflow)
        if name == "teacher_lesson_prep":
            monkeypatch.setattr(module, "lesson_prep_service", lesson_module.lesson_prep_service)
        client.app.include_router(module.router, prefix="/api")
    client.app.state.direct_calls = calls
    return client, sessions, directory


DIRECT_ROUTES = [
    ("/api/dashboard/student/{actor}", False),
    ("/api/homework/student/list", False),
    ("/api/language/wordbook", False),
    ("/api/learning-diagnosis/snapshots/synthetic?student_id={actor}", False),
    ("/api/teacher/learning-diagnosis/reviews", True),
    ("/api/teacher/lesson-prep/config", True),
]


@pytest.mark.parametrize("route,teacher_only", DIRECT_ROUTES)
def test_six_direct_decoder_routes_reject_deleted_account(direct_harness, route, teacher_only):
    client, _, _ = direct_harness
    response = client.get(route.format(actor="deleted"), headers=headers("deleted", "teacher"))
    assert response.status_code == 401
    assert client.app.state.direct_calls == {"workflow": 0, "lesson_config": 0}


@pytest.mark.parametrize("route,teacher_only", DIRECT_ROUTES)
def test_six_direct_decoder_routes_use_current_role_and_allow_current_own_access(direct_harness, route, teacher_only):
    client, sessions, _ = direct_harness
    with sessions() as db:
        db.get(UserAccount, "teacher").role = "student"
        db.commit()
    response = client.get(route.format(actor="teacher"), headers=headers("teacher", "teacher"))
    assert response.status_code == (403 if teacher_only else 200), response.text
    if teacher_only:
        assert client.app.state.direct_calls == {"workflow": 0, "lesson_config": 0}


@pytest.mark.parametrize("route,teacher_only", DIRECT_ROUTES)
def test_six_direct_decoder_routes_legitimate_current_role_controls(direct_harness, route, teacher_only):
    client, _, _ = direct_harness
    actor = "teacher" if teacher_only else "student"
    response = client.get(route.format(actor=actor), headers=headers(actor, "student" if teacher_only else "teacher"))
    assert response.status_code == 200, response.text


def test_direct_auth_payload_omitted_dependency_owns_and_closes_current_account_session(harness, monkeypatch):
    _, sessions, _ = harness
    closed = []

    def factory():
        db = sessions()
        original = db.close

        def close():
            closed.append(True)
            original()

        monkeypatch.setattr(db, "close", close)
        return db

    monkeypatch.setattr(deps, "SessionLocal", factory, raising=False)
    payload = deps.get_auth_payload(headers("teacher", "student")["Authorization"])
    assert payload == {"sub": "teacher", "role": "teacher"}
    assert closed == [True]


def test_direct_auth_payload_owned_session_closes_on_missing_account(harness, monkeypatch):
    from fastapi import HTTPException
    _, sessions, _ = harness
    closed = []

    def factory():
        db = sessions()
        original = db.close

        def close():
            closed.append(True)
            original()

        monkeypatch.setattr(db, "close", close)
        return db

    monkeypatch.setattr(deps, "SessionLocal", factory, raising=False)
    with pytest.raises(HTTPException) as error:
        deps.get_auth_payload(headers("deleted", "teacher")["Authorization"])
    assert error.value.status_code == 401
    assert closed == [True]


def test_direct_auth_payload_owned_session_closes_on_database_exception(harness, monkeypatch):
    _, sessions, _ = harness
    closed = []

    def factory():
        db = sessions()
        original = db.close

        def close():
            closed.append(True)
            original()

        def fail_query(*args, **kwargs):
            raise RuntimeError("synthetic lookup failure")

        monkeypatch.setattr(db, "close", close)
        monkeypatch.setattr(db, "query", fail_query)
        return db

    monkeypatch.setattr(deps, "SessionLocal", factory, raising=False)
    with pytest.raises(RuntimeError, match="synthetic lookup failure"):
        deps.get_auth_payload(headers()["Authorization"])
    assert closed == [True]


def test_direct_auth_payload_explicit_session_stays_caller_owned(harness, monkeypatch):
    _, sessions, _ = harness
    with sessions() as db:
        closed = []
        original = db.close
        monkeypatch.setattr(db, "close", lambda: (closed.append(True), original()))
        payload = deps.get_auth_payload(headers("student", "teacher")["Authorization"], db)
        assert payload == {"sub": "student", "role": "student"}
        assert closed == []
        assert db.get(UserAccount, "student") is not None


def test_announcement_reads_project_trusted_identity_and_never_rewrite_legacy(harness):
    client, sessions, _ = harness
    forged = {"id": "legacy-ann", "title": "Old", "author": "Teacher", "authorId": "teacher", "authorRole": "teacher", "provenance": "verified_account", "avatar": "https://evil.invalid/a", "isAi": True}
    with sessions() as db:
        JsonStore(db).upsert("forum", "announcement", "legacy-ann", forged)
    before = stored(sessions, "announcement")
    response = client.get("/api/forum/announcements")
    assert response.status_code == 200 and response.json()["code"] == 200
    public = response.json()["data"][0]
    assert public["title"] == "Old" and public["provenance"] == "legacy_unknown"
    assert public["authorId"] == public["authorRole"] == public["avatar"] == ""
    assert public["isAi"] is None
    assert stored(sessions, "announcement") == before


def test_announcement_reads_use_current_canonical_avatar(harness):
    client, sessions, _ = harness
    object.__setattr__(settings, "FORUM_MODERATOR_IDS", '["moderator"]')
    published = client.post("/api/forum/announcements", headers=headers("moderator"), json={"title": "Notice"})
    assert published.status_code == 200
    with sessions() as db:
        db.get(UserAccount, "moderator").avatar_path = "new-current.png"
        db.commit()
    public = client.get("/api/forum/announcements").json()["data"][0]
    assert public["authorId"] == "moderator" and public["provenance"] == "verified_account"
    assert public["avatar"] == "/static/avatars/new-current.png"


def test_ai_audit_updates_record_status_and_payload_atomically(harness):
    client, sessions, _ = harness
    object.__setattr__(settings, "FORUM_MODERATOR_IDS", '["moderator"]')
    with sessions() as db:
        JsonStore(db).upsert("forum", "ai_reply_log", "status-log", {"id": "status-log", "content": "original", "status": "pending_audit"})
    response = client.put("/api/forum/ai-replies/logs/status-log", headers=headers("moderator"), json={"status": "approved"})
    assert response.status_code == 200
    with sessions() as db:
        record = db.query(DomainRecord).filter_by(module="forum", record_type="ai_reply_log", record_key="status-log").one()
        assert record.status == "approved" and json.loads(record.payload)["status"] == "approved"
