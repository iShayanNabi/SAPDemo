"""Turn a raw uploaded file into the canonical spend dataset.

On top of the shared type coercion this module derives the columns every spend
metric depends on:

* ``spend_base``          - line value converted into the base currency
* ``effective_date``      - transaction date, falling back to the order date
* ``spend_month``         - first day of the month, for the monthly trend
* ``is_contracted``       - from the contract status column, or the contract number
* ``is_preferred_supplier`` - from the preferred supplier status column
* ``is_maverick``         - configured combination of the two flags above
* ``is_under_management`` - configured definition of spend under management
* ``price_variance_base`` / ``price_variance_pct`` - against the baseline price

Every derivation is deterministic and driven by the configuration file. None of
it decides whether something is *good or bad* - that is the job of the metrics,
analytics and savings layers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.modules.spend.field_definitions import (
    CANONICAL_FIELDS,
    DATE_FIELD_GROUP,
    REGISTRY,
    VALUE_INGREDIENT_FIELDS,
)
from app.modules.spend.thresholds import SpendConfig
from app.services.tabular.parsing import (
    DataQualityIssue,
    build_canonical_frame,
    check_required_completeness,
    coerce_types,
)

logger = get_logger(__name__)


@dataclass
class SpendDataset:
    """The canonical spend dataset handed to the metrics and analytics layers."""

    frame: pd.DataFrame
    issues: list[DataQualityIssue]
    applied_mapping: dict[str, str]
    unmapped_columns: list[str]
    present_fields: list[str]
    missing_fields: list[str]

    @property
    def record_count(self) -> int:
        return len(self.frame)

    def issues_as_dicts(self) -> list[dict[str, Any]]:
        return [issue.to_dict() for issue in self.issues]


def _normalize_status(value: Any) -> str:
    """Lowercase a status value for list comparison."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    return str(value).strip().lower()


def classify_contract_status(
    status: Any, contract_number: Any, config: SpendConfig
) -> bool:
    """Decide whether a transaction is contracted.

    The explicit status column wins. When it is absent or unrecognised and the
    configuration allows it, the presence of a contract number is used instead -
    which is what makes a plain purchase order extract analysable here.
    """
    settings = config.classification
    text = _normalize_status(status)
    if text:
        if text in {v.lower() for v in settings.contracted_status_values}:
            return True
        if text in {v.lower() for v in settings.non_contracted_status_values}:
            return False
    if settings.derive_contract_status_from_contract_number:
        return bool(_normalize_status(contract_number))
    return False


def classify_preferred_supplier(status: Any, config: SpendConfig) -> bool:
    """Decide whether the supplier is a preferred supplier.

    Unknown or missing values are treated as *not preferred*: claiming preferred
    status without evidence would understate maverick spend.
    """
    settings = config.classification
    text = _normalize_status(status)
    if not text:
        return False
    if text in {v.lower() for v in settings.preferred_status_values}:
        return True
    if text in {v.lower() for v in settings.non_preferred_status_values}:
        return False
    return False


def normalize_spend_dataframe(
    raw: pd.DataFrame,
    mapping: dict[str, str],
    config: SpendConfig,
) -> SpendDataset:
    """Apply ``mapping`` to ``raw`` and produce the canonical spend dataset."""
    if raw.empty:
        raise ValidationError("The dataset contains no rows to analyse.")

    mapped_fields = set(mapping.values())
    missing_required = [f for f in REGISTRY.required if f not in mapped_fields]
    if missing_required:
        raise ValidationError(
            "The column mapping is missing required fields.",
            details={"missing_required_fields": missing_required},
        )
    if not mapped_fields.intersection(DATE_FIELD_GROUP):
        raise ValidationError(
            "A date column is required. Map either a transaction date or an order date.",
            details={"one_of_required": list(DATE_FIELD_GROUP)},
        )
    has_value = "total_value" in mapped_fields
    has_ingredients = set(VALUE_INGREDIENT_FIELDS).issubset(mapped_fields)
    if not (has_value or has_ingredients):
        raise ValidationError(
            "A spend value is required. Map a total value column, or both quantity "
            "and unit price so the value can be calculated.",
            details={
                "one_of_required": ["total_value", list(VALUE_INGREDIENT_FIELDS)],
            },
        )

    frame = build_canonical_frame(raw, mapping, REGISTRY)
    issues: list[DataQualityIssue] = []
    frame = coerce_types(frame, REGISTRY, issues)
    frame = _derive_columns(frame, config, issues)
    check_required_completeness(frame, REGISTRY, issues)

    present_fields = sorted(mapped_fields)
    missing_fields = [f for f in CANONICAL_FIELDS if f not in present_fields]
    unmapped_columns = [c for c in raw.columns if c not in mapping]

    logger.info(
        "Normalised %d spend rows | %d mapped fields | %d data quality issues",
        len(frame), len(present_fields), len(issues),
    )
    return SpendDataset(
        frame=frame.reset_index(drop=True),
        issues=issues,
        applied_mapping=dict(mapping),
        unmapped_columns=unmapped_columns,
        present_fields=present_fields,
        missing_fields=missing_fields,
    )


