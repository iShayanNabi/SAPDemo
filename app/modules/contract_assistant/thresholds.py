"""Typed, validated access to the Contract Assistant configuration.

Every clause pattern, confidence weight, date window and risk threshold lives
in ``config/contract_rules.json`` and is validated here at load time. Regular
expressions are compiled once, during validation, so a typo in a pattern is a
startup error with the offending clause named - never a rule that silently
matches nothing at request time.

The engine reads values through this object, which is what makes "add a clause
type" or "tighten the notice-period threshold" a JSON edit rather than a code
change.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, PrivateAttr
from pydantic import ValidationError as PydanticValidationError

from app.core.exceptions import ConfigurationError
from app.core.logging import get_logger
from app.schemas.common import Severity

logger = get_logger(__name__)

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "contract_rules.json"

#: The clause types the module extracts, in the order the UI should show them.
#: The names must exist in the configuration; the loader enforces that.
CLAUSE_TYPES: tuple[str, ...] = (
    "term",
    "auto_renewal",
    "termination",
    "payment_terms",
    "pricing",
    "service_levels",
    "penalties",
    "liability",
    "indemnification",
    "confidentiality",
    "data_privacy",
    "insurance",
    "governing_law",
    "dispute_resolution",
    "force_majeure",
    "assignment",
    "audit_rights",
)

#: How important a missing clause is, ordered from least to most serious.
IMPORTANCE_LEVELS: tuple[str, ...] = ("low", "medium", "high", "critical")


def compile_patterns(
    patterns: list[str], *, where: str, case_sensitive: bool = False
) -> list[re.Pattern[str]]:
    """Compile a list of patterns, naming the source on failure.

    Vocabulary patterns (clause phrases, dates, duty verbs) are compiled
    case-insensitively, because a contract may shout or whisper the same words.

    Structure patterns - headings, titles and party names - are compiled
    **case-sensitively**, because capitalisation is the signal they read.
    Compiling ``[A-Z]`` with ``re.IGNORECASE`` quietly makes it match anything,
    which turns "the line is in capitals" into "the line exists" and produces
    party names like ``is entered into between Nordwind Industrie GmbH``.
    """
    flags = 0 if case_sensitive else re.IGNORECASE
    compiled: list[re.Pattern[str]] = []
    for pattern in patterns:
        try:
            compiled.append(re.compile(pattern, flags))
        except re.error as exc:
            raise ValueError(f"invalid regular expression in {where}: {pattern!r} ({exc})") from exc
    return compiled


class ExtractionSettings(BaseModel):
    """How much text a clause carries and when a match is discarded."""

    description: str = ""
    excerpt_chars: int = Field(default=320, gt=0)
    max_excerpt_chars: int = Field(default=700, gt=0)
    min_confidence: float = Field(default=0.3, ge=0.0, le=1.0)
    max_instances_per_clause: int = Field(default=3, ge=1)
    context_chars_before: int = Field(default=60, ge=0)
    review_below_confidence: float = Field(default=0.55, ge=0.0, le=1.0)


class ConfidenceSettings(BaseModel):
    """The documented, deterministic confidence formula."""

    description: str = ""
    base: float = Field(default=0.3, ge=0.0, le=1.0)
    heading_match: float = Field(default=0.32, ge=0.0, le=1.0)
    primary_keyword: float = Field(default=0.2, ge=0.0, le=1.0)
    secondary_keyword: float = Field(default=0.05, ge=0.0, le=1.0)
    max_secondary: float = Field(default=0.15, ge=0.0, le=1.0)
    value_extracted: float = Field(default=0.1, ge=0.0, le=1.0)
    scattered_penalty: float = Field(default=0.08, ge=0.0, le=1.0)
    minimum: float = Field(default=0.05, ge=0.0, le=1.0)
    maximum: float = Field(default=0.99, ge=0.0, le=1.0)

    def score(
        self,
        *,
        heading_match: bool,
        primary_hits: int,
        secondary_hits: int,
        value_extracted: bool,
        scattered: bool,
    ) -> float:
        """Compute one clause's confidence from the evidence actually seen."""
        value = self.base
        if heading_match:
            value += self.heading_match
        if primary_hits:
            value += self.primary_keyword
        value += min(secondary_hits * self.secondary_keyword, self.max_secondary)
        if value_extracted:
            value += self.value_extracted
        if scattered:
            value -= self.scattered_penalty
        return round(min(max(value, self.minimum), self.maximum), 3)


