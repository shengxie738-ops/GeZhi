from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Literal
import re
import secrets
import string

from sqlalchemy.orm import Session

from app.models.gitea_account_binding import GiteaAccountBinding
from app.models.user_account import UserAccount
from app.services.gitea_service import GiteaService, GiteaUnavailableError
from app.utils.datetime import utc_now_iso


class GiteaTokenError(Exception):
    """Raised when Gitea access token creation or rotation fails."""


@dataclass
class GiteaIdentity:
    campus_user_id: str
    role: str
    student_id: str
    teacher_id: str
    class_name: str
    gitea_user_id: int | None
    gitea_username: str
    gitea_email: str
    sync_status: str
    sync_error: str
    token_last_four: str = ""


@dataclass
class GiteaTokenResult:
    gitea_username: str
    token: str
    token_last_four: str
    token_created_at: str


@dataclass
class RepoPermission:
    campus_user_id: str
    permission: Literal["read", "write", "admin"]
    reason: str = ""


def _clean(value: str | None) -> str:
    return str(value or "").strip()


def _safe_part(value: str) -> str:
    part = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip())
    part = re.sub(r"-{2,}", "-", part).strip("-._")
    return part or "user"


def _random_password(length: int = 28) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def gitea_username_for_account(account: UserAccount) -> str:
    if (account.role or "student") == "teacher":
        source = _clean(account.teacher_id) or _clean(account.username)
        return f"tea_{_safe_part(source)}"
    source = _clean(account.student_id) or _clean(account.username)
    return f"stu_{_safe_part(source)}"


def gitea_email_for_account(account: UserAccount) -> str:
    if (account.role or "student") == "teacher":
        source = _clean(account.teacher_id) or _clean(account.username)
        return f"teacher_{_safe_part(source)}@gezhi.local"
    source = _clean(account.student_id) or _clean(account.username)
    return f"{_safe_part(source)}@gezhi.local"


def _identity_from_binding(binding: GiteaAccountBinding) -> GiteaIdentity:
    return GiteaIdentity(
        campus_user_id=binding.campus_user_id,
        role=binding.role,
        student_id=binding.student_id,
        teacher_id=binding.teacher_id,
        class_name=binding.class_name,
        gitea_user_id=binding.gitea_user_id,
        gitea_username=binding.gitea_username,
        gitea_email=binding.gitea_email,
        sync_status=binding.sync_status,
        sync_error=binding.sync_error,
        token_last_four=binding.token_last_four,
    )


def _apply_account_fields(binding: GiteaAccountBinding, account: UserAccount, *, username: str, email: str) -> None:
    binding.role = account.role or "student"
    binding.student_id = account.student_id or ""
    binding.teacher_id = account.teacher_id or ""
    binding.class_name = account.class_name or ""
    binding.gitea_username = username
    binding.gitea_email = email


def get_gitea_binding_summary(db: Session, account: UserAccount) -> dict:
    """Read-only Gitea summary for login/user profile; does not call Gitea API."""
    binding = db.query(GiteaAccountBinding).filter(GiteaAccountBinding.campus_user_id == account.username).first()
    if binding:
        return {
            "username": binding.gitea_username,
            "email": binding.gitea_email,
            "syncStatus": binding.sync_status,
            "tokenLastFour": binding.token_last_four,
        }
    return {
        "username": gitea_username_for_account(account),
        "email": gitea_email_for_account(account),
        "syncStatus": "pending",
        "tokenLastFour": "",
    }


def _uses_real_gitea_api(client: GiteaService | object) -> bool:
    if hasattr(client, "enabled") and hasattr(client, "token"):
        return bool(client.enabled and client.token)
    return False


def ensure_gitea_account_for_user(
    db: Session,
    account: UserAccount,
    *,
    gitea: GiteaService | None = None,
    force_sync: bool = False,
) -> GiteaIdentity:
    client = gitea or GiteaService()
    username = gitea_username_for_account(account)
    email = gitea_email_for_account(account)
    binding = db.query(GiteaAccountBinding).filter(GiteaAccountBinding.campus_user_id == account.username).first()
    if not binding:
        binding = GiteaAccountBinding(
            campus_user_id=account.username,
            role=account.role or "student",
            student_id=account.student_id or "",
            teacher_id=account.teacher_id or "",
            class_name=account.class_name or "",
            gitea_username=username,
            gitea_email=email,
            sync_status="pending",
            sync_error="",
        )
        db.add(binding)

    _apply_account_fields(binding, account, username=username, email=email)

    if isinstance(client, GiteaService) and not _uses_real_gitea_api(client):
        binding.sync_status = "unavailable"
        binding.sync_error = "Gitea provider unavailable"
        db.commit()
        db.refresh(binding)
        return _identity_from_binding(binding)

    if (
        not force_sync
        and binding.sync_status == "synced"
        and binding.gitea_user_id is not None
    ):
        db.commit()
        db.refresh(binding)
        return _identity_from_binding(binding)

    if not _uses_real_gitea_api(client):
        if binding.sync_status != "synced" or binding.gitea_user_id is None:
            try:
                user = client.create_user(
                    username=username,
                    email=email,
                    full_name=account.real_name or account.username,
                    password=_random_password(),
                    must_change_password=False,
                )
                binding.gitea_user_id = user.get("id")
                if hasattr(client, "ensure_org_membership"):
                    client.ensure_org_membership(username, role="member")
                binding.sync_status = "synced" if user.get("id") is not None else "failed"
                binding.sync_error = ""
            except Exception as exc:
                binding.sync_status = "failed"
                binding.sync_error = "Gitea account synchronization failed"
        db.commit()
        db.refresh(binding)
        return _identity_from_binding(binding)

    try:
        user = client.create_user(
            username=username,
            email=email,
            full_name=account.real_name or account.username,
            password=_random_password(),
            must_change_password=False,
        )
        binding.gitea_user_id = user.get("id")
        org_error = ""
        try:
            client.ensure_org_membership(username, role="member")
        except Exception as org_exc:
            org_error = "Gitea organization membership failed"
        binding.sync_status = "synced" if user.get("id") is not None else "failed"
        binding.sync_error = org_error
    except Exception as exc:
        try:
            existing = client.get_user(username) if hasattr(client, "get_user") else None
        except Exception:
            existing = None
        if existing and existing.get("id") is not None:
            binding.gitea_user_id = existing.get("id")
            org_error = ""
            try:
                client.ensure_org_membership(username, role="member")
            except Exception as org_exc:
                org_error = "Gitea organization membership failed"
            binding.sync_status = "synced"
            binding.sync_error = org_error
        else:
            binding.sync_status = "failed"
            binding.sync_error = "Gitea account synchronization failed"

    db.commit()
    db.refresh(binding)
    return _identity_from_binding(binding)


