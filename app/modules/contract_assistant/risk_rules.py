"""Deterministic contract risk rules.

Each rule is one small function that looks at the already-extracted clauses,
key dates and document facts and returns findings. Rules never call an AI
model, never touch the database and never re-read the file, which is what makes
them cheap to unit test and completely reproducible.

Every rule is wrapped in ``try/except`` by the engine: one broken rule lands in
``rule_errors`` on the response and the other nineteen still produce findings.

Thresholds - notice periods, payment policy, expiry windows, the approved
jurisdiction list - are read from the configuration through ``spec.param(...)``.
No rule may hardcode a limit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable

from app.core.logging import get_logger
from app.core.security import contains_injection_markers
from app.modules.contract_assistant.clauses import ClauseExtraction, SourceReference
from app.modules.contract_assistant.thresholds import (
    ContractAssistantConfig,
    RuleSpec,
)
from app.schemas.common import OutputOrigin, Severity

logger = get_logger(__name__)

__all__ = ["ContractRiskFinding", "RiskContext", "RULES", "run_rule"]


@dataclass
class ContractRiskFinding:
    """One deterministic risk finding about a contract."""

    rule_id: str
    rule_name: str
    category: str
    severity: Severity
    title: str
    explanation: str
    recommended_action: str
    clause_type: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    references: list[SourceReference] = field(default_factory=list)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED

    def to_dict(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "category": self.category,
            "severity": self.severity.value,
            "title": self.title,
            "explanation": self.explanation,
            "recommended_action": self.recommended_action,
            "clause_type": self.clause_type,
            "evidence": _json_safe(self.evidence),
            "page_number": self.references[0].page_number if self.references else None,
            "section_heading": self.references[0].section_heading if self.references else None,
            "excerpt": self.references[0].excerpt if self.references else "",
            "references": [reference.to_dict() for reference in self.references],
            "output_origin": self.output_origin.value,
        }


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, date):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


@dataclass
class RiskContext:
    """Everything a rule may look at, computed once per analysis."""

    clauses: dict[str, ClauseExtraction]
    key_dates: dict[str, Any]
    config: ContractAssistantConfig
    as_of_date: date
    full_text: str = ""
    char_count: int = 0
    needs_ocr: bool = False
    injection_markers: list[str] = field(default_factory=list)

    def clause(self, clause_type: str) -> ClauseExtraction | None:
        """Return an extracted clause only when it was actually found."""
        extraction = self.clauses.get(clause_type)
        return extraction if extraction and extraction.present else None

    def references_for(self, clause_type: str) -> list[SourceReference]:
        extraction = self.clause(clause_type)
        return list(extraction.references[:2]) if extraction else []

    def date_value(self, name: str) -> date | None:
        value = self.key_dates.get(name)
        return value if isinstance(value, date) else None


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------


def rule_auto_renewal_present(
    spec: RuleSpec, context: RiskContext
) -> list[ContractRiskFinding]:
    """CA-R001: the contract renews itself unless someone acts."""
    clause = context.clause("auto_renewal")
    if clause is None:
        return []

    term = clause.values.get("renewal_term_label")
    notice = clause.values.get("renewal_notice_label")
    detail = f" for a further {term}" if term else ""
    notice_text = (
        f" unless {notice} notice is given" if notice else " unless notice is given in time"
    )
    return [
        _finding(
            spec,
            context,
            title="Contract renews automatically",
            explanation=(
                f"The agreement renews automatically{detail}{notice_text}. Missing the notice "
                f"deadline commits the company to another full term."
            ),
            clause_type="auto_renewal",
            evidence={
                "renewal_term_days": clause.values.get("renewal_term_days"),
                "renewal_notice_days": clause.values.get("renewal_notice_days"),
                "confidence": clause.confidence,
            },
        )
    ]


def rule_short_notice_period(spec: RuleSpec, context: RiskContext) -> list[ContractRiskFinding]:
    """CA-R002: the termination notice window is shorter than policy allows."""
    clause = context.clause("termination")
    if clause is None:
        return []
    days = clause.values.get("notice_period_days")
    if days is None:
        return []

    minimum = int(spec.param("minimum_notice_days", 30))
    critical = int(spec.param("critical_notice_days", 14))
    if days >= minimum:
        return []

    severity = Severity.CRITICAL if days <= critical else spec.base_severity
    return [
        _finding(
            spec,
            context,
            title=f"Termination notice period is only {clause.values.get('notice_period_label', f'{days} days')}",
            explanation=(
                f"The shortest notice period found in the termination clause is {days} day(s), "
                f"below the {minimum}-day minimum in the configuration. A window this short "
                f"leaves little time to arrange a replacement supply."
            ),
            severity=severity,
            clause_type="termination",
            evidence={
                "notice_period_days": days,
                "minimum_notice_days": minimum,
                "all_notice_periods": clause.values.get("notice_periods_found"),
            },
        )
    ]


def rule_no_termination_clause(
    spec: RuleSpec, context: RiskContext
) -> list[ContractRiskFinding]:
    """CA-R003: the document never says how to get out."""
    if context.clause("termination") is not None:
        return []
    return [
        _finding(
            spec,
            context,
            title="No termination clause found",
            explanation=(
                "No termination clause was extracted, so the document does not state how "
                "either party can end the agreement or how much notice is required."
            ),
            clause_type="termination",
            evidence={"clause_present": False},
        )
    ]


def rule_missing_required_clause(
    spec: RuleSpec, context: RiskContext
) -> list[ContractRiskFinding]:
    """CA-R004: a clause the configuration marks as required is absent."""
    findings: list[ContractRiskFinding] = []
    for clause_type in context.config.required_clauses:
        # Termination has its own, more specific rule; reporting both would
        # double-count the same gap in the risk score.
        if clause_type == "termination":
            continue
        extraction = context.clauses.get(clause_type)
        if extraction is not None and extraction.present:
            continue
        clause_spec = context.config.clause(clause_type)
        severity = context.config.risk.severity_for_importance(clause_spec.importance)
        findings.append(
            _finding(
                spec,
                context,
                title=f"Required clause missing: {clause_spec.label}",
                explanation=clause_spec.missing_message
                or f"No {clause_spec.label.lower()} clause was found in the document.",
                severity=severity,
                clause_type=clause_type,
                evidence={"clause_present": False, "importance": clause_spec.importance},
                references=[],
            )
        )
    return findings


def rule_unlimited_liability(spec: RuleSpec, context: RiskContext) -> list[ContractRiskFinding]:
    """CA-R005: the liability clause explicitly removes the cap."""
    clause = context.clause("liability")
    if clause is None:
        return []
    patterns = spec.patterns("unlimited_patterns")
    text = " ".join(reference.excerpt for reference in clause.references)
    matched = [pattern.pattern for pattern in patterns if pattern.search(text)]
    if not matched:
        return []
    return [
        _finding(
            spec,
            context,
            title="Liability is stated as unlimited",
            explanation=(
                "The limitation of liability clause states that liability is unlimited or "
                "not subject to a cap. The company's maximum exposure under this agreement is "
                "therefore not bounded by the contract."
            ),
            clause_type="liability",
            evidence={"matched_phrases": matched},
        )
    ]


def rule_no_liability_cap(spec: RuleSpec, context: RiskContext) -> list[ContractRiskFinding]:
    """CA-R006: a liability clause exists but never limits anything."""
    clause = context.clause("liability")
    if clause is None:
        return []
    text = " ".join(reference.excerpt for reference in clause.references)
    if any(pattern.search(text) for pattern in spec.patterns("cap_patterns")):
        return []
    # An explicitly unlimited clause is CA-R005's finding, not this one.
    unlimited = context.config.rule("CA-R005").patterns("unlimited_patterns")
    if any(pattern.search(text) for pattern in unlimited):
        return []
    return [
        _finding(
            spec,
            context,
            title="Liability clause states no cap",
            explanation=(
                "A limitation of liability clause was found, but it contains no limiting "
                "phrase such as 'shall not exceed', 'limited to' or 'capped at', so the "
                "extracted text does not establish a ceiling on exposure."
            ),
            clause_type="liability",
            evidence={"cap_found": False},
        )
    ]


def rule_penalty_exposure(spec: RuleSpec, context: RiskContext) -> list[ContractRiskFinding]:
    """CA-R007: the contract carries penalties or service credits."""
    clause = context.clause("penalties")
    if clause is None:
        return []
    amount = clause.values.get("amount")
    percentage = clause.values.get("percentage")
    figure = ""
    if amount is not None:
        figure = f" Amounts of up to {amount:,.2f} {clause.values.get('currency') or ''}".rstrip()
    elif percentage is not None:
        figure = f" A rate of {percentage:g}% appears in the clause."
    return [
        _finding(
            spec,
            context,
            title="Penalties or service credits apply",
            explanation=(
                f"The contract contains a penalty, liquidated-damages or service-credit "
                f"clause, so failing to perform carries a direct financial consequence.{figure}"
            ),
            clause_type="penalties",
            evidence={
                "amount": amount,
                "currency": clause.values.get("currency"),
                "percentage": percentage,
            },
        )
    ]


def rule_expiring_soon(spec: RuleSpec, context: RiskContext) -> list[ContractRiskFinding]:
    """CA-R008: the contract has expired or is about to."""
    expiration = context.date_value("expiration_date")
    if expiration is None:
        return []

    days = (expiration - context.as_of_date).days
    window = int(spec.param("expiring_within_days", 90))
    critical = int(spec.param("critical_within_days", 30))
    if days > window:
        return []

    if days < 0:
        title = f"Contract expired {abs(days)} day(s) ago"
        explanation = (
            f"The extracted expiration date is {expiration.isoformat()}, which is "
            f"{abs(days)} day(s) before the assessment date {context.as_of_date.isoformat()}."
        )
        severity = Severity.CRITICAL
    else:
        title = f"Contract expires in {days} day(s)"
        explanation = (
            f"The extracted expiration date is {expiration.isoformat()}, {days} day(s) after "
            f"the assessment date {context.as_of_date.isoformat()}, inside the {window}-day "
            f"warning window."
        )
        severity = Severity.CRITICAL if days <= critical else spec.base_severity

    return [
        _finding(
            spec,
            context,
            title=title,
            explanation=explanation,
            severity=severity,
            clause_type="term",
            evidence={
                "expiration_date": expiration,
                "days_to_expiration": days,
                "as_of_date": context.as_of_date,
            },
            references=context.references_for("term"),
        )
    ]


def rule_renewal_deadline(spec: RuleSpec, context: RiskContext) -> list[ContractRiskFinding]:
    """CA-R009: the auto-renewal notice deadline is closing or has passed."""
    deadline = context.date_value("notice_deadline")
    if deadline is None or context.clause("auto_renewal") is None:
        return []

    days = (deadline - context.as_of_date).days
    warning = int(spec.param("warning_days", 45))
    if days > warning:
        return []

    if days < 0:
        title = f"Auto-renewal notice deadline passed {abs(days)} day(s) ago"
        explanation = (
            f"The notice deadline computed from the expiration date and the notice period was "
            f"{deadline.isoformat()}. It has passed, so on the current terms the agreement "
            f"renews for another term."
        )
    else:
        title = f"Auto-renewal notice deadline in {days} day(s)"
        explanation = (
            f"Notice to prevent automatic renewal must be given by {deadline.isoformat()}, "
            f"{days} day(s) from the assessment date {context.as_of_date.isoformat()}."
        )

    return [
        _finding(
            spec,
            context,
            title=title,
            explanation=explanation,
            clause_type="auto_renewal",
            evidence={
                "notice_deadline": deadline,
                "days_to_deadline": days,
                "expiration_date": context.date_value("expiration_date"),
                "notice_period_days": context.key_dates.get("notice_period_days"),
            },
        )
    ]


def rule_payment_terms_outside_policy(
    spec: RuleSpec, context: RiskContext
) -> list[ContractRiskFinding]:
    """CA-R010: the agreed payment days fall outside the company policy band."""
    clause = context.clause("payment_terms")
    if clause is None:
        return []
    days = clause.values.get("net_days")
    if days is None:
        return []

    maximum = int(spec.param("policy_max_days", 60))
    minimum = int(spec.param("policy_min_days", 14))
    if minimum <= days <= maximum:
        return []

    direction = "longer than" if days > maximum else "shorter than"
    limit = maximum if days > maximum else minimum
    return [
        _finding(
            spec,
            context,
            title=f"Payment terms of {days} days are outside policy",
            explanation=(
                f"The extracted payment term is net {days} days, which is {direction} the "
                f"{limit}-day policy limit in the configuration."
            ),
            clause_type="payment_terms",
            evidence={
                "net_days": days,
                "policy_min_days": minimum,
                "policy_max_days": maximum,
            },
        )
    ]


def rule_one_sided_indemnity(spec: RuleSpec, context: RiskContext) -> list[ContractRiskFinding]:
    """CA-R011: only one party indemnifies the other."""
    clause = context.clause("indemnification")
    if clause is None:
        return []
    text = " ".join(reference.excerpt for reference in clause.references)
    customer = [p.pattern for p in spec.patterns("customer_indemnifies_patterns") if p.search(text)]
    supplier = [p.pattern for p in spec.patterns("supplier_indemnifies_patterns") if p.search(text)]

    if not customer or supplier:
        return []
    return [
        _finding(
            spec,
            context,
            title="Indemnity runs one way only",
            explanation=(
                "The indemnification clause obliges the customer side to indemnify, with no "
                "matching obligation on the supplier side in the extracted text."
            ),
            clause_type="indemnification",
            evidence={"customer_indemnifies": customer, "supplier_indemnifies": supplier},
        )
    ]


def rule_service_levels_without_remedy(
    spec: RuleSpec, context: RiskContext
) -> list[ContractRiskFinding]:
    """CA-R012: service levels are promised but nothing happens when they are missed."""
    if context.clause("service_levels") is None:
        return []
    if context.clause("penalties") is not None:
        return []
    return [
        _finding(
            spec,
            context,
            title="Service levels carry no stated remedy",
            explanation=(
                "The contract commits to service levels but no penalty, service credit or "
                "other remedy clause was found, so missing a service level has no stated "
                "financial consequence."
            ),
            clause_type="service_levels",
            evidence={"service_levels_present": True, "penalties_present": False},
            references=context.references_for("service_levels"),
        )
    ]


def rule_free_assignment(spec: RuleSpec, context: RiskContext) -> list[ContractRiskFinding]:
    """CA-R013: the agreement can be handed to another entity without consent."""
    clause = context.clause("assignment")
    if clause is None:
        return []
    text = " ".join(reference.excerpt for reference in clause.references)
    if any(pattern.search(text) for pattern in spec.patterns("consent_patterns")):
        return []
    matched = [p.pattern for p in spec.patterns("free_assignment_patterns") if p.search(text)]
    if not matched:
        return []
    return [
        _finding(
            spec,
            context,
            title="Assignment permitted without consent",
            explanation=(
                "The assignment clause allows the agreement to be transferred without a "
                "consent requirement in the extracted text, so the counterparty could change "
                "without the company's agreement."
            ),
            clause_type="assignment",
            evidence={"matched_phrases": matched},
        )
    ]


def rule_no_audit_rights(spec: RuleSpec, context: RiskContext) -> list[ContractRiskFinding]:
    """CA-R014: no right to inspect the supplier's records."""
    if context.clause("audit_rights") is not None:
        return []
    return [
        _finding(
            spec,
            context,
            title="No audit rights found",
            explanation=(
                "No audit or inspection clause was extracted, so the company has no stated "
                "contractual right to inspect the supplier's records under this agreement."
            ),
            clause_type="audit_rights",
            evidence={"clause_present": False},
            references=[],
        )
    ]


