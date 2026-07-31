"""The Supplier Risk Copilot's deterministic question answering.

The copilot is **not** a language model. It classifies a question against a
fixed set of intents, answers it from the computed risk assessment, and cites
the internal records it used. That matters for three reasons:

* the answer and the supplier page can never disagree - both read the same
  computed profile;
* every claim carries a citation pointing at the record it came from;
* when the answer is not in the loaded data the copilot says so, instead of
  producing a plausible sentence about a supplier nobody uploaded.

Uploaded questions are untrusted text. They are only ever matched against
patterns and supplier names here - never executed, and never used to select
code paths beyond this intent table.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import Enum
from typing import Any

from app.core.logging import get_logger
from app.modules.supplier_risk.engine import (
    RiskAssessmentResult,
    SupplierRiskProfile,
    find_alternatives,
)
from app.modules.supplier_risk.thresholds import SupplierRiskConfig

logger = get_logger(__name__)

__all__ = [
    "COPILOT_VERSION",
    "Citation",
    "CopilotAnswer",
    "CopilotIntent",
    "answer_question",
    "detect_intent",
    "resolve_supplier",
]

COPILOT_VERSION = "1.0.0"

#: Name of the uploaded dataset a citation points at.
PROFILE_SOURCE = "supplier_risk_profiles"
EVENT_SOURCE = "supplier_risk_events"


class CopilotIntent(str, Enum):
    """The questions the copilot knows how to answer."""

    SUPPLIER_RISK = "supplier_risk"
    WHY_RISK = "why_risk"
    DELIVERY_ISSUES = "delivery_issues"
    CONTRACTS_EXPIRING = "contracts_expiring"
    ALTERNATIVES = "alternatives"
    RECOMMENDED_ACTION = "recommended_action"
    HIGHEST_RISK = "highest_risk"
    UNKNOWN = "unknown"


@dataclass
class Citation:
    """A pointer to the internal record that backs part of an answer."""

    source: str
    record_type: str
    record_id: str
    field_name: str | None = None
    value: Any = None
    detail: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "record_type": self.record_type,
            "record_id": self.record_id,
            "field_name": self.field_name,
            "value": self.value,
            "detail": self.detail,
        }


@dataclass
class CopilotAnswer:
    """One answer, with everything needed to audit it."""

    question: str
    intent: CopilotIntent
    answer: str
    data_available: bool = True
    citations: list[Citation] = field(default_factory=list)
    suppliers_referenced: list[str] = field(default_factory=list)
    follow_up_suggestions: list[str] = field(default_factory=list)
    unavailable_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "question": self.question,
            "intent": self.intent.value,
            "answer": self.answer,
            "data_available": self.data_available,
            "citations": [citation.to_dict() for citation in self.citations],
            "suppliers_referenced": list(self.suppliers_referenced),
            "follow_up_suggestions": list(self.follow_up_suggestions),
            "unavailable_reason": self.unavailable_reason,
        }


#: Intent patterns, evaluated in order. The first match wins, so the more
#: specific questions are listed before the general ones.
_INTENT_PATTERNS: tuple[tuple[CopilotIntent, tuple[str, ...]], ...] = (
    (
        CopilotIntent.CONTRACTS_EXPIRING,
        (
            r"contract[s]?\s+(that\s+)?(are\s+)?expir",
            r"expiring\s+contract",
            r"contract[s]?\s+.*(renew|lapse|run\s+out|end)",
            r"which\s+.*contract",
        ),
    ),
    (
        CopilotIntent.DELIVERY_ISSUES,
        (
            r"delivery\s+(issue|problem|failure)",
            r"late\s+deliver",
            r"deliver[a-z]*\s+.*(worst|most|poor)",
            r"(most|worst)\s+.*deliver",
            r"on[-\s]?time\s+.*(worst|poor|problem)",
        ),
    ),
    (
        CopilotIntent.ALTERNATIVES,
        (
            r"alternativ",
            r"(other|different|another)\s+supplier",
            r"replace\s+(this\s+)?supplier",
            r"second\s+source",
            r"who\s+else\s+(can|could)\s+supply",
            r"lower[-\s]risk\s+supplier",
        ),
    ),
    (
        CopilotIntent.RECOMMENDED_ACTION,
        (
            r"what\s+(action|should)",
            r"recommend",
            r"what\s+.*procurement\s+.*(do|take)",
            r"next\s+step",
            r"mitigat",
        ),
    ),
    (
        CopilotIntent.WHY_RISK,
        (
            r"^\s*why\b",
            r"\bwhy\s+(is|are|does|did)\b",
            r"(reason|driver|cause)s?\s+for",
            r"what\s+(is\s+)?driv",
            r"explain\s+.*risk",
        ),
    ),
    (
        CopilotIntent.HIGHEST_RISK,
        (
            r"(highest|worst|top|riskiest|most)\s+risk",
            r"which\s+supplier[s]?\s+.*(risk|riskiest)",
            r"riskiest\s+supplier",
            r"high[-\s]risk\s+supplier",
        ),
    ),
    (
        CopilotIntent.SUPPLIER_RISK,
        (
            r"\brisk\b",
            r"\bprofile\b",
            r"\bscore\b",
            r"\bshow\b",
            r"how\s+risky",
        ),
    ),
)


def detect_intent(question: str) -> CopilotIntent:
    """Classify a question against the fixed intent table."""
    text = (question or "").strip().lower()
    if not text:
        return CopilotIntent.UNKNOWN
    for intent, patterns in _INTENT_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, text):
                return intent
    return CopilotIntent.UNKNOWN


def _normalise(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


#: Words that trail a supplier name in a question ("supplier ABC's risk score")
#: and must not become part of the name being matched.
_TRAILING_NOISE = {
    "risk", "risks", "risky", "profile", "profiles", "score", "scores", "rating",
    "detail", "details", "data", "record", "records", "status", "s", "is", "are",
    "have", "has", "and", "the", "a", "an", "of", "for",
}


def _clean_candidate(text: str) -> str:
    """Trim question words and punctuation from a captured supplier phrase."""
    cleaned = text.strip().strip("?.!,;:")
    cleaned = re.sub(r"['’]s\b", "", cleaned)
    tokens = [token for token in cleaned.split() if token]
    while tokens and tokens[-1].strip("?.!,;:'").lower() in _TRAILING_NOISE:
        tokens.pop()
    return " ".join(tokens).strip()


def resolve_supplier(
    question: str,
    assessment: RiskAssessmentResult,
    config: SupplierRiskConfig,
    supplier_id: str | None = None,
) -> tuple[SupplierRiskProfile | None, str | None]:
    """Work out which supplier a question is about.

    Returns ``(profile, mentioned_text)``. ``mentioned_text`` is what the user
    appeared to name when no supplier matched, so the answer can quote it back
    ("no supplier called 'Northwind' is in the loaded records").
    """
    if supplier_id:
        for profile in assessment.profiles:
            if profile.supplier_id == supplier_id:
                return profile, supplier_id

    text = question or ""
    lowered = text.lower()

    # 1. An exact supplier id anywhere in the question.
    for profile in assessment.profiles:
        if profile.supplier_id.lower() in lowered:
            return profile, profile.supplier_id

    # 2. A supplier name appearing verbatim in the question.
    best_named: tuple[int, SupplierRiskProfile] | None = None
    for profile in assessment.profiles:
        if not profile.supplier_name:
            continue
        name = profile.supplier_name.lower()
        if name in lowered and (best_named is None or len(name) > best_named[0]):
            best_named = (len(name), profile)
    if best_named:
        return best_named[1], best_named[1].supplier_name

    # 3. Fuzzy match against the significant words of the question.
    quoted = re.findall(r"['\"]([^'\"]{2,60})['\"]", text)
    candidates: list[str] = [_clean_candidate(item) for item in quoted]
    match = re.search(
        r"(?:supplier|vendor)\s+([A-Za-z0-9&.\-]+(?:\s+[A-Za-z0-9&.\-']+){0,3})",
        text,
        re.IGNORECASE,
    )
    if match:
        candidates.append(_clean_candidate(match.group(1)))
    candidates = [item for item in candidates if item]

    best_score = 0.0
    best_profile: SupplierRiskProfile | None = None
    mentioned: str | None = candidates[0] if candidates else None

    for candidate in candidates:
        normalised_candidate = _normalise(candidate)
        if not normalised_candidate:
            continue
        for profile in assessment.profiles:
            for target in (profile.supplier_name, profile.supplier_id):
                if not target:
                    continue
                normalised_target = _normalise(target)
                # A distinctive leading word ("Ravenna" for "Ravenna Frontier
                # Trading BV") is how people actually refer to a supplier, so
                # treat a contained name as a strong match rather than leaving
                # it to the ratio, which punishes the length difference.
                if len(normalised_candidate) >= 4 and normalised_candidate in normalised_target:
                    score = 0.95
                else:
                    score = SequenceMatcher(None, normalised_candidate, normalised_target).ratio()
                if score > best_score:
                    best_score = score
                    best_profile = profile
                    mentioned = candidate

    if best_profile is not None and best_score >= config.copilot.minimum_name_match_score:
        return best_profile, mentioned
    return None, mentioned


def _profile_citation(
    profile: SupplierRiskProfile,
    field_name: str,
    value: Any,
    detail: str | None = None,
) -> Citation:
    return Citation(
        source=PROFILE_SOURCE,
        record_type="supplier_risk_profile",
        record_id=profile.supplier_id,
        field_name=field_name,
        value=value,
        detail=detail,
    )


def _event_citation(profile: SupplierRiskProfile, event: dict[str, Any]) -> Citation:
    parts = [part for part in (event.get("event_date"), event.get("reference")) if part]
    detail = event.get("description") or event.get("event_type")
    if parts:
        detail = f"{detail} ({', '.join(str(part) for part in parts)})"
    return Citation(
        source=EVENT_SOURCE,
        record_type=str(event.get("event_type") or "risk_event"),
        record_id=str(event.get("event_id")),
        field_name="supplier_id",
        value=profile.supplier_id,
        detail=detail,
    )


def _score_phrase(profile: SupplierRiskProfile) -> str:
    if profile.overall_score is None:
        return (
            f"{profile.supplier_name or profile.supplier_id} has too little data for an overall "
            f"risk score (only {profile.score.data_completeness_pct:g}% of the risk model could "
            f"be evaluated)"
        )
    return (
        f"{profile.supplier_name or profile.supplier_id} ({profile.supplier_id}) has an overall "
        f"risk score of {profile.overall_score:g}/100, which is the '{profile.overall_band}' band"
    )


def _no_data_answer(question: str, config: SupplierRiskConfig) -> CopilotAnswer:
    return CopilotAnswer(
        question=question,
        intent=detect_intent(question),
        answer=config.copilot.no_data_message,
        data_available=False,
        unavailable_reason="no_assessment_loaded",
        follow_up_suggestions=[
            "Upload a supplier risk profile file, then run a risk calculation.",
        ],
    )


def _supplier_not_found(
    question: str,
    intent: CopilotIntent,
    mentioned: str | None,
    assessment: RiskAssessmentResult,
    config: SupplierRiskConfig,
) -> CopilotAnswer:
    known = ", ".join(
        f"{item.supplier_name or item.supplier_id} ({item.supplier_id})"
        for item in assessment.profiles[: config.copilot.max_suppliers_listed]
    )
    if mentioned:
        answer = (
            f"{config.copilot.unavailable_message} No supplier matching '{mentioned}' is in the "
            f"{assessment.supplier_count} loaded supplier record(s)."
        )
    else:
        answer = (
            f"{config.copilot.unavailable_message} The question does not name a supplier that is "
            f"in the loaded records."
        )
    if known:
        answer += f" Loaded suppliers include: {known}."
    return CopilotAnswer(
        question=question,
        intent=intent,
        answer=answer,
        data_available=False,
        unavailable_reason="supplier_not_found",
        follow_up_suggestions=["Which suppliers are the highest risk?"],
    )


def _answer_supplier_risk(
    question: str,
    profile: SupplierRiskProfile,
    config: SupplierRiskConfig,
) -> CopilotAnswer:
    citations = [
        _profile_citation(
            profile,
            "overall_score",
            profile.overall_score,
            f"Overall risk computed from {len(profile.score.scored_categories)} risk categories.",
        )
    ]
    lines = [_score_phrase(profile) + "."]

    drivers = profile.score.top_drivers(config.copilot.top_drivers_in_answer)
    if drivers:
        driver_text = "; ".join(
            f"{item.label} {item.score:g} ('{item.band}', contributing "
            f"{item.contribution:.2f} points)"
            for item in drivers
        )
        lines.append(f"The largest contributors are: {driver_text}.")
        for item in drivers:
            citations.append(
                _profile_citation(profile, f"category.{item.category}", item.score, item.description)
            )

    facts: list[str] = []
    if profile.total_spend is not None:
        facts.append(f"total spend {profile.total_spend:,.0f} {profile.currency or ''}".strip())
        citations.append(_profile_citation(profile, "historical_spend", profile.total_spend))
    if profile.purchase_order_count is not None:
        facts.append(f"{profile.purchase_order_count} purchase orders")
        citations.append(
            _profile_citation(profile, "historical_order_count", profile.purchase_order_count)
        )
    if profile.on_time_delivery_rate is not None:
        facts.append(f"on-time delivery {profile.on_time_delivery_rate:g}%")
        citations.append(
            _profile_citation(profile, "on_time_delivery_rate", profile.on_time_delivery_rate)
        )
    if profile.contract_status:
        contract_fact = f"contract status '{profile.contract_status}'"
        if profile.contract_expiration:
            contract_fact += f" expiring {profile.contract_expiration.isoformat()}"
        facts.append(contract_fact)
        citations.append(_profile_citation(profile, "contract_status", profile.contract_status))
    if facts:
        lines.append("Supporting records: " + ", ".join(facts) + ".")

    if profile.trend.data_available:
        lines.append(f"Risk trend is {profile.trend.direction}. {profile.trend.basis}")
    else:
        lines.append(f"Risk trend is unknown. {profile.trend.basis}")

    if profile.score.limited_data:
        lines.append(
            f"Note: only {profile.score.data_completeness_pct:g}% of the risk model could be "
            f"evaluated for this supplier, so the score rests on partial data."
        )

    return CopilotAnswer(
        question=question,
        intent=CopilotIntent.SUPPLIER_RISK,
        answer=" ".join(lines),
        citations=citations,
        suppliers_referenced=[profile.supplier_id],
        follow_up_suggestions=[
            f"Why is {profile.supplier_name or profile.supplier_id} high risk?",
            f"What action should procurement take for {profile.supplier_id}?",
            f"Which alternative supplier to {profile.supplier_id} has lower risk?",
        ],
    )


def _answer_why_risk(
    question: str,
    profile: SupplierRiskProfile,
    config: SupplierRiskConfig,
) -> CopilotAnswer:
    if profile.overall_score is None:
        return CopilotAnswer(
            question=question,
            intent=CopilotIntent.WHY_RISK,
            answer=(
                f"{profile.supplier_name or profile.supplier_id} ({profile.supplier_id}) does not "
                f"have an overall risk score: only "
                f"{profile.score.data_completeness_pct:g}% of the risk model could be evaluated "
                f"from the loaded records, below the minimum needed to state one."
            ),
            data_available=False,
            unavailable_reason="insufficient_data_for_score",
            citations=[
                _profile_citation(
                    profile, "data_completeness_pct", profile.score.data_completeness_pct
                )
            ],
            suppliers_referenced=[profile.supplier_id],
        )

    drivers = profile.score.top_drivers(config.copilot.top_drivers_in_answer)
    lines = [
        f"{profile.supplier_name or profile.supplier_id} ({profile.supplier_id}) scores "
        f"{profile.overall_score:g}/100 ('{profile.overall_band}'). "
        f"That score is driven by:"
    ]
    citations: list[Citation] = []

    for item in drivers:
        metric_bits = []
        for metric in item.metrics:
            if not metric.available:
                continue
            metric_bits.append(
                f"{metric.label} {metric.raw_value}{' ' + metric.unit if metric.unit else ''} "
                f"(normalised {metric.normalized_score:g}, weight "
                f"{metric.normalized_weight * 100:.0f}% of the category)"
            )
        detail = "; ".join(metric_bits) if metric_bits else "no metric detail recorded"
        lines.append(
            f" {item.label}: {item.score:g}/100 ('{item.band}') contributing "
            f"{item.contribution:.2f} points to the overall score - {detail}."
        )
        citations.append(
            _profile_citation(profile, f"category.{item.category}", item.score, item.description)
        )

    # Point at the individual internal records behind the worst category.
    issue_sets = (
        (profile.delivery_issues, "delivery"),
        (profile.quality_issues, "quality"),
        (profile.invoice_issues, "invoice"),
        (profile.compliance_issues, "compliance"),
    )
    driver_names = {item.category for item in drivers}
    for issues, name in issue_sets:
        if name in driver_names and issues:
            for event in issues[:3]:
                citations.append(_event_citation(profile, event))

    if profile.trend.data_available:
        lines.append(f"Trend: {profile.trend.direction}. {profile.trend.basis}")

    return CopilotAnswer(
        question=question,
        intent=CopilotIntent.WHY_RISK,
        answer="\n".join(lines),
        citations=citations,
        suppliers_referenced=[profile.supplier_id],
        follow_up_suggestions=[
            f"What action should procurement take for {profile.supplier_id}?",
            f"Which alternative supplier to {profile.supplier_id} has lower risk?",
        ],
    )


def _answer_delivery_issues(
    question: str,
    assessment: RiskAssessmentResult,
    config: SupplierRiskConfig,
) -> CopilotAnswer:
    ranked = [
        item
        for item in assessment.profiles
        if item.category_score("delivery") is not None
        or (item.late_delivery_count or 0) > 0
    ]
    if not ranked:
        return CopilotAnswer(
            question=question,
            intent=CopilotIntent.DELIVERY_ISSUES,
            answer=(
                f"{config.copilot.unavailable_message} No delivery performance data was found in "
                f"the loaded supplier records."
            ),
            data_available=False,
            unavailable_reason="no_delivery_data",
        )

    ranked.sort(
        key=lambda item: (
            -(item.category_score("delivery") or 0.0),
            -(item.late_delivery_count or 0),
            item.supplier_id,
        )
    )
    top = ranked[: config.copilot.max_suppliers_listed]

    lines = [f"Suppliers with the highest delivery risk in the loaded records ({len(ranked)} assessed):"]
    citations: list[Citation] = []
    for index, item in enumerate(top, start=1):
        bits = [f"delivery risk {item.category_score('delivery'):g}/100"]
        if item.late_delivery_count is not None and item.delivery_count:
            bits.append(f"{item.late_delivery_count} late of {item.delivery_count} deliveries")
        if item.on_time_delivery_rate is not None:
            bits.append(f"on-time rate {item.on_time_delivery_rate:g}%")
        lines.append(
            f" {index}. {item.supplier_name or item.supplier_id} ({item.supplier_id}): "
            + ", ".join(bits)
            + "."
        )
        citations.append(
            _profile_citation(item, "category.delivery", item.category_score("delivery"))
        )
        if item.late_delivery_count is not None:
            citations.append(
                _profile_citation(item, "late_delivery_count", item.late_delivery_count)
            )
        for event in item.delivery_issues[:2]:
            citations.append(_event_citation(item, event))

    return CopilotAnswer(
        question=question,
        intent=CopilotIntent.DELIVERY_ISSUES,
        answer="\n".join(lines),
        citations=citations,
        suppliers_referenced=[item.supplier_id for item in top],
        follow_up_suggestions=[
            f"Why is {top[0].supplier_name or top[0].supplier_id} high risk?",
        ],
    )


def _answer_contracts_expiring(
    question: str,
    assessment: RiskAssessmentResult,
    config: SupplierRiskConfig,
) -> CopilotAnswer:
    window = config.contract_expiry.expiring_within_days
    expiring = [
        item
        for item in assessment.profiles
        if item.days_to_contract_expiry is not None and item.days_to_contract_expiry <= window
    ]
    if not expiring:
        with_dates = [
            item for item in assessment.profiles if item.contract_expiration is not None
        ]
        if not with_dates:
            return CopilotAnswer(
                question=question,
                intent=CopilotIntent.CONTRACTS_EXPIRING,
                answer=(
                    f"{config.copilot.unavailable_message} No contract expiration dates were "
                    f"found in the loaded supplier records."
                ),
                data_available=False,
                unavailable_reason="no_contract_dates",
            )
        return CopilotAnswer(
            question=question,
            intent=CopilotIntent.CONTRACTS_EXPIRING,
            answer=(
                f"No contracts expire within the next {window} days. "
                f"{len(with_dates)} supplier record(s) carry a contract expiration date."
            ),
            citations=[
                _profile_citation(item, "contract_expiration", item.contract_expiration.isoformat())
                for item in with_dates[: config.copilot.max_suppliers_listed]
            ],
        )

    expiring.sort(key=lambda item: (item.days_to_contract_expiry or 0, item.supplier_id))
    top = expiring[: config.copilot.max_suppliers_listed]

    lines = [
        f"{len(expiring)} supplier contract(s) expire within {window} days "
        f"(as of {assessment.as_of_date.isoformat() if assessment.as_of_date else 'the assessment date'}):"
    ]
    citations: list[Citation] = []
    for item in top:
        days = item.days_to_contract_expiry or 0
        state = "has already lapsed" if days < 0 else f"expires in {days} day(s)"
        reference = f" (contract {item.contract_number})" if item.contract_number else ""
        lines.append(
            f" {item.supplier_name or item.supplier_id} ({item.supplier_id}){reference}: "
            f"{item.contract_expiration.isoformat() if item.contract_expiration else 'unknown'} "
            f"- {state}, status '{item.contract_status or 'unknown'}'."
        )
        citations.append(
            _profile_citation(
                item,
                "contract_expiration",
                item.contract_expiration.isoformat() if item.contract_expiration else None,
                f"Contract risk {item.category_score('contract')}",
            )
        )

    return CopilotAnswer(
        question=question,
        intent=CopilotIntent.CONTRACTS_EXPIRING,
        answer="\n".join(lines),
        citations=citations,
        suppliers_referenced=[item.supplier_id for item in top],
        follow_up_suggestions=["What action should procurement take?"],
    )


def _answer_alternatives(
    question: str,
    profile: SupplierRiskProfile,
    assessment: RiskAssessmentResult,
    config: SupplierRiskConfig,
) -> CopilotAnswer:
    alternatives = find_alternatives(profile, assessment.profiles, config)
    base = f"{profile.supplier_name or profile.supplier_id} ({profile.supplier_id})"

    if profile.overall_score is None:
        return CopilotAnswer(
            question=question,
            intent=CopilotIntent.ALTERNATIVES,
            answer=(
                f"{base} has no overall risk score, so no lower-risk comparison can be made. "
                f"Only {profile.score.data_completeness_pct:g}% of the risk model could be "
                f"evaluated from the loaded records."
            ),
            data_available=False,
            unavailable_reason="insufficient_data_for_score",
            suppliers_referenced=[profile.supplier_id],
        )

    if not alternatives:
        return CopilotAnswer(
            question=question,
            intent=CopilotIntent.ALTERNATIVES,
            answer=(
                f"No lower-risk alternative to {base} was found in the loaded records. A "
                f"candidate must share its spend category "
                f"('{profile.spend_category or 'not recorded'}') or one of its materials, and "
                f"score at least {config.alternatives.minimum_improvement:g} points lower than "
                f"{profile.overall_score:g}."
            ),
            data_available=False,
            unavailable_reason="no_alternative_found",
            citations=[_profile_citation(profile, "overall_score", profile.overall_score)],
            suppliers_referenced=[profile.supplier_id],
        )

    lines = [
        f"{len(alternatives)} lower-risk alternative(s) to {base} "
        f"(risk {profile.overall_score:g}) in the loaded records:"
    ]
    citations = [_profile_citation(profile, "overall_score", profile.overall_score)]
    for item in alternatives:
        improvement = profile.overall_score - (item.overall_score or 0.0)
        shared = sorted(
            {m.lower() for m in profile.materials_supplied}
            & {m.lower() for m in item.materials_supplied}
        )
        basis = (
            f"same spend category '{item.spend_category}'"
            if item.spend_category
            and profile.spend_category
            and item.spend_category.lower() == profile.spend_category.lower()
            else f"shares material(s) {', '.join(shared)}"
            if shared
            else "comparable supply"
        )
        lines.append(
            f" {item.supplier_name or item.supplier_id} ({item.supplier_id}): risk "
            f"{item.overall_score:g}/100 ('{item.overall_band}'), "
            f"{improvement:.1f} points lower - {basis}."
        )
        citations.append(_profile_citation(item, "overall_score", item.overall_score, basis))

    lines.append(
        "These are ranked from the loaded internal records only; they are not a "
        "sourcing decision and have not been validated in a live SAP environment."
    )

    return CopilotAnswer(
        question=question,
        intent=CopilotIntent.ALTERNATIVES,
        answer="\n".join(lines),
        citations=citations,
        suppliers_referenced=[profile.supplier_id] + [item.supplier_id for item in alternatives],
        follow_up_suggestions=[
            f"Show {alternatives[0].supplier_name or alternatives[0].supplier_id}'s risk."
        ],
    )


def _answer_recommended_action(
    question: str,
    profile: SupplierRiskProfile | None,
    assessment: RiskAssessmentResult,
    config: SupplierRiskConfig,
) -> CopilotAnswer:
    if profile is not None:
        base = f"{profile.supplier_name or profile.supplier_id} ({profile.supplier_id})"
        if not profile.actions:
            return CopilotAnswer(
                question=question,
                intent=CopilotIntent.RECOMMENDED_ACTION,
                answer=(
                    f"No escalation is triggered for {base}. "
                    f"{config.actions.no_action_message} "
                    + (
                        f"Its overall risk is {profile.overall_score:g}/100 "
                        f"('{profile.overall_band}')."
                        if profile.overall_score is not None
                        else "It has too little data for an overall risk score."
                    )
                ),
                citations=[_profile_citation(profile, "overall_score", profile.overall_score)],
                suppliers_referenced=[profile.supplier_id],
            )

        lines = [f"Recommended actions for {base}, from the risk rules that fired:"]
        citations: list[Citation] = []
        for action in profile.actions:
            lines.append(f" [{action.priority}] {action.action} Trigger: {action.trigger}")
            if action.category != "overall":
                citations.append(
                    _profile_citation(
                        profile,
                        f"category.{action.category}",
                        profile.category_score(action.category),
                        action.trigger,
                    )
                )
        lines.append(
            "These are rule-based suggestions from the loaded records, not validated SAP "
            "recommendations."
        )
        return CopilotAnswer(
            question=question,
            intent=CopilotIntent.RECOMMENDED_ACTION,
            answer="\n".join(lines),
            citations=citations,
            suppliers_referenced=[profile.supplier_id],
        )

    # No supplier named: report the portfolio's most urgent actions.
    with_actions = [item for item in assessment.profiles if item.actions]
    if not with_actions:
        return CopilotAnswer(
            question=question,
            intent=CopilotIntent.RECOMMENDED_ACTION,
            answer=(
                f"No supplier in the loaded records triggers an escalation. "
                f"{config.actions.no_action_message}"
            ),
        )
    with_actions.sort(key=lambda item: (-(item.overall_score or 0.0), item.supplier_id))
    top = with_actions[: config.copilot.max_suppliers_listed]

    lines = ["The most urgent actions across the loaded suppliers:"]
    citations: list[Citation] = []
    for item in top:
        action = item.actions[0]
        lines.append(
            f" {item.supplier_name or item.supplier_id} ({item.supplier_id}, risk "
            f"{item.overall_score:g}): [{action.priority}] {action.action}"
        )
        citations.append(_profile_citation(item, "overall_score", item.overall_score, action.trigger))

    return CopilotAnswer(
        question=question,
        intent=CopilotIntent.RECOMMENDED_ACTION,
        answer="\n".join(lines),
        citations=citations,
        suppliers_referenced=[item.supplier_id for item in top],
    )


def _answer_highest_risk(
    question: str,
    assessment: RiskAssessmentResult,
    config: SupplierRiskConfig,
) -> CopilotAnswer:
    scored = [item for item in assessment.profiles if item.overall_score is not None]
    if not scored:
        return CopilotAnswer(
            question=question,
            intent=CopilotIntent.HIGHEST_RISK,
            answer=(
                f"{config.copilot.unavailable_message} None of the "
                f"{assessment.supplier_count} loaded supplier record(s) has enough data for an "
                f"overall risk score."
            ),
            data_available=False,
            unavailable_reason="no_scored_suppliers",
        )

    scored.sort(key=lambda item: (-(item.overall_score or 0.0), item.supplier_id))
    top = scored[: config.copilot.max_suppliers_listed]

    lines = [f"Highest-risk suppliers in the loaded records ({len(scored)} scored):"]
    citations: list[Citation] = []
    for index, item in enumerate(top, start=1):
        drivers = item.score.top_drivers(2)
        driver_text = ", ".join(f"{d.label} {d.score:g}" for d in drivers)
        lines.append(
            f" {index}. {item.supplier_name or item.supplier_id} ({item.supplier_id}): "
            f"{item.overall_score:g}/100 ('{item.overall_band}') - led by {driver_text}."
        )
        citations.append(_profile_citation(item, "overall_score", item.overall_score))

    return CopilotAnswer(
        question=question,
        intent=CopilotIntent.HIGHEST_RISK,
        answer="\n".join(lines),
        citations=citations,
        suppliers_referenced=[item.supplier_id for item in top],
        follow_up_suggestions=[
            f"Why is {top[0].supplier_name or top[0].supplier_id} high risk?",
        ],
    )


def answer_question(
    question: str,
    assessment: RiskAssessmentResult | None,
    config: SupplierRiskConfig,
    supplier_id: str | None = None,
) -> CopilotAnswer:
    """Answer one question from a computed risk assessment.

    Every path either produces an answer backed by citations, or says plainly
    that the information is not in the loaded records.
    """
    text = (question or "").strip()
    if not text:
        return CopilotAnswer(
            question=question or "",
            intent=CopilotIntent.UNKNOWN,
            answer="Please ask a question about the loaded supplier risk data.",
            data_available=False,
            unavailable_reason="empty_question",
            follow_up_suggestions=[
                "Which suppliers are the highest risk?",
                "Which suppliers have contracts expiring soon?",
            ],
        )

    if assessment is None or not assessment.profiles:
        return _no_data_answer(text, config)

    intent = detect_intent(text)
    profile, mentioned = resolve_supplier(text, assessment, config, supplier_id)

    if intent in {CopilotIntent.SUPPLIER_RISK, CopilotIntent.WHY_RISK, CopilotIntent.ALTERNATIVES}:
        if profile is None:
            # A named-but-unknown supplier is the important case: say so rather
            # than silently answering about the portfolio.
            if mentioned or intent is not CopilotIntent.SUPPLIER_RISK:
                return _supplier_not_found(text, intent, mentioned, assessment, config)
            return _answer_highest_risk(text, assessment, config)

    if intent is CopilotIntent.SUPPLIER_RISK and profile is not None:
        return _answer_supplier_risk(text, profile, config)
    if intent is CopilotIntent.WHY_RISK and profile is not None:
        return _answer_why_risk(text, profile, config)
    if intent is CopilotIntent.ALTERNATIVES and profile is not None:
        return _answer_alternatives(text, profile, assessment, config)
    if intent is CopilotIntent.DELIVERY_ISSUES:
        return _answer_delivery_issues(text, assessment, config)
    if intent is CopilotIntent.CONTRACTS_EXPIRING:
        return _answer_contracts_expiring(text, assessment, config)
    if intent is CopilotIntent.RECOMMENDED_ACTION:
        return _answer_recommended_action(text, profile, assessment, config)
    if intent is CopilotIntent.HIGHEST_RISK:
        return _answer_highest_risk(text, assessment, config)

    return CopilotAnswer(
        question=text,
        intent=CopilotIntent.UNKNOWN,
        answer=(
            f"{config.copilot.unavailable_message} This copilot answers questions about supplier "
            f"risk scores, risk drivers, delivery issues, contract expiry, lower-risk "
            f"alternatives and recommended actions, using only the loaded internal records."
        ),
        data_available=False,
        unavailable_reason="unsupported_question",
        follow_up_suggestions=[
            "Which suppliers are the highest risk?",
            "Which suppliers have the most delivery issues?",
            "Which suppliers have contracts expiring soon?",
            "What action should procurement take?",
        ],
    )
