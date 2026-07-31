"""Scalar parsers and type coercion shared by every module.

The guiding rule: a bad cell is a *reported* problem, never an exception. One
unreadable quantity in a 50,000 row export must not stop an analysis - it
becomes a :class:`DataQualityIssue` the user can see and act on.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from app.services.tabular.field_registry import FieldRegistry, FieldType

# Date formats seen in SAP exports and typical spreadsheet edits.
DATE_FORMATS = (
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d.%m.%Y",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%Y%m%d",
    "%d-%m-%Y",
    "%d %b %Y",
    "%Y-%m-%d %H:%M:%S",
)

#: First numeric token in a string, tolerating thousands/decimal separators.
_NUMBER_TOKEN = re.compile(r"[-+]?\d[\d.,]*(?:[eE][-+]?\d+)?")

TRUE_VALUES = {"true", "yes", "y", "1", "x", "ja", "j", "preferred", "active"}
FALSE_VALUES = {"false", "no", "n", "0", "", "nein", "inactive"}


@dataclass
class DataQualityIssue:
    """A non-fatal problem detected while normalising the dataset."""

    field_name: str
    issue_type: str
    message: str
    affected_rows: int
    sample_rows: list[int] = field(default_factory=list)
    severity: str = "warning"

    def to_dict(self) -> dict[str, Any]:
        return {
            "field": self.field_name,
            "issue_type": self.issue_type,
            "message": self.message,
            "affected_rows": self.affected_rows,
            "sample_rows": self.sample_rows[:10],
            "severity": self.severity,
        }


def parse_number(value: Any) -> float | None:
    """Parse a number written in either European or Anglo-Saxon notation.

    ``"1.234,56"`` -> ``1234.56``; ``"1,234.56"`` -> ``1234.56``;
    ``"(500)"`` -> ``-500``; ``"12 EUR"`` -> ``12.0``.
    """
    if value is None:
        return None
    if isinstance(value, (int, float, np.integer, np.floating)):
        number = float(value)
        return None if pd.isna(number) else number

    text = str(value).strip()
    if not text:
        return None

    negative = text.startswith("(") and text.endswith(")")
    if negative:
        text = text[1:-1]

    # Pull out the first numeric token so currency suffixes/prefixes
    # ("12 EUR", "USD 1,200.50") do not break the conversion.
    match = _NUMBER_TOKEN.search(text)
    if match is None:
        return None
    text = match.group(0)
    if text in {"-", "+", ".", ","}:
        return None

    has_comma, has_dot = "," in text, "." in text
    if has_comma and has_dot:
        # The right-most separator is the decimal separator.
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        decimals = len(text.split(",")[-1])
        text = text.replace(",", "." if decimals != 3 else "")
    try:
        number = float(text)
    except ValueError:
        return None
    return -number if negative else number


def parse_date(value: Any) -> date | None:
    """Parse a date from the formats produced by SAP and spreadsheet tools."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, pd.Timestamp):
        return None if pd.isna(value) else value.date()
    if isinstance(value, (int, float, np.integer, np.floating)):
        if pd.isna(value):
            return None
        text = str(int(value))
    else:
        text = str(value).strip()

    if not text or text in {"00000000", "0"}:
        return None

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        parsed = pd.to_datetime(text, errors="coerce")
    except (ValueError, TypeError):
        return None
    if parsed is None or pd.isna(parsed):
        return None
    return parsed.date()


def parse_string(value: Any, max_length: int | None = None) -> str | None:
    """Trim a string value and enforce the field's maximum length."""
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:max_length] if max_length else text


def parse_boolean(value: Any) -> bool | None:
    """Parse a flag written as a word, a letter or a number."""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float, np.integer, np.floating)):
        if pd.isna(value):
            return None
        return bool(value)
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return None if text == "" else False
    return None