def ensure_gitea_account_by_username(db: Session, campus_user_id: str, *, gitea: GiteaService | None = None) -> GiteaIdentity | None:
    account = db.query(UserAccount).filter(UserAccount.username == campus_user_id).first()
    if not account:
        return None
    return ensure_gitea_account_for_user(db, account, gitea=gitea)


def create_or_rotate_gitea_token(db: Session, account: UserAccount, *, gitea: GiteaService | None = None) -> GiteaTokenResult:
    identity = ensure_gitea_account_for_user(db, account, gitea=gitea)
    token_name = "campus-learning-system"
    client = gitea or GiteaService()
    try:
        token = client.create_user_token(identity.gitea_username, token_name)
    except Exception as exc:
        raise GiteaTokenError(str(exc)) from exc
    if not token:
        raise GiteaTokenError("Gitea 未返回有效 Token")
    token_created_at = datetime.now(timezone.utc)
    token_created_at_iso = utc_now_iso()
    binding = db.query(GiteaAccountBinding).filter(GiteaAccountBinding.campus_user_id == account.username).one()
    binding.token_name = token_name
    binding.token_last_four = token[-4:] if token else ""
    binding.token_created_at = token_created_at
    db.commit()
    return GiteaTokenResult(
        gitea_username=identity.gitea_username,
        token=token,
        token_last_four=binding.token_last_four,
        token_created_at=token_created_at_iso,
    )


def ensure_repository_collaborators(
    db: Session, repo_owner: str, repo_name: str, permissions: list[RepoPermission], *, gitea: GiteaService | None = None,
) -> list[dict]:
    client = gitea or GiteaService()
    result = []
    for item in permissions:
        record = {"campusUserId": item.campus_user_id, "permission": item.permission}
        try:
            identity = ensure_gitea_account_by_username(db, item.campus_user_id, gitea=client)
            if not identity:
                result.append({**record, "status": "missing_user"})
                continue
            record["giteaUsername"] = identity.gitea_username
            if identity.sync_status != "synced" or identity.gitea_user_id is None:
                result.append({**record, "status": "unavailable" if identity.sync_status == "unavailable" else "failed",
                               "error": "Gitea account is not synchronized"})
                continue
            succeeded = client.add_repository_collaborator(owner=repo_owner, repo=repo_name,
                         username=identity.gitea_username, permission=item.permission)
            result.append({**record, "status": "synced" if succeeded is True else "failed"})
        except GiteaUnavailableError:
            result.append({**record, "status": "unavailable", "error": "Gitea provider unavailable"})
        except Exception:
            result.append({**record, "status": "failed", "error": "Gitea collaborator synchronization failed"})
    return result


def match_campus_user_from_gitea_event(db: Session, *, sender_username: str = "", commit_author: dict | None = None) -> dict:
    """Associate metadata, not cryptographically authenticate authorship.

    Presence of commit_author (including {}) forbids falling back to the pusher.
    Display names and guessed email local parts are never identity evidence.
    """
    author = commit_author if isinstance(commit_author, dict) else {}
    username = _clean(author.get("username") or author.get("login")) if commit_author is not None else _clean(sender_username)
    email = _clean(author.get("email"))
    candidates = {}
    for field, value, source in ((GiteaAccountBinding.gitea_username, username, "gitea_username"),
                                 (GiteaAccountBinding.gitea_email, email, "gitea_email")):
        if not value:
            continue
        bindings = db.query(GiteaAccountBinding).filter(field == value,
                    GiteaAccountBinding.sync_status == "synced", GiteaAccountBinding.gitea_user_id.isnot(None)).all()
        for binding in bindings:
            account = db.query(UserAccount).filter(UserAccount.username == binding.campus_user_id).first()
            if account:
                candidates[account.username] = (account, binding, source)
    if len(candidates) == 1:
        account, binding, source = next(iter(candidates.values()))
        return {"campusUserId": account.username, "studentId": account.student_id or "",
                "giteaUsername": binding.gitea_username if binding else "",
                "displayName": account.real_name or account.username, "matchSource": source, "source": source}
    source = "ambiguous" if len(candidates) > 1 else "unmatched"
    return {"campusUserId": "", "studentId": "", "giteaUsername": "", "displayName": _clean(author.get("name")) or username or "unknown",
            "matchSource": source, "source": source}
