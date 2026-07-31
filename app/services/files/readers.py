"""Readers that turn an accepted upload into a pandas DataFrame.

CSV, XLSX and JSON are supported. Everything is read as *text first*
(``dtype=str``) so that SAP identifiers keep their leading zeros
(``0000004711`` must not become ``4711``). Type coercion happens later, in the
normaliser, where failures can be reported as data quality issues.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.core.config import settings
from app.core.exceptions import FileValidationError
from app.core.logging import get_logger
from app.services.files.validation import decode_text

logger = get_logger(__name__)

_CSV_CANDIDATE_SEPARATORS = (",", ";", "\t", "|")


@dataclass(frozen=True)
class ReadResult:
    """A parsed dataset plus a little information about how it was parsed."""

    dataframe: pd.DataFrame
    source_columns: list[str]
    row_count: int
    notes: list[str]


def read_tabular(content: bytes, extension: str) -> ReadResult:
    """Parse ``content`` into a DataFrame based on ``extension``."""
    extension = extension.lower()
    if extension == ".csv":
        frame, notes = _read_csv(content)
    elif extension == ".xlsx":
        frame, notes = _read_xlsx(content)
    elif extension == ".json":
        frame, notes = _read_json(content)
    else:  # pragma: no cover - validation rejects this earlier
        raise FileValidationError(f"Unsupported file type '{extension}'.")

    frame = _post_process(frame)

    if frame.empty:
        raise FileValidationError("The file contains no data rows.")
    if len(frame) > settings.max_rows_per_upload:
        raise FileValidationError(
            f"The file has {len(frame):,} rows which exceeds the "
            f"{settings.max_rows_per_upload:,} row limit.",
            details={"row_count": len(frame), "max_rows": settings.max_rows_per_upload},
        )

    return ReadResult(
        dataframe=frame,
        source_columns=[str(c) for c in frame.columns],
        row_count=len(frame),
        notes=notes,
    )


def _read_csv(content: bytes) -> tuple[pd.DataFrame, list[str]]:
    """Read a CSV, sniffing the delimiter from the header line."""
    text = decode_text(content)
    if text is None:
        raise FileValidationError("The CSV file could not be decoded as text.")

    separator = _detect_separator(text)
    try:
        frame = pd.read_csv(
            io.StringIO(text),
            sep=separator,
            dtype=str,
            keep_default_na=True,
            skip_blank_lines=True,
            engine="python",
        )
    except Exception as exc:  # noqa: BLE001 - surfaced as a safe message
        logger.warning("CSV parsing failed: %s", exc)
        raise FileValidationError(
            "The CSV file could not be parsed. Check for inconsistent column counts."
        ) from exc

    notes = [f"CSV parsed with '{separator}' delimiter."]
    return frame, notes


def _detect_separator(text: str) -> str:
    """Pick the delimiter that yields the most columns on the header line."""
    header = text.splitlines()[0] if text.splitlines() else ""
    counts = {sep: header.count(sep) for sep in _CSV_CANDIDATE_SEPARATORS}
    best = max(counts, key=lambda sep: counts[sep])
    return best if counts[best] > 0 else ","


def _read_xlsx(content: bytes) -> tuple[pd.DataFrame, list[str]]:
    """Read the first worksheet of an XLSX workbook."""
    try:
        workbook = pd.ExcelFile(io.BytesIO(content), engine="openpyxl")
        sheet_name = workbook.sheet_names[0]
        frame = workbook.parse(sheet_name=sheet_name, dtype=str)
    except FileValidationError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("XLSX parsing failed: %s", exc)
        raise FileValidationError("The Excel workbook could not be read.") from exc

    notes = [f"Worksheet '{sheet_name}' loaded."]
    if len(workbook.sheet_names) > 1:
        notes.append(
            "The workbook has multiple worksheets; only the first one was analysed."
        )
    return frame, notes


def _read_json(content: bytes) -> tuple[pd.DataFrame, list[str]]:
    """Read JSON supplied as a list of objects or ``{"records": [...]}``."""
    text = decode_text(content)
    if text is None:
        raise FileValidationError("The JSON file could not be decoded as text.")
    try:
        payload: Any = json.loads(text)
    except json.JSONDecodeError as exc:
        raise FileValidationError(
            f"The JSON file is not valid: line {exc.lineno}, column {exc.colno}."
        ) from exc

    notes: list[str] = []
    if isinstance(payload, dict):
        for key in ("records", "data", "items", "rows", "value"):
            if isinstance(payload.get(key), list):
                notes.append(f"Records read from the '{key}' property.")
                payload = payload[key]
                break
        else:
            raise FileValidationError(
                "The JSON object must contain a list under 'records', 'data', "
                "'items', 'rows' or 'value'."
            )

    if not isinstance(payload, list) or not payload:
        raise FileValidationError("The JSON file must contain a non-empty list of records.")
    if not all(isinstance(row, dict) for row in payload):
        raise FileValidationError("Every JSON record must be an object with named fields.")

    frame = pd.DataFrame(payload).astype("object")
    return frame, notes


def _post_process(frame: pd.DataFrame) -> pd.DataFrame:
    """Trim headers/values and drop fully empty rows and unnamed columns."""
    frame = frame.copy()
    frame.columns = [str(column).strip() for column in frame.columns]

    # Drop the index column pandas writes when a file was exported with index=True.
    drop = [c for c in frame.columns if c.lower().startswith("unnamed:") or c == ""]
    if drop:
        frame = frame.drop(columns=drop)

    for column in frame.columns:
        frame[column] = frame[column].map(_clean_cell)

    frame = frame.dropna(axis=0, how="all")
    return frame.reset_index(drop=True)


def _clean_cell(value: Any) -> Any:
    """Trim whitespace and turn blank/NA placeholders into ``None``."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    if not isinstance(value, str):
        return value
    text = value.strip()
    if text == "" or text.lower() in {"nan", "none", "null", "#n/a", "n/a", "na", "-"}:
        return None
    return text


def preview_records(frame: pd.DataFrame, limit: int = 10) -> list[dict[str, Any]]:
    """Return the first ``limit`` rows as JSON-safe dictionaries."""
    head = frame.head(limit)
    records: list[dict[str, Any]] = []
    for _, row in head.iterrows():
        record = {}
        for column, value in row.items():
            record[str(column)] = None if pd.isna(value) else str(value)
        records.append(record)
    return records
