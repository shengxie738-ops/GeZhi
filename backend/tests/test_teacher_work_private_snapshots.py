"""Pure snapshot projection/immutability, separate from native acceptance."""
import pytest
from pydantic import ValidationError

from app.repositories.teacher_work import WorkRepositoryError
from app.schemas.teacher_work import PrivateTaskCapabilities
from tests.test_teacher_work_repository import create, setup_repository


def test_private_projection_keeps_anchor_and_copies_public_arrays():
    repository, memory = setup_repository()
    task = create(repository, memory)
    with memory:
        snapshot = repository.get_private_snapshot("A", task.task_id)
    assert snapshot.task == task
    data = snapshot.public_data()
    assert not {"owner_subject", "owner_storage_id", "institution_id", "offering_id", "lesson_draft_id"} & data.keys()
    assert data["created_at"].endswith("Z") and data["updated_at"].endswith("Z")
    original = snapshot.working.resource_ids
    data["working"]["resource_ids"][0] = "public-mutation"
    assert snapshot.working.resource_ids == original and snapshot.public_data()["working"]["resource_ids"] != ["public-mutation"]
    with pytest.raises(ValidationError):
        snapshot.working.requirements = "mutated"
    with pytest.raises(TypeError):
        snapshot.working.resource_ids[0] = "mutated"


def test_private_capabilities_strict_default_closed():
    assert PrivateTaskCapabilities().model_dump() == {"create": False, "read": False, "update": False}
    for body in ({"create": "yes"}, {"read": 1}, {"delete": True}):
        with pytest.raises(ValidationError):
            PrivateTaskCapabilities.model_validate(body)
