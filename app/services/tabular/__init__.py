"""Reusable tabular data services: field registries, column mapping, parsing.

Extracted from the Purchase Order Risk Checker so that every module of the lab
shares one implementation of "turn an uploaded spreadsheet into a canonical,
type-checked DataFrame".
"""

from app.services.tabular.field_registry import (
    FieldDefinition,
    FieldRegistry,
    FieldType,
    normalize_header,
)
from app.services.tabular.mapping import (
    ColumnSuggestion,
    MappingResult,
    merge_mapping,
    suggest_mapping,
    validate_mapping,
)
from app.services.tabular.parsing import (
    DataQualityIssue,
    build_canonical_frame,
    check_required_completeness,
    coerce_types,
    frame_to_records,
    parse_boolean,
    parse_date,
    parse_number,
    parse_string,
)

__all__ = [
    "ColumnSuggestion",
    "DataQualityIssue",
    "FieldDefinition",
    "FieldRegistry",
    "FieldType",
    "MappingResult",
    "build_canonical_frame",
    "check_required_completeness",
    "coerce_types",
    "frame_to_records",
    "merge_mapping",
    "normalize_header",
    "parse_boolean",
    "parse_date",
    "parse_number",
    "parse_string",
    "suggest_mapping",
    "validate_mapping",
]
