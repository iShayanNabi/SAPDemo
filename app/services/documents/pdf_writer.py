"""A minimal, dependency-free writer for text-based PDFs.

The Contract Assistant has to be *tested* against real PDFs, and the bundled
sample contracts have to ship as real PDFs. Every Python library that writes
PDFs is another dependency for something the lab needs in exactly one shape:
Helvetica text, one column, several pages, extractable by ``pypdf``.

So this module writes that PDF directly. It emits an uncompressed PDF 1.4 with
a single Type 1 base font, one content stream per page and a correct cross
reference table - the minimum a conforming reader needs, and enough that the
text comes back out through the same ``PdfTextExtractor`` a user's contract
goes through.

It has a second consumer: the Test Case Generator's PDF export, which is a
readable test script rather than a laid-out report - the same requirement, one
column of text that a reviewer reads top to bottom.

It is a *plain text PDF writer*, not a reporting engine: no images, no tables,
no styling beyond a bold-ish title size. Anything needing a real layout belongs
in a proper reporting library, not here.
"""

from __future__ import annotations

from dataclasses import dataclass

#: US Letter at 72 dpi, the default a PDF reader assumes.
PAGE_WIDTH = 612
PAGE_HEIGHT = 792
MARGIN = 56
BODY_FONT_SIZE = 10.5
LINE_HEIGHT = 14
#: Characters that fit on one line at the body size, used for wrapping.
CHARS_PER_LINE = 92
#: Lines that fit between the margins.
LINES_PER_PAGE = int((PAGE_HEIGHT - 2 * MARGIN) / LINE_HEIGHT)


@dataclass(frozen=True)
class PdfDocument:
    """A finished PDF payload plus the page count it was laid out into."""

    content: bytes
    page_count: int


def build_text_pdf(text: str, *, title: str | None = None) -> PdfDocument:
    """Render ``text`` into a text-based PDF.

    Explicit form feeds (``\\f``) start a new page; otherwise pages break when
    the line budget runs out. The result is a real PDF whose text extracts
    cleanly, which is what makes it a useful fixture.
    """
    pages = _lay_out(text)
    if not pages:
        pages = [[""]]
    return PdfDocument(content=_assemble(pages, title=title), page_count=len(pages))


def _lay_out(text: str) -> list[list[str]]:
    """Wrap ``text`` into a list of pages, each a list of rendered lines."""
    pages: list[list[str]] = []
    current: list[str] = []

    for block in (text or "").split("\f"):
        for raw_line in block.split("\n"):
            for line in _wrap(raw_line.rstrip()):
                if len(current) >= LINES_PER_PAGE:
                    pages.append(current)
                    current = []
                current.append(line)
        # A form feed always starts a new page, even mid-budget.
        if current:
            pages.append(current)
            current = []
    if current:
        pages.append(current)
    return pages


def _wrap(line: str) -> list[str]:
    """Wrap one logical line to the page width, preserving its indentation."""
    if not line:
        return [""]
    if len(line) <= CHARS_PER_LINE:
        return [line]

    indent = line[: len(line) - len(line.lstrip())]
    words = line.split()
    wrapped: list[str] = []
    current = indent
    for word in words:
        candidate = f"{current}{word}" if current in ("", indent) else f"{current} {word}"
        if len(candidate) > CHARS_PER_LINE and current.strip():
            wrapped.append(current)
            current = f"{indent}{word}"
        else:
            current = candidate
    if current.strip():
        wrapped.append(current)
    return wrapped or [""]


def _escape(text: str) -> str:
    """Escape a string for a PDF literal, dropping characters WinAnsi lacks."""
    encodable = text.encode("cp1252", "replace").decode("cp1252")
    return encodable.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _content_stream(lines: list[str]) -> bytes:
    """Build the drawing commands for one page."""
    parts = ["BT", f"/F1 {BODY_FONT_SIZE} Tf", f"{LINE_HEIGHT} TL"]
    parts.append(f"1 0 0 1 {MARGIN} {PAGE_HEIGHT - MARGIN} Tm")
    for index, line in enumerate(lines):
        if index:
            parts.append("T*")
        parts.append(f"({_escape(line)}) Tj")
    parts.append("ET")
    return "\n".join(parts).encode("cp1252", "replace")


def _assemble(pages: list[list[str]], *, title: str | None) -> bytes:
    """Serialise the laid-out pages into a complete PDF file."""
    page_count = len(pages)
    # Object numbering: 1 catalog, 2 pages tree, 3 font,
    # then per page: a page object and its content stream.
    font_object = 3
    first_page_object = 4
    page_object_ids = [first_page_object + index * 2 for index in range(page_count)]
    stream_object_ids = [object_id + 1 for object_id in page_object_ids]

    objects: dict[int, bytes] = {}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    kids = " ".join(f"{object_id} 0 R" for object_id in page_object_ids)
    objects[2] = (
        f"<< /Type /Pages /Count {page_count} /Kids [{kids}] >>".encode("ascii")
    )
    objects[font_object] = (
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
        b"/Encoding /WinAnsiEncoding >>"
    )

    for index, lines in enumerate(pages):
        page_id = page_object_ids[index]
        stream_id = stream_object_ids[index]
        objects[page_id] = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_WIDTH} {PAGE_HEIGHT}] "
            f"/Resources << /Font << /F1 {font_object} 0 R >> >> "
            f"/Contents {stream_id} 0 R >>"
        ).encode("ascii")
        stream = _content_stream(lines)
        objects[stream_id] = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii")
            + stream
            + b"\nendstream"
        )

    info_id = max(objects) + 1
    safe_title = _escape(title or "Contract")
    objects[info_id] = f"<< /Title ({safe_title}) /Producer (SAP AI Application Lab) >>".encode(
        "cp1252", "replace"
    )

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: dict[int, int] = {}
    for object_id in sorted(objects):
        offsets[object_id] = len(out)
        out += f"{object_id} 0 obj\n".encode("ascii")
        out += objects[object_id]
        out += b"\nendobj\n"

    xref_offset = len(out)
    highest = max(objects)
    out += f"xref\n0 {highest + 1}\n".encode("ascii")
    out += b"0000000000 65535 f \n"
    for object_id in range(1, highest + 1):
        out += f"{offsets[object_id]:010d} 00000 n \n".encode("ascii")
    out += (
        f"trailer\n<< /Size {highest + 1} /Root 1 0 R /Info {info_id} 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n"
    ).encode("ascii")
    return bytes(out)