class SectionSettings(BaseModel):
    """How a heading is recognised in extracted text."""

    description: str = ""
    min_heading_chars: int = Field(default=3, ge=1)
    max_heading_chars: int = Field(default=90, gt=1)
    max_heading_words: int = Field(default=12, ge=1)
    numbered_patterns: list[str] = Field(default_factory=list)
    uppercase_pattern: str
    title_case_pattern: str
    stop_words_in_heading: list[str] = Field(default_factory=list)

    _numbered: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _uppercase: re.Pattern[str] | None = PrivateAttr(default=None)
    _title_case: re.Pattern[str] | None = PrivateAttr(default=None)

    def model_post_init(self, _context: object) -> None:
        self._numbered = compile_patterns(
            self.numbered_patterns, where="sections.numbered_patterns", case_sensitive=True
        )
        self._uppercase = compile_patterns(
            [self.uppercase_pattern], where="sections.uppercase_pattern", case_sensitive=True
        )[0]
        self._title_case = compile_patterns(
            [self.title_case_pattern], where="sections.title_case_pattern", case_sensitive=True
        )[0]

    @property
    def numbered(self) -> list[re.Pattern[str]]:
        return self._numbered

    @property
    def uppercase(self) -> re.Pattern[str]:
        assert self._uppercase is not None  # set in model_post_init
        return self._uppercase

    @property
    def title_case(self) -> re.Pattern[str]:
        assert self._title_case is not None  # set in model_post_init
        return self._title_case


class DocumentSettings(BaseModel):
    """How the contract title and the parties are recognised."""

    description: str = ""
    title_patterns: list[str] = Field(default_factory=list)
    title_scan_lines: int = Field(default=40, ge=1)
    party_patterns: list[str] = Field(default_factory=list)
    #: Leading words trimmed from a captured party name ("between Nordwind ...").
    party_stop_words: list[str] = Field(default_factory=list)
    #: A capture containing one of these is document furniture, not a party.
    party_reject_words: list[str] = Field(default_factory=list)
    role_patterns: dict[str, list[str]] = Field(default_factory=dict)
    party_scan_chars: int = Field(default=4000, ge=100)
    max_parties: int = Field(default=6, ge=1)

    _titles: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _parties: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _roles: dict[str, list[re.Pattern[str]]] = PrivateAttr(default_factory=dict)

    def model_post_init(self, _context: object) -> None:
        self._titles = compile_patterns(
            self.title_patterns, where="document.title_patterns", case_sensitive=True
        )
        self._parties = compile_patterns(
            self.party_patterns, where="document.party_patterns", case_sensitive=True
        )
        self._roles = {
            role: compile_patterns(patterns, where=f"document.role_patterns.{role}")
            for role, patterns in self.role_patterns.items()
        }

    @property
    def titles(self) -> list[re.Pattern[str]]:
        return self._titles

    @property
    def parties(self) -> list[re.Pattern[str]]:
        return self._parties

    @property
    def roles(self) -> dict[str, list[re.Pattern[str]]]:
        return self._roles

    def clean_party_name(self, raw: str) -> str | None:
        """Trim and sanity-check a captured party name.

        A capture like ``between Nordwind Industrie GmbH`` or ``This Master
        Services Agreement`` is what generous patterns produce; a contract
        register full of those is worse than an empty one. Leading connectives
        are trimmed and document furniture is rejected outright.
        """
        name = re.sub(r"\s+", " ", raw or "").strip(" ,.;:\"'")
        if not name:
            return None

        stop_words = {word.lower() for word in self.party_stop_words}
        tokens = name.split()
        while tokens and tokens[0].strip(",.;:").lower() in stop_words:
            tokens.pop(0)
        name = " ".join(tokens).strip(" ,.;:\"'")

        if len(name) < 3 or len(name) > 80:
            return None
        lowered = name.lower()
        if any(word in lowered for word in (item.lower() for item in self.party_reject_words)):
            return None
        if not any(char.isalpha() for char in name):
            return None
        return name