def rule_governing_law_not_approved(
    spec: RuleSpec, context: RiskContext
) -> list[ContractRiskFinding]:
    """CA-R015: the contract is governed by law outside the approved list."""
    clause = context.clause("governing_law")
    if clause is None:
        return []
    jurisdiction = clause.values.get("jurisdiction")
    if not jurisdiction:
        return []

    approved = {str(item).lower() for item in spec.param("approved_jurisdictions", [])}
    lowered = str(jurisdiction).lower()
    if any(item in lowered for item in approved):
        return []
    return [
        _finding(
            spec,
            context,
            title=f"Governing law is {jurisdiction}",
            explanation=(
                f"The agreement is governed by the laws of {jurisdiction}, which is not on the "
                f"approved jurisdiction list in the configuration. Enforcement and legal cost "
                f"assumptions may not hold."
            ),
            clause_type="governing_law",
            evidence={"jurisdiction": jurisdiction, "approved_count": len(approved)},
        )
    ]


def rule_instruction_like_text(
    spec: RuleSpec, context: RiskContext
) -> list[ContractRiskFinding]:
    """CA-R016: the document tries to give the application instructions.

    An uploaded contract is data. Text inside it that reads like an instruction
    is neutralised before any AI call and reported here, so a reviewer learns
    the document was tampered with rather than the application quietly obeying
    it.
    """
    if not context.injection_markers and not contains_injection_markers(context.full_text):
        return []
    return [
        _finding(
            spec,
            context,
            title="Document contains instruction-like text",
            explanation=(
                "The document contains text written as an instruction to an automated system "
                "(for example an attempt to override rules or request secrets). It was treated "
                "strictly as data: it was neutralised before any AI call, it did not change any "
                "extraction, and no part of it was executed. "
                + context.config.reporting.injection_notice
            ),
            evidence={
                "markers_found": context.injection_markers[:5],
                "marker_count": len(context.injection_markers),
            },
            references=[],
        )
    ]


