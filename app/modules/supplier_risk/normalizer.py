"""Turn uploaded supplier risk files into canonical, typed records.

Two datasets are normalised here:

``profiles``
    One row per supplier - the aggregated internal facts a risk profile needs.
``events``
    Optional. One row per dated internal record (a late delivery, an invoice
    exception, a compliance finding). These drive the risk trend and are what
    the copilot cites.

Both use the shared tabular pipeline (``build_canonical_frame`` ->
``coerce_types`` -> ``check_required_completeness``), so a bad cell becomes a
reported data-quality issue rather than an exception.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.modules.supplier_risk.field_definitions import (
    CANONICAL_FIELDS,
    EVENT_CANONICAL_FIELDS,
    EVENT_REGISTRY,
    REGISTRY,
)
from app.modules.supplier_risk.thresholds import SupplierRiskConfig
from app.services.tabular.parsing import (
    DataQualityIssue,
    build_canonical_frame,
    check_required_completeness,
    coerce_types,
)

logger = get_logger(__name__)

__all__ = [
    "NormalizedRiskEvent",
    "NormalizedSupplierProfile",
    "SupplierRiskDataset",
    "SupplierRiskEventDataset",
    "normalize_risk_event_dataframe",
    "normalize_supplier_risk_dataframe",
    "split_list",
]


def split_list(value: Any, delimiters: list[str] | tuple[str, ...]) -> list[str]:
    """Split a delimited cell into a de-duplicated list, preserving order."""
    if value is None:
        return []
    text = str(value).strip()
    if not text:
        return []
    parts = [text]
    for delimiter in delimiters:
        expanded: list[str] = []
        for part in parts:
            expanded.extend(part.split(delimiter))
        parts = expanded
    seen: set[str] = set()
    result: list[str] = []
    for part in parts:
        cleaned = part.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _cell(value: Any) -> Any:
    """Return ``None`` for any pandas/NumPy null, otherwise the value."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def _float(value: Any) -> float | None:
    value = _cell(value)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value: Any) -> int | None:
    value = _cell(value)
    if value is None:
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _str(value: Any) -> str | None:
    value = _cell(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _bool(value: Any) -> bool | None:
    value = _cell(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"true", "yes", "y", "1", "x"}:
        return True
    if text in {"false", "no", "n", "0"}:
        return False
    return None


def _as_date(value: Any) -> date | None:
    value = _cell(value)
    if value is None:
        return None
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return pd.Timestamp(value).date()
    except (TypeError, ValueError):
        return None


@dataclass
class NormalizedSupplierProfile:
    """One supplier's aggregated internal facts, typed and ready to score."""

    row_number: int
    supplier_id: str

    # -- inherited supplier master (module 3) --------------------------
    supplier_name: str | None = None
    materials_supplied: list[str] = field(default_factory=list)
    plants_served: list[str] = field(default_factory=list)
    regions_served: list[str] = field(default_factory=list)
    unit_price: float | None = None
    currency: str | None = None
    lead_time_days: int | None = None
    available_capacity: float | None = None
    on_time_delivery_rate: float | None = None
    quality_score: float | None = None
    defect_rate: float | None = None
    risk_score: float | None = None
    esg_score: float | None = None
    contract_status: str | None = None
    contract_expiration: date | None = None
    payment_terms: str | None = None
    historical_order_count: int | None = None
    historical_spend: float | None = None
    historical_spend_base: float | None = None

    # -- risk facts (module 5) -----------------------------------------
    country: str | None = None
    spend_category: str | None = None
    open_purchase_order_count: int | None = None
    active_contract_count: int | None = None
    contract_number: str | None = None
    delivery_count: int | None = None
    late_delivery_count: int | None = None
    average_delay_days: float | None = None
    quality_incident_count: int | None = None
    invoice_count: int | None = None
    invoice_exception_count: int | None = None
    disputed_invoice_count: int | None = None
    credit_score: float | None = None
    days_payable_outstanding: float | None = None
    payment_default_count: int | None = None
    financial_distress_flag: bool | None = None
    category_spend_share: float | None = None
    single_source_material_count: int | None = None
    compliance_finding_count: int | None = None
    certification_status: str | None = None
    audit_status: str | None = None
    last_audit_date: date | None = None
    capacity_utilization: float | None = None
    lead_time_variability_days: float | None = None
    alternative_supplier_count: int | None = None

    # -- derived ratios, computed once so scoring stays declarative -----
    @property
    def late_delivery_ratio(self) -> float | None:
        """Late deliveries as a percentage of all deliveries."""
        if self.late_delivery_count is None or not self.delivery_count:
            return None
        return round(self.late_delivery_count / self.delivery_count * 100.0, 4)

    @property
    def invoice_exception_rate(self) -> float | None:
        """Invoice exceptions as a percentage of all invoices."""
        if self.invoice_exception_count is None or not self.invoice_count:
            return None
        return round(self.invoice_exception_count / self.invoice_count * 100.0, 4)

    @property
    def region_coverage_count(self) -> int | None:
        """How many regions the supplier serves."""
        if not self.regions_served:
            return None
        return len(self.regions_served)

    def days_to_contract_expiry(self, as_of: date) -> int | None:
        """Days until the contract expires; negative once it has lapsed."""
        if self.contract_expiration is None:
            return None
        return (self.contract_expiration - as_of).days

    def to_record(self) -> dict[str, Any]:
        """A JSON/DB-safe dict of every canonical field."""
        record: dict[str, Any] = {"row_number": self.row_number}
        for name in CANONICAL_FIELDS:
            value = getattr(self, name, None)
            record[name] = value.isoformat() if isinstance(value, date) else value
        record["historical_spend_base"] = self.historical_spend_base
        return record


@dataclass
class NormalizedRiskEvent:
    """One dated internal record the copilot can cite."""

    row_number: int
    event_id: str
    supplier_id: str
    event_type: str
    event_date: date | None = None
    reference: str | None = None
    severity: str | None = None
    description: str | None = None
    amount: float | None = None
    currency: str | None = None
    amount_base: float | None = None

    def to_record(self) -> dict[str, Any]:
        """A JSON/DB-safe dict of every canonical event field."""
        record: dict[str, Any] = {"row_number": self.row_number}
        for name in EVENT_CANONICAL_FIELDS:
            value = getattr(self, name, None)
            record[name] = value.isoformat() if isinstance(value, date) else value
        record["amount_base"] = self.amount_base
        return record


@dataclass
class SupplierRiskDataset:
    """The normalised supplier risk profiles plus what went wrong loading them."""

    profiles: list[NormalizedSupplierProfile] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)
    applied_mapping: dict[str, str] = field(default_factory=dict)
    unmapped_columns: list[str] = field(default_factory=list)
    present_fields: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)

    @property
    def profile_count(self) -> int:
        return len(self.profiles)

    def issues_as_dicts(self) -> list[dict[str, Any]]:
        return [issue.to_dict() for issue in self.issues]


