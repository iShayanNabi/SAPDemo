"""Page segmentation and section detection.

Every extracted clause has to be able to say *where* it came from. That means
the document cannot be flattened into one string and searched: a match offset
must be translatable back into a page number and the heading it sat under.

:class:`DocumentIndex` is that translation. It concatenates the extracted pages
once, remembers where each page starts, detects the headings, and then answers
``page_for(offset)`` and ``section_for(offset)`` in one step.

Heading detection deliberately does not rely on blank lines: PDF text
extraction discards them, so a detector built on spacing would work on TXT and
DOCX and quietly fail on the format users actually upload. What it uses instead
is what survives extraction - clause numbering (``4.2 Termination``), the
ARTICLE/SECTION keywords, and full-capital or title-case lines that carry no
sentence verb.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from app.modules.contract_assistant.thresholds import ContractAssistantConfig
from app.services.documents.base import ExtractedPage

#: Pages are joined with a newline so an offset never straddles two pages
#: without a boundary character between them.
PAGE_SEPARATOR = "\n"

_SENTENCE_END = re.compile(r"[.!?][\"')\]]?\s")
_WHITESPACE = re.compile(r"\s+")


@dataclass(frozen=True)
class PageSpan:
    """One page's position inside the concatenated document text."""

    page_number: int
    start: int
    end: int
    text: str


@dataclass
class Section:
    """One detected section of the contract."""

    index: int
    number: str | None
    title: str
    heading: str
    page_number: int
    start: int
    end: int

    @property
    def label(self) -> str:
        """The heading exactly as the document prints it: ``4.2 Termination``.

        Citing the raw line rather than a reassembled ``number + title`` keeps
        the reference verbatim, so a reviewer can search for it in the original
        file and find it character for character.
        """
        if self.heading.strip():
            return self.heading.strip()
        if self.number and self.title:
            return f"{self.number} {self.title}".strip()
        return (self.number or self.title or "").strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "index": self.index,
            "number": self.number,
            "title": self.title,
            "heading": self.label,
            "page_number": self.page_number,
            "start": self.start,
            "end": self.end,
        }


class DocumentIndex:
    """A searchable view of an extracted document that never loses provenance."""

    def __init__(
        self, pages: list[ExtractedPage], config: ContractAssistantConfig
    ) -> None:
        self.config = config
        self._spans: list[PageSpan] = []

        chunks: list[str] = []
        cursor = 0
        for page in pages:
            text = page.text or ""
            self._spans.append(
                PageSpan(page_number=page.page_number, start=cursor, end=cursor + len(text), text=text)
            )
            chunks.append(text)
            cursor += len(text) + len(PAGE_SEPARATOR)

        self.text: str = PAGE_SEPARATOR.join(chunks)
        # A newline-free view of exactly the same length, so an offset means the
        # same thing in both. PDF extraction hard-wraps sentences, which would
        # otherwise hide "...in force until 31 March\n2029" from any pattern
        # that has to exclude newlines to stop at a sentence boundary.
        self.flat_text: str = self.text.replace("\n", " ")
        self.sections: list[Section] = detect_sections(self.text, self._spans, config)

    # -- geometry --------------------------------------------------------
    @property
    def page_count(self) -> int:
        return len(self._spans)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def pages(self) -> list[PageSpan]:
        return list(self._spans)

    def page_for(self, offset: int) -> int:
        """Return the 1-based page number containing ``offset``."""
        for span in self._spans:
            if span.start <= offset <= span.end:
                return span.page_number
        return self._spans[-1].page_number if self._spans else 1

    def section_for(self, offset: int) -> Section | None:
        """Return the section ``offset`` falls inside, if any."""
        for section in self.sections:
            if section.start <= offset < section.end:
                return section
        return None

    def page_text(self, page_number: int) -> str:
        for span in self._spans:
            if span.page_number == page_number:
                return span.text
        return ""

    def section_span(self, index: int) -> tuple[int, int] | None:
        """Return the ``(start, end)`` offsets of one section by its index."""
        for section in self.sections:
            if section.index == index:
                return section.start, section.end
        return None

    # -- excerpting ------------------------------------------------------
    def excerpt(self, offset: int, *, length: int | None = None) -> str:
        """Return a short, readable excerpt around ``offset``.

        The excerpt starts at the beginning of the sentence the match sits in
        (or a configured number of characters before it, whichever is closer)
        and stops at a sentence boundary, so a citation reads like a quotation
        rather than a slice.

        It is also clamped to the section the match sits in. Without that, a
        payment-terms excerpt runs on into the pricing and liability clauses
        that follow it, and the "short supporting excerpt" stops supporting
        anything in particular.
        """
        settings = self.config.extraction
        length = length or settings.excerpt_chars
        section = self.section_for(offset)
        floor, ceiling = (section.start, section.end) if section else (0, len(self.text))

        start = max(floor, offset - settings.context_chars_before)
        boundary = _last_sentence_boundary(self.text[start:offset])
        if boundary is not None:
            start += boundary

        end = min(ceiling, start + length)
        tail = self.text[end : min(ceiling, end + 200)]
        match = _SENTENCE_END.search(tail)
        if match:
            end = min(ceiling, end + match.end())
        end = min(end, start + settings.max_excerpt_chars)

        return _WHITESPACE.sub(" ", self.text[start:end]).strip()

    def sentence_at(self, offset: int, *, max_chars: int = 400) -> str:
        """Return the single sentence containing ``offset``."""
        start = max(0, offset - max_chars)
        boundary = _last_sentence_boundary(self.text[start:offset])
        begin = start + boundary if boundary is not None else start
        match = _SENTENCE_END.search(self.text, offset)
        end = match.end() if match else min(len(self.text), offset + max_chars)
        return _WHITESPACE.sub(" ", self.text[begin:end]).strip()

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_count": self.page_count,
            "char_count": self.char_count,
            "section_count": len(self.sections),
            "sections": [section.to_dict() for section in self.sections],
        }


