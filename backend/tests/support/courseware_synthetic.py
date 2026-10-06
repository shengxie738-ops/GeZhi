"""Owned, tiny engineering documents. Never represents actual course materials."""
from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from pptx import Presentation

from app.services.teacher_lesson_prep.courseware_catalog import DEFAULT_COURSE_DIRECTORIES

PDF_PAGES = (
    "Synthetic engineering fixture. Utility functions select actions.",
    "Synthetic second page. Computer instructions connect software and hardware.",
)
SLIDE_TEXTS = ("Synthetic slide one: linked list nodes.", "Synthetic slide two: pointer changes.")
AI_PDF = "/AI_technology/synthetic-decisions.pdf"
COMPUTER_PDF = "/Computer_ Organization/synthetic-introduction.pdf"


def write_pdf(path: Path, pages=PDF_PAGES):
    writer = PdfWriter()
    for value in pages:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                                 NameObject("/Subtype"): NameObject("/Type1"),
                                 NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
            DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        escaped = value.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 30 750 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.add_metadata({"/Title": "Synthetic engineering fixture", "/Subject": "Not actual教材"})
    with path.open("wb") as handle:
        writer.write(handle)


def build_courseware(frontend: Path):
    """Five PDFs, one real PPTX and one unread unsupported-extension sentinel."""
    frontend.mkdir()
    filenames = dict(zip(DEFAULT_COURSE_DIRECTORIES, (
        "synthetic-decisions.pdf", "synthetic-introduction.pdf", "synthetic-database.pdf",
        "synthetic-programming.pdf", "synthetic-structure.pdf")))
    for course, name in filenames.items():
        folder = frontend / course
        folder.mkdir()
        write_pdf(folder / name)
    presentation = Presentation()
    for value in SLIDE_TEXTS:
        slide = presentation.slides.add_slide(presentation.slide_layouts[1])
        slide.shapes.title.text = "Synthetic engineering fixture"
        slide.placeholders[1].text = value
    presentation.save(frontend / "data_structure/synthetic-slides.pptx")
    # Production explicitly does not parse .ppt. This is a named extension
    # sentinel, not a valid legacy Office file or a claim of legacy extraction.
    (frontend / "data_structure/synthetic-unsupported.ppt").write_bytes(
        b"Synthetic unsupported extension sentinel; not legacy Office bytes.\n")
    excluded = frontend / "not_a_course"
    excluded.mkdir()
    write_pdf(excluded / "synthetic-excluded.pdf")
    return frontend