@dataclass
class SupplierRiskEventDataset:
    """The normalised risk events plus what went wrong loading them."""

    events: list[NormalizedRiskEvent] = field(default_factory=list)
    issues: list[DataQualityIssue] = field(default_factory=list)
    applied_mapping: dict[str, str] = field(default_factory=dict)
    unmapped_columns: list[str] = field(default_factory=list)

    @property
    def event_count(self) -> int:
        return len(self.events)

    def issues_as_dicts(self) -> list[dict[str, Any]]:
        return [issue.to_dict() for issue in self.issues]


def normalize_supplier_risk_dataframe(
    raw: pd.DataFrame,
    mapping: dict[str, str],
    config: SupplierRiskConfig,
) -> SupplierRiskDataset:
    """Normalise a raw supplier risk profile frame into typed records."""
    if raw.empty:
        raise ValidationError("The supplier risk file contains no rows to load.")

    mapped_fields = set(mapping.values())
    missing_required = [name for name in REGISTRY.required if name not in mapped_fields]
    if missing_required:
        raise ValidationError(
            "The supplier risk file is missing required fields.",
            details={"missing_required_fields": missing_required},
        )

    frame = build_canonical_frame(raw, mapping, REGISTRY)
    issues: list[DataQualityIssue] = []
    frame = coerce_types(frame, REGISTRY, issues)
    check_required_completeness(frame, REGISTRY, issues)

    delimiters = [";", "|", ",", "/"]
    profiles: list[NormalizedSupplierProfile] = []

    for record in frame.to_dict(orient="records"):
        supplier_id = _str(record.get("supplier_id"))
        if not supplier_id:
            # Rows without a supplier id cannot be profiled; the completeness
            # check above has already reported them.
            continue

        currency = _str(record.get("currency"))
        historical_spend = _float(record.get("historical_spend"))

        profiles.append(
            NormalizedSupplierProfile(
                row_number=_int(record.get("row_number")) or 0,
                supplier_id=supplier_id,
                supplier_name=_str(record.get("supplier_name")),
                materials_supplied=split_list(record.get("materials_supplied"), delimiters),
                plants_served=split_list(record.get("plants_served"), delimiters),
                regions_served=split_list(record.get("regions_served"), delimiters),
                unit_price=_float(record.get("unit_price")),
                currency=currency,
                lead_time_days=_int(record.get("lead_time_days")),
                available_capacity=_float(record.get("available_capacity")),
                on_time_delivery_rate=_float(record.get("on_time_delivery_rate")),
                quality_score=_float(record.get("quality_score")),
                defect_rate=_float(record.get("defect_rate")),
                risk_score=_float(record.get("risk_score")),
                esg_score=_float(record.get("esg_score")),
                contract_status=_str(record.get("contract_status")),
                contract_expiration=_as_date(record.get("contract_expiration")),
                payment_terms=_str(record.get("payment_terms")),
                historical_order_count=_int(record.get("historical_order_count")),
                historical_spend=historical_spend,
                historical_spend_base=(
                    None
                    if historical_spend is None
                    else round(float(historical_spend) * config.conversion_rate(currency), 2)
                ),
                country=_str(record.get("country")),
                spend_category=_str(record.get("spend_category")),
                open_purchase_order_count=_int(record.get("open_purchase_order_count")),
                active_contract_count=_int(record.get("active_contract_count")),
                contract_number=_str(record.get("contract_number")),
                delivery_count=_int(record.get("delivery_count")),
                late_delivery_count=_int(record.get("late_delivery_count")),
                average_delay_days=_float(record.get("average_delay_days")),
                quality_incident_count=_int(record.get("quality_incident_count")),
                invoice_count=_int(record.get("invoice_count")),
                invoice_exception_count=_int(record.get("invoice_exception_count")),
                disputed_invoice_count=_int(record.get("disputed_invoice_count")),
                credit_score=_float(record.get("credit_score")),
                days_payable_outstanding=_float(record.get("days_payable_outstanding")),
                payment_default_count=_int(record.get("payment_default_count")),
                financial_distress_flag=_bool(record.get("financial_distress_flag")),
                category_spend_share=_float(record.get("category_spend_share")),
                single_source_material_count=_int(record.get("single_source_material_count")),
                compliance_finding_count=_int(record.get("compliance_finding_count")),
                certification_status=_str(record.get("certification_status")),
                audit_status=_str(record.get("audit_status")),
                last_audit_date=_as_date(record.get("last_audit_date")),
                capacity_utilization=_float(record.get("capacity_utilization")),
                lead_time_variability_days=_float(record.get("lead_time_variability_days")),
                alternative_supplier_count=_int(record.get("alternative_supplier_count")),
            )
        )

    present_fields = sorted(mapped_fields)
    missing_fields = [name for name in CANONICAL_FIELDS if name not in mapped_fields]

    logger.info(
        "Normalised %d supplier risk profiles (%d mapped fields, %d data quality issues)",
        len(profiles),
        len(present_fields),
        len(issues),
    )

    return SupplierRiskDataset(
        profiles=profiles,
        issues=issues,
        applied_mapping=dict(mapping),
        unmapped_columns=[col for col in raw.columns if col not in mapping],
        present_fields=present_fields,
        missing_fields=missing_fields,
    )


