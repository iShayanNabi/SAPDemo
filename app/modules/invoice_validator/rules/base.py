"""Building blocks for the deterministic invoice validation rules.

A rule is a small class with one job: look at the joined datasets (via
:class:`MatchContext`) and return :class:`ExceptionFinding` objects. Rules never
call an AI model, never touch the database and never read files, which is why
they are cheap to unit test and fully reproducible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from app.modules.invoice_validator.matching import MatchContext
from app.modules.invoice_validator.thresholds import InvoiceValidatorConfig
from app.schemas.common import OutputOrigin, Severity


def _json_safe(value: Any) -> Any:
    """Recursively convert numpy/pandas scalars into plain Python values."""
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return round(float(value), 6)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


@dataclass
class ExceptionFinding:
    """One deterministic invoice exception.

    ``output_origin`` is always ``rule_based``: the validation itself is never
    made by an AI model. Optional AI narratives are attached later, in separate
    fields.
    """

    rule_id: str
    rule_name: str
    exception_type: str
    category: str
    severity: Severity
    explanation: str
    recommended_action: str
    confidence_score: float
    difference_amount: float
    currency: str = "EUR"
    invoice_number: str | None = None
    supplier_id: str | None = None
    supplier_name: str | None = None
    po_number: str | None = None
    po_item: str | None = None
    gr_number: str | None = None
    expected_value: str | None = None
    actual_value: str | None = None
    difference: str | None = None
    evidence: dict[str, Any] = field(default_factory=dict)
    output_origin: OutputOrigin = OutputOrigin.RULE_BASED

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation used by exports, the API and persistence."""
        return {
            "rule_id": self.rule_id,
            "rule_name": self.rule_name,
            "exception_type": self.exception_type,
            "category": self.category,
            "severity": self.severity.value,
            "invoice_number": self.invoice_number,
            "supplier_id": self.supplier_id,
            "supplier_name": self.supplier_name,
            "po_number": self.po_number,
            "po_item": self.po_item,
            "gr_number": self.gr_number,
            "expected_value": self.expected_value,
            "actual_value": self.actual_value,
            "difference": self.difference,
            "difference_amount": round(float(self.difference_amount), 2),
            "currency": self.currency,
            "explanation": self.explanation,
            "recommended_action": self.recommended_action,
            "confidence_score": round(float(self.confidence_score), 3),
            "evidence": _json_safe(self.evidence),
            "output_origin": self.output_origin.value,
        }


def as_optional_str(value: Any) -> str | None:
    """Convert a value to ``str`` unless it is missing."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return str(value)


class BaseInvoiceRule:
    """Base class for every deterministic invoice rule.

    Subclasses set ``rule_id`` and implement :meth:`evaluate`.
    """

    rule_id: str = ""

    def __init__(self, config: InvoiceValidatorConfig) -> None:
        self.config = config
        self.settings = config.rule(self.rule_id)

    # -- convenience accessors ------------------------------------------------
    @property
    def name(self) -> str:
        return self.settings.name

    @property
    def category(self) -> str:
        return self.settings.category

    @property
    def base_severity(self) -> Severity:
        return self.settings.base_severity

    @property
    def confidence(self) -> float:
        return float(self.settings.confidence)

    @property
    def enabled(self) -> bool:
        return bool(self.settings.enabled)

    @property
    def action(self) -> str:
        return self.settings.recommended_action

    def param(self, key: str, default: Any = None) -> Any:
        """Return a configured parameter of this rule."""
        return self.settings.params.get(key, default)

    # -- API ------------------------------------------------------------------
    def evaluate(self, context: MatchContext) -> list[ExceptionFinding]:  # pragma: no cover - abstract
        """Return the exceptions this rule detects in ``context``."""
        raise NotImplementedError

    def make_exception(
        self,
        *,
        exception_type: str,
        explanation: str,
        evidence: dict[str, Any],
        difference_amount: float = 0.0,
        severity: Severity | None = None,
        confidence: float | None = None,
        currency: str | None = None,
        invoice_number: Any = None,
        supplier_id: Any = None,
        supplier_name: Any = None,
        po_number: Any = None,
        po_item: Any = None,
        gr_number: Any = None,
        expected_value: Any = None,
        actual_value: Any = None,
        difference: Any = None,
        recommended_action: str | None = None,
    ) -> ExceptionFinding:
        """Create an exception pre-filled with this rule's metadata."""
        return ExceptionFinding(
            rule_id=self.rule_id,
            rule_name=self.name,
            exception_type=exception_type,
            category=self.category,
            severity=severity or self.base_severity,
            explanation=explanation,
            recommended_action=recommended_action or self.action,
            confidence_score=self.confidence if confidence is None else confidence,
            difference_amount=float(difference_amount),
            currency=currency or self.config.base_currency,
            invoice_number=as_optional_str(invoice_number),
            supplier_id=as_optional_str(supplier_id),
            supplier_name=as_optional_str(supplier_name),
            po_number=as_optional_str(po_number),
            po_item=as_optional_str(po_item),
            gr_number=as_optional_str(gr_number),
            expected_value=as_optional_str(expected_value),
            actual_value=as_optional_str(actual_value),
            difference=as_optional_str(difference),
            evidence=evidence,
        )
