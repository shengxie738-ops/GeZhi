"""Pure summary contract; permission/transaction acceptance is native full app."""
from datetime import datetime, timezone
from uuid import UUID

import pytest
from pydantic import ValidationError

from app.schemas.teacher_work import PrivateTaskSummary, PrivateTaskList


def summary(number):
    return PrivateTaskSummary(task_id=UUID(int=number), title="合成任务",
        created_at=datetime(2026, 10, 6, tzinfo=timezone.utc),
        updated_at=datetime(2026, 10, 6, tzinfo=timezone.utc))


def test_minimal_projection_has_no_operation_authority():
    item = summary(2)
    page = PrivateTaskList(items=(item,), has_more=True, next_before=item.task_id)
    assert set(page.model_dump(mode="json")["items"][0]) == {"task_id", "title", "created_at", "updated_at"}
    assert PrivateTaskList(items=(), has_more=False, next_before=None).model_dump(mode="json") == {
        "items": [], "has_more": False, "next_before": None}


@pytest.mark.parametrize("changes", [
    {"items": (summary(1), summary(2)), "has_more": False, "next_before": None},
    {"items": (summary(2), summary(2)), "has_more": False, "next_before": None},
    {"items": (), "has_more": True, "next_before": UUID(int=1)},
    {"items": (summary(2),), "has_more": True, "next_before": UUID(int=1)},
    {"items": (summary(2),), "has_more": False, "next_before": UUID(int=2)},
])
def test_rejects_unstable_or_unusable_pages(changes):
    with pytest.raises(ValidationError):
        PrivateTaskList(**changes)


def test_summary_rejects_permission_fields_and_naive_dates():
    with pytest.raises(ValidationError):
        PrivateTaskSummary(**summary(1).model_dump(), owner_subject="teacher")
    with pytest.raises(ValidationError):
        PrivateTaskSummary(**{**summary(1).model_dump(), "created_at": datetime(2026, 10, 6)})
