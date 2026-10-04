"""Server-owned GeZhi theme constants; no font discovery or external assets."""
from dataclasses import dataclass, field


TEMPLATE_VERSION = "gezhi-office-theme@1"
PPTX_EXPORTER_VERSION = "gezhi-pptx@1"
DOCX_EXPORTER_VERSION = "gezhi-docx@1"
PPTX_FONT = "Microsoft YaHei"
PPTX_FONT_DISCLOSURE = "字体：Microsoft YaHei；可替代：PingFang SC、黑体；未嵌入字体"
DOCX_FONT_DISCLOSURE = "字体：黑体/宋体；可替代：Microsoft YaHei、Songti SC；未嵌入字体"
WIDTH = 960
HEIGHT = 540
EMU_PER_POINT = 12700
BODY_FONT_SIZE = 24
TITLE_FONT_SIZE = 32
INK = "1C2B38"
SECONDARY = "52606D"
ACCENT = "B91C1C"
RULE = "D7DDE3"
BACKGROUND = "FFFFFF"


@dataclass(frozen=True)
class ThemeVersion:
    """A selected fixed release, never a request-supplied style configuration."""
    version: str = field(default=TEMPLATE_VERSION, init=False)


def text_boxes(layout: str) -> dict[str, tuple[int, int, int, int]]:
    """Fixed native box geometry in points; all six layouts share readable sizes."""
    if layout not in {"title", "section", "bullets", "two_column", "question", "summary"}:
        raise ValueError("UNSUPPORTED_LAYOUT")
    boxes = {
        "gezhi:title": (40, 36, 880, 86),
        "gezhi:source": (40, 480, 880, 30),
        "gezhi:font": (40, 515, 880, 16),
    }
    if layout == "two_column":
        boxes.update({"gezhi:left": (40, 142, 420, 316), "gezhi:right": (500, 142, 420, 316)})
    elif layout == "title":
        boxes["gezhi:body"] = (40, 170, 880, 288)
    elif layout == "section":
        boxes["gezhi:body"] = (40, 160, 880, 298)
    elif layout == "question":
        boxes["gezhi:body"] = (60, 142, 840, 316)
    else:
        boxes["gezhi:body"] = (40, 142, 880, 316)
    return boxes


def check_density(items: tuple[str, ...], box: tuple[int, int, int, int], size: int, page: int) -> None:
    """Conservative CJK-width estimate, not a claim about actual Office metrics.

    Every codepoint is budgeted at a full em, including ASCII; tabs at four ems.
    Explicit line breaks and empty lines count. No text fitting, clipping, font
    discovery, truncation or outline editing occurs here.
    """
    usable_width = box[2] - 16
    usable_height = box[3] - 16
    columns = max(1, int(usable_width // size))
    lines = 0
    for item in items:
        for line in item.split("\n"):
            units = sum(4 if char == "\t" else 1 for char in line)
            lines += max(1, (units + columns - 1) // columns)
    required = lines * size * 1.2 + max(0, len(items) - 1) * 6
    if required > usable_height:
        raise ValueError(f"SLIDE_OVERFLOW:page={page}")