def normalize_risk_event_dataframe(
    raw: pd.DataFrame,
    mapping: dict[str, str],
    config: SupplierRiskConfig,
) -> SupplierRiskEventDataset:
    """Normalise a raw risk-event frame into typed records."""
    if raw.empty:
        raise ValidationError("The risk event file contains no rows to load.")

    mapped_fields = set(mapping.values())
    missing_required = [name for name in EVENT_REGISTRY.required if name not in mapped_fields]
    if missing_required:
        raise ValidationError(
            "The risk event file is missing required fields.",
            details={"missing_required_fields": missing_required},
        )

    frame = build_canonical_frame(raw, mapping, EVENT_REGISTRY)
    issues: list[DataQualityIssue] = []
    frame = coerce_types(frame, EVENT_REGISTRY, issues)
    check_required_completeness(frame, EVENT_REGISTRY, issues)

    events: list[NormalizedRiskEvent] = []
    for record in frame.to_dict(orient="records"):
        event_id = _str(record.get("event_id"))
        supplier_id = _str(record.get("supplier_id"))
        event_type = _str(record.get("event_type"))
        if not event_id or not supplier_id or not event_type:
            continue

        currency = _str(record.get("currency"))
        amount = _float(record.get("amount"))
        severity = _str(record.get("severity"))

        events.append(
            NormalizedRiskEvent(
                row_number=_int(record.get("row_number")) or 0,
                event_id=event_id,
                supplier_id=supplier_id,
                event_type=event_type.strip().lower(),
                event_date=_as_date(record.get("event_date")),
                reference=_str(record.get("reference")),
                severity=severity.strip().lower() if severity else None,
                description=_str(record.get("description")),
                amount=amount,
                currency=currency,
                amount_base=(
                    None
                    if amount is None
                    else round(float(amount) * config.conversion_rate(currency), 2)
                ),
            )
        )

    logger.info("Normalised %d supplier risk events (%d data quality issues)", len(events), len(issues))

    return SupplierRiskEventDataset(
        events=events,
        issues=issues,
        applied_mapping=dict(mapping),
        unmapped_columns=[col for col in raw.columns if col not in mapping],
    )
