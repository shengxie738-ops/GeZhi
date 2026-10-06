"""Pure manual material shaping. No storage/client/renderer construction."""
from app.services.teacher_work.types import canonical_digest
from app.services.teacher_work.exporters.validation import _require_xml_text
from app.services.teacher_work.exporters.theme import check_density, text_boxes, TITLE_FONT_SIZE, BODY_FONT_SIZE


def outline_digest(snapshot):
    return canonical_digest(snapshot.model_dump(mode="json", exclude={"outline_id", "outline_digest", "created_at"}))


def source_digest(task, requirements, resources):
    return canonical_digest({"task_id": str(task.task_id), "input_revision": task.input_revision,
        **{name: getattr(task, name) for name in ("title", "topic", "audience", "duration_minutes", "target_slide_count")},
        "requirements": requirements, "resources": [{"resource_id": key, "sha256": digest} for key, digest in resources],
        "reference_ids": [str(value) for value in task.reference_ids]})


def check_manual_approval_content(lesson, slides):
    """Reuse conservative exporter text checks, without building Office bytes."""
    from app.services.teacher_work.exporters.validation import check_docx_snapshot_text
    check_docx_snapshot_text(lesson)
    for page, slide in enumerate(slides, 1):
        _require_xml_text(slide.model_dump())
        boxes = text_boxes(slide.layout)
        check_density((slide.title,), boxes["gezhi:title"], TITLE_FONT_SIZE, page)
        check_density((slide.source_note,), boxes["gezhi:source"], 10, page)
        if slide.layout == "two_column":
            for name, items in zip(("gezhi:left", "gezhi:right"), slide.columns):
                check_density(items, boxes[name], BODY_FONT_SIZE, page)
        else:
            check_density(slide.body, boxes["gezhi:body"], BODY_FONT_SIZE, page)
