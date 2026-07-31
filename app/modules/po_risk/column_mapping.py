"""Column mapping for the Purchase Order Risk Checker.

The matching algorithm itself lives in :mod:`app.services.tabular.mapping` and
is shared with the other modules of the lab. This module binds it to the
purchase order field registry and keeps the module's public API stable.
"""

from __future__ import annotations

from app.modules.po_risk.field_definitions import REGISTRY
from app.services.tabular.mapping import (
    CONTAINMENT_CONFIDENCE,
    EXACT_CONFIDENCE,
    FUZZY_FLOOR,
    ColumnSuggestion,
    MappingResult,
    merge_mapping,
)
from app.services.tabular.mapping import suggest_mapping as _suggest_mapping
from app.services.tabular.mapping import validate_mapping as _validate_mapping

__all__ = [
    "CONTAINMENT_CONFIDENCE",
    "EXACT_CONFIDENCE",
    "FUZZY_FLOOR",
    "ColumnSuggestion",
    "MappingResult",
    "merge_mapping",
    "suggest_mapping",
    "validate_mapping",
]


def suggest_mapping(source_columns: list[str]) -> MappingResult:
    """Suggest a mapping of ``source_columns`` onto the purchase order fields."""
    return _suggest_mapping(source_columns, REGISTRY)


def validate_mapping(mapping: dict[str, str], source_columns: list[str]) -> None:
    """Validate a user supplied purchase order column mapping.

    Raises:
        ValidationError: unknown canonical field, unknown source column,
            duplicate target field, or a missing required field.
    """
    _validate_mapping(mapping, source_columns, REGISTRY)
