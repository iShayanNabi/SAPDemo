"""Filtering of the canonical spend dataset.

Filters are applied *before* every metric, analytic and savings calculation, so
a filtered dashboard is internally consistent: the KPI cards, the charts, the
drill-down tables and the opportunity list all describe the same slice.

The filter is a plain value object. It is built once from the API request and
passed down, which keeps the filtering logic in one place instead of being
re-implemented per chart.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import pandas as pd

from app.modules.spend.field_definitions import FILTERABLE_FIELDS

#: Filters that accept a list of values and match on equality.
CATEGORICAL_FILTERS: tuple[str, ...] = FILTERABLE_FIELDS


@dataclass
class SpendFilter:
    """A set of user selected filters.

    ``values`` maps a canonical field name to the list of accepted values.
    An empty list, or an absent key, means "no restriction on this field".
    """

    date_from: date | None = None
    date_to: date | None = None
    values: dict[str, list[str]] = field(default_factory=dict)

    @property
    def is_empty(self) -> bool:
        """True when the filter would not remove any row."""
        return (
            self.date_from is None
            and self.date_to is None
            and not any(self.values.get(name) for name in CATEGORICAL_FILTERS)
        )

    def active_filters(self) -> dict[str, Any]:
        """Describe the active restrictions, for display and for the export."""
        active: dict[str, Any] = {}
        if self.date_from:
            active["date_from"] = self.date_from.isoformat()
        if self.date_to:
            active["date_to"] = self.date_to.isoformat()
        for name in CATEGORICAL_FILTERS:
            selected = self.values.get(name)
            if selected:
                active[name] = list(selected)
        return active

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe representation stored with the analysis."""
        return {
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "values": {k: list(v) for k, v in self.values.items() if v},
        }

    @classmethod
    def from_request(
        cls,
        date_from: date | None = None,
        date_to: date | None = None,
        values: dict[str, list[str]] | None = None,
    ) -> "SpendFilter":
        """Build a filter, dropping empty selections."""
        cleaned = {
            name: [str(v) for v in selected if str(v).strip()]
            for name, selected in (values or {}).items()
            if name in CATEGORICAL_FILTERS and selected
        }
        return cls(date_from=date_from, date_to=date_to, values=cleaned)


def apply_filter(frame: pd.DataFrame, spend_filter: SpendFilter | None) -> pd.DataFrame:
    """Return the rows of ``frame`` that satisfy ``spend_filter``.

    Rows with no effective date are kept when no date range is requested and
    dropped when one is, because an undated row cannot be shown to fall inside
    a period.
    """
    if spend_filter is None or spend_filter.is_empty:
        return frame

    mask = pd.Series(True, index=frame.index)

    if spend_filter.date_from is not None or spend_filter.date_to is not None:
        dated = frame["effective_date"].notna()
        mask &= dated
        if spend_filter.date_from is not None:
            mask &= frame["effective_date"].map(
                lambda d: d is not None and not pd.isna(d) and d >= spend_filter.date_from
            )
        if spend_filter.date_to is not None:
            mask &= frame["effective_date"].map(
                lambda d: d is not None and not pd.isna(d) and d <= spend_filter.date_to
            )

    for name in CATEGORICAL_FILTERS:
        selected = spend_filter.values.get(name)
        if not selected or name not in frame.columns:
            continue
        accepted = {str(value) for value in selected}
        mask &= frame[name].map(lambda v: v is not None and str(v) in accepted)

    return frame[mask]


def available_filter_values(frame: pd.DataFrame, limit: int = 500) -> dict[str, list[str]]:
    """List the distinct values available for each filterable field.

    Used by the UI to populate the filter controls from the uploaded data
    rather than from a hardcoded list.
    """
    options: dict[str, list[str]] = {}
    for name in CATEGORICAL_FILTERS:
        if name not in frame.columns:
            options[name] = []
            continue
        distinct = sorted({str(v) for v in frame[name].dropna().unique()})
        options[name] = distinct[:limit]
    return options


def date_bounds(frame: pd.DataFrame) -> tuple[date | None, date | None]:
    """Earliest and latest effective date present in the dataset."""
    dates = [d for d in frame["effective_date"].tolist() if d is not None and not pd.isna(d)]
    if not dates:
        return None, None
    return min(dates), max(dates)
