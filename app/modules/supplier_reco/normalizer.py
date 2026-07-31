"""Turn a raw uploaded supplier master file into canonical supplier records.

On top of the shared type coercion this module:

* splits the three multi-valued columns (materials, plants, regions) into lists
  using the configured delimiters;
* derives ``unit_price_base`` and ``historical_spend_base`` in the base currency,
  so a catalogue mixing EUR, USD and GBP prices is comparable.

Every derivation is deterministic. Nothing here decides whether a supplier is
*good* - that is the job of the eligibility and scoring layers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.modules.supplier_reco.field_definitions import (
    CANONICAL_FIELDS,
    LIST_FIELDS,
    REGISTRY,
)
from app.modules.supplier_reco.thresholds import SupplierRecoConfig
from app.services.tabular.parsing import (
    DataQualityIssue,
    build_canonical_frame,
    check_required_completeness,
    coerce_types,
)

logger = get_logger(__name__)


@dataclass
class NormalizedSupplier:
    """One supplier's canonical, parsed record."""

    row_number: int
    supplier_id: str
    supplier_name: str | None = None
    materials_supplied: list[str] = field(default_factory=list)
    plants_served: list[str] = field(default_factory=list)
    regions_served: list[str] = field(default_factory=list)
    unit_price: float | None = None
    currency: str | None = None
    unit_price_base: float | None = None
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

    def to_record(self) -> dict[str, Any]:
        """A JSON/DB-safe dictionary of this supplier."""
        return {
            "row_number": self.row_number,
            "supplier_id": self.supplier_id,
            "supplier_name": self.supplier_name,
            "materials_supplied": list(self.materials_supplied),
            "plants_served": list(self.plants_served),
            "regions_served": list(self.regions_served),
            "unit_price": self.unit_price,
            "currency": self.currency,
            "unit_price_base": self.unit_price_base,
            "lead_time_days": self.lead_time_days,
            "available_capacity": self.available_capacity,
            "on_time_delivery_rate": self.on_time_delivery_rate,
            "quality_score": self.quality_score,
            "defect_rate": self.defect_rate,
            "risk_score": self.risk_score,
            "esg_score": self.esg_score,
            "contract_status": self.contract_status,
            "contract_expiration": self.contract_expiration.isoformat()
            if self.contract_expiration
            else None,
            "payment_terms": self.payment_terms,
            "historical_order_count": self.historical_order_count,
            "historical_spend": self.historical_spend,
            "historical_spend_base": self.historical_spend_base,
        }


@dataclass
class SupplierCatalogDataset:
    """The normalised supplier catalogue handed to the engine and persistence."""

    suppliers: list[NormalizedSupplier]
    issues: list[DataQualityIssue]
    applied_mapping: dict[str, str]
    unmapped_columns: list[str]
    present_fields: list[str]
    missing_fields: list[str]

    @property
    def supplier_count(self) -> int:
        return len(self.suppliers)

    def issues_as_dicts(self) -> list[dict[str, Any]]:
        return [issue.to_dict() for issue in self.issues]


def split_list(value: Any, delimiters: list[str]) -> list[str]:
    """Split a delimited string into a clean list of tokens.

    Tolerates any of the configured delimiters, collapses blanks and duplicates
    while preserving order.
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return []
    text = str(value).strip()
    if not text:
        return []
    primary = delimiters[0] if delimiters else ";"
    for delimiter in delimiters[1:]:
        text = text.replace(delimiter, primary)
    seen: set[str] = set()
    result: list[str] = []
    for token in text.split(primary):
        cleaned = token.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            result.append(cleaned)
    return result


def _cell(value: Any) -> Any:
    """Return ``None`` for pandas NA, otherwise the value unchanged."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    return value


def normalize_supplier_dataframe(
    raw: pd.DataFrame,
    mapping: dict[str, str],
    config: SupplierRecoConfig,
) -> SupplierCatalogDataset:
    """Apply ``mapping`` to ``raw`` and produce canonical supplier records."""
    if raw.empty:
        raise ValidationError("The supplier file contains no rows to load.")

    mapped_fields = set(mapping.values())
    missing_required = [f for f in REGISTRY.required if f not in mapped_fields]
    if missing_required:
        raise ValidationError(
            "The column mapping is missing required fields.",
            details={"missing_required_fields": missing_required},
        )

    frame = build_canonical_frame(raw, mapping, REGISTRY)
    issues: list[DataQualityIssue] = []
    frame = coerce_types(frame, REGISTRY, issues)
    check_required_completeness(frame, REGISTRY, issues)

    delimiters = config.list_delimiters
    suppliers: list[NormalizedSupplier] = []
    for record in frame.to_dict(orient="records"):
        supplier_id = _cell(record.get("supplier_id"))
        if supplier_id is None:
            # Rows without a supplier id are unusable; recorded by
            # check_required_completeness above.
            continue
        currency = _cell(record.get("currency"))
        unit_price = _cell(record.get("unit_price"))
        historical_spend = _cell(record.get("historical_spend"))
        rate = config.conversion_rate(currency)
        suppliers.append(
            NormalizedSupplier(
                row_number=int(record.get("row_number") or 0),
                supplier_id=str(supplier_id),
                supplier_name=_cell(record.get("supplier_name")),
                materials_supplied=split_list(record.get("materials_supplied"), delimiters),
                plants_served=split_list(record.get("plants_served"), delimiters),
                regions_served=split_list(record.get("regions_served"), delimiters),
                unit_price=None if unit_price is None else float(unit_price),
                currency=currency,
                unit_price_base=None if unit_price is None else round(float(unit_price) * rate, 4),
                lead_time_days=_int(record.get("lead_time_days")),
                available_capacity=_float(record.get("available_capacity")),
                on_time_delivery_rate=_float(record.get("on_time_delivery_rate")),
                quality_score=_float(record.get("quality_score")),
                defect_rate=_float(record.get("defect_rate")),
                risk_score=_float(record.get("risk_score")),
                esg_score=_float(record.get("esg_score")),
                contract_status=_cell(record.get("contract_status")),
                contract_expiration=_as_date(record.get("contract_expiration")),
                payment_terms=_cell(record.get("payment_terms")),
                historical_order_count=_int(record.get("historical_order_count")),
                historical_spend=None if historical_spend is None else float(historical_spend),
                historical_spend_base=None
                if historical_spend is None
                else round(float(historical_spend) * rate, 2),
            )
        )

    if not suppliers:
        raise ValidationError("No usable supplier rows were found (every row lacked a supplier id).")

    present_fields = sorted(mapped_fields)
    missing_fields = [f for f in CANONICAL_FIELDS if f not in present_fields]
    unmapped_columns = [c for c in raw.columns if c not in mapping]

    logger.info(
        "Normalised %d suppliers | %d mapped fields | %d data quality issues",
        len(suppliers), len(present_fields), len(issues),
    )
    return SupplierCatalogDataset(
        suppliers=suppliers,
        issues=issues,
        applied_mapping=dict(mapping),
        unmapped_columns=unmapped_columns,
        present_fields=present_fields,
        missing_fields=missing_fields,
    )


def _float(value: Any) -> float | None:
    value = _cell(value)
    return None if value is None else float(value)


def _int(value: Any) -> int | None:
    value = _cell(value)
    return None if value is None else int(value)


def _as_date(value: Any) -> date | None:
    value = _cell(value)
    if value is None:
        return None
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return value.date()
    return None
