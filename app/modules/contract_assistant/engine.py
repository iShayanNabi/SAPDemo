"""The Contract Assistant analysis engine.

One pure function, :func:`analyze_contract`, runs the documented pipeline over
an already-extracted document:

    page segmentation -> section detection -> document facts (title, parties)
    -> clause extraction -> key dates -> structured validation -> obligations
    -> missing clauses -> risk analysis -> risk score

It takes an :class:`ExtractionResult` and returns a
:class:`ContractAnalysisResult`. It never touches the database, never reads a
file and never calls an AI model, so it is fully reproducible and can be tested
without any of those things.

Every risk rule is isolated: a rule that raises is recorded in ``rule_errors``
and the remaining rules still run. An analysis is never lost to one bad rule.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.core.logging import get_logger
from app.core.security import contains_injection_markers
from app.modules.contract_assistant import dates as date_tools
from app.modules.contract_assistant.clauses import (
    ClauseExtraction,
    SourceReference,
    extract_clauses,
)
from app.modules.contract_assistant.obligations import Obligation, extract_obligations
from app.modules.contract_assistant.risk_rules import (
    RULES,
    ContractRiskFinding,
    RiskContext,
    run_rule,
)
from app.modules.contract_assistant.segmentation import DocumentIndex
from app.modules.contract_assistant.thresholds import (
    CLAUSE_TYPES,
    ContractAssistantConfig,
)
from app.schemas.common import OutputOrigin, Severity
from app.services.documents.base import ExtractionResult

logger = get_logger(__name__)

#: Bumped when the pipeline's behaviour changes. Stored on every analysis.
ENGINE_VERSION = "1.0.0"

__all__ = [
    "ENGINE_VERSION",
    "ContractAnalysisResult",
    "ContractParty",
    "MissingClause",
    "analyze_contract",
]

_WHITESPACE = re.compile(r"\s+")


@dataclass
class ContractParty:
    """One party named in the contract."""

    name: str
    role: str | None
    page_number: int | None
    section_heading: str | None
    excerpt: str
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "page_number": self.page_number,
            "section_heading": self.section_heading,
            "excerpt": self.excerpt,
            "confidence": round(float(self.confidence), 3),
        }


@dataclass
class MissingClause:
    """One clause type the configuration expected but the document lacks."""

    clause_type: str
    label: str
    importance: str
    required: bool
    message: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "clause_type": self.clause_type,
            "label": self.label,
            "importance": self.importance,
            "required": self.required,
            "message": self.message,
        }


@dataclass
class ContractAnalysisResult:
    """Everything one analysis produced."""

    contract_title: str | None
    title_reference: SourceReference | None
    parties: list[ContractParty]
    clauses: dict[str, ClauseExtraction]
    key_dates: dict[str, Any]
    obligations: list[Obligation]
    missing_clauses: list[MissingClause]
    risks: list[ContractRiskFinding]
    sections: list[dict[str, Any]]

    risk_score: float = 0.0
    risk_band: str = "low"
    severity_counts: dict[str, int] = field(default_factory=dict)
    clauses_found: int = 0
    clauses_expected: int = 0
    obligation_count: int = 0
    page_count: int = 0
    char_count: int = 0
    section_count: int = 0
    needs_ocr: bool = False
    injection_detected: bool = False
    injection_markers: list[str] = field(default_factory=list)
    extraction: dict[str, Any] = field(default_factory=dict)
    rule_errors: list[dict[str, str]] = field(default_factory=list)
    as_of_date: date | None = None
    config_version: str = ""
    engine_version: str = ENGINE_VERSION
    duration_ms: int = 0
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED

    def clause(self, clause_type: str) -> ClauseExtraction | None:
        return self.clauses.get(clause_type)

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_title": self.contract_title,
            "title_reference": self.title_reference.to_dict() if self.title_reference else None,
            "parties": [party.to_dict() for party in self.parties],
            "clauses": {name: clause.to_dict() for name, clause in self.clauses.items()},
            "key_dates": _dates_to_dict(self.key_dates),
            "obligations": [item.to_dict() for item in self.obligations],
            "missing_clauses": [item.to_dict() for item in self.missing_clauses],
            "risks": [item.to_dict() for item in self.risks],
            "sections": list(self.sections),
            "risk_score": round(self.risk_score, 2),
            "risk_band": self.risk_band,
            "severity_counts": dict(self.severity_counts),
            "clauses_found": self.clauses_found,
            "clauses_expected": self.clauses_expected,
            "obligation_count": self.obligation_count,
            "page_count": self.page_count,
            "char_count": self.char_count,
            "section_count": self.section_count,
            "needs_ocr": self.needs_ocr,
            "injection_detected": self.injection_detected,
            "injection_markers": list(self.injection_markers),
            "extraction": dict(self.extraction),
            "rule_errors": list(self.rule_errors),
            "as_of_date": self.as_of_date.isoformat() if self.as_of_date else None,
            "config_version": self.config_version,
            "engine_version": self.engine_version,
            "output_origin": self.output_origin.value,
        }


def analyze_contract(
    extraction: ExtractionResult,
    config: ContractAssistantConfig,
    *,
    as_of_date: date | None = None,
    enabled_rules: list[str] | None = None,
) -> ContractAnalysisResult:
    """Run the full deterministic analysis over an extracted document."""
    started = time.perf_counter()
    as_of = as_of_date or date.today()

    index = DocumentIndex(extraction.pages, config)
    title, title_reference = _extract_title(index, config)
    parties = _extract_parties(index, config)
    clause_map = extract_clauses(index, config)
    key_dates = _extract_key_dates(index, clause_map, config)

    clause_spans = {
        name: [
            (reference.char_offset, reference.char_offset + len(reference.excerpt))
            for reference in clause.references
            if reference.char_offset is not None
        ]
        for name, clause in clause_map.items()
        if clause.present
    }
    obligation_list = extract_obligations(
        index,
        config,
        party_names=[party.name for party in parties],
        clause_spans=clause_spans,
    )

    missing = [
        MissingClause(
            clause_type=name,
            label=config.clause(name).label,
            importance=config.clause(name).importance,
            required=config.clause(name).required,
            message=config.clause(name).missing_message,
        )
        for name in CLAUSE_TYPES
        if not clause_map[name].present and config.clause(name).required
    ]

    markers = _injection_markers(index.text)
    context = RiskContext(
        clauses=clause_map,
        key_dates=key_dates,
        config=config,
        as_of_date=as_of,
        full_text=index.text,
        char_count=index.char_count,
        needs_ocr=extraction.needs_ocr,
        injection_markers=markers,
    )

    risks, rule_errors = _run_rules(context, enabled_rules)
    risks.sort(key=lambda finding: (-finding.severity.rank, finding.rule_id))

    severity_counts = {level.value: 0 for level in Severity}
    for finding in risks:
        severity_counts[finding.severity.value] += 1

    score = min(
        sum(config.risk.weight_for(finding.severity) for finding in risks),
        config.risk.score_cap,
    )

    result = ContractAnalysisResult(
        contract_title=title,
        title_reference=title_reference,
        parties=parties,
        clauses=clause_map,
        key_dates=key_dates,
        obligations=obligation_list,
        missing_clauses=missing,
        risks=risks,
        sections=[section.to_dict() for section in index.sections],
        risk_score=round(score, 2),
        risk_band=config.risk.band_for(score),
        severity_counts=severity_counts,
        clauses_found=sum(1 for clause in clause_map.values() if clause.present),
        clauses_expected=len(CLAUSE_TYPES),
        obligation_count=len(obligation_list),
        page_count=index.page_count,
        char_count=index.char_count,
        section_count=len(index.sections),
        needs_ocr=extraction.needs_ocr,
        injection_detected=bool(markers),
        injection_markers=markers,
        extraction=extraction.to_dict(),
        rule_errors=rule_errors,
        as_of_date=as_of,
        config_version=config.config_version,
    )
    result.duration_ms = int((time.perf_counter() - started) * 1000)
    logger.info(
        "Analysed contract: %d/%d clauses, %d obligations, %d risks, score %.1f (%s)",
        result.clauses_found,
        result.clauses_expected,
        result.obligation_count,
        len(result.risks),
        result.risk_score,
        result.risk_band,
    )
    return result


# ---------------------------------------------------------------------------
# Document facts
# ---------------------------------------------------------------------------


def _extract_title(
    index: DocumentIndex, config: ContractAssistantConfig
) -> tuple[str | None, SourceReference | None]:
    """Read the contract title from the first page.

    Only the opening lines are scanned: a document that mentions "MASTER
    SERVICES AGREEMENT" on page 7 is referring to itself, not titling itself.
    """
    settings = config.document
    lines = index.text.split("\n")[: settings.title_scan_lines]
    offset = 0
    for line in lines:
        stripped = line.strip()
        for pattern in settings.titles:
            match = pattern.match(stripped)
            if match:
                title = _WHITESPACE.sub(" ", match.group("title")).strip()
                reference = SourceReference(
                    page_number=index.page_for(offset),
                    section_heading=None,
                    excerpt=stripped,
                    confidence=config.confidence.score(
                        heading_match=True,
                        primary_hits=1,
                        secondary_hits=0,
                        value_extracted=False,
                        scattered=False,
                    ),
                    char_offset=offset,
                )
                return title, reference
        offset += len(line) + 1

    # Fall back to the first detected heading, clearly at lower confidence.
    if index.sections:
        section = index.sections[0]
        return section.title or None, SourceReference(
            page_number=section.page_number,
            section_heading=section.label,
            excerpt=section.heading,
            confidence=config.confidence.base,
            char_offset=section.start,
        )
    return None, None


def _extract_parties(
    index: DocumentIndex, config: ContractAssistantConfig
) -> list[ContractParty]:
    """Read the party names from the opening of the contract."""
    settings = config.document
    # The flat view again: a party name hard-wrapped across two lines
    # ("Ravenna Frontier\nTrading Pte Ltd") would otherwise be captured from
    # the second half only.
    window = index.flat_text[: settings.party_scan_chars]
    found: dict[str, ContractParty] = {}

    for pattern in settings.parties:
        for match in pattern.finditer(window):
            name = settings.clean_party_name(match.groupdict().get("name") or "")
            if name is None:
                continue
            key = name.lower()
            if key in found:
                continue
            offset = match.start("name") if "name" in match.groupdict() else match.start()
            sentence = index.sentence_at(offset)
            found[key] = ContractParty(
                name=name,
                role=_role_for(sentence, name, config),
                page_number=index.page_for(offset),
                section_heading=(
                    index.section_for(offset).label if index.section_for(offset) else None
                ),
                excerpt=sentence,
                confidence=config.confidence.score(
                    heading_match=False,
                    primary_hits=1,
                    secondary_hits=1 if _role_for(sentence, name, config) else 0,
                    value_extracted=False,
                    scattered=False,
                ),
            )
            if len(found) >= settings.max_parties:
                return list(found.values())
    return list(found.values())


def _role_for(sentence: str, name: str, config: ContractAssistantConfig) -> str | None:
    """Read the role a party is given, from the text immediately around it."""
    index = sentence.lower().find(name.lower())
    window = sentence[index : index + 160] if index != -1 else sentence
    for role, patterns in config.document.roles.items():
        if any(pattern.search(window) for pattern in patterns):
            return role
    return None


# ---------------------------------------------------------------------------
# Key dates
# ---------------------------------------------------------------------------


def _extract_key_dates(
    index: DocumentIndex,
    clauses: dict[str, ClauseExtraction],
    config: ContractAssistantConfig,
) -> dict[str, Any]:
    """Extract the dates a contract register needs, and derive the rest.

    Two details matter here:

    * the search runs over ``index.flat_text``, which is the same length as the
      document but has no newlines, so a hard-wrapped ``until 31 March\\n2029``
      is still one phrase and the offsets still map back to a page;
    * the term length is looked for **inside the term clause first**, because
      ``for a period of 5 years`` also appears in a confidentiality clause and
      reading that as the contract term produces a confidently wrong expiry.
    """
    text = index.flat_text
    term_scope = _clause_scope(index, clauses, "term")
    result: dict[str, Any] = {}

    effective = _scoped_date(text, term_scope, "effective_date", config)
    expiration = _scoped_date(text, term_scope, "expiration_date", config)
    renewal = _scoped_date(text, term_scope, "renewal_date", config)
    signature = date_tools.find_first_by_patterns(
        text, config.dates.patterns_for("signature_date"), config
    )
    term_length = _scoped_duration(text, term_scope, "term_length", config)

    if effective:
        result["effective_date"] = effective.value
        result["effective_date_excerpt"] = effective.matched_text
        result["effective_date_page"] = index.page_for(effective.offset)
        result["effective_date_basis"] = "stated"
    if signature:
        result["signature_date"] = signature.value
        result["signature_date_excerpt"] = signature.matched_text
        result["signature_date_page"] = index.page_for(signature.offset)
        result["signature_date_basis"] = "stated"
    if term_length:
        result["term_length_days"] = term_length.days
        result["term_length_label"] = term_length.label

    if expiration:
        result["expiration_date"] = expiration.value
        result["expiration_date_excerpt"] = expiration.matched_text
        result["expiration_date_page"] = index.page_for(expiration.offset)
        result["expiration_date_basis"] = "stated"
    elif effective and term_length:
        derived = date_tools.add_duration(effective.value, term_length)
        if derived:
            result["expiration_date"] = derived
            result["expiration_date_basis"] = "derived_from_term"
            result["expiration_date_excerpt"] = (
                f"Derived: {effective.value.isoformat()} plus the stated "
                f"{term_length.label} term."
            )
            result["expiration_date_page"] = index.page_for(effective.offset)

    auto_renewal = clauses.get("auto_renewal")
    termination = clauses.get("termination")

    notice_days = None
    if termination and termination.present:
        notice_days = termination.values.get("notice_period_days")
        if notice_days is not None:
            result["notice_period_days"] = notice_days
            result["notice_period_label"] = termination.values.get("notice_period_label")
    if auto_renewal and auto_renewal.present:
        result["auto_renewal"] = True
        if auto_renewal.values.get("renewal_term_label"):
            result["renewal_term_days"] = auto_renewal.values.get("renewal_term_days")
            result["renewal_term_label"] = auto_renewal.values.get("renewal_term_label")
        renewal_notice = auto_renewal.values.get("renewal_notice_days")
        if renewal_notice is not None:
            # The renewal clause's own notice period wins: it is the one that
            # governs whether the contract rolls over.
            notice_days = renewal_notice
            result["renewal_notice_days"] = renewal_notice
            result["renewal_notice_label"] = auto_renewal.values.get("renewal_notice_label")
    else:
        result["auto_renewal"] = False

    if renewal:
        result["renewal_date"] = renewal.value
        result["renewal_date_excerpt"] = renewal.matched_text
        result["renewal_date_page"] = index.page_for(renewal.offset)
        result["renewal_date_basis"] = "stated"
    elif result.get("auto_renewal") and result.get("expiration_date"):
        # Automatic renewal starts the day after the current term ends.
        result["renewal_date"] = date_tools.add_days(result["expiration_date"], 1)
        result["renewal_date_basis"] = "derived_from_expiration"

    if result.get("auto_renewal") and result.get("expiration_date") and notice_days:
        deadline = date_tools.add_days(result["expiration_date"], -int(notice_days))
        result["notice_deadline"] = deadline
        result["notice_deadline_basis"] = "derived_from_expiration_and_notice"

    return result


def _clause_scope(
    index: DocumentIndex, clauses: dict[str, ClauseExtraction], clause_type: str
) -> tuple[int, int] | None:
    """The offsets of the section one clause was found in, when it has one."""
    extraction = clauses.get(clause_type)
    if extraction is None or not extraction.present:
        return None
    for reference in extraction.references:
        if reference.char_offset is None:
            continue
        section = index.section_for(reference.char_offset)
        if section is not None:
            return section.start, section.end
    return None


def _scoped_date(
    text: str,
    scope: tuple[int, int] | None,
    group: str,
    config: ContractAssistantConfig,
) -> date_tools.ParsedDate | None:
    """Look inside the scoped range first, then fall back to the whole document."""
    patterns = config.dates.patterns_for(group)
    if scope is not None:
        start, end = scope
        found = date_tools.find_first_by_patterns(text[start:end], patterns, config)
        if found is not None:
            return date_tools.ParsedDate(
                value=found.value,
                matched_text=found.matched_text,
                offset=found.offset + start,
                format_basis=found.format_basis,
            )
    return date_tools.find_first_by_patterns(text, patterns, config)


def _scoped_duration(
    text: str,
    scope: tuple[int, int] | None,
    group: str,
    config: ContractAssistantConfig,
) -> date_tools.ParsedDuration | None:
    """Look for a duration inside the scoped range only.

    Unlike a date, a duration found anywhere in the document is *not* a safe
    fallback: "a period of 5 years" belongs to whichever clause it sits in.
    """
    if scope is None:
        return None
    start, end = scope
    found = date_tools.find_duration(text[start:end], config.dates.patterns_for(group), config)
    if found is None:
        return None
    return date_tools.ParsedDuration(
        days=found.days,
        count=found.count,
        unit=found.unit,
        matched_text=found.matched_text,
        offset=found.offset + start,
    )


def _dates_to_dict(key_dates: dict[str, Any]) -> dict[str, Any]:
    return {
        key: (value.isoformat() if isinstance(value, date) else value)
        for key, value in key_dates.items()
    }


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def _run_rules(
    context: RiskContext, enabled_rules: list[str] | None
) -> tuple[list[ContractRiskFinding], list[dict[str, str]]]:
    """Run every enabled rule in isolation."""
    findings: list[ContractRiskFinding] = []
    errors: list[dict[str, str]] = []

    for rule_id in context.config.enabled_rule_ids(enabled_rules):
        if rule_id not in RULES:
            errors.append(
                {
                    "rule_id": rule_id,
                    "error": "not_implemented",
                    "message": "The rule is configured but no implementation is registered.",
                }
            )
            continue
        try:
            findings.extend(run_rule(rule_id, context))
        except Exception as exc:  # noqa: BLE001 - one bad rule never loses an analysis
            logger.warning("Contract rule %s failed: %s", rule_id, type(exc).__name__)
            errors.append(
                {
                    "rule_id": rule_id,
                    "error": type(exc).__name__,
                    "message": "The rule failed and was skipped. The other rules still ran.",
                }
            )
    return findings, errors


def _injection_markers(text: str) -> list[str]:
    """List the instruction-like sentences found in a document, for reporting.

    The document is data. Anything listed here is reported to the user and
    neutralised before any AI call - it is never acted on.
    """
    if not contains_injection_markers(text):
        return []
    markers: list[str] = []
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped and contains_injection_markers(stripped):
            markers.append(_WHITESPACE.sub(" ", stripped)[:200])
        if len(markers) >= 10:
            break
    return markers
