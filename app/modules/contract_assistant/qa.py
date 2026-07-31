"""Deterministic question answering over an analysed contract.

The Contract Assistant does not "chat about" a document. It scores the question
against the clause vocabulary it already used for extraction, then answers from
the clauses it actually extracted - quoting them, and citing the page and
heading each answer came from.

Three consequences follow, and all three are the point:

* the answer and the clause table can never disagree, because they are the same
  data;
* every sentence in an answer is traceable to a page;
* when the contract does not cover something, the assistant says so instead of
  producing a fluent, confident, wrong paragraph.

The question itself is untrusted input. It is matched against a fixed pattern
table and never used to select a code path beyond that table, never
interpolated into a shell or a query, and never allowed to change the system
prompt of the optional AI narrative.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.core.logging import get_logger
from app.modules.contract_assistant.clauses import ClauseExtraction, SourceReference
from app.modules.contract_assistant.thresholds import CLAUSE_TYPES, ContractAssistantConfig

logger = get_logger(__name__)

__all__ = [
    "QA_VERSION",
    "ContractAnswer",
    "answer_question",
    "score_intents",
]

QA_VERSION = "1.0.0"

#: Question shapes that are answered from computed facts rather than from one
#: clause: key dates, the risk list, the missing-clause list, the parties.
_META_INTENTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "key_dates",
        (
            r"\bkey dates?\b",
            r"when does .*(expire|end|start|begin|commence)",
            r"\b(expiry|expiration) date\b",
            r"\beffective date\b",
            r"\bimportant dates?\b",
            r"\bnotice deadline\b",
        ),
    ),
    (
        "parties",
        (r"\bwho (are|is) the part", r"\bparties\b", r"\bwho signed\b", r"\bcounterpart"),
    ),
    (
        "risks",
        (r"\brisks?\b", r"\bconcerns?\b", r"what should i (worry|watch)", r"\bred flags?\b"),
    ),
    (
        "missing",
        (r"\bmissing\b", r"what.*not (covered|included)", r"\bgaps?\b", r"\bomitted\b"),
    ),
    (
        "obligations",
        (r"\bobligations?\b", r"\bwhat must\b", r"\bwhat do (i|we) have to\b", r"\bduties\b"),
    ),
    (
        "summary",
        (r"\bsummar", r"\boverview\b", r"what is this (contract|agreement|document)"),
    ),
)


@dataclass
class ContractAnswer:
    """One answer, with everything needed to audit it."""

    question: str
    intent: str
    answer: str
    answered: bool = True
    clause_types: list[str] = field(default_factory=list)
    citations: list[SourceReference] = field(default_factory=list)
    unavailable_reason: str | None = None
    follow_up_suggestions: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "intent": self.intent,
            "answer": self.answer,
            "answered": self.answered,
            "clause_types": list(self.clause_types),
            "citations": [citation.to_dict() for citation in self.citations],
            "unavailable_reason": self.unavailable_reason,
            "follow_up_suggestions": list(self.follow_up_suggestions),
        }


def score_intents(question: str, config: ContractAssistantConfig) -> dict[str, float]:
    """Score a question against every clause type's vocabulary.

    A hit on a clause's ``question_patterns`` or heading vocabulary scores
    higher than a hit on its body vocabulary, because "what are the payment
    terms" should reach the payment clause and not every clause that happens to
    mention an invoice.
    """
    text = (question or "").strip().lower()
    scores: dict[str, float] = {}
    if not text:
        return scores

    settings = config.questions
    for clause_type in CLAUSE_TYPES:
        spec = config.clause(clause_type)
        score = 0.0
        for pattern in spec.questions:
            if pattern.search(text):
                score += settings.heading_match_score
        for pattern in spec.headings:
            if pattern.search(text):
                score += settings.keyword_match_score
        for pattern in spec.primary:
            if pattern.search(text):
                score += settings.keyword_match_score
        if score:
            scores[clause_type] = round(score, 3)
    return scores


def _meta_intent(question: str) -> str | None:
    """Return the non-clause intent a question matches, if any."""
    text = (question or "").strip().lower()
    if not text:
        return None
    for intent, patterns in _META_INTENTS:
        for pattern in patterns:
            if re.search(pattern, text):
                return intent
    return None


def answer_question(
    question: str,
    *,
    config: ContractAssistantConfig,
    clauses: dict[str, ClauseExtraction] | None,
    key_dates: dict[str, Any] | None = None,
    risks: list[dict[str, Any]] | None = None,
    obligations: list[dict[str, Any]] | None = None,
    missing_clauses: list[dict[str, Any]] | None = None,
    parties: list[dict[str, Any]] | None = None,
    contract_title: str | None = None,
    needs_ocr: bool = False,
) -> ContractAnswer:
    """Answer one question about an analysed contract.

    Every path either produces an answer backed by citations, or says plainly
    that the contract does not cover it.
    """
    settings = config.questions
    text = (question or "").strip()

    if not text:
        return ContractAnswer(
            question="",
            intent="unknown",
            answer="Please ask a question about this contract.",
            answered=False,
            unavailable_reason="empty_question",
            follow_up_suggestions=list(settings.suggested_questions[:4]),
        )

    if clauses is None:
        return ContractAnswer(
            question=text,
            intent="unknown",
            answer=settings.no_analysis_message,
            answered=False,
            unavailable_reason="not_analysed",
            follow_up_suggestions=list(settings.suggested_questions[:4]),
        )

    if needs_ocr:
        return ContractAnswer(
            question=text,
            intent="unknown",
            answer=settings.needs_ocr_message,
            answered=False,
            unavailable_reason="no_text_extracted",
        )

    meta = _meta_intent(text)
    scores = score_intents(text, config)
    best_clause_score = max(scores.values()) if scores else 0.0

    # A clause question that scores clearly is answered from the clause, even
    # when it also brushes a meta pattern ("when does the payment term start").
    if meta and best_clause_score < settings.heading_match_score:
        handler = {
            "key_dates": _answer_key_dates,
            "parties": _answer_parties,
            "risks": _answer_risks,
            "missing": _answer_missing,
            "obligations": _answer_obligations,
            "summary": _answer_summary,
        }[meta]
        return handler(
            text,
            config=config,
            clauses=clauses,
            key_dates=key_dates or {},
            risks=risks or [],
            obligations=obligations or [],
            missing_clauses=missing_clauses or [],
            parties=parties or [],
            contract_title=contract_title,
        )

    if best_clause_score < settings.min_intent_score:
        return _not_understood(text, config, clauses)

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    selected = [name for name, _ in ranked[: settings.max_answer_clauses]]
    present = [name for name in selected if clauses[name].present]

    if not present:
        # Only name the clause the question really asked about. A weaker match
        # picked up on one shared word ("cover") should not appear in the
        # answer as though the user had asked about it.
        best = ranked[0][1]
        return _clause_not_in_contract(
            text, [name for name, score in ranked if score == best], config, clauses
        )

    return _answer_from_clauses(text, present, config, clauses)


# ---------------------------------------------------------------------------
# Clause answers
# ---------------------------------------------------------------------------


def _answer_from_clauses(
    question: str,
    clause_types: list[str],
    config: ContractAssistantConfig,
    clauses: dict[str, ClauseExtraction],
) -> ContractAnswer:
    """Answer by quoting the extracted clauses, with their citations."""
    lines: list[str] = []
    citations: list[SourceReference] = []

    for clause_type in clause_types:
        extraction = clauses[clause_type]
        reference = extraction.primary_reference
        where = _where(reference)
        summary = _value_summary(extraction)
        lines.append(f"{extraction.label}{where}:")
        if summary:
            lines.append(f"  {summary}")
        lines.append(f'  "{extraction.excerpt}"')
        lines.append(
            f"  (extraction confidence {extraction.confidence:.2f}"
            + (", low - check the cited page" if extraction.needs_review else "")
            + ")"
        )
        citations.extend(extraction.references[: config.questions.max_citations])

    return ContractAnswer(
        question=question,
        intent=clause_types[0],
        answer="\n".join(lines),
        clause_types=clause_types,
        citations=citations[: config.questions.max_citations],
        follow_up_suggestions=_suggestions(config, exclude=clause_types),
    )


def _clause_not_in_contract(
    question: str,
    clause_types: list[str],
    config: ContractAssistantConfig,
    clauses: dict[str, ClauseExtraction],
) -> ContractAnswer:
    """Say plainly that the clause the question is about is not in the document."""
    labels = ", ".join(config.clause(name).label for name in clause_types)
    messages = [
        config.clause(name).missing_message
        for name in clause_types
        if config.clause(name).missing_message
    ]
    present = [clauses[name].label for name in CLAUSE_TYPES if clauses[name].present]

    answer = f"{config.questions.not_found_message}\n\nNo {labels} clause was extracted from this contract."
    if messages:
        answer += f" {messages[0]}"
    if present:
        answer += "\n\nClauses that were found: " + ", ".join(present) + "."

    return ContractAnswer(
        question=question,
        intent=clause_types[0],
        answer=answer,
        answered=False,
        clause_types=clause_types,
        unavailable_reason="clause_not_in_contract",
        follow_up_suggestions=_suggestions(config, exclude=clause_types),
    )


def _not_understood(
    question: str, config: ContractAssistantConfig, clauses: dict[str, ClauseExtraction]
) -> ContractAnswer:
    """The question does not match anything this assistant extracts."""
    present = [clauses[name].label for name in CLAUSE_TYPES if clauses[name].present]
    answer = (
        f"{config.questions.not_found_message}\n\nThis assistant answers from the clauses it "
        f"extracted from the uploaded document."
    )
    if present:
        answer += " Clauses found in this contract: " + ", ".join(present) + "."
    return ContractAnswer(
        question=question,
        intent="unknown",
        answer=answer,
        answered=False,
        unavailable_reason="unsupported_question",
        follow_up_suggestions=list(config.questions.suggested_questions[:4]),
    )


# ---------------------------------------------------------------------------
# Computed answers
# ---------------------------------------------------------------------------


def _answer_key_dates(
    question: str,
    *,
    config: ContractAssistantConfig,
    clauses: dict[str, ClauseExtraction],
    key_dates: dict[str, Any],
    **_ignored: Any,
) -> ContractAnswer:
    labels = (
        ("effective_date", "Effective date"),
        ("expiration_date", "Expiration date"),
        ("renewal_date", "Renewal date"),
        ("notice_deadline", "Notice deadline to prevent renewal"),
        ("signature_date", "Signature date"),
    )
    lines: list[str] = []
    for name, label in labels:
        value = key_dates.get(name)
        if isinstance(value, date):
            lines.append(f"  {label}: {value.isoformat()}")
        elif value:
            lines.append(f"  {label}: {value}")
        else:
            lines.append(f"  {label}: not stated in the document")

    for extra, label in (
        ("term_length_label", "Initial term"),
        ("notice_period_label", "Termination notice period"),
        ("renewal_term_label", "Renewal term"),
    ):
        if key_dates.get(extra):
            lines.append(f"  {label}: {key_dates[extra]}")

    citations = list(clauses["term"].references[:2]) if clauses["term"].present else []
    if clauses["auto_renewal"].present:
        citations.extend(clauses["auto_renewal"].references[:1])

    answered = any(isinstance(key_dates.get(name), date) for name, _ in labels)
    header = (
        "Key dates extracted from this contract:"
        if answered
        else "No key dates could be extracted from this contract:"
    )
    return ContractAnswer(
        question=question,
        intent="key_dates",
        answer=header + "\n" + "\n".join(lines),
        answered=answered,
        clause_types=["term"],
        citations=citations[: config.questions.max_citations],
        unavailable_reason=None if answered else "no_dates_extracted",
        follow_up_suggestions=_suggestions(config, exclude=["term"]),
    )


def _answer_parties(
    question: str,
    *,
    config: ContractAssistantConfig,
    parties: list[dict[str, Any]],
    contract_title: str | None = None,
    **_ignored: Any,
) -> ContractAnswer:
    if not parties:
        return ContractAnswer(
            question=question,
            intent="parties",
            answer=(
                f"{config.questions.not_found_message}\n\nNo party names could be extracted "
                f"from this document."
            ),
            answered=False,
            unavailable_reason="no_parties_extracted",
        )

    lines = [f"This contract ({contract_title or 'title not extracted'}) names:"]
    citations: list[SourceReference] = []
    for party in parties:
        role = party.get("role")
        role_text = f" - {role}" if role else ""
        lines.append(
            f"  {party.get('name')}{role_text} (page {party.get('page_number', '?')})"
        )
        if party.get("excerpt"):
            citations.append(
                SourceReference(
                    page_number=party.get("page_number"),
                    section_heading=party.get("section_heading"),
                    excerpt=party["excerpt"],
                    confidence=float(party.get("confidence", 0.0)),
                )
            )
    return ContractAnswer(
        question=question,
        intent="parties",
        answer="\n".join(lines),
        citations=citations[: config.questions.max_citations],
        follow_up_suggestions=_suggestions(config, exclude=[]),
    )


def _answer_risks(
    question: str,
    *,
    config: ContractAssistantConfig,
    risks: list[dict[str, Any]],
    **_ignored: Any,
) -> ContractAnswer:
    if not risks:
        return ContractAnswer(
            question=question,
            intent="risks",
            answer="No risk findings were raised by the contract rules for this document.",
        )

    lines = [f"{len(risks)} risk finding(s) were raised by the contract rules:"]
    citations: list[SourceReference] = []
    for risk in risks[: config.reporting.top_risks_default]:
        page = risk.get("page_number")
        where = f" (page {page})" if page else ""
        lines.append(f"  [{str(risk.get('severity', '')).upper()}] {risk.get('title')}{where}")
        lines.append(f"    {risk.get('explanation')}")
        if risk.get("excerpt"):
            citations.append(
                SourceReference(
                    page_number=page,
                    section_heading=risk.get("section_heading"),
                    excerpt=risk["excerpt"],
                    confidence=1.0,
                    clause_type=risk.get("clause_type"),
                )
            )
    lines.append(
        "These are rule-based findings from the uploaded document, not legal advice."
    )
    return ContractAnswer(
        question=question,
        intent="risks",
        answer="\n".join(lines),
        citations=citations[: config.questions.max_citations],
        follow_up_suggestions=_suggestions(config, exclude=[]),
    )


def _answer_missing(
    question: str,
    *,
    config: ContractAssistantConfig,
    missing_clauses: list[dict[str, Any]],
    clauses: dict[str, ClauseExtraction],
    **_ignored: Any,
) -> ContractAnswer:
    if not missing_clauses:
        return ContractAnswer(
            question=question,
            intent="missing",
            answer=(
                "Every clause type the configuration marks as required was found in this "
                "contract."
            ),
        )
    lines = [f"{len(missing_clauses)} expected clause(s) were not found in this contract:"]
    for item in missing_clauses:
        lines.append(f"  {item.get('label')} ({item.get('importance')} importance)")
        if item.get("message"):
            lines.append(f"    {item['message']}")
    present = [clauses[name].label for name in CLAUSE_TYPES if clauses[name].present]
    if present:
        lines.append("Clauses that were found: " + ", ".join(present) + ".")
    return ContractAnswer(
        question=question,
        intent="missing",
        answer="\n".join(lines),
        follow_up_suggestions=_suggestions(config, exclude=[]),
    )


def _answer_obligations(
    question: str,
    *,
    config: ContractAssistantConfig,
    obligations: list[dict[str, Any]],
    **_ignored: Any,
) -> ContractAnswer:
    if not obligations:
        return ContractAnswer(
            question=question,
            intent="obligations",
            answer="No obligation sentences were extracted from this contract.",
            answered=False,
            unavailable_reason="no_obligations_extracted",
        )

    lines = [f"{len(obligations)} obligation(s) were extracted. The first few:"]
    citations: list[SourceReference] = []
    for obligation in obligations[:8]:
        owner = obligation.get("party") or obligation.get("party_role") or "not attributed"
        page = obligation.get("page_number")
        lines.append(f"  [{owner}] {obligation.get('text')} (page {page})")
        citations.append(
            SourceReference(
                page_number=page,
                section_heading=obligation.get("section_heading"),
                excerpt=obligation.get("excerpt", ""),
                confidence=float(obligation.get("confidence", 0.0)),
            )
        )
    return ContractAnswer(
        question=question,
        intent="obligations",
        answer="\n".join(lines),
        citations=citations[: config.questions.max_citations],
        follow_up_suggestions=_suggestions(config, exclude=[]),
    )


def _answer_summary(
    question: str,
    *,
    config: ContractAssistantConfig,
    clauses: dict[str, ClauseExtraction],
    key_dates: dict[str, Any],
    parties: list[dict[str, Any]],
    risks: list[dict[str, Any]],
    contract_title: str | None = None,
    **_ignored: Any,
) -> ContractAnswer:
    found = [clauses[name] for name in CLAUSE_TYPES if clauses[name].present]
    lines = [f"{contract_title or 'This document'}:"]
    if parties:
        lines.append("  Parties: " + ", ".join(str(item.get("name")) for item in parties))
    effective = key_dates.get("effective_date")
    expiration = key_dates.get("expiration_date")
    lines.append(
        f"  Term: {effective.isoformat() if isinstance(effective, date) else 'start not stated'}"
        f" to {expiration.isoformat() if isinstance(expiration, date) else 'end not stated'}"
    )
    lines.append(f"  Clauses extracted: {len(found)} of {len(CLAUSE_TYPES)}")
    if found:
        lines.append("    " + ", ".join(item.label for item in found))
    lines.append(f"  Risk findings: {len(risks)}")
    lines.append(
        "  Every figure above was read from the uploaded document by deterministic pattern "
        "matching, with the page reference shown on each clause."
    )
    citations = [item.references[0] for item in found[:3] if item.references]
    return ContractAnswer(
        question=question,
        intent="summary",
        answer="\n".join(lines),
        citations=citations,
        follow_up_suggestions=_suggestions(config, exclude=[]),
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _where(reference: SourceReference | None) -> str:
    """Render the ' (page 4, "4.2 Termination")' part of an answer line."""
    if reference is None:
        return ""
    parts: list[str] = []
    if reference.page_number:
        parts.append(f"page {reference.page_number}")
    if reference.section_heading:
        parts.append(f'"{reference.section_heading}"')
    return f" ({', '.join(parts)})" if parts else ""


def _value_summary(extraction: ClauseExtraction) -> str:
    """Turn a clause's structured values into one readable sentence."""
    values = extraction.values
    bits: list[str] = []
    if "net_days" in values:
        bits.append(f"payment due net {values['net_days']} days")
    if "early_payment_discount_pct" in values:
        bits.append(
            f"{values['early_payment_discount_pct']:g}% discount if paid within "
            f"{values['early_payment_days']} days"
        )
    if "notice_period_label" in values:
        bits.append(f"notice period {values['notice_period_label']}")
    if "renewal_term_label" in values:
        bits.append(f"renews for {values['renewal_term_label']}")
    if "renewal_notice_label" in values:
        bits.append(f"renewal notice {values['renewal_notice_label']}")
    if "amount" in values:
        bits.append(f"amount {values['amount']:,.2f} {values.get('currency') or ''}".strip())
    if "percentage" in values:
        bits.append(f"{values['percentage']:g}%")
    if "availability_pct" in values:
        bits.append(f"availability {values['availability_pct']:g}%")
    if "jurisdiction" in values:
        bits.append(f"law of {values['jurisdiction']}")
    return "; ".join(bits)


def _suggestions(config: ContractAssistantConfig, exclude: list[str]) -> list[str]:
    """Offer follow-up questions that are not the one just answered."""
    excluded = {config.clause(name).label.lower() for name in exclude if name in config.clauses}
    return [
        question
        for question in config.questions.suggested_questions
        if not any(label.split()[0] in question.lower() for label in excluded)
    ][:4]