class DateSettings(BaseModel):
    """Date parsing and the windows used to report a contract as expiring."""

    description: str = ""
    day_first: bool = True
    expiring_within_days: int = Field(default=90, ge=0)
    critical_within_days: int = Field(default=30, ge=0)
    notice_deadline_warning_days: int = Field(default=45, ge=0)
    effective_date_patterns: list[str] = Field(default_factory=list)
    expiration_date_patterns: list[str] = Field(default_factory=list)
    renewal_date_patterns: list[str] = Field(default_factory=list)
    signature_date_patterns: list[str] = Field(default_factory=list)
    term_length_patterns: list[str] = Field(default_factory=list)
    renewal_term_patterns: list[str] = Field(default_factory=list)
    notice_period_patterns: list[str] = Field(default_factory=list)
    number_words: dict[str, int] = Field(default_factory=dict)
    unit_days: dict[str, int] = Field(default_factory=dict)

    _compiled: dict[str, list[re.Pattern[str]]] = PrivateAttr(default_factory=dict)

    def model_post_init(self, _context: object) -> None:
        self._compiled = {
            name: compile_patterns(getattr(self, f"{name}_patterns"), where=f"dates.{name}_patterns")
            for name in (
                "effective_date",
                "expiration_date",
                "renewal_date",
                "signature_date",
                "term_length",
                "renewal_term",
                "notice_period",
            )
        }

    def patterns_for(self, name: str) -> list[re.Pattern[str]]:
        """Return the compiled patterns for one date/duration kind."""
        if name not in self._compiled:
            raise ConfigurationError(f"Unknown date pattern group: {name}")
        return self._compiled[name]

    def to_days(self, count: str, unit: str) -> int | None:
        """Turn a captured ``('three', 'months')`` into a day count."""
        raw = (count or "").strip().lower()
        if raw.isdigit():
            number = int(raw)
        elif raw in self.number_words:
            number = int(self.number_words[raw])
        else:
            return None
        factor = self.unit_days.get((unit or "").strip().lower())
        if factor is None:
            return None
        return number * factor


class PaymentSettings(BaseModel):
    """Payment term parsing and the policy the extracted terms are checked against."""

    description: str = ""
    net_days_patterns: list[str] = Field(default_factory=list)
    early_payment_discount_patterns: list[str] = Field(default_factory=list)
    policy_max_days: int = Field(default=60, ge=0)
    policy_min_days: int = Field(default=14, ge=0)

    _net_days: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _discounts: list[re.Pattern[str]] = PrivateAttr(default_factory=list)

    def model_post_init(self, _context: object) -> None:
        self._net_days = compile_patterns(self.net_days_patterns, where="payment.net_days_patterns")
        self._discounts = compile_patterns(
            self.early_payment_discount_patterns, where="payment.early_payment_discount_patterns"
        )

    @property
    def net_days(self) -> list[re.Pattern[str]]:
        return self._net_days

    @property
    def discounts(self) -> list[re.Pattern[str]]:
        return self._discounts


class AmountSettings(BaseModel):
    """How monetary caps and percentages are recognised inside a clause."""

    description: str = ""
    currency_symbols: dict[str, list[str]] = Field(default_factory=dict)
    amount_pattern: str
    percentage_pattern: str

    _amount: re.Pattern[str] | None = PrivateAttr(default=None)
    _percentage: re.Pattern[str] | None = PrivateAttr(default=None)

    def model_post_init(self, _context: object) -> None:
        self._amount = compile_patterns([self.amount_pattern], where="amounts.amount_pattern")[0]
        self._percentage = compile_patterns(
            [self.percentage_pattern], where="amounts.percentage_pattern"
        )[0]

    @property
    def amount(self) -> re.Pattern[str]:
        assert self._amount is not None
        return self._amount

    @property
    def percentage(self) -> re.Pattern[str]:
        assert self._percentage is not None
        return self._percentage

    def currency_for(self, token: str | None) -> str | None:
        """Map a captured currency token ('€', 'EUR') to an ISO code."""
        if not token:
            return None
        raw = token.strip().upper()
        for code, symbols in self.currency_symbols.items():
            if raw == code or raw in {symbol.upper() for symbol in symbols}:
                return code
        return None


class ClauseSpec(BaseModel):
    """One clause type: how it is recognised and how serious its absence is."""

    label: str
    description: str = ""
    required: bool = False
    importance: str = "medium"
    heading_patterns: list[str] = Field(default_factory=list)
    primary_patterns: list[str] = Field(default_factory=list)
    secondary_patterns: list[str] = Field(default_factory=list)
    #: Phrases that *veto* a primary hit in the same sentence. "This Agreement
    #: does not renew automatically" contains "renew automatically" and means
    #: the exact opposite of it; without a veto the clause reports a renewal
    #: that the contract explicitly rules out.
    negation_patterns: list[str] = Field(default_factory=list)
    question_patterns: list[str] = Field(default_factory=list)
    missing_message: str = ""

    _headings: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _primary: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _secondary: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _negations: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _questions: list[re.Pattern[str]] = PrivateAttr(default_factory=list)

    def model_post_init(self, _context: object) -> None:
        if self.importance not in IMPORTANCE_LEVELS:
            raise ValueError(
                f"clause '{self.label}' has importance '{self.importance}', "
                f"expected one of {list(IMPORTANCE_LEVELS)}"
            )
        if not self.primary_patterns:
            raise ValueError(f"clause '{self.label}' has no primary_patterns to match on")
        where = f"clauses.{self.label}"
        self._headings = compile_patterns(self.heading_patterns, where=f"{where}.heading_patterns")
        self._primary = compile_patterns(self.primary_patterns, where=f"{where}.primary_patterns")
        self._secondary = compile_patterns(self.secondary_patterns, where=f"{where}.secondary_patterns")
        self._negations = compile_patterns(
            self.negation_patterns, where=f"{where}.negation_patterns"
        )
        self._questions = compile_patterns(self.question_patterns, where=f"{where}.question_patterns")

    @property
    def headings(self) -> list[re.Pattern[str]]:
        return self._headings

    @property
    def negations(self) -> list[re.Pattern[str]]:
        return self._negations

    @property
    def primary(self) -> list[re.Pattern[str]]:
        return self._primary

    @property
    def secondary(self) -> list[re.Pattern[str]]:
        return self._secondary

    @property
    def questions(self) -> list[re.Pattern[str]]:
        return self._questions