def _derive_columns(
    frame: pd.DataFrame, config: SpendConfig, issues: list[DataQualityIssue]
) -> pd.DataFrame:
    """Add the derived columns every downstream calculation depends on."""
    # --- line value -----------------------------------------------------
    computed = frame["quantity"].astype("object").combine(
        frame["unit_price"].astype("object"),
        lambda q, p: None if q is None or p is None else float(q) * float(p),
    )
    derived_mask = frame["total_value"].isna() & computed.notna()
    frame["total_value"] = frame["total_value"].where(frame["total_value"].notna(), computed)
    derived_count = int(derived_mask.sum())
    if derived_count:
        issues.append(
            DataQualityIssue(
                field_name="total_value",
                issue_type="derived_value",
                message=(
                    f"{derived_count} line value(s) were calculated as quantity x unit price "
                    "because the file did not supply a total value."
                ),
                affected_rows=derived_count,
                sample_rows=[int(r) for r in frame.loc[derived_mask, "row_number"].head(10)],
                severity="info",
            )
        )

    # --- base currency --------------------------------------------------
    rates = frame["currency"].map(config.conversion_rate)
    frame["spend_base"] = [
        0.0 if value is None or pd.isna(value) else round(float(value) * float(rate), 2)
        for value, rate in zip(frame["total_value"], rates)
    ]
    for source, target in (
        ("unit_price", "unit_price_base"),
        ("baseline_price", "baseline_price_base"),
        ("current_price", "current_price_base"),
    ):
        frame[target] = [
            None if value is None or pd.isna(value) else round(float(value) * float(rate), 4)
            for value, rate in zip(frame[source], rates)
        ]

    # The paid price defaults to the purchase order unit price.
    frame["current_price_base"] = frame["current_price_base"].where(
        frame["current_price_base"].notna(), frame["unit_price_base"]
    )

    # --- dates ----------------------------------------------------------
    frame["effective_date"] = frame["transaction_date"].where(
        frame["transaction_date"].notna(), frame["order_date"]
    )
    missing_dates = int(frame["effective_date"].isna().sum())
    if missing_dates:
        issues.append(
            DataQualityIssue(
                field_name="effective_date",
                issue_type="missing_date",
                message=(
                    f"{missing_dates} row(s) have neither a transaction date nor an order date "
                    "and are excluded from the monthly trend."
                ),
                affected_rows=missing_dates,
                sample_rows=[
                    int(r) for r in frame.loc[frame["effective_date"].isna(), "row_number"].head(10)
                ],
                severity="warning",
            )
        )
    frame["spend_month"] = frame["effective_date"].map(
        lambda d: f"{d.year:04d}-{d.month:02d}" if d is not None and not pd.isna(d) else None
    )

    # --- classification flags -------------------------------------------
    frame["is_contracted"] = [
        classify_contract_status(status, contract, config)
        for status, contract in zip(frame["contract_status"], frame["contract_number"])
    ]
    frame["is_preferred_supplier"] = frame["preferred_supplier_status"].map(
        lambda value: classify_preferred_supplier(value, config)
    )

    maverick = config.classification.maverick_definition
    conditions = []
    if maverick.requires_no_contract:
        conditions.append(~frame["is_contracted"])
    if maverick.requires_non_preferred_supplier:
        conditions.append(~frame["is_preferred_supplier"])
    if conditions:
        combined = conditions[0]
        for condition in conditions[1:]:
            combined = combined & condition
        frame["is_maverick"] = combined
    else:
        frame["is_maverick"] = False

    under_management = config.classification.spend_under_management_definition
    managed = pd.Series(False, index=frame.index)
    if under_management.counts_contracted:
        managed = managed | frame["is_contracted"]
    if under_management.counts_preferred_supplier:
        managed = managed | frame["is_preferred_supplier"]
    frame["is_under_management"] = managed

    # --- price variance against the baseline ----------------------------
    variance_values: list[float | None] = []
    variance_pct: list[float | None] = []
    for baseline, current, quantity in zip(
        frame["baseline_price_base"], frame["current_price_base"], frame["quantity"]
    ):
        if baseline is None or current is None or pd.isna(baseline) or pd.isna(current) or not baseline:
            variance_values.append(None)
            variance_pct.append(None)
            continue
        units = 0.0 if quantity is None or pd.isna(quantity) else float(quantity)
        variance_values.append(round((float(current) - float(baseline)) * units, 2))
        variance_pct.append(round((float(current) - float(baseline)) / float(baseline) * 100.0, 2))
    frame["price_variance_base"] = variance_values
    frame["price_variance_pct"] = variance_pct

    return frame