def rule_little_text(spec: RuleSpec, context: RiskContext) -> list[ContractRiskFinding]:
    """CA-R017: nothing readable came out of the document."""
    minimum = int(spec.param("min_chars", 400))
    if not context.needs_ocr and context.char_count >= minimum:
        return []
    reason = (
        "No selectable text was found, which is the signature of a scanned document."
        if context.needs_ocr
        else f"Only {context.char_count} characters of text were extracted, below the "
        f"{minimum}-character minimum for a usable analysis."
    )
    return [
        _finding(
            spec,
            context,
            title="Little or no text could be extracted",
            explanation=(
                f"{reason} Clause extraction and the answers below are therefore incomplete "
                f"and must not be relied on."
            ),
            evidence={"char_count": context.char_count, "needs_ocr": context.needs_ocr},
            references=[],
        )
    ]


def rule_missing_key_date(spec: RuleSpec, context: RiskContext) -> list[ContractRiskFinding]:
    """CA-R018: a date the contract register needs was not stated."""
    labels = {
        "effective_date": "effective date",
        "expiration_date": "expiration date",
        "renewal_date": "renewal date",
    }
    missing = [
        name
        for name in spec.param("required_dates", ["effective_date", "expiration_date"])
        if context.date_value(name) is None
    ]
    if not missing:
        return []
    names = ", ".join(labels.get(name, name.replace("_", " ")) for name in missing)
    return [
        _finding(
            spec,
            context,
            title=f"Key date not stated: {names}",
            explanation=(
                f"The document does not state a readable {names}. Expiry monitoring and "
                f"renewal notice deadlines cannot be computed without it."
            ),
            clause_type="term",
            evidence={"missing_dates": missing},
            references=context.references_for("term"),
        )
    ]


