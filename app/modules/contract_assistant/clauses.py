"""Deterministic clause extraction.

A clause is found by pattern matching against the configured vocabulary, not by
asking a language model. That choice is deliberate and it is the project's
central rule: an extraction that can be done reliably by code is done by code,
because a rule-based match is reproducible, auditable and free, and it can
point at the exact page and heading it came from.

What the AI layer adds on top is a *plain-language summary* of an already
extracted clause, in its own field, labelled with its origin. It never decides
whether a clause exists, never changes an excerpt and never invents a page
number.

Every extraction carries four things, because a clause a reviewer cannot verify
is worthless:

* the page number,
* the section heading it sat under,
* a short supporting excerpt,
* a confidence score built from the evidence that was actually seen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.core.security import contains_injection_markers
from app.modules.contract_assistant.segmentation import DocumentIndex, Section
from app.modules.contract_assistant.thresholds import (
    CLAUSE_TYPES,
    ClauseSpec,
    ContractAssistantConfig,
)

logger = get_logger(__name__)

__all__ = [
    "ClauseExtraction",
    "SourceReference",
    "extract_clauses",
    "extract_clause_type",
]


@dataclass
class SourceReference:
    """Where one piece of extracted information came from.

    This is the module's contract with a reviewer: every clause and every
    answer can be opened on the page it was read from.
    """

    page_number: int | None = None
    section_heading: str | None = None
    section_number: str | None = None
    excerpt: str = ""
    confidence: float = 0.0
    char_offset: int | None = None
    clause_type: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "section_heading": self.section_heading,
            "section_number": self.section_number,
            "excerpt": self.excerpt,
            "confidence": round(float(self.confidence), 3),
            "char_offset": self.char_offset,
            "clause_type": self.clause_type,
        }


@dataclass
class ClauseExtraction:
    """One extracted clause."""

    clause_type: str
    label: str
    description: str
    present: bool
    importance: str
    required: bool
    confidence: float = 0.0
    text: str = ""
    references: list[SourceReference] = field(default_factory=list)
    matched_terms: list[str] = field(default_factory=list)
    heading_matched: bool = False
    needs_review: bool = False
    #: Structured values pulled out of the clause (notice days, net days, cap).
    values: dict[str, Any] = field(default_factory=dict)
    #: Optional, clearly separated AI summary. Never overwrites ``text``.
    ai_summary: str | None = None
    ai_origin: str | None = None

    @property
    def primary_reference(self) -> SourceReference | None:
        return self.references[0] if self.references else None

    @property
    def page_number(self) -> int | None:
        reference = self.primary_reference
        return reference.page_number if reference else None

    @property
    def section_heading(self) -> str | None:
        reference = self.primary_reference
        return reference.section_heading if reference else None

    @property
    def excerpt(self) -> str:
        reference = self.primary_reference
        return reference.excerpt if reference else ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_type": self.clause_type,
            "label": self.label,
            "description": self.description,
            "present": self.present,
            "importance": self.importance,
            "required": self.required,
            "confidence": round(float(self.confidence), 3),
            "page_number": self.page_number,
            "section_heading": self.section_heading,
            "excerpt": self.excerpt,
            "text": self.text,
            "matched_terms": list(self.matched_terms),
            "heading_matched": self.heading_matched,
            "needs_review": self.needs_review,
            "values": dict(self.values),
            "references": [reference.to_dict() for reference in self.references],
            "ai_summary": self.ai_summary,
            "ai_origin": self.ai_origin,
        }


@dataclass
class _Hit:
    """One raw pattern hit before it becomes a reference."""

    offset: int
    term: str
    primary: bool
    section: Section | None
    page_number: int


def extract_clauses(
    index: DocumentIndex, config: ContractAssistantConfig
) -> dict[str, ClauseExtraction]:
    """Extract every configured clause type from an indexed document."""
    return {name: extract_clause_type(name, index, config) for name in CLAUSE_TYPES}


def extract_clause_type(
    clause_type: str, index: DocumentIndex, config: ContractAssistantConfig
) -> ClauseExtraction:
    """Extract one clause type, present or absent."""
    spec = config.clause(clause_type)
    absent = ClauseExtraction(
        clause_type=clause_type,
        label=spec.label,
        description=spec.description,
        present=False,
        importance=spec.importance,
        required=spec.required,
        confidence=0.0,
    )
    if not index.text.strip():
        return absent

    hits = _collect_hits(spec, index)
    if not any(hit.primary for hit in hits):
        # Secondary phrases alone are not a clause: "written notice" appears in
        # half a contract and would otherwise report a termination clause in a
        # document that has none.
        return absent

    groups = _group_hits(hits, index, config)
    references: list[SourceReference] = []
    matched_terms: list[str] = []
    heading_matched = False
    best_confidence = 0.0

    pages_with_primary = {hit.page_number for hit in hits if hit.primary}
    scattered = len(pages_with_primary) > 2

    for group in groups[: config.extraction.max_instances_per_clause]:
        anchor = group[0]
        primary_hits = sum(1 for hit in group if hit.primary)
        secondary_hits = sum(1 for hit in group if not hit.primary)
        section = anchor.section
        group_heading_match = _heading_matches(spec, section)
        heading_matched = heading_matched or group_heading_match

        excerpt = index.excerpt(anchor.offset)
        values = extract_values(clause_type, excerpt, config)
        confidence = config.confidence.score(
            heading_match=group_heading_match,
            primary_hits=primary_hits,
            secondary_hits=secondary_hits,
            value_extracted=bool(values),
            scattered=scattered,
        )
        best_confidence = max(best_confidence, confidence)
        references.append(
            SourceReference(
                page_number=anchor.page_number,
                section_heading=section.label if section else None,
                section_number=section.number if section else None,
                excerpt=excerpt,
                confidence=confidence,
                char_offset=anchor.offset,
                clause_type=clause_type,
            )
        )
        matched_terms.extend(hit.term for hit in group if hit.primary)

    if best_confidence < config.extraction.min_confidence:
        return absent

    references.sort(key=lambda reference: -reference.confidence)
    text = references[0].excerpt if references else ""
    values = extract_values(clause_type, " ".join(r.excerpt for r in references), config)

    return ClauseExtraction(
        clause_type=clause_type,
        label=spec.label,
        description=spec.description,
        present=True,
        importance=spec.importance,
        required=spec.required,
        confidence=best_confidence,
        text=text,
        references=references,
        matched_terms=sorted(dict.fromkeys(matched_terms)),
        heading_matched=heading_matched,
        needs_review=best_confidence < config.extraction.review_below_confidence,
        values=values,
    )


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def _collect_hits(spec: ClauseSpec, index: DocumentIndex) -> list[_Hit]:
    """Find every primary and secondary pattern hit for one clause type.

    A primary hit is dropped when its own sentence carries one of the clause's
    negation phrases: "This Agreement does not renew automatically" contains
    "renew automatically" and asserts the opposite of it.
    """
    hits: list[_Hit] = []
    for patterns, primary in ((spec.primary, True), (spec.secondary, False)):
        for pattern in patterns:
            for match in pattern.finditer(index.text):
                offset = match.start()
                if primary and spec.negations:
                    sentence = index.sentence_at(offset)
                    if any(negation.search(sentence) for negation in spec.negations):
                        continue
                hits.append(
                    _Hit(
                        offset=offset,
                        term=_normalise_term(match.group(0)),
                        primary=primary,
                        section=index.section_for(offset),
                        page_number=index.page_for(offset),
                    )
                )
    hits.sort(key=lambda hit: hit.offset)
    return hits


def _group_hits(
    hits: list[_Hit], index: DocumentIndex, config: ContractAssistantConfig
) -> list[list[_Hit]]:
    """Group hits into clause instances, anchored on a primary hit.

    Hits inside the same section belong together; outside a section the excerpt
    window is used, so two mentions a page apart do not merge into one clause.
    """
    window = config.extraction.excerpt_chars
    groups: list[list[_Hit]] = []
    current: list[_Hit] = []
    current_section: Section | None = None

    for hit in hits:
        if not current:
            if hit.primary:
                current, current_section = [hit], hit.section
            continue
        same_section = (
            current_section is not None
            and hit.section is not None
            and hit.section.index == current_section.index
        )
        near = hit.offset - current[0].offset <= window
        if same_section or near:
            current.append(hit)
            continue
        groups.append(current)
        current, current_section = ([hit], hit.section) if hit.primary else ([], None)
    if current:
        groups.append(current)

    # Best evidence first: most primary hits, then earliest in the document.
    groups.sort(key=lambda group: (-sum(1 for hit in group if hit.primary), group[0].offset))
    return groups


def _heading_matches(spec: ClauseSpec, section: Section | None) -> bool:
    """Return ``True`` when the section heading names this clause type."""
    if section is None:
        return False
    heading = section.label
    return any(pattern.search(heading) for pattern in spec.headings)


def _normalise_term(text: str) -> str:
    """Collapse a matched phrase into a short, readable term."""
    collapsed = re.sub(r"\s+", " ", text).strip().lower()
    return collapsed[:60]


# ---------------------------------------------------------------------------
# Structured values
# ---------------------------------------------------------------------------


def extract_values(
    clause_type: str, text: str, config: ContractAssistantConfig
) -> dict[str, Any]:
    """Pull the structured numbers a clause type carries out of its text.

    Only clause types that actually have a number have an entry here. Anything
    that cannot be parsed is simply absent from the result - never zero, and
    never a default that would look like a real figure downstream.
    """
    if not text:
        return {}
    values: dict[str, Any] = {}

    if clause_type == "payment_terms":
        days = _first_int(text, config.payment.net_days)
        if days is not None:
            values["net_days"] = days
        for pattern in config.payment.discounts:
            match = pattern.search(text)
            if match:
                groups = match.groupdict()
                values["early_payment_discount_pct"] = float(groups["pct"])
                values["early_payment_days"] = int(groups["days"])
                break

    elif clause_type == "termination":
        from app.modules.contract_assistant.dates import find_all_durations

        durations = find_all_durations(text, config.dates.patterns_for("notice_period"), config)
        if durations:
            shortest = min(durations, key=lambda item: item.days)
            values["notice_period_days"] = shortest.days
            values["notice_period_label"] = shortest.label
            if len(durations) > 1:
                values["notice_periods_found"] = [item.label for item in durations]

    elif clause_type == "auto_renewal":
        from app.modules.contract_assistant.dates import find_duration

        renewal = find_duration(text, config.dates.patterns_for("renewal_term"), config)
        if renewal is not None:
            values["renewal_term_days"] = renewal.days
            values["renewal_term_label"] = renewal.label
        notice = find_duration(text, config.dates.patterns_for("notice_period"), config)
        if notice is not None:
            values["renewal_notice_days"] = notice.days
            values["renewal_notice_label"] = notice.label

    elif clause_type in {"liability", "penalties", "insurance"}:
        match = config.amounts.amount.search(text)
        if match:
            amount = _parse_amount(match.group("amount"))
            if amount is not None:
                values["amount"] = amount
                values["currency"] = config.amounts.currency_for(match.group("currency"))
        percentage = config.amounts.percentage.search(text)
        if percentage:
            values["percentage"] = float(percentage.group("pct"))

    elif clause_type == "service_levels":
        percentage = config.amounts.percentage.search(text)
        if percentage:
            values["availability_pct"] = float(percentage.group("pct"))

    elif clause_type == "governing_law":
        jurisdiction = _extract_jurisdiction(text)
        if jurisdiction:
            values["jurisdiction"] = jurisdiction

    if contains_injection_markers(text):
        # Recorded, never acted on. The engine turns this into a finding.
        values["contains_instruction_like_text"] = True

    return values


def _first_int(text: str, patterns: list[re.Pattern[str]]) -> int | None:
    """Return the first integer captured by one of ``patterns``."""
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            for group in match.groupdict().values():
                if group and str(group).isdigit():
                    return int(group)
    return None


def _parse_amount(raw: str) -> float | None:
    """Parse ``1.000.000,00`` / ``1,000,000.00`` into a float."""
    cleaned = raw.strip()
    if "," in cleaned and "." in cleaned:
        # Whichever separator comes last is the decimal separator.
        decimal = "," if cleaned.rfind(",") > cleaned.rfind(".") else "."
        thousands = "." if decimal == "," else ","
        cleaned = cleaned.replace(thousands, "").replace(decimal, ".")
    elif "," in cleaned:
        parts = cleaned.split(",")
        cleaned = cleaned.replace(",", "" if len(parts[-1]) == 3 else ".")
    try:
        return float(cleaned)
    except ValueError:
        return None


_JURISDICTION = re.compile(
    r"laws?\s+of\s+(?:the\s+)?(?P<name>[A-Z][A-Za-z ]{2,40}?)(?=[,.;)]|\s+and\b|\s+without\b|$)",
    re.IGNORECASE,
)


def _extract_jurisdiction(text: str) -> str | None:
    """Read the named jurisdiction out of a governing-law clause."""
    match = _JURISDICTION.search(text)
    if not match:
        return None
    name = re.sub(r"\s+", " ", match.group("name")).strip(" .,")
    return name or None
