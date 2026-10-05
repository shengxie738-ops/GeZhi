"""Strict frozen Work mapping around the unchanged legacy DOCX renderer body."""
from __future__ import annotations

from io import BytesIO
from time import monotonic

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Pt

from app.schemas.teacher_work import LessonSnapshot
from app.services.teacher_lesson_prep.docx_exporter import build_lesson_plan_docx
from app.services.teacher_work.exporters.theme import DOCX_FONT_DISCLOSURE
from app.services.teacher_work.exporters.validation import (
    _check_stage_time, _docx_expected_paragraphs, _finalize_generated_office_bytes,
    _parts_and_roots, _paragraphs, _require_xml_text,
)


def _exact_legacy_text(snapshot: LessonSnapshot) -> None:
    """Reject trimming/dropping/coercion instead of modifying the frozen lesson."""
    payload = snapshot.model_dump()
    _require_xml_text(payload, error="DOCX_UNREPRESENTABLE")
    strings = [payload[key] for key in ("title", "topic", "course_name", "audience", "summary")]
    for key in ("objectives", "key_points", "difficulties", "questions", "exercises", "homework"):
        strings.extend(payload[key])
    for stage in payload["teaching_flow"]:
        strings.extend((stage["stage"], stage["content"]))
    for citation in payload["citations"]:
        strings.extend((citation["name"], citation["excerpt"]))
        if not citation["name"] and not citation["excerpt"]:
            raise ValueError("DOCX_UNREPRESENTABLE")
    if any(text != text.strip() for text in strings):
        raise ValueError("DOCX_UNREPRESENTABLE")
    if snapshot.summary and any(not line or line != line.strip() for line in snapshot.summary.splitlines()):
        raise ValueError("DOCX_UNREPRESENTABLE")
    # XML/Office line ending normalization cannot silently alter a frozen string.
    if any("\r" in text or "\v" in text or "\f" in text for text in strings):
        raise ValueError("DOCX_UNREPRESENTABLE")


def build_docx(snapshot: LessonSnapshot) -> bytes:
    started = monotonic()
    if type(snapshot) is not LessonSnapshot:
        raise ValueError("INVALID_EXPORT_INPUT")
    snapshot = LessonSnapshot.model_validate(snapshot.model_dump())
    _exact_legacy_text(snapshot)
    # Full frozen JSON projection uses the exact legacy field names and plain lists/dicts.
    raw = build_lesson_plan_docx(snapshot.model_dump(mode="json"))
    _check_stage_time(started)
    raw = _finalize_generated_office_bytes("docx", raw)
    document = Document(BytesIO(raw))
    paragraph = document.add_paragraph()
    run = paragraph.add_run(DOCX_FONT_DISCLOSURE)
    run.font.name = "宋体"
    run.font.size = Pt(10)
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
    document.core_properties.author = "GeZhi"
    document.core_properties.last_modified_by = "GeZhi"
    document.core_properties.title = snapshot.title
    output = BytesIO()
    document.save(output)
    _check_stage_time(started)
    raw = _finalize_generated_office_bytes("docx", output.getvalue())
    _, roots = _parts_and_roots("docx", raw)
    if _paragraphs(roots["word/document.xml"], "w") != _docx_expected_paragraphs(snapshot):
        raise ValueError("DOCX_UNREPRESENTABLE")
    _check_stage_time(started)
    return raw