def rule_low_confidence_clause(
    spec: RuleSpec, context: RiskContext
) -> list[ContractRiskFinding]:
    """CA-R019: a clause was found, but the evidence for it is thin."""
    threshold = float(spec.param("below_confidence", 0.55))
    weak = [
        extraction
        for extraction in context.clauses.values()
        if extraction.present and extraction.confidence < threshold
    ]
    if not weak:
        return []
    weak.sort(key=lambda extraction: extraction.confidence)
    names = ", ".join(f"{item.label} ({item.confidence:.2f})" for item in weak[:5])
    return [
        _finding(
            spec,
            context,
            title=f"{len(weak)} clause(s) extracted with low confidence",
            explanation=(
                f"These clauses matched below the {threshold:.2f} confidence threshold and "
                f"should be checked against the cited pages before being relied on: {names}."
            ),
            evidence={
                "threshold": threshold,
                "clauses": [
                    {
                        "clause_type": item.clause_type,
                        "confidence": item.confidence,
                        "page_number": item.page_number,
                    }
                    for item in weak
                ],
            },
            references=[item.references[0] for item in weak[:2] if item.references],
        )
    ]


def rule_no_cap_amount(spec: RuleSpec, context: RiskContext) -> list[ContractRiskFinding]:
    """CA-R020: the liability cap is described but never quantified."""
    clause = context.clause("liability")
    if clause is None:
        return []
    if clause.values.get("amount") is not None or clause.values.get("percentage") is not None:
        return []
    # A clause with no cap at all is CA-R006's finding; this one is about a cap
    # that exists but carries no number.
    cap_patterns = context.config.rule("CA-R006").patterns("cap_patterns")
    text = " ".join(reference.excerpt for reference in clause.references)
    if not any(pattern.search(text) for pattern in cap_patterns):
        return []
    return [
        _finding(
            spec,
            context,
            title="Liability cap is not quantified",
            explanation=(
                "The liability clause limits liability but the extracted text contains no "
                "amount or percentage, so the cap cannot be recorded as a figure in the "
                "contract register."
            ),
            clause_type="liability",
            evidence={"cap_amount_found": False},
        )
    ]


