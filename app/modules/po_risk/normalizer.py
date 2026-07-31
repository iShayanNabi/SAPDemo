"""Turn a raw uploaded DataFrame into the canonical purchase order dataset.

Steps:

1. rename the mapped source columns to canonical names and drop the rest;
2. coerce each column to its declared type (numbers, dates, codes), recording
   every failure instead of raising;
3. derive ``total_value`` when it is missing and convert values into the base
   currency so rules can compare across currencies;
4. return the dataset together with a list of data quality issues.

Nothing here decides whether something is *risky* - that is the job of the
rules. This layer only decides whether the data is *usable*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.core.exceptions import ValidationError
from app.core.logging import get_logger
from app.modules.po_risk.field_definitions import CANONICAL_FIELDS, REGISTRY
from app.modules.po_risk.thresholds import PoRiskConfig
from app.services.tabular.parsing import (
    DataQualityIssue,
    frame_to_records,
    build_canonical_frame,
    check_required_completeness,
    coerce_types,
    parse_date,
    parse_number,
    parse_string,
)

logger = get_logger(__name__)

__all__ = [
    "DataQualityIssue",
    "NormalizedDataset",
    "frame_to_records",
    "normalize_dataframe",
    "parse_date",
    "parse_number",
    "parse_string",
]


@dataclass
class NormalizedDataset:
    """The canonical dataset handed to the rule engine."""

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


# ---------------------------------------------------------------------------
# Normalisation pipeline
# ---------------------------------------------------------------------------


def normalize_dataframe(
    raw: pd.DataFrame,
    mapping: dict[str, str],
    config: PoRiskConfig,
) -> NormalizedDataset:
    """Apply ``mapping`` to ``raw`` and produce the canonical dataset."""
    if raw.empty:
        raise ValidationError("The dataset contains no rows to analyse.")

    missing_required = [f for f in REGISTRY.required if f not in mapping.values()]
    if missing_required:
        raise ValidationError(
            "The column mapping is missing required fields.",
            details={"missing_required_fields": missing_required},
        )

    frame = build_canonical_frame(raw, mapping, REGISTRY)

    issues: list[DataQualityIssue] = []
    frame = coerce_types(frame, REGISTRY, issues)
    frame = _derive_values(frame, config, issues)
    check_required_completeness(frame, REGISTRY, issues)

    present_fields = sorted(set(mapping.values()))
    missing_fields = [f for f in CANONICAL_FIELDS if f not in present_fields]
    unmapped_columns = [c for c in raw.columns if c not in mapping]

    ordered = ["row_number", *CANONICAL_FIELDS, "total_value_base", "unit_price_base",
               "total_value_was_derived"]
    frame = frame[[c for c in ordered if c in frame.columns]]

    logger.info(
        "Normalised %d rows | %d mapped fields | %d data quality issues",
        len(frame), len(present_fields), len(issues),
    )
    return NormalizedDataset(
        frame=frame.reset_index(drop=True),
        issues=issues,
        applied_mapping=dict(mapping),
        unmapped_columns=unmapped_columns,
        present_fields=present_fields,
        missing_fields=missing_fields,
    )


def _derive_values(
    frame: pd.DataFrame, config: PoRiskConfig, issues: list[DataQualityIssue]
) -> pd.DataFrame:
    """Derive ``total_value`` when absent and add base-currency columns."""
    quantity = pd.to_numeric(frame["quantity"], errors="coerce")
    unit_price = pd.to_numeric(frame["unit_price"], errors="coerce")
    total_value = pd.to_numeric(frame["total_value"], errors="coerce")

    computed = quantity * unit_price
    derived_mask = total_value.isna() & computed.notna()
    frame["total_value_was_derived"] = derived_mask
    frame["total_value"] = total_value.where(~derived_mask, computed)

    derived_count = int(derived_mask.sum())
    if derived_count:
        issues.append(
            DataQualityIssue(
                field_name="total_value",
                issue_type="derived_value",
                message=(
                    f"Total value was calculated as quantity x unit price for {derived_count} "
                    "line item(s) because the source file did not provide it."
                ),
                affected_rows=derived_count,
                sample_rows=[int(r) for r in frame.loc[derived_mask, "row_number"].head(10)],
                severity="info",
            )
        )

    # Inconsistent totals: supplied value differs from quantity x price.
    both = total_value.notna() & computed.notna() & (computed != 0)
    inconsistent = both & ((total_value - computed).abs() > (computed.abs() * 0.01))
    inconsistent_count = int(inconsistent.sum())
    if inconsistent_count:
        issues.append(
            DataQualityIssue(
                field_name="total_value",
                issue_type="inconsistent_total",
                message=(
                    f"{inconsistent_count} line item(s) have a total value that differs by more "
                    "than 1% from quantity x unit price. The supplied total value was kept."
                ),
                affected_rows=inconsistent_count,
                sample_rows=[int(r) for r in frame.loc[inconsistent, "row_number"].head(10)],
                severity="warning",
            )
        )

    rates = frame["currency"].map(config.conversion_rate).astype(float)
    frame["total_value_base"] = pd.to_numeric(frame["total_value"], errors="coerce").fillna(0.0) * rates
    frame["unit_price_base"] = pd.to_numeric(frame["unit_price"], errors="coerce") * rates

    unknown_currencies = sorted(
        {
            str(c)
            for c in frame["currency"].dropna().unique()
            if str(c).upper() not in config.currency_rates
        }
    )
    if unknown_currencies:
        issues.append(
            DataQualityIssue(
                field_name="currency",
                issue_type="unknown_currency",
                message=(
                    "No conversion rate is configured for "
                    f"{', '.join(unknown_currencies)}; a rate of 1.0 was assumed."
                ),
                affected_rows=int(frame["currency"].isin(unknown_currencies).sum()),
                severity="warning",
            )
        )
    return frame
