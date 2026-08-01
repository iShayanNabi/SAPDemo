"""Reusable field-registry primitives shared by every module of the lab.

A *field registry* is the data contract of a module: the canonical fields it
understands, their types, whether they are required and which source column
names map onto them.

The Purchase Order Risk Checker and the Spend Analytics Dashboard both describe
their data with a registry, so the column mapper, the type coercion pass and
the field catalogue endpoints work identically for both without duplication.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FieldType(str, Enum):
    """Normalised data type of a canonical field."""

    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    DATE = "date"
    CURRENCY_CODE = "currency_code"
    BOOLEAN = "boolean"


@dataclass(frozen=True)
class FieldDefinition:
    """Definition of one canonical field."""

    name: str
    label: str
    field_type: FieldType
    required: bool
    description: str
    aliases: tuple[str, ...] = field(default_factory=tuple)
    max_length: int | None = None


def normalize_header(header: str) -> str:
    """Normalise a source column header for alias matching.

    Lowercases, replaces punctuation with underscores and collapses separators,
    so ``"Purchase Order Nr."``, ``"purchase-order-nr"`` and
    ``"PURCHASE_ORDER_NR"`` all reduce to ``purchase_order_nr``.
    """
    text = str(header or "").strip().lower()
    out: list[str] = []
    for char in text:
        out.append(char if char.isalnum() else "_")
    return "_".join(part for part in "".join(out).split("_") if part)


class FieldRegistry:
    """An ordered collection of field definitions with alias lookups.

    Aliases are resolved with ``setdefault``, so when two fields claim the same
    alias the one declared *first* wins. Declaration order is therefore
    meaningful: put the more specific field earlier.
    """

    def __init__(self, definitions: tuple[FieldDefinition, ...]) -> None:
        self.definitions = definitions
        self.names: tuple[str, ...] = tuple(d.name for d in definitions)
        self.by_name: dict[str, FieldDefinition] = {d.name: d for d in definitions}
        self.required: tuple[str, ...] = tuple(d.name for d in definitions if d.required)
        self.date_fields: tuple[str, ...] = tuple(
            d.name for d in definitions if d.field_type is FieldType.DATE
        )
        self.numeric_fields: tuple[str, ...] = tuple(
            d.name for d in definitions
            if d.field_type in (FieldType.NUMBER, FieldType.INTEGER)
        )

        alias_lookup: dict[str, str] = {}
        for definition in definitions:
            alias_lookup.setdefault(normalize_header(definition.name), definition.name)
            alias_lookup.setdefault(normalize_header(definition.label), definition.name)
            for alias in definition.aliases:
                alias_lookup.setdefault(normalize_header(alias), definition.name)
        self.alias_lookup = alias_lookup

    def __contains__(self, name: object) -> bool:
        return name in self.by_name

    def __len__(self) -> int:
        return len(self.definitions)

    def label(self, name: str) -> str:
        """Human readable label for a canonical field name."""
        definition = self.by_name.get(name)
        return definition.label if definition else name

    def extend(self, extra: tuple[FieldDefinition, ...]) -> FieldRegistry:
        """Return a new registry with ``extra`` fields appended.

        Used by the spend module to reuse the purchase order contract and add
        its own analytics fields on top.
        """
        return FieldRegistry(self.definitions + extra)

    def with_required(self, required: tuple[str, ...]) -> FieldRegistry:
        """Return a copy where exactly ``required`` fields are mandatory.

        Two modules can share the same field definitions but disagree about
        what is mandatory - spend analysis needs a date and a value, while risk
        rules also need the order/item keys.
        """
        wanted = set(required)
        unknown = wanted - set(self.by_name)
        if unknown:
            raise ValueError(f"Unknown required fields: {sorted(unknown)}")
        rebuilt = tuple(
            FieldDefinition(
                name=d.name,
                label=d.label,
                field_type=d.field_type,
                required=d.name in wanted,
                description=d.description,
                aliases=d.aliases,
                max_length=d.max_length,
            )
            for d in self.definitions
        )
        return FieldRegistry(rebuilt)