#: Rule id -> implementation. The engine iterates this in order.
RULES: dict[str, Callable[[RuleSpec, RiskContext], list[ContractRiskFinding]]] = {
    "CA-R001": rule_auto_renewal_present,
    "CA-R002": rule_short_notice_period,
    "CA-R003": rule_no_termination_clause,
    "CA-R004": rule_missing_required_clause,
    "CA-R005": rule_unlimited_liability,
    "CA-R006": rule_no_liability_cap,
    "CA-R007": rule_penalty_exposure,
    "CA-R008": rule_expiring_soon,
    "CA-R009": rule_renewal_deadline,
    "CA-R010": rule_payment_terms_outside_policy,
    "CA-R011": rule_one_sided_indemnity,
    "CA-R012": rule_service_levels_without_remedy,
    "CA-R013": rule_free_assignment,
    "CA-R014": rule_no_audit_rights,
    "CA-R015": rule_governing_law_not_approved,
    "CA-R016": rule_instruction_like_text,
    "CA-R017": rule_little_text,
    "CA-R018": rule_missing_key_date,
    "CA-R019": rule_low_confidence_clause,
    "CA-R020": rule_no_cap_amount,
}


def run_rule(rule_id: str, context: RiskContext) -> list[ContractRiskFinding]:
    """Run one rule. Raises only if the rule itself is broken."""
    spec = context.config.rule(rule_id)
    implementation = RULES.get(rule_id)
    if implementation is None:
        raise KeyError(f"No implementation registered for rule {rule_id}")
    return implementation(spec, context)


def _finding(
    spec: RuleSpec,
    context: RiskContext,
    *,
    title: str,
    explanation: str,
    severity: Severity | None = None,
    clause_type: str | None = None,
    evidence: dict[str, Any] | None = None,
    references: list[SourceReference] | None = None,
) -> ContractRiskFinding:
    """Build a finding, defaulting its references to the clause it is about."""
    resolved_references = (
        references
        if references is not None
        else (context.references_for(clause_type) if clause_type else [])
    )
    return ContractRiskFinding(
        rule_id=spec.rule_id,
        rule_name=spec.name,
        category=spec.category,
        severity=severity or spec.base_severity,
        title=title,
        explanation=explanation,
        recommended_action=spec.recommended_action,
        clause_type=clause_type,
        evidence=evidence or {},
        references=resolved_references,
    )