class ObligationSettings(BaseModel):
    """How duty sentences are recognised and classified."""

    description: str = ""
    modal_patterns: list[str] = Field(default_factory=list)
    negative_patterns: list[str] = Field(default_factory=list)
    min_words: int = Field(default=6, ge=1)
    max_chars: int = Field(default=400, gt=0)
    max_obligations: int = Field(default=80, ge=0)
    duty_type_patterns: dict[str, list[str]] = Field(default_factory=dict)

    _modals: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _negatives: list[re.Pattern[str]] = PrivateAttr(default_factory=list)
    _duty_types: dict[str, list[re.Pattern[str]]] = PrivateAttr(default_factory=dict)

    def model_post_init(self, _context: object) -> None:
        self._modals = compile_patterns(self.modal_patterns, where="obligations.modal_patterns")
        self._negatives = compile_patterns(
            self.negative_patterns, where="obligations.negative_patterns"
        )
        self._duty_types = {
            name: compile_patterns(patterns, where=f"obligations.duty_type_patterns.{name}")
            for name, patterns in self.duty_type_patterns.items()
        }

    @property
    def modals(self) -> list[re.Pattern[str]]:
        return self._modals

    @property
    def negatives(self) -> list[re.Pattern[str]]:
        return self._negatives

    @property
    def duty_types(self) -> dict[str, list[re.Pattern[str]]]:
        return self._duty_types


class QuestionSettings(BaseModel):
    """Deterministic question-answering behaviour."""

    description: str = ""
    max_citations: int = Field(default=4, ge=1)
    max_answer_clauses: int = Field(default=3, ge=1)
    min_intent_score: float = Field(default=1.0, ge=0.0)
    heading_match_score: float = Field(default=2.0, ge=0.0)
    keyword_match_score: float = Field(default=1.0, ge=0.0)
    not_found_message: str = ""
    no_analysis_message: str = ""
    needs_ocr_message: str = ""
    suggested_questions: list[str] = Field(default_factory=list)


class RiskBand(BaseModel):
    """One labelled band of the 0-100 contract risk scale."""

    label: str
    min_score: float = Field(ge=0.0, le=100.0)
    max_score: float = Field(ge=0.0, le=100.0)


class RiskSettings(BaseModel):
    """How findings roll up into a contract risk score."""

    description: str = ""
    severity_by_importance: dict[str, str] = Field(default_factory=dict)
    score_weights: dict[str, float] = Field(default_factory=dict)
    score_cap: float = Field(default=100.0, gt=0.0)
    bands: list[RiskBand] = Field(min_length=1)

    def model_post_init(self, _context: object) -> None:
        allowed = {item.value for item in Severity}
        for importance, severity in self.severity_by_importance.items():
            if severity not in allowed:
                raise ValueError(
                    f"severity_by_importance['{importance}'] is '{severity}', "
                    f"expected one of {sorted(allowed)}"
                )
        for severity in self.score_weights:
            if severity not in allowed:
                raise ValueError(
                    f"score_weights has unknown severity '{severity}', expected one of "
                    f"{sorted(allowed)}"
                )

    def severity_for_importance(self, importance: str) -> Severity:
        """Map a clause importance onto the severity a missing clause gets."""
        return Severity(self.severity_by_importance.get(importance, "medium"))

    def weight_for(self, severity: Severity) -> float:
        return float(self.score_weights.get(severity.value, 0.0))

    def band_for(self, score: float) -> str:
        """Label a 0-100 contract risk score."""
        value = float(score)
        for band in self.bands:
            if band.min_score <= value < band.max_score:
                return band.label
        top = max(self.bands, key=lambda item: item.max_score)
        if value >= top.max_score:
            return top.label
        return min(self.bands, key=lambda item: item.min_score).label