# ---------------------------------------------------------------------------
# Heading detection
# ---------------------------------------------------------------------------


def detect_sections(
    text: str, spans: list[PageSpan], config: ContractAssistantConfig
) -> list[Section]:
    """Find the headings in ``text`` and turn them into bounded sections."""
    settings = config.sections
    stop_words = {word.lower() for word in settings.stop_words_in_heading}

    found: list[tuple[int, str | None, str, str]] = []  # (offset, number, title, heading)
    offset = 0
    for line in text.split("\n"):
        stripped = line.strip()
        if _is_candidate(stripped, settings.min_heading_chars, settings.max_heading_chars):
            parsed = _parse_heading(stripped, config, stop_words)
            if parsed is not None:
                number, title = parsed
                found.append((offset, number, title, stripped))
        offset += len(line) + 1

    sections: list[Section] = []
    for index, (start, number, title, heading) in enumerate(found):
        end = found[index + 1][0] if index + 1 < len(found) else len(text)
        page_number = _page_for(start, spans)
        sections.append(
            Section(
                index=index,
                number=number,
                title=title,
                heading=heading,
                page_number=page_number,
                start=start,
                end=end,
            )
        )
    return sections


def _is_candidate(line: str, min_chars: int, max_chars: int) -> bool:
    """Cheap rejection before the (more expensive) pattern matching."""
    if not line:
        return False
    if not (min_chars <= len(line) <= max_chars):
        return False
    # A heading is not a sentence: it does not end in a full stop, and it does
    # not contain a mid-line sentence break.
    if line.endswith((".", ";", ",")) and not re.match(r"^\s*\d", line):
        return False
    return True


def _parse_heading(
    line: str, config: ContractAssistantConfig, stop_words: set[str]
) -> tuple[str | None, str] | None:
    """Return ``(number, title)`` when ``line`` looks like a heading."""
    settings = config.sections
    words = line.split()
    lowered = {word.strip(".,:;()").lower() for word in words}

    for pattern in settings.numbered:
        match = pattern.match(line)
        if match:
            groups = match.groupdict()
            number = (groups.get("number") or "").strip()
            title = (groups.get("title") or "").strip(" .:-")
            if title and len(title.split()) > settings.max_heading_words:
                continue
            if title and lowered & stop_words:
                continue
            return number or None, title
    if len(words) > settings.max_heading_words:
        return None
    if lowered & stop_words:
        return None

    match = settings.uppercase.match(line)
    if match:
        title = (match.groupdict().get("title") or "").strip()
        # A run of capitals with no lowercase letter anywhere is a heading;
        # a full sentence in capitals would have been rejected by the trailing
        # full stop check above.
        if title and title.upper() == title and any(ch.isalpha() for ch in title):
            return None, title.strip(" .:-")

    match = settings.title_case.match(line)
    if match:
        title = (match.groupdict().get("title") or "").strip(" .:-")
        if title and len(title.split()) >= 1:
            return None, title
    return None


def _page_for(offset: int, spans: list[PageSpan]) -> int:
    for span in spans:
        if span.start <= offset <= span.end:
            return span.page_number
    return spans[-1].page_number if spans else 1


def _last_sentence_boundary(window: str) -> int | None:
    """Return the offset just after the last sentence break in ``window``."""
    best: int | None = None
    for match in _SENTENCE_END.finditer(window):
        best = match.end()
    if best is None:
        # Fall back to a paragraph/line break, which is where a clause usually
        # starts in a contract that has no full stop in the preceding window.
        index = window.rfind("\n")
        if index != -1:
            best = index + 1
    return best
