"""Automatic column mapping between a source file and a field registry.

Three matching strategies are applied in order of decreasing confidence:

1. **Exact alias match** (confidence 1.00) - the normalised header is a known
   alias such as ``EBELN`` or ``purchase_order_number``.
2. **Token containment** (confidence 0.80) - the header contains a known alias
   as a whole token group, e.g. ``sap_ebeln_key``.
3. **Fuzzy similarity** (confidence = ratio) - ``difflib`` similarity above the
   configured floor, which catches typos such as ``suplier_id``.

The result is a *suggestion*. A user can always override it through the API or
the mapping interface before an analysis runs.

This module is registry-driven, so every module of the lab gets the same
mapping behaviour from one implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher

from app.core.exceptions import ValidationError
from app.services.tabular.field_registry import FieldRegistry, normalize_header

EXACT_CONFIDENCE = 1.0
CONTAINMENT_CONFIDENCE = 0.8
FUZZY_FLOOR = 0.82


@dataclass(frozen=True)
class ColumnSuggestion:
    """One suggested source column -> canonical field mapping."""

    source_column: str
    canonical_field: str
    confidence: float
    strategy: str


@dataclass(frozen=True)
class MappingResult:
    """Outcome of the automatic mapping step."""

    mapping: dict[str, str]
    """source column -> canonical field"""

    suggestions: list[ColumnSuggestion]
    unmapped_columns: list[str]
    missing_required_fields: list[str]

    @property
    def is_analyzable(self) -> bool:
        """True when every required canonical field has a source column."""
        return not self.missing_required_fields


def _fuzzy_best_match(normalized: str, registry: FieldRegistry) -> tuple[str | None, float]:
    """Return the closest canonical field for a normalised header."""
    best_field: str | None = None
    best_score = 0.0
    for alias, canonical in registry.alias_lookup.items():
        score = SequenceMatcher(None, normalized, alias).ratio()
        if score > best_score:
            best_score = score
            best_field = canonical
    return best_field, best_score


def _containment_match(normalized: str, registry: FieldRegistry) -> tuple[str | None, float]:
    """Match when a known alias appears as a whole token group in the header."""
    tokens = normalized.split("_")
    best_field: str | None = None
    best_len = 0
    for alias, canonical in registry.alias_lookup.items():
        alias_tokens = alias.split("_")
        alias_len = len(alias_tokens)
        if alias_len > len(tokens) or alias_len <= best_len:
            continue
        for start in range(len(tokens) - alias_len + 1):
            if tokens[start : start + alias_len] == alias_tokens:
                best_field, best_len = canonical, alias_len
                break
    return (best_field, CONTAINMENT_CONFIDENCE) if best_field else (None, 0.0)


def suggest_mapping(source_columns: list[str], registry: FieldRegistry) -> MappingResult:
    """Suggest a mapping for ``source_columns`` against ``registry``.

    Each canonical field is assigned at most once: the highest confidence
    source column wins and the remaining candidates stay unmapped.
    """
    candidates: dict[str, list[ColumnSuggestion]] = {}

    for column in source_columns:
        normalized = normalize_header(column)
        if not normalized:
            continue

        canonical = registry.alias_lookup.get(normalized)
        if canonical:
            suggestion = ColumnSuggestion(column, canonical, EXACT_CONFIDENCE, "exact_alias")
        else:
            canonical, score = _containment_match(normalized, registry)
            if canonical:
                suggestion = ColumnSuggestion(column, canonical, score, "token_containment")
            else:
                canonical, score = _fuzzy_best_match(normalized, registry)
                if canonical and score >= FUZZY_FLOOR:
                    suggestion = ColumnSuggestion(column, canonical, round(score, 3), "fuzzy")
                else:
                    continue
        candidates.setdefault(suggestion.canonical_field, []).append(suggestion)

    mapping: dict[str, str] = {}
    suggestions: list[ColumnSuggestion] = []
    for canonical_field, options in candidates.items():
        winner = max(options, key=lambda s: (s.confidence, -len(s.source_column)))
        mapping[winner.source_column] = canonical_field
        suggestions.append(winner)

    unmapped = [column for column in source_columns if column not in mapping]
    missing_required = [f for f in registry.required if f not in mapping.values()]

    suggestions.sort(key=lambda s: registry.names.index(s.canonical_field))
    return MappingResult(
        mapping=mapping,
        suggestions=suggestions,
        unmapped_columns=unmapped,
        missing_required_fields=missing_required,
    )


def validate_mapping(
    mapping: dict[str, str], source_columns: list[str], registry: FieldRegistry
) -> None:
    """Validate a user supplied mapping.

    Raises:
        ValidationError: unknown canonical field, unknown source column,
            duplicate target field, or a missing required field.
    """
    if not mapping:
        raise ValidationError("Column mapping must not be empty.")

    unknown_sources = sorted(set(mapping) - set(source_columns))
    if unknown_sources:
        raise ValidationError(
            "The mapping refers to columns that are not present in the file.",
            details={"unknown_source_columns": unknown_sources},
        )

    unknown_targets = sorted(set(mapping.values()) - set(registry.names))
    if unknown_targets:
        raise ValidationError(
            "The mapping refers to unknown canonical fields.",
            details={"unknown_fields": unknown_targets, "allowed_fields": list(registry.names)},
        )

    targets = list(mapping.values())
    duplicates = sorted({t for t in targets if targets.count(t) > 1})
    if duplicates:
        raise ValidationError(
            "Each canonical field may be mapped only once.",
            details={"duplicate_fields": duplicates},
        )

    missing = [f for f in registry.required if f not in targets]
    if missing:
        raise ValidationError(
            "The mapping is missing required fields.",
            details={
                "missing_required_fields": missing,
                "labels": [registry.label(f) for f in missing],
            },
        )


def merge_mapping(suggested: dict[str, str], overrides: dict[str, str] | None) -> dict[str, str]:
    """Apply user ``overrides`` on top of the ``suggested`` mapping.

    An override value of ``""`` or ``None`` removes the column from the mapping,
    which is how a UI expresses "ignore this column".
    """
    merged = dict(suggested)
    for source_column, canonical_field in (overrides or {}).items():
        if not canonical_field:
            merged.pop(source_column, None)
            continue
        # A canonical field can only be used once: drop any previous holder.
        for existing_source, existing_field in list(merged.items()):
            if existing_field == canonical_field and existing_source != source_column:
                merged.pop(existing_source)
        merged[source_column] = canonical_field
    return merged