class RuleSpec(BaseModel):
    """One configured risk rule."""

    #: Filled in by the parent config from the dictionary key, so a rule
    #: implementation always knows its own id without looking itself up.
    rule_id: str = ""
    name: str
    category: str
    enabled: bool = True
    base_severity: Severity
    recommended_action: str = ""
    params: dict[str, Any] = Field(default_factory=dict)

    def param(self, key: str, default: Any = None) -> Any:
        """Read one rule parameter, with a documented fallback."""
        return self.params.get(key, default)

    def patterns(self, key: str) -> list[re.Pattern[str]]:
        """Compile a list-of-patterns rule parameter."""
        return compile_patterns(list(self.params.get(key, [])), where=f"rules.{key}")


class ReportingSettings(BaseModel):
    """Presentation defaults and the standing disclaimers."""

    top_risks_default: int = Field(default=10, ge=1)
    contract_disclaimer: str = ""
    injection_notice: str = ""


class ContractAssistantConfig(BaseModel):
    """The complete, validated Contract Assistant configuration."""

    config_version: str
    description: str = ""
    extraction: ExtractionSettings = Field(default_factory=ExtractionSettings)
    confidence: ConfidenceSettings = Field(default_factory=ConfidenceSettings)
    sections: SectionSettings
    document: DocumentSettings
    dates: DateSettings
    payment: PaymentSettings
    amounts: AmountSettings
    clauses: dict[str, ClauseSpec]
    obligations: ObligationSettings = Field(default_factory=ObligationSettings)
    questions: QuestionSettings = Field(default_factory=QuestionSettings)
    risk: RiskSettings
    rules: dict[str, RuleSpec]
    reporting: ReportingSettings = Field(default_factory=ReportingSettings)

    def model_post_init(self, _context: object) -> None:
        missing = [name for name in CLAUSE_TYPES if name not in self.clauses]
        if missing:
            raise ValueError(f"configuration is missing clause types: {missing}")
        unknown = [name for name in self.clauses if name not in CLAUSE_TYPES]
        if unknown:
            raise ValueError(
                f"configuration declares clause types the engine does not know: {unknown}. "
                f"Add them to CLAUSE_TYPES in thresholds.py first."
            )
        for rule_id, spec in self.rules.items():
            spec.rule_id = rule_id

    # -- helpers ---------------------------------------------------------
    def clause(self, name: str) -> ClauseSpec:
        """Return one clause specification."""
        if name not in self.clauses:
            raise ConfigurationError(f"Unknown clause type: {name}")
        return self.clauses[name]

    def rule(self, rule_id: str) -> RuleSpec:
        """Return one rule specification."""
        if rule_id not in self.rules:
            raise ConfigurationError(f"Unknown contract rule: {rule_id}")
        return self.rules[rule_id]

    @property
    def required_clauses(self) -> list[str]:
        """Clause types whose absence is reported as a missing clause."""
        return [name for name in CLAUSE_TYPES if self.clauses[name].required]

    def enabled_rule_ids(self, enabled_rules: list[str] | None = None) -> list[str]:
        """Rule ids that should run, honouring an optional caller allow-list."""
        selected = set(enabled_rules) if enabled_rules else None
        return [
            rule_id
            for rule_id, spec in self.rules.items()
            if spec.enabled and (selected is None or rule_id in selected)
        ]


def load_contract_config(path: Path | str | None = None) -> ContractAssistantConfig:
    """Load and validate the Contract Assistant configuration from ``path``."""
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_file():
        raise ConfigurationError(
            f"Contract Assistant configuration file is missing: {config_path.name}"
        )
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError(
            f"Contract Assistant configuration is not valid JSON: {exc.msg} (line {exc.lineno})"
        ) from exc
    try:
        config = ContractAssistantConfig.model_validate(raw)
    except PydanticValidationError as exc:
        raise ConfigurationError(
            f"Contract Assistant configuration failed validation: {exc.error_count()} problem(s).",
            details={"errors": exc.errors(include_url=False)[:10]},
        ) from exc

    logger.info(
        "Loaded contract assistant configuration v%s (%d clause types, %d rules)",
        config.config_version,
        len(config.clauses),
        len(config.rules),
    )
    return config


@lru_cache(maxsize=1)
def get_contract_config() -> ContractAssistantConfig:
    """Return the cached default configuration."""
    return load_contract_config()