def coerce_types(
    frame: pd.DataFrame,
    registry: FieldRegistry,
    issues: list[DataQualityIssue],
) -> pd.DataFrame:
    """Coerce every canonical column of ``frame`` to its declared type.

    Values that cannot be converted become ``None`` and are summarised into
    ``issues`` with a sample of the affected spreadsheet row numbers.
    """
    for field_name in registry.names:
        definition = registry.by_name[field_name]
        original = frame[field_name]
        non_null_before = original.notna()

        if definition.field_type in (FieldType.NUMBER, FieldType.INTEGER):
            converted = original.map(parse_number)
            if definition.field_type is FieldType.INTEGER:
                # ``map`` infers float64 as soon as the column has a hole, so a
                # missing integer arrives here as NaN rather than None - and a
                # plain re-map would hand the column back as floats. Rebuild it
                # as an object column so an INTEGER field keeps real ints and
                # real ``None``s, whether or not any cell was blank.
                converted = pd.Series(
                    [
                        None if value is None or pd.isna(value) else int(round(value))
                        for value in converted
                    ],
                    index=converted.index,
                    dtype=object,
                )
            frame[field_name] = converted
        elif definition.field_type is FieldType.DATE:
            frame[field_name] = original.map(parse_date)
        elif definition.field_type is FieldType.CURRENCY_CODE:
            frame[field_name] = original.map(lambda v: (parse_string(v, 3) or "").upper() or None)
        elif definition.field_type is FieldType.BOOLEAN:
            frame[field_name] = original.map(parse_boolean)
        else:
            frame[field_name] = original.map(
                lambda v, ln=definition.max_length: parse_string(v, ln)
            )

        failed_mask = non_null_before & frame[field_name].isna()
        failed_count = int(failed_mask.sum())
        if failed_count:
            issues.append(
                DataQualityIssue(
                    field_name=field_name,
                    issue_type="type_conversion_failed",
                    message=(
                        f"{failed_count} value(s) in '{definition.label}' could not be read as "
                        f"{definition.field_type.value} and were treated as missing."
                    ),
                    affected_rows=failed_count,
                    sample_rows=[int(r) for r in frame.loc[failed_mask, "row_number"].head(10)],
                    severity="warning",
                )
            )
    return frame


def check_required_completeness(
    frame: pd.DataFrame, registry: FieldRegistry, issues: list[DataQualityIssue]
) -> None:
    """Record an issue for every required field that has empty values."""
    for field_name in registry.required:
        if field_name not in frame.columns:
            continue
        missing_mask = frame[field_name].isna()
        missing_count = int(missing_mask.sum())
        if missing_count:
            issues.append(
                DataQualityIssue(
                    field_name=field_name,
                    issue_type="missing_required_value",
                    message=(
                        f"{missing_count} row(s) have no value for the required field "
                        f"'{registry.label(field_name)}'."
                    ),
                    affected_rows=missing_count,
                    sample_rows=[int(r) for r in frame.loc[missing_mask, "row_number"].head(10)],
                    severity="warning",
                )
            )


def build_canonical_frame(
    raw: pd.DataFrame, mapping: dict[str, str], registry: FieldRegistry
) -> pd.DataFrame:
    """Rename mapped source columns to canonical names and add the missing ones.

    ``row_number`` refers to the row in the source spreadsheet (the header is
    row 1), so a data-quality warning can point the user at the exact line.
    """
    frame = pd.DataFrame(index=raw.index)
    frame["row_number"] = [int(i) + 2 for i in range(len(raw))]

    for source_column, canonical_field in mapping.items():
        if source_column in raw.columns:
            frame[canonical_field] = raw[source_column].to_numpy()

    for field_name in registry.names:
        if field_name not in frame.columns:
            frame[field_name] = None
    return frame


def frame_to_records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """Convert the canonical frame into JSON-safe dictionaries."""
    records: list[dict[str, Any]] = []
    for _, row in frame.iterrows():
        record: dict[str, Any] = {}
        for column, value in row.items():
            if value is None or (isinstance(value, float) and pd.isna(value)):
                record[str(column)] = None
            elif isinstance(value, (date, datetime)):
                record[str(column)] = value.isoformat()[:10]
            elif isinstance(value, (np.integer,)):
                record[str(column)] = int(value)
            elif isinstance(value, (np.floating,)):
                record[str(column)] = float(value)
            elif isinstance(value, (np.bool_, bool)):
                record[str(column)] = bool(value)
            else:
                record[str(column)] = value
        records.append(record)
    return records
